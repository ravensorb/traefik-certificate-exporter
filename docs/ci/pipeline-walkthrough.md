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
                                              validate-tag (exactly vX.Y.Z)
                                              build
                                              publish-package ─┐
                                              publish-image  ──┤
                                                               └► release (generated notes,
                                                                  wheel + sdist attached)
```

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
  `--skip-existing` makes the re-run safe (AD-11).
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

`act` needs nothing special. No checkout carries a `ref:` (ADR-0028), so `act` uses
your working tree as it is. No step looks at `env.ACT`. Both rules are checked by pre-commit
hooks (`workflows-ref-free-checkout`, `workflows-no-act-env`).

## What polices the pipeline

Only standard tools, all run by `pre-commit` (locally and in `build.yaml`):

| Tool | Catches |
| --- | --- |
| actionlint | invalid workflow syntax and expressions |
| zizmor | unpinned actions (everything outside `LiquidLogicLabs/*` needs a commit SHA; `LiquidLogicLabs/*` needs only some ref, so zizmor accepts a branch such as `@main` as readily as `@vN` and the major-tag form is held by review), template injection, excessive permissions |
| gitleaks | committed secrets; the repository adds no path exemption, and gitleaks' default allowlist is inherited (ADR-0037) |
| pygrep hooks | a `paths` allowlist in `.gitleaks.toml`; `ref:`/`repository:` or `ACT` in any workflow |
| ruff, mypy | Python lint, format and types |

Dependabot proposes updates for actions, Python dependencies and the Docker base image.

## Requirements

- **Gitea 1.27 or newer.** That is the first release with reusable workflows; `concurrency`
  needs 1.26.
- **Runners:** `ubuntu-latest` on GitHub, an `act_runner` mapping `ubuntu-latest` on Gitea,
  `act` locally.
- **Private CA:** set `PUBLISH_CA_CERTIFICATE` and the publish jobs trust it,
  BuildKit included.
