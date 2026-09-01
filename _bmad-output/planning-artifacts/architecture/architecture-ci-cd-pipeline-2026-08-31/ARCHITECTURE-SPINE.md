---
title: CI/CD Pipeline Architecture Spine
project: traefik-certificate-exporter
date: 2026-08-31
status: approved-for-implementation
source_report: docs/ci/codex-assesment.md
recovered_on: 2026-09-01
---

# CI/CD Pipeline Architecture Spine

## Purpose

This spine defines the invariants for building, verifying, packaging, and publishing
`traefik-certificate-exporter`. It supports GitHub.com and one self-hosted Gitea installation
as alternative repository owners, Docker Hub as an additional image destination, TestPyPI for
development packages, and PyPI for stable packages.

The pipeline is designed around one rule: build once, verify once, and publish the exact same
artifact set everywhere. GitHub Actions-compatible YAML is the orchestration format; local
developer commands are exposed through `just` and invoke the same underlying tools and
contracts.

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
                                                         +-- multi-arch image
                                                         +-- manifest + checksums
                                                                 |
                  +------------------ immutable publish <---------+
                  |                  |                  |
               PyPI/TestPyPI     Docker Hub       active forge registry
                  |                                     |
                  +--------------- aliases/release <----+
```

## Architecture Requirements

The `CI-AR` identifiers are stable traceability keys. Stories and tests refer to them directly.

### Forge and portability

- **CI-AR1 — Single active forge.** The repository owner is either GitHub.com or self-hosted
  Gitea for a run. The active forge is derived from `github.server_url` and repository context;
  the pipeline does not publish across both forges in one run.
- **CI-AR2 — One workflow implementation.** GitHub Actions, Gitea Actions, and local `act`
  execute the same workflow graph. No step branches on the `ACT` environment variable.
- **CI-AR3 — Action-first composition.** Prefer maintained actions over repository shell
  scripts. Use LiquidLogicLabs actions where their documented contract fits; retain scripts
  only for project-specific validation or atomic transactions that no suitable action owns.
- **CI-AR4 — Version policy for actions.** Approved first-party and LiquidLogicLabs actions
  use a documented floating major alias when available; unfamiliar third-party actions are
  pinned to a reviewed commit SHA. Dependabot keeps action references current.
- **CI-AR5 — Stable workflow topology.** The post-cutover workflow set is exactly
  `ci.yaml`, `dev.yaml`, `release.yaml`, and reusable `verify-build.yaml`. Publishing adapters
  call the verifier rather than duplicate its build logic.
- **CI-AR6 — Host-neutral context.** Repository, owner, API, server, and registry coordinates
  come from action context and a minimal documented override when Gitea cannot derive a value.

### Local developer interface and version ownership

- **CI-AR7 — `just` is the local interface.** A root `justfile` exposes at least `setup`,
  `lint`, `test`, `test-local`, `package`, `image`, `build`, `verify`, and `release PART`.
- **CI-AR8 — One committed version.** Poetry project metadata is the committed version
  authority. Application/package metadata and release tags must agree with it.
- **CI-AR9 — Guarded release preconditions.** `just release PART` accepts only `major`,
  `minor`, or `patch`; requires a clean worktree on the default branch, an up-to-date upstream,
  a green local verification run, and an unused target version/tag.
- **CI-AR10 — Atomic deliberate tag.** The release recipe bumps SemVer, refreshes the lock if
  required, commits `release: vX.Y.Z`, creates annotated tag `vX.Y.Z`, then atomically pushes
  the commit and exact tag. CI never invents the stable version.
- **CI-AR11 — Stable agreement gate.** A stable workflow rejects any mismatch among the exact
  tag, committed Poetry version, built package metadata, lock state, and application-reported
  version.
- **CI-AR12 — Development identity.** Default-branch builds calculate the next patch PEP 440
  identity `X.Y.(Z+1).devN`, where `N` is the first-parent distance from `vX.Y.Z`; they do not
  commit, bump, or tag the repository.

### Build and verification

- **CI-AR13 — One distribution set.** A run creates one wheel and one sdist, records their
  names and SHA-256 hashes, and passes those exact files to every package publisher.
- **CI-AR14 — Exact-wheel image provenance.** The container image installs the verified wheel
  produced by the run. It does not rebuild the Python project or independently resolve
  dependencies inside the image job.
- **CI-AR15 — Reproducible build manifest.** `build-manifest-v1.json` records source SHA,
  package version, channel, artifact hashes, image platforms, and image digest without secrets
  or run-specific fields that would make identical source produce different evidence.
- **CI-AR16 — Multi-architecture image.** The supported image platforms are
  `linux/amd64,linux/arm64`. QEMU and Buildx produce one OCI manifest list, and verification
  proves both platform descriptors exist.
- **CI-AR17 — Immutable identities.** Development images first publish as
  `dev-<12-character-source-sha>`; stable images first publish as exact `X.Y.Z`/`vX.Y.Z`
  according to the repository naming contract. Package versions are inherently immutable.
- **CI-AR18 — Verify before mutation.** Linting, unit/integration tests, package metadata
  checks, install smoke tests, container smoke tests, workflow contract tests, and artifact
  checksum verification finish before any external publisher authenticates or mutates state.

### Destination and publication contracts

- **CI-AR19 — Strict toggles.** Publication variables accept only case-normalized `true` or
  `false`; absent means false; any other value fails planning. Shell truthiness is forbidden.
- **CI-AR20 — Image destinations.** `PUBLISH_IMAGE_DOCKERHUB` independently enables Docker
  Hub. `PUBLISH_IMAGE_FORGE` enables the current owner's registry: GHCR on GitHub or the local
  Gitea registry on Gitea. There are no separate GHCR and Gitea booleans.
- **CI-AR21 — Package channels.** Development releases may publish only to TestPyPI under
  `PUBLISH_PACKAGE_TESTPYPI`. Stable releases may publish only to PyPI under
  `PUBLISH_PACKAGE_PYPI`. Forge package publication is intentionally out of scope.
- **CI-AR22 — Publication plan.** Before publishing, the workflow emits schema-validated
  `publication-plan-v1.json` with channel, version, source SHA, enabled targets, non-secret
  coordinates, immutable tags, aliases, credential modes, and run correlation.
- **CI-AR23 — Aggregate preflight.** Every enabled destination is validated before the first
  login, OIDC request, upload, image push, release creation, or alias mutation. A failure blocks
  the complete fan-out.
- **CI-AR24 — Least privilege.** Each publisher receives only its destination's credentials
  and job-level permissions. Disabled destinations map no secrets, request no OIDC identity,
  perform no login, and contact no endpoint.
- **CI-AR25 — Credential modes.** GitHub.com uses PyPI/TestPyPI trusted publishing where
  configured. Gitea uses protected API tokens for PyPI/TestPyPI. Docker Hub and Gitea registry
  use scoped tokens; GHCR uses the repository token with package-write permission.
- **CI-AR26 — Idempotent immutable publication.** A rerun accepts a remote object only when
  filenames, hashes, or manifest digest match the local manifest. Mismatch is a hard failure;
  immutable objects are never overwritten or silently skipped.
- **CI-AR27 — Immutable-first fan-out.** Enabled package and image destinations publish in
  parallel only after aggregate preflight and verification. Mutable aliases never advance
  until all enabled immutable publications have succeeded or been identity-matched.
- **CI-AR28 — Stable forge release.** A stable run creates or reconciles one release on the
  active forge for the exact tag and attaches checksums/evidence; no release is created for a
  development build.
- **CI-AR29 — Forward-only aliases.** Stable image aliases `X.Y`, `X`, and `latest`, plus Git
  tags `vX.Y` and `vX`, may advance only to a newer compatible stable version. `dev` advances
  only after the whole development fan-out succeeds. Prereleases never advance stable aliases.
- **CI-AR30 — Release receipt.** `release-receipt-v1.json` records planned and observed
  identities, destination outcomes, image digests, package hashes, release URL, and alias
  movements. It contains no credentials.
- **CI-AR31 — Evidence retention.** Distribution artifacts, manifests, plans, receipts, and
  test evidence used for recovery are retained for 30 days and stay inside the originating
  workflow run.

### Trust boundaries and Gitea certification

- **CI-AR32 — Secret-free pull requests.** Pull-request workflows receive read-only contents
  permission, no publisher secrets, no OIDC write permission, and never execute publication
  jobs, including for forked pull requests.
- **CI-AR33 — Safe local `act`.** `just test-local` runs the selected workflow against a
  disposable clone/worktree so checkout and cleanup behavior cannot rewrite the developer's
  working tree. It uses synthetic/local-only secrets and never production publisher tokens.
- **CI-AR34 — Pinned isolated Gitea runners.** The supported Gitea/runner/action tuple is
  documented and pinned. Untrusted verification and protected publishing use isolated runner
  labels/pools, ephemeral job environments, minimal host mounts, and restricted network access.
- **CI-AR35 — Gitea conformance gate.** Migration to Gitea requires a staging run proving PR,
  development, stable, multi-arch, private-CA, token, registry, artifact, release, retry, and
  recovery behaviors. The evidence is recorded before changing the production owner.

## Workflow Responsibilities

| Workflow | Trigger | Secrets | Mutation |
|---|---|---|---|
| `ci.yaml` | pull request; optional manual | none | none |
| `dev.yaml` | push to protected default branch | enabled destination jobs only | optional TestPyPI/images; `dev` alias last |
| `release.yaml` | exact `vX.Y.Z` tag | enabled destination jobs only | PyPI/images/forge release; stable aliases last |
| `verify-build.yaml` | `workflow_call`, `workflow_dispatch` | none | workflow artifacts only |

`verify-build.yaml` accepts only channel, package version, and source SHA. Publisher adapters
own destination planning, preflight, authentication, and mutation.

## Configuration Contract

### Repository variables

| Variable | Meaning | Default |
|---|---|---|
| `PUBLISH_IMAGE_DOCKERHUB` | Publish image to Docker Hub | `false` |
| `PUBLISH_IMAGE_FORGE` | Publish image to active forge registry | `false` |
| `PUBLISH_PACKAGE_TESTPYPI` | Publish development package to TestPyPI | `false` |
| `PUBLISH_PACKAGE_PYPI` | Publish stable package to PyPI | `false` |
| `FORGE_REGISTRY` | Gitea registry override only when host derivation is unsafe | derived |
| `DOCKERHUB_REPOSITORY` | Docker Hub namespace/repository | required when enabled |

The package toggles are intentionally channel-specific. The image toggles are destination-
specific because a release may fan out to Docker Hub and the active forge registry together.

### Secrets and protected environments

| Target | GitHub.com | Gitea |
|---|---|---|
| TestPyPI/PyPI | OIDC trusted publishing, protected environment | scoped token, protected environment |
| GHCR | repository token, `packages: write` | N/A |
| Gitea registry | N/A | scoped registry token |
| Docker Hub | username + scoped access token | username + scoped access token |
| Private CA | optional CA bundle input | protected CA bundle input |

## Publication State Machine

```text
PLAN
  -> VERIFY
  -> PREFLIGHT_ALL_ENABLED_TARGETS
  -> PUBLISH_IMMUTABLES
  -> RECONCILE_FORGE_RELEASE (stable only)
  -> ADVANCE_ALIASES
  -> WRITE_RECEIPT

Any failure before ADVANCE_ALIASES leaves the previous mutable pointers intact.
Recovery reruns PLAN and verifies existing immutable identities before continuing.
```

## Local Release Transaction

`just release patch` (or `minor`/`major`) owns the deliberate release transaction:

1. Verify the requested part and required tools.
2. Require a clean default-branch worktree and a non-detached `HEAD`.
3. Fetch tags and prove local default branch equals its upstream.
4. Run the same local verification interface used by CI.
5. Read the committed version once and calculate the SemVer target.
6. Update Poetry metadata and lock consistency.
7. Re-run the version and package checks.
8. Commit `release: vX.Y.Z` and create annotated `vX.Y.Z`.
9. Use `git push --atomic <remote> <default-branch> vX.Y.Z`.
10. On any failure before push, leave a clearly reported, recoverable local state; never force
    or delete a remote tag.

Floating Git tags are intentionally created by the stable CI finalizer with
`LiquidLogicLabs/git-action-tag-floating-version@v1`, after immutable publication succeeds.

## Verification and Test Anchors

- Unit tests for SemVer calculation, strict booleans, channel routing, forge derivation,
  schemas, alias ordering, and idempotency decisions.
- Workflow contract tests parse YAML and prove permissions, triggers, reusable-workflow edges,
  secret isolation, and verify-before-publish dependencies.
- Package smoke tests install the wheel in an empty environment and invoke the CLI.
- Image tests inspect both `linux/amd64` and `linux/arm64`, start the container, and prove its
  installed distribution hash/version matches the wheel manifest.
- Failure injection tests cover missing credentials, one registry unavailable, partial remote
  state, alias finalizer failure, rerun, tag/version mismatch, and cancelled verification.
- Gitea staging conformance runs the same contract suite under the pinned runner tuple.

## Implementation Sequence

1. **Epic 7 — Reproducible Build and Verification:** local interface, version transaction,
   contracts, one artifact set, PR/act governance.
2. **Epic 8 — Multi-Channel Package and Image Delivery:** development and stable publication,
   multi-registry fan-out, aliases, receipts, recovery.
3. **Epic 9 — Certified Gitea Portability:** pinned runners, private CA and credentials,
   end-to-end conformance and migration.

This sequence is deliberately serial at epic level: publication depends on verified artifacts,
and Gitea certification depends on the complete publication system it certifies.
