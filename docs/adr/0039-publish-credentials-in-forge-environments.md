# ADR-0039: Publish credentials live in forge environments

- **Status:** Accepted
- **Amended by:** ADR-0046 (2026-10-11) -- a release may run fully from Gitea; see
  "Amendment 2026-10-11 — release may run fully from Gitea" below; ADR-0052 (2026-10-14) --
  GHCR and the forge release use the job's own token, GitHub is the release forge, the
  Gitea token is `write:package` only
  ([0052-release-publication-one-forge-run.md](0052-release-publication-one-forge-run.md))
- **Date:** 2026-10-09
- **Deciders:** Maintainer + architecture gate (E013, story E013-S02-002)
- **Epic:** E013
- **Departs from spec:** n/a
- **Amends:** AD-5, AD-6, AD-9, AD-13, the Consistency Conventions table and the Deferred
  list of the CI/CD architecture spine
  (`_bmad-output/planning-artifacts/architecture/architecture-ci-cd-pipeline-2026-10-08/ARCHITECTURE-SPINE.md`);
  resolves BL-E013-018 (RT-E013-01)

## Context

Every `PUBLISH_*` secret was a repository secret. A repository secret is readable by any
workflow on any branch, so anyone with write access (a collaborator, a stolen write token,
a write-capable agent) could push a branch carrying a workflow that prints PyPI, registry
and release tokens. AD-9's presence flags gate publishing, not reading.

What the forges offer (verified 2026-10-09):

- **GitHub.** A job receives an environment's secrets only if it names the environment,
  and only after the environment's deployment policy accepts the run's ref; otherwise the
  job fails before a runner starts. "Selected branches and tags" policies match by Ref
  type **Branch** or **Tag**. An environment secret shadows a repository secret of the same
  name, so `${{ secrets.PUBLISH_X_TOKEN != '' }}` keeps working. A workflow that names a
  missing environment creates it, with no protection rules and no secrets. A job that
  calls a reusable workflow cannot set `environment:`. Sources: github/docs
  `content/actions/reference/workflows-and-actions/deployments-and-environments.md`,
  `content/actions/how-tos/deploy/configure-and-manage-deployments/manage-environments.md`,
  `content/actions/how-tos/reuse-automations/reuse-workflows.md`.
- **Gitea 1.27+** ignores `jobs.<id>.environment` (gitea/docs
  `docs/usage/actions/comparison.md`, "Unsupported workflows syntax") and has secrets only
  at user, organisation and repository level (`docs/usage/actions/secrets.md`).
- **nektos/act 0.2.89** accepts `environment:` and ignores it (run on a throwaway
  repository: the job printed `flag=true` from a `-s` secret).
- **zizmor 1.30.1** reports `secrets-outside-env` and `anonymous-definition` only under
  `--persona=auditor`. On the tree with `name:` on every job and `environment:` on the five
  publish jobs, it prints "No findings to report" and exits 0.
- **GitHub ruleset bypass actors.** GitHub's guide "Creating rulesets for a repository" →
  "Granting bypass permissions" lists roles, teams and apps; the REST schema
  (github/rest-api-description, `components.schemas.repository-ruleset-bypass-actor`,
  checked 2026-10-09) accepts `actor_type` `Integration`, `OrganizationAdmin`,
  `RepositoryRole`, `Team`, `DeployKey` and `User`, and says `OrganizationAdmin` does not
  apply to personal repositories. Both rulesets therefore use the Repository admin role,
  the form the guide documents; on this user-owned repository the owner is the only admin.
- **Gitea package scope** (v1.27.3 `services/context/package.go` `determineAccessMode`).
  Packages belong to a user or organisation, not a repository. A user's token writes all of
  that user's packages; an organisation team with Packages on write writes all of that
  organisation's packages. No token setting narrows this to one package.

## Decision

1. **Two GitHub environments, least privilege per workflow.**
   - `dev`, policy Branch `main`: `dev.yaml` `publish-package` and `publish-image`.
   - `release`, policy Tag `v*`: `release.yaml` `publish-package`, `publish-image` and
     `release`.
   - No other job declares one. `build` holds no secret (AD-2) and is called as a reusable
     workflow, which cannot carry `environment:`.
   - Secrets per environment are the AD-9 table read by column: `dev` holds
     `PUBLISH_GITEA_TOKEN`, `PUBLISH_TESTPYPI_TOKEN`, `PUBLISH_GHCR_TOKEN`,
     `PUBLISH_DOCKERHUB_TOKEN`, `PUBLISH_CA_CERTIFICATE`; `release` holds
     `PUBLISH_GITEA_TOKEN`, `PUBLISH_PYPI_TOKEN`, `PUBLISH_GHCR_TOKEN`,
     `PUBLISH_DOCKERHUB_TOKEN`, `PUBLISH_RELEASE_TOKEN`, `PUBLISH_CA_CERTIFICATE`. No
     `PUBLISH_*` secret is held at repository level on GitHub. Secret names are unchanged;
     `vars.PUBLISH_*` stay at repository level.
   - The key is the plain string form with no `url:`, placed under the job id with
     `name: <job-id>`. Required reviewers on `release` are an optional maintainer choice,
     off by default, because they block unattended releases.
2. **The order the maintainer applies the settings in (AG-21)** is fixed, because GitHub
   auto-creates a named but missing environment unprotected:
   1. delete the unused legacy repository secrets `DOCKERHUB_TOKEN` and
      `DOCKERHUB_USERNAME`;
   2. create `dev` and `release` with their policies and no secrets;
   3. apply the `v*` tag ruleset (ADR-0038) and the `main` ruleset, and the Gitea
      protected tag and branch;
   4. merge;
   5. confirm via `gh api` that exactly `dev` and `release` exist, both with custom
      policies;
   6. add secrets only when publishing should go live, `dev` first.

   Each step's verification command is in `docs/ci/pipeline-walkthrough.md`
   §"Forge settings the maintainer applies". Between steps 4 and 6 every GitHub
   destination is off and runs succeed as no-ops (AD-9), so merging is decoupled from
   going live.
3. **The zizmor rule.** The pre-commit `zizmor` hook runs with `args: [--persona=auditor]`
   and no severity floor. A job in any file under `.github/workflows/` that reads
   `secrets.*` without `environment:` fails `just check` (`secrets-outside-env`); a job
   without `name:` fails it too (`anonymous-definition`). Every job carries `name:` equal
   to its id, so check names (`build / build`) are unchanged. A future false positive is
   suppressed per line with `# zizmor: ignore[<audit>]` citing an AD/ADR (ADR-0036 §4),
   never by a severity floor or a persona change.
4. **Branch protection on `main` is required** (maintainer decision (a), AG-20; approvals
   and the required check added in fix iteration 1). `dev` holds the GHCR, Docker Hub and
   Gitea registry tokens that `release` also uses, and ADR-0038's ancestry check trusts
   `main`. GitHub: a branch ruleset on the default branch with Restrict deletions, Block
   force pushes, Require a pull request before merging (`required_approving_review_count`
   1, `dismiss_stale_reviews_on_push` and `require_last_push_approval` true) and Require
   status checks to pass (`required_status_checks` with the context `build / build`);
   bypass list the Repository admin role only, so the maintainer can merge their own pull
   request. Gitea: `main` protected with push and force push disabled or allowed to the
   maintainer only (a protected branch cannot be deleted by push), a merge allowlist of the
   maintainer only, required approvals 1 or more with stale approvals dismissed, and
   status checks enabled for the `build` job's pull-request context. The required check is
   what makes `secrets-outside-env` (Decision 3) block a merge rather than only fail a
   run. A direct push or unapproved merge by the maintainer, as bypass actor, still runs
   `dev`; that is accepted. This removes "Branch protection" from the spine's Deferred
   list; the required check named in the Conventions table is configured here.
5. **AD-6 carve-out.** A forge-enforced key that another runner ignores (`environment:`)
   is allowed: it adds protection on the forge that honours it and changes nothing
   elsewhere. It is not behaviour branching. No forge condition, `env.ACT` or forge-specific
   YAML is added.
6. **Gitea: residual risk recorded, not branched on.** Any workflow on any branch pushed by
   a write-holder receives every secret stored in Gitea; the `main` and `v*` protections
   (merge allowlist and required approval on `main`) stop code the maintainer has not
   merged from being *published*, not that theft. Containment:
   - store only Gitea-destination secrets in Gitea (`PUBLISH_GITEA_TOKEN`, a Gitea
     `PUBLISH_RELEASE_TOKEN`, `PUBLISH_CA_CERTIFICATE` if needed), never PyPI, TestPyPI,
     GHCR or Docker Hub tokens;
   - issue the package token from a namespace that owns only this project's packages (a
     dedicated bot user or organisation); the maintainer's personal token exposes all of
     the maintainer's packages;
   - for releases, use a bot collaborator with write on this repository only;
   - keep write collaborators minimal.

   Moving the package namespace is a maintainer choice; `docs/ci/gitea-runners.md` states
   the containment each choice gives.

## Consequences

- On GitHub, a branch workflow naming `dev` or `release` is refused by the policy; one
  naming an invented environment gets an empty auto-created environment, which step 5
  lists. A typo in a workflow's `environment:` silently disables that job's destinations.
- Each environment job creates a deployment record (ref and run): an audit trail of which
  refs received publish credentials.
- Shared tokens live in both environments; rotating one means updating both, and the
  Gitea store (`docs/operational.md`).
- Re-runs still qualify: the policy matches the run's `GITHUB_REF` (ADR-0036 §5
  unchanged).
- Gitea and act runs behave as before.
- **Residual: the forge settings are not checked from the repository.** Reading them needs
  forge-specific API calls, which AD-9 forbids. `just check` enforces only that every
  secret-reading job declares an environment. The evidence for the settings is the
  maintainer's `gh api` / Gitea API output from the checklist, and
  `docs/ci/gitea-certification.md` lists the Gitea checks as live items.
- **Residual: approval is the boundary on GitHub, not a guarantee.** The `main` ruleset
  closes the route for a collaborator, a stolen write token or a write-capable agent acting
  alone: it cannot merge its own pull request, and a push after an approval needs a new
  one. It does not stop a bypass actor (the Repository admin role) from landing anything on
  `main`, two colluding write-holders (or one person with two accounts) from approving each
  other, or anyone who can approve from approving a pull request that prints the `dev`
  secrets, which include the registry tokens `release` also uses.
- **Residual: GitHub environment secrets are not isolated on self-hosted runners.** GitHub
  runs here use GitHub-hosted runners; Gitea runner trust is BL-E013-024.
- Not adopted: OIDC / trusted publishing (rejected for forge neutrality, ADR-0035).

## Revisit when

- Gitea gains environment-scoped secrets or honours `jobs.<id>.environment`; or
- either forge exposes environment, ruleset or branch-protection state to a workflow
  without a forge-specific API call, so it can be checked mechanically.

## Amendment 2026-10-11 — release may run fully from Gitea

Maintainer decision 2026-10-11 (option 2; last entry of the CI spine `.memlog.md`), recorded
by ADR-0046. It supersedes Decision 6's "store only Gitea-destination secrets in Gitea".

- **One forge per release.** All destinations of a release publish from one forge's run,
  all-GitHub or all-Gitea. Each destination's secrets live on that forge only (CI spine
  AD-9).
- **When Gitea is the publishing forge** it holds the PyPI, TestPyPI, GHCR and Docker Hub
  tokens as well as its own, as repository-level secrets, because Gitea ignores
  `environment:` (CI spine AD-13).
- **Required mitigations** (CI spine AD-13):
  - `main` and `v*` tags are protected, with push and tag creation limited to trusted
    accounts;
  - every token is scoped to this project only;
  - every token is rotated after any untrusted push.
- **Accepted residual risk.** A trusted account's branch workflow on Gitea can read the
  tokens. Nothing in Gitea prevents it.
- On GitHub nothing changes: `PUBLISH_*` secrets live in the `dev` or `release` environment
  and never at repository level.

### Consequences

- **Single-forge secrets rule.** The forge that does not run the release holds no
  `PUBLISH_*` secret or variable, so a mirrored tag run there is silent and publishes nothing
  (a variable left there alone sets an `ANY_*` intent flag and warns on every run). This is
  not mechanically enforced. The per-release checklist in `docs/ci/pipeline-walkthrough.md`
  compares secret names on both forges.
- A Gitea-run release concentrates every destination's token in one store that any branch
  workflow can read. The mitigations above narrow who can push such a workflow; they do not
  isolate the tokens from it.
