# ADR-0035: A standard, trigger-selected CI/CD pipeline replaces the governed pipeline

- **Status:** Accepted — implemented in E013 sprint 01; live forge verification pending (E013-S02-001)
- **Date:** 2026-10-08
- **Deciders:** Maintainer + architecture gate
- **Spine:** `_bmad-output/planning-artifacts/architecture/architecture-ci-cd-pipeline-2026-10-08/ARCHITECTURE-SPINE.md` (AD-1..AD-18)
- **Supersedes:**
  - the 2026-08-31 CI/CD spine (CI-AR1..CI-AR50);
  - ADR-0006, 0007, 0009, 0011, 0015, 0019, 0020, 0021, 0022, 0029, 0031, 0032;
  - the near-miss-probe and untracked-file-gate parts of ADR-0033.
- **Amends:**
  - ADR-0008: the image is still built from the tested wheel, but with `docker/build-push-action`, not bake;
  - ADR-0010: release credential;
  - ADR-0012: tag set.
- **Carries forward:** ADR-0004, ADR-0018, ADR-0028, and ADR-0033's rule as restated by ADR-0037: the repository adds no path exemption to secret scanning.
- **Walkthrough:** `docs/ci/pipeline-walkthrough.md`
- **Amended by:** ADR-0036 (E013 arch gate); ADR-0037 (inherited gitleaks default allowlist)

## Context

The pipeline grew to 5 workflows, 31 jobs and about 4,100 lines of workflow YAML. Around it sat:
- 3 composite actions;
- a custom `publication_contract` validator;
- about 12,000 lines of `tests/ci/` policy code that parses the workflows and asserts their shape;
- 1,300 lines of release and integrity scripts.

For one Python package and one Docker image this was disproportionate, and a review on 2026-10-08 showed what that cost:
- Several guards had become tautologies after ADR-0028: the `dev` freshness check, the release tag re-check, and `verified-bundle`'s identity match.
- The wheel was hashed three times on its way to publication.
- Each fix to the policy machinery produced new findings in the machinery itself.

The maintainer asked for a cleaner, more standard pipeline with these constraints:
- prefer LiquidLogicLabs actions (major-pinned), then widely used documented actions, then scripts only when necessary;
- the same YAML on local `act`, Gitea runners and GitHub runners;
- no `env.ACT`, and no complicated step conditionals;
- standard SemVer, with the package and image versions matching;
- dev builds and releases;
- `just` for local entry points.

## Decision

Adopt the 2026-10-08 spine. In summary:

1. **Four workflows, chosen by trigger.** `build.yaml` is reusable and credential-free. `ci.yaml` runs it on pull requests, `dev.yaml` on pushes to the default branch, and `release.yaml` on `vX.Y.Z` tags. Nothing branches on channel, forge or host.
2. **One build.** Pre-commit (the same hook list `just check` runs), pytest, `poetry build`, a smoke-tested single-arch image, and one `dist` artifact. The build job owns the version and hands it to every other job.
3. **Tags are the only version source.** `poetry-dynamic-versioning` produces `X.Y.Z` on a tag and `X.Y.(Z+1).devN` otherwise. The image uses the SemVer spelling `X.Y.(Z+1)-dev.N` of the same version. `just release <bump>` creates and pushes only a tag; no release commit.
4. **Every destination is optional and enabled by its `PUBLISH_*_TOKEN` secret**, in any combination, in the same run, from either forge:
   - Python package: Gitea package index, TestPyPI (dev), PyPI (release);
   - image: GHCR, Gitea registry, Docker Hub;
   - the forge release itself.

   The only step conditions are one flag per destination and one tag-validity check.
5. **One multi-arch image build per run**, pushed to every enabled registry. Each tag has exactly one workflow that writes it:
   - dev images: `-dev.N`, `sha-*` and `dev`;
   - release images: `X.Y.Z`, `X.Y`, `X` and `latest`.
6. **Standard checks only.** actionlint, zizmor (whose pin policy allows `LiquidLogicLabs/*` at major tags and requires commit SHAs for everything else), gitleaks, ruff and mypy. No repository code polices workflows.

## Alternatives considered

- **Amend the 2026-08-31 spine.** Rejected: most of its 50 rules would be retired or rewritten, and partial amendment leaves contradictions.
- **Committed version in `pyproject.toml`, bumped by a release commit (ADR-0006).** Rejected: a tag and a commit can disagree, and it needs the 727-line `release_version.py`.
- **Short commit SHA in the dev version.** Rejected for the package: PEP 440 `.dev` takes only a number, and PyPI and TestPyPI reject local `+hash` versions. Kept for the image as the `sha-<7>` tag.
- **`pypa/gh-action-pypi-publish`.** Rejected: it exits on Gitea and `act` because it requires `GITHUB_WORKFLOW_REF`, and upstream declined to change that (issue #275). `twine upload` is used instead (accepted "for now").
- **Trusted publishing (OIDC) to PyPI.** Rejected: GitHub-only, so it would need a forge condition.
- **The ambient forge token for creating releases.** Rejected in favour of `PUBLISH_RELEASE_TOKEN`, so every credential follows the same rule.

## Consequences

- About 4,100 lines of workflow YAML become four small workflows. Removed in the change that implements this ADR:
  - `tests/ci/` and `src/publication_contract/`;
  - the three composite actions;
  - `scripts/release_version.py`, `scripts/committed_versions.py`, `scripts/vendored_trees.py`, `vendored-trees.lock`;
  - `docker/act-build.sh` and `scriv`.
- The vendored `.agents/`, `.claude/` and `_bmad/` trees lose their repository-side integrity record. Secret scanning still reads them.
- LiquidLogicLabs actions ride their major tags. A moved tag in that org reaches credentialed jobs; this is accepted because the org is the maintainer's own. Third-party actions stay commit-pinned, and Dependabot proposes updates.
- Build provenance attestations are not produced (GitHub-only).
- Gitea 1.27 is the minimum server version (reusable workflows; `concurrency` needs 1.26).
- Live verification on a Gitea runner is part of implementation. That covers the artifact actions, `workflow_call`, `concurrency` and `twine`. The artifact actions are held at upload-artifact v5.0.0 / download-artifact v6.0.0 because act 0.2.89 rejects newer majors (spine Stack and Deferred sections).
- Superseded ADRs keep their text. Their status lines are updated to "Superseded by ADR-0035" in the implementing change, when the pipeline they describe is removed.
