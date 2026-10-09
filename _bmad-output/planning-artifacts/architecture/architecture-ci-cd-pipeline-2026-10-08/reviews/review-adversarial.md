---
review: adversarial (two-units-one-level-down)
target: ../ARCHITECTURE-SPINE.md (status: draft, 2026-10-08)
decision-log: ../.memlog.md (user-settled decisions not relitigated; only tightened)
date: 2026-10-08
verdict: NOT READY — 3 CRITICAL, 6 HIGH, 5 MEDIUM, 2 LOW holes; every one closable by tightening an existing AD or adding an AD, without reopening any settled decision
---

# Adversarial review — CI/CD pipeline spine (2026-10-08)

## Method

For each pair of units one level down (two stories, or two developers, each owning one
workflow/job/recipe), I asked: can both obey every AD to the letter and still produce
outputs that clash? Each "yes" is a hole. For each hole: the two units, how each stays
compliant, the clash, severity, and the exact rule text that closes it.

Evidence used beyond the spine: `pyproject.toml` (no `[tool.poetry-dynamic-versioning]`
section; `packages` still lists `publication_contract`; `[build-system]` is plain
`poetry-core==2.4.0`), `docker/Dockerfile` (requires build args `POETRY_VERSION`,
`WHEEL_PATH`, `WHEEL_SHA256`, `VERSION`, `REVISION`), `.pre-commit-config.yaml` (mypy
`files:` scoped to `src/publication_contract/` and retired scripts; gitleaks `entry`
already overridden to `gitleaks dir`), current `justfile` recipe set.

Items marked **[verify]** depend on forge/tool behaviour I did not prove in this review;
the rule text is written so it holds regardless, but the claim should be checked during
implementation.

Severity: CRITICAL = wrong bytes/version shipped or a destination silently overwritten;
HIGH = a pipeline that cannot run, or runs differently per forge; MEDIUM = race, scope
gap or local/CI divergence; LOW = naming/clarity.

---

## CRITICAL

### C1 — The version has no single owner and two unconverted spellings

**Units:** story A writes `build.yaml` + `pyproject.toml`; story B writes `publish-image` in
`dev.yaml`; story C writes `publish-image` in `release.yaml`; story D writes `just build`.

**Both compliant, still clash:**
- AD-7 says `poetry-dynamic-versioning` "supplies the version" but no AD fixes its
  configuration. `pyproject.toml` has no `[tool.poetry-dynamic-versioning]` section today.
  pdv's default for a commit 3 past `v1.4.0` is `1.4.0.post3.dev0+g<hash>` — a local
  version PyPI rejects, and not the `1.4.1.dev3` AD-7 requires. A developer who sets
  `bump = true, style = "pep440"` and one who writes `format-jinja` produce different
  strings; both "use pdv".
- AD-7 says publish jobs read the version "from the built wheel's metadata". The wheel
  carries `1.4.1.dev3`. The image needs `1.4.1-dev.3`. No AD names who converts. Story B
  writes a `run:` string-rewrite (custom code AD-4 discourages); story C uses
  `git-action-docker-metadata` `type=semver` patterns, which read `github.ref` (the git tag),
  not the wheel — a second version source in direct contradiction of AD-7's last bullet,
  yet story C cites AD-8 and the memlog ("via git-action-docker-metadata semver patterns").
- The Dockerfile takes `ARG VERSION` (label). Nothing says which spelling goes there.
- Local: if the pdv plugin is not installed, `poetry build` silently emits `0.0.0`; `just
  image` then builds an image labelled from a `0.0.0` wheel while CI's is `1.4.1.dev3`.
  `[build-system]` does not declare pdv, and nothing requires the plugin.

**Proposed rule — tighten AD-7 and add AD-16:**

> **AD-7 (add bullets).**
> - `pyproject.toml` carries exactly:
>   `[tool.poetry-dynamic-versioning] enable = true, vcs = "git", style = "pep440", bump = true, metadata = false, dirty = false, strict = true, pattern = "^v(?P<base>\\d+\\.\\d+\\.\\d+)$"`,
>   `[tool.poetry.requires-plugins] poetry-dynamic-versioning = { version = "==1.10.0", extras = ["plugin"] }`,
>   and `[build-system] requires = ["poetry-core==2.4.0", "poetry-dynamic-versioning==1.10.0"]`, `build-backend = "poetry_dynamic_versioning.backend"`.
>   No workflow or recipe passes pdv/dunamai options on a command line; this table is the only place the version format is defined.
> - `strict = true` makes a checkout with no matching tag fail the build instead of emitting `0.0.0`.
>
> **AD-16 — Version hand-off [NEW].**
> - **Binds:** `build.yaml`, every publish job, `justfile`, `docker/Dockerfile`.
> - **Rule:** `build.yaml`'s build job computes two values once, after `poetry build`, and exposes them as `workflow_call` outputs `version` (PEP 440, read from the wheel's `METADATA` `Version:` field) and `image-version` (SemVer, produced by `dunamai from git --pattern '^v(?P<base>\d+\.\d+\.\d+)$' --bump --format '{base}-dev.{distance}'` when distance > 0 and `--format '{base}'` otherwise — expressed as `dunamai from git ... --format-jinja` with the same pattern as AD-7, one invocation, no shell branching). Publish jobs read only `needs.build.outputs.version` / `needs.build.outputs.image-version`. Every `git-action-docker-metadata` tag uses `value=${{ needs.build.outputs.image-version }}` explicitly; no tag is derived from `github.ref`. The Dockerfile `VERSION` build arg receives `image-version`; `REVISION` receives `github.sha`. `just build` and `just image` obtain the same two values by the same commands.
> - **Enforced by:** `strict = true` (no-tag fails); the two strings are produced by pinned tools from one pattern. Not mechanically enforced: that publish jobs do not recompute — reviewed.

### C2 — `sha-<short>` is written by both dev and release, to different digests

**Units:** `publish-image` in `dev.yaml` vs `publish-image` in `release.yaml`.

**Both compliant, still clash:** AD-8 gives both channels a `sha-<7-char>` tag. Commit C is
pushed to main → dev run pushes `sha-C` → image with `VERSION=1.4.1-dev.3`. `just release`
then tags C `v1.4.1` → release run pushes `sha-C` again → different image (different wheel
version baked in, different digest). `sha-C` now silently points at whichever ran last,
and the dev/release concurrency groups (AD-14) are separate, so the order is not even
defined. One tag, two owners.

**Proposed rule — tighten AD-8:**

> - Dev images: `X.Y.(Z+1)-dev.N`, `sha-<7-char short sha>`, `dev`.
> - Release images: `X.Y.Z`, `X.Y`, `X`, `latest`. **Release images carry no `sha-` tag.**
> - Every tag in the union of both lists has exactly one writing workflow: `dev`, `sha-*` and `*-dev.*` are written only by `dev.yaml`; `latest`, `X`, `X.Y`, `X.Y.Z` only by `release.yaml`.
> - `git-action-docker-metadata` is configured with `flavor: latest=false` in both workflows, and `latest` is emitted only as an explicit `type=raw,value=latest` in `release.yaml`.

### C3 — A dev run on a tagged commit publishes the release version

**Units:** `dev.yaml` `publish-package` vs `release.yaml` `publish-package`; `just release`.

**Both compliant, still clash:** AD-13's `just release` requires "a clean tree on the
default branch" but not that the branch is pushed. If local `main` is ahead of `origin`,
pushing tag `v1.4.1` carries the commits; a later `git push` of `main` triggers `dev.yaml`
on a commit at **distance 0**. With `bump = true`, distance 0 yields the bare base:
package `1.4.1`, image `1.4.1`. `dev.yaml` uploads `1.4.1` to the Gitea index (dev+release
destination); `release.yaml` then fails with a 409 on the same file — or, if it ran first,
`dev.yaml` fails. The dev image also writes `1.4.1`, a tag C2 assigns to release only.
`git push --atomic origin main v1.4.1` produces the same race directly.

**Proposed rule — tighten AD-13 and AD-7:**

> **AD-13:** `just release` requires a clean tree, `HEAD` on the default branch, and `HEAD` equal to `origin/<default>` after `git fetch` — so the tagged commit has already been built by `dev.yaml` at distance ≥ 1 and no later default-branch push can land on it. It pushes only the tag (`git push origin vX.Y.Z`), never the branch.
>
> **AD-7 (add):** The version format cannot tell the dev channel from the release channel (both see a tagged commit at distance 0 as `X.Y.Z`), so channel separation rests on AD-13's precondition, not on the format. Pushing the default branch and a release tag together (`git push --atomic`, `--follow-tags`) is unsupported. If it happens, the collision fails loudly: AD-11's `skip-existing: false` makes the second upload of `X.Y.Z` fail, and C2's single-writer tag rule means the `X.Y.Z` image tag written by `dev.yaml` is a visible defect, not a silent overwrite.

Not mechanically enforced: the forge cannot stop a hand-pushed branch-and-tag pair. AD-13
should say so in the rule itself, per global rule 3.

---

## HIGH

### H1 — The `dist` artifact has no fixed on-disk shape

**Units:** story A (`build.yaml` upload) vs story B (`publish-package` download) vs story C
(`release` job asset attach) vs `just image`.

**Clash:** `actions/upload-artifact@v4` with `path: dist/` stores the files **without** the
`dist/` prefix; `actions/download-artifact@v4` with only `name: dist` extracts them into the
workspace root. `pypa/gh-action-pypi-publish` defaults `packages-dir: dist/` → "no
distributions found". Story B fixes it with `path: dist`; story C with `packages-dir: .`;
`build-push-action` context then sees the wheel at a different path from what the
Dockerfile's `WHEEL_PATH` expects. Locally, `poetry build` appends to an existing `dist/`,
so `just image` can see two wheels (the Dockerfile's "exactly one wheel" contract fails, or
a stale wheel is picked).

**Proposed rule — add to Consistency Conventions and AD-2:**

> | Artifact | name `dist`; uploaded with `path: dist/`; **every** consumer downloads with `name: dist, path: dist/`; contents are exactly one `dist/*.whl` and one `dist/*.tar.gz`. `just build` deletes `dist/` before `poetry build`. |

### H2 — Three callers of the Dockerfile, no shared build-arg contract

**Units:** `build.yaml` smoke build (AD-2) vs `publish-image` (AD-10) vs `just image` (AD-13).

**Clash:** `docker/Dockerfile` requires `POETRY_VERSION`, `WHEEL_PATH`, `WHEEL_SHA256`
(and takes `VERSION`, `REVISION`). The spine names none of them, and **Poetry's version is
not in the Stack table** — so the setup step (AD-2) and the `POETRY_VERSION` build arg each
pick one independently. Three call sites, three owners. Also AD-2's stated "Prevents: a
publish job testing different bytes from the ones it ships" is not delivered for the image:
the smoke-tested image is single-arch and locally built; the shipped one is rebuilt
multi-arch by a different job. (Acceptable given the memlog decision, but the Prevents line
overstates — global rule 3.)

**Proposed rule — new AD-17:**

> **AD-17 — Image build contract [NEW].**
> - **Binds:** every `docker build` / `docker/build-push-action` / `just image` invocation.
> - **Rule:** Every image build uses context `.`, file `docker/Dockerfile`, and exactly these build args: `POETRY_VERSION` = the Poetry version in the Stack table; `WHEEL_PATH` = `dist/<the one wheel>`; `WHEEL_SHA256` = its sha256; `VERSION` = `image-version` (AD-16); `REVISION` = the commit sha. The Stack table gains a `poetry` row, and the Python setup step installs that exact version. AD-2's Prevents line is amended to "a publish job **packaging** different bytes from the ones it tested"; the image's own bytes are tested after push (AD-10), not before.

### H3 — Image references and registry logins are under-specified across forges

**Units:** `publish-image` in `dev.yaml` vs in `release.yaml`, run on GitHub vs on Gitea.

**Clashes:**
1. Owner is "from `github.repository_owner`" (Conventions). On a Gitea runner that is the
   **Gitea** owner; AD-9 says GHCR publishes "regardless of which forge runs", so a Gitea run
   pushes to `ghcr.io/<gitea-owner>/...` — a different (or nonexistent) GHCR namespace from
   a GitHub run. The same row also says "never read from forge-specific contexts", which
   `github.repository_owner` is.
2. GHCR rejects upper-case repository names; nothing lower-cases the owner, and doing so
   needs a script or expression nobody owns.
3. `GITEA_URL` shape is undefined: the registry needs `host[:port]` (no scheme); the PyPI
   index needs `https://host/api/packages/<owner>/pypi`. Story A sets `https://git.x`,
   story B strips the scheme with a `run:` step, story C expects a bare host.
4. Login usernames: AD-9 lists no username for GHCR or Gitea. `docker/login-action` needs
   one; Gitea's PyPI upload uses basic auth with the account name, not `__token__`
   **[verify]**. Each story picks a different source.
5. AD-10's "image name set in job env to an empty string when its secret is absent"
   requires an expression of the form `secrets.X != '' && '...' || ''` — that is a
   combined expression, which the Conventions row forbids, and no AD fixes its form.

**Proposed rule — replace the Conventions "Image name" row and tighten AD-9/AD-10:**

> **Variables (AD-9 table gains a column of required variables per destination):**
> | Destination | Secret | Variables |
> | GHCR | `GHCR_TOKEN` | `GHCR_USERNAME`, `GHCR_IMAGE` |
> | Gitea container registry | `GITEA_TOKEN` | `GITEA_USERNAME`, `GITEA_REGISTRY` (host[:port], no scheme), `GITEA_IMAGE` |
> | Gitea package index | `GITEA_TOKEN` | `GITEA_USERNAME`, `GITEA_PYPI_URL` (full upload URL) |
> | Docker Hub | `DOCKERHUB_TOKEN` | `DOCKERHUB_USERNAME`, `DOCKERHUB_IMAGE` |
>
> Every `*_IMAGE` variable is the full, lower-case reference without tag (e.g. `ghcr.io/ravensorb/traefik-certificate-exporter`). No workflow derives an owner, host or image path from `github.*` / `gitea.*` contexts or from `GITEA_URL`. `GITEA_URL` is removed.
>
> **AD-10 (replace first bullet):** `publish-image` job `env` sets each image name with exactly one expression of the form `${{ secrets.<TOKEN> && vars.<NAME>_IMAGE || '' }}`. This is the only non-step conditional allowed, and AD-9's step-level presence check is the only other. Conventions "Conditionals" is amended to name both.

### H4 — The forge release step has no legal credential

**Units:** `release` job on GitHub vs on Gitea.

**Clash:** AD-12 creates the release "on the running forge"; AD-15 gives the job `contents:
write` — which only affects the ambient token; AD-9 forbids `GITHUB_TOKEN` "as a publish
credential". Story A passes `github.token` (allowed? is a release a publication?), story B
passes `GITEA_TOKEN` — which on a GitHub run is a token for a **different** forge and fails.
The release step is also ungated, so it is the one step that does not follow AD-9.

**Proposed rule — tighten AD-9 and AD-12:**

> **AD-9 (add):** Forge-release creation in `release.yaml`'s `release` job is not a destination. It always runs, and it authenticates with the running forge's ambient token (`${{ github.token }}`), which is the only use of the ambient token anywhere. On Gitea this token must be permitted to create releases **[verify act_runner token scope]**.

### H5 — A run with zero enabled registries fails, and the image is published before it is tested

**Units:** `publish-image` on a fork's main, on `just act dev.yaml`, or on a Gitea instance
with only package secrets.

**Clash:** AD-10 pushes "when the tag list is non-empty" (a second, unnamed conditional:
`push: ${{ steps.meta.outputs.tags != '' }}`) and then runs `git-action-docker-test@v2`
on "the pushed image" unconditionally — so with no registry enabled, the test step pulls a
nonexistent image and the run fails. With several registries enabled, story A tests
`ghcr.io/...:tag`, story B tests the Docker Hub ref; one may not exist on that run. Whether
`git-action-docker-metadata@v6` errors when every `images:` line is blank is unspecified
**[verify]**. Separately, the release image's `latest`, `X`, `X.Y` are already moved
before the test runs; a failing test leaves a broken `latest` published.

**Proposed rule — tighten AD-10:**

> - Pick one, and state it in the rule. (a) **Preferred, adds no conditional:** `build-push-action` always runs with `push: true`. A `dev.yaml` or `release.yaml` run with no registry secret fails `publish-image` by design, and the rule names this as the expected result for forks and `act`. (b) The push step and the test step both carry AD-9's presence check against a job-env `ANY_REGISTRY` value. This adds a second named conditional form to the Conventions.
> - `git-action-docker-test@v2` tests `<first non-empty image>@<digest>` from the build step's `digest` output — by digest, never by tag. A failed test fails the job and therefore blocks the `release` job (AD-12). The spine records that a failed test leaves the moved tags in place; recovery is a new patch release.

(The architect must pick one branch of the first bullet; the hole is that the spine is
silent, not which answer is right.)

### H6 — Gate scope after retirement: mypy checks nothing, the build includes a retired package

**Units:** the retirement story (deletes `src/publication_contract/`, retired scripts) vs
the `.pre-commit-config.yaml` story vs the `pyproject.toml` story.

**Clash (global rule 4 — scope, not rule):** mypy's hook `files:` is
`^(src/publication_contract/|scripts/(committed_versions|release_version)\.py)`. Every path
it matches is retired by this spine. After retirement mypy runs, passes and examines zero
files; AD-3 still lists it as "required". `pyproject.toml` `packages` still includes
`publication_contract` — `poetry build` fails once the directory is gone, or, if a story
keeps the directory "to keep the build green", ships it. The optional `jsonschema` /
`packaging` deps and `scriv` dev-dep are similarly orphaned.

**Proposed rule — tighten AD-3:**

> Each hook's file scope is derived from the source tree, not enumerated: mypy runs with `files: ^src/` (or no `files:` key and `[tool.mypy] packages = ["traefik_certificate_exporter"]`), ruff with its default discovery. The retirement change removes `publication_contract` from `[tool.poetry] packages` and drops `jsonschema`, `packaging` (optional) and `scriv` in the same commit. Check: a planted type error in `src/traefik_certificate_exporter/` must fail `just check`.

---

## MEDIUM

### M1 — Release concurrency is per tag, so two releases race on `latest`/`X`/`X.Y`

AD-14 groups releases by `github.ref`; `v1.4.0` and `v1.4.1` pushed minutes apart run in
parallel and the slower one moves `latest`, `1`, `1.4` last — possibly backwards.
Also: AD-14 cancels in-progress dev runs, which can stop a run after it pushed to registry
A but before registry B (a single `build-push-action` push to several registries is not
atomic), leaving `dev` divergent until the next run. And Gitea Actions' honouring of
`concurrency:` depends on Gitea version **[verify]**; if ignored, AD-14 is silently absent
on one forge.

> **AD-14 (replace):** `dev.yaml`: `concurrency: { group: dev, cancel-in-progress: false }` — a queued newer run supersedes the pending one (GitHub keeps only the latest pending), and a running fan-out is never cut mid-push. `release.yaml`: `concurrency: { group: release, cancel-in-progress: false }` — one release at a time, in order. The spine states the minimum Gitea version that honours `concurrency:`; below it, AD-14 is documented as GitHub-only.

### M2 — `just act` cannot run `build.yaml`, and can publish from a dirty tree

AD-13 mandates "plain `act -W ...`". `build.yaml` uploads an artifact; act requires
`--artifact-server-path` for `actions/upload-artifact@v4`, so `just act` fails on the
default workflow **[verify against pinned act version]**. Conversely, act copies the working
directory (AD-6 forbids replacing it), including uncommitted files; if a developer has a
`.secrets` file, `just act dev.yaml` publishes a dev version computed from git but built
from uncommitted bytes — a real publication AD-9 permits "regardless of forge".

> **AD-13 (replace `just act` row):** `just act [workflow]` runs `act -W .github/workflows/<workflow> --artifact-server-path <tmpdir> --secret-file /dev/null --var-file /dev/null`, default `ci.yaml`. Local `act` never receives destination secrets; publishing happens only on a forge.

### M3 — "Last tag" has two owners: `just release` and dunamai

`just release` "computes the next version from the last tag with `pysemver bump`" — story A
uses `git describe --abbrev=0` (nearest reachable, any pattern), story B uses `git tag
--sort=-v:refname | head -1` (highest, any branch). dunamai uses nearest reachable tag
matching its pattern. A stray `v2.0.0-rc.1` or an off-branch tag makes `just release` and
the dev version disagree about the base.

> **AD-13 (add):** `just release` obtains the base from `dunamai from git --pattern '<AD-7 pattern>' --format '{base}'` — the same tool, version and pattern as AD-7 — and bumps it with `pysemver bump`. Tags not matching the AD-7 pattern are ignored by both. Out-of-band tags (not created by `just release`) are unsupported; release.yaml does not detect them.

### M4 — Partial release re-run is not idempotent

If PyPI upload fails after Gitea index and images succeed, the `release` job is skipped
(AD-12 requires both publish jobs). "Re-run all jobs" rebuilds and re-uploads to the Gitea
index → 409. "Re-run failed jobs" reuses the artifact. Two operators, two outcomes.

> **AD-11 (add):** Recovery from a partially failed publish is "re-run failed jobs" only, which reuses the `dist` artifact. Every `pypa/gh-action-pypi-publish` step sets `skip-existing: false` explicitly, so a full re-run fails loudly rather than shipping rebuilt bytes under an existing version.

### M5 — `X`/`X.Y` and `latest` semantics left to the metadata action's defaults

`git-action-docker-metadata` (a docker/metadata-action fork) suppresses `{{major}}` when
major is `0` and applies `latest=auto` heuristics. Story A uses `type=semver` patterns,
story B uses `type=raw`; the resulting sets differ at `0.x` and for dev versions
(prerelease). Partly closed by C2's `flavor: latest=false`.

> **AD-8 (add):** Release tags are emitted as `type=semver,pattern={{version}}|{{major}}.{{minor}}|{{major}},value=${{ needs.build.outputs.image-version }}` plus `type=raw,value=latest`; dev tags as `type=raw,value=${{ needs.build.outputs.image-version }}`, `type=sha,prefix=sha-,format=short`, `type=raw,value=dev`. At major 0 no `X` tag is produced; this is accepted.

---

## LOW

### L1 — Job ids and the required check name do not match what the forge reports

The Conventions list job ids `build`, `publish-package`, `publish-image`, `release`, but
AD-12 needs a tag-validation job before `build` with no assigned id. A caller job `build`
calling `build.yaml` whose inner job is also `build` reports the check as `build / build`
(caller job / called job), not `ci / build` as the Deferred section states. Also, workflow
`outputs` and artifacts crossing a `workflow_call` boundary on Gitea act_runner are
**[verify]** — C1/AD-16 depend on them.

> **Conventions (replace Job ids row):** `validate` (release.yaml only), `build` (caller job in ci/dev/release), `verify` (the single job inside build.yaml), `publish-package`, `publish-image`, `release`. The required check is `build / verify`. AD-16's outputs and AD-2's artifact must be demonstrated crossing the `workflow_call` boundary on a Gitea runner before Epic sign-off.

### L2 — Private-CA import gating is not per-job consistent

AD-15 imports the CA "in publish jobs that reach Gitea", gated on `GITEA_CA_CERTIFICATE`,
which is not in AD-9's table. Story A puts it in `publish-package` only; `publish-image`
then fails `docker login` to the private-CA registry (buildx also needs the CA in its
builder config **[verify]**).

> **AD-15 (replace first bullet):** `publish-package`, `publish-image` and `release` each run `git-action-ca-certificate-import@v3` as their first step after checkout, gated per AD-9 on `GITEA_CA_CERTIFICATE` (added to AD-9's table as an optional secret with no destination). The buildx builder is created after the import.

---

## Summary table

| Id | Sev | Pair that clashes | Closed by |
| --- | --- | --- | --- |
| C1 | CRITICAL | build.yaml/pyproject vs publish-image (dev, release) vs justfile — version format & SemVer spelling unowned; docker-metadata reads git ref | AD-7 tightened, AD-16 new |
| C2 | CRITICAL | dev vs release publish-image — both write `sha-<short>` | AD-8 tightened |
| C3 | CRITICAL | dev vs release publish — dev at distance 0 publishes `X.Y.Z` | AD-13, AD-7 tightened |
| H1 | HIGH | upload vs download vs release attach — `dist/` path | Conventions, AD-2 |
| H2 | HIGH | smoke build vs publish build vs `just image` — Dockerfile args, Poetry version | AD-17 new |
| H3 | HIGH | GitHub vs Gitea runs — image owner, URL shape, usernames, blanking expression | AD-9/AD-10 + Conventions |
| H4 | HIGH | GitHub vs Gitea release job — credential | AD-9, AD-12 |
| H5 | HIGH | zero/many registries — push condition, test target, test-after-push | AD-10 |
| H6 | HIGH | retirement vs hook config vs pyproject — mypy scope, packages | AD-3 |
| M1 | MEDIUM | two release runs; cancelled dev fan-out; Gitea concurrency | AD-14 |
| M2 | MEDIUM | local act vs forge — artifact server, secrets, dirty tree | AD-13 |
| M3 | MEDIUM | just release vs dunamai — "last tag" | AD-13 |
| M4 | MEDIUM | two operators re-running a partial release | AD-11 |
| M5 | MEDIUM | metadata-action defaults — `latest`, major 0 | AD-8 |
| L1 | LOW | job ids / required check name / Gitea workflow_call outputs | Conventions |
| L2 | LOW | CA import in one publish job only | AD-15 |

No finding reopens a memlog decision: tag-only version source, token-gated destinations,
one multi-arch fan-out, image-only floating tags, generated notes, LLL major pinning,
justfile interface and retirement all stand; each fix narrows how they are implemented.
