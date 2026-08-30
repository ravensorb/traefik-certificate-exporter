---
title: 'traefik-certificate-exporter PRD'
status: final
created: '2026-08-30'
updated: '2026-08-30'
---

# Product Requirements Document — traefik-certificate-exporter

> Reverse-engineered from the shipped codebase (v0.1.3) plus the [l3io-arch-review](../../../implementation-artifacts/review-report.md)
> findings, since no PRD was authored at build time. Treat this as a baseline to validate
> with the maintainer, not a historical record of original intent.
>
> **Location note:** this lives under `{planning_artifacts}/prds/prd-traefik-certificate-exporter-2026-08-30/`,
> the canonical `bmad-prd` run-folder location — not `/docs`. PRDs are planning artifacts,
> not part of the permanent architectural/developer/operational docs skeleton in
> [docs/README.md](../../../../docs/README.md). `status: final` reflects that this baseline
> has been accepted as input by `bmad-create-epics-and-stories` (see
> `_bmad-output/planning-artifacts/epics.md`) and `bmad-architecture` (see the companion
> spine at `_bmad-output/planning-artifacts/architecture/`).

## 1. Purpose

Traefik stores ACME (Let's Encrypt) certificates for all managed domains inside a single
`acme.json`/`acme-*.json` file, keyed by resolver, in a Traefik-internal JSON shape. Many
tools downstream of Traefik (other reverse proxies, mail servers, monitoring stacks, manual
inspection) need the certificate and private key as **plain PEM/PFX files on disk**, not
buried in Traefik's JSON. `traefik-certificate-exporter` watches Traefik's ACME store and
extracts every managed certificate to a configurable output directory in PEM and PKCS12
form, optionally restarting Docker containers that depend on a certificate that just changed.

## 2. Users

- Self-hosters and homelab operators running Traefik as their ingress/reverse proxy.
- Operators who run a second service (mail, VPN, internal dashboards) that needs the same
  certificate Traefik obtained, in a format that service can consume.

## 3. Functional requirements (as implemented today)

| ID | Requirement | Evidence |
|---|---|---|
| FR-1 | Parse both legacy (v1, `DomainsCertificate.Certs`) and current (v2, `Certificates`) Traefik ACME JSON shapes | [certificate_exporter.py](../../../../src/traefik_certificate_exporter/libs/certificate_exporter.py) `__exportCertificate` |
| FR-2 | Export each domain's private key, leaf cert, chain, full chain, and a PKCS12 (`.pfx`) bundle | same, PEM + `PemToPfxConverter.export_to_pkcs12` |
| FR-3 | Support both a "flat" layout (`{name}.crt` etc. in one folder) and a per-domain subfolder layout (`{name}/cert.pem` etc.) | `settings.flat` branch |
| FR-4 | Filter which domains are exported via an include-list or an exclude-list (mutually exclusive) | `cli_args.py` mutually-exclusive group; `settings.domains` |
| FR-5 | Optionally scope processing to one named Traefik certificate resolver, or auto-detect resolver nodes in the JSON | `traefikResolverId` handling |
| FR-6 | Run once at start (`--run-at-start`) and/or watch the data path continuously for file create/modify events | `watchdog` usage in `app.py` / `AcmeCertificateFileHandler` |
| FR-7 | Debounce rapid repeated filesystem events for the same file (coalesce into one export pass) | `AcmeCertificateFileHandler.handleEvent` 2s timer |
| FR-8 | Optionally restart Docker containers labeled with the exported domain name, to pick up the new cert | [docker.py](../../../../src/traefik_certificate_exporter/libs/docker.py) `DockerManager.restartLabeledContainers` |
| FR-9 | Support a dry-run mode that logs intended actions without writing files or restarting containers | `settings.dryRun` checks |
| FR-10 | Configurable via CLI flags, a YAML config file, or environment variables (CLI > env var > config file > packaged default, `confuse`-managed) | [settings.py](../../../../src/traefik_certificate_exporter/libs/settings.py) `loadFromFile` |
| FR-11 | Ship as a PyPI package and as a Docker image (linuxserver.io-style, s6-overlay, PUID/PGID) | `pyproject.toml` scripts; [docker/Dockerfile](../../../../docker/Dockerfile) |

## 4. Non-functional requirements

| ID | Requirement | Current state |
|---|---|---|
| NFR-1 | Must not leak certificate private keys or PKCS12 passphrases into logs | **Violated** — see review finding #5 (BLOCKER) |
| NFR-2 | Must reliably signal misconfiguration (e.g. missing data path) rather than silently continuing | **Violated** — see review finding #2 (BLOCKER) |
| NFR-3 | Installable via `pip install traefik-certificate-exporter` with no missing transitive imports | **Violated** — see review finding #3 (BLOCKER) |
| NFR-4 | CI must build and publish the package/image on every tagged release | **Violated** — see review finding #4 (BLOCKER), pipeline is not wired correctly |
| NFR-5 | Regressions in ACME parsing (v1/v2) or export logic must be caught before release | **Unmet** — zero automated tests (review finding #1, BLOCKER) |
| NFR-6 | Logs should be traceable/structured enough to diagnose a failed export after the fact | Partially unmet — unstructured string logs (review finding #9, MAJOR) |
| NFR-7 | First container boot should produce a usable default config without manual intervention | **Violated** — see review finding #6 (MAJOR), sample copy writes to wrong filename |

## 5. Out of scope (today)

- No metrics/health endpoint (no way to scrape export success/failure externally).
- No support for certificate stores other than Traefik's ACME JSON (e.g. cert-manager, Caddy).
- No Kubernetes-native mode (Docker socket only; no CRD/annotation watch).
- No multi-instance/leader-election story — assumes a single exporter instance per data path.

## 6. Fix / upgrade / enhancement backlog

Derived from the [architectural review](../../../implementation-artifacts/review-report.md)
plus gaps surfaced while reverse-engineering this PRD. Priority mirrors review severity, with
enhancements layered in at the end. Fully decomposed into epics/stories in
`_bmad-output/planning-artifacts/epics.md`.

### Must-fix (BLOCKER — correctness/security/CI, ship-blocking)

1. Stop logging `pkcs12Passphrase` and full config dumps at DEBUG (review #5).
2. Fix `Settings.dataPath`/`outputPath` `None`-stringification so the missing-path guard in
   `app.py` actually fires (review #2).
3. Declare `cryptography` as an explicit dependency (review #3).
4. Fix `build.yaml`'s reusable-workflow wiring so CI can build/publish again (review #4).
5. Add a `pytest` suite covering ACME v1/v2 parsing, `Settings`, and `DockerManager`, wired into CI (review #1).

### Should-fix (MAJOR — reliability/consistency)

6. Fix the s6 first-run script so `/config/config.yaml` is actually seeded (review #6).
7. Move `poetry` out of runtime dependencies (review #7).
8. Build the Docker image from the locked dependency set instead of a hand-maintained `pip install` list (review #8).
9. Adopt structured (JSON) logging for the file handler (review #9).
10. Fix the documented `DOMAINS_INCLUDE`/`DOMAINS_EXCLUDE` mutual-exclusivity gap for env-var-driven config (the `FIXME` already recorded in [docker/README.md](../../../../docker/README.md) — the CLI enforces mutual exclusivity via `argparse`, but env-var/YAML config paths do not).
11. Remove the `if: ${{ env.ACT }}` conditional in [build-container.yaml](../../../../.github/workflows/build-container.yaml) that installs a custom CA cert only under `nektos/act` — violates the one-pipeline/no-ACT-dependency guideline in [docs/guidelines.md §7](../../../../docs/guidelines.md#7-one-pipeline-three-runners--no-act-env-var-dependency); replace with a runner-agnostic CA install mechanism.

### Nice-to-have (MINOR — polish)

12. Remove dead code (commented `sans` loop, disabled publish steps, disabled pre-commit hooks, unused `PemToPfxConverter.dump()`) (review #10, #11).
13. Pin the Docker base image by digest; record the PUID/PGID privilege model in an ADR (review #12).
14. Align GitHub Actions to consistent, current major versions; enable Dependabot for `github-actions` and Python (review #13).
15. Stand up the `/docs` skeleton — done as part of this pass (review #14).
16. ~~Resolve the unverified "LiquidLogic actions" vendor preference~~ — done: confirmed org is [`LiquidLogicLabs`](https://github.com/LiquidLogicLabs); see [docs/guidelines.md §6](../../../../docs/guidelines.md#6-cicd--github-actions-prefer-marketplace-actions-over-scripts) for the resolved preference and the two actions (`git-action-ca-certificate-import`, `git-action-docker-act-compatibility`) directly applicable to backlog item #11. Adopting them in the workflows themselves remains open work, tracked under Epic 6 Story 6.2.

### Open-source hygiene (public repo — [docs/guidelines.md §9](../../../../docs/guidelines.md#9-public-open-source-repo-hygiene))

17. Add `SECURITY.md` with a private vulnerability-disclosure process — this project handles
    private keys and passphrases, so this matters more than for a typical utility.
18. Add `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, an issue template (bug/feature), and a PR
    template — none exist today.
19. ~~Add a secret-scanning pre-commit hook~~ — done: `gitleaks` wired into `.pre-commit-config.yaml` (see [docs/guidelines.md §10](../../../../docs/guidelines.md#10-pre-commit-hooks-wired-in-pre-commit-configyaml)). Still open: enable GitHub's own secret-scanning/push-protection on the repo (not something a local hook can do).
20. Ensure any test fixtures added under backlog item #5 use synthetic domains/keys, never
    real captured data.

### Candidate enhancements (require stakeholder validation — not yet requirements)

21. Emit a metrics/health surface (even a simple `/healthz` file or Prometheus textfile) so
    export success/failure is observable without grepping logs.
22. Support SANs export (the code already extracts `sans` per certificate but the per-SAN
    file-writing loop is commented out — decide whether to finish or delete it).
23. Consider a `--once`/exit-code contract for CI/cron use cases distinct from the
    long-running watch mode, so failures are scriptable without parsing logs.
