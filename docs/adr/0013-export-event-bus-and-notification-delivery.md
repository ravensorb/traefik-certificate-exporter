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
| transport | subprocess | Apprise |

The last row is deliberately separated from the rest. A first draft of this ADR wrote
"mechanism: subprocess / Apprise" into the contract itself, which is wrong: it makes the
transport definitional and leaves "is a webhook an action or a notification?" unanswerable.

**The question that classifies a consumer is whether anything downstream depends on its
outcome.** A POST that announces an export is a notification. A POST to a service's reload
endpoint, where a 500 means the certificate is live but unloaded, is an action that happens to
speak HTTP. Same transport, different contract.

**Webhooks are therefore notifications by default**, delivered through Apprise's generic
`json://` / `form://` / `xml://` handlers, because that is what the overwhelmingly common case
wants.

**HTTP is not an action transport, and the reasoning behind that reversal is worth keeping.**

An earlier draft of this ADR argued HTTP into the action contract as a second transport. It was
dropped, and the reason is the honest one: **no requirement asked for it.** The question that
produced it was a classification question — *are webhooks actions or notifications?* — and the
answer to a classification question is a classification, not a new capability. The rest followed
from a need nobody had stated.

So: **webhooks are notifications, delivered by Apprise, and that is the whole answer.** Apprise's
`json://` already emits a caller-defined flat body (see the evaluation below), over TLS, with URL
parsing, the destination list and retries handled. Nothing of ours issues an HTTP request.

Two consequences are accepted rather than hidden:

- **A failed webhook stops nothing.** Delivery is fire-and-forget, so an operator must not use one
  where the outcome matters. The documentation is required to say this plainly (Story 10.4)
  rather than leave it to be discovered during an incident.
- **A checked HTTP call has no supported route**, and the obvious workaround does not exist —
  `docker/Dockerfile`'s runtime stage installs `python3` and nothing else, so there is no `curl`,
  and BusyBox `wget` is not a substitute for anything needing a method, headers or a body. This
  gap is open deliberately. **If a real requirement appears, the work is small and already
  scoped**: `requests` is a non-optional runtime dependency, so it is a POST with explicit
  connect/read timeouts, `urllib3.Retry`, and a non-2xx treated exactly as a non-zero exit — and
  the library survey below records what was already checked, so nobody repeats it.

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
events — and each is overridable. **The override is bounded by a hard ceiling.**

**The reason for the ceiling is worse than latency, and an earlier draft of this ADR got it
wrong.** It said a slow action "stalls the watch loop and the events behind it". There are no
events behind it. `AcmeCertificateFileHandler.handleEvent` reads:

```python
with self.lock:
    if not self.isWaiting:
        self.isWaiting = True
        self.timer = threading.Timer(2, self.doTheWork, args=[event])
        self.timer.start()
```

An event arriving while `isWaiting` is set is **silently discarded** — not queued, not coalesced,
not deferred. And `doTheWork` clears `isWaiting` only at its very end, *after* the consumers have
run. So the blind window is `2s + export + every consumer`, and any acme.json change inside it is
**lost**.

Today that window is bounded by one 30-second hook. Under this ADR it becomes the sum of every
action across a pass — with per-certificate actions on a large domain set, minutes. A renewal
landing in that window is not delayed, it is never exported at all, and nothing reports it.

So the ceiling is a correctness control, not a performance one, and the per-event budget exists to
keep the blind window bounded. Exceeding the ceiling is a startup configuration error, not a
silent clamp.

**The debounce itself is out of scope here and named as prior art rather than fixed**: dropping
duplicate events is what `isWaiting` is *for*, and the discard is only a defect at the tail. Story
10.1 owns proving where the boundary is; changing the handler's queuing model is its own decision
and would need its own record.

**7. Console is not a sink.**

The tool already has a logging stack governed by ADR-0003 — coloredlogs, python-json-logger,
secret redaction — and already logs `Extracted certificate for: {name}` per certificate. A console
sink would be a second path to the same terminal with its own formatting and its own
configuration. Logging stays logging.

## Libraries surveyed, and why webhooks are Apprise's job (global rule 1)

**Recorded because the question was asked and answered, not because code depends on it.** With
HTTP dropped from the action contract, nothing here issues a request; Apprise does. The survey
stays because it is the reason that choice is safe, and because it is the file the next person
reads if the checked-HTTP requirement ever arrives.

**The outbound-webhook-sender category was searched rather than assumed, and it is a graveyard.**
This matters: the first draft of this section asserted no package wraps it usefully without
looking, which is the reasoning rule 1 exists to prevent, applied to itself.

| package | latest | last release | why not |
|---|---|---|---|
| `webhook-sender` 0.1.0.1 (MIT) | 0.1.0.1 | **2016-06-22** | Its summary is this feature exactly — "sending webhooks, with automatic retry and CLI". Two releases, ten years dead. |
| `webhooks` 0.4.2 (BSD) | 0.4.2 | **2014-05-22** | Twelve years dead. |
| `pywebhooks` 0.5.5 | 0.5.5 | **2019-02-10** | Seven years dead, and it is a webhook *receiving* service, not a sender. |
| `svix` 2.3.0 (MIT) | 2.3.0 | 2026-09-03, actively maintained | Not a library for this: it dispatches through Svix's hosted service and needs an account. The genuinely standalone part is signature verification, which is `standardwebhooks` below. |
| `notifiers` 1.3.6 (MIT) | 1.3.6 | 2025-05-17, maintained | Twenty named providers (`slack`, `email`, `pagerduty`, `telegram`, …) and **no generic webhook or custom provider at all** — checked against the package's `providers/` directory, not inferred. There is no route to a body of your own. |

So the category exists, three attempts at it were abandoned between 2014 and 2019, and everything
still maintained is either a notification dispatcher with fixed payloads or a SaaS client. The
reason is visible in the shape of the problem: once retry is delegated to `urllib3` and the body
comes from configuration, what remains above `requests` is roughly forty lines of mapping and
logging. That is too thin to sustain a package, which is why none of them survived — and why
adopting a dead one would import a maintenance burden rather than remove one.

Three sub-problems inside the action *are* rule-1 domains and are answered with libraries rather
than code:

| sub-problem | chosen | evaluated and rejected |
|---|---|---|
| retry / backoff | `urllib3.Retry` via `requests.adapters.HTTPAdapter` — already in the image (`urllib3` is a main-group dependency) | `tenacity` 9.1.4 (Apache-2.0), `backoff` 2.2.1 (MIT): both good general retry decorators, but generic. `urllib3.Retry` understands HTTP specifically — status-forcelist, `Retry-After`, which methods are safe to repeat — which a decorator wrapping an opaque callable cannot. Adding either would be a new dependency doing less. |
| body templating | `string.Template` (stdlib) for scalar substitution | `Jinja2` 3.1.6: the right answer for real templating, and currently a **dev-group** dependency, so adopting it means promoting it plus `markupsafe` into the runtime image. Rejected for v1 on scope, not weight: an operator substituting a domain into a JSON body needs `$domain`, not loops, conditionals and filters. Config files that can execute logic are a category of problem this project does not need. **Escalation is named: if a real templating need appears, it is Jinja2, not an extended `string.Template`.** |
| HTTP client | `requests` (present) | `httpx` 0.28.1 (BSD-3-Clause): a good library whose advantage is async, which nothing here needs. Adding a second HTTP client to a codebase that has one is strictly worse. |

**Deliberately out of scope for v1, and recorded so it is a decision rather than an omission:
webhook signing.** A receiver may reasonably want to verify a request came from this exporter.
The answer is `standardwebhooks` 1.1.0 (MIT), which implements the Standard Webhooks
specification — HMAC over a canonical payload, timestamp header, replay window. Stdlib `hmac`
supplies the primitive, but the primitive is not the hard part; the protocol is, and that is
precisely what the library encodes. Not v1 because no requirement has asked for it, and shipping
a bespoke signing scheme that later has to be replaced is worse than shipping none.

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
- **"Webhook" has one meaning here, and that is a feature of the design rather than an accident.**
  It is an Apprise notification: fire-and-forget, caller-defined flat body. There is no second
  thing wearing the same name for a reader to pick wrongly.
- **This project issues no HTTP requests of its own.** Every network call belongs to a maintained
  library, which is the position rule 1 wants and the one that needs no exception recorded.
- **Consumer duration is now a correctness budget.** Every second an action spends is a second in
  which a certificate change is dropped rather than delayed, because the watch handler discards
  events while it is busy. This was found by spot-checking one assumption in this ADR after it was
  written, which is the reason Epic 10 is gated on an architecture review rather than going
  straight to stories.
- **A new secret shape enters settings.** A notification URL usually *is* the credential.
  `_SECRET_FIELD_PATTERN` in `settings.py` matches on key *name*
  (`secret|password|passphrase|token|api[_-]?key`), so a key called `notificationUrl` would be
  dumped in full by `_dump_settings()`. That is **BL-E001-005** becoming real, and it is a
  prerequisite of the notification story rather than follow-up work.
- **The payload becomes an interface.** Once a webhook body ships, changing it breaks consumers.
  It is versioned from the first release.
