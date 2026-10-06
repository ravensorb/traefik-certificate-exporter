# Adversarial Architecture Review: CI/CD Pipeline Spine

## Verdict

**CHANGES REQUIRED — 2 blockers, 4 major findings, 2 minor findings.**

The correction to CI-AR21/CI-AR25 removes the earlier cross-forge PyPI credential
contradiction: a Gitea run cannot select PyPI/TestPyPI and a GitHub run cannot select a
forge Python index. That is a useful policy decision. It does not, however, define a complete
Gitea package-publication contract. Independently implemented event-owner, package-publisher,
runner, and certification units can obey every stated rule while selecting incompatible package
coordinates, credentials, and recovery behavior. The spine is therefore not yet sufficiently
deterministic for Epic 9 certification.

This review treats a downstream unit as compliant when it follows the literal CI-AR rules; it
does not assume knowledge held only in the current workflow implementation or an operator's
head. Each finding constructs two such units and shows the conflict that remains.

## Findings

### B1 — The required Gitea Python destination has no canonical coordinate or owner contract

**Rules involved:** CI-AR6, CI-AR21, CI-AR25, CI-AR36; Configuration Contract; Trigger and
Coordinate Guards.

CI-AR21 requires the "owning-forge Python index," while CI-AR6 and the coordinate guard say
coordinates are projected from `github.server_url` and `github.repository` alone. Neither says
what the package owner is or gives the canonical upload endpoint.

Two independently built, literally compliant units can do this:

- Unit A takes the repository owner from `owner/repo` and uploads to the owner's package API,
  treating "owning forge" as repository owner.
- Unit B treats the repository as the ownership scope and constructs a repository-scoped package
  endpoint, or uses a maintained generic uploader configured with a simple-index URL rather than
  an upload URL.

Both use only action context, both publish to the active Gitea, and both avoid PyPI. They do not
address the same remote resource. This is particularly dangerous because the destination is
always required: the pipeline has no supported mode in which certification can bypass the
ambiguity.

The retirement of `FORGE_REGISTRY` does not resolve this. Lines 233–240 reason only about the
container registry authority. A Python registry commonly has a path-level owner/API contract,
not merely a host authority, so "there is nothing to validate" at lines 274–276 is too broad.

**Required change:** Define, as an invariant, the canonical Gitea package upload coordinate,
including scheme/authority derivation, API path template, owner selection and normalization, and
the exact distinction between upload and install/simple-index URLs. Name the maintained upload
action or protocol adapter expected to consume it. Add a contract test with an organization-owned
repository and a non-default server port/base path. If any component is not safely derivable from
the two context fields, specify one narrowly scoped protected variable rather than relying on an
operator convention.

### B2 — CI-AR25 does not define a usable or separable Gitea authentication interface

**Rules involved:** CI-AR24, CI-AR25, CI-AR34, CI-AR40; Protected Credentials table.

The spine says Gitea uses "scoped protected tokens" and lists a scoped registry token and scoped
package token. It does not define the associated login identity, secret names, token permissions,
or whether the two rows must be distinct principals/tokens.

Two compliant units can therefore do this:

- Unit A accepts one forge service-account token with both image and package scopes, passes it to
  separate jobs, and supplies the service-account name from an undocumented runner variable.
- Unit B requires distinct image and package tokens, uses the repository owner as the image login,
  and expects a fixed token username for the package uploader.

Both can claim each publisher receives only "its destination's credentials": in Unit A, the same
credential happens to authorize both destinations; in Unit B, credentials are physically
separate. Yet their workflow-call secret interfaces and staging setup are incompatible. Unit A
also weakens the intended blast-radius isolation without violating any explicit MUST.

CI-AR40 sharpens the image/package separation but still does not say whether credential identity
must be distinct. CI-AR34 requires separate runner pools, but runner-pool isolation cannot repair
an over-scoped shared credential.

**Required change:** Specify the complete secret interface for each Gitea destination: login
identity plus token, exact minimum scopes, protected-environment placement, whether tokens and
principals MUST be distinct, and which workflow owns each secret. State that no username or token
may be inferred from repository ownership unless Gitea's authenticated API contract guarantees
it. Epic 9 certification must demonstrate negative authorization (the image credential cannot
publish packages and the package credential cannot push images), not just successful uploads.

### M1 — The host capability decision can diverge between planning and publishing units

**Rules involved:** CI-AR1, CI-AR6, CI-AR21, CI-AR25, CI-AR40.

CI-AR21 correctly forbids the Gitea PyPI/TestPyPI path, but "Gitea" versus "GitHub.com" lacks a
single normative classifier and output contract. One unit can classify by `server_url ==
https://github.com`; another can classify by the presence or value of a forge-specific context
field. On a staged Gitea with a GitHub-compatible context surface, they can disagree.

Example: the plan job classifies the host as Gitea and enables the required forge-package job,
while a package job's condition classifies it as unknown/GitHub and skips. CI-AR40 will then either
block forever (if the plan output is authoritative) or incorrectly accept the skip (if each job
recomputes support). Both implementations can cite CI-AR6 and the fail-closed guard.

**Required change:** Define one forge-classification operation and one authoritative plan output
consumed by every job. Enumerate accepted normalized values (`github.com`, supported Gitea tuple,
unknown), require unknown to fail before secret selection, and prohibit destination jobs from
recomputing forge kind or capability.

### M2 — The pinned runner tuple omits the package and release actions that Epic 9 must prove

**Rules involved:** CI-AR3–CI-AR5, CI-AR34–CI-AR35, CI-AR38.

CI-AR34 records an "action-major tuple," while CI-AR4 makes version policy per action and CI-AR38
pins the PyPI action to a full SHA. The tuple's schema and membership are undefined. A certification
unit can record checkout/artifact/QEMU/Buildx majors and call the tuple complete; another can add
the Gitea package uploader, release action, and every transitive/nested reusable-workflow action.
Both satisfy the prose. Only the latter proves the interfaces most likely to diverge on Gitea.

This is amplified by the CI-AR5 correction: `publish-image.yaml` was added because its nested
`workflow_call` edge and credentials had previously escaped certification. The same class of
omission remains possible for actions within nested workflows because the tuple is not defined as
the transitive closure of executed action references.

**Required change:** Define the pinned tuple as the complete transitive set of server version,
runner version, runner image digest, reusable-workflow edges, and action references actually
executed in each certified scenario. Record resolved commits for floating majors and full SHAs for
credential-bearing actions. Certification should fail when the observed set differs from the
recorded set.

### M3 — One-build image fan-out and failed-job-only recovery admit incompatible partial state

**Rules involved:** CI-AR20, CI-AR26, CI-AR29, CI-AR35, CI-AR38–CI-AR40.

CI-AR39 requires one Buildx invocation to the required forge registry and optional Docker Hub.
The aggregate preflight and idempotent remote reconciliation requirements are retired. If the
forge push succeeds and Docker Hub fails, the image job fails after mutating one destination.

Two compliant recovery units can then conflict:

- Unit A reruns the failed image job, re-pushing the immutable forge tag before retrying Docker
  Hub because CI-AR38 says to rerun failed jobs.
- Unit B treats the existing forge tag as an immutable conflict and halts/escalates because
  CI-AR38 also says an immutable conflict halts publication.

The rules do not distinguish an exact same-digest replay from a conflicting immutable write, nor
say whether the chosen actions are guaranteed to accept the former on both registries. Epic 9's
required failed-jobs-only rerun can therefore pass or fail based on an adapter's undocumented
behavior rather than the architecture.

**Required change:** Define same-digest replay semantics for every immutable image destination and
the evidence used to distinguish it from a conflict. The certification scenario must inject a
second-registry failure after the forge push, rerun only the image job, and prove no rebuild,
same digest, and successful convergence. If ordinary actions cannot guarantee that behavior,
split publication mechanics or narrow the recovery claim.

### M4 — Stable Release and Git-alias mutation credentials are absent from the credential model

**Rules involved:** CI-AR24, CI-AR25, CI-AR28–CI-AR29, CI-AR35; Protected Credentials table.

The pipeline must create an active-forge Release and move `vX.Y`/`vX` Git tags, but CI-AR25 and
the protected-credentials table define only package and image credentials. On GitHub, an
implementation can use the repository token. On Gitea, one unit can reuse the package token,
another the image token, and another the ambient actions token. All are plausible because no rule
assigns these mutations a credential or minimum scope.

These choices are not interchangeable: package/image tokens ought not have repository write
scope, while an ambient repository token may differ across the pinned Gitea/runner tuple. The
omission also prevents CI-AR24's least-privilege claim from being tested.

**Required change:** Add forge Release and Git alias mutation rows to the credential matrix for
both forges, define minimum permissions and job ownership, and require a distinct protected
repository-mutation credential on Gitea if its job token cannot meet the contract. Certify denied
use from package/image jobs.

### m1 — `publish-image.yaml` secret declaration semantics are not reconciled with disabled targets

**Rules involved:** CI-AR5, CI-AR20, CI-AR24, CI-AR40.

CI-AR5 says the reusable workflow "holds every registry credential" while CI-AR24 says disabled
targets receive no secret and CI-AR40 says the image job receives only enabled credentials. A
caller can comply by declaring optional Docker Hub secrets in `workflow_call` but omitting values
when disabled; another can pass empty strings; another can use `secrets: inherit`. Those are
materially different trust boundaries, yet all may be described as the workflow holding the
credentials.

**Required change:** State that reusable workflows enumerate explicit optional secret inputs,
callers pass no disabled-target secret, empty-string substitution is not equivalent to absence,
and `secrets: inherit` is forbidden on publisher calls. Include this in the workflow contract
tests and Gitea nested-call certification.

### m2 — Private-CA ownership permits incompatible trust propagation

**Rules involved:** CI-AR24, CI-AR34–CI-AR36; Protected Credentials table.

The table distinguishes runner-bootstrap CA from an optional job-level downstream CA, but it does
not bind the latter to destinations. A runner unit can install one private root globally so action
resolution and all publishers trust it; a publisher unit can import the root only for Gitea API,
registry, and package endpoints. Both can claim support for a private CA and minimal mounts, but
the first silently expands trust to GitHub/PyPI/Docker Hub and survives across jobs if the runner
is not truly ephemeral.

**Required change:** Define destination-scoped CA injection, prohibit global mutation by workflow
jobs, identify which Gitea endpoints share the staging CA, and require an after-job proof that the
ephemeral workspace/trust changes are gone. Runner-bootstrap trust must remain a host
administration precondition, not a publisher secret.

## CI-AR21/CI-AR25 Correction Assessment

The corrected rules now agree on the high-level channel matrix:

| Forge/channel | Development | Stable | Credential mode |
|---|---|---|---|
| GitHub package | optional TestPyPI | optional PyPI | GitHub OIDC trusted publishing |
| Gitea package | required forge index | required forge index | protected Gitea package credential |
| Cross-forge package | absent | absent | no credential path |

That closes the policy-level contradiction. It does **not** yet close the interface-level gap:
the Gitea row lacks a canonical endpoint, owner, uploader, username, secret names, minimum scopes,
and replay behavior. Until those are made normative, the correction cannot be certified by an
independently built Epic 9 harness.

## Minimum Acceptance Bar Before Epic 9 Execution

1. Resolve B1 and B2 in the spine and credential/configuration tables.
2. Make one forge/capability plan output authoritative for all destination conditions.
3. Define the certification tuple as the observed transitive workflow/action set, including the
   corrected `publish-image.yaml` nested edge.
4. Specify same-digest rerun behavior and test partial image fan-out failure.
5. Add explicit Release/Git-alias credentials and negative-scope tests.
6. Certify explicit reusable-workflow secret passing and destination-scoped private CA handling.

With these changes, downstream workflow and staging-harness units can be built independently and
still converge on the same destinations, identities, trust boundaries, and recovery outcome.
