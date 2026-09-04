"""The shape of the workflow set: who owns an event, who is called, who blocks whom.

BL-E008-010 phase 3. Two classes of file and nothing else -- a reusable workflow another
one calls and which owns no automatic event, and a channel that owns events and is called
by nobody. Anything else is a defect: a file nothing can reach reads as governed while
doing nothing, and a called file that also self-triggers runs twice for one event.

The guards here assert a PARTITION rather than a count. An earlier form asserted "exactly
five files", which is satisfied by any five, and CI-AR5 in the spine named four while five
shipped -- the missing one holding every registry credential.
"""

from __future__ import annotations

import fnmatch
import itertools
import json
from typing import Any

import pytest

from tests.ci.support import (
    ACT_BRANCH,
    GOVERNED_DEFINITIONS,
    PROJECT_ROOT,
    PUBLISH_IMAGE_WORKFLOW,
    VERIFIER_REFERENCE,
    VERIFY_WORKFLOW,
    WORKFLOWS,
    _action_references,
    _declared_events,
    _jobs,
    _load_fixture,
    _load_workflow,
    _publishers,
    _transitive_needs,
    _trigger_surface,
    _workflow_documents,
)


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
    """Epic 7 deleted test.yaml and nothing replaced it, so pushes ran zero tests. This
    guard was written while that was still true, and it asserted the conditional
    invariant -- any workflow that reacts to an event must reach the verifier before
    anything that ships -- so that it passed vacuously rather than sitting permanently
    red, which is how a gate gets disabled instead of fixed.

    It is no longer vacuous. `dev.yaml` reacts to `push` on the default branch and
    `release.yaml` to `v*` tags, and both are examined here: every publisher in each must
    depend transitively on the governed verifier. The docstring said otherwise for two
    stories after that stopped being true.
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


def test_no_workflow_calls_a_local_workflow_or_action_that_does_not_exist() -> None:
    # Deleting the legacy workflows left every `uses:` pointing at them dangling. GitHub
    # fails such a call at run time, not at lint time, so nothing else here catches it.
    # Parsed, not line-matched. `uses: "./.github/workflows/x.yaml"` -- a perfectly
    # ordinary quoted reference -- does not match a `uses:\s*(\./...)` regex, so a
    # dangling local call written that way went unchecked. `_action_references` exists
    # for exactly this and says so in its own docstring.
    for path in GOVERNED_DEFINITIONS:
        for reference in _action_references(path):
            if not reference.startswith("./"):
                continue
            target = PROJECT_ROOT / reference.removeprefix("./")
            if target.is_dir():
                target = target / "action.yml"
            assert target.exists(), f"{path.name}: `uses: {reference}` does not exist"


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
    assert not ACT_BRANCH.search(VERIFY_WORKFLOW.read_text(encoding="utf-8"))

    event = _load_fixture("workflow-dispatch.json")
    assert event["event_name"] == "workflow_dispatch"
    assert event["inputs"] == {
        "channel": "ci",
        "package-version": "0.1.3",
        "source-sha": event["sha"],
    }


def test_every_gate_job_blocks_the_distribution_job() -> None:
    """A gate that does not block the build is decorative.

    Scope is derived: any job fanning out from `source-integrity` is a gate, so a gate
    added later is covered without editing this test. Written after adding the `mypy` job
    and forgetting to add it to `distribution.needs` -- it ran, it could fail, and nothing
    downstream cared.
    """
    jobs = _jobs(_load_workflow(VERIFY_WORKFLOW))
    # Every job except the one they all block. Derived from the graph rather than from
    # the shape of one `needs:` value: "gates" used to mean `needs: [source-integrity]`
    # exactly, so a `pip-audit` job with `needs: [source-integrity, poetry-lock]` and a
    # body of `exit 1` was outside the set, `assert gates` stayed non-empty on the other
    # eight, and a permanently-failing gate did not block the build.
    #
    # Transitive, because blocking through another gate blocks all the same -- and it is
    # the shape a longer chain would take.
    blocking = _transitive_needs(jobs, "distribution")
    assert blocking, "distribution depends on nothing; this guard examined nothing"
    unblocked = set(jobs) - {"distribution"} - blocking
    assert not unblocked, (
        f"jobs that can fail without blocking the build: {sorted(unblocked)}. A gate "
        f"that does not block the build is decorative."
    )


def test_the_image_publisher_is_reusable_only_like_the_verifier() -> None:
    """Prep finding P2: this is a fifth workflow file, and the topology assertion in
    story E008-S01-004 expects it -- distinguished as reusable-only, exactly as
    verify-build.yaml already is. A trigger added here would make it a sixth entry point.
    """
    document = _load_workflow(PUBLISH_IMAGE_WORKFLOW)
    assert set(document["on"]) == {"workflow_call"}
    assert set(document["on"]["workflow_call"]["outputs"]) >= {"digest", "platforms"}


GLOB_METACHARACTERS = frozenset("*?[]+!")


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
