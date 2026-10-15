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
  alike). **Adopted** (`@v3`) in every publish job, directly after the version guard (ADR-0036 §1), gated on
  `PUBLISH_CA_CERTIFICATE` and feeding BuildKit its CA config (AD-18). It replaced the
  `if: ${{ env.ACT }}`-gated CA install of the legacy `build-container.yaml`.
- **[`git-action-docker-act-compatibility`](https://github.com/LiquidLogicLabs/git-action-docker-act-compatibility)**
  — resolves Docker build-context/Dockerfile-path differences between `act` and real GitHub
  Actions. Still a candidate: `just act` runs the workflows unmodified today (AD-6), so nothing
  needs it.
- **[`git-action-docker-metadata`](https://github.com/LiquidLogicLabs/git-action-docker-metadata)**
  — a drop-in fork of `docker/metadata-action` (identical inputs/tags/flavor semantics, same
  version numbering — **verified at `@v6` in [ADR-0012](adr/0012-image-metadata-action.md)**)
  with no GitHub API dependency, so it works identically across GitHub, Gitea, and local `act`.
  **Adopted** in the `publish-image` jobs of `dev.yaml` and `release.yaml`, which derive every
  image tag and label through it; which workflow writes which tag is AD-8.

Also **adopted** by ADR-0035 (versions in the spine's Stack table):
`git-action-release@v2` creates the forge release on GitHub or Gitea from one step
([ADR-0010](adr/0010-forge-release-mechanism.md), amended by ADR-0035 for its credential);
`git-action-release-changelog-builder@v3` generates its notes from the commit log (COMMIT
mode, categories in `.github/release-notes.json`), so there is no changelog file;
`git-action-tag-validate-version@v2` is `release.yaml`'s `validate-tag` (AD-12); and
`git-action-docker-test@v2` smoke-tests the image in `build.yaml` and after each push.
Every action is read at the tag being pinned before adoption, because Actions passes an
unknown input through in silence.

Still a candidate, adopted nowhere: `git-action-docker-cleanup` and
`git-action-docker-act-compatibility`. Adopting one is a separate decision.

## 7. One pipeline, three runners — no `ACT` env var dependency

The build must run, unmodified, under:
- **`nektos/act`** locally, via `just act [workflow]` (AD-16),
- **Gitea Actions** (act-compatible runner),
- **real GitHub Actions**.

A single GitHub Actions YAML is the source of truth for all three — do not maintain
separate pipeline definitions per runner (AD-6).

**Do not branch behavior on the `ACT` env var, under any circumstances.**

**Previously a known violation, now resolved.** The legacy `build-container.yaml` had a step
gated `if: ${{ env.ACT }}` that installed a custom CA certificate (`ca-ravenwolf.pfx.crt`) mounted
through `act`'s `--container-options`. That workflow was deleted in E007 and the violation went
with it.

**Enforced by a pre-commit hook.** The test that refused `ACT` in any workflow was retired with
the governed pipeline (ADR-0035, AD-4: no custom policy code), and neither actionlint nor
zizmor checks for it. The `workflows-no-act-env` pygrep hook in `.pre-commit-config.yaml` now
fails on any `ACT` token in `.github/workflows/*.y(a)ml` (configuration of a standard tool,
which AD-4 permits). It does not see `ACT` read inside a called action; `just act` running the
same YAML as both forges is the practical check for that.

The private-CA case this rule used to block is now handled runner-agnostically by
`git-action-ca-certificate-import` (AD-18), never by a conditional on which tool is executing.

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

## 10. Pre-commit hooks

[`.pre-commit-config.yaml`](../.pre-commit-config.yaml) is the one list of hooks (CI/CD spine
AD-3). This section does not copy it, because a copied table drifts from the file and then
describes hooks that do not run. `just check` and `build.yaml` both run
`pre-commit run --all-files`; its output, one line per hook with `Passed`, `Failed` or
`Skipped`, is the evidence of what runs and what it examined. Most hooks carry a comment in
`.pre-commit-config.yaml` stating what they guard; every `repo: local` pygrep guard's comment
also states what it does not match.

## 11. Defect provenance belongs in the comment, and this is a deliberate deviation

Core §6 says change history is git's job and that changelog-in-comments is a review finding. This
project deviates on purpose, and records it here so the next reviewer reads it as a choice rather
than an oversight.

Where a guard or a workflow step exists **because a specific defect got through**, the comment says
which one. `release.yaml` is roughly a third comments and much of that mass is provenance: "this was
a hand-kept 2-tuple that tier 1 had already replaced"; "the list had only the first, so an `env:`
block naming a secret was invisible to every guard here"; "a count is satisfied by any five files".

The reason is narrow and evidenced. Epic 8 found **eleven** instances of one defect class -- a
correct rule over a hand-enumerated set -- and several were introduced *while fixing earlier
instances of it*, by people and agents who had read the rule and agreed with it. Knowing that a line
is the fix for a specific escape is what stops the next reader simplifying it back. A commit message
does not travel with the line; a comment does.

The limits, so this does not become licence:

- **The invariant comes first.** Provenance is the second half of a comment whose first half says
  what the code guarantees. A comment that is *only* history is a review finding here too.
- **One defect, one place.** Where an ADR already records it, the comment names the ADR and stops.
- **It expires.** When a comment describes a shape the code no longer has, delete it. Several went
  at E008 closure for exactly that -- a reusable image workflow's "becomes the fifth workflow file
  once release.yaml lands", and a push-verification guard still calling itself vacuous two stories after
  it had stopped being.
