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
| [adr/](adr/) | Recorded architectural decisions (dependency management, container base image, logging, build parity, the CI/CD pipeline). [ADR-0035](adr/0035-standard-ci-cd-pipeline.md) is the current pipeline; each ADR it superseded or amended says so in its status line or an amendment note |
| [ci/pipeline-walkthrough.md](ci/pipeline-walkthrough.md) | How the four-workflow pipeline works: build, dev and release flows, versions, publishing destinations and their `PUBLISH_*` secrets, `just` recipes, releasing |
| [ci/gitea-runners.md](ci/gitea-runners.md) | Gitea runner and private-CA guidance for running the pipeline on self-hosted Gitea (AD-6, AD-18) |
| [developer.md](developer.md) | Setup, `just` recipes, local CI under `act`, releasing, build, run, conventions |
| [operational.md](operational.md) | Deploy, configuration, runbooks (including CI recovery and bad releases), monitoring, rollback |
| [upgrading.md](upgrading.md) | Upgrade notes per release (0.2.0 → 0.3.0: restarts, privileges, setting names and the legacy-name table, hook/notification contract, run-once, PKCS12, versioning and image tags, where releases come from) |

Keep this index current — a doc that stops matching the code is a defect (Core §10).
