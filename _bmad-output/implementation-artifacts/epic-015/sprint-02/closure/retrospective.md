# E015 sprint 02 — retrospective

Inline in the closure agent (`bmad-retrospective` is epic-scoped). Date: 2026-10-14.

## What was delivered

| Story | Status | Fix iterations | Notes |
|---|---|---|---|
| E015-S02-001 setup-buildx `buildkitd-config` + guard | done | 0 | Live act probe proved `buildx create --config` with a private-CA registry. `tests_passing` is false only because superseded commands keep an old exit 1 as their last run. |
| E015-S02-002 one build per release; GHCR and forge-release tokens | done | 2 | Blocked 2.4 h on maintainer forge actions, then re-scoped by MD-26. `tests_passing` is false only because retired row 9 (the 0.3.0 `onedigest` check) has a recorded exit 1, and the tracker cannot retire a command. Its live rows pass. |
| E015-S02-003 hook dependencies from `poetry.lock` | done | 1 | mypy and import-linter run `language: system` through `poetry run`; `precommit-hook-deps-locked` guards this. It closed BL-E015-053 (mypy saw `confuse` as `Any`). |
| E015-S02-005 `settings.loaddotenv`, off in the image | done | 0 | A third trust class (`environment-only-in-every-mode`), one image `ENV` line, and no LinuxServer change. |
| E015-S02-004 release 0.3.1 | ready-for-dev (carried over) | — | Run by the maintainer, as E014-S02-007 was. |

Velocity: 4 stories done of 5 planned. Carry-over: 1 (S02-004).

## What went well

- **Guards came with the fixes.** S02-001 and S02-003 each added a pygrep guard for the defect class they fixed, with the coverage limit stated where the rule lives. S02-003's anti-false-green probes (planted type error, planted layering violation, planted `confuse` misuse) proved the new hooks fail when they should.
- **S02-005 was re-probed on the real image** before the design was fixed. The probe found that the s6 service's cwd is not `/config`, and that corrected three documents that had said otherwise.

## What did not

- **S02-002 was over-designed and stalled on forge actions.** The first design (classic PAT, fine-grained release token, one-forge check, digest equality, token-expiry table, 0.3.0 retag and backfill) needed several maintainer steps on two forges. The story sat blocked for 2.4 h until the maintainer cut it back to their stated goals (MD-26). Two review rounds and two fix iterations were spent on machinery that was then dropped.
- **The simplification introduced a forge-specific bug.** The `github.token` fallback for GHCR was not limited to github.com, so on Gitea it enabled GHCR with a token that cannot push there. Closure caught it (AR-1 / SD-02-1) and fixed it. No act or live run exercised a Gitea configuration with only `PUBLISH_GHCR_IMAGE` set.
- **The tracker cannot retire a verification command.** When a story is re-scoped, its retired or superseded rows keep `tests_passing` false forever (S02-001, S02-002).

## Action items

1. Before accepting a release-pipeline design, check its maintainer-action count against the maintainer's stated goals; prefer the forge's own token where it works (MD-26 lesson).
2. When a workflow expression falls back to `github.token`, state and test which forge that token belongs to (`github.server_url`). AR-1 would have been caught by one act run with Gitea-like `GITHUB_SERVER_URL`.
3. Ask the l3io maintainers for a way to retire a recorded test command (or mark it superseded) so `tests_passing` reflects live rows only.
4. E015-S02-004: the GHCR first push with the job token is the 0.3.1 release run; its checklist already covers the "Manage Actions access" 403 case.

## Summary (for the sprint node)

Four of five stories done: the buildx input fix with its guard, hook dependencies locked and audited, `.env` loading off in the image, and the release publishing design simplified to forge tokens by maintainer decision MD-26. S02-002 was blocked 2.4 h on an over-built credential design until MD-26 replaced it. Closure fixed one Medium expression bug in that design (GHCR fallback on Gitea). The 0.3.1 release (S02-004) carries over to the maintainer.
