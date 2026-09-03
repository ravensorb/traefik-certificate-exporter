# ADR-0010: Forge Release creation uses one multi-platform action, not a per-forge branch

- **Status:** Accepted
- **Date:** 2026-09-02
- **Deciders:** Maintainer (ravensorb)
- **Principle(s) in tension:** One implementation across forges versus writing a client for an API that is only *shaped* like the one we know
- **Resolves:** Epic 8 architecture gate finding **F3** (BLOCKER)

## Context

Epic 8 must create a forge Release with attached assets. Epic 9's entire premise is that the
*same* workflow YAML does this on a self-hosted Gitea instance. The gate recorded this as a
BLOCKER on the grounds that no mechanism existed within the project's constraints:

- the action owner allowlist is `{actions, docker, pypa, LiquidLogicLabs}`, mechanically enforced;
- actions must match the floating-major alias (with the ADR-0009 SHA exception for credential
  handlers);
- `gh release create` speaks only GitHub's API.

**The gate's premise was wrong.** It proposed building
`LiquidLogicLabs/git-action-forge-release@v1`. That action already exists under a different name
and major — `LiquidLogicLabs/git-action-release`, described as "Multi-platform release action
(GitHub, Gitea, self-hosted Gitea)". F3 was a discovery gap, not a capability gap.

## What was verified

- The repository exists and is public; its README states it "Works with GitHub, Gitea (including
  self-hosted instances)". It is a fork of `ncipollo/release-action` extended with Gitea support.
- Its Gitea backend is real, not a stub: `POST {base}/api/v1/repos/{owner}/{repo}/releases`,
  asset upload to `.../releases/{id}/assets`, authenticating with `Authorization: token …`.
- `v2` and `v2.0.3` both resolve to `3db5b5dd6bf0`; `main` is ahead at `7acfef55e6ff`, which is
  what a floating major tracking the latest release should look like. **`v2.0` is stale** at
  `90d0e4f4` — pin `v2`, never `v2.0`.
- There is **no `base-url` input**. The instance URL derives from `GITHUB_SERVER_URL`, which
  Gitea Actions sets. This is *better* for CI-AR6 than an override: coordinates come from action
  context. A `platform:` input exists as the explicit escape hatch.
- Its inputs cover what E008-S01-003 needs (`tag`, `name`, `body-file`, `artifacts`,
  `prerelease`, `allow-updates`) and its outputs (`html-url`, `assets`) satisfy the
  CI-AR41 run-summary evidence requirement. **`commit` is deliberately not among them** --
  see the amendment below; it was listed here and passed, and it is wrong for this workflow.

Two things this ADR relies on are **explicitly unverified**, and both belong in E009's pinned
tuple rather than being assumed here:

- The action's platform auto-detection delegates to `git-platform-detector`, distributed from a
  private npm registry, so whether detection is offline or makes a network probe **could not be
  inspected**. Behind a private CA that distinction decides whether TLS trust matters at this
  step. E009 staging must prove it empirically.
- The action declares `using: node24`, so the pinned `act_runner` must accept node24. This is
  already load-bearing for this repo (`actions/checkout@v7`, `actions/setup-python@v7` are node24
  too), but the exact accepting runner version is unconfirmed.

## Options considered

1. **Build `git-action-forge-release@v1`** (the gate's suggestion). Rejected: it already exists.
2. **A forge-conditional step pair in `release.yaml`.** Rejected, and it is the worst option.
   Gitea is GitHub-*shaped* but not GitHub-compatible: asset upload accepted only
   `multipart/form-data` before Gitea 1.22, and asset **deletion** still uses a different path
   today (`.../releases/{id}/assets/{attachment_id}` versus GitHub's
   `.../releases/assets/{id}`). Choosing this commits the project to hand-writing and maintaining
   an HTTP client against an API whose lifecycle semantics demonstrably differ — precisely the
   hand-rolling the engineering rules forbid, and for a second code path that E009 would then
   have to certify twice.
3. **`softprops/action-gh-release@v3.0.2+`.** Genuinely viable — PR #816 added real Gitea 1.24.7
   and 1.26.4 coverage. But `softprops` is not an approved owner, so it costs an allowlist entry
   plus (per CI-AR4) a reviewed SHA, forfeiting the floating-major auto-patch guarantee. It also
   offers no explicit platform override if `GITHUB_API_URL` detection misfires.
4. **`LiquidLogicLabs/git-action-release@v2` (chosen).**

## Decision

`release.yaml`'s finalizer creates the Release with `LiquidLogicLabs/git-action-release@v2`,
passing the verified bundle (wheel, sdist, `SHA256SUMS`, `build-manifest.json`) through
`artifacts`, and records `html-url` and `assets` in the run summary.

No change to `APPROVED_ACTION_OWNERS`, `FLOATING_MAJOR_ALIAS`, or `SHA_PINNED_ACTIONS` is
required — the owner is already approved and `v2` already satisfies the pin policy. That the
choice costs no policy amendment is a point in its favour, not a coincidence: the allowlist was
built around this org.

**Fallback, named now rather than discovered later:** if E009 staging fails to certify this
action against the private-CA Gitea, substitute `softprops/action-gh-release` pinned to a
reviewed SHA, accepting the allowlist entry and the manual-bump obligation. Do **not** fall back
to building a client.

## Enforcement

A contract test asserts that Release creation happens only through the approved action — no
publisher job may run `gh release create`, `gh api …/releases`, or `curl` against
`…/api/v1/repos/…/releases`. Without it, "we use the action" is prose: the cheapest way to ship a
Release is a two-line `curl`, and nothing would notice. The planted violation is exactly that
`curl`.

This complements ADR-0006's `RELEASE_FINALIZER_JOBS` registry, which governs *which job* may
write; this governs *how* it writes. Per gate finding F6 the registry must become
`(workflow, job)` pairs before its first entry, since bare job names match across every workflow.

## Implemented (E008-S01-003)

`release.yaml`'s `finalize` job creates the Release with `LiquidLogicLabs/git-action-release@v2`.
Confirmed against the published `action.yml` rather than assumed:

- `token` defaults to `${{ github.token }}`; it is passed explicitly so the job's capability is
  visible in the parsed job rather than implied by an action default.
- `artifacts` is a comma-delimited path list, and it carries all four files -- wheel, sdist,
  `SHA256SUMS`, `build-manifest.json` -- every one of them addressed through the *revalidated*
  bundle's own step output. `test_the_release_carries_the_whole_verified_bundle_and_is_traceable`
  asserts every entry resolves through that step, not merely that one of them does: the planted
  violation attached the wheel from `dist/` beside a bundle-path sdist, which the weaker form
  accepted.
- `html-url` and `assets` are recorded twice, and the guard requires both: as job outputs, which
  is what the run aggregator reports, and in the finalizer's own summary step `env:`. The planted
  violation degraded the summary row to a literal while leaving the job output intact -- green
  under the single-reader form.
- `using: node24` is confirmed. ADR-0006's alias action is node24 too at `@v2`, so E009's pinned
  `act_runner` needs one JavaScript runtime for both, not node20 and node24 (E008-S01-003).

## Amended after the first real release: `commit:` must not be passed

The first stable release, v0.1.4, failed here:

```
HTTP 422 Unprocessable Entity: {"message":"Reference already exists"}
```

`commit:` tells the action to **create** the tag at the given SHA — the inherited
`ncipollo/release-action` behaviour for workflows that cut a release from a branch. This workflow
does the opposite: it is *triggered by* the tag push, so `refs/tags/vX.Y.Z` exists before the job
starts. Passing `commit:` asked the forge to create the very ref the run depends on already
existing, and the forge refused, correctly.

Nothing is lost by omitting it. The tag identifies the Release, it already points at the released
commit, and the identity re-check in the step immediately above re-proves that it still peels to
`source-sha` before anything is written.

**What this cost, and why it is recorded rather than quietly fixed.** The failure landed *after* the
multi-platform image was published to the registry and the distributions were attested, and *before*
the Release and every alias. That is the partially-applied state the finalizer ordering was designed
to make rare — and the design held: the image is immutable and re-runnable at the same identity, no
alias moved, and `finalize-image-aliases` never started because it waits on this job. The recovery is
exactly what `docs/operational.md` prescribes: re-run the failed job only.

It is also a plain instance of this project's own lesson. Every input in the list above was
*confirmed to exist* on the published `action.yml` (ADR-0010's original verification, and ADR-0012
did the same for the metadata action). Existing is not the same as being correct to pass, and no
amount of reading the manifest would have shown it — only running a release did.

`test_the_release_step_never_asks_the_forge_to_create_its_own_trigger` keeps it out.


## Consequences

- Positive: one implementation, one step, no forge branch — CI-AR2 stays clean and E009 inherits
  the Gitea path for free.
- Positive: the maintainer's own org owns the action, so it is first-party in practice.
- Trade-off: a runtime dependency on a bundled 1.4 MB `dist/index.js` that cannot be rebuilt
  outside a private registry. Runtime is unaffected; auditability is reduced, and that is the
  accepted cost.
- Trade-off: a floating major is a moving ref. Deliberate here — this action receives a forge
  token but is not a package publisher, so ADR-0009's SHA exception does not extend to it. If it
  ever gains publish capability, register it in `SHA_PINNED_ACTIONS`.
- Revisit if: the action stops tracking Gitea's API, `v2` goes stale, or E009 certification fails.
