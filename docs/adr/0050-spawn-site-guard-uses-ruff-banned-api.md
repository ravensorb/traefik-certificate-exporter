# ADR-0050: The spawn-site guard uses ruff's banned-api rule, not a hand-written scanner

- **Status:** Accepted
- **Date:** 2026-10-12
- **Deciders:** Maintainer + E015 epic architecture gate (l3io-arch-review + bmad-agent-architect)
- **Epic:** E015
- **Departs from spec:** `_bmad-output/planning-artifacts/architecture/architecture-traefik-certificate-exporter-2026-08-30/ARCHITECTURE-SPINE.md#ad-2--container-base-image-privilege-model-and-root-mode-settings-trust-adopted`
  (AD-2 "Trust classes", enforcement: "a test walks the installed package with `rglob` and
  `ast`"; the spine is updated in the same change)
- **Principle(s) in tension:** global rule 1 (a maintained tool over a hand-rolled one;
  departing is a recorded decision); global rule 3 (state what a guard covers where the rule
  lives); global rule 4 (a hand-kept list must be derived or checked against its source of
  truth); Core §7 dependency selection
- **Implemented by:** E015-S01-001 (merged 2026-10-12), AC 5.
- **Records:** arch-gate finding AG-2 and the architect's ruff comparison
  (`_bmad-output/implementation-artifacts/epic-015/arch/arch-gate-review.md`,
  `arch-gate-review-architect.md`).

## Context

ADR-0049 makes `postexportcommand` the only route by which a root exporter runs a
command, and gates it on the source of the value. That gate is only the gate if the hook is
the **only** process the package spawns. The rule: `libs/post_export.py` is the package's
only process-spawn site.

E015-S01-001 first planned a pytest test that walks the installed package with `rglob`,
parses every module with `ast`, and reports calls to `subprocess.*`, `os.system`,
`os.popen`, `os.exec*`, `os.spawn*`, `os.posix_spawn*`, `os.fork*`, `pty.spawn` and
`asyncio.create_subprocess_*`, plus `from subprocess import`, with a planted-call test. Its
Existing-library check said only "stdlib `ast` … a test helper inside pytest". It did not
evaluate ruff, which already runs as a required pre-commit hook (CI AD-3) and is on CI AD-4's
list of allowed mechanisms. `pyproject.toml` has no `[tool.ruff]` section today.

**The comparison** (architect, 2026-10-12; ruff **0.16.5**, the pre-commit `rev`
`1f1e8bf…`; throwaway files outside the repository; re-run for this ADR on the same binary):

| Spawn form | flake8-bandit `S602`–`S606` | `TID251` banned-api | `ast` scan as planned |
|---|---|---|---|
| `subprocess.run(argv)` etc. with non-literal arguments, aliases included | caught (`S603`) | caught (import of the banned module) | caught |
| `subprocess.run(["/bin/sh", "-c", "id"])`, literal arguments | **not caught** (`S603` exempts literal input; `S607` fires only on partial paths) | caught | caught |
| `subprocess.run(cmd, shell=True)` | caught (`S602`) | caught | caught |
| `subprocess.getoutput`/`getstatusoutput`, `os.system`, `os.popen`, `from os import system as s; s()` | caught (`S605`) | caught | caught |
| `os.exec*`, `os.spawn*`, `os.startfile` | caught (`S606`) | caught (each name listed) | caught |
| `os.posix_spawn`, `os.posix_spawnp` | **not caught** | caught | caught |
| `os.fork`, `os.forkpty` | **not caught** | caught | caught |
| `pty.spawn` | **not caught** | caught (module ban) | caught |
| `asyncio.create_subprocess_exec`/`_shell` | **not caught** | caught | caught |
| `f = os.system; f(…)` (attribute reference, not a call) | **not caught** | caught | depends on the implementation |
| `getattr(os, "system")`, `importlib.import_module("subprocess")`, `__import__("subprocess")` | not caught | not caught | not caught |

Over today's `src/`, `S602`–`S606` produce exactly one finding (`libs/post_export.py:88`,
`S603`). Re-run for this ADR: `TID251` also reports `multiprocessing` and
`concurrent.futures.ProcessPoolExecutor` when they are listed, and a `# noqa: TID251` on one
import line suppresses only that line (a banned name used elsewhere in the same file is still
reported; `--ignore-noqa` shows the suppressed one).

## Options considered

| Option | Pros | Cons | Standards fit |
|--------|------|------|---------------|
| A. ruff flake8-bandit `S602`–`S606`, per-file ignore for `post_export.py` | Maintained tool; configuration only | Misses literal-argument `subprocess` calls, `posix_spawn*`, `fork`/`forkpty`, `pty`, `asyncio.create_subprocess_*` and attribute references: weaker than the rule it would enforce | Rejected: does not cover the case (global rule 1 prefers a tool only when it covers the case) |
| B. ruff `TID251` banned-api over the spawn-capable modules and names, plus one pytest test that derives the spawn-capable `os` names from `dir(os)` and checks they are all in the banned table | Maintained tool; covers every form the `ast` scan covers, and attribute references; runs in the existing ruff hook and in `just check`/CI; no custom scanner | banned-api has no wildcard, so the `os` names are a list in `pyproject.toml` (closed by the derived test); `noqa` can silence it | **Chosen** |
| C. Keep the hand-written `ast` scan (AC 5 as first planned) with the evaluation recorded | No list to keep; fully under the project's control | ~30 lines of custom scanner whose own defects show up as false greens; duplicates what the configured tool already does | Rejected: global rule 1 and its test-harness clause — a maintained tool covers the case |

## Decision

1. **ruff `TID251` is the spawn-site guard.** `pyproject.toml` gains:
   - `[tool.ruff.lint]` `extend-select = ["TID251"]` (the default rule set is kept);
   - `[tool.ruff.lint.flake8-tidy-imports.banned-api]` entries, each with a `msg` naming
     ADR-0050, for:
     - the modules `subprocess`, `pty` and `multiprocessing`;
     - `concurrent.futures.ProcessPoolExecutor`;
     - `asyncio.create_subprocess_exec` and `asyncio.create_subprocess_shell`;
     - `os.system`, `os.popen`, `os.startfile`, every `os.exec*` and `os.spawn*` name,
       `os.posix_spawn`, `os.posix_spawnp`, `os.fork` and `os.forkpty`;
   - `[tool.ruff.lint.per-file-ignores]` `"tests/**" = ["TID251"]`, because the test suite
     spawns processes (`tests/test_s6_*.py`, `tests/test_app.py`, the container tests).
2. **The one allowed site is suppressed on its line, not by file.** `libs/post_export.py`
   carries `# noqa: TID251` on its `import subprocess` line only. Other banned names in
   that file (`os.system`, `asyncio.create_subprocess_*`, …) are still reported, but ruff
   reports a banned module only at its import, so that one `noqa` also admits every
   `subprocess` call in `post_export.py`. A second `subprocess` call in that file is held
   by review, not by this rule (coverage limit; arch-gate re-validation N-1).
3. **The hand-kept `os` list is derived and checked** (global rule 4). One pytest test in
   `tests/libs/test_post_export.py` reads the banned-api table from `pyproject.toml` with
   `tomllib` (`tomli`, already in the dev lock, on Python 3.10), derives the spawn-capable
   names from `dir(os)` (prefixes `exec`, `spawn`, `posix_spawn`, `fork`, plus `system` and
   `popen`) and from `dir(asyncio)` (`create_subprocess_*`), and asserts every derived name
   is banned, together with the modules `subprocess`, `pty`, `multiprocessing`. A companion
   test runs the same helper over a copy of the table with `os.posix_spawn` removed and
   asserts that the helper names it. A second test asserts that the only `noqa` naming
   `TID251` under the package directory is the `import subprocess` line of
   `libs/post_export.py`.
4. **The rule's reach is proven against the tool**, as a Verification row of E015-S01-001,
   not a pytest test (ruff is a pre-commit hook, not a dev dependency): a scratch clone with
   the change, plus a planted module under `src/traefik_certificate_exporter/libs/` holding
   `os.posix_spawn(…)` and a literal `subprocess.run(["/bin/sh", "-c", "id"], check=False)`,
   makes the `ruff-check` hook fail with `TID251` for both, and the same row exits non-zero
   on today's tree (no banned table).

## Coverage limit

Stated here and in a comment beside the banned-api table:
- **Dynamic access is not covered:** `getattr(os, "system")`, `importlib.import_module`,
  `__import__`, `eval`/`exec` of source text. Neither ruff nor `ast` can resolve them; review
  is the only check.
- **`noqa` silences the rule.** Decision 3's second test catches a `# noqa: TID251` added
  under the package directory; a blanket `# noqa` (no code) is not caught.
- **Third-party code is not covered.** The rule covers first-party source only. What a
  dependency spawns is reviewed, not checked: the Docker SDK can spawn `ssh` for an
  `ssh://` `DOCKER_HOST` (`docker/transport/sshconn.py`) and a `docker-credential-*` helper
  for registry auth (`docker/credentials/store.py`); both are chosen by the environment
  (`DOCKER_HOST`) or unused (`docker.py` never authenticates). Apprise's only spawning
  plugin, `macosx`, is disabled off Darwin (ADR-0049, `appriseurls`).
- **The `os` derivation is per platform.** `dir(os)` on the runner decides the derived set;
  Windows-only names (`os.startfile`) are listed by hand.
- **Files ruff does not see.** The pre-commit `exclude` (`^(\.agents|\.claude|_bmad)/`) holds
  no package code. A Python file outside the package (`scripts/`) is checked by the same
  table but is not a spawn site of the package.
- **The embedded init resolver** (`init-traefik-certificate-exporter-config/run`) is Python
  inside a shell script, so ruff does not lint it. It imports the package's settings loader
  and spawns nothing; it is reviewed with the s6 scripts.

## Consequences

- Positive: the guard runs in the hook every contributor already runs, reports each
  violation at its line, catches literal-argument calls and attribute references the bandit
  rules miss, and needs no custom scanner.
- Negative / accepted: a hand-kept name list in `pyproject.toml`, closed by a derived test;
  the dynamic-access limit above.
- `pyproject.toml` gains its first `[tool.ruff]` section. `extend-select` keeps ruff
  0.16.5's default rule set; nothing else changes for existing code.

## Revisit when

- ruff gains a wildcard or prefix form for banned-api (the `os` list and its derived test go
  away); or
- a second legitimate spawn site is needed (it must be a new decision: ADR-0049 assumes one);
  or
- the derived-name test is ever skipped or deselected in CI.

## Amendment (2026-10-12) — E015-S01-001

Code review findings F2 and F3 (`_bmad-output/implementation-artifacts/epic-015/sprint-01/closure/review-E015-S01-001.md`).

- **Modules added to the banned table, banned whole:** `posix`, `nt`, `_posixsubprocess`,
  `asyncio.subprocess`, `concurrent.futures.process`, `ctypes` and `webbrowser`. Each reaches
  a spawn primitive without naming an `os` function or a banned module: `os` re-exports its
  primitives from `posix` (`nt` on Windows), `_posixsubprocess` is `subprocess`'s back end,
  `asyncio.subprocess` and `concurrent.futures.process` are submodules the existing
  `asyncio.create_subprocess_*` / `concurrent.futures.ProcessPoolExecutor` entries do not
  match on import, `ctypes` reaches libc `system`/`fork`/`exec`, and `webbrowser` spawns a
  browser. None is imported under `src/`.
- **The derived-name test takes its scope from `dir(posix)` (`dir(nt)` where present) as
  well as `dir(os)`**, requires `os.<name>` for every spawn-shaped name in either, and
  requires every module above. A planted platform-module name is reported.
- **Attribute calls on runtime objects are not statically resolvable:**
  `loop.subprocess_exec` / `loop.subprocess_shell` on an event loop, and a method on a
  `ctypes.CDLL` object. ruff resolves imports, not the type of a value; the module bans catch
  the import of `ctypes` and `asyncio.subprocess`, not a loop method. Review is the only check.
- **Suppressions.** The suppression test asks ruff which TID251 reports a comment
  suppresses, rather than matching comment spellings (F10): it runs the dev group's ruff
  (pinned to the pre-commit hook's version; a test fails if the two differ) as
  `ruff check --config pyproject.toml --select TID251 --ignore-noqa` over the installed
  package directory, and asserts that the only report is `libs/post_export.py`'s
  `import subprocess` line. `--ignore-noqa` disregards every suppression comment ruff honours
  -- line-level `noqa`, file-level `ruff: noqa` / `flake8: noqa`, and the range form
  `ruff: disable[...]` -- so the gate's clean run plus this test leave no comment-suppressed
  TID251 report under the package directory. A copy of the package with a planted
  `# noqa: TID251`, `# ruff: noqa: TID251` and `# ruff: disable[TID251]` spawn is reported
  for each. ruff's `PGH004` (blanket-noqa) is also selected. A further test reads
  `pyproject.toml` and fails if `per-file-ignores` / `extend-per-file-ignores` maps TID251
  (or a prefix: `TID`, `TID2`, `TID25`) to anything but `tests/**`, or if `ignore` /
  `extend-ignore` at `[tool.ruff]` or `[tool.ruff.lint]` holds it; each check has a planted
  violation. Still not checked: a ruff `exclude` / `extend-exclude`, a second ruff
  configuration file, a CLI `--ignore`, the `ALL` selector in an ignore list, and a
  suppression outside the package directory.

This replaces the Coverage-limit bullet "a blanket `# noqa` (no code) is not caught" and
extends "Dynamic access is not covered" with the runtime-object case; the comment beside the
banned-api table in `pyproject.toml` states the same limits.

## Amendment (2026-10-12) — sprint closure

Findings AR-2 and AR-3 (`_bmad-output/implementation-artifacts/epic-015/sprint-01/closure/adversarial-review.md`).

- **Decision 4's parenthetical is superseded.** "ruff is a pre-commit hook, not a dev
  dependency" is no longer true: `ruff==0.16.5` is in the Poetry dev group, pinned to the
  pre-commit hook's version, and `tests/libs/test_post_export.py` fails if the two differ.
  The rule's reach is therefore also proven by pytest (the suppression test runs that ruff
  over a copy of the package with planted violations), not only by the Verification row.
  Decision 4 is otherwise unchanged.
- **Re-export of the admitted import (AR-2) is now banned.**
  `traefik_certificate_exporter.libs.post_export.subprocess` is in the banned table. ruff
  0.16.5 resolves `from .post_export import subprocess`, `from . import post_export` followed
  by `post_export.subprocess.<x>`, and the absolute forms to that name (verified). The
  suppression test plants these forms in a copy of the package and requires a report for
  each. **Still not caught:** another module's `subprocess` or `os` attribute
  (`imaplib.subprocess.Popen`, `socketserver.os.fork`, a dependency's; verified unreported),
  and `getattr` / `vars` / `sys.modules` access. Review is the only check for those.
- **Stdlib code that spawns internally (AR-3).** Banned whole: `platform` (`architecture`,
  `processor`, `platform` and `uname().processor` run a subprocess, verified with an audit
  hook), `pydoc` (its pagers), `_pyrepl.pager`, `mailcap`, `pipes`, `distutils`, `ensurepip`,
  `venv`, `asyncio.base_subprocess`, `asyncio.windows_utils`, `_osx_support`, `_aix_support`,
  `_bootsubprocess`. Banned by name, because the package uses other names from the module
  (`uuid.uuid4`) or the rest of the module does not spawn: `imaplib.IMAP4_stream`,
  `uuid.getnode`, `uuid.uuid1`, `uuid.uuid6`, `http.server.CGIHTTPRequestHandler`,
  `socketserver.ForkingMixIn` / `ForkingTCPServer` / `ForkingUDPServer` /
  `ForkingUnixStreamServer` / `ForkingUnixDatagramServer`. None is used under `src/`.
  `tests/libs/test_post_export.py` requires each of these names in the table, and derives
  the set of stdlib modules that can spawn by AST-scanning the runner's stdlib sources
  (modules that import `subprocess` / `_posixsubprocess` or use an `os.<spawn>` attribute);
  it fails on any such module that is not banned whole (or through a parent), has no named
  entry, and is not in its reviewed list (`os`, `asyncio`: derived names;
  `asyncio.base_events` / `events` / `unix_events`: the event-loop runtime-object gap). A
  planted module and a removed `imaplib` entry are reported.
- **What the stdlib check does not prove.** It proves each spawning MODULE is accounted for,
  not that every spawning FUNCTION in a partially banned module (`imaplib`, `uuid`,
  `socketserver`, `http.server`) is banned: that selection is review. The scan only sees a
  direct `subprocess` import or `os.<spawn>` attribute; a module that spawns through another
  module's call is not found. The builtin `help()` reaches the `pydoc` pager and is not
  caught. The scan runs on the runner's Python, so a module present only on another
  supported version is checked only where a runner has that version.

The Coverage-limit comment beside the banned-api table in `pyproject.toml` states the same.
