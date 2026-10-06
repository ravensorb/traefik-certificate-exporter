"""ADR-0021: one authoritative forge classifier and coordinate-projection contract.

The classifier is not a Python module -- `test_no_publication_decision_lives_in_a_python_module`
(`tests/ci/test_action_policy.py`) enforces the opposite of that: E008 deleted
`scripts/forge_coordinates.py` deliberately, and a resurrected module fails the moment a
workflow calls it. The "one authoritative function" ADR-0021 requires is therefore the single
`Derive forge coordinates` step each of `dev.yaml` and `release.yaml` runs once per workflow run,
with every other job in the same file consuming its outputs through `needs.plan.outputs.*` rather
than recomputing them. This module proves the two copies are the same function body, and
exercises its table-driven positive/negative/normalization cases by executing the real `run:`
body -- not by reading it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.ci.support import (
    DEV_WORKFLOW,
    RELEASE_WORKFLOW,
    _load_workflow,
    _run_step,
    _step_with_id,
    _uncommented,
)

DERIVATION_STEP_ID = "forge"


def _derivation_body(path: Path) -> str:
    return str(_step_with_id(path, DERIVATION_STEP_ID)["run"])


def test_the_classifier_body_is_identical_in_both_channels() -> None:
    """Two copies, one function. `dev.yaml`'s and `release.yaml`'s `plan` jobs each run
    the derivation once per workflow run; ADR-0021 is violated the moment the two copies
    can disagree on the same inputs, not merely by the existence of two copies -- so what
    is asserted here is that they cannot.
    """
    dev_body = _uncommented(_derivation_body(DEV_WORKFLOW))
    release_body = _uncommented(_derivation_body(RELEASE_WORKFLOW))
    assert dev_body == release_body, (
        "dev.yaml and release.yaml derive forge coordinates with different bodies; "
        "two implementations of 'derive coordinates from context' can disagree even "
        "when both pass their own tests (ADR-0021)"
    )


def test_forge_registry_override_is_retired() -> None:
    """`FORGE_REGISTRY` does not return implicitly (CI-AR6, ARCHITECTURE-SPINE.md). No
    operator-supplied value participates in coordinate derivation; the only accepted
    inputs are `github.server_url` and `github.repository`.
    """
    for path in (DEV_WORKFLOW, RELEASE_WORKFLOW):
        body = _derivation_body(path)
        assert "FORGE_REGISTRY" not in body, (
            f"{path.name}: references the retired FORGE_REGISTRY override (ADR-0021)"
        )


@pytest.mark.parametrize("path", [DEV_WORKFLOW, RELEASE_WORKFLOW], ids=lambda p: p.name)
def test_classifier_recognizes_github_and_gitea_and_fails_closed_for_everything_else(
    path: Path, tmp_path: Path
) -> None:
    """Forge recognition (ADR-0021): a positive case per accepted forge, and the named
    "unknown forge" rejection reason for everything else. The rejection must be
    distinguishable: the step's own stderr names it, rather than failing for an
    unrelated reason such as the https-only check.
    """
    body = _derivation_body(path)

    completed, emitted = _run_step(
        body,
        {"FORGE_SERVER_URL": "https://github.com", "FORGE_REPOSITORY": "Owner/Name"},
        tmp_path,
    )
    assert completed.returncode == 0, completed.stderr
    assert emitted["forge"] == "github"

    completed, emitted = _run_step(
        body,
        {
            "GITEA_ACTIONS": "true",
            "FORGE_SERVER_URL": "https://git.example.com:3000",
            "FORGE_REPOSITORY": "Owner/Name",
        },
        tmp_path,
    )
    assert completed.returncode == 0, completed.stderr
    assert emitted["forge"] == "gitea"

    completed, _ = _run_step(
        body,
        {"FORGE_SERVER_URL": "https://gitlab.example.com", "FORGE_REPOSITORY": "Owner/Name"},
        tmp_path,
    )
    assert completed.returncode != 0, "an unrecognised forge must fail closed"
    assert "unknown forge" in completed.stderr, (
        f"{path.name}: rejected an unrecognised forge, but not with the named reason "
        f"'unknown forge' (ADR-0021 failure taxonomy)"
    )


@pytest.mark.parametrize("path", [DEV_WORKFLOW, RELEASE_WORKFLOW], ids=lambda p: p.name)
def test_classifier_normalizes_host_case_and_trailing_slash(
    path: Path, tmp_path: Path
) -> None:
    """Normalization (ADR-0021): case folding and trailing-slash handling applied before
    projection, so `https://Git.Example.COM:3000/` and `https://git.example.com:3000`
    project to the same registry and image repository. Mixed-case hosts are a real
    shape an operator can type when registering a Gitea server URL; a registry
    reference that is not lowercase cannot be pushed to (most registries reject
    uppercase repository paths), so an un-normalized host is a latent publish failure
    rather than a cosmetic one.
    """
    body = _derivation_body(path)
    lowercase_completed, lowercase_emitted = _run_step(
        body,
        {
            "GITEA_ACTIONS": "true",
            "FORGE_SERVER_URL": "https://git.example.com:3000",
            "FORGE_REPOSITORY": "Owner/Name",
        },
        tmp_path,
    )
    mixed_completed, mixed_emitted = _run_step(
        body,
        {
            "GITEA_ACTIONS": "true",
            "FORGE_SERVER_URL": "https://Git.Example.COM:3000/",
            "FORGE_REPOSITORY": "Owner/Name",
        },
        tmp_path,
    )
    assert lowercase_completed.returncode == 0, lowercase_completed.stderr
    assert mixed_completed.returncode == 0, mixed_completed.stderr
    assert mixed_emitted["registry"] == lowercase_emitted["registry"], (
        f"{path.name}: a mixed-case server host projects to a different registry than "
        f"its lowercase spelling; normalization is not applied before projection "
        f"(ADR-0021)"
    )
    assert mixed_emitted["image-repository"] == lowercase_emitted["image-repository"]


@pytest.mark.parametrize("path", [DEV_WORKFLOW, RELEASE_WORKFLOW], ids=lambda p: p.name)
def test_classifier_requires_https_before_any_coordinate_is_used(
    path: Path, tmp_path: Path
) -> None:
    """Every emitted coordinate ends up carrying a credential downstream (the package
    index URL takes FORGE_PACKAGE_TOKEN); accepting a non-https server URL would cross
    that credential over the network in cleartext the moment a coordinate is used. This
    is distinguishable from "unknown forge": the rejection names the scheme problem,
    not the forge-recognition problem.
    """
    body = _derivation_body(path)
    completed, _ = _run_step(
        body,
        {"FORGE_SERVER_URL": "http://github.com", "FORGE_REPOSITORY": "Owner/Name"},
        tmp_path,
    )
    assert completed.returncode != 0
    assert "https" in completed.stderr.lower()


def test_no_malformed_registry_or_same_host_path_taxonomy_is_reachable() -> None:
    """ADR-0021 names "malformed registry" and "same-host/path mismatch" as rejection
    reasons in the general contract. Under this repository's design they are
    structurally unreachable rather than untested: `FORGE_REGISTRY` is retired (no
    operator-supplied registry value exists to be malformed or to mismatch the source
    repository's host/path), so the registry is always a direct projection of the same
    `github.server_url` the repository coordinate is projected from, and the two can
    never disagree. This test records that as a deliberate taxonomy collapse, not a gap
    silently left untested -- if `FORGE_REGISTRY` or an equivalent operator override is
    ever reintroduced, this test (and the two retired-reasons) must be revisited.
    """
    for path in (DEV_WORKFLOW, RELEASE_WORKFLOW):
        body = _derivation_body(path)
        assert "FORGE_REGISTRY" not in body
    document = _load_workflow(DEV_WORKFLOW)
    assert "jobs" in document  # the file still parses; a sanity check, not a guard
