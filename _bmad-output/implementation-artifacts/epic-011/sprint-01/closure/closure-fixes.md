# Epic E011 Sprint 01 — closure fixes

## Closure fix pass 1

Eleven findings from the four closure reviews (`adversarial-review.md`,
`redteam-report.md`, `arch-drift-review.md`, `ux-review.md`), implemented as a scoped fix
pass. Everything not listed here was deliberately left for the backlog.

Every safety property below is proved by an **injected fault** — a crafted acme store, a
planted placeholder file, a real SIGTERM at a real process, a drain fired into the shutdown
window — never by a clean run.

| Fix | Finding(s) | Files touched | Test that proves it |
| --- | --- | --- | --- |
| **F1** | RT-001 (HIGH) — `domain.main`/`resolverName` unvalidated into a filesystem path | `src/traefik_certificate_exporter/libs/certificate_exporter.py` (`_PATH_COMPONENT_PATTERN`, `_is_safe_path_component`, `_is_contained_within`, `AcmeCertificateExporter.__exportCertificate`) | `tests/libs/test_certificate_exporter.py::test_a_crafted_domain_name_cannot_escape_the_output_path` (7 params), `::test_a_crafted_domain_name_cannot_escape_in_flat_mode`, `::test_a_crafted_resolver_name_cannot_escape_the_output_path`, `::test_a_rejected_domain_does_not_stop_the_rest_of_the_sweep` |
| **F2** | RT-002 / AD-03 (HIGH) — private keys written 0644 | `certificate_exporter.py` (`_SECRET_FILE_MODE`, `_atomic_write(mode=…)`, `privkey.pem` / `*.key` / `*.pfx` call sites, `PemToPfxConverter.export_to_pkcs12`) | `::test_key_bearing_artifacts_are_never_group_or_world_readable`; the parity test `::test_an_atomic_write_matches_what_open_w_would_have_produced` was narrowed to the non-secret artifacts |
| **F3** | RT-003 + AD-05 (HIGH + Medium) — mode/ownership inherited from whatever occupies the target | `certificate_exporter.py` (`_inheritable_metadata`, `os.lstat` probe, `_SYMLINK_WARNED`) | `::test_a_symlink_at_the_target_does_not_donate_its_metadata`, `::test_a_permissive_placeholder_does_not_dictate_the_key_mode`, `::test_a_placeholder_owned_by_another_uid_is_not_inherited`, `::test_an_operators_tighter_mode_still_wins` |
| **F4** | RT-005 / AD-01 (HIGH) — shutdown path unreachable under SIGTERM | `src/traefik_certificate_exporter/app.py` (`install_shutdown_signal_handlers`, watch block restructured, guarded `observer.join()`), `docs/operational.md` §Shutdown | `tests/test_app.py::test_sigterm_reaches_the_shutdown_path_and_exits_cleanly` (spawns the console script, sends a real SIGTERM, asserts the shutdown line, no traceback, exit 0) |
| **F5** | SD-01-1 / AD-02 (MAJOR + HIGH) — `cancel()` TOCTOU | `certificate_exporter.py` (`__drainWindow` timer target, latch re-check at `doTheWork` entry, `drainsRun` counter, outcome-derived `cancel()` messages) | `tests/libs/test_certificate_exporter_watch.py::test_a_drain_that_starts_after_the_shutdown_latch_exports_nothing`, `::test_cancel_never_claims_cancelled_for_a_drain_that_actually_ran` (60 iterations across the real debounce timer, with an inertness guard) |
| **F6** | RT-004 (HIGH, auto-discovery half only) — `/config` is a writable volume and a code-load path | `src/traefik_certificate_exporter/libs/logging_utils.py::setup_logging` (CWD discovery and the relative fallback both removed), `docs/operational.md` §"Trust boundary: `/config` and `settings.postexportcommand`" | `tests/libs/test_logging_config.py::test_a_planted_logging_yaml_in_the_working_directory_is_not_loaded`, `::test_an_explicitly_pointed_logging_config_is_still_honoured` (both plant a config whose `()` key executes a marker) |
| **F7** | UX-001 (High) — unset secrets render as `***REDACTED***` | `src/traefik_certificate_exporter/libs/settings.py` (`_is_empty_secret`, value-aware `_redact_secrets`, `_mark_present_secrets` moved after `set_args`) | `tests/libs/test_settings.py::test_an_unset_declared_secret_is_not_reported_as_configured`, `::test_an_empty_declared_secret_is_not_reported_as_configured`, `::test_a_set_declared_secret_is_still_masked_in_every_sink` (each × `pkcs12passphrase` and `appriseurls`), `::test_both_dump_sinks_agree_that_an_unset_secret_is_absent`, `::test_an_empty_secret_value_is_recognised_but_zero_is_not`, `::test_an_unset_secret_renders_as_null_rather_than_redacted` |
| **F8** | AD-04 / RT-012 (Medium) — rename not durable | `certificate_exporter.py::_fsync_directory`, called after `os.replace` | `::test_the_rename_is_followed_by_a_directory_fsync`, `::test_a_filesystem_that_rejects_a_directory_fsync_does_not_fail_the_export` |
| **F9** | AD-06 / RT-011 (Medium) — orphaned `.tmp` files carry key material | `certificate_exporter.py` (`_STALE_TEMP_AGE_SECONDS`, `_sweep_stale_temp_files`, per-pass `sweptDirectories`; final mode applied immediately before `os.replace`) | `::test_a_stale_staging_file_is_reaped_by_the_next_export_pass` (plants a 2h-old temp beside a live one), `::test_the_staging_file_holds_key_material_at_0600_until_it_is_complete` |
| **F10** | AD-07 / RT-010 + CR-03 (Medium) — lazy process-wide umask mutation | `certificate_exporter.py` (`_probe_default_file_mode` at import, lock removed, `except OSError:` narrowed) | `::test_the_default_file_mode_is_probed_once_at_import` |
| **F11** | AD-10 (Medium) + AD-11 (Low) — docs and self-sufficiency | (a) `README.md` CLI section, `docs/operational.md` §"Exit code 2 at start-up"; (b) `src/traefik_certificate_exporter/logging.yaml` (`defaults: {correlation_id: "-"}` on all six formatters, `()` factory form), `logging_utils.CorrelationIdColoredFormatter` | `tests/libs/test_logging_config.py::test_the_packaged_config_formats_without_the_record_factory` |

### Notes

- **F6 scope.** Only the auto-discovery half was closed. The s6 `s6-setuidgid root` runtime
  and the `postexportcommand` execution model are untouched and remain backlog items; the
  new operational section states the trust boundary they depend on.
- **F11(b) mechanism.** `logging.config.dictConfig` ignores a `defaults:` key when a
  formatter is declared with `class:`, so the formatters moved to the `()` factory form.
  `coloredlogs.ColoredFormatter` does not forward `defaults` to `logging.Formatter`, hence
  the thin `CorrelationIdColoredFormatter` subclass. The record factory remains the
  mechanism that supplies the real id; `defaults` is only the floor underneath it.
- **Adapted existing tests.** Three pre-existing tests asserted behaviour this pass
  deliberately changed and were updated rather than deleted:
  `test_an_atomic_write_matches_what_open_w_would_have_produced` (F2),
  `test_an_interrupted_drain_does_not_re_arm_during_shutdown` (F5 — the Ctrl-C now lands
  *during* the drain, which is the case the unwind guard actually exists for), and
  `test_redact_secrets_handles_none_value_without_raising` →
  `test_an_unset_secret_renders_as_null_rather_than_redacted` (F7).
- **Out-of-scope lint.** `tests/ci/test_runner_trust_routing.py` carried two pre-existing
  ruff findings (`F401`, `PERF102`) that the `--fix` git hook had been silently absorbing
  but that `just check`'s no-fix twin reports. Both were fixed mechanically so the required
  verification command is green; nothing else in that file changed.

### Verification

```
poetry run pytest -q --ignore=tests/test_release_version.py   # 525 passed, 4 skipped
python -m ruff check src/traefik_certificate_exporter tests   # All checks passed
python -m ruff format --check (files touched by this pass)    # clean
```

`tests/test_release_version.py` is excluded: its 6 failures are environmental, caused by
this host's global git `safe.bareRepository=explicit`, and are unrelated to this pass.

## Closure fix pass 2

Scope: the one regression and three residual gaps reported in `fix-verification.md`.
Nothing else was touched.

### G1 — R1: SIGTERM outside the watch block died with a traceback

`main()` installed the SIGTERM->`KeyboardInterrupt` handler unconditionally, but the only
`except KeyboardInterrupt` lived in the watch block. A signal during the `runAtStart`
sweep (the default) or on a one-shot `watchforchanges: false` run surfaced as an uncaught
`KeyboardInterrupt: signal 15`, no shutdown line, and exit status -2.

`main()`'s work is now in `_run(logger)`, called from a single `try/except
KeyboardInterrupt` in `main()`, with the "stopping...." line after it. Every phase --
settings load, path validation, the start-up sweep, the post-export hook, the
notification hop, the watch block -- reaches one handling point, so a signal at any
moment produces the same clean line and exit 0. The watch-mode shutdown semantics fix
pass 1 established (observer stop -> `event_handler.cancel()` -> guarded
`observer.join()`) are unchanged; its inner `except` still runs first and the outer one
only covers what used to be uncovered.

- Files: `src/traefik_certificate_exporter/app.py`
- Test: `tests/test_app.py::test_sigterm_during_the_run_at_start_sweep_exits_cleanly` --
  a real SIGTERM at a real spawned process held inside the sweep by a
  `postexportcommand: sleep 20` hook, with `watchforchanges: false` so the one-shot path
  is the one under test. Asserts the watch loop was never reached, no `Traceback` on the
  merged stream, the shutdown line present, and `returncode == 0`. Confirmed red against
  the pre-fix `app.py`.

### G2 — `_PATH_COMPONENT_PATTERN` accepted a trailing newline

`$` matches before a trailing newline in Python, so `"nl.example.test\n"` validated and
created a directory whose name ended in a newline -- contained, but an odd on-disk name
and a line of log injection. Anchored with `\Z`.

- Files: `src/traefik_certificate_exporter/libs/certificate_exporter.py`
- Test: `tests/libs/test_certificate_exporter.py::test_a_crafted_domain_name_cannot_escape_the_output_path`
  gains the `"nl.example.test\n"` case -- rejected end-to-end, nothing written under the
  output path, "Refusing to export" logged.

### G3 — the `cancel()` race test's inertness guard was half-present

The test asserted `sawCancelled` but not `sawRan`, so the drain-already-ran ordering
could stop occurring silently. `assert sawRan` added. The ordering did not occur at all
on this machine with the original jitter -- an immediate `cancel()` always won -- so the
window is now jittered on both sides: the debounce length as before, plus a varying
`delayBeforeCancel` (0-0.016s) before `cancel()`. Both orderings now occur across the 60
iterations; verified stable over repeated runs. The assertion was not weakened.

- Files: `tests/libs/test_certificate_exporter_watch.py`
- Test: `test_cancel_never_claims_cancelled_for_a_drain_that_actually_ran`

### G4 — `correlation_id` default was not uniform across sinks

`pythonjsonlogger.JsonFormatter` reads fields off the record and emits
`"correlation_id": null` for a record lacking the attribute, while the console
`CorrelationIdColoredFormatter` rendered `CORRELATION_ID_UNSET` (`-`). No `ValueError`
either way, so F11(b) held, but the two sinks spelled the absent case differently -- the
UX-001 class of inconsistency. Added `CorrelationIdJsonFormatter`, which fills any
`defaults` field the record does not carry before delegating to `JsonFormatter`, and
pointed all four JSON formatters in `logging.yaml` at it. `defaults` stays declared in
`logging.yaml`, so the file still stands on its own.

- Files: `src/traefik_certificate_exporter/libs/logging_utils.py`,
  `src/traefik_certificate_exporter/logging.yaml`
- Test: `tests/libs/test_logging_config.py::test_the_packaged_config_formats_without_the_record_factory`
  now captures what each handler renders for the bare record and asserts the JSON sink's
  parsed `correlation_id` and the console sink's `[-]` are both the sentinel.

### Verification

```
poetry run pytest -q --ignore=tests/test_release_version.py   # 528 passed, 4 skipped
poetry run ruff check src tests                               # All checks passed!
```

Baseline was 526 passed / 4 skipped; +2 are G1's new test and G2's new parametrize case.
`tests/test_release_version.py` is excluded for its pre-existing, environmental
`safe.bareRepository=explicit` failures on this host.

Note: `tests/ci/test_gates.py::test_no_file_escapes_every_gate_by_never_having_been_added`
failed on the first run because the verifier's own `fix-verification.md` and
`sprint-01-postfix.diff` were untracked. Both were `git add`-ed (staged, not committed) to
clear it.
