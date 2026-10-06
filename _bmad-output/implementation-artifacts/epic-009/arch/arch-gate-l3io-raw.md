# Epic E009 Pre-execution Architecture Gate — l3io-arch-review Mode B

## Executive summary

Epic E009 is **not ready for execution**: 3 BLOCKER, 6 MAJOR, and 2 MINOR findings remain.
The stories are unusually strong on negative cases and fail-closed behavior, but the runner-routing
contract, story dependency boundary, and evidence authenticity model are not implementable as
written. Resolve those three blockers first; then make credentials, trust/network boundaries,
failure injection, and action governance explicit before changing readiness to green.

Review scope was strictly limited to the two E009 story files, the supplied epic goal, the named
plan, and the spec index. Spec alignment was enabled, but neither story contains a resolvable Spec
pointer; the indexed specifications were therefore not opened or treated as additional review
inputs.

## Findings table

| # | Severity | Principle | Location | Finding | Remediation |
|---|---|---|---|---|---|
| 1 | BLOCKER | Core §3 Design by Contract; Core §4 Testability | `E009-S01-001.md:30-36,129-130` | Both trust classes use the same `ubuntu-24.04` label, while registration scope is the only named isolation mechanism. Owner/repository registration scope does not define a selector that distinguishes a protected publication job from an untrusted PR job in that same repository. The negative test demands that the protected registration cannot claim the PR job, but no schedulable discriminator or enforceable Gitea primitive is specified. The contract can therefore reject every tuple without describing a tuple that can pass. | Define the concrete Gitea routing primitive and its pre/postconditions. It must provide a mechanically testable trust-class selector that a PR cannot request or inherit. If this requires distinct labels or another topology change, record the ADR before execution and update the story rather than retaining the same-label prohibition. |
| 2 | BLOCKER | Core §1 Separation of Concerns; Core §3 Design by Contract | `E009-S01-001.md:104-108`; `E009-S01-002.md:13,17-49` | Story 9.1 cannot satisfy its DoD before Story 9.2: it requires the observed transitive action closure for **every certified scenario**, but the certification scenarios and evidence are owned by Story 9.2, which depends on Story 9.1. This creates a completion cycle and blurs baseline provisioning with certification. | Make Story 9.1 record the transitive closure of its structural preflight probes only. Make Story 9.2 own the closure across every certification scenario and the observed/recorded drift gate. Alternatively merge the stories and remove the dependency, but do not leave a predecessor dependent on its successor's executions. |
| 3 | BLOCKER | Core §3 Design by Contract; Core §4 Testability | `E009-S01-002.md:46-63,88-93` | The mechanical gate checks that a Markdown evidence document has an exact case set, run URL, and conclusion, but it does not authenticate those values against Gitea or bind them to the pinned tuple, source SHA, workflow revision, artifact hashes, and actual run conclusions. A fabricated or stale row can satisfy the declared test while providing no staging proof, so the gate cannot support the epic goal's repository-owner migration decision. | Define a machine-verifiable evidence acquisition boundary: query/export immutable run metadata from the pinned Gitea, bind every case to tuple ID, repository, source/workflow SHA, run attempt, job IDs/conclusions, and artifact hashes, and verify the document against that captured evidence. If offline verification is required, retain signed or hashed raw API exports as fixtures/artifacts and validate the report is a projection of them. |
| 4 | MAJOR | Core §1 Separation of Concerns; Core §3 Design by Contract | `E009-S01-001.md:17-23,75-82,109-110,131-132`; `E009-S01-002.md:74-80` | The stories conflate TLS trust roots with endpoint/network allowlisting. A CA bundle grants issuer trust and is not an endpoint-scoped list; “omit one derived verifier endpoint” is therefore not a CA-negative case. Conversely, minimal network access is stated but no firewall/proxy/DNS enforcement boundary owns the derived endpoint allowlist. | Split the model into (a) trust-store roots and rotation, and (b) network egress destinations and enforcement. Give each a distinct owner, evidence, and negative test: wrong/missing issuer for TLS; denied omitted host/port for egress. State whether public endpoints use system trust or a private interception root. |
| 5 | MAJOR | Core §3 Design by Contract; GitHub Actions overlay — least privilege/secrets | `E009-S01-001.md:30-43,111-112,126,133-136`; `E009-S01-002.md:36-39,74-77` | Credential isolation is asserted without a complete credential interface. The stories do not name the login identities, secret inputs, minimum token scopes, distinct-principal requirement, ownership of Release/Git-alias mutation credentials, or negative cross-destination authorization. “Only the forge package token” is not enough to build or certify least privilege. | Add a per-job credential matrix with secret name, principal/login identity, exact minimum scopes, protected environment/owner, and forbidden operations. Require distinct image/package/repository-mutation principals unless an ADR accepts a combined blast radius. Add denial tests proving each credential cannot mutate the other destinations and that disabled destinations receive no secret. |
| 6 | MAJOR | Core §4 Testability | `E009-S01-002.md:23-29,74-77,91-93` | The failed-jobs-only scenario specifies observations but not a deterministic fault-injection seam. “One destination fails after successful immutable publication elsewhere” can be induced by revoking a live credential, breaking a network path, or corrupting an endpoint; these exercise different behavior and can leave unrecoverable remote state. Cleanup is recorded but its required postconditions are not defined. | Specify a staging-only, destination-local failure mechanism and the exact failure point after the first immutable mutation. Define pre-state, expected partial state, rerun operation, same-artifact identity checks, and cleanup postconditions for packages, images, releases, aliases, tokens, and runner workspaces. |
| 7 | MAJOR | Core §3 Design by Contract | `E009-S01-001.md:25-28,53-56,135`; `E009-S01-002.md:41-44,74-77` | Forge/coordinate validation is not a complete contract. The stories require all coordinates to derive from two context values and test unknown forge/malformed registry, but never define accepted forge identities, normalization, same-host/path rules, canonical Gitea package/image coordinates, or the malformed cases. Independent implementations can disagree while passing the prose. | Define one authoritative forge classifier and coordinate projection with accepted normalized inputs, exact outputs, path/port handling, and failure taxonomy. Make the plan/classifier output the single value consumed by jobs; add table-driven positive and negative contract cases. |
| 8 | MAJOR | Core §7 Dependency selection; Core §8 GA over preview; GitHub Actions overlay — pinning | `E009-S01-001.md:45-62,84-91,104-108` | Recording an observed action set and source does not require that every action is maintained, licensed compatibly, GA, current, or pinned according to trust level. The fallback mentions SHA pinning, but the primary credential-bearing action paths have no equivalent acceptance rule. A pinned tuple can therefore certify stale or moving dependencies. | Extend tuple acceptance to record action reference and resolved commit, publisher/trust class, current supported major, maintenance/license status, and GA status. Require full SHAs for credential-bearing or untrusted third-party actions, current majors for approved actions, and an ADR plus exit plan for any preview/non-GA component. |
| 9 | MAJOR | Core §3 Design by Contract | `plan-2026-10-04-v1.yaml:3-4,26-34` | The plan declares readiness `green` and no gaps while also saying `stories_elaborated: 0` and `arch_gate_summary.ran: false`. That is internally contradictory for a pre-execution plan whose stories are present and whose architecture gate is required. Consumers can begin execution from a green signal before this gate's blockers are represented. | Mark E009 and plan readiness blocked/red until the gate is resolved or ADR-justified; set the elaboration count consistently; populate the architecture-gate summary with reviewers and findings before execution authorization. |
| 10 | MINOR | Core §9 Unified structured logging/correlation | `E009-S01-001.md:53-62,136`; `E009-S01-002.md:46-49,96-97` | Run ID/URL is retained at final evidence, but provisioning probes, structural probes, negative cases, cleanup, and secret-scan output are not required to carry a common correlation field. Diagnosing one certification attempt across runner-host and workflow boundaries may require manual timestamp matching. | Require a non-secret certification attempt ID propagated through runner/probe logs, job outputs, evidence rows, and cleanup records, with Gitea run/job IDs as structured fields. |
| 11 | MINOR | Core §10 Documentation | `E009-S01-001.md:95-116`; `E009-S01-002.md:65-82` | Story 9.1 requires a trust-ordering sequence diagram, but Story 9.2's non-trivial certification, partial-failure/rerun, decision, cutover, and rollback flow has no diagram requirement. The most operationally risky flow can remain prose-only. | Add a Mermaid certification/recovery flow or sequence diagram showing immutable publication, injected failure, failed-job rerun, gate decision, owner cutover, stop conditions, and rollback. Link it from the operational document. |

## Per-principle walkthrough

- **Core §1 Separation of Concerns:** Findings 2 and 4. Provisioning baseline, certification,
  trust roots, and egress policy cross their intended story/control boundaries.
- **Core §2 Reuse over copy-paste:** PASS. The stories explicitly exercise shared reusable
  workflows and local composites; no duplicate implementation is prescribed in the bounded input.
- **Core §3 Design by Contract:** Findings 1, 2, 3, 4, 5, 7, and 9. Several load-bearing
  preconditions and invariants are asserted without implementable interfaces or authoritative
  validation boundaries.
- **Core §4 Testability:** Findings 1, 3, and 6. The declared negative cases need enforceable
  routing, authentic evidence, and deterministic fault injection.
- **Core §5 Brevity/readability:** PASS. The stories are long but organize complex constraints and
  test anchors clearly; no implementation ceremony is mandated by the bounded input.
- **Core §6 Current-state comments:** PASS. Historical gate context is segregated and explains why
  requirements exist rather than prescribing changelog comments in code.
- **Core §7 Dependency selection:** Finding 8. Action adoption is observed but not vetted.
- **Core §8 GA over preview:** Finding 8. Tuple pinning alone does not prohibit preview components.
- **Core §9 Structured logging/correlation:** Finding 10. Final run identity exists, but end-to-end
  certification-attempt correlation is not required.
- **Core §10 Documentation/diagrams:** Finding 11. Trust ordering is diagrammed, but the
  certification/recovery/cutover flow is not.
- **GitHub Actions — marketplace actions over scripts:** PASS with bounded evidence. The stories
  refer to adopted actions/reusable workflows and do not prescribe sprawling inline shell.
- **GitHub Actions — pinning/latest versions:** Finding 8.
- **GitHub Actions — workflow hygiene:** Findings 1, 5, and 10. Least privilege, scheduling
  isolation, and correlated evidence are incomplete.
- **Shell — shebang/strict mode:** NOT ASSESSABLE. No shell script is included or explicitly added
  by the bounded story file scopes.
- **Shell — quoting:** NOT ASSESSABLE for the same reason.
- **Shell — temporary files/cleanup:** Finding 6 applies at the architectural cleanup-contract
  level; no shell implementation is available to inspect.
- **Shell — structure/escalation:** NOT ASSESSABLE. No script design is specified.
- **Shell — quality toolchain:** NOT ASSESSABLE. No shell artifact is in bounded scope.
- **Shell — secrets/logging:** Findings 5 and 10 apply to the workflow/probe contract; no shell
  implementation is available to inspect.

## Gate

**FAIL / BLOCKED FOR EXECUTION.** All BLOCKER and MAJOR findings must be resolved in the stories
and plan, or explicitly accepted by an ADR where the standard permits a departure. MINOR findings
may be deferred to the backlog. In particular, do not begin runner provisioning or enable any
publication credential until Findings 1–3 are closed.

## Recommended ADRs

1. **Gitea runner trust-class routing** — required if the supported tuple needs distinct labels,
   runner groups, on-demand registration, or another departure from the same-label constraint.
2. **Gitea credential principal and scope model** — required if image, package, Release, and Git
   alias mutations cannot use distinct least-privilege principals.
3. **Certification evidence authenticity/offline retention** — record the selected API-export,
   signing/hash, retention, and verification boundary.
4. **Non-GA or exceptional action adoption** — only if tuple discovery finds a load-bearing
   preview component or requires a pinning-policy exception.

## Sections read

- `.agents/skills/l3io-arch-review/SKILL.md` — complete
- `.agents/skills/l3io-arch-review/references/config-resolution.md` — complete
- `.agents/skills/l3io-arch-review/references/standards-core.md` — complete (§§1–10)
- `.agents/skills/l3io-arch-review/references/standards-github-actions.md` — complete
- `.agents/skills/l3io-arch-review/references/standards-shell.md` — complete
- `.agents/skills/l3io-arch-review/references/review-report.md` — complete
- `_bmad-output/implementation-artifacts/epic-009/sprint-01/stories/E009-S01-001.md` — complete
- `_bmad-output/implementation-artifacts/epic-009/sprint-01/stories/E009-S01-002.md` — complete
- `_bmad-output/planning-artifacts/plan-2026-10-04-v1.yaml` — complete
- `_bmad-output/implementation-artifacts/spec/spec-index.md` — complete; index only, no spec widening
- Supplied epic goal — complete

Spec alignment note: enabled, but no story supplied a resolvable Spec pointer; no full spec was
opened. Work type reviewed as `CONFIG`.
