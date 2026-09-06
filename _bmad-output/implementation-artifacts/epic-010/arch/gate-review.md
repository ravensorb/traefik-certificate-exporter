# Epic 010 — Architecture Gate Review

- **Date:** 2026-09-06
- **Work type:** MIXED (E010-S01-001..003 CODE, -004 DOCS) → gate runs
- **Reviewers run:** `l3io-arch-review` (Mode B) — alone
- **Escalation:** not possible. `bmad-agent-architect` and superpowers are both absent, so
  §4's escalation-on-signal is a no-op here and every finding is single-source by
  construction. Per §5 a single-source MAJOR still blocks; corroboration would have altered
  labels, not the verdict.
- **Verdict:** **BLOCKED** — 5 BLOCKER, 13 MAJOR (18 blocking), 8 MINOR

## What this gate was reviewing

ADR-0013 (Status: Proposed) and the four Epic 10 stories. The ADR was written and revised
seven times in a single sitting, four of those revisions correcting factual errors in it that
were caught only when the maintainer challenged a claim. The gate was requested on exactly
that basis, and the instruction to the reviewer said so: *assume more remain.*

Three more were found.

## Independently re-verified before acceptance

Findings are the reviewer's; these three were re-checked against the repository because they
carry the most weight, and a wrong correction is no better than the original error.

| Claim | Verdict | Evidence |
|---|---|---|
| `TRAEFIK_CERTIFICATE_EXPORTER_CONFIGFILE` is inert | **CONFIRMED** | `cli_args.py:13-20` has `default="config.yaml"` and no env fallback; `settings.py:182` calls `set_file(globalArgs.configfile)` *before* `set_env` at `:184`, so the variable cannot select the file. It appears once in the repo — a commented-out compose line, `docker/README.md:126`. ADR §5 asserted it as the container route. **The ADR was wrong.** |
| Apprise as an extra is unreachable in the shipped image | **CONFIRMED** | `docker/Dockerfile:41` is `poetry install --only main --no-root --no-directory`. No `--extras`, no build ARG, and `docker-bake.hcl` carries no such arg. E010-S01-003's "unless the extra is requested" describes a path that does not exist. |
| "`urllib3` is a main-group dependency" is false | **PARTIALLY** — the reviewer overstated it | `urllib3` is **not declared** in `pyproject.toml`, but `poetry.lock` records `groups = ["main", "dev"]`, so it *does* resolve into the main group and *is* in the runtime image. "Already in the image" was true; "is a main-group dependency" was imprecise. The reviewer's underlying point stands and is the better one: `pyproject.toml:46-50` records this project's own policy of declaring rather than relying on someone else's transitive staying put. |

## BLOCKER (5)

1. **`isWaiting` is never cleared on an unwinding path, and E010-S01-002 designs one.**
   `doTheWork` (`certificate_exporter.py:404-428`) has no `try/finally`. A blocking
   `pre-export` abort is an early return or an exception on a `threading.Timer` thread — the
   thread dies via `threading.excepthook` and `isWaiting` stays `True` **for the life of the
   process**. Every later acme.json change is discarded at `handleEvent:396`, emitting only a
   misleading "Certificates changed found in file" per lost event. Live today too:
   `restartLabeledContainers` is reached with `domains=None` via `:246-247`.
2. **E010-S01-002 is built from the sentence ADR §6 exists to retract.** The story's ceiling
   rationale says "*every event queued behind it*"; §6 says "*There are no events behind it.*"
   The story's own footer makes the ADR authoritative, so it is self-contradictory — and on
   the ceiling's entire justification, latency versus event loss. Built from the story, the
   ceiling gets tuned as a generous per-consumer performance budget instead of a tight budget
   summed across the pass.
3. **The queuing deferral rests on a false premise.** ADR §6 defers it because the discard is
   "duplicate coalescing". It is not: `handleEvent` watches `*.json` across the data directory
   while `doTheWork` processes one `args[0].src_path`. A change to `acme-dns.json` while
   `acme-http.json`'s timer is pending is a **distinct file whose certificates are never
   exported**. Multi-resolver multi-file is the documented setup.
4. **`TRAEFIK_CERTIFICATE_EXPORTER_CONFIGFILE` is inert** (see table). Under this epic it turns
   from harmless into silent: point it at an events config and every action and notification
   simply never fires, with no error.
5. **Apprise is unreachable in the shipped image** (see table). The precedent invoked in ADR §4
   does not transfer — `jsonschema`/`packaging` are optional to keep a *compiled* rpds-py chain
   out of a CI-only tool; Apprise is a user-facing runtime feature whose chain has no such
   problem. Global rule 2: the constraint was inherited, not interrogated.

## MAJOR (13) — summarised

Env-var grammar cannot address hyphenated nested keys at all (`sep="_"` vs `pre-export`), so
ADR §5's "env vars remain fully supported" is false as designed · secret redaction is key-name
based while the new credentials are *list items* (an Apprise URL), so `--logginglevel DEBUG`
prints them, and `_dump_config()` is named by no AC · no correlation ID across watch → Timer →
subprocess → notification, in an epic that creates those four hops · the two-contract split
collapses once 002 makes "blocking" a per-consumer boolean · "one emitter" is really three
emission sites with two different pass scopes, and the anti-divergence test is scoped to the
one behaviour a human noticed · "no delivery blocks the pass" needs threads no story specifies,
bounds, or shuts down · shutdown becomes a data-corruption path (non-daemon timers, plain
truncate-then-write, `docker stop`'s 10s grace) · the `cert-export` payload names four
always-present fields, three of which are absent or undefined in normal operation, shipping as
a versioned interface · dry-run specified for actions, silent for notifications · consumer
exceptions land in an existing broad handler and are mislabelled, so the isolation AC goes
green against accidental behaviour · the image guard's "transitive chain" is a prose-enumerated
list, not a derived scope · the duration test asserts a bound derived from nothing · nothing
requires `post_export.py` be retired, so the epic likely ends with two subprocess
implementations · no diagram for a design whose whole difficulty is threading and timing.

## MINOR (8)

`urllib3` claim (above) · Apprise version/licence/`requires_python` unverifiable from the repo
(it is in neither `pyproject.toml` nor `poetry.lock`) · unsynchronised write to `isWaiting` at
`:412` · 001's "no event delivery code executes" contradicts its own first AC · "blocking"
misnames what is really fail-closed · `post-export` ordering vs `restartContainers`
unspecified · no dev-group mirror for the new extra, breaking the pattern
`test_publication_contract.py` holds · no AC requires the emitter be injectable.

## Reviewer's minimum to unblock

Re-derive ADR §4 (extras vs. the shipped image) and §5 (which configuration surfaces actually
reach the new keys) against the code; correct E010-S01-002's ceiling rationale to match §6;
and settle the queuing decision rather than defer it.

## Recommended ADRs (reviewer)

Watch-handler queuing model · notification concurrency and process shutdown · event payload
contract v1 (nullability, correlation ID, versioning) · configuration addressing · secret
redaction for value-shaped credentials, superseding the key-name mechanism — **BL-E001-005
should be re-scoped, not closed.**

## Process note

§6 prescribes one ADR per blocking finding, which here is 18 — disproportionate, and not
started. The reviewer's own "minimum to unblock" is four items and is the better entry point.
No remediation has been performed; this gate is a record, not a change.
