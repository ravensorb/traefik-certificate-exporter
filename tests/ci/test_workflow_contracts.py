"""Cross-cutting workflow governance, and the operator runbook.

BL-E008-010 phase 3. What was left once every subject with a name of its own moved out:
the rules that hold across the whole workflow set rather than inside one channel -- one
authority per fact, who may write a ref or create a Release, what a privileged job may
hold -- and the cutover runbook's prohibited-instruction guard.

Each subject module states its own scope. This one is the remainder by construction, so a
new guard belongs here only when it genuinely spans the set; anything about a channel, an
image, a fork or a finalizer has a module already.
"""

from __future__ import annotations

import copy
import json
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from packaging.version import Version

from tests.ci.support import (
    APPROVED_ALIAS_ACTION,
    APPROVED_RELEASE_ACTION,
    GOVERNED_DEFINITIONS,
    PROJECT_ROOT,
    PUBLISH_IMAGE_REFERENCE,
    RECOVERY_HEADING,
    REGISTRY_READ_COMMANDS,
    RELEASE_FINALIZER_JOBS,
    SETUP_ACTION,
    WORKFLOWS,
    _alias_moving_jobs,
    _gate_steps,
    _governed_step_groups,
    _is_credential_bearing,
    _is_publishing_step,
    _jobs,
    _load_document,
    _load_fixture,
    _load_workflow,
    _publishers,
    _publishing_workflows,
    _runbook_findings,
    _transitive_needs,
    _workflow_documents,
    committed_versions,
)

SETUP_ACTION_REFERENCE = "./.github/actions/setup-poetry-python"
# Workflows that build or ship an artifact. A push event that reaches one of these
# without first reaching the verifier is the regression this file exists to prevent.


# `release` and `tag` as verbs in an action name -- the ref-writing ones. `publish` is
# deliberately absent so pypa/gh-action-pypi-publish and image pushes, which write no ref,
# are not caught by a guard about repository writes.
RELEASE_ACTION_VERB = re.compile(r"(?:\A|[-/])(?:release|tag)(?:[-/]|\Z)")


def _is_registered_finalizer(definition: str, container: str) -> bool:
    """`RELEASE_FINALIZER_JOBS` holds (workflow filename, job name) pairs, so only a
    workflow job can ever match -- which is the point: a composite action is never a
    grant holder in its own right."""
    return (Path(definition).name, container) in RELEASE_FINALIZER_JOBS


def _scalars(
    node: Any, path: tuple[str, ...] = ()
) -> Iterator[tuple[tuple[str, ...], str]]:
    """Every string leaf of a parsed document, with the key path that reaches it."""
    if isinstance(node, dict):
        for key, value in node.items():
            yield from _scalars(value, path + (str(key),))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _scalars(value, path + (str(index),))
    elif isinstance(node, str):
        yield path, node


def _trigger_branch_literals() -> set[str]:
    """Branch names spelled literally in an `on:` trigger.

    The trigger is the one place a literal is unavoidable -- GitHub takes no expression
    there -- which is exactly what makes it the authority for the name.
    """
    literals: set[str] = set()
    for document in _workflow_documents().values():
        triggers = document.get("on")
        if not isinstance(triggers, dict):
            continue
        for event in ("push", "pull_request", "pull_request_target"):
            specification = triggers.get(event)
            if isinstance(specification, dict):
                literals |= {
                    branch
                    for branch in (specification.get("branches") or [])
                    if "*" not in branch
                }
    return literals


def test_the_default_branch_is_named_once_and_derived_everywhere_else() -> None:
    """One fact, one spelling. It had three, and the two channels chose opposite answers.

    `release.yaml` pinned `DEFAULT_BRANCH_REF: origin/main`; `dev.yaml` already read
    `github.event.repository.default_branch`; and `on: push: branches: [main]` is a
    third. Only the trigger *must* be a literal -- GitHub accepts no expression there --
    so it is the authority, and every other use derives from the forge.

    A rename is what makes this matter, and it fails three different ways: `dev.yaml`
    stops triggering with no run, no red and no alert; `release.yaml`'s reachability
    check refuses a tag that is genuinely reachable; and an empty event field would make
    `actions/checkout` fall back to the default branch and *appear* correct. The first is
    unguardable from inside the workflow. The other two are now refusals, and this keeps
    the literal from spreading back out of the trigger.
    """
    literals = _trigger_branch_literals()
    assert literals, "no workflow names a branch in its trigger; nothing was examined"
    for path in GOVERNED_DEFINITIONS:
        for key_path, value in _scalars(_load_document(path)):
            if key_path and key_path[0] == "on":
                continue
            for branch in literals:
                assert not (
                    value == branch
                    or value.endswith(f"/{branch}")
                    or f"refs/heads/{branch}" in value
                ), (
                    f"{path}: {'.'.join(key_path)} spells the default branch "
                    f"{branch!r} literally. Derive it from "
                    f"`github.event.repository.default_branch`; only the `on:` trigger "
                    f"has to name it, and that makes the trigger the authority."
                )


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


ENABLED_SET_OUTPUT = "enabled-destinations"


def _enabled_set_producers(path: Path) -> set[str]:
    """Jobs a finalizer's gate reads the enabled set from, in this workflow.

    Derived from the gate step's own text rather than from what a job calls its outputs:
    a job is the producer because something consumes it as one, which a label cannot
    fake. `_gate_steps` is already asserted non-empty by the guards that own it.
    """
    producers = set()
    for step in _gate_steps(path).values():
        rendered = json.dumps(step)
        for job_name in _jobs(_load_workflow(path)):
            if f"needs.{job_name}.outputs.{ENABLED_SET_OUTPUT}" in rendered:
                producers.add(job_name)
    return producers


def test_the_enabled_destination_set_has_one_producer() -> None:
    """ADR-0011: publishers consume the enabled set; they never re-read `PUBLISH_*`.

    Two readers of one truth is the F7 defect one layer along -- the static job graph and
    the runtime enabled set drift apart, and the finalizer starts blocking on a
    destination nobody turned off. The plan job is the single producer.
    """
    toggle = re.compile(r"\bPUBLISH_[A-Z_]+\b")
    for path in sorted(WORKFLOWS.glob("*.yaml")):
        producers = _enabled_set_producers(path)
        for job_name, job in _jobs(_load_workflow(path)).items():
            # The producer is defined by role: it is the job the finalizer's gate reads
            # the enabled set FROM. The previous form tested two labels -- the output
            # name `enabled-destinations`, or any output whose name merely *contained*
            # "version" -- and the second was this epic's own defect in a milder form: a
            # publisher declaring `image-version` and holding no secret was exempted and
            # could read PUBLISH_* directly, which is the two-readers drift ADR-0011
            # exists to prevent.
            if job_name in producers:
                continue
            body = json.dumps(job)
            assert not toggle.search(body), (
                f"{path.name}: job {job_name!r} reads a PUBLISH_* toggle directly. The "
                f"enabled set is produced once by the plan job and consumed from its "
                f"output (ADR-0011)."
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
    for definition, container, steps in _governed_step_groups():
        if _is_registered_finalizer(definition, container):
            continue
        for step in steps:
            command = str(step.get("run", ""))
            for pattern in write_commands:
                assert not re.search(pattern, command), (
                    f"{definition}: {container!r} writes refs or releases; "
                    "register it in RELEASE_FINALIZER_JOBS with an ADR"
                )
            name = str(step.get("uses", "")).split("@", 1)[0]
            assert not RELEASE_ACTION_VERB.search(name), (
                f"{definition}: {container!r} uses a release/tag-writing action "
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
    for definition, container, steps in _governed_step_groups():
        for step in steps:
            command = str(step.get("run", ""))
            for pattern in hand_rolled:
                assert not re.search(pattern, command), (
                    f"{definition}: {container!r} creates a Release by hand. Use "
                    f"{APPROVED_RELEASE_ACTION}@v2, which speaks both GitHub's and "
                    f"Gitea's APIs from one step (ADR-0010)."
                )


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
    for definition, container, steps in _governed_step_groups():
        for step in steps:
            command = str(step.get("run", ""))
            assert not FORCED_REF_WRITE.search(command), (
                f"{definition}: {container!r} forces a ref update by hand. Alias "
                f"moves go through {APPROVED_ALIAS_ACTION}; `vX.Y.Z` is immutable and "
                f"is never forced at all (ADR-0006)."
            )


def test_the_alias_action_runs_only_from_a_registered_finalizer() -> None:
    # The action needs `contents: write` to push tags, so its use is a grant in exactly
    # the sense ADR-0006 means, and belongs in the same registry as the Release finalizer.
    for definition, container, steps in _governed_step_groups():
        for step in steps:
            if not str(step.get("uses", "")).startswith(APPROVED_ALIAS_ACTION):
                continue
            assert _is_registered_finalizer(definition, container), (
                f"{definition}: {container!r} moves version aliases but is not a "
                f"registered finalizer (ADR-0006)"
            )


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


def test_the_dispatch_fixture_carries_a_well_formed_version() -> None:
    """Shape, not the repository's current version.

    This asserted equality with the committed Poetry version, and that made the project
    **unreleasable at any version**. `just release` bumps the version and then runs
    `just check` before it commits or tags, so at that moment the fixture still holds
    the old value and the check fails -- restoring the version, refusing the release,
    and reporting only "just check failed". The guard's rule was reasonable and its
    coupling was a deadlock, and nothing found it until a release was actually
    attempted.

    Nothing depends on which version the fixture names: the three guards that consume
    it use it as an event payload and care about the relations between its fields.
    """
    event = _load_fixture("workflow-dispatch.json")
    assert re.fullmatch(r"\d+\.\d+\.\d+", str(event["inputs"]["package-version"])), (
        event["inputs"]["package-version"]
    )
    assert re.fullmatch(r"[0-9a-f]{40}", str(event["sha"]))
    assert event["inputs"]["source-sha"] == event["sha"], (
        "the dispatch fixture's declared source SHA and event SHA disagree"
    )


# Every spelling of "give an image that already exists another name". A digest copy is
# a registry WRITE, which is why it is not matched by REGISTRY_READ_COMMANDS: the
# ordering guard forbids asking a registry what is there, not putting something there.


# ---------------------------------------------------------------------------
# Cutover topology and operator recovery (story E008-S01-004). Every guard below
# was proven by planting the violation it forbids, and each plant is kept as a test
# of its own rather than recorded in a comment -- a comment cannot fail when someone
# narrows the derivation under it. The plants include the ones review found this
# section's first draft missing: a second owner whose ref filter is a *glob* rather
# than the same literal, and the ordinary rewordings of each prohibited action.
# ---------------------------------------------------------------------------


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
