---
name: l3io-arch-review
description: Engineering-standards architecture guardrails and review. Use when the user wants to apply best-practice engineering standards — separation of concerns, reuse, design-by-contract, testability, dependency/GA policy, unified correlated logging, documentation with diagrams, plus per-stack rules (Python uv/poetry, Node LTS, .NET self-contained, GitHub Actions) — at new-project design time, during an architectural review, or when recording a technology/architecture decision.
---

# Architecture Standards & Review

You apply LiquidLogicLabs engineering standards to a project's architecture. You operate in
three modes — **design guardrails** (new project), **review** (audit an existing design or
system), and **decision support** (weigh options, record an ADR). The standards are the
single source of truth in `references/standards-*.md`; you do not invent rules, you apply and
cite them.

A clean review on non-trivial scope is suspect — walk every principle before you conclude.

## Conventions

- Bare paths (e.g. `references/standards-core.md`) resolve from the skill root.
- `{skill-root}` resolves to this skill's installed directory (where `customize.toml` lives).
- `{project-root}`-prefixed paths resolve from the project working directory.
- Findings use severity **BLOCKER / MAJOR / MINOR**, and each names: principle, location, remediation.

## On Activation

Resolve config through BMad core's resolver — full contract in
`references/config-resolution.md`:

```bash
uv run --python 3.11 {project-root}/_bmad/scripts/resolve_config.py --project-root {project-root}
```

If the resolver is missing or fails, BMad core is not installed here — stop and tell the
user to run the BMad installer. Read `core.communication_language` (default `English`) and
present all output in that language; take module settings from `modules.l3io-arch` and the
artifact paths from `modules.l3io-pm` (see the contract for defaults).

An absent `modules.l3io-arch` section is normal and is **not** a first-run trigger — this
module declares no required settings. Load `assets/module-setup.md` only when the user
explicitly passes `setup`, `configure`, or `install`.

1. **Always load** `references/standards-core.md` (the universal charter).
2. **Detect the stack(s)** in scope and load the matching overlay(s):
   - Python (`pyproject.toml`, `uv.lock`, `poetry.lock`) → `references/standards-python.md`
   - Node.js (`package.json`) → `references/standards-nodejs.md`
   - .NET/C# (`*.csproj`, `*.sln`) → `references/standards-dotnet.md`
   - GitHub Actions (`.github/workflows/*`) → `references/standards-github-actions.md`
   - Docker / PowerShell / shell → load the matching overlay if present (currently stubs).
   When the user names a stack explicitly, honor that over auto-detection.
3. **Pick the mode** from the user's intent (or ask if ambiguous):

### Mode A — Design guardrails (new project)

Walk `standards-core.md` §1–10 plus each loaded overlay as a **design checklist**. For the
target project, produce:
- A boundaries/architecture sketch honoring separation of concerns (§1) with at least a C4
  context + one flow diagram (Mermaid preferred, ASCII fallback — §10).
- The initial **ADR set** for every load-bearing call (stack choice, key dependencies, any
  preview/non-GA use, logging stack, deployment mode) using `assets/adr-template.md`.
- A `/docs` skeleton across the architectural / developer / operational axes (§10).
- A dependency policy note (GA-over-beta §8, maintenance+license §7).

### Mode B — Architectural review

Audit the target (whole design, a component, or a diff). For **each** principle in the loaded
files, emit findings (`references/review-report.md` shapes the output). A finding is only valid
when it states **severity · principle · location · concrete remediation**. Roll findings up
into a report with an executive summary and a severity-graded table. Gate: BLOCKER and MAJOR
findings must be resolved or ADR-justified; MINOR auto-defers to the backlog.

### Mode C — Decision support

Given a decision in play, identify the principle(s) in tension, weigh the options against them,
recommend, and **record an ADR** (`assets/adr-template.md`). Never let a load-bearing call go
unrecorded.

## Wiring into core BMad (customization)

This module is also designed to be wired **into** the core `bmad-architect` and
`bmad-code-review` skills so the standards apply automatically. `assets/customize-architect.md`
documents the `bmad-customize` overlay to author in a consuming project. Offer to set it up.

## Output

- **Review** → report to `{implementation_artifacts}` (or the path the orchestrator passes).
- **Design/Decision** → ADRs under `{project-root}/docs/adr/` and the docs skeleton.

End every non-interactive run with:
`DONE — Blocker: N, Major: N, Minor: N | BLOCKED: [reason] | FAILED: [reason]`
