# ADR-0012: The image metadata action, verified at the tag this repository pins

- **Status:** Accepted
- **Date:** 2026-09-03
- **Deciders:** Maintainer (ravensorb)
- **Principle(s) in tension:** Reusing a maintained renderer against verifying what it actually accepts
- **Resolves:** Epic 8 sprint-closure architecture-drift finding **M4** (MAJOR)

## Context

`LiquidLogicLabs/git-action-docker-metadata@v6` renders **every published image reference** in
this project — `dev.yaml:200` and `release.yaml:330` both hand it the destination list and consume
its `tags` output. Its two sibling actions each got a verified record: ADR-0006 read
`git-action-tag-floating-version`'s `action.yml` at `@v1` and `@v2` and found a camelCase→hyphen
input rename that Actions passes through **silently**, and ADR-0010 did the same for
`git-action-release@v2`. This one was adopted on a `docs/guidelines.md` vendor-preference note and
nothing else.

The silent-failure class is the same and the blast radius is worse.
`test_image_references_are_rendered_by_the_metadata_action_never_hand_joined` asserts the string
`flavor: latest=false` is **passed**, which is not the same as **honoured**. Had `flavor` not been
an input at `@v6`, Actions would have accepted the unknown key without complaint, the renderer's
`latest=auto` default would have applied, and the **publisher** would have pushed `latest` —
defeating the finalizer's sole ownership of aliases (CI-AR29, ADR-0011) with the whole suite green,
because every alias-ownership guard reads the workflow rather than the rendered tag list.

## What was verified

Read from the published `action.yml` at the pinned tag, not assumed.

- **`v6` resolves to `78e256380e83`.** Unlike `git-action-tag-floating-version`, where `v2.0` was
  stale and `v2` was not, there is **no `v6.0` and no `v5`** — no stale minor alias to pin by
  mistake. There is also no `main` branch under that name (404).
- **`flavor` is an input**, alongside `images` and `tags` — the three this repository passes. The
  failure mode above is therefore not live. Also present: `context`, `labels`, `annotations`,
  `sep-tags`, `sep-labels`, `sep-annotations`, `bake-target`, `github-token`.
- **Outputs** cover what the workflows consume and more: `version`, `tags`, `tag-names`, `labels`,
  `annotations`, `json`, `bake-file`, `bake-file-tags`, `bake-file-labels`, `bake-file-annotations`.
- **`using: node24`.** The same runtime as `git-action-release@v2` and
  `git-action-tag-floating-version@v2`, so E009's pinned `act_runner` needs **one** JavaScript
  runtime for all three, not a mixture.
- **The fork's version line matches upstream.** `docs/guidelines.md` claimed "same version
  numbering" without evidence and the drift review flagged it as unverified. `docker/metadata-action`
  is at `v6.2.0`, so the fork's `v6` does track upstream's major. The claim is correct; it is now
  checked.
- **`github-token` defaults to `${{ github.token }}`** and is documented as "unused in this fork;
  retained for upstream compatibility". So the action receives a token by default even though this
  repository passes it nothing. Both callers are `plan` jobs holding `contents: read`, so what it
  receives is a read-only token, not a publication credential.

## Decision

Keep `@v6`, and **stop depending on `flavor` being honoured**.

`test_image_references_are_rendered_by_the_metadata_action_never_hand_joined` still asserts the
input is passed, because passing it is correct. But the property that matters — a publisher never
moves an alias — is now enforced where the tag list is *real* rather than where it is *requested*:
`publish-image.yaml`'s composition step refuses any tag whose reference is `latest`, a bare major,
or a bare major.minor, and that refusal is proven by executing the shipped step. If the renderer
ever changes behaviour, the publisher halts instead of quietly taking a grant that belongs to the
finalizer.

This is the general shape worth keeping: where a third-party action's *output* is load-bearing,
check the output, not the input.

## Consequences

- Positive: the alias-ownership rule no longer depends on a third-party action honouring an input.
- Positive: E009's runtime requirement is now confirmed across all three actions, not two.
- Trade-off: another bundled `dist/index.js` that cannot be rebuilt locally — the same accepted
  cost ADR-0010 records, and the same reason: the org is maintainer-owned.
- **Known limit, stated rather than implied.** `_credential_handling_actions` derives what an
  action receives from the step's `with:`/`env:` and its position after a registry login. It
  **cannot see an action's own input defaults** — this action's implicit `github.token` is exactly
  that case, found by reading the `action.yml` and not by the guard. Offline contract tests cannot
  fetch remote manifests, so this stays a reading obligation whenever an action is adopted, which
  is what ADR-0006, ADR-0010 and this record exist to discharge.
- Revisit if: `v6` goes stale against upstream, `flavor` or `tags` change shape, the fork diverges
  from `docker/metadata-action`'s tag grammar, or the action gains a capability that makes its
  implicit token load-bearing.
