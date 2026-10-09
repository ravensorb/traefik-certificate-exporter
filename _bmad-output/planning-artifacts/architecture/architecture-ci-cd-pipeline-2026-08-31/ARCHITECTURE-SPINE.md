---
title: CI/CD Pipeline Architecture Spine
project: traefik-certificate-exporter
date: 2026-10-08
status: superseded
superseded_by: _bmad-output/planning-artifacts/architecture/architecture-ci-cd-pipeline-2026-10-08/ARCHITECTURE-SPINE.md (ADR-0035)
source_report: docs/ci/codex-assesment.md
revision: ref-free-checkout
---

# CI/CD Pipeline Architecture Spine

> **Superseded 2026-10-08** by `architecture-ci-cd-pipeline-2026-10-08/ARCHITECTURE-SPINE.md` (ADR-0035). No CI-AR rule below binds; kept as history.

## Purpose

This spine defines the invariants for building, verifying, packaging, and publishing
`traefik-certificate-exporter`. The complete earlier design remains inspectable at commit
`dbc991c7595d087edc1a2f91e763d0418209116e` on
`archive/publication-transaction-v1`; it is not an active implementation dependency.

The active design follows one rule: build once, validate the manifest and checksums at every
publisher boundary, and use ordinary maintained actions for each destination. Mutable aliases
move only after the required publishers succeed.

A second rule, added 2026-10-08 (ADR-0028): **no checkout step anywhere in this pipeline ever
supplies `ref:`, `repository:`, or any other identity-overriding input.** Every checkout -- in
`ci.yaml`, `dev.yaml`, `release.yaml`, all ten jobs of `verify-build.yaml`, and
`publish-image.yaml` -- is the plainest possible `actions/checkout@v7` call
(`fetch-depth`/`fetch-tags`/`persist-credentials` only), relying purely on the ambient event
context GitHub, Gitea, and local `act` each already provide. This was not a style preference:
explicit `ref:` pinning, threaded through every checkout call site so every job could re-verify an
externally-computed identity, was also the thing that made local `act` verification structurally
impossible to run safely (see CI-AR42 and ADR-0028 for the full account). Removing it closed the
gap and collapsed the duplication at the same time.

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
  execute the same workflow graph; no step branches on `ACT`, on channel, or on any other
  dimension for checkout identity purposes. *(Amended 2026-10-08, ADR-0028: generalized, not
  weakened. See CI-AR42 -- the ref-free checkout rule achieves a strictly stronger guarantee
  than the original ACT-specific wording by construction, since no checkout step anywhere needs
  a different input for any reason.)*
- **CI-AR3 — Action-first composition.** Maintained actions own standard checkout, artifact,
  registry, package-index, and release integrations. Repository Python owns only project-specific
  version and build-evidence validation.
- **CI-AR4 — Action version policy.** *(Superseded by CI-AR47 as of E012-S01-002. The
  original text is kept because ADR-0009 and several guards reason about it.)* Approved
  first-party and LiquidLogicLabs actions use a documented floating major when available; other
  third-party actions require a reviewed SHA. **The classification is per action, not per owner:**
  an action handed a publication credential requires a reviewed full commit SHA even when its
  owner is approved, because a floating major is a moving ref and whoever can move it can
  exfiltrate the credential. Registered in `SHA_PINNED_ACTIONS` (`tests/ci/support.py`); see
  ADR-0009. This is what reconciled CI-AR4 with CI-AR38, which previously contradicted it for
  `pypa/gh-action-pypi-publish`.
- **CI-AR5 — Stable topology.** The pipeline consists of `ci.yaml`, `dev.yaml` and `release.yaml`
  as event owners, and reusable `verify-build.yaml` and `publish-image.yaml`. Five files, in two
  classes, and the classes are a partition rather than a count -- an earlier form of this
  requirement named four and omitted `publish-image.yaml`, which holds every registry credential,
  both registry logins, the QEMU/Buildx build, and one of the two nested `workflow_call` edges
  E009 must certify. A reader working from that list would not have known to certify it.
  `test_the_workflow_topology_is_a_partition_of_reusable_files_and_event_owners` enforces the
  partition; it deliberately does not enforce a count, because a count is satisfied by any five.
- **CI-AR6 — Host-neutral coordinates.** Repository, API, server, and registry coordinates come
  from action context. The retired `FORGE_REGISTRY` override does not return implicitly: a
  deployment whose coordinates cannot be derived is unsupported until a new, narrowly scoped
  variable is specified and accepted in an ADR.

### Local interface and version ownership

- **CI-AR7 — `just` is the local interface.** The root `justfile` is the authority for which
  recipes exist; `just --list` enumerates them. This requirement deliberately does not restate
  that list. It did, and three of the nine names it gave — `setup`, `package`, `verify` — were
  never recipes, while `fix` and `release-resume` existed and were unlisted.
  `test_every_recipe_a_document_prescribes_exists` now fails any prescriptive document naming a
  recipe the justfile does not define.
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
- **CI-AR21 — Package channels.** On GitHub, development uses optional TestPyPI and stable uses
  optional PyPI. On Gitea, both are absent by host capability because their trusted-publishing
  identity is GitHub OIDC; Gitea's owning-forge Python index is the only package publication
  channel and is always required. GitHub has no forge Python index, so that destination is absent
  there and Release assets carry the distributions.
- **CI-AR22 — Retired: publication plan.** The original requirement introduced
  `publication-plan-v1.json`. It is intentionally retired and has no active replacement schema;
  see `archive/publication-transaction-v1` at
  `dbc991c7595d087edc1a2f91e763d0418209116e`.
- **CI-AR23 — Retired: aggregate preflight.** The original all-destination preflight barrier is
  intentionally retired; see `archive/publication-transaction-v1` at
  `dbc991c7595d087edc1a2f91e763d0418209116e` for its historical meaning.
- **CI-AR24 — Least privilege.** Each publisher receives only its destination's credentials and
  job permissions. Disabled external targets receive no secret and make no endpoint request.
- **CI-AR25 — Credential modes.** GitHub uses trusted publishing for PyPI/TestPyPI and the
  repository token for GHCR. Gitea image publication and repository mutation use the runner's
  automatic repository token (`GITHUB_TOKEN`) with job-local permissions; its forge package index
  uses the distinct `FORGE_PACKAGE_TOKEN`. Gitea has no PyPI/TestPyPI credential path. Docker Hub
  uses a username plus scoped token on either forge. *(Scope note, 2026-10-06: Epic E009 was
  rescoped to drop live-Gitea-runner certification; certifying the automatic token's effective
  Gitea permissions against a real instance is deferred until this project operates against a
  live Gitea deployment, not a current E009 deliverable. What ships now is the statically correct
  job-local `permissions:` declaration per the credential matrix, ADR-0019.)*
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

*(Scope note, 2026-10-06: Epic E009 was rescoped to drop live-Gitea-runner certification — see
`epic.yaml` goal and `docs/adr/0015`, `0016`, `0017`, `0020`, `0022`. CI-AR34 and CI-AR35 below
describe the staging/live-proof target state this project would certify **if and when** it is
actually operated against a pinned Gitea deployment; no such deployment is currently planned, and
neither requirement is a current E009 deliverable. The statically provable half of this project's
own responsibility — the forge classifier and per-job credential matrix — is implemented and
tested in `tests/ci/`, independent of whether this section's live proof is ever performed.)*

- **CI-AR32 — Secret-free pull requests.** Pull requests receive read-only contents permission,
  no publisher secrets, and no publication jobs, including forked requests.
- **CI-AR33 — Safe local `act`.** Local workflow testing uses a disposable clone/worktree and
  synthetic local inputs; it never rewrites the developer worktree or accepts production tokens.
  *(Clarified 2026-10-08, ADR-0028: retained as cheap defense-in-depth against a future regression
  reintroducing a `ref:` override, but no longer load-bearing for the failure mode that originally
  motivated it -- see CI-AR42, which makes every job's checkout a no-op under `act` unconditionally,
  with no disposable-clone step required to achieve that.)*
- **CI-AR34 — Pinned isolated Gitea runners.** *(Deferred under the 2026-10-06 rescope; not a
  current E009 deliverable.)* Operating this project against a live Gitea instance requires
  recording and certifying a supported Gitea server, act-runner, runner image digest, transitive
  executed-action set, and reusable-workflow edge set before any Gitea tuple is considered
  supported. Untrusted verification and protected publication would require separately scoped
  runner registrations with ephemeral workspaces and minimal mounts; inability to prove that
  routing would reject the tuple.
- **CI-AR35 — Practical conformance gate.** *(Deferred under the 2026-10-06 rescope; not a
  current E009 deliverable.)* Migrating to a live Gitea instance would require staging proof of PR
  verification, dev/stable destinations, private CA, artifacts, multi-arch images, forge Release,
  aliases-last, one failed-jobs-only rerun, and rollback steps for the pinned tuple.


### Lean publication requirements

- **CI-AR36 — Boundary revalidation.** Every publisher downloads the verified bundle, checks
  `SHA256SUMS`, validates `build-manifest.json`, matches source/version, and for image publication
  proves the exact wheel hash is the declared image input before any login or upload.
- **CI-AR37 — Destination-local failure.** Package, image, and forge Release jobs report their
  own actionable failures without a repository-specific all-destination protocol.
- **CI-AR38 — Maintained action behavior.** Standard actions own upload behavior. Package upload
  uses `pypa/gh-action-pypi-publish@dc37677b2e1c63e2034f94d8a5b11f265b73ba33`
  (`release/v1`, tagged `v1.14.2`, reviewed 2026-09-02). Operators rerun failed jobs only. If the forge
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

### Ref-free checkout (2026-10-08, ADR-0028)

Investigation of a local-`act` checkout failure found that `actions/checkout` reconstructs its
expected remote URL from the `repository`/`server-url` inputs and wipes/reinitializes the
workspace on any mismatch with the actual recorded origin -- the same mechanism behind the
2026-09-01 destructive-checkout incident. The only genuine no-op path is `act`'s own built-in skip
of the whole step, triggered only when a checkout step's `with:` block has no `ref:` key at all.
This pipeline's checkout call sites all carried `ref:` (threaded through so every job could
re-verify an externally-computed source identity), which is why this repository hit the failure
where comparable local `act`-based pipelines that never pass `ref:` to checkout do not. The scope
is **five** reusable/event-owner files, not four: `publish-image.yaml` has its own
`ref: ${{ inputs.source-sha }}` checkout, missed in an earlier pass of this redesign and caught by
the reviewer gate. Rejected alternatives: git URL `insteadOf` rewrites (reproduces the
destructive-checkout mechanism itself), `env.ACT`-based step branching (Gitea's own runners are
act-based too, so `ACT` does not distinguish local from production; also in tension with CI-AR2),
and a custom `LOCAL_VERIFY` environment flag (still host-conditional branching). A
single-checkout-plus-artifact-fanout design was also considered and rejected in favor of total
uniformity; see CI-AR43 for the resulting accepted trade-off. `act`'s no-`ref:` checkout skip
(the mechanism CI-AR42 depends on) was re-confirmed by live, side-by-side reproduction in a
disposable sandbox on 2026-10-08: a `ref:`-bearing checkout is executed for real, deletes the
workspace, and fails fetching an unpushed SHA against the real remote; a `ref:`-free checkout on
the same job is skipped entirely in under 40ms via a plain file copy, for both `actions/checkout@v4`
and `@v7`.

- **CI-AR42 — Ref-free checkout, everywhere.** No checkout step in `ci.yaml`, `dev.yaml`,
  `release.yaml`, `verify-build.yaml`, or `publish-image.yaml` ever supplies `ref:`, `repository:`,
  or any other identity-overriding input, **and no step after a ref-free checkout re-pins identity
  by another route** (no `git fetch`/`git checkout <sha>` shell step, no env-var-indirected
  `ref:` expression, no nested composite action that re-checks-out). Every checkout is the
  plainest possible `actions/checkout@v7` call (`fetch-depth`/`fetch-tags`/`persist-credentials`
  only), relying on the ambient event context GitHub, Gitea, and local `act` each already provide.
  **Prevents:** host-conditional or channel-conditional checkout branching, destructive-checkout
  failures under local `act` for unpushed commits, and N-times-duplicated `ref:` plumbing across
  call sites. **Enforceable** by a workflow-contract test asserting (a) no `actions/checkout` step
  anywhere under `.github/workflows/` declares a `ref:` or `repository:` key, and (b) no step in
  any job that runs after a checkout step invokes `git fetch`, `git checkout`, or `git reset
  --hard` against an argument other than a path already present in the working tree.
- **CI-AR43 — PR verification tests the merge commit.** `ci.yaml`'s verification of a pull
  request exercises GitHub's synthesized merge-with-base commit (the default `pull_request`
  checkout target), not an explicitly pinned PR head SHA; no job computes or asserts
  `github.event.pull_request.head.sha`. **Accepted trade-off:** a long-running PR run's
  independently-checked-out jobs could in principle observe a recomputed merge ref if the base
  branch moves mid-run. This narrow drift risk is accepted in favor of CI-AR42's uniformity rather
  than engineered around with a single-checkout-plus-artifact-fanout design.
- **CI-AR44 — Self-discovered build identity; assertion values still flow as data.** `verify-build.yaml`
  does not accept `source-sha` as a `workflow_call`/`workflow_dispatch` input. Its
  `source-integrity` job discovers it via `git rev-parse HEAD` as the immediate next step after
  checkout -- before any other step, so no later step in that job can change what is recorded --
  and emits it only as a job output; every other job's own identity output (used only for its
  own `build-manifest.json` evidence row) is likewise captured as the first post-checkout step of
  that job. `package-version` is an optional `workflow_call` input (`required: false`): a caller
  that has one **omits the key from `with:` entirely** (never an empty string); `dev.yaml`/
  `release.yaml` omit it for the `ci` channel's own call and supply it only for their own
  dev/stable calls, to cross-validate against the built wheel. When the key is absent, the
  `distribution` job reads the committed `pyproject.toml` version directly and performs no
  cross-validation. This does not weaken CI-AR11 or CI-AR36, and it does not stop `source-sha`
  from flowing where boundary revalidation needs it: `verify-build.yaml`'s self-discovered
  `source-sha` output is still threaded as a plain **data value** (never a checkout `ref:`) into
  `publish-image.yaml`'s required `source-sha` input and into every destination job's
  `expected-source-sha` revalidation argument against the `verified-bundle` composite action,
  exactly as the pre-existing CI-AR36 boundary-revalidation mechanism requires. Only the checkout
  pinning is removed; the assertion chain is unchanged.
- **CI-AR45 — `ci.yaml` is a single job.** `ci.yaml` has no separate `plan` job; it calls
  `verify-build.yaml` directly with only `channel: ci`, since CI-AR42/CI-AR44 remove the need for
  a pre-checkout pre-validation stage.
- **CI-AR46 — No internal ref re-threading.** `dev.yaml` and `release.yaml` retain their `plan`
  jobs (genuine dev-distance version derivation and stable-tag validation are real, channel-specific
  work that belongs there, including self-discovering their own `source-sha` output via
  `git rev-parse HEAD` for downstream data-flow use under CI-AR44), but no job downstream of `plan`
  -- including `stable-tag-guard`, `attest`, the `verify-build.yaml` call, and the
  `publish-image.yaml` call -- re-threads `ref:` into its own checkout. `github.sha` is immutable
  for the whole run on push/tag triggers, so every job's independent ref-free checkout resolves to
  the identical commit with zero drift risk; only the `source-sha`/`package-version` **values**
  (never a checkout override) continue to flow downstream for CI-AR36 boundary-revalidation
  assertions.

## Workflow Responsibilities

| Workflow | Trigger | Secrets | Mutation |
|---|---|---|---|
| `ci.yaml` | pull request | none | none |
| `dev.yaml` | protected default-branch push | destination jobs only | immutable dev packages/images; Story 8.3 moves `dev` |
| `release.yaml` | exact `vX.Y.Z` tag | destination jobs only | stable packages/images/Release; aliases last |
| `verify-build.yaml` | reusable call or dispatch | none | workflow artifacts only |
| `publish-image.yaml` | reusable call from dev/release | explicit forge token and optional Docker Hub credentials only | one multi-platform build, immutable image publication, attestation, and image aliases |

`verify-build.yaml` accepts only channel and an optional expected package version (CI-AR44); it
discovers source identity itself via `git rev-parse HEAD` after a ref-free checkout (CI-AR42).
Publisher adapters consume its single evidence bundle.

## Configuration Contract

### Repository variables

| Variable | Meaning | Default |
|---|---|---|
| `PUBLISH_IMAGE_DOCKERHUB` | additionally publish to Docker Hub; **stable channel only, inert in `dev.yaml`** | `false` |
| `PUBLISH_PACKAGE_TESTPYPI` | publish development distributions to TestPyPI | `false` |
| `PUBLISH_PACKAGE_PYPI` | publish stable distributions to PyPI | `false` |
| `DOCKERHUB_ORG` | Docker Hub namespace only; the image name follows the built image | derived from the forge owner |

The active forge registry is always required. The Gitea package index is always required on
Gitea; GitHub has no equivalent Python index. The canonical Gitea upload endpoint appends
`/api/packages/<lowercase repository owner>/pypi` to `github.server_url`, derived once by the plan
job and consumed through its `package-index-url` output. Destination jobs do not recompute forge
kind or coordinates. The maintained `pypa/gh-action-pypi-publish` adapter consumes this upload
endpoint with username `__token__` and `FORGE_PACKAGE_TOKEN`; an install/simple-index URL is not
interchangeable with the upload endpoint.

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
| TestPyPI/PyPI | OIDC trusted publishing | unsupported by host capability; no credential path |
| forge image | automatic repository token to GHCR | automatic repository token to the derived Gitea registry; effective scope: live certification deferred, 2026-10-06 rescope |
| forge package | unavailable | scoped package token |
| Docker Hub | username + scoped token | username + scoped token |
| forge Release and Git aliases | automatic repository token with `contents: write` | automatic repository token; write behavior and denial boundaries: live certification deferred, 2026-10-06 rescope |
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

## Supply-chain and gate-coverage rules (E012-S01-002)

- **CI-AR47 — Every external action is pinned to a reviewed commit.** Supersedes CI-AR4's
  default. Every `uses:` in a governed definition names a 40-character commit SHA with a
  trailing `# vX.Y.Z` comment, and the commit is the one recorded in
  `tests/ci/support.py::PINNED_ACTIONS`. The floating major is no longer the default for
  approved owners: the weakest reference in a job sets the trust level of the whole job, and
  five tagged actions beside one pinned one bought nothing. The one exception is registered,
  not implied — `ACTIONS_ON_MOVING_REFS` holds `actions/upload-artifact` and
  `actions/download-artifact` at `@v4`, because Gitea's `act_runner` implements only the v4
  artifact protocol (Epic 9 forge portability) and resolving a GitHub commit SHA there is not
  something this repository can assume. Guards:
  `test_no_governed_definition_calls_an_action_on_a_moving_ref` and
  `test_every_pinned_action_is_called_at_exactly_the_commit_it_was_reviewed_at`. See ADR-0031.

- **CI-AR48 — The vendored tool trees have a repository-side integrity record.**
  `vendored-trees.lock` names the vendored set (`.agents/`, `.claude/`, `_bmad/`) and holds a
  SHA-256 for every tracked file in it. The pre-commit `exclude:` is validated *against* that
  set rather than parsed to recover it, so no integrity check depends on a regex keeping one
  shape. `scripts/vendored_trees.py --write` regenerates the lock and the generated coverage
  block in `.github/CODEOWNERS` in one command, which is what keeps the asserted counts from
  being a person's arithmetic. The lock is a repository-side reference and does not claim to
  match what upstream published; the 142 files a `payload-manifest.json` names are the only
  ones that do. See ADR-0032.

- **CI-AR49 — The content gates exempt no path, and block in proportion to what they mean.**
  `.gitleaks.toml` allowlists values, never directories: the vendored trees are scanned, and
  the two false-positive classes that surfaced are allowlisted by their whole value or whole
  line, with no `paths` key (which exempts a file outright, even under `condition = "AND"`).
  `verify-build.yaml`'s self-proving probe plants a credential inside `_bmad/`, and a
  near-miss for each allowlist, and requires the scan to **fail** on every one. The untracked-file
  gate blocks under `src/`, `tests/` and `.github/`, where "untracked" means a linter reported
  green over code it never read, and warns everywhere else, where no file-scoped hook would
  have read the file whether it was tracked or not. See ADR-0033.

- **CI-AR50 — Governance gates live in `verify-build.yaml`.** The `supply-chain` and
  `untracked-coverage` jobs join `gitleaks`, `actionlint`, `file-hygiene` and
  `source-integrity` there, and block `distribution` like every other gate. `ci.yaml`,
  `dev.yaml` and `release.yaml` hold no gates of their own (ADR-0029); a gate added to one of
  them would run on one channel.
