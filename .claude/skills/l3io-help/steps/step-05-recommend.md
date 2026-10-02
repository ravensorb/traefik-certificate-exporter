### 5. Recommend next action

Section 2 has already terminated with its own recommendation on the legacy, multi-layout,
and orphan branches — this table is only reached when the sharded layout is the only one
present, or on a verified genuine first run. Apply the first matching rule:

| Condition | Recommendation |
|---|---|
| No state files, no epics (**only after section 2's first-run check passed**) | `Run bmad-create-epics-and-stories to create your project backlog first.` |
| No plan-output-meta.yaml | `Run /l3io-plan to validate readiness and build the execution plan.` |
| plan readiness = red | `Run /l3io-plan to resolve readiness gaps (readiness: red).` |
| plan readiness = amber | `Run /l3io-plan to address readiness warnings (readiness: amber), or /l3io-execute to proceed.` |
| Any epic has stale lock | `Epic {key} has a stale lock (claimed {N}m ago). Run: uv run {pm_status} clear-lock --state-root {pm_state_root} --epic {key}` |
| Active epic, no BLOCKED sprint | `Run /l3io-execute {key} to continue the in-progress epic.` |
| No active epics, plan exists, planned epics available | `Run /l3io-execute to start execution (plan is green).` |
| All epics done (active + planned = 0) | `All work complete. Run /l3io-sync to push closure to GitHub/ADO.` |

**One more follow-up, checked after the table above:** if `{pm_status_present}` is `absent`,
prepend it to the recommendation — this takes priority because it explains a failure the user
would otherwise hit with no clue why:
`pm-status.py is missing at {project-root}/_bmad/scripts/pm-status.py. Run /l3io-doctor
first to install it — this report read epic.yaml directly instead.`

**Second follow-up, checked after the absent-warning above:** if `{pm_status_stale}` is `yes`,
prepend a stale warning after the absent warning (or first if no absent warning fired):
`pm-status.py at {project-root}/_bmad/scripts/pm-status.py is stale — the installed copy is
behind the shipped version. Run /l3io-doctor to refresh it (its activation self-install
picks up the current copy).`

If `{pm_status_stale}` is `unknown`, prepend:
`Note: l3io-doctor is not installed here, so pm-status.py freshness could not be checked.
It is a required module of this extension — see docs/l3io-util-reference.md.`

**Third follow-up, checked after the pm-status warnings:** if `check-deps`'s JSON output at
activation reported any entry under `related_present` (bmad-loop, bmad-loop-setup,
bmad-loop-sweep, bmad-loop-resolve, or bmad-build-auto not in a role we dispatch), append one
paragraph after the recommendation, verbatim:

`Note: bmad-loop is installed alongside l3io-pm. Both drive an unattended dev loop.
l3io-execute covers epic + sprint orchestration with phased parallel execution,
calibrated estimates, and quality-gated closure across multiple stories; bmad-loop is a
lighter single-loop pass around bmad-build-auto with an integrated review. The two state
trees are independent, so you can run either without the other. See
docs/l3io-pm-reference.md §Relationship to bmad-loop for when to use which.`

The `related_present` list is derived from `l3io-doctor check-deps --format json` at
activation and passed through in `{related_installed}`. When the doctor is absent this note is
omitted (the `pm_status_stale` unknown branch already tells the user the doctor is missing).

One of the strings above is also inlined elsewhere so that path does not need to load this
file: this `pm_status_present` warning in `steps/mode-list-plan.md`. Keep both copies in
sync if it changes. (The stale-lock recommendation used to be inlined a second time, in
`steps/mode-progress.md` — that mode now forwards to `/l3io-doctor stats` instead of
reading state itself, so its own copy of the stale-lock row is gone; the remedy lives on in
`skills/l3io-doctor/steps/stats.md`, a cross-skill duplication noted there. `check:docs`
check 4 validates each copy's subcommand and flags against the real CLI; it does not compare
the copies to each other.)

Output the recommendation as a clear, one-paragraph response with the exact command to run.

