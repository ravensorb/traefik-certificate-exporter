# ADR-0052: Release publishing uses the forge's own token where it can

- **Status:** Accepted
- **Date:** 2026-10-14
- **Deciders:** Maintainer (ravensorb), 2026-10-14. Replaces the first version of this ADR
  (same day), which recorded maintainer decisions MD-10 … MD-15 of 2026-10-12.
- **Epic:** E015 (E015-S02-002)
- **Spine:** CI/CD spine AD-9 (configuration-gated destinations), AD-13 (credentials)
- **Amends:** ADR-0039 (which tokens live in a forge environment)

## Context

The pipeline's goals, as the maintainer stated them on 2026-10-14:

1. Run under nektos `act` locally, on self-hosted Gitea, and on GitHub.
2. Use LiquidLogicLabs actions where possible, pinned to their major version.
3. Publish the Python package to a custom registry or PyPI on release, and to a custom
   registry or TestPyPI on dev.
4. Publish the image to a custom registry, GHCR or Docker Hub.
5. Publish to a destination only when its variables are defined.
6. Keep the tokens for GitHub in Infisical, and copy them into GitHub when needed.

`dev.yaml` and `release.yaml` already meet 1–5 (AD-9). The first version of this ADR added a
classic personal access token for GHCR, a fine-grained token for the forge release, a "one
forge per release" rule with a per-release name check, a ban on workstation publishing, a
digest-equality checklist and a token-expiry table. The maintainer judged that
over-complicated for these goals.

## Decision

- **GHCR uses the job's own token on GitHub.** `publish-image` has `packages: write`. GHCR is
  enabled when `vars.PUBLISH_GHCR_IMAGE` is set and a token is available:
  `secrets.PUBLISH_GHCR_TOKEN` if set, else `github.token` when the run is on github.com
  (`github.server_url`). The username is
  `vars.PUBLISH_GHCR_USERNAME`, else `github.actor`. `PUBLISH_GHCR_TOKEN` stays as an
  optional override for `act` and Gitea runs, where the job token cannot push to ghcr.io.
- **The forge release uses the job's own token.** The `release` job has `contents: write` and
  `pull-requests: read` (for the changelog builder). It creates the release with
  `secrets.PUBLISH_RELEASE_TOKEN` if set, else `github.token`, so every forge tag run creates
  its release. Under `just act` the token is empty and the release is skipped.
- **Gitea keeps its own token.** Gitea's job token cannot publish to its package registry,
  so `PUBLISH_GITEA_TOKEN` is a separate token with `write:package` only, never an
  instance-admin token.
- **GitHub is the release forge.** Its `release` environment holds the release publish
  settings, copied from Infisical with `gh secret set` reading stdin. A destination is
  configured on one forge only; this is guidance, not a check.
- **Dropped:** the one-forge name check, the workstation-publishing rule (`just act` still
  passes no secrets and an empty `GITHUB_TOKEN`, AD-16), the digest-equality checklist and
  the token-expiry table.
- **Publishing from `act` is opt-in per destination** (amended 2026-10-14). `just act-publish`
  passes Infisical's token for each destination named (PyPI, TestPyPI, Gitea, Docker Hub)
  and the caller's var file. `GITHUB_TOKEN` stays empty, so GHCR and the forge release never
  publish from `act`.
- **0.3.0 is left as published.** Its Gitea image came from a local `act` run and differs
  from the Docker Hub build; 0.3.1 supersedes both. Backfilling a `v0.3.0` GitHub release
  is optional.

## Consequences

- The release needs no new personal access tokens on GitHub. GHCR's first push with the job
  token is the 0.3.1 release run (or a dev run with `PUBLISH_GHCR_IMAGE` set in `dev`); the
  package is public and linked to this repository.
- Two jobs have write permissions on GitHub: `publish-image` (`packages: write`) and
  `release` (`contents: write`). Both run only in the `release` or `dev` environment, behind
  its deployment policy (ADR-0039).
- Production on docker 6 follows GHCR `latest`, which moves from 0.2.0 to 0.3.1 with the
  first release that pushes to GHCR (`docs/upgrading.md`).
- Residual, unchanged: `publish-image` runs `LiquidLogicLabs/git-action-docker-metadata@v6`
  and `git-action-docker-test@v2` (major tags, AD-5) after the registry logins; BL-E015-005
  (log out before the image test) is the follow-up.
