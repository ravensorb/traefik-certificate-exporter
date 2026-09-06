# ADR-0013: One export event bus, two consumer contracts, and Apprise for delivery

- **Status:** Proposed
- **Date:** 2026-09-06
- **Deciders:** Maintainer (ravensorb)
- **Principle(s) in tension:** One abstraction that reads simply against two consumer kinds whose failure semantics genuinely differ
- **Supersedes in part:** ADR-none; extends the post-export hook shipped under Epic 5

## Context

Epic 5 added `settings.postexportcommand`: one subprocess, run once after an export pass,
30-second timeout, non-zero exit logged as an error, never allowed to crash the watch loop.
It is called from two places — `app.py` inside the `runAtStart` block, and
`AcmeCertificateFileHandler.doTheWork` on the watch path.

Three extensions are wanted:

1. more points in the export lifecycle than "after the pass" — before it, and per certificate;
2. delivery over HTTP rather than a subprocess;
3. further channels after that, email being the one named.

Taken naively, that is three lifecycle points multiplied by N delivery mechanisms, each wired
as its own flat `settings.*` key. Six settings before email is mentioned. That shape does not
survive the fourth channel.

## The observation this decision rests on

**The consumers are not all the same kind of thing, and the difference is in the contract, not
the transport.**

The existing shell hook *blocks*, carries a *timeout*, captures *stderr*, and treats a non-zero
exit as an error. It exists (GitHub issue #2) to `chown` a file into another service's location.
Whether it succeeded is the point. It is an **action**.

A Slack message is not that. It is fire-and-forget; its failure is a log line and nothing
downstream depends on it. It is a **notification**.

Folding both into a single "notification layer" forces a choice between weakening the action's
contract to fit and giving notifications a blocking, exit-code-bearing contract they have no use
for. The common shape — *something happened, tell someone* — is real, and it belongs in the
event, not in the delivery.

## Options considered

1. **Flat settings per lifecycle point per mechanism.** Rejected: six keys before email, and
   each new channel edits the exporter.
2. **One "notification layer" with hand-written console, email, shell and webhook sinks.**
   Rejected on two counts. It merges the two contracts above, and the notification half is a
   solved problem — writing SMTP handling, HTTP retry and per-service payload shaping by hand is
   what global rule 1 exists to prevent.
3. **An event bus with two consumer contracts, notifications delegated to a library.** Chosen.

## Decision

**1. The exporter emits events; it does not know who consumes them.**

Three events, each carrying a payload rather than a bare domain list:

| event | emitted | payload |
|---|---|---|
| `pre-export` | before any acme file is read | the trigger (start / watch), the source path where one applies |
| `cert-export` | per certificate written | the domain, its SANs, the output directory, the resolver |
| `post-export` | after the pass completes | the processed domain list |

Both call paths — `runAtStart` and `doTheWork` — emit the same events. That they currently
disagree about the `restartContainers` gate is a defect this refactor is expected to settle, not
preserve.

**2. Two consumer contracts, deliberately not unified.**

| | **actions** | **notifications** |
|---|---|---|
| mechanism | subprocess | Apprise |
| blocking | yes | no |
| timeout | fixed, per invocation | the library's |
| failure | logged as an error | logged, never propagated |
| may abort the pass | `pre-export` only, and only if configured to | never |

The existing `postexportcommand` becomes the `post-export` action and keeps its behaviour
exactly. This ADR does not change what it does today.

**3. Notification delivery is Apprise, not our code.**

`apprise` 1.13.1, BSD-2-Clause, `requires_python >=3.9` (this project is `>=3.10,<3.15`).
One configuration string per destination yields email, generic webhooks, Slack, Discord, ntfy,
Gotify, Telegram, Matrix and roughly a hundred others, with their auth and retry handling
already written and maintained.

Evaluated against writing it ourselves: a hand-written email sink alone is six-plus settings
(host, port, TLS mode, user, password, from, to), credentials to redact, and the delivery path
most likely to hang. A hand-written webhook sink needs retry/backoff, which global rule 1 names
explicitly as a domain not to hand-roll. Neither is work this project should own.

**4. Apprise is an optional extra, not a core dependency.**

It pulls `requests, requests-oauthlib, click, markdown, PyYAML, certifi`. `pyproject.toml`
already keeps `jsonschema` and `packaging` optional so `poetry install --only main` — what
`docker/Dockerfile` runs — does not drag compiled chains into the runtime image. Apprise gets the
same treatment. With the extra absent, a configured notification logs "notifications requested but
the extra is not installed" once, and export is unaffected.

**5. Console is not a sink.**

The tool already has a logging stack governed by ADR-0003 — coloredlogs, python-json-logger,
secret redaction — and already logs `Extracted certificate for: {name}` per certificate. A console
sink would be a second path to the same terminal with its own formatting and its own
configuration. Logging stays logging.

## Consequences

- **Adding a channel becomes configuration, not a story.** Discord is a URL.
- **The two call paths converge.** One emitter, so `runAtStart` and the watch path cannot drift
  again the way the restart gate did.
- **A new failure mode is accepted deliberately:** a `pre-export` action configured to abort can
  stop an export that would otherwise have succeeded. That is the point of the hook, and it is
  the only place where consumer failure is allowed to affect the pass.
- **Cost accepted — per-certificate delivery multiplies.** Fifty domains with a `cert-export`
  notification is fifty deliveries per pass, on a watch loop that debounces at two seconds.
  `cert-export` therefore carries a shorter timeout than `post-export`, and the story that adds it
  owns proving the pathological case.
- **A new secret shape enters settings.** A notification URL usually *is* the credential.
  `_SECRET_FIELD_PATTERN` in `settings.py` matches on key *name*
  (`secret|password|passphrase|token|api[_-]?key`), so a key called `notificationUrl` would be
  dumped in full by `_dump_settings()`. That is **BL-E001-005** becoming real, and it is a
  prerequisite of the notification story rather than follow-up work.
- **The payload becomes an interface.** Once a webhook body ships, changing it breaks consumers.
  It is versioned from the first release.
