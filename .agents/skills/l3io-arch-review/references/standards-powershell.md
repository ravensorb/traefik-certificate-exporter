# Engineering Standards — PowerShell Overlay

Loaded on top of `standards-core.md` when the project (or the component under review) is
PowerShell.

## Version — scope to the major, track the LTS within it

**Rule.** New work targets **PowerShell 7** (the major). Windows PowerShell **5.1 is a
different product**, not an older minor, and is not a target for new code.

Within 7.x, run a **currently supported LTS**. Which minor that is moves — and a standards file
that names one goes stale silently — so the rule is the major and the support state, not a
number. Check Microsoft's PowerShell support-lifecycle page at review time; a project on an
out-of-support 7.x minor is a finding with a date attached, not a preference.

- **Declare the floor** — `#Requires -Version 7` at minimum, tighter where a specific feature
  demands it. A version floor is a contract (core §3); its absence leaves requirements unstated.
- **Review** — Flag: `#Requires -Version 5.1` in new code, no `#Requires` at all, or a pinned
  7.x minor that is past end of support.

### 5.1 → 7: the breaks that actually bite

These are behavioural, not stylistic, and each has produced real incidents:

- **Default encoding.** 7.x is uniformly **UTF-8 without BOM**. 5.1 is inconsistent *per
  cmdlet* — `Out-File` and redirection UTF-16LE, `Set-Content`/`Get-Content` ANSI, `Export-Csv`
  ASCII. A BOM-less file written by 7 is misread by 5.1 as the legacy ANSI codepage, so
  non-ASCII content corrupts in one direction only. Set `-Encoding` explicitly at any boundary
  the two share.
- **Workflows are gone.** Windows Workflow Foundation is not in .NET Core, so `workflow` has no
  equivalent. A port is a rewrite, not a migration.
- **Windows-only modules** may load through `WinPSCompatSession`, which proxies into a
  background 5.1 process via implicit remoting. Know what that costs: you get **serialised
  values, not live objects**, it is local-Windows only, and it shares one runspace. Treat it as
  a bridge with a cost, never as "it works".

### Exceptions — where 5.1 is legitimate

A constrained endpoint, a legacy agent, or a Windows-only module with no 7.x path. When one
applies: **say so in the file header**, keep to the compatible subset deliberately, and record
it as a decision (core §6). What is not acceptable is silently writing 5.1-compatible code in a
7.x project and losing the newer constructs for an unstated reason.

## Script contract — strict, failing, and shaped like a cmdlet

**Rule.** Every non-trivial script or function opens with the same three lines, and advanced
functions carry `[CmdletBinding()]`.

```powershell
#Requires -Version 7
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
```

- **Why all three** — `StrictMode` turns a typo'd variable from a silent `$null` into an error;
  `ErrorActionPreference = 'Stop'` makes non-terminating errors actually stop, which is almost
  never what you want off. Neither is the default, and both change whether a bug is visible.
- **Approved verbs** — `Get-Verb`; a non-approved verb warns on module import and signals the
  function is doing something other than what its name implies.
- **Output objects, not formatted strings** — emit `[pscustomobject]`, let the caller format.
  A function that `Write-Host`s its result cannot be composed, tested, or piped (core §1).
  `Write-Host` is for interactive progress only; never for data.
- **Comment-based help** (`.SYNOPSIS`, `.PARAMETER`, `.EXAMPLE`) on anything exported (core §10).

## Quality toolchain

- **Lint** — **PSScriptAnalyzer** clean in CI, with a committed `PSScriptAnalyzerSettings.psd1`
  so local and CI agree. A suppression carries a justification comment (core §6).
- **Test** — **Pester 5**, invoked through a `[PesterConfiguration]` object rather than the
  older `Invoke-Pester` parameter set, which is why a Pester 4 invocation in CI is a finding
  rather than a style point. Keep logic in functions so it is testable (core §4).
- **Modules** — install with **PSResourceGet** (`Install-PSResource`), not the deprecated
  `PowerShellGet` v2 path. Pin versions for CI reproducibility.

## Secrets and logging

- **Never plaintext** — use the **SecretManagement** module with a vault; no credentials in
  source, in `$env:`, or echoed to a transcript.
- `[SecureString]`/`[pscredential]` at boundaries; do not `ConvertFrom-SecureString -AsPlainText`
  except at the exact point of use.
- **Structured logging with a correlation ID** (core §9). Prefer emitting objects a downstream
  collector can parse over free-text `Write-Verbose` narration.

## Review checklist (PowerShell-specific)

- [ ] Targets PowerShell 7 on a currently supported LTS minor; `#Requires -Version 7` present.
- [ ] Any 5.1 dependency is declared in the header with its reason, not silently implied.
- [ ] Encoding set explicitly at any boundary shared with 5.1.
- [ ] `#Requires`, `Set-StrictMode -Version Latest`, `$ErrorActionPreference = 'Stop'`.
- [ ] Approved verbs; `[CmdletBinding()]` on advanced functions.
- [ ] Emits objects, not formatted strings; `Write-Host` only for interactive progress.
- [ ] PSScriptAnalyzer clean with committed settings; suppressions justified.
- [ ] Pester 5 via `[PesterConfiguration]`; meaningful coverage of branching logic.
- [ ] Secrets via SecretManagement; nothing plaintext in source, env or transcript.
- [ ] Comment-based help on exported functions (core §10).
