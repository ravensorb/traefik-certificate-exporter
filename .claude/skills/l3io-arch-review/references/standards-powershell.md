# Engineering Standards — PowerShell Overlay (COMING NEXT — stub)

> **Status: placeholder.** Scaffolded, not yet authored. Apply `standards-core.md` meanwhile.

Planned rules (draft):

- PowerShell 7+ (cross-platform, GA); avoid Windows PowerShell 5.1 for new work.
- `Set-StrictMode`; `$ErrorActionPreference = 'Stop'`; approved verbs; `[CmdletBinding()]`.
- PSScriptAnalyzer clean in CI; Pester tests for non-trivial logic (core §4).
- Structured output objects over formatted strings; comment-based help (core §6/§10).
- No plaintext secrets; use SecretManagement; correlation IDs in logs (core §9).

TODO: promote to full standard.
