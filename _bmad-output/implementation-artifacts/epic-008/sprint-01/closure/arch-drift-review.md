---
title: 'Sprint architectural drift review — E008 Sprint 01'
mode: 'B — Architectural review (sprint closure drift)'
date: '2026-09-02'
reviewer: 'l3io-arch-review'
dispatched_by: 'l3io-pm-execute sprint-closure §6'
epic_key: 'E008'
sprint: 'S01'
work_type: 'MIXED'
baseline: '_bmad-output/implementation-artifacts/epic-008/arch/arch-gate-review-2.md'
standards_loaded:
  - '.claude/skills/l3io-arch-review/references/standards-core.md'
  - '.claude/skills/l3io-arch-review/references/standards-github-actions.md'
  - '.claude/skills/l3io-arch-review/references/standards-python.md'
  - '.claude/skills/l3io-arch-review/references/standards-docker.md (stub)'
  - '.claude/skills/l3io-arch-review/references/standards-shell.md (stub)'
verdict: 'CHANGES REQUIRED — 1 BLOCKER, 6 MAJOR, 8 MINOR'
---

# Sprint architectural drift review — E008 / S01

## Executive summary

The two maintainer rulings landed well. Deleting 749 lines of Python and 613 lines of its
pytest in favour of `run:` bodies that the contract suite *executes* against real git and real
`jq` is a net strengthening, not a weakening: a module test proved the module, and these prove
what the workflow actually runs. The `@v1 → @v2` migration is the best-documented decision in
the epic — ADR-0006 read the published `action.yml` at each tag and caught an input rename that
would have left `vMAJOR.MINOR` silently frozen. Both named duplications carry the mitigation
they were promised: `test_forge_coordinates_are_derived_from_action_context_and_fail_closed`
executes **both** copies of the coordinate derivation against eleven identical input sets, and
the two same-body guards hold the re-check copies to one body. Those mitigations are real.

**The signature defect recurs three times, and I proved each by planting.** The rule is right
every time; the set examined is smaller than the rule. One BLOCKER is not a scope problem at
all: **the contract suite is red on the committed tree right now** — one of this sprint's own
closure documents trips a guard whose corpus is "every tracked text file".

**The single most important action:** fix the corpus of
`test_the_retired_local_build_paths_are_gone_and_nothing_invokes_them` so the suite is green,
then widen the ref-write prohibitions from `WORKFLOWS.glob("*.yaml")` to `GOVERNED_DEFINITIONS`
— the set this same file already computes — because ADR-0006's bolded "**never**, under any
spelling" is once again mechanically false.

## Scope of this review

Read in full: `/tmp/e008-closure/sprint-diff.txt`, `.github/workflows/{ci,dev,release,publish-image}.yaml`,
`.github/actions/{verified-bundle,publication-contract}/action.yml`,
`tests/ci/test_workflow_contracts.py` (all 124 guards),
`docs/adr/{0006,0009,0010,0011}`, `ARCHITECTURE-SPINE.md`, the baseline gate report.
Read in part: `verify-build.yaml`, `docs/{operational,architecture,guidelines,developer}.md`,
ADR-0004/0005/0007/0008, the four stories, `justfile`, `scripts/committed_versions.py`,
`.github/dependabot.yml`.

**Widened, with reason:** `docs/architecture.md`, `docs/guidelines.md`, `docs/developer.md` and
`.github/dependabot.yml` are outside the named inputs. `docs/architecture.md` is the Core §10
architectural axis and no other named input covers it; `docs/guidelines.md` §6 is cited *by the
workflows themselves* (`dev.yaml:193`, `release.yaml:322`) as the authority for a new dependency,
which makes it load-bearing rather than incidental; `dependabot.yml` is named by ADR-0009's
pin policy. Findings F-M5, F-M6 and F-M4 come from that widening.

**Method.** No claim of the form "the guard fires" or "nothing catches this" was taken on trust.
The tree (including `.git` and `_bmad-output`, so `tracked_text_files()` resolves) was copied to
a disposable root, violations were planted one at a time, and the full 215-item suite was run
after each. Four probes are cited by result below. **No file in the repository was modified by
this review** other than this report.

---

## Findings table

| # | Severity | Principle | Location | Finding | Remediation |
|---|----------|-----------|----------|---------|-------------|
| B1 | **BLOCKER** | Global rule §4 (a guard's reach exceeds its rule); Core §4 | `tests/ci/test_workflow_contracts.py:4895,4899,4917-4926` vs `_bmad-output/implementation-artifacts/epic-008/sprint-01/closure/review-E008-S01-004.md:197` | **The contract suite is red on the committed tree.** `test_the_retired_local_build_paths_are_gone_and_nothing_invokes_them` scans *every tracked text file* for an invocation of the retired build script. This sprint's own code-review artifact documents the pattern's match table — the cell `\| bash docker/build.sh \| yes \|` has no preceding backtick, so it matches. `1 failed, 214 passed`. The rule is "nothing in the delivery path invokes the retired script"; the set is "every byte git tracks", which now includes process artifacts that *discuss* the pattern. | Derive the corpus from the surface the rule is about rather than from all of git: workflows, composite actions, `justfile`, `scripts/`, `docker/`, `docs/`, `README.md` — or keep `tracked_text_files()` and exclude the `_bmad-output/` process tree. Then re-plant `run: ./docker/build.sh` inside `.github/workflows/` and inside `docs/` to prove the narrowed corpus still catches a real resurrection. Do **not** fix this by adding the review file to `INVOCATION_SCAN_EXEMPTIONS`: that turns a one-file exemption into a growing list, which is the hand-kept scope global rule §4 forbids. |
| M1 | MAJOR | Global rule §4; ADR-0006:191-196, :209-211 (the immutability table) | Guards at `tests/ci/test_workflow_contracts.py:748,785,856,870,2934,3046,3074,3603,3679,3807` — all iterate `WORKFLOWS.glob("*.yaml")` — vs `GOVERNED_DEFINITIONS` at `:57-60` | **Every ref-write, Release-creation and alias-move prohibition is blind to composite actions.** The same module computes `GOVERNED_DEFINITIONS` (workflows **plus** `ACTIONS.rglob("action.yml")`) and uses it for the pin policy, the `ACT` scan and the descriptor-count scan — but not for any of these. `release.yaml`'s `finalize` holds `contents: write` and calls `./.github/actions/verified-bundle`, so a step inside that composite runs with the finalizer's authority. **Probe P1:** `git push -f origin refs/tags/v1`, `git push origin :refs/tags/v1.2.3`, `gh release create v1.2.3`, and `docker buildx imagetools create` planted together in `.github/actions/verified-bundle/action.yml` → **suite unchanged (214 passed)**. ADR-0006's table says `refs/tags/vX.Y.Z` is force-written "**never**, under any spelling"; that claim is again false, and this is finding N2 recurring with the pattern fixed and the scope not. | Replace `sorted(WORKFLOWS.glob("*.yaml"))` with `GOVERNED_DEFINITIONS` in all ten loops and walk steps with the existing `_steps()` helper (which already yields `runs.steps` for composite actions). `_alias_moving_jobs()` and `_writing_steps()` need a `(file, job-or-action)` key rather than `(workflow, job)`. Plant all four of P1's violations inside a composite action — the current plants all live in workflows and prove nothing about this set. |
| M2 | MAJOR | Global rule §3 (a rule enforced by memory); Core §3; spine CI-AR36 `ARCHITECTURE-SPINE.md:165-167` | `.github/actions/verified-bundle/action.yml` (the mechanism); no guard — the only `verified-bundle` assertion in 5,024 lines is `tests/ci/test_workflow_contracts.py:3696-3710`, scoped to the Release-attaching finalizer | **CI-AR36 boundary revalidation is enforced for one job out of six.** "Every publisher downloads the verified bundle, checks `SHA256SUMS`, validates `build-manifest.json`, matches source/version … before any login or upload" is the trust boundary between the secret-free verifier and the credentialed publishers. **Probe P2:** in `dev.yaml`, `publish-package-forge`'s `verified-bundle` step replaced with a bare `actions/download-artifact@v4` — no checksum recheck, no manifest revalidation, no identity match, and the wheel uploaded to the forge index regardless → **suite unchanged (214 passed)**. The mechanism is correct in all six publishers today; nothing keeps it there. | Add a derived guard over `_publishers()` across `_channel_workflows()`, restricted to jobs that have steps: assert a `uses:` ending `/verified-bundle` appears strictly before the job's first `_is_publishing_step` and before its first `docker/login-action` — both helpers already exist. Plant the removal (P2) and the reordering (revalidation after the login). |
| M3 | MAJOR | Core §2 (duplication without the mitigation its siblings got); global rule §3; ADR-0011:118-123 | `dev.yaml:628-654` and `release.yaml:647-673` (two copies of the ~27-line `jq` gate); `tests/ci/test_workflow_contracts.py:3176-3183` (`_run_gate`), `:4199-4341` (twelve input-validation tests, **all against `RELEASE_WORKFLOW`**), `:3250-3278` (the only two executions of the dev copy) | **The third duplication of this sprint got no same-body guard.** The forge-coordinate derivation (2 copies) and the tag re-checks (4 + 3 copies) each carry a mitigation. The finalization gate — the largest copied body, and the one that decides whether an alias moves — carries none, and its twelve input-validation tests are keyed to `release.yaml`. **Probe P3:** the `enabled set names no destination at all`, `no publisher result was supplied for …` and `results were supplied for …` refusals deleted from `dev.yaml`'s copy only → **suite unchanged (214 passed)**. ADR-0011's "Every property the deleted pytest files proved is now proven the same way" is therefore true of the stable copy and false of the development one — prose overstating its own coverage, which is the failure global rule §3 exists for. | Either (a) add `test_every_finalization_gate_is_the_same_body`, locating gates by `GATE_MARKER` across `_channel_workflows()` and asserting `len(set(bodies)) == 1` once comments are stripped — the shape the two sibling guards already use; or (b) parametrize the twelve `F7` input-validation tests over `_gate_steps(path)` for every channel workflow, with per-channel bindings derived from `_publishers()`. (b) is stronger and costs one fixture. Plant P3 either way. |
| M4 | MAJOR | Core §7 (dependency selection unrecorded); Core §8; the decision-making hook (a load-bearing call with no ADR) | `dev.yaml:200`, `release.yaml:330`; constant at `tests/ci/test_workflow_contracts.py:1217`; guard `:1535-1595`; the only record is `docs/guidelines.md:84-88` | **`LiquidLogicLabs/git-action-docker-metadata@v6` renders every published image reference and has no ADR and no verification of its `action.yml`.** Its two sibling actions each got both: ADR-0006 read `git-action-tag-floating-version`'s `action.yml` at `@v1` and `@v2` and found a camelCase→hyphen input rename that Actions passes through silently, and ADR-0010 did the same for `git-action-release@v2`. Nothing in the four stories, the ADRs or the spine records that `@v6`'s `images`, `flavor` and `tags` inputs were read at that tag. The same silent-failure class applies with a worse blast radius: `test_image_references_are_rendered_by_the_metadata_action_never_hand_joined:1583-1587` asserts the string `latest=false` is *passed*, not that it is *honoured* — so if `flavor` is not an input at `@v6`, the action's `latest=auto` default makes the **publisher** push `latest`, defeating the finalizer's sole ownership of aliases (CI-AR29, ADR-0011, `test_only_registered_finalizers_move_an_alias`) with the whole suite green. It is also a fork of `docker/metadata-action` on a different major line; guidelines' claim of "same version numbering" is unverified. | Read `git-action-docker-metadata@v6`'s published `action.yml` and record the result the way ADR-0006 and ADR-0010 record theirs — inputs, outputs, `using:` runtime (E009's pinned tuple needs it), upstream and fork divergence, maintenance, and the accepted cost. An amendment to ADR-0011 is sufficient; a new ADR is cleaner. If `flavor` cannot be confirmed, drop it and pass only the one `type=raw` tag, which needs no flavor at all. |
| M5 | MAJOR | Core §10 (architectural axis; docs that contradict the code); Core §6 | `docs/architecture.md:92-101` ("## 5. Known architectural gaps (tracked, not yet fixed)"), `:111` (ADR index), whole file | **The architectural-axis document still describes the pre-Epic-7 world.** It lists "**CI cannot currently build or publish either artifact**" as an open gap — the exact gap this epic closed — and "dependency/build-artifact parity gap … hand-maintained `pip install` list", closed by ADR-0004/E007. Its recorded-decisions table stops at ADR-0005 while 0006–0011 exist, and its only entry for 0005 describes "CI reusable-workflow wiring for `build.yaml`", a workflow deleted in E007. It carries three Mermaid diagrams, none of the delivery pipeline: after this sprint the publication graph is five workflow files, two reusable, twelve jobs, three registered finalizers and two credential classes, and there is no view of it anywhere in `/docs`. This is gate finding F24 carried, and the graph got materially larger. Nothing guards it: `test_the_runbook_names_every_channel_and_no_workflow_that_is_not_on_disk:4841` derives its channel set from disk but reads `docs/operational.md` alone. | Delete the two closed gaps, extend the ADR index through 0011, and add a delivery-topology section with one Mermaid job-graph (plan → verify → fan-out → gate → finalize → aliases → evidence) for each channel. Then widen the runbook guard's *citation* half — "every workflow filename this page cites exists on disk" — from one page to every tracked file under `docs/`, which makes M6 mechanical rather than a re-reading. |
| M6 | MAJOR | Core §6 (a document asserting the opposite of the code); global rule §3 | `docs/guidelines.md:78`, `:87`, `:92-94`, `:96-99`, `:114` | **The document the workflows cite as their authority contradicts them in four places.** `dev.yaml:193` and `release.yaml:322` both justify the metadata action with "docs/guidelines.md section 6". That section: links three times to `.github/workflows/build-container.yaml`, deleted in E007 (`:78`, `:87`, `:114`); states the metadata action is "Adopted in build-container.yaml's `Docker meta` steps" — it is adopted in `dev.yaml` and `release.yaml`; states `release.yaml` "does not currently exist, having been deleted … in `9e43b90`"; and lists `git-action-tag-floating-version` and `git-action-docker-test` among actions that "remain candidates … adopting them is a separate implementation decision, not bundled into this vendor-preference fix" — both are adopted and load-bearing (`release.yaml:810`, `publish-image.yaml:334`, `verify-build.yaml:548`). A reader following §6 to check why the metadata action was chosen lands on a deleted file. | Rewrite §6's adoption paragraphs against what shipped, citing ADR-0006 and ADR-0010 for the two actions that have one and M4's new record for the third. Enforce it: extend the citation half of the runbook guard (M5) to every markdown file git tracks, so a `.github/workflows/*.yaml` reference that no longer exists on disk fails the suite. Plant a link to a deleted workflow. |
| m1 | MINOR | Global rule §4 (a hand-kept literal where the property is derivable) | `tests/ci/test_workflow_contracts.py:4013-4017` (`== 4`), `:4025-4029` (`== 3`) | The two same-body guards assert hand-counted copy counts. The property is "one re-check before each irreversible act", and `test_step_based_publishers_re_read_the_tag_set_before_they_upload:1981` already derives exactly that from `_publishers()`. The literal adds no reach — an irreversible act added *without* a re-check leaves the count at 4 and passes here — and goes red for the wrong reason the day a destination is added. | Keep `len(set(bodies)) == 1`; replace the count with `len(refusers) == len([publishers with steps that reach an irreversible act])`, derived from the same helper the neighbouring guard uses. |
| m2 | MINOR | Global rule §4 | `tests/ci/test_workflow_contracts.py:672-680` vs `_alias_moving_jobs()` at `:2926-2944` | `test_alias_ordering_is_decided_from_git_never_from_a_registry` defines "this file moves aliases" as "some step uses `APPROVED_ALIAS_ACTION`" — a **Git** alias. `dev.yaml` moves the `dev` **registry** alias and uses that action nowhere, so the whole file is skipped, while `_alias_moving_jobs()` twenty pages later already treats a registry alias move as an alias move. Coverage is currently supplied by `test_channel_workflows_consume_image_inspection_rather_than_performing_it:1709`, so this is redundancy lost rather than reach lost — but the docstring's "Only files that move aliases are examined" is untrue of the file that moves one. | Compute `moves_aliases` from `_alias_moving_jobs()`. One line, and it removes a dependency on another guard's continued existence. |
| m3 | MINOR | Global rule §4 | `tests/ci/test_workflow_contracts.py:1186-1187`, `:1256-1270` (`_channel_workflows`), `:1599-1650` | CI-AR39's "one Buildx invocation" count is asserted only inside the literal file `publish-image.yaml`, and `_channel_workflows()` is keyed on the literal reference string. **Probe P4:** a second reusable image publisher (`publish-image-extra.yaml`, a copy with its own `bake`) wired into `release.yaml` → **five guards fired** (`test_publisher_credentials_stay_disjoint_between_destinations`, `test_the_run_evidence_job_blocks_on_every_publisher`, `test_every_finalizer_waits_for_every_publisher_and_reads_every_result`, `test_every_run_summary_reports_the_verified_bundle_and_every_destination`). So it is not a silent escape — but the fan-out guard itself was not one of the five, and a correctly-wired second publisher would carry a second build unexamined. | Derive the publisher set as "a local reusable workflow containing a Buildx build" rather than by path literal, and assert one build across that whole set. |
| m4 | MINOR | Core §6 (a record describing a shape it no longer has) | `docs/adr/0006-release-version-transaction.md:112` vs `:126` | Gate finding N9's one-line correction was applied at `:126` ("`(workflow filename, job name)` **pairs**") and missed at `:112`, which still reads "unless its **job name** is registered in `RELEASE_FINALIZER_JOBS`". The two sentences now contradict each other inside one ADR. | One line: `(workflow filename, job name)` pair. |
| m5 | MINOR | Core §6 | `docs/adr/0009-action-pin-policy.md:96` | Still reads "When `release.yaml` lands (**E008-S01-003**), record the reviewed SHA…". `release.yaml` landed in E008-S01-002, the SHA and its review date *are* recorded (`release.yaml:421`, `:509`, `dev.yaml:365`, `:465`, each with the review date in the comment above it), and the follow-up is done — but it is written in the future tense against the wrong story. Gate finding N10, unresolved. | Correct the story reference and move the bullet from "Follow-ups" to a completed record. |
| m6 | MINOR | Core §10 (documentation contradicting the code); global rule §4 | `ARCHITECTURE-SPINE.md:76-77` vs `justfile:4,10,17,21,25,28,40,44,51` | CI-AR7 still claims the justfile exposes `setup`, `lint`, `test`, `test-local`, `package`, `image`, `build`, `verify`, `release PART`. Three do not exist: `setup` (it is `install`), `package` (none — `build` produces distributions), `verify` (it is `check`). Two that exist are unlisted: `fix`, `release-resume`. Gate finding N11, unresolved and unchanged. | Replace the enumeration with a pointer to the justfile plus a guard asserting that every recipe a workflow or document invokes exists — the global-rule-§3 answer. The one-line alternative is to correct the names. |
| m7 | MINOR | Core §5 (failure mode readability) | `tests/ci/test_workflow_contracts.py:1421-1436` | `_coordinate_derivations()` locates a job by `FORGE_COORDINATE_OUTPUTS & set(outputs)` — correctly derived — then resolves the step with the hard-coded output name `"registry"`. A channel that emits `image-repository` and `package-index-url` but not `registry` raises a bare `KeyError` from the dict subscript inside `_producing_step`, which reads as a broken test rather than as a caught violation; `_step_with_id:2201-2209` explains at length why that matters. | Resolve through one of the emitted names (`next(iter(sorted(emitted)))`), and assert `"registry" in emitted` with a message. |
| m8 | MINOR | Global rule §3 (a rule the ADR claims is enforced, enforced two-thirds) | `tests/ci/test_workflow_contracts.py:3639-3653` vs `docs/adr/0006-release-version-transaction.md:227` | ADR-0006 says the guard "asserts the hyphenated inputs AND the hyphenated outputs". It asserts `update-minor`, `ignore-prerelease` and both outputs, and that the three camelCase names are absent — but never that **`ref-tag` is passed at all**. An alias step with `update-minor: "true"`, `ignore-prerelease: "true"` and no `ref-tag` passes, and the action would then move an alias against whatever it defaults to. | `assert inputs.get("ref-tag")`, and assert it resolves through the plan job's `release-tag` output rather than a literal. Plant the omission. |

---

## Per-principle walkthrough

**Core §1 — Separation of concerns.** PASS. The strongest structural result of the sprint. The
finalization split (`finalize` holds `contents: write` and no registry credential;
`finalize-image-aliases` holds registry credentials and no `contents:`) is real least privilege,
and `test_ref_writing_and_registry_alias_privileges_never_meet:3064` plants both directions. Every
read of a *published* image lives in `publish-image.yaml`, which moves no alias, so the CI-AR39
inspection and the CI-AR26 revival guard no longer collide — the baseline's BLOCKER N1 is closed
by placement rather than by weakening a rule, which is the better fix. `PUBLISH_*` has one reader
per file and the channel distinction costs no runtime condition.

**Core §2 — Reuse over copy-paste.** M3. Three duplications shipped; two carry the mitigation
they were promised and one does not. The forge-coordinate mitigation is genuinely strong — both
copies are executed against eleven input sets including four fail-closed hosts and four
`GITEA_ACTIONS` spellings, and asserted to emit byte-identical output. The `jq` gate is the
largest copied body in the sprint and the one whose divergence moves an alias. Separately, and
below the finding line: the four-times-repeated "Stage only the verified wheel and sdist" step and
the four package-evidence summary blocks are small enough that the §2 nuance ("do not
over-abstract") applies.

**Core §3 — Design by contract.** M2. The contracts are declared well — the enabled/required/
skipped relation as a `jq` program with explicit refusals for malformed JSON, unknown result,
unknown planned state, unreported destination and undeclared destination; the identity relation
as a comparison between fields rather than a literal; fail-closed forge coordinates. What is
missing is the precondition at the trust boundary: nothing asserts that a publisher revalidates
before it holds a credential (M2), and one of the two gate implementations can lose its input
validation silently (M3).

**Core §4 — Testability.** B1, M1, M2, M3. The design is highly testable and the sprint used
that: real git repositories with real annotated tags, real `jq`, the real `run:` bodies with the
step's own `env:` rendered through the workflow's own expressions so a renamed job breaks the
render. `_render:3007-3018` is the best single idea in the file. The failures are all the same
shape as the baseline's: **each new guard was tested by planting the violation the author had in
mind.** Four probes, four escapes or breakages. And a suite that is red on `main` is the most
consequential testability defect available, because a permanently-red gate gets disabled rather
than fixed — a risk this file's own docstring at `:487-489` names.

**Core §5 — Brevity without sacrificing readability.** PASS with m7. Two `run:` bodies are at the
edge: the `jq` finalizer gate (27 lines of a language most readers skim) and the Docker Hub
repository composition in `release.yaml:218-250`. Both are justified in place — the `jq` because a
decision spelled as an `if:` expression is testable only by reading it, which is exactly right —
and both are executed by tests. Baseline N12 is resolved: `APPROVED_ALIAS_ACTION` and
`FORCED_REF_WRITE` now sit at `:802-818` beside the tests that use them.

**Core §6 — Comments describe current state.** M5, M6, m4, m5, m6. Baseline N13 is fully
resolved — `ci.yaml:44-49` no longer credits `build.yaml`, and `scripts/committed_versions.py:93`
now says release-please "was retired by ADR-0006 and is forbidden by contract test". But four
stale records survive and two are new-ish: `docs/guidelines.md` §6 now points a reader at a
deleted workflow to explain a dependency the workflows cite it for, and `docs/architecture.md`
lists this epic's deliverable as an open gap. The in-code comments are the opposite — unusually
good, and several of them (`:1449-1452` on why the 535-line module went, `:2894-2896` on why each
channel's re-check has its own marker) would survive a reader who disagreed.

**Core §7 — Dependency selection.** M4. Four `LiquidLogicLabs` actions are now load-bearing.
Two have an ADR that verified the published `action.yml` at the exact tag; `git-action-docker-test@v2`
arrived in E007 and is recorded in `docs/developer.md:114`; `git-action-docker-metadata@v6`
has neither. `pypa/gh-action-pypi-publish` is pinned to a reviewed 40-character SHA in all four
call sites with the review date recorded and asserted
(`test_every_sha_pinned_publisher_records_the_date_it_was_reviewed:1888`), and
`test_credential_handling_publishers_are_registered_as_sha_pinned:300` derives the *candidate*
set from the workflows so a new publisher cannot take the floating-major branch unnoticed. That
pair is the model M4 asks the metadata action to be held to.

**Core §8 — GA over alpha/beta.** PASS. No preview dependency is load-bearing. Every external
action is an approved owner on a floating major (`@v3`/`@v4`/`@v6`/`@v7`) or the one reviewed SHA.
The `upload-artifact@v4` / `download-artifact@v4` exception is ADR-grade, Dependabot-protected
(`.github/dependabot.yml:12-23`) and asserted both ways
(`test_artifact_actions_remain_on_the_both_forge_v4_pair:1029`,
`test_dependabot_protects_the_artifact_pin_it_would_otherwise_undo:1057`). `dependabot.yml`'s
comment — "the contract tests enforce the *form* of a reference … they do not and cannot check
currency, which needs a network call. **Do not add a test that claims to**" — is global rule §3
applied unprompted and correctly.

**Core §9 — Unified correlated logging.** PASS. Every publisher writes a run summary carrying the
run ID, run URL, package version, source SHA, wheel SHA-256 and build-manifest SHA-256;
`test_every_run_summary_reports_the_verified_bundle_and_every_destination:4969` derives the
aggregator ("depends on a publisher and ships nothing") and requires every publisher's `result`,
the digest, the platforms, the Release URL and the manifest hash to reach it. The image-alias
step's `trap report EXIT` (`release.yaml:989`) is the right instinct: a partial registry write
still reports which names moved. No secret reaches a log — the alias action's credential lives in
`GIT_CONFIG_VALUE_0` on one step and never in `.git/config`
(`test_a_finalizer_never_leaves_a_credential_in_the_workspace:3828`). The reverse join from a
published digest back to its run is now documented (`docs/operational.md:331` ("From an image digest to the run that published it")), closing baseline F30.

**Core §10 — Documentation.** M5, M6, m6. `docs/operational.md` is genuinely good and genuinely
guarded: the recovery runbook, the prohibited-recovery-action list with its wording plants
(`:4811`), the accepted tag race, `DOCKERHUB_ORG`, and a channel set derived from disk. The spine
carries `DOCKERHUB_ORG`, the `FORGE_REGISTRY` retirement and CI-AR40's evaluation-not-wiring
clause. The gap is one level up: the *architectural* axis was never updated, the vendor-preference
document that the workflows cite is now wrong, and the publication job graph — the most complex
structure this repository contains — has no diagram anywhere.

**GH Actions overlay — marketplace over custom scripting.** PASS, and this is the ruling under
review. Deleting `forge_coordinates.py` (235), `stable_tags.py` (301) and `finalizer_gate.py`
(213) plus 613 lines of pytest, in favour of `run:` bodies each under 30 code lines, is sound on
the overlay's own terms — the overlay's fallback clause asks for custom logic to be "testable,
reusable", and executing the real step body against real git is *more* faithful than testing a
module the workflow calls. The overlay's preference for a marketplace action over hand-rolled
shell is honoured in both directions: the alias move, the Release, the image references and the
smoke test are all actions. M4 is the cost of that second ruling being taken without the record
its two siblings got.

**GH Actions overlay — pinning.** PASS. Per-action rather than per-owner, `SHA_PINNED_ACTIONS`
reached by a derived candidate set, no `@main`, no interpolated `uses:`, Dependabot on
`github-actions` weekly. `test_no_third_party_action_creates_a_release:820` closes baseline N6 —
`APPROVED_RELEASE_ACTION` is no longer a dead constant, and `actions/create-release@v1` now fails.

**GH Actions overlay — hygiene.** M1, M2. Least privilege is precise: `contents: write` exists in
exactly one job in the repository, the scalar `permissions:` form is refused outright
(`:718-724`), no secret sits at workflow scope, and `secrets: inherit` on a verifier caller fails.
Concurrency is right in both channels and the *difference* between them is deliberate and asserted
(`cancel-in-progress: true` for dev candidates that supersede, `false` for stable identities that
queue). The hygiene gap is M1: the prohibitions stop at the workflow file boundary, and a
composite action called from the one `contents: write` job is on the other side of it.

**Python overlay.** PASS. Poetry single manager, lock committed, `requires-python` bounded, one
interpreter authority through `setup-poetry-python`, one committed-version implementation in
`scripts/committed_versions.py` asserted by a guard keyed on *any* version-shaped output
(baseline N4 closed — a job emitting `dev-version` is now governed). `pytest` throughout; no
bespoke harness anywhere. `dockerfile-parse` and `markdown_it` are maintained libraries doing work
a hand-rolled scanner would do badly.

**Docker overlay (stub — provisional).** PASS. One multi-platform Buildx invocation carrying every
tag, digest-pinned base, the published index asserted by the `vnd.docker.reference.type`
annotation rather than a descriptor count (with the count spelling forbidden across every governed
definition *and* `scripts/*.py`), and the published image pulled by digest and actually started —
with the limit of that smoke test (native descriptor only; the other platform rests on
`py3-none-any` provenance) stated in the run summary rather than left implicit.

**Shell overlay (stub — provisional).** PASS. Every `run:` body opens `set -euo pipefail`, every
expansion is quoted, every operator-influenced value arrives through `env:` rather than through
interpolation into the script text, and no body outgrew shell — the largest is the `jq` gate,
which is a program in a language suited to it, not branching shell.

---

## Answers to what you asked be challenged hardest

**1. Is there another guard keyed on a name or literal where the property is derivable?** Yes —
three, and the worst of them is not keyed on a name at all but on a *set*: **M1**, where ten
prohibitions iterate `WORKFLOWS.glob("*.yaml")` while the module's own derived scope,
`GOVERNED_DEFINITIONS`, is one line above and includes the composite actions those workflows call.
That is the same defect as the hand-written 2-tuple the baseline found, one refactor later: the
derived set was built, and then not used by the guards that most need it. **M3** is the same shape
keyed on a filename (`RELEASE_WORKFLOW`), **m3** on a path literal, **m1**/**m6** on hand-kept
enumerations, **m2** on a definition of "alias" narrower than the one the same file uses elsewhere.
Set against that: F11, F12/N4, F15 and F2 are all genuinely closed, and the new derivations
(`_publishers`, `_channel_workflows`, `_alias_moving_jobs`, `_coordinate_derivations`,
`_trigger_surface`, `_membership_steps`) are the right instinct applied ten times.

**2. Does the ADR set still describe what shipped?** Mostly, and better than most repositories.
ADR-0010's and ADR-0011's "Implemented" sections are honest about what changed *and* about what
they had to amend to accommodate it — ADR-0011 records that the finalization split forced
`test_publisher_credentials_stay_disjoint_between_destinations` to become per-destination-class,
and pays for the narrowing in two other directions, both planted. Two claims are now false:
ADR-0011's "Every property the deleted pytest files proved is now proven the same way" (M3, true
of the stable gate only) and ADR-0006's "**never**, under any spelling" (M1, again). ADR-0006 also
contradicts itself internally on the registry's shape (m4), and ADR-0009 still speaks in the
future tense about work that is done (m5). This is F4's failure mode — an ADR that misdescribes
the code — recurring at lower amplitude.

**3. Do the CI-AR requirements still hold?**
- **CI-AR36 (boundary revalidation)** — holds in the code, enforced by nothing. **M2**, proven.
- **CI-AR37 (no all-destination protocol)** — **holds, and I checked this specifically.** The gate
  is `jq` over two `env:` values, both of which are workflow-native: `needs.<job>.result` and a
  plan-job output. No artifact is written, no schema exists, nothing is exchanged between
  destinations, and the evaluation happens *after* the fan-out. It revives neither CI-AR22 nor
  CI-AR23. `_executable_text` even ensures the *prose* about a retired mechanism is not mistaken
  for the mechanism.
- **CI-AR39 (one-build fan-out)** — holds. One `buildx bake --push` carrying every tag for both
  platforms, no per-registry rebuild anywhere in a channel workflow, a caller that narrows
  `platforms:` fails, and the digest and inspected platforms are exported as workflow outputs.
  Scope caveat at **m3**.
- **CI-AR40 (required fan-out)** — holds, and this is where the baseline's N3 was most at risk.
  Every finalizer `needs:` every publisher, the transitive-needs check is derived from
  `_publishers()`, `!cancelled()` is now *required* on a registered finalizer rather than merely
  `always()` being forbidden (`:606-616`), and step-level `always()` is refused too. The two
  mandatory ADR-0011 anchors are executed. For the stable channel this is now enforced end to end;
  for the development channel the *shape* is enforced and the *content* is not (M3).
- **CI-AR41 (workflow-native evidence)** — holds, and is enforced at the job that actually writes
  the summary rather than "somewhere in the file", with every set derived. Best-enforced
  requirement in the sprint.

**4. Is anything unreachable, unproven, or asserted only by prose?**
- *Asserted only by prose:* CI-AR36 across five of six publishers (M2); the dev channel's gate
  semantics (M3); `@v6`'s input contract (M4); `ref-tag` (m8); ADR-0006's `refs/tags/vX.Y.Z`
  immutability against anything outside a workflow file (M1).
- *Unreachable:* nothing. The topology guard proves the workflow set partitions into reusable
  files and event owners with no orphan and no second owner of an event, and
  `test_no_workflow_calls_a_local_workflow_or_action_that_does_not_exist` proves every local
  `uses:` resolves. The same is *not* true of documentation links — `docs/guidelines.md` points
  three times at a deleted workflow (M6), and no guard covers doc links outside `operational.md`.
- *Unproven:* `docker buildx bake` consuming `TAGS`/`PLATFORMS` as env overrides is asserted by
  the presence of the two variables in the step's `env:` (`:1638-1642`) rather than by executing
  bake against `docker-bake.hcl`. That is a reasonable line — the guard cannot run a build — but
  it means a rename of the bake variables would pass. Not raised as a finding; noted for E009,
  which will run the real thing.

**5. What did the two rulings cost, and was it worth it?** The Python deletion cost one
un-mitigated duplication (M3) and bought executable evidence for everything else — a good trade,
and the two mitigations that *were* built are the strongest guards in the file. The
prefer-an-action ruling cost one unrecorded dependency (M4) and bought the `@v1 → @v2` input audit
that ADR-0006 now carries, which is worth more than it cost. Neither ruling is the problem; in
both cases the remediation added rules faster than it added reach, which is the same sentence the
baseline report ended on.

---

## Gate

**CHANGES REQUIRED.** The sprint cannot be marked done as it stands.

- **BLOCKER (1): B1.** The contract suite is red on the committed tree. This is not a judgement
  call — `poetry run pytest tests/ci/test_workflow_contracts.py` returns `1 failed, 214 passed`
  today. Roughly ten lines of corpus derivation plus two plants.
- **MAJOR (6): M1, M2, M3, M4, M5, M6.** M1, M2 and M3 are each one derived loop and one planted
  violation, and each closes a claim an ADR or the spine already makes in writing. M4 is one
  reading of a published `action.yml` and one record. M5 and M6 are documentation the sprint
  changed the world under; M5's remediation makes M6 mechanical, so do M5 first.
- **MINOR (8): m1–m8.** Defer to the issues backlog, **except m4** (ADR-0006:112 contradicting
  ADR-0006:126) which is one line inside a file M1's remediation must open anyway.
- **Carried and still open from the baseline:** N10 (m5), N11 (m6), F24 (folded into M5). The
  dispatch states everything the baseline raised was addressed before implementation; N10 and N11
  were not, and I found no record of a decision to defer them. Recorded as a fact, not a
  re-litigation.

**Assumptions recorded, since no decision could be requested.**
1. I treated a red suite as a BLOCKER on its own terms rather than asking whether the sprint
   intends to land the closure documents. If those artifacts are meant to stay untracked, B1's
   remediation is smaller — but the guard would still be one committed review document away from
   red, so the corpus fix stands either way.
2. I treated `git-action-docker-metadata@v6`'s `flavor` input as *unverified*, not as *broken*. I
   have no network access and did not read the published `action.yml`. M4 asks for the reading,
   not for a change of action.
3. I did not re-open the two accepted duplications. Both mitigations were probed and both hold.

## Recommended ADRs and records

1. **One ADR or one ADR-0011 amendment** for `LiquidLogicLabs/git-action-docker-metadata@v6`
   (M4): the verified `action.yml` contract at that tag, the fork's relationship to
   `docker/metadata-action`, its `using:` runtime for E009's pinned tuple, maintenance and bus
   factor, and the accepted cost. Its two siblings each have one; this one is the odd surface out.
2. **A record, not an ADR, for the composite-action authority boundary** (M1): composite actions
   execute with the calling job's `permissions:` and credentials, so the ADR-0006 grant registry
   governs them transitively. State it in ADR-0006 beside the registry, and let the widened guard
   enforce it.
3. **Four one-line corrections:** ADR-0006:112 (m4), ADR-0009:96 (m5), spine CI-AR7 (m6),
   `docs/architecture.md:101` (part of M5).
