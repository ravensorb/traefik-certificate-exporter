# Epic Closure Retrospective — E002: Reliable Installation, Build & Release Pipeline

**Velocity:** 5/5 stories done in a single sprint (S01) — no carry-over.

**What this epic actually validated:** every fix was checked against a real `docker build` +
`docker run`, not just a review of the YAML/Dockerfile diff. That discipline caught two real
defects that would otherwise have shipped silently: a completely dead base-image tag (empty
manifest index at the registry) and a `confuse`/Python 3.14 incompatibility introduced by the
very base-image upgrade this epic made. Static review of the Dockerfile diff alone would not
have caught either.

**Process note:** a `pre-commit run --all-files` verification step caused an unintended
~200-file repo-wide reformat (including installed tooling under `.agents/`), recovered by
reverting out-of-scope files and reconstructing `.pre-commit-config.yaml`'s hook wiring. Lesson
recorded in agent memory (`pre-commit-and-ruff.md`): scope hook runs to touched files only.

## Architectural drift review (epic-level, work_type=CODE)

Single sprint, so epic-level scope matches sprint-level review already performed. Consistent
with ADR-0001 (Poetry), ADR-0002 (base image/digest pinning), ADR-0004 (locked-dependency
image build), ADR-0005 (job-level reusable workflows). No new ADR required.

## Epic security review (work_type=CODE)

Multi-stage build correctly excludes the build toolchain (gcc, musl-dev, libffi-dev,
openssl-dev, cargo, poetry itself) from the final image — smaller attack surface than the
original single-stage Dockerfile. No secrets committed; the CA-certificate mechanism sources
from `secrets.CI_CA_CERTIFICATE`, never a hardcoded value. No CRITICAL/HIGH/MEDIUM findings.

## Issue triage

2 issues total: 1 fixed in-sprint (`BL-E002-001`, HIGH — confuse/Python 3.14), 1 process note
(`BL-E002-002`, LOW — pre-commit scope-creep incident, not a shipped code defect). Neither
promoted or deferred further at epic level.
