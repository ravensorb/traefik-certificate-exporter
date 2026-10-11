# Whole-solution review — all epics against the architecture (2026-10-10, HEAD 2139ad8)

Three independent lenses, each with a full report in this folder:

| Lens | Report | Verdict | Blocker | Major | Minor |
|---|---|---|---|---|---|
| Product spine vs code (E001–E006, E010–E012, E013-S02-004) | review-product.md | Not conformant | 2 | 8 | 11 |
| CI/CD spine vs pipeline (E007–E009, E012-S01-003, E013) | review-cicd.md | Conditional pass | 0 | 5 | 16 |
| Cross-epic coherence (decisions, PRD, state, docs) | review-coherence.md | Code/CI coherent; written record lags | 0 | 7 | 14 |

`just check` is green in all three (14 hooks, 216 tests). Neither blocker is visible to it.

## Blockers (product)

- **B1 — Container restart cannot work in any shipped build.** Locked `docker` 6.1.3 + `requests` 2.32.3 → `DockerException: Not supported URL scheme http+docker` (re-confirmed by the orchestrator with a direct client ping). Fixed upstream in docker-py 7.1. `docker.py` catches and logs it; every restart test mocks `docker.from_env`.
- **B2 — Setting `pkcs12passphrase` breaks every `.pfx` export** (`certificate_exporter.py:625` passes the passphrase as the key-load password → `TypeError`); the domain then drops out of the exported list, so its restart, hook and notification are skipped after its PEMs were already replaced.

## Majors, grouped

**Product behaviour**
- Settings that do nothing: `--restart-container` writes `restartcontainer` (code reads `restartcontainers`); sample env-var names in `docker/README.md` and `docker/docker-compose.yml` match no setting; container log level cannot be changed (overlaps BL-E013-042).
- ACME parsing: version detected by substring `"acme-v02"` (non-Let's-Encrypt CAs export nothing); `"Certificates": null` aborts the whole file.
- s6 service reads `WATCHFORCHANGES` from raw env instead of resolved settings → restart loop when watching is off.
- Restart cooldown drops (not defers) a second renewal inside 300 s; no ADR.
- Module layering drift (watch, restart, hook, notify in `certificate_exporter.py`) with no ADR.

**Decision record and docs**
- ADR statuses wrong: ADR-0030 still `Proposed` with the old rule in its title; 0003, 0023, 0024, 0026, 0027 implemented but `Proposed`; 0016/0017 "superseded by scope" with no recording ADR; ADR-0039 missing from `docs/architecture.md` §6; `adr-register.yaml` mis-numbered and incomplete; ADR-0034 gap unexplained.
- Product spine (2026-08-30) never updated: base image, AD-2/AD-4/AD-5, privilege model, Deferred list contradict live ADRs.
- README, `docs/operational.md`, `docs/architecture.md` describe `PUBLISH_*` secrets without the `dev`/`release` environments — following them bypasses the ADR-0039 gate.
- `AGENTS.md` points to the stale product spine and PRD §6 as the backlog; omits the CI/CD spine.
- `docs/guidelines.md` §10 hook table lists hooks that do not run and omits zizmor, gitleaks-history and the pygrep rules.

**CI/CD and forge**
- GitHub still holds repository-level `DOCKERHUB_TOKEN`/`DOCKERHUB_USERNAME` (checklist step 1 pending).
- Actions settings `default_workflow_permissions: write` + `can_approve_pull_request_reviews: true` are outside the checklist and could let a branch workflow approve its own PR.
- Release path never run on any forge; PyPI, TestPyPI, GHCR, Docker Hub, forge release, floating `X.Y`/`X`/`latest` (and `:0` on 0.x) and a Gitea runner unproven.
- ~150 lines of publish logic duplicated between `dev.yaml` and `release.yaml` without an ADR.

**State**
- E012 still `in-progress` with a stale lock; E012-S01-002 stuck `in-progress` though ADR-0035 retired its work; sprint statuses wrong; nine Medium issues scheduled into E012, five already settled by ADR-0035/0037.

## Recommended handling

1. **Release blockers for 0.3.0** (product correctness): B1, B2, the dead setting names, the s6 restart loop, ACME version detection / null-Certificates handling.
2. **Forge hygiene** (minutes, maintainer): delete legacy repository secrets; set default workflow permissions to read and disable Actions PR approval; add both to the checklist.
3. **Decision-record repair** (docs only): ADR statuses and titles, §6 index, register, product-spine update, AGENTS.md pointers, guidelines §10, environment wording in README/operational/architecture.
4. **State cleanup**: close E012 (S01-002 superseded; triage its scheduled issues; S01-004 CLI hygiene to the next epic).
5. **Then** the 0.3.0 release dry run (release path, floating tags, forge release) before `just release minor`.
