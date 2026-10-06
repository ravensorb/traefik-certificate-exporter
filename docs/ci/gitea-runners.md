# Gitea runner trust, CA bootstrap, and credential isolation

**Rescope note (2026-10-06):** Epic E009 was rescoped to drop live-Gitea-runner certification.
No live runner is provisioned for this project; the design below documents intent and the
structural guards it is checked against, not executed runtime behavior. Items marked **requires
live Gitea** are formally out-of-scope, tracked as resolved (`wontfix`) backlog issues
(`BL-E009-007` through `BL-E009-013`).

Status: **partially executed**. This runbook was written against the pinned
`traefik-certificate-exporter` CI/CD pipeline for E009-S01-001, but this repository has
no live Gitea server, no registered act-runner, and no provisioned credentials in the
environment it was authored in. Everything below marked **requires live Gitea** has
not been executed; the structural guards in `tests/ci/` that *would* check it once a
real Gitea exists are implemented and passing against the committed workflow text.

## Trust ordering

The job-level CA import this story adds (`LiquidLogicLabs/git-action-ca-certificate-import@v3`)
exists because runner-host bootstrap trust (the OS/system CA store a registered runner
starts with) covers `git`/OS tooling only — Node.js (`actions/attest-build-provenance`,
`LiquidLogicLabs/git-action-release`, `LiquidLogicLabs/git-action-tag-floating-version`)
bundles its own Mozilla root list, and Python's `requests`/`certifi`
(`pypa/gh-action-pypi-publish`) bundles its own CA store, independent of the OS trust
store either runs on. A private Gitea CA reaching a job's publication step therefore
needs importing *after* the job starts, on top of bootstrap trust, not instead of it.

```mermaid
sequenceDiagram
    participant Runner as Registered act-runner (bootstrap trust)
    participant Gitea as Gitea server / forge API
    participant Job as Credential-bearing job
    participant CA as Downstream private CA (job-level import)

    Note over Runner: Bootstrap trust installed at runner provisioning time,<br/>outside any workflow job (operational prerequisite).
    Runner->>Gitea: Register runner identity
    Runner->>Gitea: Resolve forge coordinates (classifier step, ADR-0021)
    Runner->>Gitea: Download pinned actions (SHA/floating-major, ADR-0009/ADR-0022)
    Runner->>Job: Schedule job onto eligible registration (ADR-0015, requires live Gitea)
    Note over Job: Checkout runs first; it needs only bootstrap trust.
    Job->>CA: Import downstream CA (gated on secrets.<DESTINATION>_CA_CERTIFICATE != '')
    Note over CA: Job-level CA import action (ADR-0018). Scoped to this job only;<br/>never the job's first or last step (tests/ci/test_runner_trust_routing.py).
    Job->>Gitea: Credentialed call to the protected endpoint (package upload, Release, etc.)
```

Bootstrap trust precedes registration, forge-coordinate resolution, and action
download; downstream (job-level) trust import happens strictly after job start and
strictly before the credentialed call it protects. This ordering is checked
structurally (step placement, not live timing) by
`tests/ci/test_runner_trust_routing.py::test_ca_import_steps_follow_checkout_and_precede_the_credentialed_call`.

## Credential matrix (ADR-0019)

See `tests/ci/test_credential_matrix.py::CREDENTIAL_MATRIX` for the authoritative,
test-checked table (principal, secret names, minimum scopes, protected
owner/environment, permitted/forbidden mutations per job). Summary:

| Workflow | Job | Principal | Secrets | Forbidden secrets |
|---|---|---|---|---|
| dev.yaml | `publish-package-forge` | `FORGE_PACKAGE_TOKEN` bearer | `FORGE_PACKAGE_TOKEN`, `GITEA_PACKAGE_INDEX_CA_CERTIFICATE` | `DOCKERHUB_*` |
| dev.yaml | `publish-package-testpypi` | OIDC trusted publishing | none | all |
| dev.yaml | `publish-image` | automatic repository token | `GITHUB_TOKEN` | `FORGE_PACKAGE_TOKEN`, `DOCKERHUB_*` |
| dev.yaml | `finalize-dev-alias` | automatic repository token | `GITHUB_TOKEN` | `FORGE_PACKAGE_TOKEN` |
| release.yaml | `publish-package-forge` | `FORGE_PACKAGE_TOKEN` bearer | `FORGE_PACKAGE_TOKEN`, `GITEA_PACKAGE_INDEX_CA_CERTIFICATE` | `DOCKERHUB_*` |
| release.yaml | `publish-package-pypi` | OIDC trusted publishing | none | all |
| release.yaml | `publish-image` | automatic repository token + optional Docker Hub | `GITHUB_TOKEN`, `DOCKERHUB_*` | `FORGE_PACKAGE_TOKEN` |
| release.yaml | `finalize` | automatic repository token (contents: write) | `GITHUB_TOKEN`, `GITEA_FORGE_API_CA_CERTIFICATE` | `FORGE_PACKAGE_TOKEN`, `DOCKERHUB_*` |
| release.yaml | `finalize-image-aliases` | automatic repository token + optional Docker Hub | `GITHUB_TOKEN`, `DOCKERHUB_*` | `FORGE_PACKAGE_TOKEN` |
| release.yaml | `attest` | GitHub OIDC attestation identity | none | all |

Every row is cross-checked against the workflow files' actual `secrets:`/`permissions:`
blocks by `tests/ci/test_credential_matrix.py`; a secret referenced by a job but absent
from its row (or declared forbidden for it elsewhere) fails that suite.

**Requires live Gitea** (not executed here): attempting each destination's mutation
with another destination's credential and observing the forge deny it
(`tests/ci/test_credential_matrix.py::test_cross_destination_mutation_is_denied_by_the_forge`,
marked `@pytest.mark.requires_live_gitea`).

## Action governance (ADR-0022)

Every externally-referenced action in the observed transitive closure (derived from the
committed workflows/composites, not hand-listed) has a governance row in
`tests/ci/test_action_governance.py::ACTION_GOVERNANCE`: publisher, trust class,
maintenance status, license, GA status, supported major, and required pin kind.
Credential-bearing or unapproved-third-party actions require a full-SHA pin
(`tests/ci/support.py::SHA_PINNED_ACTIONS`) or an explicit accepted-risk entry
(`tests/ci/support.py::CREDENTIAL_ACTIONS_ON_MOVING_REFS`, each with an ADR). Every
action in this repository's closure today is GA, actively maintained, and
permissively licensed; no non-GA exception currently exists.

**Requires live Gitea** (not executed here): probing whether
`LiquidLogicLabs/git-action-release@v2`'s Gitea-path platform detection makes a network
request, and which trust boundary covers it — the Story 9.1 predecessor decision that
governs whether the tuple proceeds with the primary release action or an ADR accepts
the `softprops/action-gh-release` fallback
(`tests/ci/test_action_governance.py::test_release_action_gitea_path_probe_records_network_and_trust_boundary`).

## Forge classifier (ADR-0021)

One authoritative forge classifier/coordinate-projection step (the "Derive forge
coordinates" step in the `plan` job) is duplicated byte-identically across `dev.yaml`
and `release.yaml`; every other job consumes `needs.plan.outputs.*` rather than
recomputing coordinates. `tests/ci/test_forge_coordinates.py` proves the two copies are
identical, executes the real bash body against table-driven cases (GitHub/Gitea
recognition, case/trailing-slash normalization, unknown-forge and https-only rejection
reasons), and documents why ADR-0021's "malformed registry" and "same-host/path
mismatch" taxonomy categories are structurally vacuous now that `FORGE_REGISTRY` is
retired.

## Runner trust-class routing (ADR-0015)

**Requires live Gitea** (not executed here, in full): ADR-0015's proof obligation is
entirely behavioral — identify the concrete Gitea scheduling primitive, capture a
sanitized eligibility matrix showing the protected registration ineligible for every
untrusted context, and submit a credential-free sentinel job recording the selected
runner identity and the scheduler's denial evidence, including a planted
overlapping-scope negative case
(`tests/ci/test_runner_trust_routing.py::test_protected_registration_is_mechanically_ineligible_for_untrusted_jobs`).

What *is* checked statically: the topology has not silently grown a second
`runs-on` trust-class label ahead of the later ADR that decision requires, and the
CA-import steps this story adds appear only in credential-bearing jobs, strictly after
checkout and strictly before the job's last (credentialed) step
(`tests/ci/test_runner_trust_routing.py`).

## Preflight tuple record

Per the Definition of Done, the preflight tuple record names the supported Gitea
server, act-runner, runner image, action-resolution source, adopted-action set,
`environment:` parse result, minimum restricted-permission version, and registration
scopes, scoped to Story 9.1's own structural probes and secondary smoke scenarios
(ADR-0016). **This record cannot be populated here**: every field is an observation
about a running Gitea/act-runner pair this environment does not have, and fabricating
values would misrepresent evidence that was never collected. The schema and acceptance
rules this record must satisfy (action governance fields, pin-kind requirements,
non-GA/ADR requirement) are implemented and tested in
`tests/ci/test_action_governance.py`; populating the record itself is listed as a
backlog item (see the issues filed alongside this story).

## Items explicitly requiring live Gitea — not executed

- The ADR-0015 scheduling-primitive configuration + behavioral denial proof (sanitized
  eligibility matrix, credential-free sentinel job, planted overlapping-scope negative).
- Cross-destination credential-denial proof against a running forge (ADR-0019).
- The `git-action-release@v2` Gitea-path network/trust-boundary probe and the resulting
  release-fallback ADR decision, if the primary probe fails (ADR-0022).
- node24 action execution and `environment: pypi` parse-acceptance probes on a real
  Gitea runner; nested `workflow_call` edge traversal; cross-workflow artifact download;
  local composite-action resolution — all of Story 9.1's structural probe set.
- Populating the preflight tuple record itself with observed (not fabricated) evidence.
- Confirming `TokenPermissionMode = restricted` is an enforced organisation/repository
  precondition via an actual denial test (a settings read-back is not evidence).
- Verifying whether the job-level CA import action's OS-trust-store installation is
  sufficient for Node.js/Python's independently-bundled CA stores, or whether
  `NODE_EXTRA_CA_CERTS`/`SSL_CERT_FILE` must also be set — an assumption in this
  implementation, not confirmed against live runner behavior.
