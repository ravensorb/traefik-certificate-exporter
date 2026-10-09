---
review: web-verification
target: ../ARCHITECTURE-SPINE.md (+ ../.memlog.md)
date: 2026-10-08
lens: every committed decision checked against live sources (GitHub API, PyPI JSON, upstream source/docs), not training data
verdict: NOT READY — versions/SHAs are correct, but 1 critical and 4 high findings show behaviours the spine relies on are not real as written
---

# Web-verification review — CI/CD pipeline spine 2026-10-08

## Verdict

**Not ready to bind.** The Stack table holds up completely: every version is current and every
SHA matches its tag. The spine's problems are in *behaviour*. It assumes things the upstream
code does not do. The most serious is in AD-9: the secret name `GITEA_TOKEN` (and the variable
`GITEA_URL`) is reserved on Gitea. A user cannot create it, and Gitea fills it with the
automatic job token. On Gitea the presence gate is therefore always true, and the publish runs
with the ambient token that AD-9 forbids.

| Severity | Count |
| --- | --- |
| CRITICAL | 1 |
| HIGH | 4 |
| MEDIUM | 3 |
| LOW | 5 |

---

## Findings

### F1 — CRITICAL — `GITEA_TOKEN` / `GITEA_URL` are reserved names on Gitea; `secrets.GITEA_TOKEN` is the ambient job token (AD-9, AD-15)

- **Spine claims:** "Each destination publishes only when its secret is set … The automatic `GITHUB_TOKEN` is never used as a publish credential". Secret `GITEA_TOKEN` and variable `GITEA_URL` are listed for the Gitea index and registry.
- **Reality:**
  - Gitea docs (`docs.gitea.com/usage/actions/secrets`): "Secret names must not start with the `GITHUB_` and `GITEA_` prefix."
  - `go-gitea/gitea` `services/secrets/validation.go`: `forbiddenPrefixPattern = regexp.MustCompile("(?i)^(GITEA_|GITHUB_)")`. `services/actions/variables.go` calls the same `ValidateName` for **variables**, so `GITEA_URL` is also rejected.
  - `models/secret/secret.go` `GetSecretsOfTask`: `baseSecrets["GITHUB_TOKEN"] = task.Token` and `baseSecrets["GITEA_TOKEN"] = task.Token`. Reusable-workflow scoping (`getScopedSecretsForJob`) always forwards both.
- **Consequence:** On a Gitea runner, `env.GITEA_TOKEN != ''` is always true. Every Gitea publish step runs with the automatic job token, which is exactly what AD-9 forbids. Fork pull requests also receive this token. The user cannot supply a PAT under this name on Gitea. On GitHub the name is allowed, so the two forges behave differently, which AD-9 says must not happen.
- **Fix:** Rename the secret and variable to names without the reserved prefix (for example `GITEAPKG_TOKEN` / `GITEAPKG_URL`, or `PKG_GITEA_TOKEN`). State in AD-9 that `GITEA_*` and `GITHUB_*` are reserved on Gitea.

### F2 — HIGH — `git-action-tag-validate-version@v2` does not reject anything (AD-12)

- **Spine claims:** it "rejects any tag that is not exactly `vX.Y.Z` before `build` runs."
- **Reality:** In `src/index.ts@v2.1.8`, an invalid parse only produces `logger.warning("⚠ Failed to parse tag …")` and `core.setOutput('is-valid', 'false')`. `core.setFailed` is called only for a missing `version-regex` or an exception. The step passes on a bad tag. Also, `version-type` defaults to `auto`/`semver`, which accepts pre-release and build metadata (`has-prerelease`, `has-build` outputs). So `v1.2.3-rc.1`, which also matches the `v*.*.*` trigger glob, would be "valid".
- **Consequence:** The gate is a no-op. Enforcing it needs both of the following:
  - a `version-regex: '^v\d+\.\d+\.\d+$'` with `version-type: regex`;
  - a follow-up that acts on `is-valid`: a job `if:` or a `run: test …` step.

  The job `if:` is a second kind of conditional, which the Consistency Conventions forbid ("only AD-9's presence check").
- **Fix:** Record the regex and the `is-valid` assertion explicitly, and either allow that one extra conditional or use a one-line `run:` assertion.

### F3 — HIGH — `poetry-dynamic-versioning`/dunamai as specified produce the wrong dev version on this repo (AD-7)

Reproduced with `dunamai 1.26.2` (the pinned version) on this repository and on a scratch repo:

| Command | Result | Spine expects |
| --- | --- | --- |
| `dunamai from git --bump` (this repo, HEAD = v0.2.0 + 9) | `1.dev9` (matched tag **`v0`**) | `0.2.1.dev9` |
| same, `--pattern '^v(?P<base>\d+\.\d+\.\d+)$' --no-metadata` | `0.2.1.dev9` | ✓ |
| scratch: `v1.4.0` + 3, `--bump` (default) | `1.4.1.dev3+3c7fc07` | `1.4.1.dev3` (no hash) |
| scratch: `--bump --format '{base}-dev.{distance}'` **on the tag** | `1.4.0-dev.0` | `1.4.0` (memlog line 15 claims this) |

- The repo already carries the floating tags `v0` and `v0.2` (both created 2026-09-07, both on `v0.2.0`'s commit). Dunamai's default pattern accepts them and picks `v0`.
- The `poetry-dynamic-versioning` README (v1.10.0) confirms that `bump = true` yields `1.3.2.dev3+28c1684`, and that metadata is included whenever the commit is not tagged.
- The memlog's "on tag gives 1.4.0" is true only **without** `--format`.
- **Fix:** Record the binding `[tool.poetry-dynamic-versioning]` config in AD-7: `pattern` anchored to `X.Y.Z`, `metadata = false`, `bump = true`. Either delete the legacy `v0`/`v0.2` tags or rely on the anchored pattern. Any SemVer `format` must handle `distance == 0` (`format-jinja`).
- **Verified OK:** Poetry 2 `[tool.poetry.requires-plugins]` support is documented (README §Installation). PyPI shows `poetry-dynamic-versioning` 1.10.0 and `dunamai` 1.26.2 as latest.

### F4 — HIGH — "pushes when the tag list is non-empty" is not a real behaviour; zero enabled registries does not yield an empty list (AD-10)

- **`git-action-docker-metadata@v6.2.1`:** The README says "If `images` is empty, tags will be generated without base name". `src/meta.ts` `getTags()` confirms this: `images.length > 0 ? … : tags.push(...this.generateTags(version))`. The blank-line dropping in `getInputList` is real (memlog verified this correctly). But when all three names are blank, the output is bare tags (`0.2.1-dev.9`, `sha-1e89fff`, `dev`), not an empty list.
- **`docker/build-push-action@v7.4.0`:** `push` is `getBooleanInput` and tags are passed straight to `--tag`. I reproduced locally with buildx v0.37.1: `docker buildx build --push` with no tags fails with `ERROR: failed to build: tag is needed when pushing to registry`. With bare tags it would try `docker.io/library/<tag>`.
- **Consequence:** The "no image registry configured" combination, which AD-9 says is allowed, makes `publish-image` fail or push to the wrong place. The `push` expression the spine implies (`tags != ''`) never evaluates false.
- **Fix:** Gate `push` on something that really is empty when no registry is enabled, such as the concatenated image names in job `env`, and record that expression.

### F5 — HIGH — `pypa/gh-action-pypi-publish` does not run on Gitea `act_runner` / local `act` as-is (AD-11, AD-1 "same YAML")

- **Mechanism (v1.14.2 `action.yml`):** a composite action writes a trampoline `runs.using: docker` action whose image is `docker://ghcr.io/pypa/gh-action-pypi-publish:<action_ref>`. The SHA-tagged image does exist on GHCR. The entrypoint `twine-upload.sh` runs `set -Eeuo pipefail` and then expands `${GITHUB_WORKFLOW_REF}` at line 45.
- **Gitea does not set `GITHUB_WORKFLOW_REF`:**
  - `go-gitea/gitea` `services/actions/context.go` has no `workflow_ref` key.
  - The `act` code vendored into `gitea/act_runner` main (`act/runner/run_context.go:1634`) sets only `GITHUB_WORKFLOW`.
  - So the action fails with "unbound variable". This is upstream issue pypa/gh-action-pypi-publish#275 (Gitea), and #278 covers the same failure under `act`.
  - The maintainers closed #275 as out of scope ("I don't think it makes sense for us to maintain such corner cases"). They suggested setting the variable to a dummy value via `env:`, or using `twine` directly.
- **Fix:** Pick one and record it:
  - set `GITHUB_WORKFLOW_REF` in job `env` (on GitHub this overrides the real value, which is used only for a nudge message);
  - or make the Gitea-index upload a `run: twine upload` step (this falls under AD-5's "run only when no action fits").

  Either way, record that Gitea is an unsupported environment for this action.
- **Verified OK:**
  - Inputs `repository-url`, `password` and `attestations` exist.
  - With `attestations: false` and a password, no OIDC is attempted.
  - `user` defaults to `__token__`. Gitea's basic auth (`services/auth/basic.go`) resolves a token passed as the password regardless of username, so the default user works against the Gitea PyPI index.

### F6 — MEDIUM — The artifact actions' "v4: Gitea artifact protocol" rationale is stale (Stack)

- The SHAs are correct, and v4.6.2 / v4.3.0 are the last v4 releases. But both declare `runs.using: node20`. GitHub's Node 20 deprecation post (editor's note of 2026-08-25) says "remove Node20 on September 23rd, 2026", which is two weeks before this spine.
- Gitea PR #36786, "Feature non-zipped actions artifacts (action v7 / nodejs / npm v6.2.0)", merged 2026-03-25 with milestone **1.26.0**. Its earlier v4 backend fix (#36805) is also in 1.26.0.
- The upload-artifact v5 and v6 release notes describe only Node 24 runtime changes, not a protocol change. The same "v5+ are GitHub-only" claim sits in `.github/dependabot.yml`.
- **Fix:** Re-test on the target Gitea version and move to the current major (v7 upload / v8 download), or record why the project stays on a Node 20 action.

### F7 — MEDIUM — The Gitea features the spine relies on carry minimum versions it never states (AD-1, AD-2, AD-14)

| Feature | Gitea PR | Milestone |
| --- | --- | --- |
| `concurrency` syntax (AD-14) | #32751 | 1.26.0 |
| Server-side reusable workflows (`build.yaml` via `workflow_call`, AD-1/2) | #37478 `feat(actions)!` | 1.27.0 |
| Reusable-workflow fixes (caller event/inputs) | #39452 | 2026-09-27 |
| Concurrency fixes | #39437, #39461 | 2026-09-26 and 2026-09-29 |
| v7 artifacts | #36786 | 1.26.0 |

- Latest Gitea is v28.1.0 (2026-10-06). `docs/adr/0010` references Gitea 1.24.7 and 1.26.4. The memlog's assumption that `act_runner` ignores concurrency is outdated for ≥1.26, but it still holds for older servers.
- `vars` is supported: the Variables docs page exists, and `services/actions/variables.go` is present.
- **Fix:** State a minimum Gitea server and `act_runner` version in the spine's deployment section.

### F8 — MEDIUM — AD-7's "read from wheel metadata, never recomputed" does not yield the image's SemVer spelling (AD-7, AD-8)

- The wheel carries the PEP 440 string `X.Y.(Z+1).devN`. `git-action-docker-metadata`'s `type=semver` parses with `semver.valid` / `semver.parse({loose:true})` (`src/meta.ts procSemver`).
- Tested with node `semver@7`: `1.4.1.dev3` → `null` (invalid); `1.4.1-dev.3` → valid.
- So the dev image tag needs one of the following:
  - a string conversion step, which is custom logic AD-4/AD-5 discourage and the spine doesn't name;
  - a second dunamai call, which is recomputation, contradicting AD-7;
  - `type=pep440`, which exists in the fork's README but emits the PEP 440 spelling, contradicting AD-8.
- **Fix:** Pick one and record it.

### F9 — LOW — zizmor will fail the hook on `use-trusted-publishing` (AD-3, AD-5)

- zizmor 1.30.1 `audit/use_trusted_publishing.rs` raises an `Informational` / `High`-confidence finding when the `password` input is used with `upload.pypi.org` or `test.pypi.org`. Any finding makes zizmor exit non-zero, which fails pre-commit.
- The spine's `.github/zizmor.yml` covers only `unpinned-uses`. A `rules.use-trusted-publishing.disable: true` entry, or inline ignores, is needed. Both are standard configuration, so AD-4 is satisfied, but the entry must be recorded.
- **Verified OK:**
  - `rules.unpinned-uses.config.policies` with `hash-pin` / `ref-pin` / `any` and `*` patterns (docs/audits.md, v1.6.0+).
  - The `.github/zizmor.yml` discovery path (docs/configuration.md, first in the order).
  - The official hook `zizmorcore/zizmor-pre-commit` (tag v1.30.1, `id: zizmor`).
  - `secrets-outside-env` fires only under the auditor persona (≥1.24), so it does not affect the default hook.

### F10 — LOW — `git-action-release` defaults `token` to `${{ github.token }}` (AD-9 vs AD-15)

The `action.yml@v2.0.11` default is `${{ github.token }}`. AD-15 grants `contents: write` for this, which is consistent. But AD-9's absolute "the automatic `GITHUB_TOKEN` is never used as a publish credential" reads as contradicting it. Clarify that forge-release creation uses the ambient token. The `changelog-builder` `token` likewise defaults to the "environment token".

### F11 — LOW — The `just release` mechanics need two details recorded (AD-13)

- `semver 3.1.0` CLI: `pysemver bump patch 1.4.0` → `1.4.1`, and `pysemver bump minor v1.4.0` → `ERROR v1.4.0 is not valid SemVer string` (exit 2). The recipe must strip the `v`.
- "Last tag": on this repo, `git describe --tags --abbrev=0` warns `tag 'v0' is externally known as 'v0.2.0'`, because the legacy floating tags are annotated copies. The recipe needs `--match 'v[0-9]*.[0-9]*.[0-9]*'` (or `--exclude`) for this, which is the same root cause as F3.

### F12 — LOW — Testing a *pushed* image silently skips its healthcheck (AD-10)

`git-action-docker-test@v2.0.6` runs `docker inspect <image>` (`src/lib/docker.ts extractHealthcheck`) **before** `docker run` pulls the image. When the image is not local, inspect fails and the action logs "No healthcheck detected", then skips verification (`src/index.ts:46-154`). This is latent today because `docker/Dockerfile` has no `HEALTHCHECK`. A `docker pull` before the test step avoids it.

### F13 — LOW — Unstated inputs in AD-10 and AD-15

- `docker/login-action@v4.6.0` needs `username`, and no username is defined for GHCR or Gitea. Gitea ignores the username for token auth, but a non-empty value is still required.
- `docker buildx` (`docker-container` driver) does not trust the host CA store. A private-CA Gitea registry needs `git-action-ca-certificate-import`'s `generate-buildkit: true` → `buildkit-path` output → `docker/setup-buildx-action`'s `buildkitd-config` input. All of these inputs exist; the wiring is unstated.

---

## Verified as stated

| Item | Evidence |
| --- | --- |
| All 9 third-party SHAs match their tags | `gh api repos/<o>/<r>/commits/<tag> --jq .sha` (e.g. checkout v7.0.1 `3d3c42e…`, build-push v7.4.0 `c3c9e26…`, pypi-publish v1.14.2 `dc37677…`) |
| checkout, setup-python, login, qemu, buildx, build-push, pypi-publish are the latest releases | `releases/latest` |
| 6 LiquidLogicLabs majors resolve to the stated patch (major tag SHA == patch SHA) and are latest | docker-metadata v6.2.1, docker-test v2.0.6, release v2.0.11, changelog-builder v3.0.14, tag-validate v2.1.8, ca-import v3.0.7 |
| LLL inputs/outputs exist | docker-metadata `images`/`tags`, `type=sha` default `prefix=sha-` with 7-char short SHA, `type=semver` patterns with `{{major}}`/`{{major}}.{{minor}}` (pre-release extends only `{{version}}`), `latest` auto on semver; release `body`/`artifacts` (comma globs)/`platform`; changelog-builder output `changelog`; docker-test `image`; ca-import `certificate` |
| docker-metadata drops blank and `#` lines in `images` | `src/context.ts` `getInputList('images', {ignoreComma: true, comment: '#'})` |
| poetry-dynamic-versioning 1.10.0, dunamai 1.26.2, semver 3.1.0, zizmor 1.30.1, gitleaks v8.30.1 are latest | PyPI JSON / GitHub releases |
| `pysemver bump <part> <version>` syntax | ran semver 3.1.0 CLI |
| Secrets cannot be used in `if:` | GitHub docs `use-secrets.md`: "Secrets cannot be directly referenced in `if:` conditionals. Instead, consider setting secrets as job-level environment variables …". (Applies to step `if` too, not only job-level as the memlog says.) |
| A step's own `env` is visible to its `if` | actions/runner `StepsRunner.cs` evaluates the step environment into the `env` context (l.124) before `EvaluateStepIf` (l.221); act_runner `act/runner/step.go` runs `setupEnv` (l.89) before `isStepEnabled` (l.92) |
| `secrets` usable in job `env` | GitHub contexts table: `jobs.<job_id>.env` → `…, vars, secrets, inputs` |
| Workflow-level `concurrency` may use `github` | contexts table: `concurrency` → `github, inputs, vars` |
