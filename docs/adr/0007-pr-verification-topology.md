# ADR-0007: Pull-request verification topology and the secret-free verifier

- **Status:** Accepted
- **Date:** 2026-09-01
- **Deciders:** Maintainer (ravensorb), via Epic E007 Sprint S01
- **Principle(s) in tension:** GitHub Actions overlay (reusable workflows over copy-paste, least
  privilege, fork safety), Core §2 reuse, Core §3 enforce rules mechanically, Core §4 a guard's
  scope must be derived rather than hand-kept
- **Supersedes:** ADR-0005 (CI reusable-workflow wiring for `build.yaml`)

## Context

ADR-0005 recorded a wiring shape in which `build.yaml` orchestrates `build-package.yaml` and
`build-container.yaml` as job-level `uses:` calls with `secrets: inherit`, on push to `main` and on
`v*` tags. That ADR was never implemented as written, and Epic E007 Sprint S01 shipped a materially
different topology. ADR-0005 now describes a system that does not exist, which makes it actively
misleading to the next reader.

Three forces drove the change:

1. **Fork pull requests must be verifiable.** ADR-0005's shape routes every event through workflows
   that hold registry credentials. `build-container.yaml` requests `packages: write`,
   `attestations: write`, and `id-token: write` (`.github/workflows/build-container.yaml:26-30`)
   and performs three `docker/login-action@v4` logins
   (`.github/workflows/build-container.yaml:110-129`). Running that graph — even conditionally — on
   contributor-controlled code is a credential-exfiltration path, so verification and publication
   cannot share one workflow.

2. **Verification must be one graph, not two.** A pull-request pipeline that differs from the
   push pipeline verifies neither: green on a PR stops predicting green on `main`. The verification
   steps therefore belong in exactly one reusable workflow that every event adapter calls with the
   same inputs.

3. **The old test job was both weaker and duplicated.** `.github/workflows/test.yaml` ran `pytest`
   on Python 3.11 only, on `ubuntu-latest`, on push to `main`/`master` and on every
   `pull_request` (see `git show HEAD:.github/workflows/test.yaml`). It was deleted in this sprint;
   its replacement runs the full suite across Python 3.10 through 3.14 on a pinned runner
   (`.github/workflows/verify-build.yaml:203-230`) alongside eight sibling gates.

The shipped shape is a thin event adapter in front of a shared verifier:

- `.github/workflows/ci.yaml` — the pull-request adapter. Trigger is `pull_request` on `main` only
  (`ci.yaml:3-6`), workflow permissions are `contents: read` (`ci.yaml:8-9`), and concurrency is
  keyed on the PR number with `cancel-in-progress` (`ci.yaml:11-13`). Its `plan` job checks out the
  pull request's head SHA with `persist-credentials: false` (`ci.yaml:25-30`), rejects any head SHA
  that is not a full lowercase 40-character Git SHA and asserts the checkout matches it
  (`ci.yaml:36-45`), and reads the committed Poetry version through `tomllib` rather than a
  hand-written TOML scan (`ci.yaml:46-58`). Its `verify` job passes those two immutable values plus
  `channel: ci` to the reusable verifier (`ci.yaml:60-69`). The adapter contains no build, test,
  lint, or publish step of its own.
- `.github/workflows/verify-build.yaml` — the verifier. It exposes `workflow_call` and
  `workflow_dispatch` with the identical input triple `channel`/`package-version`/`source-sha` and
  four outputs (`verify-build.yaml:3-44`), declares `permissions: contents: read` at workflow level
  with no job-level escalation (`verify-build.yaml:46-47`), and runs nine jobs: a `source-integrity`
  gate that revalidates the inputs against the checkout (`verify-build.yaml:50-81`), seven parallel
  quality gates, and a `distribution` job that fans in from all of them
  (`verify-build.yaml:233-243`) to build, smoke-test, and upload the promotable artifact set.

## Options considered

| Option | Pros | Cons | Standards fit |
|--------|------|------|---------------|
| A. Implement ADR-0005 as written — one `build.yaml` orchestrator calling the publisher workflows with `secrets: inherit` for every event | Single entry point; no new files | Fork PRs would execute workflows holding registry credentials and `id-token: write`; verification and publication become inseparable, so "did it pass" and "did it publish" cannot be answered independently | Violates the Actions overlay's least-privilege and fork-safety guidance |
| B. One monolithic `ci.yaml` carrying the verification steps inline, triggered on `pull_request` **and** `push` | Fewest files; no `workflow_call` indirection | The PR and push paths drift the moment one is edited; local `act` execution has to re-enter through an event adapter it cannot supply; the "no secrets" property has to be re-argued per trigger instead of held by one file | Fails Core §2 reuse and makes the mechanical guard's scope ambiguous |
| C. Thin per-event adapters (`ci.yaml` for pull requests, `build.yaml` for pushes and tags) that resolve immutable inputs and call one secret-free reusable verifier; publishers stay separate and keep their credentials | One verification graph for every event; the verifier can be dispatched directly (`workflow_dispatch`, and locally through `docker/act-build.sh`); the secret-free property is a property of one named file set and can be asserted by a test | Two adapter files to keep aligned; adapters must resolve `package-version`/`source-sha` themselves | Satisfies the Actions overlay and Core §2/§3 directly |

## Decision

**Option C.** The following are invariants.

1. **Adapters resolve; the verifier verifies.** An event adapter's only jobs are `plan` (turn a
   mutable event into an immutable `package-version` + `source-sha` pair) and `verify` (call
   `./.github/workflows/verify-build.yaml` with them). No build, test, lint, or publish logic lives
   in an adapter. This is enforced for `ci.yaml`:
   `tests/ci/test_workflow_contracts.py:43-89` pins its trigger, permissions, concurrency and job
   set, requires `github.event.pull_request.head.sha` and `persist-credentials: false`, forbids
   `pull_request_target`, and asserts the strings `poetry build`, `pytest`, `ruff-check`,
   `build-manifest`, `docker build` and `upload-artifact` are absent from the file.

2. **The verifier is mechanically forbidden to publish.** A verifier that can publish is not a
   verifier: its result no longer means "this source is sound", it means "this source is sound *and*
   whatever it did with the credentials was fine". Because fork pull requests must be able to run it,
   the constraint is asserted rather than documented —
   `tests/ci/test_workflow_contracts.py:138-156` requires `permissions: {contents: read}` at
   workflow level, *no* job-level `permissions` key at all, `runs-on: ubuntu-24.04` on every job,
   and the literal absence of each of `secrets:`, `id-token: write`, `packages: write`,
   `attestations: write`, `docker/login-action@`, `actions/cache@`, `runs-on: self-hosted` and
   `secrets: inherit`. `actions/cache@` is on that list for the same reason as the credentials: a
   cache writable from a fork PR is an injection channel into later trusted builds.

3. **Every event is verified by the same graph.** Pull requests enter through `ci.yaml` with
   `channel: ci`. Pushes to `main`/`master` and `v*` tags enter through `build.yaml`, which gains a
   `plan` job and a `verify` job calling `./.github/workflows/verify-build.yaml` with `channel: dev`
   for branch pushes and `channel: stable` for `v*` tags; `build-container` gains a `needs:` on that
   verify job so no image is published from source that has not passed the verifier. This is
   strictly stronger than the deleted `test.yaml`: the same nine-gate graph, five Python versions
   instead of one, a pinned runner, and a gate on publication rather than a parallel advisory job.

4. **Governance is deliberately two-tier.** The tiers are not the same rule applied unevenly; they
   answer different questions.

   | Tier | Applies to | Rules |
   |---|---|---|
   | Repo-wide supply chain | every workflow and composite action in `.github/` | third-party actions must come from an approved owner, and must be pinned to the maintained floating major alias (`vN`) |
   | Verifier isolation | the named verifier set only — `ci.yaml`, `verify-build.yaml` | no secrets, no `id-token`/`packages`/`attestations` write, no registry login, no cache, no self-hosted runner |

   The second tier is deliberately *not* repo-wide. `build-package.yaml`, `build-container.yaml`
   and `release.yaml` exist to publish; withholding credentials from them would not harden anything,
   it would break them. `build-package.yaml` declares `contents: write`
   (`.github/workflows/build-package.yaml:8-9`), `build-container.yaml` declares `packages: write`,
   `attestations: write` and `id-token: write` (`.github/workflows/build-container.yaml:26-30`), and
   `release.yaml` declares `contents: write` and `pull-requests: write`
   (`.github/workflows/release.yaml:6-8`). Those are correct for their role. The split is what makes
   "no credentials" a meaningful assertion about the verifier instead of an aspiration about the
   repo.

5. **The guard's scope is a property of the rule, not of convenience.** The act-independence check
   already derives its scope from the filesystem (`WORKFLOWS.glob("*.yaml")`,
   `tests/ci/test_workflow_contracts.py:177-183`) and therefore covers files added later. The
   action-owner and floating-major check is currently scoped to the hand-named `GOVERNED_WORKFLOWS`
   tuple (`tests/ci/test_workflow_contracts.py:15-16`, `:186-196`); as a tier-1 rule it must be
   widened to the same derived scope, so that a new workflow cannot introduce an unreviewed action
   owner by simply not being on a list.

6. **Retirement path for the legacy files.** `.github/workflows/test.yaml` is deleted; its coverage
   is subsumed by invariant 3, and no replacement is planned. `build.yaml` is *retained* and
   re-shaped as the push/tag adapter rather than retired. `build-package.yaml`,
   `build-container.yaml` and `release.yaml` are retained as publishers and stay outside the
   verifier tier. ADR-0005 is superseded by this ADR.

The verifier is reachable without an adapter — `workflow_dispatch` takes the same inputs
(`verify-build.yaml:3-17`), and `docker/act-build.sh` drives that entry point locally with no
`--secret` and no `--env-file`, asserted at `tests/ci/test_workflow_contracts.py:159-174`. That
property is what keeps the adapters thin: there is nothing an adapter could usefully add.

## Consequences

- Positive: a fork pull request can run the complete verification graph, because there is nothing in
  it worth stealing. Contributors get real CI without a maintainer approving each run.
- Positive: "verified" and "published" are separate, individually inspectable facts. The verifier's
  four outputs (`verify-build.yaml:32-44`) let a publisher consume a verification result rather than
  re-deriving one.
- Positive: pushes and tags are now verified by nine gates across five Python versions, where before
  this sprint's `test.yaml` deletion they would have been verified by nothing, and before that by a
  single-version `pytest`.
- Positive: the isolation constraints are executable. `tests/ci/test_workflow_contracts.py` runs as
  the `workflow-policy` pre-commit hook (`.pre-commit-config.yaml:12-17`) and again inside the
  verifier's own `actionlint` job (`verify-build.yaml:177-179`), so a regression fails locally and
  in CI rather than being noticed in review.
- Trade-off accepted: two adapters must stay aligned. They share the verifier but each resolves its
  own `plan` inputs, and a change to the input contract touches both. The contract test pins
  `ci.yaml`'s `verify` job exactly (`tests/ci/test_workflow_contracts.py:63-73`); an equivalent
  assertion for `build.yaml`'s `verify` job is required to close the gap.
- Trade-off accepted: the verifier cannot use `actions/cache@`, so every job reinstalls its
  dependencies. Wall-clock time is spent to keep a fork-writable cache out of the trusted build path.
- Trade-off accepted: `channel` is a plain string input validated inside the verifier
  (`verify-build.yaml:62-71`) rather than a typed enum, because `workflow_call` inputs offer no
  enumeration; a bad value fails at the first gate instead of at definition time.
- Follow-ups: widen the action-owner/floating-major assertion from `GOVERNED_WORKFLOWS` to a derived
  repo-wide scope (invariant 5), and add a `build.yaml` adapter assertion mirroring the `ci.yaml` one.

## Open questions

- **Tier-1 widening will surface existing violations.** Applied repo-wide today, the approved-owner
  set `{actions, docker, pypa, LiquidLogicLabs}` (`tests/ci/test_workflow_contracts.py:16`) rejects
  `googleapis/release-please-action@v5` (`release.yaml:16`), `snok/install-poetry@v1`
  (`build-package.yaml:39`), and `cadifyai/poetry-publish@v0.1.1` (`build-package.yaml:46`) — the
  last also fails the floating-major rule, being pinned to `v0.1.1`. Whether each is allowlisted with
  recorded justification or replaced is an open decision, not settled by this ADR.
- **The `build.yaml` re-shape is landing in parallel with this ADR.** At the time of writing,
  the committed `build.yaml` still triggers on push to `master`/`main` and `v*`
  (`.github/workflows/build.yaml:3-9`) and calls only `build-container` with `secrets: inherit`
  and no verification job (`.github/workflows/build.yaml:16-18`). Invariant 3 records the decided
  shape; a reader should confirm the file matches it before relying on the claim that non-PR events
  are verified.
- **`build-package.yaml` retains two trigger paths** — `workflow_call` and `release: published`
  (`build-package.yaml:2-6`) — an unresolved question inherited from ADR-0005 and not settled here.
