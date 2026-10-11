# E014 plan review — stories vs architecture and PRD (2026-10-11)

| Lens | Report | Initial | After patches |
|---|---|---|---|
| Architecture alignment | review-architecture.md | 1 BLOCKER / 8 MAJOR / 16 MINOR | 25/25 resolved; 1 new MAJOR (stale cert after crash) closed by the mtime-vs-StartedAt restart rule (S01-006) |
| PRD traceability | review-prd.md | 0 / 3 / 9 | 12/12 resolved; 2 MINOR wording fixes applied to S02-005 |
| Cross-story consistency | review-consistency.md | 1 / 7 / 11 | 17/19 resolved; C-07 (S02-005 HITL estimate) and C-08 (re-estimates) fixed in state; 2 ordering MINORs fixed (S01-006 after S01-003; S01-008 after S01-006) |

Maintainer decisions applied: restart only on certificate change (hook/notifications only for changed domains; runatstart on); deptry instead of hand-written dependency test; hash-pinned Poetry bootstrap as ADR-recorded exception; one release run per tag; mandatory pre-release integration evidence; generated upgrade notes; spine/ADR amendments routed through notes to S02-003.

Remaining known residuals (documented in stories): S02-001 state `resolves` still lists BL-E013-001 (already resolved as duplicate); 2 s restart slack; new dependency python-dateutil (Python 3.10 cannot parse Docker timestamps natively).
