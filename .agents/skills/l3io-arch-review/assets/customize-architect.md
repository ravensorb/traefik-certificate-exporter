# Wiring the standards into core BMad (bmad-customize overlay)

The `l3io-arch-review` skill is self-contained, but the standards deliver the most value when
they fire **automatically** inside the core architecture and review flows. Do this
non-destructively with the BMad **`bmad-customize`** skill — no forking of core skills, and
the overlay survives BMad updates.

Author these overlays **in the consuming project** (not in this extensions repo — the core
skills live in the target repo). Run `/bmad-customize` and add, for each target skill, an
instruction block equivalent to the following.

## Overlay for `bmad-architect` (design + decisions)

> Before finalizing any architecture or technology decision, load
> `l3io-arch-review/references/standards-core.md` and the overlay(s) matching the project's
> stack(s). Hold the design against every principle (§1–10). For each load-bearing call
> (stack, key dependency, non-GA/preview use, logging stack, deployment mode) record an ADR
> using the l3io-arch ADR template. Produce at least a C4 context + one flow diagram (Mermaid
> preferred). Ensure the docs skeleton covers architectural / developer / operational axes.

## Overlay for `bmad-create-story` (technical acceptance criteria)

> When drafting a story's acceptance criteria, additionally load
> `l3io-arch-review/references/standards-core.md` (plus the overlay(s) matching the story's
> stack) and ensure the ACs make the **technical contract** explicit wherever the story implies
> one — interfaces / API contracts, data model, error/edge/failure handling, observability
> (logging/metrics/tracing), security controls (authz/authn, input validation at trust
> boundaries, secrets), and testability / measurable NFRs. Add a concrete technical AC for each
> applicable dimension; do not expand scope beyond the story's intent. This makes the
> implementation contract unambiguous before development, rather than leaving it to each dev
> agent — and it is what `l3io-pm-execute`'s story technical-AC gate checks for.

## Overlay for `bmad-code-review` (and/or l3io-sec-redteam)

> During review, additionally check compliance with `l3io-arch-review/references/standards-core.md`
> and the loaded stack overlay(s). Emit any deviation as a finding (severity · principle ·
> location · remediation). Treat BLOCKER/MAJOR as gating; MINOR defers to backlog.

## Notes

- Keep the overlay text short; it *points at* the standards files rather than duplicating them
  (single source of truth — Core §2, reuse over copy-paste).
- The standards files must be resolvable in the consuming repo (the module is installed there).
- Re-run `/bmad-customize` to update the overlay if the standards' entry points change.
