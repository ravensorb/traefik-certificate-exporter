# ADR-0042: The dependency audit covers every lock group and every CI bootstrap file

- **Status:** Accepted
- **Date:** 2026-10-11
- **Deciders:** E014 epic architecture gate (l3io-arch-review + bmad-agent-architect)
- **Epic:** E014
- **Departs from spec:** `_bmad-output/planning-artifacts/architecture/architecture-ci-cd-pipeline-2026-10-08/ARCHITECTURE-SPINE.md#ad-3--local-and-ci-gates-are-one-hook-list-adopted`
  ("`pip-audit` … audits the whole dev venv") and
  `_bmad-output/planning-artifacts/prds/prd-traefik-certificate-exporter-2026-08-30/prd.md#4-non-functional-requirements`
  (NFR-3, "no locked dependency carries a known advisory"). Both wordings are corrected
  by E014-S02-003 from the amendment text in `notes-E014-S01-007.md` and
  `notes-E014-S02-001.md`.
- **Principle(s) in tension:** Global rule 4 (a guard's scope is derived from the source
  of truth, never "whatever happens to be installed"); global rule 1 (maintained tools
  only); global rule 3 (a claim of coverage ships with the check); Core §7 (dependency
  selection); CI AD-4 (no custom policy code).
- **Resolves:** arch-gate finding AG-3 (MAJOR) with AR-1 folded in
  (`_bmad-output/implementation-artifacts/epic-014/arch/arch-gate-review.md`,
  `arch-gate-review-architect.md`).

## Context

E014-S01-007 adds a `pip-audit` pre-commit hook,
`poetry run pip-audit --skip-editable --progress-spinner off`. It audits the packages
installed in the venv it runs in, nothing else. That venv is built by `just install`
(`justfile:13`, `poetry install`) locally and by `build.yaml:47` (`poetry install`) in CI.
Plain `poetry install` skips optional groups.

E014-S02-001 then moves `twine` into a new **optional** group `publish`, installed only
by the credentialed publish jobs (`poetry install --only publish --no-root`). From that
point the gate never sees twine or its transitive set, which are the only packages that
run beside a live PyPI or Gitea token. S02-001 also introduces a second package set
outside `poetry.lock`: the hashed Poetry bootstrap file `.github/requirements/poetry.txt`,
which pip-compile resolves independently and which every credentialed job installs. The
gate never sees that either.

PRD NFR-3 says the gate means "no locked dependency carries a known advisory", and CI AD-3
says it "audits the whole dev venv". After S02-001 both overstate the gate: its real scope
is "whatever `poetry install` happened to install", which is the hand-kept, implicit scope
global rule 4 forbids.

Facts checked on 2026-10-11 in this repository:

- Poetry 2.4.2 (`poetry --version`) supports `poetry sync` and `--all-groups` on both
  `install` and `sync` (`poetry sync --help`, `poetry install --help`). `poetry sync`
  removes any installed package the lock does not list.
- `poetry export` does not exist on this install ("The requested command export does not
  exist"); since Poetry 2.0 it needs the separate `poetry-plugin-export` plugin. The only
  plugin declared is `poetry-dynamic-versioning` (`pyproject.toml`,
  `[tool.poetry.requires-plugins]`).
- pip-audit 2.10.1 (`uvx pip-audit --help`): `-r/--requirement` "can be used multiple
  times"; `--disable-pip` works only with hashed requirements files; `--locked` "audit[s]
  lock files from the local Python project". Run against this repository,
  `pip-audit --locked .` prints `no lockfiles found in .`, so it does not read
  `poetry.lock`.
- The only `pip install` lines in `.github/workflows/` are the three
  `python -m pip install "poetry==2.4.2"` lines (`build.yaml:46`, `dev.yaml:77`,
  `release.yaml:123`), which S02-001 converts to the hashed file.

## Options considered

### Lock groups

| Option | Pros | Cons | Standards fit |
|--------|------|------|---------------|
| A. Keep `poetry install` (default groups) | No change | Optional groups (`publish`) are never audited; the gap is silent | Violates global rule 4 and NFR-3 |
| B. `poetry install --with publish` in `just install` and `build.yaml` | One flag; the arch gate's first suggestion | The group name is a hand-kept list. The next optional group escapes the same way | Violates global rule 4 (enumerated scope) |
| C. `poetry export --all-groups` then `pip-audit -r … --disable-pip` | Audits the lock text directly, independent of the venv | Needs `poetry-plugin-export`, a new plugin in the Poetry plugin env (itself unaudited, see Consequences), for parity with D | Core §7: a dependency added for no gain over D |
| D. `pip-audit --locked` over the lock | No venv involved | pip-audit 2.10.1 reads PEP 751 `pylock` files only; it finds nothing here | Not available |
| **E. `poetry sync --all-groups` in `just install` and `build.yaml`** | The venv equals the whole lock, every group, optional or not, with no group named anywhere; the existing hook is unchanged; Poetry is already the tool | Twine and every future optional group are installed in the credential-free build job and in dev venvs; a local venv not re-synced after a lock change is audited as it stands | Global rules 1 and 4; AD-4 (standard tool configuration only) |

### Bootstrap requirements files

| Option | Pros | Cons | Standards fit |
|--------|------|------|---------------|
| F. Second hook naming `.github/requirements/poetry.txt` | Simple | A second bootstrap file escapes; the file name is a hand-kept list | Violates global rule 4 |
| **G. Second hook whose file set is its `files:` glob over `.github/requirements/`, plus a pygrep reach guard on workflows** | Scope comes from the directory, and the guard keeps every CI `pip install` inside that directory | One `bash -c` loop in the hook `entry` to turn file names into `-r` flags | Global rule 4; AD-4 (hook configuration, no script file) |

## Decision

**The dependency audit's scope is every dependency group in `poetry.lock` plus every
requirements file used to bootstrap tooling in CI. Both sets are derived from the files
themselves, never from a hand-kept list.**

1. **Lock scope (option E).** `just install` and the `build.yaml` install step run
   `poetry sync --all-groups`. The audited venv is therefore exactly the lock, every
   group included, with no group named. The `pip-audit` hook's `entry` is unchanged
   (`poetry run pip-audit --skip-editable --progress-spinner off`) and its `files:` stays
   `^(pyproject\.toml|poetry\.lock)$`. The publish jobs keep installing
   `--only publish`; nothing about what a credentialed job installs changes.
2. **Bootstrap scope (option G).** A second `repo: local` hook beside it:
   - `id: pip-audit-bootstrap`, `language: system`, `pass_filenames: true`;
   - `files: ^\.github/requirements/[^/]+\.txt$`;
   - `entry: bash -c 'rc=0; for f; do poetry run pip-audit --require-hashes --disable-pip --progress-spinner off -r "$f" || rc=1; done; exit "$rc"' --`.

   Every hashed file in that directory is audited without a resolver run, at its own
   pins. The directory is empty until S02-001 adds `poetry.txt`; pre-commit then skips
   the hook, which is correct.
3. **Reach guard.** A pygrep hook `workflows-pip-install-from-requirements`
   (`files: ^\.github/workflows/.*\.ya?ml$`) fails on any
   `pip install(?! --require-hashes -r \.github/requirements/[^/\s]+\.txt\b)`. A CI
   `pip install` that is not a hashed install from the audited directory cannot land, so
   the glob in item 2 stays complete. It lands with S02-001, the change that makes the
   workflows comply.
4. **Probes that attack scope**, each in a throwaway clone, recorded in the story notes:
   - **Lock.** Add an optional group with a new name (for example `zzprobe`) holding one
     package that is not otherwise in the lock, at a version OSV lists with an advisory.
     Relock. After plain `poetry install` the `pip-audit` hook **passes**: the old scope
     misses it. After `poetry sync --all-groups` it **fails**, naming the advisory. A
     plant in the `publish` group itself gives the same result after S02-001.
   - **Bootstrap.** Add `.github/requirements/zz-probe.txt`, generated with
     `pip-compile --generate-hashes` from `urllib3==2.2.2`. `pip-audit-bootstrap` fails,
     naming GHSA-2xpw-w6gg-jr37. The file name is one no configuration mentions.
   - **Reach.** Add `python -m pip install "poetry==2.4.2"` to one workflow, and in a
     second plant `pip install --require-hashes -r tools/x.txt`. The guard fails on both.
5. **Owners.** E014-S01-007 owns items 1, 2 and the lock and bootstrap probes (one story
   owns the audit hooks). E014-S02-001 owns item 3 and its probe, and shows that the
   `publish` group and `poetry.txt` are inside the audited set. E014-S02-003 applies the
   CI AD-3 and PRD NFR-3 wording below.

Replacement wording for E014-S02-003 (carried verbatim in the notes files):

- **PRD NFR-3**, last clause: "…and no package in any `poetry.lock` group, optional groups
  included, nor in any hashed CI bootstrap file under `.github/requirements/`, carries a
  known advisory (`pip-audit` gates, ADR-0042)."
- **CI AD-3**, `pip-audit` bullet: "`pip-audit` audits the venv that
  `poetry sync --all-groups` produces (`just install`, `build.yaml`), so its scope is
  every lock group; `pip-audit-bootstrap` audits every `.github/requirements/*.txt` with
  `--require-hashes --disable-pip`; the `workflows-pip-install-from-requirements` guard
  keeps every workflow `pip install` inside that directory (ADR-0042)."

## Consequences

- **Positive.** The packages that run beside live publish tokens (twine, its transitive
  set, and Poetry's bootstrap closure) are audited on every `just check` and CI run. A new
  optional group or a new bootstrap file is inside the gate on the day it appears.
- **Negative / trade-offs accepted.**
  - The credential-free `build` job and every dev venv install twine and any future
    optional group. `build.yaml` holds no secret (AD-2), so this widens nothing that
    matters.
  - A stale local venv is audited as it stands. CI syncs from scratch on every run, so
    CI is the authoritative gate; `just install` re-syncs locally.
  - `pip-audit-bootstrap` carries a one-line `bash -c` loop in its `entry`. It is hook
    configuration, not a script file, and it exists only because pip-audit takes files as
    `-r` flags, not as positional arguments.
- **Not covered, stated (global rule 3):**
  - Poetry's plugin environment (`[tool.poetry.requires-plugins]`:
    `poetry-dynamic-versioning` and its dependencies) is not in `poetry.lock` and not
    audited. Locking it is BL-E013-033.
  - Poetry installed inside the Dockerfile builder stage (`docker/Dockerfile:29`,
    `pip install "poetry==${POETRY_VERSION}"`) is outside `.github/workflows/`, so the
    reach guard does not see it; it stays an S02-001 non-goal.
  - Pre-commit's own isolated hook environments (ruff, gitleaks and the rest) are pinned
    by frozen SHAs (AD-3, AD-5), not audited by pip-audit.
  - The guard is a regex over workflow text. A `pip install` written through a variable,
    or split across lines with `\`, is not matched.
- **Revisit when** Poetry can write a PEP 751 `pylock.toml` that `pip-audit --locked`
  reads. Auditing the lock text directly would then remove the dependence on the venv
  being synced, and option D replaces option E.
