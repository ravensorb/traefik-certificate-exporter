## Harvest Debt Mode

Invoked with `harvest-debt` argument. Sweeps the source tree for `bmad-defer:` deferred-shortcut
markers and harvests them into the consolidated `backlog:` list so intentional simplifications stay
visible instead of rotting into "later means never." Report-only by default; the backlog merge is a
separate confirmed step. All [Safety Rules](`SKILL.md` § Safety Rules) apply — dry-run first, never overwrite,
never guess. Re-runnable: a marker already harvested is not added twice.

### The deferral marker contract (the shared source of truth)

A deferral marker is a single source-code comment in this form (the comment leader varies by
language; everything after `bmad-defer:` is the payload):

```
<comment-leader> bmad-defer: <what was simplified>. ceiling: <the limit this assumes>. upgrade: <the trigger to revisit>.
```

Examples across languages (all matched):

```python
# bmad-defer: linear scan over the cache. ceiling: <500 entries. upgrade: switch to an index past that.
```
```go
// bmad-defer: in-memory rate limit. ceiling: single instance. upgrade: move to Redis when horizontally scaled.
```
```sql
-- bmad-defer: full-table count. ceiling: <100k rows. upgrade: maintain a counter table beyond that.
```

- **Recognized comment leaders** (so the sweep is language-generic): `#`, `//`, `--`, `;`, `%`,
  `/*` (C-style block open), `<!--` (HTML/XML/Markdown), `'` (VB/VBScript). The marker keyword
  `bmad-defer:` is matched **case-insensitively**.
- **Payload parsing:** the text after `bmad-defer:` up to `ceiling:` is `<what>`; the text after
  `ceiling:` up to `upgrade:` is the `<ceiling>`; the text after `upgrade:` is the `<upgrade>`
  trigger. `ceiling`/`upgrade` are optional in the text — a marker that names **no** `upgrade:`
  trigger is tagged **`no-trigger`** (these rot silently and are escalated; see severity below).
- This is the same marker the PM dev and clean-release phases write and read — keep the keyword and
  field names stable; other skills depend on this exact contract.

### Grep contract

Search the whole tree from `{project-root}`, **case-insensitive**, with line numbers, skipping
vendored/build/VCS output:

```bash
grep -rniE '(#|//|--|;|%|/\*|<!--|'\'') ?bmad-defer:' . \
  --exclude-dir=node_modules --exclude-dir=.git --exclude-dir=dist --exclude-dir=build \
  --exclude-dir=vendor --exclude-dir=.venv --exclude-dir=target --exclude-dir=out \
  --exclude-dir='{implementation_artifacts}' --exclude-dir='{planning_artifacts}'
```

Append `--exclude-dir={dir}` for each directory listed in `harvest_exclude_dirs` (resolved in Step H1).

Artifact directories are excluded — markers are a **source-code** convention, not an artifact one,
and a marker quoted inside a backlog description must never re-harvest itself.

**Then drop every hit whose path falls inside this skill's own installed payload** — the
directory this step file was loaded from, and any sibling mirror of it (a BMad install writes
both `.claude/skills/l3io-doctor/` and `.agents/skills/l3io-doctor/`). A hit in
`…/skills/l3io-doctor/steps/harvest-debt.md` is one of this file's own three syntax examples,
never project debt.

This is a **post-sweep filter, not an `--exclude-dir`, and the distinction is load-bearing.**
Excluding `.claude` and `.agents` wholesale is one line shorter and wrong: projects keep real
hooks and tooling scripts under `.claude/`, and a marker in one of those is exactly the debt
this mode exists to surface. Blinding the sweep to a whole directory trades a visible false
positive for a silent false negative, which is the worse failure for a tool whose entire job is
noticing what would otherwise be forgotten. Mangling the examples so they stop matching is worse
still — they sit in `python`/`go`/`sql` fences precisely so they can be copied, and a copied
marker that the sweep cannot find is that same silent false negative, relocated into user code.
The examples stay verbatim; the sweep stays broad; only this file's own payload is filtered.

Narrowing the exclusion to a *path* instead (`--exclude-dir=./.claude/skills/l3io-doctor`) does
not rescue the `--exclude-dir` form either: GNU grep matches `--exclude-dir` against the
directory **basename**, so a path-shaped value is **silently a no-op** — no error, no warning,
both the example and any real marker come back. Verified against GNU grep 3.12. The trap is that
some drop-in replacements (ugrep, for one) *do* honour the path form, so whoever re-litigates
this may test it on a machine whose `grep` is not GNU grep, see it work, and revert. Resolving
the filter at parse time sidesteps that whole portability surface rather than depending on it.

Without this filter the mode finds its own examples in every project that installs the skill —
three markers × two install mirrors = six phantom hits on a tree with no real debt. Dedupe does
not absorb them: H3 matches on `source: code-marker ({file}:{line})` against items already in the
backlog, and an example nobody harvested matches nothing, so it is classified `new` and offered
for filing. Reported 2026-09-29 as a Health Check defect, but the sweep is shared — Health
Check's Check 6 delegates to this contract, so it faithfully reported this mode's wrong number.
Fixing it here fixes both; fixing it in Check 6 alone would have left `/l3io-doctor
harvest-debt` still offering to write the examples into the backlog.

### Steps

**Step H1 — Load config and resolve the backlog file**

Load config (same as layout cleanup). Also resolve:
- `harvest_exclude_dirs` — from the `l3io-util` section; default `[]`. Additional directories to exclude from the sweep on top of the built-in exclusion list. Each entry is passed as an additional `--exclude-dir` argument in the [Grep contract](#grep-contract).

Bind `{status_backlog}` = `{pm_issues_file}` (`{pm_state_root}/issues.yaml`) — the single flat
deferred-issue list of the current layout. Then check for a legacy layout using the same
three-way count Check 2b uses, and refuse to write past one:

1. If a legacy layout is present (legacy flat `sprint-status*.yaml`, or legacy per-epic
   `_bmad/state/`) and `{pm_state_root}` does not exist → print:
   ```
   State is still on a legacy layout — harvest-debt writes to {pm_issues_file}, which does
   not exist yet. Run /l3io-doctor migrate-state first, then re-run harvest-debt.
   ```
   and exit (never write into a legacy file).
2. Else → `{status_backlog}` is the target. It is created lazily in Step H6 if absent,
   containing only a top-level `backlog:` list (the shape `append-issue` writes).

**Step H2 — Sweep and parse**

Run the [Grep contract](#grep-contract). For each hit, parse one marker record:
`{file}` (path relative to `{project-root}`), `{line}`, `{what}`, `{ceiling}` (or empty),
`{upgrade}` (or empty), and `no_trigger` = true when `{upgrade}` is empty. If the sweep finds
nothing, print `No bmad-defer: markers found. Clean tree — nothing to harvest.` and exit.

**Step H3 — Dedupe against the existing backlog**

Read both issue lists with `uv run {pm_status} list-issues --state-root {pm_state_root} --all --format json` (if `{pm_status}` is absent, read the `backlog:` list from `{status_backlog}` and treat the resolved list as empty). A marker is
**already harvested** if an existing item has `source` containing `code-marker ({file}:{line})` — this matches both entries written by `harvest-debt` itself (`source: 'code-marker ({file}:{line})'`) and entries written by sprint closure Step 9 (`source: 'clean-release (code-marker {file}:{line})'`), so running either tool first does not produce duplicates when the other runs later. Dedupe is matched by `source` field, not by key — so legacy `DEBT-NN` keyed entries from prior runs are also correctly deduped by their source field. Partition the swept markers:
- `existing` — matches an open item, or a resolved item whose `resolution` is not `fixed`
  (skip; do not duplicate or re-key).
- `new` — matches nothing, **or matches only resolved `fixed` items**: the shortcut came back
  after it was fixed. H6 passes it to `append-issue`, which records it as a recurrence.

**Step H4 — Dry-run ledger**

Group `new` markers by file and print the ledger (this is also the report-only output — a user who
declines Step H5 still gets this):

```
DEBT HARVEST DRY RUN — bmad-defer: markers
================================================================
{file}
  L{line} — {what}
            ceiling: {ceiling | '(none)'}   upgrade: {upgrade | 'NO-TRIGGER — rots silently'}
...
================================================================
Markers found: {total}  ·  new: {new_count}  ·  already harvested: {existing_count}  ·  no-trigger: {no_trigger_count}
Backlog target: {status_backlog}
```

If `{new_count}` is 0: print `All {total} marker(s) already harvested — backlog is current.` and exit.

**Step H5 — Confirm merge**

Ask: "Harvest {new_count} new marker(s) into the backlog at {status_backlog}? Existing entries are untouched."

If no: print `Harvest cancelled — report only, no changes made.` and exit.

**Step H6 — Merge into the backlog**

Append one item per `new` marker to the top-level `backlog:` list of `{status_backlog}`, following
the consolidated backlog schema (`references/status-files.md` is the schema source of
truth).

**When `{project-root}/_bmad/scripts/pm-status.py` is present, use it — this is the only correct
path when it is available.** Call `append-issue` **without `--key`**:

```bash
uv run {project-root}/_bmad/scripts/pm-status.py append-issue --file {pm_issues_file} \
  --epic 000 --title "{what}" \
  --source "code-marker ({file}:{line})" --severity {Low|Medium} \
  --description "{what} (ceiling: {ceiling | none}; upgrade: {upgrade | NONE — no revisit trigger})."
```

The `BL-E000-{nnn}` number is **allocated by the command itself**, under an exclusive flock, from
the highest existing suffix it finds — that lock is what makes `issues.yaml` safe as the one
shared-append target across every epic and every parallel caller. Do not choose or pass a number:
a hand-picked `{nnn}` is exactly the failure this command exists to close off, since two callers
inventing a number from the same directory listing can both succeed and silently overwrite one
another. Severity rule: a marker that names an `upgrade:` trigger is `Low`; a `no-trigger` marker
is `Medium` (it has no built-in escape from rotting, so it earns a higher gate). Never invent a
ceiling or upgrade the comment did not state — pass `none`/`NONE`.

**Fallback — only when `pm-status.py` is absent.** Hand-write the item into `{status_backlog}`'s
`backlog:` list, deriving the key by continuing the highest existing `BL-E000-{nnn}` suffix (check
existing items with `epic: '000'`; also check for any legacy `DEBT-NN` or narrower-padded
`BL-E00-NN` items to avoid gap collisions, parsing sequence numbers numerically):

```yaml
- key: BL-E000-001                     # BL-E000-{nnn} — repo-global, not epic-scoped
  epic: '000'                          # '000' = repo-global marker
  sprint: ''
  title: {what}                        # first clause of the marker, trimmed
  source: 'code-marker ({file}:{line})'
  severity: Low                        # Medium when no_trigger — a deferral with no revisit trigger rots silently
  status: backlog
  description: '{what} (ceiling: {ceiling | none}; upgrade: {upgrade | NONE — no revisit trigger}).'
```

This manual derivation **cannot be made collision-safe** — there is no lock protecting a
hand-edited YAML file — so it is for single-agent, non-parallel use only, when no other process
could be appending to the same backlog at the same time. As soon as `pm-status.py` becomes
available, use it instead.

**Step H7 — Verify**

Re-parse `{status_backlog}` as YAML. If parsing fails, restore the pre-merge content and print:
```
FAILED — Written backlog is not valid YAML. Original restored. Parse error: {error}
```

**Step H8 — Report**

```
DONE — Debt harvest complete.
  Markers swept:     {total}
  Harvested (new):   {new_count}  (Low: {low_count}, Medium/no-trigger: {no_trigger_count})
  Already harvested: {existing_count}
  Backlog:           {status_backlog}
```

Markers stay in the source until the developer removes them when the shortcut is upgraded; harvest
records them, it never edits source. A future run re-sweeps and dedupes, so removing a marker simply
stops it reappearing (the backlog item it created persists until triaged like any other).

---
