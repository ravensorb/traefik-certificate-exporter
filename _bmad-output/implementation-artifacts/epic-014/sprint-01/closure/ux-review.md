# UX review — E014 Sprint 01 (CLI and container operator surface)

- **Stories reviewed:** E014-S01-004, E014-S01-005, E014-S01-008, E014-S01-009, E014-S01-010
- **Evidence:** `/tmp/e014-s01-review/sprint-diff.patch` (hunks for `cli_args.py`, `settings.py`,
  `legacy_settings.py`, `suggest.py`, `app.py`, `README.md`, `docker/README.md`,
  `docs/operational.md`, s6 `init-…/run`, `svc-…/run`, `svc-…/finish`), the working tree, and
  live runs of `poetry run traefik-certificate-exporter` (`--help`, flag typos, legacy and
  unknown env names, an invalid `LOGGING_LEVEL`, quoted env values).
- **Date:** 2026-10-11
- **Out of scope (known):** BL-E014-017 (the image's env default `WATCHFORCHANGES=true`
  overrides the config file).

## How this review was run

The `bmad-ux` Reviewer Gate was invoked in headless review mode. Its lenses are written
for a `DESIGN.md` + `EXPERIENCE.md` spine pair. The rubric walker checks token completeness,
component coverage, visual references and so on. This project has no GUI and no spine
pair, so the gate has nothing it can validate, and running it headless would produce an
empty or `blocked` report. The review was therefore done **inline**. It keeps the gate's
structure (one lens per concern, severity set by downstream impact) and uses lenses
suited to a CLI and an operator-facing product:

| Lens | What it examines |
|---|---|
| L1 Error recovery | Strict-parse errors, typo suggestions, legacy and unknown setting warnings: does each one tell the operator what to do next? |
| L2 Discoverability and help text | `--help`, metavars, and README `## Usage` and examples |
| L3 Voice and consistency | Log and warning wording across surfaces, and singular/plural and case rules across CLI, env and config |
| L4 Docs-to-behaviour fidelity | README, `docker/README.md`, `docs/operational.md` and samples, each checked against observed behaviour |
| L5 Container operator journey | Run-once vs watch, exit codes, s6 messages, scheduler use |

Two story ACs had their user-facing parts verified as met, with no finding:
- the run-once/watch start lines and the `run mode unresolved` WARNING (S01-005 AC2/AC4);
- the `Did you mean '--data-path'?` text, the `--help` pointer and exit code 2 (S01-008).

Also met:
- metavars no longer leak `SETTINGS.*` (S01-008);
- the `Log level: <L> (source: …)` line and the invalid-env fallback WARNING (S01-004);
- legacy and unknown env-name warnings, with no values logged (S01-009);
- `No certificate changed; no hook or notification` (S01-010);
- the README and `docs/operational.md` "only on change" wording (S01-010).

Severity counts: **HIGH 0 · MEDIUM 6 · LOW 8**

## Findings

### UX-1 — MEDIUM — The unknown-setting pointer sends operators to a section that lists no setting names

- **Location:** `src/traefik_certificate_exporter/libs/legacy_settings.py:63` (`USAGE_POINTER`), used by `_message()` at `:323-325`. The destination is `README.md` `## Usage` (`:21-70`).
- **Lens:** L1, L4
- **Evidence:** Live run with `TRAEFIK_CERTIFICATE_EXPORTER_FOO=1` logs
  `Unknown setting TRAEFIK_CERTIFICATE_EXPORTER_FOO in environment matches no setting; see the "## Usage" section of README.md for the valid names`.
  `README.md` `## Usage` is the `--help` block. It contains **0** `TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_*` names, and README nowhere states the env-name rule
  (`TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_<KEY>`). The only enumerated env list is the compose sample in `docker/README.md`. S01-009's AC requires the pointer, and its target does not deliver what the message promises.
- **Fix:** Add a short "Environment variables" section to `README.md`. It should state the mapping rule (prefix + `SETTINGS_` + upper-cased `config_default.yaml` key path joined by `_`, with list indices `_<n>`) and the `LOGGING_*` family. Then point `USAGE_POINTER` at that section. A derived test should check that the section names every key in `config_default.yaml`, following the S01-008 pattern for long options.

### UX-2 — MEDIUM — "After every export pass" wording survives next to the new "only on change" contract

- **Location:**
  - `docker/README.md:114`: "notified when an export pass completes";
  - `docker/README.md:183`: compose comment "Command run after a successful export pass";
  - `config.sample.yml:15`: "run after a successful export pass";
  - `src/traefik_certificate_exporter/config_default.yaml:20`: "Apprise destinations notified after an export pass completes".
- **Lens:** L4
- **Evidence:** `docker/README.md:114` introduces the notifications section with the 0.2.x meaning. Two dozen lines later (`:138-143`), the same section says "A notification means 'a certificate changed': it is sent only on change". S01-010's AC requires the docs to state "only on change". The packaged default and the sample file still describe every-pass behaviour.
- **Fix:** Reword all four to "only on change (when at least one domain's exported files changed in the pass)". To keep this from drifting again, extend the existing settings-surface test with a check that these phrasings are absent outside `docs/adr/`, or record why that is not checked mechanically.

### UX-3 — MEDIUM — The `docker/README.md` compose sample still quotes values, which become part of the value

- **Location:** `docker/README.md:173-175` (`…_SETTINGS_DATAPATH="/data"`, `…_FILESPEC="*.json"`, `…_OUTPUTPATH="/certs"`)
- **Lens:** L4, L5
- **Evidence:** S01-004 unquoted `docker/docker-compose.yml` and added the comment "in list form Compose passes quotes through as part of the value". The README copy of the same sample was not changed. Live run with `TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_DATAPATH='"/tmp/uxr/data"'` gives `ERROR … Data Path '"/tmp/uxr/data"' does not exist. Exiting...`. An operator who uncomments these lines gets a start-up failure that looks like a missing mount. The S01-009 name checks do not catch it, because the name is valid.
- **Fix:** Unquote the three values and carry over the `docker/docker-compose.yml` comment about quotes. Optionally, extend the env-name scan to flag `=…"` quoted values in list-form compose samples.

### UX-4 — MEDIUM — The "nothing to do" WARNING has no remedy, and it is what a bare CLI run produces

- **Location:**
  - `src/traefik_certificate_exporter/app.py:195`;
  - `-r` help at `src/traefik_certificate_exporter/libs/cli_args.py:106`;
  - defaults at `src/traefik_certificate_exporter/config_default.yaml` (`watchforchanges: false`, `runatstart: false`).
- **Lens:** L1, L2
- **Evidence:** `traefik-certificate-exporter -d /tmp/uxr/data -o /tmp/uxr/out` logs `WARNING … neither runatstart nor watchforchanges is set; nothing to do` and exits. Most first-time PyPI users will see this as their first result. The message names config keys, not the flags a CLI user typed. `--help` gives `-r` as "Runs Export immediately on start (used with watch-for-changes)", which reads as a modifier of `-w`. So `--help` never says that `-r` alone is the run-once mode, although the README example "Run it once and then exit" depends on it.
- **Fix:**
  - Change the message to `nothing to do: pass -r/--run-at-start to export once, or -w/--watch-for-changes to watch (settings runatstart / watchforchanges)`.
  - Change the `-r` help to "Run one export pass at start; without -w the process then exits".
  - Regenerate the README usage block.

### UX-5 — MEDIUM — The README "watch" example is broken by a missing line continuation

- **Location:** `README.md:90-95` (pre-existing; inside the README block S01-008 regenerated around)
- **Lens:** L2, L4
- **Evidence:** Line 94, `-fs "acme-*.json" `, has no trailing `\`, so the pasted example runs without `-w` and the shell then reports `-w: command not found`. With the new defaults, the first command hits UX-4's "nothing to do" WARNING. The operator copied the documented watch command and gets a process that exits at once.
- **Fix:** Add the missing `\`. Optionally, run the README example commands through `--help`-free parsing in a test (`shlex` + `globalArgParser.parse_args`) so a broken example fails `just check`.

### UX-6 — MEDIUM — A scheduled run-once container can hang forever, and the docs give no scheduler guard

- **Location:** `docker/README.md` `### Run once` (`:59-88`); `docs/operational.md:62-75`; behaviour from `svc-traefik-certificate-exporter/run` (`*)` branch) and `finish`.
- **Lens:** L5
- **Evidence:** S01-005 AC4 deliberately falls back to watch mode when init cannot resolve the mode, for example with a malformed `/config/config.yaml`. `docs/operational.md` states the consequence: "s6 respawns the failing exporter until the config is fixed". For the use the Run once section recommends (cron, a systemd timer, a Kubernetes Job), that means the container never exits. Each scheduled run then starts another container that never exits, and the exit-code signal the operator relies on never arrives. Neither doc tells the operator to bound the run.
- **Fix:** In `docker/README.md` `### Run once`, add one bullet with a bounded example: `timeout 15m docker run --rm …`, Kubernetes `activeDeadlineSeconds`, or systemd `TimeoutStartSec=`. State that an unbounded run-once job can hang when start-up settings resolution fails. Mirror one sentence in `docs/operational.md`.

### UX-7 — LOW — With several typos, the "Did you mean" lines are not tied to the token they correct

- **Location:** `src/traefik_certificate_exporter/libs/cli_args.py:201-206`
- **Lens:** L1
- **Evidence:** `--dry-runn --restart-containers` prints `unrecognized arguments: --dry-runn --restart-containers`, then `Did you mean '--dry-run'?` and `Did you mean '--restart-container'?`. A typo with no match, mixed with ones that have a match, makes the pairing ambiguous.
- **Fix:** Use `'<token>': did you mean '<match>'?` when more than one dash token is left over. The S01-008 test still holds, because it asserts that `Did you mean '--data-path'?` is contained in the output.

### UX-8 — LOW — `-ll` is case-sensitive while `LOGGING_LEVEL` is case-insensitive

- **Location:** `src/traefik_certificate_exporter/libs/cli_args.py:142-155`
- **Lens:** L3
- **Evidence:** `-ll debug` gives `invalid choice: 'debug'` (exit 2). The help text in the same entry says the env value is "case-insensitive", and `TRAEFIK_CERTIFICATE_EXPORTER_LOGGING_LEVEL=debug` is accepted.
- **Fix:** Add `type=str.upper` to the `-ll` argument so both entry points accept the same spellings.

### UX-9 — LOW — Prefix abbreviations pass silently, outside the typo-suggestion path

- **Location:** `src/traefik_certificate_exporter/libs/cli_args.py:16` (`argparse.ArgumentParser` with default `allow_abbrev=True`)
- **Lens:** L1
- **Evidence:** `-x` is accepted as `-xd/--exclude-domains` with an empty list, and `--watch` is accepted as `--watch-for-changes`. Neither reaches the strict-parse error. A short or truncated flag in a `command:` override can change meaning when a later flag is added that shares the prefix.
- **Fix:** Decide and record one of two options. Either set `allow_abbrev=False`, which is a breaking change for anyone relying on abbreviations and so needs a release note, or keep abbreviations and document them in README `## Usage` next to the strict-parse paragraph.

### UX-10 — LOW — `--restart-container` (singular) vs `restartcontainers` (plural)

- **Location:** `src/traefik_certificate_exporter/libs/cli_args.py:81-90`
- **Lens:** L3
- **Evidence:** S01-004 made the key, env name and dest plural (`settings.restartcontainers`, `…_SETTINGS_RESTARTCONTAINERS`), and the flag stays singular. `--restart-containers` is the natural guess from the env name. It now gets a suggestion, but it still fails with exit 2.
- **Fix:** Add `--restart-containers` as a second option string on the same action. Keep the singular form for compatibility.

### UX-11 — LOW — Unknown-setting warnings are worded differently from legacy-setting warnings

- **Location:** `src/traefik_certificate_exporter/libs/legacy_settings.py:318-333`
- **Lens:** L3
- **Evidence:**
  - the legacy warning reads `Legacy setting X in environment is ignored; use Y`;
  - the unknown warning reads `Unknown setting X in environment; did you mean Y?`, without saying the value is ignored;
  - the no-match form, `Unknown setting X in environment matches no setting; …`, is self-contradictory.
- **Fix:** Use `Unknown setting X in environment is ignored; did you mean Y?` and `Unknown setting X in environment is ignored; it matches no setting (see …)`.

### UX-12 — LOW — Help-text copy defects, now regenerated verbatim into README

- **Location:** `src/traefik_certificate_exporter/libs/cli_args.py:54, 63, 79, 106, 114, 172` (pre-existing)
- **Lens:** L2, L3
- **Evidence:**
  - "The folder to exports the certificates in to";
  - "If specified, all certificates into a single folder";
  - "Added the resolvername in the path";
  - "If specified. certificates that match …";
  - `-fs GLOB` described as "file that contains the traefik certificates", where a glob pattern is meant;
  - mixed sentence case and lower case across entries.
- **Fix:** Edit the help strings once and regenerate `README.md` `## Usage`. The S01-008 derived test keeps the two in sync.

### UX-13 — LOW — `finish` messages are undocumented and go to a different stream from `run`'s

- **Location:** `docker/root/etc/s6-overlay/s6-rc.d/svc-traefik-certificate-exporter/finish` (echo and WARNING lines); `docker/README.md` `### Run once`
- **Lens:** L4, L5
- **Evidence:** `finish` prints `run-once pass finished with exit code N; stopping container`, and its two WARNINGs go to **stdout**. `run` sends its WARNING to **stderr**, deliberately (comment at `run:459-460`). The Run once docs never show the line the operator sees at the end of every scheduled run.
- **Fix:** Quote the `finish` line in `docker/README.md` `### Run once`. Send the `finish` WARNINGs to stderr, as `run` does.

### UX-14 — LOW — Typos in config-file keys stay silent while the same typos in env warn

- **Location:** `src/traefik_certificate_exporter/libs/legacy_settings.py:279-311` (unknown config keys are a recorded non-goal)
- **Lens:** L1, L3
- **Evidence:** `TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_WATCHFORCHANGE=false` gives `did you mean …WATCHFORCHANGES?`. The same typo as `watchforchange: false` in `config.yaml` is ignored with no message. Operators are told to fix config in either place.
- **Fix:** Open a backlog item to apply the same `suggest.nearest_name` check to unknown config keys (against `config_default.yaml` paths). Until then, state the asymmetry in `docs/operational.md` next to the legacy-name runbook.

## Observed, not raised

- Console output carries ANSI colour codes even when stdout is not a TTY. This was seen when piping the CLI, and `docker logs` sees the same under `CONSOLEONLY=true`. The behaviour predates this sprint and touches no reviewed story. It is a candidate for a `NO_COLOR` or TTY check in a later sprint.
- That run-once exit codes reflect start-up failures only is a recorded decision (ADR-0044, with a PRD #23 backlog key). The decision is documented consistently in both docs, so it is not raised.
