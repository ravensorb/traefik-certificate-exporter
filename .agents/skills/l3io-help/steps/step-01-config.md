### 1. Load paths from config

Resolve config through BMad core's resolver — full contract in
`{skill-root}/references/config-resolution.md`:

```bash
uv run --python 3.11 {project-root}/_bmad/scripts/resolve_config.py --project-root {project-root}
```

If the resolver is missing or fails, BMad core is not installed here — stop and tell the
user to run the BMad installer. Extract, applying the default when a key is absent:

- `{output_folder}` — `core.output_folder` (default `{project-root}/_bmad-output`)
- `{implementation_artifacts}` — `modules.l3io-pm.implementation_artifacts`
  (default `{output_folder}/implementation-artifacts`)
- `{planning_artifacts}` — `modules.l3io-pm.planning_artifacts`
  (default `{output_folder}/planning-artifacts`)
- Set `{pm_state_root}` = `{implementation_artifacts}/state`
- Set `{pm_issues_file}` = `{pm_state_root}/issues.yaml`
- Set `{pm_status}` = `{project-root}/_bmad/scripts/pm-status.py` (self-installed by the
  other PM skills; l3io-help only reads, it does not self-install)

Then check whether `{pm_status}` is actually on disk and bind `{pm_status_present}`:

```bash
[ -f {project-root}/_bmad/scripts/pm-status.py ] && echo present || echo absent
```

When `{pm_status_present}` is `present`, also check whether it is current. The doctor owns
this comparison (its `module_version` is the source of truth for the shipped version at this
extension level). Invoke `skill:l3io-doctor` with `check-pm-status`, capture its exit
code, and bind `{pm_status_stale}`:

- Exit 0 → `no` (current)
- Exit 3 → `yes` (stale)
- Exit 4 → `no` (absent — already caught above; treat here as `no` to avoid double warning)

If `l3io-doctor` is not installed here, bind `{pm_status_stale}` to `unknown` and
continue. `l3io-doctor` is a required module of this extension (see `CLAUDE.md`
Dependencies), so `unknown` is an install anomaly the report should surface, not a normal
state.

Also — when `l3io-doctor` IS installed here — run its dependency inventory to see whether
this project has adjacent tooling worth naming in the report. `check-deps` reports skills we
detect but do not dispatch (bmad-loop is the shape) in its `related_present` array:

```bash
skill:l3io-doctor check-deps --format json
```

Bind `{related_installed}` to the comma-joined list of `related_present[*].name` in that JSON
output, or the empty string when the array is empty or the doctor is absent. Step-05 uses this
to decide whether to append the overlap note.

**Never invoke `{pm_status}` when it is absent.** On a fresh install nothing has
self-installed it yet, so every `{pm_status}` call below is conditional: when
`{pm_status_present}` is `absent`, read each `epic.yaml` directly instead (it is plain YAML).

Note in the report, when absent:

```
pm-status.py not installed yet — reading epic.yaml files directly. Run /l3io-doctor to
install it (l3io-help only reads; it does not self-install).
```

Not a hard blocker: everything l3io-help needs can still be read.

