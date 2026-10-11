# CI/CD pipeline walkthrough

How the pipeline in ADR-0035 works, for anyone setting it up, running it, or changing
it. The binding rules are the spine's `AD-1`..`AD-18`
(`_bmad-output/planning-artifacts/architecture/architecture-ci-cd-pipeline-2026-10-08/ARCHITECTURE-SPINE.md`);
this page explains them. The diagrams are plain text so they read the same in a terminal
and in a browser.

## The whole pipeline

```text
                         ┌────────────────────────────────────────────┐
                         │ build.yaml  (reusable, no credentials)     │
                         │                                            │
                         │  checkout (all history + tags)             │
                         │  pre-commit run --all-files                │
                         │  pytest                                    │
                         │  poetry build ─► dist/ (1 wheel + 1 sdist) │
                         │  version, image-version  ─► job outputs    │
                         │  upload artifact "dist"                    │
                         │  docker build (1 arch) + smoke test        │
                         └───────────────▲────────────────────────────┘
                                         │ calls
        ┌────────────────────────────────┼────────────────────────────────┐
        │                                │                                │
 pull_request                     push to main                     tag vX.Y.Z
 ci.yaml                          dev.yaml                         release.yaml
   └─ build                         ├─ build                         ├─ validate-tag
                                    ├─ publish-package (dev)         ├─ build
                                    └─ publish-image   (dev)         ├─ publish-package
                                                                     ├─ publish-image
                                                                     └─ release
```

- Pull requests only build and test. They never see a credential. On GitHub-hosted runners that
  makes fork PRs safe; on a self-hosted Gitea runner it depends on the runner's isolation and the
  instance's fork-PR approval setting (see `docs/ci/gitea-runners.md`).
- Pushing to `main` publishes a dev build to whichever destinations are configured.
- Pushing a `vX.Y.Z` tag publishes the release and creates the forge release with
  generated notes.

## Versions

Git tags are the only source of a version. `pyproject.toml` always says `0.0.0`;
`poetry-dynamic-versioning` replaces it at build time.

```text
 history:   v1.4.0 ── c1 ── c2 ── c3 (main)          tag v1.5.0 on c7
                                │                            │
 package:                 1.4.1.dev3                       1.5.0
 image:                   1.4.1-dev.3                      1.5.0
                          sha-abc1234                      1.5, 1, latest
                          dev
```

- The package and the image carry the same version. Python spells a dev version
  `1.4.1.dev3`, Docker spells it `1.4.1-dev.3` (SemVer).
- The build job works this out once and passes both spellings to every later job.
- Commit hashes appear only as the image tag `sha-<7>`. PyPI rejects hashes in package
  versions, and they don't sort.
- Each tag has one owner. `dev.yaml` writes `-dev.N`, `sha-*` and `dev`. `release.yaml`
  writes `X.Y.Z`, `X.Y`, `X` and `latest`.

## Where things are published

Nothing is required. Each destination switches on when its secret is set, on either
forge, in any combination:

```text
                          dev   release   switched on by
 Python  Gitea index       ✓       ✓      PUBLISH_GITEA_TOKEN
         TestPyPI          ✓       -      PUBLISH_TESTPYPI_TOKEN
         PyPI              -       ✓      PUBLISH_PYPI_TOKEN
 Image   GHCR              ✓       ✓      PUBLISH_GHCR_TOKEN
         Gitea registry    ✓       ✓      PUBLISH_GITEA_TOKEN
         Docker Hub        ✓       ✓      PUBLISH_DOCKERHUB_TOKEN
 Forge   release           -       ✓      PUBLISH_RELEASE_TOKEN
 TLS     private CA        ✓       ✓      PUBLISH_CA_CERTIFICATE
```

Variables that go with them:

| Variable | Shape | Example |
| --- | --- | --- |
| `PUBLISH_GITEA_USERNAME` | account name | `ravensorb` |
| `PUBLISH_GITEA_PYPI_URL` | full upload URL | `https://git.example.com/api/packages/ravensorb/pypi` |
| `PUBLISH_GITEA_REGISTRY` | host, no scheme | `git.example.com` |
| `PUBLISH_GITEA_IMAGE` | full image, lower case, no tag | `git.example.com/ravensorb/traefik-certificate-exporter` |
| `PUBLISH_GHCR_USERNAME` | GitHub user | `ravensorb` |
| `PUBLISH_GHCR_IMAGE` | full image | `ghcr.io/ravensorb/traefik-certificate-exporter` |
| `PUBLISH_DOCKERHUB_USERNAME` | Docker Hub user | `ravensorb` |
| `PUBLISH_DOCKERHUB_IMAGE` | full image | `docker.io/ravensorb/traefik-certificate-exporter` |

**Why the `PUBLISH_` prefix.** Gitea refuses secret and variable names that start with
`GITEA_` or `GITHUB_`. It also fills in its own `GITEA_TOKEN`, which would make
"is the token set?" always true.

`PUBLISH_RELEASE_TOKEN` is set separately in each forge's secrets: a GitHub token on
GitHub, a Gitea token on Gitea. Each one creates the release on the forge running the
workflow.

On GitHub every `PUBLISH_*` secret lives in the `dev` or `release` environment, never at
repository level, so only a publish job on `main` or on a `v*` tag can read it
([Environments (GitHub)](#environments-github), ADR-0039); `PUBLISH_*` variables stay at
repository level.

### How "publish if the token is set" is written

```text
 publish-package:
   env:                                   <- job level: computed once
     PUBLISH_PYPI: ${{ secrets.PUBLISH_PYPI_TOKEN != '' }}
   steps:
     - name: Upload to PyPI
       if: env.PUBLISH_PYPI == 'true'     <- the only kind of step condition
       env:
         TWINE_USERNAME: __token__
         TWINE_PASSWORD: ${{ secrets.PUBLISH_PYPI_TOKEN }}
       run: twine upload --non-interactive --skip-existing --repository-url ... dist/*
```

The flag is computed at job level because neither GitHub nor Gitea allows `secrets` in
an `if:`.

## One image, every registry

```text
 publish-image
   env:  PUBLISH_GHCR / PUBLISH_GITEA / PUBLISH_DOCKERHUB       (one flag each)
         PUBLISH_IMAGE = any of the three                        (the only combined flag)
         GHCR_IMAGE / GITEA_IMAGE / DOCKERHUB_IMAGE = name, or "" when switched off

   ca-certificate-import          if PUBLISH_CA
   registry configuration guard   if PUBLISH_IMAGE   enabled registry with an empty image/registry var → fail
   login ghcr                     if PUBLISH_GHCR
   login gitea                    if PUBLISH_GITEA
   login docker hub               if PUBLISH_DOCKERHUB
   docker-metadata                if PUBLISH_IMAGE   images: the three names (blanks dropped)
   setup-qemu + setup-buildx      if PUBLISH_IMAGE
   build-push (amd64 + arm64)     if PUBLISH_IMAGE   one build, every tag, every registry
   docker-test (by digest)        if PUBLISH_IMAGE
```

- One build means one digest, identical on every registry.
- The `Registry configuration guard` runs after the CA import and before every login
  (AD-10, AD-18). For each registry whose token is set but whose image variable is empty,
  and for Gitea with an empty `PUBLISH_GITEA_REGISTRY`, it prints one line such as
  `publish-image: GHCR is enabled by PUBLISH_GHCR_TOKEN but vars.PUBLISH_GHCR_IMAGE is empty`,
  reports every half-configured registry, then fails the job. Nothing has been logged in
  to or pushed, so re-running after setting the variable needs no cleanup. Without it, an
  empty `PUBLISH_GITEA_REGISTRY` would make `docker/login-action` default to Docker Hub
  and send the Gitea token there.
- With no registry configured, every step is skipped and the job succeeds. Releases that
  only publish to PyPI still create their forge release.

## Releasing

```text
 you                                   forge
 ───                                   ─────
 git switch main && git pull
 just release minor
   ├─ clean tree?  HEAD == origin/main?
   ├─ just check  (same hooks + tests as CI)
   ├─ last tag v1.4.0, not already at HEAD?
   ├─ v1.4.0 → pysemver bump minor → v1.5.0
   ├─ git tag -a v1.5.0
   └─ git push origin v1.5.0  ───────────►  release.yaml
                                              validate-tag (exactly vX.Y.Z, on main)
                                              build
                                              publish-package ─┐
                                              publish-image  ──┤
                                                               └► release (generated notes,
                                                                  wheel + sdist attached)
```

- `validate-tag` also checks that the tagged commit is on the default branch
  (`git merge-base --is-ancestor` against `origin/<default>`) and logs the tag, the commit
  and the default branch. That check catches mistakes; it is not protection, because it runs
  from the tagged commit. What stops anyone else releasing is tag protection on `v*`
  (ADR-0038, [Tag protection](#tag-protection)).
- **Never delete or re-push a released tag; cut the next patch.** PyPI keeps the first wheel
  for a version, so a moved tag would make the images and the forge release disagree with it
  (ADR-0038).
- A tag pushed before `main` fails `validate-tag` with
  `refusing to release tag <tag>: commit <sha> is not on origin/main`, and nothing builds.
  If the tagged commit reaches `main` unchanged (a merge commit, or a direct push by a
  bypass actor), re-run the release workflow; the re-run checks out fresh and passes. If
  it lands under a new SHA (squash or rebase merge), the tagged commit will never be on
  `main`: delete the tag (a bypass action once tag protection is on; nothing was
  published, so this is not a re-push of a released tag) and tag the commit that landed.
- `just release` refuses when the base tag already points at HEAD — the commit is
  already released (AD-16). Its message is
  `release: HEAD <sha> is already released as <tag>`.
- `just release` pushes only the tag, and only when `main` is already pushed. The
  `dev.yaml` run for that commit therefore happened before the tag existed and published
  a dev version.
- If `dev.yaml` is re-run after tagging, it refuses to publish, because its version is no
  longer a `.dev` version.
- No commit is created by a release.
- A failed release can be re-run safely. Uploads skip files that already exist, the forge
  release is updated in place, and image tags are re-pointed to the digest this run built
  (ADR-0036 §5).
- If `publish-image`'s registry configuration guard fails, `release` (which `needs` it) does
  not run, so no forge release is created: a half-configured release halts loudly rather
  than shipping without that registry. `publish-package` may already have uploaded;
  the re-run uploads only what is missing (`--skip-existing` for PyPI/TestPyPI, a files check for Gitea; AD-11).
- The `release` job gates its steps on `PUBLISH_RELEASE`, except its CA import, which is
  gated on `PUBLISH_CA`: a step tests exactly one flag (AD-9, AD-18), and the import
  publishes nothing.

## Running locally

| Command | Does |
| --- | --- |
| `just install` | install the project and dev tools |
| `just check` | every pre-commit hook + pytest: the build job's gates (the build job also builds the dists and the image on Python 3.14; `just image` covers that) |
| `just build` | clean `dist/`, build the wheel and sdist |
| `just image` | build and load the image from `dist/` |
| `just act` | run `ci.yaml` under `act` |
| `just act dev.yaml` | run the dev pipeline; no secrets are passed, so nothing publishes |
| `just release patch` | see above |

No checkout carries a `ref:` (ADR-0028), so `act` uses your working tree as it is.
`just act release.yaml` needs a clone with an `origin` remote tracking the default branch,
with the tag checked out: `validate-tag` checks the tag's commit against
`refs/remotes/origin/<default>` and fails closed without it. `just act` passes the default branch (from `origin/HEAD`, else `main`) as
`--defaultbranch`, since `act` would otherwise report `master`. No step looks at `env.ACT`. Both rules are checked by pre-commit
hooks (`workflows-ref-free-checkout`, `workflows-no-act-env`).

## Forge settings the maintainer applies

Some controls are forge settings, not files in this repository, so no check here can see
them: reading them needs forge-specific API calls, which AD-9 rules out. Each subsection
gives the setting on GitHub and on Gitea and a verification whose output is the evidence.
Until a setting is applied, the protection it describes exists only on paper.

These settings are **required** (ADR-0038, ADR-0039). Apply them in this order; each step's
detail and verification are in the linked subsection. The order matters: an environment a
workflow names but that does not exist yet is created by GitHub on the first run with no
policy and no secrets, and a secret added before its environment and rulesets exist is
readable from any branch.

1. **Delete the unused legacy repository secrets** `DOCKERHUB_TOKEN` and
   `DOCKERHUB_USERNAME` ([Environments (GitHub)](#environments-github), step 1).
2. **Create the `dev` (Branch `main`) and `release` (Tag `v*`) environments with no
   secrets** ([Environments (GitHub)](#environments-github), step 2).
3. **Apply the `v*` tag ruleset and the `main` ruleset**, and the Gitea protected tag and
   branch ([Tag protection](#tag-protection), [Branch protection on main](#branch-protection-on-main)).
4. **Merge** the change that adds `environment:` to the publish jobs.
5. **Confirm exactly `dev` and `release` exist**, both with custom policies, and nothing was
   auto-created ([Environments (GitHub)](#environments-github), step 5).
6. **Add secrets only when publishing should go live**, `dev` first; keep verifying
   `release` until the first real tag ([Environments (GitHub)](#environments-github), step 6).

No check in this repository sees whether these settings are applied. What `just check`
does enforce is the half in the files: every job that reads a secret declares an
environment (zizmor `secrets-outside-env`, auditor persona).

### Tag protection

Only the maintainer may create, move or delete a `v*` tag, so only the maintainer can
release (ADR-0038). It needs no secret and can be applied at any time.

**GitHub**

1. Settings → Rules → Rulesets → New ruleset → New tag ruleset, named `release-tags`.
   - Enforcement status: Active.
   - Target tags: include by pattern `v*`.
   - Rules: Restrict creations, Restrict updates, Restrict deletions, Block force pushes.
   - Bypass list: the Repository admin role only. GitHub's ruleset guide lists roles,
     teams and apps as bypass actors ("Creating rulesets for a repository" → "Granting
     bypass permissions"); the REST schema also accepts `User`
     (`repository-ruleset-bypass-actor.actor_type`, github/rest-api-description, checked
     2026-10-09), but the role is the form the guide documents. On this user-owned
     repository the owner (the maintainer) is the only admin unless a collaborator is
     given the admin role, so keep it that way.
2. Verify:

   ```bash
   gh api repos/ravensorb/traefik-certificate-exporter/rulesets \
     --jq '.[] | {id, name, target, enforcement}'
   gh api repos/ravensorb/traefik-certificate-exporter/rulesets/<id> \
     --jq '.conditions, [.rules[].type], .bypass_actors'
   ```

   Expect an `active` ruleset with `target: "tag"`, `refs/tags/v*` in
   `conditions.ref_name.include`, the rule types `creation`, `update`, `deletion` and
   `non_fast_forward`, and only `RepositoryRole` (the admin role) as a bypass actor.

A refused push reports the ruleset violation to the pusher. Bypasses are recorded under
Settings → Rules → Insights.

**Gitea**

1. Settings → Tags → add a protected tag with the pattern `v*` and the maintainer as the
   only allowed user (no teams). Gitea refuses creation, force-move and deletion of a
   matching tag by anyone else ("Tag … is protected").
2. Verify:

   ```bash
   curl -fsS -H "Authorization: token $GITEA_TOKEN" \
     "https://<gitea-host>/api/v1/repos/<owner>/<repo>/tag_protections"
   ```

   Expect one entry with `name_pattern: "v*"` and only the maintainer in `whitelist_usernames`.

**Never test this by pushing a `v*` tag on a side branch to a real forge.** The next real
release's `validate-tag` log, which shows the tag, commit and default branch it checked, is
the end-to-end evidence.

The operator rule holds on both forges: never delete or re-push a released tag; cut the
next patch.

### Environments (GitHub)

A job receives an environment's secrets only if it names the environment, and only after
the environment's deployment policy accepts the run's ref; a refused job fails before a
runner starts with "… is not allowed to deploy to <env> due to environment protection
rules" (ADR-0039). Two environments, so each workflow sees only its own tokens:

| Environment | Policy (ref type, pattern) | Jobs | Secrets |
| --- | --- | --- | --- |
| `dev` | Branch `main` | `dev.yaml` `publish-package`, `publish-image` | `PUBLISH_GITEA_TOKEN`, `PUBLISH_TESTPYPI_TOKEN`, `PUBLISH_GHCR_TOKEN`, `PUBLISH_DOCKERHUB_TOKEN`, `PUBLISH_CA_CERTIFICATE` |
| `release` | Tag `v*` | `release.yaml` `publish-package`, `publish-image`, `release` | `PUBLISH_GITEA_TOKEN`, `PUBLISH_PYPI_TOKEN`, `PUBLISH_GHCR_TOKEN`, `PUBLISH_DOCKERHUB_TOKEN`, `PUBLISH_RELEASE_TOKEN`, `PUBLISH_CA_CERTIFICATE` |

The secrets column is the [publish table](#where-things-are-published) read by column; to
derive it from the files, run
`grep -o 'secrets\.PUBLISH_[A-Z_]*' .github/workflows/<file> | sort -u`. Shared tokens
(Gitea, GHCR, Docker Hub, CA) are set in both environments. `vars.PUBLISH_*` stay at
repository level. Gitea and `act` ignore `environment:`; see
[gitea-runners.md](gitea-runners.md#secrets-and-variables-on-gitea) for what that leaves
open on Gitea.

1. Delete the unused legacy repository secrets (nothing in `.github`, `justfile` or
   `docker` references them):

   ```bash
   gh secret delete DOCKERHUB_TOKEN --repo ravensorb/traefik-certificate-exporter
   gh secret delete DOCKERHUB_USERNAME --repo ravensorb/traefik-certificate-exporter
   gh api repos/ravensorb/traefik-certificate-exporter/actions/secrets --jq '.secrets[].name'
   ```

   Expect no output from the last command: no secret at repository level.
2. Settings → Environments → New environment, twice, adding **no secrets**:
   - `dev`: Deployment branches and tags → Selected branches and tags → add rule, Ref
     type **Branch**, pattern `main`.
   - `release`: Selected branches and tags → add rule, Ref type **Tag**, pattern `v*`.
   - Required reviewers on `release` are optional and off by default; turning them on
     blocks unattended releases.

   Verify:

   ```bash
   gh api repos/ravensorb/traefik-certificate-exporter/environments \
     --jq '.environments[] | {name, deployment_branch_policy}'
   gh api repos/ravensorb/traefik-certificate-exporter/environments/dev/deployment-branch-policies \
     --jq '.branch_policies[] | {name, type}'
   gh api repos/ravensorb/traefik-certificate-exporter/environments/release/deployment-branch-policies \
     --jq '.branch_policies[] | {name, type}'
   ```

   Expect `dev` and `release`, each with `custom_branch_policies: true`; `main`/`branch`
   for `dev` and `v*`/`tag` for `release`.
3. Apply the rulesets: [Tag protection](#tag-protection) and
   [Branch protection on main](#branch-protection-on-main).
4. Merge.
5. Verify again with the first command of step 2. Expect still exactly `dev` and `release`
   with their policies. Any other name is an environment a workflow auto-created (a typo
   in `environment:`); it has no secrets, so that job published nothing. Fix the workflow
   and delete the stray environment.
6. Go live when you choose. Add the `dev` secrets first:

   ```bash
   gh secret set PUBLISH_GHCR_TOKEN --env dev --repo ravensorb/traefik-certificate-exporter
   gh api repos/ravensorb/traefik-certificate-exporter/environments/dev/secrets --jq '.secrets[].name'
   ```

   Compare the names with the table above (a secret missing from, or put in the wrong,
   environment silently disables that destination, AD-9). The next push to `main` shows a
   `dev` deployment (Settings → Environments, or `gh api repos/ravensorb/traefik-certificate-exporter/deployments`) and runs the
   enabled destinations. Then add the `release` secrets the same way with `--env release`,
   and re-run the step-2 and step-5 commands until the first real `v*` tag has released.

Paste each verification's output into the PR or the story notes as the evidence.

### Branch protection on main

`dev` hands registry tokens (GHCR, Docker Hub, Gitea, which `release` uses too) to whatever
is on `main`, so `main` must change only through a pull request that someone other than
its author approved and that passed the `build / build` check, and must not be
force-pushed or deleted (ADR-0039). The required check is also what makes the zizmor
`secrets-outside-env` rule block a merge: it fails `pre-commit` inside `build / build`,
and only a required check stops a failing pull request from being merged. The maintainer,
through the bypass list, can still push directly or merge without an approval, and that
runs `dev`; this is accepted.

What this closes, and what it does not:

- **Closed:** a collaborator, a stolen write token or a write-capable agent acting alone
  cannot land a workflow on `main`, so cannot reach the `dev` secrets that way. A pull
  request it opens needs another account's approval, and with
  `require_last_push_approval` a push after the approval needs a new one.
- **Not closed:** a bypass actor (the Repository admin role, that is the owner) can land
  anything on `main`. Two colluding write-holders, or one holding two accounts, can approve
  each other's pull requests. Anyone who can approve can approve a pull request that prints
  the `dev` secrets. On GitHub, a fork or branch run still gets no environment secrets
  (the `dev` policy admits only `main`), so these are the remaining routes.

**GitHub**

1. Settings → Rules → Rulesets → New ruleset → New branch ruleset, named `main`.
   - Enforcement status: Active.
   - Target branches: Include default branch.
   - Rules:
     - Restrict deletions.
     - Block force pushes.
     - Require a pull request before merging, with Required approvals 1,
       Dismiss stale pull request approvals when new commits are pushed, and Require
       approval of the most recent reviewable push.
     - Require status checks to pass, with the check `build / build` (the `ci.yaml`
       caller job `build` running the reusable `build.yaml` job `build`; Conventions).
   - Bypass list: the Repository admin role only, as for [Tag protection](#tag-protection),
     so the maintainer can merge their own pull request.
2. Verify:

   ```bash
   gh api repos/ravensorb/traefik-certificate-exporter/rulesets \
     --jq '.[] | {id, name, target, enforcement}'
   gh api repos/ravensorb/traefik-certificate-exporter/rulesets/<id> \
     --jq '.conditions, [.rules[].type], .bypass_actors'
   gh api repos/ravensorb/traefik-certificate-exporter/rulesets/<id> \
     --jq '.rules[] | select(.type=="pull_request") | .parameters
           | {required_approving_review_count, dismiss_stale_reviews_on_push,
              require_last_push_approval}'
   gh api repos/ravensorb/traefik-certificate-exporter/rulesets/<id> \
     --jq '.rules[] | select(.type=="required_status_checks")
           | .parameters.required_status_checks[].context'
   ```

   Expect an `active` ruleset with `target: "branch"`, `~DEFAULT_BRANCH` (or
   `refs/heads/main`) in `conditions.ref_name.include`, the rule types `deletion`,
   `non_fast_forward`, `pull_request` and `required_status_checks`, and only
   `RepositoryRole` as a bypass actor, next to the `release-tags` ruleset. The
   `pull_request` parameters show `required_approving_review_count` 1 or more and
   `dismiss_stale_reviews_on_push` and `require_last_push_approval` both `true`; the
   status-check context is `build / build`.

**Gitea**

1. Settings → Branches → add a branch protection rule for `main`:
   - Push: disabled, or a push allowlist with the maintainer only.
   - Force push: disabled, or a force-push allowlist with the maintainer only.
   - Deletion: a protected branch cannot be deleted by push; nothing to set.
   - Merge allowlist: enabled, with the maintainer only. Required.
   - Required approvals: 1 or more, with Dismiss stale approvals. Required. Leave
     "Block admin merge override" off, so the maintainer, as repository admin, can still
     merge their own pull request (Gitea's counterpart of the GitHub bypass).
   - Status checks: enabled, with the context of the `build` job's pull-request run.
     Gitea names a context `<workflow> / <job> (<event>)` (v1.27.3
     `services/actions/commit_status.go`), not GitHub's `build / build`, so copy the exact
     context from a pull request's checks list; the field also accepts a glob pattern.

   Gitea has no separate "require a pull request" switch: with push disabled, or allowed
   to the maintainer only, a merged pull request is the only way anyone else changes
   `main`, and the merge allowlist means only the maintainer can merge one.
2. Verify:

   ```bash
   curl -fsS -H "Authorization: token $GITEA_TOKEN" \
     "https://<gitea-host>/api/v1/repos/<owner>/<repo>/branch_protections"
   ```

   Expect an entry with `rule_name: "main"`, `enable_push` false (or
   `enable_push_whitelist` true with only the maintainer in `push_whitelist_usernames`),
   `enable_force_push` false (or `enable_force_push_allowlist` true with only the
   maintainer in `force_push_allowlist_usernames`), `enable_merge_whitelist` true with only
   the maintainer in `merge_whitelist_usernames`, `required_approvals` 1 or more,
   `dismiss_stale_approvals` true, `block_admin_merge_override` false, `enable_status_check` true with the `build` context in
   `status_check_contexts`, and no one but the maintainer in `bypass_allowlist_usernames`.
   Field names are from the Gitea v1.27.3 API schema (`BranchProtection`).

This protects what Gitea **publishes** from `main`; it does not stop a branch workflow on
Gitea from reading Gitea's secrets
([gitea-runners.md](gitea-runners.md#secrets-and-variables-on-gitea)).

## What polices the pipeline

Only standard tools, all run by `pre-commit` (locally and in `build.yaml`):

| Tool | Catches |
| --- | --- |
| actionlint | invalid workflow syntax and expressions |
| zizmor | unpinned actions (everything outside `LiquidLogicLabs/*` needs a commit SHA; `LiquidLogicLabs/*` needs only some ref, so zizmor accepts a branch such as `@main` as readily as `@vN` and the major-tag form is held by review), template injection, excessive permissions, a secret used outside an environment (auditor persona), an unnamed job |
| gitleaks | committed secrets; the repository adds no path exemption, and gitleaks' default allowlist is inherited (ADR-0037) |
| pygrep hooks | a `paths` allowlist in `.gitleaks.toml`; `ref:`/`repository:` or `ACT` in any workflow |
| ruff, mypy | Python lint, format and types |
| pip-audit | a known advisory in any `poetry.lock` group (the venv is built by `poetry sync --all-groups`) or, as `pip-audit-bootstrap`, in any hashed `.github/requirements/*.txt` (ADR-0042). Only packages installed for the running Python and platform are audited: a lock entry gated by an environment marker for another platform or Python minor is not (BL-E014-023). Needs network access to PyPI/OSV: offline it fails rather than skips (within 15 minutes of an online run, pip's HTTP cache answers instead; CI starts with a cold cache). An advisory with no fix is accepted only by `--ignore-vuln <ID>` in the hook, with the reason and a `BL-` key |
| deptry | a dependency `src/` imports but `pyproject.toml` does not declare in the main group, or a main dependency `src/` never imports (review m8, NFR-3) |

Dependabot proposes updates for actions, Python dependencies and the Docker base image.

## Requirements

- **Gitea 1.27 or newer.** That is the first release with reusable workflows; `concurrency`
  needs 1.26.
- **Runners:** `ubuntu-latest` on GitHub, an `act_runner` mapping `ubuntu-latest` on Gitea,
  `act` locally.
- **Private CA:** set `PUBLISH_CA_CERTIFICATE` and the publish jobs trust it,
  BuildKit included.
