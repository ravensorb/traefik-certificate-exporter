# Architecture Spine Rubric Review

**Artifact:** `ARCHITECTURE-SPINE.md`  
**Review lens:** BMad good-spine checklist  
**Date:** 2026-10-04  
**Verdict:** **AMBER — the Gitea package-channel correction is sound, but the spine needs two
clarifications and one responsibility-table repair before it is a fully reliable consistency
contract for Epic 9.**

## Deterministic pass

`lint_spine.py` completed with zero findings. The artifact has no placeholder, duplicate-key,
identifier, or version-pin defect detected by the mechanical gate.

## Checklist assessment

| Good-spine criterion | Result | Assessment |
|---|---|---|
| Fixes the real divergence points for the level below and misses none | Amber | The CI requirements are unusually comprehensive, and the corrected host-specific package channels close the material PyPI/Gitea ambiguity. The responsibility table nevertheless omits one of the five load-bearing workflows. |
| Every rule is enforceable and prevents its stated divergence | Amber | Most rules name contract-test or staging evidence anchors. CI-AR25 does not say whether Gitea's forge-image credential is the automatic workflow token constrained by the restricted permission mode or a separately provisioned registry token; the current workflows choose the former. |
| Nothing deferred can let independently built units diverge | Amber | The split-port Gitea case is explicitly left unrepresented with a revisit trigger, which is adequate. The unselected Gitea tuple is correctly owned by Story 9.1 and consumed by Story 9.2, but the spine should mark that as an open implementation decision rather than reading as if the tuple were already recorded. |
| Named technology is verified-current | Amber | Action policy and reviewed action pins have explicit verification anchors elsewhere, while the Gitea server/runner/image tuple is deliberately not yet selected. That is acceptable for Story 9.1, but the frontmatter's `approved-for-implementation` status overstates how much of CI-AR34 is already settled. |
| Ratifies rather than contradicts the brownfield codebase | Amber | CI-AR21 and the protected-credentials table now agree with the actual host gates: PyPI/TestPyPI are GitHub-only and Gitea's forge package index is required. The image credential wording is less precise than the workflows' concrete use of `secrets.GITHUB_TOKEN`. |
| Covers the driving capabilities | Pass | Build-once verification, destination-local publication, alias ordering, trust bootstrap, runner isolation, Gitea conformance, rerun recovery, evidence retention, and rollback are covered. |
| Does not weaken an inherited spine | Pass | No conflicting inherited `AD` was identified in the supplied architecture context. |
| Every owned dimension is decided, deferred, or open | Pass with note | The operational/environmental envelope is present through runner pools, CA boundaries, staging certification, retention, migration, and rollback. The open tuple selection should be labeled explicitly for handoff clarity. |

## Findings

### High — workflow responsibility map omits `publish-image.yaml`

**Evidence:** CI-AR5 says the topology is a five-file partition and specifically calls
`publish-image.yaml` a reusable workflow that holds every registry credential and one of the two
nested `workflow_call` edges Epic 9 must certify (lines 69–76). The Workflow Responsibilities
table lists only four files (lines 210–214), omitting `publish-image.yaml`.

**Why it matters:** This reproduces, in the document's responsibility map, the exact omission that
CI-AR5 says previously made certification incomplete. A Story 9 implementer using the table as the
handoff summary could certify `verify-build.yaml` but miss the reusable image workflow's secrets,
Buildx behavior, and nested-call compatibility.

**Disposition:** **Autofix.** Add a `publish-image.yaml` row identifying it as a reusable call,
listing forge-registry and conditional Docker Hub secrets, and describing its single multi-platform
publication mutation. Keep the table a partition of the same five files named by CI-AR5.

### Medium — CI-AR25 leaves the Gitea forge-image credential mode ambiguous

**Evidence:** CI-AR25 and the credential table describe the Gitea forge-image credential as a
"scoped protected token" / "scoped registry token" (lines 139–142 and 244–249). The current
`dev.yaml` and `release.yaml` calls pass `${{ secrets.GITHUB_TOKEN }}` as the forge registry
password, not a separately named protected registry secret (`dev.yaml` lines 565–567;
`release.yaml` lines 754–756). The adjacent Epic 9 contract also makes
`TokenPermissionMode = restricted` a deployment precondition because omitted grants can otherwise
widen this automatic token.

**Why it matters:** Two independently implemented Story 9 paths could provision different
credentials: one could retain and constrain Gitea's automatic workflow token, while another could
create a separate registry PAT. Those choices have different rotation, revocation, secret-storage,
and permission-denial evidence.

**Disposition:** **Discuss, then fix.** If the intended design is the current workflow shape, say
that Gitea forge images use the forge-issued workflow token, constrained by the pinned restricted
permission model and protected runner/repository scope. If a separate registry PAT is intended,
the workflows and story contracts must change together. Do not leave "scoped token" to cover both.

### Medium — CI-AR6 retains an override allowance that the active contract retires

**Evidence:** CI-AR6 permits "a documented Gitea override where safe derivation is impossible"
(lines 77–78), while the Configuration Contract says no operator value participates, retires
`FORGE_REGISTRY`, and requires a new variable to be specified only against a demonstrated
split-port deployment (lines 233–240).

**Why it matters:** The earlier sentence can be read as standing authorization to add an ad hoc
override during Epic 9, contradicting the fail-closed coordinate contract and Story 9.1's explicit
ban on operator-supplied registry values.

**Disposition:** **Autofix.** Make CI-AR6 match the active decision: coordinates are derived solely
from action context; a topology that cannot be represented is unsupported until a separately
specified architecture change introduces and validates a new coordinate.

### Low — status obscures the deliberate open Gitea tuple

**Evidence:** The frontmatter says `approved-for-implementation`, while CI-AR34 requires the
supported Gitea server, act-runner, runner image, and action-major tuple to be recorded (lines
170–172), and Story 9.1 still owns selecting and proving that tuple.

**Why it matters:** This is not an implementation blocker—the stories correctly order selection
before certification—but the spine does not visibly distinguish adopted invariants from the tuple
that remains to be discovered and pinned.

**Disposition:** **Defer to an explicit Open Item.** Record that Story 9.1 owns tuple selection,
state the acceptance/rejection conditions, and have Story 9.2 consume only the resulting pinned
tuple. The overall spine may remain implementation-approved once that boundary is explicit.

## Focused assessment of the CI-AR21 / CI-AR25 correction

The correction itself is **accepted**:

- CI-AR21 now separates host capability from operator toggles: TestPyPI/PyPI trusted publishing
  exists only on GitHub, while Gitea's own Python index is its required package channel.
- CI-AR25 now correctly removes any PyPI/TestPyPI credential path from Gitea.
- The Protected Credentials table agrees with both requirements.
- The brownfield workflows agree: their plan jobs report PyPI/TestPyPI as `unsupported` on Gitea,
  and the required Gitea forge-package publisher uses `FORGE_PACKAGE_TOKEN` against the owning
  forge index.

No blocker remains in the package-channel correction. The outstanding credential finding is
narrowly about the **Gitea forge-image** token's identity and lifecycle, not the corrected Python
package path.

## Gate conclusion

Epic 9 may proceed from the corrected package-channel premise. Repair the missing
`publish-image.yaml` responsibility row and remove the CI-AR6 override ambiguity before treating
the spine as the final handoff contract. Resolve the forge-image token identity before provisioning
credentials in Story 9.1; it is the only finding here that requires an architectural choice rather
than editorial alignment.
