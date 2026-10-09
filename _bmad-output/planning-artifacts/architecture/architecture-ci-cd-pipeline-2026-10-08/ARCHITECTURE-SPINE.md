---
name: 'traefik-certificate-exporter CI/CD pipeline'
type: architecture-spine
purpose: build-substrate
altitude: initiative
paradigm: 'pipes-and-filters: one credential-free build stage feeding flag-gated publish stages, selected by trigger'
scope: 'Every GitHub Actions / Gitea Actions workflow and justfile recipe that tests, builds, versions, publishes, or releases the Python package and the Docker image'
status: final
created: '2026-10-08'
updated: '2026-10-09'
binds: [all]
sources:
  - .memlog.md
  - reviews/review-rubric-walker.md
  - reviews/review-web-verification.md
  - reviews/review-adversarial.md
  - ../architecture-ci-cd-pipeline-2026-08-31/ARCHITECTURE-SPINE.md (superseded)
  - docs/adr/0028-ref-free-checkout-across-ci-cd.md
companions:
  - docs/adr/0035-standard-ci-cd-pipeline.md
  - docs/adr/0036-ci-cd-pipeline-arch-gate-amendments.md
  - docs/ci/pipeline-walkthrough.md
supersedes: 'architecture-ci-cd-pipeline-2026-08-31 (CI-AR1..CI-AR50)'
---

# Architecture Spine — traefik-certificate-exporter CI/CD pipeline

This spine replaces the 2026-08-31 CI/CD spine in full. None of CI-AR1..CI-AR50 binds any
more; where a rule survives, it is restated below under a new `AD` id.

## Design Paradigm

**Pipes and filters, selected by trigger.** One reusable, credential-free **build** filter
verifies, versions and packages the source. Each trigger has its own thin workflow that
pipes the build's artifact and version outputs into **publish** filters. A publish
filter writes to a destination only when that destination is enabled by its credential.

```text
 trigger              workflow       pipeline
 -------              --------       --------
 pull_request    -->  ci.yaml        build
 push to main    -->  dev.yaml       build --> publish-package (dev)
                                           --> publish-image   (dev)
 tag vX.Y.Z      -->  release.yaml   validate-tag --> build --> publish-package (release)
                                                            --> publish-image   (release)
                                                            --> release (notes + assets)

 dependency direction:  ci/dev/release.yaml --calls--> build.yaml
                        publish jobs --needs--> build (artifact `dist`, outputs version + image-version)
                        build.yaml holds no credential and calls nothing that does
```

## Invariants & Rules

### AD-1 — Four workflows, chosen by trigger [ADOPTED]

- **Binds:** `.github/workflows/`
- **Prevents:** channel or forge branching inside steps; a fifth entry point duplicating build logic.
- **Rule:** The pipeline is exactly `build.yaml` (`workflow_call` only), `ci.yaml` (`pull_request`), `dev.yaml` (`push` to the default branch) and `release.yaml` (`push` of tags `v*`). Trigger selects behaviour; nothing branches on channel, forge, or host. `ci.yaml` and `dev.yaml` call `build.yaml` as their first job, with job id `build`; `release.yaml` calls it after `validate-tag` (AD-12).

### AD-2 — One build, no credentials [ADOPTED]

- **Binds:** `build.yaml`
- **Prevents:** fork pull requests reaching a credential; a publish job shipping bytes the build did not test.
- **Rule:** `build.yaml` runs, in order:
  1. checkout (AD-6);
  2. Python + Poetry (version per Stack);
  3. `pre-commit run --all-files`;
  4. `pytest`;
  5. `poetry build`;
  6. version outputs (AD-7);
  7. a single-arch, non-pushed `docker/build-push-action` build per AD-17, tested with `git-action-docker-test@v2`;
  8. upload of `dist/`.

  It uploads `dist/` (exactly one `.whl` and one `.tar.gz`) as artifact `dist`, and exposes `workflow_call` outputs `version` and `image-version`. Its jobs declare `permissions: contents: read` and receive no secrets. Publish jobs download `dist` with `path: dist/` and never run `poetry build`.

### AD-3 — Local and CI gates are one hook list [ADOPTED]

- **Binds:** `.pre-commit-config.yaml`, `justfile`, `build.yaml`
- **Prevents:** a check that runs only in CI, or only locally; a hook that silently examines nothing.
- **Rule:** Every lint, type, secret, workflow and hygiene check is a pre-commit hook. `just check` and `build.yaml` both run `pre-commit run --all-files` followed by `pytest`; neither adds a check the other lacks. Required hooks are ruff, mypy (scoped to `^src/`), gitleaks, actionlint and zizmor (its official hook).
  - Secret scanning covers the tree and the history (ADR-0036). The gitleaks repo carries two hooks: `gitleaks` (`gitleaks dir --redact --no-banner --config .gitleaks.toml .`) and a second hook with `alias: gitleaks-history` (`entry: gitleaks git --redact --no-banner --config .gitleaks.toml`). Both set `always_run: true` and `pass_filenames: false`. `build.yaml` checks out with `fetch-depth: 0` (AD-6), so CI scans full history.

### AD-4 — No custom policy code [ADOPTED]

- **Binds:** all gates
- **Prevents:** bespoke harnesses that must themselves be tested (global rule 1).
- **Rule:** Workflow and supply-chain policy is enforced only by standard tools' configuration (actionlint, zizmor, gitleaks, ruff, mypy, pre-commit-hooks). No repository code parses workflows, validates publication contracts, or maintains integrity registries. `tests/` holds product tests only.

### AD-5 — Action choice and pinning [ADOPTED]

- **Binds:** every `uses:`
- **Prevents:** custom scripts where an action exists; third-party code moving under a credentialed job.
- **Rule:** Prefer a `LiquidLogicLabs/git-action-*` action, then a widely used documented action, then a `run:` step only when neither works on all three runners (AD-6). `LiquidLogicLabs/*` is referenced at its major tag (`@v2`). Every other action is referenced by full commit SHA with a trailing `# vX.Y.Z` comment. This is enforced by zizmor `rules.unpinned-uses.config.policies` in `.github/zizmor.yml`: `LiquidLogicLabs/*: ref-pin`, `*: hash-pin`. Dependabot (`github-actions`, weekly) proposes pin updates.
  - **Suppressions (ADR-0036).** A zizmor finding the design accepts on purpose is suppressed only per finding, by an inline `# zizmor: ignore[<audit>]` comment on the flagged line that cites the AD/ADR accepting it. Example: `use-trusted-publishing` on each `twine upload` step cites AD-11 / ADR-0035 and `pypa/gh-action-pypi-publish` issue #275. `.github/zizmor.yml` disables no audit; it configures only `unpinned-uses`. Every other finding is fixed, for example `dependabot-cooldown` by a `cooldown` block in `.github/dependabot.yml`.

### AD-6 — Same YAML on GitHub, Gitea and act; ref-free checkout; no `env.ACT` [ADOPTED]

- **Binds:** every workflow, every `actions/checkout` step, every `if:`
- **Prevents:** behaviour that differs by runner; checkout replacing a local `act` workspace.
- **Rule:**
  - Supported runners: GitHub-hosted, Gitea **1.27+** with `act_runner`, and `nektos/act`.
  - No checkout supplies `ref:` or `repository:` (carries ADR-0028 forward).
  - Nothing references `env.ACT` or `ACT`.
  - `build.yaml` checks out with `fetch-depth: 0` and `fetch-tags: true`.
  - Every job uses `runs-on: ubuntu-latest`.

### AD-7 — Version identity, owned by the build [ADOPTED]

- **Binds:** `pyproject.toml`, `build.yaml`, every published package and image
- **Prevents:** the package and image describing different versions; unsortable or rejected dev versions; a second place computing the version.
- **Rule:**
  - Git tags `vX.Y.Z` are the only version source. `pyproject.toml` carries `version = "0.0.0"`, `[tool.poetry.requires-plugins]` `poetry-dynamic-versioning[plugin]`, the plugin's build backend, and exactly this configuration: `enable = true`, `vcs = "git"`, `style = "pep440"`, `bump = true`, `metadata = false`, `strict = true`, `pattern = "^v(?P<base>\d+\.\d+\.\d+)$"`. No workflow or recipe passes version options on a command line.
  - On a tag, the package version is `X.Y.Z`. Elsewhere it is `X.Y.(Z+1).devN`, where N is the commit distance from the last `vX.Y.Z` tag. Floating tags such as `v0` never match.
  - `build.yaml` reads the built wheel's `Version` and emits `version` (PEP 440). It also emits `image-version`, the same version in SemVer spelling: `.devN` becomes `-dev.N`, and a release is unchanged. This one `run:` step is the only place the version is transformed.
  - Every other job reads these two outputs and never recomputes them. No commit hash appears in a package version.

### AD-8 — Image tags, one writer per tag [ADOPTED]

- **Binds:** `git-action-docker-metadata@v6` configuration in `dev.yaml` and `release.yaml`
- **Prevents:** two workflows writing the same tag with different digests; tag sets drifting between registries.
- **Rule:** Every tag value comes from `needs.build.outputs.image-version` or an explicit `type=raw`/`type=sha`; no tag is derived from `github.ref`. Both workflows set `flavor: latest=false`. Each tag has exactly one writing workflow:

  | Tags | Written only by |
  | --- | --- |
  | `X.Y.(Z+1)-dev.N`, `sha-<7 char>`, `dev` | `dev.yaml` |
  | `X.Y.Z`, `X.Y`, `X`, `latest` | `release.yaml` |

  No floating git tags (`v1`, `v1.4`) are created.

### AD-9 — Credential-gated destinations [ADOPTED]

- **Binds:** every publish job
- **Prevents:** forge detection logic; credentials required everywhere; a secret that a forge pre-populates passing the presence check.
- **Rule:**
  - Each destination is enabled exactly when its token secret is set, regardless of which forge runs the workflow, and any combination may publish in one run.
  - Each publish job computes one boolean flag per destination in its job-level `env`, for example `PUBLISH_PYPI: ${{ secrets.PUBLISH_PYPI_TOKEN != '' }}`. Each publishing step tests exactly one flag: `if: env.PUBLISH_PYPI == 'true'`. The token itself is passed only to the step that uses it.
  - No secret or variable name starts with `GITEA_` or `GITHUB_`; Gitea rejects or pre-populates those.
  - The ambient token is never used, by any step.

  | Destination | dev | release | Secret (enables) | Variables |
  | --- | --- | --- | --- | --- |
  | Gitea package index | yes | yes | `PUBLISH_GITEA_TOKEN` | `PUBLISH_GITEA_USERNAME`, `PUBLISH_GITEA_PYPI_URL` |
  | TestPyPI | yes | no | `PUBLISH_TESTPYPI_TOKEN` | |
  | PyPI | no | yes | `PUBLISH_PYPI_TOKEN` | |
  | GHCR | yes | yes | `PUBLISH_GHCR_TOKEN` | `PUBLISH_GHCR_USERNAME`, `PUBLISH_GHCR_IMAGE` |
  | Gitea container registry | yes | yes | `PUBLISH_GITEA_TOKEN` | `PUBLISH_GITEA_USERNAME`, `PUBLISH_GITEA_REGISTRY`, `PUBLISH_GITEA_IMAGE` |
  | Docker Hub | yes | yes | `PUBLISH_DOCKERHUB_TOKEN` | `PUBLISH_DOCKERHUB_USERNAME`, `PUBLISH_DOCKERHUB_IMAGE` |
  | Forge release (running forge) | no | yes | `PUBLISH_RELEASE_TOKEN` | |
  | Private CA (AD-18) | yes | yes | `PUBLISH_CA_CERTIFICATE` | |

  `PUBLISH_RELEASE_TOKEN` is set in each forge's own secret store, holding a token for that forge with permission to create releases.

  Values have a fixed shape:
  - `*_IMAGE` is a full lower-case reference without a tag, for example `ghcr.io/ravensorb/traefik-certificate-exporter`.
  - `PUBLISH_GITEA_REGISTRY` is a host with no scheme.
  - `PUBLISH_GITEA_PYPI_URL` is the full upload URL.
  - No value is derived from forge contexts.

### AD-10 — One image build per run, fanned out to every enabled registry [ADOPTED]

- **Binds:** `publish-image` in `dev.yaml` and `release.yaml`
- **Prevents:** per-registry rebuilds producing different digests; a failed push when no registry is enabled; moving tags before the image is tested.
- **Rule:**
  - The job's `env` holds one flag per registry (AD-9) and `PUBLISH_IMAGE`, true when any registry flag is true. This is the only flag combining conditions.
  - It also holds one image name per registry, empty when that registry is disabled: `${{ secrets.PUBLISH_GHCR_TOKEN != '' && vars.PUBLISH_GHCR_IMAGE || '' }}`, and the same form for the others.
  - Each registry's `docker/login-action` step tests its own flag. Every other step tests `PUBLISH_IMAGE`, so with no registry enabled the job succeeds having pushed nothing.
  - `git-action-docker-metadata@v6` receives the three names in `images:` and drops blank lines.
  - One `docker/build-push-action` step builds `linux/amd64,linux/arm64` per AD-17 and pushes all tags.
  - `git-action-docker-test@v2` then tests the pushed image by its digest.

### AD-11 — Python package publishing [ADOPTED]

- **Binds:** `publish-package` in `dev.yaml` and `release.yaml`
- **Prevents:** an upload path that works on only one runner; uploading anything other than the build artifact; a re-run failing on files already published.
- **Rule:** Each enabled index gets one step, gated on its own flag (AD-9). The step runs `twine upload --non-interactive --skip-existing --repository-url <index> dist/*`, with `TWINE_USERNAME`/`TWINE_PASSWORD` from that index's credentials (`__token__` for TestPyPI and PyPI). `twine` is the project's pinned dev dependency.
  - **Why not the action:** `pypa/gh-action-pypi-publish` exits on Gitea and `act` because it requires `GITHUB_WORKFLOW_REF`, which those runners don't set, and upstream declined the fix.

### AD-12 — Release [ADOPTED]

- **Binds:** `release.yaml`
- **Prevents:** publishing from a malformed or pre-release tag; a hand-kept changelog; a release created before its artifacts exist.
- **Rule:** `release.yaml` runs these jobs in order:
  1. **`validate-tag`** runs `git-action-tag-validate-version@v2` with `version-regex: '^v\d+\.\d+\.\d+$'`, followed by one step `if: steps.tag.outputs.is-valid != 'true'` that exits 1.
  2. **`build`** (`needs: validate-tag`).
  3. **`publish-package`** and **`publish-image`**.
  4. **`release`**, which `needs` both publish jobs and gates each of its steps on `PUBLISH_RELEASE` (AD-9); with the token unset it succeeds as a no-op. `git-action-release-changelog-builder@v3` generates the notes, and `git-action-release@v2` creates the release on the running forge with `token: PUBLISH_RELEASE_TOKEN` and `allow-updates: true`, attaching the `dist` wheel and sdist.

  There is no CHANGELOG file and no `scriv`.

### AD-13 — Permissions [ADOPTED]

- **Binds:** every workflow
- **Prevents:** ambient write access; a credential that means different things on each forge.
- **Rule:** Every workflow declares `permissions: contents: read` and no job widens it. Every credential is a `PUBLISH_*` secret (AD-9), including the release token.

### AD-14 — Ordering and concurrency [ADOPTED]

- **Binds:** `dev.yaml`, `release.yaml`
- **Prevents:** an older dev run moving `dev` after a newer one; two releases racing on `latest`.
- **Rule:** `dev.yaml` declares `concurrency: { group: dev, cancel-in-progress: true }`. `release.yaml` declares `concurrency: { group: release, cancel-in-progress: false }`.

### AD-15 — Dev never publishes a release version [ADOPTED]

- **Binds:** `dev.yaml` publish jobs, `just release`
- **Prevents:** a dev run on a tagged commit publishing `X.Y.Z` and colliding with `release.yaml`.
- **Rule:**
  - `just release` requires `HEAD` to equal `origin/<default>` after a fetch, and pushes only the tag, so the branch push that ran `dev.yaml` happened before the tag existed.
  - Each `dev.yaml` publish job starts with a step that fails unless `needs.build.outputs.version` contains `.dev`. This covers re-runs of `dev.yaml` after tagging.
  - Pushing a branch and a tag together is unsupported.

### AD-16 — The justfile is the local interface [ADOPTED]

- **Binds:** `justfile`
- **Prevents:** release or verification logic living in bespoke scripts; a local run that publishes.
- **Rule:**

  | Recipe | Does |
  | --- | --- |
  | `just install` | `poetry install` |
  | `just check` | AD-3 |
  | `just build` | clean `dist/`, then `poetry build` |
  | `just image` | build and load the image from `dist/` per AD-17 |
  | `just act [workflow]` | `act --detect-event -W .github/workflows/<workflow> --artifact-server-path <tmp>`, default `ci.yaml`, no `--secret` arguments |
  | `just release <major\|minor\|patch>` | see below |

  - Running `dev.yaml` or `release.yaml` locally passes no secrets, so every destination is disabled (AD-9).
  - `--detect-event` is mandatory (ADR-0036): without it act sends `push`, and a `pull_request`-only workflow runs no job and exits 0. Evidence of a local run must show the `build` job executed, not only exit status 0.
  - `just release` requires a clean tree on the default branch, AD-15's sync check, and `just check`, and refuses when the base tag already points at HEAD (the commit is already released). It computes the next version from the latest tag matching `^v\d+\.\d+\.\d+$` (AD-7's pattern) with `pysemver bump`, creates annotated tag `vX.Y.Z`, and pushes only that tag. A release creates no commit.

### AD-17 — Image build contract [ADOPTED]

- **Binds:** `docker/Dockerfile`, `build.yaml`, `publish-image`, `just image`
- **Prevents:** three callers building the image with different inputs; an image not built from the tested wheel.
- **Rule:**
  - Every image build uses `docker/Dockerfile` with context `.` and exactly these build args, all required:
    - `POETRY_VERSION` (Stack);
    - `WHEEL_PATH` (the `dist` wheel);
    - `WHEEL_SHA256` (its SHA-256);
    - `VERSION` (`image-version` in CI; the wheel's PEP 440 version in `just image`, ADR-0036);
    - `REVISION` (the full commit SHA).
  - The image installs that wheel and verifies its hash (ADR-0008's provenance, built with `docker/build-push-action` rather than bake).
  - The Dockerfile verifies the installed version against `VERSION` under PEP 440 normalisation, using the `packaging` vendored in the builder's pip (ADR-0036). `1.4.1-dev.3` and `1.4.1.dev3` both match an installed `1.4.1.dev3`.
  - The Dockerfile's dependency-install step runs with `POETRY_DYNAMIC_VERSIONING_BYPASS=0.0.0`, because the builder has no `.git` (AD-7 `strict`). The installed application version still comes from the hashed wheel (ADR-0036).
  - In a `dev.yaml` publish job, the AD-15 version guard runs before the AD-18 CA import; the CA import is the first step that touches a credential (ADR-0036).
  - Labels come from `git-action-docker-metadata@v6`.

### AD-18 — Private CA [ADOPTED]

- **Binds:** publish jobs
- **Prevents:** TLS failures to a private-CA Gitea from the runner, BuildKit, or `twine`.
- **Rule:** Each publish job's first step is `git-action-ca-certificate-import@v3`, gated on `PUBLISH_CA` (AD-9), with `certificate: PUBLISH_CA_CERTIFICATE` and `generate-buildkit: true`. In `publish-image`, `docker/setup-buildx-action` receives that step's `buildkit-path` output as `config`. `twine` steps set `REQUESTS_CA_BUNDLE: /etc/ssl/certs/ca-certificates.crt`, so Python uses the system store the action updated. That is harmless when no CA was imported.

## Consistency Conventions

| Concern | Convention |
| --- | --- |
| Job ids | `validate-tag`, `build`, `publish-package`, `publish-image`, `release`, identical across workflows. Required check on pull requests: `build / build` |
| Artifact | one artifact `dist`, always downloaded with `path: dist/`, holding exactly one `.whl` and one `.tar.gz` |
| Version hand-off | `needs.build.outputs.version` (PEP 440) and `needs.build.outputs.image-version` (SemVer) only |
| Secrets and variables | `PUBLISH_<DESTINATION>_<FIELD>`, upper snake case, as in AD-9 |
| Conditionals | Only two forms are allowed: AD-9's single-flag `if: env.PUBLISH_X == 'true'` on steps (a job-level `if:` cannot read `env`, so the `release` job gates each of its steps), and the AD-12 validity check. Flags and image names are computed in job `env`, never inline in `if:` |
| Idempotent re-run | uploads use `--skip-existing`; the release step uses `allow-updates: true`; a re-run re-points every tag written by that run, across every enabled registry, to the one digest that run built. It does not reproduce the previous digest (ADR-0036) |

## Stack

| Name | Version |
| --- | --- |
| Gitea (server, minimum) | 1.27.0 |
| LiquidLogicLabs/git-action-docker-metadata | v6 (v6.2.1) |
| LiquidLogicLabs/git-action-docker-test | v2 (v2.0.6) |
| LiquidLogicLabs/git-action-release | v2 (v2.0.11) |
| LiquidLogicLabs/git-action-release-changelog-builder | v3 (v3.0.14) |
| LiquidLogicLabs/git-action-tag-validate-version | v2 (v2.1.8) |
| LiquidLogicLabs/git-action-ca-certificate-import | v3 (v3.0.7) |
| actions/checkout | v7.0.1 `3d3c42e5aac5ba805825da76410c181273ba90b1` |
| actions/setup-python | v7.0.0 `5fda3b95a4ea91299a34e894583c3862153e4b97` |
| actions/upload-artifact | v5.0.0 `330a01c490aca151604b8cf639adc76d48f6c5d4` (newest `act`-compatible; declares node20, runs on Node 24 on GitHub) |
| actions/download-artifact | v6.0.0 `018cc2cf5baa6db3ef3c5f8a56943fffe632ef53` (newest `act`-compatible; declares node20, runs on Node 24 on GitHub) |
| docker/login-action | v4.6.0 `dbcb813823bdd20940b903addbd779551569679f` |
| docker/setup-qemu-action | v4.4.0 `99012661954931238ded8c8b007157a8430204e1` |
| docker/setup-buildx-action | v4.4.1 `f87e5991a6d7451dcb8d9637bfbc97413f497069` |
| docker/build-push-action | v7.4.0 `c3c9e263c25d99ce0380d002d59b67737d91b0dc` |
| Poetry | 2.4.2 |
| poetry-dynamic-versioning | 1.10.0 |
| dunamai | 1.26.2 |
| twine | 7.0.0 |
| semver (`pysemver`) | 3.1.0 |
| zizmor | 1.30.1 |
| gitleaks | v8.30.1 |

## Structural Seed

```text
.github/
  workflows/
    build.yaml      # AD-2: reusable, credential-free; outputs version + image-version
    ci.yaml         # pull_request -> build
    dev.yaml        # push to default branch -> build -> publish-package, publish-image
    release.yaml    # tag v* -> validate-tag -> build -> publish-* -> release
  zizmor.yml        # AD-5 pin policy
  dependabot.yml    # github-actions, pip, docker; artifact actions held below the majors act cannot run
.pre-commit-config.yaml   # AD-3: the one hook list
pyproject.toml            # AD-7: version 0.0.0 + poetry-dynamic-versioning config
justfile                  # AD-16
docker/Dockerfile         # AD-17
```

```text
 deployment / environments
 -------------------------
 runners:     GitHub-hosted | Gitea 1.27+ act_runner | local act        (same YAML)
 indexes:     Gitea PyPI index (dev+rel) | TestPyPI (dev) | PyPI (rel)
 registries:  GHCR | Gitea container registry | Docker Hub (dev+rel)
 enabled:     a destination publishes iff its PUBLISH_*_TOKEN secret is set (AD-9)
 local act:   no secrets -> nothing publishes
```

**Retired with this spine.** These are removed, not ported:
- workflows `verify-build.yaml`, `publish-image.yaml`;
- composite actions `verified-bundle`, `publication-contract`, `setup-poetry-python`;
- `src/publication_contract/` (and its `pyproject.toml` package entry) and `tests/ci/`;
- scripts `scripts/release_version.py`, `scripts/committed_versions.py`, `scripts/vendored_trees.py`, and `vendored-trees.lock`;
- `docker/act-build.sh`;
- the `scriv` dependency;
- `git-action-tag-floating-version`;

**ADRs superseded by ADR-0035:** 0006, 0007, 0009, 0011, 0015, 0019, 0020, 0021, 0022, 0029, 0031, 0032, and the near-miss-probe and untracked-file-gate parts of 0033.

**ADRs amended by ADR-0035:**
- 0008: built with build-push-action, not bake.
- 0010: release credential per AD-9 and AD-13.
- 0012: tags per AD-8.

**ADRs carried forward:** 0004, 0018 and 0028, plus 0033's rule as restated by ADR-0037: the repository adds no path exemption to secret scanning (gitleaks' default allowlist is inherited).

## Deferred

- **Build provenance attestations / SBOM.** GitHub-only (needs OIDC), so they would need a forge condition that AD-9 does not allow. Revisit if Gitea gains an attestation equivalent.
- **Image vulnerability scanning.** No scanner is bound. Revisit when a consumer requires it.
- **Branch protection.** This is a forge setting outside the repository; the required check is named in the Conventions table.
- **Live certification on Gitea 1.27.** The artifact action pair (upload v5.0.0, download v6.0.0), reusable `workflow_call`, `concurrency`, and `twine` uploads are verified by running the workflows on a real Gitea runner during implementation (E013-S01-004).
- **Artifact action majors.** Under `act` 0.2.89, upload-artifact v6+ fails at upload (`Error unauthorized`, signature padding, nektos/act #6114) and v7 also sends an unknown `mime_type` (#6022); verified 2026-10-09 with a two-job upload/download matrix (v4.6.2/v4.3.0 and v5.0.0/v6.0.0 pass, v6.0.0 with v6.0.0/v7.0.0 fail). Dependabot ignores those majors until an `act` release ships PR #6174, then revisit.
