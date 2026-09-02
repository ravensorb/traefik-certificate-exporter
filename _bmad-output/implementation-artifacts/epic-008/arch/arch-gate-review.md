---
title: 'Epic architecture gate — E008 Multi-Channel Delivery, E009 Certified Gitea Portability'
mode: 'B — Architectural review (pre-implementation)'
date: '2026-09-01'
reviewer: 'l3io-arch-review'
dispatched_by: 'l3io-pm-execute step-04'
work_type: 'MIXED'
epics: ['E008 (phase 1)', 'E009 (phase 2)']
sprint: 'S01'
standards_loaded:
  - '.claude/skills/l3io-arch-review/references/standards-core.md'
  - '.claude/skills/l3io-arch-review/references/standards-github-actions.md'
  - '.claude/skills/l3io-arch-review/references/standards-python.md'
  - '.claude/skills/l3io-arch-review/references/standards-docker.md (stub)'
  - '.claude/skills/l3io-arch-review/references/standards-shell.md (stub)'
verdict: 'CHANGES REQUIRED — 3 BLOCKER, 17 MAJOR, 10 MINOR'
---

# Epic architecture gate — E008 / E009

## Executive summary

The six stories describe a coherent, genuinely leaner delivery model, and the retirement of the
publication-transaction framework holds: **no story requires a publication plan, a release
receipt, remote identity reconciliation, or an aggregate transactional preflight.** The
build-once provenance root (one wheel, one hash, one manifest) is real and already enforced by
shipped code. Leanness is not a finding anywhere in this report.

What the review found instead is that this design lands its first credential-bearing workflows
onto a guard set that was written when no such workflow existed, and **several of those guards
are scoped to the files that exist today rather than to the rule they enforce**. Three
contradictions are hard stops: the mandated PyPI action pin is rejected by the shipped tier-one
policy test; nothing prevents the caller of the secret-free verifier from handing it
`secrets: inherit`; and the forge Release — the one artifact E009 must reproduce on Gitea — has
no host-neutral mechanism, because the approved-owner set contains no release-creating action
and `gh` is GitHub-only.

**The single most important action:** before any of `dev.yaml` / `release.yaml` is written,
settle the four decisions that determine job topology — the PyPI pin form (F1), the Release
mechanism (F3), how "enabled but skipped" is distinguished from "required and failed" at the
finalizer (F7), and where the forward-only alias comparison reads its "current" version (F4).
Each is cheap now and expensive after two workflows exist in duplicate.

## Scope of this review

Read in full: the six stories. Read as needed: `ARCHITECTURE-SPINE.md`,
`spec-retire-publication-transaction.md`, `docs/ci/codex-assesment.md`, ADR-0006 / 0007 / 0008,
`.github/workflows/ci.yaml`, `.github/workflows/verify-build.yaml`,
`.github/actions/setup-poetry-python/action.yml`,
`.github/actions/publication-contract/action.yml`, `tests/ci/test_workflow_contracts.py`,
`docker-bake.hcl`, `justfile`. Two files outside the named set were opened to resolve a specific
question and are cited as such: `docker/Dockerfile` (multi-platform feasibility) and
`scripts/committed_versions.py` (dev-version authority). One network read was made against
`ghcr.io` to resolve the pinned base-image digest (see F13).

### Scoping gaps

- The preamble states CI-AR20/21 were amended and **CI-AR21a added** on 2026-09-01. No `CI-AR21a`
  exists in `ARCHITECTURE-SPINE.md`; the identifier survives only in the superseded
  `_bmad-output/planning-artifacts/plan-2026-09-01-v3.yaml:54`.
- The preamble names a **"Divergences resolved"** section in `docs/ci/codex-assesment.md`
  recording three maintainer decisions. That section is not in the file; the document was
  rewritten by the retirement. Two of the three decisions are still traceable in the v3 plan's
  `readiness_detail`; the third (the accepted tag race) is discussed in F16.

---

## Findings table

| # | Severity | Principle | Location | Finding | Remediation |
|---|----------|-----------|----------|---------|-------------|
| F1 | BLOCKER | GH Actions overlay "Pin actions to a major version"; Core §3 | `E008-S01-001.md:26-27`, `E008-S01-002.md:30-32`, spine CI-AR38 vs `tests/ci/test_workflow_contracts.py:88,186-200` | The mandated `pypa/gh-action-pypi-publish@<full commit SHA>` is **rejected by the shipped tier-one test**, which requires `FLOATING_MAJOR_ALIAS` (`^(release/)?v\d+$`) for every external `uses:`. CI-AR38 also contradicts CI-AR4, which places `pypa` in the approved floating-major class. As written, story 001 cannot go green. | Decide before implementation. Preferred: use `pypa/gh-action-pypi-publish@release/v1` — the guard's own comment already names that branch as pypa's floating major — and amend CI-AR38. If a SHA pin is genuinely wanted, amend the guard to a per-owner exception table and record an ADR; do not weaken the regex globally. |
| F2 | BLOCKER | ADR-0007 invariant 2; spine CI-AR32; Core §4 (a guard must prove its reach) | `tests/ci/test_workflow_contracts.py:56,213-217` vs `E008-S01-001.md:42` | Tier two is asserted on the **callee's text only** (`SECRET_FREE_WORKFLOWS = (ci.yaml, verify-build.yaml)`). `dev.yaml`/`release.yaml` become the first callers that hold secrets, and `secrets: inherit` on their `uses: ./.github/workflows/verify-build.yaml` job would hand the verifier every publisher credential **with no test failing**. The secret-free property is a property of the call graph, not of one file. | Add to E008-S01-001: a guard derived from `WORKFLOWS.glob("*.yaml")` asserting that no job whose `uses:` equals `./.github/workflows/verify-build.yaml` declares a `secrets` key at all. Planted violation: `secrets: inherit` on `dev.yaml`'s verify job. |
| F3 | BLOCKER | Core §1 (host concern leaking into topology); spine CI-AR2/CI-AR28; ADR-0007 tier 1 | `E008-S01-003.md:17-19`, `E009-S01-002.md:19-20` | "Creates the active-forge Release" names **no mechanism**, and none exists within the constraints: the approved owner set `{actions, docker, pypa, LiquidLogicLabs}` contains no release-creating action, and `gh release create` speaks only GitHub's API. E009's entire premise is that this same YAML creates a Release on Gitea (`/api/v1/.../releases`). Discovered during E009 staging, this reopens E008. | Decide now, and record it. Options: (a) a `LiquidLogicLabs/git-action-forge-release@v1` composite that speaks both APIs — approved owner, floating major, one implementation, and the only option that keeps CI-AR2 clean; (b) a forge-conditional step pair (legal — only `ACT` branching is forbidden) with an ADR accepting two code paths and a test asserting both are exercised. Add the chosen mechanism to E008-S01-003's ACs and Files in scope. |
| F4 | MAJOR | Core §3 (contract undeclared); retirement spec "Never … remote identity reconciliation" | `E008-S01-003.md:22-25` | Forward-only alias movement compares the incoming version against a *current* one that the story never sources. For image aliases, the naive reading is "inspect `latest` in each registry" — a per-destination remote-state read that is one refactor away from the retired CI-AR26. | State the authority explicitly: the **Git tag set is the only source of the stable version ordering**; an alias moves iff the tag being released is the greatest annotated `vX.Y.Z` in the repository (and, for `vX.Y`, the greatest within its minor). No registry is read to decide ordering. Add a test anchor: plant a step that reads a registry tag to decide an alias. |
| F5 | MAJOR | ADR-0006 §"Identity versus artifacts" and §5 (force prohibited); Core §3 | `E008-S01-003.md:22-25` vs `E008-S01-002.md:52-53`, ADR-0006:52 | Moving `vMAJOR`/`vMAJOR.MINOR` **requires a forced ref update** (a tag move is a non-fast-forward write, whether by `git push --force`, delete-and-recreate, or `PATCH …/git/refs` with `force:true`). ADR-0006 prohibits force in the release transaction, and E008-S01-002's DoD restates "never force, delete, or overwrite" without scoping it to *immutable* identities. Read literally, the only mechanism that can satisfy CI-AR29 is forbidden. | Amend ADR-0006's identity/artifacts table: alias tags are force-updated by the registered finalizer only, with expected-old-ref (`--force-with-lease`) semantics, never `--tags`, never on `refs/tags/vX.Y.Z`. Add a guard: a forced ref write may appear only in a registered finalizer and only against `refs/tags/v\d+(\.\d+)?$`. |
| F6 | MAJOR | ADR-0006:122-126 (the registry *is* the grant); Core §4 | `E008-S01-003.md:41-50`; `tests/ci/test_workflow_contracts.py:63` | No story says the finalizer must be **registered in `RELEASE_FINALIZER_JOBS` with an ADR**, though ADR-0006 makes that the grant. Worse, the registry is a set of **bare job names matched across every workflow**: registering `finalize` for `release.yaml` silently grants the same name in `dev.yaml`, and E008-S01-003 creates finalizers in both files. | Add to E008-S01-003's DoD: register the finalizer(s) and author the ADR-0006 amendment. Change the registry to `(workflow filename, job name)` pairs before adding the first entry, and add the planted violation: a same-named job in the other workflow. |
| F7 | MAJOR | Core §3 (undeclared precondition); spine CI-AR40 | `E008-S01-003.md:17-19,27-30`, `E008-S01-002.md:51` | "Required failure **or skip** blocks the Release and every alias" collides with GitHub/Gitea `needs:` semantics: a legitimately *disabled* optional destination (Docker Hub off, TestPyPI off) is also `skipped`, and a job that `needs:` it is skipped in turn. The design never states how the finalizer distinguishes "skipped because disabled" from "skipped because a required need failed", nor how the runtime "enabled" set (repository variables) is reconciled with the static `needs:` graph. This is the design hole most likely to be discovered by a silently-not-finalized release. | Decide and write down: the finalizer statically `needs:` **every** publisher, runs under `if: ${{ !cancelled() }}`, and evaluates `needs.<job>.result` against an **enabled-set output emitted once by the guard job** (`enabled-destinations` JSON), failing on any `failure`/`cancelled` and on any `skipped` job that the enabled set says should have run. Add test anchors: a disabled optional destination must still finalize; a required destination that skipped must not. |
| F8 | MAJOR | Core §2 (reuse over copy-paste); GH Actions overlay ("promote a repeated pattern to a composite/reusable workflow") | `E008-S01-001.md:42`, `E008-S01-002.md:41`, `E008-S01-003.md:37-38`, `E009-S01-001.md:36` | `dev.yaml` and `release.yaml` will hold near-identical implementations of: forge fail-closed detection, `FORGE_REGISTRY` validation, bundle download + CI-AR36 revalidation, the one-Buildx image job, and the alias finalizer — then E008-S01-003 edits both, and E009-S01-001 edits both again. Four stories touching two files that ought to share one implementation is how the divergence starts. | Name the shared surface now and give it an owner in E008-S01-001: `.github/actions/forge-coordinates` (detection + validation, fail-closed), `.github/actions/verified-bundle` (download + checksum + manifest + wheel-hash match), and a reusable `publish-image.yaml` taking channel, tags and enabled registries. `release.yaml` then consumes them rather than restating them. |
| F9 | MAJOR | Global rule §1 (never hand-roll URL/path matching); Core §4 (testability) | `E008-S01-001.md:66-67`, `E009-S01-001.md:60`, `E008-S01-002.md:59-64` | The anchors presuppose hand-written patterns living in workflow YAML — "plant an unanchored pattern" only makes sense against an inline regex. Host/port validation that must reject userinfo, path, query and fragment is URL parsing; annotated-tag peeling and reachability is Git plumbing. Neither is unit-testable inside a `run:` block, so the guard degenerates into grepping the workflow for its own regex. | Put both validators in `scripts/` (or `src/publication_contract/`) as Python functions with pytest cases — `urllib.parse` for the coordinate rule, `git rev-parse`/`merge-base --is-ancestor` wrapped for the tag rule — and have the workflow call them. The planted violations then attack real code paths. Add the files to E008-S01-001/002 Files in scope. |
| F10 | MAJOR | Core §4 (the guard must prove its reach) | `E008-S01-001.md:71-72`, `E009-S01-001.md:58-59` | The secret-isolation anchor derives "per-job secret references" from the parsed jobs. A `secrets.*` expression placed in **workflow-level `env:`** (or `defaults:`) is visible to every job and is invisible to that derivation — the exact scope failure the anchor is meant to prevent, in the cheapest possible form. | Derive secret references from job scope **union workflow scope**, and make the planted violation a workflow-level `env: DOCKERHUB_TOKEN: ${{ secrets.… }}` in a workflow whose package job must not see it — not only a job-level one. |
| F11 | MAJOR | Core §4; the stated invariant "upload-artifact stays pinned @v4 for Gitea" | `tests/ci/test_workflow_contracts.py:546-565` | `test_artifact_actions_remain_on_the_both_forge_v4_pair` derives its references from **`VERIFY_WORKFLOW` alone**. `dev.yaml`/`release.yaml` will use `actions/download-artifact`, and tier one happily accepts `@v7` (any `vN` matches `FLOATING_MAJOR_ALIAS`). The Gitea pin can therefore be broken in the new workflows with every test green — and the breakage surfaces only in E009. | Widen that test's scope to `GOVERNED_DEFINITIONS` in E008-S01-001, with the planted violation being `actions/download-artifact@v7` **in `dev.yaml`** (a scope attack, not a rule attack). |
| F12 | MAJOR | Core §4; ADR-0007 invariant 1 | `tests/ci/test_workflow_contracts.py:279-291`; `E008-S01-001.md:40-44` | The single-version-authority guard skips any workflow without a job literally named `plan` (`if "plan" not in jobs: continue`). A `dev.yaml` whose version job is called `identity` or `resolve` is silently ungoverned and free to re-implement version derivation. Compounding it, E008-S01-001's Files in scope omits both surfaces the dev version must come from — `scripts/committed_versions.py` (which already has `development_version(distance)`) and `.github/actions/setup-poetry-python/action.yml`, whose input set is asserted by **exact equality** (`:428`), so adding a `development-distance` input breaks a shipped test. | Re-scope the guard to "any job that emits a `package-version` output" rather than the name `plan`. Add both files, plus the exact-equality assertion, to E008-S01-001's Files in scope, and state in an AC that the dev version comes from `committed_versions.development_version(distance)` and nowhere else. |
| F13 | MAJOR | Core §4; ADR-0008 open question 2; spine CI-AR16/CI-AR39 | `docker/Dockerfile:6,29-32`, `docker-bake.hcl:51,69`; `E008-S01-001.md:30-34` | Multi-platform publication is the epic's central new capability and **its feasibility is unproven and unowned**. The builder stage declares no `--platform=$BUILDPLATFORM`, and it cannot: the venv crossing the stage boundary contains compiled artifacts, so `linux/arm64` must run `apk add gcc cargo` plus a full `poetry install` under QEMU. ADR-0008 records this as undemonstrated. Two sub-risks: the **pinned base digest is fine** — verified against ghcr.io as an OCI index carrying `linux/amd64` and `linux/arm64` — but that index also carries `platform: unknown/unknown` attestation manifests, so a naive "the published index has exactly two platforms" assertion will misread Buildx's own provenance attestations on the published index. | Make the first task of E008-S01-001 a spike: one emulated `linux/amd64,linux/arm64` bake of the current wheel, recording wall-clock time, and a decision on `--provenance` (`docker-bake.hcl:36-39` already exposes `ATTESTATIONS`). Specify that platform inspection **filters `unknown/unknown` descriptors** and asserts the set `{linux/amd64, linux/arm64}` rather than a count. If emulated build time is unworkable, that is an architecture decision (a second native runner, or a cross-built wheel-only image) and belongs in an ADR before the stories proceed. |
| F14 | MAJOR | Core §4 / ADR-0008 ("test what you ship") | `.github/workflows/verify-build.yaml:531-548` vs `E008-S01-001.md:30-34` | The verifier builds a **single-platform, `--load`ed** image and smoke-tests it with `LiquidLogicLabs/git-action-docker-test@v2`. The publisher then builds a *different* image (multi-platform, pushed) which is never started. This is precisely ADR-0008's Option-B objection — "the artifact that was tested and the artifact that ships are two different builds" — reappearing one layer up. Digest/platform *inspection* is not a smoke test. | Either (a) add to E008-S01-001: after push and before any alias moves, pull the published index by digest, resolve the native descriptor, and re-run the container smoke test against it; or (b) record an ADR accepting that image equivalence is delegated to wheel-hash provenance plus platform inspection, and say so in the runbook. Do not leave it unstated. |
| F15 | MAJOR | Core §4; ADR-0007 invariant 3 | `tests/ci/test_workflow_contracts.py:314-345`; `E008-S01-004.md:55-56` | `test_any_push_triggered_workflow_verifies_before_it_ships` recognises a publisher **only** as a job whose `uses:` is another local workflow. E008's publishers are ordinary step-based jobs, so the test passes **vacuously** over `dev.yaml`. The replacement ("every credential-bearing job sits in the verifier's transitive `needs`") is deferred to story 004 — three stories after the first publisher lands. | Move the credential-bearing-job ordering guard into **E008-S01-001**, deriving "credential-bearing" from any job referencing `secrets.*` or declaring `packages: write`/`id-token: write`, and plant a publisher outside the verifier's transitive `needs`. Story 004 then only widens it to the whole topology. |
| F16 | MAJOR | Core §6 / §10 (a decision that lost its record); spine "Trigger and Coordinate Guards" | `E008-S01-001.md:17-19` | `just release` pushes branch and tag **atomically**, which fires a `push` event on `main` *and* a tag event. Dev suppression depends on `dev.yaml` observing the exact stable tag on the source commit — an ordering the forge does not guarantee. If the tag is not yet visible to the dev run, an immutable, unretractable `X.Y.(Z+1).dev0` package is published for the release commit. The superseded plan recorded this as knowingly accepted ("the immutable half of the tag race is accepted because tagging drives the release"); the rewrite dropped the record, so the next reader meets it as a bug. | Re-record the acceptance in the spine or an ADR, and harden it cheaply: re-run `git fetch --tags && git describe --exact-match` **immediately before the first dev credentialed step**, not only in the guard job. Add the anchor: plant a tag arriving between the guard and the upload. |
| F17 | MAJOR | Retirement spec "Never … remote identity reconciliation"; Core §3 | `E008-S01-004.md:26-30` | "…or a remote immutable identity conflicts, when recovery is evaluated, then the run halts and escalates" does not say **who detects the conflict**. An implementer reading it as "check whether this version already exists before uploading" reintroduces retired CI-AR26 under a new name — which the spec forbids explicitly. | State that detection is the destination action's own failure (pypa's action rejects a duplicate; a registry rejects an immutable tag) and that the halt is operator-mediated via the runbook. Add a guard forbidding a pre-upload remote-existence query in a publisher job (`pip index versions`, `curl …/pypi/…/json`, `docker manifest inspect` before the push step). |
| F18 | MAJOR | Core §4; spine CI-AR2/CI-AR5 | `E009-S01-001.md:45-48` | The Gitea smoke list omits the capability the **entire topology** rests on: nested reusable workflows (`uses: ./.github/workflows/verify-build.yaml` at job level, i.e. `workflow_call`), and downloading in a *caller* job an artifact uploaded inside the *called* workflow. Everything else in the list is secondary to those two. | Add both to the E009-S01-001 smoke set and to the pinned-tuple record, and make them the first cases run — if the pinned act-runner cannot do them, E008's topology is not portable and that must be known before E009-S01-002 begins. |
| F19 | MAJOR | ADR-0007 invariant 2 (verifier holds no `secrets:`); Core §1 | `E009-S01-001.md:17-23,41-48`; `tests/ci/test_workflow_contracts.py:213-217` | The verifier pair is **structurally unable** to receive a job-level CA bundle: `secrets:` is a literal prohibition in its text. So on a private-CA Gitea, *every* endpoint the verifier touches — forge clone, action download, PyPI (`poetry install`), and the ghcr.io base image — must be covered by runner-host bootstrap trust. The story separates bootstrap from job trust correctly but never states this consequence, and it is the constraint that decides how the runner image is built. | Add to E009-S01-001's DoD: enumerate every endpoint the verifier contacts and assert each is covered by bootstrap trust; record it as part of the pinned tuple. Add a negative case: a runner whose bootstrap trust covers the forge but not the package index must fail at the verifier, not mid-publication. |
| F20 | MAJOR | Global rule §3 (a rule with no mechanical check); Core §4 | `E009-S01-002.md:36-39` vs `:52-62` | The story declares mechanical test anchors — "the gate derives its required cases from the declared negative-case set and demands a run URL and conclusion for each; plant a removed case" — but its **Files in scope contains only two markdown documents**. There is no home for the gate, so the anchors are prose describing a check that nothing will implement. | Either add `tests/ci/` (a test that parses the declared case table out of `docs/ci/gitea-certification.md` and asserts each row carries a run URL and conclusion), or delete the mechanical language and say plainly that the gate is a human review — per global rule §3, prose that overstates its own coverage is worse than none. |
| F21 | MINOR | Core §10 (traceability) | preamble vs `ARCHITECTURE-SPINE.md:105-113`, `docs/ci/codex-assesment.md` | `CI-AR21a` does not exist in the spine (only in the superseded `plan-2026-09-01-v3.yaml:54`), and the "Divergences resolved" section naming three maintainer decisions is absent from the assessment. The stories cite only live keys, so nothing is broken — but the provenance of three decisions is now unrecoverable from the active artifacts. | Either add `CI-AR21a` to the spine or correct the dispatch preamble; restore a short "Decisions of record" section to `codex-assesment.md` carrying the three decisions (owning forge never optional; the contract decides aliases and vendor actions execute them; the accepted tag race — see F16). |
| F22 | MINOR | GH Actions overlay (concurrency); Core §3 | `E008-S01-002.md` (absent) | `dev.yaml` concurrency is owned (`E008-S01-001.md:48-49`); `release.yaml` concurrency is owned by nobody. A duplicate or replayed tag event could start a second publishing run against immutable destinations. | Specify `concurrency: {group: release-<tag>, cancel-in-progress: false}` — grouped so it serialises, never cancelling a run that may hold a half-finished fan-out. |
| F23 | MINOR | Core §1 (one owner per artifact) | `E008-S01-004.md:34`, `E009-S01-002.md:39` | `docs/operational.md` is in scope for two stories in two epics. Sequencing saves it, but neither story says which sections it owns. | Name the sections: E008-S01-004 owns "Publication recovery"; E009-S01-002 owns "Gitea migration and rollback". |
| F24 | MINOR | Core §10 (diagram-first where it helps) | `E008-S01-004.md:31-35` | The publication job graph — four workflows, a fan-in verifier, independent destinations, aliases-last, and the failed-jobs-only rerun path — is exactly the non-trivial flow §10 asks for a diagram of, and none of the six stories produces one. The spine's ASCII sketch predates the job-level design. | Add one Mermaid flow (or sequence) diagram of the publication graph to `docs/operational.md` in E008-S01-004. |
| F25 | MINOR | Core §6 (comments describe the current state) | `.github/workflows/ci.yaml:48`; `scripts/committed_versions.py:93`; `docker/Dockerfile:106` | Three stale statements the epic walks past: `ci.yaml` credits a shared authority with the deleted `build.yaml`; `committed_versions.py` names **release-please** as a version owner, a mechanism ADR-0006 deleted and a contract test forbids; and the runtime stage bakes `DOCKER_PLATFORMS="linux/amd64,linux/arm64"` into the shipped image's environment, a build-time concern leaking into runtime config. | Fix all three in E008-S01-001 (the first story to touch that neighbourhood). The Dockerfile `ENV` should simply be deleted — the platform set is a bake input, not runtime state. |
| F26 | MINOR | Core §10 (docs contradicting the code) | spine CI-AR7 vs `justfile:4,21,44,51` | CI-AR7 says the justfile exposes `setup`, `package`, `verify`; it exposes `install`, `build`, `check`, `fix`, `release-dry-run`, `release-resume`. No E008/E009 story cites CI-AR7, so nothing is blocked — but a story that did would be wrong on arrival. | Correct CI-AR7 to the shipped recipe names. |
| F27 | MINOR | GH Actions overlay (least privilege); Core §7 | spine CI-AR39/CI-AR40; `E008-S01-001.md:30-34` | "Build once" is implemented as "one job holds every enabled registry credential", so a compromise of the image job yields both the forge registry and Docker Hub. The alternative was not weighed: push the single multi-platform build to the forge registry only, then copy by digest to Docker Hub (`docker buildx imagetools create`) in a job holding **only** the Docker Hub credential. That preserves build-once *and* isolates. | Record an ADR weighing the two; if the current shape stands, state the accepted blast radius in it. |
| F28 | MINOR | Core §3 (the only *required* channel has no contract) | spine CI-AR21; `E008-S01-001.md:26-28`, `E008-S01-002.md:30-32` | The Gitea forge Python index is the only **always-required** package destination, and it is the one with no dedicated AC: no URL derivation rule (`{server}/api/packages/{owner}/pypi`), no statement that it is skipped on GitHub by host capability rather than by toggle. Both stories describe package publication in terms of the optional external channels. | Give the forge index its own AC in both stories, including how the URL is derived from action context (CI-AR6) and how "absent by host capability" differs from "disabled by toggle" at the finalizer (see F7). |
| F29 | MINOR | Core §3 / §5 | `E008-S01-001.md:21-23`, `E008-S01-002.md:26-28`; `.github/actions/publication-contract/action.yml:82-110` | CI-AR36 revalidation is stated as an outcome with no mechanism. The only implementation is the local `publication-contract` composite action, which runs `poetry run python -m publication_contract` — so *every* credential-bearing job must first check out the repo and install Poetry. That is a real shape decision (a three-step job becomes a ten-step job) and it is invisible in the stories. | Name the mechanism in the ACs. If the cost is unwanted, specify a lighter path — `sha256sum -c SHA256SUMS` plus a JSON field comparison — and say which jobs use which. |
| F30 | MINOR | Core §9 (correlation across boundaries) | spine CI-AR15/CI-AR41; `E008-S01-004.md:40-42` | By design the manifest carries no run identity, so a published digest cannot be traced back to its run from the artifact alone; the join key is `org.opencontainers.image.revision` (the source SHA) plus the run summary. Deliberate, but undocumented for the operator who has only a digest. | Document the digest → revision → run lookup in the runbook section E008-S01-004 owns. |

---

## Per-principle walkthrough

**Core §1 — Separation of concerns.** Adapter/verifier/publisher separation is sound and is the
design's strongest property. Two leaks: the forge-specific Release mechanism has nowhere to live
(F3), and build-time platform data sits in the runtime image env (F25). Also F23.

**Core §2 — Reuse over copy-paste.** The one systemic weakness. Two publisher workflows will
carry five duplicated concerns each, then be edited in lockstep by two later stories — F8. The
positive counterweight: version derivation, evidence validation and Poetry setup already have
single owners and the stories inherit them (subject to F12).

**Core §3 — Design by contract.** Boundary revalidation (CI-AR36) is a genuine
precondition asserted at every publisher edge — good. Undeclared contracts: the
enabled/required/skipped relation (F7), the alias ordering authority (F4), the conflict-detector
(F17), the revalidation mechanism (F29), the forge index (F28).

**Core §4 — Testability.** The anchors are unusually good — most already attack scope, not just
rule. Where they fall short they fall short in the same way: the scope is derived from the files
that exist today rather than from the rule (F2, F11, F12, F15), or the thing under test is
inline shell that cannot be unit-tested (F9). F10 is the anchor that would pass over the cheapest
real violation. F13/F14 are capabilities asserted by inspection rather than by exercise.

**Core §5 — Brevity without sacrificing readability.** PASS. The rewrite from 267–370 lines to
43–77 is a clear improvement; every finding above concerns a *decision* that is missing, not a
paragraph. Two ACs read tersely enough to be misread rather than under-specified — F7's
"failure or skip" and F17's "conflicts" — and both are called out as decisions, not prose.

**Core §6 — Comments describe current state.** F25 (three stale statements), F16 (an accepted
risk whose record was deleted in the rewrite).

**Core §7 — Dependency selection.** PASS with one note. Every action named is from a maintained
approved owner. F27 records an unweighed credential-footprint trade-off rather than a bad
dependency.

**Core §8 — GA over alpha/beta.** PASS. No preview action, service or language feature is
load-bearing. `actions/upload-artifact@v4` is a deliberate, ADR-grade *older*-than-latest pin
with a Dependabot ignore protecting it — the risk there is scope (F11), not currency.

**Core §9 — Unified correlated logging.** Partial. CI-AR41's run-native evidence is the right
call for a pipeline and needs no schema. The gap is the reverse join from a published artifact
back to its run (F30). No secret-in-log risk was found; E009-S01-001's "no leaked values" anchor
covers it explicitly and well.

**Core §10 — Documentation.** The ADR set is unusually strong and the stories build on it
honestly. Gaps: no flow diagram for the new job graph (F24), a spine requirement contradicting
the shipped justfile (F26), and lost decision provenance (F21).

**GH Actions overlay — marketplace over custom scripting.** Mostly honoured; F9 is where custom
shell is being chosen for something a library does properly.

**GH Actions overlay — pinning.** F1 is a direct contradiction between the mandated pin form and
the shipped policy test. F11 is the pin whose guard cannot see the new files.

**GH Actions overlay — hygiene (least privilege, secrets, concurrency, reuse).** F2, F5, F6, F7,
F10, F22, F27. Least-privilege *intent* is right throughout; the enforcement scope is what slips.

**Python overlay.** PASS. Poetry is the single manager, the lock is committed, CI installs from
it, `requires-python` is bounded, the interpreter and Poetry pins each have one authority, and
the wheel/sdist smoke tests install into clean environments. Nothing in E008/E009 disturbs this.

**Docker overlay (stub — provisional).** Multi-stage, digest-pinned base, non-root s6 model, no
secrets in layers, no `pip` in the runtime. F13 (multi-arch feasibility), F14 (the shipped image
is not the tested image) and F25 (stray runtime `ENV`) are the open items.

**Shell overlay (stub — provisional).** Workflow shell uses `set -euo pipefail` and quoted
expansions consistently. F9 is the case where a script has outgrown shell.

---

## Answers to the gate questions

**Does the four-story split hold together?** Mostly. Nothing falls *between* the stories at the
level of destinations — dev, stable, aliases and cutover partition cleanly, and E008-S01-003's
sole ownership of aliases is stated and testable. What falls between are three cross-cutting
obligations no story claims: the shared publisher implementation (F8), the finalizer's grant and
ADR (F6), and widening three existing guards whose scope the new files escape (F2, F11, F15).
`docs/operational.md` and `tests/ci/test_workflow_contracts.py` are owned by several stories;
only the former needs section-level ownership (F23).

**Are the dependency edges right and acyclic?** Yes — `001 → 002 → 003 → 004 → E009-001 →
E009-002` is a chain, trivially acyclic, and matches the spine's implementation sequence. Two
notes: `002`'s dependency on `001` is a *sharing* edge, not a functional one (release.yaml needs
nothing dev.yaml produces), which is exactly why the shared surface should be extracted in `001`
(F8); and three guards are sequenced after the code they should govern (F15).

**Does anything require a retired capability?** No — and this was checked story by story. No
publication plan, no release receipt, no aggregate preflight, no reconciliation. `needs:`-based
aggregate gating (CI-AR40) and per-publisher boundary revalidation (CI-AR36) are ordinary
workflow mechanics, not the retired transaction. Two ACs are *ambiguous enough to be
re-implemented as* a retired capability if left as written: F17 (who detects an immutable
conflict) and F4 (where alias ordering reads current state). Both are cheap to close now.

**Do the credential boundaries actually isolate?** Package vs image: yes, stated and anchored.
Verifier vs publisher: **no — the callee is protected, the call site is not** (F2). Forge vs
external: deliberately not, for images — one job holds both registries' credentials by
construction of CI-AR39, and the isolating alternative was never weighed (F27). Enabled vs
disabled: the "disabled destinations receive no credential and make no request" rule is stated
in three places, but the guard that would prove it can be evaded by a workflow-level `env:`
(F10).

**Is "build once, publish many" genuinely achievable as specified?** For packages, yes — one
wheel and sdist flow from the verifier to every destination. For images, "build once" is already
false today and stays false: the verifier builds a single-platform image to smoke-test, the
publisher builds a second, multi-platform image to ship (F14). Provenance is preserved (both
contain the same hash-verified wheel), but the tested image and the shipped image are different
builds — ADR-0008's own objection to Option B. And the multi-platform build itself is unproven
(F13): the base image is genuinely multi-arch, but the builder stage must run under emulation
because its output venv is architecture-specific. No story forces a *rebuild per registry* —
that invariant is intact and well anchored in both 001 and 002.

**Are the planted violations the right ones?** Better than typical: six anchors explicitly
attack scope ("plant a new publisher nothing depends on", "plant a fifth workflow file, and a
rename", "plant a removed case"). Three do not, and they are the ones that matter most —
secret isolation misses workflow-level `env:` (F10), the artifact pin is never attacked in a new
workflow (F11), and the verifier-secret boundary is never attacked from the caller (F2). One
anchor set describes a mechanical gate with no file to implement it (F20).

**Is E009 coherent given the repository is on github.com today?** Yes as a *certification*
epic — proving the pinned tuple on staging before moving ownership is the right shape, and
gating migration on a demonstrated failed-jobs-only rerun is the correct hard stop. Its
coherence depends on three things it does not currently assert: that Gitea's act-runner supports
nested reusable workflows and cross-workflow artifacts (F18), that a Release can be created on
Gitea at all (F3 — this is E009's exposure to an E008 decision), and that runner-host bootstrap
trust covers every endpoint the secret-free verifier touches (F19). Until F3 is decided, E009's
certification checklist contains a row that no implementation can satisfy.

---

## Gate

- **BLOCKER (3):** F1, F2, F3 — must be resolved before E008-S01-001 begins. F1 and F3 are
  decisions, not work; F2 is roughly twenty lines of test.
- **MAJOR (17):** F4–F20 — must be resolved or ADR-justified before the owning story starts.
  Story assignment: F4–F7 → E008-S01-003 (decide before 001, since F7 shapes every job's `if:`);
  F8–F16 → E008-S01-001 (F13 as a spike first); F17 → E008-S01-004; F18–F20 → E009.
- **MINOR (10):** F21–F30 — defer to backlog, except F22 and F28, which are one line each in a
  story that has not been written yet and are cheapest to fold in now.

## Recommended ADRs

1. **Forge Release and alias mechanism across GitHub and Gitea** (F3, F5) — the host-neutral
   mechanism, plus the amendment to ADR-0006's identity/artifacts table authorising forced
   alias-tag updates by a registered finalizer, with expected-old-ref semantics.
2. **Amend ADR-0006 to register the Epic 8 finalizers** (F6) — the grant itself, and the change
   of `RELEASE_FINALIZER_JOBS` from bare names to (workflow, job) pairs.
3. **Action pin policy for `pypa/gh-action-pypi-publish`** (F1) — floating `release/v1` versus a
   reviewed SHA, and whichever is chosen, the corresponding correction to CI-AR38/CI-AR4.
4. **Multi-platform image build strategy** (F13, F14) — emulated build cost, provenance
   attestation handling in platform inspection, and whether the published digest is smoke-tested
   before aliases move.
5. **Image registry credential topology** (F27) — one job with all registry credentials versus
   push-to-forge then copy-by-digest with isolated credentials.
6. **Destination enablement and finalizer evaluation** (F7) — how the enabled set is derived and
   how `skipped` is disambiguated; small, but it is load-bearing for every publisher `if:`.

DONE — Blocker: 3, Major: 17, Minor: 10
