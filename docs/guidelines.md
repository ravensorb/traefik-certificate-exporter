# Engineering Guidelines — traefik-certificate-exporter

Project-specific conventions layered on top of the generic `l3io-arch-review` standards
(`standards-core.md` + `standards-python.md` + `standards-github-actions.md` +
`standards-docker.md`). These govern how the [PRD backlog](../_bmad-output/planning-artifacts/prds/prd-traefik-certificate-exporter-2026-08-30/prd.md#6-fix--upgrade--enhancement-backlog)
gets implemented. Where a guideline here and a recorded [ADR](adr/) already overlap, this
file is the more specific, current statement — update the ADR to match if they ever diverge.

## 1. Python best practices

Standard, boring, idiomatic Python: type hints as contracts, `src/` layout (already in
place), `pyproject.toml` as the single manifest, no bare `except:`. `ruff` (lint + format,
via `astral-sh/ruff-pre-commit`) is now wired into `.pre-commit-config.yaml` in place of the
disabled `black`/`isort` hooks — see §10. `mypy`/`pyright` type checking is not yet wired;
add it once the codebase has been brought to a ruff-clean baseline (running the new hook for
the first time will surface a backlog of existing violations to triage).

## 2. Package management — Poetry or uv

Either is acceptable; this project already uses **Poetry** with a committed `poetry.lock`
(see [ADR-0001](adr/0001-python-dependency-management-poetry.md)) — keep it unless a
concrete reason to migrate to `uv` emerges. Whichever tool is in force, it is the **only**
source of the dependency list — no hand-maintained parallel list anywhere else in the repo
(this is what broke in the Dockerfile; see [ADR-0004](adr/0004-dependency-build-artifact-parity.md)).

## 3. Logging

Must be:
- **Clean** — structured (JSON) at rest for anything written to a file/log sink; human-readable
  is fine for interactive console output.
- **Toggle-able** — enabling/disabling verbosity must not require a code change (already
  true via `-ll/--log-level`; keep it that way as logging is reworked).
- **Level-aware everywhere** — a level change must affect every handler consistently; don't
  hardcode a handler's level independent of the requested level (current `logging.yaml`
  hardcodes `standard_console_handler`/`extended_console_handler` levels — revisit when
  implementing [ADR-0003](adr/0003-logging-stack-and-secret-redaction.md)).
- **Never leak secrets** — non-negotiable at any level, including DEBUG (closes
  [review finding #5](../_bmad-output/implementation-artifacts/review-report.md), BLOCKER).

## 4. Dual packaging — PyPI package AND Docker

Both distribution paths must work from the **same** dependency source (Poetry/`poetry.lock`)
and stay behaviorally identical. No dependency, default, or behavior may exist in one
packaging path but not the other. This directly governs the fix for
[review finding #8](../_bmad-output/implementation-artifacts/review-report.md) (Docker image
dependency drift) — closing it must not just re-sync the two lists once, but structurally
prevent them from diverging again (build the image from the locked set, not a parallel list).

## 5. Configuration — config file + CLI + env vars

All three input modes are first-class and must apply the **same validation rules**
consistently. The existing precedence (CLI > env vars > config file > packaged default via
`confuse`) stays — env vars outrank the config file deliberately, since this is a Docker-first
tool where env vars are the standard vehicle for per-deployment overrides of a static/mounted
config file. Any constraint enforced for one input mode (e.g. the CLI's
`argparse` mutually-exclusive include/exclude domains) must be enforced for the other two —
closing the gap tracked as [PRD backlog item #6](../_bmad-output/planning-artifacts/prds/prd-traefik-certificate-exporter-2026-08-30/prd.md#6-fix--upgrade--enhancement-backlog)
(env-var/config-file domain include/exclude).

## 6. CI/CD — GitHub Actions, prefer marketplace actions over scripts

Prefer well-maintained marketplace actions over hand-rolled `run:` shell, per the
[GitHub Actions overlay](../.agents/skills/l3io-arch-review/references/standards-github-actions.md) —
this is what governs [review findings #4 and #13](../_bmad-output/implementation-artifacts/review-report.md).

**Vendor preference — resolved.** Confirmed org: [`LiquidLogicLabs`](https://github.com/LiquidLogicLabs)
(checked 2026-08-30 via GitHub search — the earlier "liquidlogicapps"/"liquidlogiclabs" search
had simply used the wrong handle). **Maintainer-owned**, confirmed with the maintainer at Epic 8
sprint closure. The earlier wording recorded only that the org exists, which is identification
rather than ownership; a red-team review read it that way and treated the org's actions as
ordinary third-party supply chain. Ownership is what makes ADR-0010's "first-party in practice"
accurate and what ADR-0009's accepted-risk entries rest on, so it is stated rather than implied. It publishes a suite of `git-action-*` GitHub Actions that
are **multi-platform (GitHub + Gitea)** by design — a direct fit for this project's
[§7 one-pipeline-three-runners rule](#7-one-pipeline-three-runners--no-act-env-var-dependency).
Prefer a `LiquidLogicLabs` action over an official/community one where one exists and covers
the need; otherwise fall back to the general rule (official/verified marketplace action, no
vendor preference). Several are directly applicable to open findings in this repo:

- **[`git-action-ca-certificate-import`](https://github.com/LiquidLogicLabs/git-action-ca-certificate-import)**
  — installs custom CA certificates into the runner unconditionally (GitHub, Gitea, or `act`
  alike). This is the runner-agnostic replacement for the `if: ${{ env.ACT }}`-gated CA install
  in [build-container.yaml](../.github/workflows/build-container.yaml) — see §7's known violation
  and PRD backlog item #11.
- **[`git-action-docker-act-compatibility`](https://github.com/LiquidLogicLabs/git-action-docker-act-compatibility)**
  — resolves Docker build-context/Dockerfile-path differences between `act` and real GitHub
  Actions; relevant given [docker/act-build.sh](../docker/act-build.sh) already exists for local
  `act` testing.
- **[`git-action-docker-metadata`](https://github.com/LiquidLogicLabs/git-action-docker-metadata)**
  — a drop-in fork of `docker/metadata-action` (identical inputs/tags/flavor semantics, same
  version numbering) with no GitHub API dependency, so it works identically across GitHub,
  Gitea, and local `act`. Adopted in [build-container.yaml](../.github/workflows/build-container.yaml)'s
  `Docker meta` steps for semver/major/minor/sha/beta/latest image tagging.

`git-action-release@v2` is **selected**, not a candidate: it creates Releases on GitHub and on
self-hosted Gitea from one step, resolving the instance from `GITHUB_SERVER_URL` (ADR-0010). It
lands with `release.yaml` in Epic 8 — that workflow does not currently exist, having been deleted
along with the rest of the legacy publish path in `9e43b90`, and `release-please` was retired by
ADR-0006 rather than merely disabled.

Other `LiquidLogicLabs` actions (`git-action-release-changelog-builder`,
`git-action-tag-validate-version`, `git-action-tag-floating-version`, `git-action-docker-test`,
`git-action-docker-cleanup`) remain candidates for the same workflow precisely because they
are multi-platform — but
adopting them is a separate implementation decision, not bundled into this vendor-preference fix.

## 7. One pipeline, three runners — no `ACT` env var dependency

The build must run, unmodified, under:
- **`nektos/act`** locally (already used via [docker/act-build.sh](../docker/act-build.sh)),
- **Gitea Actions** (act-compatible runner),
- **real GitHub Actions**.

A single GitHub Actions YAML is the source of truth for all three — do not maintain
separate pipeline definitions per runner.

**Do not branch behavior on the `ACT` env var, under any circumstances.**

**Known current violation** (not yet fixed, tracked here so it isn't lost): [build-container.yaml](../.github/workflows/build-container.yaml)
has a step gated `if: ${{ env.ACT }}` that installs a custom CA certificate
(`ca-ravenwolf.pfx.crt`) mounted via `act`'s `--container-options`. This directly violates
this guideline and must be replaced with a runner-agnostic mechanism — e.g. a custom runner
image with the CA baked in, or installing trusted CAs unconditionally from a repo-committed
source available to every runner (GitHub, Gitea, and `act`), not a conditional on which tool
is executing the workflow. Added as a new backlog item below.

## 8. Always validate decisions against latest docs

Before committing to a specific library, action, or version in any of the above (logging
library, a marketplace action, a lint tool), check current upstream documentation/marketplace
listings rather than relying on prior knowledge — tooling and best practices in this space
move fast enough that "what was true when this was last touched" is not a safe assumption.
Record what was checked and when in the relevant ADR.

## 9. Public open-source repo hygiene

This is a **public** repository — treat GitHub-facing surfaces as product, not scratch space.

- **No secrets committed, ever.** `.gitignore` already excludes `.env`, `.pipeline*`, `data`,
  `*.log` — keep that current as new local-only artifacts appear. Add a secret-scanning
  pre-commit hook (e.g. `gitleaks`) rather than relying on discipline alone; GitHub's own
  push-protection/secret-scanning should also be enabled on the repo.
- **Standard community files** — this repo currently has `LICENSE` and `README.md` but no
  `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `SECURITY.md`, issue templates, or a PR template.
  For a project that handles private keys and passphrases, `SECURITY.md` (how to privately
  report a vulnerability) matters more than usual — do not let cert/key-handling bugs get
  reported in a public issue.
- **Issues and PRs** — use issue templates (bug report / feature request) and a PR template
  so external contributors know what information is expected; keep discussion respectful and
  actionable (this is a process/culture note as much as a file).
- **Dependabot** — enable it for both `github-actions` (already noted in §6/[review finding #13](../_bmad-output/implementation-artifacts/review-report.md))
  and the Python ecosystem, so dependency CVEs surface as PRs automatically.
- **Commit hygiene** — no debug prints of real domains/paths/credentials in example commits
  or fixtures added for tests (backlog item #5); sample data must be synthetic.

## 10. Pre-commit hooks (wired in `.pre-commit-config.yaml`)

Validated against each tool's current release as of this writing (§8 in practice):

| Hook | Source | Guards |
|---|---|---|
| `check-toml`, `check-yaml`, `end-of-file-fixer`, `trailing-whitespace`, `mixed-line-ending`, `detect-private-key` | `pre-commit/pre-commit-hooks` v6.0.0 | Basic file hygiene; `detect-private-key` is a direct backstop for §9 given this tool's domain |
| `poetry-lock` (local) | repo-local | §2 lockfile-in-sync check — previously mis-declared under `pre-commit/pre-commit-hooks` (that repo doesn't ship this hook id, so it would never resolve); moved to a `repo: local` block |
| `ruff-check` / `ruff-format` | `astral-sh/ruff-pre-commit` v0.16.5 | §1 lint/format, replacing the disabled `black`/`isort` hooks |
| `gitleaks` | `gitleaks/gitleaks` v8.30.1 | §9 secret scanning |
| `actionlint` | `rhysd/actionlint` v1.7.12 | §7 GitHub Actions workflow validation — this class of tool would have caught the broken `build.yaml` wiring ([review finding #4](../_bmad-output/implementation-artifacts/review-report.md)) before it was committed |

Not yet added: a `mypy`/`pyright` hook (needs a ruff-clean baseline first, per §1).
