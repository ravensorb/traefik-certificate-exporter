# CI/CD Pipeline Assessment and Lean Publication Recommendation

Date: 2026-09-01

Status: implementation-ready planning baseline

Scope: build, verify, package, publish, release, GitHub/Gitea portability, and local workflows

## Executive Assessment

The repository has a strong secret-free verifier. It builds one wheel and one sdist, validates
their metadata and checksums, installs each distribution in a clean environment, and performs a
native image smoke test from the exact wheel. It does not yet produce a published multi-platform
OCI index; Epic 8 owns that work.

The complete pre-simplification design is preserved at commit
`dbc991c7595d087edc1a2f91e763d0418209116e` on
`archive/publication-transaction-v1`. Active development uses a leaner model:

- `ci.yaml` verifies pull requests without publication credentials;
- `dev.yaml` verifies protected default-branch commits and invokes normal destination jobs;
- `release.yaml` validates an annotated exact SemVer tag and invokes stable destination jobs;
- `verify-build.yaml` is the reusable, secret-free source of distributions and build evidence;
- each publisher validates `SHA256SUMS` and `build-manifest.json` before authenticating; and
- Story 8.3 moves mutable aliases only after all required destinations succeed.

## Retained Build Foundation

The retained bundle contains exactly one wheel, one sdist, `SHA256SUMS`, and
`build-manifest.json`. `build-manifest-v1` is the schema/version identifier, not the filename.
The manifest records only source SHA, normalized package version, optional development distance,
distribution filenames and hashes, image inputs and labels, and their fingerprint. It does not
record channel, platforms, lock hash, observed image digest, credentials, or run identity.

The verifier performs package and native-image smoke checks. Epic 8 must consume the exact wheel
and run one Buildx invocation for `linux/amd64,linux/arm64`. That single invocation applies tags
for the required forge registry and, when enabled, Docker Hub; a registry must never trigger a
second image build. Published digest and platform inspection become workflow/action outputs and
run-summary evidence, not another repository-owned schema.

## Trigger and Identity Guards

Development checkout fetches full history and tags once so first-parent distance is well-defined.
The version is `X.Y.(Z+1).devN`. If the source commit already has an exact stable tag, dev
publication is suppressed. Workflow concurrency prevents obsolete dev finalizers, and Story 8.3
rechecks immediately before moving `dev` that the candidate is still the protected default-branch
head.

Stable publication accepts only an annotated exact `vX.Y.Z` tag. Its peeled commit must equal the
event SHA and be reachable from the protected default branch; tag, committed Poetry version, built
metadata, lock, and application version must agree before credentials are available.

Forge detection fails closed for unknown hosts. A Gitea `FORGE_REGISTRY` override is valid only as
`host[:port]`: no user information, path, query, or fragment, and it must satisfy the same-forge
policy.

## Destination Model

The owning forge image registry is required. Docker Hub is optional under strict
`PUBLISH_IMAGE_DOCKERHUB=true|false`. One image job logs in only to enabled registries, receives
only their credentials, and publishes both registries' tags in its one multi-platform invocation.

Development packages optionally publish to TestPyPI; stable packages optionally publish to PyPI.
The owning Gitea Python index is required when that host capability exists. Package credentials
remain isolated from the image job. Disabled optional destinations receive no credential and make
no endpoint request; invalid booleans fail before authentication.

## Action Policy

Maintained actions own standard integrations. Approved first-party and LiquidLogicLabs actions
may use a documented floating major where policy permits; other third-party actions require a
reviewed full commit SHA. Package publishing is therefore planned as
`pypa/gh-action-pypi-publish@<reviewed-full-commit-sha>`. Implementation must resolve, review, and
record the actual SHA rather than invent one in planning.

Every destination revalidates the bundle before its first credentialed step. The image job emits
the published digest and inspected platforms. Package jobs emit destination outcomes. Run ID/URL,
artifact hashes, digest/platform inspection, Release URL, and alias outcomes are written to action
outputs and the workflow run summary.

## Failure and Rerun Policy

Destination failures stay local and actionable. Successful immutable package uploads must not be
repeated: operators rerun failed jobs only using the retained verifier evidence. If the active
forge cannot rerun only failed jobs, the evidence expired, or an immutable remote identity
conflicts, the run halts and is escalated; development uses a new version when appropriate. A
whole-workflow rerun is not the normal recovery procedure. Gitea certification must demonstrate
the supported failed-jobs-only path.

## Alias Finalization

Story 8.3 alone owns both development and stable alias finalization. Stable aliases `X.Y`, `X`,
`latest`, `vX.Y`, and `vX` move only forward to newer compatible stable versions. `dev` moves only
after all required development publishers succeed and the just-in-time head check passes. Alias
jobs copy the already-published digest and never rebuild it.

## Gitea Trust and Certification

Runner-host bootstrap trust is installed before a runner registers with or resolves the forge and
actions. A first job step cannot establish trust needed to start that same job. The job-level
`LiquidLogicLabs/git-action-ca-certificate-import@v3` action is separate: it adds trust only for
downstream endpoints contacted after the job begins.

Certification pins the Gitea server, act-runner, runner image, and action tuple. It proves PR
verification, artifact round-trip, protected dev/stable delivery, the one-build multi-platform
image flow, Release creation, forward-only aliases, private-CA behavior, credential isolation,
failed-jobs-only rerun, cleanup, and rollback. Evidence is retained in workflow run summaries and
outputs rather than a release-receipt schema.

## Delivery Plan and Definition of Done

Epic 7 is complete and retained as the build foundation. Epic 8 implements development and stable
immutable publication, Story 8.3 finalization, and topology/runbook cutover. Epic 9 certifies the
pinned Gitea environment. Dependencies remain `E007 -> E008 -> E009`.

The redesign is done when secret-free verification is portable; the exact verified distributions
reach the intended package destinations; one image build publishes both required platforms to all
enabled registries; disabled destinations do not authenticate; aliases are forward-only and last;
stable tags satisfy the annotated/reachability guard; failed-jobs-only recovery is proven on both
forges; and the pinned Gitea staging checklist is green.
