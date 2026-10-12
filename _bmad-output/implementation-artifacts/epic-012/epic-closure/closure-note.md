# E012 closure note — Residual Security/CI Hardening Backlog

Closed and archived 2026-10-12 by E014-S02-004 (evidence:
`_bmad-output/implementation-artifacts/epic-014/sprint-02/closure/notes-E014-S02-004.md`).
No retrospective was written for E012 (story non-goal).

## Where the code shipped

E012's code shipped inside E013 commit `fb75fc6` ("feat(ci): standard trigger-selected CI/CD
pipeline (E013 S01) + E012 hardening"), which is on `main`. E012 never had a closure commit of
its own.

## Story outcomes

| Story | Title | Outcome |
|---|---|---|
| E012-S01-001 | Harden privileged write/execution surfaces | `done` (delivered; shipped in `fb75fc6`) |
| E012-S01-002 | CI & supply-chain integrity | **Superseded.** `blocked` → `done`, resolution "superseded by ADR-0035 (E013-S01-002 removed ADR-0031/0032 gates, vendored_trees.py, verify-build.yaml)". Its deliverables were removed by ADR-0035/E013. |
| E012-S01-003 | Fix local act-build.sh checkout/mount strategy | `done` (delivered; `docker/act-build.sh` later removed by ADR-0035) |
| E012-S01-004 | CLI/output hygiene: redaction, usage text, flag errors | **Moved.** Moved to E014-S01-008 at the maintainer's request (2026-10-10); `blocked` → `done`, resolution "moved to and delivered by E014-S01-008". |

## Backlog dispositions made at closure

Items scheduled into E012-S01-002 (all resolved before that story went `done`):

- BL-E011-013, BL-E011-021 — `wontfix`: integrity gates retired; loss accepted by ADR-0035
  (`docs/adr/0035-standard-ci-cd-pipeline.md:74`).
- BL-E011-014 — `duplicate` of BL-E013-022 (ADR-0035 pin policy; residue BL-E013-022/-029).
- BL-E011-015 — `fixed`, ref `fb75fc6` (ADR-0037 plus the `gitleaks-no-paths-allowlist` hook).
- BL-E011-020 — `obsolete`: untracked-file gate retired by ADR-0035.

Items scheduled into E012-S01-004: BL-E011-033, -034, -035, -036 — `fixed`, ref E014-S01-008
(all four delivered there, with tests in `tests/libs/test_settings.py` and
`tests/libs/test_cli_args.py`).

E012 backlog items: BL-E012-003 `fixed` (ref `2139ad8`, `tests/test_s6_privilege_drop.py`);
BL-E012-013 and BL-E012-006 `obsolete` (retired gate/verify-build process).

## State housekeeping

- The stale lock (session `l3io-pm-20261008T123118Z-079584`, claimed 2026-10-08T12:41:41Z,
  ttl 30m) was cleared.
- The open `l3io-pm-story` and `bmad-code-review` dispatch brackets on E012-S01-002 were closed.
- Sprint S01 and E012 set `done`, then E012 moved to `state/archived/epic-012/`.
- `pm-status verify --scope epic --epic E012` → `PASS epic E012`.
