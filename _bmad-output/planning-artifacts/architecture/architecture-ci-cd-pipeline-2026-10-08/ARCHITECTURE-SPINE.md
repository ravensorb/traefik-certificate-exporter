---
name: 'traefik-certificate-exporter CI/CD pipeline'
type: architecture-spine
purpose: build-substrate
altitude: initiative
paradigm: 'pipes-and-filters: one credential-free build stage feeding flag-gated publish stages, selected by trigger'
scope: 'Every GitHub Actions / Gitea Actions workflow and justfile recipe that tests, builds, versions, publishes, or releases the Python package and the Docker image'
target: '0.3.1'
status: final
created: '2026-10-08'
updated: '2026-10-12'
binds: [all]
sources:
  - .memlog.md
  - reviews/review-rubric-walker.md
  - reviews/review-web-verification.md
  - reviews/review-adversarial.md
  - ../architecture-ci-cd-pipeline-2026-08-31/ARCHITECTURE-SPINE.md (superseded)
  - _bmad-output/implementation-artifacts/review-all-epics-2026-10-10/review-cicd.md
  - _bmad-output/planning-artifacts/research/research-2026-10-10-release-0.3.0.md
  - _bmad-output/implementation-artifacts/epic-014/sprint-01/stories/E014-S01-005.md
  - _bmad-output/implementation-artifacts/epic-014/sprint-01/stories/E014-S01-007.md
  - _bmad-output/implementation-artifacts/epic-014/sprint-02/stories/E014-S02-001.md
  - _bmad-output/implementation-artifacts/epic-014/sprint-02/stories/E014-S02-002.md
  - _bmad-output/implementation-artifacts/epic-014/sprint-02/stories/E014-S02-005.md
  - _bmad-output/implementation-artifacts/epic-014/sprint-02/closure/notes-E014-S02-001.md, notes-E014-S02-002.md, notes-E014-S02-006.md (S02-003 routing)
  - _bmad-output/implementation-artifacts/epic-014/epic-closure/closure-report.md, spec-proposals/AD-1.md, spec-proposals/AD-2.md, redteam-report.md (RT-2)
  - _bmad-output/planning-artifacts/research/research-2026-10-12-release-0.3.1.md (§5-§8)
  - _bmad-output/implementation-artifacts/epic-015/maintainer-decisions.md (MD-10..MD-18 accepted 2026-10-12)
  - _bmad-output/implementation-artifacts/epic-015/sprint-02/stories/E015-S02-001..004.md
companions:
  - docs/adr/0042-dependency-audit-scope-is-the-whole-lock.md
  - docs/adr/0046-e014-pipeline-amendments.md
  - docs/adr/0047-dev-release-publish-duplication.md
  - docs/adr/0028-ref-free-checkout-across-ci-cd.md
  - docs/adr/0033-secret-scanning-exempts-no-path.md
  - docs/adr/0035-standard-ci-cd-pipeline.md
  - docs/adr/0036-ci-cd-pipeline-arch-gate-amendments.md
  - docs/adr/0037-gitleaks-default-allowlist-is-inherited.md
  - docs/adr/0038-release-only-from-protected-tags-on-main.md
  - docs/adr/0039-publish-credentials-in-forge-environments.md
  - docs/ci/pipeline-walkthrough.md
supersedes: 'architecture-ci-cd-pipeline-2026-08-31 (CI-AR1..CI-AR50)'
---

# Architecture Spine — traefik-certificate-exporter CI/CD pipeline

**Target: 0.3.1 — describes the pipeline after epic E015; parts are ahead of the code until E015 lands.** Where a rule needs an ADR that does not exist yet, the AD names the E015 story that writes it.

This spine replaces the 2026-08-31 CI/CD spine in full. None of CI-AR1..CI-AR50 binds any
more; where a rule survives, it is restated below under an `AD` id. Each Rule states the
current decision; the history of how it got there is in `.memlog.md` and the ADRs.

## Design Paradigm

**Pipes and filters, selected by trigger.** One reusable, credential-free **build** filter
verifies, versions, hashes and packages the source. Each trigger has its own thin workflow
that pipes the build's artifact and outputs into **publish** filters. A publish filter writes
to a destination only when that destination is fully configured on the forge running it.

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
                        publish jobs --needs--> build
                          artifact `dist`
                          outputs version, image-version, wheel-sha256, sdist-sha256
                        build.yaml holds no credential and calls nothing that does

 publish-job step order (every publish job, AD-18):
   Destination configuration -> version guard (dev only, AD-15) -> hash verify (AD-17)
   -> CA import (AD-18) -> login / publish
```

## Invariants & Rules

### AD-1 — Four workflows, chosen by trigger [ADOPTED]

- **Binds:** `.github/workflows/`
- **Prevents:** channel or forge branching inside steps; a fifth entry point duplicating build logic; a fix landing in one publish workflow and not the other.
- **Rule:**
  - The pipeline is exactly `build.yaml` (`workflow_call` only), `ci.yaml` (`pull_request`), `dev.yaml` (`push` to the default branch) and `release.yaml` (`push` of tags `v*`). Trigger selects behaviour; nothing branches on channel, forge, or host.
  - `ci.yaml` and `dev.yaml` call `build.yaml` as their first job, with job id `build`; `release.yaml` calls it after `validate-tag` (AD-12).
  - The publish logic duplicated between `dev.yaml` and `release.yaml` (`publish-package`, `publish-image`, including each copy of the Destination configuration step) is accepted. A change to a shared publish step lands in both files in the same commit and the pull request says so; this is held by CODEOWNERS review of `.github/workflows/`, not by a check (ADR-0047). Local composite actions are deferred.

### AD-2 — One build, no credentials [ADOPTED]

- **Binds:** `build.yaml`
- **Prevents:** fork pull requests reaching a credential; a publish job shipping bytes the build did not test; a moved action tag altering `dist` after it was built; a transient base-image 429 failing the required check.
- **Rule:** `build.yaml` runs, in order:
  1. checkout (AD-6);
  2. Python, then Poetry from the hash-locked bootstrap file (AD-11), then `poetry sync --all-groups` (ADR-0042);
  3. `pre-commit run --all-files` (AD-3);
  4. `pytest`;
  5. `poetry build`;
  6. version and hash outputs (AD-7): `version`, `image-version`, `wheel-sha256`, `sdist-sha256`;
  7. upload of `dist/`, before any ref-pinned (`LiquidLogicLabs/*`) action runs in the job;
  8. a `Resolve base image` step that reads `docker/Dockerfile`'s digest-pinned `ARG BASE_IMAGE` default at run time (never repeated in the YAML) and fails, naming the file and the `^ARG BASE_IMAGE=<image>@sha256:<64 hex>$` pattern, unless there is exactly one pinned default; then a `Pre-pull base image` step that pulls it anonymously with `nick-fields/retry` (4 attempts, a fixed 30 s wait; the last `docker pull` error fails the job);
  9. `docker/setup-buildx-action` with `driver: docker`, so the build reads that local copy rather than fetching the base from ghcr.io, then a single-arch, non-pushed `docker/build-push-action` build per AD-17, tested with `git-action-docker-test@v2`.

  It uploads `dist/` (exactly one `.whl` and one `.tar.gz`) as artifact `dist`, and exposes the four outputs above as `workflow_call` outputs; the two hashes are 64-hex lower case. Its jobs declare `permissions: contents: read` and receive no secrets. Publish jobs download `dist` with `path: dist/` and never run `poetry build`. The retry is the maintained action `nick-fields/retry`, SHA-pinned (AD-5); its wait is constant, accepted over a hand-written backoff loop (ADR-0046 item 12). `publish-image` has no pre-pull: its multi-arch build runs on a `docker-container` BuildKit, which does not read the local store; a 429 there, or four in `build`, is answered by re-running the failed jobs.

### AD-3 — Local and CI gates are one hook list [ADOPTED]

- **Binds:** `.pre-commit-config.yaml`, `justfile`, `build.yaml`
- **Prevents:** a check that runs only in CI, or only locally; a hook that silently examines nothing; a moved hook tag changing code that runs in the job producing `dist`; unpinned, unaudited packages installed for a hook in the job producing `dist`.
- **Rule:** Every lint, type, secret, workflow, dependency and hygiene check is a pre-commit hook, and `.pre-commit-config.yaml` is the one list of what runs. `just check` and `build.yaml` both run `pre-commit run --all-files` followed by `pytest`; neither adds a check the other lacks.
  - Required hooks: ruff, mypy (`repo: local`, `language: system`, `poetry run mypy --config-file=pyproject.toml`, scoped to `^src/`, `require_serial: true`; mypy and the type stubs from `poetry.lock`), gitleaks (tree and history), actionlint, zizmor (its official hook, AD-5), `poetry check --lock`, `pip-audit`, `pip-audit-bootstrap`, `deptry`, `import-linter` (`repo: local`, `language: system`, `env PYTHONPATH=src poetry run lint-imports --no-cache`, from `poetry.lock`; product spine AD-13), `shellcheck` (`shellcheck-py`, SHA-frozen, `files: ^docker/root/`, `types_or: [shell, executable]` and `types: [file]`, because upstream's `types: [shell]` would otherwise exclude the `with-contenv` executables; product spine AD-12), and the `repo: local` pygrep guards: `precommit-revs-frozen`, `precommit-hook-deps-locked` and `workflows-pip-install-from-requirements` (this AD, [ADR-0042](../../../../docs/adr/0042-dependency-audit-scope-is-the-whole-lock.md)), `workflows-lll-major-tag` (AD-5), `workflows-ref-free-checkout` and `workflows-no-act-env` (AD-6), `workflows-major-tag-gated`, `workflows-version-label-priority` and `workflows-latest-tag-gated` (AD-8), `workflows-if-no-secrets-vars` (AD-9), `workflows-no-auth-header-argv` (AD-11), `workflows-no-removed-buildx-inputs` (AD-18), `gitleaks-no-paths-allowlist`, and product AD-12's `s6-no-raw-settings-env` (`files: ^docker/root/`). Each pygrep guard's coverage limit is stated in its comment in `.pre-commit-config.yaml` and in the AD it enforces.
  - Secret scanning covers the tree and the history. The gitleaks repo carries two hooks: `gitleaks` (`gitleaks dir --redact --no-banner --config .gitleaks.toml .`) and one with `alias: gitleaks-history` (`gitleaks git --redact --no-banner --config .gitleaks.toml`), both `always_run: true`, `pass_filenames: false`. `build.yaml` checks out full history (AD-6), so CI scans it. The repository adds no path exemption; gitleaks' default global allowlist is inherited and its exempt set is recorded with the producing versions in the `.gitleaks.toml` header and `docs/developer.md`, re-diffed in the same change as any gitleaks, plugin-lock or interpreter change (ADR-0037). The `gitleaks-no-paths-allowlist` pygrep hook refuses a `paths` key.
  - `pip-audit` audits the venv that `poetry sync --all-groups` produces (`just install`, `build.yaml`), so its scope is every lock group; `pip-audit-bootstrap` audits every `.github/requirements/*.txt` with `--require-hashes --disable-pip`; the `workflows-pip-install-from-requirements` guard keeps every workflow `pip install` inside that directory (ADR-0042). Both hooks are `repo: local`, `language: system` (`poetry run pip-audit --skip-editable --progress-spinner off --aliases on`; `--aliases on` prints GHSA/CVE IDs beside the PYSEC ID). Not covered: lock entries whose environment marker excludes the interpreter and platform the hook runs on (other OSes, other Python minors) are not installed and so not audited (BL-E014-023). Both need network and fail offline rather than skipping; within PyPI's 15-minute cache lifetime of an online run pip's HTTP cache answers instead, and CI starts cold. An advisory is ignored only by `--ignore-vuln <ID>` in the hook entry with a comment giving the reason and a `BL-` key; no tool polices that comment, review does.
  - `deptry` (`repo: local`, `language: system`, `poetry run deptry src`) checks declared versus imported dependencies over `src/` only, with `[tool.deptry]` in `pyproject.toml`; no rule is ignored globally, and an exception is a `per_rule_ignores` entry naming one package with a reason and a `BL-` key.
  - Every non-`local` repo is pinned `rev: <40-hex SHA>  # frozen: vX.Y.Z` by `pre-commit autoupdate --freeze`; the `precommit-revs-frozen` pygrep hook refuses a `rev` that is not a 40-hex SHA; the `# frozen:` comment itself is not checked (coverage: block-style `rev:` lines in `.pre-commit-config.yaml`; a flow-style mapping is not matched). `repo: local` hooks have no `rev`; their tool versions come only from `poetry.lock`.
  - **Hook dependencies are locked.** Every Python package a `repo: local` hook needs is a Poetry dev-group package, hash-locked by `poetry.lock` and audited by `pip-audit`; no hook declares `additional_dependencies`, and every `repo: local` hook is `language: system` (or `unsupported`, pre-commit ≥ 4.4's alias for it) or `pygrep`. The `precommit-hook-deps-locked` pygrep hook over `^\.pre-commit-config\.yaml$` refuses an `additional_dependencies:` key and any other `language:`; coverage limit: block-style keys only (a flow-style hook mapping is not matched), and a remote repo's own manifest language is not visible. Not covered, stated in ADR-0042 (amended by E015-S02-003, maintainer decision MD-17): the remote Python hook repos still install from a package index inside the `build` job — `pre-commit-hooks` (range-resolved `ruamel.yaml>=0.15`; a Low backlog item), `ruff-pre-commit` and `zizmor-pre-commit` (exact versions, fetched unhashed), `shellcheck-py` (binary sha256-pinned, build tooling unpinned); `gitleaks` and `actionlint` are golang hooks checked by `go.sum` and not audited by pip-audit. Revisit when pre-commit ships hash-locked installs, a hook bump adds dependencies, or every hook moves into the lock.

### AD-4 — No custom policy code [ADOPTED]

- **Binds:** all gates, `tests/`
- **Prevents:** bespoke harnesses that must themselves be tested (global rule 1).
- **Rule:** Workflow, dependency and supply-chain policy is enforced only by standard tools' configuration (actionlint, zizmor, gitleaks, ruff, mypy, pip-audit, deptry, pre-commit-hooks, pre-commit `pygrep`). No repository code parses workflows, validates publication contracts, or maintains integrity registries. `tests/` holds product tests only. A test that checks the product's own surface (settings keys, environment names, CLI flags, operator docs such as `docs/upgrading.md`) against the product source is a product test; a test that polices workflows, pins or the supply chain is not.

### AD-5 — Action choice and pinning [ADOPTED]

- **Binds:** every `uses:`, every pre-commit `rev:`
- **Prevents:** custom scripts where an action exists; third-party code moving under a credentialed job; a documented pin rule no check enforces.
- **Rule:** Prefer a `LiquidLogicLabs/git-action-*` action, then a widely used documented action, then a `run:` step only when neither works on all three runners (AD-6).
  - `LiquidLogicLabs/*` is referenced at its bare major tag (`@vN`). The `workflows-lll-major-tag` pygrep hook enforces this over every YAML file under `.github/` (owner case-insensitive; the ref must be exactly `v<digits>`, optionally quoted and followed by a comment). zizmor's `ref-pin` accepts any ref, `@main` included, and is not the enforcement. Coverage limit: block-style `uses:` lines with the value on the same line; a flow-style mapping, a quoted `"uses":` key, a folded or next-line value, or a reference built by a called script is not matched. The `workflows-no-auth-header-argv` hook's limit is stated in AD-11.
  - Every other action is referenced by full commit SHA with a trailing `# vX.Y.Z` comment, enforced by zizmor `rules.unpinned-uses.config.policies` in `.github/zizmor.yml` (`LiquidLogicLabs/*: ref-pin`, `*: hash-pin`). Pre-commit hook repos follow the same SHA rule (AD-3).
  - Updates: Dependabot `github-actions` (`/`), `pip` (`/` and `/.github/requirements`), `docker` (`/docker`) and `pre-commit` (`/`) ecosystems, each weekly with `cooldown.default-days: 7`. Gitea has no Dependabot; there `pre-commit autoupdate --freeze` is run by hand, monthly and before each release (`docs/developer.md`). A hook repo whose newest tag would turn `just check` red, or would downgrade, is held at its current tag's commit with the reason in a comment beside the rev.
  - zizmor runs from its pre-commit hook with `args: [--persona=auditor]` and no severity floor, so `secrets-outside-env` and `anonymous-definition` gate `just check`. `.github/zizmor.yml` disables no audit and configures only `unpinned-uses`. A finding the design accepts is suppressed only per line with `# zizmor: ignore[<audit>]` citing the AD/ADR (example: `use-trusted-publishing` on each `twine upload` step, citing AD-11); every other finding is fixed.

### AD-6 — Same YAML on GitHub, Gitea and act; ref-free checkout; no `env.ACT` [ADOPTED]

- **Binds:** every workflow, every `actions/checkout` step, every `if:`
- **Prevents:** behaviour that differs by runner; checkout replacing a local `act` workspace.
- **Rule:**
  - Supported runners: GitHub-hosted, Gitea **1.27+** with `act_runner` (image providing `curl` ≥ 7.55 and `jq`), and `nektos/act`.
  - No checkout supplies `ref:` or `repository:`, and no later step re-pins identity by another route (ADR-0028); the `workflows-ref-free-checkout` pygrep hook enforces the key.
  - Nothing references `env.ACT` or `ACT`; the `workflows-no-act-env` pygrep hook enforces it.
  - `build.yaml` checks out with `fetch-depth: 0`, `fetch-tags: true`, `persist-credentials: false`.
  - Every job uses `runs-on: ubuntu-latest`.
  - Forge-enforced keys that another runner ignores (`environment:`) are allowed. They add protection on the forge that honours them and change nothing elsewhere; they are not behaviour branching.

### AD-7 — Version identity, owned by the build [ADOPTED]

- **Binds:** `pyproject.toml`, `build.yaml`, every published package and image
- **Prevents:** the package and image describing different versions; unsortable or rejected dev versions; a second place computing the version.
- **Rule:**
  - Git tags `vX.Y.Z` are the only version source. `pyproject.toml` carries `version = "0.0.0"`, `[tool.poetry.requires-plugins]` `poetry-dynamic-versioning[plugin]`, the plugin's build backend, and exactly this configuration: `enable = true`, `vcs = "git"`, `style = "pep440"`, `bump = true`, `metadata = false`, `strict = true`, `pattern = "^v(?P<base>\d+\.\d+\.\d+)$"`. No workflow or recipe passes version options on a command line.
  - On a tag, the package version is `X.Y.Z`. Elsewhere it is `X.Y.(Z+1).devN`, where N is the commit distance from the last `vX.Y.Z` tag. Floating tags such as `v0` never match.
  - `build.yaml` reads the built wheel's `Version` and emits `version` (PEP 440) and `image-version`, the same version in SemVer spelling (`.devN` becomes `-dev.N`; a release is unchanged). This one `run:` step is the only place the version is transformed; it also emits `wheel-sha256` and `sdist-sha256`.
  - Every other job reads these outputs and never recomputes them. No commit hash appears in a package version.
  - The project stays on `0.x` until the maintainer declares it stable, then releases `v1.0.0`.

### AD-8 — Image tags, one writer per tag [ADOPTED]

- **Binds:** `git-action-docker-metadata@v6` configuration in `dev.yaml` and `release.yaml`
- **Prevents:** two workflows writing the same tag with different digests; tag sets drifting between registries; every 0.y.z release moving a bare `:0`.
- **Rule:** Every tag value comes from `needs.build.outputs.image-version` or an explicit `type=raw`/`type=sha`; no tag is derived from `github.ref`. Both workflows set `flavor: latest=false`. Each tag has exactly one writing workflow:

  | Tags | Written only by |
  | --- | --- |
  | `X.Y.(Z+1)-dev.N`, `sha-<7 char>`, `dev` | `dev.yaml` |
  | `X.Y.Z`, `X.Y`, `X` (only when X ≥ 1), `latest` | `release.yaml` |

  The release `tags:` input is exactly:

  ```text
  type=raw,value=${{ needs.build.outputs.image-version }},priority=1000
  type=semver,pattern={{major}}.{{minor}},value=${{ needs.build.outputs.image-version }}
  type=semver,pattern={{major}},value=${{ needs.build.outputs.image-version }},enable=${{ !startsWith(needs.build.outputs.image-version, '0.') }}
  type=raw,value=latest,enable=${{ needs.validate-tag.outputs.is-latest == 'true' }}
  ```

  So `v0.3.0` writes `0.3.0`, `0.3`, `latest`, and `v1.2.3` writes `1.2.3`, `1.2`, `1`, `latest` with no workflow change. The `workflows-major-tag-gated` pygrep hook refuses a major-only pattern line without `enable=` (it checks presence, not the expression). The action labels the image (`org.opencontainers.image.version`) from its highest-priority tag and `type=semver` (900) outranks `type=raw` (200), so the `image-version` raw line in both workflows carries `priority=1000` (BL-E014-075, [ADR-0046](../../../../docs/adr/0046-e014-pipeline-amendments.md) item 14); without it 0.3.0 is labelled `0.3`. The `workflows-version-label-priority` pygrep hook refuses that line without `,priority=1000`; coverage limit: it does not check that no other tag ties or outranks it (held by review and the release dry run's label check). `latest` moves only when the tag is the highest plain `vX.Y.Z` tag: `validate-tag` compares the tag with `git tag -l 'v*' --sort=-v:refname` and outputs `is-latest`, so a re-run of an older release or a patch on an older line never points `latest` backwards (AR-3). The `workflows-latest-tag-gated` pygrep hook refuses a `latest` line without that gate; coverage limit: it checks the gate's presence, not how `is-latest` is computed. Existing `:0` tags from the retired pipeline stay frozen and are not deleted. No floating git tags (`v1`, `v1.4`) are created.

### AD-9 — Configuration-gated destinations, one forge per release [ADOPTED]

- **Binds:** every publish job, every forge's secret store
- **Prevents:** forge detection logic; credentials required everywhere; a half-configured destination failing or half-publishing a run; noisy warnings for destinations nobody configured; a mirrored tag publishing twice from two forges.
- **Rule:**
  - A destination is **enabled** exactly when its token secret **and** every variable it requires are set and non-empty (`!= ''`; unset counts as empty; whitespace is not trimmed). Any combination may publish in one run.
  - Each publish job computes, in its job-level `env`, one `PUBLISH_<DEST>` flag per destination (the full conjunction) and, for multi-input destinations, one `ANY_<DEST>` intent flag (the disjunction of its intent inputs), for example `PUBLISH_GHCR: ${{ secrets.PUBLISH_GHCR_TOKEN != '' && vars.PUBLISH_GHCR_USERNAME != '' && vars.PUBLISH_GHCR_IMAGE != '' }}`. The rule exists only there. Each publishing step tests exactly one flag: `if: env.PUBLISH_X == 'true'`. The token itself is passed only to the step that uses it. No `if:` contains `secrets.` or `vars.`.
  - Each publish job's first step, **Destination configuration**, has no `if:`, always exits 0, writes no `$GITHUB_OUTPUT`/`$GITHUB_ENV`, and only reads the flags plus per-input presence booleans (`HAS_<NAME>`); it holds no conjunction of its own. Per destination it owns: **enabled** (`PUBLISH_<DEST>` true) prints one plain `<Destination> enabled` line; **partial** (`ANY_<DEST>` true, `PUBLISH_<DEST>` false) prints exactly one `::warning title=<job>::` naming every missing `secrets.NAME` / `vars.NAME` and where to set it (GitHub: the job's environment; Gitea: repository Actions secrets/variables) or how to disable it; **unconfigured** prints nothing. It never prints a secret's value or length. Single-input destinations are never partial.
  - The two Gitea destinations are independent: each is judged by its own variables. `PUBLISH_GITEA_TOKEN` or `PUBLISH_GITEA_USERNAME` set with none of `PYPI_URL`, `REGISTRY`, `IMAGE` set is one "Gitea shared inputs" warning, reported by `publish-package` only (`ANY_GITEA_SHARED`).
  - No secret or variable name starts with `GITEA_` or `GITHUB_`. No step is handed the ambient token for publishing; checkout uses it read-only without persisting it, and the artifact actions use the runner's own token.
  - **One release run per tag, from a forge only.** All destinations of a release publish from one forge's run, all-GitHub or all-Gitea. Every `PUBLISH_*` secret and variable lives in that forge's secret store only; the other forge holds none, so a mirrored run there is silent and publishes nothing (a `PUBLISH_*` variable left there alone sets an `ANY_*` intent flag and warns on every run). The forge release is created on the publishing forge.
  - **No workstation publishing of release versions** (maintainer decision MD-14). Release versions are published only by the publishing forge's run. No publish token is held on a workstation, in a password-manager export or in a local `act` run, and no workstation run publishes a release version; `just act` neutralises act's ambient secret sources (AD-16). Not mechanically preventable, stated: a raw `act -s <token>` run outside the recipe. A forge-tag check in `validate-tag` was rejected: the Gitea repository is not anonymously readable, so the check would need the ambient token.
  - **From 0.3.1 the publishing forge is GitHub.** Its `release` environment holds every release destination (PyPI, Gitea package index, GHCR, Gitea container registry, Docker Hub, forge release) and Gitea holds no `PUBLISH_*` secret or variable (maintainer decisions MD-10 to MD-12). An all-Gitea release remains allowed and can publish to every destination: when Gitea is the publishing forge it holds the PyPI, TestPyPI, GHCR and Docker Hub tokens as well as its own (maintainer decision 2026-10-11); it is unproven (BL-E013-044). Not mechanically enforced: the per-release checklist compares secret names on both forges (AD-12). — ADR-0039 (amended by the ADR to be written by E015-S02-002), E015-S02-002.
  - On GitHub, secrets live in the job's environment (AD-13); variables stay at repository level or in the environment. Gitea and act ignore `environment:` and read repository/organisation secrets and variables under the same names.

  | Destination | dev | release | Flag (job) | Required to enable | Intent inputs (`ANY_*`) |
  | --- | --- | --- | --- | --- | --- |
  | Gitea package index | yes | yes | `PUBLISH_GITEA_PYPI` (`publish-package`) | `PUBLISH_GITEA_TOKEN`, `PUBLISH_GITEA_USERNAME`, `PUBLISH_GITEA_PYPI_URL` | `PUBLISH_GITEA_PYPI_URL` |
  | TestPyPI | yes | no | `PUBLISH_TESTPYPI` (`publish-package`) | `PUBLISH_TESTPYPI_TOKEN` | none |
  | PyPI | no | yes | `PUBLISH_PYPI` (`publish-package`) | `PUBLISH_PYPI_TOKEN` | none |
  | GHCR | yes | yes | `PUBLISH_GHCR` (`publish-image`) | `PUBLISH_GHCR_TOKEN`, `PUBLISH_GHCR_USERNAME`, `PUBLISH_GHCR_IMAGE` | all three |
  | Gitea container registry | yes | yes | `PUBLISH_GITEA` (`publish-image`) | `PUBLISH_GITEA_TOKEN`, `PUBLISH_GITEA_USERNAME`, `PUBLISH_GITEA_REGISTRY`, `PUBLISH_GITEA_IMAGE` | `PUBLISH_GITEA_REGISTRY`, `PUBLISH_GITEA_IMAGE` |
  | Gitea shared inputs | yes | yes | report only (`publish-package`) | n/a | token or username set, no Gitea destination variable set |
  | Docker Hub | yes | yes | `PUBLISH_DOCKERHUB` (`publish-image`) | `PUBLISH_DOCKERHUB_TOKEN`, `PUBLISH_DOCKERHUB_USERNAME`, `PUBLISH_DOCKERHUB_IMAGE` | all three |
  | Forge release (publishing forge) | no | yes | `PUBLISH_RELEASE` (`release`) | `PUBLISH_RELEASE_TOKEN` | none |
  | Private CA (AD-18, not a destination; never warns) | yes | yes | `PUBLISH_CA` (all publish jobs) | `PUBLISH_CA_CERTIFICATE` | none |

  `*_TOKEN` and `PUBLISH_CA_CERTIFICATE` are secrets; the rest are variables. `PUBLISH_RELEASE_TOKEN` is a token for the publishing forge with permission to create releases. Values have a fixed shape: `*_IMAGE` is a full lower-case reference without a tag (for example `ghcr.io/ravensorb/traefik-certificate-exporter`); `PUBLISH_GITEA_REGISTRY` is a host with no scheme; `PUBLISH_GITEA_PYPI_URL` is the full upload URL. No value is derived from forge contexts.

### AD-10 — One image build per run, fanned out to every enabled registry [ADOPTED]

- **Binds:** `publish-image` in `dev.yaml` and `release.yaml`
- **Prevents:** per-registry rebuilds producing different digests; one release version carrying two digests across registries; a failed push when no registry is enabled; a half-configured registry failing the run; moving tags before the image is tested.
- **Rule:**
  - The job's `env` holds the three registry flags and their `ANY_*` flags (AD-9) and `PUBLISH_IMAGE`, true when any registry conjunction is true. `PUBLISH_IMAGE` is the only flag combining destinations; it repeats the three conjunctions because job `env` entries cannot reference each other.
  - It also holds one image name per registry, non-empty only when that registry's full conjunction is true: `${{ <that registry's conjunction> && vars.PUBLISH_GHCR_IMAGE || '' }}`, and the same form for the others. A half-configured registry is skipped, never failed; there is no fail-fast registry guard.
  - Each registry's `docker/login-action` step tests its own flag. Every other image step tests `PUBLISH_IMAGE`, so with no registry enabled the job succeeds having pushed nothing.
  - `git-action-docker-metadata@v6` receives the three names in `images:` and drops blank lines.
  - One `docker/build-push-action` step builds `linux/amd64,linux/arm64` per AD-17 and pushes all tags to every enabled registry, so every registry and tag of a run carries one digest.
  - `git-action-docker-test@v2` then tests the pushed image by its digest.
  - **One build per release.** A release version reaches every configured registry only through this one build of its release run; no registry receives a release tag from another build (a workstation run, the other forge, a later rebuild). Equality across registries is a per-release checklist command (AD-12, maintainer decision MD-15), not CI-gating.
  - Exception on record: 0.3.0, whose Gitea image came from a workstation `act` run and carries a second digest. Its Gitea `0.3.0`, `0.3` and `latest` are re-pointed to the Docker Hub digest with `docker buildx imagetools create` (a copy of the existing index, no rebuild); GHCR receives no `0.3.0` (it goes from 0.2.0 to 0.3.1). The exception is recorded by the ADR to be written by E015-S02-002 (maintainer decision MD-13).

### AD-11 — Python package publishing [ADOPTED]

- **Binds:** `publish-package` in `dev.yaml` and `release.yaml`, `pyproject.toml` groups, `.github/requirements/`
- **Prevents:** an upload path that works on only one runner; uploading anything other than the build artifact; a re-run failing on files already published; a token on a process command line; an unhashed or oversized install beside a live token.
- **Rule:**
  - Each enabled index gets one step, gated on its own flag (AD-9). The step runs `twine upload --non-interactive --repository-url <index>` with `TWINE_USERNAME`/`TWINE_PASSWORD` from that index's credentials (`__token__` for TestPyPI and PyPI). `pypa/gh-action-pypi-publish` is not used: it requires `GITHUB_WORKFLOW_REF`, which Gitea and act do not set, and upstream declined the fix.
  - TestPyPI and PyPI steps pass `--skip-existing` and upload `dist/*`. twine refuses `--skip-existing` for any other index, so the Gitea step asks `/api/v1/packages/<owner>/pypi/<name>/<version>/files` which files Gitea already holds: 200 compares and uploads only the missing ones, 404 uploads all, any other status fails the step.
  - That lookup sends its `Authorization` header on stdin (`printf 'Authorization: token %s\n' "$TWINE_PASSWORD" | curl … -H @- …`), never on argv. The `workflows-no-auth-header-argv` pygrep hook refuses a literal `-H`/`--header` `authorization:` flag in any quoting (`-H "…"`, `-H'…'`, `-H $'…'`, `--header=…`) in every YAML file under `.github/`, case-insensitive. Coverage limit: flag and value on the same line only; a value on the next line after a `\` continuation, a header assembled in a variable, one passed through curl's `--config`/`-K` file, and other credential flags (`-u`/`--user`, `--oauth2-bearer`) are not matched.
  - `twine` is declared once, in the optional Poetry group `publish`; publish jobs run `poetry install --only publish --no-root`. Locally, `poetry install --with publish`.
  - Poetry itself is installed everywhere in CI with `pip install --require-hashes -r .github/requirements/poetry.txt`, generated (never hand-edited) from `.github/requirements/poetry.in` by the command in its header (`pipx run --python 3.14 --spec 'pip-tools==7.6.2' pip-compile --generate-hashes --output-file .github/requirements/poetry.txt .github/requirements/poetry.in`). This file is the one bootstrap-only exception to ADR-0001 (ADR-0046): it installs Poetry and nothing else; application, dev and publish dependencies stay in `poetry.lock`. Updates: Dependabot `pip` on `/.github/requirements` on GitHub; if a Dependabot PR drops the `--hash=` lines or fails `pip install --require-hashes`, the entry is removed and the maintainer regenerates the file when bumping Poetry (always manual on Gitea).

### AD-12 — Release [ADOPTED]

- **Binds:** `release.yaml`, the per-release checklist
- **Prevents:** publishing from a malformed or pre-release tag; a release from a commit not on the default branch; a hand-kept changelog; a release created before its artifacts exist; announcing a release that silently skipped a target destination.
- **Rule:** `release.yaml` runs these jobs in order:
  1. **`validate-tag`** runs `git-action-tag-validate-version@v2` with `version-regex: '^v\d+\.\d+\.\d+$'`, followed by one step `if: steps.tag.outputs.is-valid != 'true'` that exits 1. It then checks out ref-free with `fetch-depth: 0`, `persist-credentials: false` (AD-6) and runs one step with no `if:`, `Tag is on the default branch`: it reads `github.event.repository.default_branch` through `env`, fails if it is empty, logs the tag, commit and default branch, and exits 1 with `refusing to release tag <tag>: commit <sha> is not on origin/<default>` unless `git merge-base --is-ancestor HEAD refs/remotes/origin/<default>` succeeds. That step guards against mistakes only; the control is forge tag protection on `v*` (ADR-0038).
  2. **`build`** (`needs: validate-tag`).
  3. **`publish-package`** and **`publish-image`**.
  4. **`release`**, which `needs` both publish jobs, runs the AD-18 step order (Destination configuration reporting `Forge release` only, hash verify, CA import), and gates each further step on `PUBLISH_RELEASE` (a job-level `if:` cannot read `env`); with the token unset it succeeds as a no-op. `git-action-release-changelog-builder@v3` generates the notes, and `git-action-release@v2` creates the release on the running forge with `token: PUBLISH_RELEASE_TOKEN` and `allow-updates: true`, attaching the `dist` wheel and sdist.

  There is no CHANGELOG file and no `scriv`. Operator upgrade notes live in `docs/upgrading.md`. A release is acceptable only when its run shows **zero** partial-configuration warnings, each target destination `enabled` exactly once and **zero** `Unexpected input` lines (the runner checks every step's `with:` against the pinned `action.yml`; AD-18), when the one-forge check finds no `PUBLISH_*` name on the non-publishing forge (AD-9), and when every configured registry carries one digest for the release's `X.Y.Z`, `X.Y` and `latest`; otherwise fix and re-run before announcing. Not mechanically enforced: per-release checklist items in `docs/ci/pipeline-walkthrough.md`. The digest check is a checklist command (maintainer decision MD-15) that ends every lookup with a newline, because `imagetools inspect --format` prints none and several digests piped into `sort -u` would otherwise collapse into one line:

  ```sh
  dig() { for t in "$@"; do docker buildx imagetools inspect "$t" --format '{{json .Manifest.Digest}}'; echo; done; }
  for r in $GHCR_IMAGE $DOCKERHUB_IMAGE $GITEA_IMAGE; do dig "$r:X.Y.Z" "$r:X.Y" "$r:latest"; done | sort -u | grep -c .   # must print 1
  ```

  The image names are the configured `PUBLISH_*_IMAGE` values. A defect found after tagging is fixed in the next patch release, never by moving or re-pushing the tag.

### AD-13 — Permissions [ADOPTED]

- **Binds:** every workflow, the forges' secret stores
- **Prevents:** ambient write access; a credential that means different things on each forge; a branch workflow reading publish secrets; a forge-admin token in reach of a publish job.
- **Rule:** Every workflow declares `permissions: contents: read` and no job widens it. Every credential is a `PUBLISH_*` secret (AD-9), including the release token, held only in a forge secret store. On GitHub each is held in the environment of the jobs that use it (`dev` or `release`, Conventions) and none at repository level. Credential types for the GitHub publishing forge (maintainer decisions MD-10 to MD-12, 2026-10-12), each with an expiry:
  - `PUBLISH_GHCR_TOKEN`: a classic personal access token with only `write:packages` (GHCR accepts only classic tokens). Accepted residual: it can write every package of the account. The workflow `GITHUB_TOKEN` with `packages: write` is not used: it would widen job permissions and hand the ambient token to a publish step (AD-9). Revisit if GHCR accepts fine-grained tokens.
  - `PUBLISH_RELEASE_TOKEN`: a fine-grained token on this repository only, Contents read/write and Pull requests read (the changelog builder).
  - `PUBLISH_GITEA_TOKEN`: a `write:package`-only token, never an instance-admin token, stored only in the GitHub `release` environment. Gitea package access is per user or organisation, never per package; moving the packages to a bot or organisation namespace is Deferred.
  - PyPI and Docker Hub tokens stay scoped to this project and repository. On Gitea, which ignores `environment:`, publish secrets are repository-level and present only when Gitea is the publishing forge (AD-9); they may include PyPI, TestPyPI, GHCR and Docker Hub tokens. Because any branch workflow on Gitea can read them, a Gitea publishing forge requires: pushes and tag creation restricted to trusted accounts (protected `main` and protected `v*` tags), tokens scoped to this project only (PyPI project-scoped token, GHCR/Docker Hub tokens limited to this repository/image, Gitea package/release tokens from a namespace or bot account), and rotation of every token after any untrusted push. Accepted residual risk (maintainer decision 2026-10-11): a trusted account's branch workflow can read the tokens.

### AD-14 — Ordering and concurrency [ADOPTED]

- **Binds:** `dev.yaml`, `release.yaml`
- **Prevents:** an older dev run moving `dev` after a newer one; two releases racing on `latest`.
- **Rule:** `dev.yaml` declares `concurrency: { group: dev, cancel-in-progress: true }`. `release.yaml` declares `concurrency: { group: release, cancel-in-progress: false }`: at most one release runs and one waits; a running release is never cancelled. GitHub keeps one pending run per group, so a newer tag cancels the waiting release, which published nothing. It is re-run (`gh run rerun <run-id>`) only while no newer tag has released — a later re-run would re-point `X.Y` backwards (`latest` is gated on the highest tag, AD-8); otherwise it stays unreleased and the next patch is cut. The comment in `release.yaml` and the walkthrough say exactly this. A per-ref group is rejected (two releases would race on `latest`); `queue: max` is revisited when actionlint accepts it (ADR-0046 item 11).

### AD-15 — Dev never publishes a release version [ADOPTED]

- **Binds:** `dev.yaml` publish jobs, `just release`
- **Prevents:** a dev run on a tagged commit publishing `X.Y.Z` and colliding with `release.yaml`.
- **Rule:**
  - `just release` requires `HEAD` to equal `origin/<default>` after a fetch, and pushes only the tag, so the branch push that ran `dev.yaml` happened before the tag existed.
  - Each `dev.yaml` publish job runs, right after Destination configuration, a step that fails unless `needs.build.outputs.version` contains `.dev`. This covers re-runs of `dev.yaml` after tagging.
  - Pushing a branch and a tag together is unsupported.

### AD-16 — The justfile is the local interface [ADOPTED]

- **Binds:** `justfile`
- **Prevents:** release or verification logic living in bespoke scripts; a local run that publishes; ambient workstation secrets reaching a local workflow run.
- **Rule:**

  | Recipe | Does |
  | --- | --- |
  | `just install` | `poetry sync --all-groups` (ADR-0042) |
  | `just check` | AD-3 |
  | `just build` | clean `dist/`, then `poetry build` |
  | `just image` | build and load the image from `dist/` per AD-17 |
  | `just act [workflow]` | `act --detect-event -W .github/workflows/<workflow> --defaultbranch <default> --artifact-server-path <tmp> -P ubuntu-latest=ghcr.io/catthehacker/ubuntu:act-latest --secret-file /dev/null --var-file /dev/null`, with `HOME` and `XDG_CONFIG_HOME` set to fresh temporary directories; default `ci.yaml`; no `--secret` arguments; exits 1 with `act: refusing to run with ./.actrc present (it can pass secrets); remove it` when `./.actrc` exists |
  | `just release <major\|minor\|patch>` | see below |

  - Running `dev.yaml` or `release.yaml` through `just act` passes no secrets and reads none of act's ambient sources (`~/.actrc`, `.secrets`, `.vars`), so every destination is unconfigured and silent (AD-9). Limits, stated in the recipe comment: a `.env` file still sets container environment variables (not `secrets.*`), and a raw `act` run outside the recipe is not covered (AD-9). — E015-S02-002.
  - The default branch is derived once, as the justfile variable `default_branch` (`origin/HEAD` with `origin/` stripped, else `main`; it never fails). `just release` reads it, and `just act` passes it as `--defaultbranch` so AD-12's ancestry check sees the real default branch rather than act's `master`.
  - `--detect-event` is mandatory: without it act sends `push`, and a `pull_request`-only workflow runs no job and exits 0. Evidence of a local run must show the `build` job executed, not only exit status 0.
  - `just release` requires a clean tree on the default branch, AD-15's sync check and `just check`, and refuses when the base tag already points at HEAD. It computes the next version from the latest tag matching `^v\d+\.\d+\.\d+$` (AD-7's pattern) with `pysemver bump`, creates annotated tag `vX.Y.Z`, and pushes only that tag. A release creates no commit.

### AD-17 — Image build contract [ADOPTED]

- **Binds:** `docker/Dockerfile`, `build.yaml`, `publish-image`, `just image`, every job that downloads `dist`
- **Prevents:** three callers building the image with different inputs; an image not built from the tested wheel; a `dist` altered between the build job and a publish job.
- **Rule:**
  - Every image build uses `docker/Dockerfile` with context `.` and exactly these build args, all required:
    - `POETRY_VERSION` (Stack);
    - `WHEEL_PATH` (the `dist` wheel);
    - `WHEEL_SHA256` (in CI, `needs.build.outputs.wheel-sha256` from the build job, never recomputed from the downloaded file);
    - `VERSION` (`image-version` in CI; the wheel's PEP 440 version in `just image`);
    - `REVISION` (the full commit SHA).
  - The image installs that wheel and verifies its hash (ADR-0008's provenance, built with `docker/build-push-action` rather than bake).
  - The Dockerfile verifies the installed version against `VERSION` under PEP 440 normalisation, using the `packaging` vendored in the builder's pip: `1.4.1-dev.3` and `1.4.1.dev3` both match an installed `1.4.1.dev3`.
  - The Dockerfile's dependency-install step (`--no-root`) runs with `POETRY_DYNAMIC_VERSIONING_BYPASS=0.0.0`, because the builder has no `.git`; it is the only bypass site. The installed application version still comes from the hashed wheel.
  - Every job that downloads `dist` (`publish-package` and `publish-image` in both workflows, and `release`) runs a hash-verify step at its AD-18 position: it asserts each hash output matches `^[0-9a-f]{64}$` (naming the output otherwise), prints file, expected and computed hash, and runs `sha256sum -c` against `needs.build.outputs.wheel-sha256` and `sdist-sha256`. A mismatch fails the job before any login, upload, build or release step.
  - Labels come from `git-action-docker-metadata@v6`.

### AD-18 — Publish-job step order and private CA [ADOPTED]

- **Binds:** every publish job
- **Prevents:** TLS failures to a private-CA Gitea from the runner, BuildKit, or `twine`; a credential touched before the job has checked what it is about to publish; a CA config handed to an input the pinned action no longer has.
- **Rule:**
  - Every publish job runs, in this order: Destination configuration (AD-9) → version guard (AD-15, `dev.yaml` only) → hash verify (AD-17) → CA import → login / publish. Presence-only evaluation of secrets (`!= ''` in job `env` and the `HAS_*` step booleans) is not a credential touch; the CA import is the first step that touches a credential.
  - The CA import is `git-action-ca-certificate-import@v3`, gated on `PUBLISH_CA` (AD-9), with `certificate: PUBLISH_CA_CERTIFICATE` and `generate-buildkit: true`. In `publish-image`, `docker/setup-buildx-action` (v4) receives that step's `buildkit-path` output through its `buildkitd-config` input; an empty value adds no `--config` to `buildx create`, so the no-CA path is unchanged. v4 removed the earlier `config` and `config-inline` inputs. `twine` steps set `REQUESTS_CA_BUNDLE: /etc/ssl/certs/ca-certificates.crt`, harmless when no CA was imported.
  - The `workflows-no-removed-buildx-inputs` pygrep hook refuses a `config:` or `config-inline:` key in any YAML under `.github/workflows/` or `.github/actions/`. Coverage limit: those two key names only, block style, for every action (pygrep cannot see the step, so another action's input of that name is refused too); a flow-style `with:` mapping is not matched, and other actions' removed inputs are not seen.
  - actionlint validates `with:` keys only for popular actions referenced at a major tag, so it checks no SHA-pinned step here, and no maintained tool validates inputs of SHA-pinned actions. The GitHub runner's `Unexpected input(s)` warning, which checks every step against its pinned `action.yml`, is read by the per-release checklist (AD-12); it is not CI-gating. — E015-S02-001.

## Consistency Conventions

| Concern | Convention |
| --- | --- |
| Job ids | `validate-tag`, `build`, `publish-package`, `publish-image`, `release`, identical across workflows; every job carries `name:` equal to its id. Required check on pull requests: `build / build` |
| Artifact | one artifact `dist`, always downloaded with `path: dist/`, holding exactly one `.whl` and one `.tar.gz` |
| Hand-off | `needs.build.outputs.version` (PEP 440), `image-version` (SemVer), `wheel-sha256`, `sdist-sha256` only |
| Secrets and variables | `PUBLISH_<DESTINATION>_<FIELD>`, upper snake case, as in AD-9; intent flags `ANY_<DEST>`; presence booleans `HAS_<NAME>` |
| Conditionals | No `if:` reads `secrets` or `vars` (enforced by the `workflows-if-no-secrets-vars` hook, dot and index form; a multi-line `if: >-` is checked on its first line only, and "exactly one flag" is held by review). Allowed forms only: AD-9's single-flag `if: env.PUBLISH_X == 'true'` on steps (the `release` job gates each step, since a job-level `if:` cannot read `env`); the AD-12 validity check; the unconditional Destination configuration step; and the metadata `enable=` attribute of AD-8's major-tag line. Flags (conjunctions and disjunctions of presence tests) and image names are computed in job `env`, never inline in `if:` |
| Publish-job step order | AD-18 |
| Environments | GitHub `dev` (policy Branch `main`) on `dev.yaml` `publish-package`/`publish-image`; `release` (policy Tag `v*`) on `release.yaml` `publish-package`/`publish-image`/`release`; plain string form, no `url:`; none on `validate-tag` or `build` (a reusable-workflow caller cannot set one, and `build` holds no secret) |
| Shared publish logic | edited in `dev.yaml` and `release.yaml` in the same commit (AD-1) |
| Idempotent re-run | PyPI/TestPyPI uploads use `--skip-existing`; the Gitea upload sends only the files Gitea does not already hold (AD-11); the release step uses `allow-updates: true`; a re-run re-points every tag written by that run, across every enabled registry, to the one digest that run built, not the previous digest. Gating is evaluated per run attempt; never re-push a tag |
| Transient registry errors | a ghcr.io `429` in `build` or `publish-image` is answered by re-running the job; no login is added to `build` |

## Stack

| Name | Version |
| --- | --- |
| Gitea (server, minimum) | 1.27.0 |
| nektos/act (local runner, as verified) | 0.2.89 |
| curl on runners (`-H @-`) | ≥ 7.55.0 |
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
| Python (CI) | 3.14 |
| Poetry | 2.4.2 (hash-locked bootstrap, AD-11) |
| pip-tools (`pip-compile`, bootstrap generator) | 7.6.2 (`pipx run --python 3.14`) |
| poetry-dynamic-versioning | 1.10.0 |
| dunamai | 1.26.2 |
| twine | 7.0.0 (`publish` group) |
| semver (`pysemver`) | 3.1.0 |
| mypy | 2.4.0 (dev group, locked in `poetry.lock`; `repo: local`, `language: system` hook, AD-3) |
| types-pyyaml, types-python-dateutil | 6.0.12.20260906, 2.9.0.20260807 (dev group, locked; mypy stubs) |
| pip-audit, deptry | `^2.10.1`, `^0.25.1`; dev group, locked in `poetry.lock`; `repo: local` hooks, not `--freeze`'d |
| import-linter | 2.15 (dev group, locked in `poetry.lock`; `repo: local`, `language: system` hook; product AD-13) |
| shellcheck-py | v0.11.0.1-1 (SHA-frozen) |
| nick-fields/retry | v4.0.0 `ad984534de44a9489a53aefd81eb77f87c70dc60` (`build` job only; no credentials there) |
| pre-commit-hooks | v6.0.0 (SHA-frozen) |
| ruff (`ruff-pre-commit`) | v0.16.5 (SHA-frozen) |
| actionlint | v1.7.12 (SHA-frozen) |
| zizmor | v1.30.1 (SHA-frozen) |
| gitleaks | v8.30.1 (SHA-frozen) |

Hook rows give the tag a `# frozen:` comment names; `pre-commit autoupdate --freeze` may move them, and the row moves with the bump.

## Structural Seed

```text
.github/
  workflows/
    build.yaml      # AD-2: reusable, credential-free; outputs version, image-version, wheel/sdist sha256
    ci.yaml         # pull_request -> build
    dev.yaml        # push to default branch -> build -> publish-package, publish-image
    release.yaml    # tag v* -> validate-tag -> build -> publish-* -> release
  requirements/
    poetry.in       # AD-11: poetry==<Stack version>
    poetry.txt      # AD-11: generated with hashes; bootstrap-only exception to ADR-0001
  zizmor.yml        # AD-5 hash-pin policy
  dependabot.yml    # github-actions, pip (/ and /.github/requirements), docker, pre-commit; cooldowns;
                    # artifact-action majors act cannot run are ignored
.pre-commit-config.yaml   # AD-3: the one hook list, SHA-frozen
pyproject.toml            # AD-7 versioning config; AD-11 `publish` group; AD-3 [tool.deptry]
justfile                  # AD-16
docker/Dockerfile         # AD-17
docs/upgrading.md         # AD-12: operator upgrade notes (no CHANGELOG)
```

```text
 deployment / environments
 -------------------------
 runners:     GitHub-hosted | Gitea 1.27+ act_runner (curl, jq) | local act    (same YAML)
 indexes:     Gitea PyPI index (dev+rel) | TestPyPI (dev) | PyPI (rel)
 registries:  GHCR | Gitea container registry | Docker Hub (dev+rel)
 enabled:     a destination publishes iff its token AND all its variables are set (AD-9)
 per release: one forge's run publishes everything (GitHub from 0.3.1); the other forge holds no PUBLISH_* secret or variable
 workstation: holds no publish token; never publishes a release version
 just act:    ambient act secret sources ignored -> nothing publishes, nothing warns
```

**Retired with this spine.** These are removed, not ported:
- workflows `verify-build.yaml`, `publish-image.yaml`;
- composite actions `verified-bundle`, `publication-contract`, `setup-poetry-python`;
- `src/publication_contract/` (and its `pyproject.toml` package entry) and `tests/ci/`;
- scripts `scripts/release_version.py`, `scripts/committed_versions.py`, `scripts/vendored_trees.py`, and `vendored-trees.lock`;
- `docker/act-build.sh`;
- the `scriv` dependency;
- `git-action-tag-floating-version`;
- the fail-fast "Registry configuration guard" step.

**ADRs superseded by ADR-0035:** 0006, 0007, 0009, 0011, 0015, 0019, 0020, 0021, 0022, 0029, 0031, 0032, and the near-miss-probe and untracked-file-gate parts of 0033.

**ADRs amended by ADR-0035:**
- 0008: built with build-push-action, not bake.
- 0010: release credential per AD-9 and AD-13.
- 0012: tags per AD-8.

**ADRs carried forward:** 0004, 0018 and 0028, plus 0033's rule as restated by ADR-0037: the repository adds no path exemption to secret scanning (gitleaks' default allowlist is inherited). ADR-0036, 0038 and 0039 are folded into the Rules above. The E014 amendments (configuration gating, hash hand-off, Poetry bootstrap exception, one forge per release, zero-warning release rule, step order, 0.x major tag) are recorded in ADR-0046, and the accepted publish duplication in ADR-0047. The E015 decisions are recorded by the ADR to be written by E015-S02-002 (forge-run-only publishing, credential types, the 0.3.0 exception; amends ADR-0039) and by ADR-0042's amendment written by E015-S02-003 (locked hook dependencies and the remaining "Not covered" hooks); E015-S02-001 needs no ADR.

## Deferred

- **SBOM and `provenance: mode=max`.** `docker/build-push-action`'s `sbom` and `provenance` inputs are BuildKit attestations and need no OIDC. Inspected 2026-10-11 (E014-S02-003, `docker buildx imagetools inspect …/traefik-certificate-exporter:dev --format '{{json .Provenance}}'` on the Gitea `dev` image, version `0.2.1-dev.13`; no workflow sets a `provenance` input, so this is `docker/build-push-action`'s default): the Gitea registry holds a BuildKit SLSA provenance attestation per platform (`linux/amd64`, `linux/arm64`), and it already includes `internalParameters.buildConfig` and `buildkit_metadata.layers` (fields BuildKit emits only in `mode=max`) and the full `github_event_payload`, which is therefore published with the image. `{{json .SBOM}}` is empty: the image has no SBOM. Still deferred, not in 0.3.1: `sbom: true` (Gitea registry acceptance of an SBOM attestation and `act` behaviour are unverified) and setting the provenance mode explicitly. Revisit with BL-E014-073, which also weighs the published event payload.
- **Image vulnerability scanning.** No scanner is bound. Revisit when a consumer requires it.
- **Cross-registry digest equality as a CI job** (maintainer decision MD-15, option c). It stays a per-release checklist command (AD-12). Revisit once GHCR, Docker Hub and Gitea publish from one run routinely.
- **Validation of SHA-pinned action inputs.** No maintained tool does it (actionlint covers major-tag references only); the runner warning plus the checklist item stand in (AD-18). Revisit when a maintained validator exists.
- **Every remote Python hook in the lock** (option B of maintainer decision MD-17: pre-commit-hooks, ruff, zizmor, shellcheck-py as `repo: local` system hooks), including `pre-commit-hooks`' range-resolved `ruamel.yaml` (Low backlog item). Recorded in ADR-0042 "Not covered" (AD-3).
- **Gitea packages in a bot or organisation namespace** (maintainer decision MD-12, option b). It changes the image and index names users pull; a separate decision.
- **Forge settings are documentation unless configured** (checklist in `docs/ci/pipeline-walkthrough.md` §"Forge settings the maintainer applies"). Required, not deferred: GitHub environments `dev`/`release` with their policies; a `main` ruleset (no deletion, no force push, pull request with ≥ 1 approval, stale approvals dismissed, last-push approval, required check `build / build`, bypass the Repository admin role only) and a protected Gitea `main` (maintainer-only merge allowlist, required approval, the `build` status check); tag protection on `v*` on both forges (GitHub ruleset `release-tags`, Gitea protected tag, maintainer only); GitHub Actions `default_workflow_permissions: read` and `can_approve_pull_request_reviews: false`; GitHub secret scanning and push protection enabled; no repository-level `PUBLISH_*` secret on GitHub. Only `secrets-outside-env` and `anonymous-definition` are checked from the repository. The admin bypass actor, and anyone who can approve, can still land code on `main`.
- **One forge per release, no workstation publishing, zero partial-configuration warnings, zero `Unexpected input` lines and one digest per release** are checklist items or rules, not checks (AD-9, AD-10, AD-12, AD-18). A raw `act -s <token>` run cannot be prevented by the repository.
- **Live certification.** Proven by the 0.3.0 GitHub release run 38281339396: `validate-tag` on GitHub, PyPI, Docker Hub with `X.Y.Z`/`X.Y`/`latest`, and the `release` environment. Unproven until E015-S02-004 releases 0.3.1: GHCR, the Gitea package index and container registry from a forge run, and the forge release with assets. The private-CA path is proven under `act` against a local TLS registry by E015-S02-001, not on a forge. The Gitea `act_runner` release path (BL-E013-044) and a TestPyPI dev publish are unexercised.
- **Artifact action majors.** Under `act` 0.2.89, upload-artifact v6+ fails at upload (`Error unauthorized`, signature padding, nektos/act #6114) and v7 also sends an unknown `mime_type` (#6022); verified 2026-10-09 with a two-job upload/download matrix (v4.6.2/v4.3.0 and v5.0.0/v6.0.0 pass; v6.0.0 with v6.0.0/v7.0.0 fail). Dependabot ignores those majors until an `act` release ships PR #6174, then revisit.
- **`queue: max` for release concurrency.** actionlint v1.7.12 rejects it. Revisit when actionlint accepts it.
- **SHA pins for `LiquidLogicLabs/*` actions** (BL-E013-022/029), **locking Poetry's plugin transitive dependencies** and Poetry inside the Dockerfile builder (BL-E013-033), and **local composite actions** for the shared publish logic (ADR-0047) stay open.
- **`.dockerignore`** (review F-19) is undecided.

## Changelog

- 2026-10-11: consolidated to a clean 0.3.0 target state from `.memlog.md` (through 2026-10-11), ADR-0028, 0033 (as amended), 0035, 0036, 0037, 0038, 0039, E014-S01-007, E014-S02-001, E014-S02-002, E014-S02-005, `review-all-epics-2026-10-10/review-cicd.md` and `research-2026-10-10-release-0.3.0.md`.
- 2026-10-11 E014-S02-003 routing (post-merge deltas only, one `.memlog.md` line each): AD-2 install is `poetry sync --all-groups` and the pre-pull is `nick-fields/retry` with a fixed 30 s wait plus buildx `driver: docker` (F-06, AG-14); AD-3 `pip-audit` bullet carries ADR-0042's wording and the hook list names every pygrep guard, `pip-audit-bootstrap` and `import-linter`; AD-5 Dependabot ecosystems as configured and the LLL hook's coverage limit; AD-11 pip-tools command from the file header; AD-14 re-run wording (BL-E013-036); AD-16 `just install`; Conventions Conditionals cite `workflows-if-no-secrets-vars`; Stack versions; `companions` gain ADR-0042, 0046, 0047; Deferred SBOM/provenance states the inspection result.
- 2026-10-11 baseline cross-check (`epic-014/plan-review/review-baseline-consistency.md`): `target` set; AD-3 required hooks gain `shellcheck` and `s6-no-raw-settings-env` (E014-S01-005, product AD-12) and the Deferred ShellCheck item is removed; E014-S01-005 added to `sources`; GitHub secret scanning and push protection added to the forge-settings list; AD-13 already reads "only when Gitea is the publishing forge (AD-9)".
- 2026-10-12: consolidated to a clean 0.3.1 target state (E015), no amendment layering. Sources: E015-S02-001..004, maintainer decisions MD-10..MD-18 accepted 2026-10-12, research brief 2026-10-12 §5-§8, E014 closure spec proposals AD-1 (release topology) and AD-2 (hook dependencies), red-team RT-2. AD-3: mypy and import-linter run `repo: local` `language: system` from `poetry.lock`, the hook-dependency lock rule and `precommit-hook-deps-locked`, the remaining remote hooks not covered, and the hook list completed with `workflows-latest-tag-gated` (AD-8) and `workflows-no-removed-buildx-inputs`; AD-9: forge-run-only publishing, no workstation publishing, GitHub as the publishing forge from 0.3.1; AD-10: one build per release and the 0.3.0 exception; AD-12: `Unexpected input`, one-forge and digest-equality checklist items with the newline-safe command; AD-13: GHCR, release and Gitea credential types; AD-16: `just act` isolation and `./.actrc` refusal; AD-18: `buildkitd-config` and its guard; Stack, deployment sketch, Deferred and live-certification status updated. ADRs not yet written are named by the E015 story that writes them. Production upgrade handling (MD-16) is not a pipeline invariant and lives in E015-S02-004.
