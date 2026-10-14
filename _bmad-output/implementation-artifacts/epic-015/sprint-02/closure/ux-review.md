# E015 sprint 02 — UX review

- **Method:** `bmad-ux` Reviewer Gate (operator-experience lens), run inline in the closure agent because this runtime has no subagent tool.
- **Stories:** E015-S02-002 (operator docs for publishing: walkthrough, `docs/upgrading.md`, ADR-0052) and E015-S02-005 (the `--no-dotenv` flag, the "Not reading .env" WARNING, the every-mode ERROR, `docker/README.md`, and the 0.3.1 upgrade notes).
- **Surfaces read:** `src/traefik_certificate_exporter/libs/settings.py` message templates (`_EVERY_MODE_WITHHELD_MESSAGE`, `_UNREAD_DOTENV_MESSAGE`); `cli_args.py` `--no-dotenv` help; the `docker/README.md` and `docs/upgrading.md` 0.3.0 → 0.3.1 sections; walkthrough "GHCR and the forge release use the forge's own token"; the classify-step GHCR hint.

## Findings

| ID | Story | Severity | Finding | Disposition |
|---|---|---|---|---|
| UX-1 | S02-005 | LOW | **The "Not reading .env" WARNING repeats on every start for an operator who is already set up correctly.** It fires whenever `/config/.env` exists, whether or not its contents are delivered another way. One natural setup keeps the file in the host directory mounted at `/config` and points Compose `env_file:` at it. That operator gets a WARNING on every restart and is never told that removing or renaming the file is the way to clear it. Neither the message, `docker/README.md` nor `docs/upgrading.md` says how to silence it. | Deferred, Low |
| UX-2 | S02-005 | LOW | **The `--no-dotenv` help ends with "The container image sets this."** The image sets the environment variable (`…_LOADDOTENV=false`), not the flag. A reader checking `ps` output or a Compose `command:` will not find the flag. | Deferred, Low |

No HIGH or MEDIUM findings.

### Checked and fine

- **S02-002, GHCR hint:** the classify step's GHCR warning names the missing input and adds "On GitHub the job's own token pushes to ghcr.io, so secrets.PUBLISH_GHCR_TOKEN is needed only on act or Gitea." With the AR-1 fix, that hint is exactly when the warning appears on Gitea.
- **S02-002, walkthrough:** it states which tokens are optional and why, and S02-004's checklist covers the GHCR 403 case ("Manage Actions access", then the classic-token fallback).
- **S02-005, every-mode ERROR:** it names the source file, the environment variable, the actual flag and the value in effect. This is better than S01's root ERROR (BL-E015-040/041).
- **S02-005, upgrade notes:** the container, CLI and CLI-as-root cases are separate bullets, each with its action.
