# Architectural Review — traefik-certificate-exporter

**Mode:** B (audit of existing solution) · **Stacks loaded:** core, python, github-actions, docker (stub)
**Date:** 2026-08-30

## Executive summary

The tool is a small, single-process Python watcher/CLI with a clean top-level layering
(`app.py` orchestrates; `libs/` separates settings, Docker, logging, cert export) — the
architecture itself is sound. What's accumulated are correctness, security, and CI-reliability
defects typical of an unreviewed personal/OSS utility: zero tests, a secret (PKCS12 passphrase)
that gets logged in full at DEBUG level, an undeclared runtime dependency (`cryptography`), and
a push/tag CI pipeline that is not wired correctly and cannot actually run. **Single most
important action:** fix `build.yaml` and stop logging the PKCS12 passphrase before anything
else — both are one-line-scale fixes with outsized blast radius.

## Findings table

| # | Severity | Principle | Location | Finding | Remediation |
|---|----------|-----------|----------|---------|-------------|
| 1 | BLOCKER | Core §4 Testability / Python quality toolchain | [tests/__init__.py](tests/__init__.py), `pyproject.toml`, [.github/workflows/build.yaml](.github/workflows/build.yaml) | No test files exist beyond an empty package init; no `pytest` dependency; no CI job runs tests or lint | Add a `pytest` suite covering ACME v1/v2 parsing, `Settings` loading, `DockerManager`; add a CI job that runs it and gates merges |
| 2 | BLOCKER | Core §3 Design by Contract | [src/traefik_certificate_exporter/libs/settings.py](src/traefik_certificate_exporter/libs/settings.py) `Settings.__init__` | `self.dataPath = str(dataPath)` unconditionally stringifies `None` into the literal text `"None"`, so `app.py`'s `if settings.dataPath is None` check can never fire | Preserve `None` as `None`; only stringify a real path; add a regression test for the missing-datapath case |
| 3 | BLOCKER | Core §7 Dependency selection | `pyproject.toml` (missing), [src/traefik_certificate_exporter/libs/certificate_exporter.py](src/traefik_certificate_exporter/libs/certificate_exporter.py) (imports `cryptography.x509`/`hazmat`/`pkcs12`) | `cryptography` is imported directly but never declared in `[tool.poetry.dependencies]` — a plain `pip install traefik-certificate-exporter` has no guaranteed path to it | Add `cryptography` as an explicit direct dependency with a version constraint |
| 4 | BLOCKER | GitHub Actions overlay / Core §2 Reuse | [.github/workflows/build.yaml](.github/workflows/build.yaml) | The only job calls `uses: ./.github/actions/build-package.yaml` / `build-container.yaml` as **steps**; `.github/actions/` doesn't exist, and reusable-workflow calls must be **job-level** `uses:` pointing at `.github/workflows/*.yaml` | Rewrite as `jobs.<name>.uses: ./.github/workflows/build-package.yaml` (and `build-container.yaml`), threading required secrets/inputs; the push-to-main/tag pipeline cannot run today |
| 5 | BLOCKER | Core §9 secrets in logs | [src/traefik_certificate_exporter/libs/settings.py](src/traefik_certificate_exporter/libs/settings.py) `_dump_settings` / `_dump_config` | `jsonpickle.dumps` serializes the full `Settings` object (including `pkcs12Passphrase`, the PFX encryption secret) and the full `confuse.Configuration` at DEBUG level | Redact `pkcs12Passphrase` (and any secret-shaped field) before serializing; never dump full config that can carry env-sourced secrets |
| 6 | MAJOR | Operational docs / Core §10 | [docker/root/etc/s6-overlay/s6-rc.d/init-traefik-certificate-exporter-config/run](docker/root/etc/s6-overlay/s6-rc.d/init-traefik-certificate-exporter-config/run) | Checks `[ ! -f /config/config.yaml ]` but then writes the sample back to `/config/config.yaml.sample` — the real config file is never seeded | Fix destination to `/config/config.yaml`; add a container boot smoke test asserting the file exists |
| 7 | MAJOR | Core §7/§8 Dependency selection | `pyproject.toml` `[tool.poetry.dependencies]` | `poetry` (the build tool) is declared as a **runtime** dependency of the published package | Move to `[tool.poetry.group.dev.dependencies]` — nothing in `src/` imports Poetry |
| 8 | MAJOR | Core §2 Reuse / Python packaging | [docker/Dockerfile](docker/Dockerfile) | Hand-maintained, unpinned `pip install` list duplicates `pyproject.toml`'s dependencies instead of installing from the committed `poetry.lock`; it has already drifted (`pyOpenSSL` added, isn't a project dependency; `cryptography` missing explicitly) | Build from the locked env (`poetry export` / `poetry install --only main`) so image and package can't disagree |
| 9 | MAJOR | Core §9 Unified structured logging | throughout `libs/*.py`, [src/traefik_certificate_exporter/logging.yaml](src/traefik_certificate_exporter/logging.yaml) | All logging is hand-formatted strings, no correlation ID, no JSON formatter | Adopt `structlog` or a JSON formatter at least for the file handler; console can stay human-readable |
| 10 | MINOR | Core §6 Comments / dead code | [src/traefik_certificate_exporter/libs/certificate_exporter.py](src/traefik_certificate_exporter/libs/certificate_exporter.py) (commented `sans` loop), [.github/workflows/build-package.yaml](.github/workflows/build-package.yaml) (disabled publish steps), [.pre-commit-config.yaml](.pre-commit-config.yaml) (disabled black/isort) | Dead, commented-out code left in place across several files | Delete; if intentionally kept, replace with a one-line rationale comment |
| 11 | MINOR | Core §3 Design by Contract | [src/traefik_certificate_exporter/libs/certificate_exporter.py](src/traefik_certificate_exporter/libs/certificate_exporter.py) `PemToPfxConverter.dump()` | Calls an undefined `crypto` module (`OpenSSL.crypto`, never imported) — would raise `NameError` if invoked | Delete the unused method or fix the import |
| 12 | MINOR | Docker overlay (stub) | [docker/Dockerfile](docker/Dockerfile) | `FROM ghcr.io/linuxserver/baseimage-alpine:3.19` pinned by tag only, not digest; no explicit non-root `USER` (linuxserver's PUID/PGID s6 drop-privilege pattern likely covers this) | Pin by digest for supply-chain reproducibility; record the PUID/PGID pattern in an ADR so it isn't re-flagged |
| 13 | MINOR | GitHub Actions overlay | [.github/workflows/build-package.yaml](.github/workflows/build-package.yaml) (`actions/checkout@v3`, `setup-python@v4`) vs [build-container.yaml](.github/workflows/build-container.yaml) (`actions/checkout@v4`) | Inconsistent action major versions across workflows | Bump to latest majors consistently; enable Dependabot for `github-actions` |
| 14 | MINOR | Core §10 Documentation | repo root | No `/docs`, no architecture diagrams, no ADRs, no operational runbook beyond README's CLI usage | Stand up a docs skeleton (Mode A) once the BLOCKERs above are fixed, so it documents a corrected system |

## Per-principle walkthrough

| Principle | Result |
|---|---|
| Core §1 Separation of Concerns | PASS — clean `app.py` / `libs/` layering |
| Core §2 Reuse over copy-paste | Findings #8 |
| Core §3 Design by Contract | Findings #2, #11 |
| Core §4 Testability | Finding #1 |
| Core §5 Brevity without sacrificing readability | PASS |
| Core §6 Comments explain state/intent | Finding #10 |
| Core §7 Dependency selection | Findings #3, #7, #8 |
| Core §8 GA over alpha/beta | PASS — no preview/beta dependencies found |
| Core §9 Unified structured logging | Findings #5, #9 |
| Core §10 Documentation | Finding #14 |
| Python overlay — packaging/env | Finding #7 |
| Python overlay — quality toolchain | Finding #1 (no ruff/mypy/pytest wired; `.pre-commit-config.yaml` has black/isort disabled) |
| GitHub Actions overlay | Findings #4, #13 |
| Docker overlay (provisional stub) | Findings #6, #12 |

## Gate

- **BLOCKER (5):** #1, #2, #3, #4, #5 — must be resolved or ADR-justified before sign-off.
- **MAJOR (4):** #6, #7, #8, #9 — fix or ADR-justify.
- **MINOR (5):** #10, #11, #12, #13, #14 — deferred to backlog.

## Recommended ADRs

- Logging stack & schema (Core §9) — record the chosen structured-logging approach and secret-redaction policy (ties to findings #5, #9).
- Container base-image & privilege model (Docker overlay) — record the digest-pinning policy and the linuxserver PUID/PGID drop-privilege pattern (finding #12), so it stops looking like an unaddressed non-root violation.
- Dependency/build-artifact parity between `pyproject.toml`/`poetry.lock` and the Docker image (finding #8).
- CI reusable-workflow wiring for `build.yaml` (finding #4) — record the corrected job-level `uses:` shape once fixed, so it doesn't regress.

DONE — Blocker: 5, Major: 4, Minor: 5 | BLOCKED: none | FAILED: none
