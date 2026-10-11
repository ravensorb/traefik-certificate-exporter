# Step 03: Story Elaboration

Communicate all responses in `{communication_language}`.

This step runs for every work type. `{work_type}` selects the dimension **vocabulary** the enricher uses, not whether the step runs — see `references/ac-dimensions.md`.
This step is a **no-op** when `{readiness}` is green (no technical AC gaps found).

---

## 1. Check elaboration condition

If `{readiness}` is `green` (no technical AC gaps):

Bind `{elaborated_count}` = 0 and `{failed_count}` = 0.

```
Step 03 skipped — all stories have technical ACs.
```

Skip to step 7 (output status line).

## 2. Identify thin stories

From `{planning_artifacts}/readiness-report.md`, extract all stories with an Amber finding on
**either** "Technical ACs" **or** "Business ACs".

Both rows, not just the technical one. §4 below writes `## Business acceptance criteria` and
`## Technical acceptance criteria` in the same pass, so a story thin in either section is work
for this step. Matching only "Technical ACs" would let a story whose business outcome is missing
be reported by step 02 and then elaborated by nobody — a finding that appears in every readiness
report and never clears, which is worse than not having checked.

That set includes stories whose document **does not exist yet** — step 02 grades an absent document Amber precisely so it reaches this step, because §4 below is the only place that creates one. Do not filter them out for having no file to read: a missing file is the input §4 is written for, not a malformed finding.

For each thin story, record: `key`, `title`, the path to its story file (`{implementation_artifacts}/epic-{nnn}/sprint-{nn}/stories/{story_key}[-{slug}].md` — bare canonical or with optional trailing slug; both shapes are accepted by every reader).

## 3. Confirm with user (unless auto_elaborate = true)

If `{auto_elaborate}` is `false`, present:

```
📝 {count} stories need technical AC elaboration before arch review:

{list of story keys and titles}

Elaborate now? (Recommended — elaborated stories give the arch gate full technical designs.)
Type 'yes' to proceed, 'skip' to continue without elaborating.
```

If user types `skip`, go to step 7 (output status line without elaborating).

If `{auto_elaborate}` is `true`, proceed directly to step 4 without prompting.

## 4. Elaborate the thin stories

```
Elaborating {N} thin stories...
```

**One spawn per epic's worth of thin stories, not one per story** — and this step is where
that matters most, because planning runs across the whole backlog at once. An elaboration
agent's cost is dominated by reading the project, and that read is identical whether it then
enriches one story or twelve. Batch in groups of at most 8; past that a single agent's
attention per story thins out.

**Resolve the enricher.** Same shape as the dev loop's implementer.

```bash
ls {project-root}/.claude/skills/bmad-create-story/SKILL.md 2>/dev/null \
  || ls {project-root}/.claude/commands/bmad-create-story.md 2>/dev/null \
  || ls ~/.claude/skills/bmad-create-story/SKILL.md 2>/dev/null \
  || ls ~/.claude/commands/bmad-create-story.md 2>/dev/null
```

A path printed → `{enrich_agent}` = the legacy `bmad-create-story`. <!-- l3io-deprecation-exempt: phase-3 — replaced by a bmad-build overlay; see docs/superpowers/specs/2026-09-20-l3io-customization-layer-design.md §5 Phase 3 --> Nothing printed →
`{enrich_agent}` = `l3io-story-enrich`, dispatched as a general subagent. The instruction below is unchanged either
way, including the batching rule above: **one spawn per epic's worth of thin stories, not one per story.**

Bracket each batch with `dispatch --event open` / `--event close`, same
`--agent {enrich_agent} --epic {epic_key} --session-id {session_id}` identity on both,
closed on every exit path, so a hung elaboration shows up in `report --stall-minutes` rather
than at invoice time. Planning spend sits outside the execution roll-up, so the bracket here
is for stall detection only — there is no bucket to attribute it to.

Spawn `{enrich_agent}` with:
- Every thin story file path in the batch. Before the spawn, make sure every story has a
  document — `story-doc-init` creates a missing one from its state node and never touches an
  existing one. Run it once per story:
  ```bash
  uv run {pm_status} story-doc-init --state-root {pm_state_root} \
    --artifacts-root {implementation_artifacts} --story {story_key}
  ```
- Instruction to enrich **each** story under exactly this layout, in this order, treating each
  story on its own terms rather than applying one answer across the batch:

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

*(End of layout — the spawn instructions continue below; they are directed at the enriching agent, not story content.)*

- Tell the enriching agent, before writing technical ACs, to list the files the story will add or change, inspect their existing siblings, and record any convention a new file must follow.
- Tell the enriching agent to load `{skill-root}/references/ac-dimensions.md` (the skill's `references/ac-dimensions.md`,
  rooted so the agent can find it) for per-dimension guidance in this epic's vocabulary.
  `spec_alignment` and `spec_paths` are `l3io-execute` keys only and `l3io-plan` passes no spec
  index, so in plan mode `Spec: none — <reason>` is the expected answer for every applicable
  dimension; only when `{spec_alignment}` is bound and true do you also pass the index path
  and require resolving `Spec: <path>#<anchor>` lines. `Non-goals` takes no pointer. A
  dimension that does not apply is marked `N/A — <reason>`, never omitted.
- Context preamble: `epic_key: {epic_key}`, `work_type: {work_type}`, `skill: l3io-plan`
- `{agent_contract}` (verbatim — see `steps/shared/step-00-digest.md`)

Issue the next batch only after the previous one has returned. That is sequencing, not waiting
on a reply — nothing is ever awaited from a subagent that has not returned.

Record result: `elaborated` or `failed` (if `{enrich_agent}` errors).

## 5. Re-run readiness on updated stories

After all stories are processed, re-run the Technical ACs check from step-02 on the elaborated stories only. Update `{readiness}`:

- All previously-amber stories now green → `{readiness}` = `green` (or `amber` if non-AC gaps remain)
- Any story still lacking technical ACs → keep `{readiness}` = `amber`

## 6. Write elaboration-summary.md

Write `{planning_artifacts}/elaboration-summary.md`:

```markdown
# Elaboration Summary

Generated: {timestamp}
Stories elaborated: {elaborated_count}
Stories failed: {failed_count}

## Results

| Story | Result | Notes |
|-------|--------|-------|
| E001-S01-002 | ✅ Elaborated | Business ACs (outcome, non-goals) and technical ACs (interfaces, error handling, observability) added |
| E002-S01-001 | ❌ Failed | enrichment agent returned an error |
```

## 7. Output status line

```
Step 03 complete — elaborated: {elaborated_count}, failed: {failed_count}, readiness after: {readiness}
```
