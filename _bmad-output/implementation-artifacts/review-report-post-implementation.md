# Architectural Review — traefik-certificate-exporter (post-implementation)

**Mode:** B (audit of existing solution) · **Stacks loaded:** core, python, github-actions,
docker (stub)
**Date:** 2026-08-30 (after Epics 1–6 closed)
**Supersedes for current-state purposes:** `review-report.md` (pre-implementation review
that fed the PRD backlog — kept as historical record; every finding in it has since been
fixed and is not repeated here except where a residual gap remains).

## Executive summary

All 6 planned epics are closed: 46 automated tests, zero known secrets in logs, a working
CI/CD pipeline verified via live `docker build`/`docker run` and `actionlint`, current
GitHub Actions versions with Dependabot enabled, governance files in place, and dead code
removed. The architecture itself remains sound and unchanged in shape: `app.py`
orchestrates a small, single-process watcher/CLI; `libs/` cleanly separates settings,
Docker, logging, certificate export, and the new post-export hook — no leakage across
those boundaries was found. **No BLOCKER findings.** Two MAJOR findings (both about
workflow permissions being broader than the steps in them actually need) were found and
fixed immediately as part of this review. The remaining gaps are all MINOR and center on
one thing worth prioritizing: no static type checker is wired in despite extensive type
hints already present in the code.

## Findings table

| # | Severity | Principle | Location | Finding | Remediation |
|---|----------|-----------|----------|---------|-------------|
| 1 | ~~MAJOR~~ FIXED | GH Actions — least privilege | [.github/workflows/test.yaml](.github/workflows/test.yaml) | No `permissions:` block at all — the workflow ran under whatever the repo/org default granted, not an explicit minimum, for a job that only checks out code and runs `pytest` | **Fixed in this review**: added `permissions:\n  contents: read` at the workflow level |
| 2 | ~~MAJOR~~ FIXED | GH Actions — least privilege | [.github/workflows/build-package.yaml](.github/workflows/build-package.yaml) lines 8–9 | `contents: write` and `pull-requests: write` granted workflow-wide; `contents: write` is genuinely needed (`cadifyai/poetry-publish` commits an adjusted version back to `pyproject.toml`/`__init__.py` using it, confirmed via the action's own docs), but nothing in this workflow ever opens a PR | **Fixed in this review**: dropped `pull-requests: write`, kept `contents: write` (verified necessary) |
| 3 | MINOR | GH Actions — SHA-pin third-party actions | [.github/workflows/build-container.yaml](.github/workflows/build-container.yaml) (`LiquidLogicLabs/git-action-ca-certificate-import@v3`), [build-package.yaml](.github/workflows/build-package.yaml) (`cadifyai/poetry-publish@v0.1.1`, `snok/install-poetry@v1`) | Third-party/less-trusted actions pinned to a floating major tag, not a commit SHA, per the GH Actions overlay's supply-chain guidance | Pin to a specific commit SHA (with the version as a trailing comment), or record an ADR accepting the floating-tag risk given Dependabot already surfaces bumps as reviewable PRs |
| 4 | MINOR | Python overlay — static type checking | repo-wide (no `mypy`/`pyright` config anywhere) | Extensive type hints already exist (`str \| None`, `list[str]`, etc.) but nothing enforces them; `# type: ignore` is already used defensively in `settings.py` around `confuse`'s dynamic typing | Add `mypy` (non-strict initially, given `confuse`'s dynamic API) to dev deps + pre-commit; record the chosen strictness level in an ADR |
| 5 | MINOR | Core §9 — structured logs need a correlation ID | [libs/certificate_exporter.py](src/traefik_certificate_exporter/libs/certificate_exporter.py) (`exportCertificates`/`exportCertificatesForFile`), [logging.yaml](src/traefik_certificate_exporter/logging.yaml) (Epic 4's new JSON formatter) | JSON file logs (Epic 4) have no per-export-pass ID — in watch mode, overlapping export passes triggered by rapid file-change events can't be told apart by any single log field | Generate a short run ID (e.g. `uuid4().hex[:8]`) once per `exportCertificates`/`exportCertificatesForFile` call and thread it through as a logging `extra` field (`pass_id`) |
| 6 | MINOR | Core §2 — reuse over copy-paste | [build-container.yaml](.github/workflows/build-container.yaml) | 3 near-identical `docker/login-action` steps (Docker Hub/GHCR/Custom) and 2 near-identical `docker/build-push-action` steps, differing only by registry/tags | Low priority — a matrix keyed by registry would remove the duplication, but GitHub Actions' conditional-secrets-per-registry pattern is a common, defensible trade-off; acceptable as-is or revisit if a 4th registry is ever added |
| 7 | MINOR (carried forward, not new) | Python overlay — ruff-clean | `settings.py` (RUF012 mutable class default, EXE001 shebang-not-executable), `certificate_exporter.py` (UP031 percent-format strings) | Pre-existing findings, already documented in AGENTS.md as "not yet fixed" before this session began; confirmed via `git diff` throughout Epics 1–6 that none of this session's changes touched these specific lines | Cosmetic; fix opportunistically or as a small follow-up story |

## What's now solid (confirmed, not just assumed)

- **Separation of concerns** — `app.py` (orchestration) never contains ACME-parsing or
  Docker-restart logic; `libs/settings.py`, `libs/docker.py`, `libs/certificate_exporter.py`,
  `libs/post_export.py`, `libs/logging_utils.py` each own one concern. No inward dependency
  on an outer layer found.
- **Testability** — 46 tests exercise real behavior: ACME v1/v2 parsing via synthetic
  fixtures, settings precedence across all 3 config surfaces, domain include/exclude across
  CLI/env/config-file, a real `subprocess`-invoking post-export hook (not over-mocked),
  redaction, and JSON logging output — verified via `logging.config.dictConfig`, not
  assumptions.
- **Dependency selection (core §7/§8)** — every dependency added this cycle
  (`cryptography`, `python-json-logger`) is GA, actively maintained, permissively licensed;
  no alpha/beta/preview dependency anywhere. GitHub Actions versions were checked against
  live release pages before bumping, not assumed.
- **Documentation (core §10)** — architectural, developer, and operational axes all
  present under `docs/`, with Mermaid diagrams in `docs/architecture.md` and
  `ARCHITECTURE-SPINE.md`; 5 ADRs recorded for every load-bearing decision made across the
  6 epics (Poetry, base image/privilege model, logging/secret redaction,
  dependency/build-artifact parity, CI reusable-workflow wiring).
- **No secrets in logs** — verified end-to-end that the PKCS12 passphrase and any
  future secret-shaped field are redacted before serialization, and that the new JSON log
  format doesn't re-expose an already-redacted value.

## Deferred, already recorded (not fresh findings)

- **Observability/metrics surface** — explicitly deferred in `ARCHITECTURE-SPINE.md`
  pending stakeholder validation (PRD backlog #21). Not re-flagged here.
- **GitHub repo-level secret-scanning/push-protection settings** — flagged as unverifiable
  in Epic 6's closure report (no admin/settings API access in-session), not silently
  dropped. Still open as a human action item, not a code gap.

## Gate

No BLOCKER findings. Both MAJOR findings (workflow permissions) were fixed immediately as
part of this review and verified with `actionlint`. The remaining MINOR findings can be
scheduled as a follow-up story or fixed opportunistically.

`DONE — Blocker: 0, Major: 0 (2 found, both fixed in-review), Minor: 4`
