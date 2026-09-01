from __future__ import annotations

import json
import re
from pathlib import Path

import tomllib
import yaml

PROJECT_ROOT = Path(__file__).parents[2]
WORKFLOWS = PROJECT_ROOT / ".github" / "workflows"
FIXTURES = Path(__file__).parent / "fixtures" / "workflows"
CI_WORKFLOW = WORKFLOWS / "ci.yaml"
VERIFY_WORKFLOW = WORKFLOWS / "verify-build.yaml"
GOVERNED_WORKFLOWS = (CI_WORKFLOW, VERIFY_WORKFLOW)
APPROVED_ACTION_OWNERS = {"actions", "docker", "pypa", "LiquidLogicLabs"}


def _load_workflow(path: Path) -> dict[str, object]:
    # BaseLoader keeps GitHub's `on` key as a string instead of applying YAML 1.1's
    # obsolete yes/no boolean coercion.
    document = yaml.load(path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    assert isinstance(document, dict)
    return document


def _load_fixture(name: str) -> dict[str, object]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _external_action_references(path: Path) -> list[str]:
    return [
        reference
        for reference in re.findall(
            r"^\s*uses:\s*([^\s#]+)",
            path.read_text(encoding="utf-8"),
            re.MULTILINE,
        )
        if not reference.startswith("./")
    ]


def test_pull_request_adapter_is_minimal_and_fork_safe() -> None:
    workflow = _load_workflow(CI_WORKFLOW)
    triggers = workflow["on"]
    jobs = workflow["jobs"]

    assert isinstance(triggers, dict)
    assert set(triggers) == {"pull_request"}
    assert triggers["pull_request"] == {"branches": ["main"]}
    assert workflow["permissions"] == {"contents": "read"}
    assert workflow["concurrency"] == {
        "group": "${{ github.workflow }}-pr-${{ github.event.pull_request.number }}",
        "cancel-in-progress": "true",
    }
    assert isinstance(jobs, dict)
    assert set(jobs) == {"plan", "verify"}

    plan = jobs["plan"]
    verify = jobs["verify"]
    assert plan["runs-on"] == "ubuntu-24.04"
    assert plan["permissions"] == {"contents": "read"}
    assert verify == {
        "name": "Run governed verifier",
        "needs": "plan",
        "permissions": {"contents": "read"},
        "uses": "./.github/workflows/verify-build.yaml",
        "with": {
            "channel": "ci",
            "package-version": "${{ needs.plan.outputs.package-version }}",
            "source-sha": "${{ needs.plan.outputs.source-sha }}",
        },
    }

    source = CI_WORKFLOW.read_text(encoding="utf-8")
    assert "pull_request_target" not in source
    assert "github.event.pull_request.head.sha" in source
    assert "persist-credentials: false" in source
    assert "tomllib.loads" in source
    assert "secrets:" not in source
    for implementation_detail in (
        "poetry build",
        "pytest",
        "ruff-check",
        "build-manifest",
        "docker build",
        "upload-artifact",
    ):
        assert implementation_detail not in source


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
    assert set(workflow["jobs"]) == {
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


def test_fork_verification_has_no_publisher_capability_or_persistent_runner() -> None:
    workflow = _load_workflow(VERIFY_WORKFLOW)
    assert workflow["permissions"] == {"contents": "read"}
    for job in workflow["jobs"].values():
        assert job["runs-on"] == "ubuntu-24.04"
        assert "permissions" not in job

    source = VERIFY_WORKFLOW.read_text(encoding="utf-8")
    for forbidden in (
        "secrets:",
        "id-token: write",
        "packages: write",
        "attestations: write",
        "docker/login-action@",
        "actions/cache@",
        "runs-on: self-hosted",
        "secrets: inherit",
    ):
        assert forbidden not in source


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


def test_local_wrapper_never_runs_act_against_the_working_tree() -> None:
    """Running act against this repository destroyed it on 2026-09-01.

    `~/.actrc` sets `--bind`, so act mounts the host directory as the container workspace
    rather than copying it, and verify-build.yaml's first job runs `actions/checkout` with
    a `ref:`. checkout deletes the workspace contents before it discovers it cannot fetch
    the ref -- taking `.git`, and therefore every local commit, with it. The wrapper must
    therefore hand act a throwaway clone and never the real tree.
    """
    wrapper = (PROJECT_ROOT / "docker" / "act-build.sh").read_text(encoding="utf-8")

    # Assert against the executable lines only. The header comment explains why
    # --no-hardlinks matters, and an earlier version of this test searched the whole file
    # -- so deleting the flag from the command left the guard green, satisfied by the
    # prose describing it. A guard that a comment can satisfy is not a guard.
    code = "\n".join(
        line for line in wrapper.splitlines() if not line.lstrip().startswith("#")
    )

    assert "mktemp -d" in code, "wrapper must create a disposable working directory"
    clone = [line for line in code.splitlines() if line.startswith("git clone")]
    assert len(clone) == 1, f"expected exactly one git clone invocation, got {clone}"
    # Without --no-hardlinks the clone's objects are hardlinked into this repository's
    # object store, so a destructive checkout inside the container can still reach them.
    assert "--no-hardlinks" in clone[0], (
        f"the clone must not share an object store with this repository: {clone[0]}"
    )
    assert "--local" in clone[0], "the clone must carry local commits, not fetch a remote"
    # The clone must be proven to be somewhere else before act is invoked.
    assert "refusing to run" in code, "wrapper must verify the clone is not the repo"
    assert "trap " in code and "rm -rf" in code, "the clone must be cleaned up"

    # act must be invoked only after the working directory has moved to the clone.
    act_at = code.index("act workflow_dispatch")
    assert code.index("CLONE_ROOT=") < act_at, "act invoked before the clone exists"
    assert code.index('cd "$CLONE_ROOT"') < act_at, (
        "act must run from the disposable clone, not the repository root"
    )


def test_all_workflow_steps_are_independent_of_the_act_environment() -> None:
    for path in WORKFLOWS.glob("*.yaml"):
        workflow = _load_workflow(path)
        for job in workflow.get("jobs", {}).values():
            for step in job.get("steps", []):
                assert "ACT" not in str(step.get("if", "")), path
                assert "ACT" not in str(step.get("run", "")), path


def test_governed_actions_use_approved_owners_and_floating_major_aliases() -> None:
    for path in GOVERNED_WORKFLOWS:
        for reference in _external_action_references(path):
            action, version = reference.rsplit("@", 1)
            owner = action.split("/", 1)[0]
            assert owner in APPROVED_ACTION_OWNERS, (
                f"{path}: {owner} requires an approved ADR or architecture update"
            )
            assert re.fullmatch(r"v[0-9]+", version), (
                f"{path}: {reference} must use the maintained floating major alias"
            )


def test_artifact_actions_remain_on_the_both_forge_v4_pair() -> None:
    references = _external_action_references(VERIFY_WORKFLOW)
    for action in ("actions/upload-artifact", "actions/download-artifact"):
        assert all(
            reference == f"{action}@v4"
            for reference in references
            if reference.startswith(f"{action}@")
        )
    assert not any("${{" in reference for reference in references)


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
    metadata = tomllib.loads(
        (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )
    assert event["inputs"]["package-version"] == metadata["tool"]["poetry"]["version"]
