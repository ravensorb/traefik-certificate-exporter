# Epic Closure Retrospective — E001: Trustworthy Certificate Export Core

**Velocity:** 3/3 stories done in a single sprint (S01) — no carry-over.

**Recurring pain point:** writing the first real tests for a codebase that had none surfaced
more defects than the stories' own listed scope anticipated (2 pre-existing bugs found and
fixed: import-time argv-parsing crash, and a missing `return`/append-extend nesting bug pair
in ACME export whose real impact was narrower than first assessed — see below). This is
expected and desirable — it is exactly what Story 1.3 existed to do — but it means "write
tests for X" stories in an untested codebase should budget for defect discovery, not just
defect documentation. **A separate, unforced error** also surfaced this sprint: a fourth
"defect" (config precedence) was retracted after the maintainer confirmed the original
behavior was correct and already working — the agent had "fixed" working code to match its
own undocumented assumption rather than a confirmed requirement. See `BL-E001-004`.

**Top learnings to carry forward:**
- A module-level singleton that parses `sys.argv` at import time (the `globalArgs` pattern)
  is fundamentally untestable from any host other than the console script. Watch for the same
  shape recurring — `globalSettingsMgr` and `globalLogger` are the same pattern family, so
  future epics touching them should check for equivalent import-time side effects.
- `confuse`'s precedence model is "later-added source wins" — the actual, maintainer-confirmed
  precedence is `CLI > env var > config file > packaged default` (env vars outrank the config
  file, matching this Docker-first tool's deployment model); any future change to
  `SettingsManager.loadFromFile`'s source-add order must be checked against this.
- **Before "fixing" a behavior to match a documented rule, check where that rule came from.**
  If the documentation was written during the same body of work as the fix, it is not
  independent confirmation — verify with the maintainer, or against git history/behavior that
  predates the documentation, before changing working code.
- Fixture-driven ACME tests (v1/v2, lowercase/uppercase) are cheap to write and caught a
  functional bug (missing `return`) that no amount of manual testing had apparently surfaced —
  this validates prioritizing regression tests early rather than deferring them. But when
  assessing a found bug's severity, trace exactly which observable behavior it affects before
  reporting impact — the missing `return` never affected certificate export to disk, only an
  optional downstream feature.

## Architectural drift review (epic-level, work_type=CODE)

Epic has a single sprint, so epic-level scope is identical to the sprint-level review already
performed in `sprint-01/closure/retrospective.md` — no additional drift found. All changes
remain consistent with ADR-0001–0005 and `ARCHITECTURE-SPINE.md`; no new ADR required.

## Epic security review (work_type=CODE)

Same scope note as above — no unredacted secret-dump path found; no CLI flag currently
carries the PKCS12 passphrase; `require_existing_path`'s `sys.exit(1)` is a straightforward
availability improvement with no new attack surface. No CRITICAL/HIGH/MEDIUM findings. Two
LOW findings already logged during sprint closure (`BL-E001-005`, `BL-E001-006`) stand as the
epic's residual — neither promoted, given their narrow, already-understood scope.

## Issue triage

6 issues total for this epic: 2 fixed in-sprint at Medium severity (`BL-E001-001`,
`BL-E001-002`, `BL-E001-003` — `BL-E001-002`/`003` downgraded from Critical/High after scope
correction), 1 retracted (`BL-E001-004` — not a shipped defect, see above), 2 deferred as LOW
(`BL-E001-005`, `BL-E001-006`). None promoted at epic level — both deferred items remain
genuinely low-impact, narrow-scope trade-offs.
