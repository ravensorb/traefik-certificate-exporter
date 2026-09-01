from __future__ import annotations

import importlib.util
import json
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).parents[2]
WORKFLOWS = PROJECT_ROOT / ".github" / "workflows"
ACTIONS = PROJECT_ROOT / ".github" / "actions"
FIXTURES = Path(__file__).parent / "fixtures" / "workflows"
CI_WORKFLOW = WORKFLOWS / "ci.yaml"
BUILD_WORKFLOW = WORKFLOWS / "build.yaml"
VERIFY_WORKFLOW = WORKFLOWS / "verify-build.yaml"
SETUP_ACTION = ACTIONS / "setup-poetry-python" / "action.yml"

VERIFIER_REFERENCE = "./.github/workflows/verify-build.yaml"
SETUP_ACTION_REFERENCE = "./.github/actions/setup-poetry-python"
# Workflows that build or ship an artifact. A push event that reaches one of these
# without first reaching the verifier is the regression this file exists to prevent.
PUBLISHER_REFERENCES = frozenset(
    {
        "./.github/workflows/build-container.yaml",
        "./.github/workflows/build-package.yaml",
    }
)


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
    # googleapis/release-please-action: official vendor action, generally available,
    # published under a maintained floating major alias. Approved rather than replaced
    # -- release-please has no local substitute.
    "googleapis",
}

# A maintained floating major alias, so a fix ships without a manifest edit. Most
# owners publish it as a `vN` tag; pypa publishes it as the `release/vN` branch, which
# is the same guarantee spelled differently. A pinned patch tag is not an alias.
FLOATING_MAJOR_ALIAS = re.compile(r"\A(?:release/)?v[0-9]+\Z")


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
            assert FLOATING_MAJOR_ALIAS.fullmatch(version), (
                f"{path}: {reference} must use the maintained floating major alias"
            )
    assert examined, "no external action references were examined"


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
    """ci.yaml's plan job used to be a third `tool.poetry.version` reader, inline, on
    an unpinned interpreter. Both plan jobs now pin the interpreter through the
    composite action and read the version through the shared script."""
    for path in (CI_WORKFLOW, BUILD_WORKFLOW):
        plan = _jobs(_load_workflow(path))["plan"]
        uses = [step.get("uses") for step in plan["steps"]]
        assert SETUP_ACTION_REFERENCE in uses, path
        commands = "\n".join(str(step.get("run", "")) for step in plan["steps"])
        assert "tomllib" not in commands, path
        # An inline heredoc reimplementation would need an import statement.
        assert not re.search(r"^\s*import\s", commands, re.MULTILINE), path

    build_plan = _jobs(_load_workflow(BUILD_WORKFLOW))["plan"]
    build_commands = "\n".join(str(step.get("run", "")) for step in build_plan["steps"])
    assert "scripts/committed_versions.py" in build_commands
    assert committed_versions.development_version(7) == (
        f"{committed_versions.package_version()}.dev7"
    )


def test_every_pushed_ref_reaches_the_governed_verifier() -> None:
    """Sprint S01 deleted test.yaml, and nothing replaced it: pushes to main and v*
    tags ran zero tests. This asserts the path back to the verifier exists and that a
    publisher can never be reached without it."""
    push_triggered = {}
    for path in sorted(WORKFLOWS.glob("*.yaml")):
        document = _load_workflow(path)
        triggers = document["on"]
        events = (
            set(triggers)
            if isinstance(triggers, dict)
            else {triggers}
            if isinstance(triggers, str)
            else set(triggers)
        )
        if "push" in events:
            push_triggered[path.name] = document
    assert push_triggered, "no workflow reacts to push; main can never be verified"

    verified_builders = set()
    for name, document in push_triggered.items():
        jobs = _jobs(document)
        called = {job_name: job.get("uses") for job_name, job in jobs.items()}
        publishers = {j for j, used in called.items() if used in PUBLISHER_REFERENCES}
        if not publishers:
            continue
        verifiers = {j for j, used in called.items() if used == VERIFIER_REFERENCE}
        assert verifiers, f"{name}: builds artifacts on push without the verifier"
        for publisher in publishers:
            assert verifiers <= _transitive_needs(jobs, publisher), (
                f"{name}: job {publisher!r} does not depend on the governed verifier"
            )
        verified_builders.add(name)
    assert verified_builders, "no push-triggered workflow builds through the verifier"

    build = _load_workflow(BUILD_WORKFLOW)
    push = build["on"]["push"]
    assert set(push["branches"]) == {"main", "master"}
    assert push["tags"] == ["v*"]

    verify = _jobs(build)["verify"]
    assert verify["uses"] == VERIFIER_REFERENCE
    assert verify["with"] == {
        "channel": "${{ needs.plan.outputs.channel }}",
        "package-version": "${{ needs.plan.outputs.package-version }}",
        "source-sha": "${{ needs.plan.outputs.source-sha }}",
    }

    # Branch pushes verify a development version; v* tags verify the committed
    # release identity. Both reach the same verifier.
    plan_commands = "\n".join(
        str(step.get("run", "")) for step in _jobs(build)["plan"]["steps"]
    )
    assert 'channel="dev"' in plan_commands
    assert 'channel="stable"' in plan_commands


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


def test_artifact_actions_remain_on_the_both_forge_v4_pair() -> None:
    references = _external_action_references(VERIFY_WORKFLOW)
    for action in ("actions/upload-artifact", "actions/download-artifact"):
        assert all(
            reference == f"{action}@v4"
            for reference in references
            if reference.startswith(f"{action}@")
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
