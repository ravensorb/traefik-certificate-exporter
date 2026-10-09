# ADR-0038: Release only from protected `v*` tags on the default branch

- **Status:** Accepted
- **Date:** 2026-10-09
- **Deciders:** Maintainer + architecture gate (E013, story E013-S02-003)
- **Epic:** E013
- **Departs from spec:** n/a
- **Amends:** AD-12 and AD-16 of the CI/CD architecture spine
  (`_bmad-output/planning-artifacts/architecture/architecture-ci-cd-pipeline-2026-10-08/ARCHITECTURE-SPINE.md`);
  resolves BL-E013-019 (RT-E013-02, AR-01, AR-07)

## Context

`release.yaml` runs on a push of any `v*` tag. Before this change, `validate-tag` checked only
the tag's name. So any write-holder (or a stolen write token, or an agent) could tag any
commit, on any branch, and publish it as a release: PyPI, every image tag including
`latest`, and the forge release. `README.md`'s "a release is a `vX.Y.Z` tag on `main`" held
only inside `just release`, which nothing forces anyone to use.

A tag could also be deleted and re-pushed on different code (AR-07). The re-run rebuilds the
images and the forge release from the new commit, while PyPI keeps the first wheel, because
it never accepts a re-upload of an existing filename. One version then names two different
commits.

A check inside the workflow cannot close this alone. `release.yaml` runs from the **tagged
commit**, so whoever can push a `v*` tag can also push a commit that deletes the check. What
limits who can create, move or delete a `v*` tag is a forge setting.

No LiquidLogicLabs action reports whether a commit is an ancestor of a branch
(`git-action-tag-info`, `git-action-commit-info` and `git-action-tag-validate-version` were
read; none does), so AD-5's third tier applies: a `run:` step using git's own
`merge-base --is-ancestor`.

## Decision

1. **Tag protection on `v*` is the control.** The maintainer applies it on each forge; the
   checklist is `docs/ci/pipeline-walkthrough.md` §"Forge settings the maintainer applies" →
   "Tag protection".
   - GitHub: a tag ruleset `release-tags` targeting `v*`, enforcement Active, with Restrict
     creations, Restrict updates, Restrict deletions and Block force pushes; the bypass list
     holds only the Repository admin role (the bypass form GitHub's ruleset guide documents;
     on this user-owned repository the maintainer is the only admin; ADR-0039 records the
     source).
   - Gitea: a protected tag `v*` whose only allowed user is the maintainer. Gitea's
     pre-receive hook checks every tag ref update against it, so creation, force-move and
     deletion are all refused for anyone else.
   - The same pattern, `v*`, on both forges. It also covers floating `v1` / `v1.2` tags,
     which `release.yaml` rejects by name; the maintainer pushes those as a bypass actor or
     allowed user.
2. **`validate-tag` checks that the tagged commit is on the default branch — as a guard
   against mistakes, not a boundary.** After the name check, it checks out ref-free with full
   history (`fetch-depth: 0`, `persist-credentials: false`, no `ref:`, AD-6) and runs one step,
   `Tag is on the default branch`, with no `if:`:
   - the default branch comes from `github.event.repository.default_branch` through `env`;
     an empty value fails the step;
   - it logs the tag, the commit SHA and the default branch;
   - it runs `git merge-base --is-ancestor HEAD refs/remotes/origin/<default>` and, on
     failure, writes `refusing to release tag <tag>: commit <sha> is not on origin/<default>`
     and exits 1, so `build` never runs.

   It catches tagging the wrong commit, tagging before `main` is pushed, and a plain
   `git push` of a tag that bypasses `just release`. It does not stop a write-holder who
   controls the tagged commit; decision 1 does.
3. **"On the default branch" means "reviewed" only together with the required `main`
   protection** that E013-S02-002 documents (changes through a PR, no force-push, no
   deletion, maintainer may bypass). Until that is applied, the check proves only
   reachability from `main`.
4. **AR-07 is handled by tag protection plus registry immutability, with no "already
   released" guard.** With creation, update and deletion of `v*` restricted, a tag cannot
   be moved without an explicit bypass, so every re-run (ADR-0036 §5) rebuilds the same
   commit. PyPI and Gitea's package index refuse an existing filename, and
   `--skip-existing` keeps re-runs green. A "release exists" guard was rejected: it would
   break ADR-0036 §5 re-runs; `git-action-tag-info` in release mode needs a token and a
   forge-derived `platform` / `base-url`, which AD-9 forbids; and it would need a
   conditional form the Conventions table does not allow.
5. **The justfile derives the default branch once** (`default_branch`: `origin/HEAD` with
   `origin/` stripped, else `main`; it never fails). `just release` reads it, and `just act`
   passes it as `--defaultbranch`, because act otherwise synthesises `master`. The same
   YAML runs on GitHub, Gitea and act; nothing reads `env.ACT`.

## Consequences

- A tag on a commit outside `main` fails `validate-tag`; nothing builds or publishes. Once
  protection is applied, deleting that tag needs bypass rights, which is intended.
- A tag pushed before `main` fails the same way. If the tagged commit reaches `main`
  unchanged (a merge commit, or a direct push by a bypass actor), a re-run checks out fresh
  and passes. If it lands under a new SHA (squash or rebase merge), the tag must be deleted
  (a bypass action once protection is on; nothing was published) and the landed commit
  tagged instead.
- A local `act` run of `release.yaml` needs a clone with an `origin` remote tracking the
  default branch. Without one the check fails closed (`fatal: Not a valid object name
  refs/remotes/origin/<default>`).
- **Residual: admin bypass.** A bypass actor can still delete and re-push a released tag,
  and the workflow cannot tell. The operator rule is: never delete or re-push a released
  tag; cut the next patch. GitHub records bypasses under Settings → Rules → Insights.
- **Residual: the forge settings are not checked from the repository.** Reading them needs
  forge-specific API calls, which AD-9 forbids. The evidence is the maintainer's `gh api` /
  Gitea API verification in the checklist, and `docs/ci/gitea-certification.md` lists the
  Gitea checks as live items. Until the settings are applied, this ADR's control exists
  only as documentation.
- Not covered: signed-tag verification.

## Revisit when

- either forge exposes tag-protection state to a workflow without a forge-specific API
  call, so it can be checked mechanically; or
- the project adopts signed release tags.
