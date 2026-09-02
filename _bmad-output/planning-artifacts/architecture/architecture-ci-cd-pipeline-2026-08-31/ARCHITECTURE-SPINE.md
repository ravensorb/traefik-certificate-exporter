---
title: CI/CD Pipeline Architecture Spine
project: traefik-certificate-exporter
date: 2026-09-01
status: approved-for-implementation
source_report: docs/ci/codex-assesment.md
revision: lean-action-publication
---

# CI/CD Pipeline Architecture Spine

## Purpose

This spine defines the invariants for building, verifying, packaging, and publishing
`traefik-certificate-exporter`. The complete earlier design remains inspectable at commit
`dbc991c7595d087edc1a2f91e763d0418209116e` on
`archive/publication-transaction-v1`; it is not an active implementation dependency.

The active design follows one rule: build once, validate the manifest and checksums at every
publisher boundary, and use ordinary maintained actions for each destination. Mutable aliases
move only after the required publishers succeed.

## System Context

```text
developer
   |
   | just build / test / test-local / release <major|minor|patch>
   v
git repository (GitHub OR Gitea)
   |
   +-- pull request ----------> ci.yaml ----------+
   |                                             |
   +-- main branch -----------> dev.yaml ---------+--> verify-build.yaml
   |                                             |       |
   +-- exact vX.Y.Z tag ------> release.yaml -----+       +-- wheel + sdist
                                                         +-- SHA256SUMS
                                                         +-- build-manifest.json
                                                         +-- native image smoke evidence
                                                                  |
                              destination action jobs <------------+
                                   |             |
                            packages      one multi-platform image job
                                   |
                            aliases-last finalizer
```

## Architecture Requirements

The `CI-AR` identifiers remain stable traceability keys.

### Forge and portability

- **CI-AR1 — Single active forge.** A run belongs to GitHub.com or one self-hosted Gitea
  instance, derived from action context. It does not publish across both forges.
- **CI-AR2 — One workflow implementation.** GitHub Actions, Gitea Actions, and local `act`
  execute the same workflow graph; no step branches on `ACT`.
- **CI-AR3 — Action-first composition.** Maintained actions own standard checkout, artifact,
  registry, package-index, and release integrations. Repository Python owns only project-specific
  version and build-evidence validation.
- **CI-AR4 — Action version policy.** Approved first-party and LiquidLogicLabs actions use a
  documented floating major when available; other third-party actions require a reviewed SHA.
  **The classification is per action, not per owner:** an action handed a publication credential
  requires a reviewed full commit SHA even when its owner is approved, because a floating major
  is a moving ref and whoever can move it can exfiltrate the credential. Registered in
  `SHA_PINNED_ACTIONS` (`tests/ci/test_workflow_contracts.py`); see ADR-0009. This is what
  reconciles CI-AR4 with CI-AR38, which previously contradicted it for
  `pypa/gh-action-pypi-publish`.
- **CI-AR5 — Stable topology.** The pipeline consists of `ci.yaml`, `dev.yaml`, `release.yaml`,
  and reusable `verify-build.yaml`.
- **CI-AR6 — Host-neutral coordinates.** Repository, API, server, and registry coordinates come
  from action context, with only a documented Gitea override where safe derivation is impossible.

### Local interface and version ownership

- **CI-AR7 — `just` is the local interface.** The root `justfile` exposes `setup`, `lint`,
  `test`, `test-local`, `package`, `image`, `build`, `verify`, and `release PART`.
- **CI-AR8 — One committed version.** Poetry project metadata is the committed version authority.
- **CI-AR9 — Guarded release preconditions.** `just release PART` accepts only `major`, `minor`,
  or `patch` and requires a clean, current default branch plus green local verification.
- **CI-AR10 — Atomic exact tag.** The release command updates metadata, commits
  `release: vX.Y.Z`, creates annotated tag `vX.Y.Z`, and atomically pushes commit and tag.
- **CI-AR11 — Stable agreement.** Stable CI rejects mismatch among tag, committed version,
  package metadata, lock state, and application-reported version.
- **CI-AR12 — Development identity.** Default-branch builds use next-patch
  `X.Y.(Z+1).devN`, where `N` is first-parent distance, without committing or tagging.

### Build and verification

- **CI-AR13 — One distribution set.** A run creates exactly one wheel and one sdist and records
  their filenames and SHA-256 hashes.
- **CI-AR14 — Exact-wheel image provenance.** The image installs the verified wheel; it does not
  rebuild the project or resolve an independent application dependency set.
- **CI-AR15 — Reproducible evidence.** `build-manifest.json`, whose schema/version identifier is
  `build-manifest-v1`, records only source SHA, normalized package version, optional development
  distance, wheel/sdist filenames and hashes, image inputs and labels, and their fingerprint. It
  never records channel, platforms, lock hash, observed image digest, credentials, or run identity.
- **CI-AR16 — Multi-architecture image.** Supported platforms are
  `linux/amd64,linux/arm64`; verification proves both descriptors exist.
- **CI-AR17 — Immutable first names.** Development images first publish under
  `dev-<12sha>` and stable images under exact version tags. Package versions are immutable.
- **CI-AR18 — Verify before publishing.** Lint, tests, metadata checks, clean-wheel install,
  native image smoke tests, workflow contracts, manifest validation, and checksum validation
  finish before a publisher can mutate its destination. Epic 8 adds the multi-platform Buildx
  publication and inspects both published descriptors before finalization.

### Destination action jobs

- **CI-AR19 — Strict toggles.** Optional publication variables accept only case-normalized
  `true` or `false`; absent means false and any other value fails the owning job.
- **CI-AR20 — Image destinations.** The active forge registry is always required. Docker Hub is
  independently enabled by `PUBLISH_IMAGE_DOCKERHUB`, **and applies to the stable channel only**:
  development images publish to the active forge registry and nowhere else, so the toggle is inert
  in `dev.yaml`. See ADR-0011.
- **CI-AR21 — Package channels.** Development uses optional TestPyPI; stable uses optional PyPI.
  Gitea's owning-forge Python index is always required. GitHub has no forge Python index, so this
  destination is absent by host capability and Release assets carry the distributions.
- **CI-AR22 — Retired: publication plan.** The original requirement introduced
  `publication-plan-v1.json`. It is intentionally retired and has no active replacement schema;
  see `archive/publication-transaction-v1` at
  `dbc991c7595d087edc1a2f91e763d0418209116e`.
- **CI-AR23 — Retired: aggregate preflight.** The original all-destination preflight barrier is
  intentionally retired; see `archive/publication-transaction-v1` at
  `dbc991c7595d087edc1a2f91e763d0418209116e` for its historical meaning.
- **CI-AR24 — Least privilege.** Each publisher receives only its destination's credentials and
  job permissions. Disabled external targets receive no secret and make no endpoint request.
- **CI-AR25 — Credential modes.** GitHub uses trusted publishing for PyPI/TestPyPI, GHCR uses
  the repository token, and Gitea/Docker Hub use scoped protected tokens.
- **CI-AR26 — Retired: idempotent immutable publication.** The original custom remote-identity
  reconciliation requirement is intentionally retired; see `archive/publication-transaction-v1`
  at `dbc991c7595d087edc1a2f91e763d0418209116e`.
- **CI-AR27 — Retired: immutable-first fan-out.** The original transaction fan-out requirement
  is intentionally retired; see `archive/publication-transaction-v1` at
  `dbc991c7595d087edc1a2f91e763d0418209116e`.
- **CI-AR28 — Stable forge Release.** A stable run creates one active-forge Release for the exact
  tag and attaches wheel, sdist, checksums, and build manifest. Development creates no Release.
- **CI-AR29 — Forward-only aliases.** Stable image aliases `X.Y`, `X`, and `latest`, plus Git
  tags `vX.Y` and `vX`, may advance only to a newer compatible stable version. `dev` advances
  only after the whole development fan-out succeeds and a just-in-time remote check proves the
  candidate remains the protected default-branch head. Prereleases never advance stable aliases.
  Workflow concurrency prevents stale dev finalizers, and all alias jobs copy the already-published
  digest without rebuilding.
- **CI-AR30 — Retired: release receipt.** The original requirement introduced
  `release-receipt-v1.json`. It is intentionally retired and has no active replacement schema;
  see `archive/publication-transaction-v1` at
  `dbc991c7595d087edc1a2f91e763d0418209116e`.
- **CI-AR31 — Evidence retention.** Distribution artifacts, checksums, build manifest, and test
  evidence remain attached to the originating workflow for 30 days.

### Trust boundaries and Gitea certification

- **CI-AR32 — Secret-free pull requests.** Pull requests receive read-only contents permission,
  no publisher secrets, and no publication jobs, including forked requests.
- **CI-AR33 — Safe local `act`.** Local workflow testing uses a disposable clone/worktree and
  synthetic local inputs; it never rewrites the developer worktree or accepts production tokens.
- **CI-AR34 — Pinned isolated Gitea runners.** The supported Gitea server, act-runner, runner
  image, and action-major tuple are recorded. Untrusted verification and protected publication
  use separate pools with ephemeral workspaces and minimal mounts.
- **CI-AR35 — Practical conformance gate.** Migration requires staging proof of PR verification,
  dev/stable destinations, private CA, artifacts, multi-arch images, forge Release, aliases-last,
  one failed-jobs-only rerun, and rollback steps for the pinned tuple.

### Lean publication requirements

- **CI-AR36 — Boundary revalidation.** Every publisher downloads the verified bundle, checks
  `SHA256SUMS`, validates `build-manifest.json`, matches source/version, and for image publication
  proves the exact wheel hash is the declared image input before any login or upload.
- **CI-AR37 — Destination-local failure.** Package, image, and forge Release jobs report their
  own actionable failures without a repository-specific all-destination protocol.
- **CI-AR38 — Maintained action behavior.** Standard actions own upload behavior. Package upload
  uses `pypa/gh-action-pypi-publish@<reviewed-full-commit-sha>`; implementation must resolve,
  review, and record the real full commit SHA. Operators rerun failed jobs only. If the forge
  cannot do that, evidence expired, or an immutable conflict exists, publication halts and is
  escalated (using a new development version where appropriate); a whole-workflow rerun is not
  the normal recovery path.
- **CI-AR39 — One-build image fan-out.** One channel-run image job consumes the exact verified
  wheel and performs one Buildx multi-platform invocation for `linux/amd64,linux/arm64`, tagging
  the required forge registry and optional Docker Hub in that invocation. There is no per-registry
  rebuild. The job exports the published digest and inspected platforms as action/workflow outputs.
- **CI-AR40 — Required fan-out.** Required and enabled destination jobs may run independently
  after verification; aggregate success gates the Story 8.3 finalizer. **"Aggregate success" is
  evaluated, not depended on:** the finalizer `needs:` every publisher in its file statically,
  runs under `if: ${{ !cancelled() }}`, and compares `needs.<job>.result` against the enabled set
  emitted once as a plan-job output. A `skipped` destination that the enabled set says was off, or
  is unsupported on this host, does not block; one that should have run does. `needs:` cannot
  express selective dependency — it is structural and takes no expression — so this is evaluation,
  not wiring. See ADR-0011. The image job receives
  only enabled image-registry credentials, while package credentials stay isolated in package jobs.
- **CI-AR41 — Workflow-native run evidence.** Run ID/URL, manifest and artifact hashes, published
  image digest/platform inspection, Release URL, and alias outcomes are emitted as job outputs and
  workflow run summaries. They are not added to a repository-owned schema.

## Workflow Responsibilities

| Workflow | Trigger | Secrets | Mutation |
|---|---|---|---|
| `ci.yaml` | pull request | none | none |
| `dev.yaml` | protected default-branch push | destination jobs only | immutable dev packages/images; Story 8.3 moves `dev` |
| `release.yaml` | exact `vX.Y.Z` tag | destination jobs only | stable packages/images/Release; aliases last |
| `verify-build.yaml` | reusable call or dispatch | none | workflow artifacts only |

`verify-build.yaml` accepts only channel, package version, and source SHA. Publisher adapters
consume its single evidence bundle.

## Configuration Contract

### Repository variables

| Variable | Meaning | Default |
|---|---|---|
| `PUBLISH_IMAGE_DOCKERHUB` | additionally publish to Docker Hub; **stable channel only, inert in `dev.yaml`** | `false` |
| `PUBLISH_PACKAGE_TESTPYPI` | publish development distributions to TestPyPI | `false` |
| `PUBLISH_PACKAGE_PYPI` | publish stable distributions to PyPI | `false` |
| `DOCKERHUB_REPOSITORY` | Docker Hub namespace/repository | required when enabled |

The active forge registry is always required. The Gitea package index is always required on
Gitea; GitHub has no equivalent Python index.

**`FORGE_REGISTRY` is retired (spec change).** It was specified as an operator-supplied
`host[:port]` override for a Gitea deployment whose registry answers on a different port from its
web UI. There is no such value: the registry authority *is* `github.server_url`'s host, so the
override could only ever restate what is already derived, and validating a restatement cost a
235-line module, a 60-line composite action and 240 lines of tests to produce six template
expressions over action context. A Gitea deployment that genuinely splits the two ports is
unrepresented until someone runs one; the replacement then is a new variable specified against
that deployment, not this one restored.

### Protected credentials

| Target | GitHub.com | Gitea |
|---|---|---|
| TestPyPI/PyPI | OIDC trusted publishing | scoped token |
| forge image | repository token to GHCR | scoped registry token |
| forge package | unavailable | scoped package token |
| Docker Hub | username + scoped token | username + scoped token |
| runner bootstrap CA | runner-host trust before registration/action resolution | runner-host trust before registration/action resolution |
| downstream private CA | optional job-level bundle | protected bundle imported only for downstream endpoints |

## Publication Flow

```text
VERIFY
  -> DOWNLOAD_AND_VALIDATE_EVIDENCE in each destination job
  -> PUBLISH_PACKAGES + ONE_MULTI_PLATFORM_IMAGE_BUILD_TO_ALL_ENABLED_REGISTRIES
  -> CREATE_FORGE_RELEASE (stable only)
  -> ADVANCE_ALIASES

A failed or skipped required destination prevents ADVANCE_ALIASES.
Only failed jobs are rerun with retained build-manifest/checksum evidence. If that path is not
supported or the evidence is no longer valid, halt and escalate rather than rerun everything.
```

## Trigger and Coordinate Guards

- Unknown forge identity fails closed before a destination or credential is selected.
- Development checkout fetches full history and tags once for first-parent distance, and suppresses
  publication when the source commit has an exact stable tag.
- Stable publication requires an annotated exact `vX.Y.Z` tag whose peeled commit equals the event
  SHA and is reachable from the protected default branch.
- Forge coordinates are a projection of `github.server_url` and `github.repository` alone -- forge
  kind, registry authority, image repository, and whether the host offers a Python index. No
  operator value participates, so there is nothing to validate and no override to reject.
- Development workflows use source/ref-scoped concurrency. Story 8.3 rechecks the protected
  default-branch head immediately before moving `dev`; stale candidates halt without alias movement.

## Guarded Local Release

`just release patch` (or `minor`/`major`) remains the deliberate release interface:

1. Validate input and required tools.
2. Require a clean, attached, current default branch.
3. Fetch tags and reject an existing target tag.
4. Run the local verification interface.
5. Calculate and apply the SemVer target through Poetry.
6. Recheck lock, package metadata, and application version.
7. Commit `release: vX.Y.Z` and create annotated `vX.Y.Z`.
8. Atomically push the branch and exact tag; never force or delete a remote tag.

Floating Git tags are moved by the stable finalizer only after publication succeeds.

## Verification Anchors

- Contract tests cover deterministic JSON, duplicate keys, forbidden secret fields, schema
  strictness, exact artifact hashes, image inputs, and checksum revalidation.
- Workflow tests prove permissions, triggers, action ownership/version policy, secret isolation,
  verifier dependencies, required destination fan-out, and aliases-last ordering.
- Package smoke tests install the wheel in an empty environment and invoke the CLI.
- Current verifier image tests prove native image smoke and installed version/wheel provenance.
  Epic 8 publication tests inspect both required platforms from the single published index.
- Gitea certification records the pinned tuple and run/build identifiers without credentials.

## Implementation Sequence

1. **Epic 7 — Reproducible Build and Verification:** complete and archived; retain it.
2. **Epic 8 — Action-Based Multi-Channel Delivery:** dev jobs, stable jobs, Release/aliases-last,
   then topology cutover and operator runbook.
3. **Epic 9 — Practical Gitea Certification:** runner/CA/credential setup, then staging proof and
   migration.

Epic ordering remains `E007 -> E008 -> E009`.
