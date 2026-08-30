# Sprint Step 02: Story Preparation

Communicate all responses in `{communication_language}`.

Validate and prepare all stories in this sprint for development. Run the technical AC gate,
write estimates, and mark stories ready-for-dev.

## 1. Gate eligibility

Skip the technical AC gate (proceed to §3) if `{work_type}` is `DOCS` or `CONFIG`.
Only §2 is skipped — §3 onward run for every work type, and §3 in particular is what
gives a `DOCS`/`CONFIG` story its `Files in scope` block.

## 2. Technical AC gate

```bash
python3 {pm_status} show --state-root {pm_state_root} --epic {epic_key}
```

Read `{pm_state_root}/{active|planned|archived}/epic-{epic_nnn}/epic.yaml` (wherever
`find_epic_dir` resolves it — normally `active/` at this point in the flow) and bind
`{epic_goal}` from its `goal` field. This is needed for story enrichment prompts below.

For each story key in `{story_keys}`:

Read story file at `{sprint_root}/stories/{story_key}.md`.

Check the story against **every** dimension below. This is not an any-one-of check:

| # | Dimension | Satisfied when the story states… |
|---|---|---|
| 1 | Interface contracts | API signatures, data models, events the story adds or changes |
| 2 | Error and edge cases | what fails, how it fails, and what the caller sees |
| 3 | Observability | the logging, metrics or tracing the change must emit |
| 4 | Security | auth, validation, and how data is handled |
| 5 | Testability | test entry points and mock boundaries |
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

**If technical ACs are missing (gate: "block" — always enforced):**

Bind `{thin_story_keys}` = every story in `{story_keys}` that failed the check. If it is
empty, go to §3.

**One spawn for the whole sprint, not one per story.** An enrichment agent's cost is
dominated by reading the project — the specs, the architecture, the standards — and that read
is the same whether it then enriches one story or five. Spawning per story pays it per story.
Batching pays it once and is the single largest saving available in this step: a five-story
sprint goes from five cold reads to one. If `{thin_story_keys}` exceeds 8, split into batches
of at most 8 — past that a single agent's attention per story starts to thin, which is the
thing being bought here.

Bracket the spawn with `dispatch --event open` / `--event close`, same
`--agent bmad-create-story --epic {epic_key} --sprint {sprint_num} --session-id {session_id}`
identity on both, closing on every exit path. The bracket carries no `--story` because the
span covers several.

```
Two things for each story file listed below. Preserve all existing content in every file.

1. Enrich it with technical ACs, addressing ALL SIX dimensions, marking any that genuinely
   do not apply as "N/A — <one-line reason>" rather than omitting them:
   - Interface contracts
   - Error and edge case handling
   - Observability requirements
   - Security considerations
   - Testability approach
   - Existing-library check: name the library or platform capability that covers this work,
     or state why none does and custom code is warranted. Do not propose hand-written code
     for a problem a maintained library already solves.

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
{agent_contract}
```

Attribution: the span enriched `len({thin_story_keys})` stories, so split its spend evenly
across their `actual` blocks (`references/metrics-contract.md` §6). The even split is an
approximation and is meant to be — the alternative is paying N project reads to measure a
number that feeds calibration as a ratio, and prep cost does scale roughly with story count.

After enrichment, re-check every key in `{thin_story_keys}` against all six dimensions. For
any still carrying an unfilled applicable dimension:
```
BLOCKED: story {story_key} still missing technical ACs after elaboration. Investigate manually.
```

## 3. Every story carries a `Files in scope` block

**This runs on every path and for every work type** — for stories that were never thin, for
stories §2 just enriched, and for `DOCS`/`CONFIG` sprints that skipped §2 altogether at §1.
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
`--agent bmad-create-story --epic {epic_key} --sprint {sprint_num} --session-id {session_id}`
identity on both, closing on every exit path; no `--story`, the span covers several.

Send the *same* instruction 2 and example block as §2's prompt above — verbatim, including
the repo-relative-paths and best-effort wording — with these story files, plus
`work_type: {work_type}` and `{agent_contract}`:

```
{one {sprint_root}/stories/{story_key}.md per line, for each key in {no_scope_keys}}
```

Do **not** send instruction 1: these stories either passed the AC gate or were never subject
to it, and re-enriching them would rewrite ACs nobody asked to change.

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
python3 {pm_status} estimate-story \
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
python3 {pm_status} set-status \
  --state-root {pm_state_root} \
  --story {story_key} \
  --status ready-for-dev
```

Keep the story document in step with the state — the state YAML is what the machine reads and
this file is what a reviewer opens, and they have not agreed until now:

```bash
python3 {pm_status} sync-story-doc --artifacts-root {implementation_artifacts} \
  --story {story_key} --status ready-for-dev
```

This never fails: a missing or frontmatter-less document warns on stderr and returns 0, because
the state transition it follows is already durable and must not be rolled back by a
documentation write.

## 6. Output

```
Sprint Step 02 complete — stories prepared: {N}, estimates written: {N}, blocked: {N}
```
