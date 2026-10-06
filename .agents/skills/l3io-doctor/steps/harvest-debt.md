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

**Build the file list with `find`, then search it. Do not use `grep -r`.** The recursion is
`find`'s, never the grep implementation's:

```bash
find . -type f \
  -not -path '*/.git/*' -not -path '*/node_modules/*' -not -path '*/dist/*' \
  -not -path '*/build/*' -not -path '*/vendor/*' -not -path '*/.venv/*' \
  -not -path '*/target/*' -not -path '*/out/*' \
  -not -path '*/{implementation_artifacts}/*' -not -path '*/{planning_artifacts}/*' \
  -print0 > "$list"

files_searched=$(tr -dc '\0' < "$list" | wc -c)
xargs -0 --no-run-if-empty grep -niE '(#|//|--|;|%|/\*|<!--|'\'') ?bmad-defer:' < "$list"
```

`$list` comes from `mktemp` with its `trap` on the next line, per
`l3io-arch-review/references/standards-shell.md`:

```bash
list="$(mktemp)"
trap 'rm -f "$list"' EXIT
```

**The list goes to a file rather than straight down a pipe** so the count and the search read
the same set. A first draft piped `find` into `tee >(tr -dc '\0' | wc -c >&2)`, which produced
the right number but wrote it to the process substitution's own stderr, where the pipeline's
redirect could not capture it — the count printed to the terminal and `{files_searched}` came
back empty. Running `find` twice would also work and would risk the two runs disagreeing if
the tree changed between them.

Append `-not -path '*/{dir}/*'` for each directory listed in `harvest_exclude_dirs` (resolved in Step H1).

**Why `find` and not `grep -r`, which this contract used until 3.2.4.** `grep -r`'s recursion
semantics are not the same across the implementations actually on PATH: **ugrep honours
`.gitignore` during a recursive search and GNU grep does not.** Measured on one box carrying
both, same command, one marker in a tracked directory and one in a git-ignored directory:

    GNU grep 3.12  -> both markers
    ugrep 7.8.4    -> the tracked one only

A consuming project whose org root git-ignores its six source repositories therefore swept
none of them and reported a clean tree. `find` has no notion of `.gitignore`, so the result
stops depending on which `grep` is installed. Passing ugrep's `--no-ignore` would fix that box
and reintroduce the same class, because the flag is not portable to GNU grep.

`--no-run-if-empty` is load-bearing: with no input, `xargs` runs `grep` with no file operands,
`grep` then reads **stdin**, and the sweep hangs instead of reporting zero files. The flag is a
GNU extension — on a system without it, guard the pipeline with a non-empty test instead.

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
`{upgrade}` (or empty), and `no_trigger` = true when `{upgrade}` is empty.

**Always report how many files were searched, not only how many markers were found.** Bind
`{files_searched}` to the count the contract prints, and branch on it:

- `{files_searched}` is 0 → **this is a fault, not a clean tree.** Print
  `Searched 0 files — the sweep matched nothing to search, so "no markers" means nothing here.
  Check the exclusion list and {harvest_exclude_dirs}.` and exit **without** reporting a clean
  tree.
- markers found is 0, files searched > 0 → `Searched {files_searched} files. No bmad-defer:
  markers found — clean tree, nothing to harvest.` and exit.
- otherwise → carry `{files_searched}` into the Step H4 ledger header.

**Why the count is not cosmetic.** Before it existed, "0 markers found" and "0 files searched"
printed the identical sentence. A consuming project's sweep returned six hits — all of them
this skill's own doc examples across two install mirrors — and zero real markers, while a real
marker sat in the tree the whole time; the post-sweep payload filter then dropped the six and
the mode reported a clean tree. The output looked like good news, which is the only reason it
went unnoticed. A search that examined nothing must not be able to render as a search that
found nothing.

**Step H3 — Dedupe against the existing backlog**

Read both issue lists with `uv run {pm_status} list-issues --state-root {pm_state_root} --all --format json` (if `{pm_status}` is absent, read the `backlog:` list from `{status_backlog}` and treat the resolved list as empty). A marker is
**already harvested** when an existing item matches on **file path plus normalised marker
text**. Normalise both sides the same way before comparing: strip the comment leader and the
`bmad-defer:` keyword, collapse internal whitespace, casefold. Match against the item's
`source` **and** its title, since the text is what survives.

**The line number is metadata, not identity.** Where an existing item's `source` carries a
stale line, refresh it to the swept one rather than filing a second item.

*Identity used to be `code-marker ({file}:{line})`, so any edit ABOVE a marker changed its
identity and the next sweep re-filed it as new. Observed: a marker harvested at line 120,
reported at 123 three days later, already queued to duplicate. A line number is the one part
of a marker's location guaranteed to drift.*

**Back-compat is the acceptance criterion, not a nicety.** The two formats already in the wild
must still match, or every previously-harvested item orphans and re-files on the next sweep —
which is the bug, inverted and applied to the whole backlog at once:
- `code-marker ({file}:{line})` — written by `harvest-debt` itself
- `clean-release (code-marker {file}:{line})` — written by sprint closure Step 9

Both carry the path, so path-plus-text matches them with the line ignored. A third shape has
been seen in the field (`harvest-debt (bmad-defer: {file}:{line})`), authored outside this tool
and matching neither documented format; path-plus-text absorbs it too, which is the point of
keying on content rather than on a source string's exact spelling. Dedupe is matched on the
`source`/title content, not by key — so legacy `DEBT-NN` keyed entries from prior runs are also
correctly deduped. Partition the swept markers:
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
