# E013 Sprint 01: adversarial and clean-release review

- **Date:** 2026-10-09
- **Method:** `bmad-review` adversarial lens, run directly by the reviewer (headless), with the clean-release checklist as `also_consider`.
- **Target:** uncommitted E013-S01 changes against HEAD, limited to the in-scope paths in the review brief. E012 work (`docker/root/**`, `libs/{docker,certificate_exporter}.py`, `tests/test_s6_privilege_drop.py`, `docs/operational.md`, ADR-0028..0033) was not reviewed.
- **Spec context:** ADR-0035, ADR-0036, ADR-0037, `docs/ci/pipeline-walkthrough.md`.
- **Gate after fixes:** `poetry run pre-commit run --all-files` passed every hook: poetry-lock, check-toml, check-yaml, mixed-line-ending, ruff check, ruff format, gitleaks, gitleaks-history, actionlint, zizmor, mypy.

## Clean-release sweep (no findings)

- **Stale references to deleted files:** the in-scope files were grepped for `publish-image.yaml`, `verify-build.yaml`, `.github/actions`, `publication_contract`, `tests/ci`, `release_version`, `committed_versions`, `vendored-trees`, `act-build.sh`, `tests/support.py`, `docker-bake`, `scriv` and `workflow-policy`.
  - Hits appear only in three places, all intended:
    - documents carrying the "Historical — describes the pipeline retired by ADR-0035" banner (`docs/ci/gitea-certification.md`, `docs/ci/codex-assesment.md`, `docs/ci/ref-free-checkout-walkthrough.md`);
    - the context and consequences text of ADR-0035 and ADR-0036;
    - the `justfile-fmt was removed` note in `.pre-commit-config.yaml`.
  - Nothing under `tests/`, `src/` or `docker/root/` imports a deleted module.
- **TODO/FIXME/debug markers:** none in the in-scope files.
- **Secrets:** none. Both gitleaks hooks (tree and history) pass.
- **Commented-out code:** the only instance is `# - id: end-of-file-fixer` (`.pre-commit-config.yaml:35`). It was already in HEAD, so it is not reported against this change.

## Findings

### AR-01 | adversarial | HIGH | Open: a `v*` tag on any commit releases, bypassing review of `main`
- **Where:** `.github/workflows/release.yaml:5-7` (trigger `push: tags: ['v*']`) and `:22-41` (`validate-tag` checks only the tag's name).
- **Problem:** Nothing checks that the tagged commit is reachable from `main`.
  - Anyone with tag-push rights can tag an unreviewed commit on a side branch, for example `v9.9.9`.
  - That commit is then published to PyPI, every registry (including `latest`) and the forge release.
  - This bypasses the PR review and CODEOWNERS approval that `.github/CODEOWNERS:10-13` depends on.
- **Docs disagree with the workflow:**
  - `README.md:140` says "A release is a `vX.Y.Z` tag on `main`".
  - `just release` (`justfile:67-79`) enforces this only on the maintainer's machine.
- **Suggested fix:** in `validate-tag`, check out with `fetch-depth: 0` and run `git merge-base --is-ancestor "$GITHUB_SHA" refs/remotes/origin/main`. Also, or instead, enable forge tag protection for `v*`.
- **Why not fixed:** this changes AD-12, and whether checkout fetches remote branches has to be verified live on Gitea and `act` (AD-6, ADR-0035 Consequences). That is not a small, clearly correct edit.

### AR-02 | adversarial | MEDIUM | Fixed: the dist artifact was uploaded after a ref-pinned action ran in the same job
- **Where:** `.github/workflows/build.yaml`. The upload step was at the end of the job; it is now at `:100`. The action is `LiquidLogicLabs/git-action-docker-test@v2`, now at `:129`.
- **Problem:** `upload-artifact` ran after `git-action-docker-test@v2`.
  - That action is pinned to a mutable tag (ADR-0035 accepts a moved tag in that org).
  - It shared the workspace, so a moved tag could rewrite `dist/` before upload.
  - `dev.yaml` and `release.yaml` publish that `dist` to PyPI and the registries.
  - Their `WHEEL_SHA256` is recomputed from the downloaded artifact (`dev.yaml:172`, `release.yaml:190`), so the substitution would not be detected.
- **Why the ADR's acceptance doesn't cover it:** ADR-0035 accepts the moved-tag risk for credentialed jobs. Here the credential-free build job could still taint what gets published.
- **Fix:**
  - The upload now runs directly after `Read version` and before any LiquidLogicLabs action. A comment states why.
  - The `docs/ci/pipeline-walkthrough.md` diagram (lines 20-21) shows the new order.
  - A failing smoke test still fails the job, so no publish job runs.

### AR-03 | adversarial | MEDIUM | Fixed: the pin policy was documented as "major tags", but zizmor accepts any ref, including branches
- **Where:** `.github/zizmor.yml:7` (`"LiquidLogicLabs/*": ref-pin`) and `docs/ci/pipeline-walkthrough.md:211`.
- **Problem:** the walkthrough said `LiquidLogicLabs/*` "may use `@vN`". The gate does not enforce that.
  - **Evidence:** zizmor 1.30.1 was run with `--config .github/zizmor.yml` on a workflow containing `LiquidLogicLabs/git-action-docker-test@main` and `LiquidLogicLabs/git-action-release@some-branch`. Result: "No findings to report."
  - A branch-pinned action in a credentialed job would pass the gate (global rule 4: the guard's reach was overstated).
- **Fix:**
  - The `zizmor.yml` header now says `ref-pin` accepts any ref, and that the major-tag form is NOT MECHANICALLY ENFORCED and is held by CODEOWNERS review.
  - The walkthrough's zizmor row says the same.
  - zizmor has no tag-only policy, so no mechanical check is possible with the current tool.

### AR-04 | adversarial | MEDIUM | Fixed: ADR-0037 relied on `poetry.lock` being CODEOWNERS-owned, but it was not
- **Where:** ADR-0037 Consequences ("these files are generated or reviewed configuration, and both are CODEOWNERS-owned") and `.github/CODEOWNERS:24-30`.
- **Problem:** `poetry.lock` is skipped by gitleaks' inherited path allowlist, in both tree and history modes. ADR-0037 accepts that risk on the grounds that review covers the file. But CODEOWNERS listed only `.gitleaks.toml`, not `poetry.lock`.
- **Fix:** added `/poetry.lock @ravensorb` to CODEOWNERS, with a comment giving the reason.

### AR-05 | adversarial | MEDIUM | Open: pre-commit hook repos are pinned to mutable tags and run inside the build that produces the published dist
- **Where:** `.pre-commit-config.yaml:31,39,54,74,81,87` (`rev: v6.0.0`, `v0.16.5`, `v8.30.1`, `v1.7.12`, `v1.30.1`, `v1.14.1`).
- **Problem:**
  - `build.yaml:49-50` runs every hook before `poetry build`, and `ruff-check --fix` and `ruff-format` write to the tree.
  - A moved tag in any of six third-party repos runs arbitrary code in the job whose output is published.
  - AD-5's SHA-pin rule covers only workflow `uses:` entries, not hook repos. Dependabot has no `pre-commit` entry in `.github/dependabot.yml`.
- **Suggested fix:** freeze revs to commit SHAs (`pre-commit autoupdate --freeze`, which writes `rev: <sha>  # frozen: vX`), and choose an update path for them.
- **Why not fixed:** this needs a maintainer decision on how frozen hooks stay current, and it extends AD-5's scope.

### AR-06 | adversarial | MEDIUM | Open: Poetry is installed without hashes, and credentialed jobs install the whole dev group
- **Where:**
  - `dev.yaml:72-75` and `release.yaml:92-95`: `pip install "poetry==2.4.2"`, then `poetry install --only dev --no-root`;
  - `build.yaml:43-46`;
  - `docker/Dockerfile:29-30`.
- **Problem:** `pip install poetry==2.4.2` has no `--require-hashes`, and Poetry's transitive dependencies are resolved fresh from PyPI on every run.
  - In `publish-package`, that install, plus the whole dev group (pre-commit, pytest, mypy, poetry, semver, pyyaml) and the `requires-plugins` plugin env, lands in the job that later puts `PUBLISH_PYPI_TOKEN` / `PUBLISH_GITEA_TOKEN` into twine's environment.
  - Code installed there can persist, for example through a `.pth` file, and run when twine runs.
- **Suggested fix:** install only twine, from a hash-locked requirements export (`pip install --require-hashes -r ...`). Install Poetry itself from a hashed constraints file.
- **Why not fixed:** this changes AD-11's "locked twine from the dev group" mechanism.

### AR-07 | adversarial | MEDIUM | Deferred: re-creating a tag silently splits one version across destinations
- **Where:** `release.yaml:104,113` (`--skip-existing`), `:228-231` (image tags, including `latest`) and `:328` (`allow-updates: true`).
- **Problem:** suppose a released tag is deleted and pushed again on a different commit.
  - The run rebuilds and moves `X.Y.Z`, `X.Y`, `X` and `latest` to new image content.
  - It replaces the forge release assets.
  - PyPI and Gitea silently keep the original wheel.
  - The run is green, but the package and the image of one version now differ.
- **Why deferred:** ADR-0036 §5 deliberately accepts re-run semantics (a re-run moves tags to a new digest). It does not consider the re-tag case. The mitigation is forge tag protection, which AR-01 also recommends, and the decision belongs to the maintainer.

### AR-08 | adversarial | LOW | Deferred: registry credentials are on disk when ref-pinned actions run
- **Where:** `dev.yaml:179-197` (logins), then `:200` (`git-action-docker-metadata@v6`) and `:245` (`git-action-docker-test@v2`). Same pattern in `release.yaml:197-218,264`. `PUBLISH_RELEASE_TOKEN` is passed to two ref-pinned actions (`release.yaml:314-328`).
- **Problem:** `docker/login-action` writes `~/.docker/config.json` before mutable-tag actions run in the same job.
- **Why deferred:** ADR-0035 Consequences accepts this explicitly. A partial mitigation would be to move the metadata step above the logins, since it needs none.

### AR-09 | adversarial | LOW | Open: images are pushed, including `latest`, before the pushed digest is smoke-tested
- **Where:** `release.yaml:242-269` and `dev.yaml:223-250`.
- **Problem:** the multi-arch push writes every tag, then `git-action-docker-test` tests the digest. The build job's smoke test covers one architecture only (`build.yaml`, `push: false`, single-arch). A failing arm64 image, or a failing pushed digest, is already published under `latest` / `X.Y.Z` when the test fails.
- **Suggested fix:** push by digest only (`outputs: type=image,push-by-digest=true`), test, then tag. Or accept this and record it as accepted.

### AR-10 | adversarial | LOW | Open: no job sets `timeout-minutes`
- **Where:** all four workflows (`grep -c timeout-minutes` = 0 in each).
- **Problem:**
  - A hung step runs for the 360-minute default.
  - In `release.yaml:13-15` (`group: release`, `cancel-in-progress: false`), a hung release blocks every later release for that time.
  - A hung `publish-*` job keeps its secrets in scope for the whole period.
- **Suggested fix:** set a per-job `timeout-minutes` (for example 30 for build, 20 for publish).

### AR-11 | clean-release | LOW | Open: the walkthrough says a re-run reuses the same digest, which ADR-0036 retracted
- **Where:** `docs/ci/pipeline-walkthrough.md:180`: "image tags are rewritten to the same digest".
- **Problem:** ADR-0036 §5 (AG-10) amended this: a re-run re-points tags to a new digest. The walkthrough still states the retracted claim.
- **Suggested fix:** "image tags are re-pointed to the digest this run built (ADR-0036 §5)".

### AR-12 | clean-release | LOW | Open: the walkthrough says "no path exempted", contradicting ADR-0037
- **Where:** `docs/ci/pipeline-walkthrough.md:212` ("gitleaks | committed secrets, with no path exempted").
- **Problem:** ADR-0037 records an inherited path allowlist (`.git`, `poetry.lock`, `.gitleaks.toml`, site-packages, and others). The correct statement is "the repository adds no path exemption".
- **Suggested fix:** reword to match ADR-0037 Decision 2.

### AR-13 | clean-release | LOW | Open: ADR-0035's status line is stale
- **Where:** `docs/adr/0035-standard-ci-cd-pipeline.md:3`: "Accepted — implementation pending".
- **Problem:** this change is the implementation. It deletes the files listed in Consequences and updates the superseded ADRs' status lines.
- **Suggested fix:** "Accepted", or "Accepted — implemented in E013-S01".

### AR-14 | clean-release | LOW | Open: ADR-0037 overstates its own check
- **Where:** ADR-0037 Consequences: "the recorded-set diff makes any change visible".
- **Problem:** no standing check diffs the recorded set. `.gitleaks.toml`'s own header says "NOT MECHANICALLY ENFORCED … No standing CI check diffs it". The ADR implies a mechanism that ran once at story verification (global rule 3).
- **Suggested fix:** say the diff is run by hand on a gitleaks upgrade, and is not run in CI.

### AR-15 | clean-release | LOW | Open: stray `uv.lock` is staged
- **Where:** `uv.lock` (index status `A`, 3 lines: `version = 1`, `revision = 3`, `requires-python = ">=3.11"`).
- **Problem:** this is an empty uv lock in a Poetry project. AGENTS.md and ADR-0001 record Poetry, not uv. It looks like a tool artifact.
- **Note:** this file is outside the listed in-scope paths, so it is flagged only and was not modified. It should be unstaged and deleted unless a story intends it.

## Summary

- **Fixed:** AR-02, AR-03, AR-04 (in-scope edits to `.github/workflows/build.yaml`, `.github/zizmor.yml`, `.github/CODEOWNERS` and `docs/ci/pipeline-walkthrough.md`).
- **Deferred:** AR-07, AR-08. Both are ADR-accepted design decisions.
- **Open:** AR-01 (HIGH), AR-05, AR-06, AR-09 to AR-15.
- Nothing was staged or committed.

## Sprint-closure disposition (2026-10-09)

- **Fixed in closure:** AR-11, AR-12 (`docs/ci/pipeline-walkthrough.md`), AR-13 (ADR-0035 status), AR-14 (ADR-0037 Consequences).
- **Deferred to the backlog:** AR-01 and AR-07 → BL-E013-019 (with RT-E013-02); AR-05 → BL-E013-020 (with RT-E013-03); AR-06 → BL-E013-024; AR-08 → BL-E013-030; AR-09 → BL-E013-031; AR-10 → BL-E013-032; AR-15 → BL-E013-033.
- AR-01 (HIGH) is not fixed: it changes AD-12 and needs a maintainer decision plus live verification on Gitea and act.
