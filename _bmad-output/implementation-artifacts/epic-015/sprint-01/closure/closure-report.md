# E015 sprint 01 — closure report

Date: 2026-10-12 (local; state timestamps are UTC 2026-10-13). Work type MIXED, no skipped phases.

## Stories

| Story | Status | Elapsed h | Man h | Tokens k (corrected) |
|---|---|---|---|---|
| E015-S01-001 root-mode settings trust | done | 1.30 | 24 | 29,222.1 |
| E015-S01-002 validatekeys + .pfx fingerprint | done | 0.45 | 24 | 12,589.8 |
| E015-S01-003 watch rename detection | done | 0.21 | 8 | 3,940.5 |
| E015-S01-004 pre-confuse env-name warnings | done | 0.35 | 10 | 6,913.4 |

Carry-over: 0. Blocked stories: none.

Sprint estimate vs actual: man-hours 74.8–105.8 estimated, 58 re-assessed at closure (formed from
the delivered diff before the estimate was read); elapsed 6.0–7.6 h estimated, about 3.0 h actual;
tokens 36.1–41.0 M estimated, about 52.7 M for stories plus closure spend (see sprint node).

## Orchestrator items

1. **ruff==0.16.5 in the dev group / root-mode `.env` narrowing.** The dev-group ruff is coherent
   with the spine (Changelog 2026-10-12 "hook tools in the Poetry dev group") and NFR-9; it is
   pinned to the hook version and a test fails if the two differ. ADR-0050 Decision 4 still said
   "ruff is a pre-commit hook, not a dev dependency": superseded in the ADR-0050 closure
   amendment. The `.env` narrowing (ADR-0049 amendment, spine AD-2 changelog) deviates from
   S01-001 AC 3 and is not stated in PRD FR-18 or spine AD-6. It does not touch LinuxServer
   conventions (`/config` stays PUID-owned and editable). **Flagged for the maintainer:**
   BL-E015-052 (ratify, then update FR-18), BL-E015-049 (AD-6). Arch-drift SD-01-1 disposed
   `adr-justified` on ADR-0049 pending that ratification.
2. **Pre-filled dates.** Every "merged/Amended/amendment 2026-10-13" in ADR-0030, ADR-0049,
   ADR-0050, the spine, `.memlog.md`, `docs/operational.md`, `docs/upgrading.md`,
   `pyproject.toml`, `settings.py` and `tests/libs/test_post_export.py` corrected to 2026-10-12,
   the local date of the merge commit. UTC state timestamps and quotations in the per-story
   notes and reviews are left as recorded. BL-E015-009 resolved.
3. **`ruff format` over `certificate_exporter.py`.** No record shows S01-003's pass changing
   S01-002 lines. S01-002 passed `ruff format` clean at its own gate (notes-E015-S01-002.md),
   and the formatter is pinned to one version (0.16.5) in hook and dev group. Formatting is
   idempotent within a version, so a later pass cannot reshape lines that were already
   formatted. Only S01-003's own new lines could change. The closure `just check` passes
   `ruff format` and the full suite (595 passed). No semantic change found.
4. **Token actuals.** The figure for S01-004 was not under-recorded: it was over-recorded, at
   7,750.6k recorded against 6,913.4k measured. The other three stories were over-recorded the
   same way (8–16%). The measurement scoped `pm-status usage` to each story's dispatch
   bracket. For S01-001 it was cross-checked by summing that story's six agent transcripts,
   which gave the identical 29,222.1k. The likely cause is transcript records that were not
   de-duplicated. All four story actuals were corrected with `set-actual` (elapsed, man and HITL
   values unchanged). Their calibration samples were taken at the inflated values and could not
   be replayed (`skipped (replay)`). They overstate story token use for this sprint.
5. **mypy.** The two `Subview` vs `Configuration` errors in `settings.py` were not pre-existing.
   They came from S01-001's new `view = self._config; view = view[segment]` walks. The
   pre-commit hook misses them because its isolated environment has no `confuse`, and
   `ignore_missing_imports` then types it `Any`. Fixed by annotating
   `view: confuse.ConfigView`, and `poetry run mypy src` is now clean. The gate gap is real and
   is filed as BL-E015-053.

## Phases

| Phase | Ran | Output | Result |
|---|---|---|---|
| Retrospective | yes (inline; bmad-retrospective is epic-scoped) | retrospective.md | 7 action items |
| Clean-release + adversarial (one bmad-review invocation) | yes | adversarial-review.md | 1 HIGH, 3 MEDIUM, 9 LOW |
| Red team (l3io-sec-redteam) | yes | redteam-report.md | 2 HIGH, 2 MEDIUM, 4 LOW |
| UX review (bmad-ux Reviewer Gate) | yes | ux-review.md | 0 HIGH, 4 MEDIUM, 6 LOW |
| Arch drift (l3io-arch-review Mode B) | yes | arch-drift-review.md | Blocker 0, Major 1, Minor 6 |
| Fix loop | 1 iteration | closure-fixes.md | all blocking findings fixed |

The red-team report's demo output had a fake bearer token that tripped gitleaks. It was
redacted to `<hook-secret>`.

Gate on the final tree: `just check` exit 0 — every pre-commit hook passed, pytest
`595 passed, 10 skipped` (the skips are the opt-in Docker integration tests).

## Issues resolved (11)

| Severity | Items |
|---|---|
| High | AR-1 = RT-2 (root `.env` interpolation exfiltration; `interpolate=False` in root mode), RT-1 (chmod follows a swapped symlink; `O_NOFOLLOW` + `fchmod`) |
| Medium | AR-2 (re-export bypass now banned), AR-3 (stdlib spawning functions banned or listed; BL-E015-013), AR-4 (sidecar records build recipe), RT-3 (ADR-0049 `/certs` claim corrected, residual risk recorded), mypy errors in `settings.py` |
| Low | CR-1 (timing prints), SD-01-5 / ADR-0050 Decision 4 dev-dependency text, BL-E015-009 (dates), story token over-recording |

## Issues deferred (30 new, BL-E015-024 … 053)

| Severity | Count | Items |
|---|---|---|
| Medium | 8 | RT-4 (appriseurls trust class: maintainer decision), RT-1 remainder (dir-fd writes), UX-1…UX-4, ADR-0049 amendment ratification + PRD FR-18, mypy hook gate gap |
| Low | 22 | AR-5…AR-12, RT-6…RT-8, UX-5…UX-10, SD-01-2, -3, -4, -6, -7 |

RT-5 duplicates the existing BL-E015-014 and was not re-filed.

## Not staged

`config.sample.yml` is a story deliverable (S01-002 `validatekeys`). It was staged even though
the orchestrator's path list did not name it, because the commit would otherwise leave the
documented key out of the shipped sample. `_bmad/scripts/pm-status.py` (maintainer's 3.4.5 bump)
and `_bmad/memory/` are not staged.

## Calibration

The sprint actual set the elapsed, tokens and cost samples. Two were skipped:
- `man_hours`: a negative residual, because the sprint counterfactual (58) is below the sum of
  the story counterfactuals (66). The story-level figures double-count shared context, which is
  the case the contract expects when the sprint is re-assessed as a whole.
- `hitl_hours`: a zero residual, because the run was headless and human attention really was 0.

The orchestration block recorded 3 metrics. Its `hitl_hours` was skipped because the children
total 0.
