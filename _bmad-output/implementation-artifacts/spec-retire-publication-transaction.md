---
title: 'Archive and retire the publication transaction framework'
type: 'refactor'
created: '2026-09-01'
status: 'done'
baseline_commit: 'dbc991c7595d087edc1a2f91e763d0418209116e'
review_loop_iteration: 0
context:
  - '{project-root}/docs/guidelines.md'
  - '{project-root}/docs/ci/codex-assesment.md'
  - '{project-root}/_bmad-output/planning-artifacts/architecture/architecture-ci-cd-pipeline-2026-08-31/ARCHITECTURE-SPINE.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Epic 8 is ready but not started, while its publication transaction and
reconciliation design makes ordinary multi-destination publishing too expensive to maintain.

**Approach:** Preserve the complete pre-retirement repository at exact commit
`dbc991c7595d087edc1a2f91e763d0418209116e` on pushed branch
`archive/publication-transaction-v1`, then simplify `main` to build-manifest/checksum evidence
plus normal action-based publishing and replace the active Epic 8/9 plan accordingly.

## Boundaries & Constraints

**Always:** Push the archive branch successfully before changing tracked files; never rewrite
that branch; retain `build-manifest-v1`, `SHA256SUMS`, exact-wheel provenance, multi-arch
verification, `ci.yaml`, `verify-build.yaml`, `just`, and guarded release versioning; preserve
GitHub/Gitea, Docker Hub, TestPyPI/PyPI, active-forge, aliases-last, and secret-isolation goals;
keep current planning and l3io state consistent with the simplified implementation.

**Ask First:** The archive branch already exists locally or remotely at a different commit; the
archive push fails; removing transaction code requires changing the retained verifier interface,
renaming the `publication_contract` package/action, or reducing a publishing destination.

**Never:** Force-update/delete the archive branch; reset or rewrite `main`; remove the build
manifest/checksum path; leave active stories or architecture requiring retired schemas; implement
remote identity reconciliation, aggregate transactional preflight, or a release receipt under a
different name.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|---|---|---|---|
| Archive | Branch absent; clean synced HEAD at the recorded SHA | Local and remote archive refs resolve exactly to the recorded SHA | Halt before source edits if creation/push cannot be proven |
| Existing archive | Local/remote ref exists | Reuse only if it resolves to the recorded SHA | Never force; halt for human direction on mismatch |
| Retained evidence | Wheel/sdist and image-plan inputs | Canonical build manifest and checksums validate unchanged | Existing field-specific failures remain |
| Retired contract | Plan/receipt contract requested | Unsupported contract; no packaged schema or fixture exists | CLI/action fails clearly rather than accepting stale input |
| Current planning | E008/E009 backlog loaded | Lean action-based stories and valid acyclic l3io state/plan | Schema/readiness failure blocks commit/push |

</frozen-after-approval>

## Code Map

- `src/publication_contract/contract.py` -- keep deterministic JSON, secrets guard, hashes,
  build-manifest, and checksums; remove plan/receipt constants and validators.
- `src/publication_contract/schemas/` -- keep only `build-manifest-v1.schema.json`.
- `.github/actions/publication-contract/action.yml` -- retained adapter used by
  `verify-build.yaml`; narrow its documented contract choices to build-manifest.
- `.github/workflows/verify-build.yaml` -- retain its build-manifest/checksum operations.
- `tests/ci/test_publication_contract.py` and `tests/ci/fixtures/publication-contract/` -- retain
  generic hardening and build evidence tests; delete plan/receipt/reconciliation cases.
- `docs/ci/codex-assesment.md`, CI architecture spine, and `epics.md` -- replace transaction
  claims with the lean build-once, publish-with-actions model.
- Epic 8/9 stories and planned state -- replace transaction stories with a smaller backlog and
  regenerated plan.

## Tasks & Acceptance

**Execution:**
- [x] Git refs -- create/push the immutable archive ref at the recorded SHA before source edits.
- [x] `src/publication_contract/` and `.github/actions/publication-contract/action.yml` -- remove
  publication-plan/release-receipt support while preserving build evidence behavior.
- [x] `tests/ci/` -- remove transaction fixtures/tests and keep equivalent JSON/build-manifest
  hardening coverage.
- [x] Planning/report/architecture/story/state files -- rewrite the active E008/E009 plan around
  ordinary destination jobs, aliases-last finalization, and practical Gitea certification.
- [x] Git `main` -- commit the reviewed simplification after all gates pass; leave remote push
  for explicit post-review confirmation.

**Acceptance Criteria:**
- Given the archive branch, when local and remote refs are resolved, then both equal the recorded
  pre-retirement SHA.
- Given current `main`, when transaction identifiers are searched, then no runtime schema,
  validator, fixture, active story, or canonical architecture requires a publication plan or
  release receipt.
- Given the retained verifier, when CI contract tests run, then the exact build manifest,
  checksums, wheel provenance, and multi-arch interfaces remain green.
- Given the rewritten backlog, when BMad/l3io validation runs, then E008/E009 are green,
  dependency-acyclic, and the stable plan pointer names the new immutable snapshot.

## Spec Change Log

## Design Notes

The archive branch is a complete repository snapshot so later review can run its tests and
inspect dependencies at the exact pre-retirement commit. `main` keeps the package/action name;
renaming can be a later cleanup.

## Verification

**Commands:**
- `poetry run pytest tests/ci/test_publication_contract.py tests/ci/test_workflow_contracts.py`
  -- expected: retained contract and workflow tests pass.
- `poetry run pre-commit run --all-files` -- expected: repository quality gates pass.
- `poetry check --lock` -- expected: package metadata and lock remain valid.
- `python3 _bmad/scripts/pm-status.py verify --state-root _bmad-output/implementation-artifacts/state --epic E008 --scope epic --runtime other` -- expected: PASS.
- The same `pm-status.py verify` command for `E009` -- expected: PASS.

**Results (2026-09-01, review-fix pass):**

- Archive assertions passed: local and `origin/` tracking refs both resolve to
  `dbc991c7595d087edc1a2f91e763d0418209116e`.
- Targeted CI tests passed: 63 tests.
- Full repository regression tests passed: 139 tests in 88.63 seconds on the final post-format run.
- `poetry run pre-commit run --all-files` passed after its first run applied one Ruff formatting
  change; the post-format rerun passed every hook.
- The four untracked additions were also passed explicitly to `pre-commit run --files`; every
  applicable hook passed, proving they were not skipped by `--all-files`.
- `poetry check --lock` passed with existing Poetry metadata-deprecation warnings.
- E008 and E009 l3io epic verification both passed; the stable pointer names the new immutable
  `plan-2026-09-01-v4.yaml` snapshot.
- `git diff --check` passed. Active-runtime/planning audits found retired identifiers only in
  explicit historical-retirement/archive references; no active contract or story requires them.
- Matrix audit: archive/current-ref rows are covered by the shell ref assertions; retained and
  retired contract rows by `tests/ci/test_publication_contract.py`; current planning by both
  `pm-status.py verify` invocations. All covering checks ran and passed.

## Suggested Review Order

**Decision and architecture**

- Start with the lean recommendation, retained evidence boundary, and reduced delivery plan.
  [`codex-assesment.md:9`](../../docs/ci/codex-assesment.md#L9)

- Historical requirement identities remain reviewable while lean replacements receive new keys.
  [`ARCHITECTURE-SPINE.md:110`](../planning-artifacts/architecture/architecture-ci-cd-pipeline-2026-08-31/ARCHITECTURE-SPINE.md#L110)

- Lean publishing invariants define revalidation, one-build fan-out, recovery, and run evidence.
  [`ARCHITECTURE-SPINE.md:157`](../planning-artifacts/architecture/architecture-ci-cd-pipeline-2026-08-31/ARCHITECTURE-SPINE.md#L157)

**Executable backlog**

- Development publication builds one multi-platform image and keeps aliases out of scope.
  [`E008-S01-001.md:17`](epic-008/sprint-01/stories/E008-S01-001.md#L17)

- One finalization story exclusively owns forward-only development and stable aliases.
  [`E008-S01-003.md:17`](epic-008/sprint-01/stories/E008-S01-003.md#L17)

- Gitea runner bootstrap trust is separated from downstream job-level CA installation.
  [`E009-S01-001.md:17`](epic-009/sprint-01/stories/E009-S01-001.md#L17)

- Migration requires failed-jobs-only recovery and complete staging evidence.
  [`E009-S01-002.md:17`](epic-009/sprint-01/stories/E009-S01-002.md#L17)

**Retained contract and verification**

- The runtime registers only the build manifest and forbids credential-shaped fields.
  [`contract.py:26`](../../src/publication_contract/contract.py#L26)

- Installed wheel and sdist smoke tests enforce the exact surviving schema set.
  [`verify-build.yaml:415`](../../.github/workflows/verify-build.yaml#L415)

- Tests prove retired names fail clearly and undeclared schemas cannot return silently.
  [`test_publication_contract.py:106`](../../tests/ci/test_publication_contract.py#L106)

**Planning state**

- The immutable v4 plan sequences four Epic 8 stories before two Epic 9 stories.
  [`plan-2026-09-01-v4.yaml:7`](../planning-artifacts/plan-2026-09-01-v4.yaml#L7)

- The generated progress view confirms the current plan and reduced story counts.
  [`progress-report.md:5`](progress-report.md#L5)
