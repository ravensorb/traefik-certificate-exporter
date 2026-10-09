# Step Reorg Undo: put a reorg back

Communicate all responses in `{communication_language}`.

Loaded when the user asks, in prose, to undo a reorg — "undo that reorg", "put the stories
back", "revert the last reorganisation". **Undo has no keyword and no flag.** It is a
conversational request, and resolving *which* reorg they mean is the first half of this
procedure.

There is no undo *flag* on `/l3io-plan reorg`, and there must never be one written in a doc or
improvised in conversation. No l3io skill parses flags, so an invocation written that way does
not run, and teaching it to a user teaches them something false.

---

## 1. Resolve which entry they mean

```bash
uv run {pm_status} reorg-log --state-root {pm_state_root} --list
```

- **No entries.** Say so and stop — there is nothing to undo, and no reorg has been applied in
  this project:

  ```
  No reorg has been recorded for this project, so there is nothing to undo.
  DONE — Undo: no journal entries
  ```

- **One entry.** That is the one they mean. Show it (§2) and confirm before acting.
- **More than one.** The default reading of "that reorg" is the most recent. Show the list,
  say which one you are about to undo, and let them name a different entry. Do not guess past
  the most recent one — a user who meant an older reorg will say so, and undoing the wrong
  reorg is not something a confirmation prompt they skimmed can be blamed for.

A user who names a reorg by what it did rather than by its id ("the one that retired the export
shim") is resolved against the journal, not against memory of the session. Read the entries and
match.

## 2. Show the entry before acting

```bash
uv run {pm_status} reorg-log --state-root {pm_state_root} --show {reorg_id}
```

The entry carries the rationale the user accepted, verbatim, and every operation that ran.
Summarise it in the same terms the proposal used — what moved, what was retired — so the user
confirms against a description they have already seen:

```
Undo {reorg_id} ({timestamp})?

  Puts back:   E003-S01-005 → E007 sprint 02
               E012-S02-001 → E012 sprint 01
  Restores:    E041 "Legacy export shim" from archived/ to planned/

Reason given at the time: "{rationale}"

Each story returns to the sprint it came from, with a NEW number — see below.
```

## 3. Check the guard before promising anything

```bash
uv run {pm_status} reorg-undo --state-root {pm_state_root} \
  --artifacts-root {implementation_artifacts} --id {reorg_id} --check
```

`--check` tests the guard and reports without moving anything, so "can this be undone?" is
answered before the user is asked to confirm. It prints `OK {id} can be undone (N
operation(s))` and exits 0.

**Undo refuses if the planned tree has changed since the reorg was applied.** The journal
recorded the tree's placement digest at the moment the reorg landed; the guard recomputes it
and compares. That refusal is correct and must not be worked around: an undo replays placements
derived from a plan that no longer exists, so it would move work somewhere nobody chose — a
story added since has no place in the recorded placement, and one moved again by hand would be
silently moved back.

Two other refusals the guard can raise, each meaning something different: the entry was
**already undone** (it says when), or an undo is **in flight** for it (it failed part way;
the journal and `dump-plan` together say how far it got).

If the guard refuses, report it plainly and stop. Name what it said, and say what the user's
real options are: `/l3io-plan reorg` can propose the shape they want from where the tree
actually is now, which is a correct operation on a known state rather than a replay onto an
unknown one.

```
BLOCKED: {reorg_id} cannot be undone — {the guard's own message}.
Run /l3io-plan reorg to propose the shape you want from the tree as it stands now.
```

## 4. Confirm, then undo

Confirm explicitly. `modules.l3io-pm.reorg_auto_apply` pre-authorises *applying a proposal*; it
says nothing about reversing one, and an undo is never silent.

```bash
uv run {pm_status} reorg-undo --state-root {pm_state_root} \
  --artifacts-root {implementation_artifacts} --id {reorg_id}
```

Undo is **the forward path run backwards**, not a bespoke restore: each operation is inverted
with the same primitives that applied it, in reverse order, so it takes the same locks and the
same gates. There is no second code path here that could be wrong in a way the forward one is
not.

**Placement is restored; keys are not, and cannot be.** Say this to the user before they
confirm, because it is the one thing an undo does not put back. A story returns to the sprint
it came from with a **new number**: the allocator's high-water never decreases, which is what
stops a vacated key being reissued to different work and silently retargeting its remote issue.
The chain of `previous_keys` records the whole journey, oldest first, so a story reorganised
and then un-reorganised is still reconcilable on the next `/l3io-sync`. The command prints every
`old -> new` pair; quote them.

**A retired epic comes back.** Retirement moved it to `archived/` and never deleted it, so undo
moves it back to the status it held before, and clears the recorded reason.

**A sprint the reorg created is left standing, empty.** Removing it would mean deleting a
directory, and deletion is the one thing this feature never does unasked. The command names
every such sprint; pass that on so the user can remove it deliberately if they want to.

## 5. Re-estimate and report

Sprint and epic roll-ups are stale again for every node the undo touched, for the same reason
they were after the apply:

```bash
uv run {pm_status} estimate-rollup --state-root {pm_state_root} \
  --epic {epic} --sprint {sprint} --model {model}
uv run {pm_status} estimate-rollup --state-root {pm_state_root} \
  --epic {epic} --model {model}
```

Add `--token-rates '{token_rates_json}'` to both when `{token_rates_json}` is non-empty.

```
✅ Undid reorg {reorg_id}

Restored (new keys — placement comes back, numbers do not):
  E003-S01-005 → E007-S02-006
  ...
  E041 back to planned/

Left standing: E003 sprint 01 was created by the reorg and is now empty. Nothing is deleted
unasked — say so if you want it removed.

Next: run /l3io-plan to write a plan snapshot that reflects the restored shape, and
/l3io-sync to reconcile the keys with their issues.
```

Omit the "Left standing" paragraph when the command reported no such sprints.

## 6. Output status line

```
Step reorg-undo complete — entry: {reorg_id}, restored: {restored_count}
DONE — Undo: {reorg_id}, {restored_count} nodes restored
```

Use `BLOCKED: <one-line reason>` when the guard in §3 refused, and `DONE — Undo: declined` when
the user chose not to go ahead.
