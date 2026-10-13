# UX review — E015 sprint 01 (operator-facing surface)

- Date: 2026-10-12
- Skill: `bmad-ux`, Reviewer Gate, headless, review only (no DESIGN.md / EXPERIENCE.md; the
  caller restricted output to this file, so the skill's `validation-report.{md,html}` was not written)
- Scope: `git diff HEAD -- src/traefik_certificate_exporter README.md docker/README.md docs/operational.md docs/upgrading.md config.sample.yml src/traefik_certificate_exporter/config_default.yaml`
- Stories: E015-S01-001 (root-mode trust), E015-S01-002 (`validatekeys`, `.pfx` fingerprint sidecar), E015-S01-004 (pre-confuse env warnings)
- Surface reviewed: start-up ERROR / WARNING / INFO wording, CLI flags and config keys, operator docs, upgrade notes
- Out-of-diff files read to verify one claim each: `docker/Dockerfile:126-127` (image ENV sets `..._DATAPATH`/`..._OUTPUTPATH`),
  `docker/root/defaults/config/config.yaml.sample`

## Result

| Severity | Count |
|---|---|
| HIGH | 0 |
| MEDIUM | 4 |
| LOW | 6 |

No secret values are logged. The withheld-setting ERROR names the key, the file and the env var, never the value. The `.env` ERROR lists only names. The filespec ERROR leaves out the rejected value. The legacy WARNINGs print only the name. The hook INFO line prints `set`/`not set` and never prints the command. Key and env naming is consistent: `settings.validatekeys`, `TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_VALIDATEKEYS`, and `--no-validate-keys` maps to `dest="settings.validatekeys"`. The diff breaks no LinuxServer.io convention. It brings the docs in line with LSIO practice: `/config` is owned by `PUID`/`PGID` via `init-adduser`. The image ENV supplies `datapath`/`outputpath`, so a stock `/config/config.yaml` that copies `/data` and `/certs` from the sample does not trigger the root-mode ERROR.

## Findings

| ID | Severity | Location | Finding | Fix |
|---|---|---|---|---|
| UX-1 | MEDIUM | `src/traefik_certificate_exporter/libs/settings.py` `_validatedFileSpec` (ERROR "Ignoring settings.filespec from …") | The ERROR states the rule and that `*.json` is used, but not how to keep exporting the store the operator meant. Operators who had an absolute `filespec` (the case this targets) get no remedy at the point of failure. The remedy ("set `datapath` to its directory and `filespec` to its name") is only in `docs/upgrading.md`. In root mode `datapath` must also come from the environment, which the message does not say either. Falling back to `*.json` can also pick up other `.json` files in the data path without any notice. | Append: "Put the directory in settings.datapath (TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_DATAPATH; from the environment when running as root) and only the file name in settings.filespec." |
| UX-2 | MEDIUM | `docs/upgrading.md` 0.3.0 → 0.3.1 ".env" bullet; `docs/operational.md` "Trust boundary" 2nd bullet | "may set only `any-source` settings" uses an internal code term (`ROOT_TRUST_ANY_SOURCE`) that no operator doc defines. The operator can't tell which `.env` variables will survive in root mode. | Replace it with the operator-facing rule: "every `TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_*` variable except `…_POSTEXPORTCOMMAND`, `…_OUTPUTPATH` and `…_DATAPATH`". Or list the allowed keys once in operational.md and link to that list. |
| UX-3 | MEDIUM | `docker/README.md` (no link to `docs/upgrading.md`) | The biggest behaviour change in this sprint is root mode ignoring a `config.yaml` hook, and it hits container operators. `docker/README.md` is the Docker Hub page, and it never links the upgrade notes. Only `README.md:195` does. Container operators reading Docker Hub won't find the 0.3.0 → 0.3.1 action items. | Add the same "Upgrading from an earlier release: docs/upgrading.md" line to `docker/README.md`, using an absolute GitHub URL because relative links break on Docker Hub. Place it near the new `/config` ownership paragraph. |
| UX-4 | MEDIUM | `settings.py` `_ROOT_WITHHELD_MESSAGE` ("Using the {fallback} value instead") | When `fallback` is `default`, the message doesn't say which value is now in effect. For a PyPI root install the packaged default is the relative `./data` / `./certs` (`config_default.yaml:4,6`), so the exporter silently moves its data or output location to the working directory. The operator only finds out from the later `Data Path:` / `Output Path:` lines, if at all. | For `datapath`/`outputpath` (paths, not secrets), include the effective value: "Using the default value './certs' instead". For `postexportcommand`, say "the hook is not run" rather than "Using the default value". |
| UX-5 | LOW | `settings.py` `_ROOT_WITHHELD_MESSAGE` ("or pass the command-line flag") | The message doesn't name the flag. Inside the container no flag can be passed at all (`docker/README.md` says "the container cannot take -ll"), so that half of the advice is a dead end for the main audience. | Name the flag per key (`--post-export-command`, `-o/--output-path`, `-d/--data-path`) and drop the flag clause when running in the image. Alternatively, phrase it as "or, outside the container, pass `<flag>`". |
| UX-6 | LOW | `docker/README.md` new `/config` paragraph ("only from the container's environment or the command line") | Same issue as UX-5, in the docs: "the command line" isn't available to a container operator. | Say "only from the container's `environment:`" in `docker/README.md`. Keep "or the command line" in operational.md and the PyPI bullet of upgrading.md. |
| UX-7 | LOW | `app.py` hook INFO line | `Post-export command: not set (source: default), runs as uid 0` reads as if something runs as root when nothing does. That can alarm someone auditing the RT-1 replay. | When not set, end with "…, would run as uid 0", or leave out the uid clause. If the AC wording is binding, leave the line as it is and note this in operational.md. |
| UX-8 | LOW | `legacy_settings.py` pre-confuse rows (WARNING "Legacy setting FLAT in environment is ignored; use …") | The 0.0.x names were presence-based (`FLAT=false` meant on). The WARNING points to the replacement but not to that change in meaning. Only `docs/upgrading.md` explains it. An operator who copies the value across keeps today's behaviour, which differs from what 0.0.x did, without knowing it. | Give the boolean rows (`DRYRUN`, `FLAT`, `RESTART_CONTAINERS`, `RUN_AT_START`, `TRAEFIK_RESOLVERID_INOUTPUTPATHNAME`) a hint suffix such as "…; set it to true or false explicitly (0.0.x treated any value as on)". |
| UX-9 | LOW | `docker/root/defaults/config/config.yaml.sample` (not in diff) vs `config.sample.yml` | `config.sample.yml` gained `# validatekeys: true`, but the image's LSIO default sample, the one copied to `/config/config.yaml` on first run, did not. Container operators who edit `config.yaml` won't find the new setting there. | Add the same commented `# validatekeys: true` line to the image sample. Do not add `postexportcommand` there, since it is ignored in root mode. |
| UX-10 | LOW | `README.md` / `cli_args.py` `--no-validate-keys` help | "Only when the ACME store is written by your own Traefik" is a sentence fragment. It reads as if it describes when the flag works, not when it is safe to use. | Change it to "Use only when the ACME store is written by your own Traefik: …" in the help text, which is mirrored in README.md, and in the `config.sample.yml` / `config_default.yaml` / `docker/README.md` comments. |

## Assumptions

- Confuse gives the environment priority over the config file, so the image ENV (`docker/Dockerfile:126-127`) wins over a `config.yaml` `datapath`/`outputpath`, and the root-mode ERROR never fires for a stock container config. This follows from `set_env` being added after the config source, and the story's ACs rely on it. It was not re-tested here.
- The INFO (not WARNING) level for `RSA key validation: off` follows story E015-S01-002 AC 14 and is not raised as a finding.
