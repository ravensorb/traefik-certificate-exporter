# Architectural Review — Report Shape

Structure a review (Mode B) output as follows.

## Executive summary

2–4 sentences: overall posture, the count by severity, and the single most important action.

## Findings table

| # | Severity | Principle | Location | Finding | Remediation |
|---|----------|-----------|----------|---------|-------------|
| 1 | BLOCKER  | Core §1 Separation of Concerns | `path:line` | domain imports ORM type | extract mapping layer |

Severity: **BLOCKER** (hard-rule violation) · **MAJOR** (clear deviation, fix or ADR-justify) ·
**MINOR** (improvement; auto-defers to backlog).

## Per-principle walkthrough

For each principle in `standards-core.md` §1–10 and each loaded overlay, one line: PASS, or the
finding number(s). Do not skip a principle — an unwalked principle is an incomplete review.

## Gate

- BLOCKER + MAJOR: must be resolved or recorded as an accepted ADR before sign-off.
- MINOR: defer to backlog.

## Recommended ADRs

Any decision surfaced by the review that lacks a record → list it for authoring via
`assets/adr-template.md`.
