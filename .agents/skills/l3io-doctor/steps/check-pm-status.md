# check-pm-status — verify the installed pm-status.py is current

Invoked with `check-pm-status`. **Read-only.** Compares the installed
`{project-root}/_bmad/scripts/pm-status.py` against this doctor's `module_version` and reports
whether it is current, stale, or absent.

Why this lives here: `pm-help` and other consumers used to inline the comparison against a
`module.yaml` local to themselves, but only module homes carry `module_version`. This mode
lets any consumer ask "is pm-status.py current?" without a cross-skill file read of their
own — pm-help calls this, then reads the exit code.

## 1. Run the check

```bash
uv run {skill-root}/scripts/check-pm-status.py --project-root {project-root}
```

## 2. Report

Print the output as-is. Then:

- Exit 0 → `DONE — pm-status.py is current.`
- Exit 3 → `STALE — installed pm-status.py is behind the shipped version. Run any l3io-pm or
  l3io-doctor skill; the activation self-install refreshes the copy.`
- Exit 4 → `ABSENT — no pm-status.py has been self-installed at
  {project-root}/_bmad/scripts/pm-status.py yet. Run any l3io-pm or l3io-doctor skill to
  self-install it.`
- Exit 2 → `FAILED: <the script's stderr>`

Change nothing. This mode never writes.
