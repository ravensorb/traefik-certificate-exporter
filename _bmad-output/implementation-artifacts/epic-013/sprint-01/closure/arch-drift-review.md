# E013 Sprint 01 — Architectural drift review (l3io-arch-review, Mode B, headless)

- **Scope:** stories E013-S01-001, -002, -003, -005 (004 is carried to S02 and was not reviewed) and the uncommitted diff over `.github/`, `.pre-commit-config.yaml`, `.gitleaks.toml`, `justfile`, `pyproject.toml`, `docker/Dockerfile`, `.gitignore`, `README.md`, `CONTRIBUTING.md`, `AGENTS.md`, `docs/{developer,guidelines,architecture,project-context}.md`, `docs/ci/`, `docs/adr/` (0006–0022 status/amendment edits; 0029, 0031–0033 because S01-003/S01-005 list them in their File Lists; new 0035–0037), the untracked `.github/zizmor.yml` and `docs/ci/pipeline-walkthrough.md`, and the deletions (`tests/ci/`, `src/publication_contract/`, `scripts/`, `vendored-trees.lock`, `docker/act-build.sh`, `tests/support.py`, `tests/test_release_version.py`).
- **Out of scope:** E012 work (`docker/root/**`, `libs/docker.py`, `libs/certificate_exporter.py`, `docs/operational.md`, ADR-0028/0030).
- **Standards loaded:** core §1–10, plus the GitHub Actions, Python, Docker and shell overlays. The shell overlay applies to the justfile recipes and the `run:` steps.
- **Prior gate:** `_bmad-output/implementation-artifacts/epic-013/arch/arch-gate-review.md` (AG-1..AG-18). Findings already in the backlog are not raised again: BL-E013-001 (hook `rev:` pinning), BL-E013-007 (`self-repository` suppression) and BL-E013-017 (AD-7/AD-12/AD-18 wording).

## Executive summary

The implementation follows the 2026-10-08 spine as amended by ADR-0036 and ADR-0037. There are four workflows with the AD-1 job ids, and `build.yaml` holds no credentials. Every destination is gated on a single flag. The version is transformed in exactly one place, and checkouts are ref-free. Third-party actions are pinned by SHA and checked by zizmor. Tags are the only version source, and the legacy policy code is gone.

The review found no BLOCKER, 3 MAJOR and 7 MINOR findings.

The most important action is to **restore mechanical enforcement of the rules the retired `tests/ci/` used to hold** (SD-01-2). Three rules can be checked with pre-commit's built-in `pygrep` hooks, which is configuration and therefore allowed by AD-4, yet they are now held only by CODEOWNERS review:
- `.gitleaks.toml` has no `paths` key;
- no checkout sets `ref:` or `repository:`;
- no workflow references `env.ACT`.

The other two MAJORs are about the record itself:
- The spine, ADR-0035 and the walkthrough still say secret scanning "exempts no path", which ADR-0037 has shown is false (SD-01-1).
- The SBOM/provenance deferral gives a reason that does not apply to BuildKit attestations (SD-01-3).

## Findings table

| # | Severity | Principle | Location | Finding | Remediation |
|---|----------|-----------|----------|---------|-------------|
| SD-01-1 | MAJOR | Core §10 (docs contradict the system); global rule 3 (prose that overstates coverage) | `ARCHITECTURE-SPINE.md` "ADRs carried forward" (≈L333: "0033's rule that secret scanning exempts no path"); `docs/adr/0035-standard-ci-cd-pipeline.md:15` (same claim; header has `Amended by: ADR-0036` only); `docs/ci/pipeline-walkthrough.md:212` ("committed secrets, with no path exempted") | ADR-0037 records that `useDefault = true` inherits gitleaks' default global allowlist. That allowlist skips `.git`, `poetry.lock`, `.gitleaks.toml`, `.venv/lib/python3.x` and `.poetry/plugins/*`, so a credential in `poetry.lock` or `.gitleaks.toml` is not reported. Only ADR-0033's amendment, `.gitleaks.toml` and `docs/developer.md` were corrected. The binding spine, ADR-0035 and the walkthrough's "What polices the pipeline" table still assert the opposite of the shipped behaviour. This is the same false claim AG-12 was raised for. | Restate the spine's carried-forward line and ADR-0035's `Carries forward` as "ADR-0033's rule, as restated by ADR-0037: the repository adds no path exemption". Add an ADR-0037 pointer to ADR-0035's header. Change the walkthrough row to "committed secrets; the repository adds no path exemption, gitleaks' default allowlist is inherited (ADR-0037)". |
| SD-01-2 | MAJOR | Core §3 (contract asserted at the boundary); global rule 3 (write the check with the rule); AD-4 | `.gitleaks.toml` header ("ENFORCED BY: CODEOWNERS review of this file only. No mechanical check refuses a `paths` key"); `docs/adr/0033-secret-scanning-exempts-no-path.md` Amendment (ADR-0035); `docs/guidelines.md` §7 ("Not mechanically enforced … held by CODEOWNERS review"); `.pre-commit-config.yaml` (no such hooks) | Deleting `tests/ci/` turned three hard rules back into review-only prose: no `paths` allowlist (the RT-008 red-team fix), no `ref:`/`repository:` on any checkout (AD-6, ADR-0028), and no `ACT` in workflows (AD-6). The docs say this honestly, but global rule 3 allows review-only enforcement only when a rule *cannot* be checked mechanically. Each of these is a one-line regex that pre-commit's built-in `language: pygrep` checks with no repository code, which AD-4 permits ("standard tools' configuration"). zizmor and actionlint check none of them. | Add `repo: local` hooks with `language: pygrep`: `^\s*paths\s*=` over `^\.gitleaks\.toml$`; `^\s+(ref\|repository):` and `\bACT\b` over `^\.github/workflows/`. Exclude the `ref:` pattern's legitimate non-checkout uses if any appear. Update the three "not mechanically enforced" texts to name the hooks. If the maintainer prefers review-only enforcement, record that explicitly in ADR-0035's Consequences. |
| SD-01-3 | MAJOR | Docker overlay "Supply chain — SBOM and provenance at build time"; core §8 decision hook (the recorded reason must hold) | `.github/workflows/dev.yaml:223-242`, `.github/workflows/release.yaml:242-261` (`docker/build-push-action` sets no `sbom:`/`provenance:`); spine `## Deferred` first bullet; `docs/adr/0035-standard-ci-cd-pipeline.md:76` | The overlay requires the BuildKit flags `--sbom=true --provenance=true`, which `build-push-action` exposes as the `sbom` and `provenance` inputs. The spine defers "build provenance attestations / SBOM" as "GitHub-only (needs OIDC)". That reason applies to GitHub's artifact-attestation service, not to BuildKit attestations, which are produced by BuildKit itself on any builder. So the deferral rests on a reason that does not apply. Whether the Gitea container registry accepts attestation manifests has not been verified. | Either set `sbom: true` and `provenance: mode=max` on both publish `build-push-action` steps and confirm Gitea registry acceptance in E013-S01-004, or amend the spine's Deferred bullet and ADR-0035 with the real, checkable reason (for example, registry compatibility unverified) and a revisit condition. |
| SD-01-4 | MINOR | Core §10 (stale docs) | `docs/ci/pipeline-walkthrough.md:179-180` ("image tags are rewritten to the same digest"); `docs/adr/0035-standard-ci-cd-pipeline.md:78` ("covers the v7/v8 artifact actions … fallback for `download-artifact` is v7.0.0"); `docs/guidelines.md:81` (CA import "as the first step of every publish job") | Each of these contradicts a later decision. ADR-0036 §5 says a re-run produces a new digest. The spine's Stack and Deferred sections pin upload-artifact v5.0.0 and download-artifact v6.0.0 because act 0.2.89 rejects newer majors. ADR-0036 §1 puts the version guard before the CA import, and the workflows match ADR-0036. | Correct the three sentences. The walkthrough should say a re-run re-points the run's tags to that run's digest. ADR-0035 should name the v5/v6 pair, or point to the spine Stack table. Guidelines should say the CA import follows the version guard. |
| SD-01-5 | MINOR | Core §10 / §3 (stated guarantee vs behaviour) | `.github/workflows/release.yaml:12-15` ("Releases queue; one is never cancelled mid-flight"); spine AD-14 | With `cancel-in-progress: false`, a group holds at most one running and one *pending* run. GitHub documents that a newer run joining the group cancels the existing pending run. So if a third tag is pushed while one release runs and another waits, the waiting release is cancelled and never published, with no failure on its own tag. Gitea's behaviour is unverified. "Releases queue" overstates the guarantee. | Spec-proposal: record in AD-14 and the walkthrough runbook that a superseded pending release is cancelled and must be re-run, and fix the workflow comment. Per-tag groups are the alternative, but they give up the `latest` ordering AD-14 protects. |
| SD-01-6 | MINOR | Core §3 (validate at the edge); AD-8 one writer per tag | `.github/workflows/release.yaml:22-41` (`validate-tag` checks the tag's form only) | Any well-formed `vX.Y.Z` tag publishes, wherever it points. Examples are a tag on a commit not reachable from `main`, or a lower version pushed after a higher one. Such a tag publishes to PyPI and moves `X`, `X.Y` and `latest` backwards. `just release` prevents this locally (default branch, HEAD equals origin, highest reachable base tag), but nothing on the CI side does. A tag push needs only repository write access, and branch protection is deferred. | Spec-proposal: either accept this in AD-12 (manual tag pushes are unsupported) or add a `validate-tag` step that requires the tag's commit to be an ancestor of `origin/<default>` and the tag to be the highest `vX.Y.Z`. |
| SD-01-7 | MINOR | Core §2 (reuse over copy-paste); GHA overlay ("repeated job logic → reusable workflow") | `dev.yaml` `publish-package`/`publish-image` vs `release.yaml` `publish-package`/`publish-image` (≈150 near-identical lines); the Poetry bootstrap (`setup-python` + `pip install poetry==2.4.2`) in three jobs | Per job pair, the copies differ only in the version guard, the tag set and the index destination. BL-E013-008's guard already had to be written twice, character for character. The duplication follows from AD-1's four-file rule, but no ADR weighs that trade-off. | Record the trade-off in ADR-0035's Consequences, or amend AD-1 to allow one reusable publish workflow, parameterised by tag set and index and called by `dev.yaml` and `release.yaml`. |
| SD-01-8 | MINOR | Docker overlay ("scan images in CI, fail on fixable HIGH/CRITICAL") | `dev.yaml`/`release.yaml` `publish-image`; spine Deferred "Image vulnerability scanning" | No image is scanned before or after it is pushed. The deferral is in the spine, but ADR-0035's Consequences, the decision record, does not mention it. | Defer. Add the deferral and its revisit condition to ADR-0035's Consequences. |
| SD-01-9 | MINOR | Global rule 4 (derive scope, do not enumerate by hand); core §10 | `.gitleaks.toml` header "Inherited set, one path per line"; `docs/developer.md` (same list) | ADR-0037's inherited exempt set is a hand-kept list. It says itself that it is "NOT MECHANICALLY ENFORCED", and it changes with the gitleaks version, the plugin lock and the venv interpreter. Neither Dependabot nor any hook bumps the gitleaks hook `rev`, so a change to the set goes unnoticed unless someone re-traces by hand. ADR-0037 accepts this. | Defer. When BL-E013-001 (hook rev maintenance) is decided, add a re-trace step to that upgrade path. Until then, keep the "NOT MECHANICALLY ENFORCED" statement. |
| SD-01-10 | MINOR | Shell overlay ("`mktemp` … with `trap` on the following line") | `justfile:51` (`--artifact-server-path "$(mktemp -d)"`) | Every `just act` run leaves a temp directory holding the run's artifacts (`dist`) and never removes it. | Use a shebang recipe that sets `tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT` and runs act without masking its exit status. Or record that the directory is kept deliberately for inspection. |

## Per-principle walkthrough

**Core**
- §1 Separation of concerns: PASS. `build.yaml` alone builds, tests and versions; publish jobs only download `dist`; `just` is the only local interface; the AD-17 Dockerfile consumes only the hashed wheel.
- §2 Reuse over copy-paste: SD-01-7.
- §3 Design by contract: SD-01-2 and SD-01-6. Passing items:
  - the version guards (AD-15, release tag equality);
  - the artifact-count assertions;
  - the Dockerfile's PEP 440 `VERSION` check using pip's vendored `packaging`, which ADR-0036 records;
  - the registry configuration guard (BL-E013-008), which fails before any login.
- §4 Testability: PASS. `tests/` now holds only product tests (AD-4). Workflow behaviour is evidenced by `just act` runs of ci, dev and release (notes-E013-S01-002.md). Live forge certification is E013-S01-004.
- §5 Brevity: PASS. Workflow YAML went from about 4,100 lines to 4 files, and about 12,000 lines of `tests/ci` were removed.
- §6 Comments: PASS. Comments cite AD/ADR ids. Comments that cited deleted tests were removed (Dockerfile, pyproject, pre-commit). The stale comment at `release.yaml:12` is raised under SD-01-5.
- §7 Dependency selection: PASS.
  - Added: `poetry-dynamic-versioning` 1.10.0 (MIT), `semver` 3.1.0 (BSD), `zizmor` hook (MIT).
  - Removed: `scriv`, `jsonschema`, `packaging`, `markdown-it-py`, `dockerfile-parse`, `types-jsonschema`.
  - Third-party actions are SHA-pinned. LiquidLogicLabs actions use major tags, an accepted risk recorded in ADR-0035.
- §8 GA over preview: PASS. All pins are GA releases. The artifact actions are held below the latest majors on purpose (spine Stack and Deferred).
- §9 Logging and correlation: PASS for CI scope.
  - Correlation runs through `github.sha`: the `REVISION` build arg, the OCI revision label and the `sha-<7>` dev tag.
  - Every guard prints its offending value to stderr.
  - `just release` echoes all its precondition values.
- §10 Documentation: SD-01-1 and SD-01-4.
  - The walkthrough has ASCII flow diagrams (the Mermaid fallback).
  - `docs/architecture.md` §6 derives its ADR markers from the ADR files themselves (BL-E013-013).
  - The `docs/operational.md` runbook is out of scope here.

**GitHub Actions overlay**
- Marketplace actions over shell: PASS. The remaining `run:` steps are the ones AD-11 and AD-7 justify (twine, the version read, the hash, the guards, the previous-tag lookup).
- Pinning: PASS. zizmor `unpinned-uses` applies the policy (`LiquidLogicLabs/*` ref-pin, `*` hash-pin), and no `@main` is used.
- Dependabot: PASS. It covers `github-actions`, `pip` and `docker`, each with `cooldown`. The artifact major-version ignores are kept, consistent with the spine's Deferred section.
- Least privilege: PASS. Every workflow and job has `contents: read`, and the ambient token is never used.
- Secrets: PASS. They are passed per step through `env:`/`with:`, never in job env (only boolean flags are). There is no `secrets: inherit` and no `pull_request_target`.
- Concurrency: SD-01-5.
- Composite/reusable workflows for repeated logic: SD-01-7.

**Python overlay**
- Poetry, committed lock and `poetry check --lock` hook: PASS.
- `requires-python` bounded (`>=3.10,<3.15`): PASS.
- mypy (scoped to `^src/`) and ruff hooks: PASS.
- `pip install poetry==2.4.2` in CI only bootstraps the chosen tool: PASS.

**Docker overlay** (diff hunks only)
- Digest-pinned base `ARG` is unchanged: PASS.
- No secret in any layer; the bypass is an inline env on a dependency-only `RUN`: PASS.
- SBOM/provenance: SD-01-3.
- Image scan: SD-01-8.
- Runtime posture lives under `docker/root/**` and is E012 territory, so it was not reviewed.

**Shell overlay**
- Recipes use `set -euo pipefail`, either through just's `set shell` or a `#!/usr/bin/env bash` shebang plus strict mode: PASS.
- Expansions are quoted: PASS.
- The `pipefail` and SIGPIPE hazard is avoided with the `awk` filter: PASS.
- `mktemp` cleanup: SD-01-10.

## Gate

- **BLOCKER + MAJOR (SD-01-1, -2, -3):** each must be resolved or recorded in an accepted ADR before E013 closes.
- **MINOR (SD-01-4 to -10):** deferred to the backlog. SD-01-5 and SD-01-6 go in as spec-proposals.

## Recommended ADRs

- An amendment to ADR-0035 or ADR-0036, or a new ADR, covering these changes:
  - restate the carried-forward secret-scanning rule per ADR-0037 (SD-01-1);
  - record whether the `pygrep` guards are adopted or review-only enforcement is accepted (SD-01-2);
  - correct the SBOM/provenance deferral rationale (SD-01-3);
  - record the dev/release publish-job duplication trade-off under AD-1 (SD-01-7);
  - record the image-scan deferral (SD-01-8).
- A spine amendment to AD-14 (pending-run cancellation) and AD-12 (tag placement validation), via the spec-proposal items for SD-01-5 and SD-01-6.

## Sections read

The task allowed one spec-index section. The ranges below exceed that allowance. The spine is the design authority that every in-scope story and ADR-0035/0036 cite by AD id, and its Stack and Deferred sections were needed to classify the artifact-action pins and the SBOM deferral. Every range opened is listed:

- `_bmad-output/implementation-artifacts/spec/spec-index.md` L1–40
- `_bmad-output/planning-artifacts/architecture/architecture-ci-cd-pipeline-2026-10-08/ARCHITECTURE-SPINE.md` L60–135 (AD-2..AD-8)
- `_bmad-output/planning-artifacts/architecture/architecture-ci-cd-pipeline-2026-10-08/ARCHITECTURE-SPINE.md` L160–215 (AD-10..AD-16 opening)
- `_bmad-output/planning-artifacts/architecture/architecture-ci-cd-pipeline-2026-10-08/ARCHITECTURE-SPINE.md` L255–343 (Conventions tail, Stack, Structural Seed, Retired/Carried, Deferred)
- The same spine, keyword `grep` hits only: L1–24 frontmatter markers, L34, L50, L58–59, L104, L106, L122, L127, L167, L200, L229

Blocker: 0, Major: 3, Minor: 7
