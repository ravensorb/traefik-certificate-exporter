# ADR-0001: Use Poetry for Python dependency and environment management

- **Status:** Accepted (existing practice, recorded retroactively)
- **Date:** 2026-08-30
- **Deciders:** Maintainer (ravensorb)
- **Principle(s) in tension:** Core §7 dependency selection, Python overlay packaging & environment

## Context

The project needs a single source of truth for runtime/dev dependencies, a committed
lockfile for reproducible installs, and a build backend that produces both a PyPI package
and the version metadata consumed by `poetry-dynamic-versioning`. `pyproject.toml` already
uses `[tool.poetry.*]` tables and a committed `poetry.lock`.

## Options considered

| Option | Pros | Cons | Standards fit |
|--------|------|------|---------------|
| A. Poetry (current) | Already in place; lockfile committed; PEP 621-adjacent `pyproject.toml`; mature plugin ecosystem (`poetry-dynamic-versioning`) | Slower installs than `uv`; not the tool's own preference for *new* projects per standards | Satisfies Python overlay "Poetry or uv" requirement |
| B. Migrate to `uv` | Faster; single tool for env + build; is the standards' default preference for new work | Migration cost for no functional gain on an established, working project; would need to re-validate `poetry-dynamic-versioning`-equivalent tooling | Also satisfies the requirement, but standards explicitly say "Poetry is fully acceptable where already established" |

## Decision

Keep Poetry. It is already established, the lockfile is committed and used correctly by
`pre-commit`'s `poetry-lock --check` hook, and there is no functional problem it is causing —
the actual defects found (review findings #3, #7, #8) are dependency **declaration** bugs
(missing `cryptography`, `poetry` itself misplaced as a runtime dependency, Docker image
drifting from the lockfile), not a tooling-choice problem. Fix those in place rather than
migrating tools.

## Consequences

- Positive: no migration risk or churn on a stable toolchain choice.
- Negative / trade-offs accepted: does not get `uv`'s install-speed advantage; that's
  accepted as immaterial for a project this size.
- Follow-ups: none — this ADR does not require an exit plan since Poetry is GA and
  actively maintained (Core §8 n/a).
