"""ADR-0019: per-job credential matrix, with distinct principals and denial proofs.

The matrix below is the hand-kept registry the ADR requires: one row per job that holds
a publication-capable credential, recording principal, secret/context name, minimum
scopes, protected owner/environment, and permitted/forbidden mutations. It is checked
against the actual parsed `secrets:`/`permissions:` of `dev.yaml` and `release.yaml`
rather than merely asserted -- the rule the sibling test modules in this package follow.

What this module can prove without a live Gitea: every publication-capable job is
covered by a matrix row, every row's declared secrets are exactly what the job
references, and no job references a secret declared forbidden for it. What it cannot
prove: that a live Gitea instance actually REJECTS an attempted mutation made with
another destination's credential, or that a disabled destination's job cannot reach its
endpoint at all. Those are marked `requires_live_gitea` below (ADR-0019's negative
tests proper).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

import pytest

from tests.ci.support import (
    DEV_WORKFLOW,
    RELEASE_WORKFLOW,
    _is_credential_bearing,
    _jobs,
    _load_workflow,
)

# The one credential every job on a forge is issued automatically and whose authority is
# set per job by `permissions:` rather than by which secret it was handed -- the same
# exclusion `tests/ci/test_image_publication.py` makes, for the same reason.
AMBIENT_FORGE_TOKEN = "GITHUB_TOKEN"


@dataclass(frozen=True)
class CredentialRow:
    """One row of the ADR-0019 matrix."""

    workflow: str
    job: str
    principal: str
    secrets: frozenset[str]
    minimum_scopes: frozenset[str]
    protected_owner_or_environment: str
    permitted_mutations: str
    forbidden_mutations: str
    forbidden_secrets: frozenset[str] = field(default_factory=frozenset)


# Image publication, forge Release creation, and Git-alias mutation use distinct
# principals (ADR-0019): `publish-image` authenticates as the automatic repository
# token scoped `packages: write` plus an optional distinct Docker Hub principal;
# `finalize` authenticates as the automatic repository token scoped `contents: write`
# and holds no registry credential; `finalize-image-aliases` repeats the `publish-image`
# registry principal to move an alias at an already-published digest, never a Git ref.
# `publish-package-forge`/`publish-package-pypi`/`publish-package-testpypi` each use a
# distinct package-destination principal. Verifier/PR jobs are absent from this table
# by construction: absence here is the claim that they hold nothing (ADR-0007).
CREDENTIAL_MATRIX: tuple[CredentialRow, ...] = (
    CredentialRow(
        workflow=DEV_WORKFLOW.name,
        job="publish-package-forge",
        principal="FORGE_PACKAGE_TOKEN bearer (__token__)",
        # GITEA_PACKAGE_INDEX_CA_CERTIFICATE is trust material (ADR-0018), not a
        # mutation credential, but it reaches the job through secrets.* the same way,
        # so it is declared here rather than left for the drift check to flag.
        secrets=frozenset({"FORGE_PACKAGE_TOKEN", "GITEA_PACKAGE_INDEX_CA_CERTIFICATE"}),
        minimum_scopes=frozenset({"package:write (forge index)"}),
        protected_owner_or_environment="forge package index owner",
        permitted_mutations="upload wheel/sdist to the forge Python index",
        forbidden_mutations="image push, forge Release, Git-alias mutation",
        forbidden_secrets=frozenset(
            {"DOCKERHUB_TOKEN", "DOCKERHUB_USERNAME"}
        ),
    ),
    CredentialRow(
        workflow=DEV_WORKFLOW.name,
        job="publish-package-testpypi",
        principal="GitHub OIDC trusted publishing",
        secrets=frozenset(),  # id-token: write, no secret
        minimum_scopes=frozenset({"id-token:write"}),
        protected_owner_or_environment="TestPyPI trusted-publishing binding",
        permitted_mutations="upload wheel/sdist to TestPyPI",
        forbidden_mutations="image push, forge Release, Git-alias mutation, forge package upload",
    ),
    CredentialRow(
        workflow=DEV_WORKFLOW.name,
        job="publish-image",
        # Docker Hub is a stable-channel-only destination (ADR-0011): the dev channel's
        # `publish-image` job never receives DOCKERHUB_* at all, not merely an empty
        # string, so its principal is the forge registry token alone.
        principal="automatic repository token (packages: write)",
        secrets=frozenset({"GITHUB_TOKEN"}),
        minimum_scopes=frozenset({"packages:write"}),
        protected_owner_or_environment="forge registry owner",
        permitted_mutations="push the one built multi-platform image to the forge registry",
        forbidden_mutations="forge Release, Git-alias mutation, package upload, Docker Hub push",
        forbidden_secrets=frozenset(
            {"FORGE_PACKAGE_TOKEN", "DOCKERHUB_TOKEN", "DOCKERHUB_USERNAME"}
        ),
    ),
    CredentialRow(
        workflow=DEV_WORKFLOW.name,
        job="finalize-dev-alias",
        principal="automatic repository token (packages: write)",
        secrets=frozenset({"GITHUB_TOKEN"}),
        minimum_scopes=frozenset({"packages:write"}),
        protected_owner_or_environment="forge registry owner",
        permitted_mutations="move the dev image alias to the already-published digest",
        forbidden_mutations="ref write, forge Release, package upload",
        forbidden_secrets=frozenset({"FORGE_PACKAGE_TOKEN"}),
    ),
    CredentialRow(
        workflow=RELEASE_WORKFLOW.name,
        job="attest",
        principal="GitHub OIDC attestation identity",
        secrets=frozenset(),  # id-token/attestations: write, no stored secret
        minimum_scopes=frozenset({"id-token:write", "attestations:write"}),
        protected_owner_or_environment="GitHub attestation store (absent on Gitea)",
        permitted_mutations="attach build provenance to the verified distributions",
        forbidden_mutations="image push, package upload, forge Release, Git-alias mutation",
    ),
    CredentialRow(
        workflow=RELEASE_WORKFLOW.name,
        job="publish-package-forge",
        principal="FORGE_PACKAGE_TOKEN bearer (__token__)",
        # GITEA_PACKAGE_INDEX_CA_CERTIFICATE is trust material (ADR-0018), not a
        # mutation credential, but it reaches the job through secrets.* the same way,
        # so it is declared here rather than left for the drift check to flag.
        secrets=frozenset({"FORGE_PACKAGE_TOKEN", "GITEA_PACKAGE_INDEX_CA_CERTIFICATE"}),
        minimum_scopes=frozenset({"package:write (forge index)"}),
        protected_owner_or_environment="forge package index owner",
        permitted_mutations="upload wheel/sdist to the forge Python index",
        forbidden_mutations="image push, forge Release, Git-alias mutation",
        forbidden_secrets=frozenset({"DOCKERHUB_TOKEN", "DOCKERHUB_USERNAME"}),
    ),
    CredentialRow(
        workflow=RELEASE_WORKFLOW.name,
        job="publish-package-pypi",
        principal="GitHub OIDC trusted publishing",
        secrets=frozenset(),
        minimum_scopes=frozenset({"id-token:write"}),
        protected_owner_or_environment="PyPI trusted-publishing binding",
        permitted_mutations="upload wheel/sdist to PyPI",
        forbidden_mutations="image push, forge Release, Git-alias mutation, forge package upload",
    ),
    CredentialRow(
        workflow=RELEASE_WORKFLOW.name,
        job="publish-image",
        principal="automatic repository token (packages: write) + optional Docker Hub principal",
        secrets=frozenset({"GITHUB_TOKEN", "DOCKERHUB_USERNAME", "DOCKERHUB_TOKEN"}),
        minimum_scopes=frozenset({"packages:write"}),
        protected_owner_or_environment="forge registry owner / Docker Hub org",
        permitted_mutations="push the one built multi-platform image to enabled registries",
        forbidden_mutations="forge Release, Git-alias mutation, package upload",
        forbidden_secrets=frozenset({"FORGE_PACKAGE_TOKEN"}),
    ),
    CredentialRow(
        workflow=RELEASE_WORKFLOW.name,
        job="finalize",
        principal="automatic repository token (contents: write)",
        # GITEA_FORGE_API_CA_CERTIFICATE is trust material (ADR-0018), not a mutation
        # credential, declared here for the same reason as the package-forge rows above.
        secrets=frozenset({"GITHUB_TOKEN", "GITEA_FORGE_API_CA_CERTIFICATE"}),
        minimum_scopes=frozenset({"contents:write"}),
        protected_owner_or_environment="protected default branch / tag namespace",
        permitted_mutations="create the forge Release, advance vMAJOR/vMAJOR.MINOR",
        forbidden_mutations="image push, package upload",
        forbidden_secrets=frozenset(
            {"FORGE_PACKAGE_TOKEN", "DOCKERHUB_TOKEN", "DOCKERHUB_USERNAME"}
        ),
    ),
    CredentialRow(
        workflow=RELEASE_WORKFLOW.name,
        job="finalize-image-aliases",
        principal="automatic repository token (packages: write) + optional Docker Hub principal",
        secrets=frozenset({"GITHUB_TOKEN", "DOCKERHUB_USERNAME", "DOCKERHUB_TOKEN"}),
        minimum_scopes=frozenset({"packages:write"}),
        protected_owner_or_environment="forge registry owner / Docker Hub org",
        permitted_mutations="move stable image aliases to the already-published digest",
        forbidden_mutations="ref write, forge Release, package upload",
        forbidden_secrets=frozenset({"FORGE_PACKAGE_TOKEN"}),
    ),
)


_WORKFLOW_PATHS = {DEV_WORKFLOW.name: DEV_WORKFLOW, RELEASE_WORKFLOW.name: RELEASE_WORKFLOW}


def _matrix_row(workflow: str, job: str) -> CredentialRow:
    for row in CREDENTIAL_MATRIX:
        if row.workflow == workflow and row.job == job:
            return row
    raise AssertionError(f"no CREDENTIAL_MATRIX row for ({workflow!r}, {job!r})")


def _referenced_secrets(job: dict) -> set[str]:
    pattern = re.compile(r"secrets\.([A-Za-z_][A-Za-z0-9_-]*)")
    return set(pattern.findall(json.dumps(job)))


def test_every_credential_bearing_job_has_a_matrix_row() -> None:
    """ADR-0019 scope: derived from capability, not from a hand-kept job name list, so a
    new publication-capable job is covered the moment it is added -- or fails here the
    moment it is not.
    """
    covered = {(row.workflow, row.job) for row in CREDENTIAL_MATRIX}
    examined = 0
    for workflow_name, path in _WORKFLOW_PATHS.items():
        document = _load_workflow(path)
        for job_name, job in _jobs(document).items():
            if not _is_credential_bearing(job):
                continue
            examined += 1
            assert (workflow_name, job_name) in covered, (
                f"{workflow_name}: job {job_name!r} holds a publication-capable "
                f"credential (permission or secrets.* reach) but has no CREDENTIAL_MATRIX "
                f"row (ADR-0019)"
            )
    assert examined, "no credential-bearing job was examined; this guard is vacuous"


def test_matrix_rows_match_the_jobs_actual_secret_references() -> None:
    """A matrix entry that lists secrets the job does not reference, or omits ones it
    does, is not a credential matrix -- it is prose next to the workflow that can drift
    from it silently. Checked both directions.
    """
    for row in CREDENTIAL_MATRIX:
        document = _load_workflow(_WORKFLOW_PATHS[row.workflow])
        job = _jobs(document)[row.job]
        actual = _referenced_secrets(job) - {AMBIENT_FORGE_TOKEN}
        declared = row.secrets - {AMBIENT_FORGE_TOKEN}
        assert actual == declared, (
            f"{row.workflow}:{row.job}: references secrets {sorted(actual)} but the "
            f"matrix declares {sorted(declared)} (ADR-0019 drift)"
        )


def test_no_job_references_another_destinations_forbidden_secret() -> None:
    """The mechanical half of the ADR-0019 cross-destination denial proof: a job must
    not even REFERENCE a secret its row forbids. This cannot prove a live Gitea would
    reject an attempted mutation made with the right secret and the wrong scope (that
    needs a running forge); it does prove the simpler, still load-bearing property that
    the wrong secret never reaches the job's `with:`/`env:`/`secrets:` at all.
    """
    for row in CREDENTIAL_MATRIX:
        document = _load_workflow(_WORKFLOW_PATHS[row.workflow])
        job = _jobs(document)[row.job]
        actual = _referenced_secrets(job)
        leaked = actual & row.forbidden_secrets
        assert not leaked, (
            f"{row.workflow}:{row.job}: references forbidden secret(s) {sorted(leaked)} "
            f"(ADR-0019 cross-destination denial)"
        )


def test_disabled_destination_jobs_receive_no_secret_for_that_destination() -> None:
    """PyPI/TestPyPI trusted publishing takes an OIDC identity and no stored secret at
    all; a disabled Docker Hub destination passes empty strings rather than the stored
    secret (already enforced structurally by the `fromJSON(...) == 'enabled' && secrets.X
    || ''` form each publisher uses, read here as a fact about the matrix rather than
    re-derived).
    """
    for row in CREDENTIAL_MATRIX:
        if row.job in {"publish-package-testpypi", "publish-package-pypi"}:
            assert not row.secrets, (
                f"{row.workflow}:{row.job}: trusted publishing should hold no stored "
                f"secret, only an OIDC identity"
            )


@pytest.mark.requires_live_gitea
def test_cross_destination_mutation_is_denied_by_the_forge() -> None:
    """ADR-0019's actual negative test: attempt each destination's mutation using
    another destination's credential (e.g. FORGE_PACKAGE_TOKEN against the image
    registry, or the registry token against the package index) and require the forge to
    deny it. This requires a running Gitea instance issuing real scoped credentials; it
    cannot be executed against parsed YAML, so it is not run here. See
    `docs/ci/gitea-runners.md` for the staging runbook this test anchors to.
    """
    pytest.skip("requires a live Gitea instance; see docs/ci/gitea-runners.md")
