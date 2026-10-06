# Epic E011 Closure Report — Residual Technical-Debt Backlog Triage

## Epic goal and final status

E011 was a backlog-cleanup epic: promote 10 code/config items accumulated as deferred
findings in earlier epics (E007, E008) into a single sprint, close `BL-E002-002` as deferred,
and leave the residual backlog in a demonstrably better state than it started.

**Final status: DONE.** 1 sprint, 4 stories, all `status: done`. 0 blocked stories. 0
unresolved Critical/High/Medium findings carried past closure (see §Security review
resolution below) — every HIGH/MEDIUM red-team finding and every MAJOR drift finding found
during closure was either fixed in code or recorded as an accepted ADR amendment before this
report was written.

## Estimate vs actual

| Metric | Estimate (low–high) | Actual | Note |
|---|---|---|---|
| man_hours | 35.37–39.14 | **42** | Counterfactual re-assessed from delivered work (§1 of step-06), *before* reading the estimate, per the ordering rule. Above the high end — closure's own security-hardening fix passes (path-traversal, key-permission, log-forging, Docker-socket-claim correction) went beyond the 4 stories' original scope. |
| hitl_hours | 0.9–1.05 | 0.35 | Below range — closure ran with minimal direct human review beyond the initiating command. |
| elapsed_hours | 8.15–10.29 | 3.55 | Below range (sprint 3.1h + closure 0.45h). |
| tokens_k | 796–905 | N/A | `runtime=other` was bound this session — tokens are not observable from a transcript, recorded as N/A consistently at every node (stories, sprint, epic, orchestration). |
| cost | $3.29–$3.73 | N/A | Follows from the tokens_k N/A above. |

Orchestration overhead (dispatching/deciding/waiting, no human-developer counterfactual):
elapsed_hours 0.35, man_hours 0, hitl_hours 0.05, tokens N/A.

## Sprint velocity

| Sprint | Stories | Fix iterations | Deferred findings | Status |
|---|---|---|---|---|
| S01 | 4/4 done | 2 total (1 each on S01-002, S01-004) | 30 (1 High, 11 Medium, 18 Low) | done |

## Retrospective learnings (epic-level, synthesized from the sprint's own retrospective —
single-sprint epic)

1. Hardening the *write* side of a trust boundary (atomic writes, path containment) is
   incomplete without also hardening what reaches it unvalidated — closure's own red-team
   pass found three more instances of the same class (misleading socket-privilege docs,
   unenforced `/config` writability, unsanitized log interpolation) that the sprint's stories
   did not scope.
2. A shutdown mechanism built during a *fix pass* (not the original story diff) is the one
   most likely to go undocumented — SIGTERM routing and the TOCTOU-safe `cancel()` rewrite
   both originated in sprint-01's postfix diff and were invisible to the ADRs until this
   epic's own architectural-drift review surfaced them.
3. "Fix in place, record if justified" (§3's security vocabulary) is looser than arch-drift's
   disposition-tracked process (§2) by design — but the fixes still benefit from the same
   independent-verification discipline before being accepted, which this closure applied to
   every finding from every reviewer, not just the ones with a formal CLI disposition step.

## Outstanding issues (by severity, after epic-closure triage)

| Severity | Count |
|---|---|
| High | 1 |
| Medium | 13 |
| Low | 27 |
| **Total** | **41** |

Triage promoted 2 items from Low → Medium given full-epic context (§4):
- `BL-E011-019` (post-export hook inherits full environment, including credentials) —
  promoted because full-epic context now also includes `BL-E011-012` (High: hook is
  RCE-equivalent, runs as root) and `BL-E011-016` (Medium: container restarts driven by
  attacker-influenced strings over the Docker socket); the combination compounds rather than
  stands alone.
- `BL-E011-009` (atomic write replaces a symlinked path with a regular file instead of
  writing through it) — promoted because this epic's own TOCTOU-hardening theme
  (ADR-0023 Amendment 4b) makes a symlink-swap gap in the same code path a known-class
  security gap, not an isolated correctness nit.

All other Low items were reviewed and left at Low — none met the bar of materially combining
with another finding under full-epic context.

Blocked stories: none (§4a — `blocked_stories` did not appear in `pm-status.py show`).

## Security review resolution (§3)

`l3io-sec-redteam`, dispatched epic-level (not sprint-scoped), found 0 Critical, 1 High, 2
Medium, 0 Low, 2 Observation. All three actionable findings were fixed in code during closure,
each independently re-verified against source before being accepted as resolved:

| ID | Severity | Finding | Resolution |
|---|---|---|---|
| EC-001 | High | `docker-compose` samples and `docs/operational.md` claimed a `ro` Docker-socket mount narrows privilege to "list/restart," when it grants host-root-equivalent access regardless of mount mode | Corrected both docker-compose sample comments (`docker/README.md`) and the runbook (`docs/operational.md` step 3) to state the real risk and recommend a socket-proxy pattern |
| EC-002 | Medium | The documented `/config` trust-boundary invariant (must not be world-writable) had zero runtime enforcement | Added `_warn_if_group_or_world_writable()` to `settings.py`, wired into all 3 trust-boundary read points in `loadFromFile`; covered by two new tests (fires on a planted world-writable file, silent on a safe one) |
| EC-003 | Medium | Rejected ACME `domain.main`/`resolverName` values were logged verbatim, unsanitized — CR/LF/ESC-CSI log-forging injection, demonstrated live by the red-team agent | Added `_sanitize_for_log()` to `certificate_exporter.py`, applied at both refusal log sites; covered by two new tests (a planted control-character domain no longer reaches the log sink; the helper's own stripping behavior) |

Observations (no action required): noted in `redteam-report.md`, not reproduced here.

No new ADR was written for EC-002/EC-003 — both are implementation hardening of an
*already-recorded* invariant (the `/config` trust boundary and the logging contract,
respectively), not new architectural decisions, matching §3's "fix in place" instruction for
Medium findings (as distinct from §2's disposition-tracked process for architectural drift).

## Architectural drift review resolution (§2)

`l3io-arch-review` Mode B, epic-level, scoped to all 5 ADRs + 4 story files + the cumulative
diff (`2213e42..434dc87`), found 2 Major, 0 Blocker, 0 Minor:

| ID | Severity | Finding | Resolution |
|---|---|---|---|
| AD-1 | Major | SIGTERM routing + the TOCTOU-safe `cancel()` rewrite (`drainsRun`, `SHUTDOWN_JOIN_TIMEOUT_SECONDS`), both built during sprint-01's own fix pass, were undocumented in ADR-0023/0026 | Amendment 4b added to `docs/adr/0023-export-pipeline-correlation-id-and-atomic-writes.md` |
| AD-2 | Major | `./logging.yaml` CWD auto-discovery removal (an RCE-closing decision) was undocumented in ADR-0003 | New "Amended at 2026-10-06" section added to `docs/adr/0003-logging-stack-and-secret-redaction.md` |

Both dispositioned `resolved-in-code` via `spec-align disposition`; `check-dispositions`
passed.

## ADRs produced or amended this epic

- **New**: ADR-0024 (atomic-write helper covers PKCS12 exports), ADR-0025 (strict CLI parse
  without import-time regression), ADR-0026 (None-safe timer cancellation on shutdown),
  ADR-0027 (vendored-tree framing lives in CODEOWNERS) — all written during the arch-gate
  (step-04) resolution of 4 ADR-gap findings.
- **Amended**: ADR-0023 (Amendment 4b, this closure, AD-1), ADR-0003 (new amendment section,
  this closure, AD-2).

## Spec changes (§2a, `spec_alignment: true`)

| Finding | Disposition | Commit / proposal | Backlog key |
|---|---|---|---|
| SD-01-5 (sprint-01 closure) | spec-updated | `df8411965e8cc8ee4d2eb1138a50f7e379bdbe57` | `BL-E011-041` |
| AD-1 (epic closure) | resolved-in-code | (ADR-0023 Amendment 4b, uncommitted at report time) | — |
| AD-2 (epic closure) | resolved-in-code | (ADR-0003 amendment, uncommitted at report time) | — |

Spec index: 25,503 bytes, 100 sections, 4 spec files (`spec-index.md` header line 2).
Across this epic's two architectural-drift reviews (sprint-01 closure + epic closure),
reviewers' `Sections read:` footers list 24 ranges total (18 + 6).

Spec sync's share of this epic's fresh tokens: N/A — `runtime=other` means tokens are not
observable from a transcript at any node this epic, so the 5%-budget check cannot be
evaluated numerically; `l3io-spec-sync`'s one dispatch (SD-01-5) was a single narrow fix (one
missing ADR cross-reference) and is not believed material.

## Dispatch brackets this epic (epic-closure phase only)

`l3io-arch-review` (epic-level), `l3io-spec-sync`, `l3io-sec-redteam` (epic-level),
`bmad-retrospective` — all opened and closed cleanly; no bracket left open at report time.
