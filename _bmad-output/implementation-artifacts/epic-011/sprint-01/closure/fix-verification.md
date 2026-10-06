# Epic E011 Sprint 01 — closure fix verification

Narrow re-verification of the eleven-fix closure pass described in `closure-fixes.md`.
Scope limited to the listed items; deferred findings were not re-raised. No code changed.

Method: read the current source, read the tests that claim each property, ran
`poetry run pytest` on the five in-scope test files (**101 passed, 1.79s**), and
independently injected faults outside the test suite — crafted path components, a
symlinked sub-directory inside `outputPath`, a symlinked `outputPath`, a bare
`LogRecord` formatted through both handler types, and a real SIGTERM at a real
process during the start-up sweep.

| Item | Verdict | Evidence |
| --- | --- | --- |
| **1. RT-001 (HIGH)** — path traversal via `domain.main` / `resolverName` | **RESOLVED** | Whitelist regex `_PATH_COMPONENT_PATTERN` at `certificate_exporter.py:262-265`, applied to `resolverName` at `:300-312` (ERROR + return for that resolver) and to `name` after wildcard stripping at `:358-370` (ERROR + `continue`, so the sweep carries on — proved by `tests/libs/test_certificate_exporter.py:426`). Containment re-asserted on the resolved directory at `:418-427`. **Independent bypass attempts, all rejected:** `/etc/x`, `../../etc`, `..`, `.`, `""`, `a..b`, `x.` (trailing dot), `.x` (empty leading label), `a/b`, `a\b`, `a\x00b`, `C:`, `C:/x`, `~/x`, `..\..\x`, `-bad.com`, 64-char label, and the IDN/unicode set (`über.com`, `exаmple.com` with Cyrillic а, `İstanbul`, `K\u212a`, `\uff0e\uff0e`, `a\u2024b`) — ASCII-only class rejects every one; punycode `xn--…` is accepted as the correct normalised form. **Symlink escape attempted end-to-end:** `outputPath/evil.example.test → /victim` was refused by `_is_contained_within` (`certificate_exporter.py:418`, log line "resolved output directory … escapes …"), victim directory stayed empty. A *legitimately* symlinked `outputPath` still exports correctly. Flat mode covered by the same gate (name is the filename), test at `:444`. |
| **2. RT-002 / AD-03 (HIGH)** — key material at 0600 | **RESOLVED** | `_SECRET_FILE_MODE = 0o600` (`certificate_exporter.py:62`) passed at all three key-bearing call sites: hierarchical `privkey.pem` (`:463-467`), flat `*.key` (`:435-439`), and every `*.pfx` unconditionally inside `PemToPfxConverter.export_to_pkcs12` (`:645`), which covers both layouts. `cert.pem` / `chain.pem` / `fullchain.pem` / `*.crt` are written with `mode=None` → umask-derived (`:469-478`). Proved by `test_key_bearing_artifacts_are_never_group_or_world_readable` (`tests/libs/test_certificate_exporter.py:243`) and the narrowed parity test (`:225`). **Confirmed end-to-end outside the suite:** a real hierarchical export produced `privkey.pem 0o600`, `cert.pem/chain.pem/fullchain.pem 0o644`. |
| **3. RT-003 / AD-05 (HIGH/Medium)** — metadata inherited from a target not ours | **RESOLVED** | `_inheritable_metadata` (`certificate_exporter.py:103-156`): probes with `os.lstat` (`:123`) so a symlink is never followed; refuses a symlink target with a once-per-path WARNING (`:127-139`, `_SYMLINK_WARNED` guarded by a lock at `:68-69`); refuses a foreign `st_uid` (`:141-147`); refuses any mode carrying a bit outside the policy floor (`existingMode & ~policyMode`, `:149-155`). A **tighter** operator mode still wins because `fileMode` takes the existing mode verbatim when it passes (`:171`) — proved by `test_an_operators_tighter_mode_still_wins` (`:556`) and `test_an_atomic_write_preserves_an_existing_files_permissions` (`:262`, 0600 survives a 0644 policy write). Fault-injection tests at `:487`, `:508`, `:524`. |
| **4. RT-005 / AD-01 (HIGH)** — SIGTERM reaches shutdown | **RESOLVED** (see regression R1) | `install_shutdown_signal_handlers` (`app.py:46-74`) installs a `KeyboardInterrupt`-raising handler for SIGTERM and SIGINT inside a `try/except (ValueError, OSError, AttributeError, RuntimeError)` → guarded, a non-main-thread or missing-signal platform degrades to a debug line (`:69-74`). Called once from `main()` at `app.py:95`. The watch block's `except KeyboardInterrupt` now reaches `observer.stop()` + `event_handler.cancel()` (`app.py:167-173`) and `observer.join()` is guarded by `observerStarted` (`:175-177`). The test (`tests/test_app.py:156-216`) spawns the installed console script as a **real subprocess**, waits for "Watching for changes", calls `proc.send_signal(signal.SIGTERM)` (`:205`) and asserts the stopping line, no traceback, rc 0 — not a direct handler call. Independently timed at 0.53s, so it genuinely spawns and signals. |
| **5. SD-01-1 / AD-02 (MAJOR/HIGH)** — `cancel()` TOCTOU | **RESOLVED** | `draining` is now published as the *first* statement on the timer thread (`__drainWindow`, `certificate_exporter.py:1001-1013`), and `doTheWork` re-checks the `shuttingDown` latch under the lock at entry, clearing `isWaiting` and abandoning the pass (`:889-903`). `cancel()` derives its message from an **observed outcome** — `drainsRun` delta plus a post-join `draining`/`is_alive()` re-read (`:826-861`) — so the "cancelled" line is unreachable for a drain that ran. `drainsRun` increments only past the latch (`:906-907`). The race test (`test_certificate_exporter_watch.py:600-641`) drives 60 iterations across a varying **real** debounce timer, asserts `not (ran and saidCancelled)` and `drainsRun == (1 if ran else 0)`, and carries an inertness guard (`assert sawCancelled`). The latch test (`:576`) injects the exact post-latch timer firing and asserts nothing was exported. **Deadlock check (the fix moved lock acquisition): none found.** `__drainWindow` releases the lock before calling `doTheWork`; `cancel()` releases the lock before every `timer.join()`; the `BaseException` unwind in `doTheWork` reaches `__rearm`/`__arm` with the lock held but neither re-acquires it; `self.lock` is never held across a join or a nested acquisition on any path. Signal-delivered `KeyboardInterrupt` lands only on the main thread, which never holds `self.lock` outside `cancel()`'s own `with`, which releases on unwind. |
| **6. RT-004 (HIGH, auto-discovery half)** — logging config from CWD | **RESOLVED** | `setup_logging` (`logging_utils.py:166-245`) resolves `path` from the env var only (`:187-190`), else the packaged copy via `importlib_resources.files(...)` (`:199-212`), else `coloredlogs.install` (`:214-220`). No `Path.cwd()`, no bare relative `cfg_file_name` fallback anywhere in the function. Proved by `test_a_planted_logging_yaml_in_the_working_directory_is_not_loaded` (`tests/libs/test_logging_config.py:201`) and `test_an_explicitly_pointed_logging_config_is_still_honoured` (`:222`), both planting a config whose `()` key executes a marker. s6-root runtime and `postexportcommand` deliberately out of scope, as stated. |
| **7. UX-001 (High)** — value-aware redaction | **RESOLVED** | `_is_empty_secret` (`settings.py:58-68`) treats `None` and any empty str/bytes/list/tuple/dict/set as absent while deliberately **not** treating `0`/`False` as absent. `_redact_secrets` masks only a present value (`:96-114`). `_mark_present_secrets` marks a confuse path `redact = True` only when `not _is_empty_secret(current)` (`:350-373`) and now runs after `set_args` (`:296`), so a CLI-supplied passphrase is still marked. **No regression on the set case:** `test_a_set_declared_secret_is_still_masked_in_every_sink` (`tests/libs/test_settings.py:286`) captures every DEBUG record across all three sinks (argparse-namespace dump `settings.py:286`, `_dump_config` `:387`, `_dump_settings` `:375`) and asserts the planted value appears nowhere while `REDACTED` does appear — × `pkcs12passphrase` and `appriseurls`. Both-sinks-agree case at `:303`; `0`-is-not-empty at `:335`. |
| **8. F8/F9/F10/F11** | **RESOLVED** | **F8:** `_fsync_directory` (`certificate_exporter.py:223-244`) called immediately after `os.replace` (`:211`), best-effort on `OSError`; tests `:571`, `:591`. **F9:** `tempfile` creates at 0600 and the final `os.chmod` is the statement immediately before `os.replace` (`:210-211`) — nothing widens the staging file earlier; `_sweep_stale_temp_files` (`:76-102`, 1h cutoff at `:66`) is invoked once per directory per pass (`:428-430`), skips symlinks/non-regular files, swallows `OSError`; tests `:608`, `:632`. **F10:** `_probe_default_file_mode()` runs at import, module level, single-threaded (`:50-57`), lock removed; test `:658`. **F11(b), verified independently outside the suite:** loading a *copy* of `logging.yaml` with the record factory replaced by the stock `logging.LogRecord` and formatting a bare record — console `CorrelationIdColoredFormatter` rendered `… [    INFO] [-] : hello` **with ANSI colour intact** (`\x1b[32m…`), and the `RotatingFileHandler`'s `JsonFormatter` rendered valid JSON. With a real id set, console rendered `[abc-123]` in colour and JSON rendered `"correlation_id": "abc-123"` — so the subclass works for the console handlers, the JSON formatter is unbroken, and colour output is unaffected. `logging_utils.py:61-80` only augments `self._style._defaults`, touching nothing `coloredlogs` relies on. Test `tests/libs/test_logging_config.py:241` formats the bare record through **both** handler types. |

## Residual gaps (noted, not verdict-changing)

- **Item 1 — trailing newline accepted.** `_PATH_COMPONENT_PATTERN` is anchored with `$`,
  which in Python matches before a trailing newline, so `"nl.example.test\n"` passes
  validation and creates a directory whose name ends in a newline (confirmed
  end-to-end). It is **not** a traversal — `"abc\n../x"` is still rejected, and the
  containment assertion holds — but it permits an odd on-disk name and one line of log
  injection. `\Z` instead of `$` (`certificate_exporter.py:263`) would close it.
- **Item 5 — half the inertness guard.** The race test asserts `sawCancelled` but not
  `sawRan`, so the "drain already ran" ordering could silently stop occurring without
  failing the test.
- **Item 8 — `defaults` floor is not uniform.** `pythonjsonlogger.JsonFormatter` emits
  `"correlation_id": null` rather than the `-` literal for a record lacking the
  attribute. No `ValueError`, so the self-sufficiency property holds, but the file/JSON
  sink and the console sink render the absent case differently.

## Regressions introduced by the fix pass

**R1 (from F4, `app.py:46-74`) — SIGTERM outside the watch block now dies with a
traceback and a signal exit status.** The handler raises `KeyboardInterrupt`
unconditionally, but only the `watchForChanges` block has an `except KeyboardInterrupt`
(`app.py:152-173`). The start-up sweep (`app.py:115-147`, `runAtStart: true` — the
default) has a `try/finally` with **no** `except`, as does everything before it
(`setup_logging`, `globalSettingsMgr.loadFromFile`, `require_existing_path`).

Reproduced outside the suite: a real process with `runatstart: true` over a large data
directory, SIGTERMed 2s into the sweep, produced an uncaught
`KeyboardInterrupt: signal 15` traceback, **no** "stopping...." line, and
`returncode -2` (CPython re-raises SIGINT to itself for an uncaught
`KeyboardInterrupt`), i.e. the process reports itself killed by SIGINT after being sent
SIGTERM. Before F4, SIGTERM in that window terminated silently with status 143.

Two consequences: (a) the clean-exit contract F4's own docstring claims for an operator
who "stops the container during start-up" holds for the watch loop only; (b) the
captured traceback shows the interrupt landing *inside* a `logging` handler `emit`,
so a raise-from-signal-handler can also abort a log write mid-line. A
`except KeyboardInterrupt` around the start-up sweep (or a flag-based handler) would
close it; filing as a backlog item is reasonable — it is a start-up-window cosmetic and
exit-status defect, not a certificate-safety one.

Resolved: 8, Partial: 0, Not resolved: 0, Regressions: 1
