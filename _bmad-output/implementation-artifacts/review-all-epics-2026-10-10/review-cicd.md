# Whole-solution architecture conformance review — lens 2 of 3: CI/CD architecture vs delivered pipeline

- **Date:** 2026-10-10
- **Mode:** l3io-arch-review Mode B. Standards loaded: standards-core, standards-github-actions, standards-docker, standards-shell.
- **Repository:** HEAD `2139ad8` (local). `origin/main` = `9f9398c`. `6772f07` and `2139ad8` are local only.
- **Authority:** CI/CD spine `architecture-ci-cd-pipeline-2026-10-08/ARCHITECTURE-SPINE.md` (AD-1..AD-18 as amended) + `.memlog.md`. ADRs 0028, 0033 (amended), 0035, 0036, 0037, 0038 and 0039.
- **Gate run:** `just check` at HEAD returned rc 0. All 14 pre-commit hooks passed (poetry-lock, 3 pygrep guards, check-toml, check-yaml, mixed-line-ending, ruff check/format, gitleaks, gitleaks-history, actionlint, zizmor `--persona=auditor`, mypy) and pytest passed 216/216 (local Python 3.11). The working tree was unchanged afterwards apart from the pre-existing untracked `uv.lock`.

## Verdict

**CONDITIONAL PASS: the files conform; the forge and the release path do not yet.**

Each of the four workflows, the justfile, `pyproject.toml`, the Dockerfile build contract, the zizmor/Dependabot/pre-commit configuration and the pins conform to AD-1..AD-18 and the Conventions rows. There is one undocumented ordering drift (AD-2) and three places where the rule's prose claims more than is enforced (AD-5, AD-9, AD-14).

The live evidence holds up for what it claims:
- PR/dev builds on GitHub-hosted runners;
- local `act` (ci, dev, release including the ancestry refusal, dev re-run guard);
- a dev publish to the Gitea index and registry, run from local `act`.

Three areas remain open:
- **Release path.** No forge has run it.
- **Gitea `act_runner`.** No workflow has run on it.
- **Destinations other than Gitea.** None has published.

The GitHub forge state does not match the documented checklist:
- legacy repository-level secrets are still present;
- two Actions settings outside the checklist weaken the approval boundary that ADR-0039 says is closed.

Severity counts: **BLOCKER 0 · MAJOR 5 · MINOR 16**.

Gate: the five MAJORs must be resolved or ADR-justified before E013 closes. MINORs defer to the backlog.

## AD-by-AD conformance

| AD / row | Status | Evidence (file:line) | Notes |
| --- | --- | --- | --- |
| AD-1 four workflows by trigger | CONFORMS | `build.yaml:5-6` (`workflow_call` only); `ci.yaml:5-7`; `dev.yaml:5-7`; `release.yaml:5-7`; `build` caller ids at `ci.yaml:13`, `dev.yaml:22`, `release.yaml:69-71` | No channel/forge branching. |
| AD-2 one credential-free build | CONFORMS with drift | `build.yaml:15-16,27-28` (contents: read); steps `34-132`; outputs `7-13,29-31`; one-wheel/one-sdist check `56-67` | **Drift (F-06):** the spine's order puts docker build and smoke (step 7) before the upload (step 8). The implementation uploads first (`build.yaml:98-106`), with a justified comment, and the walkthrough diagram (`pipeline-walkthrough.md:20-21`) agrees with the code. The spine was not amended. |
| AD-3 one hook list | CONFORMS | `justfile:16-18` = `build.yaml:50-54`; gitleaks dir/history `.pre-commit-config.yaml:80-91`; mypy `^src/` `:114-116`; zizmor `:104-108`; actionlint `:93-96`; full-history checkout `build.yaml:36-37` | Local Python differs from CI (3.11 vs 3.14); documented in `CONTRIBUTING.md:26-29`. |
| AD-4 no custom policy code | CONFORMS | `tests/` holds product tests only; the three pygrep guards (`.pre-commit-config.yaml:32-48`) are standard-tool configuration | — |
| AD-5 action choice and pinning | CONFORMS; prose overclaims | All non-LLL `uses:` are SHA plus `# vX.Y.Z` comment; 13 LLL uses at `@v2/@v3/@v6`; `zizmor.yml:6-11`; `dependabot.yml:4-9` cooldown; auditor persona `.pre-commit-config.yaml:108`; per-line suppression `ci.yaml:14` cites AD-6 | **F-07:** the spine says the major-tag form "is enforced by zizmor", but `ref-pin` accepts `@main` (as `zizmor.yml:3-5` admits). |
| AD-6 same YAML, ref-free, no ACT | CONFORMS | No `ref:`/`repository:` (pygrep `:38-42` passes); no `ACT` (`:44-48`); `runs-on: ubuntu-latest` on every job; `environment:` carve-out `dev.yaml:28,129`, `release.yaml:76,175,334` | GitHub notice: `ubuntu-latest` moves to Ubuntu 26 from 2026-10-19 (re-verify). |
| AD-7 version identity | CONFORMS | `pyproject.toml:3,72-87` (exact config, pattern anchored); one transform `build.yaml:71-96` | Live: `0.2.1.dev13` / `0.2.1-dev.13` (act, Gitea). |
| AD-8 image tags, one writer | CONFORMS; 0.x gap | dev `dev.yaml:234-246`; release `release.yaml:278-291`; `flavor: latest=false` both | **F-11:** a 0.y.z release writes `:0`. Legacy git tags `v0.1` and `v0.2` remain from the old pipeline (F-17). |
| AD-9 credential-gated destinations | CONFORMS; prose overclaims | Job-env flags `dev.yaml:34-37,135-143`, `release.yaml:82-85,181-189,340-342`; single-flag `if:`; token only in the consuming step | **F-08:** "ambient token never used by any step" is literally false (`actions/checkout` defaults `token: github.token`). **F-09:** the Gitea token appears in curl argv. |
| AD-10 one build, fan-out | CONFORMS | `PUBLISH_IMAGE` and blank image names `dev.yaml:140-143`; config guard `:164-182`; per-registry logins `:213-231`; one build-push `:257-276`; test by digest `:279-284` (release mirrors this at `:208-329`) | Proven live for Gitea only. |
| AD-11 package publishing (amended 2026-10-09) | CONFORMS (HEAD) | Gitea files check `dev.yaml:80-115`, `release.yaml:126-161`; `--skip-existing` TestPyPI `dev.yaml:124`, PyPI `release.yaml:170`; twine locked 7.0.0 | Fix `6772f07` is local only. **F-05:** the duplicated script. |
| AD-12 release | CONFORMS (static, act) | validate-tag `release.yaml:22-67`; `build needs validate-tag` `:69-71`; `release needs` both publish jobs `:335`; per-step `PUBLISH_RELEASE` gates `:353-391`; `allow-updates: true` `:391` | No forge has run it (F-03). |
| AD-13 permissions | Files CONFORM; **forge DOES NOT** | Every workflow and job is `contents: read` | **F-01:** repository-level `DOCKERHUB_TOKEN` and `DOCKERHUB_USERNAME` are still set. **F-02:** the repository default workflow permission is `write`. |
| AD-14 concurrency | CONFORMS; comment overclaims | `dev.yaml:13-15`; `release.yaml:13-15` | **F-10:** GitHub keeps one pending run per group and cancels older pending runs. |
| AD-15 dev never publishes a release | CONFORMS | Guards `dev.yaml:40-47,146-153`; `just release` sync check `justfile:79-84` | Live (act): the re-run on the tagged commit refused. |
| AD-16 justfile | CONFORMS | `justfile:5,12-121`; `--detect-event`, `--defaultbranch`, no `--secret` at `:58`; already-released refusal `:97-99` | Minor: the `mktemp -d` directory is never removed (F-22). |
| AD-17 image build contract | CONFORMS | Five build-args in `build.yaml:121-126`, `dev.yaml:271-276`, `release.yaml:316-321`, `justfile:42-46`; hash check `docker/Dockerfile:47-80`; PEP 440 compare `:104-112`; bypass `:41-43`; guard before CA import | — |
| AD-18 private CA | CONFORMS | First credential step `dev.yaml:50-55,156-161`, `release.yaml:96-101,200-205,346-351`; buildx `config:` `dev.yaml:251-254`; `REQUESTS_CA_BUNDLE` on twine steps | Not exercised live: the Gitea server is publicly trusted. |
| Conv: job ids / `name:` | CONFORMS | All jobs `name:` = id; required check `build / build` matches ruleset 24821203 | — |
| Conv: artifact | CONFORMS | `dist`, `path: dist/` everywhere | — |
| Conv: version hand-off | CONFORMS | Only `needs.build.outputs.*` | — |
| Conv: secret naming | CONFORMS in files | All `PUBLISH_*` | Forge still holds non-conforming `DOCKERHUB_*` (F-01). |
| Conv: conditionals | CONFORMS | Only single-flag and the AD-12 validity check | The `Tag is on the default branch` step has no `if:`, as specified. |
| Conv: environments | Files CONFORM; forge partial | Env keys as specified; GitHub has `dev` (branch `main`) and `release` (tag `v*`) | Both environments are empty (expected before go-live). |
| Conv: idempotent re-run | CONFORMS (Gitea dev proven) | AD-11 files check; `allow-updates`; re-point digest | ADR-0036 §5 text is stale (F-12). |
| Stack pins | CONFORM | checkout `3d3c42e`, setup-python `5fda3b9`, upload `330a01c`, download `018cc2c`, login `dbcb813`, qemu `9901266`, buildx `f87e599`, build-push `c3c9e26`; Poetry 2.4.2; pdv 1.10.0; twine 7.0.0; semver 3.1.0; zizmor 1.30.1; gitleaks v8.30.1 | Outside the Stack table: mypy hook v1.14.1 vs dev mypy 2.3.1 (F-16). |
| Retired machinery | REMOVED | No live file references `verify-build`, `publication_contract`, composites, scripts, `act-build.sh`, `scriv`, `tag-floating-version` or bake | Historical docs are labelled as such (`docs/ci/{gitea-certification,ref-free-checkout-walkthrough,codex-assesment}.md`). Forge leftovers remain (F-17). |
| Superseded ADR status | CORRECT | 0006, 0007, 0009, 0011, 0015, 0019, 0020, 0021, 0022, 0029, 0031 and 0032 say "Superseded by ADR-0035". 0008, 0010, 0012 and 0033 carry 2026-10-09 amendment sections. 0004, 0018 and 0028 are Accepted. | `guidelines.md:72` still leans on "ADR-0009's accepted-risk entries" (superseded). |

## Evidence vs claim

| Claim | Evidence | Supports? | Unproven remainder |
| --- | --- | --- | --- |
| PR build runs the gates (`build / build`) | GitHub run 38001947526 (Dependabot PR #17) ran every hook and the tests | Yes for the gates. That run **failed** at build-push with ghcr.io `429 Too Many Requests` pulling the linuxserver base anonymously (F-18). | No green PR run of the current `ci.yaml` on GitHub was examined. |
| dev.yaml on GitHub-hosted runners | Run **38001738260**, `9f9398c`, conclusion success; jobs `build / build`, `publish-package`, `publish-image` succeeded; destinations skipped | Yes (no-op path, artifact v5/v6 on Node 24) | `6772f07` and `2139ad8` are not pushed, so HEAD has not run on any forge. |
| Local act: ci/dev/release, ancestry refusal, AD-15 guard | `notes-E013-S02-001.md` table (act 0.2.89, `9f9398c`) | Yes, with `build` shown executing (ADR-0036 §3) | The local tag `v0.2.1` was never pushed. |
| Gitea index and registry publish, re-run idempotence | Notes runs 1–3 + `pip download` + `dev` index digest `sha256:6e8deee…` | Yes for **dev from local act** with the fix applied | Gitea `act_runner` itself; release-channel Gitea upload; Gitea forge release; protected tag/branch on Gitea. |
| Release path (validate-tag on forge → PyPI → images → forge release) | None | **No** | All of it: GitHub `release` environment tag policy, PyPI `--skip-existing`, GHCR, Docker Hub, `X.Y`/`X`/`latest` (including `:0` for 0.x), changelog builder `from-tag`, `git-action-release` on GitHub and on Gitea. |
| TestPyPI / GHCR / Docker Hub dev publish | None (environments hold no secrets) | No | All three. |
| Forge settings applied per checklist | `gh api` (this review) | **Partially.** Environments `dev` (branch `main`) and `release` (tag `v*`) exist with no secrets. Rulesets `main` (24821203: deletion, non_fast_forward, PR with 1 approval, dismiss_stale, require_last_push_approval, check `build / build`, bypass RepositoryRole 5) and `release-tags` (24821202: creation/update/deletion/non_fast_forward on `refs/tags/v*`) are active. | Checklist step 1 is **not done**: repo secrets `DOCKERHUB_TOKEN` and `DOCKERHUB_USERNAME` are present (F-01). Rulesets were applied after the `9f9398c` merge and run, not before (step 3 before step 4). That did no harm because no secrets existed. Actions settings `default_workflow_permissions: write` and `can_approve_pull_request_reviews: true` are not covered by the checklist (F-02). |
| Private CA path | None (Gitea is publicly trusted) | No | CA import, BuildKit config, `REQUESTS_CA_BUNDLE` and curl trust. |

## Documentation consistency

- **Consistent:**
  - Secret and variable names across the spine AD-9, walkthrough §Where things are published, ADR-0039 Decision 1, `gitea-runners.md` and the environment table.
  - Action pins and versions across the Stack table, `developer.md:73-75` and `dependabot.yml:10-18`.
  - Checklist order: walkthrough `:244-254` = ADR-0039 Decision 2.
  - Re-run semantics: walkthrough `:201-207`, ADR-0038 `:72` and `operational.md:346` all describe the AD-11 Gitea files check.
  - `just` recipes: developer.md = walkthrough = justfile.
- **Inconsistent:**
  - ADR-0036 §5 line 40 still says every upload uses `--skip-existing` (F-12).
  - The ADR-0035 header "Amended by" omits 0038, 0039 and the AD-11 amendment (F-12).
  - The spine and `gitea-runners.md:24` cite E013-S01-004 (blocked) for live certification instead of S02-001 (F-13).
  - The `gitea-runners.md` requirements omit `curl`/`jq`, and its diagram calls the version guard "dev.yaml only" (F-14).
  - `gitea-certification.md` is headed "Historical" but ADR-0038:98 and ADR-0039:145 cite it as the current live-items list (F-15).
  - The `guidelines.md` §10 hook table is stale and overstates coverage (F-04).
  - The spine AD-2 order differs from the code and the walkthrough (F-06).
  - The AD-5 and ADR-0035 Decision 6 "major tags enforced" claim (F-07).
  - The `release.yaml:12` "Releases queue" comment (F-10).

## Findings

| ID | SEVERITY | finding | evidence | remediation |
| --- | --- | --- | --- | --- |
| F-01 | MAJOR | Legacy repository-level secrets remain on GitHub, against AD-13, ADR-0039 Decision 1 and checklist step 1. Any workflow on any same-repo branch (including a PR branch) can read them. The rulesets were also applied after the merge (step 3 after step 4). | `gh api …/actions/secrets` → `DOCKERHUB_TOKEN`, `DOCKERHUB_USERNAME`; notes-E013-S02-001 "Remaining" and "Forge state" | Run `gh secret delete DOCKERHUB_TOKEN` and `gh secret delete DOCKERHUB_USERNAME`, re-run the walkthrough step-1 verification, and paste the output into S02-001 notes. Revoke the Docker Hub token itself. |
| F-02 | MAJOR | GitHub Actions settings undercut the ADR-0039 approval boundary, and the checklist does not cover them. With `can_approve_pull_request_reviews: true` and `default_workflow_permissions: write`, a write collaborator can push a branch workflow (`pull_request`) that approves their own PR with `GITHUB_TOKEN`. That may satisfy `required_approving_review_count: 1`, which contradicts ADR-0039's "Closed: a collaborator … acting alone". Whether a bot approval counts toward the ruleset was not tested live. | `gh api …/actions/permissions/workflow` → `{"default_workflow_permissions":"write","can_approve_pull_request_reviews":true}`; ADR-0039:149-153; walkthrough `:400-403` | Set the default to `read` and disable "Allow GitHub Actions to create and approve pull requests". Add both to the walkthrough checklist, with `gh api …/actions/permissions/workflow` as the verification, and to ADR-0039 Decision 4. |
| F-03 | MAJOR | The release path and most destinations are unproven on any forge. No `v*` tag has run `release.yaml`. Also unexercised: PyPI, TestPyPI, GHCR, Docker Hub, forge release (GitHub and Gitea), floating `X.Y`/`X`/`latest`, the `release` environment tag policy and a Gitea `act_runner`. HEAD (`6772f07` AD-11 fix, `2139ad8`) has not run on any forge. | notes-E013-S02-001 §Remaining; `gh api …/tags` (newest v0.2.0, old pipeline); `gh run list` | Push `main`. Finish S02-001: TestPyPI dev publish, then cut `v0.2.1` with release secrets (or with none, to prove the no-op path plus validate-tag on GitHub), then the same three runs on the Gitea `act_runner`. Keep ADR-0035's status "pending" until then. |
| F-04 | MAJOR | `docs/guidelines.md` §10 hook table is stale and overstates coverage (global rule 3). It lists `end-of-file-fixer`, `trailing-whitespace` and `detect-private-key` as wired, calling `detect-private-key` "a direct backstop", but none runs (`.pre-commit-config.yaml:53-56`, EOF fixer commented out). It omits zizmor, gitleaks-history and the three pygrep guards, and says mypy is "Not yet added" (wired at `:111-117`). AGENTS.md sends readers here before design changes. | `guidelines.md:163-176` vs `.pre-commit-config.yaml` | Rewrite the table from `.pre-commit-config.yaml`, or replace it with a pointer to that file plus `pre-commit run --all-files` output. Either wire `detect-private-key` or drop the claim. |
| F-05 | MAJOR | Duplicated publish logic with no recorded acceptance (core §2, GHA overlay "repeated job logic"). Both workflows carry: the `publish-image` job (~150 lines), the 36-line Gitea upload script, the registry guard, the Locate-wheel step and the twine install. The `6772f07` fix had to land identically twice. | `dev.yaml:80-115` vs `release.yaml:126-161`; `dev.yaml:126-284` vs `release.yaml:172-329` | Either record in ADR-0035 Consequences that AD-1's four-workflow shape accepts this duplication, naming the owner and a diff check (e.g. a pygrep or review rule), or extract local composite actions (`.github/actions/gitea-pypi-upload`, `…/registry-guard`). Local composites resolve on act and Gitea. |
| F-06 | MINOR | Silent drift in AD-2's step order: upload `dist` before the docker build and smoke test. The code comment justifies it, but the spine was not amended. | spine AD-2 items 7-8; `build.yaml:98-106` | Amend AD-2 in place (upload precedes ref-pinned actions) with a memlog line. |
| F-07 | MINOR | AD-5 and ADR-0035 Decision 6 say zizmor enforces LLL at major tags, but `ref-pin` accepts any ref. Prose overstates coverage (global rules 3/4). | spine AD-5; ADR-0035:44; `zizmor.yml:3-5` | Add a pygrep hook failing on `uses:\s*LiquidLogicLabs/[^@\s]+@(?!v\d+\s*(#.*)?$)` over `.github/workflows/`, then correct the prose. |
| F-08 | MINOR | AD-9 says "The ambient token is never used, by any step". `actions/checkout` defaults `token: ${{ github.token }}` (with `persist-credentials: false`), and the artifact actions use the runtime token. | spine AD-9; `build.yaml:34-38` | Reword to "no step is handed the ambient token for publishing; checkout uses it read-only and does not persist it". |
| F-09 | MINOR | The Gitea token is passed in curl argv (shell overlay: no secret in argv). | `dev.yaml:99`, `release.yaml:145` | Pass the header on stdin (`curl -H @- … <<<"Authorization: token $TWINE_PASSWORD"`) or with `--config -`. |
| F-10 | MINOR | `release.yaml:12` says "Releases queue; one is never cancelled mid-flight". GitHub keeps only one pending run per concurrency group and cancels older *pending* runs, so three tags pushed in quick succession would drop the middle release's run. | `release.yaml:12-15`; spine AD-14 | Correct the comment and the walkthrough, and add an operator note: re-run any cancelled release. Optionally include `github.ref` in the group. |
| F-11 | MINOR | 0.x floating major is unrecorded. `type=semver,pattern={{major}}` writes `:0` for every 0.y.z release, which the action's README advises disabling. The current line is 0.2.x, so the next release publishes `:0`. | `release.yaml:290`; LiquidLogicLabs/git-action-docker-metadata README §"Major version zero" | Decide and record (AD-8): either accept `:0` or skip it while major is 0. |
| F-12 | MINOR | ADR cross-references are stale. ADR-0036 §5 still says all uploads use `--skip-existing`. The ADR-0035 "Amended by" line lists only 0036 and 0037. The spine `companions` omit 0037 and 0039. The AD-11 amendment has no ADR (spine and memlog only). | `0036:40`; `0035:17`; spine frontmatter | Add one-line amendment notes to 0035 and 0036 and list 0038/0039 in "Amended by". |
| F-13 | MINOR | Live certification is attributed to E013-S01-004, which is blocked; the work is E013-S02-001. | spine Deferred "Live certification…"; `gitea-runners.md:23-24`; `state/active/epic-013/sprint-01/E013-S01-004.yaml:6` | Re-point to S02-001. |
| F-14 | MINOR | Gitea runner requirements omit `curl` and `jq`, which the Gitea upload step needs. The trust diagram says the version guard is "dev.yaml only", but release has a tag guard. | `gitea-runners.md:17-19,36`; `dev.yaml:99,107`; `release.yaml:88-93` | Add `curl` and `jq` to the requirements and fix the diagram line. |
| F-15 | MINOR | The current pipeline's Gitea live items sit at the bottom of a document headed "Historical — describes the pipeline retired by ADR-0035". ADR-0038 and ADR-0039 cite it as the live list. | `gitea-certification.md:3-7,289-303`; `0038:98`; `0039:145` | Move the current items into `gitea-runners.md` (or a new section of the walkthrough) and re-point both ADRs. |
| F-16 | MINOR | The mypy version is split: hook `mirrors-mypy v1.14.1` vs dev dependency `mypy 2.3.1`. Pre-commit `rev`s (zizmor, gitleaks, actionlint, ruff: Stack-table tools) are not watched by Dependabot. | `.pre-commit-config.yaml:112`; `pyproject.toml:39`; `poetry.lock`; `dependabot.yml` | Align mypy, and add `pre-commit autoupdate` to a documented cadence or a Dependabot `pre-commit` ecosystem entry if available. |
| F-17 | MINOR | Leftover forge state from the retired pipeline: open PR #7 `chore(main): release 0.2.0` (release-please), Dependabot PRs #14/#15/#16 for retired-pipeline actions (login/qemu v3→v4, attest-build-provenance), and floating git tags `v0.1`/`v0.2` (AD-8: none created; harmless, pattern anchored). | `gh pr list`; `gh api …/tags` | Close #7 and #14-16 and delete the release-please branch. Leave or remove the legacy tags (removal needs the ruleset bypass). |
| F-18 | MINOR | The credential-free build pulls the base image anonymously from ghcr.io. The required check `build / build` failed on PR #17 with `429 Too Many Requests`, so it is flaky. | run 38001947526 log (`ghcr.io/v2/linuxserver/baseimage-alpine/blobs/… 429`) | Document a re-run as the response. Consider a buildx registry mirror or retry, which stays credential-free (AD-2). |
| F-19 | MINOR | Docker overlay: no `.dockerignore`. Context `.` sends `.git`, `.venv` and local env files to BuildKit, and the wheel step bind-mounts the whole context. `apk -U upgrade` makes the runtime layer non-reproducible despite the digest-pinned base. | `ls .dockerignore` → absent; `docker/Dockerfile:49,137` | Add a `.dockerignore` that excludes `.git`, `.venv`, `.poetry` and `*.env` but keeps `dist/`, `docker/`, `pyproject.toml` and `poetry.lock`. Record the upgrade trade-off. Image layers are lens 1's scope. |
| F-20 | MINOR | An untracked `uv.lock` sits in the working tree. ADR-0001 makes Poetry the tool, and the file could be committed by accident. | `git status` → `?? uv.lock` | Delete it, or add it to `.gitignore`. |
| F-21 | MINOR | Shell overlay: no ShellCheck hook in AD-3's list. actionlint shellchecks `run:` blocks only when a `shellcheck` binary is present (true on ubuntu-latest, not guaranteed on a Gitea runner image). s6 scripts are not checked; they are clean locally at `-S warning`. | `.pre-commit-config.yaml` (no shellcheck); `docker/root/.../run`, `privilege-decision.sh` | Add the `shellcheck-py` pre-commit hook over `docker/root/**` and the justfile scripts. |
| F-22 | MINOR | `just act` creates `--artifact-server-path "$(mktemp -d)"` and never removes it (shell overlay: mktemp plus trap). | `justfile:58` | Use a shebang recipe with `trap 'rm -rf "$d"' EXIT`. |

## Per-principle walkthrough

| Principle | Result |
| --- | --- |
| Core §1 Separation of concerns | PASS: build is credential-free, publish is flag-gated, each trigger has its own workflow. |
| Core §2 Reuse over copy-paste | F-05 |
| Core §3 Design by contract | PASS: wheel/hash/VERSION contract in the Dockerfile, version guards, registry guard. |
| Core §4 Testability | PASS: `just act` runs the same YAML; no bespoke harness (AD-4). |
| Core §5 Brevity | PASS; F-05 is the main bulk. |
| Core §6 Comments state current intent | F-10 (overclaiming comment). Other comments are current. |
| Core §7 Dependency selection | PASS; F-16 (version split). |
| Core §8 GA only | PASS: all pins are GA releases. |
| Core §9 Logging / correlation | PASS for the pipeline's scope: run-scoped logs, and validate-tag logs tag/commit/branch. |
| Core §10 Documentation | F-04, F-12, F-13, F-14, F-15 |
| GHA: marketplace over shell | PASS. The Gitea files-check `run:` is justified (no action exists; twine refuses the flag), but see F-05. |
| GHA: pinning / latest major | PASS (SHA plus comment; LLL major); F-07. Artifact actions are deliberately held below the latest major, recorded in the spine Deferred section. |
| GHA: Dependabot | PASS (actions, pip, docker, cooldown); F-16 for pre-commit. |
| GHA: least privilege / secrets | Files PASS; forge F-01, F-02; F-09 |
| GHA: concurrency | PASS; F-10 |
| GHA: composite/reusable for repeats | F-05 |
| Docker: digest-pinned GA base | PASS (`Dockerfile:6`) |
| Docker: multi-stage, no toolchain in final | PASS (`Dockerfile:150-152`) |
| Docker: SBOM/provenance, scan | Deferred and recorded in the spine (no finding) |
| Docker: non-root, `.dockerignore`, exec-form, HEALTHCHECK | `.dockerignore` F-19. Privilege model is ADR-0030 (lens 1). No HEALTHCHECK (lens 1). |
| Shell: strict mode | PASS for workflows (`defaults.run.shell: bash` gives `-e -o pipefail`) and the justfile (`set shell` with `-euo pipefail`, shebang recipes `set -euo pipefail`). s6 scripts are lens 1. |
| Shell: quoting / argv secrets | F-09 |
| Shell: mktemp plus trap | F-22 |
| Shell: ShellCheck in CI | F-21 |

## Recommended ADRs

- An amendment to ADR-0035 Consequences, or a new ADR, that accepts or removes the dev/release publish duplication (F-05).
- An AD-8 decision on the 0.x floating major tag (F-11).
- An ADR-0039 amendment adding the GitHub Actions workflow-permission and PR-approval settings to the required forge settings (F-02).

Sections read: SKILL.md (Mode B, Output) and references/review-report.md, standards-core.md (headings and rules), standards-github-actions.md, standards-docker.md, standards-shell.md (headings and checklist). Spine ARCHITECTURE-SPINE.md (all) and .memlog.md (all). ADR-0035 and ADR-0036 (all); ADR-0039 (Decision through Revisit); ADR-0038 (header, :72, :90-100). Header and amendment status lines of ADRs 0004-0033 as listed. docs/ci/pipeline-walkthrough.md (all); docs/ci/gitea-runners.md (:13-60, headings); docs/ci/gitea-certification.md (header, headings, :268-303); docs/ci/ref-free-checkout-walkthrough.md and codex-assesment.md (headers); docs/developer.md, docs/guidelines.md and CONTRIBUTING.md (CI-relevant lines; guidelines §6, §7, §10); AGENTS.md. .github/workflows/{build,ci,dev,release}.yaml (all); .github/{zizmor.yml,dependabot.yml,CODEOWNERS} (all); .pre-commit-config.yaml, .gitleaks.toml, justfile and docker/Dockerfile (all); pyproject.toml (version, dev group, pdv, build-system); poetry.lock (tool versions). notes-E013-S02-001.md (all); E013-S01-004 state. Git: `git show --stat 6772f07 2139ad8`, tags. Forge (read-only `gh api` / `gh run` / `gh pr`): repo secrets/variables, environments plus policies/secrets/variables, rulesets 24821202/24821203, branch protection, Actions permissions, tags, releases, runs 38001738260 and 38001947526, open PRs. LiquidLogicLabs/git-action-docker-metadata README (major-zero section). `just check` run once (rc 0).
