# E009 closure note: which of its ADRs are still live

Written 2026-10-11 by E014-S02-003 (review-coherence CO-07). E009 had no closure note, so a
reader could not tell which of its decision records still bind.

E009 was rescoped on 2026-10-06 to drop live-Gitea-runner certification. On 2026-10-08
ADR-0035 replaced the governed pipeline those ADRs were written for.

| ADR | State | Pointer |
| --- | --- | --- |
| [ADR-0018](../../../../docs/adr/0018-tls-trust-vs-network-egress-separation.md) | **Live** (`Status: Accepted`). ADR-0035 carries it forward; the private-CA import of CI spine AD-18 is where it binds. | `docs/adr/0035-standard-ci-cd-pipeline.md` "Carries forward" |
| [ADR-0015](../../../../docs/adr/0015-gitea-runner-trust-class-routing.md) | Retired: superseded by ADR-0035 | `docs/adr/0035-standard-ci-cd-pipeline.md` "Supersedes" |
| [ADR-0016](../../../../docs/adr/0016-gitea-tuple-evidence-ownership.md) | Retired: superseded by ADR-0035 (first retired by the 2026-10-06 rescope) | ADR-0016 `Status:` line |
| [ADR-0017](../../../../docs/adr/0017-gitea-certification-evidence-authenticity.md) | Retired: superseded by ADR-0035 (first retired by the 2026-10-06 rescope) | ADR-0017 `Status:` line |
| [ADR-0019](../../../../docs/adr/0019-per-job-credential-matrix.md) | Retired: superseded by ADR-0035 | `docs/adr/0035-standard-ci-cd-pipeline.md` "Supersedes" |
| [ADR-0020](../../../../docs/adr/0020-fault-injection-and-cleanup-postconditions.md) | Retired: superseded by ADR-0035 | as above |
| [ADR-0021](../../../../docs/adr/0021-forge-classifier-coordinate-contract.md) | Retired: superseded by ADR-0035 | as above |
| [ADR-0022](../../../../docs/adr/0022-action-governance-and-release-fallback-ownership.md) | Retired: superseded by ADR-0035 | as above |

The current index of every ADR and its marker is `docs/architecture.md` §6.
