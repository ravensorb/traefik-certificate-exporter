# Step 01: Classify Work Type

Communicate all responses in `{communication_language}`.

Run after step-00-activate. Determines `{work_type}` for all in-scope epics/stories
before any orchestration begins. `{work_type}` is carried in all subsequent step
instructions and every headless subagent prompt.

---

## Classification rules

Examine the stories in scope (those in the active epics or the epics being planned):

| Type | Condition |
|------|-----------|
| `CODE` | At least one story has implementation ACs (code changes, APIs, services, data model) |
| `DOCS` | All stories are documentation only (no code or infrastructure changes) |
| `CONFIG` | All stories are infrastructure, CI/CD, configuration, or IaC only |
| `MIXED` | Stories span more than one type (e.g. both CODE and DOCS stories in same scope) |

## Classification procedure

1. For each in-scope story (read from story files in `{implementation_artifacts}` or from
   the status file if story files are absent):
   - Read the story's `classification` field if present. Classifications are:
     - `simple`, `standard`, `complex` → these describe sizing, not type. Read the story's
       Acceptance Criteria to determine type.
   - If the story file exists, read its "Acceptance Criteria" section.
   - Assign a type: CODE, DOCS, CONFIG, or MIXED (a single story can be MIXED if its ACs
     span multiple types).

2. Aggregate across all in-scope stories:
   - All DOCS → `{work_type}` = DOCS
   - All CONFIG → `{work_type}` = CONFIG
   - Mix of CODE + anything else → `{work_type}` = MIXED
   - Any CODE (even one story) → `{work_type}` = CODE (if rest are also CODE or unclassified)
   - Unclassifiable stories (no ACs at all) → treat as CODE (conservative default)

3. Bind `{work_type}` for all subsequent steps.

3a. Bind `{ui_facing_stories}` = the set of story keys whose ACs change something a person
   directly perceives: rendered UI, CLI output a person reads, user-facing copy or error
   text, or an API response a UI consumes. The test is whether a person would notice the
   change without reading logs, and it is about the **consumer, not the layer or the format**:
   - A backend rule that changes a displayed error message IS UI-facing — a person perceives
     the effect, whichever layer implements it.
   - Output consumed only by another program (machine-read logs, flags, JSON) is NOT.
   - Infrastructure that merely *serves* a UI is not UI-facing.
   - If the story does not say whether a UI or a person consumes the output, do not guess
     about callers — apply the default below.
   - **Default: when unclear, INCLUDE the story.** A false positive costs one extra UX check
     and one business-AC requirement; a false negative silently skips review on a story a
     user can see. A story with no ACs is CODE by this step's conservative default and is
     likewise included.
   - Examples: a pipeline change that alters the failure message a developer reads in CI
     output is UI-facing; an IAM role scope change with no human-visible surface is not.
   Bind it here, once, for the same reason `{skip_phases}` is bound here once: UX review and
   the business-AC gate must not reach different answers about the same story. Do not store
   it on the state node — it is derived from a story's ACs, and a stored copy drifts the
   moment the story is enriched.

4. Compute `{skip_phases}` from the phase matrix below.

**This matrix is the single source of truth for phase gating.** No other step file computes
`{skip_phases}` — `step-05-epic-loop.md` passes through what is bound here, and
`closure/sprint-closure.md` skips whatever this names. If you are about to recompute it
somewhere else, that is the bug this table exists to prevent.

**Two mechanisms, and the difference matters.** Rows marked `{skip_phases}` are skipped by
being named in that binding. Rows marked with a step file are gated by a `{work_type}` check
inside that step and never appear in `{skip_phases}` at all. Do not migrate the second kind
into the first: a malformed `{skip_phases}` string would silently disable a gate, whereas a
`{work_type}` check cannot be turned off by a typo.

**Governing principle.** A phase is skipped by `{work_type}` only when that work type means
the phase has **no subject matter at all** — true of `DOCS` alone. Everything else gates on
its own applicability signal (an installed check, UI-facing stories), never on the work type.
IaC and CI/CD are where IAM misconfiguration, secret handling, blast radius and supply-chain
compromise live, so red team and the arch gate are *more* applicable to infrastructure than
to typical app code, not less.

This resolves a standing contradiction: **sprint** architectural drift ran for `CONFIG` while
**epic** architectural drift skipped — the same concern, the same work type, opposite answers,
with no principle separating them.

UX review is `run` for `CONFIG` not because infra epics need it, but because it is already
gated on UI-facing stories independently of work type (`{ui_facing_stories}`, bound above), so
that check is the operative one. Leaving the cell `skip` would make `CONFIG` a second
suppressing type and contradict the principle. An infra story still gets no UX review —
decided now by the signal that actually means it.

| Phase | CODE | DOCS | CONFIG | MIXED | Enforced by |
|---|---|---|---|---|---|
| Retrospective | run | run | run | run | always runs |
| Clean release review | run | skip | run | run | `{skip_phases}` |
| Adversarial analysis | run | skip | run | run | `{skip_phases}` |
| Red team (`l3io-sec`) | run | skip | run | run | `{skip_phases}` + installed check |
| UX review | run | skip | run | run | `{skip_phases}` + installed check + UI-facing stories |
| Sprint architectural drift | run | skip | run | run | `{skip_phases}` + installed check |
| Issue triage | run | run | run | run | always runs |
| Story technical-AC gate | run | skip | run | run | `{work_type}` at `l3io-execute/steps/sprint/step-02-story-prep.md` |
| Epic arch gate | run | skip | run | run | `{work_type}` at `l3io-execute/steps/execute/step-04-arch-gate.md` |
| Epic architectural drift | run | skip | run | run | `{work_type}` at `l3io-execute/steps/closure/epic-closure.md` |
| Epic security review (`l3io-sec`) | run | skip | run | run | `{work_type}` at `l3io-execute/steps/closure/epic-closure.md` + installed check |

Bind `{skip_phases}` = comma-separated list of the `{skip_phases}`-enforced phase names that
this `{work_type}` column marks `skip` (empty if none). Rows whose *Enforced by* is a step
file, or "always runs", are never included.

For `{work_type}` = CODE, CONFIG or MIXED, `{skip_phases}` is empty unless an installed check fails.

5. Bind `{max_fix_iterations}` from `{work_type}`:

| `{work_type}` | Binding |
|---|---|
| CODE, MIXED | `max_fix_iterations` (default 3) |
| DOCS, CONFIG | `max_fix_iterations` (default 3) — same cap (a DOCS run has no fix-loop phase to bound; CONFIG runs them) |

It comes from the resolved `customize.toml` `[workflow]` table.

> There used to be a separate `max_fix_iterations_non_code`. It was doubly inert: it held the
> same value, AND every phase containing a fix loop was then skipped for DOCS and CONFIG
> work, so it had nothing to bound either way. (Historical: CONFIG now runs those phases, so
> only DOCS still has nothing to bound; the removal stands because the value was identical.) It was removed rather than documented, because
> it was user-settable in four `customize.toml` files and therefore invited tuning that could
> not do anything. This one integer is the cap for
**every** fix loop in the run — per-story in the dev loop, and at sprint and epic closure.
A ten-iteration autonomous fix loop is proportionate to a broken API contract and wildly
disproportionate to a typo, which is why it follows the work type.

To check if a skill is installed — query the installer's module manifest, never a config
section. A module can be installed and carry no config at all, so a config lookup reports a
present module as absent and the phase silently self-skips. See
`references/config-resolution.md` §6.

For `l3io-arch-review` (module code `l3io-arch`) and `l3io-sec-redteam` (module code
`l3io-sec`), run with the module code substituted:

```bash
grep -qE "^[[:space:]]*-[[:space:]]*name:[[:space:]]*l3io-arch[[:space:]]*$" \
  {project-root}/_bmad/_config/manifest.yaml 2>/dev/null && echo "present" || echo "absent"
```

## Output

Report the classification result:

```
Work type: {work_type}
UI-facing stories: {count of {ui_facing_stories}} of {count of in-scope stories}
Skipping phases: {skip_phases or "(none)"}
Max fix iterations: {max_fix_iterations}
Rationale: [one sentence explaining the dominant story type]
```

Then continue to the next step.
