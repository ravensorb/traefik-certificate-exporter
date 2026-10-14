# E015 sprint 02 — red team report

- **Method:** `l3io-sec-redteam` lenses (external attacker, malicious insider, supply chain, misconfiguration, abuse of trust). It ran inline in the closure agent because this runtime has no subagent tool.
- **Scope:** sprint-level security analysis, epic E015 sprint S02, covering the four done stories and MD-26.
- **Seeds:** the sprint diff (see `adversarial-review.md`) and the Files in scope of E015-S02-001, -002, -003 and -005.
- **Widened to, and why:**
  - The whole `release` and `publish-image` jobs of `release.yaml`, and the classify step. The token fallback changes which credential reaches which step.
  - The `justfile` `act` recipe. It is the boundary for local runs.
  - The "Maintainer actions record" in `notes-E015-S02-002.md`. It establishes what the deployed Gitea token can do; it records names and HTTP codes only, no values.
- **Target design:** MD-26 / ADR-0052. Residual risks the maintainer accepted are stated as such and are not re-litigated.

## Surface map (what changed)

| Surface | Before the sprint | After |
|---|---|---|
| `publish-image` job token | `contents: read` | `contents: read`, `packages: write`. On github.com it is used for GHCR when `PUBLISH_GHCR_TOKEN` is unset. |
| `release` job token | `contents: read`; the release used `PUBLISH_RELEASE_TOKEN` | `contents: write`, `pull-requests: read`; the release uses `PUBLISH_RELEASE_TOKEN` or the job token |
| BuildKit CA trust | not delivered (removed `config` input) | delivered through `buildkitd-config`, scoped to the enabled Gitea registry host only |
| Hook tool installs | import-linter and mypy envs resolved unpinned at install time | from `poetry.lock` (hashed, `pip-audit`ed); a guard refuses `additional_dependencies` |
| `.env` reading | cwd `.env` plus the `.env` in the package folder (under abc-owned `/app`); the image could read `/config/.env` from one-off runs | cwd `.env` only, and never in the image (`LOADDOTENV=false`); the switch cannot be set from any file |

## Findings

| ID | Lens | Severity | Finding | Disposition |
|---|---|---|---|---|
| RT-1 | supply chain | LOW | **Write-scoped job tokens are reachable by major-tag actions.** `publish-image` runs `LiquidLogicLabs/git-action-docker-metadata@v6` and `git-action-docker-test@v2`, and `release` runs `git-action-release-changelog-builder@v3` and `git-action-release@v2`. These are mutable major tags (AD-5, MD-26 goal 2). A composite action can evaluate `${{ github.token }}` in its own `action.yml`, so a compromised tag in `publish-image` can now use `packages: write` on this repository's packages until the job ends. In `release`, the actions were already handed a contents-write credential (`PUBLISH_RELEASE_TOKEN`) before MD-26, so the change there is small. This is a residual the maintainer accepted with goal 2; the related BL-E015-005 (log out before the image test) remains open. | Deferred, Low |
| RT-2 | misconfiguration | LOW | **A raw `act` run of `release.yaml` can create a real GitHub release from a workstation.** Outside `just act`, act fills `GITHUB_TOKEN` from `gh auth token`. That token usually has the `repo` scope, so `PUBLISH_RELEASE` is true and `git-action-release@v2` creates the release, with the locally built `dist/*`. MD-26 dropped the workstation-publishing rule on purpose, and `just act` still passes an empty token. The `justfile` comment now states this limit (AR-3). A cheap guard, if wanted: also require `github.actor != 'nektos/act'` (act's default actor) for the job-token fallback. | Deferred, Low (maintainer's call) |
| RT-3 | abuse of trust | LOW | **The Gitea publish token is broader than ADR-0052 and AD-13 state.** The GitHub `release` environment's `PUBLISH_GITEA_TOKEN` is the existing Infisical `GITEA_TOKEN`. It is not instance-admin (403 on `/api/v1/admin/users`) and it has `write:package`. It is not package-only, though, and it has the same value as Infisical's `E2E_GITEA_TOKEN` and `TEST_GITEA_TOKEN`. A leak from any one of those uses exposes all of them. The maintainer kept it on purpose (2026-10-14); a package-only token is the follow-up. | Deferred, Low |

No CRITICAL, HIGH or MEDIUM findings.

### Checked and not raised

- **AR-1's Gitea case** is a correctness defect (a misfire that fails the job), not a credential leak: the Gitea job token was sent only to ghcr.io, which rejects it. It is fixed (see `adversarial-review.md`).
- **Forge release on a Gitea tag run:** it uses the Gitea job token on the Gitea instance itself, which is ADR-0052's intent ("creates the release on the running forge").
- **S02-005:** a `PUID`-writable `/config/.env` no longer reaches any exporter run in the image, and the package-folder `.env` source under `/app` (BL-E015-002's tree) is gone. `loaddotenv` itself is withheld from every file source in every mode, and an invalid value fails closed. This narrows the PUID-to-root surface; no regression was found.
- **S02-003:** `poetry run` resolves `poetry` from PATH. In CI that is the hashed bootstrap (ADR-0042); locally it is the developer's own Poetry. There is no new trust boundary.
- **S02-001:** the private-CA BuildKit file now reaches `buildx create`, and only for the enabled Gitea registry host (`buildkit-registries`), so GHCR and Docker Hub pushes do not trust the private CA.

## Counts

| Severity | Count | Fixed | Deferred |
|---|---|---|---|
| CRITICAL / HIGH / MEDIUM | 0 | 0 | 0 |
| LOW | 3 | 0 | 3 |
