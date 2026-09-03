# E009 — Practical Gitea Certification: pre-execution architecture gate

- **Mode:** B (architectural review of an existing design)
- **Date:** 2026-09-03
- **Standards applied:** `references/standards-core.md` §1–10, `references/standards-github-actions.md`,
  `references/standards-python.md`, plus the user's global engineering rules §1–4.
- **Scope:** the bounded input set named by the orchestrator — `E009-S01-001.md`, `E009-S01-002.md`,
  `ARCHITECTURE-SPINE.md`, ADR-0006/0007/0010/0011/0012, `.github/workflows/`, `docs/project-context.md`,
  `docs/operational.md`. The repository was not read at large.
- **State reviewed:** working tree at the time of the gate. `docs/adr/0011-*.md`, `.github/workflows/dev.yaml`
  and `.github/workflows/release.yaml` were modified-uncommitted; findings that turn on that are marked.

## Executive summary

E009's two stories describe the right *shape* of work — pin a tuple, bootstrap trust outside the job,
isolate credentials, then certify against staging and gate migration on the result. What they do not
carry is the epic's actual risk. **Four recorded unknowns decide whether the epic is possible at all,
and none of them is a story, a spike, or an acceptance criterion — three appear only as prose inside
story 001 and the fourth (`TokenPermissionMode`) appears in neither story at all**, despite ADR-0006
assigning it to E009 by name. Story 001's Definition of Done also drops precisely the two capabilities
its own F18 text says "must be in the pinned tuple and **run first**", while keeping every item F18 calls
secondary. Story 002's certification gate — the mechanism that decides whether migration proceeds —
derives its required case set from the same document it audits, which is this project's signature defect
(`docs/project-context.md` §3) reproduced on the epic's own gate.

Counts: **4 BLOCKER, 14 MAJOR, 4 MINOR.** The single most important action is to convert the four
unknowns into structure — a spike or a first-run gate ahead of story 002 — with a named response for each
"no", because the current two-story sequence has no branch for any of them and story 002's estimate
assumes all four are "yes".

A note on the shape of these findings: for a pre-execution gate, most of what follows is *"the story is
silent on X"*, not *"the story is wrong about X"*. Where the design is actually contradicted by shipped
code or by an ADR, that is stated as such and the contradiction is quoted.

---

## Findings table

| # | Severity | Principle | Location | Finding | Remediation |
|---|----------|-----------|----------|---------|-------------|
| B1 | BLOCKER | Global §3 (enforce mechanically); Core §3 (contracts); Core §10 | `E009-S01-001.md` (whole file), `E009-S01-002.md` (whole file) vs `docs/adr/0006-release-version-transaction.md:328-338` | ADR-0006 assigns `TokenPermissionMode = restricted` to E009 explicitly — *"E009 therefore owns a deployment precondition rather than a YAML change"* and *"Staging must prove it by granting nothing and confirming a write is refused, not by reading the setting back"* — and neither story contains the words `TokenPermissionMode`, `permissions`, `restricted`, or any deny-by-default proof. Grep confirms the term exists only in ADR-0006, a guard docstring, and E008 closure reports. Until certified, ADR-0006 concedes the finalizer authority split is *"stated on Gitea and enforced only on GitHub"*. | Add an acceptance criterion to story 001 (deployment precondition recorded, minimum Gitea version pinned) and a negative case to story 002's set: grant nothing, attempt a write from a job declaring `contents: read`, assert refusal. Read-back of the setting must be explicitly disallowed as evidence. |
| B2 | BLOCKER | Global §4 (a guard's reach); Core §4 (testability) | `E009-S01-001.md:39-44` vs `:76-77` | Story 001's own F18 text says nested reusable workflows and caller-downloads-callee-artifact *"must be in the pinned tuple and **run first** — if the pinned `act_runner` cannot do them, E008's topology is not portable"*, and *"Everything else in the list is secondary."* The DoD smoke list is then `checkout/action resolution, artifacts, Poetry, QEMU/Buildx, downstream CA, cleanup, wrong-CA failure, and missing-scope failure` — nested `workflow_call` is absent entirely, and bare "artifacts" does not distinguish the cross-workflow round-trip from an in-job upload/download. The DoD keeps every secondary item and drops both gating ones. | Promote both to acceptance criteria with an explicit ordering constraint (they run before any other smoke case), and name the two live edges: `ci.yaml:76`/`dev.yaml:232`/`release.yaml:387` → `verify-build.yaml`, and `dev.yaml:550`/`release.yaml:737` → `publish-image.yaml`. State the response if either fails. |
| B3 | BLOCKER | Global §4 ("derive the scope from the source of truth; never enumerate it by hand"); `docs/project-context.md` §3 | `E009-S01-002.md:36-47`, `:70-72` | The certification gate is specified as *"a test parses the declared case table out of `docs/ci/gitea-certification.md` and asserts every row carries a run URL and a conclusion, with the planted violation being a removed row."* The required set and the audited set are then the same hand-written document: deleting a row shortens both, and the gate passes over the shorter set — the exact outcome the story says must not happen (*"must fail the gate rather than pass over a shorter set (scope attack)"*). No second authority for the required set is named. | Give the required case set a source of truth independent of the evidence document — e.g. derive it from the negative-case constants already in `tests/ci/test_workflow_contracts.py`, or from the workflow/ADR set the cases are drawn from — and have the gate compare the document against it. If no independent authority is available, delete the mechanical language and describe the gate as a human review (the story's own fallback at `:45-47`). |
| B4 | BLOCKER | Core §1 (separation); CI-AR2, CI-AR34 | `E009-S01-001.md:30-32` vs `.github/workflows/*.yaml` (every `runs-on: ubuntu-24.04`), `tests/ci/test_workflow_contracts.py:1120`, `:141` | AC4 requires untrusted verification and protected publication to *"use separate pinned runner pools"*. Every job in all five workflows is `runs-on: ubuntu-24.04`; `test_fork_verification_has_no_publisher_capability_or_persistent_runner` pins that literal for every `verify-build.yaml` job; `runs-on: self-hosted` is a forbidden literal in the fork-facing set. Gitea routes work by runner label, so two pools require a label distinction — which one file cannot spell for both forges without violating CI-AR2 ("no step branches on host"). This is structurally the same problem ADR-0006 recorded for Gitea's `code:`/`releases:` scopes: *"A single file cannot spell both vocabularies."* Neither story names it. | Decide and record the mechanism before story 001 starts: register both Gitea pools under the `ubuntu-24.04` label and separate them by repository/organisation runner registration rather than by label (if Gitea permits), or accept a label divergence and record the CI-AR2 exception in an ADR. Do not leave AC4 as an assertion with no expressible mechanism. |
| M1 | MAJOR | Core §8 (GA/recorded need); Global §2 (test a constraint) | `E009-S01-001.md:54-57`; `docs/adr/0010:49-51`; `docs/adr/0012:39-41` | node24 acceptance by the pinned `act_runner` appears only as prose in a "Also for the pinned tuple" paragraph — no AC, no DoD line, no test anchor. Three adopted actions (`git-action-release@v2`, `git-action-tag-floating-version@v2`, `git-action-docker-metadata@v6`) plus `actions/checkout@v7` and `actions/setup-python@v7` are all `using: node24`, so a "no" invalidates the entire pipeline, not one step. ADR-0010 records the accepting runner version as *"unconfirmed"*. | Make node24 acceptance an acceptance criterion of story 001, measured first, with the pinned `act_runner` version recorded as the answer. Name the response to "no" (older action majors are node20 for one of the three only, so there is no uniform downgrade). |
| M2 | MAJOR | Core §7/§8 (dependency risk with an exit plan) | `E009-S01-001.md:59-61`; `docs/adr/0010:44-48`, `:81-84` | Whether `git-platform-detector` makes a network probe is prose-only in story 001 and *"E009 staging must prove it empirically"* in ADR-0010. No AC, no DoD, no anchor. ADR-0010 names a fallback — substitute `softprops/action-gh-release` at a reviewed SHA — whose cost (an `APPROVED_ACTION_OWNERS` amendment, a `SHA_PINNED_ACTIONS` entry, and re-certification of the Release path) is in neither story's Files in scope and in neither estimate. | Add the probe determination as an AC of story 001 and the fallback as a named, estimated branch of story 002. The allowlist amendment is a policy change and needs its own ADR if taken. |
| M3 | MAJOR | Core §3 (contracts, failure modes); Global §2 | both stories (absent) vs `.github/workflows/dev.yaml:611-624`, `:635`; `release.yaml:157` | Whether Gitea populates `github.event.repository.default_branch` is unmentioned in either story. Both channels now fail closed on it: `dev.yaml` refuses with `exit 2` before the just-in-time checkout, and `release.yaml` composes `origin/${{ ... }}` into `DEFAULT_BRANCH_REF`. Failing closed is correct, but a "no" halts *every* dev run and *every* stable run on Gitea, and this appears in none of story 002's negative cases, no runbook entry, and no fallback derivation. | Add it to story 002's declared negative-case set with an explicit expected outcome, and record in story 001 what the fallback derivation is if the field is empty (e.g. a runner-provided value, or an operator-recorded default-branch name) — or state that no fallback exists and the tuple is rejected. |
| M4 | MAJOR | Core §4 (testability); `docs/project-context.md` §7 (echo guards) | `E009-S01-002.md:22-25` vs `:73-74` | AC2 asserts the tuple *"reruns failed jobs only and does not repeat successful immutable package uploads."* Its declared anchor is *"plant a repeat of an already-successful package upload, which the immutable index must reject and the report must record."* Those are different propositions: the anchor proves the *index* is immutable, which is true on every tuple — including one whose rerun re-executes every job. A tuple that fails the AC passes the anchor. This is the code-and-guard-wrong-in-the-same-direction pattern project-context §7 records twice. | Restate the anchor as an observation of the rerun itself: after a per-job rerun, the previously successful publisher jobs carry their original conclusion, start time and outputs, and no second upload request was made. The index's rejection is a safety net, not the evidence. |
| M5 | MAJOR | Core §3; CI-AR38 | `E009-S01-002.md:22-25` vs `docs/operational.md:322-333` | The runbook's recovery procedure depends on three properties, and AC2 names only one. `operational.md` states the rerun *"reuses the outputs of the jobs that already succeeded — including the plan job's identity and the verifier's `build-manifest-sha256`"* and that *"the verified distribution artifact uploaded by the original attempt is still the artifact the rerun downloads."* Whether a Gitea per-job rerun repopulates `needs.<job>.outputs` and preserves artifact scope is the load-bearing unknown; AC2 tests only "does not repeat". A rerun that runs only the failed job but supplies empty `needs` outputs satisfies AC2 and breaks recovery. | Extend AC2 to assert output propagation and artifact availability across the rerun, and add both as declared negative cases. |
| M6 | MAJOR | Global §4 (scope from a hand-written list); Core §1 | `E009-S01-001.md:46-52` vs `.github/workflows/verify-build.yaml:610`, `docker/Dockerfile:8,23,125`, `.github/workflows/publish-image.yaml:358` | F19 instructs *"Enumerate every endpoint and assert each is covered"* and then supplies the list — *"forge clone, action download, PyPI for `poetry install`, and ghcr.io for the base image"* — which a reader will take as the set. The verifier also reaches `dl-cdn.alpinelinux.org` (`apk add` in both Dockerfile stages, executed by the native image smoke build) and `docker.io` (`docker/setup-buildx-action@v4` pulls `moby/buildkit`; `docker/setup-qemu-action@v3` pulls `tonistiigi/binfmt`). Those two are the ones an egress-restricted private-CA deployment is most likely to block, and they are missing. | Derive the endpoint set from the workflows, composite actions and `docker/Dockerfile` mechanically rather than restating it in prose, and make the derivation the gate's scope. At minimum, add the Alpine CDN and Docker Hub legs to the enumeration. |
| M7 | MAJOR | CI-AR6; Core §1; Global §2 | `E009-S01-001.md:25-28`, `:71` | AC3 requires *"every coordinate is derived from `github.server_url` and `github.repository` alone"*, but the action-resolution endpoint is not such a coordinate: on Gitea, `uses: actions/checkout@v7` resolves from `act_runner`'s configured actions URL (github.com by default, or a mirror), which is a runner setting. The DoD records *"the supported Gitea server, act-runner, runner image, and action tuple"* — the tuple, not the source. That choice decides both the F19 trust set and whether `@v7`/`@v4` exist at all on a mirror. | Add the action-resolution source to the pinned tuple as a first-class element, with the trust obligation it implies, and state whether a mirror is in use. |
| M8 | MAJOR | Global §4; Core §4 | `E009-S01-001.md:39-44` (F18 list) vs `.github/actions/*/action.yml`, `publish-image.yaml:141`, `verify-build.yaml:99…679` | Local composite actions (`uses: ./.github/actions/...`) appear 20+ times, including *inside both reusable workflows*, and `.github/actions/verified-bundle/action.yml:82` is where `actions/download-artifact@v4` actually runs — so the F18 artifact round-trip is really "reusable workflow uploads → a local composite action invoked from a caller job (and from a sibling reusable workflow) downloads". `act_runner` support for local composite actions is a third structural capability that F18 does not name and story 001's DoD does not smoke. | Add local composite action resolution to the must-run-first set alongside B2's two capabilities. |
| M9 | MAJOR | Core §10 (docs contradict code); Core §3 | `ARCHITECTURE-SPINE.md` "Protected credentials" table (TestPyPI/PyPI → Gitea: *scoped token*) vs `release.yaml:243-253`, `dev.yaml:194-201`, `release.yaml:696-700` | The spine promises a Gitea scoped-token path for PyPI/TestPyPI. The shipped implementation does the opposite and does it deliberately: both channels set the destination to `unsupported` when `FORGE != github` (*"PyPI is reached by trusted publishing, which needs a GitHub OIDC identity. On a Gitea runner there is none"*), and the upload steps carry no `password:` input at all. Story 001's DoD (*"package jobs receive only their own credentials"*) and story 002's AC1 (*"required package channels"*) are written against the stale table. On Gitea the only package channel is the forge index. | Correct the spine's credential table to record PyPI/TestPyPI as absent-by-host-capability on Gitea, and restate story 002's package-channel case as the forge index only. |
| M10 | MAJOR | Core §10; CI-AR5 | `ARCHITECTURE-SPINE.md` CI-AR5 vs `.github/workflows/` (five files) | CI-AR5 states *"The pipeline consists of `ci.yaml`, `dev.yaml`, `release.yaml`, and reusable `verify-build.yaml`"*. `publish-image.yaml` (520 lines) also shipped and is the file that holds every registry credential, both `docker/login-action@v3` steps, the QEMU/Buildx multi-platform build, and one of the two nested `workflow_call` edges E009 must certify. A reader working from the spine would not know to certify it. | Amend CI-AR5 to the five-file partition the topology guard already enforces, and name `publish-image.yaml` in story 002's certification set. |
| M11 | MAJOR | Core §6/§10 (stale documentation is a defect) | `docs/adr/0011-*.md:164-168` vs `.github/workflows/*.yaml` (no job-level `concurrency`), `tests/ci/test_workflow_contracts.py:4681` | ADR-0011 still asserts *"`finalize` and `finalize-image-aliases` carry a job-level `concurrency: { group: <workflow>-aliases, cancel-in-progress: false }` … so every stable run queues behind every other for the alias stage"*. No workflow contains any job-level concurrency; the only groups are workflow-level in `ci.yaml:11`, `dev.yaml:23`, `release.yaml:41`. The guard's own docstring says *"The groups are gone."* Story 002 AC3 and its "stale dev" / "forward-only stable" cases are designed against a serialisation mechanism that does not exist. (Observed in the working tree; ADR-0011 is modified-uncommitted.) | Amend ADR-0011 to record the removal and the reason (GitHub cancels rather than queues the pending group member), then re-derive story 002's AC3 from what actually enforces ordering: re-derivation in the writing job. |
| M12 | MAJOR | Core §3; ADR-0006 | `tests/ci/test_workflow_contracts.py:4770` (`AUTHORITY_SCOPES`) vs `docs/adr/0006:322-326` | The explicit-`none` mitigation covers four scopes — `contents`, `packages`, `id-token`, `attestations` — of GitHub's ~15. Under a permissive Gitea, omission grants, so every unlisted scope (`actions`, `checks`, `deployments`, `issues`, `pull-requests`, `statuses`, `security-events`, …) is still granted on every credential-bearing job. Gitea's own vocabulary (`code:`, `releases:`) does not map one-to-one either. Neither story bounds the residual, and B1's certification would only cover the four. | State the four-scope subset as a deliberate limit with its reasoning, or widen `AUTHORITY_SCOPES`; either way, make the residual an explicit item of the E009 certification report. |
| M13 | MAJOR | Core §4 (test strategy and confidence); `docs/project-context.md` §2, §8 | `state/planned/epic-009/epic.yaml`, `sprint-01/sprint.yaml` | Epic estimate is 28.81–29.90 man-hours with **0.17–0.18 HITL hours** for an epic whose deliverable is a physical deployment: provisioning a private-CA Gitea, registering two runner pools, installing host trust before registration, minting scoped credentials, and exercising a per-job rerun through a forge UI. All of those are human actions. Project-context §8 records that six CI runs on an already-reviewed pipeline found five defects unreachable by static analysis and that *"the first runs of a new channel should be expected to cost a few cycles"* — E009 is the first runs on a new *forge*, with none budgeted; §2 records E008 at 210 actual against 74.6–77.4 estimated. Separately, `closure_ratios.man_hours` is 0.2587 at epic level and 1.8449 at sprint level — a 7× inconsistency between two files describing the same work. | Re-estimate with a realistic HITL figure and an explicit allowance for first-forge execution cycles; reconcile the two closure ratios. |
| M14 | MAJOR | Core §8; CI-AR2 | `release.yaml:627` (`environment: pypi`) | Whether Gitea Actions accepts the job-level `environment:` key — and whether an unsupported key is ignored or is a parse error — is **unverified** and named in neither story. If it is fatal, `release.yaml` fails to parse on Gitea and the entire stable channel is unavailable, regardless of the fact that `publish-package-pypi` is `unsupported` there and would never run. | Add `environment:` acceptance to story 001's smoke set (a parse-level check on the pinned tuple), and record the outcome in the tuple. |
| m1 | MINOR | CI-AR41; Core §9 | `E009-S01-002.md:31-34`; 16 `$GITHUB_STEP_SUMMARY` writes across `dev.yaml`, `release.yaml`, `publish-image.yaml` | AC4 makes run summaries an evidence surface. `act_runner`'s step-summary rendering is unverified and unnamed in either story. Lower severity because CI-AR41 also mandates job outputs, which are the durable half. | Note summary rendering as an observation in the certification report rather than an AC. |
| m2 | MINOR | Core §10 (diagram-first where it helps) | both stories | Story 001's design is a boundary and ordering problem — bootstrap trust before registration, job trust after startup, two runner pools, an endpoint coverage set — and carries no diagram. This is the case §10 names ("at least a context + one flow diagram"). | Add one Mermaid sequence diagram of the trust bootstrap ordering to `docs/ci/gitea-runners.md`. |
| m3 | MINOR | Core §10 (organized, discoverable) | `E009-S01-001.md:65`, `E009-S01-002.md:53`; `docs/README.md` | Both stories create documents in `docs/ci/`, which currently holds only `codex-assesment.md` and is not referenced from `docs/README.md`. No guard requires new docs to be indexed. | Index `docs/ci/` from `docs/README.md` as part of story 001. |
| m4 | MINOR | Core §10 (record the decision); Global §2 | `E009-S01-001.md:93-95`, `E009-S01-002.md:79-81` | Story 001's Out of Scope names only production ownership migration; story 002's names only "claiming compatibility with unpinned versions". The "no" branch of each of the four unknowns is neither in scope nor recorded as deferred — the same shape as the E008 gate findings F18/F19, which story 001 itself says were carried *"because the gate found them unaddressed and nothing documented a deferral"*. | For each unknown, record either the response or an explicit deferral with an owner. |

---

## Per-principle walkthrough

**Core §1 — Separation of concerns.** B4 (untrusted/protected pool separation asserted with no expressible
mechanism), M6 (the trust boundary's endpoint set is enumerated by hand rather than derived from the
components that cross it), M7 (action resolution is a runner concern presented as a context coordinate).
The bootstrap-versus-job-trust separation itself (story 001 AC1–AC2) is **coherent and correctly stated** —
*"A job step is never claimed to establish trust required for that same job to start"* is the right
invariant, and its test anchor (*"plant a job-level CA step in a job whose checkout already needed that
CA"*) attacks the right property. It is incomplete only in its endpoint enumeration (M6) and its silence on
the action-resolution endpoint (M7).

**Core §2 — Reuse over copy-paste.** PASS for the stories as specified. E008's copied bodies
(finalization gate, alias ordering, tag re-checks) are each pinned byte-identical by a same-body guard;
E009 adds no new duplication. Worth noting only that story 001's job-level CA step will be added to both
`dev.yaml` and `release.yaml` — a third copied body, which should get the same-body treatment its siblings
have.

**Core §3 — Design by contract.** B1 (the deny-by-default precondition the authority split rests on is
asserted nowhere in E009), M3 (a fail-closed contract whose "no" branch has no recorded response), M5
(recovery's real preconditions — output propagation, artifact scope — are unstated), M9 (the spine's
credential contract contradicts the shipped implementation), M12 (the stated denials cover a quarter of
the scope surface).

**Core §4 — Testability.** B2 (the gating capabilities are not in the DoD), B3 (the gate's scope is its own
subject), M4 (an anchor that tests a different proposition than its AC), M8 (an untested capability the
whole artifact path runs through), M13 (an estimate with no allowance for the empirical cycles this
project has twice recorded as unavoidable).

**Core §5 — Brevity without sacrificing readability.** PASS. Both stories are 95 and 81 lines and read
cleanly; the F18/F19/F20 carried-findings sections are the right length for what they carry.

**Core §6 — Comments explain current state and intent.** M11 (ADR-0011 describes a mechanism that has been
removed; the guard docstring and the ADR now contradict each other). Otherwise the workflow commentary is
exemplary and is the reason several of these findings could be grounded at all.

**Core §7 — Dependency selection.** M2 (`git-action-release`'s bundled `dist/index.js` cannot be rebuilt
outside a private registry — ADR-0010 accepts this, but E009 is where its unverified network behaviour
becomes load-bearing, and the story does not structure that determination). ADR-0010's named fallback is
correct practice; it is just unbudgeted.

**Core §8 — GA over alpha/beta.** M1 (node24 acceptance unconfirmed on the runtime three actions require),
M14 (`environment:` support unverified). Neither is a preview dependency in the classic sense, but both are
"depending on unconfirmed platform behaviour in the shipped path", which is the same rule.

**Core §9 — Unified structured logging with correlation.** m1. CI-AR41's evidence design (run ID/URL,
digests, hashes as job outputs) is sound and correlation-shaped; only the summary rendering surface is
unverified on the target platform.

**Core §10 — Documentation, organized, diagram-first.** M9, M10, M11 (three places where the architecture
documents E009 is built from no longer describe what shipped), m2, m3.

**GitHub Actions overlay — marketplace over custom scripting.** PASS. E008's composition is action-first
and the allowlist/pin policy (CI-AR4, ADR-0009) is mechanically enforced. E009 adds one "approved job-level
CA import action" (story 001 AC2), which is unnamed — worth naming before implementation so the owner
allowlist implication is known, but the story is not wrong to defer it to the tuple record.

**GitHub Actions overlay — pin to major, use the latest.** PASS with one recorded, justified exception:
`actions/upload-artifact@v4`/`download-artifact@v4` are deliberately off the latest major because *"Gitea's
act_runner implements the v4 artifact protocol; v5+ are GitHub-only"*
(`tests/ci/test_workflow_contracts.py:2233-2241`). That is exactly the right shape of exception and it is
guarded repo-wide. E009 should confirm the v4 protocol claim empirically — it is currently a documented
assumption, and it is the substrate of the F18 artifact round-trip.

**GitHub Actions overlay — hygiene (permissions, secrets, concurrency, reuse).** B1, B4, M12, M11.

**Python overlay.** Largely out of scope — E009 adds no packaging or runtime Python. One point of contact:
story 002's gate is a pytest module in `tests/ci/`, which is the right home (the project's framework, not a
bespoke harness). But its specified implementation — *"a test parses the declared case table out of
`docs/ci/gitea-certification.md`"* — is a hand-rolled Markdown table parser, which global rule §1 forbids
and which this repository has already paid ~two sprints for once (a hand-written YAML parser, three
CRITICAL defects). Folded into B3: the remediation there — declare the case set in a machine-readable file
parsed with the library the suite already uses, and render the human page from it — resolves both the scope
defect and the parser.

---

## Gate

**Not passed.** 4 BLOCKER and 14 MAJOR findings must be resolved or ADR-justified before story 001 starts.
The 4 MINOR findings defer to the backlog.

The structural question the orchestrator asked — *can the story structure survive any of the four unknowns
coming back "no"?* — answers **no** as written. All four are single points of failure for the epic; three
are prose inside story 001 and one is absent entirely; none has an acceptance criterion, a test anchor, or
a named response; and story 002 is a strict dependency of story 001 with no branch. The minimum structural
change is a determination step ahead of story 001's build work — a spike, or story 001's first acceptance
criterion — that answers node24, `TokenPermissionMode`, `default_branch`, the detector probe, nested
`workflow_call`, local composite actions, artifact-v4 round-trip and `environment:` acceptance, each with a
recorded response to "no", before any of the tuple's remaining work is estimated.

## Recommended ADRs

1. **Runner pool separation on a single-label pipeline (B4).** How CI-AR34's two pools are routed to without
   a per-forge `runs-on` divergence, or the recorded CI-AR2 exception if a divergence is accepted.
2. **The Gitea deployment preconditions E009 owns (B1, M12).** `TokenPermissionMode = restricted`, the
   minimum Gitea version whose token model honours job-level `permissions:`, the four-scope `AUTHORITY_SCOPES`
   limit and its residual, and how each is proven by refusal rather than by read-back.
3. **The certification gate's source of truth (B3).** Where the required case set lives independently of the
   evidence document, and how the case table is represented so no Markdown parser is written.
4. **Amendment to ADR-0011 (M11).** Record that the job-level alias concurrency groups were removed and why,
   so ordering is documented as re-derivation in the writing job rather than as serialisation.
5. **Amendments to ARCHITECTURE-SPINE (M9, M10).** CI-AR5's five-file topology; the Protected-credentials
   table's Gitea PyPI/TestPyPI row corrected to absent-by-host-capability.
6. **Action resolution source as a tuple element (M7).** Whether actions resolve from github.com or a mirror
   on the certified deployment, and the trust and version consequences of that choice.

---

DONE — Blocker: 4, Major: 14, Minor: 4
