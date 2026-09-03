# ADR-0011: Channel decides the destination set, and how the finalizer reads a skipped job

- **Status:** Accepted
- **Date:** 2026-09-02
- **Deciders:** Maintainer (ravensorb)
- **Principle(s) in tension:** Expressing "only wait for what applies" against `needs:` being static
- **Resolves:** Epic 8 architecture gate finding **F7** (MAJOR)

## Context

`needs:` collapses two unrelated outcomes into one state. A job is `skipped` when an upstream
`needs:` job failed **or** when its own `if:` evaluated false. Publishers are conditional, so:

| Situation | `needs.<job>.result` | Should it block the Release and aliases? |
|---|---|---|
| Docker Hub disabled by policy | `skipped` | **no** |
| Docker Hub enabled, upstream died | `skipped` | **yes** |
| PyPI enabled, upload failed | `failure` | yes |

The first two are indistinguishable from `needs:` alone. `E008-S01-003` said "required failure
**or skip** blocks the Release and every alias", which taken literally is the wrong behaviour: a
release with Docker Hub deliberately off would silently never finalize — green run, aliases
unmoved, no alert.

**"Depend only on what is enabled" cannot be written.** `needs:` is structural, resolved when the
job graph is built, before any job runs; it takes neither an expression nor a computed list. The
only literal way to express it is one finalizer variant per enabled-combination — 2ⁿ jobs, each a
separate `contents: write` grant needing registration, each carrying a copy of the alias logic.
That is the duplication gate finding F8 already warns about.

So the fix is not to make `needs:` cleverer. It is to make **n** small.

## Decision

### 1. Channel decides the destination set, and channel is fixed per workflow file

`dev.yaml` is always the development channel; `release.yaml` is always the stable channel. So the
channel distinction costs no runtime condition at all — the two files simply have different job
graphs.

| Destination | `dev.yaml` | `release.yaml` |
|---|---|---|
| image → active forge registry | **always** | **always** |
| image → Docker Hub | **never** | if `PUBLISH_IMAGE_DOCKERHUB` |
| package → forge Python index | if supported *(host capability)* | if supported *(host capability)* |
| package → TestPyPI | if `PUBLISH_PACKAGE_TESTPYPI` | **never** |
| package → PyPI | **never** | if `PUBLISH_PACKAGE_PYPI` |

No toggle is renamed or removed. What changes is that each toggle is **channel-scoped**, so a
given workflow only ever sees a subset, and development images publish to the forge registry
only.

This leaves each workflow with a small, enumerable set of conditional publishers — two in
`dev.yaml` (forge package index, TestPyPI) and three in `release.yaml` (forge package index,
Docker Hub, PyPI). At that size the finalizer's evaluation is exhaustively testable, which is
the property the original design could not offer.

### 2. Two reasons a job may legitimately be absent, and they are not the same

- **Disabled by toggle** — an operator set `PUBLISH_* = false`. A policy choice.
- **Absent by host capability** — GitHub has no forge Python index, so that destination cannot
  exist there. Not a choice, and not something a toggle should be able to override.

Both produce `skipped`. Both are non-blocking. They are recorded distinctly anyway, because
conflating them is how "GitHub silently stopped publishing packages" becomes indistinguishable
from "someone turned it off deliberately" (gate finding F28).

### 3. The finalizer evaluates results; it does not depend selectively

One finalization *stage* per workflow — implemented as two jobs in the stable channel, so that
ref authority and registry authority are never held together; see "Implemented" below. It
`needs:` **every** publisher in its file, statically, and runs under `if: ${{ !cancelled() }}` — the alternative GitHub documents for `always()`, and correct
here because a cancelled run must never move aliases over a half-published set.

It then reads `needs.<job>.result` against the **enabled set emitted once by the plan job** as a
job output:

- any `failure` or `cancelled` → **fail**, move nothing
- any `skipped` job the enabled set says *should* have run → **fail**
- `skipped` for a destination the enabled set says was off, or unsupported on this host → **ignore**
- otherwise → create the Release, then advance aliases

The enabled set has exactly **one producer**. No publisher re-reads `PUBLISH_*`: two readers of
one truth is the same class of defect as F7 itself, one layer along, and it would let the static
graph and the runtime set disagree.

This stays inside CI-AR37 — a `needs.<job>.result` comparison is not "a repository-specific
all-destination protocol" — and inside CI-AR41, since the enabled set is a job output rather than
a repository-owned schema. It revives neither retired CI-AR22 (publication plan) nor CI-AR23
(aggregate preflight).

## Options rejected

- **A finalizer per enabled-combination.** The literal reading of "only depend on what applies".
  2ⁿ jobs, each a `contents: write` grant, each duplicating the alias rule. Rejected as F8.
- **`if: always()`.** Runs the finalizer even when the workflow was cancelled, so aliases could
  advance over a half-published artifact set. GitHub recommends `!cancelled()` explicitly.
- **Making Docker Hub unconditional for releases.** Would have removed one toggle, but a Docker
  Hub outage or an expired token would then block a release that is otherwise sound. Rejected:
  the cost is one extra conditional, and the release path should not be hostage to an optional
  destination.

## Implemented (E008-S01-003), and one guard amended to match the rule it states

The decision table above is a `jq` program in one step of each channel's finalizer -- shell in
the workflow, not a Python module. E008-S01-003's second directive removed the modules
`scripts/finalizer_gate.py` and `scripts/stable_tags.py` along with their pytest files, on the
precedent set when `scripts/forge_coordinates.py` became a `run:` step. It is a program rather than an `if:`
expression because it is a decision, and a decision spelled as a workflow expression is testable
only by reading it: the two mandatory anchors are asserted by executing the real `run:` body with
the job results substituted into the step's real `env:`, so renaming a publisher breaks the
render rather than silently supplying the old value. Every property the deleted pytest files
proved is now proven the same way, in `tests/ci/test_workflow_contracts.py`.

**Finalization is split across two jobs in the stable channel, and that split forced an amendment
to `test_publisher_credentials_stay_disjoint_between_destinations`.** `finalize` writes refs and
the Release and holds no registry credential; `finalize-image-aliases` moves registry aliases and
holds no `contents: write`. Neither can do the other's damage. But the alias job and the image
publisher address *the same registry*, so they necessarily present the same credential to it --
and the guard's pairwise-across-every-publisher comparison encoded "one publisher per
destination", which had stopped being true. It rejected the correct arrangement while the rule
its docstring states was satisfied.

The comparison is now per **destination class**, derived from what each job does. That is a
narrowing in one direction, so it was paid for in two others, both proven by planted violation:

- a publisher must belong to exactly **one** destination class, so a job that both logs into a
  registry and uploads a package now fails rather than being compared only against itself;
- a package publisher may not declare `packages: write`, which is the only way the automatic
  forge token becomes a registry credential -- and the reason that token can be excluded from the
  comparison at all. Its authority is set per job by `permissions:`, which
  `test_ref_writing_and_registry_alias_privileges_never_meet` audits directly.

The original planted violation -- a registry credential on the package job -- still fails.

## Consequences

- Positive: the channel distinction costs nothing at runtime — it is which file you are in.
- Positive: development images never reach Docker Hub, so dev noise stays off a public registry
  and the dev path holds one fewer credential.
- Positive: the finalizer's decision table is small enough to test exhaustively.
- Trade-off: the finalizer is the most conditional thing in the pipeline and its `if:` is the
  piece most likely to be wrong in a way that only appears on the one release where a destination
  was toggled off. Two anchors are therefore mandatory, not optional: **a disabled optional
  destination must still finalize**, and **an enabled destination that skipped must not**.
- Trade-off: `PUBLISH_IMAGE_DOCKERHUB` in the development channel is now inert. It is not an
  error, it simply has no effect there, and that should be stated where the variable is
  documented rather than left for someone to discover.
