# Sprint Step 02: Story Preparation

Communicate all responses in `{communication_language}`.

Validate and prepare all stories in this sprint for development. Run the acceptance-criteria gate
(business and technical ACs), write estimates, and mark stories ready-for-dev.

## 1. Gate eligibility

The gate runs for `CODE`, `CONFIG` and `MIXED`, and is skipped for `DOCS` (the matrix in
`steps/shared/step-01-classify-work.md` is the authority). `{work_type}` selects the dimension
vocabulary through `references/ac-dimensions.md`. §3 onward run for every work type, and §3 in
particular is what gives a `DOCS` story its `Files in scope` block.

## 2. Technical AC gate

```bash
uv run {pm_status} show --state-root {pm_state_root} --epic {epic_key}
```

Read `{pm_state_root}/{active|planned|archived}/epic-{epic_nnn}/epic.yaml` (wherever
`find_epic_dir` resolves it — normally `active/` at this point in the flow) and bind
`{epic_goal}` from its `goal` field. This is needed for story enrichment prompts below.

For each story key in `{story_keys}`:

Read story file at `{sprint_root}/stories/{story_key}.md`.

Check the story against **every** dimension below, business and technical alike. This is not an any-one-of check. Two different questions are answered about the dimensions, and they have different answers:

- **Which are enriched:** all of them, for every story, whatever `{business}` is. A story missing a business dimension is thin and is enriched.
- **Which can block advancement:** every technical dimension always; the business dimensions (B1, B2) only when the story's `{business}` is `required`. For an `advisory` story a business dimension still missing or unresolved after enrichment is reported and the story proceeds to `ready-for-dev`.

Authoring is unconditional and blocking is configurable: if "not required" also meant "not written", the setting would decay into business ACs that never exist anywhere.


| # | Dimension | Satisfied when the story states… |
|---|---|---|
| B1 | **Outcome** | what a person or the business can do or rely on afterwards, in this epic's vocabulary |
| B2 | **Non-goals** | what this story deliberately does not change |
| 1 | Interface contracts | API signatures, data models, events the story adds or changes |
| 2 | Error and edge case handling | what fails, how it fails, and what the caller sees |
| 3 | Observability requirements | the logging, metrics or tracing the change must emit |
| 4 | Security considerations | auth, validation, and how data is handled |
| 5 | Testability approach | test entry points and mock boundaries |
| 6 | **Existing-library check** | which library or platform capability covers this, or why none does and custom code is warranted |

**Every dimension is either satisfied or explicitly marked not-applicable with a one-line
reason in the story.** "Not applicable" is a legitimate answer — a pure refactor may add no
interface, a background job may face no auth — but it has to be *stated*, because an absent
dimension and an inapplicable one look identical otherwise, and that ambiguity is what let
this gate pass stories carrying one dimension out of six.

That was the defect, and it was silent: this step read "at least one of" while the gate is
documented as blocking on any unfilled *applicable* dimension. A story with interface
contracts and nothing else — no error handling, no observability, no security, no
testability — advanced to `ready-for-dev`. Everything downstream, the dev agent and the code
review both, assumes stories arrive with technical ACs; this gate is the only thing making
that true.

Dimension 6 exists because the cheapest code is the code not written. A story that
hand-rolls retry logic, date parsing, config merging or an HTTP client is a story whose
review, fix loop and long-term maintenance you pay for indefinitely, and none of the other
five dimensions would catch it — they all assume the code *should* exist and only ask
whether it is well specified.

Apply the built-in checklist above. If `l3io-arch-review` is installed, also load
`l3io-arch-review/references/standards-core.md` (plus any overlay matching the story's stack)
and hold the story to those standards as well.

**Business-AC policy (every run, whatever `{spec_alignment}` is).**

Bind `{business_ac_required}` from `modules.l3io-pm.business_ac_required`, default `"CODE,MIXED"`.
Parse it as a comma-separated list, ignoring whitespace around entries and matching
case-insensitively against `CODE`, `DOCS`, `CONFIG`, `MIXED`. An unrecognised entry **halts**
with a message naming the value and the legal set — never drop it silently, because a typo would
otherwise read as "advisory" and disable the gate exactly where someone meant to enable it.

For each story, bind `{business}` = `required` when the story key is in `{ui_facing_stories}`
(bound by `steps/shared/step-01-classify-work.md` and handed to you in the execution context
block; an absent binding means the set is EMPTY — never re-derive it here, because UX review
and this gate must not reach different answers about the same story), else `required` when `{work_type}` is in
`{business_ac_required}`, else `advisory`.

**Provenance (when `{spec_alignment}` is `true`).** Every applicable dimension must also name
the spec section it came from. This is checked mechanically: no model is called, and a fresh
index is not rewritten.

```bash
{spec_align} build --if-stale
```

Because `{business}` is per-story, split the invocation by resolved value rather than passing one
flag for the whole sprint, omitting either line when its set is empty:

```bash
{spec_align} check-pointers --business required --story {each {sprint_root}/stories/{story_key}.md whose {business} is required}
{spec_align} check-pointers --business advisory --story {each {sprint_root}/stories/{story_key}.md whose {business} is advisory}
```

Bind `{spec_index_path}` = `{implementation_artifacts}/spec/spec-index.md`. Exit 0 → every
story carries a resolving `Spec:` line on each applicable dimension. Exit 2 → every story it
names on stderr fails this gate: a missing dimension, a missing or broken `Spec:` line, or no
`## Technical acceptance criteria` section at all. Under `--business required`, a missing
`## Business acceptance criteria` section, a missing `Outcome` or `Non-goals`, or an
unresolving `Outcome` pointer also fail. Under `--business advisory` those are reported on
stderr and do not fail. Add the failing stories to `{thin_story_keys}` below, even if they
passed the dimension check.

**If any business or technical AC check failed (gate: "block" — always enforced):**

Bind `{thin_story_keys}` = every story in `{story_keys}` that failed the check. If it is
empty, go to §3.

Make sure every story in `{thin_story_keys}` has a document before the spawn. `story-doc-init`
creates a missing one from its state node and never touches an existing one:

```bash
uv run {pm_status} story-doc-init --state-root {pm_state_root} \
  --artifacts-root {implementation_artifacts} --story {story_key}
```

**One spawn for the whole sprint, not one per story.** An enrichment agent's cost is
dominated by reading the project — the specs, the architecture, the standards — and that read
is the same whether it then enriches one story or five. Spawning per story pays it per story.
Batching pays it once and is the single largest saving available in this step: a five-story
sprint goes from five cold reads to one. If `{thin_story_keys}` exceeds 8, split into batches
of at most 8 — past that a single agent's attention per story starts to thin, which is the
thing being bought here.

**Resolve the enricher.** Same shape as the dev loop's implementer: BMad 6.12.0 still **ships**
`bmad-create-story`, deprecated to a shim with its full body retained — it is frozen, not gone.
Where it is installed it is still what runs; where it is absent the prompt below is the whole
instruction anyway.

```bash
ls {project-root}/.claude/skills/bmad-create-story/SKILL.md 2>/dev/null \
  || ls {project-root}/.claude/commands/bmad-create-story.md 2>/dev/null \
  || ls ~/.claude/skills/bmad-create-story/SKILL.md 2>/dev/null \
  || ls ~/.claude/commands/bmad-create-story.md 2>/dev/null
```

If a path printed, bind `{enrich_agent}` = the legacy `bmad-create-story` and spawn that skill. <!-- l3io-deprecation-exempt: phase-3 — replaced by a bmad-build overlay; see docs/superpowers/specs/2026-09-20-l3io-customization-layer-design.md §5 Phase 3 -->
If nothing printed, bind `{enrich_agent}` = `l3io-story-enrich` and dispatch it as a general subagent. The instruction below is unchanged either
way, including the batching rule: **one spawn for the whole sprint, not one per story.**

Bracket the spawn with `dispatch --event open` / `--event close`, same
`--agent {enrich_agent} --epic {epic_key} --sprint {sprint_num} --session-id {session_id}`
identity on both, closing on every exit path. The bracket carries no `--story` because the
span covers several.

```
Two things for each story file listed below. Every file exists — the orchestrator created any
missing one with `story-doc-init` before this spawn. Preserve all existing content.

1. Enrich it with business and technical ACs under exactly this layout — both `##` sections
   and all eight `###` headings, in this order. Load `{execute_skill_root}/references/ac-dimensions.md` (`references/ac-dimensions.md` of the execute skill) for
   per-dimension guidance in `work_type`'s vocabulary. A dimension that genuinely does not
   apply is a paragraph starting "N/A — <one-line reason>", never an omitted heading:

   ## Business acceptance criteria

   ### Outcome

   ### Non-goals

   ## Technical acceptance criteria

   ### Interface contracts

   ### Error and edge case handling

   ### Observability requirements

   ### Security considerations

   ### Testability approach

   ### Existing-library check

   *(End of layout — the instructions continue below; they are directed at the enriching agent, not story content.)*

   `Outcome` ends with a resolving `Spec:` line like the technical dimensions; `Non-goals`
   takes no pointer.

   Before writing technical ACs, list the files the story will add or change, inspect their
   existing siblings, and record any convention a new file must follow.

   The existing-library check names the library or platform capability that covers this
   work, or states why none does and custom code is warranted. Do not propose hand-written
   code for a problem a maintained library already solves.

   Provenance (only when spec_alignment is true): end every applicable dimension with one or
   more `Spec: <path>#<anchor>` lines copied from the spec index at {spec_index_path} — cite
   the section, never copy its text — or with exactly one `Spec: none — <reason>` when no
   spec section covers it (`Spec: none — no spec docs in this project` when the index is
   empty). Open only the index and the sections you cite.

2. Write a `## Files in scope` section into the document — you are reading the project to
   do (1), so you are the cheapest place in the whole run to answer this. Repo-relative
   paths, one line of why each:

   ## Files in scope

   - `src/foo/bar.py` — the module this story changes
   - `src/foo/baz.py` — its only caller; signature change lands here
   - `tests/foo/test_bar.py` — the suite that must stay green

   Best effort is the right standard: the list is a starting point, not a fence. If the
   story already has such a section, correct it rather than adding a second one.

Treat each story on its own terms — shared context is why these are batched, but a story
that needs a different interface contract from its neighbour must get one.

Story files (do both for every one):
{one {sprint_root}/stories/{story_key}.md per line, for each key in {thin_story_keys}}
Epic goal: {epic_goal}
work_type: {work_type}
spec_alignment: {spec_alignment}
Spec index: {spec_index_path}
{agent_contract}
```

Attribution: the span enriched `len({thin_story_keys})` stories, so split its spend evenly
across their `actual` blocks (`references/metrics-contract.md` §6). The even split is an
approximation and is meant to be — the alternative is paying N project reads to measure a
number that feeds calibration as a ratio, and prep cost does scale roughly with story count.

After enrichment, re-check every key in `{thin_story_keys}` against every dimension — and,
when `{spec_alignment}` is `true`, rerun the `check-pointers` split above over those
story files (exit 2 is a failure). For any still carrying an unfilled applicable technical dimension, a failing pointer, or —
only when its `{business}` is `required` — an unfilled business dimension:
```
BLOCKED: story {story_key} still missing required acceptance criteria after elaboration. Investigate manually.
```

For an `advisory` story whose business dimension is still unfilled, do not block: note it in
the step output and continue.

## 3. Every story carries a `Files in scope` block

**This runs on every path and for every work type** — for stories that were never thin, for
stories §2 just enriched, and for `DOCS` stories, which skip §2 and still get this block.
It is the only step that guarantees the block exists, and `steps/sprint/step-03-dev-loop.md`
§2 hands it to the dev agent unconditionally and reports a story-prep defect when it is
missing. Anything less than "every story" here produces that defect report on the common
path, which is the steady state, not the exception.

Why it is worth a pass of its own: the dev agent receives the block verbatim and starts
there instead of discovering the shape of the work by reading around it. The measured spread
was 19k to 138k tokens read per file changed, on stories of comparable size, and that spread
is the largest uncontrolled cost in a run.

For each story key in `{story_keys}`, read `{sprint_root}/stories/{story_key}.md` and check
for a `## Files in scope` heading. Bind `{no_scope_keys}` = every key whose document has
none.

If `{no_scope_keys}` is empty, go to §4 — §2's enrichment already wrote them, or a previous
run did.

Otherwise **one spawn for the whole set, not one per story**, for the same reason §2 batches:
the cost is dominated by reading the project, and that read is the same whether the agent
then scopes one story or five. Split into batches of at most 8. Bracket the spawn with
`dispatch --event open` / `--event close`, same
`--agent {enrich_agent} --epic {epic_key} --sprint {sprint_num} --session-id {session_id}`
identity on both, closing on every exit path; no `--story`, the span covers several.

Send the *same* instruction 2 and example block as §2's prompt above — verbatim, including
the repo-relative-paths and best-effort wording — with these story files, plus
`work_type: {work_type}` and `{agent_contract}`:

```
{one {sprint_root}/stories/{story_key}.md per line, for each key in {no_scope_keys}}
```

Do **not** send instruction 1: these stories passed the AC gate, and re-enriching them would rewrite ACs nobody asked to change.

If a story's scope genuinely cannot be determined — a spike, or work whose files are chosen
during implementation — the agent still writes the heading and says so in one line under it
(`- To be determined during implementation: <why>`). An empty-but-present block is a
deliberate answer the dev can read; an absent one is indistinguishable from prep having
failed, which is exactly the ambiguity this section removes.

Attribution: split the span's spend evenly across the `actual` blocks of the stories it
scoped (`references/metrics-contract.md` §6), as for §2's span.

## 4. Write story estimates

For each story in `{story_keys}` that does not already have an `estimate` block:

Read classification from story file (`classification: simple|standard|complex`).

The model's only job is supplying the classification — `estimate-story` does the rest: it
looks up the cold-start base band (or the calibrated per-metric scope ratio once a metric has
≥3 samples), applies the classification's fix factor, and derives `cost` from the resulting
`tokens_k` and `--model`. **Do not hand-compute the base bands or ratios here** — they live in
`BASE_BANDS` inside `pm-status.py`, not in this file, and a re-derivation here can drift from
what `estimate-story` actually applies. See `references/metrics-contract.md` §6.

```bash
uv run {pm_status} estimate-story \
  --state-root {pm_state_root} \
  --story {story_key} \
  --classification {simple|standard|complex} \
  --model {model} \
  [--token-rates '{token_rates_json}'] \
  [--confidence {low|medium|high}]
```

`{model}` and `{token_rates_json}` are bound at activation (`step-00-activate.md` §1). Pass
`--model` always; add `--token-rates` only when `{token_rates_json}` is non-empty.

## 5. Mark stories ready-for-dev

For each story in `{story_keys}` with `status: backlog`:

```bash
uv run {pm_status} set-status \
  --state-root {pm_state_root} \
  --story {story_key} \
  --status ready-for-dev
```

Keep the story document in step with the state — the state YAML is what the machine reads and
this file is what a reviewer opens, and they have not agreed until now:

```bash
uv run {pm_status} sync-story-doc --artifacts-root {implementation_artifacts} \
  --story {story_key} --status ready-for-dev
```

This never fails: a missing or frontmatter-less document warns on stderr and returns 0, because
the state transition it follows is already durable and must not be rolled back by a
documentation write.

## 6. Output

```
Sprint Step 02 complete — stories prepared: {N}, estimates written: {N}, blocked: {N}
```
