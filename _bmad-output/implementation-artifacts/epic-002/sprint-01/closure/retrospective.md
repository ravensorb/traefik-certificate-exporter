# Retrospective — E002 / Sprint S01

**Stories completed:** 5/5 (E002-S01-001 through E002-S01-005)

## What shipped

- **E002-S01-001** — `cryptography` declared as an explicit runtime dependency.
- **E002-S01-002** — `poetry` moved to dev dependencies; Docker image rebuilt as a multi-stage
  `poetry install --only main` build (ADR-0004), replacing the hand-maintained `pip install`
  list entirely.
- **E002-S01-003** — base image upgraded `ghcr.io/linuxserver/baseimage-alpine:3.19` (EOL,
  confirmed dead at the registry — its manifest index now resolves to zero platform
  manifests) → `3.24`, pinned by the multi-arch index digest.
- **E002-S01-004** — `build.yaml` rewritten to call `build-package.yaml`/`build-container.yaml`
  as job-level reusable workflows (ADR-0005); `actionlint` findings fixed (reserved `GITHUB_`
  var prefix, `ubuntu-20.04` runner label, missing `steps:` in `release.yaml`, shellcheck
  quoting) — `release.yaml`'s release-please job uncommented and restored to working order.
- **E002-S01-005** — the `if: ${{ env.ACT }}` CA-certificate step replaced with
  `LiquidLogicLabs/git-action-ca-certificate-import@v2`, gated on whether a
  `CI_CA_CERTIFICATE` secret is configured (works identically on GitHub, Gitea, and local
  `act`, rather than branching on which runner this is).

## Verification

Every change in this sprint was verified against a **real `docker build` + `docker run`**, not
just static review — this surfaced two real defects that static review would have missed:

1. Story 2.2/2.3 had to be resolved together: the rewritten Dockerfile initially failed to
   build (base image manifest empty, then PEP 668 externally-managed-environment blocking
   Poetry's system-wide install, then a venv shebang baked to the wrong build-stage path).
   All fixed; final image builds and the console script runs end-to-end (loads config, starts
   watching).
2. Upgrading to Alpine 3.24 (Python 3.14) broke `confuse` 2.0.1 at runtime
   (`pkgutil.get_loader` removed in 3.14). Fixed by updating to `confuse` 2.2.1 (already
   within the existing `^2.0.1` constraint) — `confuse`'s own changelog confirms 2.1.0 added
   Python 3.13/3.14 support for exactly this reason.

## Process incident (recorded for transparency, not a story-scope issue)

Running `pre-commit run --all-files` as a verification step applied `ruff-check --fix` /
`ruff-format` repo-wide, touching ~200 unrelated tracked files (including installed tooling
under `.agents/`). Recovered by reverting everything outside this sprint's actual scope, then
reconstructing `.pre-commit-config.yaml`'s hook wiring (lost in the same revert) from
`pre-commit`'s local cache plus session context. Also discovered and fixed `poetry lock
--check` no longer existing in Poetry 2.0+ (replaced with `poetry check --lock`). Full account
in `BL-E002-002`; lesson recorded in agent memory to prevent recurrence.

## Carry-over

None — all 5 stories completed within this sprint.
