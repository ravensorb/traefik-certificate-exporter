---
reviewer: rubric-walker
spine: ../ARCHITECTURE-SPINE.md
decision-log: ../.memlog.md
date: 2026-10-08
verdict: not ready — two critical defects; fix before story breakdown
---

# Rubric-walker review: CI/CD pipeline spine (2026-10-08)

## Verdict

**Not ready to bind stories. The direction is sound, but two critical defects need fixing first.**
The paradigm (one build with no credentials, publish steps gated on tokens, one workflow per
trigger) fits the user's decisions, and the named tech checks out. Two rules cannot work as
written on one of the three runners the spine targets:

1. the Gitea credential names in AD-9;
2. AD-10's "push when the tag list is non-empty".

Beyond those, several real divergence points are left open, so two story implementers would
build different things: the Docker build arguments, the image-version spelling, the Gitea
registry host and owner, how private-CA trust reaches containers, re-run idempotency, and how
`act` gets an artifact server and a tag event. Three of the "carried forward" ADRs contradict
the spine.

No user-settled decision in `.memlog.md` is relitigated below. Every fix stays inside those
decisions: LiquidLogicLabs actions at major tags, token-gated destinations, no custom policy
code, no `env.ACT`, and the agreed dev version spellings.

## How each finding was checked

The following were run or read on 2026-10-08:

- **Third-party SHAs.** Checked with `git ls-remote`. All nine SHAs in the Stack table match
  their tags, and each is the newest tag in its line. `pypa/gh-action-pypi-publish` v1.14.2 is
  an annotated tag: its tag object is `a892a5a…` and the spine correctly pins the peeled commit
  `dc37677…`.
- **LiquidLogicLabs majors.** The latest tags match the Stack table (v6.2.1, v2.0.6, v2.0.11,
  v3.0.14, v2.1.8, v3.0.7).
- **PyPI versions.** poetry-dynamic-versioning 1.10.0, dunamai 1.26.2, semver 3.1.0 and zizmor
  1.30.1 are all current. `zizmor-pre-commit` has a v1.30.1 tag. Poetry is at 2.5.1, but the
  spine names no Poetry version (see F-8).
- **dunamai 1.26.2.** Run against a scratch repo with tag `v1.4.0` plus 3 commits:
  - `--bump --style pep440` gives `1.4.1.dev3+a878967`, which includes a **local hash** by
    default;
  - adding `--no-metadata` gives `1.4.1.dev3`;
  - `--format '{base}-dev.{distance}'` gives `1.4.1-dev.3`;
  - on the tag itself, the output is `1.4.0`.
- **`act` 0.2.89 (local).** A step's own `env:` *is* visible to that step's `if:` under `act`.
  The test workflow is in `/tmp/rv/acttest`.
- **GitHub documentation.** Secrets "cannot be directly referenced in `if:`"; the documented
  pattern is **job-level** `env`.
- **Gitea documentation.** Secret names "must not start with the `GITHUB_` and `GITEA_`
  prefix". Gitea injects `secrets.GITEA_TOKEN` (and `secrets.GITHUB_TOKEN`) as the automatic
  task token. Gitea's `concurrency:` support arrived in **1.26.0**.
- **LiquidLogicLabs action sources.**
  - `git-action-docker-metadata` v6.2.1, `src/meta.ts` `getTags()`: with no image names it
    still emits **bare** tags (`generateTags(version.main)`). The default short SHA is 7
    characters.
  - `git-action-ca-certificate-import` v3.0.7 runs only `update-ca-certificates`. It can also
    write a `buildkit.toml` (`generate-buildkit`). It sets no `NODE_EXTRA_CA_CERTS`, writes
    nothing to Docker `certs.d`, and sets no `REQUESTS_CA_BUNDLE`.
  - `git-action-tag-validate-version` calls `setFailed` only on errors. For a malformed tag it
    reports `is-valid=false` and does not fail.
- **`pypa/gh-action-pypi-publish` v1.14.2.** A composite action that generates and runs a
  **Docker container action** (`docker://ghcr.io/pypa/gh-action-pypi-publish:<ref>`). The image
  tag for SHA `dc37677…` exists on GHCR.
- **Brownfield files.** Read `docker/Dockerfile`, `docker-bake.hcl`, `justfile`,
  `pyproject.toml`, `.pre-commit-config.yaml` and `.github/dependabot.yml`, plus ADRs 0004,
  0008, 0010, 0012, 0018 and 0028. Current `dev.yaml` lines 386–418 record that Gitea's basic
  auth accepts `__token__` as the user.

## Findings

### F-1 [critical] On Gitea, the Gitea secret names cannot be created, and `GITEA_TOKEN` is always set

AD-9 and AD-15 gate the Gitea package index and the Gitea registry on `secrets.GITEA_TOKEN`,
and the CA import on `GITEA_CA_CERTIFICATE`, with variable `GITEA_URL`. On Gitea, which is
where these destinations matter:

- **A user cannot create a secret whose name starts with `GITEA_`.** That rules out
  `GITEA_TOKEN` and `GITEA_CA_CERTIFICATE`. The same prefix rule very likely applies to
  `GITEA_URL` as a variable; this was not confirmed separately.
- **`secrets.GITEA_TOKEN` is the automatic task token, injected into every job.** The presence
  check is therefore always true on Gitea. Both Gitea destinations would publish with the
  ambient token. That breaks two of AD-9's own clauses:
  - "enabled iff its secret is set";
  - "the automatic token is never used as a publish credential".

  Gitea also documents that its automatic token "cannot publish to the package registry of its
  repository", so the upload would also fail at runtime.

**What breaks:** "any combination per run" is impossible on Gitea. Gitea publishing is either
always attempted (and fails) or cannot be configured.

**Fix:** rename every user-supplied name so it avoids the `GITEA_` and `GITHUB_` prefixes. For
example `FORGE_PACKAGE_TOKEN` (the brownfield name, already in `dev.yaml`), `FORGE_URL` and
`FORGE_CA_CERTIFICATE`. Alternatively use a destination-first prefix such as
`GITEAPKG_TOKEN`. Add one sentence to AD-9: *no secret or variable name may start with
`GITHUB_` or `GITEA_`*. This is mechanically checkable with a gitleaks- or zizmor-free
actionlint `config-variables` list, or with a pre-commit `pygrep` hook, so it needs no custom
code.

### F-2 [critical] AD-10's "push when the tag list is non-empty" is false, so the release never happens without a registry

`git-action-docker-metadata@v6` drops blank `images:` lines, as the memlog says. But when
*every* image name is blank, `getTags()` falls back to bare tags such as `1.4.1-dev.3`, `dev`
and `sha-abc1234`. **The tag list is never empty.** `build-push-action` with `push: true` then
tries `docker.io/library/dev:…` and fails.

Consequences:

- **No registry configured.** `publish-image` fails. In `release.yaml`, `release` needs both
  publish jobs, so **no forge release is created even though PyPI published**. That is a
  stranded release.
- **The push gate itself.** It would be a second, non-secret conditional, which the
  Consistency table ("only AD-9's presence check") forbids.
- **The image test.** AD-10's final `git-action-docker-test@v2` on "the pushed image" has no
  image to test when nothing was pushed. Neither its gate nor the image reference it receives
  is specified.

**Fix:** pick one mechanism and write it into AD-10.

- **Recommended:** a job-level `IMAGE_ENABLED` value, computed in `env` as one presence
  expression over the three image secrets. The Docker login, build-push and image-test steps
  are each gated on `env.IMAGE_ENABLED == 'true'`. This is still a presence check and needs
  no custom code.
- **Also add to AD-12:** `release` must not depend on a destination being configured. This
  holds once F-2 is fixed, because publish jobs with every step skipped succeed.
- **Also fix the memlog's "verified" claim.** It covers blank-line dropping only, not the
  empty-images fallback.

### F-3 [high] AD-9's condition form does not work the same way on all three runners

AD-9 says "the secret mapped into the **step's** `env`, and `if: env.<SECRET> != ''`".

- **On GitHub:** the documented pattern is **job-level** `env`. A step's own `env` is not the
  supported source for that step's `if`.
- **Under local `act`:** a step's own `env` *is* visible to its `if` (verified). The same
  YAML would therefore publish under `act` and silently skip on GitHub, which is exactly the
  divergence AD-6 exists to prevent.

**Fix:** define the presence check once per job, at job level, as a boolean rather than the
raw secret. For example:

```yaml
env: { GHCR_ENABLED: "${{ secrets.GHCR_TOKEN != '' }}" }
...
if: env.GHCR_ENABLED == 'true'
```

The token itself then goes only into the consuming step's `with:` or `env:`. This keeps the
secret out of the process environment of every third-party step in the job (`build-push`,
`metadata`, `docker-test`), which job-level raw-secret env would leak to. It stays a single
presence condition.

### F-4 [high] AD-15's CA import does not reach any publish client

`git-action-ca-certificate-import@v3` updates only the runner's system trust store. None of the
three publish paths reads that store:

- **`pypa/gh-action-pypi-publish`** runs twine in a **separate Docker container**, so the host
  store is invisible to it. Twine uses `certifi` regardless.
- **`docker/login-action` and `build-push`** go through the Docker daemon and the BuildKit
  container. A running `dockerd` does not reload host CAs, and BuildKit needs `buildkit.toml`
  passed to `setup-buildx-action` through its `config` input.
- **`git-action-release` and `release-changelog-builder`** are node24 actions. Node uses its
  bundled CA list unless `NODE_EXTRA_CA_CERTS` is set.

**What breaks:** AD-15's "Prevents: TLS failures to a private-CA Gitea" is not achieved for
**any** destination.

**Fix:** state the operational envelope explicitly.

- Private-CA trust for the Docker daemon and for container actions is a **runner-provisioning
  prerequisite**: the act_runner host has the CA in `/etc/docker/certs.d/<host>/ca.crt` and in
  the system store. This is consistent with the "bootstrap trust" half of ADR-0018.
- The CA-import step additionally:
  - uses `generate-buildkit: true`, with the output passed to `setup-buildx-action` `config`;
  - exports `NODE_EXTRA_CA_CERTS` for the node actions;
  - pairs `REQUESTS_CA_BUNDLE` with the certificate path for any `run:` steps.
- Record which client each mechanism covers, and that pypi-publish to a private-CA index
  depends on host or daemon trust.

### F-5 [high] The Docker build interface is undecided, and both the Dockerfile and ADR-0008 constrain it

`docker/Dockerfile` (kept per ADR-0004 and ADR-0008) fails closed unless it receives
`POETRY_VERSION`, `WHEEL_PATH`, `WHEEL_SHA256`, `VERSION` and `REVISION`. Note two specifics:

- **`VERSION` must equal the wheel's PEP 440 metadata** (`1.4.1.dev3`), not the image spelling
  (`1.4.1-dev.3`).
- **`REVISION` must be a 40- or 64-character SHA.**

AD-2's smoke build and AD-10's publish build name none of these arguments. ADR-0008 invariant
6 (carried forward) says CI and `just image` both drive **`docker-bake.hcl`**. AD-10 says
`docker/build-push-action`. The bake file appears in neither the Structural Seed nor the
retirement list. One implementer will use bake (`docker/bake-action`, which is not in the
Stack); another will use build-push with hand-copied arguments and labels.

**Fix:** add to AD-10:

- which build front-end is used (keep bake and add `docker/bake-action` to the Stack, or
  retire bake and amend ADR-0008 §6);
- the exact build arguments and their sources: wheel path and SHA-256 from the `dist`
  artifact, `VERSION` from wheel metadata, `REVISION` from `github.sha`, and `POETRY_VERSION`
  from a single declared value;
- that the OCI `version` label carries the PEP 440 value or the SemVer value, chosen once.

### F-6 [high] The image's SemVer spelling has no derivation path that obeys AD-7

AD-7 says the version is "computed once, in `build.yaml`, and read by publish jobs from the
built wheel's metadata, never recomputed". The wheel holds `1.4.1.dev3`. The image tag must be
`1.4.1-dev.3`. Producing it requires one of three things:

- a string transformation, which is a custom script;
- a second dunamai call (`--format '{base}-dev.{distance}'`, from the memlog), which is a
  recompute;
- `git-action-docker-metadata`'s `type=pep440`, which normalises to PEP 440 rather than
  SemVer.

Separately, AD-7 never names the poetry-dynamic-versioning settings that make the package
version legal: `style = "pep440"`, `bump = true`, `metadata = false` (the default emits
`+<hash>`, which PyPI and TestPyPI reject, as verified above) and `dirty = false`.

**Fix:**

- Have the `build` job compute **both spellings once**, from the same dunamai invocation
  context at the same commit.
- Expose them as `workflow_call` outputs (`package-version`, `image-version`) for publish jobs
  to read through `needs.build.outputs`.
- Assert in the `build` job that the wheel's metadata equals `package-version`.
- Write the `[tool.poetry-dynamic-versioning]` block into AD-7 verbatim. Also write in the
  Poetry 2 `[tool.poetry.requires-plugins]` entry, `version = "0.0.0"`, and whether
  `[build-system]` switches to the `poetry_dynamic_versioning.backend` backend. Without that
  backend, a plain `pip wheel` or `python -m build` produces 0.0.0.

### F-7 [high] Re-runs and partial publication are undecided (operational envelope)

PyPI, TestPyPI and the Gitea index all reject re-upload of an existing version. If
`publish-image` fails after `publish-package` succeeded, re-running the release fails at
`publish-package` with "file exists", and `release` can never run. The same thing happens
when `dev.yaml`'s `cancel-in-progress` cancels a run between destinations.

**Fix:** add an AD covering re-run semantics:

- every pypi-publish step uses `skip-existing: true`;
- image pushes are idempotent per digest;
- `git-action-release` uses `allow-updates: true`, which matches the brownfield ADR-0008
  amendment;
- a release re-run is the documented recovery.

### F-8 [medium] The operational envelope is largely unstated

**Minimum runner versions are not declared.** The following need to be stated:

- checkout v7, setup-python v7, login v4 and the LiquidLogicLabs v6/v2/v3 actions are
  `node24`, so act_runner and `act` must support node24;
- `concurrency` needs Gitea 1.26 or later, otherwise AD-14's "Prevents" does not hold on Gitea;
- local `act` ignores `concurrency` entirely.

**Also missing:**

- the Python version, Poetry version and Poetry install method in CI (the
  `setup-poetry-python` composite action is being retired, and the Stack lists neither);
- `timeout-minutes`, which matters because an arm64 QEMU build with `cargo` in the builder
  stage is slow;
- artifact retention;
- the Docker requirement for Gitea runners, which build both images and the pypi-publish
  container.

**Fix:** add an "Operational envelope" section with these values. Where a value is left open,
list it under Deferred with an owner.

### F-9 [medium] `just act` cannot run `build.yaml`, `dev.yaml` or `release.yaml` as specified

- **Artifacts.** Plain `act -W …` starts no artifact server, so `upload-artifact@v4` fails
  without `ACTIONS_RUNTIME_TOKEN`. Every workflow calls `build.yaml`, which uploads `dist`.
- **Release event.** `release.yaml` needs a tag `push` event. Without
  `-e <event.json>` carrying `ref: refs/tags/vX.Y.Z`, `github.ref` is the branch, so tag
  validation rejects the run.
- **Release token.** `git-action-release` and the changelog builder need a token (default
  `github.token`), which is empty under `act` without `-s GITHUB_TOKEN`.

**Fix:**

- `just act` passes `--artifact-server-path` to a temporary directory.
- Add `just act-release <tag>`, which supplies a checked-in event fixture.
- State in AD-13 that a local release run without secrets is expected to skip every
  destination and **stop at `release`**, or else gate `release` on a token too.

None of this needs `env.ACT`.

### F-10 [medium] Owner and host derivation for registries and indexes is unspecified

The Consistency table says the owner comes "from `github.repository_owner` or
`DOCKERHUB_USERNAME`". This leaves four gaps:

- **GHCR on Gitea.** `github.repository_owner` on Gitea is the **Gitea** owner, which may not
  exist on GHCR.
- **Gitea on GitHub.** The Gitea index URL (`<url>/api/packages/<owner>/pypi`) and registry
  image (`<host>/<owner>/…`) take the GitHub owner on GitHub runs.
- **Registry host.** The Gitea registry needs a bare host, but `GITEA_URL` is a URL with a
  scheme. Expressions cannot strip it without a script.
- **Lowercasing.** Expressions have no lowercase function, which GHCR requires.

**Fix:** add explicit variables (`GHCR_OWNER`, `FORGE_OWNER`, `FORGE_REGISTRY` as a bare host,
`DOCKERHUB_NAMESPACE`), all lowercase by convention. Alternatively, state the assumption
"owner is identical and lowercase on every forge" as an envelope constraint.

Record the Gitea `__token__` user, which brownfield `dev.yaml:410-417` shows works. Also record
which username each Docker login uses.

### F-11 [medium] Carried-forward ADRs contradict the spine

| ADR | Contradiction with the spine |
| --- | --- |
| ADR-0008 | Requires bake, `SHA256SUMS`, `build-manifest.json`, and `actions/attest-build-provenance` (OIDC) on PyPI. The spine defers attestations and drops manifests. |
| ADR-0010 | Attaches `SHA256SUMS` and `build-manifest.json`. The spine attaches the wheel and sdist only. |
| ADR-0012 | Its decision is a composition step that **refuses** `latest`, `X` and `X.Y` tags. AD-8 publishes exactly those, and AD-4 bans the policy step. |
| ADR-0018 | Names the `GITEA_PACKAGE_INDEX_CA_CERTIFICATE` and `GITEA_FORGE_API_CA_CERTIFICATE` secrets (both also hit F-1). The spine uses `GITEA_CA_CERTIFICATE`. |

**Fix:** have ADR-0034 list each as *amended*, with the specific clauses superseded, rather
than "carried forward" wholesale.

### F-12 [medium] The brownfield has Dependabot, but the spine defers it

The spine's Deferred section says "Pins are updated by hand until this is decided". Yet
`.github/dependabot.yml` exists and covers `github-actions`, `pip` and `docker`. Its
artifact-v4 ignore cites `tests/ci`, which is being retired. Dependabot updates SHA pins along
with their `# vX.Y.Z` comments.

**Fix:** ratify the existing Dependabot setup in a short AD. Keep the v4 artifact ignore and
re-cite the reason as AD-5 or the Stack. Remove the Deferred item.

### F-13 [medium] Retiring parts of the hook list breaks AD-3

The existing hook list contains three things that will change meaning after the retirement:

- **`workflow-policy`** runs `pytest tests/ci`, which is being retired.
- **The mypy hook** is scoped (`files:`) to `src/publication_contract/` and the retired
  scripts. After retirement it checks **nothing** and stays green. This is the false-green
  scope failure that global rule 4 warns about.
- **`justfile-fmt`** needs `just`, which CI does not install. The hook's own comment says so.

The brownfield `just check` is deliberately non-mutating: `lint` uses `SKIP=` and
manual-stage twins. AD-3's plain `pre-commit run --all-files` silently replaces that behaviour.

**Fix:** in AD-3, specify:

- mypy's scope, derived from `src/`;
- how `just` gets into CI (an action at a pinned SHA), or that the hook is removed;
- whether `check` may mutate the tree;
- removal of the `workflow-policy` hook.

Also add the dependent removals to the retirement list:

- `pyproject.toml`: the `publication_contract` package and script, the extras, and the dev
  dependencies `types-jsonschema`, `dockerfile-parse`, `markdown-it-py`, `pyyaml`, `twine`
  (unless kept) and `scriv`;
- the CODEOWNERS lines that reference retired paths;
- the Dockerfile and bake comments that cite `tests/ci`.

### F-14 [low] Smaller issues

- **AD-12, tag validation.** `git-action-tag-validate-version` does not fail on an invalid
  tag; it only outputs `is-valid=false`. Use `version-type: regex` with
  `^v(?<major>0|[1-9]\d*)\.(?<minor>…)\.(?<patch>…)$` so that a non-match fails. Then confirm
  that a non-match actually calls `setFailed` (from source, it does not); if it does not, gate
  `build` with `needs:` on a job whose `if:` reads `is-valid`. That is a second conditional,
  which needs an explicit exception in the Consistency table.
- **AD-2, build jobs.** Whether `build.yaml` is one job or several (smoke build in parallel
  with test) is unspecified, and so is its job id. The required check name is not
  `ci / build`: a reusable call reports as `<caller job> / <called job>`, for example
  `build / build`. Fix the job id and state the exact check name.
- **AD-6, checkout credentials.** Add `persist-credentials: false`, which zizmor's `artipacked`
  audit flags by default and which ADR-0028 already lists. Also confirm that `fetch-depth: 0`
  is used in **every** job that runs `poetry build` or dunamai. Tags arrive with
  `fetch-depth: 0`, and dunamai accepts the lightweight tag that checkout creates on tag events.
- **AD-13, `pysemver`.** Using `pysemver` requires `semver` as a dev dependency. Say so. Also
  state how "the last tag" is selected: `git describe --tags --abbrev=0 --match 'v*.*.*'`.
- **AD-14, concurrency group.** The `dev` group should include the workflow and ref
  (`dev-${{ github.ref }}`) if forks or other default-branch names are ever in scope. As
  written it is fine for a single default branch.
- **Docker Hub.** The memlog's constraint entry says Docker Hub was "not named"; a later
  decision adds it. Consistent, but the AD-9 table should cite the later decision.

## Checklist walk

| Checklist item | Result |
| --- | --- |
| Fixes the real divergence points | **Partly.** Missing: the Docker build arguments and front-end (F-5), the image-version derivation (F-6), owner and host (F-10), re-run behaviour (F-7), the `build.yaml` job shape (F-14). |
| Every Rule is enforceable and prevents its divergence | **No for AD-9, AD-10 and AD-15** (F-1, F-2, F-3, F-4). AD-5 is enforceable by zizmor. AD-14 holds only on Gitea 1.26 or later. AD-3's mypy scope is not checked (F-13). |
| Nothing under Deferred lets implementers diverge | **The Dependabot item conflicts with the brownfield** (F-12). The attestations deferral conflicts with carried-forward ADR-0008 (F-11). The other deferrals are safe. |
| Named tech is verified-current | **Yes.** All SHAs and versions were verified. Gaps: Poetry and Python versions are unnamed; `docker/bake-action` is missing if bake is kept. |
| Ratifies rather than contradicts the brownfield | **Partly.** It keeps the Dockerfile, but does not ratify its build-argument contract or bake. ADRs 0008, 0010, 0012 and 0018 are contradicted. The `just check` non-mutation property is dropped silently. |
| Every owned dimension is decided, deferred or open, especially the operational envelope | **No.** Runner minimum versions, timeouts, retention, re-run and recovery, private-CA scope and the `act` artifact server are all absent (F-4, F-7, F-8, F-9). |

## Feasibility matrix

| Concern | GitHub | Gitea act_runner | local `act` |
| --- | --- | --- | --- |
| Step-env `if` (AD-9) | Use job-level env | Use job-level env | Works either way |
| `GITEA_*` secret names | Allowed | **Rejected, and `GITEA_TOKEN` is auto-injected** | Allowed |
| Artifacts v4 across jobs | OK | OK (v4 protocol) | **Needs `--artifact-server-path`** |
| Reusable-workflow outputs | OK | OK (act-based) | OK |
| pypi-publish (Docker action) | OK | Needs Docker; host CA not visible | Needs Docker socket |
| CA import reaches clients | n/a | **No** (F-4) | n/a |
| `concurrency` | OK | Gitea 1.26 or later | Ignored |
| Empty image set | **Fails** (F-2) | **Fails** | **Fails** |
| Release without secrets | Uses `GITHUB_TOKEN` | Uses the task token | **Token empty; needs `-s`** |
| dunamai tags | `fetch-depth: 0` | `fetch-depth: 0` | Local `.git` (user must have fetched tags) |
