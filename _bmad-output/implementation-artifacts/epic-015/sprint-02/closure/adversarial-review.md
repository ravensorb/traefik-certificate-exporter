# E015 sprint 02 — adversarial and clean-release review

- **Method:** `bmad-review` adversarial lens, with the clean-release checklist as `also_consider`. It ran inline in the closure agent because this runtime has no subagent tool, and it was scoped to the diff in the same way.
- **Content:** `git diff HEAD -- .github/workflows justfile .pre-commit-config.yaml pyproject.toml docker src tests docs README.md`, plus the untracked `docs/adr/0052-release-publication-one-forge-run.md` and `tests/test_container_dotenv.py`. These are the changes of the four done stories (S02-001, -002, -003, -005) and the maintainer's MD-26 simplification. E015-S02-004 (the 0.3.1 release) is carried over and was not reviewed.
- **Authorities:** ADR-0052 (rewritten 2026-10-14), CI spine AD-9, AD-13 and AD-18, ADR-0042 as amended, and ADR-0049 as amended by S02-005.
- **Target design:** MD-26 / ADR-0052 as rewritten. Findings judge whether the new design is correct; none proposes restoring MD-10 … MD-15.
- **Excluded:** findings already raised in `review-E015-S02-00{1,2,3,5}*.md`.

## Findings

| ID | scope | severity | location | finding | disposition |
|---|---|---|---|---|---|
| AR-1 | adversarial | MEDIUM | `.github/workflows/dev.yaml:248` and `release.yaml:313` (`PUBLISH_GHCR`), plus `PUBLISH_IMAGE` and `GHCR_IMAGE` in both files | **On Gitea, the GHCR fallback enabled GHCR with a token that cannot push to ghcr.io.** The flag was `vars.PUBLISH_GHCR_IMAGE != '' && (secrets.PUBLISH_GHCR_TOKEN != '' \|\| github.token != '')`. On Gitea, `github.token` is the Gitea job token, which is never empty. So setting `PUBLISH_GHCR_IMAGE` on Gitea without `PUBLISH_GHCR_TOKEN` marked GHCR **enabled**. The login to ghcr.io with the Gitea token would then fail and take down the whole multi-registry `publish-image` job, including the Gitea and Docker Hub pushes. ADR-0052 and the step's own hint say the job token "cannot push to ghcr.io" on Gitea, and that `PUBLISH_GHCR_TOKEN` is needed there. | **Fixed in place.** The fallback is now `(github.server_url == 'https://github.com' && github.token != '')` in all six expressions. On Gitea without the token, GHCR is reported "partially configured, skipped: missing secrets.PUBLISH_GHCR_TOKEN". The quoted expression was updated in the walkthrough and spine AD-9, the ADR-0052 bullet now says "when the run is on github.com", and a spine changelog line was added. actionlint and zizmor pass. |
| AR-2 | adversarial | LOW | `docs/upgrading.md:377-379` | **"A mirrored run there publishes nothing" is no longer true.** With MD-26, `PUBLISH_RELEASE` is `PUBLISH_RELEASE_TOKEN != '' \|\| github.token != ''`. A tag run on the forge that holds no publish secrets still creates that forge's own release with its job token. | **Fixed in place** (doc wording). |
| AR-3 | adversarial | LOW | `justfile:60-61` | **The recipe comment understated what a raw `act` run carries.** It said only "a raw `act -s ...` run" is not covered. Under MD-26, a raw `act` with no `-s` fills `GITHUB_TOKEN` from `gh auth token`, and the forge release falls back to that token. | **Fixed in place** (comment). The behaviour itself is RT-2, deferred. |

### Clean-release checks with no finding

- **TODO markers:** none in added lines (`TODO`, `FIXME`, `XXX`, `HACK`).
- **Debug artifacts:** no `print(`, `breakpoint()` or `pdb` in added lines.
- **Commented-out code:** none. The one regex hit was the prose comment "for popular actions in its embedded data" in `.pre-commit-config.yaml`.
- **Secrets:** no token-shaped strings (`ghp_`, `gho_`, `github_pat_`, `glpat-`, `pypi-Ag`, `dckr_pat_`) in added lines. The full `gitleaks` tree and history hooks ran in `just check`.
- **Dead code:** the module-folder `.env` branch was deleted outright (S02-005), and `_warn_if_group_or_world_writable` is still used for the cwd `.env`. `generate-buildkit: true` was removed from the jobs that never pass a BuildKit config, so no unused output remains.

## Counts

| scope | CRITICAL | HIGH | MEDIUM | LOW | total |
|---|---|---|---|---|---|
| adversarial | 0 | 0 | 1 | 2 | 3 |
| clean-release | 0 | 0 | 0 | 0 | 0 |

All three were fixed in place; none is deferred.
