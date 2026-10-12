# Spec proposal AD-2 (MAJOR) — import-linter / mypy hook dependency closures are unpinned in the dist-building job

- **Target pointer:** `_bmad-output/planning-artifacts/architecture/architecture-ci-cd-pipeline-2026-10-08/ARCHITECTURE-SPINE.md#ad-3--local-and-ci-gates-are-one-hook-list-adopted` (L106–116); also `docs/adr/0042-dependency-audit-scope-is-the-whole-lock.md` "Not covered, stated".
- **Finding:** `../arch-drift-review.md` AD-2.

## What was built

`.pre-commit-config.yaml` runs `import-linter` with `additional_dependencies: [import-linter==2.15]`; its transitive closure (`click`, `grimp`, `rich`, `typing-extensions`) and `mirrors-mypy`'s dependencies resolve fresh, unhashed and unaudited, inside `build.yaml`'s `build` job, which also runs `poetry build`. AD-3's last bullet states that local hooks' versions come from `poetry.lock` or `additional_dependencies`, which overstates coverage (global rule 3).

## Proposed change (for E015 triage)

Preferred: move `import-linter==2.15` into `[tool.poetry.group.dev.dependencies]`, make the hook `language: system` with `entry: env PYTHONPATH=src poetry run lint-imports --no-cache`, so it is hash-locked and covered by `pip-audit`; update the AD-3 bullet accordingly. Alternative: state the gap in AD-3 and ADR-0042 "Not covered" with owner and revisit condition, and the same for `mirrors-mypy`.

## Disposition rationale

Not a BLOCKER; 0.3.0 released; deferred to E015 per the epic-closure directive.
