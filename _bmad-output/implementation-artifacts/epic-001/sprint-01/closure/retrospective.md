# Retrospective — E001 / Sprint S01

**Stories completed:** 3/3 (E001-S01-001, E001-S01-002, E001-S01-003)
**Velocity vs estimate:** Estimated 19.39–22.03 man-hours for the sprint; actual counterfactual
assessment (below) is toward the low end of that band — the fixes were smaller in scope than
the cold-start estimate assumed, but the test-suite story (1.3) surfaced more than its own
scope during implementation.

## What shipped

- **E001-S01-001** — name/pattern-based secret redaction wrapped around `_dump_settings()` /
  `_dump_config()`; 6 new unit tests.
- **E001-S01-002** — `Settings.dataPath`/`outputPath` no longer stringify `None` into the
  literal `"None"`; `app.py`'s path check now actually `sys.exit(1)`s (previously logged an
  error and silently continued). Extracted `require_existing_path()` for testability; 6 new tests.
- **E001-S01-003** — a real `pytest` suite now exists (`tests/`, previously an empty package):
  ACME v1/v2 (lowercase/uppercase) parsing, config precedence, `DockerManager` restart logic
  with a mocked client, plus a dedicated CI workflow (`test.yaml`) that fails the build on a
  test failure.

## Blockers encountered — and what they revealed

Writing tests for existing behavior surfaced four real, previously-undocumented defects, not
regressions from this sprint's own changes:

1. **Package uninmportable under any host but the console script** — `cli_args.py` parsed
   `sys.argv` at *module import time*, so importing under `pytest` crashed outright. Fixed
   with `parse_known_args()`. This blocked literally every test until fixed — it is the reason
   this sprint could not have shipped a green suite without touching a file outside the three
   stories' own listed scope.
2. **`AcmeCertificateExporter.__exportCertificate` never returned its `names` list** — every
   call returned `None`; wrapped in a resolver loop, this became `[None]`; unwrapped, it made
   `exportCertificatesForFile` return `None` outright. Verified against `git HEAD` (unchanged
   since tag `v0.1.2.0`) — a real, long-standing gap. **Scope, corrected from the first pass
   of this analysis:** certificate export to disk (writing `.pem`/`.pfx`/`.key` files) happens
   as a side effect *before* this return statement, so it was never affected — confirmed
   still working correctly. The only consumer of the missing return value is
   `DockerManager.restartLabeledContainers`, so this was only observable with the optional
   `--restart-container`/`restartContainers` feature enabled.
3. **Multi-resolver export used `list.append` instead of `list.extend`** — same scope note as
   above: would nest domain lists and break `set()`-based label matching in `DockerManager`
   once a second resolver was configured, but certificate export itself is unaffected.

Both are fixed and covered by a regression test, logged to `state/issues.yaml`
(`BL-E001-002`, `BL-E001-003`) with corrected severity (Medium, down from
Critical/High) reflecting the narrower, optional-feature-only blast radius.

**A fourth claimed defect was retracted.** A "config precedence" fix (making the config file
outrank an env var) was reverted after the maintainer confirmed the *original* order
(`CLI > env var > config file > packaged default`) was correct and already working in
production — the standard pattern for a Docker-first tool. The "documented precedence" that
fix was checked against had been written by the agent itself earlier in this same session,
never confirmed against the maintainer's actual intent. Logged as `BL-E001-004` (retracted,
not a shipped defect) — see that entry for the full account and the lesson: don't write a
spec assumption and then "fix" working code to match it without checking.

## Carry-over

None — all three stories completed within this sprint; no work deferred to a future sprint.

## Closure review findings (clean-release + adversarial, arch drift, red team)

- **Clean-release**: no dead code, no debug prints, no secrets added in the diff. Fixtures are
  clearly synthetic (`DUMMY_PRIVATE_KEY`/`DUMMY_FULLCHAIN`, explicitly labeled "not real").
- **Adversarial**: two LOW findings deferred to issues (see closure-report.md) — the redaction
  regex is pattern-based and could miss an oddly-named future secret field; `parse_known_args`
  silently swallows unrecognized CLI args in production too, which could mask a genuine typo.
  Neither blocks — both are pre-existing-shape trade-offs of a minimal, scoped fix.
- **Arch drift**: none — all changes are consistent with ADR-0001–0005 and the architecture
  spine; no new ADR needed.
- **Red team**: no unredacted secret-dump path exists elsewhere in the codebase (checked); no
  CLI flag currently carries the PKCS12 passphrase (that lands in Epic 3 Story 3.2, and will
  flow through the same now-redacted `Settings`/`_config` dump points by construction).
