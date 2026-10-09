# E013 Architecture Gate Review

- **Epic:** E013 — Standard CI/CD pipeline (ADR-0035)
- **Reviewers run:** l3io-arch-review (Mode B), then bmad-agent-architect (escalated on MAJOR)
- **Inputs:** E013-S01-001..004 story files, 2026-10-08 CI/CD spine, ADR-0035, spec index (no story pointers resolved)

## Consolidated findings

| ID | Severity | Sources | Finding | Resolution |
|---|---|---|---|---|
| AG-1 | BLOCKER | architect | `publish-package` (S01-002) has no checkout before `poetry install`; fails every dev/release run, and `release` needs it | Story patch: ref-free checkout (fetch-depth 0, tags, no persisted credentials) before install, or `POETRY_DYNAMIC_VERSIONING_BYPASS` |
| AG-2 | MAJOR confirmed | both | S01-001 AC "`just check` passes" cannot pass before S01-002 removes `tests/ci/`; 001+002 must land as one change | Story patch + sprint note |
| AG-3 | MAJOR confirmed | both | S01-003 consumes S01-004 outputs (act record, verification doc) but depends only on 002 | Dependency change: 003 depends on 004 |
| AG-4 | MAJOR (single-source; architect rated MINOR) | arch-review | AD-17 `VERSION = image-version` conflicts with `just image` passing the PEP 440 wheel version; resolved locally in stories | Spine/ADR amendment (ADR-0036) |
| AG-5 | MAJOR confirmed | both | Dockerfile builder `poetry install` with no `.git` + pdv strict fails once AD-7 lands; no owner | Story patch (S01-002 Dockerfile) + ADR-0036 |
| AG-6 | MAJOR confirmed | both | Poetry 2 `requires-plugins` installs into project-local `.poetry/`, not gitignored: `just release` clean-tree check always fails; gitleaks scans it | Story patch (S01-001 `.gitignore`) |
| AG-7 | MAJOR confirmed | both | `just act` without `--detect-event` runs nothing for `pull_request` workflows: false green | ADR-0036 (AD-16 amendment) + story patches |
| AG-8 | MAJOR confirmed | both | zizmor audits beyond `unpinned-uses` (use-trusted-publishing, dependabot-cooldown) make "zizmor passes" unmeetable without an ad hoc suppression | ADR-0036 (AD-5 suppression rule) + story patches |
| AG-9 | MAJOR confirmed | both | `.gitleaks.toml` comments claim enforcement by tests/jobs S01-002 deletes; S01-003 leaves it unchanged (global rule 3) | Story patch (S01-003 scope) |
| AG-10 | MAJOR confirmed | both | "re-run rewrites tags to the same digest" is unachievable for a multi-arch rebuild | ADR-0036 (Conventions amendment) + story patches |
| AG-11 | MAJOR (single-source) | architect | Secret scanning of history (`gitleaks git`) silently dropped by AD-3's hook list | ADR-0036 (AD-3 amendment: history hook) + S01-001 patch |

MINOR findings: folded into the same resolution pass where they are story-text corrections (release-job CA import, tag/version equality guard, changelog previous-tag pattern, `git fetch --tags --force` and empty-match handling, ADR-0035 status change moved to S01-004, reference-sweep terms, bad-release runbook entry, `0.x` major-tag check, pip-vendored `packaging` note). Deferred to the issues file: pre-commit hook `rev:` pinning to commit SHAs (design decision for the maintainer), and story `Spec:` pointers to the indexed spine.

## Resolution approach

One ADR (ADR-0036) records the four spine-level amendments (AG-4, AG-7, AG-8, AG-10, AG-11) instead of one ADR per finding: the remaining blocking findings are story-text and sequencing corrections with no design decision to record, the same precedent as E012's gate (AG-1 there was a doc/state sync). Story files are patched in one pass; re-validation asks each reviewer only whether its findings are resolved by the ADR and the patched sections.

## Gate pass 2 — 2026-10-09 (new story E013-S01-005 only)

Reviewers run: l3io-arch-review (Mode B), escalated to bmad-agent-architect on MAJOR. Stories 001–003 were gated in pass 1 and are done.

| ID | Severity | Sources | Finding | Resolution |
|---|---|---|---|---|
| AG-12 | MAJOR confirmed | both | BL-E013-004 AC claims "no path is exempted" but `useDefault = true` inherits gitleaks' default global allowlist (trace: `.git`, `.venv/lib/python3.11`, `.poetry/plugins/*.dist-info`, `poetry.lock`, `.poetry/plugins/poetry.lock`, `.gitleaks.toml`); the grep check is a false green | ADR-0037 (accept the maintained default allowlist; repository adds no path exemption; inherited set recorded and diffed against a trace) + story patch |
| AG-13 | MAJOR confirmed | both | BL-E013-003 AC sanctions a bypass site ADR-0036 does not grant; redundant where used (full-history checkout) | Story patch: conform to ADR-0036, remove the redundant bypass |
| AG-14 | MINOR confirmed | both | Registry guard ungated vs AD-10 | Folded: gate on `PUBLISH_IMAGE` |
| AG-15 | MINOR (architect PARTIAL) | both | Guard placed before CA import vs AD-18 | Folded: place after CA import; release version-guard ordering to spec-proposal item |
| AG-16 | MINOR confirmed | both | BL-E013-013 check reads amendments from the wrong place | Folded |
| AG-17 | MINOR | architect | BL-E013-013 ADR set hand-kept (rule 4) | Folded: derive from `docs/adr/*.md` |
| AG-18 | MINOR | architect | Dockerfile `poetry config` call outside the bypass is unclassified | Folded: classify with evidence; file if it loads the project |
