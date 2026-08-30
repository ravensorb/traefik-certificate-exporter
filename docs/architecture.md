# Architecture — traefik-certificate-exporter

> Reverse-engineered from the current codebase (v0.1.3) per `l3io-arch-review` Mode A. See
> [the PRD](../_bmad-output/planning-artifacts/prds/prd-traefik-certificate-exporter-2026-08-30/prd.md) for requirements and the [review report](../_bmad-output/implementation-artifacts/review-report.md)
> for the audit that fed the ADRs and backlog referenced below. A companion
> [ARCHITECTURE-SPINE.md](../_bmad-output/planning-artifacts/architecture/architecture-traefik-certificate-exporter-2026-08-30/ARCHITECTURE-SPINE.md)
> exists as the canonical `bmad-architecture` planning artifact (terse AD-n invariants); this
> document is the fuller, diagram-first developer-facing rendering.

## 1. Context (C4 level 1)

```mermaid
C4Context
  title System context — traefik-certificate-exporter

  Person(operator, "Operator", "Runs Traefik and this exporter")
  System(traefik, "Traefik", "Reverse proxy; owns ACME JSON store")
  System(tce, "traefik-certificate-exporter", "Watches ACME store, extracts PEM/PFX certs")
  System_Ext(docker, "Docker Engine", "Container runtime; restarts labeled containers")
  System_Ext(consumers, "Downstream services", "Mail, VPN, internal tools consuming PEM/PFX")

  Rel(traefik, tce, "Writes acme*.json to shared volume")
  Rel(tce, consumers, "Writes cert.pem / privkey.pem / cert.pfx to shared volume")
  Rel(tce, docker, "Restarts containers labeled with matching domain")
  Rel(operator, tce, "Configures via CLI / config.yaml / env vars")
```

## 2. Containers (C4 level 2)

```mermaid
C4Container
  title Containers — traefik-certificate-exporter

  Container_Boundary(app, "traefik-certificate-exporter process") {
    Component(cli, "cli_args", "argparse", "Parses CLI flags into confuse-dotted keys")
    Component(settings, "SettingsManager", "confuse", "Merges CLI + config.yaml + env vars into Settings")
    Component(watcher, "watchdog Observer", "watchdog", "Watches data path for ACME file create/modify")
    Component(exporter, "AcmeCertificateExporter", "python", "Parses ACME JSON, writes PEM/PFX")
    Component(dockermgr, "DockerManager", "docker SDK", "Restarts labeled containers via Docker socket")
    Component(logging, "logging_utils", "logging + coloredlogs", "Configures handlers from logging.yaml")
  }

  ContainerDb(datapath, "Data volume", "filesystem", "Traefik's acme*.json (read-only)")
  ContainerDb(outputpath, "Certs volume", "filesystem", "Exported PEM/PFX files")
  System_Ext(dockersock, "/var/run/docker.sock", "Docker Engine API")

  Rel(cli, settings, "cmdLineArgs")
  Rel(settings, exporter, "Settings")
  Rel(settings, dockermgr, "Settings")
  Rel(watcher, exporter, "on_created/on_modified -> exportCertificatesForFile")
  Rel(exporter, datapath, "reads")
  Rel(exporter, outputpath, "writes PEM + PFX")
  Rel(exporter, dockermgr, "processed domain list")
  Rel(dockermgr, dockersock, "list/restart containers by label")
```

## 3. Key flow — file change to restarted container

```mermaid
sequenceDiagram
  participant Traefik
  participant Watchdog as watchdog.Observer
  participant Handler as AcmeCertificateFileHandler
  participant Exporter as AcmeCertificateExporter
  participant Docker as DockerManager

  Traefik->>Watchdog: writes acme.json (renewal)
  Watchdog->>Handler: on_modified(event)
  Handler->>Handler: debounce (2s timer, coalesce repeat events)
  Handler->>Exporter: exportCertificatesForFile(path)
  Exporter->>Exporter: detect ACME v1 vs v2 shape
  loop each certificate
    Exporter->>Exporter: filter by include/exclude domains
    Exporter->>Exporter: decode b64 key/cert, split chain
    Exporter->>Exporter: write .key/.crt/.chain/.fullchain/.pfx
  end
  Exporter-->>Handler: [domains processed]
  Handler->>Docker: restartLabeledContainers(domains)
  Docker->>Docker: match container label against domains
  Docker-->>Traefik: (indirect) dependent service now serving new cert
```

## 4. Deployment view

- **Distribution:** PyPI package (`pip install traefik-certificate-exporter`) or a Docker
  image built on `ghcr.io/linuxserver/baseimage-alpine:3.19` (s6-overlay init, PUID/PGID
  privilege drop — see [ADR-0002](adr/0002-container-base-image-and-privilege-model.md)).
- **Runtime:** single long-lived process per data path; no clustering, no leader election.
- **External dependencies at runtime:** filesystem (data + output volumes, read-only /
  read-write respectively), optionally `/var/run/docker.sock` if container restarts are enabled.

## 5. Known architectural gaps (tracked, not yet fixed)

See [PRD §6](../_bmad-output/planning-artifacts/prds/prd-traefik-certificate-exporter-2026-08-30/prd.md#6-fix--upgrade--enhancement-backlog) for the full, severity-ordered
backlog. The items with direct architectural shape impact:

- No observability surface (no metrics/health endpoint) — the system is a black box between
  log lines.
- Dependency/build-artifact parity gap between `pyproject.toml`/`poetry.lock` and the Docker
  image's hand-maintained `pip install` list ([ADR-0004](adr/0004-dependency-build-artifact-parity.md)).
- CI cannot currently build or publish either artifact ([ADR-0005](adr/0005-ci-reusable-workflow-wiring.md)).

## 6. Recorded decisions

| ADR | Decision | Spine invariant |
|---|---|---|
| [0001](adr/0001-python-dependency-management-poetry.md) | Poetry for dependency/environment management | [AD-1](../_bmad-output/planning-artifacts/architecture/architecture-traefik-certificate-exporter-2026-08-30/ARCHITECTURE-SPINE.md#ad-1--poetry-is-the-single-dependency-source) |
| [0002](adr/0002-container-base-image-and-privilege-model.md) | linuxserver.io base image + PUID/PGID privilege model | [AD-2](../_bmad-output/planning-artifacts/architecture/architecture-traefik-certificate-exporter-2026-08-30/ARCHITECTURE-SPINE.md#ad-2--container-base-image-and-privilege-model) |
| [0003](adr/0003-logging-stack-and-secret-redaction.md) | Logging stack and secret-redaction policy | [AD-3](../_bmad-output/planning-artifacts/architecture/architecture-traefik-certificate-exporter-2026-08-30/ARCHITECTURE-SPINE.md#ad-3--logging-structured-file-output-secrets-never-logged) |
| [0004](adr/0004-dependency-build-artifact-parity.md) | Docker image built from the locked dependency set | [AD-4](../_bmad-output/planning-artifacts/architecture/architecture-traefik-certificate-exporter-2026-08-30/ARCHITECTURE-SPINE.md#ad-4--docker-image-built-from-the-locked-dependency-set) |
| [0005](adr/0005-ci-reusable-workflow-wiring.md) | CI reusable-workflow wiring for `build.yaml` | [AD-5](../_bmad-output/planning-artifacts/architecture/architecture-traefik-certificate-exporter-2026-08-30/ARCHITECTURE-SPINE.md#ad-5--one-ci-pipeline-three-runners-no-act-branching) |

The ADR is the durable, full-rationale record (Context/Options/Decision/Consequences); the
spine's AD-n block is the terse, enforceable restatement `bmad-architecture`-driven work
checks against. Neither supersedes the other — update both if a decision changes.
