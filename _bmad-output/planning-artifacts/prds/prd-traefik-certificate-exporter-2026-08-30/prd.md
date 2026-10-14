---
title: 'traefik-certificate-exporter PRD'
status: final
target: '0.3.1'
created: '2026-08-30'
updated: '2026-10-14'
---

# Product Requirements Document — traefik-certificate-exporter

> **Target: 0.3.1 — reflects requirements after epic E015.** Updated 2026-10-14.
>
> Each requirement states the intended behaviour for 0.3.1. Its status is one of:
> **Done in 0.3.0** (released, unchanged by E015), **New in 0.3.1 — &lt;story&gt;** or
> **Changed in 0.3.1 — &lt;story&gt;** (delivered by that planned E015 story), or **Deferred**
> (with the reason). 0.3.1 is a patch release (`just release patch`, maintainer decision MD-18):
> the one new setting defaults to the 0.3.0 behaviour, and the root-mode change is a security fix.
>
> **Location note:** this lives under `{planning_artifacts}/prds/prd-traefik-certificate-exporter-2026-08-30/`,
> the canonical `bmad-prd` run-folder location, not `/docs`. PRDs are planning artifacts and
> are not part of the permanent docs skeleton in [docs/README.md](../../../../docs/README.md).
> Binding design rules live in [docs/adr/](../../../../docs/adr/), the product spine
> (`_bmad-output/planning-artifacts/architecture/architecture-traefik-certificate-exporter-2026-08-30/`)
> and the CI/CD spine (`_bmad-output/planning-artifacts/architecture/architecture-ci-cd-pipeline-2026-10-08/`).
> Maintainer decisions for 0.3.1 are recorded in
> [maintainer-decisions.md](../../../implementation-artifacts/epic-015/maintainer-decisions.md).
>
> **Changelog**
>
> - 2026-08-30: baseline reverse-engineered from v0.1.3 and the
>   [architectural review](../../../implementation-artifacts/review-report.md).
> - 2026-10-11: refreshed to the 0.3.0 target (E014). FR-12 to FR-17 added; §6 backlog replaced
>   by a pointer and a closed-items table.
> - 2026-10-12: consolidated to the 0.3.1 target (E015). Sources: the E015 stories in
>   [sprint-01](../../../implementation-artifacts/epic-015/sprint-01/stories/) and
>   [sprint-02](../../../implementation-artifacts/epic-015/sprint-02/stories/);
>   [research brief 2026-10-12](../../research/research-2026-10-12-release-0.3.1.md);
>   maintainer decisions MD-06 to MD-23 accepted 2026-10-12 (MD-01 to MD-05 withdrawn);
>   E014 closure report and spec proposals AD-1/AD-2
>   (`_bmad-output/implementation-artifacts/epic-014/epic-closure/`); ADR-0040 to ADR-0048.
>   FR-2, FR-6, FR-10, FR-14, FR-15, FR-16, FR-17, NFR-1, NFR-2, NFR-4, NFR-5 restated;
>   FR-18, FR-19, NFR-8, NFR-9, NFR-10 added; FR/NFR ids unchanged; §6 gains the 0.3.1 open
>   risks and deferred items. Status is now relative to the released 0.3.0.
>
> - 2026-10-12 (E015 epic architecture gate, AG-1/AG-2/AG-4/AG-6/AR-1; maintainer decision
>   2026-10-12 extending MD-21): FR-10 and FR-18 gain `datapath` as environment-only when root
>   and `filespec` validation in every mode; FR-11 and FR-18 require `/data:ro` in both modes;
>   FR-18 names ADR-0049/ADR-0050 and states what is reviewed rather than checked; NFR-8 makes
>   load counts the gate and wall time a relative bound; §6 gains AR-1.
>
> - 2026-10-14 (maintainer decisions MD-24/MD-25, from D1/D2 of 2026-10-13/14): FR-10 states
>   `.env` as a standalone-CLI convenience (cwd only, `settings.loaddotenv`, off in the image);
>   FR-18 states the root-mode `.env` rule (ratified; supersedes BL-E015-052), `loaddotenv` as
>   environment-only in every mode, and the `appriseurls` accepted residual risk; §6 gains the
>   `appriseurls` row. Target 0.3.1, delivered by E015-S02-005.

## 1. Purpose

Traefik stores ACME certificates for all managed domains inside a single
`acme.json`/`acme-*.json` file, keyed by resolver, in a Traefik-internal JSON shape. Many
tools downstream of Traefik (other reverse proxies, mail servers, monitoring stacks, manual
inspection) need the certificate and private key as **plain PEM/PFX files on disk**.
`traefik-certificate-exporter` watches Traefik's ACME store and extracts every managed
certificate to a configurable output directory in PEM and PKCS12 form. When a certificate
changes it can restart the Docker containers that depend on it, run a post-export command,
and send notifications.

## 2. Users

- Self-hosters and homelab operators running Traefik as their ingress/reverse proxy.
- Operators who run a second service (mail, VPN, internal dashboards) that needs the same
  certificate Traefik obtained, in a format that service can consume.
- The maintainer and fork owners who cut releases to their own set of package and image
  destinations.

## 3. Functional requirements

| ID | Requirement | Status (target 0.3.1) |
|---|---|---|
| FR-1 | Parse Traefik ACME stores of both the legacy (v1, `DomainsCertificate.Certs`) and current (v2, `Certificates`) shapes, detecting the shape from the store's keys, not from the CA URL, so certificates from any RFC 8555 CA are exported. Empty resolvers (`"Certificates": null`, `"Account": null`) are tolerated. Invalid JSON fails the file; invalid base64 fails only the affected certificate. One resolver's failure does not drop the other resolvers' domains. | Done in 0.3.0 |
| FR-2 | For each domain, export the private key, leaf certificate, chain (intermediates only; empty for a single-certificate chain), full chain, and a PKCS12 (`.pfx`) bundle that carries the intermediates. The whole artifact set is built before any file is replaced, and each file is replaced atomically. An artifact whose content is unchanged is not rewritten. PEM files are compared by bytes. The `.pfx` is judged by a fingerprint file beside it, `<pfx>.fingerprint.json` (SHA-256 of the `.pfx` file, SHA-256 of the key PEM, the ordered SHA-256 certificate fingerprints, and a salted scrypt hash of the passphrase); it counts only when its `.pfx` hash matches the file on disk. A missing or unusable fingerprint file, or one whose recorded `.pfx` hash does not match the file, falls back once to a content comparison of the `.pfx`; one whose recorded inputs (key, certificates, passphrase) differ from the store's rebuilds the `.pfx` without opening it; a missing, truncated or otherwise damaged `.pfx` is rebuilt and its domain reported. Over output written by 0.3.0 the first pass verifies each `.pfx` once by content and writes only its fingerprint file: no artifact is rewritten and no domain is reported. A domain is reported as exported if and only if at least one of its artifacts changed and was replaced in this pass; writing only a fingerprint file never reports a domain. | Changed in 0.3.1 — E015-S01-002 |
| FR-3 | Support a flat layout (`{name}.crt` etc. in one folder) and a per-domain subfolder layout (`{name}/cert.pem` etc.). | Done in 0.3.0 |
| FR-4 | Filter exported domains by an include-list or an exclude-list, mutually exclusive across every configuration surface (CLI, environment, config file). | Done in 0.3.0 |
| FR-5 | Optionally scope processing to one named Traefik certificate resolver; otherwise detect every resolver node in the store. | Done in 0.3.0 |
| FR-6 | Run one export pass at start and/or watch the data path. In watch mode a pass is triggered by a file created or modified under a name matching `filespec`, or by a file renamed onto such a name (an atomic write-then-rename, a restore from backup, an editor save). A store renamed away to a non-matching name is logged at INFO and not exported, and its exported files are left in place. The watch is not recursive and directory events are ignored. When watching is off, the container image runs one pass and exits with that pass's exit code (0, or 1 for a missing data path); export failures are logged at ERROR and do not change the exit code. When both run-at-start and watch are off, one WARNING says there is nothing to do. | Changed in 0.3.1 — E015-S01-003 |
| FR-7 | Coalesce rapid repeated filesystem events for the same file into one export pass. | Done in 0.3.0 |
| FR-8 | Optionally restart the running Docker containers labeled with an exported domain name, through the Docker Engine the process is connected to (`DOCKER_HOST` or the default socket; the Docker CLI context is ignored; Engine API 1.24 or newer). When restarts are enabled, the Engine is checked once at start-up: INFO on success, one ERROR naming the endpoint on failure, and exporting continues either way. Each container is restarted at most once per 300 s (`RESTART_COOLDOWN_SECONDS`, not configurable); a restart that the floor denies is deferred to one trailing restart, never dropped. Which containers are restarted is governed by FR-15. | Done in 0.3.0 |
| FR-9 | Support a dry-run mode that builds and compares every artifact in memory, logs the intended actions, writes no file (fingerprint files included) and restarts no container, and reports a domain only when its build succeeded and at least one artifact would change. | Done in 0.3.0 |
| FR-10 | Configurable via CLI flags, a YAML config file and environment variables, with precedence CLI > environment > config file > packaged default for every setting. Every documented CLI flag and environment name reaches the setting it names (`TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_<KEY>`). The log level can be set by `-ll` or by `TRAEFIK_CERTIFICATE_EXPORTER_LOGGING_LEVEL`; an invalid value falls back to INFO with one WARNING, and one INFO line names the effective level and its source. **Root-mode trust (FR-18) is not a precedence change.** The order above holds in every mode. When the exporter runs as root, a value for `postexportcommand`, `outputpath` or `datapath` that comes from a file (the config file, the confuse user config, or a `.env` file) is not admissible; the setting then resolves by the same order over the remaining sources (CLI, environment, packaged default). Whenever the CLI or the environment sets the key, the result is the one plain precedence gives; only a value that would have won from a file is replaced, by the next non-file source. For these three keys in root mode, a `.env` file counts as a file, not as the environment. **`filespec` is a file-name glob inside the data path, in every mode.** A value from any source that is empty, contains `/` or `\`, is exactly `.` or `..`, or is absolute (or carries a drive) is rejected at load with one ERROR naming the setting and its source, never the value, and the packaged default `*.json` is used instead; this is validation of the value, not a precedence change (ADR-0049). **`.env` files are a standalone-CLI convenience.** When `settings.loaddotenv` is true (the default), the `.env` in the current working directory is loaded into the environment before the sources are merged, so its values rank as the environment; no other `.env` is read (not the installed package's folder, not the configuration file's directory). `settings.loaddotenv` itself is taken only from the environment (`TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_LOADDOTENV`) or the CLI (`--no-dotenv`), never from a file, in every mode (FR-18). The container image sets it `false`, so the image reads no `.env`; Docker's `env_file:` is applied by Docker and is the environment (MD-24). | Changed in 0.3.1 — E015-S01-001 (root-mode qualification and `filespec` validation; the precedence order is unchanged); `.env` switch and single `.env` location: Target 0.3.1, delivered by E015-S02-005 |
| FR-11 | Ship as a PyPI package and as a multi-architecture (`linux/amd64`, `linux/arm64`) Docker image on the linuxserver.io base with s6-overlay and `PUID`/`PGID`. In the image the exporter runs as **root unless the ACME store is proven readable by the `PUID`/`PGID` service account**: it drops to that account only when, at container start, the settings resolve, `restartcontainers` is off, the data path is listable, at least one `filespec` match exists and every match is readable by the account, and the output path is writable by it. Anything else keeps root, with exactly one start-up WARNING naming the reason, the files and the remedy (run Traefik as the `PUID`/`PGID` user). The decision is taken once per container start. The unprivileged mode requires `/data` mounted read-only (`/data:ro`); from 0.3.1 root mode requires it too (FR-18). | Done in 0.3.0 (`/data:ro` in root mode: E015-S01-001, documentation) |
| FR-12 | Optionally run an operator-configured post-export command (`postexportcommand`) after a pass in which at least one domain changed, passing only the changed domains in `TRAEFIK_CERTIFICATE_EXPORTER_EXPORTED_DOMAINS`. Nothing runs when no domain changed. The command is treated as a secret: logs name only its program, never its arguments. Which sources may set it when the exporter runs as root, and which uid runs it, is FR-18. | Done in 0.3.0 (root-mode sources: FR-18) |
| FR-13 | Optionally send export notifications through Apprise to a list of operator-configured URLs (`appriseurls`), after a pass in which at least one domain changed, listing only the changed domains. Nothing is sent when no domain changed. The URLs are credentials and are redacted from every settings dump. | Done in 0.3.0 |
| FR-14 | Protect the PKCS12 bundle with an optional passphrase (`pkcs12passphrase`). A non-empty passphrase yields an AES-256/SHA-256 encrypted bundle; an empty or unset passphrase yields an unencrypted bundle. Changing the passphrase (unset to set, set to another value, set to unset) rewrites only the bundle and its fingerprint file and reports the domain; the change is detected from the fingerprint file without opening the bundle. | Changed in 0.3.1 — E015-S01-002 |
| FR-15 | Restart a labeled container only when a certificate it serves changed after it started: on every pass, including the start-up pass and passes in which nothing changed, a container is restarted when the newest exported artifact of its labeled domains is more than 2 s newer than the container's start time. An exporter restart over an unchanged store restarts nothing; a restart lost to a crash or shutdown is recovered on the next pass. The `.pfx` fingerprint file is not an exported artifact: it never moves the restart time. | Changed in 0.3.1 — E015-S01-002 (fingerprint file excluded) |
| FR-16 | At start-up, warn about legacy or misspelled setting names (environment and config file), naming the replacement, and ignore the old name; warn once about unknown `TRAEFIK_CERTIFICATE_EXPORTER_*` environment variables with the nearest valid name. The legacy names include the eleven environment names of the pre-confuse 0.0.x image (`TRAEFIK_FILESPEC`, `TRAEFIK_RESOLVERID`, `TRAEFIK_RESOLVERID_INOUTPUTPATHNAME`, `DRYRUN`, `FLAT`, `RESTART_CONTAINERS`, `DOMAINS_INCLUDE`, `DOMAINS_EXCLUDE`, `RUN_AT_START`, `CONFIG_FILE`, `TEST_VERSION`), matched exactly and case-sensitively; they are never aliased and never reported as unknown, and any other unprefixed variable produces nothing. Values are never logged. | Changed in 0.3.1 — E015-S01-004 |
| FR-17 | Publish each tagged release to every destination configured on the forge that runs it: the PyPI and Gitea package indexes, the GHCR, Docker Hub and Gitea container registries, and the forge release with the wheel and sdist attached; dev builds publish to TestPyPI and the Gitea package index and to the same three registries. The same workflows run on GitHub, self-hosted Gitea and local `act`. A destination is enabled only when its token and every variable it needs are set; a partly configured destination is skipped with one warning naming what is missing; an unconfigured one is silent. GHCR (on GitHub) and the forge release use the workflow's own token unless a `PUBLISH_*` token overrides it. GitHub is the release forge: its `dev`/`release` environments hold the publish settings, with tokens kept in Infisical; `just act` passes no secrets and publishes nothing. Releases are cut only from protected `v*` tags on `main`. Images are tagged `X.Y.Z`, `X.Y` and `latest` (`latest` only for the highest release tag); no bare `:0` tag is written for 0.x releases. | Changed in 0.3.1 — E015-S02-002 (job token for GHCR and the forge release, simplified 2026-10-14, MD-26), E015-S02-004 (first release proving it) |
| FR-18 | **Root-mode settings trust.** When the exporter runs as root (euid 0), the settings whose value root executes, writes to, or trusts as the source of what it writes, `postexportcommand`, `outputpath` and `datapath`, are taken only from the environment, the command line or the packaged default. A value for any of them from a file (the config file, the confuse user config, or a `.env` file) is ignored, with one ERROR per setting at every start naming the setting and the file, never the value, and naming the environment variable to use instead; exporting continues. Every other setting may come from any source; `filespec` may because it is validated as a file-name glob inside the data path in every mode (FR-10), so it cannot point root at a store outside `datapath`. The ACME store and its directory must not be writable by the `PUID` account in either mode (`/data:ro`); a writable store directory in root mode is a documented residual risk, not enforced. Every key of the settings registry has a declared root-trust class, and an unclassified key fails the test suite. Setting the hook in the environment or on the command line is the opt-in for a root hook, which runs with the exporter's uid; in unprivileged mode a config-file hook runs as the `PUID` account. One start-up INFO line states whether a hook is set, its source and the uid it runs as. The post-export command is the only process the package spawns, enforced by ruff's banned-api rule over first-party source (ADR-0050; dynamic imports are not covered). The `any-source` classifications are reviewed claims (availability effects only), not mechanically checked. The LinuxServer base image's init and ownership conventions are unchanged: `/config` stays owned by `PUID`/`PGID` and editable by that account. This is a trust rule, not a precedence change (FR-10). **`.env` in root mode (a CLI run as root):** a `.env` file may contribute only the environment names of `any-source` settings; every other name it adds is removed, with one ERROR per file listing the names, never values; `${VAR}` is not expanded (ADR-0049 amendments 2026-10-12, ratified by MD-24). **`settings.loaddotenv` is environment-only in every mode** (third trust class, `environment-only-in-every-mode`): a value from the config file, the confuse user config or a `.env` file is ignored with one ERROR naming the setting and the file, whether or not the process is root. The image sets it `false`; a `.env` present in the working directory or beside the configuration file is then not read, and one start-up WARNING says so, never its contents (MD-24). **Accepted residual risk (MD-25):** `appriseurls` stays `any-source`, but its reach is not "egress only": Apprise `json://`, `xml://` and `form://` can send a request with a chosen method, path and headers to any host the container reaches, so a POST to a docker-socket-proxy's container endpoints, such as `/containers/<id>/stop`, which needs no body, can stop a container. Decision record: ADR-0049. | New in 0.3.1 — E015-S01-001; root-mode `.env` rule, `loaddotenv` and the `appriseurls` rationale: Target 0.3.1, delivered by E015-S02-005 |
| FR-19 | **Optional RSA key validation.** `settings.validatekeys` (env `TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_VALIDATEKEYS`, CLI `--no-validate-keys`), default `true`. When false, private keys are loaded without RSA validation; this is for stores written by the operator's own Traefik only. The check that a key matches its certificate runs in both modes, and a mismatching entry is not exported (one ERROR, existing files untouched). A private key is loaded only when a `.pfx` is built or verified, at most once per domain per pass. One start-up INFO line states `RSA key validation: on` or `off`. The setting may come from any source, root mode included (FR-18). | New in 0.3.1 — E015-S01-002 |

## 4. Non-functional requirements

| ID | Requirement | Status (target 0.3.1) |
|---|---|---|
| NFR-1 | Never write certificate private keys, PKCS12 passphrases, Apprise URLs, the post-export command or other configured secrets into logs, including the DEBUG settings dump, warnings about setting names, the root-mode ERROR and the start-up hook-source line. The `.pfx` fingerprint file is written mode 0600 and holds no passphrase and no key bytes, only hashes. | Changed in 0.3.1 — E015-S01-001, E015-S01-002 (new surfaces covered) |
| NFR-2 | Signal misconfiguration loudly instead of continuing silently: a missing data path fails the run; an unreachable Docker Engine, a legacy (including pre-confuse) or unknown setting name, an invalid log level, a configuration with nothing to do, and a file-sourced `postexportcommand` or `outputpath` in root mode each produce a start-up ERROR or WARNING. | Changed in 0.3.1 — E015-S01-001, E015-S01-004 |
| NFR-3 | `pip install traefik-certificate-exporter` works on every Python version in the declared range (`>=3.10,<3.15`) with no missing imports: every module `src/` imports is a declared dependency, every declared dependency is used, and no package in any `poetry.lock` group, optional groups included, nor in any hashed CI bootstrap file under `.github/requirements/`, carries a known advisory (`pip-audit` gates, ADR-0042). Packages a lock entry restricts by environment marker to another platform or Python minor are outside the gate (BL-E014-023). | Done in 0.3.0 (range ends re-verified at release by E015-S02-004) |
| NFR-4 | Every tagged release is built once (one wheel, one sdist, one multi-architecture image), and that build is published to every enabled destination (FR-17). A skipped, partly configured destination does not fail the run. Not a mechanical gate; per-release checklist steps: each intended destination `enabled` exactly once with zero partial-configuration warnings, and zero `Unexpected input` lines in the run log. 0.3.0's Gitea image is a separate build and is left as published (MD-26). | Changed in 0.3.1 — E015-S02-002, E015-S02-004 |
| NFR-5 | Regressions in ACME parsing, export, restart and container lifecycle are caught before release: the unit suite runs in `just check` and CI, and each release records a passing run of the opt-in integration tests (real container restart, container run-once, passphrase PFX, root-mode settings trust including the RT-1 replay) against the release-commit image. | Changed in 0.3.1 — E015-S01-001 (root-trust image test), E015-S02-004 (release record) |
| NFR-6 | Logs are structured and traceable enough to diagnose a failed export after the fact: JSON file logging, a correlation id per export pass that survives deferred restarts, and a multi-line settings dump. | Done in 0.3.0. Notification-delivery failure visibility: Deferred (third-party loggers stay suppressed; BL-E011-017). |
| NFR-7 | The first container boot produces a usable `/config/config.yaml` without manual intervention, with correct logging defaults. | Done in 0.3.0 |
| NFR-8 | **Export pass cost on RSA-4096 stores.** For 5 domains with RSA-4096 keys, an unchanged pass over existing output, with a fresh exporter and default settings (`validatekeys: true`), makes 0 private-key loads and 0 PKCS12 loads. A first pass over the same 5 domains loads each key exactly once (5 loads), passing the RSA-validation skip exactly when `validatekeys` is false. Load counts are the gate (test spies). Wall time is checked only as a relative bound measured in the same test process, never as an absolute limit in CI: the unchanged pass takes less than ¼ of a validating first pass, and a first pass with `validatekeys: false` takes less than ½ of a validating first pass. Absolute times (target: under 2.0 s for each on the maintainer's workstation) are recorded in the story notes, not asserted. Baseline before E015: 9.09 s with 10 key loads and 5 PKCS12 loads unchanged; 5.95 s with 10 key loads first pass (production: 108 s / 74 s for 74 certificates). | New in 0.3.1 — E015-S01-002 |
| NFR-9 | **Locked hook dependencies.** Every Python package a `repo: local` pre-commit hook needs in the `build` job that produces `dist` is declared in the Poetry dev group, so it is hash-locked by `poetry.lock` and audited by `pip-audit`; no hook declares `additional_dependencies`, and every local hook runs as `system` (or `unsupported`, its pre-commit ≥ 4.4 alias) or `pygrep` (enforced by a pygrep guard). The remote hook repositories that still install from a package index (pre-commit-hooks, ruff, zizmor, shellcheck-py) are listed with what they fetch in ADR-0042 "Not covered". | New in 0.3.1 — E015-S02-003 |
| NFR-10 | **Private-CA publishing and action inputs.** When a private CA is configured for publishing (`PUBLISH_CA_CERTIFICATE`), BuildKit trusts it for the multi-architecture image push: `docker/setup-buildx-action` receives the imported CA's BuildKit config through its `buildkitd-config` input. Workflow and composite-action YAML carries no `config:` or `config-inline:` key (pygrep guard). No available tool validates the inputs of SHA-pinned actions statically, so each release run must show zero `Unexpected input` lines (checklist, not CI-gating). | New in 0.3.1 — E015-S02-001 |

## 5. Out of scope

- A metrics or health endpoint (no `/healthz`, Prometheus textfile or `HEALTHCHECK`).
- A scriptable exit code for export failures: the run-once exit code reflects start-up
  failures only (FR-6). Tracked as a backlog item (closed-items table, #23).
- Exporting a file per SAN: SANs are logged, not exported.
- Certificate stores other than Traefik's ACME JSON (for example cert-manager, Caddy).
- A Kubernetes-native mode (Docker socket only; no CRD or annotation watch). Running the
  image as a Kubernetes Job in run-once mode is a generic container use and is supported.
- Restarting containers on a Docker Engine other than the one the exporter is connected to.
- Multiple exporter instances per data path, and persisted restart state: the exported
  files' modification times are the only restart state (FR-15). The `.pfx` fingerprint files
  are change-detection state for the `.pfx` only (FR-2).
- A size limit on the ACME store: it is trusted Traefik output, and `/data` is mounted
  read-only.
- Changing the LinuxServer base image's init or ownership conventions: `/config`, `/app` and
  `/defaults` stay owned by `PUID`/`PGID` (maintainer constraint 2026-10-12).
- Running a root exporter's post-export command under another uid, and an opt-in flag for
  file-sourced root hooks (FR-18).
- Aliases for legacy setting names (FR-16).
- Removing fingerprint files or exported artifacts when a domain leaves the store or a store is
  renamed away.

## 6. Backlog

The live backlog is `_bmad-output/implementation-artifacts/state/issues.yaml` (read it with
`pm-status list-issues`). This section carries no open work items; it lists the open risks and
deferred decisions that bound the 0.3.1 target, and the closed items of the 2026-08-30 backlog.

### Open risks and deferred items at 0.3.1

| Item | Severity | Status |
|---|---|---|
| BL-E015-002: the image venv lives under the `abc`-owned `/app` (LinuxServer `init-adduser` gives `/app` to `abc`), and root mode executes it. Renaming `/app/.venv` as `abc` is blocked today only by overlay2 `EXDEV`, so the boundary depends on the storage driver. LinuxServer Python images build their venv at `/lsiopy`. | Medium | **Not in 0.3.1** (maintainer decision 2026-10-12). Known open risk; documented in ADR-0049 (root-mode settings trust). |
| BL-E015-003: the seeded `/config/config.yaml` is `0:0 0644`, so the `PUID` user cannot edit it in place (replacing it by rename works). | Low | Deferred (MD-23). |
| BL-E015-001: `docs/operational.md` "Known limitation" about a relative file-log path is inaccurate. | Low | Deferred. |
| Root-mode residual risks: an environment-set root hook that runs a script stored in `/config`; `TRAEFIK_CERTIFICATE_EXPORTER_LOGGING_CFGFILE` pointed into `/config`; Docker mods and `/custom-cont-init.d` scripts. | — | Documented, not enforced (FR-18, ADR-0049, E015-S01-001). |
| AR-1: a `PUID`-writable ACME store directory in root mode lets that account forge the store a file-forced root exporter writes over `/certs`. `/data:ro` is required in both modes; a root-mode start does not yet log the "store is writable" note. | Low | Documented, not enforced (FR-18, ADR-0049); BL-E015-004 (Low) for the root-mode note (s6 script change). |
| `appriseurls` from a `PUID`-writable `config.yaml` can send requests with a chosen method, path and headers to any host the container reaches (Apprise `json://`, `xml://`, `form://`). Example: a POST to a docker-socket-proxy's `/containers/<id>/stop` needs no body. | Medium | Accepted residual risk, kept `any-source` for now (MD-25, BL-E015-032 wontfix); revisit condition in MD-25. Rationale corrected by E015-S02-005 (FR-18, ADR-0049). |
| A release fully from Gitea (`act_runner`) is unproven. | — | Deferred (BL-E013-044). |
| Remote pre-commit hook environments: `pre-commit-hooks` resolves `ruamel.yaml>=0.15` unpinned; ruff and zizmor wheels are fetched without hashes. | Low | Recorded in ADR-0042; Low item filed by E015-S02-003. Locking every hook (option B) deferred. |
| Gitea packages in a bot or organisation namespace (MD-12 option b). | — | Deferred: changes the image and index names users pull. |
| Watchtower on the production host is archived upstream and may fail against Docker 29's API floor. | — | Out of scope for the product; E015-S02-004 files a Low item if its pre-check shows it failing (MD-16). |

### Closed items from the 2026-08-30 backlog

| # | Item | Closed by |
|---|---|---|
| 1 | Stop logging `pkcs12Passphrase` and config dumps at DEBUG | E001-S01-001, E010-S01-001, E011-S01-003 |
| 2 | Fix the `dataPath`/`outputPath` `None` guard | E001-S01-002 |
| 3 | Declare `cryptography` explicitly | E002-S01-001 |
| 4 | Fix the CI build/publish wiring | E002-S01-004, rebuilt by E007/E008; replaced by the standard pipeline (E013, ADR-0035) |
| 5 | Add a `pytest` suite wired into CI | E001-S01-003 |
| 6 | Seed `/config/config.yaml` on first boot | E004-S01-001 |
| 7 | Move `poetry` out of runtime dependencies | E002-S01-002 (no dedicated story) |
| 8 | Build the image from the locked dependency set | E002-S01-002 (ADR-0004, ADR-0008) |
| 9 | Structured (JSON) file logging | E004-S01-002 |
| 10 | Include/exclude mutual exclusivity across config surfaces | E003-S01-001 |
| 11 | Remove the `nektos/act`-only CA install conditional | E002-S01-005; the workflow was later removed by ADR-0035 |
| 12 | Remove dead code | E006-S01-003 |
| 13 | Digest-pin the base image; record the privilege model | E002-S01-003 (ADR-0002), privilege model replaced by ADR-0030 as amended 2026-10-10 (E012-S01-001, E013-S02-004); root-mode settings trust added by E015-S01-001 |
| 14 | Current action versions; Dependabot | E006-S01-002; pin policy now ADR-0035 |
| 15 | `/docs` skeleton | Pre-epic documentation pass |
| 16 | LiquidLogicLabs action adoption | E006, E008, E013 |
| 17 | `SECURITY.md` | E006-S01-001 |
| 18 | `CONTRIBUTING.md`, code of conduct, issue and PR templates | E006-S01-001 |
| 19 | Secret scanning and push protection on the GitHub repository | Pre-commit `gitleaks` delivered earlier; the forge setting is re-checked before each release (E015-S02-004 AC 3, or the gap filed) |
| 20 | Synthetic test fixtures only | E001-S01-003; real-chain fixtures generated, not captured (E014-S01-002); RSA-4096 fixture generated (E015-S01-002) |
| 21 | Metrics/health surface | Not planned: out of scope (§5) |
| 22 | SANs export | Decision: SANs are logged, not exported (product spine Deferred). |
| 23 | `--once` / exit-code contract | Run-once delivered by E014-S01-005; non-zero exit on export failure is not planned and stays a backlog item |
