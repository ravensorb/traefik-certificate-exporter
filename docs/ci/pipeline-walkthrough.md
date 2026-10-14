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
  writes `X.Y.Z`, `X.Y`, `X` and `latest`; `latest` moves only when the tag is the highest
  `vX.Y.Z` tag, so an older line's patch release never takes it.

## Where things are published

Nothing is required. A destination is enabled when its token **and** every variable it
needs are set and non-empty, on either forge, in any combination. Two exceptions use the
forge's own job token when no `PUBLISH_*` token is set: GHCR (on GitHub) and the forge
release (on any forge run; under `just act` the job token is empty, so both are skipped):

```text
                          dev   release   enabled when all set (secret + vars.PUBLISH_*)
 Python  Gitea index       ✓       ✓      PUBLISH_GITEA_TOKEN + GITEA_USERNAME, GITEA_PYPI_URL
         TestPyPI          ✓       -      PUBLISH_TESTPYPI_TOKEN
         PyPI              -       ✓      PUBLISH_PYPI_TOKEN
 Image   GHCR              ✓       ✓      GHCR_IMAGE (+ PUBLISH_GHCR_TOKEN on act/Gitea; GitHub uses its own token)
         Gitea registry    ✓       ✓      PUBLISH_GITEA_TOKEN + GITEA_USERNAME, GITEA_REGISTRY, GITEA_IMAGE
         Docker Hub        ✓       ✓      PUBLISH_DOCKERHUB_TOKEN + DOCKERHUB_USERNAME, DOCKERHUB_IMAGE
 Forge   release           -       ✓      always on a forge run (the forge's own token, or PUBLISH_RELEASE_TOKEN)
 TLS     private CA        ✓       ✓      PUBLISH_CA_CERTIFICATE (not a destination; never warns)
```

Each destination is in one of three states, reported by the first step of every publish
job, `Destination configuration`. Its **intent inputs** are the inputs whose presence means
someone meant to configure it: all of its inputs for GHCR and Docker Hub,
`PUBLISH_GITEA_PYPI_URL` for the Gitea index, `PUBLISH_GITEA_REGISTRY` and
`PUBLISH_GITEA_IMAGE` for the Gitea registry (the shared Gitea token and username are
judged separately, below). Single-input destinations are enabled or silent.

| State | When | What the run shows |
| --- | --- | --- |
| unconfigured | none of its intent inputs is set | nothing: no warning, no log line |
| partial | an intent input is set, but not every required input | exactly one `::warning::` per run naming each missing `secrets.NAME` / `vars.NAME`; the destination is skipped and the run stays green |
| enabled | every input is set | one plain log line `<Destination> enabled`; it publishes |

A partial warning says where the fix goes: on GitHub, a secret or variable of the job's
environment (`dev` for `dev.yaml`, `release` for `release.yaml`; Settings → Environments);
on Gitea, a repository Actions secret or variable (Gitea ignores `environment:`). To
disable the destination instead, unset the items that are set.

The Gitea package index and the Gitea registry share `PUBLISH_GITEA_TOKEN` and
`PUBLISH_GITEA_USERNAME`, but each is enabled on its own: the index by
`PUBLISH_GITEA_PYPI_URL`, the registry by `PUBLISH_GITEA_REGISTRY` and
`PUBLISH_GITEA_IMAGE`. Those own variables decide whether a Gitea destination was meant to
be configured, so an index-only setup gets no registry warning and the reverse. A Gitea
token or username with none of those variables set is reported once per run, by
`publish-package` ("Gitea shared inputs").

`publish-package` also reports, in one warning per run, any **legacy secret** that the
pre-0.3.0 workflows read and nothing reads now (`DOCKERHUB_TOKEN`, `DOCKERHUB_USERNAME`,
`PYPI_TOKEN`, `PYPI_USERNAME`, `FORGE_PACKAGE_TOKEN`, `REGISTRY_USERNAME`,
`REGISTRY_PASSWORD`, `CI_CA_CERTIFICATE`, `GITEA_PACKAGE_INDEX_CA_CERTIFICATE`,
`GITEA_FORGE_API_CA_CERTIFICATE`), naming the `PUBLISH_*` replacement for each. Move the
value to its replacement, then delete the legacy secret. The list is hand-kept from the
git history of `.github/workflows/`; a legacy name not on it is not detected, and legacy
**variables** (`DOCKER_IMAGENAME`, `PACKAGE_REPO`, ...) are not detected at all.

Variables that go with them:

| Variable | Shape | Example |
| --- | --- | --- |
| `PUBLISH_GITEA_USERNAME` | account name | `ravensorb` |
| `PUBLISH_GITEA_PYPI_URL` | full upload URL | `https://git.example.com/api/packages/ravensorb/pypi` |
| `PUBLISH_GITEA_REGISTRY` | host, no scheme | `git.example.com` |
| `PUBLISH_GITEA_IMAGE` | full image, lower case, no tag | `git.example.com/ravensorb/traefik-certificate-exporter` |
| `PUBLISH_GHCR_USERNAME` | GitHub user; optional, defaults to the run's actor | `ravensorb` |
| `PUBLISH_GHCR_IMAGE` | full image | `ghcr.io/ravensorb/traefik-certificate-exporter` |
| `PUBLISH_DOCKERHUB_USERNAME` | Docker Hub user | `ravensorb` |
| `PUBLISH_DOCKERHUB_IMAGE` | full image | `docker.io/ravensorb/traefik-certificate-exporter` |

**Why the `PUBLISH_` prefix.** Gitea refuses secret and variable names that start with
`GITEA_` or `GITHUB_`. It also fills in its own `GITEA_TOKEN`, which would make
"is the token set?" always true.

**GHCR and the forge release use the forge's own token** (ADR-0052). On GitHub,
`publish-image` has `packages: write` and pushes to GHCR with the job's `GITHUB_TOKEN`
(username `vars.PUBLISH_GHCR_USERNAME`, else the run's actor), and `release` has
`contents: write` and creates the release with it. `PUBLISH_GHCR_TOKEN` (a classic PAT with
`write:packages`) and `PUBLISH_RELEASE_TOKEN` are optional overrides, needed only where the
job token cannot do the job: GHCR from act or Gitea. On Gitea the job token creates the
Gitea release; it cannot publish to Gitea's package registry, so `PUBLISH_GITEA_TOKEN` is
always a separate `write:package` token (never an instance-admin token).

The job token can push to a GHCR package only if this repository may write it: a package
the workflow creates is linked automatically, but one pushed first with a personal token
(as 0.2.0 was) needs this repository given the **Write** role under the package's
*Manage Actions access*. Otherwise the first tag run's `publish-image` gets a 403 after
PyPI may already have published. A `dev.yaml` run with `PUBLISH_GHCR_IMAGE` set in `dev`
proves it before a tag (done for 0.3.1, 2026-10-14).

Publish tokens for GitHub are kept in Infisical and copied into the GitHub environment with
`gh secret set` reading the value from stdin.

**Registry logins sit beside steps at major tags** (accepted residual, ADR-0052).
`publish-image` logs in to every enabled registry with `docker/login-action`, which writes
the credentials to the job's Docker config, and then runs
`LiquidLogicLabs/git-action-docker-metadata@v6` and `LiquidLogicLabs/git-action-docker-test@v2`
at mutable major tags (AD-5); either can read that config. Revisit: a `docker logout` before
the image test (BL-E015-005), or SHA-pinned LiquidLogicLabs actions.

On GitHub every `PUBLISH_*` secret lives in the `dev` or `release` environment, never at
repository level, so only a publish job on `main` or on a `v*` tag can read it
([Environments (GitHub)](#environments-github), ADR-0039). The `PUBLISH_*` variables live
in the environment of the workflow that publishes the destination too, and none at
repository level (AD-13): repository-level variables are visible to both environments, so
the other workflow would see them without the token and report the destination as
partially configured on every run. A destination both workflows publish to has its
variables set in both environments.

### How "publish if the token is set" is written

```text
 publish-image:
   env:                                   <- job level: computed once
     PUBLISH_GHCR: ${{ vars.PUBLISH_GHCR_IMAGE != '' && (secrets.PUBLISH_GHCR_TOKEN != '' || (github.server_url == 'https://github.com' && github.token != '')) }}
     ANY_GHCR:     ${{ secrets.PUBLISH_GHCR_TOKEN != '' || vars.PUBLISH_GHCR_USERNAME != '' || vars.PUBLISH_GHCR_IMAGE != '' }}
   steps:
     - name: Destination configuration    <- no if:; reads PUBLISH_*/ANY_* only
       # enabled = PUBLISH_X; partial = ANY_X and not PUBLISH_X (one ::warning::)
     - uses: docker/login-action@...
       if: env.PUBLISH_GHCR == 'true'     <- the only kind of step condition

 publish-package:
   env:
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
an `if:`. Each `PUBLISH_*` flag is the conjunction of presence tests (`!= ''`) over the
destination's token and variables, and each multi-input destination has an `ANY_*` flag
beside it; that is the only place the rule lives. "Non-empty" is `!= ''`: an unset
variable counts as missing, and a value of `" "` counts as set (the consuming step then
fails loudly). Single-input destinations (TestPyPI, PyPI, the forge release) have no
`ANY_*` flag: they are enabled or silent, never partial. The `workflows-if-no-secrets-vars`
pre-commit hook rejects an `if:` that reads `secrets` or `vars` (it checks only the first
line of a multi-line `if:`); that each `if:` tests exactly one flag is held by review.
A list entry in `Destination configuration` that names an undefined flag or input fails
that step with an `::error::`, so an edit that drifts from job `env` turns the run red
instead of going quiet.

## One image, every registry

```text
 publish-image
   env:  PUBLISH_GHCR / PUBLISH_GITEA / PUBLISH_DOCKERHUB       (token and every var, one flag each)
         ANY_GHCR / ANY_GITEA / ANY_DOCKERHUB                    (any own input set: partial if not enabled)
         PUBLISH_IMAGE = any of the three                        (the only combined flag)
         GHCR_IMAGE / GITEA_IMAGE / DOCKERHUB_IMAGE = name, or "" when not enabled

   destination configuration      always             enabled lines; one warning per partial registry
   version guard (dev) / verify dist hashes
   ca-certificate-import          if PUBLISH_CA
   login ghcr                     if PUBLISH_GHCR
   login gitea                    if PUBLISH_GITEA
   login docker hub               if PUBLISH_DOCKERHUB
   docker-metadata                if PUBLISH_IMAGE   images: the three names (blanks dropped)
   setup-qemu + setup-buildx      if PUBLISH_IMAGE
   build-push (amd64 + arm64)     if PUBLISH_IMAGE   one build, every tag, every registry
   docker-test (by digest)        if PUBLISH_IMAGE
```

- One build means one digest, identical on every registry.
- A half-configured registry is skipped, not failed: its flag is false, so it never logs
  in and its image name is `""`, and `Destination configuration` prints one warning such as
  `GHCR partially configured, skipped: missing vars.PUBLISH_GHCR_IMAGE. Set them as dev
  environment secrets/variables (GitHub) or repository Actions secrets/variables (Gitea),
  or unset secrets.PUBLISH_GHCR_TOKEN, vars.PUBLISH_GHCR_USERNAME to disable it.` The
  other registries still publish. Because `PUBLISH_GITEA` requires
  `PUBLISH_GITEA_REGISTRY`, the Gitea login never runs with an empty registry, which would
  make `docker/login-action` default to Docker Hub and send the Gitea token there.
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
- A partially configured destination does **not** fail the release: it is skipped with one
  warning and the run stays green, so a release can ship without a destination you meant
  to configure. If that happens, set the missing items and re-run; uploads skip what
  already exists (`--skip-existing` for PyPI/TestPyPI, a files check for Gitea; AD-11).
  Gating is evaluated per run attempt, so a variable changed between attempts changes
  what the re-run publishes, and a re-run repeats its own warnings.
- **Where a release publishes.** GitHub, Gitea and `act` run the same `release.yaml`; each
  publishes to whatever destinations are configured where it runs, and the
  LiquidLogicLabs actions create the forge release on the forge that runs it. GitHub is the
  release forge: its `release` environment holds the publish settings. Configure a
  destination on only one forge, or a mirrored tag run there builds and publishes it
  again.
- `just act` runs with no secrets and an empty `GITHUB_TOKEN` (it does not read `~/.actrc`,
  `.secrets`, `.vars` or your `gh` login), so a local run publishes nothing unless you pass
  secrets to act yourself ([Running locally](#running-locally)).
- **Per-release checklist:** the release run shows **zero destination warnings** and each
  target destination `enabled` exactly once; otherwise fix and re-run before announcing.
  This is not mechanically enforced: a partially configured destination does not fail
  the run (NFR-4 trade-off, E014 pipeline ADR).
- **Per-release checklist:** the release run log has zero `Unexpected input` lines (not CI-gating).
  The runner checks every step's `with:` against the pinned action and warns
  `Unexpected input(s)` for a key the action does not declare. No static tool here validates
  the inputs of a SHA-pinned action, so this is the only check that sees a removed or renamed
  input of any action; `workflows-no-removed-buildx-inputs` covers only the two
  `docker/setup-buildx-action` names (AD-18).
- The `release` job gates its steps on `PUBLISH_RELEASE`, except its CA import, which is
  gated on `PUBLISH_CA`: a step tests exactly one flag (AD-9, AD-18), and the import
  publishes nothing.
- **At most one release runs and one waits** (AD-14). The concurrency group `release`
  never cancels a running release, but GitHub keeps only one *pending* run per group: if a
  third tag is pushed while one release runs and another is waiting, the newer tag cancels
  the waiting release. That cancelled release published nothing, and it must be re-run with
  `gh run rerun <run-id>` (or "Re-run all jobs" in the forge UI) -- **only while no newer
  tag has released.** A re-run that finishes after a newer release re-points `X.Y` back
  to the older digest (`latest` is protected: it moves only for the highest tag), which is the race AD-14 exists to prevent. If the newer
  tag has already released (or is running), leave the cancelled version unreleased and cut
  the next patch instead; never delete or re-push its tag. (`queue: max` would keep every
  pending run, but actionlint v1.7.12 rejects it; it is revisited when actionlint accepts it.)
- **Re-run on a ghcr.io 429.** The linuxserver base image is pulled anonymously from
  ghcr.io, which rate-limits with `429 Too Many Requests` and publishes no numeric limit.
  `build` pre-pulls it with a bounded retry (4 attempts, 30 s apart) and builds from the
  local copy; if all four attempts hit 429, the `build` job fails with the last
  `docker pull` error. `publish-image` builds multi-arch on a BuildKit container that does
  not read the local image store, so it has no pre-pull and fails on the first 429. In both
  cases the response is to re-run the failed jobs (`gh run rerun <run-id> --failed`); never
  add a registry login to `build` (AD-2, AD-13).

## Running locally

| Command | Does |
| --- | --- |
| `just install` | install the project and dev tools |
| `just check` | every pre-commit hook + pytest: the build job's gates (the build job also builds the dists and the image on Python 3.14; `just image` covers that) |
| `just build` | clean `dist/`, build the wheel and sdist |
| `just image` | build and load the image from `dist/` |
| `just act` | run `ci.yaml` under `act` |
| `just act dev.yaml` | run the dev pipeline; no secrets are passed and act's ambient secret sources are ignored, so nothing publishes |
| `just act-publish dev.yaml <vars> <destinations>` | run under `act` and publish to the named destinations, with tokens from Infisical |
| `just release patch` | see above |

**`just act` ignores act's ambient secret sources** (AD-16, ADR-0052). It runs `act` with
`HOME` and `XDG_CONFIG_HOME` set to fresh temporary directories (so `~/.actrc`, act's XDG
actrc and `~/.docker/config.json` are not read, and image pulls are anonymous; re-run on a
429), `--secret-file /dev/null` and `--var-file /dev/null` (so `./.secrets` and `./.vars`
are not read), `-s GITHUB_TOKEN=` (an explicitly empty token: without it act runs
`gh auth token`, which reads the system keyring, not `HOME`, and would hand your GitHub CLI
token to every step), and its own `-P ubuntu-latest=ghcr.io/catthehacker/ubuntu:act-latest` (so a
`-P` preference in an actrc is ignored too). A `./.actrc` in the working directory, which act
would still read, makes the recipe exit 1 before act starts:
`act: refusing to run with ./.actrc present (it can pass secrets); remove it`. Remove or
rename it. Not covered: a `./.env` file still sets container environment variables (never
`secrets.*` or `vars.*`), and a raw `act -s ...` run outside the recipe passes whatever it is
given; never give it a publish token (releases publish only from a forge run). The temporary
directories go under `$TMPDIR` and are not removed; a fresh `HOME` also means act downloads
the workflow's actions again on every run.

**`just act-publish` publishes from `act` on purpose.** It has the same isolation as
`just act`, and adds two inputs:

- `vars`: an act var file (`NAME=value` lines) with the destinations' `PUBLISH_*` variables,
  passed as `--var-file`.
- `destinations`: a comma-separated list of `pypi`, `testpypi`, `gitea` and `dockerhub`.
  Each one named gets its token from Infisical (project `home-lab-discovery`, environment
  `prod`: `PYPI_TOKEN`, `PYPI_TEST_TOKEN`, `GITEA_TOKEN`, `DOCKERHUB_TOKEN`), read into the
  recipe's environment and passed as `-s PUBLISH_*_TOKEN`, never on the command line.

```bash
just act-publish dev.yaml ~/act/publish.vars testpypi,gitea
```

PyPI and TestPyPI are enabled by their token alone, so a destination that is not named gets
no token and stays disabled. `GITHUB_TOKEN` stays empty and Infisical's `GITHUB_TOKEN` is
never read, so GHCR and the forge release stay disabled under `act`; they publish from a
forge run only. Needs the `infisical` CLI, logged in.

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
| `dev` | Branch `main` | `dev.yaml` `publish-package`, `publish-image` | `PUBLISH_GITEA_TOKEN`, `PUBLISH_TESTPYPI_TOKEN`, `PUBLISH_DOCKERHUB_TOKEN`, `PUBLISH_CA_CERTIFICATE` (and the optional `PUBLISH_GHCR_TOKEN`) |
| `release` | Tag `v*` | `release.yaml` `publish-package`, `publish-image`, `release` | `PUBLISH_GITEA_TOKEN`, `PUBLISH_PYPI_TOKEN`, `PUBLISH_DOCKERHUB_TOKEN`, `PUBLISH_CA_CERTIFICATE` (and the optional `PUBLISH_GHCR_TOKEN`, `PUBLISH_RELEASE_TOKEN`) |

The secrets column is the [publish table](#where-things-are-published) read by column; to
derive it from the files, run
`grep -o 'secrets\.PUBLISH_[A-Z_]*' .github/workflows/<file> | sort -u`. Shared tokens
(Gitea, GHCR, Docker Hub, CA) are set in both environments when both workflows publish to
that destination; GHCR and Gitea are configured in `release` only. `vars.PUBLISH_*`
live in the environment of the workflow that publishes the destination, none at repository
level (AD-13, [Where things are published](#where-things-are-published)). Gitea and `act` ignore `environment:`; see
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
   gh secret set PUBLISH_TESTPYPI_TOKEN --env dev --repo ravensorb/traefik-certificate-exporter
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
| actionlint | invalid workflow syntax and expressions. It checks a step's `with:` keys only for popular actions in its embedded data referenced at a major tag (and local `./` actions), so it does not validate the inputs of SHA-pinned actions, which is every non-`LiquidLogicLabs/*` action here (AD-5) |
| zizmor | unpinned actions (everything outside `LiquidLogicLabs/*` needs a commit SHA; `LiquidLogicLabs/*` needs only some ref, so zizmor accepts a branch such as `@main` as readily as `@vN`; the major-tag form is enforced by the `workflows-lll-major-tag` pygrep hook), template injection, excessive permissions, a secret used outside an environment (auditor persona), an unnamed job |
| gitleaks | committed secrets; the repository adds no path exemption, and gitleaks' default allowlist is inherited (ADR-0037) |
| pygrep hooks | a `paths` allowlist in `.gitleaks.toml`; `ref:`/`repository:` or `ACT` in any workflow; a pre-commit hook `rev` that is not a frozen commit SHA (`precommit-revs-frozen`); a pre-commit hook that declares `additional_dependencies` or a `language:` other than `system`/`pygrep`/`unsupported`, so pre-commit builds no hook environment from this file and the `repo: local` tools (mypy, import-linter, pip-audit, deptry) run from the `poetry.lock` venv through `poetry run` (`precommit-hook-deps-locked`, ADR-0042; block-style keys only; a `system` hook's `entry` is not checked, review holds `poetry run`; remote hook repos' own environments are listed in ADR-0042 "Not covered"); a workflow `pip install` that is not a hashed install from `.github/requirements/` (`workflows-pip-install-from-requirements`, ADR-0042); a `LiquidLogicLabs/*` `uses:` not at a bare `@vN` (`workflows-lll-major-tag`); a literal `-H`/`--header` Authorization flag (`workflows-no-auth-header-argv`; a header built in a variable or passed by `--config`/`-K` is not seen); a metadata `pattern={{major}}` line without `enable=` (`workflows-major-tag-gated`; presence only, not the expression's value); a `config:` or `config-inline:` key, the `docker/setup-buildx-action` inputs v4 removed in favour of `buildkitd-config` (`workflows-no-removed-buildx-inputs`, AD-18; block style only, and other actions' removed inputs are not seen, see the per-release checklist) |
| ruff, mypy | Python lint, format and types |
| pip-audit | a known advisory in any `poetry.lock` group (the venv is built by `poetry sync --all-groups`) or, as `pip-audit-bootstrap`, in any hashed `.github/requirements/*.txt` (ADR-0042). Only packages installed for the running Python and platform are audited: a lock entry gated by an environment marker for another platform or Python minor is not (BL-E014-023). Needs network access to PyPI/OSV: offline it fails rather than skips (within 15 minutes of an online run, pip's HTTP cache answers instead; CI starts with a cold cache). An advisory with no fix is accepted only by `--ignore-vuln <ID>` in the hook, with the reason and a `BL-` key |
| deptry | a dependency `src/` imports but `pyproject.toml` does not declare in the main group, or a main dependency `src/` never imports (review m8, NFR-3) |

Dependabot proposes updates for actions, Python dependencies, the Docker base image, the
SHA-frozen pre-commit hook revs and the hash-locked Poetry bootstrap file
(`.github/requirements/poetry.txt`). Gitea has no Dependabot: there, hook revs and the
bootstrap file are updated by hand, as described in
[Keep pinned tools current](../developer.md#keep-pinned-tools-current).

## Requirements

- **Gitea 1.27 or newer.** That is the first release with reusable workflows; `concurrency`
  needs 1.26.
- **Runners:** `ubuntu-latest` on GitHub, an `act_runner` mapping `ubuntu-latest` on Gitea,
  `act` locally.
- **Private CA:** set `PUBLISH_CA_CERTIFICATE` and the publish jobs trust it. BuildKit
  trusts it for the enabled Gitea registry host (`PUBLISH_GITEA_REGISTRY`) only; see
  [Gitea runners](gitea-runners.md).
