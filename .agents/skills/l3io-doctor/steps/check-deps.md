# check-deps — verify BMad dependencies

Invoked with `check-deps`. **Read-only.** Reports which BMad skills this package needs, which
resolved, and which deprecated shims are still being used.

## 1. Run the verifier

```bash
uv run {skill-root}/scripts/bmad-deps.py verify --project-root {project-root}
```

## 2. Report

Print the output as-is. Then:

- Exit 0, nothing absent → `DONE — all BMad dependencies resolve.`
- Exit 0 with `absent` lines → `DONE — <n> optional dependency(ies) absent; their phases
  self-skip.` Name them, so a self-skipped gate is never mistaken for a passed one.
- Exit 0 with `shim` lines → `DONE — <n> deprecated shim(s) in use.` These work today and are
  removed at BMad v7; recommend upgrading the install.
- Exit 3 → `BLOCKED: <n> required BMad skill(s) resolve nowhere.` Print the remedy the script
  printed.
- Exit 4 → `BLOCKED: BMad is not installed here, or its manifest is unreadable.`
- Exit 2 → `FAILED: <the script's stderr>`

Change nothing. This mode never writes.
