# Architectural Drift Review — E015 sprint 02

- **Mode:** l3io-arch-review Mode B (architectural review), headless, run inline in the closure agent because this runtime has no subagent tool
- **Date:** 2026-10-14
- **Scope:** the sprint diff (see `adversarial-review.md`) for stories E015-S02-001, -002, -003 and -005, plus the maintainer's MD-26 simplification. E015-S02-004 (the 0.3.1 release) is carried over and was not reviewed.
- **Target spec:** the simplified CI spine (AD-9, AD-10, AD-12, AD-13 as rewritten 2026-10-14) and ADR-0052 as rewritten. MD-10 … MD-15 are overturned and are **not** a reference for drift.
- **ADRs:** ADR-0052 (new), ADR-0039 (amended by 0052), ADR-0042 (amended by S02-003), ADR-0049 (amended by S02-005). `spec-align adrs --epic E015` lists only 0049–0051, because ADR-0052 is still untracked; it was read directly.
- **Spec alignment:** on. `spec-align sections` found no resolvable pointers in the four story files, so the ranges below were chosen from the spec index for each diff hunk.

## Executive summary

The sprint's code matches the spine sections it binds, with one exception. S02-001's `buildkitd-config` and its guard match AD-18. S02-003's `language: system` / `poetry run` hooks and `precommit-hook-deps-locked` match AD-3 and ADR-0042 as amended. S02-005's `settings.loaddotenv`, the third trust class and the image `ENV` match product spine AD-2/AD-6, ADR-0049 and PRD FR-18. The image still follows LinuxServer conventions (one `ENV` line, no init or s6 change).

The exception is in MD-26's own workflow expression. The GHCR job-token fallback was not limited to github.com, which contradicted AD-13's statement that `PUBLISH_GHCR_TOKEN` is needed on Gitea (SD-02-1). It is fixed in code. Count: 0 BLOCKER, 1 MAJOR, 3 MINOR.

## Findings table

| # | Severity | Principle | Location | Finding | Remediation |
|---|----------|-----------|----------|---------|-------------|
| SD-02-1 | MAJOR | Spec alignment (code contradicts the ADR it cites) | `.github/workflows/dev.yaml:248`, `release.yaml:313` (`PUBLISH_GHCR`, `PUBLISH_IMAGE`, `GHCR_IMAGE`); CI spine AD-13, ADR-0052 Decision | AD-13 says `PUBLISH_GHCR_TOKEN` is "needed only where the job token cannot do the job (GHCR from act or Gitea)", and ADR-0052 says the same. The flag fell back to `github.token` on every forge, so on Gitea it enabled GHCR with a token that cannot push there (AR-1). | Resolved in code: the fallback requires `github.server_url == 'https://github.com'`. The spine AD-9 example, the walkthrough and the ADR-0052 bullet were updated, and a spine changelog line was added. |
| SD-02-2 | MINOR | Spec vs deployed configuration | CI spine AD-13 (`PUBLISH_GITEA_TOKEN`: "a `write:package`-only token"), ADR-0052 ("`write:package` only"); GitHub `release` environment | The deployed `PUBLISH_GITEA_TOKEN` is the maintainer's general Infisical `GITEA_TOKEN`. It is not admin and it has `write:package`, but it is not package-only, by the maintainer's choice on 2026-10-14. The rule is right; the deployment is behind it. | Defer: backlog item for a package-only token (same item as RT-3). |
| SD-02-3 | MINOR | Spec currency | CI spine `sources:` (line 29) | The source list still said "MD-10..MD-18 accepted 2026-10-12", although MD-26 overturns five of them. | Resolved in code: the line now names MD-26 and what it overturns. |
| SD-02-4 | MINOR | Core §10 (docs that contradict the code) | `docs/upgrading.md:377-379` | "A mirrored run there publishes nothing" no longer holds: the forge release falls back to the job token on any forge (AR-2). | Resolved in code (wording). |

## Gate

- SD-02-1 (MAJOR): **resolved-in-code**.
- SD-02-3 and SD-02-4 (MINOR): resolved in code. SD-02-2 (MINOR) is deferred to the backlog.

## Recommended ADRs

None new. The SD-02-1 fix narrows ADR-0052 to its stated intent and is recorded in the ADR text and the spine changelog.

## Sections read

- `_bmad-output/planning-artifacts/architecture/architecture-ci-cd-pipeline-2026-10-08/ARCHITECTURE-SPINE.md` L20-35 (sources), L180-215 (AD-9), L235-250 (AD-12, AD-13), L280-290 (AD-16), L305-320 (AD-18), L420-460 (ADRs carried forward, Changelog)
- `docs/adr/0052-release-publication-one-forge-run.md` (whole, one page)
- `_bmad-output/planning-artifacts/architecture/architecture-traefik-certificate-exporter-2026-08-30/ARCHITECTURE-SPINE.md` L165-200 (AD-2 `.env` rule, trust classes), L318-325 (AD-6)
- `_bmad-output/planning-artifacts/prds/prd-traefik-certificate-exporter-2026-08-30/prd.md` L50-55, L97 (FR-18)
- `docs/upgrading.md` L50-66, L124-133, L370-385; `docs/ci/pipeline-walkthrough.md` L133-180
- `_bmad-output/implementation-artifacts/epic-015/maintainer-decisions.md` L35-43 (index), MD-26 heading
- `_bmad-output/implementation-artifacts/spec/spec-index.md` (to pick the ranges above)

Blocker: 0, Major: 1, Minor: 3
