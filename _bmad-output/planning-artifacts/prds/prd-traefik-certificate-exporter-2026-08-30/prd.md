---
title: 'traefik-certificate-exporter PRD'
status: final
target: '0.3.0'
created: '2026-08-30'
updated: '2026-10-11'
---

# Product Requirements Document — traefik-certificate-exporter

> **Target: 0.3.0 — reflects requirements after epic E014.** Updated 2026-10-11.
>
> Each requirement states the intended behaviour for 0.3.0. Its status is one of:
> **Met** (delivered by E001–E013 and unchanged by E014), **Met by E014-&lt;story&gt;** (delivered
> or repaired by that planned story), or **Not planned** (with the reason).
>
> **Location note:** this lives under `{planning_artifacts}/prds/prd-traefik-certificate-exporter-2026-08-30/`,
> the canonical `bmad-prd` run-folder location, not `/docs`. PRDs are planning artifacts and
> are not part of the permanent docs skeleton in [docs/README.md](../../../../docs/README.md).
> Binding design rules live in [docs/adr/](../../../../docs/adr/), the product spine
> (`_bmad-output/planning-artifacts/architecture/architecture-traefik-certificate-exporter-2026-08-30/`)
> and the CI/CD spine (`_bmad-output/planning-artifacts/architecture/architecture-ci-cd-pipeline-2026-10-08/`).
>
> **Changelog**
>
> - 2026-08-30: baseline reverse-engineered from v0.1.3 and the
>   [architectural review](../../../implementation-artifacts/review-report.md).
> - 2026-10-11: refreshed to the 0.3.0 target. Sources:
>   [E014 plan review, PRD lens](../../../implementation-artifacts/epic-014/plan-review/review-prd.md) (forward trace);
>   [whole-solution review, coherence lens](../../../implementation-artifacts/review-all-epics-2026-10-10/review-coherence.md) §2 (PRD coverage);
>   the E014 stories in [sprint-01](../../../implementation-artifacts/epic-014/sprint-01/stories/) and
>   [sprint-02](../../../implementation-artifacts/epic-014/sprint-02/stories/);
>   [ADR-0030](../../../../docs/adr/0030-conditional-privilege-drop.md) as amended 2026-10-10;
>   maintainer decisions of 2026-10-10 and 2026-10-11 (CI/CD spine `.memlog.md`).
>   FR-12 to FR-17 added; FR/NFR ids unchanged; §6 backlog replaced by a pointer and a closed-items table.
> - 2026-10-11: FR-17 forge wording aligned with the maintainer decision of 2026-10-11 (option 2:
>   a release may run fully from Gitea) and CI/CD spine AD-9/AD-13.

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

| ID | Requirement | Status (target 0.3.0) |
|---|---|---|
| FR-1 | Parse Traefik ACME stores of both the legacy (v1, `DomainsCertificate.Certs`) and current (v2, `Certificates`) shapes, detecting the shape from the store's keys, not from the CA URL, so certificates from any RFC 8555 CA are exported. Empty resolvers (`"Certificates": null`, `"Account": null`) are tolerated. Invalid JSON fails the file; invalid base64 fails only the affected certificate. One resolver's failure does not drop the other resolvers' domains. | Met by E014-S01-003 |
| FR-2 | For each domain, export the private key, leaf certificate, chain (intermediates only; empty for a single-certificate chain), full chain, and a PKCS12 (`.pfx`) bundle that carries the intermediates. The whole artifact set is built before any file is replaced, and each file is replaced atomically. An artifact whose content is unchanged is not rewritten. A domain is reported as exported if and only if at least one of its artifacts changed and was replaced in this pass. | Met by E014-S01-002 |
| FR-3 | Support a flat layout (`{name}.crt` etc. in one folder) and a per-domain subfolder layout (`{name}/cert.pem` etc.). | Met |
| FR-4 | Filter exported domains by an include-list or an exclude-list, mutually exclusive across every configuration surface (CLI, environment, config file). | Met |
| FR-5 | Optionally scope processing to one named Traefik certificate resolver; otherwise detect every resolver node in the store. | Met by E014-S01-003 |
| FR-6 | Run one export pass at start and/or watch the data path for file create/modify events. When watching is off, the container image runs one pass and exits with that pass's exit code (0, or 1 for a missing data path); export failures are logged at ERROR and do not change the exit code. When both run-at-start and watch are off, one WARNING says there is nothing to do. | Met by E014-S01-005 |
| FR-7 | Coalesce rapid repeated filesystem events for the same file into one export pass. | Met |
| FR-8 | Optionally restart the running Docker containers labeled with an exported domain name, through the Docker Engine the process is connected to (`DOCKER_HOST` or the default socket; the Docker CLI context is ignored; Engine API 1.24 or newer). When restarts are enabled, the Engine is checked once at start-up: INFO on success, one ERROR naming the endpoint on failure, and exporting continues either way. Each container is restarted at most once per 300 s (`RESTART_COOLDOWN_SECONDS`, not configurable); a restart that the floor denies is deferred to one trailing restart, never dropped. Which containers are restarted is governed by FR-15. | Met by E014-S01-001, E014-S01-006 |
| FR-9 | Support a dry-run mode that builds and compares every artifact in memory, logs the intended actions, writes no file and restarts no container, and reports a domain only when its build succeeded and at least one artifact would change. | Met by E014-S01-002 |
| FR-10 | Configurable via CLI flags, a YAML config file and environment variables, with precedence CLI > environment > config file > packaged default. Every documented CLI flag and environment name reaches the setting it names (`TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_<KEY>`). The log level can be set by `-ll` or by `TRAEFIK_CERTIFICATE_EXPORTER_LOGGING_LEVEL`; an invalid value falls back to INFO with one WARNING, and one INFO line names the effective level and its source. | Met by E014-S01-004 |
| FR-11 | Ship as a PyPI package and as a multi-architecture (`linux/amd64`, `linux/arm64`) Docker image on the linuxserver.io base with s6-overlay and `PUID`/`PGID`. In the image the exporter runs as **root unless the ACME store is proven readable by the `PUID`/`PGID` service account**: it drops to that account only when, at container start, the settings resolve, `restartcontainers` is off, the data path is listable, at least one `filespec` match exists and every match is readable by the account, and the output path is writable by it. Anything else keeps root, with exactly one start-up WARNING naming the reason, the files and the remedy (run Traefik as the `PUID`/`PGID` user). The decision is taken once per container start. The unprivileged mode requires `/data` mounted read-only (`/data:ro`). | Met by E014-S02-005 (privilege model per [ADR-0030](../../../../docs/adr/0030-conditional-privilege-drop.md) as amended 2026-10-10 already met: E012-S01-001, E013-S02-004) |
| FR-12 | Optionally run an operator-configured post-export command (`postexportcommand`) after a pass in which at least one domain changed, passing only the changed domains in `TRAEFIK_CERTIFICATE_EXPORTER_EXPORTED_DOMAINS`. Nothing runs when no domain changed. The command is treated as a secret: logs name only its program, never its arguments. | Met by E014-S01-006 |
| FR-13 | Optionally send export notifications through Apprise to a list of operator-configured URLs (`appriseurls`), after a pass in which at least one domain changed, listing only the changed domains. Nothing is sent when no domain changed. The URLs are credentials and are redacted from every settings dump. | Met by E014-S01-006 |
| FR-14 | Protect the PKCS12 bundle with an optional passphrase (`pkcs12passphrase`). A non-empty passphrase yields an AES-256/SHA-256 encrypted bundle; an empty or unset passphrase yields an unencrypted bundle. Changing the passphrase, or switching between encrypted and unencrypted, rewrites the bundle. | Met by E014-S01-002 |
| FR-15 | Restart a labeled container only when a certificate it serves changed after it started: on every pass, including the start-up pass and passes in which nothing changed, a container is restarted when the newest exported artifact of its labeled domains is more than 2 s newer than the container's start time. An exporter restart over an unchanged store restarts nothing; a restart lost to a crash or shutdown is recovered on the next pass. | Met by E014-S01-006 |
| FR-16 | At start-up, warn about legacy or misspelled setting names (environment and config file), naming the replacement, and ignore the old name; warn once about unknown `TRAEFIK_CERTIFICATE_EXPORTER_*` environment variables with the nearest valid name. Values are never logged. | Met by E014-S01-004 |
| FR-17 | Publish each tagged release to every destination the release forge has configured: the PyPI and Gitea package indexes, and the GHCR, Docker Hub and Gitea container registries, plus the forge release. A destination is enabled only when its token and every variable it needs are set; a partly configured destination is skipped with one warning naming what is missing; an unconfigured one is silent. A release runs fully from GitHub or fully from Gitea: all destinations of a release publish from one forge's run, every publish credential lives on that forge only, and the other forge holds none. A release from Gitea can reach every destination; Gitea then holds the PyPI, TestPyPI, GHCR and Docker Hub tokens as repository-level secrets (Gitea ignores environments), which requires protected `main` and `v*` tags with pushes and tag creation limited to trusted accounts, tokens scoped to this project only, and rotation of every token after any untrusted push. On GitHub, publish credentials are held in the `dev`/`release` environments. Releases are cut only from protected `v*` tags on `main`. Images are tagged `X.Y.Z`, `X.Y` and `latest`; no bare `:0` tag is written for 0.x releases. | Met by E014-S02-002 (with E014-S02-001, E014-S02-005; ADR-0038, ADR-0039) |

## 4. Non-functional requirements

| ID | Requirement | Status (target 0.3.0) |
|---|---|---|
| NFR-1 | Never write certificate private keys, PKCS12 passphrases, Apprise URLs, the post-export command or other configured secrets into logs, including the DEBUG settings dump and warnings about setting names. | Met by E014-S01-006 (post-export command redaction; with E014-S01-008 list redaction) |
| NFR-2 | Signal misconfiguration loudly instead of continuing silently: a missing data path fails the run; an unreachable Docker Engine, a legacy or unknown setting name, an invalid log level and a configuration with nothing to do each produce a start-up ERROR or WARNING. | Met by E014-S01-004 (with E014-S01-001, E014-S01-005) |
| NFR-3 | `pip install traefik-certificate-exporter` works on every Python version in the declared range (`>=3.10,<3.15`) with no missing imports: every module `src/` imports is a declared dependency, every declared dependency is used, and no package in any `poetry.lock` group, optional groups included, nor in any hashed CI bootstrap file under `.github/requirements/`, carries a known advisory (`pip-audit` gates, ADR-0042). Packages a lock entry restricts by environment marker to another platform or Python minor are outside the gate (BL-E014-023). | Met by E014-S01-007 (range ends verified at release by E014-S02-005) |
| NFR-4 | Every tagged release builds the package and the image once and publishes them to every enabled destination (FR-17). A skipped, partly configured destination does not fail the run; the per-release check that each intended destination was enabled exactly once with zero warnings is a release-checklist step, not a mechanical gate. | Met by E014-S02-005 (with E014-S02-001, E014-S02-002) |
| NFR-5 | Regressions in ACME parsing, export, restart and container lifecycle are caught before release: the unit suite runs in `just check` and CI, and each release records a passing run of the opt-in integration tests (real container restart, container run-once, passphrase PFX) against the release-commit image. | Met by E014-S02-005 (with E014-S01-001, E014-S01-002, E014-S01-005, E014-S01-006) |
| NFR-6 | Logs are structured and traceable enough to diagnose a failed export after the fact: JSON file logging, a correlation id per export pass that survives deferred restarts, and a multi-line settings dump. | Met by E014-S01-006 (correlation id on deferred restarts; with E014-S01-008). Notification-delivery failures stay invisible while third-party loggers are suppressed: open as BL-E011-017. |
| NFR-7 | The first container boot produces a usable `/config/config.yaml` without manual intervention, with correct logging defaults. | Met |

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
  files' modification times are the only restart state (FR-15).
- A size limit on the ACME store: it is trusted Traefik output, and `/data` is mounted
  read-only.

## 6. Backlog

The live backlog is `_bmad-output/implementation-artifacts/state/issues.yaml` (read it with
`pm-status list-issues`). This section no longer carries open items.

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
| 13 | Digest-pin the base image; record the privilege model | E002-S01-003 (ADR-0002), privilege model replaced by ADR-0030 as amended 2026-10-10 (E012-S01-001, E013-S02-004) |
| 14 | Current action versions; Dependabot | E006-S01-002; pin policy now ADR-0035 |
| 15 | `/docs` skeleton | Pre-epic documentation pass |
| 16 | LiquidLogicLabs action adoption | E006, E008, E013 |
| 17 | `SECURITY.md` | E006-S01-001 |
| 18 | `CONTRIBUTING.md`, code of conduct, issue and PR templates | E006-S01-001 |
| 19 | Secret scanning and push protection on the GitHub repository | Pre-commit `gitleaks` delivered earlier; the forge setting is an item on the E014-S02-005 release checklist (verified with `gh api … --jq .security_and_analysis`, or filed as a backlog item) |
| 20 | Synthetic test fixtures only | E001-S01-003; real-chain fixtures generated, not captured (E014-S01-002) |
| 21 | Metrics/health surface | Not planned: out of scope (§5) |
| 22 | SANs export | Decision: SANs are logged, not exported. The commented-out loop was deleted in E006-S01-003; the decision is recorded here and routed to the product spine by E014-S01-003 / E014-S02-003. |
| 23 | `--once` / exit-code contract | Run-once delivered by E014-S01-005; non-zero exit on export failure is not planned for 0.3.0 and is a backlog item filed by E014-S01-005 |
