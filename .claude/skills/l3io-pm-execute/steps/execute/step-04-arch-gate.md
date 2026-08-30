# Step 04: Architecture Gate

Communicate all responses in `{communication_language}`.

Run a multi-reviewer architecture gate before any sprint executes. Skipped entirely for DOCS and CONFIG
work types, or when l3io-arch-review is not installed (gate never partially skips — minimum one reviewer
is required to run).

## 1. Gate eligibility check

Skip this step entirely and output `Step 04 skipped — work_type: {work_type}` if:
- `{work_type}` is `DOCS` or `CONFIG`

Check for l3io-arch-review installation against the installer's module manifest — not a
config section, which an installed-but-unconfigured module does not have
(`references/config-resolution.md` §6):

```bash
grep -qE "^[[:space:]]*-[[:space:]]*name:[[:space:]]*l3io-arch[[:space:]]*$" \
  {project-root}/_bmad/_config/manifest.yaml 2>/dev/null && echo "present" || echo "absent"
```

If absent:
```
Step 04 skipped — l3io-arch-review not installed (required reviewer absent).
```
Halt step and continue to step-05.

## 2. Detect available reviewers

| Reviewer | Detection command |
|---|---|
| `l3io-arch-review` | Already confirmed present |
| `bmad-agent-architect` | `ls {project-root}/.claude/commands/bmad-agent-architect.md 2>/dev/null \|\| ls ~/.claude/commands/bmad-agent-architect.md 2>/dev/null` |
| superpowers | `ls {project-root}/.claude/commands/superpowers:requesting-code-review.md 2>/dev/null \|\| ls ~/.claude/commands/superpowers:requesting-code-review.md 2>/dev/null` |

Bind `{active_reviewers}` = list of detected reviewer names. Minimum: `[l3io-arch-review]`.

## 3. Collect story files for review

For each scoped epic key in `{scope_epic_keys}`:
```bash
ls {implementation_artifacts}/epic-{epic_nnn}/*/stories/*.md 2>/dev/null
```
Bind `{story_file_paths}` = full list of story markdown files across all sprints of the scoped epics.

## 3a. Dispatch rule for every spawn in this step

Applies to the reviewers in §4 and the ADR subagents in §6 alike. Bracket each spawn with
`dispatch --event open` / `--event close`, same `--agent <name> --epic {epic_key}
--session-id {session_id}` identity on both, and **close on every exit path** — including a
reviewer that returns BLOCKER findings. Parallel reviewers make this load-bearing: without a
close, a hung reviewer is invisible to `report --stall-minutes` and stalls the whole epic
before any sprint has run.

Include `{agent_contract}` (verbatim — see `steps/shared/step-00-digest.md`) in every spawn prompt.
A `bmad-*` or `l3io-arch-review` subagent loads no part of the activation digest, so a
reviewer that waits for an answer it can never receive is exactly the failure that clause
exists to prevent.

This gate is epic-level work that belongs to no sprint and is not a closure phase, so its
bracketed spend is recorded in the **epic's `orchestration` block**, not in any child's
`actual` (`references/metrics-contract.md` §6).

## 4. Review, escalating only on signal

**Run `l3io-arch-review` first, alone.** Only if it reports a BLOCKER or MAJOR do the other
detected reviewers in `{active_reviewers}` run, in parallel, on the same inputs.

This is not a weakening of the gate, and §5's table is why. A BLOCKER from any reviewer
blocks. A MAJOR from a single reviewer is "flagged (single-source)" and **still blocks**. So
a second and third reviewer cannot change a clean verdict into a blocking one — the only
thing corroboration alters is a label. Running all three every time bought that label at the
price of two more full-epic reads, on the path that is taken most often: the one where the
design is sound.

Escalation keeps what corroboration is actually for. Once something is wrong, a second and
third perspective sharpen severity, catch what the first missed, and turn a single-source
MAJOR into a confirmed one before anybody writes an ADR against it.

Each reviewer receives **a named, bounded set of inputs — never the repository.** A reviewer
left to decide what to read loads the corpus and pays a full `cache_write` over it before its
first thought, then re-reads that prefix on every turn it takes:
- Paths in `{story_file_paths}` (reads from disk)
- Epic goal and scope context
- l3io-pm context preamble (work_type, epic key, sprint plan)
- Reviewer-specific framing:
  - `l3io-arch-review`: invoke as Mode B (architectural review of existing design)
  - `bmad-agent-architect`: architect persona — design coherence, story quality, artifact completeness
  - superpowers: broad software architecture principles, independent of either framework

Each subagent returns a list of findings in format: `{severity}: {finding_text}`.

Bind `{reviewers_run}` = the reviewers that actually ran. The closure report records it, so a
clean gate is distinguishable from a gate that was never widened.

## 5. Consolidate findings (§9.3 rules)

Apply these rules to merge findings across reviewer outputs:

| Finding | Rule |
|---|---|
| BLOCKER from any reviewer | → BLOCKER. Never downgraded. |
| MAJOR from ≥2 reviewers | → MAJOR confirmed. Blocks execution. |
| MAJOR from 1 reviewer | → MAJOR flagged (single-source). Still blocks. |
| MINOR from ≥2 reviewers | → MINOR confirmed. Deferred to issues file. |
| MINOR from 1 reviewer | → Auto-deferred to issues file. Not a gate finding. |

Annotate each consolidated finding with its source reviewer(s).

When only `l3io-arch-review` ran — the clean path — every finding is single-source by
construction, and the rows above still resolve: it raised no BLOCKER and no MAJOR, or §4
would have escalated before reaching here. Any MINORs it found auto-defer exactly as they
would have.

## 6. Gate outcome

**If BLOCKER or MAJOR findings exist:**

Set `{blocking_finding_count}` = the number of consolidated blocking findings from §5
(BLOCKER + MAJOR, after merge — one per ADR, not one per raw reviewer report).

**Reserve every ADR number before you dispatch anything.** Reserve the whole batch in one call
and hand each agent the number it must use:

```bash
python3 {pm_status} adr-reserve --state-root {pm_state_root} --epic {epic_key} \
  --slug arch-gate --count {blocking_finding_count}
```

It prints one zero-padded number per line, in order. Pair them with the findings in that order
— the Nth line is that finding's `{adr_number}` — and pass `{adr_number}` into each finding's
subagent prompt. **Never let an agent choose its own number by listing the directory** — a
listing shows who has finished, not who is in flight. Three parallel agents did exactly that:
two chose 0013 and two chose 0014, and the surviving ADR-0014 was cited by four stories meaning
two different documents.

For each blocking finding, spawn an ADR resolution subagent:
- Read the affected story files
- Draft an ADR at `{implementation_artifacts}/epic-{epic_nnn}/arch/adr-{adr_number}-{slug}.md`
  using the number you were given. Do not derive it, do not list the directory to check it.
- Patch affected story files with technical ACs implied by the ADR decision
- Return: `ADR written: {path}`

After all ADRs are written, re-validate **only what changed**: pass each reviewer the ADRs
written, the specific story-file sections those ADRs patched, and the finding each was
resolving. Ask one question — "does this resolve the finding?" — and nothing else.

Re-running the whole gate to check a patch pays for the entire epic read a second time to
answer a question about a handful of sections. If a reviewer says it cannot judge the patch
without more context, name the additional section; do not widen it back to the epic.

If blocking findings persist after one resolution pass:
```
BLOCKED: arch gate — {N} blocking findings unresolved after ADR resolution.
```

**If MINOR findings only:**

For each MINOR finding, append to issues file:
```bash
python3 {pm_status} append-issue \
  --file {pm_issues_file} \
  --epic {epic_nnn} \
  --sprint "" \
  --title "{finding_text}" \
  --source "arch-gate ({reviewer})" \
  --severity Low
```

`--key` is omitted — `append-issue` allocates `BL-{epic_key}-{nnn}` itself under a lock,
from the highest existing number for this epic; never construct the number here.
Output: `Step 04 complete — findings: 0 blocking, {N} deferred to issues`

**If no findings on non-trivial CODE scope:**

Zero findings on CODE scope is unusual enough to record, and not a reason to stop. Bind
`{file_count}` = the count of `{story_file_paths}` (§3) — a derived value, not a new input —
so a later reader can tell a thin zero-findings review from a thorough one. Write the
observation and continue:

```
NOTE arch gate returned zero findings on CODE scope for {epic_key}.
     Reviewer(s): {reviewers_run}. Scope: {file_count} story files (derived count of
     {story_file_paths}).
     Unusual — if the next sprint surfaces design defects this gate should have caught,
     start here.
```

**Do not prompt.** This step runs under a contract that forbids waiting for an answer that
cannot arrive, and it may run headless or from a dispatched agent. A prompt here hangs the run
on the one path where nothing is wrong.

## 7. Output

```
Step 04 complete — reviewers: {active_reviewers}, blocking: {N}, deferred: {N}
```
