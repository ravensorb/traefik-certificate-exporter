# ADR-0026: `AcmeCertificateFileHandler` owns a None-safe `shutdown()`/`cancel()` method

- **Status:** Accepted (implemented by E011-S01-004; status corrected 2026-10-11 by E014-S02-003)
- **Date:** 2026-10-06
- **Deciders:** Maintainer (ravensorb)
- **Epic:** E011
- **Departs from spec:** n/a
- **Principle(s) in tension:** E011-S01-004's shutdown-cancellation AC ("must not raise")
  vs. `AcmeCertificateFileHandler.__init__`'s own invariant that `self.timer` is `None`
  until the first watched-file event ever fires.

## Context

E011-S01-004 plans adding `event_handler.timer.cancel()` to
`src/traefik_certificate_exporter/app.py`'s `KeyboardInterrupt` handler (today it only
calls `observer.stop()` then `observer.join()`). But
`AcmeCertificateFileHandler.__init__` (in
`src/traefik_certificate_exporter/libs/certificate_exporter.py`) sets `self.timer = None`,
and `self.timer` is only ever reassigned to a real `threading.Timer` inside `handleEvent`
(when first arming a debounce window) and `__rearm` (when re-arming after an in-flight
drain is interrupted). Until the first watched-file event fires, `self.timer` stays
`None`. Calling `.cancel()` on `None` raises `AttributeError` — hit on the very common
"start the process, Ctrl-C before anything happens" path (e.g. an operator verifying the
process starts cleanly, or a container health-check cycling it before any ACME file
changes). This directly violates the story's own "must not raise" requirement for the
shutdown path.

## Options considered

| Option | Pros | Cons | Standards fit |
|--------|------|------|---------------|
| A. Guard the call at the `app.py` call site: `if event_handler.timer is not None: event_handler.timer.cancel()` | Minimal diff; no new method | Leaks the `None`-is-possible invariant of `AcmeCertificateFileHandler.timer` into `app.py`, a module that otherwise treats the handler as an opaque collaborator; every future caller of a cancellation path must remember to re-add the same guard | Workable but puts an encapsulation concern in the wrong module |
| B. Add a `AcmeCertificateFileHandler.cancel()` (or `shutdown()`) method that internally no-ops safely when `self.timer` is `None`, and have `app.py` call `event_handler.cancel()` instead of reaching into `.timer` directly | Keeps the `None`-check encapsulated in the class that owns the invariant (the class that sets `self.timer = None` in `__init__` and is the only place that reassigns it); `app.py` stays a thin orchestrator that calls one method on its collaborator, with no knowledge of the handler's internal timer lifecycle; a natural place to also log the shutdown/cancellation (per the story's Observability requirement that shutdown be logged at INFO) | One additional method to add/test | Preferred per the story's own guidance; matches the project's existing style of putting invariant-guarding logic inside the class that owns the state (e.g. the handler already owns `self.lock`/`self.pendingPaths` coordination internally) |

## Decision

**Option B.** Add a method `AcmeCertificateFileHandler.cancel(self) -> None` that checks
`if self.timer is not None: self.timer.cancel()` internally (a no-op, by design, when no
timer has ever been armed, and also safe per `threading.Timer.cancel()`'s own documented
behavior when the timer has already fired) and logs the cancellation at INFO with
whatever correlation-ID context is in flight, satisfying the story's
Observability requirement in the same place. `app.py`'s `KeyboardInterrupt` handler
calls `event_handler.cancel()` — not `event_handler.timer.cancel()` directly — before
`observer.join()`. This keeps the `self.timer`-may-be-`None` invariant encapsulated in the
one class that creates and owns it, rather than requiring every caller to independently
remember the guard.

## Consequences

- Positive: The "Ctrl-C before any event fires" path no longer raises `AttributeError`;
  `app.py` has no knowledge of the handler's internal timer-lifecycle invariant; the
  shutdown-is-logged observability requirement is satisfied at the same call site that
  enforces the guard, rather than needing a second change to `app.py` to add logging
  around a raw `.timer.cancel()` call.
- Negative / trade-offs accepted: One additional public method on
  `AcmeCertificateFileHandler`; trivial to test in isolation (construct a handler, call
  `cancel()` with no timer armed, assert no exception — matching the story's existing
  Testability approach of asserting over `timer.cancel()`/`is_alive()` without a real
  signal).
- Follow-ups / exit plan: none — this is a complete fix scoped to this story's shutdown
  path.
