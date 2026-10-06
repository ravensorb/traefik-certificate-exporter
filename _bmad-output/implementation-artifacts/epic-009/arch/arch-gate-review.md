# Epic E009 Pre-execution Architecture Gate

- Date: 2026-10-06
- Work type: CONFIG
- Reviewers: `l3io-arch-review`, `bmad-agent-architect`
- Scope: E009-S01-001, E009-S01-002, current plan, spec index (no resolvable story pointers)
- Initial verdict: BLOCKED pending ADR resolution

## Consolidated findings

| ID | Severity | Sources | Finding | ADR |
|---|---|---|---|---|
| AG-1 | BLOCKER | both | Same-label runner pools have no enforceable Gitea scheduling discriminator preventing protected runners from claiming untrusted jobs. | ADR-0015 |
| AG-2 | BLOCKER | both | Story 9.1 requires action-closure evidence across Story 9.2 scenarios, creating a completion cycle. | ADR-0016 |
| AG-3 | BLOCKER | both | The certification gate validates Markdown shape but does not authenticate evidence or bind it to the pinned tuple, source, workflow, and artifacts. | ADR-0017 |
| AG-4 | MAJOR confirmed | both | TLS issuer trust and endpoint-level network-egress authorization are conflated. | ADR-0018 |
| AG-5 | MAJOR confirmed | both | Per-job credential identities, secret interfaces, exact scopes, principal separation, mutation credentials, and denial boundaries are incomplete. | ADR-0019 |
| AG-6 | MAJOR confirmed | both | Failed-jobs-only recovery lacks deterministic fault injection, partial-state assertions, rerun identity checks, and cleanup postconditions. | ADR-0020 |
| AG-7 | MAJOR confirmed | both | Forge classification and coordinate projection lack one normalized, authoritative input/output contract and failure taxonomy. | ADR-0021 |
| AG-8 | MAJOR confirmed | both | The transitive action tuple lacks maintenance, licensing, GA, pinning and trust gates; the release fallback has no unambiguous owner or re-entry contract. | ADR-0022 |
| AG-9 | MINOR confirmed | both | Certification probes and evidence lack one non-secret correlation identifier. | deferred |
| AG-10 | MINOR confirmed | both | The certification, partial-publication, recovery, cutover and rollback sequence lacks a required diagram. | deferred |

The reviewers' plan-readiness finding was not consolidated: `stories_elaborated: 0` is correct
when planning readiness is already green, and `arch_gate_summary.ran: false` is mandated for an
immutable plan-time snapshot. This execution-time gate changes the outcome, not the historical
plan.

## Resolution status

ADRs 0015-0022 were reserved atomically before drafting. All eight are now written and the
corresponding story ACs patched:

| Finding | ADR | Story file(s) patched |
|---|---|---|
| AG-1 | ADR-0015 | E009-S01-001.md |
| AG-2 | ADR-0016 | E009-S01-001.md, E009-S01-002.md |
| AG-3 | ADR-0017 | E009-S01-002.md |
| AG-4 | ADR-0018 | E009-S01-001.md |
| AG-5 | ADR-0019 | E009-S01-001.md |
| AG-6 | ADR-0020 | E009-S01-002.md |
| AG-7 | ADR-0021 | E009-S01-001.md |
| AG-8 | ADR-0022 | E009-S01-001.md |

**Narrow re-validation (2026-10-06), ADR-0018 through ADR-0022 and their cited story sections
only:**

- `bmad-agent-architect` (independent, architect persona): VERDICT ALL RESOLVED — AG-4 through
  AG-8 each confirmed as a complete, checkable implementation of its ADR decision.
- `l3io-arch-review` (Mode B, same bounded inputs): concurs — each patched AC paragraph names the
  mechanism its ADR decided on, states the negative test distinguishing it from the prior
  conflated/underspecified behavior, and (for AG-8) resolves the cross-story fallback-ownership
  ambiguity explicitly. No residual gap found.

AG-1 through AG-3 (ADR-0015/0016/0017) were re-validated in the prior session pass before the
interruption; their resolution stands unchanged.

**Gate outcome: 0 blocking findings remain. All 8 BLOCKER/MAJOR findings resolved by ADR +
story patch. 2 MINOR findings (AG-9, AG-10) remain deferred to the issues file per §6 of
step-04-arch-gate.**

## Epic rescope (2026-10-06)

After this gate closed, Epic E009 was rescoped: the live-Gitea-runner-certification requirement
that ADR-0016/0017 (and the live-proof portions of ADR-0015/0020/0022) were written to satisfy
was dropped entirely. No production-owner migration is currently planned or blocked on this
project, and cross-forge runtime behavior is the responsibility of the independently-maintained
`LiquidLogicLabs/git-action-*` reusable actions this project consumes, not this repo's to
re-certify. What this gate's ADRs correctly identified as *this repo's own* responsibility — the
forge classifier (ADR-0021), the per-job credential matrix (ADR-0019), and the TLS-trust/network-
egress conceptual separation (ADR-0018) — remains in scope and is statically proven in
`tests/ci/`. The live-runner-dependent portions were resolved `wontfix` as backlog issues
`BL-E009-007` through `BL-E009-021`; see each affected ADR's 2026-10-06 scope note. Both stories
are `done`; the epic is archived.

