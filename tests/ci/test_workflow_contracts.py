from __future__ import annotations

import copy
import fnmatch
import importlib.util
import itertools
import json
import os
import re
import subprocess
import sys
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import yaml

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - exercised only on the oldest supported interpreter
    # pyproject declares >=3.10 and `tomllib` arrived in 3.11. `tomli` is the same
    # parser under its pre-stdlib name and is already resolved for <3.11 by the lock.
    import tomli as tomllib
from markdown_it import MarkdownIt
from packaging.version import Version

from tests.support import tracked_text_files

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
# apply only to definitions that can execute fork-authored code, because those must
# never hold a publishing capability -- the publisher workflows legitimately do.
#
# This was a hand-kept `(CI_WORKFLOW, VERIFY_WORKFLOW)` tuple: the *same* 2-tuple that
# tier 1 replaced with a filesystem derivation, left eight lines below the derivation
# that replaced it, carrying the rules that matter more. A second `pull_request`
# workflow on a disjoint branch filter -- a shape the topology guard asserts lawful --
# ran fork code on a self-hosted runner with `packages: write` and a registry login,
# and not one guard fired. The set is now derived; the seed is the event.
FORK_EVENTS = frozenset({"pull_request", "pull_request_target"})

# Jobs permitted to write repository contents -- push refs, or create a forge Release.
# A registry of granted exceptions, not a derived scope: adding a name here IS the grant,
# and each needs an ADR. ADR-0006 draws the line at *identity* -- the committed version
# and the exact vX.Y.Z tag are chosen only by the local guarded transaction. A finalizer
# attaching a Release, its assets, or moving aliases to an identity already decided is not
# a second version authority. Empty until Epic 8 registers one.
# `(workflow filename, job name)` pairs, NOT bare job names. A bare-name registry matches
# across every workflow, so granting `finalize` for release.yaml would silently grant the
# same name in dev.yaml -- and Epic 8 creates a finalizer in both files (gate finding F6).
# Widened before the first entry is added, while the set is still empty and the change is
# free.
#
# Epic 8 story E008-S01-003 registers three, and each entry is a deliberate grant:
#
# * `("release.yaml", "finalize")` -- creates the forge Release through
#   `LiquidLogicLabs/git-action-release@v2` (ADR-0010) and advances `vMAJOR` /
#   `vMAJOR.MINOR` through `LiquidLogicLabs/git-action-tag-floating-version@v2`
#   (ADR-0006 as amended). It is the only job in the repository declaring
#   `contents: write`, and it holds no registry credential at all.
# * `("release.yaml", "finalize-image-aliases")` -- points the `MAJOR.MINOR`, `MAJOR`
#   and `latest` image names at the digest that was already published. It writes no
#   ref and declares no `contents: write`; it is registered because it moves an alias,
#   and alias ownership is what the sole-ownership guard below asserts.
# * `("dev.yaml", "finalize-dev-alias")` -- points the `dev` image name at the
#   published digest, after proving the candidate is still the protected default
#   branch's head. Also no ref write.
#
# ADR-0006 draws the line at identity, and none of the three chooses a version: the
# committed version and the exact `vX.Y.Z` tag are still the local guarded
# transaction's alone. A Release and an alias attach to an identity already decided.
RELEASE_FINALIZER_JOBS: frozenset[tuple[str, str]] = frozenset(
    {
        ("release.yaml", "finalize"),
        ("release.yaml", "finalize-image-aliases"),
        ("dev.yaml", "finalize-dev-alias"),
    }
)

# `release` and `tag` as verbs in an action name -- the ref-writing ones. `publish` is
# deliberately absent so pypa/gh-action-pypi-publish and image pushes, which write no ref,
# are not caught by a guard about repository writes.
RELEASE_ACTION_VERB = re.compile(r"(?:\A|[-/])(?:release|tag)(?:[-/]|\Z)")
SECRET_FREE_PROHIBITIONS = (
    "secrets:",
    # `secrets:` is the mapping a caller passes down; `secrets.` is the expression that
    # materialises one into a step. The list had only the first, so an `env:` block
    # naming `${{ secrets.NPM_TOKEN }}` inside the pull-request adapter's own job was
    # invisible to every guard here.
    "secrets.",
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

# The inverse registry: actions that ARE handed a publication credential and stay on a
# floating major anyway. Not a claim that they are safe -- a registry of accepted risk,
# and the reason is the entry. Whoever can move one of these refs can exfiltrate the
# credential it receives on the next run, with no diff in this repository to review.
#
# Adding an entry IS the acceptance, and each needs an ADR, exactly as adding to
# SHA_PINNED_ACTIONS is the grant (ADR-0009). Every entry here was found by
# `_credential_handling_actions`, which derives candidates from what a step is handed;
# the previous reach guard matched the words "pypi" or "publish" in an action's name and
# saw none of them.
CREDENTIAL_ACTIONS_ON_MOVING_REFS: dict[str, str] = {
    # Maintainer-owned org (confirmed with the maintainer at E008 sprint closure; ADR-0010
    # called this "first-party in practice" and that is accurate). The residual risk is
    # the maintainer's own account rather than a third party's, and the floating major is
    # what makes an upstream fix reach this repository without a manifest edit.
    "LiquidLogicLabs/git-action-release": (
        "receives contents: write GITHUB_TOKEN as `token`; maintainer-owned org"
    ),
    "LiquidLogicLabs/git-action-tag-floating-version": (
        "receives GITHUB_TOKEN through GIT_CONFIG_VALUE_0; maintainer-owned org"
    ),
    "LiquidLogicLabs/git-action-docker-test": (
        "runs after both registry logins, so it can read ~/.docker/config.json; "
        "maintainer-owned org"
    ),
    # An approved owner under CI-AR4, and the one action here nobody in this project
    # controls. Kept floating on the ordinary CI-AR4 grounds -- a large, widely audited
    # owner whose security fixes should arrive without a manifest edit.
    "docker/login-action": "receives DOCKERHUB_USERNAME and DOCKERHUB_TOKEN",
}

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


def _is_publishing_step(step: dict[str, Any]) -> bool:
    """The step that actually ships. Everything before it is 'pre-upload'."""
    uses = str(step.get("uses", ""))
    if uses.startswith(("pypa/gh-action-pypi-publish", APPROVED_RELEASE_ACTION)):
        return True
    command = str(step.get("run", ""))
    return bool(
        re.search(
            r"(?:buildx\s+bake|docker\s+push|buildx\s+build[^\n]*--push|twine\s+upload)",
            command,
        )
    )


def _is_credential_bearing(job: dict[str, Any]) -> bool:
    """A job that holds, or can hold, a publication credential.

    Derived from capability rather than from job name or shape: any `secrets.*`
    expression anywhere in the job, or a permission that lets it push somewhere.
    """
    permissions = job.get("permissions")
    if isinstance(permissions, dict):
        for scope in ("packages", "id-token", "attestations"):
            if permissions.get(scope) == "write":
                return True
    if job.get("secrets") is not None:
        return True
    return "secrets." in json.dumps(job)


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

    # Tier 2 is a proper subset of tier 1: every fork-facing definition is also
    # governed, and the tier-2 set is smaller because publishers are excluded.
    assert set(_fork_facing_definitions()) < set(GOVERNED_DEFINITIONS)
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


REGISTRY_LOGIN_ACTION = "docker/login-action"


def _definition_step_lists(document: dict[str, Any]) -> list[dict[str, Any]]:
    """Every ordered step list in a workflow or a composite action.

    A composite action holds one list under `runs.steps`; a workflow holds one per job.
    Composite actions are in scope because they run inside the credential-bearing job
    and see the same runner state.
    """
    if "jobs" in document:
        return list(_jobs(document).values())
    runs = document.get("runs") or {}
    return [{"steps": runs.get("steps") or []}]


def _credential_handling_actions(
    definitions: dict[str, dict[str, Any]] | None = None,
) -> dict[str, set[str]]:
    """External actions handed a publication credential, and why -- derived.

    Two mechanically checkable ways an action receives one:

    * a `secrets.*` expression reaches it, through its own `with:`/`env:` or through a
      `secrets:` block on the job that calls it;
    * it runs *after* a registry login in the same job, so the runner's
      `~/.docker/config.json` holds credentials for it to read. Nothing is passed to it
      and it has them anyway, which is why "what is passed" alone is not the test.

    The rule this replaces matched `pypi|publish` against the action's *repository
    name*. That is a hand-enumerated scope wearing a derivation's clothes: four actions
    shipped this sprint are handed a credential and match neither word, so the guard
    skipped them and the floating-major branch passed them (redteam H1).
    """
    if definitions is None:
        definitions = {
            str(path.relative_to(PROJECT_ROOT)): _load_document(path)
            for path in GOVERNED_DEFINITIONS
        }
    found: dict[str, set[str]] = {}
    for document in definitions.values():
        for job in _definition_step_lists(document):
            after_login = False
            for step in job.get("steps") or []:
                used = str(step.get("uses", ""))
                if used and not used.startswith("./"):
                    action = used.rpartition("@")[0]
                    handed = json.dumps({key: step.get(key) for key in ("with", "env")})
                    reasons = set()
                    if "secrets." in handed:
                        reasons.add("a secret is passed to it")
                    if job.get("secrets") is not None:
                        reasons.add("its job receives secrets")
                    if after_login:
                        reasons.add("it runs after a registry login")
                    if reasons:
                        found.setdefault(action, set()).update(reasons)
                    if action.startswith(REGISTRY_LOGIN_ACTION):
                        after_login = True
    return found


def test_every_credential_handling_action_is_pinned_or_its_risk_is_recorded() -> None:
    """ADR-0009's reach half, over a set derived from what an action is handed.

    An action on a floating major is one moved ref away from exfiltrating whatever it
    receives, and nothing in this repository would change. So each candidate is either
    SHA-pinned or its acceptance is written down with a reason -- silence is the one
    outcome the registry does not allow.
    """
    candidates = _credential_handling_actions()
    assert candidates, "no action receives a credential; this guard examined nothing"
    for action, reasons in sorted(candidates.items()):
        assert (
            action in SHA_PINNED_ACTIONS or action in CREDENTIAL_ACTIONS_ON_MOVING_REFS
        ), (
            f"{action} is handed a publication credential ({'; '.join(sorted(reasons))}) "
            f"and rides a moving ref. Register it in SHA_PINNED_ACTIONS, or record the "
            f"accepted risk in CREDENTIAL_ACTIONS_ON_MOVING_REFS with an ADR (CI-AR38)."
        )
    assert not (SHA_PINNED_ACTIONS & set(CREDENTIAL_ACTIONS_ON_MOVING_REFS)), (
        "an action cannot be both SHA-pinned and recorded as accepted on a moving ref"
    )
    stale = set(CREDENTIAL_ACTIONS_ON_MOVING_REFS) - set(candidates)
    assert not stale, (
        f"{sorted(stale)} accept a risk this repository no longer takes; a registry that "
        f"outlives its entries stops being read"
    )


def test_the_credential_reach_follows_what_an_action_receives_not_its_name() -> None:
    """The scope attack. Neither planted action's name says `pypi` or `publish`, which
    is precisely how four real ones went unexamined for the whole sprint."""
    planted = {
        "plant.yaml": {
            "on": {"push": {}},
            "jobs": {
                "ship": {
                    "runs-on": "ubuntu-24.04",
                    "steps": [
                        {
                            "uses": "vendor/upload-thing@v1",
                            "with": {"token": "${{ secrets.VENDOR_TOKEN }}"},
                        },
                        {
                            "uses": "docker/login-action@v3",
                            "with": {"password": "${{ secrets.REGISTRY_TOKEN }}"},
                        },
                        {"uses": "vendor/smoke-test@v2"},
                    ],
                }
            },
        }
    }
    found = _credential_handling_actions(planted)
    assert found["vendor/upload-thing"] == {"a secret is passed to it"}
    assert found["vendor/smoke-test"] == {"it runs after a registry login"}, (
        "an action that reads the runner's docker config is handed a credential too, "
        "even though nothing is passed to it"
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


def _local_references(path: Path) -> set[Path]:
    """Every local workflow or composite action a definition names with `uses: ./...`.

    Resolved from the file's own text, so a directory reference picks up its
    `action.yml` the way the runner does.
    """
    found: set[Path] = set()
    for reference in re.findall(
        r"uses:\s*(\./[^\s#]+)", path.read_text(encoding="utf-8")
    ):
        target = PROJECT_ROOT / reference.removeprefix("./")
        found.add(target / "action.yml" if target.is_dir() else target)
    return found


def _fork_facing_workflow_names(documents: dict[str, dict[str, Any]]) -> set[str]:
    """Workflow filenames that can execute fork-authored code.

    Seeded from whoever owns a `pull_request*` event and closed over local
    `workflow_call`s, because a reusable workflow inherits its caller's trust boundary.
    Pure over parsed documents so the scope attack below runs through this exact code.
    """
    reachable = {
        name
        for name, document in documents.items()
        if _declared_events(document) & FORK_EVENTS
    }
    frontier = list(reachable)
    while frontier:
        document = documents.get(frontier.pop())
        if document is None:
            continue
        for job in _jobs(document).values():
            used = job.get("uses")
            if isinstance(used, str) and used.startswith("./.github/workflows/"):
                name = used.rsplit("/", 1)[-1]
                if name not in reachable:
                    reachable.add(name)
                    frontier.append(name)
    return reachable


def _fork_facing_definitions() -> tuple[Path, ...]:
    """The fork-facing workflows plus every composite action they reach, from disk."""
    documents = {path.name: _load_workflow(path) for path in WORKFLOWS.glob("*.yaml")}
    resolved: set[Path] = set()
    frontier = [WORKFLOWS / name for name in _fork_facing_workflow_names(documents)]
    while frontier:
        path = frontier.pop()
        if path in resolved or not path.exists():
            continue
        resolved.add(path)
        frontier.extend(_local_references(path))
    return tuple(sorted(resolved))


def test_tier_two_fork_facing_definitions_hold_no_publisher_capability() -> None:
    """ADR-0007 invariant 2, over every definition that can run a fork's code."""
    definitions = _fork_facing_definitions()
    assert definitions, "nothing reacts to a pull request; this guard examined nothing"
    for path in definitions:
        source = path.read_text(encoding="utf-8")
        for forbidden in SECRET_FREE_PROHIBITIONS:
            assert forbidden not in source, f"{path}: {forbidden}"
        if path.parent != WORKFLOWS:
            continue
        for job_name, job in _jobs(_load_workflow(path)).items():
            # The substrings above read the file; this reads the parsed job, so a
            # capability spelled a way the list does not anticipate still fails.
            assert not _is_credential_bearing(job), (
                f"{path.name}: job {job_name!r} runs fork-authored code and holds a "
                f"publication capability (ADR-0007 invariant 2)"
            )


def test_the_fork_facing_scope_follows_the_event_not_a_list_of_files() -> None:
    """The scope attack. Each planted document is a workflow the hand-kept 2-tuple
    could not see: a second pull-request entry point, and a reusable workflow that only
    a fork-facing caller reaches."""
    documents = {path.name: _load_workflow(path) for path in WORKFLOWS.glob("*.yaml")}
    assert _fork_facing_workflow_names(documents) >= {"ci.yaml", "verify-build.yaml"}

    planted = dict(documents)
    planted["pr-preview.yaml"] = {
        "on": {"pull_request": {"branches": ["release/**"]}},
        "jobs": {
            "preview": {
                "runs-on": "self-hosted",
                "permissions": {"packages": "write"},
                "uses": "./.github/workflows/preview-publish.yaml",
            }
        },
    }
    planted["preview-publish.yaml"] = {
        "on": {"workflow_call": {}},
        "jobs": {"push": {"runs-on": "ubuntu-24.04", "steps": []}},
    }
    names = _fork_facing_workflow_names(planted)
    assert "pr-preview.yaml" in names, (
        "a second pull-request workflow escaped the scope"
    )
    assert "preview-publish.yaml" in names, (
        "a reusable workflow reached only from a fork-facing caller escaped the scope"
    )


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
    # Keyed on what the job DOES, not what it is called (gate finding F12). Keying on the
    # name `plan` meant a dev.yaml whose version job was called `identity` or `resolve`
    # was silently ungoverned and free to re-implement version derivation.
    plans = 0
    for path in sorted(WORKFLOWS.glob("*.yaml")):
        for job_name, job in _jobs(_load_workflow(path)).items():
            outputs = job.get("outputs") or {}
            # Any version-shaped output, not the one literal name. Re-keying from the job
            # name `plan` to the output name `package-version` swapped one hand-kept
            # string for another: a job emitting `dev-version` and re-deriving with
            # tomllib passed, while the docstring claimed it was keyed on behaviour.
            if not any("version" in name for name in outputs):
                continue
            plans += 1
            steps = job.get("steps", []) or []
            assert SETUP_ACTION_REFERENCE in [x.get("uses") for x in steps], (
                f"{path}: job {job_name!r} emits package-version without the setup action"
            )
            commands = "\n".join(str(x.get("run", "")) for x in steps)
            # Targeted at version DERIVATION, not at inline Python generally. Widening the
            # scope from `plan`-named jobs caught verify-build.yaml's `distribution` job,
            # which also emits package-version but as a pass-through, and which uses
            # heredocs legitimately for checksum and artifact validation. A blanket
            # "no import" rule would have failed it for the wrong reason.
            # `poetry version` is deliberately NOT here: verify-build.yaml's distribution
            # job reads it to cross-check, and applies the planned version into a
            # disposable checkout. That consumes the authority, it does not become one.
            # The original defect was an inline tomllib parse of pyproject.toml.
            for reimplementation in ("tomllib", "tool.poetry.version"):
                assert reimplementation not in commands, (
                    f"{path}: job {job_name!r} derives the committed version inline "
                    f"({reimplementation!r}); it comes from committed_versions.py via "
                    f"the setup action and nowhere else"
                )
    assert plans, "no job emits package-version; the version authority is unasserted"

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


def _workflow_documents() -> dict[str, dict[str, Any]]:
    """Every governed workflow, parsed, keyed by filename."""
    return {
        path.name: _load_workflow(path) for path in sorted(WORKFLOWS.glob("*.yaml"))
    }


def _unverified_shipping_findings(documents: dict[str, dict[str, Any]]) -> list[str]:
    """Entry points that can ship without reaching the governed verifier.

    Pure over parsed documents so the scope attack below runs through this exact code
    rather than a second implementation that can agree with it while both are wrong.
    """
    findings: list[str] = []
    for name, document in sorted(documents.items()):
        events = _declared_events(document)
        # Every event that can start a run on its own, derived as a complement. The
        # previous form was a literal `{push, release, workflow_dispatch, schedule}`
        # that had already grown by one entry each time a hole was found -- and
        # `repository_dispatch`, `workflow_run`, `merge_group`, `create` and
        # `pull_request_target` were all still missing, each of them a way to reach a
        # publisher having run nothing. `workflow_call` is the single exemption: a
        # reusable workflow is not an entry point, and its caller owns the gate.
        if not (events - {"workflow_call"}):
            continue
        jobs = _jobs(document)
        called = {job_name: job.get("uses") for job_name, job in jobs.items()}
        # A publisher is anything that ships or can ship -- derived from capability, not
        # from shape (gate finding F15). Recognising only "calls another local workflow"
        # made this pass vacuously over Epic 8's dev.yaml, whose publishers are ordinary
        # step-based jobs holding registry credentials.
        publishers = set(_publishers(document))
        if not publishers:
            continue
        verifiers = {n for n, used in called.items() if used == VERIFIER_REFERENCE}
        if not verifiers:
            findings.append(
                f"{name}: publishes on {sorted(events)} without the governed verifier"
            )
            continue
        for publisher in sorted(publishers):
            if not verifiers <= _transitive_needs(jobs, publisher):
                findings.append(
                    f"{name}: job {publisher!r} does not depend on the governed verifier"
                )
    return findings


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
    findings = _unverified_shipping_findings(_workflow_documents())
    assert not findings, findings


@pytest.mark.parametrize(
    "trigger",
    [
        {"repository_dispatch": {"types": ["nightly"]}},
        {"workflow_run": {"workflows": ["ci"], "types": ["completed"]}},
        {"merge_group": {}},
        {"create": None},
        {"release": {"types": ["published"]}},
        {"schedule": [{"cron": "0 3 * * *"}]},
    ],
)
def test_the_shipping_gate_scope_follows_capability_not_a_list_of_events(
    trigger: dict[str, Any],
) -> None:
    """The scope attack. Every trigger here reaches a publisher on its own, and the
    previous literal event set saw only two of them -- so a job holding `id-token:
    write` could upload to PyPI having run no tests at all."""
    planted = _workflow_documents()
    planted["nightly.yaml"] = {
        "on": trigger,
        "jobs": {
            "publish-package-pypi": {
                "runs-on": "ubuntu-24.04",
                "permissions": {"id-token": "write"},
                "steps": [{"uses": "pypa/gh-action-pypi-publish@release/v1"}],
            }
        },
    }
    findings = _unverified_shipping_findings(planted)
    assert any("nightly.yaml" in finding for finding in findings), (
        f"a publisher on {sorted(trigger)} shipped without the verifier: {findings}"
    )


def test_no_workflow_exposes_a_secret_at_workflow_scope() -> None:
    """A `secrets.*` expression in workflow-level `env:` or `defaults:` is visible to
    every job in the file, including ones that must not see it.

    This is the cheapest possible form of the scope failure a per-job secret audit is
    meant to prevent, and a per-job audit is structurally blind to it (gate finding F10).
    Per-job `env:` is the correct pattern: it keeps the blast radius of a compromised
    step to the job that actually needs the credential.
    """
    for path in sorted(WORKFLOWS.glob("*.yaml")):
        document = _load_workflow(path)
        for scope in ("env", "defaults"):
            block = document.get(scope)
            if block is None:
                continue
            assert "secrets." not in json.dumps(block), (
                f"{path.name}: workflow-level `{scope}:` references a secret, exposing it "
                f"to every job in the file. Scope it to the job that needs it."
            )


def test_no_publisher_queries_a_destination_before_uploading() -> None:
    """Retired CI-AR26 was remote identity reconciliation, and the retirement spec forbids
    reviving it. The tempting reading of "halt on an immutable conflict" is "check whether
    this version already exists before uploading" -- which is exactly that, under a new
    name (gate finding F17).

    Detection is the destination action's own failure: pypa's action rejects a duplicate,
    a registry rejects an immutable tag. The halt is operator-mediated via the runbook.
    """
    remote_probes = (
        r"\bpip\s+index\s+versions\b",
        r"\bcurl\b[^\n]*/pypi/[^\n]*/json",
        r"\bdocker\s+manifest\s+inspect\b",
        r"\bbuildx\s+imagetools\s+inspect\b",
    )
    # "Before uploading" is the whole rule, and the first version of this guard did not
    # encode it -- it rejected the probe anywhere in the job. That made the post-push
    # platform inspection ADR-0008 and CI-AR39 *mandate* into a test failure, so story
    # 001 was unbuildable: a required mechanism rejected by a shipped guard. Position
    # relative to the upload is the distinction, so the guard has to find the upload.
    for path in sorted(WORKFLOWS.glob("*.yaml")):
        for job_name, job in _jobs(_load_workflow(path)).items():
            if not _is_credential_bearing(job):
                continue
            steps = job.get("steps", []) or []
            upload_at = next(
                (i for i, step in enumerate(steps) if _is_publishing_step(step)),
                len(steps),
            )
            for step in steps[:upload_at]:
                command = str(step.get("run", ""))
                for probe in remote_probes:
                    assert not re.search(probe, command), (
                        f"{path.name}: publisher {job_name!r} queries a destination "
                        f"before uploading, reviving retired CI-AR26. Let the "
                        f"destination reject the duplicate and halt on its failure. "
                        f"(Inspecting what you just published is fine -- after the push.)"
                    )


def test_a_job_gating_on_publishers_uses_not_cancelled_never_always() -> None:
    """ADR-0011: the finalizer must run despite a legitimately skipped destination, so it
    cannot rely on `needs:` alone -- but `always()` is the wrong way to get there.

    `always()` runs the job even when the workflow was cancelled, so aliases could advance
    over a half-published artifact set. GitHub documents `!cancelled()` as the recommended
    alternative for exactly this reason. The difference is invisible until someone cancels
    a release mid-fan-out, which is precisely when it matters.
    """
    for path in sorted(WORKFLOWS.glob("*.yaml")):
        for job_name, job in _jobs(_load_workflow(path)).items():
            # Steps too: a job-level `!cancelled()` with a step-level `always()` inside it
            # reintroduces exactly what the job-level check forbids, one level down.
            for step in job.get("steps", []) or []:
                assert "always()" not in str(step.get("if", "")), (
                    f"{path.name}: job {job_name!r} has a step using `always()`. It runs "
                    f"on cancellation too; use `!cancelled()` (ADR-0011)."
                )
            condition = str(job.get("if", ""))
            assert "always()" not in condition or not job.get("needs"), (
                f"{path.name}: job {job_name!r} gates on other jobs with `always()`. Use "
                f"`!cancelled()` -- `always()` also runs on cancellation, which would let "
                f"a finalizer act on a half-published set (ADR-0011)."
            )
            # Forbidding always() is only half of it. A finalizer with NO `if:` at all is
            # skipped the moment any publisher is skipped -- which is ADR-0011's exact
            # failure: green run, aliases unmoved, no alert. So the condition is required,
            # not merely constrained.
            if (path.name, job_name) not in RELEASE_FINALIZER_JOBS:
                continue
            assert "!cancelled()" in condition.replace(" ", ""), (
                f"{path.name}: finalizer {job_name!r} has no `!cancelled()` condition, so "
                f"a legitimately skipped optional destination skips it too -- the release "
                f"finishes green with aliases unmoved and nothing reported (ADR-0011)."
            )


def test_the_enabled_destination_set_has_one_producer() -> None:
    """ADR-0011: publishers consume the enabled set; they never re-read `PUBLISH_*`.

    Two readers of one truth is the F7 defect one layer along -- the static job graph and
    the runtime enabled set drift apart, and the finalizer starts blocking on a
    destination nobody turned off. The plan job is the single producer.
    """
    toggle = re.compile(r"\bPUBLISH_[A-Z_]+\b")
    for path in sorted(WORKFLOWS.glob("*.yaml")):
        for job_name, job in _jobs(_load_workflow(path)).items():
            outputs = job.get("outputs") or {}
            # The producer is a job that PLANS -- it emits the set and ships nothing. A
            # publisher that also declares `enabled-destinations` used to escape by
            # naming the output, which is the guard reading a label instead of a role.
            produces = "enabled-destinations" in outputs or any(
                "version" in name for name in outputs
            )
            if produces and not _is_credential_bearing(job):
                continue
            body = json.dumps(job)
            assert not toggle.search(body), (
                f"{path.name}: job {job_name!r} reads a PUBLISH_* toggle directly. The "
                f"enabled set is produced once by the plan job and consumed from its "
                f"output (ADR-0011)."
            )


# Every spelling of "ask a registry what is there". One authority, consumed by the alias
# ordering guard below and by the placement guard story E008-S01-001 added: two hand-kept
# copies of the same pattern list would drift, and the copy nobody updated would be the
# one still reporting success.
REGISTRY_READ_COMMANDS = (
    r"\bdocker\s+manifest\s+inspect\b",
    r"\bbuildx\s+imagetools\s+inspect\b",
    r"\bskopeo\s+(?:inspect|list-tags)\b",
    r"\bcrane\s+(?:ls|digest|manifest)\b",
)


def test_alias_ordering_is_decided_from_git_never_from_a_registry() -> None:
    """ADR-0011 / gate finding F4: the Git tag set is the only ordering authority.

    `git-action-tag-floating-version` moves an alias **unconditionally** -- it performs
    the move, it does not decide whether the move is correct. Tag `v1.2.4` after `v1.3.0`
    exists and it will drag `v1` backwards. So the *decision* is the workflow's, and it
    must come from the tag set: an alias advances only if the released tag is the greatest
    annotated `vX.Y.Z` (and for `vX.Y`, the greatest within its minor).

    Reading a registry to answer it -- "what does `latest` point at?" -- is a
    per-destination remote-state read, one refactor from retired CI-AR26, and wrong on its
    own terms: the registry is a publication side effect, not the version authority.
    """
    findings = _alias_ordering_findings(_workflow_documents())
    assert not findings, findings


def _alias_ordering_findings(documents: dict[str, dict[str, Any]]) -> list[str]:
    """Registry reads in any file that moves an alias.

    Scope is the whole workflow, not the alias job: restricting it to the job holding
    the action let a `skopeo inspect` in the plan job decide ordering and hand the
    answer downstream -- the same remote-state read, one job earlier.

    Which workflows those are comes from `_alias_moving_jobs`, not from "contains a
    `git-action-tag-floating-version` step". That earlier test keyed the scope on the
    action name, so `dev.yaml` -- which moves the `dev` image alias with `buildx
    imagetools create` and holds no Git-alias step -- was excluded outright, and
    `release.yaml` was covered only incidentally, because it happens to move a Git
    alias too. Deleting that one step would have dropped it from the scope while it
    still moved three image aliases.
    """
    alias_files = {workflow for workflow, _ in _alias_moving_jobs(documents)}
    findings: list[str] = []
    for name, document in sorted(documents.items()):
        if name not in alias_files:
            continue
        for job_name, job in _jobs(document).items():
            for step in job.get("steps", []) or []:
                command = str(step.get("run", ""))
                for probe in REGISTRY_READ_COMMANDS:
                    if re.search(probe, command):
                        findings.append(
                            f"{name}: job {job_name!r} moves aliases and reads a "
                            f"registry. Ordering comes from the Git tag set alone (F4)."
                        )
    return findings


def test_the_alias_ordering_scope_covers_registry_aliases_not_just_git_ones() -> None:
    """The scope attack, planted in the file the sprint taught to move an alias.

    `dev.yaml` moves the `dev` tag with `imagetools create`, so a registry read in any
    of its jobs decides ordering from a publication side effect -- the retired-CI-AR26
    revival this guard exists to prevent. The previous scope could not see the file at
    all, and `dev.yaml` asserted in a comment that it could.
    """
    documents = _workflow_documents()
    assert "dev.yaml" in {workflow for workflow, _ in _alias_moving_jobs(documents)}, (
        "dev.yaml no longer moves an alias; this attack examined nothing"
    )
    planted = {name: copy.deepcopy(document) for name, document in documents.items()}
    plan = _jobs(planted["dev.yaml"])["plan"]
    plan.setdefault("steps", []).append(
        {"name": "Decide", "run": 'docker buildx imagetools inspect "$IMAGE:dev"'}
    )
    findings = _alias_ordering_findings(planted)
    assert any("dev.yaml" in finding for finding in findings), findings


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
            # A non-dict `permissions:` is the scalar `write-all` / `read-all` form,
            # which grants every scope. Skipping it -- which every permission reader in
            # this file used to do -- walks straight past the ADR-0006 grant registry:
            # a job spelled that way holds `contents: write` while being registered
            # nowhere. `test_no_workflow_uses_the_scalar_permissions_form` forbids it
            # outright; this is the same refusal at the site that matters most, because
            # a guard that depends on another guard's existence is one deletion from
            # vacuous.
            assert permissions is None or isinstance(permissions, dict), (
                f"{path.name}: {job_name or 'workflow'} uses the scalar `permissions:` "
                f"form, which grants every scope and is invisible to the ADR-0006 grant "
                f"registry; spell the scopes out"
            )
            if permissions is None:
                continue
            if permissions.get("contents") != "write":
                continue
            assert (path.name, job_name) in RELEASE_FINALIZER_JOBS, (
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
            if (path.name, job_name) in RELEASE_FINALIZER_JOBS:
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


# Moving a floating major is a non-fast-forward ref update, and
# LiquidLogicLabs/git-action-tag-floating-version does it. Unlike git-action-release it
# needs no forge backend: a tag is a git concept, not a forge one, so the action pushes
# refs with plain git and is portable to Gitea for free. A Release is the opposite -- a
# forge object -- which is why that one needs per-API handling (ADR-0010).
APPROVED_ALIAS_ACTION = "LiquidLogicLabs/git-action-tag-floating-version"

# Any spelling of a non-fast-forward ref write. Hand-rolling one is what this forbids.
# Every spelling, because ADR-0006 claims "under any spelling" and a guard that only
# matched `--force` made that claim false. `-f` is the one an implementer reaches for, and
# delete-and-recreate (`push origin :ref`) does not contain the word "force" at all.
FORCED_REF_WRITE = re.compile(
    r"(?:"
    r"git\s+push[^\n]*(?:--force\b|--force-with-lease|\s-f\b)"
    r"|git\s+push[^\n]*\s:refs?/"  # delete-and-recreate
    r"|git\s+push[^\n]*\s\+refs/"  # forced refspec
    r"|\bforce\s*[:=]\s*true"  # API force
    r"|git\s+tag\s+-d\b"  # local delete preceding a recreate
    r")",
    re.IGNORECASE,
)


def test_no_third_party_action_creates_a_release() -> None:
    """`APPROVED_RELEASE_ACTION` was a dead constant -- defined, named in an error
    message, and asserted nowhere. So `actions/create-release@v1` in a finalizer passed
    every guard, silently losing the Gitea path ADR-0010 exists to secure: that action
    speaks GitHub's API only, and E009's premise is that the same YAML works on Gitea.

    Forbidding the hand-rolled `curl` was never enough. The likelier shortcut is a
    different action, and it fails in exactly the place nobody is testing yet.
    """
    release_shaped = re.compile(r"(?:^|[-/])release(?:[-/]|$)", re.IGNORECASE)
    for path in GOVERNED_DEFINITIONS:
        for reference in _external_action_references(path):
            action, _, _ = reference.rpartition("@")
            if action.startswith(APPROVED_RELEASE_ACTION):
                continue
            # The changelog builder is release-shaped but creates nothing.
            if action.startswith(f"{APPROVED_RELEASE_ACTION}-changelog-builder"):
                continue
            assert not release_shaped.search(action.split("/", 1)[-1]), (
                f"{path}: {action} is release-creating. Releases go through "
                f"{APPROVED_RELEASE_ACTION}@v2, which speaks both GitHub's and Gitea's "
                f"APIs from one step (ADR-0010). A GitHub-only action loses E009."
            )


def test_alias_moves_go_through_the_approved_action() -> None:
    """Once a valid release exists the major alias floats -- a hard requirement -- and
    moving a tag is a forced ref update. ADR-0006 permits exactly one mechanism for it.

    Hand-rolling the push is forbidden outright rather than constrained, because the
    constraints are the hard part: `--force-with-lease` rather than a bare `--force` so a
    concurrent move fails instead of being clobbered, never `--tags`, never a broad
    refspec, and never against `refs/tags/vX.Y.Z`. The action encapsulates that, including
    `ignore-prerelease`. A `run:` block re-deriving it would be a second implementation of
    the alias rule, and the one most likely to get the lease wrong.
    """
    for path in sorted(WORKFLOWS.glob("*.yaml")):
        for job_name, job in _jobs(_load_workflow(path)).items():
            for step in job.get("steps", []) or []:
                command = str(step.get("run", ""))
                assert not FORCED_REF_WRITE.search(command), (
                    f"{path.name}: job {job_name!r} forces a ref update by hand. Alias "
                    f"moves go through {APPROVED_ALIAS_ACTION}; `vX.Y.Z` is immutable and "
                    f"is never forced at all (ADR-0006)."
                )


def test_the_alias_action_runs_only_from_a_registered_finalizer() -> None:
    # The action needs `contents: write` to push tags, so its use is a grant in exactly
    # the sense ADR-0006 means, and belongs in the same registry as the Release finalizer.
    for path in sorted(WORKFLOWS.glob("*.yaml")):
        for job_name, job in _jobs(_load_workflow(path)).items():
            for step in job.get("steps", []) or []:
                if not str(step.get("uses", "")).startswith(APPROVED_ALIAS_ACTION):
                    continue
                assert (path.name, job_name) in RELEASE_FINALIZER_JOBS, (
                    f"{path.name}: job {job_name!r} moves version aliases but is not a "
                    f"registered finalizer (ADR-0006)"
                )


def test_no_workflow_delegates_versioning_to_an_external_release_bot() -> None:
    for path in sorted(WORKFLOWS.glob("*.yaml")):
        assert "release-please" not in path.read_text(encoding="utf-8"), (
            f"{path.name}: release-please is a competing version authority (ADR-0006)"
        )


def test_setup_action_owns_interpreter_and_poetry_installation() -> None:
    action = _load_document(SETUP_ACTION)
    assert action["runs"]["using"] == "composite"
    # Exact equality, so a new input cannot be added without this line being reconsidered.
    # `development-distance` was added by story E008-S01-001: the development version
    # X.Y.(Z+1).devN comes from scripts/committed_versions.py through this action, so no
    # plan job has to know how a development version is spelled (F12).
    assert set(action["inputs"]) == {
        "python-version",
        "poetry",
        "dependencies",
        "development-distance",
    }
    assert {"package-version", "poetry-version", "development-version"} <= set(
        action["outputs"]
    )

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


PRE_COMMIT_CONFIG = PROJECT_ROOT / ".pre-commit-config.yaml"
GITLEAKS_CONFIG = PROJECT_ROOT / ".gitleaks.toml"


def _gitleaks_hook() -> dict[str, Any]:
    config = yaml.safe_load(PRE_COMMIT_CONFIG.read_text(encoding="utf-8"))
    for repository in config["repos"]:
        for hook in repository["hooks"]:
            if hook["id"] == "gitleaks":
                return hook
    raise AssertionError("no gitleaks hook is configured")


def test_the_secret_scanner_reads_content_rather_than_the_index() -> None:
    """The gate passed over every commit of this project without reading any of it.

    The upstream hook's entry is `gitleaks git --pre-commit --redact --staged
    --verbose`, which scans the git *index*. `pre-commit run gitleaks --all-files` --
    what CI runs, and what `just check` runs -- stages nothing, so it read
    `~0 bytes (0)`, reported `no leaks found` and exited 0. Reproduced against a
    repository holding a live-format GitHub PAT and Slack bot token: the staged form
    exits 0, `gitleaks dir` finds both and exits 1.

    A green secret scanner that reads nothing is worse than no scanner, because it is
    the control everyone assumes has looked. The real proof is in verify-build.yaml,
    which runs the configured invocation against a planted credential on every CI run
    (`test_the_secret_scanner_proves_itself_in_ci` requires that step to exist). This
    guard covers the shape, so the defect cannot come back by editing one word.
    """
    entry = str(_gitleaks_hook()["entry"])
    assert "--staged" not in entry, (
        f"the secret scanner is back on the index rather than content: {entry}"
    )
    assert entry.split()[1] == "dir", (
        f"the secret scanner must scan a directory of content: {entry}"
    )
    assert _gitleaks_hook().get("pass_filenames") is False, (
        "`gitleaks dir` takes exactly one path; pre-commit must not append the changed "
        "file list to it"
    )


def test_the_secret_scanner_and_pre_commit_exclude_the_same_vendored_trees() -> None:
    """`gitleaks dir` takes no notice of pre-commit's `exclude:`, so the vendored trees
    are allowlisted a second time in .gitleaks.toml. Two hand-kept copies of one list
    drift, and the copy nobody updated is the one that decides what goes unscanned --
    so the two are derived from each other here rather than trusted to agree.
    """
    config = yaml.safe_load(PRE_COMMIT_CONFIG.read_text(encoding="utf-8"))
    excluded = re.fullmatch(r"\^\((?P<alternatives>.+)\)/", str(config["exclude"]))
    assert excluded, (
        f"the pre-commit exclude is no longer an alternation: {config['exclude']}"
    )
    expected = {
        f"^{alternative}/" for alternative in excluded["alternatives"].split("|")
    }

    scanner = tomllib.loads(GITLEAKS_CONFIG.read_text(encoding="utf-8"))
    allowlisted = {
        path for entry in scanner["allowlists"] for path in entry.get("paths", [])
    }
    assert allowlisted == expected, (
        f"the scanner allowlists {sorted(allowlisted)} while pre-commit excludes "
        f"{sorted(expected)}; one tree is linted by neither or scanned by neither"
    )
    assert scanner["extend"]["useDefault"] is True, (
        "the allowlist must extend the default rule set, not replace it"
    )


def test_the_secret_scanner_proves_itself_in_ci() -> None:
    """The guard above reads configuration; this requires the job that reads *behaviour*.

    Asserting "a gitleaks hook is configured" is exactly the guard this repository
    already had, and it passed throughout the period the scanner read nothing. So the
    CI job plants a credential and requires the configured invocation to fail on it,
    and this test requires that step to keep existing.
    """
    steps = _jobs(_load_workflow(VERIFY_WORKFLOW))["gitleaks"]["steps"]
    bodies = [_uncommented(str(step.get("run", ""))) for step in steps]
    assert any("pre-commit run gitleaks" in body for body in bodies), (
        "the gitleaks job no longer runs the hook"
    )
    proof = [body for body in bodies if "planted" in body]
    assert proof, (
        "the gitleaks job no longer proves the scanner reads content. A configuration "
        "check cannot replace it: the defect it exists for was a correctly configured "
        "hook scanning an empty index."
    )
    assert ".pre-commit-config.yaml" in proof[0], (
        "the proof must run the configured invocation, not a second copy of it that "
        "can stay correct while the real one rots"
    )


def test_every_matrix_dimension_is_actually_consumed_by_its_job() -> None:
    """A matrix that varies nothing runs one job N times under N names.

    `pytest` declared `python: [3.10 ... 3.14]` and every leg installed
    `${{ env.PYTHON_VERSION }}`, so five identical 3.14 runs reported themselves as
    five interpreters. pyproject declares `>=3.10,<3.15` and nothing tested the floor;
    a module-level `import tomllib`, which does not exist before 3.11, sat in the suite
    unnoticed.

    The job's display name is deliberately excluded from the search. Interpolating a
    dimension into the name is what made the failure invisible -- the CI summary read
    `pytest (Python 3.10)` -- and a guard that accepted it would have passed too.
    """
    examined = 0
    for name, document in sorted(_workflow_documents().items()):
        for job_name, job in sorted(_jobs(document).items()):
            matrix = (job.get("strategy") or {}).get("matrix")
            if not isinstance(matrix, dict):
                continue
            body = json.dumps(
                {
                    key: value
                    for key, value in job.items()
                    if key not in {"strategy", "name"}
                }
            )
            for dimension in matrix:
                if dimension in {"include", "exclude"}:
                    continue
                examined += 1
                assert f"matrix.{dimension}" in body, (
                    f"{name}: job {job_name!r} declares matrix dimension "
                    f"{dimension!r} and never uses it outside its display name, so "
                    f"every leg runs the same thing under a different label"
                )
    assert examined, "no job declares a matrix; this guard examined nothing"


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
    # Scope is every governed definition, not just the verifier (gate finding F11).
    # dev.yaml and release.yaml will use actions/download-artifact, and tier one happily
    # accepts @v7 -- so the Gitea pin could be broken in the new workflows with every test
    # green, surfacing only in Epic 9.
    examined = 0
    for path in GOVERNED_DEFINITIONS:
        for reference in _external_action_references(path):
            for action in ARTIFACT_ACTIONS:
                if not reference.startswith(f"{action}@"):
                    continue
                examined += 1
                assert reference == f"{action}@v4", (
                    f"{path}: {reference} drops Gitea's act_runner, which implements the "
                    f"v4 artifact protocol only"
                )
    assert examined, "no artifact action references were examined"


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

    # The reach half. Asserting the entry exists proves the rule, not that the rule can
    # do anything: Dependabot resolves `FROM $VAR` only through an ARG default, so an
    # undefaulted `ARG BASE_IMAGE` leaves the watched directory unupdatable while this
    # config still reports coverage. That exact regression reached main once already.
    #
    # Parsed with dockerfile-parse rather than a hand-rolled scanner; only the
    # Dependabot-specific ARG-default resolution is local.
    from dockerfile_parse import DockerfileParser

    bake = (PROJECT_ROOT / "docker-bake.hcl").read_text(encoding="utf-8")
    watched_bases: set[str] = set()
    for ecosystem, directory in configured:
        if ecosystem != "docker":
            continue
        target = PROJECT_ROOT / directory.lstrip("/")
        assert target.is_dir(), f"dependabot watches {directory}, which does not exist"
        dockerfiles = sorted(target.glob("Dockerfile*"))
        assert dockerfiles, f"dependabot watches {directory} with no Dockerfile in it"
        for dockerfile in dockerfiles:
            parser = DockerfileParser(path=str(dockerfile))
            # Walked in order, accumulating ARG defaults as they appear. `parser.args` is
            # the build-arg context, not the declared defaults, so the structure is the
            # authority. Order matters and is not incidental: Dependabot resolves a
            # variable in FROM only against an ARG that PRECEDES that FROM, so an ARG
            # declared after the stage it is meant to serve resolves to nothing.
            defaults: dict[str, str] = {}
            for line in parser.structure:
                if line["instruction"] == "ARG":
                    name, _, value = line["value"].partition("=")
                    if value:
                        defaults[name.strip()] = value.strip()
                    continue
                if line["instruction"] != "FROM":
                    continue
                image = line["value"].split(" AS ")[0].split(" as ")[0].strip()
                if not image.startswith("$"):
                    watched_bases.add(image)
                    continue
                name = image.lstrip("${").rstrip("}")
                resolved = defaults.get(name)
                assert resolved, (
                    f"{dockerfile}: FROM {image} has no ARG default, so the dependabot "
                    f"docker entry for {directory} can update nothing"
                )
                watched_bases.add(resolved)

    bake_bases = {value for value in re.findall(r'BASE_IMAGE\s*=\s*"([^"]+)"', bake)}
    assert watched_bases == bake_bases, (
        f"docker-bake.hcl and the Dockerfile ARG default disagree: "
        f"bake={sorted(bake_bases)}, dockerfile={sorted(watched_bases)}"
    )


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


# ---------------------------------------------------------------------------
# Development channel (story E008-S01-001). Every guard below was proven by
# planting the violation it forbids and confirming the guard fails.
# ---------------------------------------------------------------------------

DEV_WORKFLOW = WORKFLOWS / "dev.yaml"
PUBLISH_IMAGE_WORKFLOW = WORKFLOWS / "publish-image.yaml"
PUBLISH_IMAGE_REFERENCE = "./.github/workflows/publish-image.yaml"
REQUIRED_IMAGE_PLATFORMS = ("linux/amd64", "linux/arm64")

# "How many descriptors does the index carry" in every spelling that reaches for a
# number. ATTESTATIONS=[] does not disable attestations, so the answer is four today,
# two under `type=provenance,disabled=true`, and four again with `type=sbom` -- which is
# why the count is never the thing to assert.
DESCRIPTOR_COUNT_ASSERTIONS = (
    r"len\(\s*[^()]*manifests[^()]*\)\s*(?:==|!=|<=|>=|<|>)",
    r"(?:==|!=|<=|>=|<|>)\s*len\(\s*[^()]*manifests",
    r"\.manifests\s*\|\s*length",
)


# The coordinates every publishing workflow addresses a forge with. Used to LOCATE the
# derivation from what a job emits rather than from a filename, so a third channel
# workflow that derives its own registry is examined the day it lands.
FORGE_COORDINATE_OUTPUTS = frozenset(
    {
        "forge",
        "registry",
        "image-repository",
        "package-index-supported",
        "package-index-url",
    }
)
STEP_OUTPUT_REFERENCE = re.compile(r"steps\.([A-Za-z0-9_-]+)\.outputs\.")

# The fork of docker/metadata-action with the GitHub API dependency removed, so the same
# YAML renders the same references on GitHub and on Gitea (docs/guidelines.md section 6).
IMAGE_METADATA_ACTION = "LiquidLogicLabs/git-action-docker-metadata@v6"


def _producing_step(
    path: Path, job_name: str, job: dict[str, Any], output_name: str
) -> dict[str, Any]:
    """The step a job's named output is taken from, resolved through the expression."""
    reference = STEP_OUTPUT_REFERENCE.search(
        str((job.get("outputs") or {})[output_name])
    )
    assert reference, (
        f"{path.name}: job {job_name!r} does not take {output_name!r} from a step output"
    )
    step = next(
        (
            candidate
            for candidate in (job.get("steps") or [])
            if candidate.get("id") == reference.group(1)
        ),
        None,
    )
    assert step is not None, (
        f"{path.name}: job {job_name!r} takes {output_name!r} from step "
        f"{reference.group(1)!r}, which does not exist"
    )
    return step


def _uncommented(command: str) -> str:
    """A `run:` body with its shell comment lines removed.

    Used only by the POSITIVE half of a guard -- "this mechanism is present". A
    commented-out `imagetools inspect` is text, not a mechanism, and satisfied the
    existence check before this. Prohibitions deliberately keep the raw body: a
    commented-out forbidden command is not a violation, and stripping there would
    weaken the rule rather than sharpen it.
    """
    return "\n".join(
        line for line in command.splitlines() if not line.lstrip().startswith("#")
    )


def _publishing_workflows() -> list[Path]:
    """Every workflow that owns an automatic event and publishes something.

    The scope for the destination-agnostic rules: full-history checkouts, credential
    disjointness, re-reading the tag set before upload, gating optional credentials,
    the evidence job, the finalizer, the run summary.

    Those rules used to take their scope from `_image_channel_workflows` below, which
    derives from *whether the workflow publishes a container image*. A `nightly.yaml`
    with a single PyPI job -- `id-token: write`, `fetch-depth: 1`, no tag re-read, no
    finalizer, ungated optional credentials -- ships no image, so none of the seven
    looked at it and the suite stayed green. Publishing is the property that matters
    here, not what is published.
    """
    return [
        path
        for path in sorted(WORKFLOWS.glob("*.yaml"))
        if _trigger_surface(_load_workflow(path)) and _publishers(_load_workflow(path))
    ]


def _image_channel_workflows() -> list[Path]:
    """The subset that publishes an image through the shared reusable publisher.

    Derived from who calls it, never enumerated: release.yaml is covered the day it
    lands, without an edit here. Kept narrow deliberately -- it is the right scope for
    rules about the image wiring (platform inputs, digest and platform outputs,
    consuming an inspection rather than performing one) and the wrong scope for
    anything that is true of publishing in general.
    """
    return [
        path
        for path in sorted(WORKFLOWS.glob("*.yaml"))
        if any(
            job.get("uses") == PUBLISH_IMAGE_REFERENCE
            for job in _jobs(_load_workflow(path)).values()
        )
    ]


def test_the_publishing_scope_is_derived_from_publishing_not_from_images() -> None:
    """The scope attack for `_publishing_workflows`, as a classification proof.

    The seven destination-agnostic guards used to key on "calls publish-image.yaml".
    A push-triggered workflow holding one PyPI job satisfies none of their rules and
    was examined by none of them, because it ships no image. Planted on disk it now
    fails nine guards; here the classification itself is pinned, so the derivation
    cannot quietly narrow again.
    """
    assert set(_image_channel_workflows()) <= set(_publishing_workflows()), (
        "a workflow that publishes an image must also count as publishing"
    )
    nightly = {
        "on": {"push": {"branches": ["nightly"]}},
        "jobs": {
            "publish-package-pypi": {
                "runs-on": "ubuntu-24.04",
                "permissions": {"id-token": "write"},
                "steps": [{"uses": "pypa/gh-action-pypi-publish@" + "0" * 40}],
            }
        },
    }
    assert _trigger_surface(nightly), "a push-triggered workflow owns an event"
    assert _publishers(nightly), "an `id-token: write` job can ship"
    assert not any(
        job.get("uses") == PUBLISH_IMAGE_REFERENCE for job in _jobs(nightly).values()
    ), "and it ships no image -- which is exactly how it escaped the seven guards"


def _publishers(document: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Jobs that ship or can ship, derived from capability rather than from name.

    The same derivation `test_any_push_triggered_workflow_verifies_before_it_ships`
    uses, so a publisher added later is covered by the guards below without editing
    them -- which is the whole point of the scope attack in each anchor.
    """
    jobs = _jobs(document)
    called = {name: job.get("uses") for name, job in jobs.items()}
    return {
        name: job
        for name, job in jobs.items()
        if (
            isinstance(called.get(name), str)
            and called[name].startswith("./.github/workflows/")
            and called[name] != VERIFIER_REFERENCE
        )
        or _is_credential_bearing(job)
    }


def test_the_development_channel_owns_protected_default_branch_pushes() -> None:
    """BL-E008-001: since the legacy publish path was deleted nothing reacted to `push`.

    `test_any_push_triggered_workflow_verifies_before_it_ships` asserts the conditional
    invariant and passes vacuously with no push workflow at all. This one asserts the
    workflow exists and is shaped as ADR-0011 requires, so deleting dev.yaml reopens the
    finding loudly instead of turning that guard vacuous again.
    """
    document = _load_workflow(DEV_WORKFLOW)
    triggers = document["on"]
    assert set(triggers) == {"push"}
    assert triggers["push"] == {"branches": ["main"]}
    assert document["permissions"] == {"contents": "read"}
    # Stale candidates are superseded, not raced (definition of done).
    assert document["concurrency"]["cancel-in-progress"] == "true"

    # Exactly one verifier call for the event SHA. Counted from the parsed document, so
    # a second call added anywhere in the file -- another job, another spelling of the
    # same `uses:` -- fails here.
    verifier_calls = [
        name
        for name, job in _jobs(document).items()
        if job.get("uses") == VERIFIER_REFERENCE
    ]
    assert verifier_calls == ["verify"]
    verify = _jobs(document)["verify"]
    assert verify["with"]["channel"] == "dev"
    assert verify["with"]["source-sha"] == "${{ needs.plan.outputs.source-sha }}"


def test_the_image_publisher_is_reusable_only_like_the_verifier() -> None:
    """Prep finding P2: this is a fifth workflow file, and the topology assertion in
    story E008-S01-004 expects it -- distinguished as reusable-only, exactly as
    verify-build.yaml already is. A trigger added here would make it a sixth entry point.
    """
    document = _load_workflow(PUBLISH_IMAGE_WORKFLOW)
    assert set(document["on"]) == {"workflow_call"}
    assert set(document["on"]["workflow_call"]["outputs"]) >= {"digest", "platforms"}


def test_every_channel_checkout_keeps_full_history_and_tags() -> None:
    """The development version is a first-parent commit count, suppression peels tag
    objects, and the stable guard peels one tag and asks git whether its commit is
    reachable from the protected default branch. A shallow checkout derives `.dev1` for
    every commit, sees no tags at all, and has no `origin/main` to be reachable from --
    and it fails silently, publishing a plausible wrong version.

    Scope is every checkout of every channel workflow, derived from the parsed document
    and from who calls the image publisher, so neither a job added later nor a channel
    added later can quietly take a shallow one.
    """
    channel_workflows = _publishing_workflows()
    assert channel_workflows, "no workflow calls the image publisher"
    checkouts = 0
    for path in channel_workflows:
        for job_name, job in _jobs(_load_workflow(path)).items():
            for step in job.get("steps", []) or []:
                if not str(step.get("uses", "")).startswith("actions/checkout@"):
                    continue
                checkouts += 1
                options = step.get("with") or {}
                assert options.get("fetch-depth") == "0", (
                    f"{path.name}: {job_name}: shallow checkout"
                )
                assert options.get("fetch-tags") == "true", (
                    f"{path.name}: {job_name}: no tags fetched"
                )
                assert options.get("persist-credentials") == "false", (
                    f"{path.name}: {job_name}"
                )
    assert checkouts, (
        "no channel workflow checks anything out; this guard examined nothing"
    )


def test_every_development_publisher_is_gated_on_stable_tag_suppression() -> None:
    """An exact stable tag on the pushed commit suppresses development publication.

    Both halves are asserted: the suppression job must be a transitive dependency of
    every publisher, AND each publisher's own `if:` must read its conclusion. `needs:`
    alone is not a gate -- a job that depends on the guard and ignores its output
    publishes anyway.

    The publisher set is derived from capability, so a new publisher that forgets the
    gate fails here rather than being silently ungoverned (the scope attack).
    """
    document = _load_workflow(DEV_WORKFLOW)
    jobs = _jobs(document)
    suppressors = {
        name for name, job in jobs.items() if "suppressed" in (job.get("outputs") or {})
    }
    assert suppressors, "no job emits a suppression conclusion"

    publishers = _publishers(document)
    assert publishers, "dev.yaml has no publishers; this guard examined nothing"
    for name, job in publishers.items():
        needs = _transitive_needs(jobs, name)
        assert suppressors <= needs, (
            f"dev.yaml: publisher {name!r} does not depend on the suppression job"
        )
        condition = str(job.get("if", "")).replace(" ", "")
        assert any(
            f"needs.{suppressor}.outputs.suppressed" in condition
            for suppressor in suppressors
        ), (
            f"dev.yaml: publisher {name!r} depends on the suppression job but ignores "
            f"its conclusion, so a stable-tagged commit still publishes"
        )


def _coordinate_derivations() -> list[tuple[Path, str, dict[str, Any]]]:
    """Every job that derives forge coordinates, and the one step it derives them in.

    Scope is derived from what a job EMITS, never from a list of filenames: a channel
    workflow added later that resolves its own registry is examined here without an edit,
    and a job that split the derivation across two steps fails rather than being examined
    in half.
    """
    located: list[tuple[Path, str, dict[str, Any]]] = []
    for path in sorted(WORKFLOWS.glob("*.yaml")):
        for job_name, job in _jobs(_load_workflow(path)).items():
            outputs = job.get("outputs") or {}
            emitted = FORGE_COORDINATE_OUTPUTS & set(outputs)
            if not emitted:
                continue
            # Not every coordinate is exposed as a job output -- `package-index-supported`
            # is consumed inside the job -- so the completeness of the set is asserted by
            # EXECUTING the step below, where a missing coordinate cannot hide.
            steps = {
                _producing_step(path, job_name, job, name)["id"] for name in emitted
            }
            assert len(steps) == 1, (
                f"{path.name}: job {job_name!r} derives its forge coordinates in "
                f"{sorted(steps)}; there is one derivation or there are two answers"
            )
            located.append(
                (path, job_name, _producing_step(path, job_name, job, "registry"))
            )
    return located


def test_forge_coordinates_are_derived_from_action_context_and_fail_closed(
    tmp_path: Path,
) -> None:
    """CI-AR6, asserted by RUNNING the derivation rather than by reading it.

    Every coordinate is a projection of `github.server_url` and `github.repository`, so
    there is no operator-supplied value to validate -- the composite action and the
    ``scripts/forge_coordinates.py`` module it called were 535 lines producing six
    template expressions, and `FORGE_REGISTRY` is retired with them.

    The one behaviour worth keeping is the fail-closed branch: an unrecognised forge must
    stop the run rather than guess a registry, because a guess publishes an immutable
    artifact somewhere nobody chose. A textual check ("the word `exit` appears") passes
    with that branch deleted, so each case below is executed.
    """
    derivations = _coordinate_derivations()
    assert derivations, "no workflow derives forge coordinates; nothing was examined"
    for path, job_name, step in derivations:
        body = str(step["run"])
        where = f"{path.name}: job {job_name!r}"

        # GitHub: ghcr.io, no forge Python index, and a lowercased repository -- a forge
        # owner need not be lowercase, and a registry reference must be.
        completed, emitted = _run_step(
            body,
            {
                "FORGE_SERVER_URL": "https://github.com",
                "FORGE_REPOSITORY": "Owner/Name",
            },
            tmp_path,
        )
        assert completed.returncode == 0, f"{where}: {completed.stderr}"
        assert emitted == {
            "forge": "github",
            "registry": "ghcr.io",
            "image-name": "name",
            "image-repository": "ghcr.io/owner/name",
            "package-index-supported": "false",
            "package-index-url": "",
        }, where

        # Gitea: the registry is the forge's own authority, port included, and the
        # package index is a capability of the host rather than a toggle.
        completed, emitted = _run_step(
            body,
            {
                "GITEA_ACTIONS": "true",
                "FORGE_SERVER_URL": "https://git.example.com:3000",
                "FORGE_REPOSITORY": "Owner/Name",
            },
            tmp_path,
        )
        assert completed.returncode == 0, f"{where}: {completed.stderr}"
        assert emitted == {
            "forge": "gitea",
            "registry": "git.example.com:3000",
            "image-name": "name",
            "image-repository": "git.example.com:3000/owner/name",
            "package-index-supported": "true",
            "package-index-url": "https://git.example.com:3000/api/packages/owner/pypi",
        }, where

        # Fail closed. `github.enterprise.example` ends with neither the GitHub host nor
        # a Gitea flag, and a suffix or substring comparison accepts the first two.
        for unknown in (
            "https://github.enterprise.example",
            "https://notgithub.com",
            "https://github.com.evil.example",
            "https://git.example.com",
        ):
            completed, emitted = _run_step(
                body,
                {"FORGE_SERVER_URL": unknown, "FORGE_REPOSITORY": "owner/name"},
                tmp_path,
            )
            assert completed.returncode != 0, (
                f"{where}: {unknown} was accepted as a known forge, so a registry was "
                f"guessed for it"
            )
            assert not emitted, f"{where}: {unknown} emitted {emitted} before failing"

        # `GITEA_ACTIONS` is Gitea's flag, and only its exact value means Gitea. Anything
        # else on an unrecognised host still fails closed.
        for flag in ("false", "TRUE ", "1", ""):
            completed, _ = _run_step(
                body,
                {
                    "GITEA_ACTIONS": flag,
                    "FORGE_SERVER_URL": "https://git.example.com",
                    "FORGE_REPOSITORY": "owner/name",
                },
                tmp_path,
            )
            assert completed.returncode != 0, (
                f"{where}: GITEA_ACTIONS={flag!r} was read as a Gitea runner"
            )


def test_image_references_are_rendered_by_the_metadata_action_never_hand_joined() -> (
    None
):
    """The plan job proves the tag VALUE; joining it to each enabled repository is the
    metadata action's job.

    `git-action-docker-metadata` is a fork of `docker/metadata-action` with the GitHub
    API dependency removed, so it renders the same references on GitHub and on Gitea. It
    has no registry input and derives no registry: `images:` is handed the fully
    qualified repository the forge coordinates already derived.

    Scope is every job emitting `image-tags`, and the step examined is resolved through
    that output's own expression -- so a channel that goes back to composing references
    in a `run:` body fails here because the producing step has no `uses:` at all. That is
    the scope attack: the rule is trivial, its reach is the point.
    """
    examined = 0
    for path in sorted(WORKFLOWS.glob("*.yaml")):
        for job_name, job in _jobs(_load_workflow(path)).items():
            if "image-tags" not in (job.get("outputs") or {}):
                continue
            examined += 1
            where = f"{path.name}: job {job_name!r}"
            step = _producing_step(path, job_name, job, "image-tags")
            assert step.get("uses") == IMAGE_METADATA_ACTION, (
                f"{where} composes image references itself instead of delegating to "
                f"{IMAGE_METADATA_ACTION}"
            )
            inputs = step.get("with") or {}

            # `images:` is the derived repository, never a registry the step names.
            repository_step = _producing_step(path, job_name, job, "image-repository")[
                "id"
            ]
            images = str(inputs.get("images", ""))
            assert f"steps.{repository_step}.outputs.image-repository" in images, (
                f"{where}: the metadata action is not handed the derived image "
                f"repository as `images:` (got {images!r})"
            )

            # The rendered value is the proven identity, resolved through the job's own
            # version producer rather than a hand-kept step name.
            identity_step = _producing_step(path, job_name, job, "package-version")[
                "id"
            ]
            tags = str(inputs.get("tags", ""))
            assert tags.startswith("type=raw,value="), (
                f"{where}: the metadata action derives the tag itself ({tags!r}); the "
                f"identity step decides it and this step renders it"
            )
            assert f"steps.{identity_step}.outputs.image-tag-value" in tags, (
                f"{where}: the rendered tag {tags!r} is not the identity the plan job "
                f"proved, so the publication would carry a second version authority"
            )

            # `latest=auto` is the action's default, and it adds a mutable alias on a
            # tag push. Every alias belongs to the finalizer story.
            assert "latest=false" in str(inputs.get("flavor", "")), (
                f"{where}: the metadata action may move `latest`; aliases belong to the "
                f"finalizer, not to a publisher"
            )
    assert examined, "no job emits an image tag set; nothing was examined"


def test_the_image_fan_out_is_one_buildx_invocation_carrying_every_tag() -> None:
    """CI-AR39: one channel-run image job, one multi-platform Buildx invocation, every
    destination tagged inside it. A second `bake` per registry produces a *different*
    image for each destination, which is the defect this forbids -- and it is the
    cheapest thing to reach for when a second registry is added.

    Counted across every job of the file, so a per-registry build added to a new job
    fails here too.
    """
    document = _load_workflow(PUBLISH_IMAGE_WORKFLOW)
    builds = [
        step
        for step in _steps(document)
        if re.search(r"buildx\s+(?:bake|build)\b", str(step.get("run", "")))
    ]
    assert len(builds) == 1, (
        f"publish-image.yaml performs {len(builds)} image builds; CI-AR39 allows one"
    )
    # And nowhere else. A per-registry "just push it to Docker Hub too" step added to a
    # publishing workflow is the cheapest way to break this rule, and scoping the count
    # to one hand-named file would not see it.
    #
    # The scope is every publishing workflow, not every caller of the image publisher.
    # Keying it on "calls publish-image.yaml" was circular: a workflow that built and
    # pushed an image inline was, by that derivation, not a channel workflow, so the
    # one rule forbidding exactly that could not see it.
    for path in _publishing_workflows():
        for step in _steps(_load_workflow(path)):
            assert not re.search(
                r"buildx\s+(?:bake|build)\b", str(step.get("run", ""))
            ), (
                f"{path.name} builds an image itself. One channel run, one Buildx "
                f"invocation, every destination tagged inside it (CI-AR39)."
            )
        # A caller may pass a narrower platform list and satisfy every other guard while
        # shipping a single-platform development image.
        for job_name, job in _jobs(_load_workflow(path)).items():
            if job.get("uses") != PUBLISH_IMAGE_REFERENCE:
                continue
            supplied = (job.get("with") or {}).get("platforms")
            if supplied is None:
                continue
            assert set(str(supplied).split(",")) >= set(REQUIRED_IMAGE_PLATFORMS), (
                f"{path.name}: job {job_name!r} narrows the published platform set to "
                f"{supplied!r}; CI-AR39 requires {list(REQUIRED_IMAGE_PLATFORMS)}"
            )
    command = str(builds[0]["run"])
    assert "--push" in command
    environment = builds[0].get("env") or {}
    assert "TAGS" in environment and "PLATFORMS" in environment, (
        "the single invocation must receive every tag and every platform as bake "
        "variables; a tag applied outside it is a second build"
    )

    platforms = document["on"]["workflow_call"]["inputs"]["platforms"]["default"]
    assert set(platforms.split(",")) == set(REQUIRED_IMAGE_PLATFORMS)


def test_the_published_index_is_asserted_by_annotation_never_by_descriptor_count() -> (
    None
):
    """ADR-0008 as amended: `ATTESTATIONS = []` does NOT disable attestations.

    BuildKit emits SLSA provenance `mode=min` regardless, so the index carries four
    descriptors -- two platforms plus two attestation manifests. Adding `type=sbom`
    keeps it at four; only `type=provenance,disabled=true` drops it to two. A count
    assertion is wrong in three directions, so the filter keys on the authoritative
    annotation instead.
    """
    document = _load_workflow(PUBLISH_IMAGE_WORKFLOW)
    commands = [str(step.get("run", "")) for step in _steps(document)]
    assertions = [
        command
        for command in commands
        if "vnd.docker.reference.type" in command and "attestation-manifest" in command
    ]
    assert assertions, (
        "the published index is never filtered on vnd.docker.reference.type, so the "
        "platform assertion is reading attestation manifests as platforms"
    )
    # The prohibition's reach, not only its rule. `len(manifests) == 2` is one spelling;
    # the likelier one is `len(index["manifests"]) != 2`, and `jq '.manifests | length'`
    # is the same assertion in shell. Scope is every governed definition plus the helper
    # scripts, because F9 pushes non-trivial logic out of `run:` blocks -- so that is
    # exactly where a count assertion would come to rest.
    counted = 0
    for path in [
        *GOVERNED_DEFINITIONS,
        *sorted((PROJECT_ROOT / "scripts").glob("*.py")),
    ]:
        source = path.read_text(encoding="utf-8")
        counted += 1
        for pattern in DESCRIPTOR_COUNT_ASSERTIONS:
            assert not re.search(pattern, source), (
                f"{path.name}: the published index is asserted by descriptor count; the "
                f"count is 4, not 2, and changes with the attestation set (ADR-0008)"
            )
    assert counted, "no definition was examined for a descriptor-count assertion"
    # The expected set is the same platform list the single build was given, not a
    # second literal: two hand-kept copies drift, and the copy nobody updated is the one
    # still reporting success.
    inspecting = [
        step
        for step in _steps(document)
        if "vnd.docker.reference.type" in str(step.get("run", ""))
    ]
    for step in inspecting:
        environment = step.get("env") or {}
        assert "PLATFORMS" in environment, (
            "the platform assertion must compare against the platform list the build "
            "was given, not a literal restated beside it"
        )


def test_channel_workflows_consume_image_inspection_rather_than_performing_it() -> None:
    """Prep finding P1, enforced before the collision can happen.

    `test_alias_ordering_is_decided_from_git_never_from_a_registry` forbids a registry
    read in EVERY job of a file that moves an alias. Story E008-S01-003 puts an alias
    finalizer into dev.yaml and release.yaml; from that moment the `imagetools inspect`
    this epic mandates would fail that guard inside the same file. The resolution is
    placement: every published-image read lives in publish-image.yaml, which moves no
    alias, and the callers consume its `digest`/`platforms` outputs.

    Waiting for story 003 to discover this as a red test is the failure mode this guard
    removes. Scope is derived: any workflow that calls the image publisher is a channel
    workflow, so release.yaml is covered the day it lands.
    """
    channel_workflows = _image_channel_workflows()
    assert channel_workflows, "no workflow calls the image publisher"
    for path in channel_workflows:
        for job_name, job in _jobs(_load_workflow(path)).items():
            for step in job.get("steps", []) or []:
                command = str(step.get("run", ""))
                for probe in REGISTRY_READ_COMMANDS:
                    assert not re.search(probe, command), (
                        f"{path.name}: job {job_name!r} reads a registry. Story 003 adds "
                        f"an alias finalizer to this file, and that read must live in "
                        f"publish-image.yaml with its result consumed as an output (P1)."
                    )
    # And the reads really are somewhere: a guard that only forbids would pass over a
    # publisher that inspects nothing at all, losing CI-AR39's platform evidence.
    published = [
        _uncommented(str(step.get("run", "")))
        for step in _steps(_load_workflow(PUBLISH_IMAGE_WORKFLOW))
    ]
    assert any(
        re.search(probe, command)
        for probe in REGISTRY_READ_COMMANDS
        for command in published
    ), "publish-image.yaml inspects nothing, so CI-AR39's platform evidence is missing"


# The credential every job on a forge is issued automatically, whose authority is set
# per job by `permissions:` rather than by which secret it was handed. It is excluded
# from the cross-destination comparison below for that reason -- two jobs each holding
# it under different `permissions:` scopes is the least-privilege pattern, not a shared
# destination credential -- and the exclusion is compensated: the same guard asserts no
# package publisher may take `packages: write`, which is the only way the automatic
# token becomes a registry credential.
AMBIENT_FORGE_TOKEN = "GITHUB_TOKEN"

# What a job addresses, derived from what it actually does rather than from its name.
# A job may belong to exactly one, which is itself asserted below.
DESTINATION_CLASSES: dict[str, tuple[str, ...]] = {
    # A container registry: the reusable image publisher, a registry login, or any
    # tool that writes to one.
    "image": (
        re.escape(PUBLISH_IMAGE_REFERENCE),
        r"docker/login-action",
        r"docker/setup-buildx-action",
        r"docker/build-push-action",
        r"buildx\s+(?:bake|build|imagetools)",
        r"\bdocker\s+(?:push|tag)\b",
        r"\bcrane\s+(?:copy|tag|push|append)\b",
        r"\bskopeo\s+copy\b",
        r"\bregctl\s+(?:index|image|artifact)\s+(?:copy|put)\b",
    ),
    # A Python package index, by token or by trusted publishing.
    "package": (
        r"pypa/gh-action-pypi-publish",
        r'"id-token":\s*"write"',
        r"\btwine\s+upload\b",
        r"\buv\s+publish\b",
        r"\bpoetry\s+publish\b",
        r"\bflit\s+publish\b",
    ),
    # Repository refs and forge Releases.
    "refs": (
        re.escape(APPROVED_RELEASE_ACTION),
        re.escape(APPROVED_ALIAS_ACTION),
    ),
}


def _destination_classes(job: dict[str, Any]) -> set[str]:
    body = json.dumps(job)
    return {
        name
        for name, patterns in DESTINATION_CLASSES.items()
        if any(re.search(pattern, body) for pattern in patterns)
    }


def test_publisher_credentials_stay_disjoint_between_destinations() -> None:
    """CI-AR24 / CI-AR40: each publisher receives only its own destination's credentials.

    Package OIDC and tokens are isolated from image jobs, and the job that writes refs
    holds neither. Derived from the parsed job, so a registry credential added to the
    package job -- the planted violation -- fails regardless of where in the job it
    appears.

    **Amended by story E008-S01-003.** The original comparison was pairwise across every
    publisher in the file, which encodes "one publisher per destination". That stopped
    being true the moment a finalizer moved image aliases: the alias job and the image
    publisher address *the same registry*, so they necessarily present the same
    credential to it, and the pairwise form rejected the correct arrangement while the
    rule it documents was satisfied. The rule is per **destination**, so the comparison
    is now per destination class -- and it gained two obligations the pairwise form never
    expressed:

    * a publisher belongs to exactly one destination class, so a job that both logs into
      a registry and uploads a package fails here rather than being compared against
      itself;
    * a package publisher may not declare `packages: write`, which is the only way the
      automatic forge token becomes a registry credential -- and the reason that token
      can be excluded from the comparison at all.
    """
    secret_reference = re.compile(r"secrets\.([A-Za-z_][A-Za-z0-9_-]*)")
    channel_workflows = _publishing_workflows()
    assert channel_workflows, "no workflow calls the image publisher"
    for path in channel_workflows:
        used: dict[str, set[str]] = {}
        classes: dict[str, set[str]] = {}
        for name, job in _publishers(_load_workflow(path)).items():
            # The reusable image publisher passes its caller's secrets through a
            # `secrets:` block, so the caller job is where they are named.
            used[name] = set(secret_reference.findall(json.dumps(job))) - {
                AMBIENT_FORGE_TOKEN
            }
            classes[name] = _destination_classes(job)
        assert used, f"{path.name} has no publishers; this guard examined nothing"
        # Per file, never folded across files: disjointness over a set of publishers
        # that reference no secret at all proves nothing, and a global vacuity check
        # lets one channel pass on another's behalf.
        assert any(used.values()), (
            f"{path.name}: no publisher references a named secret; the guard is vacuous"
        )
        assert any(classes.values()), (
            f"{path.name}: no publisher addresses a recognised destination; the class "
            f"derivation has stopped seeing this file"
        )

        for name, addressed in sorted(classes.items()):
            # Exactly one, never "at most one". A publisher that matches no pattern
            # satisfied `<= 1` while escaping the `packages: write` obligation below --
            # the compensation this amendment was paid for going quietly vacuous on the
            # first destination written a way `DESTINATION_CLASSES` has not seen. An
            # unclassifiable publisher is a vocabulary that needs extending, and that is
            # a thing to be told about.
            assert len(addressed) == 1, (
                f"{path.name}: publisher {name!r} addresses "
                f"{sorted(addressed) or 'no recognised destination'}. A job serving two "
                f"destinations hands each the other's credentials; a job serving none "
                f"means DESTINATION_CLASSES no longer describes how this repository "
                f"publishes -- extend it (CI-AR24)."
            )
            permissions = _load_workflow(path)["jobs"][name].get("permissions")
            if addressed == {"package"} and isinstance(permissions, dict):
                assert permissions.get("packages") != "write", (
                    f"{path.name}: package publisher {name!r} takes `packages: write`, "
                    f"which makes the automatic forge token a registry credential "
                    f"(CI-AR24)"
                )

        # The comparison the rule actually states: a named credential must not cross a
        # destination boundary. Two jobs addressing the SAME registry present the same
        # credential to it by construction, and that is not a leak.
        by_class: dict[str, set[str]] = {}
        for name, secrets in used.items():
            for addressed in classes[name]:
                by_class.setdefault(addressed, set()).update(secrets)
        names = sorted(by_class)
        for index, first in enumerate(names):
            for second in names[index + 1 :]:
                shared = by_class[first] & by_class[second]
                assert not shared, (
                    f"{path.name}: destinations {first!r} and {second!r} share "
                    f"credentials {sorted(shared)}; each destination gets only its own "
                    f"(CI-AR24)"
                )


def test_every_sha_pinned_publisher_records_the_date_it_was_reviewed() -> None:
    """ADR-0009 requires implementation to resolve, review and RECORD the real SHA.

    The shipped guard enforces the shape -- 40 lowercase hex -- which a copied-from-
    anywhere SHA also satisfies. What makes the pin meaningful is that somebody looked
    at that commit and said when. Scope is derived from the SHA-pinned registry and from
    disk, so a second pinned publisher is covered without editing this.
    """
    # Anchored to the word. Both pinned references also carry the upstream COMMIT
    # date, so an unanchored date pattern passes with the review record deleted.
    reviewed = re.compile(r"reviewed\s+20[0-9]{2}-[01][0-9]-[0-3][0-9]\b")
    examined = 0
    for path in GOVERNED_DEFINITIONS:
        lines = path.read_text(encoding="utf-8").splitlines()
        for index, line in enumerate(lines):
            if not any(f"{action}@" in line for action in SHA_PINNED_ACTIONS):
                continue
            examined += 1
            preceding = "\n".join(lines[max(0, index - 12) : index])
            assert reviewed.search(preceding), (
                f"{path.name}:{index + 1}: a SHA-pinned publication credential handler "
                f"must record the date its commit was reviewed beside the `uses:` line "
                f"(ADR-0009)"
            )
    assert examined, "no SHA-pinned publisher was examined"


def test_the_push_fixture_drives_the_real_identity_step(tmp_path: Path) -> None:
    """Runs dev.yaml's identity step, not a restatement of the fixture's own literals.

    An assertion that re-reads a constant out of the file it just loaded is a checksum of
    that file: it passes whatever the production code does. This extracts the step's
    actual `run:` body, executes it against the fixture event, and asserts the immutable
    tag value it produces -- so changing the `:0:12` slice, or the `dev-` composition,
    fails here. Joining that value to the image repository is the metadata action's job
    and is asserted by
    `test_image_references_are_rendered_by_the_metadata_action_never_hand_joined`.
    """
    event = _load_fixture("push-main.json")
    assert event["event_name"] == "push"
    assert event["ref"] == "refs/heads/main"
    assert re.fullmatch(r"[0-9a-f]{40}", event["sha"])
    assert event["forced"] is False

    identity = next(
        step
        for step in _steps(_load_workflow(DEV_WORKFLOW))
        if step.get("id") == "identity"
    )
    output = tmp_path / "github-output"
    output.touch()
    completed = subprocess.run(
        ["bash", "-c", str(identity["run"])],
        env={
            "PATH": os.environ["PATH"],
            "GITHUB_OUTPUT": str(output),
            "DEVELOPMENT_VERSION": "0.1.4.dev37",
            "RESOLVED_PYTHON": "3.14.0",
            "SOURCE_SHA": event["sha"],
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    emitted = dict(
        line.split("=", 1)
        for line in output.read_text(encoding="utf-8").splitlines()
        if line
    )
    short = event["sha"][:12]
    assert emitted["package-version"] == "0.1.4.dev37"
    assert emitted["short-sha"] == short
    assert emitted["image-tag-value"] == f"dev-{short}"

    # The empty-version guard is the one branch that must not be silently lost: an empty
    # development version would tag an image `:dev-` and publish it.
    empty = subprocess.run(
        ["bash", "-c", str(identity["run"])],
        env={
            "PATH": os.environ["PATH"],
            "GITHUB_OUTPUT": str(output),
            "DEVELOPMENT_VERSION": "",
            "RESOLVED_PYTHON": "3.14.0",
            "SOURCE_SHA": event["sha"],
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert empty.returncode != 0


def test_step_based_publishers_re_read_the_tag_set_before_they_upload() -> None:
    """F16's hardening, which nothing else asserts.

    The suppression job's conclusion is read at job level by every publisher. That is the
    guard job's answer, taken at guard-job time. The story's anchor is narrower and is
    the one that matters: a tag arriving between the guard job and the upload must still
    suppress. Without this test both re-check steps can be deleted with all 198 tests
    green, the runbook still claiming the behaviour, and the window silently back at
    "guard job start -> upload".

    Scope is derived from `_publishers()` over every channel workflow, restricted to jobs
    that HAVE steps: the image publisher is reached through `uses:` and a called workflow
    takes no caller steps, so it is protected at job granularity and legitimately cannot
    re-read inline. The stable channel is covered by the same rule for a different
    reason: `vX.Y.Z` is immutable (ADR-0006), so a tag that no longer peels to the
    commit being published means the identity moved under a run about to publish it.

    The key each file must branch on is derived from the file, never hand-kept: a
    channel with a suppression job consumes `suppressed`, one without it consumes the
    tag set itself.
    """
    examined = 0
    for path in _publishing_workflows():
        document = _load_workflow(path)
        suppressors = {
            name
            for name, job in _jobs(document).items()
            if "suppressed" in (job.get("outputs") or {})
        }
        # How the re-read reaches its refusal, derived from the file rather than
        # hand-kept: a channel with a suppression job branches on that job's
        # `suppressed` conclusion; one without it hands the whole membership decision
        # to the tested module, whose non-zero exit is the refusal under `set -e`.
        # Grepping only for the script name accepts a step that runs it and throws the
        # answer away, which is the guard-that-cannot-fail shape (F9).
        refusal = "suppressed" if suppressors else STABLE_RECHECK_MARKER
        for name, job in _publishers(document).items():
            steps = job.get("steps") or []
            if not steps:
                continue
            examined += 1
            upload_at = next(
                (i for i, step in enumerate(steps) if _is_publishing_step(step)),
                len(steps),
            )
            # Uncommented, on both halves. The prose beside a mechanism names it, so a
            # raw-body check is satisfied by the comment explaining the call that was
            # deleted -- a guard that reads its own documentation and reports success.
            rechecks = [
                _uncommented(str(step.get("run", "")))
                for step in steps[:upload_at]
                if TAG_MEMBERSHIP_MARKER in _uncommented(str(step.get("run", "")))
            ]
            assert rechecks, (
                f"{path.name}: publisher {name!r} never re-reads the tag set before "
                f"uploading. The job-level gate is the plan or guard job's answer, taken "
                f"before the verifier finished; F16 requires the re-read immediately "
                f"before the credentialed step."
            )
            assert any(refusal in command for command in rechecks), (
                f"{path.name}: publisher {name!r} runs the tag check without reaching a "
                f"refusal from it (expected `{refusal}`)"
            )
    assert examined, "no channel workflow has a step-based publisher; nothing examined"


def _compose_tag_list(
    tags: str, registry: str = "ghcr.io", dockerhub: str = "false"
) -> Any:
    """Execute publish-image.yaml's real tag-composition body with a planted input.

    Shared by the two guards that own opposite directions of the same rule, so both
    run the shipped step rather than a paraphrase of it.
    """
    document = _load_workflow(PUBLISH_IMAGE_WORKFLOW)
    compose = next(step for step in _steps(document) if step.get("id") == "plan")
    output = Path(tempfile.mkdtemp()) / "github-output"
    output.touch()
    completed = subprocess.run(
        ["bash", "-c", str(compose["run"])],
        env={
            "PATH": os.environ["PATH"],
            "GITHUB_OUTPUT": str(output),
            "DOCKERHUB_ENABLED": dockerhub,
            "IMAGE_TAGS": tags,
            "PLATFORMS": ",".join(REQUIRED_IMAGE_PLATFORMS),
            "REGISTRY": registry,
        },
        capture_output=True,
        text=True,
        check=False,
    )
    emitted = dict(
        line.split("=", 1)
        for line in output.read_text(encoding="utf-8").splitlines()
        if line
    )
    return completed, emitted


def test_an_enabled_destination_that_receives_no_tag_halts_before_anything_ships() -> (
    None
):
    """The symmetric direction of the permission check, and the one that was missing.

    The forbidden direction -- a tag for a destination the run did not log into -- was
    enforced. Its mirror was enforced nowhere, and nothing downstream can recover it: a
    job result carries no evidence of *which* destinations it addressed, which the
    finalizer gate says of itself. So `PUBLISH_IMAGE_DOCKERHUB=true` with a tag list
    that renders forge-only pushed to the forge alone, passed the permission check,
    succeeded, let the gate join `image-dockerhub: enabled` with `success` -> ok,
    created the Release, advanced the Git aliases, and only then failed inside
    `imagetools create` against a Docker Hub digest that was never pushed.

    Run against the shipped step, like its mirror: a textual check would pass with the
    refusal deleted and the accumulator left behind.
    """
    completed, _ = _compose_tag_list("ghcr.io/owner/name:1.2.3", dockerhub="true")
    assert completed.returncode != 0, (
        "dockerhub was enabled and no tag addressed it, and the step composed a "
        "forge-only push anyway"
    )
    assert "no tag addresses docker.io" in completed.stderr, completed.stderr

    # The forge registry is never optional, so a Docker-Hub-only list is the same defect.
    completed, _ = _compose_tag_list(
        "docker.io/owner/name:1.2.3", registry="ghcr.io", dockerhub="true"
    )
    assert completed.returncode != 0, "no tag addressed the forge registry"
    assert "no tag addresses it" in completed.stderr, completed.stderr

    # Both addressed, in either Docker Hub spelling, and it goes through.
    for hub in ("docker.io/owner/name:1.2.3", "index.docker.io/owner/name:1.2.3"):
        completed, emitted = _compose_tag_list(
            f"ghcr.io/owner/name:1.2.3\n{hub}", dockerhub="true"
        )
        assert completed.returncode == 0, completed.stderr
        assert emitted["tags"].count(",") == 1

    # And with Docker Hub off, a forge-only list is correct rather than a drift.
    completed, _ = _compose_tag_list("ghcr.io/owner/name:1.2.3")
    assert completed.returncode == 0, completed.stderr


def test_every_published_tag_addresses_a_destination_the_run_logged_into() -> None:
    """ "Disabled destinations receive no credentials **or requests**."

    Buildx pushes whatever tag list it is handed. A Docker Hub tag passed with
    `dockerhub: false` issues a request to a destination the run declared disabled -- it
    fails, so nothing ships wrong, but the AC is about the request. `dev.yaml` is safe
    today only because its plan job emits a single forge tag; `release.yaml` will make
    that list conditional.

    Asserted by RUNNING the step, not by reading it. A textual check ("the word
    `permitted` appears") passes with the rejection branch deleted and the variable left
    behind, which is exactly the shape of guard this repository keeps finding.
    """
    run = _compose_tag_list

    completed, emitted = run("ghcr.io/owner/name:dev-0123456789ab")
    assert completed.returncode == 0, completed.stderr
    assert emitted["tags"] == "ghcr.io/owner/name:dev-0123456789ab"
    assert emitted["primary"] == "ghcr.io/owner/name"
    assert set(emitted["platforms"].split(",")) == set(REQUIRED_IMAGE_PLATFORMS)

    # A registry with a port must not be mistaken for a repository with a tag.
    completed, emitted = run(
        "git.example.com:3000/owner/name:dev-0123456789ab",
        registry="git.example.com:3000",
    )
    assert completed.returncode == 0, completed.stderr
    assert emitted["primary"] == "git.example.com:3000/owner/name"

    # Docker Hub, disabled: the request must never be issued.
    completed, _ = run(
        "ghcr.io/owner/name:dev-0123456789ab\ndocker.io/owner/name:dev-0123456789ab"
    )
    assert completed.returncode != 0, "a tag for a disabled destination was accepted"
    # Docker Hub's implicit authority is the same violation without the hostname.
    completed, _ = run("owner/name:dev-0123456789ab")
    assert completed.returncode != 0

    # Enabled, and it goes through.
    completed, emitted = run(
        "ghcr.io/owner/name:dev-0123456789ab\ndocker.io/owner/name:dev-0123456789ab",
        dockerhub="true",
    )
    assert completed.returncode == 0, completed.stderr
    assert emitted["tags"].count(",") == 1

    for malformed in (
        "ghcr.io/owner/name:a,b",  # a comma splits into two tags under bake's CSV parse
        "ghcr.io/owner/name",  # no tag at all
        "",  # nothing to publish
        "   ",
    ):
        completed, _ = run(malformed)
        assert completed.returncode != 0, f"accepted malformed tag list {malformed!r}"


# ---------------------------------------------------------------------------
# Stable channel (story E008-S01-002). Every guard below was proven by planting
# the violation it forbids -- rule and scope -- and confirming the guard fails.
# ---------------------------------------------------------------------------

RELEASE_WORKFLOW = WORKFLOWS / "release.yaml"


def _emitted(output: Path) -> dict[str, str]:
    """Parse a `GITHUB_OUTPUT` file, including the `key<<DELIMITER` heredoc form.

    The stable identity emits a newline-separated tag list, which the flat
    `line.split("=", 1)` parse silently mangles into three unusable entries.
    """
    values: dict[str, str] = {}
    lines = output.read_text(encoding="utf-8").splitlines()
    index = 0
    while index < len(lines):
        line = lines[index]
        index += 1
        if not line:
            continue
        name, _, value = line.partition("=")
        if "<<" in name:
            name, _, delimiter = name.partition("<<")
            collected = []
            while index < len(lines) and lines[index] != delimiter:
                collected.append(lines[index])
                index += 1
            index += 1
            values[name] = "\n".join(collected)
            continue
        values[name] = value
    return values


def _run_step(
    body: str, environment: dict[str, str], cwd: Path
) -> tuple[Any, dict[str, str]]:
    """Execute a workflow step's real `run:` body and return its emitted outputs."""
    output = Path(tempfile.mkdtemp()) / "github-output"
    output.touch()
    completed = subprocess.run(
        ["bash", "-c", body],
        cwd=cwd,
        env={
            "PATH": os.environ["PATH"],
            "GITHUB_OUTPUT": str(output),
            "GITHUB_WORKSPACE": str(PROJECT_ROOT),
            **environment,
        },
        capture_output=True,
        text=True,
        check=False,
    )
    return completed, _emitted(output)


def _executable_text(document: dict[str, Any]) -> str:
    """Everything a workflow actually executes, with shell comments removed.

    A prohibition read off the raw file cannot tell "this workflow publishes to X" from
    "this comment explains why it never publishes to X" -- and a guard that fires on the
    explanation gets deleted rather than fixed.
    """
    parts = []
    for job in _jobs(document).values():
        parts.append(json.dumps({k: v for k, v in job.items() if k != "steps"}))
        for step in job.get("steps") or []:
            parts.append(json.dumps({k: v for k, v in step.items() if k != "run"}))
            parts.append(_uncommented(str(step.get("run", ""))))
    return "\n".join(parts)


def _step_with_id(path: Path, step_id: str) -> dict[str, Any]:
    step = next(
        (step for step in _steps(_load_workflow(path)) if step.get("id") == step_id),
        None,
    )
    # A bare `next()` raises StopIteration with no message, so deleting the step a guard
    # exists to examine reads as a broken test rather than as a caught violation -- and
    # a broken test gets "fixed" by deleting it.
    assert step is not None, (
        f"{path.name} has no step with id {step_id!r}; a guard that examines it was "
        f"about to examine nothing"
    )
    return step


def _git(repository: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repository), *arguments],
        capture_output=True,
        text=True,
        check=True,
    )
    return completed.stdout.strip()


@pytest.fixture
def tagged_repository(tmp_path: Path) -> Path:
    """A real repository carrying every ref shape the stable guard must judge.

    Real git, never a mocked `subprocess`: the whole point of delegating peeling and
    reachability to git is that git's answers are the authority, and asserting against
    a fake would test the fake (F9).
    """
    root = tmp_path / "repository"
    root.mkdir()
    _git(root, "init", "--initial-branch=main")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "Test")
    (root / "file.txt").write_text("one\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "one")
    _git(root, "tag", "-a", "v0.9.0", "-m", "release 0.9.0")
    (root / "file.txt").write_text("two\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "two")
    for annotated in ("v1.2.3", "v1.2", "v1.2.3-rc1", "1.2.3", "v01.2.3"):
        _git(root, "tag", "-a", annotated, "-m", f"tag {annotated}")
    _git(root, "tag", "v9.9.9")
    # A release tag on history that never reached the protected default branch.
    _git(root, "checkout", "-b", "sidebranch")
    (root / "file.txt").write_text("side\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "side")
    _git(root, "tag", "-a", "v2.0.0", "-m", "release 2.0.0")
    _git(root, "checkout", "main")
    return root


def test_the_stable_channel_owns_exact_tag_pushes() -> None:
    """The residual left on BL-E008-001: `v*` tag pushes reached nothing.

    `test_any_push_triggered_workflow_verifies_before_it_ships` asserts the conditional
    invariant and would pass vacuously with no stable workflow at all, exactly as it did
    before dev.yaml. This one asserts the workflow exists and is shaped as ADR-0011
    requires, so deleting release.yaml reopens the finding loudly.
    """
    document = _load_workflow(RELEASE_WORKFLOW)
    triggers = document["on"]
    assert set(triggers) == {"push"}
    assert set(triggers["push"]) == {"tags"}
    assert triggers["push"]["tags"] == ["v*"]
    assert document["permissions"] == {"contents": "read"}
    # The deliberate difference from dev.yaml: two tag pushes are two distinct immutable
    # identities, so the second queues rather than cancelling a half-finished fan-out.
    assert document["concurrency"]["cancel-in-progress"] == "false"

    # Exactly one verifier call for the tagged SHA. Counted from the parsed document, so
    # a second call added anywhere in the file -- another job, another spelling of the
    # same `uses:` -- fails here.
    verifier_calls = [
        name
        for name, job in _jobs(document).items()
        if job.get("uses") == VERIFIER_REFERENCE
    ]
    assert verifier_calls == ["verify"]
    verify = _jobs(document)["verify"]
    assert verify["with"]["channel"] == "stable"
    assert verify["with"]["source-sha"] == "${{ needs.plan.outputs.source-sha }}"

    # TestPyPI is development-only, and this is the channel, not a toggle (ADR-0011).
    # Asserted over what the file EXECUTES -- job configuration, step inputs and
    # uncommented `run:` bodies -- so the prose explaining why TestPyPI is absent does
    # not read as the destination being present.
    executable = _executable_text(document)
    assert "TESTPYPI" not in executable.upper(), (
        "release.yaml reaches TestPyPI; that destination is development-only (ADR-0011)"
    )
    assert "test.pypi.org" not in executable


def test_the_release_tag_fixture_names_the_committed_version() -> None:
    """The fixture that drives the identity guard must not drift from the repository."""
    event = _load_fixture("push-tag.json")
    assert event["event_name"] == "push"
    assert event["ref"] == f"refs/tags/v{committed_versions.package_version()}"
    assert event["ref"] == f"refs/tags/{event['ref_name']}"
    assert re.fullmatch(r"[0-9a-f]{40}", event["sha"])


@pytest.mark.parametrize(
    ("ref", "reason"),
    [
        ("refs/tags/v9.9.9", "a lightweight tag is not the release identity"),
        ("refs/tags/v1.2", "a floating alias is not an exact version"),
        ("refs/tags/v1.2.3-rc1", "a prerelease is not a stable release"),
        ("refs/tags/1.2.3", "the stable spelling carries the v prefix"),
        ("refs/tags/v01.2.3", "a zero-padded component is malformed"),
        ("refs/tags/v1.2.3.4", "a fourth component is not the release spelling"),
        ("refs/tags/release-1.2.3", "a prefixed name is not the release spelling"),
        ("refs/heads/main", "a branch ref is not a tag at all"),
        (
            "refs/heads/v1.2.3",
            "a branch that shares a release tag's name is still not the tag",
        ),
        ("refs/tags/v0.9.0", "the peeled commit is not the event SHA"),
    ],
)
def test_the_release_guard_rejects_every_ref_that_is_not_an_exact_stable_tag(
    tagged_repository: Path, ref: str, reason: str
) -> None:
    """The ref table, run against the guard's real `run:` body and real git.

    Planted to prove it: delete the
    `[[ "$(git for-each-ref --format='%(objecttype)' ...)" == tag ]]` line from the
    `tag` step's body in release.yaml (`:391`) and the lightweight case passes, so this
    test fails. The instruction used to name `stable_tags.annotated_tags`, a module
    E008-S01-003 deleted -- an unfollowable plant is a claim with no evidence behind it.
    """
    head = _git(tagged_repository, "rev-parse", "HEAD")
    completed, _ = _run_step(
        str(_step_with_id(RELEASE_WORKFLOW, "tag")["run"]),
        {"DEFAULT_BRANCH_REF": "main", "EVENT_REF": ref, "EVENT_OBJECT": head},
        tagged_repository,
    )
    assert completed.returncode != 0, f"{ref} was accepted, but {reason}"


def test_the_release_guard_accepts_the_annotated_exact_tag_on_the_event_commit(
    tagged_repository: Path,
) -> None:
    head = _git(tagged_repository, "rev-parse", "HEAD")
    completed, emitted = _run_step(
        str(_step_with_id(RELEASE_WORKFLOW, "tag")["run"]),
        {
            "DEFAULT_BRANCH_REF": "main",
            "EVENT_REF": "refs/tags/v1.2.3",
            "EVENT_OBJECT": head,
        },
        tagged_repository,
    )
    assert completed.returncode == 0, completed.stderr
    assert emitted["tag"] == "v1.2.3"
    assert emitted["version"] == "1.2.3"
    assert emitted["tag-commit"] == head


def test_the_release_guard_refuses_a_tag_that_never_reached_the_default_branch(
    tagged_repository: Path,
) -> None:
    """Reachability is git's answer, not a pattern: `v2.0.0` is annotated, exactly
    spelled, and peels to the event commit. It is still not publishable, because that
    commit is on history the protected default branch never took."""
    side = _git(tagged_repository, "rev-parse", "sidebranch")
    _git(tagged_repository, "checkout", "--detach", side)
    completed, _ = _run_step(
        str(_step_with_id(RELEASE_WORKFLOW, "tag")["run"]),
        {
            "DEFAULT_BRANCH_REF": "main",
            "EVENT_REF": "refs/tags/v2.0.0",
            "EVENT_OBJECT": side,
        },
        tagged_repository,
    )
    assert completed.returncode != 0, "an unreachable release tag was accepted"


def test_the_release_guard_refuses_a_checkout_that_is_not_the_event_commit(
    tagged_repository: Path,
) -> None:
    """The guard peels tags out of the checked-out repository, so a checkout that is not
    the event commit would have it answering about the wrong history entirely."""
    ancestor = _git(tagged_repository, "rev-parse", "HEAD~1")
    completed, _ = _run_step(
        str(_step_with_id(RELEASE_WORKFLOW, "tag")["run"]),
        {
            "DEFAULT_BRANCH_REF": "main",
            "EVENT_REF": "refs/tags/v0.9.0",
            "EVENT_OBJECT": ancestor,
        },
        tagged_repository,
    )
    assert completed.returncode != 0, "a checkout that is not the event commit passed"


def _release_identity_environment(**overrides: str) -> dict[str, str]:
    event = _load_fixture("push-tag.json")
    version = committed_versions.package_version()
    environment = {
        "COMMITTED_VERSION": version,
        "IMAGE_REPOSITORY": f"ghcr.io/{event['repository']}",
        "RELEASE_TAG": f"v{version}",
        "RELEASE_VERSION": version,
        "RESOLVED_PYTHON": "3.14.0",
        "TAG_COMMIT": event["sha"],
    }
    environment.update(overrides)
    return environment


def test_the_stable_identity_is_a_relation_between_fields_never_a_literal(
    tmp_path: Path,
) -> None:
    """CI-AR11, asserted by RUNNING the identity step rather than by reading it.

    The step compares the tag, the version it spells, the committed Poetry version, the
    peeled tag commit and the event SHA against each other. Nothing in it names a
    version, which is the property that makes the next release use the same code path as
    this one -- so the literal check is part of the guard, not a separate style rule.
    """
    identity = _step_with_id(RELEASE_WORKFLOW, "identity")
    body = str(identity["run"])
    assert not re.search(r"[0-9]+\.[0-9]+\.[0-9]+", _uncommented(body)), (
        "the stable identity step names a version literal; it must compare fields"
    )

    completed, emitted = _run_step(body, _release_identity_environment(), tmp_path)
    assert completed.returncode == 0, completed.stderr
    version = committed_versions.package_version()
    event = _load_fixture("push-tag.json")
    assert emitted["package-version"] == version
    assert emitted["source-sha"] == event["sha"]
    assert emitted["python-version"] == "3.14.0"
    # Exactly one immutable tag per enabled destination, and no alias: `latest`, `vX`
    # and `vX.Y` all belong to the finalizer story. The value is decided here; rendering
    # it against each enabled repository is the metadata action's job, asserted by
    # `test_image_references_are_rendered_by_the_metadata_action_never_hand_joined` and,
    # for the Docker Hub leg, by
    # `test_docker_hub_enabled_with_a_well_formed_repository_reaches_the_image_job`.
    assert emitted["image-tag-value"] == version
    assert not emitted.get("image-tags"), (
        "the identity step composes image references itself; it decides the tag value "
        "and the metadata action renders it"
    )


@pytest.mark.parametrize(
    "mismatch",
    [
        {"COMMITTED_VERSION": "9.9.9"},
        {"RELEASE_TAG": "v9.9.9"},
        {"RELEASE_VERSION": "9.9.9"},
        {"TAG_COMMIT": "not-a-sha"},
        {"TAG_COMMIT": ""},
        {"RELEASE_TAG": ""},
        {"RELEASE_VERSION": ""},
        {"COMMITTED_VERSION": ""},
        {"RESOLVED_PYTHON": ""},
        {"IMAGE_REPOSITORY": ""},
    ],
)
def test_one_mismatched_identity_field_stops_the_run_before_any_publisher(
    tmp_path: Path, mismatch: dict[str, str]
) -> None:
    """One field planted per run, because a relation that only fails when everything
    disagrees is not a relation. Each of these would otherwise publish an artifact whose
    version identity nobody chose."""
    completed, _ = _run_step(
        str(_step_with_id(RELEASE_WORKFLOW, "identity")["run"]),
        _release_identity_environment(**mismatch),
        tmp_path,
    )
    assert completed.returncode != 0, f"{mismatch} was accepted as a stable identity"


def test_every_stable_consumer_reads_the_planned_identity_rather_than_its_own() -> None:
    """The plan job proves the identity once; everything downstream is handed that value.

    Scope is derived from the parsed jobs -- every job that is not the producer -- so a
    publisher added later that re-derives a version, or restates one, fails here. That
    is the scope attack: the rule is trivial, the reach is the whole point.
    """
    document = _load_workflow(RELEASE_WORKFLOW)
    jobs = _jobs(document)
    producers = {
        name
        for name, job in jobs.items()
        if any("version" in output for output in (job.get("outputs") or {}))
    }
    assert producers == {"plan"}, f"the planned identity has {len(producers)} producers"

    # Matched on the lowercased key, and over `env:` as well as `with:`. `env:` is
    # where a workflow actually carries identity into a `run:` body, so a guard blind to
    # it would pass a publisher that took `PACKAGE_VERSION` from `github.ref_name` --
    # the most natural spelling available to whoever adds one.
    identity_input = re.compile(r"(?:\A|[-_])(?:ref|sha|tags?|version)\Z")
    examined = 0
    for name, job in jobs.items():
        if name in producers:
            continue
        blocks = [job.get("with") or {}, job.get("env") or {}]
        for step in job.get("steps") or []:
            blocks += [step.get("with") or {}, step.get("env") or {}]
        for block in blocks:
            for key, value in block.items():
                key = str(key).lower()
                # `fetch-depth` and `fetch-tags` configure git's transport, not the
                # identity being published; the checkout's `ref:` beside them is the
                # identity, and it is asserted.
                if key.startswith("fetch") or not identity_input.search(key):
                    continue
                examined += 1
                assert "needs.plan.outputs." in str(value), (
                    f"release.yaml: job {name!r} takes {key!r} from {value!r} instead of "
                    f"the single planned identity (CI-AR11)"
                )
    assert examined, (
        "no downstream job consumes an identity value; nothing was examined"
    )


def test_the_run_evidence_job_blocks_on_every_publisher() -> None:
    """ADR-0011's finalizer aggregation: a destination that is not in the aggregator's
    `needs` is a destination whose failure finishes the run green and unreported.

    Both sets are derived from the parsed jobs -- publishers from capability, the
    aggregator from "depends on a publisher and ships nothing" -- so the planted
    violation is the scope attack: a new publisher absent from the aggregator's needs
    fails here without anyone remembering to edit a list.
    """
    channel_workflows = _publishing_workflows()
    assert channel_workflows, "no workflow calls the image publisher"
    for path in channel_workflows:
        document = _load_workflow(path)
        jobs = _jobs(document)
        publishers = set(_publishers(document))
        assert publishers, f"{path.name} has no publishers; this guard examined nothing"
        aggregators = {
            name
            for name in jobs
            if name not in publishers and _transitive_needs(jobs, name) & publishers
        }
        assert aggregators, (
            f"{path.name}: no job aggregates the publishers, so a failed destination is "
            f"reported nowhere (ADR-0011)"
        )
        for name in sorted(aggregators):
            missing = publishers - _transitive_needs(jobs, name)
            assert not missing, (
                f"{path.name}: job {name!r} aggregates publication outcomes but does not "
                f"depend on {sorted(missing)}; their failure would finish the run green "
                f"and unreported (ADR-0011)"
            )


def test_the_published_index_assertion_rejects_an_index_that_lost_a_platform(
    tmp_path: Path,
) -> None:
    """ADR-0008's platform assertion, run rather than read.

    `test_the_published_index_is_asserted_by_annotation_never_by_descriptor_count`
    proves the filter is spelled on the annotation. It cannot prove the comparison
    fires: with the `!=` branch deleted the annotation is still mentioned and that guard
    stays green. Here the real code judges real indexes -- including the one the story
    asks to plant, a published index carrying a single platform.
    """
    body = str(_step_with_id(PUBLISH_IMAGE_WORKFLOW, "index")["run"])
    heredoc = re.search(r"<<'PY'[^\n]*\n(.*?)\nPY\n", body, re.DOTALL)
    assert heredoc, "the index assertion is no longer an inline Python heredoc"
    script = tmp_path / "assert_index.py"
    script.write_text(heredoc.group(1), encoding="utf-8")

    def judge(manifests: Any) -> Any:
        (tmp_path / "published-index.json").write_text(
            json.dumps({"manifests": manifests}), encoding="utf-8"
        )
        return subprocess.run(
            [sys.executable, str(script)],
            cwd=tmp_path,
            env={
                "PATH": os.environ["PATH"],
                "PLATFORMS": ",".join(REQUIRED_IMAGE_PLATFORMS),
            },
            capture_output=True,
            text=True,
            check=False,
        )

    def platform(os_name: str, architecture: str) -> dict[str, Any]:
        return {"platform": {"os": os_name, "architecture": architecture}}

    def attestation(architecture: str) -> dict[str, Any]:
        entry = platform("unknown", architecture)
        entry["annotations"] = {
            "vnd.docker.reference.type": "attestation-manifest",
        }
        return entry

    published = [
        platform("linux", "amd64"),
        platform("linux", "arm64"),
        attestation("unknown"),
        attestation("unknown"),
    ]
    completed = judge(published)
    assert completed.returncode == 0, completed.stderr
    assert "platforms=linux/amd64,linux/arm64" in completed.stdout
    # Four descriptors, not two -- reported, never asserted on (ADR-0008 as amended).
    assert "descriptors=4" in completed.stdout

    # The planted violation: a published index carrying one platform.
    completed = judge([platform("linux", "amd64"), attestation("unknown")])
    assert completed.returncode != 0, "an index missing a platform was accepted"

    # And the filter is load-bearing: an attestation manifest must not be counted as the
    # platform it is annotated for.
    completed = judge(
        [
            platform("linux", "amd64"),
            {
                "platform": {"os": "linux", "architecture": "arm64"},
                "annotations": {
                    "vnd.docker.reference.type": "attestation-manifest",
                },
            },
        ]
    )
    assert completed.returncode != 0, "an attestation manifest was read as a platform"

    completed = judge("not-an-index")
    assert completed.returncode != 0, "a single-platform reference was accepted"


def test_the_release_guard_peels_the_pushed_object_before_comparing_it(
    tagged_repository: Path,
) -> None:
    """A push event reports the ref's new object id, and an annotated tag's ref points
    at the tag object, not at the commit.

    This channel accepts *only* annotated tags, so a comparison that never peels is a
    channel that never publishes -- failing closed on the one path it has, and doing it
    for the first time on a release day. `git rev-parse HEAD` after checking out a tag
    object is the commit, so the two values differ by construction.
    """
    tag_object = _git(tagged_repository, "rev-parse", "v1.2.3")
    commit = _git(tagged_repository, "rev-parse", "v1.2.3^{commit}")
    assert tag_object != commit, "v1.2.3 is not annotated; this test proves nothing"

    completed, emitted = _run_step(
        str(_step_with_id(RELEASE_WORKFLOW, "tag")["run"]),
        {
            "DEFAULT_BRANCH_REF": "main",
            "EVENT_REF": "refs/tags/v1.2.3",
            "EVENT_OBJECT": tag_object,
        },
        tagged_repository,
    )
    assert completed.returncode == 0, completed.stderr
    # And the peeled commit is what flows downstream: every checkout, the verifier and
    # every bundle revalidation are handed this, never the tag object.
    assert emitted["tag-commit"] == commit


def _release_destinations(**environment: str) -> tuple[Any, dict[str, str]]:
    defaults = {
        "DOCKERHUB_ORG": "",
        "DOCKERHUB_TOGGLE": "",
        "FORGE": "github",
        # The namespace is the knob; the name follows the built image, so the harness
        # supplies it the way the forge coordinate does rather than letting a test invent
        # a name Docker Hub and the forge registry could disagree on.
        "FORGE_OWNER": "ravensorb",
        "IMAGE_NAME": "traefik-certificate-exporter",
        "PACKAGE_INDEX_SUPPORTED": "false",
        "PYPI_TOGGLE": "",
    }
    defaults.update(environment)
    return _run_step(
        str(_step_with_id(RELEASE_WORKFLOW, "destinations")["run"]),
        defaults,
        Path(tempfile.mkdtemp()),
    )


def test_the_enabled_destination_set_distinguishes_disabled_from_unsupported() -> None:
    """ADR-0011 section 2, executed rather than described.

    Every decision this story takes about destinations lives in one step, and the
    distinction it exists to preserve -- an operator turned it off, versus the host
    never had it -- is invisible when it regresses: both spellings produce a run that
    publishes nothing there and reports success.
    """
    completed, emitted = _release_destinations()
    assert completed.returncode == 0, completed.stderr
    destinations = json.loads(emitted["enabled-destinations"])
    assert destinations["image-forge"] == "enabled", "the channel is not a toggle"
    assert destinations["image-dockerhub"] == "disabled"
    assert destinations["package-pypi"] == "disabled"
    # GitHub has no forge Python index, and no toggle can create one.
    assert destinations["package-forge"] == "unsupported"
    assert emitted["dockerhub-repository"] == ""
    assert "package-testpypi" not in destinations, "TestPyPI is development-only"

    completed, emitted = _release_destinations(PACKAGE_INDEX_SUPPORTED="true")
    assert completed.returncode == 0, completed.stderr
    assert json.loads(emitted["enabled-destinations"])["package-forge"] == "enabled"

    # Trusted publishing needs a GitHub OIDC identity; on Gitea there is none, and the
    # toggle cannot conjure one. `unsupported`, never `disabled`, and never a failed job.
    completed, emitted = _release_destinations(FORGE="gitea", PYPI_TOGGLE="true")
    assert completed.returncode == 0, completed.stderr
    assert json.loads(emitted["enabled-destinations"])["package-pypi"] == "unsupported"

    completed, emitted = _release_destinations(PYPI_TOGGLE="true")
    assert completed.returncode == 0, completed.stderr
    assert json.loads(emitted["enabled-destinations"])["package-pypi"] == "enabled"


@pytest.mark.parametrize(
    "toggle", ["yes", "1", "True", "enabled", "TRUE", " true", "on"]
)
def test_a_publication_toggle_is_never_coerced(toggle: str) -> None:
    """`true`, `false` or absent. Anything else fails the plan job, because the
    alternative is `PUBLISH_PACKAGE_PYPI=yes` reading as "off" for a year."""
    completed, _ = _release_destinations(PYPI_TOGGLE=toggle)
    assert completed.returncode != 0, f"PYPI_TOGGLE={toggle!r} was coerced"
    completed, _ = _release_destinations(DOCKERHUB_TOGGLE=toggle)
    assert completed.returncode != 0, f"DOCKERHUB_TOGGLE={toggle!r} was coerced"


@pytest.mark.parametrize(
    "namespace",
    # The empty string is deliberately ABSENT: it now means "derive from the forge owner"
    # and is the documented default, covered by the test below. These are the values that
    # are supplied and unusable.
    ["Foo", "acme/exporter", "docker.io/acme", "acme/", "/x", "ac me", "-acme"],
)
def test_docker_hub_is_never_enabled_without_a_namespace_to_publish_to(
    namespace: str,
) -> None:
    """An enabled toggle with an unusable namespace would push an *immutable* tag
    somewhere nobody chose, so it fails closed exactly as an unrecognised forge does.

    Only the namespace is validated now, because only the namespace is supplied. The
    image name comes from the forge coordinate, so it cannot be malformed independently
    -- and a namespace carrying a slash is rejected rather than silently composing a
    three-segment reference."""
    completed, _ = _release_destinations(
        DOCKERHUB_TOGGLE="true", DOCKERHUB_ORG=namespace
    )
    assert completed.returncode != 0, f"DOCKERHUB_ORG={namespace!r} was accepted"


def test_docker_hub_enabled_with_a_well_formed_repository_reaches_the_image_job() -> (
    None
):
    # The namespace is the only knob. The image name follows the built image, so no
    # override can make Docker Hub ship a different name from the forge registry.
    completed, emitted = _release_destinations(
        DOCKERHUB_TOGGLE="true", DOCKERHUB_ORG="acme"
    )
    assert completed.returncode == 0, completed.stderr
    assert json.loads(emitted["enabled-destinations"])["image-dockerhub"] == "enabled"
    assert emitted["dockerhub-repository"] == "acme/traefik-certificate-exporter"

    # With no override it derives from the forge owner rather than failing closed, which
    # is what made this destination unusable until an operator set a variable nobody knew
    # about. Fork-correct: a fork resolves its own namespace.
    completed, derived = _release_destinations(DOCKERHUB_TOGGLE="true")
    assert completed.returncode == 0, completed.stderr
    assert derived["dockerhub-repository"] == "ravensorb/traefik-certificate-exporter"

    # And the value reaches the reference renderer as a second `images:` entry. Without
    # this the destination is "enabled" and no Docker Hub tag is ever produced for it --
    # a disabled publication that reports itself enabled, which is the failure the
    # enabled set exists to make visible.
    jobs = _jobs(_load_workflow(RELEASE_WORKFLOW))
    plan = jobs["plan"]
    destinations_step = _producing_step(
        RELEASE_WORKFLOW, "plan", plan, "enabled-destinations"
    )["id"]
    images = str(
        (
            _producing_step(RELEASE_WORKFLOW, "plan", plan, "image-tags").get("with")
            or {}
        ).get("images", "")
    )
    assert f"steps.{destinations_step}.outputs.dockerhub-repository" in images, (
        "release.yaml: the accepted Docker Hub repository never reaches `images:`, so "
        "the enabled destination receives no tag"
    )
    assert "docker.io/" in images, (
        "release.yaml: the Docker Hub repository is not qualified with its registry"
    )


def test_optional_destination_credentials_are_gated_on_the_enabled_set() -> None:
    """ "Disabled destinations receive no credentials **or requests**."

    The requests half is publish-image.yaml's permitted-authority check. This is the
    credentials half: a secret handed to a called workflow is materialised in its
    context whether or not the destination is enabled.

    Which credentials are optional is read from the CALLEE's own `workflow_call.secrets`
    declaration -- `required: false` is exactly "this destination may be absent" -- so a
    new optional destination is covered the day the reusable workflow declares it, with
    no list here to keep.
    """
    examined = 0
    for path in _publishing_workflows():
        for job_name, job in _jobs(_load_workflow(path)).items():
            called = str(job.get("uses", ""))
            if not called.startswith("./.github/workflows/"):
                continue
            callee = _load_workflow(PROJECT_ROOT / called.removeprefix("./"))
            declared = (callee.get("on") or {}).get("workflow_call") or {}
            optional = {
                name
                for name, specification in (declared.get("secrets") or {}).items()
                if str((specification or {}).get("required", "false")).lower() != "true"
            }
            supplied = job.get("secrets")
            if not isinstance(supplied, dict):
                continue
            for name in sorted(optional & set(supplied)):
                examined += 1
                assert "enabled-destinations" in str(supplied[name]), (
                    f"{path.name}: job {job_name!r} hands {name!r} to {called} "
                    f"unconditionally. A destination the plan job reported disabled "
                    f"receives no credentials (CI-AR24, ADR-0011)."
                )
    assert examined, "no optional destination credential was examined"


def test_channel_workflows_surface_the_published_digest_and_platforms() -> None:
    """The third clause of prep finding P1, which nothing else asserts.

    `test_channel_workflows_consume_image_inspection_rather_than_performing_it` proves
    the registry read is not in the channel workflow and is in the image publisher. It
    says nothing about the result being consumed -- so deleting the digest and platform
    rows from the evidence table satisfies every other guard and CI-AR41's evidence
    disappears silently.
    """
    examined = 0
    for path in _image_channel_workflows():
        document = _load_workflow(path)
        body = json.dumps(document)
        image_jobs = [
            name
            for name, job in _jobs(document).items()
            if job.get("uses") == PUBLISH_IMAGE_REFERENCE
        ]
        assert image_jobs, f"{path.name}: no image publisher call"
        for name in image_jobs:
            for output in ("digest", "platforms"):
                examined += 1
                assert f"needs.{name}.outputs.{output}" in body, (
                    f"{path.name}: the published {output} is never surfaced. One digest "
                    f"and both inspected platforms are this channel's evidence, "
                    f"consumed from the image publisher's outputs (CI-AR41, P1)."
                )
    assert examined, "no channel workflow consumes the image publisher's outputs"


# ---------------------------------------------------------------------------
# Finalization (story E008-S01-003). Every guard below was proven by planting the
# violation it forbids -- the rule AND the scope -- and confirming the guard fails.
# ---------------------------------------------------------------------------

# How the finalization gate is LOCATED, now that it is a `jq` program in the step rather
# than a module the step calls. The prefix every one of its refusals carries, so a gate
# that stopped refusing stops being found -- which fails the coverage assertions loudly
# rather than leaving them examining nothing.
GATE_MARKER = "finalizer gate:"

# How the annotated-tag membership decision is LOCATED in a `run:` body. `%(objecttype)`
# is the annotated-object filter itself: a step that peels tags without it accepts a
# lightweight `v1.2.3` pushed by hand, which is the release-breaking defect story 002
# recorded as HIGH-1. Matching the mechanism rather than a step name means a re-check
# that was gutted is no longer found at all.
TAG_MEMBERSHIP_MARKER = "%(objecttype)"

# The stable channel's re-check names the tag it was handed; the development channel's
# enumerates every tag on the commit. Two spellings of one relation, and each is the
# marker for its own channel.
STABLE_RECHECK_MARKER = "refs/tags/$RELEASE_TAG"

# git's own version ordering, which is what makes the alias decision a delegation rather
# than a second implementation. A step that reached for `sort` instead is not found here.
ALIAS_ORDER_MARKER = "--sort=v:refname"

# Every spelling of "give an image that already exists another name". A digest copy is
# a registry WRITE, which is why it is not matched by REGISTRY_READ_COMMANDS: the
# ordering guard forbids asking a registry what is there, not putting something there.

ALIAS_MOVE_COMMANDS = (
    r"\bbuildx\s+imagetools\s+create\b",
    r"\bcrane\s+(?:tag|copy)\b",
    r"\bskopeo\s+copy\b",
    r"\bregctl\s+(?:index|image)\s+copy\b",
    r"\bdocker\s+push\b",
)

# What a finalizer must never do. It attaches names to an artifact set that already
# exists; a build here would produce a *different* artifact under a name the release
# already promised (CI-AR39, ADR-0008).
BUILD_COMMANDS = (
    r"\bbuildx\s+(?:bake|build)\b",
    r"\bdocker\s+build\b",
    r"\bpython\s+-m\s+build\b",
    r"\bpoetry\s+build\b",
)
BUILD_ACTIONS = ("docker/build-push-action", "docker/bake-action")

EXPRESSION = re.compile(r"\$\{\{\s*(.+?)\s*\}\}")


def _alias_moving_jobs(
    documents: dict[str, dict[str, Any]] | None = None,
) -> set[tuple[str, str]]:
    """Every job that points a mutable name at an artifact, from the parsed steps.

    Both kinds, because the story owns both: a Git alias moved by the approved action,
    and a registry alias moved by a digest copy. Derived rather than enumerated, so an
    alias step added to a publisher shows up here without anyone editing a list.

    Takes an optional document set so a scope attack can plant one.
    """
    moving = set()
    for name, document in sorted((documents or _workflow_documents()).items()):
        for job_name, job in _jobs(document).items():
            for step in job.get("steps", []) or []:
                if str(step.get("uses", "")).startswith(APPROVED_ALIAS_ACTION):
                    moving.add((name, job_name))
                command = _uncommented(str(step.get("run", "")))
                if any(re.search(probe, command) for probe in ALIAS_MOVE_COMMANDS):
                    moving.add((name, job_name))
    return moving


def _ordering_steps(job: dict[str, Any]) -> set[str]:
    """Step ids in this job that read the Git tag order."""
    return {
        str(step["id"])
        for step in job.get("steps", []) or []
        if step.get("id")
        and ALIAS_ORDER_MARKER in _uncommented(str(step.get("run", "")))
    }


def _ordering_outputs(document: dict[str, Any]) -> dict[str, set[str]]:
    """Job name -> the job outputs that carry an ordering decision out of it.

    Derived by following each job's `outputs:` mapping back to the step that produced
    it, so a renamed output or a new one is covered without editing anything here.
    """
    produced: dict[str, set[str]] = {}
    for job_name, job in _jobs(document).items():
        step_ids = _ordering_steps(job)
        if not step_ids:
            continue
        names = {
            output
            for output, value in (job.get("outputs") or {}).items()
            if any(f"steps.{step_id}.outputs." in str(value) for step_id in step_ids)
        }
        if names:
            produced[job_name] = names
    return produced


def test_every_alias_ordering_decision_is_the_same_body() -> None:
    """One ordering rule, one implementation, however many places read it.

    `finalize` decides and `finalize-image-aliases` re-decides; two copies of a
    `--sort=v:refname` comparison that drift are two answers to "which tag is
    greatest", and the copy nobody updated is the one that moves `latest`.
    """
    bodies = {
        _uncommented(str(step.get("run", "")))
        for document in _workflow_documents().values()
        for job in _jobs(document).values()
        for step in job.get("steps", []) or []
        if ALIAS_ORDER_MARKER in _uncommented(str(step.get("run", "")))
    }
    assert bodies, "no step reads the tag order; this guard examined nothing"
    assert len(bodies) == 1, (
        f"{len(bodies)} different alias-ordering bodies are in use; they must be one"
    )


def test_no_alias_move_consumes_an_ordering_decision_taken_in_another_job() -> None:
    """The alias inversion, closed at its source.

    `finalize` decided `advance-major` and `finalize-image-aliases` applied it a job
    later. Two stable tags are two refs and run fully in parallel by design, so a
    slower `v1.2.3` run applied a decision that was true when taken and false when
    used, dragging `latest` and `v1` back off `v1.3.0` -- both runs green. The same
    inversion happened inside one run whenever a tag landed between the two jobs.

    So the rule is structural rather than temporal: the ordering authority is read in
    the job that writes, never handed across a job boundary. Derived from each job's
    own `outputs:` mapping, so an ordering output added or renamed later is covered.
    """
    examined = 0
    for name, document in sorted(_workflow_documents().items()):
        ordering = _ordering_outputs(document)
        if not ordering:
            continue
        movers = {job for workflow, job in _alias_moving_jobs() if workflow == name}
        for job_name in sorted(movers):
            rendered = json.dumps(_jobs(document)[job_name])
            examined += 1
            for producer, outputs in sorted(ordering.items()):
                if producer == job_name:
                    continue
                for output in sorted(outputs):
                    assert f"needs.{producer}.outputs.{output}" not in rendered, (
                        f"{name}: job {job_name!r} moves an alias using "
                        f"{output!r} decided in job {producer!r}. The tag set is read "
                        f"where the write happens, or the answer can be stale by the "
                        f"time it is used (F4)."
                    )
    assert examined, "no alias mover shares a file with an ordering decision"


def test_a_job_that_decides_alias_order_serialises_against_every_other_run() -> None:
    """A fresh read is only meaningful if the writes are ordered.

    The workflow-level group is keyed on `github.ref`, which is correct for the
    immutable fan-out and wrong for a shared mutable name: two tags never queue
    against each other. Every job that takes an ordering decision therefore carries a
    ref-free job-level group, so the alias stage of one run cannot interleave with
    another's.
    """
    examined = 0
    for name, document in sorted(_workflow_documents().items()):
        for job_name, job in sorted(_jobs(document).items()):
            if not _ordering_steps(job):
                continue
            examined += 1
            group = str((job.get("concurrency") or {}).get("group", ""))
            assert group, (
                f"{name}: job {job_name!r} decides alias order with no job-level "
                f"concurrency group, so two runs' alias stages interleave"
            )
            assert "github.ref" not in group, (
                f"{name}: job {job_name!r} serialises on {group!r}, which is keyed on "
                f"the ref -- two tags are two refs, so this queues nothing"
            )
    assert examined, "no job decides alias order; this guard examined nothing"


# The scopes the finalizer authority split depends on, in both directions: the
# ref-writing job must not hold them, and the registry job must not hold `contents:
# write`. Denial is stated, never inferred.
AUTHORITY_SCOPES = ("contents", "packages", "id-token", "attestations")


def test_every_finalizer_states_the_scopes_it_relies_on_being_denied() -> None:
    """ADR-0006's split is enforced by `permissions:`, and on GitHub an unlisted scope
    is `none`. That semantic is what the whole split rests on, and it is platform
    behaviour rather than something this repository states.

    Gitea does not document it and ships `TokenPermissionMode` permissive by default,
    so on the forge E009 targets, omission grants where GitHub denies -- and the
    ref-writing finalizer would silently acquire the registry authority the split
    exists to keep away from it. An explicit `none` needs no inference from any runner.

    Gitea's granular `code:`/`releases:` spellings are deliberately absent: they are
    not valid GitHub scopes, actionlint rejects the file outright, and the remaining
    platform requirement is a precondition recorded in ADR-0006 rather than YAML.
    """
    examined = 0
    for workflow, job_name in sorted(RELEASE_FINALIZER_JOBS):
        job = _jobs(_load_workflow(WORKFLOWS / workflow))[job_name]
        declared = job.get("permissions")
        assert isinstance(declared, dict), (
            f"{workflow}: finalizer {job_name!r} declares no job-level permissions"
        )
        examined += 1
        for scope in AUTHORITY_SCOPES:
            assert scope in declared, (
                f"{workflow}: finalizer {job_name!r} omits {scope!r}. Omission denies "
                f"on GitHub and grants on a permissive Gitea; state it as `none`."
            )
    assert examined, "no finalizer is registered; this guard examined nothing"


def _finalizers(path: Path) -> set[str]:
    return {job for workflow, job in RELEASE_FINALIZER_JOBS if workflow == path.name}


# Everything a finalizer does that cannot be undone: the Release, a Git alias, a
# registry alias. Derived from the same constants the ownership guard uses, so a new
# spelling of "move an alias" reaches the ordering guard below without a second edit.
def _writing_steps(job: dict[str, Any]) -> list[int]:
    indices = []
    for index, step in enumerate(job.get("steps", []) or []):
        uses = str(step.get("uses", ""))
        command = _uncommented(str(step.get("run", "")))
        if uses.startswith((APPROVED_RELEASE_ACTION, APPROVED_ALIAS_ACTION)) or any(
            re.search(probe, command) for probe in ALIAS_MOVE_COMMANDS
        ):
            indices.append(index)
    return indices


# Every refusal this story owns, by the mechanism that performs it rather than by a step
# name: the enabled-set gate, the `vX.Y.Z` immutability re-check, the alias-ordering
# decision, and the development channel's just-in-time head proof.
REFUSAL_MARKERS = (
    GATE_MARKER,
    TAG_MEMBERSHIP_MARKER,
    ALIAS_ORDER_MARKER,
    "rev-parse HEAD",
)


def _refusing_steps(job: dict[str, Any]) -> list[int]:
    return [
        index
        for index, step in enumerate(job.get("steps", []) or [])
        if any(
            marker in _uncommented(str(step.get("run", "")))
            for marker in REFUSAL_MARKERS
        )
    ]


def _gate_steps(path: Path) -> dict[str, dict[str, Any]]:
    """Every step that evaluates publisher results, keyed by the job holding it.

    Found by the module it calls, never by a step name: a name is a label and a label
    can survive the deletion of the thing it labels. All of them, not the first one a
    set iteration happened to yield -- a second finalizer growing its own gate would
    otherwise be checked or not depending on set ordering.
    """
    found = {}
    for job_name in sorted(_finalizers(path)):
        for step in _jobs(_load_workflow(path))[job_name].get("steps", []) or []:
            if GATE_MARKER in _uncommented(str(step.get("run", ""))):
                found[job_name] = step
    return found


def _gate_step(path: Path) -> dict[str, Any]:
    gates = _gate_steps(path)
    assert len(gates) == 1, (
        f"{path.name} has {len(gates)} finalization gates ({sorted(gates)}); the "
        f"executable anchors below assume one and would silently check only some"
    )
    return next(iter(gates.values()))


def _render(step: dict[str, Any], bindings: dict[str, str]) -> dict[str, str]:
    """The step's real `env:` block with its expressions resolved.

    A binding the workflow does not ask for is never consulted, and an expression with
    no binding raises -- so this is a wiring assertion as well as a fixture: renaming a
    job breaks the render rather than silently supplying the old value.
    """
    rendered = {}
    for name, value in (step.get("env") or {}).items():
        rendered[str(name)] = EXPRESSION.sub(
            lambda match: bindings[match.group(1)], str(value)
        )
    return rendered


def test_only_registered_finalizers_move_an_alias() -> None:
    """The definition-of-done clause: this story is the sole owner of every alias job.

    Equality, not containment, in both directions. Containment one way lets a publisher
    grow an alias step; containment the other way lets a registered grant sit unused,
    which is a `contents: write` nobody is watching.
    """
    moving = _alias_moving_jobs()
    assert moving == RELEASE_FINALIZER_JOBS, (
        f"alias-moving jobs {sorted(moving)} are not the registered finalizer set "
        f"{sorted(RELEASE_FINALIZER_JOBS)}. Moving a ref, tag or registry alias is the "
        f"grant ADR-0006 governs; register the job, or move the step into a finalizer."
    )


def test_no_finalizer_builds_anything() -> None:
    """A finalizer names artifacts that already exist. Building one here would ship a
    different artifact under a name the run has already promised, and the difference is
    invisible: same tag, same version, other bits."""
    examined = 0
    for path in sorted(WORKFLOWS.glob("*.yaml")):
        for job_name in sorted(_finalizers(path)):
            job = _jobs(_load_workflow(path))[job_name]
            for step in job.get("steps", []) or []:
                examined += 1
                command = _uncommented(str(step.get("run", "")))
                for pattern in BUILD_COMMANDS:
                    assert not re.search(pattern, command), (
                        f"{path.name}: finalizer {job_name!r} builds an artifact. It "
                        f"may only name what the publishers already shipped (CI-AR39)."
                    )
                action = str(step.get("uses", "")).split("@", 1)[0]
                assert action not in BUILD_ACTIONS, (
                    f"{path.name}: finalizer {job_name!r} runs {action}, which builds"
                )
    assert examined, "no finalizer step was examined"


def test_ref_writing_and_registry_alias_privileges_never_meet() -> None:
    """Least privilege, per job, from the parsed `permissions:` and the parsed steps.

    Two planted violations, in opposite directions: a registry credential on the job
    that writes refs, and `contents: write` on the job that moves registry aliases.
    Either one recreates the single over-privileged finalizer the split exists to avoid
    -- one compromised step that can both rewrite history and publish an image.
    """
    ref_writers = 0
    alias_movers = 0
    for path in sorted(WORKFLOWS.glob("*.yaml")):
        for job_name, job in _jobs(_load_workflow(path)).items():
            steps = job.get("steps", []) or []
            permissions = job.get("permissions") or {}
            writes_refs = any(
                str(step.get("uses", "")).startswith(
                    (APPROVED_RELEASE_ACTION, APPROVED_ALIAS_ACTION)
                )
                for step in steps
            )
            moves_registry_alias = any(
                re.search(probe, _uncommented(str(step.get("run", ""))))
                for step in steps
                for probe in ALIAS_MOVE_COMMANDS
            )
            if writes_refs:
                ref_writers += 1
                assert permissions.get("packages") != "write", (
                    f"{path.name}: {job_name!r} writes refs and takes `packages: write`"
                )
                body = json.dumps(job)
                assert "docker/login-action" not in body, (
                    f"{path.name}: {job_name!r} writes refs and logs into a registry"
                )
                registry_secrets = {
                    secret
                    for secret in re.findall(
                        r"secrets\.([A-Za-z_][A-Za-z0-9_-]*)", body
                    )
                    if "DOCKER" in secret or "REGISTRY" in secret
                }
                assert not registry_secrets, (
                    f"{path.name}: {job_name!r} writes refs and holds registry "
                    f"credentials {sorted(registry_secrets)}; each finalizer holds one "
                    f"kind of authority"
                )
            if moves_registry_alias:
                alias_movers += 1
                assert permissions.get("contents") != "write", (
                    f"{path.name}: {job_name!r} moves a registry alias and takes "
                    f"`contents: write`; ref authority belongs to the Release finalizer"
                )
    assert ref_writers, "no job writes a ref; this guard examined nothing"
    assert alias_movers, "no job moves a registry alias; this guard examined nothing"


def test_every_finalizer_waits_for_every_publisher_and_reads_every_result() -> None:
    """ADR-0011: `needs:` is static, so the finalizer depends on ALL of them and then
    evaluates their results against the enabled set.

    Both halves, because either alone is satisfiable while the other is broken: a
    `needs:` entry can be deleted, and a publisher can be added that the gate's env
    never mentions. Both sets are derived from `_publishers()`, so the scope attack --
    a new publisher nothing depends on -- fails without anyone editing a list.
    """
    channel_workflows = _publishing_workflows()
    assert channel_workflows, "no workflow calls the image publisher"
    for path in channel_workflows:
        document = _load_workflow(path)
        jobs = _jobs(document)
        finalizers = _finalizers(path)
        assert finalizers, f"{path.name}: no registered finalizer"
        destinations = set(_publishers(document)) - finalizers
        assert destinations, f"{path.name}: no destination publisher; nothing examined"

        for name in sorted(finalizers):
            missing = destinations - _transitive_needs(jobs, name)
            assert not missing, (
                f"{path.name}: finalizer {name!r} does not depend on {sorted(missing)}, "
                f"so it could create a Release and move aliases while that destination "
                f"was still running (ADR-0011)"
            )

        gates = _gate_steps(path)
        assert gates, f"{path.name}: no finalizer evaluates the enabled set (ADR-0011)"
        for gated_job, step in sorted(gates.items()):
            gate = json.dumps(step.get("env") or {})
            assert "needs.plan.outputs.enabled-destinations" in gate, (
                f"{path.name}: {gated_job!r}'s gate never reads the enabled set, so a "
                f"skipped destination cannot be told from a disabled one (ADR-0011)"
            )
            for publisher in sorted(destinations):
                assert f"needs.{publisher}.result" in gate, (
                    f"{path.name}: {gated_job!r}'s gate never reads "
                    f"`needs.{publisher}.result`, so that destination's failure would "
                    f"not block the Release or the aliases (ADR-0011)"
                )

        # And every finalizer that writes is behind a gate -- its own, or one in a job
        # it transitively depends on. Without this a second finalizer could be added
        # with no gate at all and the coverage assertion above would pass, having
        # examined only the gate that does exist.
        for name in sorted(finalizers):
            if not _writing_steps(jobs[name]):
                continue
            reachable = _transitive_needs(jobs, name) | {name}
            assert reachable & set(gates), (
                f"{path.name}: finalizer {name!r} writes a Release or moves an alias "
                f"without a finalization gate in itself or in anything it needs "
                f"(ADR-0011)"
            )


def _run_gate(path: Path, bindings: dict[str, str], summary: Path | None = None) -> Any:
    step = _gate_step(path)
    environment = _render(step, bindings)
    if summary is not None:
        summary.touch()
        environment["GITHUB_STEP_SUMMARY"] = str(summary)
    completed, _ = _run_step(str(step["run"]), environment, cwd=PROJECT_ROOT)
    return completed


def _stable_bindings(**results: str) -> dict[str, str]:
    """Every expression release.yaml's gate step resolves, with results overridable."""
    defaults = {
        "publish-image": "success",
        "publish-package-forge": "success",
        "publish-package-pypi": "success",
        "verify": "success",
    }
    defaults.update(results)
    return {f"needs.{job}.result": result for job, result in defaults.items()} | {
        "needs.plan.outputs.enabled-destinations": json.dumps(
            {
                "image-forge": "enabled",
                "image-dockerhub": "disabled",
                "package-forge": "unsupported",
                "package-pypi": "enabled",
            }
        )
    }


def test_a_disabled_optional_destination_still_finalizes() -> None:
    """ADR-0011's first mandatory anchor.

    Docker Hub off by toggle and the forge index absent by host capability: both report
    `skipped`, both are legitimate, and a release with either of them off must still get
    its Release and its aliases. The literal reading of "a required failure or skip
    blocks" would leave that release green with nothing finalized and nothing reported,
    which is the failure nobody notices until they look for the Release.
    """
    completed = _run_gate(
        RELEASE_WORKFLOW,
        _stable_bindings(**{"publish-package-forge": "skipped"}),
    )
    assert completed.returncode == 0, completed.stderr


def test_an_enabled_destination_that_skipped_stops_finalization() -> None:
    """ADR-0011's second mandatory anchor, and the one the first makes possible to get
    wrong: `skipped` is also what a job reports when its upstream died, so ignoring
    every skip would advance `latest` over a release whose PyPI upload never happened."""
    completed = _run_gate(
        RELEASE_WORKFLOW, _stable_bindings(**{"publish-package-pypi": "skipped"})
    )
    assert completed.returncode != 0
    assert "package-pypi" in completed.stderr


@pytest.mark.parametrize("blocking", ["failure", "cancelled"])
def test_a_failed_or_cancelled_publisher_stops_finalization(blocking: str) -> None:
    completed = _run_gate(
        RELEASE_WORKFLOW, _stable_bindings(**{"publish-image": blocking})
    )
    assert completed.returncode != 0
    assert "image-forge" in completed.stderr


def test_a_failed_verifier_stops_finalization_whatever_the_destinations_did() -> None:
    completed = _run_gate(RELEASE_WORKFLOW, _stable_bindings(verify="failure"))
    assert completed.returncode != 0
    assert "verify" in completed.stderr


def test_the_development_gate_reads_its_own_channels_destinations() -> None:
    """The same module, a different enabled set -- and the pair registry is why that is
    safe: `finalize` in dev.yaml would have been granted by a bare-name registry."""
    bindings = {
        "needs.publish-image.result": "success",
        "needs.publish-package-forge.result": "success",
        "needs.publish-package-testpypi.result": "skipped",
        "needs.verify.result": "success",
        "needs.stable-tag-guard.result": "success",
        "needs.plan.outputs.enabled-destinations": json.dumps(
            {
                "image-forge": "enabled",
                "package-forge": "unsupported",
                "package-testpypi": "disabled",
            }
        ),
    }
    completed = _run_gate(DEV_WORKFLOW, bindings)
    assert completed.returncode == 0, completed.stderr
    bindings["needs.plan.outputs.enabled-destinations"] = json.dumps(
        {
            "image-forge": "enabled",
            "package-forge": "unsupported",
            "package-testpypi": "enabled",
        }
    )
    completed = _run_gate(DEV_WORKFLOW, bindings)
    assert completed.returncode != 0
    assert "package-testpypi" in completed.stderr


@pytest.fixture
def alias_repository(tmp_path: Path) -> Path:
    """A repository whose tag set makes every ordering decision distinguishable.

    Real git, and real annotated tags, because git's own version comparison is the
    ordering authority the workflow delegates to. `v1.2.10` is here so a lexicographic
    sort -- what a hand-rolled comparison degrades to -- gives a different answer from
    the correct one.
    """
    root = tmp_path / "ordered"
    root.mkdir()
    _git(root, "init", "--initial-branch=main")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "Test")
    for index, tags in enumerate(
        [
            ("v1.2.3",),
            ("v1.2.10",),
            ("v1.3.0",),
            ("v1.4.0-rc1", "v9.9.9-lightweight", "v1.2", "1.2.3"),
        ]
    ):
        (root / "file.txt").write_text(f"{index}\n", encoding="utf-8")
        _git(root, "add", ".")
        _git(root, "commit", "-m", f"commit {index}")
        for tag in tags:
            if tag.endswith("-lightweight"):
                _git(root, "tag", tag)
            else:
                _git(root, "tag", "-a", tag, "-m", tag)
    # An annotated stable tag on history the protected default branch never took. It is
    # the greatest tag in the repository and must count for nothing: without the
    # `--merged` scope every release after it becomes the *second* greatest, so `vMAJOR`
    # and `latest` stop advancing while every run still finishes green. Every ordering
    # expectation below is therefore also a scope attack on that scoping.
    _git(root, "checkout", "-b", "abandoned")
    (root / "file.txt").write_text("abandoned\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "abandoned")
    _git(root, "tag", "-a", "v9.0.0", "-m", "v9.0.0")
    _git(root, "checkout", "main")
    return root


@pytest.fixture
def major_boundary_repository(tmp_path: Path) -> Path:
    """`v1.2.3`, `v1.20.0`, `v2.0.0` -- the two cases prefix arithmetic gets wrong.

    `v1.2.` must not prefix `v1.20.0` (or a patch release would think a neighbouring
    minor superseded it), and the first release of a new major is greatest within a
    `MAJOR.MINOR` that contains only itself.
    """
    root = tmp_path / "boundary"
    root.mkdir()
    _git(root, "init", "--initial-branch=main")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "Test")
    for index, tag in enumerate(["v1.2.3", "v1.20.0", "v2.0.0"]):
        (root / "file.txt").write_text(f"{index}\n", encoding="utf-8")
        _git(root, "add", ".")
        _git(root, "commit", "-m", f"commit {index}")
        _git(root, "tag", "-a", tag, "-m", tag)
    return root


def _alias_plan(
    repository: Path, tag: str, branch: str = "main"
) -> tuple[Any, dict[str, str]]:
    step = _step_with_id(RELEASE_WORKFLOW, "aliases")
    commit = _git(repository, "rev-parse", f"{tag}^{{commit}}")
    return _run_step(
        str(step["run"]),
        {
            "DEFAULT_BRANCH_REF": branch,
            "RELEASE_TAG": tag,
            "SOURCE_SHA": commit,
        },
        cwd=repository,
    )


def test_the_newest_stable_release_advances_both_aliases(
    alias_repository: Path,
) -> None:
    completed, emitted = _alias_plan(alias_repository, "v1.3.0")
    assert completed.returncode == 0, completed.stderr
    assert emitted["advance-major"] == "true"
    assert emitted["advance-minor"] == "true"
    assert emitted["major-alias"] == "v1"
    assert emitted["minor-alias"] == "v1.3"


def test_a_back_port_patch_never_drags_the_major_alias_backwards(
    alias_repository: Path,
) -> None:
    """Gate finding F4, executed rather than described.

    `git-action-tag-floating-version` moves an alias unconditionally: hand it `v1.2.10`
    with `v1.3.0` already published and `v1` follows it backwards. The refusal has to
    come from the workflow, and the workflow's authority is the Git tag set alone.

    `v1.2.10` is also the case a lexicographic comparison gets wrong in the *other*
    direction -- it sorts below `v1.2.3` -- so this asserts the minor alias may still
    advance, not only that the major may not.
    """
    completed, emitted = _alias_plan(alias_repository, "v1.2.10")
    assert completed.returncode == 0, completed.stderr
    assert emitted["advance-major"] == "false"
    assert emitted["advance-minor"] == "true"
    assert emitted["greatest-stable"] == "v1.3.0"


def test_a_superseded_patch_advances_nothing(alias_repository: Path) -> None:
    completed, emitted = _alias_plan(alias_repository, "v1.2.3")
    assert completed.returncode == 0, completed.stderr
    assert emitted["advance-major"] == "false"
    assert emitted["advance-minor"] == "false"


@pytest.mark.parametrize("tag", ["v1.4.0-rc1", "v9.9.9-lightweight", "v1.2", "1.2.3"])
def test_no_alias_plan_exists_for_a_tag_that_is_not_an_exact_stable_release(
    alias_repository: Path, tag: str
) -> None:
    """A prerelease, a lightweight tag, a two-part tag and an unprefixed one. The action
    skips prereleases itself; every other shape has to be refused here, and refusing is
    the same operation as refusing an ordering violation -- the step exits non-zero and
    `set -e` stops the job before any alias is touched."""
    completed, _ = _alias_plan(alias_repository, tag)
    assert completed.returncode != 0


def _stub_docker(tmp_path: Path) -> tuple[Path, Path]:
    """A `docker` on PATH that records its arguments instead of contacting a registry."""
    directory = tmp_path / "bin"
    directory.mkdir()
    log = tmp_path / "docker.log"
    stub = directory / "docker"
    stub.write_text(
        f'#!/usr/bin/env bash\nprintf "%s\\n" "$*" >> "{log}"\n', encoding="utf-8"
    )
    stub.chmod(0o755)
    return directory, log


def _run_alias_step(
    path: Path, tmp_path: Path, **environment: str
) -> tuple[Any, list[str]]:
    directory, log = _stub_docker(tmp_path)
    summary = tmp_path / "summary.md"
    summary.touch()
    step = _step_with_id(path, "image-alias")
    completed, _ = _run_step(
        str(step["run"]),
        {
            "PATH": f"{directory}:{os.environ['PATH']}",
            "GITHUB_STEP_SUMMARY": str(summary),
            **environment,
        },
        cwd=tmp_path,
    )
    invocations = log.read_text(encoding="utf-8").splitlines() if log.exists() else []
    return completed, invocations


DIGEST = "sha256:" + "ab" * 32


def _moved(invocations: list[str]) -> set[str]:
    """Every reference the alias step actually named, across every invocation."""
    arguments = " ".join(invocations).split()
    return {
        arguments[index + 1]
        for index, token in enumerate(arguments)
        if token == "--tag"
    }


@pytest.mark.parametrize("workflow", [RELEASE_WORKFLOW, DEV_WORKFLOW])
@pytest.mark.parametrize("digest", ["", "latest", "sha256:short", DIGEST[:-1] + "z"])
def test_an_absent_or_malformed_digest_halts_before_any_name_moves(
    workflow: Path, tmp_path: Path, digest: str
) -> None:
    """The alias step is handed the publisher's `digest` output. When the publisher was
    skipped that output is the empty string, and `repo@` with nothing after it is either
    an obscure failure or -- if anything ever coerces it back to a tag -- a copy of
    whatever `repo:` resolves to. Halting is the only safe reading."""
    completed, invocations = _run_alias_step(
        workflow,
        tmp_path,
        ADVANCE_MAJOR="true",
        ADVANCE_MINOR="true",
        DOCKERHUB_REPOSITORY="",
        IMAGE_DIGEST=digest,
        IMAGE_REPOSITORY="ghcr.io/owner/name",
        MAJOR_ALIAS="v1",
        MINOR_ALIAS="v1.3",
    )
    assert completed.returncode != 0, completed.stdout
    assert not invocations, f"a name was moved onto {digest!r}"


def test_a_stable_alias_step_moves_only_the_names_the_tag_set_permits(
    tmp_path: Path,
) -> None:
    completed, invocations = _run_alias_step(
        RELEASE_WORKFLOW,
        tmp_path,
        ADVANCE_MAJOR="false",
        ADVANCE_MINOR="true",
        DOCKERHUB_REPOSITORY="docker.io/owner/name",
        IMAGE_DIGEST=DIGEST,
        IMAGE_REPOSITORY="ghcr.io/owner/name",
        MAJOR_ALIAS="v1",
        MINOR_ALIAS="v1.2",
    )
    assert completed.returncode == 0, completed.stderr
    assert _moved(invocations) == {
        "ghcr.io/owner/name:1.2",
        "docker.io/owner/name:1.2",
    }
    assert all("imagetools create" in line for line in invocations)
    assert all("@" + DIGEST in line for line in invocations)


def test_the_stable_alias_step_moves_latest_only_with_the_major(tmp_path: Path) -> None:
    completed, invocations = _run_alias_step(
        RELEASE_WORKFLOW,
        tmp_path,
        ADVANCE_MAJOR="true",
        ADVANCE_MINOR="true",
        DOCKERHUB_REPOSITORY="",
        IMAGE_DIGEST=DIGEST,
        IMAGE_REPOSITORY="ghcr.io/owner/name",
        MAJOR_ALIAS="v1",
        MINOR_ALIAS="v1.3",
    )
    assert completed.returncode == 0, completed.stderr
    assert _moved(invocations) == {
        "ghcr.io/owner/name:1.3",
        "ghcr.io/owner/name:1",
        "ghcr.io/owner/name:latest",
    }
    # `latest` and `MAJOR` mean the same thing, so they must not be two writes that can
    # disagree: one repository, one `imagetools create`.
    assert len(invocations) == 1, invocations


def test_a_superseded_release_moves_no_image_alias_at_all(tmp_path: Path) -> None:
    completed, invocations = _run_alias_step(
        RELEASE_WORKFLOW,
        tmp_path,
        ADVANCE_MAJOR="false",
        ADVANCE_MINOR="false",
        DOCKERHUB_REPOSITORY="docker.io/owner/name",
        IMAGE_DIGEST=DIGEST,
        IMAGE_REPOSITORY="ghcr.io/owner/name",
        MAJOR_ALIAS="v1",
        MINOR_ALIAS="v1.2",
    )
    assert completed.returncode == 0, completed.stderr
    assert not invocations


def test_a_disabled_docker_hub_receives_no_alias_request(tmp_path: Path) -> None:
    """The credentials half is gated on the enabled set; this is the requests half. An
    alias pushed at a destination the run declared disabled is a request to a registry
    it never logged into."""
    completed, invocations = _run_alias_step(
        RELEASE_WORKFLOW,
        tmp_path,
        ADVANCE_MAJOR="true",
        ADVANCE_MINOR="true",
        DOCKERHUB_REPOSITORY="",
        IMAGE_DIGEST=DIGEST,
        IMAGE_REPOSITORY="ghcr.io/owner/name",
        MAJOR_ALIAS="v1",
        MINOR_ALIAS="v1.3",
    )
    assert completed.returncode == 0, completed.stderr
    assert not any("docker.io" in line for line in invocations)


def test_a_stale_development_candidate_halts_without_moving_dev(
    tmp_path: Path, alias_repository: Path
) -> None:
    """The just-in-time head re-read. Concurrency cancels a superseded run, but the
    cancellation is not instantaneous and the push events are unordered, so the head is
    proven again immediately before the alias moves."""
    step = _step_with_id(DEV_WORKFLOW, "recheck-head")
    summary = tmp_path / "summary.md"
    summary.touch()
    head = _git(alias_repository, "rev-parse", "HEAD")
    stale = _git(alias_repository, "rev-parse", "HEAD~1")

    completed, _ = _run_step(
        str(step["run"]),
        {"GITHUB_STEP_SUMMARY": str(summary), "SOURCE_SHA": head},
        cwd=alias_repository,
    )
    assert completed.returncode == 0, completed.stderr

    completed, _ = _run_step(
        str(step["run"]),
        {"GITHUB_STEP_SUMMARY": str(summary), "SOURCE_SHA": stale},
        cwd=alias_repository,
    )
    assert completed.returncode != 0
    assert "no longer the head" in completed.stderr


def test_the_git_alias_action_runs_only_behind_the_ordering_gate() -> None:
    """F4's wiring half, which the behavioural tests above cannot see.

    They prove the ordering decision is correct. Nothing yet proved the action is
    actually *gated* on it -- and the action moves unconditionally, so an alias step
    that stopped consulting the decision would pass every ordering test in this file
    while dragging `vMAJOR` backwards on the next back-port release.

    The deciding step is found by the flag it passes, never by a step name, and the
    condition must name that step's own output.
    """
    examined = 0
    for path in sorted(WORKFLOWS.glob("*.yaml")):
        for job_name, job in _jobs(_load_workflow(path)).items():
            steps = job.get("steps", []) or []
            deciders = {
                str(step["id"])
                for step in steps
                if step.get("id")
                and ALIAS_ORDER_MARKER in _uncommented(str(step.get("run", "")))
            }
            for step in steps:
                if not str(step.get("uses", "")).startswith(APPROVED_ALIAS_ACTION):
                    continue
                examined += 1
                assert deciders, (
                    f"{path.name}: job {job_name!r} moves Git aliases without deciding "
                    f"from the tag set whether they may advance. The action compares "
                    f"nothing; the refusal is the workflow's (F4)."
                )
                condition = str(step.get("if", "")).replace(" ", "")
                assert any(
                    f"steps.{decider}.outputs.advance-major" in condition
                    for decider in deciders
                ), (
                    f"{path.name}: job {job_name!r} runs {APPROVED_ALIAS_ACTION} without "
                    f"gating on the ordering decision ({sorted(deciders)}); releasing an "
                    f"older patch would drag the major alias backwards (F4)"
                )
                inputs = step.get("with") or {}
                # The action's own input spelling AT `@v2`, which renamed every one of
                # them. The camelCase pair `@v1` took -- `updateMinor`,
                # `ignorePrerelease` -- is not an input here at all: Actions passes an
                # undeclared input through as an unread `INPUT_*` variable, the action
                # falls back to its defaults, and `update-minor` defaults to `false`.
                # The visible result is a `vMAJOR.MINOR` alias that silently never
                # moves. That camelCase pair is this guard's planted violation.
                assert inputs.get("update-minor") == "true", (
                    f"{path.name}: {job_name!r} does not ask for the minor alias"
                )
                assert inputs.get("ignore-prerelease") == "true", (
                    f"{path.name}: {job_name!r} does not skip prereleases"
                )
                assert not (
                    set(inputs) & {"updateMinor", "ignorePrerelease", "refTag"}
                ), (
                    f"{path.name}: {job_name!r} passes the camelCase inputs of "
                    f"`{APPROVED_ALIAS_ACTION}@v1`; at `@v2` those are undeclared, "
                    f"silently ignored, and `update-minor` then defaults to false"
                )
                # And its OUTPUT names, for the same reason the inputs are asserted:
                # `@v2` renamed those too, and a wrong one renders `none` in the summary
                # on a fully successful move -- the same silent failure the input
                # spelling would have caused, one step further on.
                consumed = json.dumps(_jobs(_load_workflow(path))[job_name])
                for output in ("major-tag", "minor-tag"):
                    assert f"steps.{step['id']}.outputs.{output}" in consumed, (
                        f"{path.name}: {job_name!r} never reads the alias action's "
                        f"{output!r} output, so a successful move is reported as none"
                    )
    assert examined, "no workflow moves a Git alias; this guard examined nothing"


def test_the_release_carries_the_whole_verified_bundle_and_is_traceable(
    tmp_path: Path,
) -> None:
    """ADR-0010 and CI-AR41.

    Four files, because two of them are what makes the other two checkable: the wheel
    and the sdist are the distributions, `SHA256SUMS` and `build-manifest.json` are how
    someone reading the Release proves the attached wheel is the one the verifier saw.

    Every path is resolved through the revalidated bundle's own step -- found by the
    action it calls, not by a hand-kept step name -- so attaching a distribution from
    anywhere else fails here. And the Release's identity outputs must reach the run
    summary: a Release nobody can find from the run is evidence that does not exist.
    """
    examined = 0
    for path in sorted(WORKFLOWS.glob("*.yaml")):
        document = _load_workflow(path)
        for job_name, job in _jobs(document).items():
            steps = job.get("steps", []) or []
            release_steps = [
                step
                for step in steps
                if str(step.get("uses", "")).startswith(APPROVED_RELEASE_ACTION)
            ]
            if not release_steps:
                continue
            assert len(release_steps) == 1, f"{path.name}: {job_name!r} releases twice"
            step = release_steps[0]
            examined += 1
            assert str(step["uses"]).endswith("@v2"), (
                f"{path.name}: {APPROVED_RELEASE_ACTION} must be pinned @v2; @v2.0 is "
                f"stale and a patch tag forfeits the floating-major guarantee (ADR-0010)"
            )
            bundle = next(
                (
                    str(candidate["id"])
                    for candidate in steps
                    if str(candidate.get("uses", "")).endswith("/verified-bundle")
                    and candidate.get("id")
                ),
                None,
            )
            assert bundle, (
                f"{path.name}: {job_name!r} attaches a Release without revalidating the "
                f"bundle first, so the distributions were never proven to be the ones "
                f"the verifier saw"
            )
            artifacts = str((step.get("with") or {}).get("artifacts", ""))
            attached = [
                entry.strip() for entry in artifacts.split(",") if entry.strip()
            ]
            for required in (
                f"steps.{bundle}.outputs.wheel-filename",
                f"steps.{bundle}.outputs.sdist-filename",
                "SHA256SUMS",
                "build-manifest.json",
            ):
                assert any(required in entry for entry in attached), (
                    f"{path.name}: the Release does not attach {required!r}; the "
                    f"evidence half of the bundle is what makes the distributions "
                    f"checkable (ADR-0010, CI-AR41)"
                )
            # Every entry, not merely one of them: a wheel taken from `dist/` beside a
            # bundle-path sdist satisfies "the bundle appears somewhere" while shipping
            # a distribution the revalidation never saw.
            for entry in attached:
                assert f"steps.{bundle}.outputs.bundle-path" in entry, (
                    f"{path.name}: the Release attaches {entry!r} from outside the "
                    f"revalidated bundle"
                )

            # Recorded twice, because the two readers are different: the job output is
            # what the aggregator surfaces, and the step `env:` is what reaches this
            # job's own summary. Asserting only that the expression appears *somewhere*
            # in the file lets the summary row degrade to a literal while the job output
            # keeps the guard green -- which is exactly what the planted violation did.
            job_outputs = json.dumps(job.get("outputs") or {})
            step_environments = json.dumps(
                [candidate.get("env") or {} for candidate in steps]
            )
            for output in ("html-url", "assets"):
                reference = f"steps.{step['id']}.outputs.{output}"
                assert reference in job_outputs, (
                    f"{path.name}: the Release's {output!r} is not a job output, so the "
                    f"run aggregator cannot report it (CI-AR41)"
                )
                assert reference in step_environments, (
                    f"{path.name}: the Release's {output!r} never reaches this job's "
                    f"run summary (CI-AR41)"
                )
            # And the alias outcome beside it: a run that moved nothing and a run that
            # moved everything must not look the same in the summary.
            decider = next(
                (
                    str(candidate["id"])
                    for candidate in steps
                    if candidate.get("id")
                    and ALIAS_ORDER_MARKER
                    in _uncommented(str(candidate.get("run", "")))
                ),
                None,
            )
            assert decider, (
                f"{path.name}: {job_name!r} creates a Release without deciding which "
                f"aliases the tag set permits, so the run summary cannot say what "
                f"moved (F4, CI-AR41)"
            )
            summaries = "\n".join(
                _uncommented(str(candidate.get("run", ""))) for candidate in steps
            )
            assert "GITHUB_STEP_SUMMARY" in summaries, (
                f"{path.name}: {job_name!r} writes no run summary"
            )
            for advance in ("advance-major", "advance-minor"):
                reference = f"steps.{decider}.outputs.{advance}"
                assert reference in step_environments, (
                    f"{path.name}: {job_name!r} never records {advance!r}, so a release "
                    f"that moved no alias reads exactly like one that moved every alias"
                )
                assert reference in job_outputs, (
                    f"{path.name}: {advance!r} is not a job output, so the image alias "
                    f"job cannot consume the same decision (F4)"
                )
    assert examined, "no workflow creates a Release; this guard examined nothing"


def test_every_refusal_a_finalizer_makes_precedes_everything_it_writes() -> None:
    """The story's central invariant, and the one every other finalizer guard assumed.

    Each of the four refusals -- the enabled-set gate, the `vX.Y.Z` immutability
    re-check, the alias-ordering decision, the development channel's just-in-time head
    proof -- is asserted *present* elsewhere, and its behaviour is executed. Nothing
    asserted it runs **first**. Moving the gate step to the end of `finalize` left every
    guard green while a release with an enabled destination missing would get its
    Release, its `vMAJOR`, its `latest` and its `dev`, and only then go red: strictly
    worse than not gating at all, because the run is now half-finalized and the Release
    has to be deleted by hand before it can be retried.

    Both sets are derived -- writes from the approved actions and the alias commands,
    refusals from the mechanisms that perform them -- so a new way to write, or a new
    refusal, is ordered by this guard without an edit here.
    """
    examined = 0
    for path in sorted(WORKFLOWS.glob("*.yaml")):
        for job_name in sorted(_finalizers(path)):
            job = _jobs(_load_workflow(path))[job_name]
            writes = _writing_steps(job)
            if not writes:
                continue
            examined += 1
            refusals = _refusing_steps(job)
            assert refusals, (
                f"{path.name}: finalizer {job_name!r} writes without refusing anything "
                f"first; the gate, the tag re-check and the ordering decision are what "
                f"make the write conditional"
            )
            assert max(refusals) < min(writes), (
                f"{path.name}: finalizer {job_name!r} performs a refusal at step "
                f"{max(refusals)} but has already written at step {min(writes)}. A "
                f"refusal after the write reports the damage instead of preventing it."
            )
    assert examined, "no finalizer writes anything; this guard examined nothing"


def test_a_finalizer_never_leaves_a_credential_in_the_workspace() -> None:
    """`persist-credentials: false` is a repository-wide invariant, and a job that needs
    to push has to supply the credential some other way. Writing it into `.git/config`
    -- a remote URL carrying userinfo, or an `http.*.extraheader` -- defeats the
    invariant rather than working within it: the token then outlives the step that
    needed it, and on the reused `act_runner` workspace E009 targets it outlives the
    job. git's own `GIT_CONFIG_COUNT`/`KEY`/`VALUE` protocol scopes it to one process
    environment, which is what a job-scoped grant means.
    """
    persisted = (
        r"git\s+remote\s+(?:set-url|add)[^\n]*\$\{?[A-Za-z_]*(?:TOKEN|PASSWORD)",
        r"git\s+config[^\n]*extraheader",
        r"credential\.helper\s+store",
    )
    for path in sorted(WORKFLOWS.glob("*.yaml")):
        for job_name, job in _jobs(_load_workflow(path)).items():
            for step in job.get("steps", []) or []:
                command = _uncommented(str(step.get("run", "")))
                for pattern in persisted:
                    assert not re.search(pattern, command), (
                        f"{path.name}: job {job_name!r} writes a credential into the "
                        f"workspace's git configuration, where it outlives the step "
                        f"that needed it. Pass it through GIT_CONFIG_* on the step "
                        f"instead."
                    )


def test_a_disabled_docker_hub_is_addressed_by_no_alias_step() -> None:
    """CI-AR40's "no credentials **or requests**", at the second place it now has to
    hold.

    `test_a_disabled_docker_hub_receives_no_alias_request` executes the bash with an
    empty repository supplied by the test, which proves the bash copes -- not that the
    workflow ever produces an empty value. Deleting the login step's `if:`, or making
    the `DOCKERHUB_REPOSITORY` expression unconditional, left every guard green; the
    runtime was safe only because the plan job happens to emit an empty
    `dockerhub-repository` when the toggle is off, which is two independently-edited
    derivations agreeing by luck.

    The step set is derived -- anything mentioning Docker Hub in a job that moves an
    alias -- so a third way of addressing that destination is covered without an edit.
    """
    examined = 0
    for path, job_name in sorted(_alias_moving_jobs()):
        job = _jobs(_load_workflow(WORKFLOWS / path))[job_name]
        for step in job.get("steps", []) or []:
            body = json.dumps({k: v for k, v in step.items() if k != "run"})
            if not re.search(r"docker\.io|DOCKERHUB", body):
                continue
            examined += 1
            condition = str(step.get("if", ""))
            assert (
                "enabled-destinations" in condition or "enabled-destinations" in body
            ), (
                f"{path}: job {job_name!r} addresses Docker Hub from a step that never "
                f"consults the enabled set, so a run with the destination disabled "
                f"would still send it credentials or requests (CI-AR40, ADR-0011)"
            )
    assert examined, "no alias step addresses Docker Hub; this guard examined nothing"


def test_a_failing_registry_write_still_reports_which_names_moved(
    tmp_path: Path,
) -> None:
    """H2: `set -e` aborts the step at the first failing `imagetools create`, and a
    summary written after the loop is then written never -- leaving a partially aliased
    registry with no record of which names moved, in exactly the situation an operator
    needs that record to reconcile by hand (CI-AR41)."""
    directory = tmp_path / "bin"
    directory.mkdir()
    log = tmp_path / "docker.log"
    stub = directory / "docker"
    # Succeeds for the forge registry, fails for Docker Hub: the ordinary transient
    # registry error, half way through the fan-out.
    stub.write_text(
        "#!/usr/bin/env bash\n"
        f'printf "%s\\n" "$*" >> "{log}"\n'
        'case "$*" in *docker.io*) exit 1 ;; esac\n',
        encoding="utf-8",
    )
    stub.chmod(0o755)
    summary = tmp_path / "summary.md"
    summary.touch()
    step = _step_with_id(RELEASE_WORKFLOW, "image-alias")
    completed, _ = _run_step(
        str(step["run"]),
        {
            "PATH": f"{directory}:{os.environ['PATH']}",
            "GITHUB_STEP_SUMMARY": str(summary),
            "ADVANCE_MAJOR": "true",
            "ADVANCE_MINOR": "true",
            "DOCKERHUB_REPOSITORY": "docker.io/owner/name",
            "IMAGE_DIGEST": DIGEST,
            "IMAGE_REPOSITORY": "ghcr.io/owner/name",
            "MAJOR_ALIAS": "v1",
            "MINOR_ALIAS": "v1.3",
        },
        cwd=tmp_path,
    )
    assert completed.returncode != 0, "a failing registry write finished green"
    rendered = summary.read_text(encoding="utf-8")
    assert "ghcr.io/owner/name:latest" in rendered, (
        f"the aliases that DID move are unreported: {rendered!r}"
    )
    assert "docker.io/owner/name" not in rendered, (
        "an alias that failed is reported as moved"
    )


def test_the_release_is_idempotent_for_the_identity_it_already_created() -> None:
    """M3: the Release is the FIRST irreversible write and every alias move comes after
    it, so the one step that cannot be retried is the one that runs first.

    With `allow-updates: false` a re-run of the finalizer -- after a transient registry
    error, an expired token, anything at all in the alias fan-out -- dies at the Release
    step, and the operator has to delete the Release from the forge UI before the run
    can be resumed. Updating is safe for this identity and only this one:
    `refs/tags/vX.Y.Z` is immutable (ADR-0006) and the step immediately before re-proves
    that the tag still peels to this commit, so a second run of this job is the same
    release by construction rather than a different one wearing the same name.
    """
    examined = 0
    for path in sorted(WORKFLOWS.glob("*.yaml")):
        for job_name, job in _jobs(_load_workflow(path)).items():
            for step in job.get("steps", []) or []:
                if not str(step.get("uses", "")).startswith(APPROVED_RELEASE_ACTION):
                    continue
                examined += 1
                inputs = step.get("with") or {}
                assert inputs.get("allow-updates") == "true", (
                    f"{path.name}: {job_name!r} cannot re-create the Release for an "
                    f"identity it already published, so any failure in the alias moves "
                    f"that follow strands the run until someone deletes the Release by "
                    f"hand (ADR-0006)"
                )
                # Idempotent is not the same as permissive: the identity re-check has to
                # still be in front of it, or "update the existing Release" becomes
                # "overwrite whatever is at that tag now".
                refusals = _refusing_steps(job)
                writes = _writing_steps(job)
                assert refusals and max(refusals) < min(writes), (
                    f"{path.name}: {job_name!r} updates an existing Release without "
                    f"re-proving the tag still names this commit first"
                )
    assert examined, "no workflow creates a Release; this guard examined nothing"


# ---------------------------------------------------------------------------
# The annotated-stable-tag relation, and the finalization gate, as workflow steps
# (story E008-S01-003, maintainer directive: no Python modules).
#
# Both used to be modules with their own pytest files. The properties those files
# proved are proven here instead, by EXECUTING the real `run:` bodies against real
# git and real `jq` -- which is strictly stronger, because a module test proves the
# module and this proves what the workflow actually runs.
# ---------------------------------------------------------------------------


def _membership_steps(path: Path) -> dict[str, list[str]]:
    """Every step deciding annotated-stable-tag membership, split by what it does.

    Located by the mechanism (`%(objecttype)`), never by a step name or an `id:`: a
    re-check whose body was gutted stops being found, and the count assertions below
    then fail loudly rather than examining nothing. `emitters` publish the conclusion
    as a step output; `refusers` exit non-zero instead.
    """
    found: dict[str, list[str]] = {"emitters": [], "refusers": []}
    for job in _jobs(_load_workflow(path)).values():
        for step in job.get("steps") or []:
            body = _uncommented(str(step.get("run", "")))
            if TAG_MEMBERSHIP_MARKER not in body:
                continue
            found["emitters" if "GITHUB_OUTPUT" in body else "refusers"].append(body)
    return found


def test_every_stable_tag_recheck_is_the_same_body() -> None:
    """One relation, copied into four steps, asserted to be one copy.

    The stable channel re-reads the tag immediately before each irreversible act: the
    two package uploads, the Release, and the image aliases. Duplication is the price
    of keeping the decision in the workflow -- so the guard is that the copies cannot
    diverge. A single edited copy fails here rather than reaching a registry.
    """
    refusers = _membership_steps(RELEASE_WORKFLOW)["refusers"]
    assert len(refusers) == 4, (
        f"release.yaml has {len(refusers)} pre-write tag re-checks; expected one before "
        f"each irreversible act (both uploads, the Release, the image aliases)"
    )
    assert len(set(refusers)) == 1, "the stable tag re-checks have diverged"
    assert all(STABLE_RECHECK_MARKER in body for body in refusers)


def test_every_suppression_recheck_is_the_same_body() -> None:
    """The development channel's copies of the same relation, under the same rule."""
    steps = _membership_steps(DEV_WORKFLOW)
    assert len(steps["emitters"]) == 1, "the suppression conclusion has one producer"
    assert len(steps["refusers"]) == 3, (
        f"dev.yaml has {len(steps['refusers'])} pre-write suppression re-checks; "
        f"expected one before each of the two uploads and the `dev` alias move"
    )
    assert len(set(steps["refusers"])) == 1, "the suppression re-checks have diverged"


def _run_stable_recheck(repository: Path, tag: str, commit: str | None = None) -> Any:
    body = _membership_steps(RELEASE_WORKFLOW)["refusers"][0]
    completed, _ = _run_step(
        body,
        {
            "RELEASE_TAG": tag,
            "SOURCE_SHA": commit or _git(repository, "rev-parse", "HEAD"),
        },
        cwd=repository,
    )
    return completed


def test_the_stable_recheck_accepts_the_annotated_tag_that_names_the_commit(
    tagged_repository: Path,
) -> None:
    completed = _run_stable_recheck(tagged_repository, "v1.2.3")
    assert completed.returncode == 0, completed.stderr


@pytest.mark.parametrize(
    ("tag", "reason"),
    [
        ("v9.9.9", "a lightweight tag of the right name is not the release identity"),
        ("v1.2", "a floating alias is not an exact version"),
        ("v1.2.3-rc1", "a prerelease is not a stable release"),
        ("1.2.3", "the stable spelling carries the v prefix"),
        ("v01.2.3", "a zero-padded component is malformed"),
        ("v1.2.3.4", "a fourth component is not the release spelling"),
        ("release-1.2.3", "a prefixed name is not the release spelling"),
        ("v0.9.0", "this tag peels to another commit"),
        ("v4.5.6", "this tag does not exist at all"),
    ],
)
def test_the_stable_recheck_refuses_anything_that_is_not_that_tag(
    tagged_repository: Path, tag: str, reason: str
) -> None:
    """The pre-upload refusal, run against real git rather than described.

    `v9.9.9` is the anchor the maintainer named: it is spelled exactly right and it
    peels to exactly this commit, and it is refused solely because it is lightweight.
    Dropping the `%(objecttype)` filter makes this case pass and this test fail --
    which is the release-breaking defect story 002 recorded as HIGH-1.
    """
    completed = _run_stable_recheck(tagged_repository, tag)
    assert completed.returncode != 0, f"{tag} was accepted, but {reason}"


def _run_suppression_guard(repository: Path, commit: str) -> tuple[Any, dict[str, str]]:
    body = _membership_steps(DEV_WORKFLOW)["emitters"][0]
    return _run_step(body, {"SOURCE_SHA": commit}, cwd=repository)


def test_only_an_annotated_exact_stable_tag_suppresses_development(
    tagged_repository: Path,
) -> None:
    """Every rejection in one execution, because the commit carries every shape.

    On this commit sit `v1.2.3` (annotated, exact), `v9.9.9` (exact but lightweight),
    `v1.2`, `v1.2.3-rc1`, `1.2.3` and `v01.2.3` (annotated, wrong spelling). Only the
    first may suppress a development publication, and the emitted list says which did.
    Deleting the annotated-object filter adds `v9.9.9`; loosening the spelling adds the
    rest; each fails here.
    """
    head = _git(tagged_repository, "rev-parse", "HEAD")
    completed, emitted = _run_suppression_guard(tagged_repository, head)
    assert completed.returncode == 0, completed.stderr
    assert emitted["suppressed"] == "true"
    assert emitted["stable-tags"] == "v1.2.3"


def test_a_stable_tag_on_an_ancestor_does_not_suppress_the_new_head(
    tagged_repository: Path,
) -> None:
    """The peel is compared to THIS commit, not asked "is a release in my history".

    Every commit after a release has a release in its history, so the reachability
    reading would suppress every development publication this project ever makes.
    """
    (tagged_repository / "file.txt").write_text("three\n", encoding="utf-8")
    _git(tagged_repository, "add", ".")
    _git(tagged_repository, "commit", "-m", "three")
    head = _git(tagged_repository, "rev-parse", "HEAD")
    completed, emitted = _run_suppression_guard(tagged_repository, head)
    assert completed.returncode == 0, completed.stderr
    assert emitted["suppressed"] == "false"
    assert emitted["stable-tags"] == ""


def test_the_suppression_recheck_refuses_a_tag_that_landed_after_the_guard(
    tagged_repository: Path,
) -> None:
    """F16's cheap hardening, executed: the window is narrowed, and the refusal is real.

    The guard job answered before the verifier finished. A tag that lands afterwards
    must stop the upload, because an immutable `X.Y.Z.devN` published for a release
    commit cannot be withdrawn.
    """
    body = _membership_steps(DEV_WORKFLOW)["refusers"][0]
    head = _git(tagged_repository, "rev-parse", "HEAD")
    completed, _ = _run_step(body, {"SOURCE_SHA": head}, cwd=tagged_repository)
    assert completed.returncode != 0
    assert "v1.2.3" in completed.stderr

    (tagged_repository / "file.txt").write_text("four\n", encoding="utf-8")
    _git(tagged_repository, "add", ".")
    _git(tagged_repository, "commit", "-m", "four")
    untagged = _git(tagged_repository, "rev-parse", "HEAD")
    completed, _ = _run_step(body, {"SOURCE_SHA": untagged}, cwd=tagged_repository)
    assert completed.returncode == 0, completed.stderr


def test_a_release_that_never_reached_the_default_branch_has_no_alias_plan(
    alias_repository: Path,
) -> None:
    """`v9.0.0` is annotated, exactly spelled, and the greatest tag in the repository.

    It is still not a release this project made: it sits on history the protected
    default branch never took. `--merged` is both the reachability answer and the
    membership test, so the ordering step refuses rather than handing `v9` an alias.
    """
    completed, _ = _alias_plan(alias_repository, "v9.0.0")
    assert completed.returncode != 0
    assert "v9.0.0" in completed.stderr


def test_a_neighbouring_minor_is_not_mistaken_for_this_one(
    major_boundary_repository: Path,
) -> None:
    """`v1.2.` cannot prefix `v1.20.0`, and the trailing separator is why.

    Without it `v1.20.0` would count as the greatest release within `v1.2`, and the
    `v1.2` alias would stop advancing on runs that all finish green.
    """
    completed, emitted = _alias_plan(major_boundary_repository, "v1.2.3")
    assert completed.returncode == 0, completed.stderr
    assert emitted["minor-alias"] == "v1.2"
    assert emitted["advance-minor"] == "true"
    assert emitted["advance-major"] == "false"
    assert emitted["greatest-stable"] == "v2.0.0"


def test_the_first_release_of_a_new_major_advances_its_own_aliases(
    major_boundary_repository: Path,
) -> None:
    """Greatest overall, and greatest within a `MAJOR.MINOR` containing only itself."""
    completed, emitted = _alias_plan(major_boundary_repository, "v2.0.0")
    assert completed.returncode == 0, completed.stderr
    assert emitted["major-alias"] == "v2"
    assert emitted["minor-alias"] == "v2.0"
    assert emitted["advance-major"] == "true"
    assert emitted["advance-minor"] == "true"


def test_the_ordering_is_gits_version_order_never_a_lexicographic_one(
    alias_repository: Path,
) -> None:
    """`v1.2.10` sorts BELOW `v1.2.3` under every string comparison and above it under
    git's `v:refname`. The greatest tag reported is the whole ordering assertion."""
    completed, emitted = _alias_plan(alias_repository, "v1.2.10")
    assert completed.returncode == 0, completed.stderr
    assert emitted["greatest-stable"] == "v1.3.0"


# --- the finalization gate's input validation (gate finding F7) -------------


def test_a_destination_with_no_result_is_a_wiring_defect() -> None:
    """The finalizer did not `needs:` everything, so a destination reported nothing.

    Treating that as absent is the silent failure: the release finalizes while a
    destination nobody watched was still running, or had died.
    """
    bindings = _stable_bindings()
    bindings["needs.plan.outputs.enabled-destinations"] = json.dumps(
        {
            "image-forge": "enabled",
            "image-dockerhub": "disabled",
            "package-forge": "unsupported",
            "package-pypi": "enabled",
            "package-testpypi": "enabled",
        }
    )
    completed = _run_gate(RELEASE_WORKFLOW, bindings)
    assert completed.returncode != 0
    # The wiring refusal specifically, not merely "something failed". Deleting the
    # check leaves the destination with a `null` result, which the unknown-result
    # branch also refuses -- green for the wrong reason, and silent the day a result
    # of `null` becomes representable.
    assert "no publisher result was supplied for package-testpypi" in completed.stderr


def test_a_result_for_a_destination_nobody_planned_is_a_wiring_defect() -> None:
    """The other direction: the static job graph and the runtime set have drifted."""
    bindings = _stable_bindings()
    bindings["needs.plan.outputs.enabled-destinations"] = json.dumps(
        {"image-forge": "enabled", "image-dockerhub": "disabled"}
    )
    completed = _run_gate(RELEASE_WORKFLOW, bindings)
    assert completed.returncode != 0
    assert "results were supplied for package-forge, package-pypi" in completed.stderr


def test_an_empty_enabled_set_blocks_rather_than_finalizing_nothing() -> None:
    bindings = {
        f"needs.{job}.result": "skipped"
        for job in ("publish-image", "publish-package-forge", "publish-package-pypi")
    }
    bindings["needs.verify.result"] = "success"
    bindings["needs.plan.outputs.enabled-destinations"] = "{}"
    completed = _run_gate(RELEASE_WORKFLOW, bindings)
    assert completed.returncode != 0
    assert "names no destination at all" in completed.stderr


@pytest.mark.parametrize("raw", ["", "   ", "not json", "[]", '"a string"'])
def test_a_malformed_enabled_set_blocks(raw: str) -> None:
    """An upstream job that failed before emitting the set must block finalization,
    never fall through to an empty one."""
    bindings = _stable_bindings()
    bindings["needs.plan.outputs.enabled-destinations"] = raw
    completed = _run_gate(RELEASE_WORKFLOW, bindings)
    assert completed.returncode != 0


@pytest.mark.parametrize("state", ["on", "true", "ENABLED", ""])
def test_an_unrecognised_destination_state_blocks(state: str) -> None:
    bindings = _stable_bindings()
    bindings["needs.plan.outputs.enabled-destinations"] = json.dumps(
        {
            "image-forge": state,
            "image-dockerhub": "disabled",
            "package-forge": "unsupported",
            "package-pypi": "enabled",
        }
    )
    completed = _run_gate(RELEASE_WORKFLOW, bindings)
    assert completed.returncode != 0
    assert "image-forge" in completed.stderr


@pytest.mark.parametrize("result", ["succeeded", "SUCCESS", "", "neutral"])
def test_an_unrecognised_job_result_blocks(result: str) -> None:
    completed = _run_gate(
        RELEASE_WORKFLOW, _stable_bindings(**{"publish-image": result})
    )
    assert completed.returncode != 0


def test_every_blocking_destination_is_reported_not_only_the_first() -> None:
    """An operator reading one line and re-running into the second failure is the
    experience this avoids."""
    completed = _run_gate(
        RELEASE_WORKFLOW,
        _stable_bindings(
            **{"publish-package-pypi": "skipped", "publish-image": "failure"}
        ),
    )
    assert completed.returncode != 0
    assert "package-pypi" in completed.stderr
    assert "image-forge" in completed.stderr


def test_the_gate_writes_its_evidence_table_where_it_is_told(tmp_path: Path) -> None:
    """Every planned state and every job result, in the run summary, on success and on
    refusal alike -- a refusal that says nothing about the other destinations leaves an
    operator guessing which ones were fine."""
    summary = tmp_path / "summary.md"
    completed = _run_gate(RELEASE_WORKFLOW, _stable_bindings(), summary)
    assert completed.returncode == 0, completed.stderr
    rendered = summary.read_text(encoding="utf-8")
    assert "### Finalization gate" in rendered
    for destination in (
        "image-forge",
        "image-dockerhub",
        "package-forge",
        "package-pypi",
        "verify",
    ):
        assert f"`{destination}`" in rendered
    assert "`blocks`" not in rendered

    blocked = tmp_path / "blocked.md"
    completed = _run_gate(
        RELEASE_WORKFLOW,
        _stable_bindings(**{"publish-package-pypi": "skipped"}),
        blocked,
    )
    assert completed.returncode != 0
    rendered = blocked.read_text(encoding="utf-8")
    assert "| `package-pypi` | `enabled` | `skipped` | `blocks` |" in rendered
    assert "| `image-forge` | `enabled` | `success` | `ok` |" in rendered


@pytest.mark.parametrize("blocking", ["failure", "cancelled"])
def test_a_failure_blocks_even_on_a_destination_the_plan_says_is_off(
    blocking: str,
) -> None:
    """`disabled` and `unsupported` excuse a SKIP, never a failure.

    A destination that was switched off cannot fail; if its job reports one, something
    ran that nobody planned, and finalizing over it is exactly the state ADR-0011 keeps
    the finalizer away from. `package-forge` is `unsupported` in these bindings.
    """
    completed = _run_gate(
        RELEASE_WORKFLOW, _stable_bindings(**{"publish-package-forge": blocking})
    )
    assert completed.returncode != 0
    assert f"package-forge reported {blocking}" in completed.stderr


# ---------------------------------------------------------------------------
# Cutover topology and operator recovery (story E008-S01-004). Every guard below
# was proven by planting the violation it forbids, and each plant is kept as a test
# of its own rather than recorded in a comment -- a comment cannot fail when someone
# narrows the derivation under it. The plants include the ones review found this
# section's first draft missing: a second owner whose ref filter is a *glob* rather
# than the same literal, and the ordinary rewordings of each prohibited action.
# ---------------------------------------------------------------------------

OPERATIONAL_RUNBOOK = PROJECT_ROOT / "docs" / "operational.md"
RECOVERY_HEADING = "## Publication recovery"

# Events that start a run without a person or another workflow asking for it. These are
# the only ones that can race each other, and "each event has one owner" is a statement
# about exactly this set. `workflow_call` is excluded because a caller decides, and
# `workflow_dispatch` because a person does -- the verifier's direct dispatch entry point
# is governed by `test_verifier_supports_call_and_direct_dispatch_with_the_same_graph`.
NON_AUTOMATIC_EVENTS = frozenset({"workflow_call", "workflow_dispatch"})

# The only filter keys that divide the ref namespace, and therefore the only ones that
# can make two claims on the same event genuinely disjoint. `paths`, `paths-ignore` and
# `types` narrow *when* a workflow fires, never *which refs* it owns: two workflows
# filtered on different paths still both fire on a push that touches both. Letting them
# separate two claims is how a second owner of `push` slips past (review HIGH-1).
REF_NAMESPACE_KEYS = {
    "branches": "branches",
    "branches-ignore": "branches",
    "tags": "tags",
    "tags-ignore": "tags",
}
GLOB_METACHARACTERS = frozenset("*?[]+!")


def _trigger_surface(document: dict[str, Any]) -> dict[str, dict[str, tuple[str, ...]]]:
    """The automatic event surface a workflow claims, as `{event: {namespace: globs}}`.

    Derived from the parsed `on:` block, never from the file's name. A name list is the
    hand-enumerated scope global rule 4 forbids, and it would have to be edited again by
    Epic 9; the trigger surface is the property that actually matters, and it is read
    from the same text GitHub reads.

    An event with no ref-namespace filter -- or filtered only by `paths`/`types`, or by
    an `-ignore` form, which describes what it does *not* take and so bounds nothing --
    claims every namespace, spelled as an empty pattern tuple.
    """
    triggers = document["on"]
    if isinstance(triggers, str):
        triggers = {triggers: None}
    if isinstance(triggers, list):
        triggers = dict.fromkeys(triggers)
    assert isinstance(triggers, dict), document
    surface: dict[str, dict[str, tuple[str, ...]]] = {}
    for event, configuration in triggers.items():
        if event in NON_AUTOMATIC_EVENTS:
            continue
        claimed: dict[str, list[str]] = {}
        if isinstance(configuration, dict):
            for key, namespace in REF_NAMESPACE_KEYS.items():
                values = configuration.get(key) or []
                if not values:
                    continue
                # An `-ignore` list names what is excluded, so what remains is the whole
                # namespace minus an unknown set: treat it as unbounded.
                patterns = [] if key.endswith("-ignore") else [str(v) for v in values]
                claimed.setdefault(namespace, []).extend(patterns)
        surface[event] = (
            {name: tuple(globs) for name, globs in claimed.items()}
            if claimed
            else dict.fromkeys(set(REF_NAMESPACE_KEYS.values()), ())
        )
    return surface


def _globs_can_both_match(left: str, right: str) -> bool:
    """Whether two ref patterns can name the same ref. Conservative on purpose.

    A false positive here costs a topology rewrite nobody wanted; a false negative is a
    second owner of a delivery event that ships. So two globs are assumed to overlap
    unless one side is a literal that the other provably excludes.
    """
    left_wild = bool(GLOB_METACHARACTERS & set(left))
    right_wild = bool(GLOB_METACHARACTERS & set(right))
    if not left_wild and not right_wild:
        return left == right
    if left_wild and right_wild:
        return True
    literal, pattern = (right, left) if left_wild else (left, right)
    # `fnmatch` is not GitHub's ref matcher -- `*` does not cross `/` there -- but it is
    # strictly more permissive for these patterns, which is the safe direction.
    return fnmatch.fnmatchcase(literal, pattern)


def _surface_overlap(
    left: dict[str, dict[str, tuple[str, ...]]],
    right: dict[str, dict[str, tuple[str, ...]]],
) -> set[str]:
    """Events both surfaces claim -- the two-owner condition, per event."""
    shared: set[str] = set()
    for event in set(left) & set(right):
        for namespace in set(left[event]) & set(right[event]):
            ours, theirs = left[event][namespace], right[event][namespace]
            if not ours or not theirs:
                # One of them takes the whole namespace.
                shared.add(event)
            elif any(_globs_can_both_match(a, b) for a in ours for b in theirs):
                shared.add(event)
    return shared


def _declared_events(document: dict[str, Any]) -> set[str]:
    triggers = document["on"]
    if isinstance(triggers, str):
        return {triggers}
    return set(triggers)


def _topology_findings(documents: dict[str, dict[str, Any]]) -> list[str]:
    """Every way the workflow set can stop being a partition, as a list of findings.

    A pure function over parsed documents so the planted violations below run through
    exactly the code that governs the repository, rather than through a second
    implementation that can agree with the guard while both are wrong.

    Two kinds of file, and nothing else: a *reusable* one, which another workflow calls
    and which owns no automatic event; and a *channel*, which owns automatic events and
    is called by nobody. Anything else is a defect -- a file nothing can reach is dead
    weight that reads as governed, and a called file that also self-triggers runs twice
    for one event.
    """
    called = {
        str(job["uses"]).rsplit("/", 1)[-1]
        for document in documents.values()
        for job in _jobs(document).values()
        if isinstance(job.get("uses"), str)
        and str(job["uses"]).startswith("./.github/workflows/")
    }
    surfaces = {
        name: _trigger_surface(document) for name, document in documents.items()
    }
    findings: list[str] = []
    for name, document in documents.items():
        surface = surfaces[name]
        if name in called:
            if "workflow_call" not in _declared_events(document):
                findings.append(
                    f"{name}: another workflow calls it but it declares no "
                    f"`workflow_call` trigger"
                )
            if surface:
                findings.append(
                    f"{name}: a reusable workflow that also owns {sorted(surface)} runs "
                    f"twice for that event -- once for the caller, once for itself"
                )
        elif not surface and "workflow_dispatch" not in _declared_events(document):
            # Not "has no automatic event": a `workflow_dispatch`-only maintenance
            # workflow is reachable by a person and is perfectly legal (review LOW-5).
            # `workflow_call` is deliberately not a reprieve -- a reusable workflow
            # nobody calls is exactly the obsolete file this branch is looking for.
            findings.append(
                f"{name}: no event, no caller and no manual trigger can reach it; an "
                f"obsolete file left behind reads as governed"
            )
    for left, right in itertools.combinations(sorted(documents), 2):
        for event in sorted(_surface_overlap(surfaces[left], surfaces[right])):
            findings.append(
                f"{left} and {right} both own the {event} event; each event has exactly "
                f"one owner, or two pipelines race one delivery"
            )
    return findings


def test_the_workflow_topology_is_a_partition_of_reusable_files_and_event_owners() -> (
    None
):
    """Prep finding P2, and the cutover AC it revised.

    The count is not the property -- Epic 8 legitimately added a fifth file, and Epic 9
    may add a sixth. What must hold is that the on-disk set partitions into reusable
    workflows and event owners, and that no two owners claim the same event.
    """
    documents = {path.name: _load_workflow(path) for path in WORKFLOWS.glob("*.yaml")}
    assert documents, "no workflows on disk; this guard examined nothing"
    assert not _topology_findings(documents), _topology_findings(documents)

    # The partition itself, so a derivation that quietly stops classifying anything --
    # every file reusable, or every file an owner -- fails here rather than passing with
    # an empty finding list.
    owners = {
        name for name, document in documents.items() if _trigger_surface(document)
    }
    reusable = set(documents) - owners
    assert owners and reusable, (
        f"the topology is no longer a partition: owners={sorted(owners)} "
        f"reusable={sorted(reusable)}"
    )


@pytest.mark.parametrize(
    "trigger",
    [
        pytest.param({"push": {"branches": ["main"]}}, id="same-branch-literal"),
        pytest.param({"push": {"branches": ["ma*"]}}, id="branch-glob-over-main"),
        pytest.param({"push": {"tags": ["v*"]}}, id="same-tag-glob"),
        pytest.param({"push": {"tags": ["v1.*"]}}, id="narrower-tag-glob"),
        pytest.param(
            {"push": {"paths": ["src/**"]}}, id="paths-only-claims-everything"
        ),
        pytest.param({"push": {"branches-ignore": ["docs"]}}, id="ignore-form"),
        pytest.param({"pull_request": {"types": ["labeled"]}}, id="types-only"),
    ],
)
def test_the_topology_rejects_every_shape_of_second_owner(
    trigger: dict[str, Any],
) -> None:
    """The plants review HIGH-1 found the first draft missing.

    Each row is a workflow somebody could add in good faith that races an existing
    channel for one delivery. Only the first was caught before: string equality of the
    ref filter is not "each event has one owner", and `v1.*` racing `release.yaml` for a
    `v1.2.3` tag is exactly the two-publishers-one-release-tag failure the cutover
    exists to prevent.
    """
    documents = {path.name: _load_workflow(path) for path in WORKFLOWS.glob("*.yaml")}
    documents["build.yaml"] = {
        "on": trigger,
        "jobs": {"publish": {"runs-on": "ubuntu-24.04", "steps": []}},
    }
    findings = _topology_findings(documents)
    assert any("both own the" in finding for finding in findings), findings


def test_the_topology_rejects_a_triggered_reusable_workflow_and_an_orphan() -> None:
    """The scope attack, and the obsolete-file attack.

    A name-list assertion sees five files and five names in both cases and passes.
    """
    real = {path.name: _load_workflow(path) for path in WORKFLOWS.glob("*.yaml")}

    # publish-image.yaml stays a called workflow AND starts reacting to the tag push
    # release.yaml owns: two runs of the image publisher for one tag, one of them with
    # no verifier above it.
    triggered = dict(real)
    document = json.loads(json.dumps(real["publish-image.yaml"]))
    document["on"]["push"] = {"tags": ["v*"]}
    triggered["publish-image.yaml"] = document
    findings = _topology_findings(triggered)
    assert any("runs twice for that event" in finding for finding in findings), findings
    assert any("both own the push event" in finding for finding in findings), findings

    orphan = dict(real)
    orphan["build-container.yaml"] = {
        "on": {"workflow_call": None},
        "jobs": {"image": {"runs-on": "ubuntu-24.04", "steps": []}},
    }
    findings = _topology_findings(orphan)
    assert any("no manual trigger can reach it" in finding for finding in findings), (
        findings
    )


@pytest.mark.parametrize(
    "trigger",
    [
        pytest.param({"schedule": [{"cron": "0 3 * * *"}]}, id="new-event-owner"),
        pytest.param({"workflow_dispatch": None}, id="manual-only-maintenance"),
        pytest.param(
            {"push": {"branches": ["release/**"]}}, id="disjoint-branch-literal-space"
        ),
    ],
)
def test_the_topology_accepts_a_workflow_that_races_nothing(
    trigger: dict[str, Any],
) -> None:
    """The other half of a conservative overlap rule: it must still be satisfiable.

    A guard that rejected every new file would be disabled rather than fixed, so each
    lawful shape is asserted as explicitly as each violation. `release/**` is disjoint
    from `main` because both sides are decidable, not because the strings differ.
    """
    documents = {path.name: _load_workflow(path) for path in WORKFLOWS.glob("*.yaml")}
    documents["maintenance.yaml"] = {
        "on": trigger,
        "jobs": {"audit": {"runs-on": "ubuntu-24.04", "steps": []}},
    }
    assert not _topology_findings(documents), _topology_findings(documents)


# The four actions CI-AR38 permits the operations guide to name only as prohibited,
# matched at the width of the vocabulary an operator would actually use. Review HIGH-2
# demonstrated the first draft's narrower patterns accepting `remove the published
# version`, `yank the version`, `replace the published image tag`, `push the tag again
# with -f` and `re-run the workflow from the start` -- every one of them the prohibited
# action under a different verb. Each row below is proven by a plant.
PROHIBITED_RECOVERY_ACTIONS = (
    (
        "whole-workflow rerun",
        re.compile(
            r"re-?run(?:ning)?\s+(?:all\b|every\b"
            r"|the\s+(?:whole|entire|full|complete)\b"
            r"|the\s+(?:run|workflow|pipeline|job list)\b)"
            r"|whole[- ](?:workflow|run)\s+re-?run"
            r"|re-?(?:trigger|dispatch|launch)\s+the\s+(?:run|workflow)"
            r"|trigger\s+the\s+workflow\s+again",
            re.IGNORECASE,
        ),
    ),
    (
        "force update",
        re.compile(
            r"--force|(?<![\w-])-f(?![\w-])|force[- ](?:push|updat|overwrit|mov|creat)"
            r"|\bforce-?(?:push|updat)\w*",
            re.IGNORECASE,
        ),
    ),
    (
        "deletion",
        re.compile(
            r"\b(?:delet(?:e|es|ed|ing|ion)|remov(?:e|es|ed|ing|al)|purg(?:e|es|ed|ing)"
            r"|yank(?:s|ed|ing)?|drop(?:s|ped|ping)?)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "overwrite",
        re.compile(
            r"\b(?:overwrit(?:e|es|ing|ten)|replac(?:e|es|ed|ing)"
            r"|re-?(?:upload|push|publish)(?:es|ed|ing)?)\b",
            re.IGNORECASE,
        ),
    ),
)

# What makes a mention a prohibition rather than an instruction. Deliberately narrow:
# review MEDIUM-1 showed that admitting the ordinary negations (`is not`, `does not`,
# `cannot`) lets an unrelated conditional excuse an instruction -- "If the release is not
# yet consumed, delete it and republish" passed. Every marker here is prohibitive on its
# own, whatever the rest of the sentence says.
PROHIBITION_MARKER = re.compile(
    r"\b(?:never|not\s+a\s+recovery|prohibited|forbidden|must\s+not|may\s+not"
    r"|do(?:es)?\s+not\s+prescribe|refus\w*|unsupported|instead\s+of"
    r"|rather\s+than)\b",
    re.IGNORECASE,
)


def _statements(text: str) -> list[str]:
    """The units a prohibition has to attach to.

    Block structure comes from `markdown-it-py`, the CommonMark parser already in this
    project's dependency tree -- global rule 1, and the first draft's hand-written block
    splitter treated a line inside a fenced block as prose (review MEDIUM-3). A table
    *row* is one unit rather than one cell, because the prohibition lives in the row's
    other columns.

    Within a block, statements are split on sentence punctuation by a deliberately naive
    rule. It gets abbreviations wrong -- `e.g. ` splits early -- and that is a knowingly
    accepted limitation because its failure direction is safe: a statement split too
    early is a *smaller* unit, so a marker in the discarded half no longer excuses a
    matched verb. It can make this guard stricter, never laxer.
    """
    tokens = MarkdownIt("commonmark").enable("table").parse(text)
    blocks: list[str] = []
    row: list[str] | None = None
    for token in tokens:
        if token.type == "tr_open":
            row = []
        elif token.type == "tr_close" and row is not None:
            blocks.append(" ".join(row))
            row = None
        elif token.type == "inline":
            if row is not None:
                row.append(token.content)
            else:
                blocks.append(token.content)
        # `fence` and `code_block` carry their content on the token itself and are
        # skipped outright: a shell transcript is not a runbook instruction.
    statements: list[str] = []
    for block in blocks:
        collapsed = " ".join(block.split())
        statements.extend(
            part for part in re.split(r"(?<=[.!?])\s+", collapsed) if part.strip()
        )
    return statements


def _runbook_findings(text: str) -> list[str]:
    return [
        f"{name} appears as an instruction, not a prohibition: {statement!r}"
        for statement in _statements(text)
        for name, pattern in PROHIBITED_RECOVERY_ACTIONS
        if pattern.search(statement) and not PROHIBITION_MARKER.search(statement)
    ]


def _recovery_section(text: str) -> str:
    """The section this story owns, located by heading and ended by the next one.

    Used only for the *positive* assertions, which are genuinely section-local. The
    prohibition scan runs over the whole page (review MEDIUM-2): `## Rollback` is another
    recovery procedure, and an operator following a prohibited instruction there is in
    the same trouble as one following it here.
    """
    assert RECOVERY_HEADING in text, f"{RECOVERY_HEADING} is missing from the runbook"
    body = text.split(RECOVERY_HEADING, 1)[1]
    return RECOVERY_HEADING + re.split(r"\n## ", body)[0]


def test_the_recovery_runbook_prescribes_failed_jobs_only_recovery() -> None:
    """CI-AR38. The runbook is the deliverable an operator acts on at 3am, so what it
    prescribes is as load-bearing as what the workflows enforce."""
    page = OPERATIONAL_RUNBOOK.read_text(encoding="utf-8")
    section = _recovery_section(page)

    assert re.search(r"re-?run\s+failed\s+jobs", section, re.IGNORECASE), (
        "the recovery section never names the failed-jobs-only rerun it exists to "
        "prescribe (CI-AR38)"
    )
    # Both forges, because the procedure differs and Epic 9 inherits this page.
    assert "GitHub" in section and "Gitea" in section

    # The three halt-and-escalate conditions, each named with its escalation.
    for condition in ("unsupported", "expired", "conflict"):
        assert re.search(condition, section, re.IGNORECASE), (
            f"the recovery section never names the {condition} halt condition"
        )
    assert re.search(r"escalat", section, re.IGNORECASE)

    # F17: the detector is the destination's own rejection, and the guard that forbids
    # the alternative is named where an operator can find it -- so the name has to
    # resolve. Derived from the page rather than hard-coded, so a second guard cited
    # later is checked too (review LOW-1).
    cited_guards = set(re.findall(r"\btest_[a-z0-9_]+", section))
    assert "test_no_publisher_queries_a_destination_before_uploading" in cited_guards
    for guard in sorted(cited_guards):
        assert guard in globals(), (
            f"docs/operational.md cites {guard}, which no longer exists; the runbook "
            f"points an operator at nothing"
        )

    # F30: a digest carries no run identity, so the join key has to be spelled out.
    assert "org.opencontainers.image.revision" in section

    # The prohibition scan is the whole page, not this section.
    assert not _runbook_findings(page), _runbook_findings(page)
    assert len(_statements(page)) > len(_statements(section)), (
        "the prohibition scan is examining only the section it was widened past"
    )


@pytest.mark.parametrize(
    ("instruction", "expected"),
    [
        ("Re-run all jobs from the run page.", "whole-workflow rerun"),
        ("Re-run the workflow from the start.", "whole-workflow rerun"),
        ("Re-run the run.", "whole-workflow rerun"),
        ("Trigger the workflow again from the tag.", "whole-workflow rerun"),
        ("Push the tag again with -f so the release points at the build.", "force"),
        ("Run git push -f origin v1.2.3 to move the tag.", "force"),
        ("Force update the tag so the release points at the new build.", "force"),
        ("Delete the published version and upload it again.", "deletion"),
        ("When the index rejects it, remove the published version.", "deletion"),
        ("Yank the version from PyPI and publish the same wheel again.", "deletion"),
        ("Overwrite the image tag with the corrected image.", "overwrite"),
        ("Replace the published image tag with the corrected image.", "overwrite"),
        ("Re-upload the wheel once the index has settled.", "overwrite"),
        ("If the release is not yet consumed, delete it and republish.", "deletion"),
    ],
)
def test_the_runbook_guard_rejects_every_wording_of_a_prohibited_instruction(
    instruction: str, expected: str
) -> None:
    """The planted violations, run through the checker the real page goes through.

    Every row is an instruction somebody would write in good faith, and review HIGH-2
    and MEDIUM-1 proved the first draft accepted all but the first. The last row is
    MEDIUM-1's: an unrelated negation must not excuse the verb it does not govern.
    """
    findings = _runbook_findings(f"{RECOVERY_HEADING}\n\n{instruction}\n")
    assert any(expected in finding for finding in findings), (instruction, findings)


def test_the_runbook_guard_accepts_the_same_actions_named_as_prohibitions() -> None:
    """The other half: a guard that rejected the words themselves would be unwritable,
    and the real page has to be able to say what must not be done."""
    lawful = (
        f"{RECOVERY_HEADING}\n\n"
        "A whole-workflow rerun is prohibited, and the tag is never force-updated, "
        "deleted, replaced or overwritten.\n\n"
        "| Action | Status |\n| --- | --- |\n"
        "| Delete the published version | prohibited |\n\n"
        "```bash\n"
        "# a code block is not an instruction and is not scanned\n"
        "git push --force origin v1.2.3\n"
        "```\n"
    )
    assert not _runbook_findings(lawful), _runbook_findings(lawful)


def test_the_runbook_names_every_channel_and_no_workflow_that_is_not_on_disk() -> None:
    """The rename attack, and the docs half of "no dangling references".

    Scope is derived from disk both ways: every publishing channel must be documented by
    name, and every workflow filename the page cites must exist. Renaming `dev.yaml` and
    forgetting the page fails the first; renaming it and leaving the old reference
    behind fails the second. Citations are collected in both the forms the page actually
    uses -- the full `.github/workflows/x.yaml` path and the bare backticked filename --
    because review MEDIUM-6 found only two of the page's references were the former.

    The documented set is "owns an event AND holds a publisher": `ci.yaml` owns the pull
    request event and ships nothing, so an operations guide has nothing to say about it.
    """
    text = OPERATIONAL_RUNBOOK.read_text(encoding="utf-8")

    tracked_names = {Path(relative).name for relative, _ in tracked_text_files()}
    cited = set(re.findall(r"\.github/workflows/([\w.-]+\.ya?ml)", text)) | {
        name
        for name in re.findall(r"`([\w.-]+\.ya?ml)`", text)
        # A name that is not a workflow filename is somebody else's file -- the page
        # cites `config.yaml` and `docker-compose.yml` too -- and is resolved against
        # the tracked corpus rather than against this directory.
        if name not in tracked_names or (WORKFLOWS / name).exists()
    }
    assert len(cited) >= 4, f"the operations guide cites almost no workflow: {cited}"
    for name in sorted(cited):
        assert (WORKFLOWS / name).exists(), (
            f"docs/operational.md cites {name}, which is not in .github/workflows"
        )

    channels = sorted(
        path.name
        for path in WORKFLOWS.glob("*.yaml")
        if _trigger_surface(_load_workflow(path)) and _publishers(_load_workflow(path))
    )
    assert channels, "no publishing channel on disk; this guard examined nothing"
    for name in channels:
        assert name in text, (
            f"{name} owns an event and publishes, but the operations guide never names "
            f"it, so an operator has no runbook for the channel it drives"
        )


def test_every_run_summary_reports_the_verified_bundle_and_every_destination() -> None:
    """CI-AR41, asserted at the job that actually writes the run summary.

    The neighbouring guards check these fields *somewhere in the file*: moving the digest
    and platform rows out of the evidence job keeps them green while the evidence table
    loses them (review MEDIUM-5). Every set here is derived -- publishers from
    capability, the aggregator from "depends on a publisher and ships nothing", the image
    and release jobs from what they call -- so a destination added later is covered
    without an edit, which is the scope attack each of these guards has to survive.
    """
    channels = _publishing_workflows()
    assert channels, "no workflow calls the image publisher"
    examined = 0
    for path in channels:
        document = _load_workflow(path)
        jobs = _jobs(document)
        publishers = set(_publishers(document))
        aggregators = {
            name
            for name in jobs
            if name not in publishers and _transitive_needs(jobs, name) & publishers
        }
        assert aggregators, f"{path.name}: no job aggregates the publication outcomes"

        required = [
            "needs.plan.outputs.source-sha",
            "needs.plan.outputs.package-version",
        ]
        for name, job in jobs.items():
            if job.get("uses") == PUBLISH_IMAGE_REFERENCE:
                required += [
                    f"needs.{name}.outputs.digest",
                    f"needs.{name}.outputs.platforms",
                ]
            if any(
                str(step.get("uses", "")).startswith(APPROVED_RELEASE_ACTION)
                for step in job.get("steps") or []
            ):
                required.append(f"needs.{name}.outputs.release-url")
        required.append("outputs.build-manifest-sha256")

        for name in sorted(aggregators):
            body = json.dumps(jobs[name])
            for publisher in sorted(publishers):
                examined += 1
                assert f"needs.{publisher}.result" in body, (
                    f"{path.name}: {name!r} never reports {publisher!r}'s conclusion, so "
                    f"a destination's outcome reaches no run summary (CI-AR41)"
                )
            for reference in required:
                examined += 1
                assert reference in body, (
                    f"{path.name}: {name!r} never reports {reference}, so the run "
                    f"summary is missing evidence CI-AR41 requires"
                )
    assert examined, "no evidence field was examined"
