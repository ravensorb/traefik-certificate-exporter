# Epic 008 — Closure Report

**Epic:** E008 — Action-Based Multi-Channel Delivery
**Goal:** Publish verified development and stable artifacts through normal destination actions, then
advance aliases only after required jobs succeed.
**Final status:** done — 1 sprint, 4/4 stories, carry-over 0.
**Closed:** 2026-09-03

## Estimate vs actual

| Metric | Estimate | Actual | Ratio |
|---|---|---|---|
| man_hours | 74.6 – 77.4 | **210** | 2.7 – 2.8× |
| elapsed_hours | 2.87 – 2.97 | **12.75** (+2.0 orchestration) | 4.3 – 4.4× |
| hitl_hours | 0.17 – 0.18 | **0.45** | 2.5 – 2.6× |
| tokens_k | 1,585 – 1,801 | N/A | — |
| cost | $6.54 – $7.43 | N/A | — |

Tokens and cost are N/A for every node in this epic: all four stories recorded `--tokens-na`, and the
closure phases were recorded the same way for consistency rather than mixing an observed sprint total
with unobserved story components.

**Two disclosures the metrics contract requires.**

1. **Anchoring.** `man_hours` was bound at 150 before the sprint estimate was read, and at 195 before
   the epic estimate was read — both correctly ordered. The increments beyond those (to 185, then
   210) were assessed *after* the corresponding estimate was known, because remediation continued
   past the point of binding. Anchoring cannot be ruled out for those increments; it can be for the
   150 and the 195.
2. **A calibration sample was taken from a figure later corrected.** The epic's `elapsed_hours` was
   first written as 15.9 and then corrected to 12.75 after measuring the closure window from the
   commit record (02:00 → 02:45 = 0.75h) rather than estimating it. The correction landed on disk;
   the calibration sample did not, because the replay marker was already stamped — `set-actual`
   reported `skipped (replay)`. **E008 therefore contributes a closure-elapsed calibration sample
   computed from a number that is 25% too high.** Future estimates drawing on that band will be
   biased upward by it. Measure the window before writing the actual, not after.

**On the ratio.** 2.7× on man-hours is not an estimating error of the ordinary kind. The estimate
covered the four stories' scope and it was roughly right about them. What it did not anticipate is
that **closure would cost more than implementation**: the review phases and the fix passes they
triggered account for roughly half the epic's man-hours (100 of 210, in the `closure` attribution
band). That is worth carrying into E009's estimate rather than treating as an overrun.

## Sprint velocity

| Sprint | Stories | Status | Carry-over |
|---|---|---|---|
| S01 | 4/4 | done | 0 |

## What shipped

Five workflow files (two reusable), three composite actions, twelve jobs, three registered
finalizers, two disjoint credential classes, and the retirement of the entire legacy publish path
(`build.yaml`, `build-package.yaml`, `build-container.yaml`, the old `release.yaml`, `build.sh`,
`docker/build.sh`, and three Python modules with their tests). The contract suite went from 34
guards to **294**.

## Review findings

| Phase | Result |
|---|---|
| Sprint retrospective | accepted-with-open-items, carry_over 0 |
| Sprint red team | 0 CRITICAL, 3 HIGH, 6 MEDIUM, 3 LOW |
| Sprint arch drift | 1 BLOCKER, 6 MAJOR, 8 MINOR |
| Sprint clean-release + adversarial | 1 CRITICAL, 6 HIGH, 5 MEDIUM, 5 LOW |
| **Epic red team** | 0 CRITICAL, 3 HIGH, 4 MEDIUM, 2 LOW, 2 OBSERVATION |
| **Epic arch drift** | 0 BLOCKER, 6 MAJOR, 6 MINOR |

**Every BLOCKER, CRITICAL, HIGH and MAJOR is fixed.** Roughly 70 findings across six phases, closed
in 31 commits.

The epic-level phases were pointed deliberately at the sprint remediation (`df6e5ed..HEAD`) — 20
commits that no reviewer had seen, written in response to the reports they were now being asked to
check. That was the right call: **all three epic HIGHs and the top two MAJORs were defects in that
remediation**, including one on a security control.

### The four that mattered most

- **The attestation added to fix "the Release evidence is unsigned" was unreachable by default.** It
  sat inside `publish-package-pypi`, a job gated on `PUBLISH_PACKAGE_PYPI` — default `false`. So the
  shipped default configuration attested nothing, which is exactly the state the finding raised. The
  guard proved the step existed, was ordered before the upload, held the right scope and was
  capability-gated; it never asked whether the step *runs*. Setting the job to `if: false` left the
  suite green. Now its own job, gated on host capability alone, modelled as a destination so the
  finalizer gate treats a skip on Gitea and a skip on GitHub differently.
- **The alias concurrency group cancelled pending finalizers instead of queueing them.** Found
  independently by both reviewers and verified against GitHub's published semantics: the default is
  `queue: single` — "any existing pending job or workflow run in the same group is canceled and
  replaced" — and `cancel-in-progress` governs only the running member. Three overlapping tags
  deterministically cancelled a finalizer that had already published irreversibly, producing no
  Release, no aliases and no run summary. The ADR recorded the opposite as established. `queue: max`
  is the fix but `actionlint` rejects the key and Gitea's behaviour is unknown, so the groups were
  removed: ordering rests on re-deriving the tag set in the job that writes, which the red team
  confirmed it could not break.
- **The credential-reach derivation could not see an ambient credential.** An OIDC identity is not
  passed to a step — it is in every step's environment — so every action in a job holding
  `id-token: write` can mint one. The derivation recognised only what is handed over.
- **The publisher's alias refusal enumerated the stable channel's alias shapes** and therefore
  accepted `dev`, which is the development channel's alias. Replaced with an allowlist of the two
  immutable shapes.

### The pattern, stated plainly

Eleven instances of one defect class were found at sprint closure: **a correct rule over a
hand-enumerated set**. The epic review found four more — *inside the remediation written to close
the first eleven*, by the same author, who had written the rule and agreed with it. That is the
epic's single most durable finding, and it is why `guidelines.md §11` now records defect provenance
in comments as a deliberate convention: knowing a line is the fix for a specific escape is what
stops the next reader simplifying it back.

Two guards caught real regressions during closure itself: the widened citation check found a guard
**missing from the module entirely**, silently deleted by a text-region replacement while an ADR
still cited it as the enforcement; and the collected-test count falling by four exposed a second such
deletion. Both were region replacements, both were mine.

## ADRs produced

| ADR | Decision |
|---|---|
| 0006 | The guarded release-version transaction; identity vs. its artifacts (amended ×3) |
| 0007 | PR-verification topology: thin adapters, one secret-free verifier (amended) |
| 0008 | Exact-wheel provenance; the release evidence is signed (amended) |
| 0009 | Action pin policy: floating major by default, reviewed SHA for credential handlers (amended ×2) |
| 0010 | Forge Release creation through one multi-platform action |
| 0011 | Channel decides the destination set; how the finalizer reads a skipped job (amended ×2) |
| 0012 | The image metadata action, verified at the tag this repository pins (new) |

## Outstanding issues

13 items opened against E008; **3 resolved**, 10 open.

| Severity | Open | |
|---|---|---|
| Medium | 5 | BL-E008-005 (upstream command injection, not exploitable here), -006 (destination vocabulary hand-spelled), -007 (branch protection), -008 (the `pypi` environment), -010 (the 6,600-line contract module) |
| Low | 5 | BL-E008-002, -009, -011, -012, -013 |

**Two are settings outside this repository**, and the guards that depend on them say so rather than
implying coverage they do not have: branch protection requiring code-owner review (BL-E008-007), and
the `pypi` environment's reviewers plus the matching PyPI trusted-publisher claim (BL-E008-008).
Until the second is set, any workflow here that can obtain `id-token: write` can mint a PyPI-scoped
token.

## Follow-through: retrospective action item A1 is built

A1 — "add a meta-guard over the contract suite: assert each guard's scope is derived rather than a
module-level literal" — was rated the sprint's highest-value item and **deferred**. The epic arch
review then found four fresh instances of the class it proposed to detect and said so.

It is now `test_no_guard_takes_its_scope_from_a_hand_written_list_of_what_the_repo_contains`. It
parses this module's own source and flags any module-level literal collection that enumerates names
**the repository contains** — filenames, tracked paths, or a collection made entirely of job names.
Vocabulary is untouched: forbidden substrings, required platforms and command patterns are the rule
itself, not the set it runs over.

`SCOPE_REGISTRIES` is the escape hatch, in the shape this project already uses twice: an entry *is*
the decision, it carries its reason, an ADR must name it, and a stale entry fails. It holds one
entry — `RELEASE_FINALIZER_JOBS`, which records a grant rather than a fact about the tree, and which
must not be derived because deriving it from "jobs that write refs" would make every new writer
self-authorising.

**Validated against history rather than asserted.** Run over `tests/ci/test_workflow_contracts.py`
as it stood at each point:

| Commit | Verdict | |
|---|---|---|
| `6a76559` | **refused** | `SECRET_FREE_WORKFLOWS = ['ci.yaml', 'verify-build.yaml']` |
| `df6e5ed` | **refused** | the same, plus `INVOCATION_SCAN_EXEMPTIONS` |
| `HEAD` | clean | |

`SECRET_FREE_WORKFLOWS` is the tuple that carried the fork-safety prohibitions while sitting eight
lines below the filesystem derivation that had replaced its twin. Finding it took a reviewer
constructing a second `pull_request` workflow on a disjoint branch filter and confirming the suite
stayed green. The meta-guard refuses it at the moment it is written, and it would have refused it
mid-sprint — before the same shape was copied into three more places.

## Known limits, stated rather than implied

- **Gitea parity is asserted, not proven.** The finalizer authority split relies on `permissions:`
  denying unlisted scopes; Gitea does not document that reading and ships permissive. Every
  privileged job now declares its denials explicitly, which needs no inference from any runner — but
  `code:`/`releases:` cannot be spelled alongside GitHub's vocabulary in one file, so a deployment
  precondition remains for E009 (ADR-0006).
- **Python 3.10 runs for real for the first time on the next CI run.** The matrix had declared five
  versions and installed one. `tomllib` was the only 3.11+ construct found; anything else surfaces
  there.
- **The attestation is GitHub-only.** Gitea has no attestation store, so a release there is
  unattested and ADR-0008 says so.
