"""What an untrusted contributor's branch can reach.

BL-E008-010 phase 3. The verifier is the one definition a fork's code runs inside, so it
holds no secret, no publisher permission and no persistent runner -- and the guards derive
the fork-facing set from the EVENTS a definition declares, never from a list of filenames.
A file added tomorrow that declares pull_request is fork-facing whether or not anyone
remembered to add it to a list.
"""

from __future__ import annotations

import json
import re

from tests.ci.support import (
    CI_WORKFLOW,
    VERIFIER_REFERENCE,
    VERIFY_WORKFLOW,
    WORKFLOWS,
    _action_references,
    _fork_facing_definitions,
    _fork_facing_workflow_names,
    _is_credential_bearing,
    _jobs,
    _load_fixture,
    _load_workflow,
    _steps,
)

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
