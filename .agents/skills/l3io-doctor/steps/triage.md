## Triage Mode

Invoked with the `triage` argument. Reviews the open backlog in `{pm_issues_file}` and closes
what is already resolved — with evidence, and only on confirmation. It runs three passes:
structural integrity (`audit-issues`), mechanical evidence (`scripts/audit-backlog.py`), then
an optional agent review of whatever is left. All [Safety Rules](`SKILL.md` § Safety Rules)
apply: nothing is written without a yes, and nothing uncertain is closed.

### Step T1 — Load config

Load config (same as layout cleanup), then bind:

- `{model_review}` — `modules.l3io-pm.model_review` (default `{model}`)
- `{triage_session}` — `triage-{UTC timestamp, e.g. 20260910T153000Z}`; pass it as
  `--session-id` and `--cause triage` on every write below

**Precondition — `{pm_state_root}`, not `{pm_issues_file}`.** If `{pm_state_root}` does not
exist, print `No state tree — nothing to triage.` and exit. Do **not** gate on
`{pm_issues_file}`: `audit-issues` runs its story-node walk over an empty store whenever the
state root exists (`pm-status.py cmd_audit_issues` takes no lock and reads no issue file in
that branch), and findings **1b** (a `resolves:` key naming neither issue file) and **1h** (two
live stories claiming one key) are reported from story nodes alone. Those are exactly the
findings Health Check 13 flags `triage` for, so exiting here would have refused the case the
detector raised. `issues-resolved.yaml` can also exist without `issues.yaml`, which makes
findings `1a` and `1j` reachable too.

When both issue files are absent the backlog passes are not skipped — they run and come back
empty on their own: `list-issues --all` returns `{"open": [], "resolved": []}` at exit 0 and
creates no lock file, `audit-backlog.py` prints `audit-backlog: no open items`, T3b's two
`--kind` queries are empty so it skips itself, and T4's `needs-review` count is zero. Report
the T2 findings and let T7 print zeroes for the rest.

### Step T2 — Integrity

```bash
uv run {pm_status} audit-issues --state-root {pm_state_root} --format json
```

Exit `0` → print `✓ Backlog integrity: no findings` and go to T3. Exit `4` with a non-empty
`findings` list → print every finding (`id`, `key`, `detail`) and the command that repairs it.
Exit `4` with `findings: []` and an `error` → a malformed issue file, or a story node that
failed to parse, was not a mapping, or was not valid UTF-8; print the `error` and stop — an
empty `findings` list on exit 4 is not "clean":

| Finding | Repair |
|---|---|
| `1a` | `uv run {pm_status} resolve-issue --state-root {pm_state_root} --key {key} --resolution obsolete --note "clear stale open copy (audit 1a)"` — the resolution already recorded is kept; this only clears the open copy |
| `1b` with a scheduled item, `1g` | `uv run {pm_status} repair-issue --state-root {pm_state_root} --key {key} --action unschedule` |
| `1c` | `uv run {pm_status} resolve-issue --state-root {pm_state_root} --key {key} --resolution fixed --ref {story}` |
| `1d` | `uv run {pm_status} repair-issue --state-root {pm_state_root} --key {key} --action link --story {story}` |
| `1e` with key `next` (a malformed map) | `uv run {pm_status} repair-issue --state-root {pm_state_root} --key {any existing BL key} --action reseed` — the finding names no epic; one reseed rebuilds every epic |
| `1e`, an alias key (value at most 1000) or a stale canonical `next` | `uv run {pm_status} repair-issue --state-root {pm_state_root} --key BL-E{epic}-001 --action reseed` |
| `1e` whose `repair` starts `report only` — a `next` value, alias or canonical, above the BL key space (1000) | report only — print the finding's `repair` text as the manual fix, naming the key and the value; `reseed` refuses this case (exit 2). An alias above 1000 reports two such findings (the alias, and the value), both with this hand-fix `repair` |
| `1j` | `uv run {pm_status} repair-issue --state-root {pm_state_root} --key {key} --action reopen` |
| `1f` whose detail says **legacy status** (a pre-3.0 resting state such as `deferred`) | `uv run {pm_status} repair-issue --state-root {pm_state_root} --key {key} --action normalize-status` — maps the legacy status to its current equivalent |
| **many** `1f` legacy-status findings (a schema upgrade, not a sick backlog) | `uv run {pm_status} repair-issue --state-root {pm_state_root} --action normalize-status --all-legacy` — one confirmed pass, one lock, no `--key`. **Epic-aware**: an item behind an open epic becomes `backlog`, one behind a CLOSED epic is resolved as `deferred` with a note (a resolution is the only place a decision can live), and one whose epic has no state node is skipped and reported rather than guessed. Relay the three-way tally it prints. Offer this instead of the per-item command whenever more than a handful are legacy: a real upgrade produced 452, and per-item that is 452 subprocesses inside a per-item confirmation loop. The same gate applies to each item, so an unrecognised status is left alone rather than swept along |
| `1b` naming an unknown key, `1f` with any other status, `1h`, `1i`, `1k` | report only — print the finding's `repair` text as the manual fix. An unrecognised status has no safe mapping, so `normalize-status` refuses it (exit 2) |

Add `--session-id {triage_session} --cause triage` to every command. When one key carries both
`1a` and `1j`, run only `reopen`: it completes an interrupted reopen, whereas the `1a` repair
would re-close the item.

Ask: `Apply {n} repair(s)? (Y = all / p = pick / n = none)`. Run the confirmed ones, then rerun
`audit-issues` and report what remains.

### Step T3 — Mechanical proposals

```bash
uv run {skill-root}/scripts/audit-backlog.py --pm-status {pm_status} \
  --state-root {pm_state_root} --artifacts-root {implementation_artifacts} \
  --project-root {project-root} --format json
```

Print every `warnings` entry first. A `project-root suspect` warning means the paths do not line
up — it only engages once there are at least 3 code-marker items and most of their files are
missing, so a single deleted file still gets its normal `obsolete-candidate` verdict rather than
being suppressed. Say so plainly and do not continue past this step until the user confirms the
project root.

Table every `fixed-candidate`, `obsolete-candidate`, and `duplicate-candidate` verdict with its
`evidence`, marking `origin_archived` items. List `open` verdicts (a marker still present) as
information. Ask: `Resolve {n}? (Y = all / p = pick / n = none)`. For each confirmed item:

- **`fixed-candidate`** — find the commit that removed the marker:
  `git -C {project-root} log -n1 --format=%h -S "{title}" -- {pointer}`. Use it as `--ref`;
  if that prints nothing, use `git -C {project-root} rev-parse --short HEAD`. Then run
  `resolve-issue --resolution fixed --ref {sha} --note "{evidence}"`. Outside a git repository,
  run `resolve-issue --resolution obsolete --note "{evidence}"` instead.
- **`obsolete-candidate`** — `resolve-issue --resolution obsolete --note "{evidence}"`
- **`duplicate-candidate`** — `resolve-issue --resolution duplicate --ref {ref}`. If it refuses
  (for example, a duplicate chain), show the refusal and leave the item open.

### Step T3b — Spec changes and proposals

```bash
uv run {pm_status} list-issues --state-root {pm_state_root} --kind spec-change --format json
uv run {pm_status} list-issues --state-root {pm_state_root} --kind spec-proposal --format json
```

Skip this step when both are empty. Otherwise take each item in turn, oldest first:
- `spec-change`: show `git -C {project-root} show --stat {ref}`, then the diff
  (`git -C {project-root} show {ref}`)
- `spec-proposal`: show the proposal file at `{ref}`

Ask: `Confirm, reject, or skip {key}? (c/r/s)`.

- **Confirm a spec change** →
  `uv run {pm_status} resolve-issue --state-root {pm_state_root} --key {key} --resolution fixed --ref {ref} --session-id {triage_session} --cause triage`
- **Confirm a proposal** → ask for the commit that changed the spec, then run the same
  command with `--ref {that sha}`. If there is no such commit yet, skip the item. A proposal
  is confirmed only once the spec actually says it.
- **Reject either kind** → `{spec_align} reject --key {key}`. It does three things:
  - reverts a spec change (`git revert`; a proposal needs nothing reverted);
  - resolves the item `wontfix`;
  - files the drift as a code fix (`Code diverges from spec: …`, at the original severity).

  Exit 2 on a revert conflict means it aborted the revert and left the item open: print its
  message. Nothing else changed.
- **Skip** → leave the item open. Health Check 18 reports it once a later commit builds on it.

### Step T4 — Agent review (optional; costs tokens)

Count the `needs-review` verdicts, split into those with a `pointer` and those without (`u`).
Ask:

```
{n} item(s) need a reviewer to check them against the current code
→ {ceil(n / 8)} spawn(s) on {model_review}. Run? (y/n)
Include the {u} untraceable item(s) too? (y/n)
```

Spawn nothing without a yes. Group the chosen items by epic, in batches of at most 8. Bracket
each spawn, closing it on every exit path:

```bash
uv run {pm_status} dispatch --state-root {pm_state_root} --event open \
  --agent l3io-util-triage --epic E{epic} --session-id {triage_session}
# ... spawn on {model_review} ...
uv run {pm_status} dispatch --state-root {pm_state_root} --event close \
  --agent l3io-util-triage --epic E{epic} --session-id {triage_session}
```

Send this prompt verbatim, filling in the item lines:

```
You are checking whether recorded findings are already fixed in the current code.
Read-only: do not edit, create, or delete any file, and run no git write command.
For each item, read the finding at its pointer (file:line) when one is given, then inspect
the current code it concerns. Answer with exactly one JSON object per item, one per line:
{"key": "<BL key>", "verdict": "fixed" | "still-present" | "can't-tell", "evidence": "<file:line> — <one sentence>"}
A "fixed" verdict MUST cite file:line evidence showing the fix. If you cannot find the code
the finding describes, answer "can't-tell".
Items (key | severity | title | source | pointer):
{one line per item}
```

### Step T5 — Agent proposals

Parse one JSON object per line. Treat a `fixed` verdict whose `evidence` has no `file:line` as
`can't-tell`. Table the `fixed` verdicts with their evidence. `still-present` and `can't-tell`
items stay open; list them. Ask as in T3. For each confirmed item:
`resolve-issue --resolution fixed --ref $(git -C {project-root} rev-parse --short HEAD) --note "{evidence}"`
("fixed as of this commit, per the reviewer's evidence"). Outside git, use `obsolete` with the
same note.

### Step T6 — Manual pass (optional)

Ask: `Re-severity or close anything else? (list keys, or n)`. For each key the user names, run
`update-issue --severity {S} --note "{why}"`, or
`resolve-issue --resolution {wontfix|obsolete} --note "{why}"` — whichever they choose.

### Step T7 — Summary

Recount with `uv run {pm_status} list-issues --state-root {pm_state_root} --all --format json`:

```
BACKLOG TRIAGE — {pm_issues_file}
================================================================
  Integrity repairs:  {n}  ({finding ids})
  Resolved:           {n}  (fixed {a} · obsolete {b} · duplicate {c} · wontfix {d})
  Re-severitied:      {n}
  Spec items:         {n}  (confirmed {a} · rejected {r} · still open {o})
  Still open:         {n}  (untriaged {u} · scheduled {s} · origin archived {o})
================================================================
```

---
