# version — which l3io-extensions version this project is running

Invoked with `version`, `--version` or `which-version`. **Read-only.** Reports the
version the installer put on disk, per skill and per module, and flags a tree where they
disagree.

Why this mode exists, and why it is not `check-pm-status`: three consumers independently
asked "which l3io am I on?" and had no way to answer it. `_bmad/_config/manifest.yaml`
records a custom-source module's `version` as the git ref that was cloned, so a project
tracking the default branch reads `version: main` — accurate and useless. `check-pm-status`
looks like the answer and is not: it compares the **self-installed** copy at
`{project-root}/_bmad/scripts/pm-status.py`, which self-install writes at skill
activation rather than the installer writing it, so immediately after a correct upgrade
it reports STALE for exactly one invocation. This mode reads the shipped manifests
instead, which are correct the instant the installer finishes.

## 1. Run the report

```bash
uv run {skill-root}/scripts/report-version.py --project-root {project-root}
```

`--skills-root` defaults to this skill's parent directory — its sibling skills — which is
where a standard install puts them. Pass it explicitly only when the skills live
somewhere else.

The report also names the **BMad** version, read from `_bmad/_config/manifest.yaml` →
`installation.version` (the key BMad's own installer writes). That half needs
`--project-root`; without it there is no `_bmad/` to read.

Add `--check-latest` when the user asks whether BMad itself is current:

```bash
uv run {skill-root}/scripts/report-version.py --project-root {project-root} --check-latest
```

It makes **one** network call to the npm registry. It is opt-in rather than default
because this mode is otherwise entirely offline, and a diagnostic that fails on a plane is
worse than one that answers the local half — which is the half that was asked for. An
unreachable registry reports the reason and still exits 0; it never turns a working report
into a failure. In `--format json` the `bmad.current` field is `null` when the check did
not run, which is a different answer from `false`: "unknown" is not "out of date".

## 2. Report

Print the output as-is. Then:

- Exit 0 → `DONE — l3io-extensions <version>.`
- Exit 3 → `MIXED VERSIONS — this tree carries more than one l3io version, which means a
  partial or interrupted install. Re-run the upgrade (see `docs/upgrading.md`), then run
  this mode again.` Name the skills and versions the report listed.
- Exit 4 → `FAILED: no l3io skills found under the skills root. Reinstall, or pass
  --skills-root if the skills are installed somewhere non-standard.`
- Exit 2 → `FAILED: <the script's stderr>`

Two lines in the output are explanatory, not findings, and should not be escalated:

- A skill with no `module.yaml` is normal — only the four module homes carry one.
- `self-installed pm-status.py` lagging the shipped version is normal immediately after an
  upgrade; it is refreshed at the next skill activation. It never changes the exit code.

If the user asked "is my install up to date?" rather than "what version am I on?", that is
a different question — this mode reports what is installed, not what the latest release is.
Say so, and point at the repository's releases.

Change nothing. This mode never writes.
