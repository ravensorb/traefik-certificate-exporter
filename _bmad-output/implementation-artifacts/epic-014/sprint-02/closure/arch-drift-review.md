# E014 Sprint 02 — Architectural drift review (l3io-arch-review, Mode B)

- **Date:** 2026-10-11
- **Scope:** the sprint diff `/tmp/e014-s02-closure-review/sprint.diff` (workflows, pre-commit, hashed Poetry bootstrap, ADR edits, ADR-0046/0047/0048, `docs/upgrading.md`, `tests/test_workflow_metadata.py`), stories E014-S02-001..006, CI/CD spine AD-1..AD-18 and Consistency Conventions.
- **Standards applied:** `standards-core.md` §1–10, `standards-github-actions.md`. The Python overlay was not loaded: the only Python change is the optional Poetry `publish` group and test files, and neither raises a packaging question that the CI spine (AD-11) does not already answer.
- **Mode:** headless. No repository file other than this report was modified.

## Executive summary

Most of the sprint matches the CI/CD spine as amended by ADR-0046/0047. The flag conjunctions and `ANY_*` intent flags (AD-9, AD-10), the publish-job step order (AD-18), the hash hand-off (AD-2, AD-17), the frozen hook revs and hashed bootstrap (AD-3, AD-5, AD-11), the `:0` gating (AD-8) and the ADR index all check out against the text. Two drifts block sign-off. Both come from the BL-E014-075 fix (version label `0.3`), which landed outside any S02-001..006 story:
- `tests/test_workflow_metadata.py` parses workflow YAML in pytest, which AD-4 forbids explicitly.
- The `,priority=1000` attribute contradicts AD-8's "exactly" tag list, and no ADR records it.

Counts: 1 BLOCKER, 1 MAJOR, 5 MINOR. The most important action is to replace the pytest workflow guard with a `repo: local` pygrep hook, or record an AD-4 exception in an ADR. In the same change, amend AD-8 to carry the priority.

## Findings

| # | Severity | Principle | Location | Finding | Remediation |
|---|----------|-----------|----------|---------|-------------|
| SD-02-1 | BLOCKER | CI spine AD-4 (no custom policy code); Core §4; global rule 1 | `tests/test_workflow_metadata.py:56-57` (whole file); spine AD-4 line 121 | The new test globs `.github/workflows/*.y*ml`, `yaml.safe_load`s each file, and asserts the metadata `tags:` priorities. It also keeps its own copy of the action's `DefaultPriorities` table (`:23-32`). AD-4 says "No repository code parses workflows" and "a test that polices workflows, pins or the supply chain is not [a product test]". No ADR records an exception. The change sits in no S02-001..006 story's Files in scope: the closure notes only *file* BL-E014-075 (`release-0.3.0-evidence.md:227,271`). | **resolved-in-code** (preferred): delete the test and add a `repo: local` pygrep hook (e.g. `workflows-version-label-priority`, `files: ^\.github/.*\.ya?ml$`) that refuses a `type=raw,value=${{ needs.build.outputs.image-version }}` line without `priority=`. State its coverage limit in the hook comment and in AD-8/AD-3, as the other guards do. **Or adr-justified**: an ADR that amends AD-4 to admit this one test, stating why pygrep cannot express it and who keeps `DEFAULT_PRIORITIES` in step with the action's `src/tag.ts`. |
| SD-02-2 | MAJOR | Core §10 (docs contradict code); global rule 3; CI spine AD-8 | `.github/workflows/release.yaml:454`, `.github/workflows/dev.yaml:402`; spine AD-8 lines 167-174 | Both workflows now write `type=raw,value=${{ needs.build.outputs.image-version }},priority=1000`. AD-8 states "The release `tags:` input is exactly:" and gives the raw line without `priority`. ADR-0046 (items 1-13) does not mention BL-E014-075 either. The spine therefore prescribes the tag list that produced the `0.3` label defect, so the next edit made "to match the spine" reintroduces it. | **spec-updated**: amend AD-8's release tag block, and the dev tag set, to carry `,priority=1000`. State why: the metadata action takes `org.opencontainers.image.version` from the highest-priority tag, and `type=semver` (900) outranks `type=raw` (200). Name the enforcing check (SD-02-1). Add an ADR-0046 item (or an amendment) for BL-E014-075 and a spine Changelog line. |
| SD-02-3 | MINOR | Core §10 (organization, discoverability) | `docs/developer.md:116-177` | The sprint inserted `## Keep pinned tools current` by replacing the heading `## Prepare and publish a release` (present at HEAD line 113). The release procedure (`git switch main && git pull`, `just release minor`, the 4-step list) now sits headless under "Keep pinned tools current". | **resolved-in-code**: restore `## Prepare and publish a release` above the ```` ```bash ```` block at line 158. |
| SD-02-4 | MINOR | Global rule 3 (prose overstating behaviour); CI spine AD-9 | spine AD-9 line 185; `.github/workflows/dev.yaml:86` (and the four other copies) | AD-9 says the Destination configuration step "always exits 0". The implementation's `defined()` emits `::error::` and `exit 1` when a list names an undefined flag or `HAS_*` key. ADR-0047 and `docs/ci/pipeline-walkthrough.md` describe that failure as intended. The spine rule is now stale. | **spec-updated**: amend AD-9 to "exits 0 unless a list names an undefined flag or input (edit error → `::error::`, exit 1)". |
| SD-02-5 | MINOR | Core §10; CI spine AD-10 | spine AD-10 line 212; `dev.yaml`/`release.yaml` `publish-image` checkout, download and `Verify dist hashes` | AD-10 says "Every other image step tests `PUBLISH_IMAGE`". The sprint made checkout, `dist` download and hash verify unconditional, on purpose: AD-17 requires the verify step in every job that downloads `dist`, and the comment explains it. AD-10's sentence no longer describes the job. | **spec-updated**: AD-10 to read "every other image step except checkout, `dist` download and the AD-17 hash verify tests `PUBLISH_IMAGE`". |
| SD-02-6 | MINOR | Core §2 (reuse over copy-paste); GHA overlay (repeated logic) | `dev.yaml:135,331`; `release.yaml:185,379,566`; ADR-0047 Context; spine AD-1 line 87 | The ~25-line `Verify dist hashes` `run:` body is identical in 5 copies, 3 of them in `release.yaml`. ADR-0047 and AD-1 count and accept the 5 Destination configuration copies but do not name this step. The `release` job's copy is not a dev/release pair, so ADR-0047's review rule ("lands in the matching job of the other workflow") does not cover it. | **spec-updated**: extend ADR-0047 Context/Decision and AD-1 to name `Verify dist hashes` (5 copies, identical body) under the same review rule. Composite actions stay deferred. |
| SD-02-7 | MINOR | Global rule 4 (derive from the source of truth); Core §7 | `.github/requirements/poetry.in:10`; `POETRY_VERSION=2.4.2` at `build.yaml:170`, `dev.yaml:430`, `release.yaml:483`, `justfile:44` | The Poetry version now lives in 5 hand-synced literals. The new Dependabot `pip` entry on `/.github/requirements` bumps only `poetry.in`/`poetry.txt`, so CI's Poetry and the image's `POETRY_VERSION` can diverge with nothing failing. ADR-0046 Consequences notes "a second update path for one package" but not the four build-arg literals. | **spec-proposal**: either derive the build-arg from `poetry.in` at run time (as `Resolve base image` derives the base ref from the Dockerfile), or add a pygrep/`check` that the build-arg values equal the `poetry.in` pin. Record the choice in ADR-0046's Consequences. |

## Per-principle walkthrough

**Core**
- §1 Separation of concerns: PASS. `build.yaml` still holds no credential. The pre-pull runs in `build` anonymously, and the publish jobs gate on job-env flags only. ADR-0048 records the exporter layering and its enforcement (`import-linter`).
- §2 Reuse over copy-paste: SD-02-6. The dev/release publish duplication and the 5 Destination configuration copies are ADR-justified by ADR-0047 and AD-1.
- §3 Design by contract: PASS. The hash verify asserts the `^[0-9a-f]{64}$` shape and exactly one wheel, one sdist and nothing else, then runs `sha256sum -c`. `Resolve base image` refuses an unpinned or ambiguous `ARG BASE_IMAGE`. Destination configuration fails on list/env drift.
- §4 Testability: SD-02-1. The workflow logic is exercised by act evidence (stories' Verification sections), not by repository tests, as AD-4 intends.
- §5 Brevity/readability: PASS. The workflow bash is dense but commented, and the step comments state intent.
- §6 Comments: PASS. Backlog and finding keys in comments (`BL-E014-075`, `F-09`) are the recorded deviation in `docs/guidelines.md` §11. The removed zizmor "NOT MECHANICALLY ENFORCED" comment was replaced by a true statement naming the hook.
- §7 Dependency selection: SD-02-7. ADR-0046 item 12 evaluates `nick-fields/retry` v4.0.0 against `Wandalen/wretry.action` v3.8.0. The new `publish` group holds `twine` only.
- §8 GA over preview: PASS. Dependabot `pre-commit` was recorded as GA after re-reading the docs (`notes-E014-S02-001.md:99`). No preview dependency was introduced.
- §9 Logging: PASS (CI scope). Warnings and errors use `::warning title=<job>::` / `::error title=<job>::`, and no secret value or length reaches a log. The Gitea auth header moved off argv (AD-11, `workflows-no-auth-header-argv`).
- §10 Documentation: SD-02-2, SD-02-3, SD-02-4, SD-02-5. `docs/upgrading.md` is added and indexed in `docs/README.md`. The ADR index in `docs/architecture.md` §6 has rows for 0039-0048. The legacy table in `upgrading.md` is rendered from `LEGACY_SETTING_NAMES` and drift-tested, which AD-4 allows as a product-surface test.

**GitHub Actions overlay**
- Marketplace over custom shell: PASS. The base-image retry uses `nick-fields/retry`, not a loop (ADR-0046 item 12). The custom `run:` steps (Destination configuration, hash verify) have no marketplace equivalent that runs on GitHub, Gitea and act (AD-5, AD-6).
- Pinning: PASS. `nick-fields/retry` is SHA-pinned with a `# v4.0.0` comment, and `LiquidLogicLabs/*` stays at `@vN`, now enforced by `workflows-lll-major-tag`. Pre-commit repos are frozen to SHAs (`precommit-revs-frozen`). The mypy mirror moved to v2.4.0, the same major as the locked mypy 2.4.0 (AD-3; `poetry.lock:1722-1723`).
- Dependabot: PASS. The `pre-commit` and `pip` (`/.github/requirements`) ecosystems were added with a 7-day cooldown (AD-5).
- Least-privilege `permissions`, secrets handling: PASS. `contents: read` is unchanged, and the token is passed only to the step that uses it.
- Repeated logic as composite/reusable: SD-02-6. The rest is accepted by ADR-0047.

## Gate

- **BLOCKER SD-02-1, MAJOR SD-02-2** must be resolved or ADR-justified before sprint sign-off. Both come from the unstoried BL-E014-075 fix and can be closed in one change.
- **MINOR SD-02-3..SD-02-7** auto-defer to the backlog.

## Recommended ADRs

- An ADR-0046 item or amendment for BL-E014-075: the version-label priority and its enforcing check (SD-02-1, SD-02-2). If the pytest guard is kept, an ADR amending CI AD-4 instead.
- An ADR-0047 amendment naming `Verify dist hashes` among the accepted copies (SD-02-6).

## Not opened

- The spec index was not opened. Every hunk maps to a story AC, an ADR or a CI spine AD read above, so no hunk was left without coverage. ADR files were read through their diff hunks; ADR-0046/0047/0048 are new files and were read in full there.

Sections read:
- `/tmp/e014-s02-closure-review/sprint.diff` lines 1-2799 and 3270-3892 (the `poetry.txt` hash body, lines 2800-3269, was only grepped for `poetry==`, `via -r` and `virtualenv`)
- `.claude/skills/l3io-arch-review/references/review-report.md` (all), `standards-core.md` (all), `standards-github-actions.md` (all)
- `_bmad-output/implementation-artifacts/epic-014/sprint-02/stories/E014-S02-001.md` headings, lines 61-89 and 221-239; `E014-S02-002.md` headings, lines 77-111 and 249-260; `E014-S02-003.md` .. `E014-S02-006.md` headings only
- `_bmad-output/planning-artifacts/architecture/architecture-ci-cd-pipeline-2026-10-08/ARCHITECTURE-SPINE.md` lines 78-320 (AD-1..AD-18, Consistency Conventions), Stack lines 321-361 (grep for poetry/retry/mypy), grep for `priority` / `test_workflow_metadata` (no match)
- `_bmad-output/planning-artifacts/architecture/architecture-traefik-certificate-exporter-2026-08-30/ARCHITECTURE-SPINE.md` grep: lines 85, 97, 497
- `docs/developer.md` heading grep and lines 150-180; `git show HEAD:docs/developer.md` grep (line 113)
- `_bmad-output/implementation-artifacts/epic-014/sprint-02/closure/notes-E014-S02-001.md` grep: lines 10-26, 92, 99, 134-135, 242
- `_bmad-output/implementation-artifacts/epic-014/sprint-02/{stories,closure}/` grep for `BL-E014-075` / `test_workflow_metadata`
- `docs/adr/`, `_bmad-output/planning-artifacts/` grep for `test_workflow_metadata` / `priority=1000` (no match)
- `.github/workflows/*.yaml`, `justfile`, `.github/requirements/poetry.in` grep for `POETRY_VERSION=` / `poetry==2`, step names and `priority=1000`; `tests/test_workflow_metadata.py` grep lines 56-57; `docker/Dockerfile` grep `POETRY_VERSION`; `poetry.lock` lines 1722-1723

Blocker: 1, Major: 1, Minor: 5
