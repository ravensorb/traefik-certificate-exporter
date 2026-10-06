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

## 3. Clean — remove this extension's payload only

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
