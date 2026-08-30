# Engineering Standards — Core (Universal)

These principles are **stack-agnostic** and apply to every project. Load the relevant
`standards-<stack>.md` overlay(s) on top of this file for language/platform specifics.

Each principle is written to be usable at **three moments**:

- **Design** — when authoring a new architecture or making a technology/decision call.
- **Review** — when auditing an existing design, diff, or system for compliance.
- **Decision** — when recording *why* a call was made (feeds the ADR; see `assets/adr-template.md`).

Severity for review findings: **BLOCKER** (violates a hard rule) · **MAJOR** (clear
deviation, must justify or fix) · **MINOR** (improvement opportunity). A finding is only
valid when it names the principle, the location, and the concrete remediation.

---

## 1. Separation of Concerns — leakage is a defect

**Rule.** Each module owns one responsibility. Concerns (domain logic, persistence,
transport, presentation, config, cross-cutting infra) do not leak across boundaries.

- **Design** — Draw the boundaries first. Domain logic never imports transport/ORM types;
  persistence details never surface in the API contract; UI holds no business rules.
- **Review** — Trace an import graph. Flag any inward dependency on an outer layer, any
  SQL/HTTP/framework type crossing a domain boundary, any "God" module doing three jobs.
- **Red flags** — a domain object with a `@Column`/`@Entity` annotation; a controller with
  business branching; config values read deep inside domain code; circular dependencies.

## 2. Reuse over copy-paste — refactor rather than duplicate

**Rule.** Duplication of non-trivial logic is not allowed. If reuse requires refactoring
(extract, generalize, promote to a shared module), do the refactor — that is the expected
cost, not an excuse to copy.

- **Design** — Identify the shared kernel up front; give it a home (shared lib/package).
- **Review** — Hunt for near-identical blocks (>~5 meaningful lines) across files/services.
  Each is a MAJOR finding: propose the extraction target.
- **Nuance** — Do not over-abstract. Two occurrences may wait; three is a duplication smell.
  Coincidental similarity (same shape, different reason to change) is *not* duplication —
  do not couple them.

## 3. Design by Contract — always preferred

**Rule.** Every non-trivial unit declares its **preconditions, postconditions, and
invariants** explicitly (types, guards, assertions, schema validation at boundaries).

- **Design** — Define interfaces/contracts before implementations. Validate inputs at the
  system edge; trust them inside. Make illegal states unrepresentable via the type system.
- **Review** — Flag public functions with unchecked inputs, implicit nullability, or
  undocumented failure modes. Flag "defensive" re-validation deep inside a trusted core
  (a boundary-validation smell — the contract should have been asserted at the edge).
- **Decision** — Prefer total functions and explicit `Result`/error types over exceptions
  for expected failure paths; reserve exceptions for the truly exceptional.

## 4. Testability is a first-class design constraint

**Rule.** If it is hard to test, the design is wrong. Dependencies are injected, side
effects are isolated at the edges, and pure logic is separable from I/O.

- **Design** — Depend on abstractions, not concretes. Keep a functional core / imperative
  shell. No hidden global state, no `new`-ing collaborators inside business logic.
- **Review** — Flag untestable seams: static singletons, hard-wired clocks/network/FS,
  private logic reachable only through heavy integration paths. Ask "what's the unit test
  for this?" — if the answer needs a full environment, that's a MAJOR finding.
- **Decision** — Record the test strategy per component (unit / contract / integration /
  e2e) and the target confidence, not a raw coverage number.

## 5. Brevity without sacrificing readability

**Rule.** The goal is the least code that a competent reader understands on first pass.
Brevity that hurts readability is a defect; verbosity that adds no clarity is waste.

- **Design** — Prefer straightforward, boring solutions. Clever one-liners that need a
  comment to decode are usually the wrong trade.
- **Review** — Flag both extremes: golfed/obscure code, *and* ceremony/boilerplate that a
  standard library or language idiom removes. Optimize for the reader, not the writer.

## 6. Comments explain current state and intent — not history

**Rule.** Comments describe *what the code does now and why*, at the level the code cannot
express itself. We do **not** annotate every fix, and we do not narrate change history in
comments (that is git's job).

- **Write** — the non-obvious *why*, invariants, contracts, gotchas, links to the deciding ADR.
- **Do not write** — "fixed bug", "changed per review", "TODO(me) 2021", restating the code
  in English, or a comment on every line.
- **Review** — Flag stale comments (contradict the code), changelog-in-comments, and dense
  code with zero explanation of intent. A stale comment is worse than none.

## 7. Dependency selection — established, maintained, well-licensed

**Rule.** Prefer well-established packages with **active maintenance**, a healthy community,
and a **permissive/compatible license**. Every dependency is a liability you are adopting.

- **Checklist (at design/decision time)** —
  - Maintenance: recent releases, responsive issues, not a single-maintainer bus factor.
  - Adoption: meaningful download/usage base; not abandoned or pre-1.0 unless justified.
  - License: compatible with the project's distribution model; **no copyleft surprises**
    in shipped artifacts. Record the license in the dependency inventory.
  - Security: no known unpatched CVEs; supports the versions you target.
  - Footprint: transitive dependency weight is proportionate to the value delivered.
- **Review** — Flag unmaintained, unvetted, or license-incompatible dependencies, and
  "left-pad" micro-deps that a few lines would replace. Record the justification in an ADR.

## 8. GA over alpha/beta — unless there is a strong, recorded need

**Rule.** Depend on **generally-available, stable** releases. Alpha/beta/preview/RC
dependencies, language features, and cloud services require an explicit, ADR-recorded
justification and an exit/upgrade plan.

- **Design** — Default to GA. If a preview capability is load-bearing, record: why it's
  needed, the blast radius, and the migration path when it GAs or is dropped.
- **Review** — Flag any `-alpha`/`-beta`/`-rc`/`-preview`/`-SNAPSHOT` dependency or
  preview cloud feature without a recorded justification. BLOCKER for anything in the
  shipped/production path without a plan.

## 9. Unified, structured logging with cross-boundary correlation

**Rule.** One logging approach across the whole system. Logs are **structured**
(key/value, not string soup) and carry a **correlation/trace ID that propagates across
every boundary** — service→service, sync→async, request→job→callback.

- **Design** — Pick one logging library/format per language and a shared schema (level,
  timestamp, service, `trace_id`/`correlation_id`, `span_id`, message, structured fields).
  Adopt or align to OpenTelemetry semantics where practical. Propagate context via headers
  (e.g. `traceparent`) and message metadata; never drop the ID at an async hop.
- **Review** — Flag: ad-hoc `print`/`console.log`, unstructured messages, missing
  correlation ID, IDs that die at a queue/boundary, secrets/PII in logs, inconsistent
  levels. A request you cannot trace end-to-end by a single ID is a MAJOR finding.
- **Decision** — Record the log schema, the correlation mechanism, retention, and the
  sink/aggregation target.

## 10. Documentation is always recommended — organized, and diagram-first where it helps

**Rule.** Every project carries documentation across the relevant axes — **architectural,
developer, operational** (and API/user where applicable) — kept **well-organized** and
discoverable. Diagrams are included wherever they aid understanding.

- **Axes** —
  - *Architectural* — context, container/component views, key decisions (ADRs), data flows.
  - *Developer* — setup, build, test, contribution, local run, conventions.
  - *Operational* — deploy, config, runbooks, monitoring/alerting, on-call, rollback.
  - *API / User* — contract reference and consumer guides where there is an external surface.
- **Diagrams** — **Mermaid is preferred** (versionable, diff-able, renders in most tooling);
  **ASCII is the accepted fallback** where Mermaid can't render. Prefer C4-style leveling
  (context → container → component) and sequence diagrams for flows. Every non-trivial
  design includes at least a context + one flow diagram.
- **Organization** — a single documented home (e.g. `/docs`) with an index; docs live in
  the repo next to what they describe; stale docs are a defect, not a nicety.
- **Review** — Flag: missing operational runbook, no architecture overview, undocumented
  public API, diagrams absent where a flow is non-trivial, docs that contradict the code.

---

## Decision-making hook

Whenever a call is made against any principle above — choosing a dependency, accepting a
preview feature, drawing a boundary, picking a logging stack — **record it as an ADR** using
`assets/adr-template.md`. The ADR must name the principle(s) in tension, the options weighed,
the decision, and the consequences. Architecture without recorded decisions is unreviewable.

## How to apply this file

- **New project (design):** walk sections 1–10 as a design checklist; produce the initial
  ADRs and the docs skeleton before code.
- **Architectural review:** walk sections 1–10 against the target; emit findings with
  severity, location, principle, and remediation; roll up into the review report.
- **Ongoing decisions:** consult the relevant principle, weigh options, record an ADR.
