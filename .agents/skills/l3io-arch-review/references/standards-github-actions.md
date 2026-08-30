# Engineering Standards — GitHub Actions Overlay

Loaded on top of `standards-core.md` when the project uses GitHub Actions CI/CD.

## Prefer marketplace actions over custom scripting

**Rule.** Prefer a **well-maintained marketplace action** over hand-rolled shell in a
workflow. Custom scripting is a fallback for genuinely bespoke steps — and when written,
it lives in a version-controlled script file, not sprawling inline `run:` blocks.

- **Design/decision** — For a given need (checkout, setup-language, cache, upload artifact,
  login to registry, deploy), **search the marketplace first** and use the established
  official/verified action. Reserve `run:` for glue and project-specific logic.
- **When custom is justified** — factor it into a script in the repo (testable, reusable —
  core §2/§4), or promote a repeated pattern to a **composite/reusable workflow** rather
  than copy-pasting across jobs (core §2, reuse over copy-paste).

## Pin actions to a major version, and use the latest

**Rule.** Reference actions by their **latest major version tag** (e.g. `@v4`), and keep
them current. Pin to **major only** where the publisher is trusted/verified so patches and
minors flow in automatically.

- **How to pin** —
  - Trusted/official actions → pin to **major** tag (`actions/checkout@v4`) to auto-receive
    fixes; bump the major deliberately when a new one ships.
  - Third-party/less-trusted actions → prefer pinning to a **full commit SHA** for supply-chain
    safety (defense-in-depth; core §7). Record the reason.
  - Enable Dependabot for `github-actions` so major bumps surface as PRs.
- **Grab the latest** — at authoring/review time, check the marketplace for the newest major
  of each action; don't ship stale majors.
- **Review** — Flag: floating `@main`/`@master` refs, unpinned actions, stale majors,
  inline shell that duplicates an available marketplace action, and repeated job logic that
  should be a composite/reusable workflow.

## Workflow hygiene (aligns with core)

- Least-privilege `permissions:` per workflow/job (deny by default, grant what's needed).
- Secrets via GitHub Secrets/OIDC — never inline; never echoed to logs (core §9).
- Concurrency groups to cancel superseded runs; matrix builds for multi-target.
- Structured, correlated logs where the pipeline drives deploys (tie run ID into app traces).

## Review checklist (GitHub Actions-specific)

- [ ] Marketplace actions used over custom shell where one exists; latest major.
- [ ] Actions pinned to major (trusted) or SHA (third-party); no `@main` floating refs.
- [ ] Dependabot enabled for `github-actions`.
- [ ] Least-privilege `permissions`; secrets via Secrets/OIDC, never logged.
- [ ] Repeated logic factored into composite/reusable workflows (no copy-paste jobs).
