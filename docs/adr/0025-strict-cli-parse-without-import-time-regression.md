# ADR-0025: Keep a lenient import-time `globalArgs`; add a separate strict parse called only from `main()`

- **Status:** Accepted (implemented E011-S01-003, 2026-10-06)
- **Amended:** 2026-10-11 (E014-S01-008) -- the strict parse is `parse_known_args()` plus
  `globalArgParser.error()` with `Did you mean` suggestions; Decision and Consequences below
  carry the current text; the 2026-10-06 text called `globalArgParser.parse_args()`
  (argparse's strict form)
- **Date:** 2026-10-06
- **Deciders:** Maintainer (ravensorb)
- **Epic:** E011
- **Departs from spec:** n/a
- **Principle(s) in tension:** BL-E001-006 (production should hard-fail on an unrecognized
  CLI flag) vs. the existing, load-bearing guarantee that importing
  `traefik_certificate_exporter` (pytest, a REPL, an embedding host) must never raise on
  foreign argv.

## Context

E011-S01-003 instructs relocating `globalArgs, _ = globalArgParser.parse_known_args()`
out of `src/traefik_certificate_exporter/libs/cli_args.py`'s module-import scope into a
`main()`-only strict-parse call, to fix BL-E001-006 (a genuine CLI typo like
`--dtaa-path` is currently silently ignored in production, not just during tests).
However, `src/traefik_certificate_exporter/app.py` line 15 does
`from .libs.cli_args import globalArgs` at module-import time, and uses `globalArgs` at
several points inside `main()` (`globalArgs.logginglevel`, `globalArgs.configfile`). If
the import-time assignment in `cli_args.py` is literally removed, as a naive reading of
the story's "move the call site" instruction would do, that `from .libs.cli_args import
globalArgs` import in `app.py` raises `ImportError` before `main()` ever runs — a strictly
worse regression than the one being fixed, because it breaks unconditionally rather than
only on a flag typo.

## Options considered

| Option | Pros | Cons | Standards fit |
|--------|------|------|---------------|
| A. Remove the import-time `globalArgs` assignment entirely; have `main()` call `globalArgParser.parse_args()` and bind the result to a local/module variable before first use | Matches a literal reading of "move the call site" | Breaks `app.py`'s existing top-level `from .libs.cli_args import globalArgs` unconditionally; every import of `app` (including under pytest) now `ImportError`s; the exact regression the story's own Non-goals/Security section says must not happen | Fails the story's own stated regression guard |
| B. Keep the lenient, import-time `globalArgs = globalArgParser.parse_known_args()[0]` assignment exactly as it is today (so `app.py`'s existing top-level import keeps working, and tests that import either module keep succeeding); additionally define `parse_args_strict() -> argparse.Namespace` in `cli_args.py`, calling `globalArgParser.parse_args()` (no suppression of unrecognized args); have `app.py`'s `main()` call `globalArgs = parse_args_strict()` as its first statement, rebinding the module-level name in `app`'s own namespace to the strict result before any attribute of it is read | Import-time behavior is unchanged (zero regression risk for the lenient path); the strict path exists and is exercised exactly where BL-E001-006 needs it — the one place `sys.argv` is guaranteed to be this process's own; no `ImportError` risk since nothing is removed, only added | Two parse calls run in the `main()` path (one lenient at import, one strict in `main()`) — a minor duplication, stated as an explicit trade-off below |

## Decision

**Option B.** `cli_args.py` keeps its existing module-level
`globalArgs, _ = globalArgParser.parse_known_args()` line untouched — this is what makes
`app.py`'s `from .libs.cli_args import globalArgs` safe at import time, and what every
existing test that imports either module already depends on. A new function
`parse_args_strict() -> argparse.Namespace` is added to `cli_args.py`. It
calls `globalArgParser.parse_known_args()` and, if any token is left over, dash or not,
calls `globalArgParser.error()`, which exits 2 with the usage line and
`unrecognized arguments: <tokens>`. For each leftover `-`-token with a close match among the
registered option strings, a `Did you mean '<flag>'?` line is added, computed by
`libs/suggest.nearest_name`, the helper the env-name suggestions also use. The message
always ends with `Try '--help' for full usage.` (E014-S01-008). `app.py`'s `main()` calls
`globalArgs = parse_args_strict()` as its very first statement, rebinding the
module-level `globalArgs` name inside `app`'s own namespace (the one `main()` reads
from for `logginglevel`, `configfile`, etc.) to the strict-parsed result — so production
invocations get BL-E001-006's hard-fail-on-typo behavior, while the lenient import-time
value remains solely a safe default for any consumer that imports without calling
`main()`.

## Consequences

- Positive: No `ImportError` risk — nothing is removed from module-import scope.
  Production (`main()`) hard-fails on an unrecognized flag, closing BL-E001-006.
  Import-only consumers (pytest, a REPL, an embedding host) keep succeeding exactly as
  today, closing the regression the story's own Security section warns against.
- Negative / trade-offs accepted: `parse_known_args()` runs twice in the `main()` path, once
  at import and once in `parse_args_strict()`. The cost is negligible (a short argv), and
  accepting it avoids a single-parse mechanism that would complicate the
  import-time/strict-time split.
- Follow-ups / exit plan: none — this is the complete, final mechanism for both paths;
  no non-GA/preview capability is involved.
