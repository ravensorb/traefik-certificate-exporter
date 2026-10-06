# Reality Review — CI/CD Architecture Spine

**Verdict:** **Changes required before Epic 9 implementation.** The recent correction that removes
PyPI/TestPyPI credentials from Gitea is consistent with the current workflows, tests, operational
guide, and revised Epic 9 stories. The spine still contains one material credential-model mismatch
and three stale or prematurely asserted statements that weaken it as a reliable brownfield contract.

## Review scope

Reviewed the committed decisions in `ARCHITECTURE-SPINE.md` against the current repository,
especially:

- `.github/workflows/dev.yaml`, `.github/workflows/release.yaml`,
  `.github/workflows/publish-image.yaml`, and `.github/workflows/verify-build.yaml`
- `tests/ci/test_workflow_contracts.py`, `tests/ci/test_image_publication.py`, and
  `tests/ci/test_finalization.py`
- `docs/operational.md`, `docs/guidelines.md`, and ADRs 0006, 0009, 0010, 0011, and 0012
- the revised Epic 9 stories and the prior Epic 9 architecture gate

The mechanical spine lint passed with zero findings. This review is semantic and reality-based; it
does not claim live Gitea compatibility, because the revised stories correctly make that a staging
certification result rather than a repository-only assertion.

## Findings

### R1 — HIGH — CI-AR25 misstates the Gitea image credential actually used

**Spine:** CI-AR25 and the Protected credentials table say Gitea uses a "scoped protected token"
for its forge image registry (`ARCHITECTURE-SPINE.md:139-142,247`).

**Repository reality:** both event-owner workflows pass `${{ secrets.GITHUB_TOKEN }}` to the
reusable image publisher as `registry_password` (`dev.yaml` and `release.yaml`). The package index
is different: it uses the explicit protected secret `FORGE_PACKAGE_TOKEN` with username
`__token__`. `docs/operational.md` likewise lists `GITHUB_TOKEN` as the per-run automatic token and
`FORGE_PACKAGE_TOKEN` as the long-lived forge-package credential; it does not list a separate
Gitea image-registry token.

**Why this matters:** the spine currently tells Story 9.1 operators to provision a credential the
workflow does not consume, while obscuring that Gitea image publication depends on the automatic
forge token honoring job-level `packages: write`. That dependency is precisely why
`TokenPermissionMode = restricted` and the behavioral permission probe are load-bearing.

**Required correction:** distinguish the two Gitea modes explicitly:

- forge image: automatic per-run repository token (`GITHUB_TOKEN` context), constrained by the
  credentialed job's `permissions:` and certified under the pinned Gitea tuple;
- forge package: protected `FORGE_PACKAGE_TOKEN`, scoped to the owner's Python package index.

If the intended design really is a separate protected image token, the workflows, tests, and
operational guide must change together; the current implementation does not realize that design.

### R2 — HIGH — CI-AR34 states unperformed Gitea certification as present fact

**Spine:** CI-AR34 says the supported server, act-runner, runner image, and action-major tuple
"are recorded" and that separate runner pools are used (`ARCHITECTURE-SPINE.md:170-172`).

**Repository reality:** no pinned tuple or completed Gitea runner guide exists yet. Revised Story
9.1 makes recording the tuple, proving shared-label registration-scope isolation, checking node24,
checking nested reusable workflows, and checking `environment: pypi` parse acceptance future
acceptance criteria. It also says the tuple is rejected if registration scope cannot enforce the
separation. The prior gate explicitly identified this as unresolved.

**Why this matters:** a reader can reasonably interpret the spine as evidence that a supported
tuple and isolation mechanism already exist. They do not; they remain the core output of Epic 9.

**Required correction:** phrase CI-AR34 as a normative gate: the tuple **must be recorded** and
separate registrations/pools **must be demonstrated** before migration. Name the current proposed
mechanism (shared `ubuntu-24.04` label plus registration-scope separation) as subject to staging
proof, with tuple rejection on failure, matching Story 9.1.

### R3 — MEDIUM — CI-AR6 preserves a Gitea override that the same spine retires

**Spine:** CI-AR6 permits "a documented Gitea override where safe derivation is impossible"
(`ARCHITECTURE-SPINE.md:77-78`). The Configuration Contract later says `FORGE_REGISTRY` is retired,
there is no operator value to validate, and a split-port deployment is unrepresented until a real
one exists (`ARCHITECTURE-SPINE.md:233-240`). Trigger guards likewise say coordinates come from
action context alone.

**Repository reality:** the workflows derive coordinates solely from `github.server_url` and
`github.repository`; revised Story 9.1 expressly says no operator-supplied registry value
participates.

**Why this matters:** two stories implementing CI-AR6 independently could diverge on whether an
override is part of the supported contract.

**Required correction:** remove the override clause from CI-AR6. Keep split-port support deferred
until a concrete deployment supplies requirements, as the Configuration Contract already says.

### R4 — MEDIUM — CI-AR38 describes an already-completed action-pin decision as future work

**Spine:** CI-AR38 says package upload uses
`pypa/gh-action-pypi-publish@<reviewed-full-commit-sha>` and that implementation "must resolve,
review, and record the real full commit SHA" (`ARCHITECTURE-SPINE.md:184-189`).

**Repository reality:** development and stable forge/PyPI publishers already use
`dc37677b2e1c63e2034f94d8a5b11f265b73ba33`; the workflows identify it as reviewed, ADR-0009
defines the pin policy, and `SHA_PINNED_ACTIONS` contract coverage protects the credential-bearing
action.

**Why this matters:** the placeholder makes the spine look unfinished and can prompt redundant or
inconsistent pin selection during Epic 9.

**Required correction:** state the invariant (credential-bearing package publisher is pinned to a
reviewed full SHA registered in `SHA_PINNED_ACTIONS`) and let the registry/workflows own the current
SHA, or record the current SHA without the future-tense instruction.

## Confirmed alignment of the recent credential correction

The correction to CI-AR21, CI-AR25's PyPI clause, and the Protected credentials table is otherwise
well grounded:

1. Both plan jobs mark TestPyPI/PyPI `unsupported` when the forge is not GitHub, while the Gitea
   forge package index is enabled from the host-capability projection.
2. PyPI/TestPyPI publisher jobs receive OIDC (`id-token: write`) and no password; their conditions
   read the plan's enabled-destination set, so they do not run on Gitea.
3. Gitea forge-package jobs use only `FORGE_PACKAGE_TOKEN` and the derived same-forge package URL.
4. The revised Epic 9 stories now require certification of the forge package channel and expressly
   treat PyPI/TestPyPI as absent on Gitea.
5. `docs/operational.md` describes PyPI as trusted-publishing-only and records no stored PyPI
   credential.

## Technology and version assertions

- No supported Gitea server, act-runner, or runner-image version is yet established. Any reading
  of CI-AR34 as a current compatibility claim is stale; Story 9.1 must produce that evidence.
- The repo consistently declares node24 as load-bearing for the adopted action majors, but actual
  support by the future pinned act-runner remains unverified and is correctly a reject-the-tuple
  probe in Story 9.1.
- Artifact action v4 is intentionally retained as the Gitea conformance baseline in workflow and
  local-action comments. The repo does not yet have staging evidence that the future tuple supports
  it; this is not a reason to change the major before certification.
- The reviewed PyPI publisher SHA is present in implementation; the spine's placeholder/future
  wording is the stale part, not the workflow pin.

## Recommendation

Repair R1–R4 in the spine before accepting the Epic 9 replan. Then keep all Gitea runtime and
version claims conditional until Story 9.1 records the pinned tuple and passes the structural
probes; do not convert planned certification into asserted compatibility.
