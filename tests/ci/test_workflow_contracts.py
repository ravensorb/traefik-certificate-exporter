from __future__ import annotations

import importlib.util
import json
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import yaml
from packaging.version import Version

PROJECT_ROOT = Path(__file__).parents[2]
WORKFLOWS = PROJECT_ROOT / ".github" / "workflows"
ACTIONS = PROJECT_ROOT / ".github" / "actions"
FIXTURES = Path(__file__).parent / "fixtures" / "workflows"
CI_WORKFLOW = WORKFLOWS / "ci.yaml"
VERIFY_WORKFLOW = WORKFLOWS / "verify-build.yaml"
SETUP_ACTION = ACTIONS / "setup-poetry-python" / "action.yml"

VERIFIER_REFERENCE = "./.github/workflows/verify-build.yaml"
SETUP_ACTION_REFERENCE = "./.github/actions/setup-poetry-python"
# Workflows that build or ship an artifact. A push event that reaches one of these
# without first reaching the verifier is the regression this file exists to prevent.


def _load_committed_versions() -> Any:
    """Load the committed-version authority shared with the workflow plan jobs."""
    location = PROJECT_ROOT / "scripts" / "committed_versions.py"
    spec = importlib.util.spec_from_file_location("committed_versions", location)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


committed_versions = _load_committed_versions()


def _governed_definitions() -> tuple[Path, ...]:
    """Tier 1 scope, derived from the filesystem rather than enumerated by hand.

    The previous hand-kept 2-tuple examined ci.yaml and verify-build.yaml only, so the
    four credential-bearing workflows and every composite action were governed by
    nothing. `test_governance_scope_is_derived_from_disk` attacks this scope directly.
    """
    return tuple(sorted(WORKFLOWS.glob("*.yaml")) + sorted(ACTIONS.rglob("action.yml")))


GOVERNED_DEFINITIONS = _governed_definitions()

# Tier 2 scope. Tier 1 (approved owners, floating major aliases, no interpolated
# `uses:`) applies to every governed definition. The credential prohibitions below
# apply only to the verifier pair, because those two run untrusted fork code and must
# never hold a publishing capability -- the publisher workflows legitimately do.
SECRET_FREE_WORKFLOWS = (CI_WORKFLOW, VERIFY_WORKFLOW)

# Jobs permitted to write repository contents -- push refs, or create a forge Release.
# A registry of granted exceptions, not a derived scope: adding a name here IS the grant,
# and each needs an ADR. ADR-0006 draws the line at *identity* -- the committed version
# and the exact vX.Y.Z tag are chosen only by the local guarded transaction. A finalizer
# attaching a Release, its assets, or moving aliases to an identity already decided is not
# a second version authority. Empty until Epic 8 registers one.
RELEASE_FINALIZER_JOBS: frozenset[str] = frozenset()

# `release` and `tag` as verbs in an action name -- the ref-writing ones. `publish` is
# deliberately absent so pypa/gh-action-pypi-publish and image pushes, which write no ref,
# are not caught by a guard about repository writes.
RELEASE_ACTION_VERB = re.compile(r"(?:\A|[-/])(?:release|tag)(?:[-/]|\Z)")
SECRET_FREE_PROHIBITIONS = (
    "secrets:",
    "id-token: write",
    "packages: write",
    "attestations: write",
    "docker/login-action@",
    "actions/cache@",
    "runs-on: self-hosted",
    "secrets: inherit",
)

APPROVED_ACTION_OWNERS = {
    "actions",
    "docker",
    "pypa",
    "LiquidLogicLabs",
}

# A maintained floating major alias, so a fix ships without a manifest edit. Most
# owners publish it as a `vN` tag; pypa publishes it as the `release/vN` branch, which
# is the same guarantee spelled differently. A pinned patch tag is not an alias.
FLOATING_MAJOR_ALIAS = re.compile(r"\A(?:release/)?v[0-9]+\Z")

# The exception to the floating-major default, and a registry of granted exceptions
# rather than a derived scope: adding an entry here IS the grant, and each needs an ADR.
#
# A floating major is a *moving* ref. For most actions that is the right trade -- a
# security fix ships without a manifest edit. For an action handed a publication
# credential it inverts: whoever can move the branch can exfiltrate the token on the next
# run. CI-AR4 sets floating-major as the default for approved owners; CI-AR38 requires a
# reviewed full commit SHA for the PyPI publisher. Both hold, because they are answering
# different questions -- convenience of upgrade versus blast radius of compromise -- and
# the split is per action, not per owner. `pypa` stays an approved owner; only this one
# action of theirs is pinned harder.
SHA_PINNED_ACTIONS = frozenset({"pypa/gh-action-pypi-publish"})

# The one action permitted to create a forge Release (ADR-0010). It speaks GitHub's and
# Gitea's release APIs from a single step, so `release.yaml` carries no forge branch and
# E009 inherits the Gitea path unchanged. Pinned `@v2` -- never `@v2.0`, which is stale.
APPROVED_RELEASE_ACTION = "LiquidLogicLabs/git-action-release"
REVIEWED_COMMIT_SHA = re.compile(r"\A[0-9a-f]{40}\Z")


def _load_document(path: Path) -> dict[str, Any]:
    # BaseLoader keeps GitHub's `on` key as a string instead of applying YAML 1.1's
    # obsolete yes/no boolean coercion.
    document = yaml.load(path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    assert isinstance(document, dict), path
    return document


def _load_workflow(path: Path) -> dict[str, Any]:
    return _load_document(path)


def _load_fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _jobs(document: dict[str, Any]) -> dict[str, Any]:
    jobs = document.get("jobs") or {}
    assert isinstance(jobs, dict)
    return jobs


def _steps(document: dict[str, Any]) -> Iterator[dict[str, Any]]:
    """Yield every step of a workflow or of a composite action definition."""
    for job in _jobs(document).values():
        for step in job.get("steps") or []:
            yield step
    runs = document.get("runs")
    if isinstance(runs, dict):
        for step in runs.get("steps") or []:
            yield step


def _action_references(path: Path) -> list[str]:
    """Every `uses:` value in a definition, read from the parsed document.

    Reading these with a line regex silently misses the `- uses:` list form, which is
    how most steps in this repository are written -- and therefore misses most of what
    the policy is supposed to examine.
    """
    document = _load_document(path)
    references = [
        str(job["uses"]) for job in _jobs(document).values() if "uses" in job
    ] + [str(step["uses"]) for step in _steps(document) if "uses" in step]
    return references


def _external_action_references(path: Path) -> list[str]:
    return [
        reference
        for reference in _action_references(path)
        if not reference.startswith("./")
    ]


def _transitive_needs(jobs: dict[str, Any], job_name: str) -> set[str]:
    """Every job `job_name` depends on, directly or through another job."""
    resolved: set[str] = set()
    pending = [job_name]
    while pending:
        current = pending.pop()
        needs = jobs.get(current, {}).get("needs") or []
        if isinstance(needs, str):
            needs = [needs]
        for dependency in needs:
            if dependency not in resolved:
                resolved.add(dependency)
                pending.append(dependency)
    return resolved


def test_governance_scope_is_derived_from_disk() -> None:
    """The guard must prove its reach, not only its rule.

    Adding a workflow or composite action must not be able to leave it ungoverned, so
    the scope is compared against the on-disk listing rather than a literal list.
    """
    assert GOVERNED_DEFINITIONS

    workflow_files = {path for path in WORKFLOWS.iterdir() if path.is_file()}
    action_files = {
        path
        for path in ACTIONS.rglob("*")
        if path.is_file() and path.name in {"action.yml", "action.yaml"}
    }
    # A `.yml` workflow, or an `action.yaml`, would be on disk yet outside the globs
    # that build the governed set. Either must fail here rather than pass unexamined.
    assert set(GOVERNED_DEFINITIONS) == workflow_files | action_files

    assert set(SECRET_FREE_WORKFLOWS) < set(GOVERNED_DEFINITIONS)
    for path in GOVERNED_DEFINITIONS:
        assert _load_document(path), path


def test_tier_one_actions_use_approved_owners_and_floating_major_aliases() -> None:
    examined = 0
    for path in GOVERNED_DEFINITIONS:
        for reference in _external_action_references(path):
            examined += 1
            action, _, version = reference.rpartition("@")
            owner = action.split("/", 1)[0]
            assert owner in APPROVED_ACTION_OWNERS, (
                f"{path}: {owner} requires an approved ADR or architecture update"
            )
            if action in SHA_PINNED_ACTIONS:
                assert REVIEWED_COMMIT_SHA.fullmatch(version), (
                    f"{path}: {reference} is handed a publication credential, so it must "
                    f"be pinned to a reviewed full 40-character commit SHA (CI-AR38), not "
                    f"a floating alias whose branch can be moved under it"
                )
            else:
                assert FLOATING_MAJOR_ALIAS.fullmatch(version), (
                    f"{path}: {reference} must use the maintained floating major alias"
                )
    assert examined, "no external action references were examined"


def test_credential_handling_publishers_are_registered_as_sha_pinned() -> None:
    # The reach half of the rule above. That test only fires on actions already in
    # SHA_PINNED_ACTIONS, so a *new* credential-handling publisher added to a workflow
    # would take the floating-major branch and never be noticed. This derives the
    # candidate set from the workflows instead: any action whose name says it publishes a
    # package must be registered, or explicitly recorded as not credential-handling.
    publisher_verb = re.compile(r"(?:\A|[-/])(?:pypi|publish)(?:[-/]|\Z)")
    not_credential_handling: frozenset[str] = frozenset()

    for path in GOVERNED_DEFINITIONS:
        for reference in _external_action_references(path):
            action, _, _ = reference.rpartition("@")
            if not publisher_verb.search(action.split("/", 1)[-1]):
                continue
            assert action in SHA_PINNED_ACTIONS or action in not_credential_handling, (
                f"{path}: {action} looks like a package publisher but is neither "
                f"SHA-pinned nor recorded as not credential-handling; decide which, "
                f"with an ADR (CI-AR38)"
            )


def test_no_caller_hands_the_verifier_any_secret() -> None:
    """The secret-free property belongs to the call graph, not to one file.

    `test_tier_two_verifier_pair_holds_no_publisher_capability` reads the *callee's*
    text, so it proves the verifier never writes `secrets:` itself. It says nothing about
    what a caller passes in. `dev.yaml` and `release.yaml` are the first callers that will
    hold publisher credentials, and `secrets: inherit` on their verify job would hand the
    verifier every one of them with that test still green -- ADR-0007 invariant 2 defeated
    from the outside.

    Scope is derived from disk, so a caller added later is covered without editing this.
    """
    verifier_callers = 0
    for path in sorted(WORKFLOWS.glob("*.yaml")):
        for job_name, job in _jobs(_load_workflow(path)).items():
            if job.get("uses") != VERIFIER_REFERENCE:
                continue
            verifier_callers += 1
            assert "secrets" not in job, (
                f"{path.name}: job {job_name!r} passes `secrets` to the verifier. The "
                f"verifier is secret-free by construction (ADR-0007 invariant 2); a "
                f"caller may not hand it credentials from the outside."
            )
    assert verifier_callers, "no job calls the verifier; this guard examined nothing"


def test_tier_one_forbids_expression_interpolated_action_references() -> None:
    for path in GOVERNED_DEFINITIONS:
        for reference in _action_references(path):
            assert "${{" not in reference, f"{path}: {reference}"


def test_tier_two_verifier_pair_holds_no_publisher_capability() -> None:
    for path in SECRET_FREE_WORKFLOWS:
        source = path.read_text(encoding="utf-8")
        for forbidden in SECRET_FREE_PROHIBITIONS:
            assert forbidden not in source, f"{path}: {forbidden}"


def test_fork_verification_has_no_publisher_capability_or_persistent_runner() -> None:
    workflow = _load_workflow(VERIFY_WORKFLOW)
    assert workflow["permissions"] == {"contents": "read"}
    for job in _jobs(workflow).values():
        assert job["runs-on"] == "ubuntu-24.04"
        assert "permissions" not in job


def test_pull_request_adapter_is_minimal_and_fork_safe() -> None:
    workflow = _load_workflow(CI_WORKFLOW)
    triggers = workflow["on"]
    jobs = _jobs(workflow)

    assert isinstance(triggers, dict)
    assert set(triggers) == {"pull_request"}
    assert triggers["pull_request"] == {"branches": ["main"]}
    assert workflow["permissions"] == {"contents": "read"}
    assert workflow["concurrency"] == {
        "group": "${{ github.workflow }}-pr-${{ github.event.pull_request.number }}",
        "cancel-in-progress": "true",
    }
    assert set(jobs) == {"plan", "verify"}

    plan = jobs["plan"]
    assert plan["runs-on"] == "ubuntu-24.04"
    assert plan["permissions"] == {"contents": "read"}

    # Asserted key by key rather than by whole-dict equality: this contract is about
    # which verifier is called with which inputs, and a benign addition such as
    # `timeout-minutes` must not fail it.
    verify = jobs["verify"]
    assert verify["uses"] == VERIFIER_REFERENCE
    assert verify["needs"] == "plan"
    assert verify["permissions"] == {"contents": "read"}
    assert verify["with"] == {
        "channel": "ci",
        "package-version": "${{ needs.plan.outputs.package-version }}",
        "source-sha": "${{ needs.plan.outputs.source-sha }}",
    }
    assert "steps" not in verify

    checkout = plan["steps"][0]
    assert checkout["uses"] == "actions/checkout@v7"
    assert checkout["with"]["persist-credentials"] == "false"
    assert checkout["with"]["ref"] == "${{ github.event.pull_request.head.sha }}"

    # Asserted against the parsed structure, not the raw file: a comment or a job name
    # containing "pytest" is not a violation, while a step that actually runs it is.
    commands = [str(step.get("run", "")) for step in _steps(workflow)]
    for forbidden in (
        r"\bpytest\b",
        r"\bpoetry build\b",
        r"\bruff\b",
        r"\bdocker\s+(?:build|buildx)\b",
    ):
        assert not any(re.search(forbidden, command) for command in commands), forbidden

    referenced = set(_action_references(CI_WORKFLOW))
    assert not any("artifact" in reference for reference in referenced)
    assert not any("publication-contract" in reference for reference in referenced)


def test_the_committed_version_authority_has_one_implementation() -> None:
    """ci.yaml's plan job used to be a third `tool.poetry.version` reader, inline, on an
    unpinned interpreter. Scope is derived from disk -- every `plan` job in every workflow
    -- so an orchestrator added later is covered without editing this test."""
    plans = 0
    for path in sorted(WORKFLOWS.glob("*.yaml")):
        jobs = _jobs(_load_workflow(path))
        if "plan" not in jobs:
            continue
        plans += 1
        plan = jobs["plan"]
        assert SETUP_ACTION_REFERENCE in [x.get("uses") for x in plan["steps"]], path
        commands = "\n".join(str(x.get("run", "")) for x in plan["steps"])
        assert "tomllib" not in commands, path
        assert not re.search(r"^\s*import\s", commands, re.MULTILINE), path
    assert plans, "no plan job found; the version authority is unasserted"

    # The plan jobs consume the version through the composite action's output, so the
    # single implementation is asserted where it actually lives.
    assert "scripts/committed_versions.py" in SETUP_ACTION.read_text(encoding="utf-8")
    # Pins the ORDERING, not the spelling. `X.Y.Z.devN` sorts BELOW `X.Y.Z` under PEP 440,
    # so a dev build of post-release work would look older than the release it follows and
    # pip would prefer the published release over it. The dev version must preview the NEXT
    # patch. An `endswith(".dev7")` assertion passes either way, which is why this defect
    # survived a restore: the code regressed and the suite stayed green.
    released = committed_versions.package_version()
    development = committed_versions.development_version(7)
    assert development.endswith(".dev7")
    assert Version(development) > Version(released), (
        f"{development} must sort above the released {released}"
    )
    major, minor, patch = released.split(".")
    assert development == f"{major}.{minor}.{int(patch) + 1}.dev7"


def test_any_push_triggered_workflow_verifies_before_it_ships() -> None:
    """Epic 7 deleted test.yaml and nothing replaced it, so pushes ran zero tests.
    build.yaml restored that, then went with the rest of the legacy publish path, so no
    workflow reacts to push right now -- Epic 8's dev.yaml closes that.

    Asserts the conditional invariant rather than the absent one: any workflow that does
    react to push must reach the verifier before anything that ships. Passes vacuously
    today and bites the moment a push workflow reappears. Deliberately does not assert
    that some push workflow exists -- that would be red for all of Epic 8, and a
    permanently-red gate gets disabled rather than fixed.
    """
    for path in sorted(WORKFLOWS.glob("*.yaml")):
        document = _load_workflow(path)
        triggers = document["on"]
        events = set(triggers) if not isinstance(triggers, str) else {triggers}
        if "push" not in events:
            continue
        jobs = _jobs(document)
        called = {name: job.get("uses") for name, job in jobs.items()}
        publishers = {
            name
            for name, used in called.items()
            if isinstance(used, str)
            and used.startswith("./.github/workflows/")
            and used != VERIFIER_REFERENCE
        }
        if not publishers:
            continue
        verifiers = {n for n, used in called.items() if used == VERIFIER_REFERENCE}
        assert verifiers, f"{path.name}: builds artifacts on push without the verifier"
        for publisher in publishers:
            assert verifiers <= _transitive_needs(jobs, publisher), (
                f"{path.name}: job {publisher!r} does not depend on the governed verifier"
            )


def test_no_workflow_calls_a_local_workflow_or_action_that_does_not_exist() -> None:
    # Deleting the legacy workflows left every `uses:` pointing at them dangling. GitHub
    # fails such a call at run time, not at lint time, so nothing else here catches it.
    for path in sorted(WORKFLOWS.glob("*.yaml")) + sorted(ACTIONS.rglob("action.yml")):
        text = path.read_text(encoding="utf-8")
        for reference in re.findall(r"uses:\s*(\./[^\s#]+)", text):
            target = PROJECT_ROOT / reference.removeprefix("./")
            if target.is_dir():
                target = target / "action.yml"
            assert target.exists(), f"{path.name}: `uses: {reference}` does not exist"


def test_no_workflow_holds_github_token_write_access_to_contents() -> None:
    """Named for exactly what it checks. `permissions:` configures only the automatic
    GITHUB_TOKEN, so a job authenticating with a PAT or App token is not governed by it
    at all. The behavioural guard below covers the credential this one cannot see."""
    for path in sorted(WORKFLOWS.glob("*.yaml")):
        document = _load_workflow(path)
        scopes = [(None, document.get("permissions"))]
        scopes += [
            (n, j.get("permissions")) for n, j in document.get("jobs", {}).items()
        ]
        for job_name, permissions in scopes:
            if not isinstance(permissions, dict):
                continue
            if permissions.get("contents") != "write":
                continue
            assert job_name in RELEASE_FINALIZER_JOBS, (
                f"{path.name}: `contents: write` makes CI a writer of repository "
                "contents; version identity goes through `just release` (ADR-0006)"
            )


def test_no_workflow_writes_refs_or_releases_outside_a_finalizer() -> None:
    """The behavioural half of the rule above -- it catches a push made with a PAT, which
    a `permissions:` check is structurally blind to."""
    write_commands = (
        r"\bgit\s+push\b",
        r"\bgh\s+release\s+(?:create|upload|edit|delete)\b",
        r"\bgh\s+api\b.*\breleases\b",
    )
    for path in sorted(WORKFLOWS.glob("*.yaml")):
        for job_name, job in _load_workflow(path).get("jobs", {}).items():
            if job_name in RELEASE_FINALIZER_JOBS:
                continue
            for step in job.get("steps", []) or []:
                command = str(step.get("run", ""))
                for pattern in write_commands:
                    assert not re.search(pattern, command), (
                        f"{path.name}: job {job_name!r} writes refs or releases; "
                        "register it in RELEASE_FINALIZER_JOBS with an ADR"
                    )
                name = str(step.get("uses", "")).split("@", 1)[0]
                assert not RELEASE_ACTION_VERB.search(name), (
                    f"{path.name}: job {job_name!r} uses a release/tag-writing action "
                    f"({name}); register it in RELEASE_FINALIZER_JOBS with an ADR"
                )


def test_releases_are_created_only_through_the_approved_action() -> None:
    """ADR-0010: one multi-platform action creates the Release on GitHub and on Gitea.

    Without this the ADR is prose. The cheapest way to ship a Release under deadline is a
    two-line `curl` against the forge API, which works on exactly one forge, and nothing
    would notice until E009 tried the other one. Gitea is GitHub-*shaped* but not
    GitHub-compatible -- asset upload was multipart-only before 1.22 and asset deletion
    still uses a different path -- so a hand-rolled client is a maintenance liability,
    not a shortcut.

    This governs *how* a Release is created; ADR-0006's RELEASE_FINALIZER_JOBS governs
    *which job* may create one.
    """
    hand_rolled = (
        r"\bgh\s+release\s+create\b",
        r"\bgh\s+api\b[^\n]*\breleases\b",
        r"\bcurl\b[^\n]*/api/v1/repos/[^\n]*/releases",
        r"\bcurl\b[^\n]*/repos/[^\n]*/releases",
    )
    for path in sorted(WORKFLOWS.glob("*.yaml")):
        for job_name, job in _jobs(_load_workflow(path)).items():
            for step in job.get("steps", []) or []:
                command = str(step.get("run", ""))
                for pattern in hand_rolled:
                    assert not re.search(pattern, command), (
                        f"{path.name}: job {job_name!r} creates a Release by hand. Use "
                        f"{APPROVED_RELEASE_ACTION}@v2, which speaks both GitHub's and "
                        f"Gitea's APIs from one step (ADR-0010)."
                    )


def test_no_workflow_delegates_versioning_to_an_external_release_bot() -> None:
    for path in sorted(WORKFLOWS.glob("*.yaml")):
        assert "release-please" not in path.read_text(encoding="utf-8"), (
            f"{path.name}: release-please is a competing version authority (ADR-0006)"
        )


def test_setup_action_owns_interpreter_and_poetry_installation() -> None:
    action = _load_document(SETUP_ACTION)
    assert action["runs"]["using"] == "composite"
    assert set(action["inputs"]) == {"python-version", "poetry", "dependencies"}
    assert {"package-version", "poetry-version"} <= set(action["outputs"])

    setup_python = action["runs"]["steps"][0]
    assert setup_python["uses"] == "actions/setup-python@v7"
    assert setup_python["with"]["python-version"] == "${{ inputs.python-version }}"

    # Every job that needs an interpreter goes through the action, so the interpreter
    # is pinned everywhere and the Poetry pin is resolved in exactly one place.
    for path in GOVERNED_DEFINITIONS:
        if path == SETUP_ACTION:
            continue
        source = path.read_text(encoding="utf-8")
        assert "actions/setup-python@" not in source, path
        assert "pipx install" not in source, path


def test_the_poetry_pin_has_one_authority_every_location_agrees_with() -> None:
    pin = committed_versions.poetry_version()
    assert re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", pin)

    # The composite action resolves the pin at run time from that authority; it does
    # not restate it.
    action_source = SETUP_ACTION.read_text(encoding="utf-8")
    assert "scripts/committed_versions.py" in action_source
    for path in GOVERNED_DEFINITIONS:
        assert re.search(r"poetry==[0-9]", path.read_text(encoding="utf-8")) is None, (
            path
        )

    # Locations consumed outside the workflow runtime still carry the literal. Each is
    # bound to the same authority here.
    bake = (PROJECT_ROOT / "docker-bake.hcl").read_text(encoding="utf-8")
    assert re.findall(r'POETRY_VERSION\s*=\s*"([^"]+)"', bake) == [pin]

    verify_source = VERIFY_WORKFLOW.read_text(encoding="utf-8")
    assert re.findall(r'"POETRY_VERSION":"([^"]+)"', verify_source) == [pin]

    developer = (PROJECT_ROOT / "docs" / "developer.md").read_text(encoding="utf-8")
    assert set(re.findall(r"Poetry ([0-9]+\.[0-9]+\.[0-9]+)", developer)) == {pin}


def test_pull_request_fixture_selects_head_sha_and_isolates_concurrency() -> None:
    event = _load_fixture("pull-request.json")
    pull_request = event["pull_request"]
    assert pull_request["base"]["ref"] == "main"
    assert pull_request["head"]["repo"]["fork"] is True
    assert pull_request["head"]["sha"] != event["sha"]
    assert re.fullmatch(r"[0-9a-f]{40}", pull_request["head"]["sha"])

    workflow_name = "Pull request verification"
    group = f"{workflow_name}-pr-{pull_request['number']}"
    other_group = f"{workflow_name}-pr-{pull_request['number'] + 1}"
    assert group == "Pull request verification-pr-42"
    assert group != other_group


def test_verifier_supports_call_and_direct_dispatch_with_the_same_graph() -> None:
    workflow = _load_workflow(VERIFY_WORKFLOW)
    triggers = workflow["on"]
    expected_inputs = {"channel", "package-version", "source-sha"}

    assert isinstance(triggers, dict)
    assert set(triggers) == {"workflow_call", "workflow_dispatch"}
    assert set(triggers["workflow_call"]["inputs"]) == expected_inputs
    assert set(triggers["workflow_dispatch"]["inputs"]) == expected_inputs
    assert set(_jobs(workflow)) == {
        "source-integrity",
        "poetry-lock",
        "ruff-check",
        "mypy",
        "ruff-format",
        "gitleaks",
        "actionlint",
        "file-hygiene",
        "pytest",
        "distribution",
    }
    assert "ACT" not in VERIFY_WORKFLOW.read_text(encoding="utf-8")

    event = _load_fixture("workflow-dispatch.json")
    assert event["event_name"] == "workflow_dispatch"
    assert event["inputs"] == {
        "channel": "ci",
        "package-version": "0.1.3",
        "source-sha": event["sha"],
    }


def test_local_wrapper_and_just_recipe_invoke_only_the_direct_verifier() -> None:
    wrapper = (PROJECT_ROOT / "docker" / "act-build.sh").read_text(encoding="utf-8")
    justfile = (PROJECT_ROOT / "justfile").read_text(encoding="utf-8")

    assert "set -euo pipefail" in wrapper
    assert 'SOURCE_SHA="$(git rev-parse HEAD)"' in wrapper
    assert 'PACKAGE_VERSION="$(poetry version --short)"' in wrapper
    assert "act workflow_dispatch" in wrapper
    assert "-W .github/workflows/verify-build.yaml" in wrapper
    assert "--input channel=ci" in wrapper
    assert '--input package-version="$PACKAGE_VERSION"' in wrapper
    assert '--input source-sha="$SOURCE_SHA"' in wrapper
    assert "--secret" not in wrapper
    assert "--env-file" not in wrapper
    assert "test-local:\n    ./docker/act-build.sh" in justfile
    assert "ci.yaml" not in wrapper


# `ACT` as a whole token, not a substring. A bare `"ACT" in text` check matches
# `PC_CONTRACT` and `GITHUB_ACTION_PATH`, so it fails on steps that never mention act --
# and a guard that cries wolf gets deleted rather than fixed.
_ACT_TOKEN = re.compile(r"(?<![A-Z_])ACT(?![A-Z_])")


def test_all_governed_steps_are_independent_of_the_act_environment() -> None:
    """No step may branch on act. The same YAML must run on GitHub, Gitea and locally;
    platform selection is data, not an `if:` on the emulator."""
    for path in GOVERNED_DEFINITIONS:
        for step in _steps(_load_document(path)):
            for field in ("if", "run"):
                assert not _ACT_TOKEN.search(str(step.get(field, ""))), (
                    f"{path}: step branches on the act environment via `{field}:`"
                )


ARTIFACT_ACTIONS = ("actions/upload-artifact", "actions/download-artifact")


def test_artifact_actions_remain_on_the_both_forge_v4_pair() -> None:
    """Deliberately NOT on the latest major, and the only such exception.

    Gitea's act_runner implements the v4 artifact protocol; v5+ are GitHub-only. The
    inherited invariant is that the same workflow YAML runs on GitHub, Gitea and local
    act, and Epic 9 is Certified Gitea Portability -- so forge compatibility wins over
    currency here. `actions/upload-artifact@v7` exists; taking it would drop Gitea.

    Revisit when Gitea's runner supports a newer artifact protocol.
    """
    references = _external_action_references(VERIFY_WORKFLOW)
    for action in ARTIFACT_ACTIONS:
        assert all(
            reference == f"{action}@v4"
            for reference in references
            if reference.startswith(f"{action}@")
        )


def test_dependabot_protects_the_artifact_pin_it_would_otherwise_undo() -> None:
    """A pin a bot reverts weekly is not a pin.

    Dependabot is what keeps every other action on its latest major, so left alone it
    proposes upload-artifact v7 until someone merges it and Gitea silently stops working.
    The exception above is only real if Dependabot is told about it.
    """
    dependabot = yaml.load(
        (PROJECT_ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8"),
        Loader=yaml.BaseLoader,
    )
    actions_entry = next(
        entry
        for entry in dependabot["updates"]
        if entry["package-ecosystem"] == "github-actions"
    )
    ignored = {
        rule["dependency-name"]
        for rule in actions_entry.get("ignore", [])
        if "version-update:semver-major" in rule.get("update-types", [])
    }
    assert set(ARTIFACT_ACTIONS) <= ignored, (
        "the forge-compatible artifact pin is not protected from Dependabot: "
        f"missing {sorted(set(ARTIFACT_ACTIONS) - ignored)}"
    )


def test_dependency_maintenance_covers_actions_python_and_docker() -> None:
    dependabot = yaml.load(
        (PROJECT_ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8"),
        Loader=yaml.BaseLoader,
    )
    configured = {
        (update["package-ecosystem"], update["directory"])
        for update in dependabot["updates"]
    }
    assert configured == {
        ("github-actions", "/"),
        ("pip", "/"),
        ("docker", "/docker"),
    }


def test_dispatch_fixture_uses_the_committed_poetry_version() -> None:
    event = _load_fixture("workflow-dispatch.json")
    assert event["inputs"]["package-version"] == committed_versions.package_version()


def test_every_gate_job_blocks_the_distribution_job() -> None:
    """A gate that does not block the build is decorative.

    Scope is derived: any job fanning out from `source-integrity` is a gate, so a gate
    added later is covered without editing this test. Written after adding the `mypy` job
    and forgetting to add it to `distribution.needs` -- it ran, it could fail, and nothing
    downstream cared.
    """
    jobs = _jobs(_load_workflow(VERIFY_WORKFLOW))
    gates = {
        name
        for name, job in jobs.items()
        if job.get("needs") == "source-integrity"
        or job.get("needs") == ["source-integrity"]
    }
    assert gates, "no gate jobs found; this test has drifted from the workflow"

    blocking = set(jobs["distribution"].get("needs") or [])
    assert gates <= blocking, (
        f"gate jobs that do not block distribution: {sorted(gates - blocking)}"
    )
