# Gitea staging certification and the migration gate (Story 9.2)

**Rescope note (2026-10-06):** Epic E009 was rescoped to drop live-Gitea-runner certification.
No production-owner migration is currently planned or blocked on this project; this document and
the validator it describes are kept as a tested reference implementation, in case a future epic
revives live certification. Every item marked **requires live Gitea** below is formally
out-of-scope, tracked as a resolved (`wontfix`) backlog issue (`BL-E009-014` through
`BL-E009-021`), not a pending task.

Status: **not executed**. This runbook, and the mechanical gate it documents
(`tests/ci/test_certification.py`), were authored against the pinned
`traefik-certificate-exporter` CI/CD pipeline for E009-S01-002, in an environment with
no live Gitea server, no registered act-runner, and no provisioned credentials. Every
item below marked **requires live Gitea** has not been run. What exists and passes
today is the schema and the validator: `REQUIRED_GITEA_CASES`, the ADR-0017 evidence
export/report resolver, the ADR-0020 recovery contract, and the ADR-0016 closure
comparison, each exercised against synthetic fixtures this test file constructs and
clearly marks as fixtures, never as Gitea evidence.

This document is prose. It is not the certification gate (F20) -- `tests/ci/`, and
specifically `tests/ci/test_certification.py::REQUIRED_GITEA_CASES`, is. If this
document and the registry ever disagree about which cases are required, the registry
wins; update this document to match it, not the reverse.

## Why a registry independent of this document (F20)

Story 9.2 declared mechanical anchors -- "the gate derives its required cases from the
declared negative-case set and demands a run URL and conclusion for each; plant a
removed case" -- while its original Files in scope held only markdown, so nothing
could implement that check. `tests/ci/test_certification.py::REQUIRED_GITEA_CASES`
resolves that: it is the single source of required case IDs, and
`resolve_certification_report` is the mechanical gate that resolves every report row
against both that registry and a retained ADR-0017 evidence export. A run URL and a
typed conclusion with no matching export-backed identity cannot pass it.

## What the gate requires, case by case

| Case ID | Kind | Status here |
|---|---|---|
| `pr-verification-secret-free` | positive | requires live Gitea |
| `protected-dev-delivery` | positive | requires live Gitea |
| `protected-stable-delivery` | positive | requires live Gitea |
| `artifact-round-trip` | positive | requires live Gitea |
| `private-ca-boundary-package-index` | positive | requires live Gitea |
| `private-ca-boundary-forge-api` | positive | requires live Gitea |
| `multi-arch-image-linux-amd64-arm64` | positive | requires live Gitea |
| `forge-package-channel` | positive | requires live Gitea |
| `forge-release` | positive | requires live Gitea |
| `reusable-workflow-dev-release-shared` | positive | requires live Gitea |
| `reusable-workflow-publish-image` | positive | requires live Gitea |
| `aliases-last-behavior` | positive | requires live Gitea |
| `failed-jobs-only-recovery` | recovery (ADR-0020) | requires live Gitea for the real rerun; the preservation/cleanup **contract** is implemented and unit-tested against synthetic fixtures |
| `wrong-ca` | negative | structurally covered by `tests/ci/test_runner_trust_routing.py` (CA-import step placement); the live denial itself requires live Gitea |
| `missing-credential-or-scope` | negative | statically covered by `tests/ci/test_credential_matrix.py` (no job references a secret its row forbids); the live forge denial requires live Gitea |
| `unknown-forge` | negative | covered today, no live Gitea needed -- `tests/ci/test_forge_coordinates.py::test_classifier_recognizes_github_and_gitea_and_fails_closed_for_everything_else` executes the real classifier body |
| `malformed-registry` | negative | structurally unreachable under this repository's design (`FORGE_REGISTRY` is retired; see `tests/ci/test_forge_coordinates.py::test_no_malformed_registry_or_same_host_path_taxonomy_is_reachable`) |
| `absent-default-branch-context` | negative | requires live Gitea (observing `github.event.repository.default_branch` on an actual Gitea run) |
| `restricted-permission-write-refusal` | negative | requires live Gitea; a `TokenPermissionMode` settings read-back is not evidence (see Definition of Done) |
| `endpoint-scope-omission` | negative | statically covered by `tests/ci/test_credential_matrix.py::test_disabled_destination_jobs_receive_no_secret_for_that_destination`; the live forge-side scope denial requires live Gitea |
| `artifact-output-loss-across-rerun` | negative (ADR-0020) | the preservation contract (empty `needs` outputs, lost artifact scope) is implemented and unit-tested against synthetic fixtures in `tests/ci/test_certification.py`; the live rerun requires live Gitea |
| `package-image-failure` | negative | requires live Gitea (an actual destination failure observed and reported) |
| `stale-dev-candidate` | negative | covered today, no live Gitea needed -- `tests/ci/test_finalization.py::test_a_stale_development_candidate_halts_without_moving_dev` |
| `failed-jobs-only-unsupported` | negative | requires live Gitea (probing the pinned Gitea's rerun API directly) |

`tests/ci/test_certification.py::CASE_REQUIRES_LIVE_GITEA` is the machine-checked
version of the "requires live Gitea" column above; a test in that module asserts every
entry in it names a real required case, and a second asserts at least one required case
is left statically resolvable, so the registry cannot silently become a list of
excuses.

## The retained evidence export (ADR-0017)

Every required case's report row must be an exact projection of a retained,
checksummed export acquired directly from the pinned Gitea API: immutable
run/attempt/job IDs, timestamps and conclusion, source SHA, workflow path and revision
SHA, the canonical pinned-tuple record and its fingerprint, artifact hashes and
published digests, and a `SHA256SUMS` whose own SHA-256 is the evidence-export digest.
`tests/ci/test_certification.py::EvidenceRecord`, `EvidenceExport`, `ReportRow`, and
`resolve_certification_report` implement that schema and the gate. Collection fails
closed on the wrong API authority, TLS failure, incomplete pagination, missing field,
or credential-shaped content (ADR-0017) -- the collector itself is a live-Gitea
dependency and is not implemented here; the schema it must produce, and the gate that
rejects anything short of it, are.

Proven today against synthetic fixtures (clearly marked as such in the test module, not
real Gitea output): a missing report row, an extra undeclared row, a duplicate row, a
cross-tuple row, a cross-source-SHA row, a cross-workflow row, a stale
evidence-export-digest row, a tampered (post-checksum) export, an incomplete export
(a file the checksum lists but does not retain), a locally-synthesized record with no
export backing, a credential-shaped value planted in the export, and the same planted
in the report -- each is mechanically rejected.

**Correlation identifier (resolves BL-E009-005 / AG-9).** One certification attempt
certifies exactly one pinned Gitea tuple (ADR-0015). `tuple_fingerprint` is that
attempt's non-secret correlation identifier: `resolve_certification_report` requires
every required case's row to agree on it, so an export silently assembled from more
than one attempt or tuple -- even if every individual row still matches its own
retained record -- fails the gate
(`test_an_export_mixing_two_tuple_fingerprints_fails_resolution`).

**Requires live Gitea** (not executed here): acquiring a real export from the pinned
Gitea API and resolving a real report against it
(`tests/ci/test_certification.py::test_a_real_certification_run_resolves_against_a_real_evidence_export`,
marked `@pytest.mark.requires_live_gitea`).

## Full-scenario action closure (ADR-0016)

Story 9.1 owns a bounded **preflight** closure (its own structural probes and smoke
scenarios); Story 9.2 owns the **full-scenario** closure across every required
positive, negative, publication, failure, rerun, cleanup, and migration-gate scenario,
compared against the preflight record. `tests/ci/test_certification.py`'s
`ActionClosureRecord` and `compare_action_closures` implement the comparison and its
drift rule: any addition or omission must be named in an `explained` mapping with a
reason, or certification fails. Proven today: identical closures pass; an explained
addition (e.g. an action reached only by the failed-jobs-only rerun path) passes; the
same addition, undeclared, fails; and an unexplained omission fails.

**Requires live Gitea** (not executed here): deriving the *real* preflight and
full-scenario closures from actually-executed runs, rather than the synthetic closures
the comparison function is unit-tested against here.

## Failed-jobs-only recovery and cleanup postconditions (ADR-0020)

One staging-only, destination-local fault-injection mechanism per destination --
revoking that destination's credential, or pointing its client at an unreachable
endpoint -- injected only after at least one other destination has already published.
`tests/ci/test_certification.py`'s `RecoveryPreState`, `RecoveryPostState`,
`ResourceCleanupState`, and `assert_recovery_contract` implement the full contract: the
fault-injection mechanism must be one of the two named forms and must be recorded as
injected after another destination's success (rerun identity), the already-successful
destination's conclusion/start time/outputs (including `build-manifest-sha256`) must be
unchanged after rerun with no second upload/publish request recorded against it
(preservation), and no orphaned partial upload, stale credential, or stale workspace
may remain afterward (cleanup postconditions). An immutable-index rejection observed
during the scenario is modeled as a defense-in-depth signal only -- planting one
alongside an otherwise-broken contract does not make the gate pass.

Proven today against a synthetic fixture: a clean recovery passes; rerunning more than
the one failed destination fails rerun identity; empty `needs` outputs on the
successful destination fails preservation; losing `build-manifest-sha256` from its
outputs fails preservation; a second upload/publish request against it fails even when
the recorded state still matches; an orphaned partial upload, a stale credential, and a
stale workspace each independently fail cleanup; a fault-injection mechanism that is
not staging-only/destination-local is refused; and a fault injected before any
destination had succeeded is refused.

**Requires live Gitea** (not executed here): actually revoking a staging credential or
redirecting a staging client, observing Gitea's native per-job rerun, and recording the
real pre-state/post-state this contract would then be checked against. See
`docs/operational.md`'s "Publication recovery" section for the equivalent GitHub/Gitea
recovery procedure this contract certifies for Gitea specifically.

## Runner bootstrap trust vs. job-level downstream trust

Every report row's `trust_boundary` field is one of exactly two values --
`runner-bootstrap` or `job-level-downstream` -- enforced by
`resolve_certification_report` as a closed vocabulary rather than free text, so a
reviewer cannot mistake one control's evidence for the other's. Runner bootstrap trust
(the OS/system CA store a registered runner starts with) is a provisioning-time
property outside any workflow job; job-level downstream trust (the CA import step
gated on `secrets.<DESTINATION>_CA_CERTIFICATE != ''`) is per-job and checked
structurally by `tests/ci/test_runner_trust_routing.py`. See
`docs/ci/gitea-runners.md`'s "Trust ordering" section for the full sequence diagram.

## Step-summary rendering is an observation, not a pass/fail criterion

`tests/ci/test_certification.py::case_passed` reads only the job output conclusion; a
misleading step summary (one that reads "FAILED" while the job output records success,
or the reverse) must not change the result. Both directions are planted and proven.

## Release fallback (ADR-0022)

If `LiquidLogicLabs/git-action-release@v2`'s Gitea-path platform detection cannot
operate within the pinned trust boundary, certification stops and requires the separate
ADR/SHA-pin/owner-policy branch (the `softprops/action-gh-release` fallback) before
retesting -- this is not a silent substitution. The static half of that probe (the
governance registry entry, its required pin kind, and the rejection of a planted
non-GA action with no accepting ADR) is implemented and tested in
`tests/ci/test_action_governance.py`.

**Requires live Gitea** (not executed here):
`tests/ci/test_action_governance.py::test_release_action_gitea_path_probe_records_network_and_trust_boundary`,
which must run the action against a real Gitea runner to observe whether it makes a
network request and which trust boundary covers it.

## Production-owner cutover

Per the Definition of Done ("Production-owner cutover has named approver, stop
conditions, rollback commands, and retained evidence links"), the cutover itself cannot
be rehearsed without a certified tuple, so this section records the procedure the
named approver follows once every required case above is green:

### Certification, recovery, and cutover sequence (resolves BL-E009-006 / AG-10)

```mermaid
sequenceDiagram
    actor Approver as Named approver
    participant Gate as Certification gate (F20 / ADR-0017)
    participant Closure as ADR-0016 closure comparison
    participant Recovery as ADR-0020 recovery contract
    participant Cutover as Production-owner cutover

    Approver->>Gate: Submit report rows + retained evidence export
    Gate-->>Gate: Verify required cases, checksums, shared tuple_fingerprint
    alt Any required case unresolved, tampered, or credential-shaped value found
        Gate--xApprover: CertificationGateError (halt -- stop condition)
    else Every required case resolves
        Gate->>Closure: Compare observed vs. declared full-scenario closure
        alt Drift detected
            Closure--xApprover: ClosureDriftError (halt -- stop condition)
        else No drift
            Closure->>Recovery: A job failed mid-run? Exercise failed-jobs-only rerun
            alt Rerun requested
                Recovery-->>Recovery: Verify preservation + cleanup postconditions
                alt Contract violated
                    Recovery--xApprover: RecoveryContractError (halt -- stop condition)
                else Contract holds
                    Recovery->>Cutover: Rerun evidence attached, gate re-resolved green
                end
            else No rerun needed
                Closure->>Cutover: Evidence links recorded, gate green
            end
        end
    end
    Cutover->>Cutover: Move publication secrets + coordinates to new forge
    Cutover->>Gate: Re-run ci.yaml against restored/new configuration
    alt PR verification fails
        Cutover->>Cutover: Rollback (restore prior secrets/coordinates, re-verify)
    else PR verification passes
        Cutover-->>Approver: Cutover complete; no tag/release/alias/package moved
    end
```

This diagram is the procedure, not a replacement for it: every box with a `--x` edge is one of the
Stop conditions below, and every `Gate`/`Closure`/`Recovery` box names the mechanical check that
decides it (`tests/ci/test_certification.py`). The sequence itself requires no live Gitea to read
or review; only walking it against a real pinned tuple does.

- **Named approver.** The repository maintainer who owns `production` branch
  protection and the publication secrets today. No other identity is authorized to
  move ownership.
- **Stop conditions.** Any required case in `REQUIRED_GITEA_CASES` without a
  resolvable report row; any `ClosureDriftError` from the ADR-0016 comparison; any
  `RecoveryContractError` from the ADR-0020 contract; any credential-shaped value found
  by the redaction scan; or `failed-jobs-only-unsupported` resolving to
  "unsupported" -- each halts the migration outright, per this story's Non-goals
  ("Does not proceed with production migration when any required case is
  unsupported").
- **Rollback commands.** Cutover changes only which forge issues publication
  credentials; it performs no data migration. Reverting is: restore the previous
  forge's repository secrets, restore the previous `on:`-trigger forge coordinates if
  they were pinned per-forge, and re-run `ci.yaml` once against the restored
  configuration to confirm PR verification still passes before resuming normal
  publication. No tag, release, alias, or package upload is moved, deleted, or
  reissued as part of either the cutover or its rollback (see "Prohibited recovery
  actions" in `docs/operational.md`).
- **Retained evidence links.** The ADR-0017 evidence-export digest and its retention
  location, and the ADR-0016 preflight and full-scenario closure digests, are recorded
  in the certification report at the time of approval; this document records no digest
  itself because no certification run has occurred in this environment.

## Items explicitly requiring live Gitea -- not executed

- Every positive case in the table above (PR verification, protected dev/stable
  delivery, artifact round-trip, private-CA boundaries, the multi-arch image flow, the
  forge package channel, forge Release, both reusable workflows, and aliases-last
  behavior).
- The live forge denials behind `wrong-ca`, `missing-credential-or-scope`,
  `endpoint-scope-omission`, `restricted-permission-write-refusal`, and
  `failed-jobs-only-unsupported`.
- `absent-default-branch-context` and the `environment: pypi` parse-acceptance probe
  on a real Gitea runner (see `docs/ci/gitea-runners.md`).
- The real failed-jobs-only rerun this story's ADR-0020 contract would then validate:
  revoking a staging credential or redirecting a staging client, observing Gitea's
  native per-job rerun, and recording the actual pre/post state.
- Deriving the real Story 9.1 preflight closure and the real Story 9.2 full-scenario
  closure from actually-executed runs, and comparing their real digests.
- Acquiring a real ADR-0017 evidence export from the pinned Gitea API and resolving a
  real certification report against it.
- The `git-action-release@v2` Gitea-path network/trust-boundary probe (ADR-0022).
- Rehearsing the production-owner cutover itself, including its rollback commands,
  against a certified tuple.
