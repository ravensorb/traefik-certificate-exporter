# Architectural Review — Epic E008, Action-Based Multi-Channel Delivery

- **Mode:** B (architectural review — what was built vs what was planned)
- **Standards applied:** `l3io-arch-review` `standards-core.md` §1–10, `standards-github-actions.md`,
  `standards-python.md`; global engineering rules §1 (no hand-rolling), §3 (enforce mechanically),
  §4 (a guard proves its rule, not its reach).
- **Scope reviewed:** cumulative epic diff `dbc991c..82819bc` (40 commits, 25,147 lines), with effort
  weighted onto the 17 unreviewed remediation commits `df6e5ed..82819bc`.
- **Review baseline:** `82819bc`. Re-confirmed no code changed between `82819bc` and `fe8ee0c`
  (`git diff --stat 82819bc..HEAD -- .github scripts tests docs` is empty), so the findings hold at HEAD.
- **Method:** every claimed defect below was verified by planting the violation in a detached
  worktree at `82819bc` and running `poetry run pytest tests/ci/` (baseline: **285 passed in 8.2s**).
  Thirteen plants were executed. Where a finding could not be executed — GitHub Actions scheduling
  semantics — it is marked **UNVERIFIED** and the reasoning is given in full.
- **Already-known findings excluded:** the 57 findings catalogued in the four sprint-closure reports
  are not re-reported. Where remediation for one of them is incomplete, that is stated as a new
  finding against the remediation, not against the original.

---

## Executive summary

The remediation is, on the whole, good work: eleven of the eleven confirmed instances of the epic's
signature defect — a correct rule over a hand-enumerated set — were converted to derivations that
survive attack. Thirteen planted violations were run against the suite; eleven were caught, several by
four to eight independent guards. `_load_document`'s `deepcopy`-over-`functools.cache` is sound: it is
the sole caller of `_parsed_definition`, nothing writes to a governed definition on disk, and no cached
function returns a mutable derived from it.

Six MAJOR findings stand. The most important is that the epic's signature defect **recurred inside the
remediation that was written to close it**, on a security control: the build-provenance attestation
added by `e50f250` runs only inside `publish-package-pypi`, a job gated on an optional destination that
this repository's default configuration disables — so in the shipped default configuration nothing is
ever attested, and the guard that is supposed to prove otherwise passes with that job made permanently
unreachable (**verified: 285 passed with `if: ${{ false }}` on the attesting job**). The same shape
appears twice more: the explicit `none` permission denials cover only the three registered finalizers
while the Gitea-permissive premise they rest on applies to all eight privileged jobs, and the rule that
guard names cited in documentation must resolve is scoped to one section of one page — with a live
violation already sitting in ADR-0009's Enforcement section.

Counts: **BLOCKER 0 · MAJOR 6 · MINOR 6.**

---

## Findings table

| # | Severity | Principle | Location | Finding | Remediation |
|---|----------|-----------|----------|---------|-------------|
| 1 | MAJOR | Core §3 (contracts), §4 (testability); global §4 (reach) | `.github/workflows/release.yaml:484-596`; `tests/ci/test_workflow_contracts.py:4367-4418` | The only `actions/attest-build-provenance` step in the repository lives in `publish-package-pypi`, whose `if:` requires `package-pypi == 'enabled'`, i.e. `vars.PUBLISH_PACKAGE_PYPI == 'true'` (default `false`). In the default configuration a stable release creates a Release with `SHA256SUMS` + `build-manifest.json` attached under `allow-updates: true` and **attests nothing** — exactly the state redteam M5 raised. `test_the_released_distributions_are_attested_before_they_are_published` proves the step exists, is ordered before the upload, holds `attestations: write` and is capability-gated; it proves nothing about reachability. **Verified: setting the attesting job to `if: ${{ false }}` leaves the suite at 285 passed.** `finalize`, which creates the Release, declares `attestations: none` and therefore cannot attest at all. | Attest in a job that always runs for the stable channel — the natural home is `finalize`, before `git-action-release`, subject-checksummed from the same revalidated bundle — or, if attestation is deliberately PyPI-only, say so in ADR-0008 and stop describing it as signing "the release evidence". Add a reachability leg to the guard: the attesting job's `if:` must not be narrower than the channel itself. |
| 2 | MAJOR | Core §1 (separation), §4; CI-AR24; global §4 | `release.yaml:381,484,613`; `dev.yaml:307,409,505`; `publish-image.yaml:106`; guard at `tests/ci/test_workflow_contracts.py:4150-4185` | `test_every_finalizer_states_the_scopes_it_relies_on_being_denied` derives its job set from `RELEASE_FINALIZER_JOBS` — three jobs. Its own premise is that "Gitea ships `TokenPermissionMode` permissive by default, so omission grants rather than denies". That premise is a property of the *runner*, not of finalizers: `release.yaml:publish-package-forge` declares `{contents: read}` while holding `secrets.FORGE_PACKAGE_TOKEN`, and on a permissive Gitea would additionally hold `packages`, `id-token` and `attestations`. Five publishers plus the `publish-image.yaml:image` job (which declares no job-level `permissions` at all) are outside the rule. **Verified: Plant 2 added a credential-bearing publisher job to `dev.yaml` declaring only `contents: read`; eight guards fired and this one was not among them.** Secondary: `AUTHORITY_SCOPES` enumerates four of GitHub's ~15 scopes, so even the three covered jobs state denial for a quarter of the surface. | Derive the scope from capability, not from the finalizer registry — `_is_credential_bearing(job)` already exists and is the right seed. State the denials on every job that holds a credential or a write permission. If the four-scope subset is deliberate, say which scopes are out of scope and why, in the guard rather than only in ADR-0006. |
| 3 | MAJOR **(UNVERIFIED — cannot execute GitHub Actions scheduling)** | Core §3; CI-AR29, CI-AR40; ADR-0011 | `release.yaml:685-687` and `release.yaml:1006-1008`; guard at `tests/ci/test_workflow_contracts.py:4124-4152` | `finalize` and `finalize-image-aliases` share one job-level concurrency group, `${{ github.workflow }}-aliases`, and the second `needs:` the first. GitHub's documented rule for a queued job in an occupied group is: it becomes *pending*, and **"any previously pending job or workflow in the concurrency group will be canceled."** With two or more stable tags in flight the two stages of one run compete with the other run's stages for one slot: when run A's `finalize` completes and A's `finalize-image-aliases` enters the group as pending, run B's pending `finalize` is cancelled — B gets no Release at all; the mirror ordering cancels A's `finalize-image-aliases` after A has already created the Release and advanced `vMAJOR`/`vMAJOR.MINOR`, leaving Git aliases ahead of image aliases. Neither state is modelled: `release-evidence` carries `if: ${{ !cancelled() }}` and is therefore skipped too, so the run summary that would show it is not written. The serialisation guard asserts only that the group is non-empty and ref-free; it says nothing about two dependent jobs sharing one. `docs/operational.md`'s recovery table has a "Partially aliased registry" row for a *failed* `finalize-image-aliases`, not a cancelled one. | Give each alias stage its own group (`…-git-aliases`, `…-image-aliases`), or collapse the two stages into one job — the authority split is what forbids the latter, so the former. Extend the guard: no two jobs where one `needs:` the other may share a concurrency group. Record the interaction in ADR-0011's concurrency amendment, and add the cancelled-stage row to the recovery runbook. |
| 4 | MAJOR | Core §10 (docs contradict the code); global §3 | `docs/adr/0007-pr-verification-topology.md` (whole file) | ADR-0007 is **untouched by the entire epic** (`git log dbc991c..HEAD -- docs/adr/0007-*.md` is empty) while the epic replaced the topology it records. It is `Status: Accepted`; invariant 3 routes pushes and tags through `build.yaml`, deleted in E007; its Status note (`:147`) states `.github/workflows/` "now contains only `ci.yaml` and `verify-build.yaml`" against five workflows on disk; it describes the verifier as "nine jobs … seven parallel gates" against ten jobs and eight gates; invariant 5 and both follow-ups (`:120`, `:181-182`) demand work already done or now moot; its entire Open Questions block names files and actions that do not exist. It is cited as live authority by `docs/architecture.md:134` and by the fork-safety guards' rationale. Its four siblings (0006, 0008, 0009, 0011) all carry sprint-closure amendments; 0007 was missed. | Amend ADR-0007 the way its siblings were amended, or supersede it with a topology ADR for the shipped five-file graph. At minimum correct invariant 3, the Status note, the job count, and strike the resolved follow-ups and Open Questions. |
| 5 | MAJOR | Global §3 and §4; Core §3 | `tests/ci/test_workflow_contracts.py:6324-6331`; live violation at `docs/adr/0009-action-pin-policy.md:71` | The rule "a guard name a document cites must resolve" exists and is executed — `assert guard in globals()` — but its corpus is `_recovery_section(docs/operational.md)`: **one section of one page.** Every ADR, the architecture spine and `docs/architecture.md` are outside it, and they are where guard names are cited as the *enforcement mechanism for a decision*. The violation is already live: ADR-0009's Enforcement section (`:71`) states in the present tense that `test_credential_handling_publishers_are_registered_as_sha_pinned` "supplies the **reach**". **Verified: `grep -rn 'def test_credential_handling_publishers_are_registered_as_sha_pinned'` returns nothing.** The shipped guard is `test_every_credential_handling_action_is_pinned_or_its_risk_is_recorded` (`:462`), and ADR-0009's own amendment explains why the old one was wrong — while the Enforcement section a reader reaches first still describes it. This is the same rule/reach split the epic spent 20 commits closing, reproduced in the remediation, and it is precisely the failure global rule §3 was written from. | Widen the corpus to `_documented_files()`, which already exists at `:6465` and is repo-wide, and assert every `test_[a-z0-9_]+` token found in this project's own documentation resolves in the collected test namespace. Fix ADR-0009:71 in the same change. Note that two other ADRs' line citations are stale (`0012` cites `dev.yaml:200`/`release.yaml:330` against `:219`/`:360`; `0008` cites `verify-build.yaml:461-493` against `:550-570`; `0009`'s follow-up cites four `uses:` lines that have all moved) — line numbers are unmaintainable citations and should be replaced with step names or anchors. |
| 6 | MAJOR | Core §1 (God module), §5 (readability) | `tests/ci/test_workflow_contracts.py` (6,612 lines / 307 KB, one module) | One module holds ~150 tests across at least ten unrelated concerns: action-pin policy, fork trust boundary, workflow topology, permissions, credential disjointness, alias ordering, executed `jq` gate fixtures, real-git fixtures, gitleaks configuration, justfile recipes, and documentation link checking. It grew by roughly 4,000 lines this epic. The consequence is not aesthetic: reviewability of this file is the control that catches everything else, and the epic's own record is that eleven mis-scoped guards hid inside it across two gates and a red-team pass. Module-level constants that are *grants* (`RELEASE_FINALIZER_JOBS`, `SHA_PINNED_ACTIONS`, `CREDENTIAL_ACTIONS_ON_MOVING_REFS`, `APPROVED_ACTION_OWNERS`) sit in the same file as the tests that read them, which is why `.github/CODEOWNERS` had to be introduced to compensate. | Split along the seams the file already has: `test_action_policy.py`, `test_trust_boundary.py`, `test_topology.py`, `test_publication_matrix.py`, `test_finalization.py`, `test_documentation.py`, with the shared derivations (`_governed_definitions`, `_publishers`, `_alias_moving_jobs`, `_trigger_surface`, `_transitive_needs`, `_load_document`) in a `tests/ci/_derivations.py` and the grant registries in a single `tests/ci/_grants.py` that CODEOWNERS can name precisely. No rule changes; the split is mechanical. |
| 7 | MINOR | Global §4; ADR-0011 | `release.yaml:723-729`; guard at `tests/ci/test_workflow_contracts.py:4590-4600` | The finalizer gate's `PUBLISHER_RESULTS` map binds each destination key to a job result by hand. `test_every_finalizer_waits_for_every_publisher_and_reads_every_result` asserts each publisher's `needs.<job>.result` appears *somewhere* in the gate's `env:`, never that a destination key is bound to the job that ships that destination. **Verified: rebinding `"image-dockerhub"` to `needs.publish-package-forge.result` leaves the suite at 285 passed.** (Gross rewiring — every key bound to `needs.verify.result` — *is* caught, by `_render`'s binding resolution: 11 failures. Only a swap between two live publishers is invisible.) Today one job ships both image destinations so the blast radius is small; it grows the moment a second image publisher is added. | Derive the expected binding: for each destination key, assert the bound job is one whose steps address that destination (the `permitted`/`repositories` inputs already carry the mapping), or assert the key set of `PUBLISHER_RESULTS` maps onto `_publishers()` by a stated rule rather than by inspection. |
| 8 | MINOR | Global §4 | `tests/ci/test_workflow_contracts.py:2059-2078` (`_publishing_workflows`) via `_trigger_surface`, `:5912` (`NON_AUTOMATIC_EVENTS`) | `_publishing_workflows` requires a non-empty `_trigger_surface`, which excludes `workflow_dispatch`. The seven destination-agnostic rules that key on it — full-history checkouts, credential disjointness, tag re-read before upload, optional-credential gating, the evidence job, the finalizer wiring, the run summary — therefore do not examine a manually-dispatched publisher. **Verified: Plant 11 added `manual-publish.yaml`, `on: workflow_dispatch`, one job with `id-token: write`, `secrets.PYPI_TOKEN`, `poetry build && twine upload`, no verifier, no bundle revalidation; two guards fired (`test_any_push_triggered_workflow_verifies_before_it_ships`, `test_every_publisher_revalidates_the_bundle_before_it_logs_in_or_uploads`), the other seven did not.** The two that fired are the load-bearing ones, which is why this is MINOR rather than MAJOR. | Split the exclusion: `workflow_dispatch` is correctly outside the *event-ownership partition* (a person asked for it, so it races nothing) and wrongly outside the *publisher* scope. Seed `_publishing_workflows` from `_publishers(document)` alone, or from `_declared_events(document) - {"workflow_call"}`. |
| 9 | MINOR | Core §4 (a guard must fail legibly) | `tests/ci/test_workflow_contracts.py:5361` | `_alias_moving_jobs()` deliberately returns composite actions keyed by repo-relative path (`.github/actions/verified-bundle/action.yml`, `runs`), but `test_a_disabled_docker_hub_is_addressed_by_no_alias_step` composes `WORKFLOWS / path` unconditionally. **Verified: Plant 1 (an `imagetools create` planted in `verified-bundle/action.yml`) produced `FileNotFoundError: …/.github/workflows/.github/actions/verified-bundle/action.yml`** alongside three clean assertion failures. A crash reads as a broken test rather than a caught violation, which is how a real one gets triaged as flake. Same class as the deferred arch-drift finding m7. | Resolve the path the way `_gate_steps` does — skip entries whose first path segment is not `.github/workflows`, or resolve against `PROJECT_ROOT` and load the composite's `runs.steps`. |
| 10 | MINOR | Core §3 (prose overstating coverage); global §4 | `tests/ci/test_workflow_contracts.py:634-668` | `test_the_authority_surfaces_are_owned`'s docstring says "The owned set is derived from where those things actually live, so a registry moved to a new file is covered or fails here." Only one of the seven required patterns is derived (`Path(__file__).…parts[0]` → `tests`); `/.github/`, `/docs/adr/`, `/.pre-commit-config.yaml`, `/.agents/`, `/.claude/`, `/AGENTS.md` are literals. Moving `RELEASE_FINALIZER_JOBS` to `scripts/` would satisfy the guard and leave the registry unowned — the exact failure the sentence promises is covered. | Either derive the required set (the modules that define the grant registries, plus the directories the workflows and ADRs live in) or delete the sentence and say the list is a registry whose entries each need a reason. |
| 11 | MINOR | Core §6 (stale comment) | `tests/ci/test_workflow_contracts.py:1044-1046` | `test_any_push_triggered_workflow_verifies_before_it_ships`'s docstring still reads "no workflow reacts to push right now -- Epic 8's dev.yaml closes that … Passes vacuously today". `dev.yaml` reacts to `push: branches: [main]` and the guard is no longer vacuous. This is retrospective action item **A3**, raised at sprint closure and not applied by the remediation. | Rewrite the docstring to describe the invariant it now enforces over `dev.yaml` and `release.yaml`. |
| 12 | MINOR | Core §6 (comments explain state and intent, not history) | `.github/workflows/release.yaml` (442 of 1,307 lines are comments, 34%), `dev.yaml` (23%), `tests/ci/test_workflow_contracts.py` (9%) | A large share of the comment mass narrates change history — "This was a hand-kept `(CI_WORKFLOW, VERIFY_WORKFLOW)` tuple: the *same* 2-tuple that tier 1 replaced…", "The list had only the first, so an `env:` block … was invisible to every guard here", "the previous comment claimed it was". Core §6 is explicit that change history is git's job and that changelog-in-comments is a review finding. Much of this text does carry genuine intent, which is why it is MINOR — but the provenance half belongs in the ADR or the commit message, and keeping it inline is what makes a 1,307-line workflow file. | Keep the invariant and the "why this shape", move the defect provenance to the ADR that already records it (each of these paragraphs has one). If the defect-provenance style is a deliberate project convention, record it as such — an ADR or a line in `docs/guidelines.md` — so it reads as a chosen deviation rather than an unnoticed one. |

---

## Per-principle walkthrough

Every principle walked; none skipped.

### `standards-core.md`

- **§1 Separation of concerns** — Findings **2**, **6**. Otherwise strong, and the epic's best structural
  work: the finalizer authority split (`contents: write` and no registry credential in `finalize`;
  registry credentials and no `contents: write` in `finalize-image-aliases`) is real, enforced in both
  directions by `test_ref_writing_and_registry_alias_privileges_never_meet`, and survived planting.
  `_governed_step_groups` correctly treats a composite action's steps as holding the calling job's
  authority — Plant 1 confirmed three independent guards fire on a forbidden step moved into
  `verified-bundle/action.yml`. Publication decisions are kept out of Python modules and enforced by
  `test_no_publication_decision_lives_in_a_python_module`.
- **§2 Reuse over copy-paste** — **PASS.** The epic's copied bodies are each pinned identical by an
  executed guard: the forge-coordinate derivation, the stable-tag re-check (four copies), the
  suppression re-check, the alias-ordering decision (two copies), and the finalization gate (two
  copies, closing arch-drift M3). `test_every_finalization_gate_is_the_same_body` and
  `test_every_alias_ordering_decision_is_the_same_body` both assert `len(distinct) == 1` over a
  derived corpus. Shared surface (`verify-build.yaml`, `publish-image.yaml`, the three composite
  actions) is called rather than restated.
- **§3 Design by contract** — Findings **1**, **5**, **10**. The positive side is unusually strong:
  boundary revalidation (`verified-bundle`) is asserted for every publisher before any login or upload;
  the finalizer gate is an executed `jq` program with twelve input-validation tests, now bound to both
  channels; the release identity is asserted as a relation between fields rather than a literal.
- **§4 Testability** — Findings **1**, **2**, **7**, **8**, **9**. The suite is fast (8s) and largely
  executes the shipped bodies rather than paraphrasing them — `_render` resolves a step's real `env:`
  and raises on an unbound expression, which is what caught Plant 12b. Eleven of thirteen plants were
  caught. **`_load_document`'s `copy.deepcopy` over a `functools.cache`d `_parsed_definition` is sound**
  and is not a finding: `_load_document` is the only caller of `_parsed_definition` (verified by grep
  across `tests/`), no test writes to a file under `.github/` (every `write_text` is `tmp_path`-scoped),
  and no cached function returns a mutable derived from a parsed document — so no mutation can leak
  between tests and no on-disk change can be masked by a stale parse.
- **§5 Brevity** — Finding **6**, and **12**'s consequence. `release.yaml` at 1,307 lines and
  `test_workflow_contracts.py` at 6,612 both exceed what a reader can hold on first pass.
- **§6 Comments** — Findings **11**, **12**.
- **§7 Dependency selection** — **PASS.** Four approved action owners; `LiquidLogicLabs/*` is
  maintainer-owned and the residual risk is recorded per action in `CREDENTIAL_ACTIONS_ON_MOVING_REFS`
  with a stated reason, backed by `test_every_granted_privilege_points_at_a_decision` (every registry
  entry must be named by some ADR). `pypa/gh-action-pypi-publish` is pinned to a reviewed 40-character
  SHA with a recorded review date, enforced by `test_every_sha_pinned_publisher_records_the_date_it_was_reviewed`.
  Global rule §1 (do not hand-roll) was honoured, and honoured *late but correctly*: 1,362 lines of
  hand-rolled forge-coordinate, stable-tag and finalizer-gate Python were written and then deleted in
  favour of action context, `git for-each-ref` and `jq`. Git owns version ordering (`--sort=v:refname`)
  and reachability (`merge-base --is-ancestor`) rather than a hand-rolled comparison.
- **§8 GA over preview** — **PASS.** No `-alpha`/`-beta`/`-rc`/`-preview` dependency in
  `pyproject.toml`; `poetry.lock` committed; `requires-python = ">=3.10,<3.15"`. Every action is on a
  floating major or a full SHA — no `@main`, no pre-release tag. *Unverified offline:* that
  `actions/checkout@v7`, `actions/setup-python@v7`, `docker/setup-buildx-action@v4` and
  `actions/attest-build-provenance@v3` are the current GA majors upstream; nothing in the repository
  records the resolution, and only the SHA-pinned action carries a review date.
- **§9 Structured, correlated logging** — **PASS with a note.** CI evidence is workflow-native per
  CI-AR41: run ID and URL, bundle and manifest hashes, published digest and inspected platforms,
  Release URL and per-alias outcomes are emitted as job outputs and `GITHUB_STEP_SUMMARY` tables, and
  `test_every_run_summary_reports_the_verified_bundle_and_every_destination` derives its scope from
  `_publishers()` (Plant 2 fired it). The join key from an image digest back to the run
  (`org.opencontainers.image.revision`) is asserted in the runbook. No secret reaches a summary.
  Note: `release-evidence` and `development-evidence` both carry `if: ${{ !cancelled() }}`, so the
  correlated record is exactly absent in the cancelled-alias-stage state of finding **3**.
- **§10 Documentation** — Findings **4**, **5**, and the unrecorded decisions listed below.
  `docs/architecture.md` gained a §7 "Delivery topology" with two Mermaid diagrams (closing
  arch-drift M5), `docs/guidelines.md` was corrected and its links are now enforced repo-wide by
  `test_no_tracked_document_links_to_a_file_that_does_not_exist`, `docs/operational.md` gained the
  publication-recovery runbook, the `pypi` environment preconditions, the partial-alias recovery row
  and a credential-compromise runbook. The `just`-recipe drift (CI-AR7) is closed and now enforced by
  `test_every_recipe_a_document_prescribes_exists`. The gap is the ADR layer, not the guides.

### `standards-github-actions.md`

- **Marketplace actions over custom scripting** — **PASS.** Checkout, setup-python, artifacts, registry
  login, Buildx, PyPI upload, Release creation, alias movement and image metadata are all actions.
  Remaining `run:` blocks are project-specific decisions (identity, enabled set, gate, tag composition),
  and the repeated ones are pinned byte-identical by same-body guards.
- **Pin to a major, and use the latest** — **PASS.** Floating major for approved owners, reviewed full
  SHA for the one action handed a publication credential (CI-AR4/CI-AR38 reconciled per action rather
  than per owner). `actions/upload-artifact@v4` / `download-artifact@v4` are deliberately held at v4
  for Gitea parity, with a Dependabot ignore and `test_dependabot_protects_the_artifact_pin_it_would_otherwise_undo`
  proving the ignore and the pin cannot drift apart. Dependabot covers `github-actions`, `pip` and
  `docker` (`test_dependency_maintenance_covers_actions_python_and_docker`).
- **Least-privilege `permissions:`** — Finding **2**.
- **Secrets via Secrets/OIDC, never logged** — **PASS.** Trusted publishing for PyPI, repository token
  for GHCR, scoped tokens elsewhere; disabled destinations receive an empty string rather than a
  secret, gated on the single enabled set; the alias credential is passed through git's
  `GIT_CONFIG_COUNT/KEY_0/VALUE_0` protocol and never written to `.git/config`
  (`test_a_finalizer_never_leaves_a_credential_in_the_workspace`). No `${{ }}` interpolation inside any
  `run:` body. `environment: pypi` was added, with its two out-of-tree preconditions written down
  rather than implied.
- **Concurrency groups** — Finding **3**. `ci.yaml` (per-PR, cancel), `dev.yaml` (per-ref, cancel),
  `release.yaml` (per-ref, no cancel) are each right for their channel; the defect is the shared
  alias-stage group.
- **Repeated logic factored into composite/reusable workflows** — **PASS.**

### `standards-python.md`

- **PASS.** Poetry with `poetry.lock` committed; `pyproject.toml` is the source of truth with a bounded
  `requires-python`; ruff and mypy configured and run as verifier gates; `pytest` is the only test
  framework and no bespoke runner was introduced — the 1,362 lines of hand-rolled pipeline Python
  written mid-epic were deleted rather than kept, which is global rule §1 landing correctly. The
  gitleaks gate now scans content (`gitleaks dir`) instead of an empty index and proves itself against
  a planted credential in CI, closing redteam H2.

---

## Verification log

Baseline `82819bc`, detached worktree, `poetry run pytest tests/ci/` — **285 passed, 8.2s**.

| Plant | Violation | Result |
|---|---|---|
| 1 | `imagetools create` + `git push --force …:refs/tags/v1` inside `verified-bundle/action.yml` | **caught** — 3 assertions + 1 crash (finding 9) |
| 2 | New credential-bearing publisher job in `dev.yaml`, no revalidation / denials / tag re-read | **caught** by 8 guards; the permissions-denial guard did **not** fire (finding 2) |
| 3 | Attesting job set to `if: ${{ false }}` | **285 passed** (finding 1) |
| 4 | `finalize-image-aliases` consumes `needs.finalize.outputs.advance-major` | caught |
| 5 | Ref-free job concurrency removed from `finalize-image-aliases` | caught |
| 6 | `attestations: none` removed from `finalize` | caught |
| 7 | Unregistered action handed `secrets.GITHUB_TOKEN` on a floating major | caught |
| 8 | Second literal spelling of the default branch | caught |
| 9 | `contents: write` on `release.yaml:publish-image` | caught |
| 10 | Finalization gate step deleted from `finalize` | caught (27 failures) |
| 11 | `workflow_dispatch`-only publisher, no verifier, no revalidation | 2 of 9 fired (finding 8) |
| 12 | `image-dockerhub` bound to the wrong job result | **285 passed** (finding 7) |
| 12b | Every destination key bound to `needs.verify.result` | caught (11 failures) |
| 13 | Image alias step moves `latest` ignoring `advance-major` | caught |

Not executable in this environment, reasoned from documented platform semantics: finding **3**
(GitHub Actions concurrency queueing), and the upstream GA status of the action majors in use (§8).

---

## Gate

- **BLOCKER:** none.
- **MAJOR (1–6):** must be resolved or recorded as an accepted ADR before epic sign-off.
  Findings 1, 2 and 3 are correctness/security; 4 and 5 are documentation integrity and are the
  cheapest of the six; 6 is structural and may reasonably be scheduled into E009.
- **MINOR (7–12):** defer to the issues backlog, except **11**, which is an unapplied sprint
  retrospective action item (A3) and costs one line.

Note for the epic record: the sprint-closure reports left the *guard-scope meta-guard* (retrospective
action item **A1**) unimplemented. Findings 1, 2, 5 and 8 are four fresh instances of exactly the class
A1 proposed to detect, all introduced by the remediation itself. That is the strongest available
argument for A1, and it should not be deferred a second time.

---

## Recommended ADRs

Shipped, load-bearing decisions that no ADR records. Each is a call made against a principle, so each
falls under Core's decision-making hook.

1. **`environment: pypi` on the irrevocable destination** — the human-approval gate and the trusted-publisher
   environment claim. Guarded by `test_the_irrevocable_destination_names_an_environment`; recorded in
   `docs/operational.md` as two out-of-tree settings; named by no ADR.
2. **https-only forge scheme** — refused in two places (`release.yaml`'s coordinate derivation and its
   push-endpoint resolution), executed against four insecure schemes by the coordinate test. A live
   E009 decision about a self-hosted Gitea; no ADR.
3. **Per-repository image-tag validation** — `publish-image.yaml`'s `repositories:` input and its
   three-spelling normalisation, motivated by Docker Hub PATs being account-scoped. ADR-0012 records
   only the *alias* refusal in the same step.
4. **`publish-image.yaml` as the shared reusable publisher** — its trigger shape, permissions, secret
   contract and the one-Buildx-invocation rule (CI-AR39) live only in the spine.
5. **`dev.yaml`'s `stable-tag-guard` suppression job** — it gates every development publisher and the
   development finalizer; no ADR mentions it.
6. **The three composite actions**, especially `verified-bundle`, described by the suite as "the trust
   boundary between the secret-free verifier and the credentialed publishers (CI-AR36)".
7. **The attestation asymmetry** — whichever way finding 1 is resolved, ADR-0008 must state which
   channels and destinations are attested and which are not, and why `dev.yaml`'s
   `publish-package-testpypi` (which holds `id-token: write`) attests nothing.
8. **The defect-provenance comment convention** (finding 12), if it is to be retained as a deliberate
   deviation from Core §6.

---

*DONE — Blocker: 0, Major: 6, Minor: 6*
