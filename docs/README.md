# Documentation Index — traefik-certificate-exporter

Authored retroactively via `l3io-arch-review` (Mode A) since none existed at build time —
see the [architectural review](../_bmad-output/implementation-artifacts/review-report.md)
that grounds it.

| Doc | Covers |
|---|---|
| [PRD](../_bmad-output/planning-artifacts/prds/prd-traefik-certificate-exporter-2026-08-30/prd.md) | What the tool does today, requirements, and the prioritized fix/upgrade/enhancement backlog (a planning artifact, not part of this skeleton — see note there) |
| [Architecture Spine](../_bmad-output/planning-artifacts/architecture/architecture-traefik-certificate-exporter-2026-08-30/ARCHITECTURE-SPINE.md) | Canonical `bmad-architecture` planning artifact (terse AD-n invariants) — also a planning artifact, not part of this skeleton |
| [guidelines.md](guidelines.md) | Project-specific engineering guidelines (Python, packaging, logging, config, CI/CD, OSS hygiene) governing how the backlog gets implemented |
| [architecture.md](architecture.md) | C4 context/container diagrams, key flow, deployment view |
| [adr/](adr/) | Recorded architectural decisions (dependency management, container base image, logging, build parity, CI wiring) |
| [developer.md](developer.md) | Setup, build, run, test (currently absent), lint, conventions |
| [operational.md](operational.md) | Deploy, configuration, runbooks, monitoring, rollback |

Keep this index current — a doc that stops matching the code is a defect (Core §10).
