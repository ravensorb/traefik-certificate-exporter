# ADR-0044: Container run-once contract and run-mode source of truth

- **Status:** Accepted
- **Date:** 2026-10-11
- **Deciders:** Maintainer (ravensorb), via the E014 plan (research 2026-10-10 §4,
  "Recommended fix"); implemented by E014-S01-005
- **Epic:** E014
- **Amends:** ADR-0030 (the init resolver now emits a second answer, the run mode, which the
  service consumes the way it consumes the privilege state)
- **Departs from spec:** n/a. Binds product spine AD-12 (container service model) and PRD
  FR-6; resolves review finding M5
- **Principle(s) in tension:** "ask the installed package, never a second parser"
  (ADR-0030) against a shell `run` script that must decide something before the package runs

## Context

The s6 service script decided whether to start the exporter by testing the raw environment
variable `TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_WATCHFORCHANGES` against `true`/`1`. That was
a second parser of operator configuration, and it disagreed with the application's: it never
saw `watchforchanges` from `/config/config.yaml`, and rejected YAML spellings confuse accepts
(`yes`, `True`). Anything it did not accept printed "Skipping start of application..." and
exited 0.

s6-overlay 3.2.1.0 (the image's pinned version) respawns a longrun whose `run` exits and has
no `finish`, once a second. So every run-once configuration produced a 1 Hz "Skipping" loop,
and if the test had passed, the single pass would have been re-run every second, repeating
exports, hooks and notifications. The documented smoke path (`WATCHFORCHANGES=false`) was
that loop.

## Decision

1. **The init resolver answers the run mode.** The Python resolver embedded in
   `init-traefik-certificate-exporter-config/run` (the installed package's
   `SettingsManager`, every confuse source) writes `true` or `false` to
   `/run/traefik-certificate-exporter/watch-for-changes`, atomically, after removing any
   stale copy. It is a separate file because `resolved-settings` has a positional layout the
   privilege helper reads (lines 1-4, then the store matches).
2. **The service always execs the exporter.** `svc-traefik-certificate-exporter/run` reads
   the mode file, echoes `Starting application (watch mode)` or `(run-once mode)`, and execs
   through the unchanged privilege branch. It reads no settings environment variable.
3. **Run-once ends the container with the pass's exit code.** A new
   `svc-traefik-certificate-exporter/finish` does nothing in watch mode (s6 respawns, as
   after any crash). In run-once mode it computes the code (`$1`, or `128 + $2` when `$1` is
   256), writes it to `/run/s6-linux-init-container-results/exitcode` and execs
   `/run/s6/basedir/bin/halt` -- s6-overlay's documented mechanism. If the code cannot be
   written it still halts; if `halt` is absent it exits 125, so s6 does not restart the
   service and the container stays up idle rather than looping.
4. **Missing state means watch.** Only the exact values `true` and `false` are a mode. A
   missing or invalid file means init's resolution failed; `run` logs
   `WARNING: run mode unresolved; defaulting to watch mode` (on stderr, so the privilege
   WARNING stays init's alone on stdout) and keeps the image default, watch.
5. **Nothing to do is said, not silent.** With both `runatstart` and `watchforchanges`
   false, the application logs one WARNING (`neither runatstart nor watchforchanges is set;
   nothing to do`) and exits 0. In the container that ends a run-once start with 0.
6. **Run-once containers use `restart: "no"`** or are started by cron, a systemd timer or a
   Kubernetes Job. `restart: always`/`unless-stopped` restarts the exited container and is a
   container-level loop; this is documented as an operator error, not prevented.
7. **The rule is enforced mechanically.** The pre-commit hook `s6-no-raw-settings-env`
   (pygrep for `TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_`, scope `^docker/root/`) fails on any
   shipped script that reads a settings variable directly, and the SHA-frozen `shellcheck`
   hook lints every shipped script.

## Exit-code limit

The exit code reflects **start-up failures only**: 0, or 1 when the data path is missing.
Export failures are logged at ERROR and do not change it, so a scheduler cannot detect a
failed export from the exit code. Making them non-zero needs a failure contract across the
export path (which failures count, whether a partial export is one) -- PRD §6 #23, filed as
backlog item **BL-E014-016**. The docs and the 0.3.0 release notes state this limit.

## Alternatives rejected

- **`finish` exits 125 in run-once mode (stay up idle).** Keeps the container running and
  hides the pass's result from anything that waits on it. Kept only as the fallback when
  `halt` is missing.
- **Keep the shell test and widen the spellings it accepts.** Still a second parser; it still
  cannot see the config file.
- **Append the mode to `resolved-settings`.** Breaks the positional contract
  `privilege-decision.sh` and its tests rely on.

## Consequences

- The container's mode is whatever the application resolves, and it exits after one pass
  when that is `false`; the 0.2.x "Skipping" respawn loop is gone. In the image the
  Dockerfile's environment default `TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_WATCHFORCHANGES=true`
  outranks `/config/config.yaml`, so the environment variable is the container's run-once
  switch; whether that default should move out of the environment is backlog item
  **BL-E014-017**.
- An unresolved mode (malformed config, or a value confuse rejects) falls back to watch
  mode, so the exporter's own start-up failure is respawned by s6 as it was in 0.2.x. That
  is a crash loop of a broken configuration, reported by the exporter's error on every
  start, not a run-once loop.
- `WATCHFORCHANGES=1` is rejected by confuse (`must be a bool, not int`), as it was by the
  0.2.x application after the shell let it through; the resolver writes no mode, so the
  service uses watch mode with the WARNING and the exporter reports the error.
- Opt-in evidence: `just image && TCE_DOCKER_INTEGRATION=1 poetry run pytest -m integration
  tests/test_container_run_once.py` (required for 0.3.0, run by E014-S02-005).
- Revisit if s6-overlay changes its `finish`/`halt`/exit-code contract (E014-S01-007
  re-verifies on the base-image bump), or when PRD #23 defines export failure.
