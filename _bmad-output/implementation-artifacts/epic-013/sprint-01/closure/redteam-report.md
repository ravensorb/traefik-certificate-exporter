# RED TEAM FINDINGS REPORT

**Sprint:** E013 / S01 — standard CI/CD pipeline (GitHub Actions + Gitea Actions + local act), ADR-0035/0036/0037
**Date:** 2026-10-09
**Analyst:** Red Team Agent (l3io-sec-redteam, headless orchestrator invocation)

## SEVERITY SUMMARY

| Severity | Count |
|---|---|
| CRITICAL | 0 |
| HIGH | 2 |
| MEDIUM | 4 |
| LOW | 2 |
| OBSERVATION | 1 |

## Scope and method

**Seed artifacts read:** working-tree state of `.github/workflows/{build,ci,dev,release}.yaml`,
`.github/zizmor.yml`, `.github/dependabot.yml`, `.github/CODEOWNERS`, `.pre-commit-config.yaml`,
`.gitleaks.toml`, `justfile`, `docker/Dockerfile`, the `pyproject.toml` and `.gitignore` diffs,
`docs/ci/pipeline-walkthrough.md`, ADR-0035/0036/0037.

**Widened to, and why:**
- `_bmad-output/planning-artifacts/architecture/architecture-ci-cd-pipeline-2026-10-08/ARCHITECTURE-SPINE.md`
  (AD-11..AD-16, Deferred) — the workflows cite AD numbers for every trust decision; needed to tell
  accepted risk from omission.
- `docs/ci/gitea-runners.md` and `docs/adr/0015-*.md` (status line only) — to trace what replaced
  the superseded runner trust-class split (credential checkpoint on the Gitea forge).
- Story grep (E013-S01-001/002/005) and the sprint's `closure/review-*.md` / `notes-*.md` — to avoid
  re-raising findings already recorded (review-E013-S01-003 M-1 superseded-run tag rewind and M-2
  publish variables are **not** re-raised here).
- Executed `uvx zizmor@1.30.1 --offline --persona=auditor .github/` (read-only): 55 findings, 45 of
  them `secrets-outside-env` (medium), 7 `anonymous-definition` (info), 3 ignored. The gated
  default-persona run (`pre-commit run zizmor`) passes.

**Out of scope, not read:** `docker/root/**`, `libs/docker.py`, `libs/certificate_exporter.py`,
`docs/operational.md`, ADR-0028..0033 (E012).

**Surface map (internal summary).** Entry points: `pull_request` (ci.yaml), `push` to main
(dev.yaml), `push` of `v*` tags (release.yaml), local `just act`/`just release`. Trust boundary:
`build.yaml` is credential-free; publish jobs read repository-level `PUBLISH_*` secrets and `vars.*`.
Credential checkpoints: three `docker/login-action` steps, twine `TWINE_PASSWORD`,
`PUBLISH_RELEASE_TOKEN` into two LiquidLogicLabs actions. Data flow of the shipped bits:
checkout → pre-commit (third-party hook code) → `poetry build` (plugin backend) → smoke test
(LiquidLogicLabs action) → `dist` artifact → publish jobs re-hash and push. No AI/ML runtime
components; AI cross-cut applies via agents that hold repository write access (CODEOWNERS:32-36).

## FINDINGS

| Severity | ID | Title | Lens | Attack Path | Impact | Recommendation |
|---|---|---|---|---|---|---|
| HIGH | RT-E013-01 | Every publish credential is a repository-level secret with no `environment:` gate, so any branch push by a write-holder can read all of them | INS, AIP, PBR | `.github/workflows/dev.yaml:32-34,102-109,126,184,191,197` and `release.yaml:54-56,71,103,112,122-129,278-279` reference `secrets.PUBLISH_*` from jobs with no `environment:`. On GitHub, a workflow on **any** branch receives repository secrets on `push`. A collaborator, a stolen write token, or an agent with write access (CODEOWNERS:32-36 says agents reading the vendored skill trees hold write access) pushes branch `x` adding `.github/workflows/x.yaml` with `on: push` and a step that sends `${{ secrets.PUBLISH_PYPI_TOKEN }}` (and the GHCR/Docker Hub/Gitea/release tokens) to an external host. The run happens before any review. CODEOWNERS (`.github/CODEOWNERS:10-13`) protects only the default branch, and only if branch protection is on. zizmor's auditor persona reports this as 45 `secrets-outside-env` findings. The gated default persona does not show it, and `notes-E013-S01-002.md:30` recorded it as information only. | Theft of the PyPI, TestPyPI, GHCR, Docker Hub, Gitea and release tokens. With them an attacker can publish to the project's PyPI name and overwrite `latest` images without touching `main`. A poisoned instruction file is enough to trigger it through an agent (AI cross-cut). | Put the publish jobs in GitHub environments (`release` restricted to `v*` tags, `dev` restricted to `main`) and move the `PUBLISH_*` secrets into those environments. AD-9's "flag = secret presence" rule still works, because environment secrets are read the same way. Record in an ADR what the Gitea equivalent is, or that none exists, and mitigate there with a dedicated bot account whose tokens are scoped to this repository. Add `secrets-outside-env` to the gate, or suppress it per line with the ADR reason (ADR-0036 §4), instead of leaving it to a non-gated persona. |
| HIGH | RT-E013-02 | A `vX.Y.Z` tag on any commit, including an unreviewed one, publishes a release; a re-pushed tag silently rewrites `X.Y.Z`/`latest` images and release assets | INS, ABU, DAR | `release.yaml:5-7` triggers on any `v*` tag. `validate-tag` (`release.yaml:22-41`) checks only the tag-name regex, and the version guard (`release.yaml:59-64,132-137`) checks only that the wheel version equals the tag. Nothing checks that the tagged commit is reachable from `main`. Those checks live only in `justfile:63-79`, which is client-side and can be bypassed with plain `git push`. Attack: a write-holder pushes an unreviewed commit on a side branch, then `git tag v9.9.9 <sha> && git push origin v9.9.9`. PyPI, the images tagged `9.9.9`, `9.9`, `9`, `latest` (`release.yaml:228-231`) and the forge release are all published from code no reviewer saw. Variant: delete and re-push an existing `v1.4.2` on a new commit. `--skip-existing` (`release.yaml:104,113`) keeps the old PyPI wheel, while the images and `allow-updates: true` release assets (`release.yaml:327-328`) are replaced, so the PyPI and image builds of `1.4.2` now contain different code. | A supply-chain release under the project's identity that bypasses CODEOWNERS review. The second variant leaves PyPI and the image disagreeing on what `1.4.2` is, and downstream users cannot detect it. The spine defers branch protection (`ARCHITECTURE-SPINE.md:341`) but never mentions tag protection. | Add a `validate-tag` step: `git merge-base --is-ancestor "$GITHUB_SHA" origin/main` after a full-history checkout, so the server enforces what `just release` checks on the client. Configure a tag ruleset (GitHub) or protected tags (Gitea) for `v*` that blocks deletion and update and limits creation to the maintainer. Then `allow-updates: true` can only rerun the same commit. Record tag protection next to branch protection in the spine's Deferred list, with the same "documentation unless configured" caveat CODEOWNERS uses. |
| MEDIUM | RT-E013-03 | Pre-commit hooks run third-party code from mutable tags inside the job that builds the published wheel; Dependabot does not watch them | INS, PBR | `.pre-commit-config.yaml:31,39,54,74,81,87` pin six third-party repos by tag (`v6.0.0`, `v0.16.5`, `v8.30.1`, `v1.7.12`, `v1.30.1`, `v1.14.1`). CI runs them in `build.yaml:49-50` on a fresh clone at that tag. The same job then runs `poetry build` (`build.yaml:55-66`) and uploads `dist` (`build.yaml:124-128`), which the publish jobs ship. A moved upstream tag, or a compromised hook repo, executes in that job. pre-commit's "files were modified" check covers only tracked files, so a hook can rewrite the gitignored `.poetry/` plugin backend or `.venv` and backdoor the wheel without failing the gate. The zizmor policy hash-pins the same vendors' *actions* (`zizmor.yml:8`) but nothing applies that rule to hook revs. `dependabot.yml:1-32` has no `pre-commit` ecosystem, which contradicts ADR-0037:51-52. | Code execution in the producer of the published artifact, and nothing downstream detects it (see RT-E013-04). The weakest pin sets the trust level of the build job. | Freeze hook revs to commit SHAs (`pre-commit autoupdate --freeze`, which keeps the tag as a comment). Add a `pre-commit` ecosystem entry to `dependabot.yml` so the SHAs stay current. Correct ADR-0037's Dependabot sentence in the same change. |
| MEDIUM | RT-E013-04 | The image's `WHEEL_SHA256` check verifies the downloaded file against its own hash; the build-time hash is never carried across jobs | DAR, INS | `build.yaml:85,94` computes `wheel-sha256`, but it is not a `workflow_call` output (`build.yaml:7-13` exports only `version`/`image-version`). The publish jobs re-hash whatever `download-artifact` returned (`dev.yaml:162-177`, `release.yaml:180-195`) and pass that as `WHEEL_SHA256` (`dev.yaml:240`, `release.yaml:258`). The Dockerfile check (`docker/Dockerfile:69-77`) can therefore never fail in CI. After the hash is taken, `LiquidLogicLabs/git-action-docker-test@v2` (ref-pinned) still runs in the build job (`build.yaml:120-122`) before upload (`build.yaml:124`), so a moved tag there can swap `dist/*.whl` undetected. Twine uploads (`dev.yaml:84,93`, `release.yaml:104,113`) check no hash at all. | ADR-0008's "the image is built from the tested wheel" holds only by assumption. The guard reads as provenance but compares a value with itself. Global rule 3 calls this kind of overstated coverage worse than none. | Export `wheel-sha256` as a `build.yaml` `workflow_call` output. In each publish job, run `sha256sum -c` against `needs.build.outputs.wheel-sha256` before twine and before the image build, and pass that value, not a recomputed one, to `WHEEL_SHA256`. Move the smoke test after `upload-artifact`, or hash immediately before upload. |
| MEDIUM | RT-E013-05 | Ref-pinned LiquidLogicLabs actions reach more than ADR-0035 accepts: all registry logins, the BuildKit config and a repo-write token | INS, PBR | The ADR-0035:75 acceptance says only that "a moved tag in that org reaches credentialed jobs". In practice: `git-action-docker-test@v2` runs **after** all three `docker/login-action` steps in the same job (`dev.yaml:179-197` then `245-250`; `release.yaml:197-215` then `264-269`), so it can read `~/.docker/config.json` with GHCR, Gitea and Docker Hub credentials. `git-action-ca-certificate-import@v3` output becomes the buildx `config:` (`dev.yaml:220`, `release.yaml:239`), so it can write BuildKit registry mirrors and redirect base-image pulls. `git-action-release-changelog-builder@v3` and `git-action-release@v2` receive `PUBLISH_RELEASE_TOKEN` (`release.yaml:318,324`). `zizmor.yml:7` allows `ref-pin` for the whole org, and a moved major tag generates no Dependabot PR, so nobody sees the change. | One compromise of the maintainer's GitHub org (an account takeover or a malicious contributor to an action repo) yields every publish credential and control of image contents on the next run. The accepted-risk record understates the reach. | The cost of hash-pinning these actions is close to zero: Dependabot already updates SHA pins in this repo with a 7-day cooldown, so switch `zizmor.yml:7` to `hash-pin`. If ref-pin stays, amend ADR-0035's Consequences to list the reach above. Also run the digest smoke test in a job without registry logins, or call `docker logout` before it. Separately, enable immutable releases or tag protection on the LiquidLogicLabs action repos. |
| MEDIUM | RT-E013-06 | On Gitea, untrusted PR jobs and credentialed publish jobs share one runner label that must expose Docker; the trust-class split was retired with no replacement | EXT, DAR, CHA | `docs/ci/gitea-runners.md:9` supersedes ADR-0015's trust-class routing. `gitea-runners.md:17-19` requires one `act_runner` mapping `ubuntu-latest` **with Docker** for every job. `ci.yaml:5-7` runs `build.yaml` for every PR, and that runs PR-controlled pytest, the PR's own `.pre-commit-config.yaml`, and `docker build --load` plus a container run (`build.yaml:100-122`). A self-hosted runner that gives job containers the host Docker daemon gives PR code root on the host. From there the code can persist, poison the shared buildx/image cache, or read the environment of a later `dev.yaml`/`release.yaml` job on the same host. Whether this is reachable depends on the instance's fork-PR approval settings, which no document in scope records. `pipeline-walkthrough.md:35` nonetheless says "fork PRs are safe". | Credential theft and image tampering on the Gitea forge, from an external contributor. GitHub-hosted runners are ephemeral and not affected. | Register a separate runner (label) for PR jobs with no Docker-host access, or an ephemeral or rootless DinD runner. If one YAML must serve all forges, use `runs-on` from a repository variable, which needs no workflow conditional. Require approval for fork-PR runs on the Gitea instance and record that requirement in `gitea-runners.md`. Qualify the "fork PRs are safe" line to GitHub-hosted runners. |
| LOW | RT-E013-07 | The Poetry plugin and the build backend's transitive dependencies resolve fresh on every build, without a committed lock or hashes | INS, PBR | `pyproject.toml:72-73` pins `poetry-dynamic-versioning==1.10.0`, but its dependencies (dunamai, jinja2, markupsafe) resolve into `.poetry/plugins/` at install time. The lock there, `.poetry/plugins/poetry.lock`, is gitignored (`.gitignore:14-15`). `pyproject.toml:86-87` makes that plugin the build backend that computes the published version. | A malicious new release of a transitive dependency reaches the version-stamping backend of the published wheel on the next CI run. The 7-day Dependabot cooldown does not apply, because these are not in `poetry.lock`. | Pin the plugin's transitive dependencies exactly in `requires-plugins` (`dunamai==…`, `jinja2==…`, `markupsafe==…`, matching the versions recorded in `.gitleaks.toml:68-69`). Alternatively record this as an accepted residual next to ADR-0037. |
| LOW | RT-E013-08 | Docs and an ADR state security coverage the pipeline does not have | DAR | `docs/ci/pipeline-walkthrough.md:212` says gitleaks runs "with no path exempted", which ADR-0037 contradicts (`poetry.lock` and `.gitleaks.toml` are exempt). `pipeline-walkthrough.md:180` says a re-run rewrites image tags "to the same digest", which ADR-0036 §5 / AG-10 retracted. `pipeline-walkthrough.md:35` says "fork PRs are safe" (see RT-E013-06). `ADR-0037:51-52` says gitleaks upgrades arrive "through … Dependabot", but no Dependabot ecosystem covers pre-commit (`dependabot.yml:1-32`). | Readers stop looking where the docs claim a guard exists (global rule 3). The walkthrough is the document ADR-0035 points operators to. | Correct the four sentences, and add the `pre-commit` Dependabot ecosystem so ADR-0037's claim becomes true (see RT-E013-03). |
| OBSERVATION | RT-E013-09 | The zizmor gate runs the default persona, so the only audit that flags credential scoping never fails CI | PBR | `.pre-commit-config.yaml:80-83` runs zizmor with no `--persona`. `secrets-outside-env` fires only under `auditor` (verified: 45 findings there, 0 in the gated run). ADR-0036 §4's "every other finding is fixed, not suppressed" rule therefore never sees it. | Credential-scoping regressions stay invisible to the gate. | After RT-E013-01, run zizmor with `--persona=auditor` and add per-line suppressions with reasons for `anonymous-definition`, or name the jobs. |

### Platform best practices (cache `ci-cd-github-actions.md`, 2026-10-06, within the 30-day TTL)

- **Third-party action SHA pinning:** compliant for every non-LiquidLogicLabs action (all `actions/*`
  and `docker/*` uses carry 40-hex SHAs with version comments). Not compliant for LiquidLogicLabs
  (accepted in ADR-0035; see RT-E013-05). GitHub security-hardening guide:
  https://docs.github.com/actions/security-guides/security-hardening-for-github-actions
- **Least-privilege `permissions:`:** compliant. Every workflow and job is `contents: read` (AD-13).
- **Fork-PR trigger:** compliant on GitHub (`pull_request`, not `pull_request_target`; no
  `secrets: inherit`). Not established on self-hosted Gitea (RT-E013-06).
- **`persist-credentials: false`:** compliant on every checkout.
- **Template injection:** none found. `github.ref_name` and version outputs reach `run:` only via
  `env:` (`release.yaml:37-40,61-64`; `dev.yaml:38-44`).
- **OIDC / trusted publishing:** not used, a recorded and justified departure (ADR-0035 Alternatives,
  forge neutrality). That raises the stakes of RT-E013-01, because the long-lived tokens are exactly
  what OIDC would have removed.
- **Environment-scoped secrets:** not compliant (RT-E013-01). zizmor `secrets-outside-env`:
  https://docs.zizmor.sh/audits/#secrets-outside-env

## EXECUTIVE SUMMARY

This review covered E013/S01's replacement of the governed CI/CD system: four workflows that run
unchanged on GitHub Actions, Gitea Actions and local `act`, plus pre-commit, zizmor, gitleaks,
Dependabot, CODEOWNERS, the justfile release flow and the wheel-to-image Dockerfile. Overall risk
posture is **HIGH**. The new pipeline is simpler and gets the basics right: SHA-pinned third-party
actions, read-only token permissions, no `pull_request_target`, no template injection, and a
credential-free reusable build. But it puts all of its publication authority in repository-level
secrets and unprotected tags, while its only stated control is review on `main`, which a branch
push or tag push bypasses entirely. The most dangerous finding is **RT-E013-01**. Anyone, or any
agent, with write access can push a throwaway branch whose workflow reads every `PUBLISH_*` token,
before any review. The repository's own CODEOWNERS file notes that the agents reading its vendored
instructions hold write access, so a poisoned instruction file is a complete credential-theft path.
The most important recommendation is to **move the publish jobs into tag- and branch-restricted
environments and protect `v*` tags** (RT-E013-01 and RT-E013-02 together), and then to carry the
build-time wheel hash across jobs, so the provenance check the Dockerfile already performs actually
verifies something (RT-E013-04).
