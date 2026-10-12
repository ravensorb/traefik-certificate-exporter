# E014 sprint 02 — closure adversarial review

- **Date:** 2026-10-11
- **Method:** `bmad-review` with `lenses=adversarial`, run headless and sequentially by the closure reviewer (no subagents). The clean-release checklist was passed as `also_consider`.
- **Input:** `/tmp/e014-s02-closure-review/sprint.diff` (3,892 lines). Surrounding context was read only from the changed files (`.github/workflows/{dev,release,build}.yaml`, `docker/Dockerfile` lines 6-31). No repository file was modified.
- **Verification:** every finding below quotes text that was checked against the diff or the working tree. Line numbers are working-tree lines.

## Checked and clean (no finding)

- **Clean-release:** the added lines contain no `TODO`/`FIXME`/`XXX`/`HACK`, no commented-out code, no `set -x`, `breakpoint()` or `pdb`, and no secrets. The 64-hex strings are package hashes, image digests and frozen hook SHAs. The `if __name__ == "__main__": print(render_legacy_table())` in `tests/test_settings_surface.py` is the documented regeneration command, not a debug leftover.
- **`${{ }}` in `run:`:** every new `run:` block reads values only through `env:` (`WHEEL_SHA256`, `SDIST_SHA256`, `HAS_*`, `BASE_IMAGE`). The `nick-fields/retry` `command:` uses `$BASE_IMAGE` from env and does not interpolate it.
- **Token on argv:** the Gitea files-check now sends `printf 'Authorization: token %s\n' "$TWINE_PASSWORD" | curl ... -H @-`. `printf` is a builtin, so the token does not appear on any argv.
- **Hash verification:** `Verify dist hashes` checks both files with `sha256sum -c` against `needs.build.outputs.*` and accepts only 64-hex values. It also rejects extra entries in `dist/` (`dotglob`, `entries == 2`) and runs before the CA import and every login. The build job records the hashes in the `version` step, before any ref-pinned action runs, and a later step cannot change that step's outputs.
- **`:0` tag / version label:** `release.yaml:451-457` gates `{{major}}` with `enable=${{ !startsWith(needs.build.outputs.image-version, '0.') }}`. `priority=1000` on the raw image-version line in both workflows ranks it above semver (900), raw (200) and sha (100).
- **Release ancestry:** `validate-tag` still runs `git merge-base --is-ancestor HEAD refs/remotes/origin/$DEFAULT_BRANCH` (not changed in this sprint).
- **Copies of the `run:` bodies:** a YAML comparison found the five `Destination configuration` bodies identical, and the five `Verify dist hashes` bodies identical too.

## Findings

| ID | Scope | Severity | File:line | Finding |
| --- | --- | --- | --- | --- |
| AR-1 | adversarial | MEDIUM | `.github/workflows/release.yaml:418-446,490`; `.github/workflows/dev.yaml:370-394,437` | Mutable-tag actions run after the registry logins |
| AR-2 | adversarial | MEDIUM | `.github/workflows/release.yaml:151,345`; `docs/adr/0046-e014-pipeline-amendments.md` item 3 | A partly configured release is green; the zero-warning rule is checklist-only though it is cheap to check |
| AR-3 | adversarial | MEDIUM | `.github/workflows/release.yaml:19-21,457` | `latest` can move backwards; the guard is prose only |
| AR-4 | adversarial | MEDIUM | `docs/adr/0046-e014-pipeline-amendments.md:28`; `docker/Dockerfile:29-30` | The "one package set outside poetry.lock" claim is false: the image build installs Poetry from PyPI without hashes |
| AR-5 | adversarial | MEDIUM | `docs/adr/0047-dev-release-publish-duplication.md:20` | The five-copy step bodies have no check, though one is cheap; `Verify dist hashes` (also 5 copies) is not recorded |
| AR-6 | adversarial | LOW | `.github/workflows/release.yaml:213,253,484` (and dev equivalents) | The hash check binds file contents, not file names; the unverified name flows into outputs, build-args and the API URL |
| AR-7 | adversarial | LOW | `tests/test_workflow_metadata.py:24-33` | Hand-copied action defaults; no end-to-end check of the label or the `enable=` value |
| AR-8 | adversarial | LOW | `.github/zizmor.yml:4-5` | Says the hook "enforces" the `@vN` form, without its coverage limit |
| AR-9 | adversarial | LOW | `.pre-commit-config.yaml:89-94` | `workflows-if-no-secrets-vars` misses whole-context use (`toJSON(secrets)`), and the stated limits don't name this |
| AR-10 | adversarial | LOW | `.github/dependabot.yml:37-43`; `.pre-commit-config.yaml:177-180` | The ruff v0.16.5 hold is prose only; the new Dependabot ecosystem will propose the held bump every week |
| AR-11 | adversarial | LOW | `.pre-commit-config.yaml:248-250` | mypy hook major bump v1.14.1 → v2.4.0 hidden inside the "freeze revs" change |
| CR-1 | clean-release | LOW | `AGENTS.md:2` | The verification marker cites "the uncommitted E014 sprint-02 tree" |

### AR-1 — MEDIUM — Mutable-tag actions run after the registry logins

- **Evidence:** `release.yaml` runs `docker/login-action` (`if: env.PUBLISH_GHCR == 'true'` … `password: ${{ secrets.PUBLISH_DOCKERHUB_TOKEN }}`), then `- uses: LiquidLogicLabs/git-action-docker-metadata@v6` (line 444), and after the push `LiquidLogicLabs/git-action-docker-test@v2` (line 490). `dev.yaml` has the same order (logins 370-384, metadata 392, docker-test 437). The sprint's step-order rationale is "so a tampered artifact meets no credential (AD-18)". That rationale covers a tampered artifact. It does not cover a tampered action: `@v6`/`@v2` are movable tags (ADR-0046 item 7), and `docker/login-action` leaves the registry tokens in `~/.docker/config.json` for every later step.
- **Consequence:** if an upstream tag is moved or the LiquidLogicLabs org is compromised, the action can read GHCR, Gitea and Docker Hub push tokens in a release job.
- **Fix:** move the metadata step above the first `docker/login-action`; it needs no credential. Run `docker logout` for each enabled registry before `git-action-docker-test`, or pin those two actions by SHA in the publish jobs, with a `# zizmor: ignore` citing the AD.

### AR-2 — MEDIUM — A partly configured release is green; the zero-warning rule is checklist-only

- **Evidence:** every copy of `Destination configuration` only does `echo "::warning title=$JOB::$dest partially configured, skipped: …"`. ADR-0046 item 3: "a release is acceptable only with **zero** partial-configuration warnings … Not mechanically enforced: a per-release checklist item". The `release` job (`needs: [build, publish-package, publish-image]`) still creates the forge release when every destination was skipped.
- **Consequence:** deleting one variable (for example `PUBLISH_GHCR_USERNAME`) produces a green, tagged, forge-published release with no image on that registry. `latest` moves on the other registries. The E013 fail-fast guard used to prevent this.
- **Fix:** in `release.yaml` only, make the partial branch `exit 1` after the warning, or set an output that the `release` job checks. Keep the warn-and-skip behaviour in `dev.yaml`. This enforces rule 3 for the one place the docs say must have zero warnings.

### AR-3 — MEDIUM — `latest` can move backwards

- **Evidence:** `release.yaml:457` `type=raw,value=latest` is unconditional. Lines 11-16 say a re-run of a cancelled pending release is safe "only while no newer tag has released, or it re-points `latest` backwards". `validate-tag` only checks ancestry, so a patch tag on an older line would move `latest` back as well.
- **Consequence:** a re-run, or a late patch tag, silently points users of `:latest` at an older image.
- **Fix:** in `validate-tag`, compute `git tag -l 'v*' --sort=-v:refname | head -1` and output `is-latest`. Gate the line with `type=raw,value=latest,enable=${{ needs.validate-tag.outputs.is-latest == 'true' }}`. The `build` job sits between, so pass the output through or recompute it in `publish-image`.

### AR-4 — MEDIUM — The image build installs Poetry from PyPI without hashes

- **Evidence:** ADR-0046:28: "`.github/requirements/poetry.txt` is the one package set outside `poetry.lock`. It installs Poetry and nothing else." Yet `docker/Dockerfile:29-30` runs `python3 -m pip install --break-system-packages --no-cache-dir "poetry==${POETRY_VERSION}"`, which resolves Poetry and about 45 transitive dependencies from PyPI with no hash check. This builder stage produces the published image. `POETRY_VERSION=2.4.2` is also written separately in `build.yaml:170`, `dev.yaml:430`, `release.yaml:483` and `justfile:44`, apart from `poetry.in`. The `workflows-pip-install-from-requirements` hook covers `^\.github/workflows/` only.
- **Consequence:** the claim overstates coverage. The published image depends on an unaudited, unhashed package set. A Dependabot bump of `poetry.in` leaves the image on the old Poetry.
- **Fix:** `COPY .github/requirements/poetry.txt` into the builder and `pip install --require-hashes -r` it, and drop the `POETRY_VERSION` build-arg. If that is out of scope for this sprint, amend ADR-0046 item 1 to name the Dockerfile bootstrap as an uncovered exception, and file a backlog item.

### AR-5 — MEDIUM — The five-copy step bodies have no check

- **Evidence:** ADR-0047:20-22: "The `run:` body is identical in all five … A copy whose `run:` body drifts from the other four is not detected." `Verify dist hashes` is also duplicated five times (`dev.yaml:135,331`, `release.yaml:185,379,566`), but ADR-0047 does not mention it. That step is the AD-17 tamper guard.
- **Consequence:** a fix to one copy of the hash guard can miss the others without anything detecting it.
- **Fix:** add a pytest next to `tests/test_workflow_metadata.py`. It loads every workflow and asserts that all steps named `Destination configuration` share one `run:`, and all steps named `Verify dist hashes` share one. It needs a non-empty-scope assertion (≥5 each). Update ADR-0047 to cite the test and to name both steps.

### AR-6 — LOW — The hash check binds contents, not file names

- **Evidence:** `echo "wheel-path=${wheels[0]}" >> "$GITHUB_OUTPUT"`, and later `WHEEL_PATH=${{ steps.verify.outputs.wheel-path }}` and `name="${wheel%%-*}"` → `files_url=…/pypi/$name/$VERSION/files`. `sha256sum -c` checks the contents of whatever name is in `dist/`. Build exports no expected file names.
- **Consequence:** an artifact with the same bytes under a different (or newline-bearing) name passes the check. The name then reaches `GITHUB_OUTPUT`, the build-args and the Gitea API path. Exploiting this needs write access to the run's artifacts, so the risk is low.
- **Fix:** export `wheel-name`/`sdist-name` (basenames) from build. In the verify step, require `[[ "${wheels[0]}" == "dist/$WHEEL_NAME" ]]` and a `^[A-Za-z0-9._+-]+$` name.

### AR-7 — LOW — Hand-copied defaults; no end-to-end check of the label or the `:0` gate

- **Evidence:** `DEFAULT_PRIORITIES = {…}  # Mirrors DefaultPriorities in the action's src/tag.ts`. The ADR-0046 item 10 hook "checks that `enable=` is present, not its value". No test asserts the expression text.
- **Consequence:** if the action's defaults change, the guard can pass while the label is wrong. An `enable=true` passes both guards and brings back `:0`.
- **Fix:** in `test_workflow_metadata.py`, assert that the `{{major}}` line carries exactly `enable=${{ !startsWith(needs.build.outputs.image-version, '0.') }}`. Pin the mirrored table to the action major in a comment and assert that the `uses:` ref is `@v6`, so a major bump fails the test.

### AR-8 — LOW — zizmor.yml states the enforcement without its limit

- **Evidence:** `.github/zizmor.yml:4-5`: "The major-tag form `@vN` AD-5 asks for is enforced by the `workflows-lll-major-tag` pygrep hook". The hook's own comment and ADR-0046 item 7 both state a coverage limit (block-style, same-line `uses:` only). This comment does not.
- **Fix:** append "(block-style same-line `uses:` only; see the hook's coverage limit)".

### AR-9 — LOW — The `if:` guard misses whole-context use

- **Evidence:** entry `'^\s*(?:-\s+)?["'']?if["'']?\s*:.*\b(secrets|vars)\s*[.\[]'`. `if: contains(toJSON(secrets), 'X')` and `if: ${{ toJSON(vars) != '{}' }}` do not match. The stated limits cover only multi-line `if:` and the one-flag rule.
- **Fix:** widen the regex to `\b(secrets|vars)\b`, or add this form to the comment's coverage-limit sentence.

### AR-10 — LOW — The ruff hold is prose only

- **Evidence:** the ruff entry says "Held at v0.16.5: v0.17.0 autofixes 9 new findings … the bump is its own change", and the new `package-ecosystem: "pre-commit"` entry has no `ignore:`.
- **Consequence:** a weekly Dependabot PR proposes the held bump, and the hold depends on someone remembering it.
- **Fix:** add `ignore: [{dependency-name: "https://github.com/astral-sh/ruff-pre-commit", versions: [">=0.17.0"]}]` (dependency name to be confirmed against Dependabot's pre-commit naming), with a pointer to the backlog item for the bump.

### AR-11 — LOW — mypy hook major bump hidden in the freeze change

- **Evidence:** `-    rev: v1.14.1` / `+    rev: 2834ec6639549dd6796205c8f011dedcd587288b  # frozen: v2.4.0`. Unlike ruff and gitleaks, there is no "held/bumped" note, although ruff's note says a version change "is its own change". The `pyproject.toml` dev group pins `mypy = "^2.3.1"` separately, so two mypy versions exist.
- **Fix:** add a one-line comment that records the bump and its reason (alignment with the dev group's mypy 2.x). Optionally assert in a test that the hook's frozen major matches the locked mypy major.

### CR-1 — LOW — Transient state in a committed marker

- **Evidence:** `AGENTS.md:2`: `<!-- Verified 2026-10-11 against 6e230db (plus the uncommitted E014 sprint-02 tree). … -->`.
- **Consequence:** once the sprint is committed, the marker names a tree state that no SHA identifies.
- **Fix:** after the sprint commit, rewrite the marker to name that commit's SHA.

Critical: 0, High: 0, Medium: 5, Low: 7
