<!-- bmad:context -->
<!-- Verified 2026-08-30 against 6bdb516. Managed by bmad-project-context; edits inside this block are replaced on refresh. Keep anything you want preserved outside the markers. -->

## traefik-certificate-exporter

Watches Traefik's ACME JSON store and exports certificates as PEM/PKCS12 files, optionally
restarting labeled Docker containers. Python (Poetry), single-process CLI + Docker image
(linuxserver.io/s6-overlay). Planning lives in `_bmad-output/planning-artifacts/` (PRD,
architecture spine, epics/stories); permanent docs in `docs/` (architecture, ADRs,
guidelines, developer/operational guides); the architectural review is
`_bmad-output/implementation-artifacts/review-report.md`.

## Where things are

- Domain logic (ACME parsing, PEM/PKCS12 export): `src/traefik_certificate_exporter/libs/certificate_exporter.py`
- Config loading (CLI/file/env precedence via `confuse`): `src/traefik_certificate_exporter/libs/settings.py`
- Docker container-restart logic: `src/traefik_certificate_exporter/libs/docker.py`
- Container image + s6 init scripts: `docker/`
- Engineering guidelines (Python, packaging, logging, CI/CD, OSS hygiene): `docs/guidelines.md` — read before making a design-shaped change
- Recorded architecture decisions: `docs/adr/` and `_bmad-output/planning-artifacts/architecture/architecture-traefik-certificate-exporter-2026-08-30/ARCHITECTURE-SPINE.md`
- Fix/upgrade/enhancement backlog with severity ordering: `_bmad-output/planning-artifacts/prds/prd-traefik-certificate-exporter-2026-08-30/prd.md` §6

## Running and verifying

- `poetry install`, then `poetry run traefik-certificate-exporter ...` — see `README.md` for the full CLI flag reference.
- No automated test suite exists yet (`tests/` is an empty package) — this is a tracked BLOCKER fix (PRD backlog #5 / Epic 1 Story 1.3), not a broken setup on your end.
- `pre-commit run --all-files` runs `ruff`, `gitleaks`, `actionlint`, and file-hygiene hooks — run this before assuming a change is clean; it currently reports pre-existing findings (ruff violations, actionlint issues) not yet fixed.
- `poetry lock --check` is wired as a pre-commit hook via a `repo: local` block, not `pre-commit/pre-commit-hooks` (that repo does not ship a `poetry-lock` hook id).

## Conventions that differ from defaults

- Config keys are lowercase-dotted (`settings.datapath`); CLI flags map via `argparse` `dest=` to the same keys; env vars use the `TRAEFIK_CERTIFICATE_EXPORTER_` prefix with `_` as the `confuse` separator — keep new settings consistent with this, not a differently-cased scheme.
- Cross-cutting concerns use module-level global singletons (`globalLogger`, `globalArgs`, `globalSettingsMgr`), not dependency injection — match this pattern rather than introducing a different one for new code.
- Dependency/environment tool is Poetry, not `uv` — this is a recorded decision (`docs/adr/0001`), not an oversight; don't migrate without a new ADR.

<!-- /bmad:context -->
