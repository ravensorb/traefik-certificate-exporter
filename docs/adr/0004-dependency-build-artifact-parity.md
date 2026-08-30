# ADR-0004: Build the Docker image from the locked dependency set

- **Status:** Accepted
- **Date:** 2026-08-30
- **Deciders:** Maintainer (ravensorb), via `l3io-arch-review` Mode C (decision support)
- **Principle(s) in tension:** Core §2 reuse over copy-paste, Core §7 dependency selection, Python overlay packaging

## Context

Review finding #8 (MAJOR): `docker/Dockerfile` installs a hand-maintained, unpinned list of
packages via `pip install --break-system-packages`, duplicating (and already diverging from)
`pyproject.toml`'s dependency set — it adds `pyOpenSSL` (not a declared project dependency)
and omits an explicit `cryptography` pin (review finding #3). The two manifests can silently
drift further with every future dependency change.

## Options considered

| Option | Pros | Cons | Standards fit |
|--------|------|------|---------------|
| A. Keep hand-maintained pip list (current) | No build-process change | Already drifted; guaranteed to drift again; violates reuse/DRY | Fails Core §2 and Python overlay "Docker/CI installs from the lockfile" |
| B. Export the locked runtime deps (`poetry export --only main`) and `pip install` from that in the Dockerfile | Single source of truth (`poetry.lock`); image and package can no longer disagree | **Ruled out on current evidence** — since Poetry 2.0, `export` is no longer bundled; it requires the separate `poetry-plugin-export` plugin (verified against `python-poetry.org/docs/cli/#export`, checked 2026-08-30), adding a plugin-version dependency to the build stage for no offsetting benefit over Option C | Satisfies Core §2, but adds an avoidable moving part |
| C. `poetry install --only main` inside a build stage, copy the resulting venv/site-packages | Same parity guarantee as B, no export plugin needed; this is Poetry's own officially documented pattern for exactly this Docker-caching problem (`python-poetry.org/docs/faq/#poetry-and-docker`, checked 2026-08-30) | Slightly heavier build stage (Poetry itself present during build only, not in the final image) | Satisfies the standard directly, with no extra plugin dependency |

## Decision

**Option C** — `poetry install --only main` in a build stage, per Poetry's own documented
Docker pattern:

```dockerfile
FROM python:<pinned> AS builder
COPY pyproject.toml poetry.lock ./
RUN pip install poetry && poetry install --only main --no-root --no-directory
COPY src/ ./src
RUN poetry install --only main
# then copy the resulting venv/site-packages into the final runtime stage
```

Option B (`poetry export`) is explicitly rejected: it would add a `poetry-plugin-export`
version dependency to the build for a result Option C already achieves with a Poetry
command that ships in the box. The Docker image's dependency set is derived from
`poetry.lock` via this mechanism — never a separately hand-maintained list. CI should fail
if the image's installed set and the lockfile diverge.

## Consequences

- Positive: eliminates an entire class of "works from PyPI, broken in the image" (or vice
  versa) bugs — this ADR exists precisely because that already happened (`cryptography`).
  No extra plugin to track/version alongside Poetry itself.
- Negative / trade-offs accepted: multi-stage Dockerfile complexity (builder stage only —
  Poetry itself never ships in the final runtime image).
- Follow-ups: once implemented (PRD backlog item #8 / Epic 2 Story 2.2), delete the
  hand-maintained `pip install` list entirely.

