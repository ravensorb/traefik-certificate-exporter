# Architecture Gate Review — Epic E012

- **Epic:** E012 (backlog-cleanup epic, 4 stories, single sprint S01)
- **Gate run:** l3io-execute step-04, 2026-10-08
- **Reviewers run:** l3io-arch-review (first pass), bmad-agent-architect (escalated —
  first pass raised MAJOR findings)
- **Spec alignment:** active. Spec index: `_bmad-output/implementation-artifacts/spec/spec-index.md`.
  Resolved pointer checked: `ARCHITECTURE-SPINE.md#workflow-responsibilities` L323–336.

## Consolidated findings

| ID | Severity | Source(s) | Finding | Resolution |
|----|----------|-----------|---------|------------|
| AG-1 | MAJOR confirmed | l3io-arch-review, bmad-agent-architect | Story E012-S01-003's frontmatter still read `classification: standard` while its own Non-goals section documents a grown scope and a deferred reclassification decision. The decision itself (→ `complex`) had already been made and applied to state during `step-estimate` on 2026-10-08; only the story document and its Non-goals note were stale. | **Resolved directly, no ADR** — this was a doc/state sync gap, not an open design decision. Patched `E012-S01-003.md` frontmatter to `classification: complex` and reworded the Non-goals note to record the completed reclassification instead of flagging it as pending. |
| AG-2 | MAJOR confirmed (+ a third MAJOR from bmad-agent-architect refining the same root cause: Story 2's gates would land in a job structure Story 3 deletes in the same sprint) | l3io-arch-review, bmad-agent-architect | Story E012-S01-002 and Story E012-S01-003 both edit `ci.yaml`/`dev.yaml`/`release.yaml`/`verify-build.yaml` in the same sprint with no sequencing or reconciliation: Story 2's gate-placement AC was written against the pre-refactor per-channel job shape, while Story 3 (CI-AR45) collapses those files to a single job calling `verify-build.yaml`. | **ADR-0029 written** (`docs/adr/0029-ci-gate-placement-sequencing.md`): governance gates land in `verify-build.yaml` (alongside existing `gitleaks`/`actionlint`/`file-hygiene`/`source-integrity` jobs), and Story 3 is sequenced before Story 2. Story 2's technical AC patched to target `verify-build.yaml` directly (placeholder `N/A` removed); `depends_on: [E012-S01-003]` recorded on Story 2's state node. |

No BLOCKER findings. 4 MINOR findings from the first-pass reviewer (marketplace-action ADR
suggestion for the SHA-pin gate, Dependabot renewal note, s6 script testability gap, cooldown
duration/config gap) and 2 MINOR findings from the escalation reviewer (missing epic-level
planning artifact directory, ADR-0028 deciders note) — all auto-deferred to the issues file
per §5 (single-source MINORs defer automatically; none repeated across both reviewers).

## Outcome

Both MAJOR findings resolved — AG-1 by direct doc/state sync (no architectural decision was
open), AG-2 by ADR-0029 plus story-doc patches and an explicit `depends_on` state edge. No
re-validation pass with the reviewers is needed for AG-1 (verifiable by inspection: state
`classification: complex` now matches the doc). ADR-0029 covers AG-2's full resolution.

Step 04 complete — reviewers: [l3io-arch-review, bmad-agent-architect], blocking: 0, deferred: 6
