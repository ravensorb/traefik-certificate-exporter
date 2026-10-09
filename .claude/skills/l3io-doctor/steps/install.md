# upgrade — update this extension, or remove its payload

Invoked with `upgrade`, `install`, or `uninstall`. **The upgrade path runs BMad's installer;
the clean path deletes files.** Nothing runs without confirmation, and the clean path reports
in full before it changes anything.

This mode works from what is installed in the project. The repository also ships a
standalone `install.sh` at its root for a FIRST install — that one cannot live here, because
a first install has no payload to run from.

Why this mode exists: the install and upgrade commands are not interchangeable, and getting
that wrong has already cost this estate data. An upgrade is `--action quick-update`, which
derives the module set and IDE list off the existing install and deletes nothing. The
first-install form takes `--modules` and `--tools`, both **authoritative rather than
additive** — BMad removes every installed module and every IDE tree those flags do not name,
without confirming. Two repos here were told to use the first-install form for an upgrade;
one lost the per-module `config.yaml` for `core`, `bmm`, `cis` and `tea`. The script encodes
which command goes with which intent so nobody has to remember, and refuses the combinations
that caused the damage.

## 1. Decide the action

Ask if the request is ambiguous. Map it:

| The user wants | Do this |
|---|---|
| to update to the current release | the upgrade in §2 |
| to remove this extension but keep BMad and their project | the clean in §3 |
| to set up a project with no BMad at all | **stop** — point them at `install.sh` in the repository root, or the install command in the README. A first install cannot run from payload that is not there yet. |

## 2. Upgrade

One command, and the flags it does *not* pass are the point:

```bash
npx -y bmad-method@latest install --directory {project-root} --action quick-update --yes
```

`--action quick-update` derives the module set and the IDE list off the existing install,
preserves module settings, and performs no selection-driven deletion. **Never** add
`--modules` or `--tools` to an upgrade: both are authoritative, and BMad removes every
installed module and every IDE tree they do not name, without confirming. Two repos were
told to use the first-install form for an upgrade and one lost the per-module `config.yaml`
for `core`, `bmm`, `cis` and `tea`.

Show the command, ask `Run this? (y/N)`, then run it.

### 2.1 Refresh the agent instruction block

The upgrade may have changed the block body. Refresh it in the running harness's instruction
file by following `assets/module-setup.md` §6 — it binds `{pm_status}`, `{runtime}` and
`{file}`, runs `--check`, asks for confirmation when `{file}` exists without markers, and only
then runs `--apply`. Do not run `--apply` outside that procedure: on a file with no markers it
appends to a document the user wrote. When the body is unchanged `--apply` writes nothing.

Exit 2 from it means ambiguous markers or invalid UTF-8; report it and continue — a
documentation block must never fail an upgrade that otherwise succeeded.

## 3. Clean — remove the instruction block, then this extension's payload

### 3.1 Remove the agent instruction block first

Bind `{pm_status}` = `{project-root}/_bmad/scripts/pm-status.py`, and `{runtime}` = exactly one
of `claude`, `codex`, `copilot` or `other`, chosen by the detection procedure in
`l3io-execute/steps/shared/step-00-activate.md`. A guessed runtime targets the wrong
harness's file.

The block is **not payload** — it lives in a user-owned file and is not covered by the
SHA-256 comparison below, so the payload sweep cannot see it. It goes first because the
payload sweep removes the self-installed `pm-status.py` this call needs. Remove it by its
markers:

```bash
uv run {pm_status} sync-agent-instructions --runtime {runtime} \
  --project-root {project-root} --remove
```

This never deletes the file, only the block. A file left empty is left empty. If
`pm-status.py` is already gone, report that the block was left in place and name its
`l3io:begin`/`l3io:end` markers so the user can delete it by hand.

### 3.2 Remove the payload

```bash
uv run {skill-root}/scripts/clean-payload.py --project-root {project-root}
```

Read-only as written. It lists every file it would delete, and every file it is **keeping**
because that file's hash does not match what we shipped — meaning somebody edited it. Relay
both lists in full; the second is the one that needs a human decision.

Only after the user has seen that list and confirmed:

```bash
uv run {skill-root}/scripts/clean-payload.py --project-root {project-root} --apply
```

Exit codes: `0` done · `2` usage error · `4` no payload found.

## 4. After an upgrade, migrate the data

**The installer refreshes skills. It does not migrate project data.** Those are separate
steps and skipping the second is the most common way to end up with a project the skills
cannot read. So after a successful `upgrade`, tell the user to run `/l3io-doctor` — the
default health check — and say why in one line. `docs/upgrading.md` carries the full
procedure and the per-version notes.

Report the installed version afterwards with the `version` mode, so the upgrade is confirmed
rather than assumed.

## Notes

- **`@latest`, not a bare `bmad-method`.** A bare `npx` reuses whatever it already cached,
  which is how one machine stayed on 6.11.0 while the fleet ran 6.12.0. `@latest` resolves
  the dist-tag on every run. Pin a specific release only for a deliberate exception.
- The clean never touches project state: `{implementation_artifacts}/state/**` appears in no
  payload manifest, so the derived delete scope excludes it by construction.
- The clean removes the self-installed `{project-root}/_bmad/scripts/pm-status.py` when it
  matches a shipped copy. That is safe — any l3io skill reinstalls it at activation.
