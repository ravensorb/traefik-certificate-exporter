# Step 03: Story Elaboration

Communicate all responses in `{communication_language}`.

This step is **skipped** when `{work_type}` is DOCS or CONFIG (the SKILL.md router does not load it).
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

From `{planning_artifacts}/readiness-report.md`, extract all stories with an Amber "Technical ACs" finding.

For each thin story, record: `key`, `title`, the path to its story file (`{implementation_artifacts}/epic-{nnn}/sprint-{nn}/stories/{story_key}.md`).

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

Bracket each batch with `dispatch --event open` / `--event close`, same
`--agent bmad-create-story --epic {epic_key} --session-id {session_id}` identity on both,
closed on every exit path, so a hung elaboration shows up in `report --stall-minutes` rather
than at invoice time. Planning spend sits outside the execution roll-up, so the bracket here
is for stall detection only — there is no bucket to attribute it to.

Spawn `bmad-create-story` with:
- Every thin story file path in the batch, as input artifacts to enrich in place
- Instruction to add technical ACs to **each** story, covering: interface contracts, data
  model changes, error handling and edge cases, observability requirements, security
  considerations, testability (unit + integration test anchors) — treating each story on its
  own terms rather than applying one answer across the batch
- Context preamble: `epic_key: {epic_key}`, `work_type: {work_type}`, `skill: l3io-pm-plan`
- `{agent_contract}` (verbatim — see `steps/shared/step-00-digest.md`)

Issue the next batch only after the previous one has returned. That is sequencing, not waiting
on a reply — nothing is ever awaited from a subagent that has not returned.

Record result: `elaborated` or `failed` (if bmad-create-story is not installed or errors).

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
| E001-S01-002 | ✅ Elaborated | Technical ACs added (interfaces, error handling, observability) |
| E002-S01-001 | ❌ Failed | bmad-create-story not installed |
```

## 7. Output status line

```
Step 03 complete — elaborated: {elaborated_count}, failed: {failed_count}, readiness after: {readiness}
```
