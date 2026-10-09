# ADR-0031: Every external action is pinned to a reviewed commit

- **Status:** Superseded by ADR-0035
- **Date:** 2026-10-08
- **Deciders:** Maintainer + E012-S01-002
- **Epic:** E012
- **Departs from spec:** n/a
- **Principle(s) in tension:** CI-AR4 (action version policy — floating major as the
  default), CI-AR38 (reviewed SHA for the package-index publisher), Epic 9 forge
  portability

## Context

RT-007 (BL-E011-014) observed that the publish jobs call
`LiquidLogicLabs/git-action-docker-metadata@v6`,
`LiquidLogicLabs/git-action-ca-certificate-import@v3`, `docker/setup-buildx-action@v4`,
`docker/login-action@v3`, `docker/setup-qemu-action@v3` and `actions/checkout@v7` by
tag, while `pypa/gh-action-pypi-publish` in the same file is pinned to a commit. Those
jobs hold `packages: write`, `id-token: write`, `secrets.FORGE_PACKAGE_TOKEN`,
`secrets.DOCKERHUB_TOKEN` and the automatic token.

A tag is a moving ref. Whoever can move it — an upstream maintainer, or anyone who
compromises that account — executes their code inside those jobs, and **no diff appears
in this repository**. That is precisely the `tj-actions/changed-files` failure mode. The
weakest reference in a job sets the trust level of the whole job, so one pinned action
beside five floating ones buys nothing.

CI-AR4 made the floating major the default on the grounds that an upstream security fix
should reach this repository without a manifest edit. That reasoning was sound when the
only alternative was a hand-edited pin. It is no longer the trade on offer: Dependabot
updates a commit pin and rewrites its trailing `# vX.Y.Z` comment in the same pull
request, so currency is preserved and the upgrade becomes a reviewable diff instead of
an invisible ref move.

The project's own guard had the same shape problem. It asserted that a pinned reference
was *40 lowercase hex*, which any SHA copied from anywhere satisfies — the pin could be
moved to a different commit of the same action with every test green.

## Decision

1. **Every external `uses:` reference in every governed definition is pinned to a full
   40-character commit SHA**, carrying a trailing `# vX.Y.Z` comment naming the tag that
   commit held when it was reviewed. This supersedes CI-AR4's floating-major default and
   is recorded as **CI-AR47**.

2. **The pin is data, not a shape.** `tests/ci/support.py::PINNED_ACTIONS` maps each
   action to `(sha, version, reviewed, reason)`, and
   `test_every_pinned_action_is_called_at_exactly_the_commit_it_was_reviewed_at`
   asserts that every `uses:` line names exactly the registry's commit and carries the
   matching version comment. This replaces the former per-line review-date guard, which
   required a `reviewed YYYY-MM-DD` comment within twelve lines of each `uses:` line and
   checked only that the pin was 40 lowercase hex. The registry
   form is strictly stronger (it pins *which* commit) and does not require 44 hand-kept
   comment blocks, one per call site.

   Actions pinned and reviewed on 2026-10-08: `actions/checkout` v7.0.1,
   `actions/setup-python` v7.0.0, `actions/attest-build-provenance` v3.0.0,
   `docker/login-action` v3.7.0, `docker/setup-buildx-action` v4.4.1,
   `docker/setup-qemu-action` v3.7.0, `LiquidLogicLabs/git-action-release` v2.0.11,
   `LiquidLogicLabs/git-action-tag-floating-version` v2.0.7,
   `LiquidLogicLabs/git-action-docker-test` v2.0.6,
   `LiquidLogicLabs/git-action-docker-metadata` v6.2.1,
   `LiquidLogicLabs/git-action-ca-certificate-import` v3.0.7. `pypa/gh-action-pypi-publish`
   keeps its existing pin (v1.14.2, reviewed 2026-09-02, ADR-0009/CI-AR38) — that
   decision is unchanged, it is now the rule rather than the exception.

3. **`actions/upload-artifact` and `actions/download-artifact` stay at `@v4`**, as the
   only registered exception, in `ACTIONS_ON_MOVING_REFS`. Gitea's `act_runner` resolves
   `uses:` through its own action index, where a bare commit SHA is not addressable the
   way it is on GitHub, and the `@v4` pin is already load-bearing for the v4 artifact
   protocol Gitea implements (`test_artifact_actions_remain_on_the_both_forge_v4_pair`).
   Forge portability wins here, as it already did for currency. Neither action is handed
   a credential and both are first-party GitHub, which bounds — it does not remove — the
   residual risk.

4. **`CREDENTIAL_ACTIONS_ON_MOVING_REFS` is now empty.** The rule it encodes is
   unchanged — a credential-handling action is pinned, or its acceptance is written down
   — but this repository currently accepts none of that risk. The five entries it held
   (`LiquidLogicLabs/git-action-release`, `…-tag-floating-version`, `…-docker-test`,
   `…-ca-certificate-import`, `docker/login-action`) and the four ambient holders
   (`actions/checkout`, `actions/attest-build-provenance`,
   `docker/setup-buildx-action`, `docker/setup-qemu-action`) are all pinned by decision
   1.

## Consequences

- An upstream compromise now requires a merged pull request in this repository to reach
  a credentialed job.
- A new third-party action referenced by tag fails
  `test_no_governed_definition_calls_an_action_on_a_moving_ref`, which names the file,
  the line and the reference.
- Upgrades arrive as Dependabot pull requests rather than silently. A security fix is
  therefore a merge away rather than already applied — accepted deliberately, because
  the same mechanism is what an attacker would use.
- Moving a pin now requires editing `PINNED_ACTIONS` as well as the `uses:` line, and
  `tests/ci/` is a CODEOWNERS surface. The registry entry, not a comment, is the record
  that somebody looked at that commit.
- CI-AR4 is superseded for external actions by CI-AR47 and retained only for its
  per-action (not per-owner) classification principle.
