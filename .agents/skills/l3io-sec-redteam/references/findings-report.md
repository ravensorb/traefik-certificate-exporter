# Findings Report

## What Success Looks Like

A report that an adversary could use to reproduce every finding, and that a developer could use to fix every finding. No finding ships without an attack path and a recommendation.

## Report Format

### Output Format Decision

- **HTML** — when invoked standalone or when output path ends in `.html`. Structured table with severity color-coding (CRITICAL=red, HIGH=orange, MEDIUM=yellow, LOW=blue, OBSERVATION=grey).
- **Markdown** — when writing to l3io-pm closure directories (output path ends in `.md`). Use structured headers and tables.

### Structure

```
RED TEAM FINDINGS REPORT
{Scope}: {Scope Target}
Date: {YYYY-MM-DD}
Analyst: Red Team Agent

SEVERITY SUMMARY
  CRITICAL:    N
  HIGH:        N
  MEDIUM:      N
  LOW:         N
  OBSERVATION: N

FINDINGS
[Findings table — see below]

EXECUTIVE SUMMARY
[See below]
```

### Findings Table

Each finding row:
| Severity | ID | Title | Lens | Attack Path | Impact | Recommendation |
|----------|----|-------|------|-------------|--------|----------------|

**Severity levels:**
- **CRITICAL** — exploitable today with significant impact; blocks release
- **HIGH** — serious risk; fix before release
- **MEDIUM** — meaningful risk; fix in next sprint or create backlog story
- **LOW** — hardening opportunity; backlog or accept with rationale
- **OBSERVATION** — not a vulnerability: monitoring gaps, logging issues, code smells worth noting

**Lens codes:** EXT (external attacker), INS (malicious insider), CHA (chaos engineer), ABU (abusive legitimate user), PBR (platform best practices), DAR (design/architecture), AIP (AI poisoning)

### Executive Summary

One paragraph covering:
1. What was reviewed (scope, surface area, tech stack)
2. Overall risk posture (CRITICAL/HIGH/MEDIUM/LOW/CLEAN — with honest justification for CLEAN)
3. The single most dangerous finding and why
4. The single most important recommendation

## HTML Color-Coding (when outputting HTML)

```html
<tr class="critical">  <!-- background: #fee2e2 (red-100) -->
<tr class="high">      <!-- background: #ffedd5 (orange-100) -->
<tr class="medium">    <!-- background: #fef9c3 (yellow-100) -->
<tr class="low">       <!-- background: #dbeafe (blue-100) -->
<tr class="obs">       <!-- background: #f1f5f9 (slate-100) -->
```

## After the Report

In interactive mode: offer to walk through findings in priority order and discuss remediation approach.

In orchestrator invocation mode: write the report to the specified output path and emit the status line.
