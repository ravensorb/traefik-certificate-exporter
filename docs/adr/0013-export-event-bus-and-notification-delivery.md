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

**2. Two consumer contracts, deliberately not unified — and the axis is the contract, not the
transport.**

| | **actions** | **notifications** |
|---|---|---|
| the caller depends on the outcome | yes | no |
| blocking | yes | no |
| timeout | configurable, per event (see 6) | the library's |
| failure | logged as an error | logged, never propagated |
| may abort the pass | `pre-export` only, and only if configured to | never |
| transport *today* | subprocess | Apprise |

The last row is deliberately separated from the rest. A first draft of this ADR wrote
"mechanism: subprocess / Apprise" into the contract itself, which is wrong: it makes the
transport definitional and leaves "is a webhook an action or a notification?" unanswerable.

**The question that classifies a consumer is whether anything downstream depends on its
outcome.** A POST that announces an export is a notification. A POST to a service's reload
endpoint, where a 500 means the certificate is live but unloaded, is an action that happens to
speak HTTP. Same transport, different contract.

**Webhooks are therefore notifications by default**, delivered through Apprise's generic
`json://` / `form://` / `xml://` handlers, because that is what the overwhelmingly common case
wants. **HTTP-as-an-action is a recognized second transport for the action contract and is out of
scope here**, for one reason worth recording: nobody should have to fake it. The obvious
workaround — a shell action running `curl` — does not work in the shipped image.
`docker/Dockerfile`'s runtime stage installs `python3` and nothing else; there is no `curl`, and
BusyBox `wget` is not a substitute for anything needing a method, headers or a body. An operator
who needs a checked HTTP call today has no supported route, and pretending the shell action
covers it would be false.

The existing `postexportcommand` becomes the `post-export` action and keeps its behaviour
exactly, apart from gaining the configurable timeout in 6. This ADR does not change what it
does today.

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

**5. Configuration lives in the existing `config.yaml`, not a new file.**

This project already has the file this decision would otherwise invent. `confuse` loads
`config.yaml` (`--config-file`, default `config.yaml`), the packaged defaults ship as
`src/traefik_certificate_exporter/config_default.yaml`, and the container already creates and
documents `/config` as the mount point with
`TRAEFIK_CERTIFICATE_EXPORTER_CONFIGFILE=/config/config.yaml`. Precedence is settled and
documented in `settings.py`: **CLI > env var > config file > packaged default**.

What changes is which surface is *primary*. Every setting so far has been a scalar, so the flat
`TRAEFIK_CERTIFICATE_EXPORTER_*` env-var convention has been sufficient and the config file
optional. Eventing is not scalar — it is a list of destinations and a per-event map of consumers,
and env vars express that badly. `domains.include/exclude` is the existing precedent for the
resolution: nested in YAML, with a comma-separated env-var fallback parsed by
`_parse_domain_list`.

So: **the config file becomes the documented primary surface for eventing**, env vars remain
fully supported for the simple single-consumer cases, and no new file format or location is
introduced. A JSON config is explicitly rejected — it would be a second format alongside the YAML
one that already works, for no gain.

**6. Action timeouts become configurable, per event, with a ceiling.**

Epic 5 fixed the timeout at 30 seconds and recorded `settings.postexportcommandtimeout` as
deliberately out of scope. Three lifecycle points make that untenable: a `chown` completes in
milliseconds, a service reload can legitimately take a minute, and a per-certificate action
multiplies whatever it is by the certificate count.

Each event therefore carries its own default — shorter for `cert-export` than for the once-per-pass
events — and each is overridable. **The override is bounded by a hard ceiling**, because the
timeout is not a private choice: `doTheWork` debounces on a two-second timer, so a long per-
certificate action does not merely delay itself, it stalls the watch loop and the events behind
it. An operator raising the value is spending shared budget, and the ceiling is where that is
made visible. Exceeding it is a startup configuration error, not a silent clamp.

**7. Console is not a sink.**

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
  consumer is fifty invocations per pass, on a watch loop that debounces at two seconds.
  `cert-export` therefore carries a shorter default timeout, the override is capped, and the story
  that adds it owns proving the pathological case.
- **Gap accepted, and named rather than hidden: there is no checked HTTP call.** An operator
  needing "POST this and fail if it does not return 2xx" is unserved until HTTP joins the action
  transports. The shell action is not a workaround, because the runtime image carries no `curl`.
  Recorded here so the next reader finds the gap stated rather than discovering it.
- **A new secret shape enters settings.** A notification URL usually *is* the credential.
  `_SECRET_FIELD_PATTERN` in `settings.py` matches on key *name*
  (`secret|password|passphrase|token|api[_-]?key`), so a key called `notificationUrl` would be
  dumped in full by `_dump_settings()`. That is **BL-E001-005** becoming real, and it is a
  prerequisite of the notification story rather than follow-up work.
- **The payload becomes an interface.** Once a webhook body ships, changing it breaks consumers.
  It is versioned from the first release.
