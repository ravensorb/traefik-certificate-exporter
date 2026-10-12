# Forge actions — E014-S02-004

Repository: `ravensorb/traefik-certificate-exporter` (GitHub). Checked 2026-10-12 against
`origin/main` = `9f9398c` and local `HEAD` = `6e230db` (7 commits ahead of `origin/main`, not
yet pushed).

**Maintainer confirmation:** Shawn Anderson (maintainer), 2026-10-11, recorded in
`_bmad-output/implementation-artifacts/epic-014/execution-notes.md` § "Maintainer approvals
recorded at execution start": "yes lets close the stale PRs (and any stale worktrees)".
Orchestrator constraint for this run: do not delete remote branches, so `--delete-branch` is
not used on #7 (deviation from the story's interface contract; see "Cleanup suggestions").

## PR state before closing (`gh pr view <n> --json number,title,headRefName,author,state,files`)

```json
{"author":"app/github-actions","files":["CHANGELOG.md","pyproject.toml"],"headRefName":"release-please--branches--main","number":7,"state":"OPEN","title":"chore(main): release 0.2.0"}
{"author":"app/dependabot","files":["poetry.lock","pyproject.toml"],"headRefName":"dependabot/pip/watchdog-6.0.0","number":8,"state":"OPEN","title":"chore(deps): bump watchdog from 2.3.1 to 6.0.0"}
{"author":"app/dependabot","files":["poetry.lock","pyproject.toml"],"headRefName":"dependabot/pip/docker-7.2.0","number":9,"state":"OPEN","title":"chore(deps): bump docker from 6.1.3 to 7.2.0"}
{"author":"app/dependabot","files":["poetry.lock","pyproject.toml"],"headRefName":"dependabot/pip/expandvars-1.1.2","number":10,"state":"OPEN","title":"chore(deps): bump expandvars from 0.12.0 to 1.1.2"}
{"author":"app/dependabot","files":["poetry.lock"],"headRefName":"dependabot/pip/requests-2.34.2","number":11,"state":"OPEN","title":"chore(deps): bump requests from 2.32.3 to 2.34.2"}
{"author":"app/dependabot","files":[".github/workflows/dev.yaml",".github/workflows/publish-image.yaml",".github/workflows/release.yaml"],"headRefName":"dependabot/github_actions/docker/login-action-4","number":14,"state":"OPEN","title":"chore(deps): bump docker/login-action from 3 to 4"}
{"author":"app/dependabot","files":[".github/workflows/publish-image.yaml"],"headRefName":"dependabot/github_actions/docker/setup-qemu-action-4","number":15,"state":"OPEN","title":"chore(deps): bump docker/setup-qemu-action from 3 to 4"}
{"author":"app/dependabot","files":[".github/workflows/release.yaml"],"headRefName":"dependabot/github_actions/actions/attest-build-provenance-4","number":16,"state":"OPEN","title":"chore(deps): bump actions/attest-build-provenance from 3 to 4"}
{"author":"app/dependabot","files":["poetry.lock"],"headRefName":"dependabot/pip/python-dotenv-1.2.4","number":17,"state":"OPEN","title":"chore(deps): bump python-dotenv from 1.0.1 to 1.2.4"}
```

Dependabot had **not** auto-closed any of #8–#11/#17: E014-S01-001 and E014-S01-007 are `done`
but their commit `6e230db` has not reached `origin/main` yet.

## Evidence per PR

| PR | Evidence | Superseded by | Decision |
|---|---|---|---|
| #7 | `release-please` workflows deleted in `94a38f1` (on `origin/main`); no `release-please*` file in `origin/main`; ADR-0035 decision 3: "Tags are the only version source … `just release <bump>` creates and pushes only a tag; no release commit." | ADR-0035, `94a38f1` | close |
| #14 | `publish-image.yaml` absent from `origin/main`; `dev.yaml`/`release.yaml` on `origin/main` already pin `docker/login-action@dbcb8138… # v4.6.0` | ADR-0035 pipeline, `fb75fc6` (on main) | close |
| #15 | `publish-image.yaml` absent; `dev.yaml`/`release.yaml` on `origin/main` already pin `docker/setup-qemu-action@99012661… # v4.4.0` | ADR-0035 pipeline, `fb75fc6` (on main) | close |
| #16 | no `attest-build-provenance` reference in `origin/main`, `HEAD` or the working tree; ADR-0035 consequences: "Build provenance attestations are not produced (GitHub-only)." | ADR-0035, `fb75fc6` (on main) | close |
| #8 | `pyproject.toml` `watchdog = "^6.0"`, `poetry.lock` watchdog 6.0.0 at `HEAD` | E014-S01-007, `6e230db` | close |
| #9 | `pyproject.toml` `docker = "^7.2"`, `poetry.lock` docker 7.2.0 at `HEAD` | E014-S01-001, `6e230db` | close |
| #10 | `expandvars` absent from `pyproject.toml` and `poetry.lock` at `HEAD` (unused, removed) | E014-S01-007, `6e230db` | close |
| #11 | `requests` no longer a direct dependency at `HEAD`; `poetry.lock` already resolves it (transitive) at 2.34.2 | E014-S01-007, `6e230db` | close |
| #17 | `pyproject.toml` `python-dotenv = "^1.2.2"`, `poetry.lock` python-dotenv 1.2.4 at `HEAD` | E014-S01-007, `6e230db` | close |

No PR was found whose update is not yet reflected in `HEAD`; none stays open.

## Close commands (executed after the confirmation above)

```sh
gh pr close 7  --comment "Closed as stale: release-please was retired. Its workflows were removed in 94a38f1, and ADR-0035 (docs/adr/0035-standard-ci-cd-pipeline.md) makes tags the only version source: releases are cut from a protected vX.Y.Z tag by release.yaml, with no release commit. 0.3.0 is released that way; see docs/ci/pipeline-walkthrough.md#releasing."
gh pr close 14 --comment "Closed as superseded: the CI/CD pipeline was rewritten under ADR-0035 (fb75fc6, already on main). publish-image.yaml no longer exists, and dev.yaml and release.yaml already pin docker/login-action to v4.6.0 by commit SHA; Dependabot keeps those pins current."
gh pr close 15 --comment "Closed as superseded: the CI/CD pipeline was rewritten under ADR-0035 (fb75fc6, already on main). publish-image.yaml no longer exists, and dev.yaml and release.yaml already pin docker/setup-qemu-action to v4.4.0 by commit SHA; Dependabot keeps those pins current."
gh pr close 16 --comment "Closed as stale: actions/attest-build-provenance is no longer used. release.yaml was rewritten under ADR-0035 (fb75fc6, already on main), which records that build provenance attestations are not produced."
gh pr close 8  --comment "Closed as superseded by E014-S01-007 (commit 6e230db, reaching main with the next push), which bumps watchdog to ^6.0 and locks 6.0.0 in poetry.lock."
gh pr close 9  --comment "Closed as superseded by E014-S01-001 (commit 6e230db, reaching main with the next push), which bumps docker to ^7.2 and locks 7.2.0 in poetry.lock."
gh pr close 10 --comment "Closed as superseded by E014-S01-007 (commit 6e230db, reaching main with the next push), which removes the unused expandvars dependency from pyproject.toml and poetry.lock."
gh pr close 11 --comment "Closed as superseded by E014-S01-007 (commit 6e230db, reaching main with the next push), which removes requests as a direct dependency; poetry.lock already resolves it transitively at 2.34.2."
gh pr close 17 --comment "Closed as superseded by E014-S01-007 (commit 6e230db, reaching main with the next push), which bumps python-dotenv to ^1.2.2 and locks 1.2.4 in poetry.lock."
```

## Cleanup suggestions (not executed)

- Remote branch `release-please--branches--main` (PR #7's head) is left in place: this run
  was told not to delete remote branches. Suggested maintainer action:
  `git push origin --delete release-please--branches--main`.
- Legacy git tags `v0.1`/`v0.2` stay; removing them needs a `release-tags` ruleset bypass
  (story non-goal).

## State after closing (2026-10-12)

All nine close commands exited 0. `gh pr view <n> --json number,state,closedAt` plus the closing comment URL:

| PR | State | Closed at | Closing comment |
|---|---|---|---|
| #7 | CLOSED | 2026-10-12T01:42:33Z | https://github.com/ravensorb/traefik-certificate-exporter/pull/7#issuecomment-6116257217 |
| #8 | CLOSED | 2026-10-12T01:42:40Z | https://github.com/ravensorb/traefik-certificate-exporter/pull/8#issuecomment-6116258717 |
| #9 | CLOSED | 2026-10-12T01:42:43Z | https://github.com/ravensorb/traefik-certificate-exporter/pull/9#issuecomment-6116259145 |
| #10 | CLOSED | 2026-10-12T01:42:45Z | https://github.com/ravensorb/traefik-certificate-exporter/pull/10#issuecomment-6116259402 |
| #11 | CLOSED | 2026-10-12T01:42:47Z | https://github.com/ravensorb/traefik-certificate-exporter/pull/11#issuecomment-6116259650 |
| #14 | CLOSED | 2026-10-12T01:42:34Z | https://github.com/ravensorb/traefik-certificate-exporter/pull/14#issuecomment-6116257945 |
| #15 | CLOSED | 2026-10-12T01:42:36Z | https://github.com/ravensorb/traefik-certificate-exporter/pull/15#issuecomment-6116258132 |
| #16 | CLOSED | 2026-10-12T01:42:38Z | https://github.com/ravensorb/traefik-certificate-exporter/pull/16#issuecomment-6116258391 |
| #17 | CLOSED | 2026-10-12T01:42:48Z | https://github.com/ravensorb/traefik-certificate-exporter/pull/17#issuecomment-6116259978 |

`gh pr list --state open --json number --jq '.[].number'` printed nothing (exit 0): no open PRs remain.

Remote heads after closing: only `release-please--branches--main` remains of the nine head branches (Dependabot deleted its own branches on close).

## Follow-up (review M-2, L-1)

- `origin/main` still carries the old dependency versions; the superseding commit `6e230db` is
  local. Push it at sprint closure. If it does not reach `main`, reopen #8, #9, #10, #11 and #17.
- The `release-please--branches--main` deletion is tracked as BL-E014-071.
