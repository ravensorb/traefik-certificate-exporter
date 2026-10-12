# Spec proposal AD-1 (MAJOR) — 0.3.0 release topology departed from CI spine AD-9/AD-10

- **Target pointer:** `_bmad-output/planning-artifacts/architecture/architecture-ci-cd-pipeline-2026-10-08/ARCHITECTURE-SPINE.md#ad-9--configuration-gated-destinations-one-forge-per-release-adopted` (L178–204); also AD-10 (L205–216) and E014-S02-007 AC 6/8/9.
- **Finding:** `../arch-drift-review.md` AD-1.

## What was built

0.3.0 reached PyPI and Docker Hub from GitHub release run 38281339396 on the real `v0.3.0` tag (`046016b`), and Gitea from a workstation `act` run on `c7394e2` with a maintainer token. One version has two image digests (Gitea `sha256:244015fe…`, Docker Hub `sha256:e3be0498…`). GHCR has no `0.3.0`; there is no GitHub release for `v0.3.0`. Wheel and sdist are byte-identical across PyPI and Gitea.

## Proposed change (for E015 "0.3.1" triage; not applied — 0.3.0 is released)

1. Retag Gitea `0.3.0`, `0.3`, `latest` to the Docker Hub digest with `docker buildx imagetools create` (copy, no rebuild).
2. Record the one-off exception to AD-9 / ADR-0039 in an ADR (or ADR-0046 item) with its revisit condition (Gitea `act_runner`, BL-E013-044).
3. Track the GHCR first publish (AC 8) and the forge release with wheel/sdist (AC 9) as backlog items, or reopen E014-S02-007.
4. Add to `docs/ci/pipeline-walkthrough.md`: an `act`-driven release publish may run only on a tag already pushed to the protected forge, and the run's `HEAD` must equal `git ls-remote origin refs/tags/vX.Y.Z^{}`.

## Why

AD-10's "one digest per run across every registry" and AD-9's "one forge per release" are no longer true of the shipped artefact, and nothing records it. Related: redteam RT-2 (token handling for the same publish).

## Disposition rationale

Not a BLOCKER; per the epic-closure directive (0.3.0 released, non-BLOCKER/CRITICAL findings defer to E015), this is proposed rather than applied.
