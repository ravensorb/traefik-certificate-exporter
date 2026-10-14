<!-- bmad:context -->
<!-- Verified 2026-10-11 against the E014 sprint-02 closure commit (parent 6e230db). Managed by bmad-project-context; edits inside this block are replaced on refresh. Keep anything you want preserved outside the markers. -->

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
- Recorded architecture decisions: `docs/adr/` (index: `docs/architecture.md` §6), the product spine `_bmad-output/planning-artifacts/architecture/architecture-traefik-certificate-exporter-2026-08-30/ARCHITECTURE-SPINE.md` and the CI/CD spine `_bmad-output/planning-artifacts/architecture/architecture-ci-cd-pipeline-2026-10-08/ARCHITECTURE-SPINE.md`
- Backlog (fix/upgrade/enhancement items with severity): `_bmad-output/implementation-artifacts/state/issues.yaml`, read through `uv run _bmad/scripts/pm-status.py list-issues --state-root _bmad-output/implementation-artifacts/state`; the PRD backlog section is only a pointer and a table of closed items

## Running and verifying

- `poetry install`, then `poetry run traefik-certificate-exporter ...` — see `README.md` for the full CLI flag reference.
- `just check` is the gate: it runs `pre-commit run --all-files` and then `pytest`. The hooks are exactly those in `.pre-commit-config.yaml` (lint/format `ruff`, `mypy` over `src/`, `import-linter`, `gitleaks` tree and `gitleaks-history`, `actionlint`, `zizmor`, `shellcheck`, `poetry check --lock`, `pip-audit` and `pip-audit-bootstrap`, `deptry`, file-hygiene hooks, and the `repo: local` pygrep guards); read that file, not this list, for the current set. CI's `build.yaml` runs the same gates, and also builds the distributions and the image on Python 3.14 (`just image` covers that locally), so run `just check` before assuming a change is clean. Other recipes: `just build`, `just image`, `just act [workflow]`, `just release <major|minor|patch>`; the pipeline is described in `docs/ci/pipeline-walkthrough.md` (ADR-0035).
- `poetry check --lock` is wired as a pre-commit hook via a `repo: local` block, not `pre-commit/pre-commit-hooks` (that repo does not ship a `poetry-lock` hook id).

## Conventions that differ from defaults

- Config keys are lowercase-dotted (`settings.datapath`); CLI flags map via `argparse` `dest=` to the same keys; env vars use the `TRAEFIK_CERTIFICATE_EXPORTER_` prefix with `_` as the `confuse` separator — keep new settings consistent with this, not a differently-cased scheme.
- Cross-cutting concerns use module-level global singletons (`globalLogger`, `globalArgs`, `globalSettingsMgr`), not dependency injection — match this pattern rather than introducing a different one for new code.
- Dependency/environment tool is Poetry, not `uv` — this is a recorded decision (`docs/adr/0001`), not an oversight; don't migrate without a new ADR.

<!-- /bmad:context -->

## Secrets and tokens

- A token or environment variable that is missing is most likely in Infisical, the key
  management system: project `home-lab-discovery` (`45365f20-36e8-4d4d-87f3-1554c5ae0615`),
  environment `prod`. Read it through the process environment
  (`infisical run --projectId 45365f20-36e8-4d4d-87f3-1554c5ae0615 --env prod --silent -- …`)
  or pipe it to `gh secret set NAME` on stdin; never print, log or write a value.
- Infisical names differ from the pipeline's: `PYPI_TOKEN` → `PUBLISH_PYPI_TOKEN`,
  `PYPI_TEST_TOKEN` → `PUBLISH_TESTPYPI_TOKEN`, `DOCKERHUB_TOKEN` → `PUBLISH_DOCKERHUB_TOKEN`,
  `GITEA_TOKEN` → `PUBLISH_GITEA_TOKEN` (same value as `REGISTRY_PASSWORD`).
  `GITHUB_TOKEN` (also `E2E_`/`TEST_GITHUB_TOKEN`) is a broad classic PAT for `ravensorb`
  (`repo`, `write:packages`, `delete:packages`, `admin:org`): do not use it as a publish
  token where the workflow's own token works.
- SSH to the production host (`svc.claude`): `CLAUDE_AD_USER` / `CLAUDE_AD_PASSWORD`, method in
  `_bmad-output/implementation-artifacts/epic-015/execution-notes.md`.
