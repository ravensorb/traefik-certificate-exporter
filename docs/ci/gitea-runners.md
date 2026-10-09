# Gitea runners and private-CA trust

How to run this project's pipeline ([ADR-0035](../adr/0035-standard-ci-cd-pipeline.md),
[pipeline-walkthrough.md](pipeline-walkthrough.md)) on a self-hosted Gitea. The binding rules
are the spine's AD-6 (same YAML on GitHub, Gitea and `act`) and AD-18 (private CA).

This page replaces the runner-trust, credential-matrix and action-governance runbook of the
pipeline ADR-0035 retired. The per-job credential matrix (ADR-0019), the action-governance
registry (ADR-0022) and trust-class runner routing (ADR-0015) are superseded: every credential
is now a `PUBLISH_*` secret that switches its destination on (AD-9), and action pinning is
checked by zizmor (AD-5).

## Runner requirements

- **Gitea 1.27 or newer**, the first release with reusable workflows (`workflow_call`);
  `concurrency` needs 1.26.
- **An `act_runner` that maps the `ubuntu-latest` label** to a runner image with `bash`,
  `git`, `python3` and Docker (for the image build and smoke test). The workflows use
  `runs-on: ubuntu-latest` everywhere and nothing else, so one label is enough (AD-6).
- **No `env.ACT` or forge-specific branch exists in any workflow** (AD-6). If something
  works on GitHub and not on Gitea, the fix is runner configuration or an action that works
  on both, never a conditional.
- Live verification of the workflows on a real Gitea runner is the spine's Deferred
  "Live certification on Gitea 1.27" item (E013-S01-004).

## Trust ordering for a private CA

Runner-host bootstrap trust (the OS CA store the runner image starts with) covers `git` and
OS tooling. It does not reach Node.js actions, which bundle their own root list, Python's
`requests`/`certifi` (used by `twine`), or BuildKit, which runs in its own container. A Gitea
served by a private CA therefore needs the CA imported again inside each job that talks to it.

```text
 runner provisioning      bootstrap trust (OS store)   -- outside any workflow
 job start
   Version guard          dev.yaml only: refuses a non-.dev version (AD-15)
   ca-certificate-import  if PUBLISH_CA                -- first step that touches a secret
   ... checkout, download-artifact, setup ...
   twine upload           REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt
   setup-buildx           config: <buildkit-path output of the CA import>
   build-push             BuildKit trusts the CA for registry pushes
```

- Set the `PUBLISH_CA_CERTIFICATE` secret to the PEM certificate. With it unset, the import
  step and its effects are skipped and nothing else changes (AD-9).
- `LiquidLogicLabs/git-action-ca-certificate-import@v3` updates the system store and, with
  `generate-buildkit: true`, writes a BuildKit config that `docker/setup-buildx-action`
  receives as `config` (AD-18).
- `twine` steps point `REQUESTS_CA_BUNDLE` at the system store the action updated, so Python
  trusts the imported CA. That is harmless when no CA was imported.
- `build.yaml` holds no credential and publishes nothing, so it needs no CA import.

## Secrets and variables on Gitea

Gitea refuses secret and variable names that start with `GITEA_` or `GITHUB_`, and fills in
its own `GITEA_TOKEN`; that is why every pipeline secret is `PUBLISH_*`. Set them in the
repository's (or organisation's) Actions secrets and variables. The full list, with the
shape of each variable, is in [pipeline-walkthrough.md](pipeline-walkthrough.md#where-things-are-published).
`PUBLISH_RELEASE_TOKEN` on Gitea is a Gitea token; on GitHub it is a GitHub token. Each
forge's secret store is separate, so a rotation is done on each forge (AD-9).

### Residual risk: no environments on Gitea (ADR-0039)

Gitea ignores `jobs.<id>.environment` (gitea/docs `docs/usage/actions/comparison.md`,
"Unsupported workflows syntax") and keeps secrets only at user, organisation and repository
level. So on Gitea, any workflow on any branch pushed by anyone with write access receives
every secret stored in Gitea. The protected `main` and `v*` (below, and
[Tag protection](pipeline-walkthrough.md#tag-protection)), with the merge allowlist and
required approval on `main`, stop code the maintainer has not merged from being
**published** through `dev.yaml` or `release.yaml`; they do not stop that secret theft.
The workflows do not branch on the forge to compensate (AD-6, AD-9). This is recorded,
not fixed; revisit when Gitea gains environment-scoped secrets or `environment:` support.

What actually contains it:

1. **Store only Gitea-destination secrets in Gitea:** `PUBLISH_GITEA_TOKEN`, a Gitea
   `PUBLISH_RELEASE_TOKEN`, and `PUBLISH_CA_CERTIFICATE` if the private CA is needed. Never
   store PyPI, TestPyPI, GHCR or Docker Hub tokens in Gitea.
2. **Issue the package token from a namespace that owns only this project's packages.**
   Gitea packages belong to a user or an organisation, not to a repository, and no token
   setting confines a token to one package (v1.27.3 `services/context/package.go`
   `determineAccessMode`): a user's token writes every package that user owns, and an
   organisation team with the Packages unit on write writes every package of that
   organisation. A token from the maintainer's own account therefore exposes all of the
   maintainer's packages. Tight containment needs a dedicated bot user, or an organisation
   that owns only this project's packages, to own them. Moving the packages is the
   maintainer's choice.
3. **For releases, use a bot collaborator with write on this repository only**, so its
   `write:repository` token reaches only this repository.
4. **Keep write collaborators to a minimum**: each one can read every Gitea secret.

### Protected `main` on Gitea

A protected `main` is a required setting (ADR-0039): push disabled or allowed to the
maintainer only, force push disabled or allowed to the maintainer only, a merge allowlist
of the maintainer only, required approvals 1 or more with stale approvals dismissed, and
status checks enabled for the `build` job's pull-request context; a protected branch
cannot be deleted by push. Gitea has no separate "require a pull request" switch;
restricting push makes a merged pull request the only way for anyone else to change
`main`, and the merge allowlist makes the maintainer the only one who can merge it. The
required status check is what makes zizmor's `secrets-outside-env` failure block a merge.
The maintainer, as repository admin, can still merge without an approval; that is
accepted. Steps and the verification call are in
[Branch protection on main](pipeline-walkthrough.md#branch-protection-on-main).
