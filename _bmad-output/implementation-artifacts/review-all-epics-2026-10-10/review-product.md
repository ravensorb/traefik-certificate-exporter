# Whole-solution architecture conformance review — lens 1 of 3: PRODUCT architecture vs delivered code

- **Mode:** `l3io-arch-review` Mode B (architectural review), standards: core, python, docker, shell
- **Repository:** traefik-certificate-exporter @ `2139ad8` (branch `main`)
- **Date:** 2026-10-10
- **Authority:** `ARCHITECTURE-SPINE.md` (product, 2026-08-30; no `.memlog.md` exists), PRD 2026-08-30 (§3 FR, §4 NFR, §6 backlog), product ADRs 0001–0004, 0013, 0014, 0023–0027, 0030 (incl. 2026-10-10 amendment)
- **Baseline gate:** `just check` → exit 0. All pre-commit hooks passed (ruff, mypy, gitleaks, gitleaks-history, actionlint, zizmor, poetry lock check, hygiene); `pytest` 216 passed in 14.7 s.

## Verdict

**NOT CONFORMANT — 2 BLOCKER, 8 MAJOR, 11 MINOR.**

The internal engineering is mostly strong: per-pass correlation IDs, atomic writes, secret redaction and the
ADR-0030 privilege decision are implemented as recorded and tested. The end-to-end product story still breaks
in two places, and the green gate does not show either. (1) The Docker restart capability (FR-8) cannot work in
any shipped artifact. The locked `docker==6.1.3` SDK cannot talk to the Engine API with the locked
`requests==2.32.3` ("Not supported URL scheme http+docker"). Every restart test mocks `docker.from_env`, and the
production code catches the error and logs it, so the suite passes. (2) Setting the documented
`pkcs12passphrase` makes every PKCS12 export fail, because the passphrase is passed as the *PEM decryption*
password. Each affected domain then drops out of the "exported" list, so its restart, hook and notification are
silently skipped even though its PEM files rotated.

Beyond these, the product spine has gone stale relative to the code and to later ADRs. It still describes 3.19,
an unimplemented AD-4, a pre-ADR-0007 AD-5, a privilege model ADR-0030 has since replaced, and a layering the code
no longer follows. The operator-facing configuration surface also has several dead names: the CLI
`--restart-container`, README env names, `docker-compose.yml` env names, `LOGGINGLEVEL` and `CONFIGFILE`.

**Single most important action:** move to `docker` ≥ 7.1 and fix `PemToPfxConverter.export_to_pkcs12`'s
passphrase use. Add one unmocked SDK-construction test and one passphrase-set PFX round-trip test, so the gate can
see both defects.

## AD-by-AD conformance (product spine)

| AD / rule | Status | Evidence |
|---|---|---|
| AD-1 Poetry is the single dependency source | Conforms (with residue) | `pyproject.toml` `[tool.poetry.dependencies]`; Dockerfile installs from lock only (`docker/Dockerfile:40-43`). Residue: untracked, un-ignored `uv.lock` at repo root (`git status` `?? uv.lock`). Unused declared deps `requests`, `docker-pycreds` and `expandvars` (no import in `src/`), see m8 |
| AD-2 linuxserver base, digest pin, PUID/PGID drop | **Drift-recorded** (ADR-0030 + 2026-10-10 amendment), spine not updated | Base `3.24@sha256:…` pinned (`docker/Dockerfile:6`). Privilege is now "root unless proven" (`privilege-decision.sh:56-174`, init `run:83-139`, svc `run:156-170`). Spine AD-2 still says "PUID/PGID privilege drop at runtime" and "3.19 EOL tracked fix". ADR-0002 carries no "amended by 0030" marker |
| AD-3 Logging: structured file output, secrets never logged, `correlation_id` | Conforms (amended by ADR-0023, recorded) | Record factory `logging_utils.py:104-132`, per-pass ids `app.py:137-163` and `certificate_exporter.py:805,912,1021-1023`, hook env `post_export.py:186`. JSON file formatter `logging.yaml` `standard_detailed_formatter`/`extended_detailed_formatter`. Path-registry redaction `settings.py:34-41,97-114,381-418`. Gaps: m4 (hook command logged verbatim) and m7 (Apprise/urllib3 loggers disabled) |
| AD-4 Image from locked dependency set (`poetry install --only main`) | Conforms; spine text stale | `docker/Dockerfile:40-43,152`. Spine still says "Tracked fix … not yet implemented" |
| AD-5 One CI pipeline, no `ACT` branching | Drift-recorded (ADR-0005 superseded by 0007, then 0035/CI spine) | Out of scope for this lens. The product spine still states AD-5 as an open tracked fix |
| Convention: lowercase-dotted keys, `dest=` = config key, `TRAEFIK_CERTIFICATE_EXPORTER_` env prefix | **Drift-silent** | `cli_args.py:73` `dest="settings.restartcontainer"` vs config key `restartcontainers` (`config_default.yaml`, `settings.py:363`). `docker/README.md:138,144,150` and `docker/docker-compose.yml:7-15` document env names that nothing reads |
| Convention: ACME v1 + v2 (lower/upper) parsed; every export produces PEM + PKCS12 | **Partially conforms** | v2 detection is a substring test, `"acme-v02" in …["uri"]` (`certificate_exporter.py:335`), so a non-Let's-Encrypt CA store is treated as v1 and fails. PKCS12 fails whenever a passphrase is set (B2) |
| Convention: precedence CLI > env > file > default | Conforms | `settings.py:278-320` source order. Tests `tests/libs/test_settings_precedence.py:13-60` |
| Convention: global singletons | Conforms | `globalLogger`, `globalArgs`, `globalSettingsMgr` |
| Design paradigm: layered, domain (`certificate_exporter.py`) pure except the export write, depends only on logging | **Drift-silent** | `certificate_exporter.py:13-30` imports watchdog, `DockerManager`, `notify` and `post_export`, and hosts `AcmeCertificateFileHandler` (`:717-1065`). Spine diagram and capability map (FR7 → `app.py`) not updated; no ADR records the move |
| ADR-0013 (superseded) | Conforms (not implemented, as recorded) | No event bus in `src/` |
| ADR-0014 Apprise notifications on post-export | Conforms | `notify.py:9-86`; per-file scope on watch path `certificate_exporter.py:1053-1062` vs union on startup `app.py:148-155`, both stated |
| ADR-0023 per-drain correlation id + atomic writes | Conforms. Status still "Proposed" | `_atomic_write` `certificate_exporter.py:154-230` (same-dir temp, fsync, `os.replace`, dir fsync) |
| ADR-0024 atomic helper covers `.pfx` | Conforms. Status "Proposed" | `certificate_exporter.py:679` |
| ADR-0025 lenient import parse + strict `main()` parse | Conforms | `cli_args.py:154,157-167`, `app.py:82-83` |
| ADR-0026 None-safe `cancel()` | Conforms. Status "Proposed" | `certificate_exporter.py:818-898`, `app.py:186-197` |
| ADR-0027 vendored-tree framing in CODEOWNERS | Conforms (no product code impact) | — |
| ADR-0030 + 2026-10-10 amendment (root unless proven) | Conforms. Status "Proposed" | Rows 1–7 `privilege-decision.sh:79-173`. Pre-written `true` `init run:42`. Missing state = root `svc run:156`. Single WARNING in init. `find -xdev ! -type l -exec chown -h` `init run:129`. tmpfs HOME `init run:114-115`, `svc run:161`. 53 tests in `tests/test_s6_privilege_drop.py`. One inconsistency with the ADR's own principle, M5 |
| Restart cooldown (BL-E011-016) | **Drift-silent** (no ADR, not in spine/FR-8) | `docker.py:28,47-82,100-108`; documented only in `docs/operational.md:78-96`. Behaviour defect M6 |
| Symlink-replace semantics (BL-E011-009) | Conforms for the leaf; parent dir not covered | `certificate_exporter.py:166-174,124-134`; m5 |

## PRD capability trace

| Capability | Delivered end-to-end? | Evidence / break |
|---|---|---|
| FR-1 ACME v1/v2 parsing | **Partial** | LE v1/v2 work (`certificate_exporter.py:335-381`). Probe: a v2 store whose registration URI is not `acme-v02` (ZeroSSL, step-ca) → `KeyError 'DomainsCertificate'`, nothing exported. A resolver with `"Certificates": null` aborts the whole file → `exportCertificatesForFile` returns `None` after earlier resolvers already wrote files (M3) |
| FR-2 PEM + PKCS12 | **Broken with passphrase** | `certificate_exporter.py:625` `load_pem_private_key(key_data, password=passphrase)` → `TypeError: Password was given but private key is not encrypted` (probe-verified). No test sets a passphrase on the export path (B2) |
| FR-3 flat / per-domain layouts | Yes | `certificate_exporter.py:460-513` |
| FR-4 include/exclude, mutually exclusive on every source | Yes (PRD #10 delivered) | `settings.py:338-351`; `tests/libs/test_domains.py` |
| FR-5 resolver scoping / auto-detect | Yes (with M3 caveat) | `certificate_exporter.py:546-581` |
| FR-6 run-once / watch | **Yes for PyPI; not in container** | Container service starts only when the *env var* `…WATCHFORCHANGES` is `true`/`1` (`svc run:153`); otherwise the longrun exits and s6 respawns it (M5) |
| FR-7 debounce/coalesce | Yes | `certificate_exporter.py:703,772-807,901-981` |
| FR-8 Docker restart of labeled containers | **No (shipped lock)** | `docker==6.1.3` + `requests==2.32.3` (`poetry.lock`) → `DockerException … Not supported URL scheme http+docker` (probe). Caught at `docker.py:121-122`. CLI flag dead (M1). Cooldown drops restarts (M6) |
| FR-9 dry-run | Yes | `certificate_exporter.py:426`, `docker.py:111-119`, `post_export.py:169`, `notify.py:261` |
| FR-10 CLI/file/env config | **Partial** | Precedence correct; operator-facing names wrong (M1, M2); log level settable only by CLI, which the container cannot pass (M2) |
| FR-11 PyPI + Docker image | Yes | Dockerfile multi-stage, wheel hash contract `docker/Dockerfile:47-115` |
| Atomic writes (ADR-0023/0024) | Yes | `_atomic_write` plus stale-temp sweep `certificate_exporter.py:76-100` |
| Post-export hook | Yes, but fed by M4's under-reported domain list | `post_export.py`; called `app.py:142`, `certificate_exporter.py:1047` |
| Notifications (Apprise) | Yes; failure detail unobservable (m7) | `notify.py` |
| Logging / correlation / redaction | Yes (NFR-1, NFR-6) | AD-3 row |
| Config precedence | Yes | AD conventions row |
| Docker operator experience (first-run seed, privilege, docs) | **Partial** | Seed fixed (`init run:32-35`, NFR-7) but `docs/operational.md:100` still calls it a known bug. Compose/README env names dead (M2). No run-once (M5) |
| NFR-2 loud misconfiguration | Yes | `app.py:36-43,125`; strict argv `cli_args.py:157-167` |
| NFR-3 installable, no missing deps | Yes for imports; FR-8 runtime-incompatible (B1) | `cryptography` declared |
| NFR-5 regression suite | Exists (216 tests); blind to B1, B2 and M1 | All docker tests patch `from_env` (`tests/libs/test_docker.py:44,57`); fixtures use dummy PEM so a PFX failure is invisible (probe: LE v2 fixture → 4 PEM files, domain list `[]`) |

## Findings

| ID | Severity | Finding | Evidence | Remediation |
|---|---|---|---|---|
| B1 | BLOCKER | FR-8 container restart cannot work in any shipped artifact. The locked Docker SDK 6.1.3 is incompatible with locked requests 2.32.3. The failure is caught and logged as "Failed restarting containers", and every test mocks the client, so the gate is green. Meanwhile ADR-0030 keeps the process **root** precisely to serve this path. Core §7: `docker ^6.0.0` and `watchdog ^2.1.9` are superseded major lines | `poetry.lock` (`docker` 6.1.3, `requests` 2.32.3); probe → `DockerException: … Not supported URL scheme http+docker`; `docker.py:93,121-122`; `tests/libs/test_docker.py:44,57` | Raise to `docker = "^7.1"` (and review `watchdog` → current major); drop `docker-pycreds`. Add one unmocked test that constructs `docker.DockerClient(base_url="unix://<tmp>/missing.sock")` and asserts the error is a connection error, not a scheme error |
| B2 | BLOCKER | Setting `pkcs12passphrase` (documented in README, CLI help and config) breaks every PFX export. The passphrase is passed as the password for loading the *unencrypted* ACME PEM key. The domain is then omitted from the returned list after its PEMs were already rotated, so restart, hook and notification are skipped for it | `certificate_exporter.py:625` (`password=passphrase`), `:483-488,508-513,515,522-523`; probe → `TypeError: Password was given but private key is not encrypted`; no export test with a non-`None` passphrase (`tests/libs/test_certificate_exporter.py:45,335`) | Load the key with `password=None`; use the passphrase only for `BestAvailableEncryption`. Add a round-trip test: export with passphrase → `pkcs12.load_key_and_certificates(…, passphrase)` succeeds and the domain is reported |
| M1 | MAJOR | `--restart-container` sets an unread key. The CLI flag is dead; operators following README/`operational.md:63` get no restarts and no error | `cli_args.py:70-74` `dest="settings.restartcontainer"` vs `settings.py:363` `restartcontainers`; probe → `restartContainers=False` with the flag | Set `dest="settings.restartcontainers"`. Add a test deriving every `dest` from the parser and asserting each one is a key in `config_default.yaml` (scope derived, not enumerated — global rule 4) |
| M2 | MAJOR | Operator docs and compose file name env vars that nothing reads. The container log level cannot be changed at all, yet runbooks say `-ll DEBUG` | `docker/README.md:138` (`…_CONFIGFILE`), `:144` (`…_SETTINGS_RESTARTCONTAINER`), `:150` (`…_LOGGINGLEVEL`; no reader in `src/`); `docker/docker-compose.yml:7-15` (every env name lacks `SETTINGS_` / uses wrong keys, e.g. `…_RESTART_CONTAINERS`); `docs/operational.md:39`, `docker/README.md:115`; svc hard-codes argv `svc run:165,170` | Correct every name to `TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_<KEY>`. Add a `settings.logginglevel` (or honour an env key) so the container can raise verbosity. Add a test that parses the compose/README env names and checks each against `config_default.yaml` |
| M3 | MAJOR | ACME parsing is brittle at the resolver level. Version detection by `"acme-v02"` substring rejects non-LE CAs. A `null` `Certificates` resolver (Traefik writes this for a resolver with no certs) raises outside the per-cert `try`, failing the whole file and discarding domains from resolvers that were already written | `certificate_exporter.py:335,352-358,584-586`; probe: ZeroSSL URI → `KeyError 'DomainsCertificate'`; two resolvers with second `null` → returns `None`, 4 files on disk | Detect shape by keys (`Certificates` vs `DomainsCertificate`), not URI. Treat `None` as `[]`. Isolate errors per resolver so one bad resolver cannot discard another's reported domains. Add fixtures for both |
| M4 | MAJOR | The "exported domains" contract is not tied to what was written. A domain whose PEM files were atomically replaced but whose PFX failed, or any domain in a file aborted later (M3), is not reported, so restart, hook and notification are skipped while consumers' files changed | `certificate_exporter.py:460-515,522-523`; `__processPath` `:1045-1065` | Report a domain once its first artifact is replaced (or write the PFX to a temp before any rename and commit all five together). State the contract in ADR-0014/0023 |
| M5 | MAJOR | The container service re-parses `watchforchanges` from the raw env var with its own truthiness. This breaks ADR-0030's own principle ("ask the installed package, never a second parser"). Config-file `watchforchanges: false`, or env `false`, makes the s6 longrun exit and be respawned (no `finish`/`down` file): repeated export passes, notifications and hook runs, or a "Skipping start" loop. Run-once (FR-6) is unusable in the image | `svc run:153-174`; `svc-traefik-certificate-exporter/` contains only `run`, `type`, `dependencies.d`; init resolver already computes settings (`init run:49-81`) | Have init emit `watchforchanges` in the resolved-settings file and have the service read it. For run-once, exec the exporter then `s6-svc -O`/exit 125 from a `finish` script; document the container run-once contract |
| M6 | MAJOR | The restart cooldown drops, rather than defers, a restart. A second renewal touching the same container within 300 s is never followed by a restart until an unrelated later ACME write (often weeks), so the container serves a stale certificate. The cooldown has no ADR and is absent from spine/FR-8 | `docker.py:28,100-108` ("moves on", `operational.md:78-81`); grep of `docs/adr` for `BL-E011-016` → none | Record an ADR. Make a suppressed restart schedule one trailing restart at window expiry (coalesced per container), so the rate floor holds and no rotation is lost. Test: two passes inside the window → exactly one deferred restart |
| M7 | MAJOR | Silent layering drift. The domain module owns the watch handler and orchestrates adapters (Docker, hook, Apprise), which inverts the spine's "domain → logging only" layering. It is a three-job module (parsing/export, filesystem atomicity, watch orchestration) — Core §1 | `certificate_exporter.py:13-30,717-1065` (1065 lines); spine Design Paradigm + diagram + Capability map FR7 → `app.py` | Extract `AcmeCertificateFileHandler` plus the pass sequence (export → hook → notify → restart) into an orchestration module, and `_atomic_write*` into an I/O module. Or record the current shape in an ADR and update the spine |
| M8 | MAJOR | The product spine and `docs/architecture.md` contradict the code and later ADRs (Core §10 "docs that contradict the code"). The ADR table is hand-kept and admits it is unenforced (global rules 3/4), and it has already drifted | Spine: `updated: 2026-08-30`; AD-2 (3.19, no ADR-0030); AD-4 "not yet implemented"; AD-5 tracked fix; Stack (`watchdog`, `docker`, "cryptography not yet declared", `3.19`); Structural seed (no `notify.py`/`post_export.py`, "tests/ currently empty"). `docs/architecture.md:86-87` (3.19, "PUID/PGID privilege drop"); §2/§3 diagrams omit hook, notify, correlation, cooldown; ADR table lacks 0039 and the 0002←0030, 0003←0023 markers; ADR-0002 not marked amended | Run `bmad-architecture` update on the spine (AD-2 → ADR-0030 as amended, AD-4/AD-5 closed, Stack/Seed refreshed, paradigm per M7). Generate the ADR table from ADR headers, or add a test comparing it with `docs/adr/` |
| m1 | MINOR | `operational.md` states a fixed bug as current and mis-cites the backlog | `docs/operational.md:100-104` (seed is fixed at `init run:32-35`); `:108` "backlog item #15" (metrics is #21) | Delete the known-bug block; fix the citation |
| m2 | MINOR | Implemented ADRs still say `Status: Proposed` | 0003, 0023, 0024, 0026, 0027, 0030 headers | Set Accepted (with implementing story) |
| m3 | MINOR | PRD §4 "current state" (all Violated/Unmet) and §6 backlog (only #16/#19 struck) are stale | `prd.md:54-64,80-123` | Mark delivered items with the closing epic/story |
| m4 | MINOR | `postexportcommand` is logged verbatim at ERROR and in the DEBUG settings dump. A command that carries a token (e.g. `curl -H "Authorization: …"`) leaks it (NFR-1 spirit; the AD-3 allowlist does not cover it) | `post_export.py:200,207,211`; `SECRET_CONFIG_KEYS` `settings.py:34-41` | Log the executable name only (`argv[0]`), or add `("settings","postexportcommand")` to the registry |
| m5 | MINOR | The symlink-safety claim covers the leaf only. `_is_contained_within` checks the directory before writes, and the temp file plus `os.replace` follow a *parent* directory that can be swapped for a symlink in between. Relevant because the stock deployment now runs as root (ADR-0030 amendment) | `certificate_exporter.py:166-174` (docstring), `:444-454` then `:185-192,221` | Open the output directory with `O_DIRECTORY\|O_NOFOLLOW` and write relative to the dir fd (`dir_fd=`), or narrow the docstring's claim |
| m6 | MINOR | The pass sequence is duplicated (export → hook → notify → restart) with divergent guards — Core §2 | `app.py:141-161` vs `certificate_exporter.py:1045-1065` | One `run_export_pass(domains, scope)` helper used by both |
| m7 | MINOR | `disable_existing_loggers: True` disables the `apprise` and `urllib3` loggers (imported before `dictConfig`). Apprise's per-destination failure detail is never emitted, and the comment claiming Apprise "logs the specifics itself" is false | `logging.yaml` `disable_existing_loggers: True`; `notify.py:288-290`; probe → `apprise disabled=True` | Set `disable_existing_loggers: False` and route `apprise` at WARNING through the redacting path (Apprise messages can include URLs), or correct the comment |
| m8 | MINOR | Declared but unused runtime deps (`requests`, `docker-pycreds`, `expandvars`), plus a stray untracked `uv.lock` contradicting ADR-0001 | `pyproject.toml`; no imports in `src/`; `git status` `?? uv.lock` (not ignored) | Remove the deps; delete `uv.lock` or add it to `.gitignore` |
| m9 | MINOR | Stale or dead text | `cli_args.py:19` (`-c` help "the path to watch for changes"); `svc run:173` (`# env \| sort`); `certificate_exporter.py:380` ("not sure what this is"); `sans` extracted only for a log line (PRD #22 undecided); `docker/README.md:74,122` (`-v` after the image name is passed to the app, not docker); `docker-compose.yml:1` obsolete `version:` | Fix/remove; decide PRD #22 |
| m10 | MINOR | No `HEALTHCHECK` or liveness signal (Docker overlay runtime posture). Deferred by PRD §5/#21 but not ADR-recorded | `docker/Dockerfile` (none); `operational.md:106-110` | Record the deferral in an ADR, or add a heartbeat-file HEALTHCHECK |
| m11 | MINOR | Shell overlay: s6 scripts use `with-contenv bash` without `set -euo pipefail`. This is deliberate for the fail-safe flow (the helper documents it), but the scripts do not record why at the top | `init run:1-2`, `svc run:1-2`, `privilege-decision.sh:19-20` | Add a one-line rationale to the two run scripts (fail-safe-to-root needs explicit, not `-e`, error handling) |

**Counts:** BLOCKER 2 · MAJOR 8 · MINOR 11.

## Per-principle walkthrough

- Core §1 Separation of concerns — M7.
- Core §2 Reuse — m6.
- Core §3 Design by contract — B2, M3, M4 (the exported-domain postcondition is undefined). Boundary validation of untrusted names passes (`certificate_exporter.py:272-317`).
- Core §4 Testability — B1, B2, M1 (mocks hide the integration seam; no config-key/`dest` contract test). Global singletons are the recorded project convention.
- Core §5 Brevity — PASS. Heavy commentary in places, but it explains intent.
- Core §6 Comments — m7 (false comment), m9. Several comments narrate history ("An earlier version…", `certificate_exporter.py:942-948`, `logging_utils.py:220-227`), which this section discourages. MINOR, folded into m9.
- Core §7 Dependencies — B1, m8.
- Core §8 GA only — PASS (no pre-release deps found in `pyproject.toml`).
- Core §9 Logging/correlation — AD-3 conforms; m4, m7.
- Core §10 Documentation — M2, M8, m1, m2, m3.
- Python overlay — PASS on Poetry, lock, mypy and ruff (gate green); m8.
- Docker overlay — digest pin PASS; multi-stage PASS; non-root USER → recorded exception (ADR-0002/0030); exec-form/s6 PASS; HEALTHCHECK m10; logs to stdout PASS (CONSOLEONLY).
- Shell overlay — quoting/structure PASS (helper is function-structured and tested); m11.

## Gate

BLOCKER and MAJOR items (B1, B2, M1–M8) must be resolved or ADR-justified before sign-off. MINOR items defer to the backlog.

## Recommended ADRs

1. Restart-cooldown semantics (drop vs trailing restart; per-container window) — M6.
2. Module layering after the watch handler moved into `certificate_exporter.py` (or the extraction) — M7.
3. Exported-domain reporting contract under partial failure — M4.
4. Container run-once / `watchforchanges` source of truth in the s6 service — M5.
5. Health/liveness deferral — m10.

## Assumptions

- B1 was verified by constructing a `DockerClient` against a non-existent unix socket in the project venv. The `http+docker` scheme error is raised before any connection attempt (the known docker-py/requests 2.32 incompatibility), so it applies with a real socket too. A live Docker daemon was not used.
- M5's respawn behaviour relies on s6-overlay longrun semantics (a `run` that exits is restarted by `s6-supervise` unless a `finish` script returns 125 or a `down` file exists). It was not executed in a container.

Sections read: SKILL.md (Mode B), references/review-report.md, standards-core.md §1–10, standards-python.md checklist, standards-docker.md runtime + checklist, standards-shell.md checklist; ARCHITECTURE-SPINE.md (full); prd.md §3–§6; ADR headers 0001, 0002, 0003, 0004, 0013, 0014, 0023, 0024, 0025, 0026, 0027, 0030 (Decision + 2026-10-10 Amendment in full), 0039 status; src/: app.py, libs/certificate_exporter.py, cli_args.py, settings.py, docker.py, post_export.py, notify.py, logging_utils.py, object.py, config_default.yaml, logging.yaml; docker/Dockerfile, privilege-decision.sh, init-traefik-certificate-exporter-config/run, svc-traefik-certificate-exporter/run, docker-compose.yml, config.yaml.sample, docker/README.md §env/compose/privilege; docs/architecture.md §1–6; docs/operational.md §runbooks, first-run, monitoring, privileges (grep-level); README.md (grep-level); pyproject.toml deps, poetry.lock versions; tests (names and fixtures only); `just check` output.
