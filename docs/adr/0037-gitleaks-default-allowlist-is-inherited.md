# ADR-0037: Secret scanning inherits gitleaks' default allowlist; the repository adds no path exemption

- **Status:** Accepted
- **Date:** 2026-10-09
- **Deciders:** Maintainer + architecture gate (E013, story E013-S01-005)
- **Epic:** E013
- **Departs from spec:** n/a
- **Amends:** ADR-0033 ("secret scanning exempts no path")

## Context

ADR-0033 states that secret scanning exempts no path, and its enforcement is that
`.gitleaks.toml` carries no `paths` key. But `.gitleaks.toml` also sets
`[extend] useDefault = true`, which loads gitleaks' built-in rules **and** its built-in
global allowlist. A traced run during the E013 architecture gate (2026-10-09:
`gitleaks dir --redact --no-banner --config .gitleaks.toml --log-level trace .`) showed that
allowlist skipping these paths:

| Skipped | Kind |
|---|---|
| `.git` | directory |
| `.venv/lib/python3.11` | directory (site-packages) |
| `.poetry/plugins/*.dist-info` (4) | directories |
| `poetry.lock`, `.poetry/plugins/poetry.lock` | files |
| `.gitleaks.toml` | file |

So "exempts no path" was not true as written, and nothing checked it.

The alternative is to drop `useDefault` and copy gitleaks' default rule set into this
repository. That is custom policy that has to be maintained by hand, which ADR-0035 and AD-4
rule out, and it would fall behind upstream rule updates.

## Decision

1. Secret scanning keeps `useDefault = true` and **accepts gitleaks' maintained default
   global allowlist**: lock files, dependency site-packages, and the VCS directory.
2. ADR-0033's rule is restated precisely: **the repository adds no path exemption.**
   `.gitleaks.toml` carries no `paths` key and no repository-specific path allowlist. Its
   two allowlists match exact values and lines (ADR-0033) and are unchanged.
3. The inherited exempt set is **written down and checked, not assumed.** The `.gitleaks.toml`
   header and `docs/developer.md` list it along with the gitleaks version that produced it.
   E013-S01-005's verification derives the set from a trace run (`skipping … global
   allowlist` lines) and diffs it against the recorded list. A gitleaks upgrade that changes
   the set must update the record in the same change.

## Consequences

- A credential committed into `poetry.lock` or `.gitleaks.toml` is not reported by the tree
  scan or the history scan. That risk is accepted: these files are generated or reviewed
  configuration, and both are CODEOWNERS-owned.
- Upstream changes to the default allowlist reach this repository through gitleaks upgrades
  — not through Dependabot, which has no `pre-commit` ecosystem entry in this repository, so a
  hook `rev` bump is manual (BL-E013-001). The recorded-set diff is run by hand at that upgrade;
  no CI check runs it, so a change to the inherited set is visible only if someone re-traces it.
- The near-miss findings in `_bmad/_config/files-manifest.csv` and in ADR-0033's own text
  that show as "skipping finding: global allowlist" come from the repository's value
  allowlists (ADR-0033), not from path exemptions.
