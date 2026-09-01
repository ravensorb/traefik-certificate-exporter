# CI/CD Pipeline Assessment and Implementation Recommendation

Date: 2026-09-01

Status: implementation-ready planning baseline

Scope: build, verify, package, publish, release, GitHub/Gitea portability, and local workflows

> Recovery note: this report recreates the decisions approved during the prior coaching
> session. No committed or dangling Git object contains the lost report. The former
> `docs/ci/claude-assesment.md` is also absent from `main` and the preserved feature branch,
> so the comparison below reconstructs the agreed differences rather than claiming a
> line-by-line recovery.

## Executive Assessment

The current pipeline has useful building blocks but does not yet provide one coherent release
system. Build, test, package publication, container publication, and release-tag maintenance are
split across five workflows with overlapping triggers and different ownership models. A stable
tag can therefore cause more than one path to build or publish, the container build defaults to
one architecture, and package and image jobs do not prove they are publishing the same verified
source artifact.

The recommended target is a three-adapter/one-verifier model:

- `ci.yaml` verifies pull requests without secrets or publication.
- `dev.yaml` verifies default-branch commits and optionally publishes development artifacts.
- `release.yaml` validates a deliberate exact SemVer tag and publishes stable artifacts.
- `verify-build.yaml` is the reusable, secret-free build and verification implementation.

This gives the project one artifact lineage, supports GitHub.com or Gitea as the active forge,
and permits image fan-out to both Docker Hub and the active forge registry. Package routing is
intentionally different: development versions go only to TestPyPI, and stable versions go only
to PyPI. The local `justfile` makes routine build/test/release operations discoverable without
turning shell scripts into a second orchestration platform.

## Current-State Findings

### What is already good

- The repository already uses reusable workflow calls for container work.
- QEMU and Buildx are present in the container workflow, so multi-architecture support is an
  extension of the current design rather than a replacement.
- LiquidLogicLabs Docker metadata and CA-certificate actions are already accepted project
  dependencies.
- Poetry is the established package and lock authority.
- Pre-commit already assembles `ruff`, secret detection, `actionlint`, and file-hygiene checks.

### Material gaps

| Severity | Finding | Consequence |
|---|---|---|
| Critical | No single artifact promotion contract | Package and image jobs can publish outputs that were built or resolved independently. |
| High | Five overlapping workflows and triggers | Tag/default-branch events can take multiple paths with unclear ownership. |
| High | Release automation invents/maintains versions remotely | The application version, repository tag, and published version can drift. |
| High | Publication is not guarded by aggregate preflight | One destination may mutate before another target is known to be unusable. |
| High | Container default is `linux/amd64` | The published image is not a proven `amd64`/`arm64` manifest. |
| High | One selected image registry per run | Docker Hub plus the active forge registry cannot receive the same digest in one release. |
| Medium | Package publication is coupled to a build action | Reuse, preflight, hash reconciliation, and GitHub/Gitea auth differences are difficult to express. |
| Medium | Mutable tags are updated through ad-hoc shell | Ordering, forward-only behavior, and rerun safety are not explicit contracts. |
| Medium | Local commands are scattered | Developers cannot reliably reproduce the CI entry points or execute a guarded release. |
| Medium | Gitea compatibility is assumed | Runner isolation, private CA, action resolution, token auth, artifacts, and release APIs remain unproven. |

## Recommended Outcome

### Build once, publish many

Every CI, development, and stable path calls the same reusable verifier. It creates exactly one
wheel and one sdist, hashes them, installs the wheel into a clean environment, and builds the
container from that wheel. The image job builds `linux/amd64` and `linux/arm64` and records the
resulting manifest digest. Docker documents QEMU plus Buildx as the standard GitHub Actions
pattern for a multi-platform manifest: [Docker multi-platform Actions guide](https://docs.docker.com/build/ci/github-actions/multi-platform/).

The evidence bundle consists of:

- wheel and sdist;
- `SHA256SUMS`;
- `build-manifest-v1.json`;
- package-install and CLI smoke-test results;
- image smoke-test and platform-inspection results.

Publisher jobs download and validate this bundle. They never rebuild it.

### Deliberate stable releases

Stable publication begins with a local, deliberate `vX.Y.Z` tag. The proposed interface is:

```text
just release patch
just release minor
just release major
```

The recipe validates a clean and current default branch, runs verification, changes the
committed Poetry version, updates the lock consistently, creates the release commit and
annotated tag, and atomically pushes both. The stable workflow validates rather than chooses
the version. This keeps repository history, application metadata, package metadata, image tags,
and forge release identity synchronized.

Development builds do not use temporary Git tags. They derive a unique PEP 440 next-patch
version (`X.Y.(Z+1).devN`) and use immutable image tag `dev-<12sha>`. The floating `dev` image
tag moves only when every enabled development publication has succeeded.

### Destination behavior

Images may publish to either or both enabled image destinations:

| Variable | Destination |
|---|---|
| `PUBLISH_IMAGE_DOCKERHUB` | Docker Hub |
| `PUBLISH_IMAGE_FORGE` | GHCR when hosted on GitHub; local Gitea registry when hosted on Gitea |

Combining GHCR and Gitea into `PUBLISH_IMAGE_FORGE` is correct because repository ownership is
an either/or decision. Forge coordinates are derived from the execution host. This prevents a
redundant platform-mode toggle and prevents accidental cross-forge publication.

Package publication is channel-driven:

| Event/channel | Toggle | Destination |
|---|---|---|
| default-branch development | `PUBLISH_PACKAGE_TESTPYPI` | TestPyPI only |
| exact stable tag | `PUBLISH_PACKAGE_PYPI` | PyPI only |

There is no `PUBLISH_PACKAGE_FORGE`. That destination was deliberately removed from scope.

All four toggles default to false and accept only boolean `true`/`false`. An invalid value is a
configuration error. Disabled targets receive no secrets and make no network calls.

### Authentication model

On GitHub.com, PyPI/TestPyPI should use trusted publishing with `id-token: write` granted only
to the protected publisher job. PyPI documents this as the tokenless, short-lived credential
path and supports TestPyPI through the same publishing action:
[PyPI trusted-publisher guide](https://docs.pypi.org/trusted-publishers/using-a-publisher/).

On Gitea, PyPI/TestPyPI use scoped tokens because GitHub's OIDC identity is unavailable.
GHCR uses the GitHub repository token with package-write permission; the Gitea registry and
Docker Hub use scoped registry credentials. Credentials are mapped at job scope after plan and
preflight validation.

### Publication ordering and recovery

```text
plan -> verify -> preflight all enabled targets -> publish immutable objects
     -> reconcile stable forge release -> advance mutable aliases -> receipt
```

This ordering matters. If TestPyPI/PyPI or one image registry fails, an already-pushed
immutable image can remain safely addressable, but `dev`, `latest`, major, and minor aliases do
not move. A rerun compares remote hashes/digests with the build manifest and continues only
when identities match. It never overwrites a package version or treats `skip-existing` as proof
of equivalence.

For stable releases the finalizer advances:

- image aliases `X.Y`, `X`, and `latest`;
- Git aliases `vX.Y` and `vX`;
- only after package, every enabled registry, and forge Release reconciliation succeed.

`LiquidLogicLabs/git-action-tag-floating-version@v1` is a good match for repository major/minor
aliases: its official contract creates `vX` and optionally `vX.Y` from the exact tag. It is
used late in the finalizer, not as the source of the release version:
[LiquidLogicLabs floating-version action](https://github.com/LiquidLogicLabs/git-action-tag-floating-version).

### Action-first implementation

Use actions for standardized integration points and small repository code only for unique
contracts:

| Responsibility | Preferred implementation |
|---|---|
| Checkout/artifacts/Python | official `actions/*` floating major |
| QEMU/Buildx/login/build | official `docker/*` floating major |
| Docker metadata | `LiquidLogicLabs/git-action-docker-metadata@v6` |
| Private CA | `LiquidLogicLabs/git-action-ca-certificate-import@v3` |
| local `act` compatibility | `LiquidLogicLabs/git-action-docker-act-compatibility` at documented major |
| floating Git tags | `LiquidLogicLabs/git-action-tag-floating-version@v1` |
| PyPI upload | `pypa/gh-action-pypi-publish@release/v1` |
| release/tag validation | LiquidLogicLabs actions where the current interface satisfies the architecture contract |
| schemas, hash identity, guarded local release | small tested project modules/actions |

The preference for floating majors is deliberate for approved actions. Dependabot supplies
upgrade visibility. For a new or weakly trusted third-party action, pin a reviewed commit SHA.
GitHub's own publishing guide notes that SHA pinning is the strongest immutability choice, so
exceptions should be explicit:
[GitHub image-publishing guidance](https://docs.github.com/en/actions/tutorials/publish-packages/publish-docker-images).

### Why `just` fits

`just` is a command runner rather than a second build system. It gives recipes arguments,
dependencies, discovery, and consistent invocation from subdirectories, which fits the goal of
making existing Poetry, Docker, pre-commit, and `act` operations easier to run. The upstream
project explicitly positions it for project-specific commands and supports parameterized
recipes: [casey/just](https://github.com/casey/just).

Recommended recipes:

| Recipe | Contract |
|---|---|
| `just setup` | install Poetry dependencies and local tooling |
| `just lint` | run pre-commit/action validation |
| `just test` | run the automated suite |
| `just test-local workflow=ci` | run `act` against a disposable clone |
| `just package` | build wheel/sdist and validate metadata |
| `just image` | build the local platform image from the wheel |
| `just build` | package plus image |
| `just verify` | full local secret-free gate |
| `just release PART` | guarded SemVer bump, commit, annotated tag, atomic push |

The `justfile` should remain declarative and short. Complex validation belongs in small tested
Python modules or composite actions, not long embedded shell blocks.

## GitHub and Gitea Portability

Gitea Actions intentionally follows GitHub Actions syntax but documents behavioral differences,
including action URL resolution. Portability must therefore be certified, not inferred:
[Gitea comparison with GitHub Actions](https://docs.gitea.com/next/usage/actions/comparison).

The Gitea phase must establish:

- a pinned Gitea server, act-runner, runner image, and supported action-major tuple;
- isolated labels/pools for untrusted verification and protected publication;
- no broad host Docker socket or workspace mounts for untrusted pull requests;
- private-CA installation before checkout/login/API access;
- protected scoped tokens and secret masking;
- artifact upload/download and 30-day recovery evidence;
- end-to-end staging runs for PR, dev, stable, multi-arch, retries, partial failure, and aliases.

The production owner should not move until the staging conformance checklist is green.

## Comparison with the Prior Claude Recommendation

The missing Claude assessment cannot be quoted or diffed exactly. The reconstructed comparison
captures the choices that were explicitly discussed and accepted afterward.

| Topic | Shared direction | Final Codex recommendation |
|---|---|---|
| Workflow simplification | Consolidate duplicated build/publish logic | Exactly three adapters plus one secret-free reusable verifier |
| Registry support | Support GitHub/Gitea/Docker Hub | Docker Hub and active forge registry can both be enabled; GitHub vs Gitea remains either/or |
| Package destinations | Multiple configurable publishers | Only TestPyPI for dev and PyPI for stable; forge package publication removed |
| Release trigger | SemVer-based publishing | A deliberate local exact tag is authoritative; CI validates it |
| Development versions | Unique non-stable identities | Next-patch `.devN`, no temporary Git tag, immutable `dev-<sha>` image tag |
| Floating versions | Maintain convenient aliases | Use image/package semantics plus LiquidLogicLabs Git floating-tag action late in finalization |
| Local tooling | Provide local equivalents | Adopt a concise `justfile`, including guarded `release major|minor|patch` |
| Multi-architecture | Build portable containers | Require and test `linux/amd64` plus `linux/arm64` in one manifest |
| Failure handling | Avoid partial releases | Plan + aggregate preflight + immutable-first + aliases-last + receipt-based recovery |
| Forge portability | Compatible Actions YAML | Add pinned runner isolation, private CA, staging conformance, and an explicit migration gate |

The main refinement is that “multiple destinations” is not treated as several independent
publishing scripts. It is one planned transaction with destination-specific credentials and
immutable identity reconciliation.

## Target File Layout

```text
.github/
  actions/
    publication-contract/
    setup-poetry-python/
  workflows/
    ci.yaml
    dev.yaml
    release.yaml
    verify-build.yaml
scripts/
  committed_versions.py
  release_transaction.py
  release_reconcile.py
schemas/
  build-manifest-v1.schema.json
  publication-plan-v1.schema.json
  release-receipt-v1.schema.json
tests/ci/
  test_workflow_contracts.py
  test_publication_contract.py
  test_release_transaction.py
justfile
```

Names may be adjusted to existing conventions, but responsibilities and trust boundaries must
remain intact.

## Delivery Plan

The work is intentionally grouped into three epics and fourteen stories to reduce execution
overhead while keeping failure domains reviewable:

1. **Epic 7 — Reproducible Build and Verification** (five stories): establish the local
   interface, release transaction, machine contracts, exact artifact lineage, and PR/act
   governance.
2. **Epic 8 — Multi-Channel Package and Image Delivery** (six stories): development package,
   development images, stable preflight, stable immutable publication, release/aliases, and
   recovery/cutover.
3. **Epic 9 — Certified Gitea Portability** (three stories): runner baseline, private-CA and
   destinations, full staging certification and migration.

Each epic is one sprint. Epic dependencies are `E007 -> E008 -> E009`.

## Definition of Done

The CI/CD redesign is complete when:

- pull requests verify without secrets on GitHub, Gitea, and local `act`;
- the wheel/sdist hashes and image-installed wheel lineage are demonstrably identical;
- published images contain both required platforms and share the planned manifest digest;
- development publication routes only to enabled TestPyPI/image targets;
- stable publication routes only to enabled PyPI/image/active-forge Release targets;
- disabled targets neither authenticate nor contact their endpoints;
- a failed target leaves floating aliases unchanged;
- reruns reconcile exact remote identities and produce a complete receipt;
- `just release major|minor|patch` keeps app, package, commit, and exact tag synchronized;
- GitHub and Gitea staging conformance evidence is recorded; and
- the obsolete five-workflow topology has been removed after a successful cutover drill.

## Recommendation

Proceed with the three-epic plan. Do not start by adding more destination-specific workflows.
First establish the reproducible verifier and version transaction, then layer publication on
the verified bundle, and certify Gitea last. This sequencing gives every later operation a
testable artifact and recovery contract.

---

## Appendix: rules recovered from the original assessment

This document is a condensed rewrite. The original (~57 KB) was lost with the working tree on
2026-09-01 and was never fully read by any session, so only grep-matched fragments survive —
35 distinct lines, preserved with their original line numbers in the recovery snapshot.

Comparing those fragments against this rewrite surfaced four rules that are **not** expressed
above. All four govern concurrency and ordering, which is the part hardest to notice missing
and most expensive to get wrong. They are reproduced here verbatim, with the original line
numbers, so they are not lost a second time.

### 1. `N` in `.devN` is the first-parent commit count (original line 188)

> `1.2.3`, it derives a version such as `1.2.4.dev7`, where `7` is the first-parent commit
> count from …

The rewrite specifies the shape `X.Y.(Z+1).devN` but never defines `N`. Without a definition
the development version is not uniquely determined by the commit, and two commits can collide
on one version. First-parent distance is also what makes the sequence monotonic along the
default branch.

### 2. A stable tag event exclusively owns publication for its commit (original lines 69–70, 301–303)

> tag events can exist. `dev.yaml` may still run verification, but it must detect an exact
> stable tag at `HEAD` and skip development publication. The tag event exclusively owns
> publication for that commit.

> Before development publication, fetch tags and skip every publisher when `HEAD` is already
> the … publishing the same commit to both TestPyPI and PyPI or moving `dev` alongside
> `latest`.

This is the rule that stops a single commit being published to both the development and stable
channels, and stops `dev` being dragged onto a commit that `latest` also points at. The
rewrite's ordering section does not cover it.

### 3. Immutable publication and alias finalization are non-cancellable (original lines 298–299)

> immutable publication is non-cancellable. All development runs use a separate
> non-cancellable alias-finalization group for the floating `dev` tag.

Two distinct concurrency groups, both non-cancellable. A publication run cancelled midway is
precisely how a half-published artifact set arises — some registries written, others not, with
no receipt. The rewrite discusses aliases at length but never states that these groups must
not be cancellable.

### 4. Moving `dev` requires comparing against what `dev` already points at (original lines 312–315)

> After every enabled development publisher succeeds and after taking the alias lock, read the
> source SHA and first-parent distance recorded by the current remote `dev` manifest. Move
> `dev` by … An out-of-order older run succeeds without changing `dev`; a newer failed build …

The rewrite says `dev` "moves only when every enabled development publication has succeeded",
which is necessary but not sufficient. Success alone does not establish that this run is the
newest: a slow older build finishing last would move `dev` backwards. The original requires
reading the distance currently recorded on the remote `dev` manifest and declining to move it
when this run is older — the older run still succeeds, it just does not touch the alias.

### Two divergences to reconcile, not recovered rules

Flagged because they differ from other surviving sources rather than from the fragments:

- This rewrite proposes `LiquidLogicLabs/git-action-tag-floating-version@v1` for Git
  major/minor aliases. That owner is on the approved action allowlist, but the surviving
  fragment at line 674 describes `.github/actions/publication-contract/` as "the sole tag
  classifier and plan/manifest/receipt producer/validator", and the elaborated Epic 8 stories
  assume `docker buildx imagetools create` for OCI aliases. Decide which owns alias creation.
- This rewrite states forge package publication is removed, keeping only TestPyPI for
  development and PyPI for stable. The surviving fragment at line 21 and the elaborated Epic 8
  stories both have the owning forge's native package registry always published on Gitea. If
  the removal is deliberate, Epic 8's stories need updating to match; if not, this line does.
