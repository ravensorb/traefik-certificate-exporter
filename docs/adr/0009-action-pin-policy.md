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
- `test_every_credential_handling_action_is_pinned_or_its_risk_is_recorded` supplies the **reach**. The
  first guard only fires on actions already registered, so a *newly added* credential handler
  would silently take the floating-major branch. This one derives candidates from the workflows
  instead — any action whose name contains `pypi` or `publish` must be either registered or
  explicitly recorded as not credential-handling.

Both were verified by planting a violation: `pypa/gh-action-pypi-publish@release/v1` fails the
first, and an unregistered `pypa/some-new-pypi-publish@v3` fails the second.

## Amended at E008 sprint closure: the classification is derived, and the inverse registry is explicit

Two things were wrong with the reach guard, and the first caused the second.

**The candidate set was the action's name.** The reach guard selected candidates by matching
`pypi|publish` against an action's repository name. That is a
hand-enumerated scope wearing a derivation's clothes, and it is the defect class this project
keeps finding: the rule was right and the set was wrong. Four references shipped in E008 are
handed a publication credential and match neither word, so the guard skipped them and the
floating-major branch passed them:

| Action | What reaches it |
|---|---|
| `LiquidLogicLabs/git-action-release` | `contents: write` `GITHUB_TOKEN` as `token`, in the repository's only ref-writing job |
| `LiquidLogicLabs/git-action-tag-floating-version` | the same token, through `GIT_CONFIG_VALUE_0` on its `env:` |
| `docker/login-action` | `DOCKERHUB_USERNAME`, `DOCKERHUB_TOKEN` |
| `LiquidLogicLabs/git-action-docker-test` | nothing *passed* — it runs after both logins and can read `~/.docker/config.json` |

The classification is now derived from what an action **receives**: a `secrets.*` expression
reaching it through `with:`/`env:` or a job-level `secrets:` block, or its position after a
registry login in the same job. The last case is why "what is passed to it" alone is not the
test — the fourth action is handed nothing and has the credentials anyway. Composite actions are
in scope, since they run inside the same job and see the same runner state.

**Silence was an available answer.** The old guard offered "SHA-pinned" or an empty
`not_credential_handling` set that no entry had ever been added to. There was no way to say
"this receives a credential, rides a moving ref, and we accept that" — so nothing said it, and
four such actions existed with nothing recorded.

`CREDENTIAL_ACTIONS_ON_MOVING_REFS` is that registry, and it is the inverse of
`SHA_PINNED_ACTIONS`: not a claim these actions are safe, but a record of accepted risk with the
reason attached. Adding an entry **is** the acceptance, the same way adding to
`SHA_PINNED_ACTIONS` is the grant. The guard also fails on a *stale* entry — one accepting a risk
the repository no longer takes — because a registry that outlives its entries stops being read.

**The four entries, and why they are entries rather than pins.** `LiquidLogicLabs` is
**maintainer-owned** (confirmed with the maintainer at sprint closure; `docs/guidelines.md`
previously recorded only that the org exists, which a reviewer correctly read as identification
rather than ownership). The residual risk on those three is the maintainer's own account rather
than a third party's, and the floating major is what lets an upstream fix reach this repository
without a manifest edit. `docker/login-action` stays floating on ordinary CI-AR4 grounds: an
approved owner, large and widely audited, whose security fixes should arrive automatically.

This does not weaken the original decision. `pypa/gh-action-pypi-publish` remains SHA-pinned:
`pypa` is not maintainer-owned and the credential it holds publishes under this project's name
on an index that does not allow re-uploads.

**Revisit if:** the maintainer stops controlling `LiquidLogicLabs`, any of those actions gains a
package-publishing capability, or a supply-chain incident affects `docker/login-action`.

## Amended again at epic closure: a credential can be ambient, not only handed over

The derivation above recognised two ways an action receives a credential — a `secrets.*`
expression reaching it, or its position after a registry login. Both are *passing* mechanisms, and
there is a third that this epic introduced the job for.

**An OIDC identity is not passed to a step.** It is ambient in the job, exposed as
`ACTIONS_ID_TOKEN_REQUEST_URL` and `ACTIONS_ID_TOKEN_REQUEST_TOKEN` in every step's environment, so
*every* action in a job holding `id-token: write` can mint one. The same holds for the automatic
token under `packages: write`, `attestations: write` or `contents: write`. Recognising only what is
handed over left the guard reporting green over the newest and most consequential job in the
repository — and it did so while `release.yaml`'s own comment stated the stakes: until PyPI's
trusted publisher is bound to an environment, anything that can obtain `id-token: write` can mint a
PyPI-scoped token.

`_credential_handling_actions` now derives that third reason from the job's own `permissions:`
mapping, which was already parsed for the denied-scopes guard. Four actions became visible, and each
is recorded rather than pinned:

| Action | Where it is ambient |
|---|---|
| `actions/checkout` | every credentialed job in the repository |
| `actions/attest-build-provenance` | `release.yaml:attest` — `id-token: write`, `attestations: write` |
| `docker/setup-buildx-action` | the three jobs holding `packages: write` |
| `docker/setup-qemu-action` | `publish-image.yaml:image` — `packages: write` |

**Why recorded and not pinned.** These are `actions` and `docker` — the platform's own namespaces,
and among the most-scrutinised actions in the ecosystem. Compromising one is a materially higher bar
than the four entries this register already held, and pinning them would mean a manual bump on the
actions that most need to receive security fixes automatically. That is a defensible acceptance; a
silent one is not, and the register exists precisely so it has to be written down.

**This does not weaken the register — it is the register working.** The entries were added because
a derivation got *wider*, which is the direction that finds things. A composite action contributes
no ambient credential of its own: it runs with the calling job's grant, and the caller is examined
separately.

**Revisit if:** any of these four gains a capability beyond what it needs, a supply-chain incident
affects `actions/*` or `docker/*`, or the PyPI trusted publisher is bound to the `pypi` environment
— which narrows what an ambient OIDC identity in that job is worth, and may make pinning
`actions/attest-build-provenance` and `actions/checkout` there the cheaper trade.


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
- **Done.** `release.yaml` landed in E008-S01-002, and the reviewed SHA is recorded with the date
  it was reviewed in the comment above each `uses:` line (`release.yaml:421`, `:509`;
  `dev.yaml:365`, `:465`). `test_every_sha_pinned_publisher_records_the_date_it_was_reviewed`
  keeps it that way. This bullet stood in the future tense against the wrong story through two
  gate reviews.
