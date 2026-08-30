## Sort Status Mode

Invoked with `sort-status` argument. Validates state file and directory naming in the sharded
`{pm_state_root}` tree against the zero-padded convention. **Read-only** — reports misnamed
entries, does not rename or reorder anything. Ordering itself can no longer drift under the
sharded layout: nodes are individual files, and zero-padded names (`epic-{nnn}`, `sprint-{nn}`,
`E{nnn}-S{nn}-{nnn}`) make directory-listing order the correct order, so there is no separate
sort step the way there was when a whole epic's sprints and stories lived as one YAML list
that could be edited out of order. What *can* still go wrong is a misnamed entry — created or
edited outside `pm-status.py` — and a misnamed entry is not cosmetic: `pm-status.py` resolves
every node path from its key, so a wrongly-padded directory or file is silently unreachable by
key lookup rather than merely out of order. That is what this mode checks for.

If you want a rename applied rather than just reported, the two-digit legacy epic form is
fixed by `steps/rename-epic-dirs.md` (Rename Epic Dirs Mode) (`rename-epic-dirs`) — this mode does
not duplicate that rename logic itself.

**Naming convention checked:**

| Entry | Expected form |
|---|---|
| Epic directory | `epic-{nnn}` — exactly three digits |
| Sprint directory | `sprint-{nn}` — exactly two digits |
| Story file | `E{nnn}-S{nn}-{nnn}.yaml` |
| Epic node file | `epic.yaml` (exactly one per epic directory) |
| Sprint node file | `sprint.yaml` (exactly one per sprint directory) |

### Steps

**Step SO1 — Load config and resolve state root**

Load config (same as layout cleanup). Resolve `{pm_state_root}` = `{implementation_artifacts}/state`.

If `{pm_state_root}` does not exist:
```
No state directory found at {pm_state_root} — nothing to validate.
```
Exit. (State is created lazily by `pm-status.py` on first write — there is no separate setup
command to point to, and `split-status` is a decommissioned migration path for a different,
older layout; do not suggest it here.)

**Step SO2 — Walk and validate naming**

Walk `{pm_state_root}/{planned,active,archived}/`. For each entry found, check:
1. Each top-level directory matches `epic-[0-9]{3}` exactly (three digits). Flag deviations —
   most commonly the legacy two-digit `epic-{nn}` form, but also unpadded or non-numeric
   suffixes.
2. Within each epic directory, each subdirectory matches `sprint-[0-9]{2}` exactly (two
   digits). Flag deviations.
3. Within each sprint directory, every `.yaml` file other than `sprint.yaml` matches
   `E[0-9]{3}-S[0-9]{2}-[0-9]{3}\.yaml` exactly. Flag deviations.
4. Each epic directory contains exactly one `epic.yaml`; each sprint directory contains
   exactly one `sprint.yaml`. Flag missing or duplicate node files.
5. Each story filename's embedded `E{nnn}-S{nn}` segment matches the epic/sprint directories
   it was found under. Flag mismatches. (This checks the *filename* against its path; Health
   Check 11's back-reference check reads the file's *contents* against its path — the two are
   independent and both worth running.)

Accumulate all findings as `{naming_issues}`.

**Step SO3 — Report**

If `{naming_issues}` is empty:
```
STATE NAMING CHECK — {pm_state_root}
  planned/:  {p_epics} epic(s) — ✓ all names valid
  active/:   {a_epics} epic(s) — ✓ all names valid
  archived/: {r_epics} epic(s) — ✓ all names valid
Ordering is not checked separately — zero-padded names make directory-listing order the
correct order, so there is nothing that can drift the way a YAML list could.
```
Exit.

Otherwise:
```
STATE NAMING ISSUES — {pm_state_root}
================================================================
Path                                              Issue
----------------------------------------------------------------
{pm_state_root}/active/epic-01/                   expected epic-{nnn} (three digits)
{pm_state_root}/active/epic-001/sprint-1/         expected sprint-{nn} (two digits)
{pm_state_root}/active/epic-001/sprint-01/E1-S01-002.yaml   expected E{nnn}-S{nn}-{nnn}.yaml
...
================================================================
{N} naming issue(s) found. Report only — this mode does not rename or move anything.
Two-digit epic-{nn}/ directories: fix with `/l3io-util-doctor rename-epic-dirs`.
Other naming issues need manual correction — they usually mean a file was created or edited
outside pm-status.py.
```

```
DONE — State naming check complete.
  Issues found: {N}  (0 means state is clean)
```

---
