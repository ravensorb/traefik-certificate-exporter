# Engineering Standards — Python Overlay

Loaded on top of `standards-core.md` when the project (or the component under review) is Python.

## Packaging & environment — poetry or uv, for ALL apps and packages

**Rule.** Every Python application **and** library uses **Poetry or uv** for dependency and
environment management. No bare `pip install`-into-system, no hand-maintained
`requirements.txt` as the source of truth, no ad-hoc virtualenv juggling.

- **Design/decision** — Pick one of Poetry or uv per repo and stay consistent. `uv` is the
  default preference for new work (speed, lockfile, single tool for envs+builds); Poetry is
  fully acceptable where already established. Record the choice.
- **Lockfile is committed** — `uv.lock` / `poetry.lock` is committed and CI installs from it
  (`uv sync --frozen` / `poetry install`). Builds are reproducible.
- **Layout** — `pyproject.toml` is the single source of truth (PEP 621 metadata). `src/`
  layout for libraries. Dependency groups separate runtime / dev / test.
- **Review** — Flag: `requirements.txt` used as the primary manifest, `pip install` in
  Dockerfiles/CI instead of the chosen tool, missing/stale lockfile, `setup.py`-only
  packaging for new code. BLOCKER if there is no locked, reproducible install path.

## Version & runtime

- Target a **supported, non-EOL** Python (per section 8 of core: GA over preview — avoid
  depending on unreleased CPython). Pin the interpreter range in `pyproject.toml`
  (`requires-python`).
- Prefer `uv python` / `.python-version` to pin the exact interpreter for reproducibility.

## Quality toolchain (aligns with core testability & brevity)

- **Type checking** — `mypy` or `pyright` in `strict` where feasible; types are contracts (core §3).
- **Lint/format** — `ruff` (lint + format) is the preferred single tool.
- **Test** — `pytest`; keep pure logic unit-testable (core §4). Fixtures inject collaborators.
- **Logging** — structured logging with correlation IDs (core §9): prefer `structlog` or
  stdlib `logging` with a JSON formatter + `contextvars`-propagated `trace_id`. Never `print`.

## Review checklist (Python-specific)

- [ ] Managed by uv or Poetry, lockfile committed, CI installs frozen.
- [ ] `pyproject.toml` is the source of truth; `requires-python` bounded to supported versions.
- [ ] Type-checked (mypy/pyright) and ruff-clean.
- [ ] Structured logging with propagated correlation ID; no stray `print`.
- [ ] Dependencies GA, maintained, license-checked (core §7/§8).
