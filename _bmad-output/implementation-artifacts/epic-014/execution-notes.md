# E014 execution notes — environment facts every story agent needs

Read this before running anything. These are verified behaviours of this workstation and
repository as of 2026-10-11; they are not design decisions (those live in the PRD and the two
spines). If something here turns out wrong, record it in your story's notes file and keep going.

## Authorities

- Requirements: `_bmad-output/planning-artifacts/prds/prd-traefik-certificate-exporter-2026-08-30/prd.md` (FR-1..17, NFR-1..7, Target 0.3.0)
- Product architecture: `_bmad-output/planning-artifacts/architecture/architecture-traefik-certificate-exporter-2026-08-30/ARCHITECTURE-SPINE.md` (AD-1..13)
- CI/CD architecture: `_bmad-output/planning-artifacts/architecture/architecture-ci-cd-pipeline-2026-10-08/ARCHITECTURE-SPINE.md` (AD-1..18)
- Verified library/platform facts: `_bmad-output/planning-artifacts/research/research-2026-10-10-release-0.3.0.md`
- Both spines describe the **target** 0.3.0 state; code catching up to them is the point of E014.

## Toolchain on this host

| Tool | Version | Notes |
|---|---|---|
| Python | 3.11.11 (pyenv) | project supports 3.10–3.14 |
| Poetry | 2.4.2 | see "Poetry plugin" below |
| act | 0.2.89 | see "act" below |
| Docker Engine | 29.9.0 | socket `/var/run/docker.sock` is available; integration tests can use it |
| just | installed | recipes: install, check, build, image, act, release |

## Poetry plugin (poetry-dynamic-versioning)

- The global Poetry's plugin resolution can fail because of an unrelated user-environment
  conflict (`docker-apps-cfgmgr` pins `ruamel.yaml ^0.18.14`). If `poetry install` fails while
  resolving plugins, run `uvx --from poetry==2.4.2 poetry install` once; after that the global
  `poetry` works.
- Strict versioning needs tags: any Poetry command other than `run`/`shell` fails when no
  `vX.Y.Z` tag is reachable. In throwaway clones use full history (`git clone` without
  `--depth`).

## Verification commands

- The gate: `just check` (all pre-commit hooks + pytest). It must pass at the end of every story.
- Targeted tests: `poetry run pytest -q <path>::<test>`; record node ids you ran.
- Integration tests (real Docker / built image): marker `integration`, opt-in with
  `TCE_DOCKER_INTEGRATION=1`; image under test from `TCE_IMAGE`
  (default `traefik-certificate-exporter:local`, built by `just image`).
  Example: `just image && TCE_DOCKER_INTEGRATION=1 poetry run pytest -q -m integration`.
- Pre-commit on specific files: `poetry run pre-commit run --files <files>`.

## act (local workflow runs)

- `~/.actrc` prompts for Infisical-backed secrets. Bypass it with a temporary HOME and pass the
  runner image explicitly:
  `HOME=$(mktemp -d) act <event> -W .github/workflows/<file> -P ubuntu-latest=ghcr.io/catthehacker/ubuntu:act-latest --pull=false --defaultbranch main --artifact-server-path "$(mktemp -d)"`
- `just act <workflow>` wraps the same flags but still reads `~/.actrc`; prefer the explicit form
  for unattended runs.
- Run act in a **throwaway clone** under `/tmp` when the test needs tags, branches or commits;
  never create tags/branches in the real repository.
- Artifact actions are pinned to upload v5.0.0 / download v6.0.0 because act 0.2.89 rejects
  newer ones; do not change them.
- `docker/build-push-action` steps set `DOCKER_BUILD_RECORD_UPLOAD: "false"` for the same reason.
- No secrets ⇒ every destination is skipped (silent when unconfigured); that is the expected
  no-secret result.

## Network

- `pip-audit`, PyPI/OSV lookups and image pulls need network access. ghcr.io may rate-limit
  anonymous pulls (HTTP 429); retry, do not log in.

## Repository rules for agents

- Do not commit, push, tag, or change forge settings; commits happen at sprint closure.
- `uv.lock` is an untracked stray file; leave it alone.
- ADR numbers: reserve with
  `uv run -q _bmad/scripts/pm-status.py adr-reserve --state-root _bmad-output/implementation-artifacts/state --epic E014 --slug <slug> --count 1 --adr-dir docs/adr`; never pick one by listing the directory.
- Spine/ADR text changes are routed through your story's notes file
  (`closure/notes-<story>.md`, section "Spine/ADR amendments for S02-003"); do not edit the
  spines from a code story.
- Each story's `## Verification` section is the definition of done: run every command listed,
  record the output (or its tail) in the notes file, and record every run with
  `pm-status add-test-run`.

## Maintainer approvals recorded at execution start (2026-10-11)

- E014-S02-004: the maintainer approved closing the stale PRs and removing stale git
  worktrees ("yes lets close the stale PRs (and any stale worktrees)"). Close each PR with a
  comment citing the reason, and record each closure in the notes file. `git worktree list`
  showed only the main checkout at execution start.
- Network access is available for `pip-audit`, PyPI/OSV lookups and image pulls.
