# ADR-0014: Notifications on `post-export`, delivered by Apprise

- **Status:** Proposed
- **Date:** 2026-09-06
- **Deciders:** Maintainer (ravensorb)
- **Supersedes:** ADR-0013, withdrawn before implementation after an architecture gate
  returned 5 BLOCKER and 13 MAJOR findings
- **Principle(s) in tension:** serving a stated need against designing for needs nobody stated

## Context

The maintainer asked how hard it would be to add webhook support and to look at
pre-export / post-export / cert-export hooks. ADR-0013 answered with an event bus, two consumer
contracts, an optional-extra packaging decision and a configuration redesign — 145–161 hours
and eighteen blocking findings, roughly ten of which existed only because of scope that
document invented. Its postmortem has the breakdown.

This ADR keeps what was asked for and drops what was not.

Today `settings.postexportcommand` runs one subprocess after an export pass
(`libs/post_export.py`, 63 lines): `shlex` parsing, no shell, fixed 30s timeout, exported
domains in `TRAEFIK_CERTIFICATE_EXPORTER_EXPORTED_DOMAINS`, dry-run suppression, failures
logged and never allowed to crash the watch loop. It works and is not changing.

## Decision

**1. Add notifications at `post-export` only, delivered by Apprise.**

One new setting alongside `postexportcommand`, taking one or more Apprise destination URLs.
After a pass completes, each is notified with the exported domain list. Delivery is
fire-and-forget: a failure is logged and never propagates, exactly like the existing hook's
non-zero exit.

That single setting covers what the original question actually asked — webhooks — and brings
email, Slack, Discord, ntfy, Gotify, Telegram and Matrix with it at no extra design cost.

**2. Apprise is an ordinary runtime dependency, not an optional extra.**

ADR-0013 made it an extra by analogy with `jsonschema`/`packaging`. The analogy does not hold:
those are optional to keep a *compiled* `rpds-py` chain out of a CI-only validator
(`pyproject.toml` records exactly that reason). Apprise is a user-facing runtime feature and
its chain — `requests` (already a main dependency), `requests-oauthlib`, `click`, `markdown`,
`PyYAML`, `certifi` — is pure Python.

The extra was also unreachable: `docker/Dockerfile` runs `poetry install --only main` with no
`--extras` and no build argument, so the feature could never have been installed in the only
artifact this project ships. Global rule 2 — the constraint was inherited rather than
interrogated, and what it bought was never restated for this case.

**3. No `cert-export`, no `pre-export`, no event bus, no new configuration surface.**

`cert-export` was the single largest complexity driver in ADR-0013 and nobody has asked for
it. `pre-export` is cheap but equally unrequested. Both are easy to add later *because* this
decision keeps the shape flat; neither is added now.

The setting is a scalar list beside the existing keys, so the current `config.yaml` and the
`TRAEFIK_CERTIFICATE_EXPORTER_` env convention address it unchanged. Nothing about the
configuration surface moves, which retires ADR-0013's two configuration findings by not
creating them.

**4. Secrets are the one thing this cannot inherit.**

An Apprise URL usually *is* the credential, and `_SECRET_FIELD_PATTERN` in `settings.py`
matches on key *name* — so a value inside a destination list is not reachable by that
mechanism at all, whatever the key is called. `_dump_config()` dumps the whole confuse
configuration and is a second exposure.

This is **BL-E001-005** ("the redaction regex could miss an oddly-named future secret field")
arriving in a shape the regex cannot address. Redaction of destination values is a
prerequisite of this work, and the backlog item is **re-scoped, not closed** — the key-name
mechanism needs superseding for value-shaped credentials, not extending.

## Consequences

- **One story, not an epic.** Estimate to follow from the calibrated estimator.
- **Every blocking gate finding about scope disappears** — they were consequences of
  `cert-export`, the extra, the config redesign and the two-contract split, none of which
  survive here.
- **The two real defects the gate found are already fixed** (`fix(watch):` — the `isWaiting`
  leak and distinct-file loss) and were never dependent on this design.
- **Deferred deliberately, and cheap to revisit:** `pre-export` and `cert-export` consumers,
  a checked HTTP action, and per-event configurable timeouts. Each becomes worth doing when a
  requirement names it. ADR-0013's library survey stands and is the record to consult first.
- **Cost accepted: a failed notification stops nothing.** An operator who needs something to
  *succeed* uses `postexportcommand`, which blocks and reports. The documentation must say so
  plainly rather than let it be discovered during an incident.
