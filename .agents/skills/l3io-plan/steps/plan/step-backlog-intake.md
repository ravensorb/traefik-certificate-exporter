# Step: Backlog Intake

Communicate all responses in `{communication_language}`.

Runs in full-plan mode only, after `step-01-classify-work.md` and before
`step-02-readiness-check.md`. It offers to turn open backlog items into stories, and **never
promotes anything without an explicit choice** — there is no automatic mode. Running before
readiness is deliberate: a promoted story then flows through readiness (graded Amber —
functional ACs only), elaboration (the enricher adds the technical ACs), and
`step-estimate`, like every other story.

## 1. Read the open backlog

```bash
uv run {pm_status} list-issues --state-root {pm_state_root} --status backlog --format json
uv run {pm_status} list-issues --state-root {pm_state_root} --status scheduled --format json
```

If the first list is empty, print `Backlog intake: no untriaged items.` and continue to the
next step.

## 2. Present

Group the untriaged items Critical → High → Medium → Low, and mark any whose
`origin_archived` is true. List scheduled items separately, as work already in flight:

```
BACKLOG INTAKE — {n} untriaged item(s)
Critical
  BL-E002-004  E002/S03  {title}   (origin archived)
High
  BL-E001-006  E001/—    {title}
In flight: BL-E001-002 → E003-S02-004
```

List candidate targets: for each epic under `{pm_state_root}/planned/` and
`{pm_state_root}/active/`, the sprints whose `sprint.yaml` has `status: backlog` (read the
files directly, or use `uv run {pm_status} show --state-root {pm_state_root} --epic {key}`).
Then ask:

```
Promote any of these into planned work? Name the items and a target sprint —
e.g. "BL-E002-004 into E005 S01 as standard" — or type skip.
```

On `skip`, continue to the next step.

## 3. Promote

For each request (several items folded into one story need a `--title`):

```bash
uv run {pm_status} promote-issue --state-root {pm_state_root} \
  --artifacts-root {implementation_artifacts} \
  --key {BL key} [--key {BL key} ...] --epic {nnn} --sprint {nn} \
  --classification {simple|standard|complex} [--title "{story title}"] \
  --model {model} --session-id {session_id} --cause plan-intake
```

Use the classification the user gave. If they gave none, propose one from the finding's
severity and scope, and confirm it before running.

Every refusal writes nothing, so it is always safe to ask again:

- **exit 2 or 3** — show the message verbatim (for example
  `sprint E001-S02 is 'in-progress', not backlog`) and ask for another target. Some exit-2
  messages point at a different fix instead of another target: an unreadable story node
  (`... does not parse`, `... is not a mapping`, or `... is not valid UTF-8`) or a resumable
  claimant with a malformed key (`... has a malformed key ...`) both say to fix the file by
  hand — do that, then rerun the same command
- **exit 2, partly promoted into a different epic or sprint** (for example `BL-E005-001 were
  partly promoted into E005-S01-001 -- retry with --epic 005 --sprint 01`) — rerun with the
  named `--epic`/`--sprint`; don't count the item as promoted until that retry succeeds. If
  that retry is itself refused because the named sprint is no longer `backlog`, recover with
  `/l3io-doctor triage` — audit finding 1d offers `repair-issue --action link` to attach
  the items to the story they were partly promoted into
- **exit 5** — another session is executing that epic; choose another epic, or wait. If the
  message says the epic's lock cannot be evaluated (it is not a mapping, has no `session_id`,
  has a `claimed_at` that is missing, unparseable, or has no timezone, or has a non-integer
  `ttl_minutes`), and the lock is abandoned, clear it with `clear-lock`, then rerun
- **exit 1 — any other failure**, for example an I/O error after the story node was saved:
  rerun the same command; it resumes the story it started
- **`OK promote-issue … (resumed)`** — an earlier interrupted promotion was completed; success

## 4. Output

```
Step backlog-intake complete — promoted {n} item(s) into {story keys}; {m} left untriaged.
```
