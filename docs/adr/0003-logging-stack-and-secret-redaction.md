# ADR-0003: Logging stack and secret-redaction policy

- **Status:** Proposed
- **Date:** 2026-08-30
- **Deciders:** Maintainer (ravensorb)
- **Principle(s) in tension:** Core §9 unified structured logging (correlation, no secrets/PII in logs)

## Context

Review findings #5 (BLOCKER) and #9 (MAJOR): `SettingsManager._dump_settings()` /
`_dump_config()` serialize the full `Settings` object and `confuse.Configuration` via
`jsonpickle` at DEBUG level, including `pkcs12Passphrase` in cleartext; and all logging
elsewhere is hand-formatted strings with no structured fields or correlation ID. This is a
single-process CLI/watcher, not a distributed service, so full OpenTelemetry-style trace
propagation is disproportionate — but secret redaction is not optional at any log level.

## Options considered

| Option | Pros | Cons | Standards fit |
|--------|------|------|---------------|
| A. Redact secrets only; keep string logging | Minimal change; fixes the BLOCKER immediately | Leaves MAJOR (unstructured logs) unresolved | Fixes §9's "no secrets in logs" clause only |
| B. Redact secrets + adopt a JSON formatter for the file handler | Fixes both findings; structured file logs are diffable/greppable/ingestible by log tooling later | Slightly more work; console output can stay human-readable via `coloredlogs` unaffected | Satisfies §9 fully for a single-process tool (no correlation ID needed — no cross-boundary hops to propagate one across) |
| C. Adopt `structlog` end-to-end | Best long-term structured-logging story | Largest change for a tool this size; not justified today | Over-engineered relative to current need |

## Decision

Option B. Redact `pkcs12Passphrase` (and any future secret-shaped field) before any
`jsonpickle`/dump call, at every log level — not just above DEBUG. Add a JSON formatter to
the `extended_file_handler` in `logging.yaml` so on-disk logs are structured; leave the
console formatter human-readable since there is no downstream log aggregator consuming
console output today. Do not adopt full correlation-ID propagation (§9's cross-boundary
clause) — this process has no service boundaries to correlate across; revisit only if a
metrics/health surface (PRD backlog item #15) turns this into a multi-component system.

## Consequences

- Positive: closes the BLOCKER immediately; file logs become machine-parseable without a
  disproportionate rewrite.
- Negative / trade-offs accepted: still no correlation ID — accepted because there is
  nothing to correlate across yet.
- Follow-ups: if a future change adds a network-facing component (health/metrics endpoint),
  revisit correlation-ID propagation at that time.

## Amended at 2026-10-06 (sprint-01 closure fix pass, epic-level arch-drift AD-2)

**Removed `./logging.yaml` CWD auto-discovery from `setup_logging`.** An earlier
implementation preferred a `./logging.yaml` found via the process's working directory over
the packaged copy, so the operator-writable `/config` volume this tool mounts in its
container image could supply a config file that `logging.config.dictConfig` would load.
`dictConfig` resolves arbitrary dotted import paths for `class:`/`()` keys — a single write
into that mounted volume was therefore a remote-code-execution path, not merely a
misconfiguration risk. Sprint-01 closure's red-team review caught this; the fix (now in
`src/traefik_certificate_exporter/libs/logging_utils.py::setup_logging`) honors only the
packaged config or an explicitly-set env var, never an implicit CWD lookup. This is
ADR-0023's governing logging/correlation decision (Decision 2, JSON console formatter)
touching the same function, which is why the amendment lives here rather than as a new,
disconnected decision point.
