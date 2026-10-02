## Migrate ADRs Mode

Moves ADRs from the old per-epic home, `{implementation_artifacts}/epic-*/arch/adr-NNNN-*.md`,
to `{project-root}/docs/adr/NNNN-slug.md`, the one ADR home. Health Check 15 detects them. A
project that never migrates keeps working: `adr-reserve` and `spec-align.py adrs` still read
the old home.

### Step MA1 — Plan (read-only)

```bash
{spec_align} migrate-adrs --plan
```

Print a table of `moves`: from, to, epic, and the `duplicate` / `collision` flags. Every move
is exactly one of three kinds, and the plan splits them into `actionable` and `duplicates`:

**Plain move** — no file in `docs/adr/` holds that number. `to` is set; it is simply moved.

**Duplicate** (`duplicate: true`) — `docs/adr/` already holds that **number AND slug**. This is
not a competing decision: it IS that decision, already migrated, and the epic file is a
leftover — usually a stale pre-supersession snapshot. **It is never moved and never
renumbered.** Report it, show `diff <docs/adr copy> <epic copy>`, and offer to delete the epic
leftover as a separate, explicitly confirmed step.

> Renumbering these was a live defect: the classifier compared numbers only, so on a project
> that had already migrated, *every* leftover was minted as a brand-new ADR duplicating one
> already in `docs/adr/`, and the epic's artifacts were rewritten to cite the invented number.

**Collision** (`collision: true`) — same number, **different** slug: two genuinely different
decisions competing for one number. `to` is empty. At apply time:
- the `docs/adr/` file keeps its number, since it may be cited outside PM artifacts;
- the epic ADR gets a newly reserved number;
- `ADR-NNNN` mentions are rewritten **only inside that epic's artifact tree**;
- every other mention is listed for a person, and not rewritten.

If `moves` is empty, print `✓ No ADRs in the old home.` and exit.

If `actionable` is empty but `duplicates` is not, print
`✓ No ADRs to move — {n} leftover duplicate(s) of ADRs already in docs/adr/.`, list them, and
exit **without** offering `--apply`. There is nothing for it to do.

### Step MA2 — Confirm

Ask: `Move {n} ADR(s) to docs/adr/ and commit? (y/n)`, where `{n}` is the count of
**`actionable`** moves — never the total, which includes duplicates that will not move.
On `n`, exit with no changes.

### Step MA3 — Apply

```bash
{spec_align} migrate-adrs --apply
```

Print its summary:
- **moved:** from → to;
- **renumbered:** old → new, from `renumbered_to`;
- **rewritten:** the files;
- **commit:** the SHA (a single `docs(adr): migrate epic ADRs to docs/adr` commit);
- **every `review` entry.** Those mentions were not rewritten; ask the user to check each
  one by hand.
