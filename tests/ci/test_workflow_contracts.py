from __future__ import annotations

import copy
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

if sys.version_info >= (3, 11):
    pass
else:  # pragma: no cover - exercised only on the oldest supported interpreter
    # pyproject declares >=3.10 and `tomllib` arrived in 3.11. `tomli` is the same
    # parser under its pre-stdlib name and is already resolved for <3.11 by the lock.
    pass
from packaging.version import Version

from tests.ci.support import (
    ACTIONS,
    APPROVED_RELEASE_ACTION,
    BUNDLE_ACTION,
    DEV_WORKFLOW,
    GOVERNED_DEFINITIONS,
    PROJECT_ROOT,
    PUBLISH_IMAGE_WORKFLOW,
    RECOVERY_HEADING,
    REGISTRY_LOGIN_ACTION,
    RELEASE_FINALIZER_JOBS,
    RELEASE_WORKFLOW,
    SETUP_ACTION,
    VERIFIER_REFERENCE,
    WORKFLOWS,
    _declared_events,
    _git,
    _governed_step_groups,
    _is_credential_bearing,
    _jobs,
    _load_document,
    _load_fixture,
    _load_workflow,
    _publishers,
    _run_step,
    _runbook_findings,
    _step_with_id,
    _steps,
    _transitive_needs,
    _trigger_surface,
    _uncommented,
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


# ---------------------------------------------------------------------------
# Development channel (story E008-S01-001). Every guard below was proven by
# planting the violation it forbids and confirming the guard fails.
# ---------------------------------------------------------------------------

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
        # Any entry point that publishes. `_trigger_surface` excludes
        # `workflow_dispatch`, which is right for the event-ownership partition -- a
        # person asked for it, so it races nothing -- and wrong here: a
        # manually-dispatched publisher holding `id-token: write` and running
        # `twine upload` escaped all seven of these rules. `workflow_call` is the one
        # exemption, because a reusable file's caller owns the gate.
        if (_declared_events(_load_workflow(path)) - {"workflow_call"})
        and _publishers(_load_workflow(path))
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
            # Resolved through one of the names this job actually emits. Hard-coding
            # `"registry"` meant a channel emitting, say, `image-repository` and
            # `package-index-url` but not `registry` raised a bare KeyError from inside
            # `_producing_step` -- which reads as a broken test rather than as a caught
            # violation, the failure mode `_step_with_id` exists to avoid.
            assert "registry" in emitted, (
                f"{path.name}: job {job_name!r} derives forge coordinates but emits no "
                f"`registry`; it emits {sorted(emitted)}. Every channel resolves the "
                f"registry from action context (CI-AR6)."
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

        # https, before the value is used for anything. Every coordinate this step emits
        # ends up carrying a credential: the package index URL takes FORGE_PACKAGE_TOKEN,
        # and release.yaml reassembles the same server URL into
        # `https://x-access-token:<contents-write-token>@host/...`. Over plain HTTP both
        # are cleartext Basic auth. Latent on GitHub, where `github.server_url` is always
        # https; live the moment E009 reaches a self-hosted Gitea, which is the
        # deployment shape where an operator can choose http.
        #
        # Each case below is one the derivation would otherwise ACCEPT, so only the
        # scheme check can reject it. `http://gitea.internal` would not do: it reaches
        # the fail-closed branch on its own and the assertion would pass with the scheme
        # check deleted -- which it did, on the first draft of this test.
        for insecure, environment in (
            ("http://github.com", {}),
            ("ftp://github.com", {}),
            ("github.com", {}),
            ("http://gitea.internal", {"GITEA_ACTIONS": "true"}),
        ):
            completed, _ = _run_step(
                body,
                {
                    "FORGE_SERVER_URL": insecure,
                    "FORGE_REPOSITORY": "Owner/Name",
                    **environment,
                },
                tmp_path,
            )
            assert completed.returncode != 0, (
                f"{where}: accepted {insecure!r}, so a publication credential would "
                f"cross the network in cleartext"
            )

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
            # GitHub has an attestation store; Gitea does not. A capability of the host,
            # emitted here so no publisher ever compares a forge name (ADR-0011 s2).
            "attestation-supported": "true",
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
            # The mirror image of the GitHub case above: each forge supports one of the
            # two, and neither is a toggle an operator can set.
            "attestation-supported": "false",
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
    # Every reusable workflow that builds an image, not the one file that does today.
    # Counting inside a literal path meant a second reusable publisher -- a copy with
    # its own `bake`, correctly wired -- carried a second build that nothing examined.
    building = {
        path.name: [
            step
            for step in _steps(_load_workflow(path))
            if re.search(r"buildx\s+(?:bake|build)\b", str(step.get("run", "")))
        ]
        for path in sorted(WORKFLOWS.glob("*.yaml"))
        # Reusable AND publishing. The verifier builds an image too -- that is its
        # smoke test -- and it holds no credential and pushes nothing, so it is not
        # what CI-AR39 is counting.
        if "workflow_call" in _declared_events(_load_workflow(path))
        and _publishers(_load_workflow(path))
    }
    building = {name: builds for name, builds in building.items() if builds}
    assert building, "no reusable workflow builds an image; this guard examined nothing"
    total = sum(len(builds) for builds in building.values())
    assert total == 1, (
        f"{total} image builds across {sorted(building)}; CI-AR39 allows one per "
        f"channel run, so every destination is tagged inside the same invocation"
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
    # The one build, reached through the derived set rather than a named file.
    builder, builds = next(iter(building.items()))
    command = str(builds[0]["run"])
    assert "--push" in command
    environment = builds[0].get("env") or {}
    assert "TAGS" in environment and "PLATFORMS" in environment, (
        f"{builder}: the single invocation must receive every tag and every platform as "
        f"bake variables; a tag applied outside it is a second build"
    )
    # `--push` states the intent and this asserts the mechanism, because the first CI
    # run showed the two can disagree. docker-bake.hcl's target sets `output = OUTPUTS`,
    # defaulting to `type=docker` for local single-platform builds, and that attribute
    # beat `--push`: the run died on `docker exporter does not currently support
    # exporting manifest lists`. The docker exporter cannot hold a multi-platform index,
    # so the push was impossible -- while this guard, asserting only that the command
    # said `--push`, was satisfied. The rule held and the outcome did not.
    exporter = str(environment.get("OUTPUTS", ""))
    assert "type=registry" in exporter, (
        f"{builder}: the multi-platform build exports {exporter!r}. Only the registry "
        f"exporter can hold a manifest list -- `--push` alone does not override the "
        f"bake target's own `output`."
    )

    triggers = _load_workflow(WORKFLOWS / builder)["on"]
    platforms = triggers["workflow_call"]["inputs"]["platforms"]["default"]
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
    tags: str,
    registry: str = "ghcr.io",
    dockerhub: str = "false",
    repositories: str = "ghcr.io/owner/name\ndocker.io/owner/name",
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
            "PERMITTED_REPOSITORIES": repositories,
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


@pytest.mark.parametrize(
    "alias",
    [
        "ghcr.io/owner/name:latest",
        "ghcr.io/owner/name:1",
        "ghcr.io/owner/name:1.2",
        # The development channel's alias, moved by dev.yaml's own finalizer. The first
        # version of this refusal enumerated the *stable* channel's alias shapes and
        # accepted `dev`, so the publisher could have taken it outside the grant --
        # skipping the just-in-time default-branch-head proof and the stable-tag
        # suppression re-check (epic redteam E1).
        "ghcr.io/owner/name:dev",
        "ghcr.io/owner/name:main",
        "ghcr.io/owner/name:stable",
        "ghcr.io/owner/name:dev-nothex12345",
        "ghcr.io/owner/name:1.2.3.4",
        "ghcr.io/owner/name:v1.2.3",
    ],
)
def test_a_publisher_refuses_to_push_an_alias_however_the_tag_list_was_rendered(
    alias: str,
) -> None:
    """CI-AR29: an alias is the finalizer's sole property, enforced where the tag list
    is real rather than where it is requested.

    The list comes from `LiquidLogicLabs/git-action-docker-metadata@v6`, a fork of
    `docker/metadata-action` on its own major line, and the neighbouring guard asserts
    `flavor: latest=false` is *passed* -- not that it is *honoured*. If the renderer
    ever emitted `latest`, or a bare major or major.minor, the publisher would move an
    alias from outside the grant and every alias-ownership guard would still pass,
    because they read the workflow and not the rendered list. Executed against the
    shipped step, so the refusal is proven rather than described.
    """
    completed, _ = _compose_tag_list(alias)
    assert completed.returncode != 0, f"the publisher accepted the alias {alias!r}"
    assert "not an immutable publication tag" in completed.stderr, completed.stderr


def test_the_exact_version_a_publisher_does_push_is_still_accepted() -> None:
    """The other half: the refusal above must not reject what a release actually
    publishes -- an exact `X.Y.Z`, or the development channel's `dev-<sha>`."""
    for permitted in (
        "ghcr.io/owner/name:1.2.3",
        "ghcr.io/owner/name:10.20.30",
        "ghcr.io/owner/name:dev-0123456789ab",
        "ghcr.io/owner/name:dev-abcdef012345",
    ):
        completed, _ = _compose_tag_list(permitted)
        assert completed.returncode == 0, completed.stderr


@pytest.mark.parametrize(
    ("tag", "why"),
    [
        (
            "ghcr.io/owner/name:a,b",
            "a comma splits into two tags under bake's CSV parse",
        ),
        (
            "ghcr.io/owner/na me:1.2.3",
            "interior whitespace was silently deleted, not refused",
        ),
        ("ghcr.io/owner/name\u200b:1.2.3", "a zero-width space survives normalisation"),
        (
            "ghcr.io/оwner/name:1.2.3",
            "a Cyrillic homoglyph reads as the proven repository",
        ),
        ("ghcr.io/owner/name;evil:1.2.3", "a separator other than the comma"),
    ],
)
def test_a_tag_outside_the_oci_character_grammar_is_refused(tag: str, why: str) -> None:
    """Refused, never repaired.

    The normalisation was `tr -d '[:space:]'`, which deletes *interior* whitespace too --
    so `ghcr.io/a b:1` became `ghcr.io/ab:1`, a different image reference, published
    without complaint. And the separator defence named only the comma, while the
    repository comparison it feeds is byte-exact: a homoglyph or zero-width character
    passes normalisation and then compares unequal to the repository the plan job proved.

    An OCI reference is ASCII by construction, so one character-class refusal subsumes
    all three. The multi-byte cases are caught because every UTF-8 continuation byte is
    outside the class.
    """
    completed, _ = _compose_tag_list(
        f"ghcr.io/owner/name:1.2.3\n{tag}", repositories="ghcr.io/owner/name"
    )
    assert completed.returncode != 0, f"accepted {tag!r}: {why}"


def test_the_digest_reference_is_the_forge_repository_never_the_first_tag() -> None:
    """`primary` is the reference the digest is resolved from, and therefore the target
    every alias the finalizer moves will follow.

    It was taken positionally -- the first tag in the rendered list -- which made an
    alias target a property of a third-party metadata action's output ORDER. With two
    enabled destinations the choice between them was the renderer's, not this
    repository's. The forge registry is the one destination that is never optional
    (ADR-0011), so it is the only stable anchor.
    """
    permitted = "ghcr.io/owner/name\ndocker.io/owner/name"
    # Docker Hub first in the rendered list, forge second: `primary` must still be the
    # forge repository.
    completed, emitted = _compose_tag_list(
        "docker.io/owner/name:1.2.3\nghcr.io/owner/name:1.2.3",
        dockerhub="true",
        repositories=permitted,
    )
    assert completed.returncode == 0, completed.stderr
    assert emitted["primary"] == "ghcr.io/owner/name", (
        f"the digest reference followed the first tag ({emitted['primary']}) rather "
        f"than the forge repository"
    )
    # And the reverse order gives the same answer, which is the point.
    completed, emitted = _compose_tag_list(
        "ghcr.io/owner/name:1.2.3\ndocker.io/owner/name:1.2.3",
        dockerhub="true",
        repositories=permitted,
    )
    assert completed.returncode == 0, completed.stderr
    assert emitted["primary"] == "ghcr.io/owner/name"


def test_a_tag_may_not_address_a_repository_the_plan_job_never_proved() -> None:
    """The permission check tested the *authority* and never the *repository*.

    A Docker Hub credential is account-scoped, so every repository that account can
    write shares one authority. A tag list naming `docker.io/<elsewhere>/x` passed --
    `buildx` pushes whatever it is handed, with the real token -- publishing this
    project's verified image under a name nobody chose, and `primary` (the digest
    reference the aliases then follow) is whichever tag came first. The list is rendered
    by a third-party action on a floating ref, which is exactly the input not to trust.

    The plan job already proved both repositories and handed them to that action; they
    are now handed to the publisher too, and every tag is checked against them.
    """
    permitted = "ghcr.io/owner/name\ndocker.io/owner/name"
    completed, _ = _compose_tag_list(
        "docker.io/elsewhere/x:1.2.3", dockerhub="true", repositories=permitted
    )
    assert completed.returncode != 0, "a tag for an unproven repository was accepted"
    assert "which the plan job did" in completed.stderr, completed.stderr

    # The forge authority is no different: same host, unproven name.
    completed, _ = _compose_tag_list(
        "ghcr.io/elsewhere/x:1.2.3", repositories="ghcr.io/owner/name"
    )
    assert completed.returncode != 0, completed.stderr

    # A run that proves nothing publishes nothing, rather than defaulting to open.
    completed, _ = _compose_tag_list("ghcr.io/owner/name:1.2.3", repositories="  \n ")
    assert completed.returncode != 0, "an empty permitted set was treated as permissive"


@pytest.mark.parametrize(
    "spelling",
    [
        "docker.io/owner/name:1.2.3",
        "index.docker.io/owner/name:1.2.3",
        "owner/name:1.2.3",
    ],
)
def test_the_three_spellings_of_one_docker_hub_repository_are_one_destination(
    spelling: str,
) -> None:
    """`docker.io/owner/name`, `index.docker.io/owner/name` and a bare `owner/name` are
    the same place. Comparing the rendered string against the proven string would refuse
    two of the three, so both sides are normalised -- and the refusal above still has to
    hold, which is what the neighbouring test keeps honest."""
    completed, _ = _compose_tag_list(
        f"ghcr.io/owner/name:1.2.3\n{spelling}",
        dockerhub="true",
        repositories="ghcr.io/owner/name\ndocker.io/owner/name",
    )
    assert completed.returncode == 0, completed.stderr


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
        repositories="git.example.com:3000/owner/name",
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


def test_the_release_tag_fixture_is_internally_consistent() -> None:
    """The relations the identity guard reads, not the repository's current version.

    Same deadlock as the dispatch fixture above: pinning this to the committed version
    meant `just release` could never pass its own `just check`, because the bump lands
    before the check and the fixture still names the previous release. What the guards
    that consume this fixture actually need is that `ref`, `ref_name` and the exact
    stable spelling agree with each other, and that the SHA is a real object name.
    """
    event = _load_fixture("push-tag.json")
    assert event["event_name"] == "push"
    assert event["ref"] == f"refs/tags/{event['ref_name']}"
    assert re.fullmatch(r"v\d+\.\d+\.\d+", str(event["ref_name"])), event["ref_name"]
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
        "ATTESTATION_SUPPORTED": "true",
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


def _moves_an_alias(step: dict[str, Any]) -> bool:
    """One step, both spellings: a Git alias moved by the approved action, and a
    registry alias moved by a digest copy."""
    if str(step.get("uses", "")).startswith(APPROVED_ALIAS_ACTION):
        return True
    command = _uncommented(str(step.get("run", "")))
    return any(re.search(probe, command) for probe in ALIAS_MOVE_COMMANDS)


def _alias_moving_jobs(
    documents: dict[str, dict[str, Any]] | None = None,
) -> set[tuple[str, str]]:
    """Every place that points a mutable name at an artifact, from the parsed steps.

    Derived rather than enumerated, so an alias step added to a publisher shows up here
    without anyone editing a list.

    Composite actions are included, keyed by their path and `runs`. Their steps execute
    inside the calling job and hold its authority: `release.yaml`'s `finalize` holds
    `contents: write` and calls `./.github/actions/verified-bundle`, so an `imagetools
    create` planted there moved a registry alias from outside the grant, and every guard
    stayed green. A composite action can never be a registered finalizer -- registration
    is `(workflow, job)` -- so its presence here is always a violation.

    Passing `documents` restricts the scan to those workflows, which is what the scope
    attacks below plant against.
    """
    moving = set()
    for name, document in sorted((documents or _workflow_documents()).items()):
        for job_name, job in _jobs(document).items():
            for step in job.get("steps", []) or []:
                if _moves_an_alias(step):
                    moving.add((name, job_name))
    if documents is None:
        for path in sorted(ACTIONS.rglob("action.yml")):
            runs = _load_document(path).get("runs") or {}
            for step in runs.get("steps") or []:
                if _moves_an_alias(step):
                    moving.add((str(path.relative_to(PROJECT_ROOT)), "runs"))
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


def test_an_alias_concurrency_group_queues_rather_than_cancels() -> None:
    """A concurrency group on an alias job is a hazard unless it is told to queue.

    Sprint closure added `concurrency: {group: <workflow>-aliases, cancel-in-progress:
    false}` to both stable finalizers and ADR-0011 recorded that "every stable run
    queues behind every other". **GitHub does not do that.** Its documented default is
    `queue: single`: at most one run is pending per group, and "any existing pending job
    or workflow run in the same group is canceled and replaced". `cancel-in-progress`
    governs the *running* member only.

    So the group did the opposite of its purpose. Three overlapping tags cancelled a
    middle finalizer that had already published to PyPI and the registry irreversibly --
    creating no Release and moving no alias -- and `release-evidence`'s `!cancelled()`
    meant no run summary was written either. Anyone able to push a tag could freeze
    `latest` by pushing a throwaway one.

    The groups are gone. Ordering is carried entirely by re-deriving the tag set in the
    job that writes (`test_no_alias_move_consumes_an_ordering_decision_taken_in_another_job`),
    which the epic-closure red team confirmed it could not break. This guard keeps the
    hazard from returning: an alias-deciding job may carry a group only with
    `queue: max`, the option that actually queues. `actionlint` v1.7.12 does not know
    that key yet (upstream PR #661 adds it, unreleased), and its behaviour on Gitea is
    unknown, which is why the group was removed rather than corrected in place.
    """
    examined = 0
    for name, document in sorted(_workflow_documents().items()):
        for job_name, job in sorted(_jobs(document).items()):
            if not _ordering_steps(job):
                continue
            examined += 1
            concurrency = job.get("concurrency")
            if not isinstance(concurrency, dict):
                continue
            assert str(concurrency.get("queue", "")) == "max", (
                f"{name}: job {job_name!r} decides alias order behind a concurrency "
                f"group without `queue: max`. GitHub cancels the pending member of a "
                f"group rather than queueing it, so this loses a finalizer that has "
                f"already published irreversibly -- worse than no group at all."
            )
    assert examined, "no job decides alias order; this guard examined nothing"


# The scopes the finalizer authority split depends on, in both directions: the
# ref-writing job must not hold them, and the registry job must not hold `contents:
# write`. Denial is stated, never inferred.
AUTHORITY_SCOPES = ("contents", "packages", "id-token", "attestations")


def test_every_privileged_job_states_the_scopes_it_relies_on_being_denied() -> None:
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
    for name, document in sorted(_workflow_documents().items()):
        for job_name, job in sorted(_jobs(document).items()):
            # Every job that holds or can hold a credential, not the three registered
            # finalizers. The premise the explicit denials rest on -- that a permissive
            # runner grants what is omitted -- applies to all of them, and scoping the
            # requirement to the finalizers left seven privileged jobs relying on the
            # inference the declarations exist to remove. `publish-image.yaml`'s job
            # declared no `permissions:` at all.
            if not _is_credential_bearing(job):
                continue
            declared = job.get("permissions")
            assert isinstance(declared, dict), (
                f"{name}: job {job_name!r} can hold a credential and declares no "
                f"job-level permissions at all, which is the widest reading a "
                f"permissive runner can take"
            )
            examined += 1
            for scope in AUTHORITY_SCOPES:
                assert scope in declared, (
                    f"{name}: job {job_name!r} omits {scope!r}. Omission denies on "
                    f"GitHub and grants on a permissive Gitea; state it as `none`."
                )
    assert examined, "no job can hold a credential; this guard examined nothing"


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


# The composite action that is the trust boundary between the secret-free verifier and
# the credentialed publishers (CI-AR36). Matched on the path a `uses:` ends with, so a
# publisher cannot satisfy the rule with a similarly-named action of its own.
BOUNDARY_ACTION = "/verified-bundle"


def test_the_bundle_action_refuses_an_empty_artifact_name_before_downloading(
    tmp_path: Path,
) -> None:
    """An explicitly-passed empty string overrides a default rather than falling back to
    it, and every publisher passes `artifact-name: ${{ needs.verify.outputs.… }}`.

    With an empty `name`, `actions/download-artifact@v4` downloads *every* artifact in
    the run into one directory. The bundle revalidation then fails several steps later
    with "expected exactly one wheel", which reads as a packaging fault rather than a
    missing input -- so the diagnosis lands nowhere near the cause. Executed, and
    asserted to come first: a refusal after the download has already fetched the run.
    """
    steps = (_load_document(BUNDLE_ACTION).get("runs") or {}).get("steps") or []
    refusal = next(
        (
            index
            for index, step in enumerate(steps)
            if "artifact-name is empty" in str(step.get("run", ""))
        ),
        None,
    )
    assert refusal is not None, "the bundle action no longer refuses an empty name"
    download = next(
        index
        for index, step in enumerate(steps)
        if str(step.get("uses", "")).startswith("actions/download-artifact")
    )
    assert refusal < download, (
        "the empty-name refusal runs after the download it exists to prevent"
    )
    for empty in ("", "   "):
        completed, _ = _run_step(
            str(steps[refusal]["run"]), {"ARTIFACT_NAME": empty}, tmp_path
        )
        assert completed.returncode != 0, f"accepted an empty artifact name {empty!r}"
    completed, _ = _run_step(
        str(steps[refusal]["run"]), {"ARTIFACT_NAME": "verified-dist-v1"}, tmp_path
    )
    assert completed.returncode == 0, completed.stderr


ATTESTATION_ACTION = "actions/attest-build-provenance"
ATTESTATION_CAPABILITY = "attestation-supported"


def test_the_irrevocable_destination_names_an_environment() -> None:
    """PyPI is the one destination nothing can be withdrawn from: a version number is
    spent the moment it is accepted. Every mitigation around it is an identity re-check,
    and identity re-checks prove the tag still names the commit -- never that a person
    meant to release it.

    An `environment:` is where a human can be required, and it is also what lets the
    PyPI trusted publisher be constrained to one workflow: without an environment claim
    to match on, *any* workflow in this repository that obtains `id-token: write` can
    mint a PyPI-scoped token.

    **What this cannot check**: whether that environment has required reviewers, and
    whether PyPI is configured to demand the claim. Both are settings outside the tree
    and this guard passes with neither set. Reviewers were declined at E008 closure
    (sole-developer project); binding the trusted publisher to the environment claim was
    not, and it is the half that costs nothing operationally -- it is latent only because
    PyPI publication is currently disabled. `docs/operational.md` records both decisions
    rather than leaving this declaration to imply protection it does not yet have.
    """
    examined = 0
    for name, job in sorted(_jobs(_load_workflow(RELEASE_WORKFLOW)).items()):
        if not any(
            str(step.get("uses", "")).startswith("pypa/gh-action-pypi-publish")
            and not (step.get("with") or {}).get("repository-url")
            for step in job.get("steps") or []
        ):
            continue
        examined += 1
        assert job.get("environment"), (
            f"release.yaml: {name!r} uploads to PyPI without naming an environment, so "
            f"there is nowhere to require a reviewer and nothing for the trusted "
            f"publisher to constrain on"
        )
    assert examined, "no job uploads to PyPI; this guard examined nothing"


def test_the_released_distributions_are_attested_on_every_release() -> None:
    """The Release's own evidence proves nothing against whoever can write the Release.

    `SHA256SUMS` and `build-manifest.json` are attached with `allow-updates: true` by a
    job holding `contents: write` -- which is right, because a stranded run must be
    resumable at an immutable identity -- so the evidence has no authority independent
    of the authority that could forge it. An attestation does.

    **The property this asserts is reachability, and that is the correction.** The first
    version of this fix put the attestation inside `publish-package-pypi`, which is
    gated on `PUBLISH_PACKAGE_PYPI` -- default `false`. In the shipped default
    configuration nothing was attested, and the guard passed, because it proved the step
    existed, was ordered before the upload and held the right scope. It never asked
    whether the step runs. Setting the attesting job to `if: false` left the suite green.
    That is the epic's signature defect -- a correct rule over the wrong set -- appearing
    inside the remediation written to close it.

    So: the attesting job may be gated on a HOST CAPABILITY and on nothing else. Not a
    `PUBLISH_*` toggle, not a destination's enabled state, not a forge name. Gitea has no
    attestation store, and that is the only reason a release may go unattested.
    """
    document = _load_workflow(RELEASE_WORKFLOW)
    jobs = _jobs(document)
    attesting = {
        name: job
        for name, job in jobs.items()
        if any(
            str(step.get("uses", "")).startswith(ATTESTATION_ACTION)
            for step in job.get("steps") or []
        )
    }
    assert attesting, (
        "no job attests the released distributions; the Release evidence has no "
        "authority independent of the `contents: write` that could replace it"
    )
    for name, job in sorted(attesting.items()):
        condition = str(job.get("if", ""))
        assert ATTESTATION_CAPABILITY in condition, (
            f"release.yaml: {name!r} gates attestation on {condition!r}. Only the host "
            f"capability may gate it -- Gitea has no attestation store."
        )
        assert (
            "PUBLISH_" not in condition and "enabled-destinations" not in condition
        ), (
            f"release.yaml: {name!r} gates attestation on a publication toggle "
            f"({condition!r}), so a release with that destination off is unattested. "
            f"An attestation is evidence, not a destination that can be switched off."
        )
        assert (job.get("permissions") or {}).get("attestations") == "write", (
            f"release.yaml: {name!r} runs the attestation action without the scope it "
            f"needs, so it fails at the point of use"
        )
        # And nothing irreversible may precede it in its own job: an attestation made
        # after an upload cannot protect the upload.
        steps = job.get("steps") or []
        attest_at = next(
            index
            for index, step in enumerate(steps)
            if str(step.get("uses", "")).startswith(ATTESTATION_ACTION)
        )
        shipping = next(
            (index for index, step in enumerate(steps) if _is_publishing_step(step)),
            None,
        )
        assert shipping is None or attest_at < shipping, (
            f"release.yaml: {name!r} ships at step {shipping} before attesting at "
            f"{attest_at}"
        )

    # Reachability is not only about the `if:`. The Release must wait for it, or a
    # failed attestation would leave a Release published with unsigned evidence.
    for finalizer in sorted(_finalizers(RELEASE_WORKFLOW)):
        if "alias" in finalizer:
            continue
        waits_on = set(jobs[finalizer].get("needs") or [])
        assert waits_on & set(attesting), (
            f"release.yaml: {finalizer!r} creates the Release without waiting for "
            f"{sorted(attesting)}, so the Release can carry evidence never signed"
        )


def test_a_package_upload_never_authenticates_as_the_pusher() -> None:
    """A token upload's identity must come from the credential, not from whoever pushed.

    Both forge index publishers passed `user: ${{ github.actor }}` alongside
    `FORGE_PACKAGE_TOKEN`. It works -- Gitea's basic auth resolves a token supplied as
    the password and ignores the username -- but the value varies per push and is
    unrelated to whoever minted the token, so the upload's apparent identity became a
    property of who triggered the run. `__token__` is the convention every Python index
    uses for this, and it is a constant.

    Scope is every package-upload step in every governed definition, so a third index
    added later is covered without editing this.
    """
    examined = 0
    for definition, container, steps in _governed_step_groups():
        for step in steps:
            if not str(step.get("uses", "")).startswith("pypa/gh-action-pypi-publish"):
                continue
            supplied = str((step.get("with") or {}).get("user", ""))
            if not supplied:
                continue  # trusted publishing passes no user at all, which is stronger
            examined += 1
            assert "github.actor" not in supplied, (
                f"{definition}: {container!r} uploads a package as `{supplied}`. The "
                f"identity of a token upload is the token's, not the pusher's; use "
                f"`__token__`."
            )
    assert examined, "no package upload supplies a user; this guard examined nothing"


def test_every_publisher_revalidates_the_bundle_before_it_logs_in_or_uploads() -> None:
    """CI-AR36, over every publisher rather than the one that attaches the Release.

    "Every publisher downloads the verified bundle, checks SHA256SUMS, revalidates
    build-manifest.json, and matches the source SHA and version it believes it is
    publishing -- before any login or upload" is the boundary between the secret-free
    verifier and the jobs holding credentials. Six publishers implement it and, until
    this guard, one was checked: the arch review replaced `dev.yaml`'s
    `publish-package-forge` revalidation with a bare `actions/download-artifact`, so the
    wheel reached the forge index with no checksum recheck, no manifest validation and
    no identity match -- and the suite was unchanged.

    Ordering is asserted, not just presence. Revalidating *after* the login satisfies
    "the step exists" while the credential is already on the runner when the unverified
    artifact arrives, which is the property the boundary is for.

    Scope is derived from capability: any step-based publisher that reaches an upload.
    The two alias finalizers are excluded because they ship no artifact -- they point a
    name at a digest that is already published.
    """
    examined = 0
    for path in sorted(WORKFLOWS.glob("*.yaml")):
        for job_name, job in sorted(_publishers(_load_workflow(path)).items()):
            steps = job.get("steps") or []

            def _first(
                predicate: Any, steps: list[dict[str, Any]] = steps
            ) -> int | None:
                return next(
                    (index for index, step in enumerate(steps) if predicate(step)), None
                )

            upload = _first(_is_publishing_step)
            if upload is None:
                continue
            examined += 1
            bundle = _first(
                lambda step: (
                    str(step.get("uses", "")).rstrip("/").endswith(BOUNDARY_ACTION)
                )
            )
            assert bundle is not None, (
                f"{path.name}: publisher {job_name!r} uploads without revalidating the "
                f"verified bundle. CI-AR36 is the trust boundary; a publisher that "
                f"skips it ships whatever the artifact store handed it."
            )
            assert bundle < upload, (
                f"{path.name}: publisher {job_name!r} revalidates the bundle at step "
                f"{bundle} but uploads at step {upload}"
            )
            login = _first(
                lambda step: str(step.get("uses", "")).startswith(REGISTRY_LOGIN_ACTION)
            )
            assert login is None or bundle < login, (
                f"{path.name}: publisher {job_name!r} logs in at step {login} before "
                f"revalidating at step {bundle}. The credential is on the runner before "
                f"the artifact is known to be the verified one."
            )
    assert examined, "no publisher uploads anything; this guard examined nothing"


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


DESTINATION_KEY = re.compile(r'"([a-z][a-z-]*)"\s*:\s*"')


def _destination_vocabulary(path: Path) -> set[str]:
    """The destination keys this workflow's plan job actually emits.

    Read from the `enabled-destinations=` line the step prints, which is the single
    producer of the set (ADR-0011). Everything downstream spells these keys by hand --
    three times in release.yaml, and dozens of times in this module -- and nothing
    derived them from here until now.
    """
    for job in _jobs(_load_workflow(path)).values():
        for step in job.get("steps") or []:
            body = str(step.get("run", ""))
            if "enabled-destinations=" not in body:
                continue
            emitted = body.split("enabled-destinations=", 1)[1].split("}", 1)[0]
            return set(DESTINATION_KEY.findall(emitted))
    return set()


def test_the_finalizer_gate_binds_every_destination_to_the_job_that_serves_it() -> None:
    """Two defects, one coupling.

    The gate's `PUBLISHER_RESULTS` maps each destination key to a `needs.<job>.result` by
    hand, and the vocabulary itself is spelled by hand everywhere downstream of the one
    step that emits it. The existing guard asserted each publisher's result appears
    *somewhere* in the gate's env, never that a key is bound to the job that ships that
    destination: rebinding `image-dockerhub` to `needs.publish-package-forge.result`
    left the suite green.

    So: the gate's keys must be exactly the vocabulary the plan job emits, and where a
    job's own definition gates on a destination key -- `fromJSON(...)['package-pypi']` in
    its `if:`, or in an input it passes down -- the gate must bind that key to that job.
    That covers every toggle-gated destination, which are the ones a mis-binding can
    actually hide. `image-forge` and `attestation` are unconstrained here because no job
    gates on them: the first is the channel and the second is a host capability.
    """
    examined = 0
    for path in sorted(WORKFLOWS.glob("*.yaml")):
        vocabulary = _destination_vocabulary(path)
        if not vocabulary:
            continue
        gates = _gate_steps(path)
        assert gates, f"{path.name}: emits a destination set and no gate reads it"
        for job_name, step in gates.items():
            results = str((step.get("env") or {}).get("PUBLISHER_RESULTS", ""))
            bound = set(DESTINATION_KEY.findall(results))
            examined += 1
            assert bound == vocabulary, (
                f"{path.name}: the gate in {job_name!r} binds {sorted(bound)} but the "
                f"plan job emits {sorted(vocabulary)}. The set has one producer."
            )
            # And each key must name the job that actually serves it.
            for key in sorted(vocabulary):
                serving = {
                    name
                    for name, job in _jobs(_load_workflow(path)).items()
                    if f"['{key}']" in json.dumps(job)
                }
                if not serving:
                    continue
                match = re.search(
                    rf'"{re.escape(key)}"\s*:\s*"\$\{{\{{\s*needs\.([a-z0-9-]+)\.result',
                    results,
                )
                assert match and match.group(1) in serving, (
                    f"{path.name}: the gate binds {key!r} to "
                    f"{match.group(1) if match else 'nothing'!r}, but the job that gates "
                    f"on that destination is {sorted(serving)}"
                )
    assert examined, "no workflow has both a destination set and a gate"


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


def test_every_finalization_gate_is_the_same_body() -> None:
    """The sprint's third copied body, and the only one that shipped without a same-body
    guard.

    The forge-coordinate derivation (two copies) and the stable-tag re-check (four and
    three copies) each carry one. The finalization gate is the largest copied body and
    the one that decides whether an alias moves, and its twelve input-validation tests
    are all bound to `release.yaml`. Deleting the "enabled set names no destination at
    all", "no publisher result was supplied" and "results were supplied for" refusals
    from `dev.yaml`'s copy alone left the suite unchanged.

    That also made ADR-0011's "every property the deleted pytest files proved is now
    proven the same way" true of the stable channel and false of the development one --
    prose overstating its own coverage. With the bodies pinned identical, executing one
    copy is a proof about both, and the sentence is true again.
    """
    bodies = {
        (path.name, job_name): _uncommented(str(step.get("run", "")))
        for path in sorted(WORKFLOWS.glob("*.yaml"))
        for job_name, step in _gate_steps(path).items()
    }
    assert bodies, "no finalization gate on disk; this guard examined nothing"
    distinct = set(bodies.values())
    assert len(distinct) == 1, (
        f"{len(distinct)} different finalization gates are in use across "
        f"{sorted(bodies)}. The channel bindings differ; the decision must not."
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
        "attest": "success",
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
                # Enabled here because the GitHub case is the one with an attestation
                # store; the unsupported (Gitea) case has its own test below.
                "attestation": "enabled",
            }
        )
    }


def test_an_attestation_that_did_not_happen_stops_finalization() -> None:
    """The attestation is a destination in ADR-0011's sense, and this is why.

    It began as a step inside `publish-package-pypi`, which is gated on
    PUBLISH_PACKAGE_PYPI -- default false -- so by default nothing was attested and the
    guard covering it still passed, because it asserted the step existed rather than
    that it runs. Modelling the attestation as a destination puts it under the gate that
    already knows the difference between "skipped because this host has none" and
    "skipped because something upstream died".
    """
    completed = _run_gate(RELEASE_WORKFLOW, _stable_bindings(attest="skipped"))
    assert completed.returncode != 0, "an enabled attestation that never ran finalized"
    assert "attestation" in completed.stderr

    # And absent by host capability is legitimate: Gitea has no attestation store, so a
    # skip there must finalize exactly as an absent forge package index does.
    bindings = _stable_bindings(attest="skipped")
    enabled = json.loads(bindings["needs.plan.outputs.enabled-destinations"])
    enabled["attestation"] = "unsupported"
    bindings["needs.plan.outputs.enabled-destinations"] = json.dumps(enabled)
    completed = _run_gate(RELEASE_WORKFLOW, bindings)
    assert completed.returncode == 0, completed.stderr


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
                # `ref-tag` is what the aliases are computed *from*. ADR-0006 claimed
                # this guard asserted the hyphenated inputs, and it asserted two of the
                # three: a step passing `update-minor` and `ignore-prerelease` and no
                # `ref-tag` passed, and the action would then move aliases against
                # whatever it defaults to. It must also resolve through the plan job's
                # released tag rather than a literal, or the alias is computed from
                # something other than the identity this run is publishing.
                # `tag` is the action's REQUIRED input at `@v2` -- the tag the major
                # and minor are extracted from. An earlier version of this guard
                # required `ref-tag`, which is the OPTIONAL override for what the
                # floating tags point at and whose documented default is the value of
                # `tag`. So it demanded the optional input and never the mandatory one,
                # and the first release to reach this step died on `Input required and
                # not supplied: tag` -- after the Release had already been created.
                #
                # Reading the manifest confirmed both names exist. Existing is not the
                # same as being the one that is required; that distinction is what this
                # release path has now cost twice.
                release_tag = str(inputs.get("tag", ""))
                assert release_tag, (
                    f"{path.name}: {job_name!r} moves aliases without passing `tag`, "
                    f"which `{APPROVED_ALIAS_ACTION}@v2` requires"
                )
                assert "needs.plan.outputs.release-tag" in release_tag, (
                    f"{path.name}: {job_name!r} passes tag={release_tag!r}, which is "
                    f"not the release tag the plan job resolved"
                )
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


def test_the_release_step_never_asks_the_forge_to_create_its_own_trigger() -> None:
    """`commit:` makes the Release action create the tag at that SHA.

    This workflow is triggered by the tag push, so `refs/tags/vX.Y.Z` exists before the
    job starts. Passing `commit:` asks the forge to create a ref the run depends on
    already existing, and the first real release died on exactly that:
    `HTTP 422 Unprocessable Entity: {"message":"Reference already exists"}` -- after the
    image had been published and attested, with the Release and every alias unmade.

    Nothing is lost by omitting it: the tag identifies the Release, it already points at
    the released commit, and the re-check immediately above re-proves that it still
    peels to `source-sha`.
    """
    steps = _jobs(_load_workflow(RELEASE_WORKFLOW))["finalize"]["steps"]
    creating = [
        step
        for step in steps
        if str(step.get("uses", "")).startswith(APPROVED_RELEASE_ACTION)
    ]
    assert creating, "no step creates the Release"
    for step in creating:
        inputs = step.get("with") or {}
        assert "commit" not in inputs, (
            "the Release step passes `commit:`, which creates the tag. The tag is this "
            "workflow's trigger and already exists; the forge answers 422."
        )
        assert inputs.get("tag"), "the Release must name the tag it attaches to"


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
        # `_alias_moving_jobs` keys composite actions by their repo-relative path, not
        # by a workflow filename, so composing `WORKFLOWS / path` raised
        # `FileNotFoundError: .../.github/workflows/.github/actions/...` -- a crash that
        # reads as a broken test rather than a caught violation, which is how a real one
        # gets triaged as flake. Composite actions carry no Docker Hub condition of
        # their own; the job that calls them does, and that job is examined here.
        if job_name == "runs":
            continue
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
    moved = [line for line in rendered.splitlines() if line.startswith("- Moved:")]
    unconfirmed = [
        line for line in rendered.splitlines() if line.startswith("- **Unconfirmed**:")
    ]
    assert any("ghcr.io/owner/name:latest" in line for line in moved), (
        f"the aliases that DID move are unreported: {rendered!r}"
    )
    assert not any("docker.io/owner/name" in line for line in moved), (
        "an alias that failed is reported as moved"
    )
    # MEDIUM-1: `imagetools create -t a -t b` writes each tag in turn, so a failure part
    # way leaves names this step may have moved and cannot confirm. Absent from the
    # record they read as untouched, which is the reconciliation reporting the opposite
    # of the truth -- so they are named as unconfirmed rather than omitted.
    assert any("docker.io/owner/name" in line for line in unconfirmed), (
        f"a name this step may have written is missing from the record: {rendered!r}"
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


def _irreversible_jobs(path: Path) -> set[str]:
    """Jobs doing something no later step can undo: ship an artifact, create the
    Release, or point a mutable name at one.

    The count of these is what "one re-check before each irreversible act" means, so it
    is derived rather than written down. The two guards below asserted 4 and 3 by hand:
    an irreversible act added *without* a re-check left the count unchanged and passed,
    which is the reach the literal was supposed to supply, and the number went red for
    the wrong reason the day a destination was added.
    """
    document = _load_workflow(path)
    shipping = {
        name
        for name, job in _jobs(document).items()
        if any(_is_publishing_step(step) for step in job.get("steps") or [])
        # An attestation is a signed public statement about an identity, written to a
        # store this repository cannot retract. It is as irreversible as an upload, and
        # it therefore re-reads the identity immediately before making it.
        or (job.get("permissions") or {}).get("attestations") == "write"
    }
    aliases = {job for workflow, job in _alias_moving_jobs() if workflow == path.name}
    return shipping | aliases


def test_every_stable_tag_recheck_is_the_same_body() -> None:
    """One relation, copied into four steps, asserted to be one copy.

    The stable channel re-reads the tag immediately before each irreversible act: the
    two package uploads, the Release, and the image aliases. Duplication is the price
    of keeping the decision in the workflow -- so the guard is that the copies cannot
    diverge. A single edited copy fails here rather than reaching a registry.
    """
    refusers = _membership_steps(RELEASE_WORKFLOW)["refusers"]
    expected = _irreversible_jobs(RELEASE_WORKFLOW)
    assert len(refusers) == len(expected), (
        f"release.yaml has {len(refusers)} pre-write tag re-checks for "
        f"{len(expected)} irreversible acts ({', '.join(sorted(expected))}); there is "
        f"one before each"
    )
    assert len(set(refusers)) == 1, "the stable tag re-checks have diverged"
    assert all(STABLE_RECHECK_MARKER in body for body in refusers)


def test_every_suppression_recheck_is_the_same_body() -> None:
    """The development channel's copies of the same relation, under the same rule."""
    steps = _membership_steps(DEV_WORKFLOW)
    assert len(steps["emitters"]) == 1, "the suppression conclusion has one producer"
    expected = _irreversible_jobs(DEV_WORKFLOW)
    assert len(steps["refusers"]) == len(expected), (
        f"dev.yaml has {len(steps['refusers'])} pre-write suppression re-checks for "
        f"{len(expected)} irreversible acts ({', '.join(sorted(expected))}); there is "
        f"one before each"
    )
    assert len(set(steps["refusers"])) == 1, "the suppression re-checks have diverged"


def _run_stable_recheck(
    repository: Path,
    tag: str,
    commit: str | None = None,
    default_branch_ref: str = "main",
) -> Any:
    body = _membership_steps(RELEASE_WORKFLOW)["refusers"][0]
    completed, _ = _run_step(
        body,
        {
            "DEFAULT_BRANCH_REF": default_branch_ref,
            "RELEASE_TAG": tag,
            "SOURCE_SHA": commit or _git(repository, "rev-parse", "HEAD"),
        },
        cwd=repository,
    )
    return completed


def test_the_stable_recheck_refuses_a_tag_that_left_the_default_branch(
    tagged_repository: Path,
) -> None:
    """The reachability leg, which the pre-upload re-check did not carry.

    The plan job proves the commit is reachable from the protected default branch, and
    every re-check then re-proved only the tag relation: the tag is annotated, exact,
    and still peels to this commit. All three survive a force-push to the branch that
    removes the history the release was cut from -- the tag object is untouched, so the
    old body passed and the publisher uploaded from history the branch no longer has.

    `v2.0.0` in the fixture is exactly that shape: annotated, exact, peeling correctly,
    and on a side branch `main` never took.
    """
    side_commit = _git(tagged_repository, "rev-parse", "v2.0.0^{commit}")
    completed = _run_stable_recheck(tagged_repository, "v2.0.0", commit=side_commit)
    assert completed.returncode != 0, (
        "a tag on history the default branch never took was accepted for publication"
    )
    assert "no longer reachable" in completed.stderr, completed.stderr


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
    assert (
        "results were supplied for attestation, package-forge, package-pypi"
        in completed.stderr
    )


def test_an_empty_enabled_set_blocks_rather_than_finalizing_nothing() -> None:
    bindings = {
        f"needs.{job}.result": "skipped"
        for job in (
            "publish-image",
            "publish-package-forge",
            "publish-package-pypi",
            "attest",
        )
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
            "attestation": "enabled",
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
        "attestation",
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
