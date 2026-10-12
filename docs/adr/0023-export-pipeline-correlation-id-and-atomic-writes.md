# ADR-0023: Per-drain correlation ID and atomic certificate writes

- **Status:** Accepted (implemented by E011-S01-004; status corrected 2026-10-11 by E014-S02-003)
- **Date:** 2026-10-06
- **Deciders:** Maintainer (ravensorb), via Epic E011 Sprint S01 (Story E011-S01-004)
- **Amended by:** ADR-0043 (Decision 3: atomicity stays per file; a domain's file set is built before the first replace, and unchanged files are not rewritten)
- **Epic:** E011
- **Amends:** ADR-0003 (Logging: structured file output, secrets never logged). ADR-0003
  decided "no correlation ID needed — no cross-boundary hops to propagate one across,"
  reasoning this is "a single-process CLI/watcher, not a distributed service." That
  premise no longer holds: the watch path now runs watchdog's event callback on one
  thread, debounces onto a `threading.Timer` thread (`certificate_exporter.py`'s
  `AcmeCertificateFileHandler`), exports, then runs a post-export subprocess and
  (ADR-0014) delivers Apprise notifications — a real sync→async hop with no join key
  across it today. This ADR amends ADR-0003's threading-model assumption; it does not
  revisit AD-3's secret-redaction decision, which stands unchanged.
- **Principle(s) in tension:** Core §9 unified structured logging (correlation, no
  secrets/PII in logs) vs. Core §2 (reuse over re-derivation, minimal surface for a
  single-process tool)

## Context

BL-E010-001 (raised at both Epic 10 architecture gates) observes that an operator asking
"why did I get no notification for `acme-dns.json`?" has no way to join the watch-event log
line, the debounce/drain pass, the export result, and the post-export/notification outcome.
`docker/Dockerfile` sets `LOGGING_CONSOLEONLY=true` in the shipped image, which selects the
`coloredlogs` formatter — console records are human-readable strings, not structured
fields, so even a human reading container logs cannot grep a shared token across the hops.

ADR-0003 explicitly declined a correlation ID, reasoning there were no cross-boundary hops
to propagate one across. That reasoning was accurate when written; the hop introduced by
the watch-debounce design (and compounded by ADR-0014's notification delivery on the same
drain) means it no longer is. This is an **intra-process** correlation id — distinct from
the architecture spine's separately-deferred **cross-process** correlation ID (relevant
only if a future network-facing component, e.g. a metrics endpoint, is added). That
distinction is the reason this does not reopen the spine's deferred item.

BL-E010-002 (same gates) separately observes that shutdown and write safety have no
guarantees: `app.py`'s `KeyboardInterrupt` handler calls `observer.stop()`/`observer.join()`
and nothing else, so a pending `threading.Timer` drain is never cancelled and (being
non-daemon) can keep the process alive or race shutdown; and `__exportCertificate` writes
every PEM artifact via `Path.open("w")` (truncate-then-write), so a kill between truncate
and write — bounded by the export window today, widened by ADR-0014's per-destination
delivery bounds (~8s/HTTP, ~19s/SMTP) — can leave a zero-length or partial
`fullchain.pem` that a consuming service loads as valid.

## Options considered

| Option | Pros | Cons | Standards fit |
|---|---|---|---|
| A. Do nothing further (status quo) | No work | Leaves BL-E010-001/002 open against a Core §9 requirement the gates have raised twice | Fails Core §9 |
| B. Per-drain `contextvars.ContextVar` pass ID, propagated through the existing thread/subprocess hops, emitted as a structured field; `tempfile`+`os.replace` atomic writes; cancel the pending `Timer` on shutdown with a bounded join | Uses only stdlib facilities already idiomatic for this exact problem; minimal surface; fixes both findings with no new dependency | Requires passing the ID explicitly across the `threading.Timer`-to-worker-thread boundary (`contextvars` does not auto-propagate across `threading.Timer`, only across `asyncio` tasks and `contextvars.copy_context()`) | Satisfies Core §9 and Core §2 |
| C. A full structured-logging/tracing library (e.g. `structlog`, OpenTelemetry) | More powerful, future-proof | Large surface increase for a single-process CLI with no distributed tracing need; contradicts the spine's explicit deferral of cross-process tracing infrastructure | Fails Core §2 (re-derivation of what stdlib already covers) |

## Decision

**1. A per-drain pass ID, generated with stdlib `uuid.uuid4()`, carried in a
`contextvars.ContextVar` and explicitly threaded across the one hop that does not inherit
it automatically** — `threading.Timer`'s target callable must receive the ID as an
argument (or via `contextvars.copy_context().run(...)`), because `ContextVar` values do
not propagate to a manually started `threading.Thread`/`Timer` the way they do to
`asyncio` tasks. The ID is generated once in `handleEvent` when a timer is first armed for
a drain window, carried through `doTheWork` → `__processPath` → `exportCertificatesForFile`
→ `run_post_export_command` → `send_export_notifications`, and emitted as a structured
`correlation_id` field at each boundary's log line.

**2. The container console handler gains a JSON formatter option alongside the existing
`coloredlogs` one.** `LOGGING_CONSOLEONLY=true` today selects `coloredlogs` unconditionally;
a structured field is useless if the sink can't carry it. Add a JSON-capable console
formatter, selected by an explicit setting (not by inferring from `LOGGINGCONSOLEONLY`
alone, since a human operator attached to `docker logs` may still want color); default
stays `coloredlogs` to preserve current behavior.

**3. Certificate and key files are written via `tempfile.NamedTemporaryFile` (same
directory, so `os.replace` stays on one filesystem) followed by `os.replace()`, never
`Path.open("w")` directly.** `os.replace` is atomic on POSIX (and on Windows, unlike
`os.rename`), so a process kill lands either the old complete file or the new complete
file, never a truncated one.

**4. Shutdown cancels the pending drain timer and joins non-daemon threads with a bounded
timeout before exit.** `app.py`'s `KeyboardInterrupt` handler calls
`event_handler.timer.cancel()` (a no-op if already fired or `None`) in addition to the
existing `observer.stop()`/`observer.join()`, closing the exposure window BL-E010-002
describes rather than leaving it to the container runtime's grace period (`docker stop`'s
default 10s is not and should not be this tool's only safety net).

**4a. Amendment (implementation, E011-S01-004): the drain threads are made daemons rather
than joined as non-daemon threads.** Decision 4 as written ("joins non-daemon threads with
a bounded timeout before exit") does not bound shutdown: CPython's interpreter shutdown
joins every non-daemon thread regardless of what the application already waited for, so a
drain inside its 30s post-export hook or an Apprise delivery would still hold the process
past `docker stop`'s 10s grace and be SIGKILLed — the outcome Decision 4 exists to avoid.
`cancel()` therefore cancels an armed timer, waits a bounded 5s for an in-flight drain, and
then lets the process exit while the daemon thread is abandoned. This is only safe because
Decision 3 (and ADR-0024) make every certificate write atomic: an abandoned drain loses an
export, it cannot leave a partial file. `cancel()` also latches a shutdown flag, so neither
a late watchdog event nor the drain's own re-arm path can start a new pass after shutdown
has begun.

**4b. Amendment (sprint-01 closure fix pass, epic-level arch-drift AD-1): SIGTERM is routed
into the same shutdown path, and `cancel()`'s logging decision is made TOCTOU-safe.**
Amendment 4a's `cancel()` is reachable only from `KeyboardInterrupt` (SIGINT); the shipped
container stops on **SIGTERM** (`docker stop`, `kubectl delete`, s6), which bypassed the
entire shutdown path until sprint-01 closure's redteam/arch-drift review caught it.
`app.py::install_shutdown_signal_handlers` now installs a handler for `signal.SIGTERM` (and
`signal.SIGINT`, superseding the bare `KeyboardInterrupt` reliance) that re-raises
`KeyboardInterrupt` from signal-handler context, so both signals drive the one path Decision
4/4a already describes — no second shutdown mechanism was added. Separately, the sprint's
first fix pass found `cancel()`'s "was a drain actually running?" check (a plain `armed`
boolean read outside any lock) was a TOCTOU race against the drain thread's own state
transitions; it now reads `timer`/`draining`/a monotonically-incrementing `drainsRun`
counter under the handler's lock, and decides its log message from the **observed
`drainsRun` delta** taken before and after the bounded wait, rather than from a
racy point-in-time flag. The 5s bound from Amendment 4a is now a named module constant,
`SHUTDOWN_JOIN_TIMEOUT_SECONDS`, same value, same semantics.

## Consequences

- Positive: an operator can grep one `correlation_id` across a watch event, its drain,
  export, post-export command, and notification delivery — closing BL-E010-001 with no new
  dependency.
- Positive: `fullchain.pem` and siblings can no longer be observed partially written by a
  consumer process, closing BL-E010-002's write-safety half with a well-known stdlib
  pattern.
- Positive: shutdown no longer leaves an armed, uncancelled timer — closing BL-E010-002's
  shutdown half.
- Negative / trade-off accepted: the correlation ID must be threaded explicitly through
  every function signature on the hop (not free, unlike `asyncio`'s automatic context
  propagation) — acceptable because the call chain is shallow and already enumerated above.
- Negative / trade-off accepted: the new JSON console formatter is additive surface in
  `logging_utils.py`; default behavior is unchanged, so existing deployments see no
  behavior change unless they opt in.
- Follow-ups: `docs/operational.md` should document the new console-logging setting and
  how to grep by `correlation_id`.

## Open questions

- Whether `os.replace`'s atomicity guarantee extends unchanged to the Docker overlay
  filesystem this image typically runs on (bind-mounted `outputPath`, most commonly). POSIX
  semantics hold for same-filesystem renames; this should be confirmed against the
  documented deployment pattern rather than assumed.
