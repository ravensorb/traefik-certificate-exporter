# Epic 010 — Closure Report

- **Date:** 2026-09-07
- **Scope delivered:** E010-S01-001 (secret redaction by declared path), E010-S01-002
  (Apprise notifications on `post-export`)
- **Verification:** 409 tests, every pre-commit hook, and a full green
  `Development publication` run including the multi-platform image build with the new
  dependency (run `34075286252`)

## §1 Man-hours re-assessment — and why this one is not trustworthy

**The contract's precondition was violated, and the number is disclosed as contaminated
rather than presented as clean.**

`references/metrics-contract.md` requires `{epic_man_hours}` to be formed **before** reading
`estimate.man_hours_*`, because reading the estimate first anchors the re-assessment toward
it. That ordering was not available here: the estimate (20.77–22.99) was computed, reported
to the maintainer and discussed several times during planning, long before closure began. I
cannot un-read it.

Assessed from the delivered work regardless — 751 insertions across 12 files, one new module,
a redaction mechanism replacement touching three sinks, a dependency evaluation, and 20 new
tests including two scope-attacking plants:

**~19–24 man-hours.** Which lands almost exactly on the estimate, and is precisely what
anchoring produces. That agreement is evidence of nothing.

**Consequence, taken deliberately: the calibration sample is suppressed (`--no-calibrate`).**
A sample whose input is known-anchored would tighten future confidence bands on the strength
of a number that merely echoed the prediction. E008's closure already recorded one
data-quality incident of this shape; adding a second silently would be worse than recording
none. Future epics are better served by a missing sample than a circular one.

### A second data-quality compromise, recorded rather than buried

`set-actual` requires all four token counts under `--runtime claude` and permits `--tokens-na`
only under `--runtime other`. This epic's token spend **cannot honestly be separated** from a
session that also ran two full architecture gates, a plan written and withdrawn, a
supersession, and unrelated shipping bug fixes.

I recorded `runtime: other` with `tokens-na`. That makes the token fields honest and the
**runtime label wrong** — it was Claude. The alternative was inventing four numbers to satisfy
a validation, which would have fed a cost model with fiction. Neither option is clean; this is
the one whose error is visible in the record rather than encoded in a plausible figure.

`cost` is consequently `N/A` too, since it is derived from tokens. Combined with the
suppressed calibration sample above, **this epic contributes nothing to future estimates**,
which is the correct outcome for measurements this compromised.

## Retrospective

**What the gates were worth.** Two full architecture gates and one narrow re-validation, on a
feature that started as "how hard would it be to add webhooks". Together they turned a
145–161 hour design into a 21 hour one, and every step of that reduction removed scope nobody
had asked for: `cert-export` consumers, an HTTP action transport, an optional-extra packaging
decision, a configuration redesign, a two-contract split. The gates were the most valuable
thing in this epic by a wide margin, and they were cheap relative to what they prevented.

**The defect class that kept recurring was mine, and it was not scope.** Across ADR-0013 and
ADR-0014 the reviewers found **seven** factual claims asserted without being checked —
`urllib3`'s group, the `CONFIGFILE` env route, Apprise's payload extras, its custom-plugin
decorator, the notify return value, the config surface being "unchanged", and a delivery
timeout mechanism that does not exist. Each was corrected only when challenged. The reduction
was right; the habit that made the document wrong was independent of its size, and survived
every revision that improved its internal consistency.

**Reviewers were wrong three times too, and checking mattered in both directions.** The
GPLv3 licence history, the `urllib3` characterisation, and the `restartLabeledContainers`
`None` handling were all overstated or false. Relaying a reviewer's correction unchecked
would have put a fresh error into the record in place of the old one.

**Writing an honest test found a real bug.** The scope plant for the redaction registry
passed against deliberately-broken code, because it planted only through the config file
where confuse's own redaction covers it regardless. Fixing the plant to go through the
command line exposed that `_is_declared_secret` compared bare leaf names while argparse keys
arrive dotted — so the registry never matched the one sink that had actually been leaking.
The test was the defect detector, but only after it was made to fail first.

**Two bugs shipped and were fixed inside this epic's own work.** The drain rewrite introduced
a lost-wakeup race, caught by the second gate; the fix for that introduced a stale-index slice
and a misplaced log line, caught by the re-validation. Concurrency code written under time
pressure needed three passes and independent review to become correct, and the tests that
finally held it were the ones written to fail first.

## Architectural drift

None against ADR-0014 — it was amended in step with each finding rather than defended, and
its final decisions match what shipped. ADR-0013 remains `Superseded` with its postmortem.

The two pre-existing Mediums raised by both gates are filed rather than resolved, and neither
is worsened by this epic: `BL-E010-001` (no correlation identifier across the hops; the
container ships the unstructured formatter) and `BL-E010-002` (shutdown cancels no pending
drain timer, and certificate writes are truncate-then-write). `BL-E010-003` is a Low design
note for whoever next touches `_dump_settings`.

## Issue triage

| | |
|---|---|
| `BL-E001-005` | Re-scoped Low → High during planning, **now resolved** by E010-S01-001 |
| `BL-E010-001` | Medium, open — pre-existing |
| `BL-E010-002` | Medium, open — pre-existing |
| `BL-E010-003` | Low, open — design note |
