---
epic: E007
date: 2026-09-01
work_type: MIXED
status: done
provenance: reconstructed
---

# Epic Closure Report — E007 (reconstructed)

**Epic 7 — Reproducible Build and Verification.** Five stories, one sprint, delivered.

## Why this report is short, and what that costs

E007 was executed and closed on 2026-09-01. Later the same day the working tree and all
local git history were destroyed by an `act` run (`docker/act-build.sh` records the
mechanism). `origin` held none of it, so the epic's original closure artifacts — the
retrospective, the sprint closure report, the architectural review report, and the
per-story completion evidence — are **gone and are not reconstructable**.

The *delivery* was recovered and is present and passing. This report exists so the state
tree does not silently claim a closure whose evidence no longer exists.

**What is genuinely lost:** the sprint retrospective, the arch-review report itself
(0 BLOCKER / 10 MAJOR / 11 MINOR), the story-level completion evidence and test-run
records, and the original `plan-2026-09-01-v1.yaml` estimates snapshot.

**What survives:** the delivery, ADRs 0006–0008, the recorded actuals below, and the
findings themselves — every MAJOR was re-applied during the restore and is verifiable in
the tree and in the contract tests.

## Estimate versus actual

Actuals are those recorded at the original closure. They are reproduced from the session
record, not re-derived, and not re-measured against the restore — re-running the clock over
a rebuild would double-count.

| Metric | Estimate | Actual | Note |
|---|---|---:|---|
| `man_hours` | 69.70 – 72.79 | **140** | epic-level counterfactual, incl. closure remediation |
| `elapsed_hours` | 23.44 – 24.44 | **3.55** | |
| `hitl_hours` | 3.90 – 4.10 | **0.10** | |
| `tokens_k` | 2,037 – 2,315 | `N/A` | stories were recorded under `runtime: other` |
| `cost` | 8.41 – 9.55 | `N/A` | derived from tokens |

Story-level actuals: 14, 16, 18, 18, 6 man-hours (72 total); 2.39 elapsed.

Two caveats carried forward from the original closure, both still true:

- The `man_hours` re-assessment ordering was violated — activation reads the state files
  that carry the estimates, so the estimate was in context before the counterfactual was
  formed. The figure landed at roughly 2× the estimate rather than near it, which argues
  against anchoring, but the guarantee was not available.
- `tokens_k` is `N/A` because all five stories were recorded under `runtime: other`. A
  total assembled from five `N/A` children would be fabricated, so none was written.

## Verdict

**Done, with open items** — the same verdict the original closure reached. Open items are
tracked as `BL-E007-001` … `004` and `BL-E008-001`, not as unfinished story scope. Two
deserve naming: nothing yet consumes `verified-dist-v1` (Epic 8 builds the consumer), and
pushes to `main` are unverified until `dev.yaml` lands.

## What the epic actually shipped

A `just`/Bake local facade over a fail-closed exact-wheel image build; a guarded two-phase
release transaction with atomic two-ref push, restore-on-failure and resume; versioned
publication-evidence contracts with a packaged validator; a secret-free reusable verifier
producing one provable promotable artifact set; and a derived-scope workflow governance
layer whose guards are each proven by a planted violation.
