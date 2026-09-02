---
title: 'Epic architecture gate (re-run) — E008 Multi-Channel Delivery, E009 Certified Gitea Portability'
mode: 'B — Architectural review (post-remediation verification)'
date: '2026-09-02'
reviewer: 'l3io-arch-review'
dispatched_by: 'l3io-pm-execute step-04'
work_type: 'MIXED'
epics: ['E008 (phase 1)', 'E009 (phase 2)']
sprint: 'S01'
supersedes_verdict_of: '_bmad-output/implementation-artifacts/epic-008/arch/arch-gate-review.md'
standards_loaded:
  - '.claude/skills/l3io-arch-review/references/standards-core.md'
  - '.claude/skills/l3io-arch-review/references/standards-github-actions.md'
  - '.claude/skills/l3io-arch-review/references/standards-python.md'
  - '.claude/skills/l3io-arch-review/references/standards-docker.md (stub)'
  - '.claude/skills/l3io-arch-review/references/standards-shell.md (stub)'
verdict: 'CHANGES REQUIRED — 1 BLOCKER, 10 MAJOR, 6 MINOR'
---

# Epic architecture gate, re-run — E008 / E009

## Executive summary

The remediation is substantial and, on the decision half, excellent. ADR-0009, ADR-0010 and
ADR-0011 are three of the better ADRs in this repository: each names the question the previous
artifacts were failing to distinguish, weighs rejected options honestly, and states its own
unverified assumptions rather than assuming them away. The F13 spike was actually run, produced
numbers, and closed ADR-0008's second open question with a *reason* the result holds
(`py3-none-any`, so exact-wheel provenance is platform-independent by construction) rather than
an observation that it did. **Eleven of the twenty blocking findings are genuinely closed, and
I verified nine of those by planting a violation and watching the suite go red.**

The failures are all of one kind, and it is the kind the previous report predicted: **a guard was
written, the rule it encodes is right, and the set it examines is smaller than the rule.** I
copied the tree to a scratch root, wrote a plausible `dev.yaml`, registered a finalizer as story
003 will, and planted fourteen violations. Five of them passed a fully green 33-test suite —
including `git push -f` onto `refs/tags/v1` from the registered finalizer, which ADR-0006 states
in bold is "forbidden outright … under any spelling", and delete-and-recreate, which the same ADR
names explicitly as the same operation.

One finding is new and hard: **`test_no_publisher_queries_a_destination_before_uploading`
(F17's fix) rejects the published-index platform inspection that CI-AR16, CI-AR18, CI-AR39,
CI-AR41, ADR-0008 and both story ACs require.** ADR-0008 prints the exact assertion to write and
names `imagetools inspect --raw <ref>` as its source; the guard forbids that command in any
credential-bearing job. This is F1 again in a different costume — a mandated mechanism rejected by
a shipped tier-one test, making `E008-S01-001` unbuildable as written.

**The single most important action:** decide, before `dev.yaml` is written, how the published
index is inspected without tripping the CI-AR26 revival guard — the fix is to scope that guard to
*pre-upload* probes as its own name says, not to the whole job. Everything else on this list is
a guard whose scope needs widening, and each is cheaper now than after two workflows exist.

## Scope of this review

Read in full: the six stories, ADR-0006/0008/0009/0010/0011, `ARCHITECTURE-SPINE.md`,
`tests/ci/test_workflow_contracts.py`, the prior gate report. Read in part: ADR-0004/0007,
`.github/workflows/ci.yaml`, `.github/workflows/verify-build.yaml`,
`.github/actions/setup-poetry-python/action.yml`, `docker/Dockerfile`, `docker-bake.hcl`,
`justfile`, `scripts/committed_versions.py`, `docs/operational.md` (headings only).

**Method note.** Claims of the form "the guard fires" were not taken on trust. The repository was
copied to a disposable root, a realistic `dev.yaml` was added (green against all 33 tests),
`RELEASE_FINALIZER_JOBS` was populated with `("dev.yaml", "finalize")` to simulate story 003's
grant, and violations were planted one at a time. Fourteen probes are cited by result below.
**No file in the repository was modified by this review** other than this report.

---

## Verdict table — F1–F20, F25

| # | Prior severity | Verdict | Evidence |
|---|---|---|---|
| F1 | BLOCKER | **resolved** | ADR-0009 (whole); `SHA_PINNED_ACTIONS` `tests/ci/test_workflow_contracts.py:109`; branch `…:238-247`; reach guard `…:251-269`; spine CI-AR4 amended `ARCHITECTURE-SPINE.md:61-68`. Probe: `pypa/gh-action-pypi-publish@release/v1` → red (tier one); unregistered `pypa/some-new-pypi-publish@v3` → red (reach). Both fire. |
| F2 | BLOCKER | **resolved** | `…:272-295`, scope derived from `WORKFLOWS.glob("*.yaml")`, with `assert verifier_callers` closing the vacuity hole. Probe: `secrets: inherit` on the verify job → red. |
| F3 | BLOCKER | **resolved** | ADR-0010 (whole); story `E008-S01-003.md:17-19,37-40`; `RELEASE_ACTION_VERB` `…:74` matches `git-action-release`, so the action is also gated by the finalizer registry. Caveat raised separately as **N6**: the guard forbids *hand-rolled* Release creation but never asserts *which* action is used. |
| F4 | MAJOR | **partially resolved** | AC is now explicit and correct — `E008-S01-003.md:42-53` names the Git tag set as the sole ordering authority and states that the action moves unconditionally. Guard `…:562-596` exists. But it examines only jobs that *use the alias action*. Probe P10: a `skopeo inspect` that computes the alias decision in the **plan** job → green. See **N7**. |
| F5 | MAJOR | **partially resolved** | ADR-0006:185-235 draws the identity/artifacts line correctly and is the strongest single piece of this remediation. The guard does not implement it. Probe P2: `git push -f origin refs/tags/v1` in the registered finalizer → **green**. Probe P3: `git push origin :refs/tags/v1 && git push origin v1` → **green**. `FORCED_REF_WRITE` `…:697-699` is spelling-bound, and no guard restricts the *target* ref. See **N2**. |
| F6 | MAJOR | **resolved** | `RELEASE_FINALIZER_JOBS: frozenset[tuple[str, str]]` `…:69`; consumed as pairs at `…:626,642,732`. Probe: a `finalize` job in `release.yaml` while only `("dev.yaml","finalize")` is registered → red on three tests. Widened while the set is still empty, which was the right moment. |
| F7 | MAJOR | **partially resolved** | ADR-0011 is a complete and correct answer; spine CI-AR40 `ARCHITECTURE-SPINE.md:180-188` and the two mandatory anchors `E008-S01-003.md:26-31` follow it. The guards do not enforce the mechanism, only prohibit one alternative to it. Probe P9: finalizer with **no `if:` at all** → green (`…:520-538` fires only when `always()` is present). Probe N3b: step-level `if: ${{ always() }}` → green. Probe P8b: a publisher re-reading `PUBLISH_*` behind an `enabled-destinations` output → green (`…:552`). See **N3**, **N8**. |
| F8 | MAJOR | **resolved** | `E008-S01-001.md:116-133` names all three shared surfaces (`forge-coordinates`, `verified-bundle`, reusable `publish-image.yaml`), gives them one owner, and `release.yaml` is stated to consume rather than restate them. Files in scope `…:169-172` match. Design-level finding, design-level fix; correct. |
| F9 | MAJOR | **resolved** | `E008-S01-001.md:135-147` moves both validators to `scripts/` with pytest cases and names `urllib.parse` and `git rev-parse`/`merge-base --is-ancestor`. Files in scope `…:173-175`. This is the global rule §1 answer, and it is the right one. |
| F10 | MAJOR | **resolved** | `…:470-488`, derived from disk, covering `env` and `defaults`. Probe: workflow-level `env: DOCKERHUB_TOKEN: ${{ secrets.… }}` → red. |
| F11 | MAJOR | **resolved** | `…:875-900` now iterates `GOVERNED_DEFINITIONS` and asserts `examined`. Probe: `actions/download-artifact@v7` in `dev.yaml` (a scope attack, not a rule attack) → red. |
| F12 | MAJOR | **partially resolved** | Re-keyed off the job name `plan` (`…:381-386`), and `E008-S01-001.md:176-180` carries both files plus the exact-equality warning. But it is now keyed on the **output name**, which is as renameable as the job name was. Probe P7: a version job emitting `dev-version`, deriving the version with `tomllib`, and feeding the verifier's `package-version` input → **green**. The docstring at `…:378-379` claims it is "keyed on what the job DOES, not what it is called"; that claim is not true. See **N4**. |
| F13 | MAJOR | **resolved, and well** | Spike executed 2026-09-02; `E008-S01-001.md:40-90` and ADR-0008's answered open question carry the numbers (50 s vs 436 s, the two QEMU steps, the 12–15 min budget) and the *reason* the contract holds under emulation. The attestation trap is documented in three directions with the correct filtered-set assertion and the nesting-level warning. Exemplary. |
| F14 | MAJOR | **resolved** | `E008-S01-001.md:149-165` mandates pull-by-digest and a re-run smoke test before any alias moves, and — better — states the limit plainly (only the native descriptor executes; the other platform rests on provenance, and the runbook must say so). Note this AC is one of the things **N1** currently makes unbuildable. |
| F15 | MAJOR | **resolved** (capability half) | `_is_credential_bearing` `…:173-186` derives from permissions and `secrets.*`; consumed at `…:450-459`. Probe: a `packages: write` publisher outside the verifier's transitive `needs` → red. The remaining gap is the *trigger* scope, which is new — see **N5**. |
| F16 | MAJOR | **not resolved** | The accepted tag race has no record: `grep -rn "race"` over the spine, all ADRs and all six stories returns nothing on this subject. The spine's Trigger and Coordinate Guards (`ARCHITECTURE-SPINE.md:245-255`) still states only "suppresses publication when the source commit has an exact stable tag" with no re-fetch obligation, and `E008-S01-001.md:17-19` is unchanged. Neither half of the remediation (re-record the acceptance; re-fetch tags immediately before the first credentialed dev step) was done. |
| F17 | MAJOR | **partially resolved — and it over-fires** | The guard exists (`…:491-517`) and does fire on the intended violation. It also fires on the *mandated* published-index inspection, which is **N1** (BLOCKER). Separately, the AC it was meant to disambiguate is unchanged: `E008-S01-004.md:26-30` still says "a remote immutable identity conflicts" without naming the destination action's own failure as the detector. |
| F18 | MAJOR | **not resolved** | `E009-S01-001.md:45-48` smoke list is unchanged: "checkout/action resolution, artifacts, Poetry, QEMU/Buildx, downstream CA, cleanup, wrong-CA failure, missing-scope failure". Neither **nested reusable workflows** (`uses: ./.github/workflows/…` at job level under `workflow_call`) nor **downloading in a caller job an artifact uploaded inside the called workflow** is named, and neither is in the pinned-tuple record (`…:41`). F8's reusable `publish-image.yaml` makes this *more* load-bearing than when the finding was written, not less. |
| F19 | MAJOR | **not resolved** | `E009-S01-001.md` DoD `:39-47` still separates bootstrap from job trust correctly but never states the consequence — that the secret-free verifier can receive no job-level CA, so forge clone, action download, PyPI and `ghcr.io` must all be covered by bootstrap trust. No endpoint enumeration, and no negative case for "bootstrap covers the forge but not the package index". |
| F20 | MAJOR | **not resolved** | `E009-S01-002.md:36-39` Files in scope is still exactly two markdown documents, while `:55-57` still declares a mechanical gate that "derives its required cases from the declared negative-case set and demands a run URL and conclusion for each; plant a removed case". There is no home for that gate. Per global rule §3 this is prose overstating its own coverage, which is the failure mode that rule exists for. |
| F25 | MINOR | **partially resolved** | `docker/Dockerfile` is fixed on both counts: `ARG BASE_IMAGE=…@sha256:…` default restored (`docker/Dockerfile:8`) and `DOCKER_PLATFORMS` is gone from the runtime `ENV` (`:110-116`). The other two stale statements remain: `.github/workflows/ci.yaml:47-49` still credits "build.yaml's plan job" (deleted in E007), and `scripts/committed_versions.py:93` still names release-please as a version owner — a mechanism ADR-0006 deleted and `…:738-742` forbids by test. See **N13**. |

**Tally:** 11 resolved · 5 partially resolved · 4 not resolved · 0 regressed. Of the three prior
BLOCKERs, all three are closed.

---

## New findings

| # | Severity | Principle | Location | Finding | Remediation |
|---|----------|-----------|----------|---------|-------------|
| N1 | **BLOCKER** | Core §3 (a contract that contradicts itself); global rule §4 (a guard whose scope exceeds its rule) | `tests/ci/test_workflow_contracts.py:491-517` vs spine CI-AR16/CI-AR18/CI-AR39/CI-AR41, `docs/adr/0008-exact-wheel-image-provenance.md` (answered open question, code block), `E008-S01-001.md:30-34,54-74,149-165`, `E008-S01-002.md:34-37` | The F17 guard forbids `buildx imagetools inspect` and `docker manifest inspect` **anywhere in a credential-bearing job**, despite being named "…before uploading". Every artifact in this epic requires exactly that command *after* uploading: CI-AR39 "exports the published digest and inspected platforms", CI-AR18 "inspects both published descriptors before finalization", and ADR-0008 prints the assertion to write and states its source is `imagetools inspect --raw <ref>`. Probes P5 and P6: the story's own inspection step in the image job → suite red. `E008-S01-001` cannot go green against the shipped contract test. This is structurally identical to the original F1. | Scope the guard to what its name says. Two workable forms: (a) split the job's steps at the first push/upload step and apply the probe patterns only to steps before it; or (b) keep the whole-job ban for the *pre-upload* probes that have no post-upload use (`pip index versions`, `curl …/pypi/…/json`) and drop `imagetools inspect`/`manifest inspect` from that list, replacing them with a narrower rule: a registry read may not appear in a step that runs **before** the job's push step. Form (b) is smaller and testable. Either way, plant both violations: a pre-upload existence probe (must fail) **and** the post-push platform inspection (must pass) — the second is the case that is currently wrong. |
| N2 | MAJOR | Global rule §3/§4; ADR-0006:219-232 | `tests/ci/test_workflow_contracts.py:697-699,702-721` vs `docs/adr/0006-release-version-transaction.md:191-196,219-232` | `FORCED_REF_WRITE` matches `--force`, `+refs/` and `force[:=]true`. It does not match `git push -f`, nor `git push origin :refs/tags/v1` followed by a recreate — the two spellings ADR-0006 explicitly names as "the same operation with different syntax". Probes P2 and P3, planted **inside the registered finalizer**, both leave the suite green. The ADR's planted violation used `--force-with-lease`, i.e. it attacked the rule and not the scope. Second half: nothing anywhere restricts the *target*. The ADR's table says `refs/tags/vX.Y.Z` is force-written "**never**, under any spelling"; probe P2 force-writes exactly that ref from the finalizer with all 33 tests green. | Two changes. (1) Widen the pattern to any non-fast-forward spelling — add `git\s+push[^\n]*(?:\s-f\b|--delete\b)`, `git\s+push[^\n]*\s:refs/`, `git\s+tag\s+-f\b`. (2) Add the target rule the ADR promises: in a **registered finalizer**, a ref-writing step may name only `refs/tags/v\d+(\.\d+)?$`; any `run:` mentioning `refs/tags/v\d+\.\d+\.\d+` in a write position fails. Plant `git push -f`, delete-and-recreate, and a force onto `v1.2.3` — the current plant proves nothing about any of them. |
| N3 | MAJOR | Global rule §3 (rule enforced by memory); Core §3 | `tests/ci/test_workflow_contracts.py:520-538` vs `docs/adr/0011-…:68-80`, spine CI-AR40, `E008-S01-003.md:26-31` | ADR-0011's mechanism is *positive*: the finalizer `needs:` every publisher, runs under `if: ${{ !cancelled() }}`, and compares `needs.<job>.result` to the enabled set. The only guard is *negative* — it forbids `always()`. Probe P9: a finalizer with **no `if:` at all** → green. That is the exact F7 failure mode ADR-0011 describes ("green run, aliases unmoved, no alert"), and it is the default a first implementation reaches for. Probe N3b: step-level `if: ${{ always() }}` → green, because the guard reads job-level `if:` only. | For every `(workflow, job)` in `RELEASE_FINALIZER_JOBS`, assert: `!cancelled()` appears in the job's `if:`; `always()` appears in neither the job's nor any step's `if:`; and the job's `needs` is a superset of every credential-bearing job in the same file (derived, per `_is_credential_bearing`, not enumerated). The registry is already the right anchor — this is the guard that makes the grant mean something. Plant: a finalizer without `!cancelled()`, one missing a publisher from `needs`, and a step-level `always()`. |
| N4 | MAJOR | Global rule §4 (derive scope from the source of truth) | `tests/ci/test_workflow_contracts.py:373-407`, docstring `:378-379` | F12 moved the key from the job name `plan` to the output name `package-version`. Both are names. Probe P7: a job emitting `dev-version`, deriving the version with an inline `tomllib` read, and passing it into the verifier's `package-version:` input → **green**. The version authority is one rename from ungoverned, and the docstring asserts the opposite ("keyed on what the job DOES"). | Derive the scope from the **consumer**, which is the actual source of truth: for every job whose `uses:` is the verifier, parse its `with.package-version` expression, resolve the `needs.<job>.outputs.<name>` it references, and govern that job whatever its output is called. Keep the `package-version` output rule as an additional, not the only, entry point. Plant the rename — the current plant does not attack the scope. |
| N5 | MAJOR | Core §4; spine CI-AR18 (unconditional) | `tests/ci/test_workflow_contracts.py:438-443` | `test_any_push_triggered_workflow_verifies_before_it_ships` filters to workflows with `push` in `on:` and `continue`s otherwise. Probe P11: a `release.yaml` on `on: release: [published]` with a `packages: write` publisher and **no verifier job at all** → green. CI-AR18 ("verify before publishing") carries no trigger qualifier, and the test's name promises less than the rule requires but more than it delivers, because the reader sees "any … workflow". A tag-triggered `release.yaml` happens to be a `push` event, so today's plan is safe — but the guard is what protects the plan from changing. | Widen to every workflow that has any credential-bearing job, regardless of trigger; keep the `continue` only for `workflow_call` files, which are verified by their caller. Plant a publisher on `workflow_dispatch` and one on `release:`. Rename the test to match its widened reach. E008-S01-004's anchor already says "every credential-bearing job", so this only pulls the guard forward to where F15 put the rest of it. |
| N6 | MAJOR | Global rule §3; ADR-0010 "Enforcement" | `tests/ci/test_workflow_contracts.py:114,658-686` | `APPROVED_RELEASE_ACTION` is defined and then used only inside an error message. Nothing asserts that the Release is created **by that action**. Probe N6: `actions/create-release@v1` inside the registered finalizer → green — approved owner, floating major, registered job, hand-rolling patterns not matched. ADR-0010 claims "a contract test asserts that Release creation happens only through the approved action"; the shipped test asserts only that it is not created by `curl`/`gh`. The whole point of ADR-0010 is that the *Gitea* path comes free from this one action; any other release action silently loses E009. | In the same loop, assert positively: any step whose action name matches `RELEASE_ACTION_VERB` and is not the alias action must equal `APPROVED_RELEASE_ACTION`. Plant `actions/create-release@v1` and `softprops/action-gh-release@v3` (the second is already caught by the owner allowlist; the first is not). |
| N7 | MAJOR | Global rule §4; retirement spec "Never … remote identity reconciliation" | `tests/ci/test_workflow_contracts.py:581-596` | The alias-ordering guard examines only jobs that contain a step using the alias action. Probe P10: the ordering decision computed in the **plan** job from `skopeo inspect docker://…:latest`, consumed by the alias job as a `needs` output → green. Story 003's own anchor says "plant a step that reads a registry tag to decide an alias"; the shipped guard only sees that plant if it lands in the alias job, which is not where a real implementation would put it — a plan job is the natural home for a decision every alias step consumes. | Forbid the registry-read patterns in **every** job of a workflow that moves aliases, not only in the alias job; or, better, in every job that is in the alias job's transitive `needs` (the machinery already exists at `…:189-202`). Plant the read in the plan job, which is the version that currently passes. |
| N8 | MINOR | Global rule §4 | `tests/ci/test_workflow_contracts.py:548-559` | The single-producer exemption is "any job declaring `enabled-destinations` **or** `package-version` as an output". Probe P8b: a publisher that declares `enabled-destinations` itself and reads `PUBLISH_IMAGE_DOCKERHUB` from `vars` → green. Separately, the toggle pattern `PUBLISH_[A-Z_]+` hand-enumerates a naming convention: `DOCKERHUB_ENABLED` or a lowercase suffix escapes it, and the convention is documented in the spine's variable table (`ARCHITECTURE-SPINE.md:209-215`), which is the derivable source of truth. | Exempt exactly one job per workflow — the one the finalizer reads the set from — rather than any job carrying the output name. Derive the toggle names from the spine's Repository variables table, or from a single constant that the table and the guard both cite. |
| N9 | MINOR | Core §6 (comments describe the current state) | `docs/adr/0006-release-version-transaction.md:112,124-127` | The enforcement prose still describes `RELEASE_FINALIZER_JOBS` in the pre-F6 shape: "unless its **job name** is registered", "adding a **name** to it *is* the grant", "empty until Epic 8 registers the stable-release finalizer". The registry is now `(workflow, job)` pairs — correctly stated in ADR-0010:93-95 and in the test's own comment, but not here, and ADR-0006 is the ADR the registry belongs to. | Update those three sentences to say `(workflow filename, job name)` pair. One-line change; the ADR is otherwise the strongest artifact in the set. |
| N10 | MINOR | Core §10 (docs contradicting the plan) | `docs/adr/0009-action-pin-policy.md:96` | "When `release.yaml` lands (E008-S01-003), record the reviewed SHA" — `release.yaml` lands in **E008-S01-002** (`E008-S01-002.md:65`); story 003 only edits it. The PyPI publisher and its SHA arrive with 002. A reader following the ADR records the SHA one story late. | Correct to `E008-S01-002`. |
| N11 | MINOR | Core §10 (docs contradicting the code) — F26 carried, now differently wrong | spine CI-AR7 `ARCHITECTURE-SPINE.md:76-77` vs `justfile:4,10,17,21,25,28,32,36,40,44,51` | CI-AR7 now claims the justfile exposes `setup`, `lint`, `test`, `test-local`, `package`, `image`, `build`, `verify`, `release PART`. Three of those do not exist: `setup` (it is `install`), `package` (there is none; `build` produces distributions), `verify` (it is `check`). Two that do exist are unlisted: `fix`, `release-resume`. The requirement was edited between gate passes and is still wrong, which is worse than stale — it now reads as freshly checked. | Either correct it to the shipped recipe names, or replace the enumeration with a pointer to the justfile and a guard asserting the recipes a workflow or document actually invokes exist. The second is the global-rule-§3 answer; the first is one line. |
| N12 | MINOR | Core §5 (readability) | `tests/ci/test_workflow_contracts.py:585` uses `APPROVED_ALIAS_ACTION`, defined at `:694` | Correct at run time, confusing on first read: the alias-ordering test reads a constant defined 109 lines below it, between two unrelated tests. The file's other registries are all defined in the header block. | Move `APPROVED_ALIAS_ACTION` and `FORCED_REF_WRITE` up beside `APPROVED_RELEASE_ACTION` at `:111-115`. |
| N13 | MINOR | Core §6 — F25 residue | `.github/workflows/ci.yaml:47-49`; `scripts/committed_versions.py:93` | Two of F25's three stale statements survive. `ci.yaml` says the version authority is "shared with build.yaml's plan job"; `build.yaml` was deleted in E007. `committed_versions.py` says the number "is owned by `scripts/release_version.py` and release-please"; ADR-0006 deleted release-please as a competing authority and `…:738-742` fails any workflow that mentions it. The second is the dangerous one: a stale comment naming a forbidden mechanism as an owner is how it gets reintroduced. | Fix both in `E008-S01-001`, which already owns that neighbourhood and already lists `committed_versions.py` in Files in scope. |

---

## Per-principle walkthrough

**Core §1 — Separation of concerns.** Improved. The forge Release now has a home that is not a
forge branch (ADR-0010), and the F25 runtime `ENV` leak is gone. The shared surface named in
`E008-S01-001.md:116-133` draws the adapter/verifier/publisher boundary explicitly rather than
leaving it to emerge. No new leak found. PASS.

**Core §2 — Reuse over copy-paste.** F8 resolved at the level a pre-implementation gate can
resolve it: three named surfaces, one owner, and `release.yaml` stated to consume them. The
remaining risk is entirely execution-time and is correctly assigned. PASS.

**Core §3 — Design by contract.** The undeclared contracts from the first pass are now declared:
the enabled/required/skipped relation (ADR-0011), alias ordering (`E008-S01-003.md:42-53`), the
conflict detector (guard `…:491-517`), the revalidation mechanism (`verified-bundle`), the forge
index (the destination matrix, twice, plus CI-AR21). What is now wrong is a contract that
contradicts itself: **N1**. Also **N3** — a declared precondition with no assertion.

**Core §4 — Testability.** This is where the pass succeeds and fails at once. Nine guards were
verified to fire against a planted violation. Five documented rules do not: N1 (fires on the
wrong thing), N2, N3, N4, N5, N7. The pattern is unchanged from the first report and is worth
naming plainly: **each new guard was tested by planting the violation the author had in mind, and
each still passes the violation an implementer would actually write.** Global rule §4 asks for a
plant that attacks the *scope*; four of the five escapes above are scope attacks that take under
a minute to construct.

**Core §5 — Brevity without sacrificing readability.** PASS with N12. The test file's comments
are unusually good — several explain why a narrower rule was chosen over a blanket one
(`…:392-400` on `poetry version`, `…:855-858` on the `ACT` token) and would survive a reader who
disagreed with them.

**Core §6 — Comments describe current state.** N9, N11, N13. Also F16: an accepted risk whose
record is still deleted, which is the most consequential of these because the next reader meets a
knowingly-accepted immutable publication as a bug.

**Core §7 — Dependency selection.** PASS. `LiquidLogicLabs/git-action-release@v2` is
maintainer-owned, verified as a real Gitea implementation rather than a stub, with `v2.0` called
out as stale and a named fallback. ADR-0010 states its own accepted cost (an unbuildable 1.4 MB
bundled `dist/index.js`) rather than omitting it. F27's credential-topology trade-off is still
unweighed; it remains MINOR and deferred.

**Core §8 — GA over alpha/beta.** PASS. No preview dependency is load-bearing. The
`upload-artifact@v4` exception is ADR-grade, Dependabot-protected (`…:903-927`), and its scope
gap (F11) is closed.

**Core §9 — Unified correlated logging.** Unchanged from the first pass. CI-AR41's run-native
evidence remains the right call; the reverse join from a published digest back to its run (F30)
is still undocumented, still MINOR. No secret-in-log risk found; N1's guard, once corrected,
should not weaken the `no leaked values` anchor in `E009-S01-001.md:61`.

**Core §10 — Documentation.** Substantially improved: three new ADRs, two amended, all
cross-referenced from the stories and from the test file's comments, which is the pattern that
makes an ADR set live rather than archival. Gaps: still no flow diagram of the publication job
graph (F24, MINOR — and the graph got *more* complex this pass, with a reusable
`publish-image.yaml` added), CI-AR7 wrong (N11), lost decision provenance (F21).

**GH Actions overlay — marketplace over custom scripting.** PASS. F9 moved the two hand-rolled
validators into Python with tests; ADR-0010 rejects hand-writing a forge API client with the
correct reasoning and names the concrete incompatibilities that make it expensive.

**GH Actions overlay — pinning.** F1 resolved with a real distinction (per action, not per
owner) rather than by discarding one side. F11 resolved. N6 is the pinning-adjacent gap: the pin
policy is enforced, the *identity* of the release action is not.

**GH Actions overlay — hygiene.** Least privilege: the two-guard permissions/behaviour pair is
right and F6 made the registry precise, but N2 and N3 mean the grant currently buys less than the
ADR says. Secrets: F2 and F10 both closed and both verified. Concurrency: `dev.yaml` owned
(`E008-S01-001.md:188`), `release.yaml` still unowned (F22, MINOR).

**Python overlay.** PASS, unchanged. Poetry single manager, lock committed, `requires-python`
bounded, one interpreter authority. `dockerfile-parse` is a maintained library doing the job a
hand-rolled scanner would have done badly — `…:952-989` is a good example of global rule §1
applied without being asked.

**Docker overlay (stub — provisional).** F13 and F25 resolved; F14 resolved in the story and
currently blocked by N1. The `ARG BASE_IMAGE` default and its reach guard (`…:945-995`) are the
strongest thing in this area: the guard proves the *config can do something*, not merely that the
config entry exists.

**Shell overlay (stub — provisional).** PASS. F9 removed the case where shell had outgrown
itself.

---

## Answers to the questions asked

**1. Do the guards actually fire, and are the scopes right?** Nine do; five do not, and the three
you asked me to look hardest at split two ways. **F11's widened scope is correct** — it iterates
`GOVERNED_DEFINITIONS`, asserts `examined`, and the `download-artifact@v7`-in-`dev.yaml` scope
attack goes red. **F15's capability derivation is correct** for what it derives — permissions plus
any `secrets.*` anywhere in the job — and the planted publisher-outside-`needs` goes red; its gap
is the trigger filter above it (N5), not the derivation. **F12's `package-version` keying is not
right**: it replaced one name with another name, and a job emitting `dev-version` while
re-deriving the version inline passes a green suite (N4). Beyond the three: F5's forced-write
guard and F7's finalizer guard are the two that matter most and the two that hold least (N2, N3).

**2. Is F7's `!cancelled()` + `needs.<job>.result` sufficient, and does it stay inside CI-AR37 and
CI-AR41?** The *design* is sufficient and stays inside both, and I checked this specifically.
`needs.<job>.result` is a workflow-native expression, not "a repository-specific all-destination
protocol" (CI-AR37) — no artifact is written, no schema exists, nothing is exchanged between
destinations. The enabled set is a job output, which is exactly what CI-AR41 permits and what
CI-AR22 (a committed `publication-plan-v1.json`) and CI-AR23 (a pre-publication aggregate
barrier) were. It revives neither: this evaluation happens *after* the fan-out, not before it, and
it produces no persisted object. ADR-0011's rejection of the 2ⁿ-finalizer alternative is also
correct — `needs:` is structural and takes no expression. **What is not sufficient is the
enforcement**: nothing requires the finalizer to be written this way (N3), and a finalizer with no
`if:` — the shape a first implementation reaches for — passes today and produces exactly the
silent non-finalization ADR-0011 exists to prevent.

**3. F5 — is the identity/artifacts line drawn correctly, and is `refs/tags/vX.Y.Z` unreachable?**
The line is drawn correctly, and the reasoning at ADR-0006:198-206 is right: an alias points at an
identity rather than choosing one, so forcing it cannot corrupt an identity, which is the harm §5
exists to prevent. Narrowing §5 to the release transaction's own atomic push is the honest reading
and is stated as such rather than quietly assumed. **`refs/tags/vX.Y.Z` is not unreachable.** It
is unreachable *through the approved action*, which derives aliases from the exact tag and never
targets it. It is fully reachable by hand from the registered finalizer: probe P2 force-writes
`refs/tags/v1` and probe P4 confirms the guard fires only on the `--force` spelling, never on the
target. The ADR's bolded "forbidden outright … under any spelling" and its table's "**never**,
under any spelling" are both currently false as mechanical statements (N2). This is the finding I
would fix first after N1, because the ADR reads as though it were already enforced.

**4. F4 — is the AC sufficient to stop a re-released older patch dragging `vMAJOR` backwards?**
The AC is sufficient *as a written obligation*: `E008-S01-003.md:47-53` states plainly that the
action moves unconditionally, that the gate is therefore the workflow's, and that the ordering
comes from the tag set; it plants the right violation ("a re-release of an older patch with a
newer stable tag present — the alias must not move"). Two caveats. The shipped guard implements
only the *negative* half (no registry read) and only inside the alias job, so the decision can be
sourced from a registry one job upstream with the suite green (N7). And nothing asserts the
*positive* half at all — that the alias step carries a gating `if:` derived from the tag set. With
the action moving unconditionally, an alias step with no `if:` is the backwards move, and no test
sees it. I would fold that assertion into the N3 finalizer guard: a step using
`APPROVED_ALIAS_ACTION` must carry a non-empty `if:`.

**5. Anything new?** Seven findings that did not exist before: N1 (the mandated inspection is
forbidden), N3, N5, N6, N7 above, plus N8 and N12. N1 and N6 both arise from the same cause — the
remediation added rules faster than it added reach, and two of the new rules now bound the design
in a direction nobody checked. N1 is the one that stops work.

---

## Gate

**CHANGES REQUIRED.** The gate does not pass.

- **BLOCKER (1): N1.** `E008-S01-001` and `E008-S01-002` cannot go green against the shipped
  contract tests as written, because the platform inspection their ACs, CI-AR16/18/39/41 and
  ADR-0008 all require is rejected by `test_no_publisher_queries_a_destination_before_uploading`.
  This must be settled before `dev.yaml` is written; it is roughly fifteen lines of test plus one
  plant, and it is the same failure the first pass opened with.
- **MAJOR (10):** N2, N3, N4, N5, N6, N7 (new), plus F16, F18, F19, F20 (carried, not resolved).
  N2 and N3 are the two whose absence is most consequential, because ADR-0006 and ADR-0011 both
  read as though they were already enforced. F16 and F20 are both instances of global rule §3 —
  a decision with no record, and a mechanical check with no implementation. F18 and F19 belong to
  E009 and can be resolved before that epic starts, but F18 got *more* load-bearing this pass:
  F8's reusable `publish-image.yaml` adds a second nested-workflow dependency to a capability
  nobody has yet confirmed Gitea's act-runner has.
- **MINOR (6):** N8, N9, N10, N11, N12, N13 — defer to backlog, except N13's
  `committed_versions.py:93` release-please line, which names a forbidden mechanism as an owner
  and is one line in a file `E008-S01-001` already owns.
- **Carried MINORs from the first pass that remain open:** F21, F22, F23, F24, F27, F30. All
  still defer. F24 (a flow diagram of the publication graph) is worth more now than when it was
  raised — the graph gained a reusable workflow this pass.

**Assumption recorded, since no decision could be requested:** I have treated the four E009
findings (F18, F19, F20) and F16 as *unresolved rather than intentionally deferred*, because
nothing in the stories, ADRs or spine records a decision to defer them, and the dispatch preamble
lists them among the twenty claimed resolved. If the intent was to defer them to the E009 gate,
that is a defensible call — but it is a decision, and per global rule §3 it needs a record, not a
silence.

## Recommended ADRs and records

1. **None new is strictly required.** The five ADRs recommended by the first pass are now written
   or amended (0009, 0010, 0011, 0006 ×2, 0008), and F27's credential-topology ADR remains the
   only outstanding MINOR recommendation.
2. **Records, not ADRs, are what is missing:** the accepted dev/stable tag race (F16) needs a home
   in the spine or ADR-0006; the E009 pinned tuple needs nested reusable workflows and
   cross-workflow artifacts added (F18); the verifier's endpoint set needs enumerating against
   bootstrap trust (F19); and `E009-S01-002` needs either a file that can hold its gate or the
   removal of the mechanical language (F20).
3. **Three one-line corrections:** ADR-0006's registry prose (N9), ADR-0009's story reference
   (N10), spine CI-AR7 (N11).

DONE — Blocker: 1, Major: 10, Minor: 6
