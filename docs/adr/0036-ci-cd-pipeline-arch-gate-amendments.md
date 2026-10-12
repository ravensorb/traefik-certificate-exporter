# ADR-0036: CI/CD pipeline amendments from the E013 architecture gate

- **Status:** Accepted
- **Date:** 2026-10-08
- **Deciders:** Maintainer + architecture gate
- **Epic:** E013
- **Departs from spec:** n/a
- **Spine:** `_bmad-output/planning-artifacts/architecture/architecture-ci-cd-pipeline-2026-10-08/ARCHITECTURE-SPINE.md` (amends AD-3, AD-5, AD-16, AD-17 and the Conventions row "Idempotent re-run")
- **Amends:** ADR-0035
- **Amended by:** ADR-0046 (§5: `--skip-existing` is TestPyPI/PyPI only; CI AD-11)
- **Gate record:** `_bmad-output/implementation-artifacts/epic-013/arch/arch-gate-review.md` (AG-4, AG-5, AG-7, AG-8, AG-10, AG-11)

## Context

The E013 architecture gate checked the four implementation stories against the 2026-10-08 spine. It found six places where the spine, as written, could not be met or would produce a false green:
- **AG-4.** AD-17 says the image's `VERSION` is `image-version` (SemVer). But `just image` passes the wheel's PEP 440 version, because AD-7 forbids transforming the version anywhere except `build.yaml`. AD-15 and AD-18 also both claim the "first step" of a dev publish job.
- **AG-5.** The Dockerfile's builder runs `poetry install` over `pyproject.toml` with no `.git`. Once AD-7's `strict = true` lands, `poetry-dynamic-versioning` fails there.
- **AG-7.** `act` defaults to the `push` event, so `just act` (`ci.yaml`, `pull_request` only) runs no job and exits 0.
- **AG-8.** zizmor has audits besides `unpinned-uses`. Some flag things this design does on purpose: `use-trusted-publishing` on the `twine` steps (AD-11). Others flag real gaps: `dependabot-cooldown`. AD-5 gave no rule for telling the two apart, so "zizmor passes" could only be met by an ad hoc suppression.
- **AG-10.** The Conventions table says a re-run rewrites image tags "to the same digest". A multi-arch rebuild is not reproducible byte for byte, so a re-run produces a new digest.
- **AG-11.** AD-3's hook list carries one gitleaks hook, `gitleaks dir`, which reads only the checked-out tree. The history scan that `verify-build.yaml` ran was dropped with that workflow, so a credential committed and later removed would go unseen.

## Decision

Amend the spine in place as follows. AD ids are unchanged.

1. **AD-17 — `VERSION` and step order (AG-4).**
   - `VERSION` is `image-version` in CI and the wheel's PEP 440 version in `just image`.
   - The Dockerfile verifies the installed version against `VERSION` under PEP 440 normalisation. It uses the `packaging` vendored in the builder's pip, not a hand-written parser, so `1.4.1-dev.3` and `1.4.1.dev3` both match an installed `1.4.1.dev3`.
   - In a dev publish job, the AD-15 version guard runs before the AD-18 CA import. The guard needs no network and no secret; the CA import is the first step that touches one.
2. **AD-17 / AD-7 — version bypass in the image builder (AG-5).** The Dockerfile's dependency-install step runs with `POETRY_DYNAMIC_VERSIONING_BYPASS=0.0.0`, because the builder has no `.git`. That step installs dependencies only (`--no-root`). The application's installed version still comes from the hashed `dist` wheel, so the bypass value never reaches the image's version.
3. **AD-16 — `just act` selects the workflow's own event (AG-7).** `just act` always passes `--detect-event`, so a `pull_request` workflow actually runs. Acceptance evidence for a local `act` run must show the `build` job executed. Exit status 0 alone is not evidence.
4. **AD-5 — zizmor suppression rule (AG-8).**
   - A zizmor finding that the design accepts on purpose is suppressed only per finding, with an inline `# zizmor: ignore[<audit>]` comment on the flagged line that cites the AD or ADR accepting it.
     - Example: `use-trusted-publishing` on each `twine upload` step, citing AD-11 / ADR-0035 and `pypa/gh-action-pypi-publish` issue #275.
   - `.github/zizmor.yml` disables no audit. It configures only `unpinned-uses`.
   - Every other finding is fixed, not suppressed. For example, `dependabot-cooldown` is fixed by a `cooldown` block in `.github/dependabot.yml`.
5. **Conventions, "Idempotent re-run" (AG-10).**
   - A re-run re-points every tag written by that run, across every enabled registry, to the one digest that run built.
   - It does not reproduce the previous run's digest.
   - Wheel and sdist uploads still use `--skip-existing`, and the release step still uses `allow-updates: true`.
     *Amended 2026-10-11 (ADR-0046, CI spine AD-11 as amended 2026-10-09):* `--skip-existing` applies to TestPyPI and PyPI only, because twine refuses it for any other index. The Gitea upload asks Gitea which files it already holds and uploads only the missing ones.
6. **AD-3 — secret scanning covers history (AG-11).**
   - The hook list carries a second gitleaks hook, with `alias: gitleaks-history`:
     - `entry: gitleaks git --redact --no-banner --config .gitleaks.toml`
     - `always_run: true`
     - `pass_filenames: false`
   - `gitleaks dir` still scans the tree. `build.yaml` already checks out with `fetch-depth: 0` (AD-6), so the history hook sees full history in CI.

## Alternatives considered

- **Compute a SemVer `VERSION` in `just image`.** Rejected: that would be a second version transform, which AD-7 forbids.
- **Copy `.git` into the image build context for `poetry install`.** Rejected: it leaks repository history into a build layer and makes the dependency layer depend on every commit.
- **Disable `use-trusted-publishing` audit-wide in `zizmor.yml`.** Rejected: an audit-wide disable would also hide any new upload path added later. A per-line suppression covers only the line that was examined.
- **Keep the previous digest on re-run (skip the rebuild when tags exist).** Rejected: it needs registry-reading logic in the workflow, which AD-4 rules out, and a registry enabled after the first run would never receive the image.
- **A history scan only in CI, outside pre-commit.** Rejected: AD-3 forbids a check that runs only in CI.

## Consequences

- The image's `VERSION` check accepts two spellings of one version. Both resolve to the same installed version, so provenance is unchanged (ADR-0008 as amended).
- `just act` evidence is reviewed for the executed `build` job, not only for exit status.
- Each zizmor suppression is visible at the line it covers, with its reason. Reviewers can grep `zizmor: ignore` to see every accepted finding.
- Image digests change on every re-run. The tags written by a run always name that run's image across every registry, so registries never disagree; the earlier digest is left untagged.
- `just check` reads full history on every run. It takes a few seconds on this repository; a shallow clone scans only what it has.
