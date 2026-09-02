# ADR-0009: Action pin policy — floating major by default, reviewed SHA for credential handlers

- **Status:** Accepted
- **Date:** 2026-09-02
- **Deciders:** Maintainer (ravensorb)
- **Principle(s) in tension:** Upgrade convenience versus blast radius of a supply-chain compromise
- **Resolves:** Epic 8 architecture gate finding **F1** (BLOCKER)

## Context

Three artifacts disagreed about how `pypa/gh-action-pypi-publish` must be pinned, and the
disagreement made story `E008-S01-001` unbuildable — it could not go green against the shipped
contract tests.

| Source | Rule |
|---|---|
| `ARCHITECTURE-SPINE.md` CI-AR4 | approved owners "use a documented floating major when available"; other third parties "require a reviewed SHA" |
| `ARCHITECTURE-SPINE.md` CI-AR38 | package upload uses `pypa/gh-action-pypi-publish@<reviewed-full-commit-sha>` |
| `tests/ci/test_workflow_contracts.py` | every external `uses:` from an approved owner must match `(?:release/)?v[0-9]+` |

`pypa` is an approved owner, so CI-AR4 and the guard both said *floating major* while CI-AR38
said *SHA*. The guard's regex was widened to accept `release/vN` specifically because pypa
publishes its floating major as a branch rather than a tag, which made the collision exact.

## The distinction the three sources were missing

They were not answering the same question. A floating major is a **moving ref**, and whether
that is good depends entirely on what the action is handed:

- For `actions/checkout` or `docker/setup-buildx-action`, a moving ref is the right trade: a
  security fix ships without a manifest edit, and the action holds nothing worth stealing.
- For an action handed a **publication credential**, it inverts. Whoever can move the branch can
  exfiltrate the PyPI token on the next run, with no diff in this repository to review. The
  upgrade convenience buys little; the blast radius is the ability to publish arbitrary code
  under this project's name.

So the split is **per action, not per owner**. That is why CI-AR4 and CI-AR38 could both be
right and still contradict each other: CI-AR4 classifies by owner, and the property that matters
is not a property of the owner.

## Options considered

1. **Use `@release/v1` and amend CI-AR38.** Simplest — no guard change, no ADR, and pypa's own
   documented recommendation. Rejected: it resolves the contradiction by discarding the stronger
   requirement, and leaves a moving ref in front of the publication token.
2. **SHA-pin every third-party action.** Most defensible in isolation. Rejected: it rewrites
   CI-AR4 wholesale, touches every workflow, and turns each routine bump into a manifest edit —
   paying the cost everywhere to solve it in one place.
3. **Per-action exception table (chosen).** Floating major stays the default for approved owners;
   named credential-handling actions require a reviewed full commit SHA.

## Decision

`SHA_PINNED_ACTIONS` in `tests/ci/test_workflow_contracts.py` is a registry of granted
exceptions to the floating-major default. It currently holds one entry,
`pypa/gh-action-pypi-publish`. `pypa` remains an approved owner; only this action of theirs is
pinned harder.

Adding an entry **is** the grant, and each entry needs an ADR — the same convention
`RELEASE_FINALIZER_JOBS` follows under ADR-0006. This is a deliberately hand-kept list, not a
derived scope, because it records decisions rather than facts about the tree.

Implementation must resolve, review and record the real full commit SHA when the publisher lands
(CI-AR38); the guard enforces the *shape* (40 lowercase hex), not the value.

## Enforcement — two guards, because the first cannot see far enough

- `test_tier_one_actions_use_approved_owners_and_floating_major_aliases` branches on membership
  of `SHA_PINNED_ACTIONS`: registered actions must match a 40-character SHA, everything else must
  match the floating-major alias.
- `test_credential_handling_publishers_are_registered_as_sha_pinned` supplies the **reach**. The
  first guard only fires on actions already registered, so a *newly added* credential handler
  would silently take the floating-major branch. This one derives candidates from the workflows
  instead — any action whose name contains `pypi` or `publish` must be either registered or
  explicitly recorded as not credential-handling.

Both were verified by planting a violation: `pypa/gh-action-pypi-publish@release/v1` fails the
first, and an unregistered `pypa/some-new-pypi-publish@v3` fails the second.

## Consequences

- Positive: the action holding the PyPI token cannot be swapped under this repository without a
  reviewed commit in it.
- Positive: the reach guard means the policy applies to publishers nobody has thought of yet, not
  only to the one named today.
- Trade-off: `pypa/gh-action-pypi-publish` no longer receives upstream fixes automatically. Its
  SHA must be reviewed and bumped deliberately; Dependabot's `github-actions` ecosystem will
  propose the bump, and the review is the point rather than an obstacle.
- Trade-off: the exception table is hand-kept and can drift from reality. The reach guard is what
  keeps that drift visible.

## Follow-ups

- `ARCHITECTURE-SPINE.md` CI-AR4 is amended to say the classification is per action for
  credential handlers, so the spine no longer contradicts CI-AR38.
- When `release.yaml` lands (E008-S01-003), record the reviewed SHA and the date it was reviewed
  alongside the `uses:` line.
