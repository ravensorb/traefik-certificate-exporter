### 3. Read state files

```bash
ls -d {pm_state_root}/active/epic-*/ 2>/dev/null || echo "(none)"
ls -d {pm_state_root}/planned/epic-*/ 2>/dev/null || echo "(none)"
uv run {pm_status} list-issues --state-root {pm_state_root} --all --format json 2>/dev/null \
  || cat {pm_issues_file} 2>/dev/null || echo "(absent)"
cat {planning_artifacts}/plan-output-meta.yaml 2>/dev/null || echo "(absent)"
```

For each active/planned epic directory found, read its `epic.yaml` directly (key, title,
status, `_lock`, `depends_on`). If `{pm_status_present}` is `present`, you may instead use
`uv run {pm_status} show --state-root {pm_state_root} --epic {key}` for a computed roll-up
including sprint/story counts. If it is `absent`, use the direct read only.

Also surface one read-only health fact — state that is gitignored will never be committed,
which defeats the point of the layout:

```bash
git -C {project-root} check-ignore -q {pm_state_root} && echo IGNORED || echo TRACKED
```

If `IGNORED`, include this in the snapshot (it does not stop the recommendation):
```
⚠️  {pm_state_root} is gitignored — project state will not be committed. Add to .gitignore:
  !{pm_state_root}/
  !{pm_state_root}/**
```

