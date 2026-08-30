# Epic Closure Retrospective — E003: Predictable, Documented Configuration

**Velocity:** 2/2 stories done in a single sprint (S01) — no carry-over.

**What this epic actually validated:** the story's own stated root cause for
E003-S01-001 was not the full picture. Reproducing the reported GitHub #5 symptom live,
against the real `SettingsManager`, before writing any fix surfaced the actual defect —
`confuse`'s nested-dict `.get()` silently drops sibling keys from lower-priority sources,
which is a sharper bug (an outright `KeyError` crash) than the "missing validation check"
the story assumed. Both the real bug and the story's originally-assumed gap are now fixed.

**Process note:** when challenged on why a custom comma-split parser was needed instead of
a `confuse`-native mechanism, checking the library's actual source (not just prior
assumptions) surfaced that `confuse` does support real array env vars, via a different,
incompatible indexed-suffix syntax. Kept the project's existing comma-separated convention
deliberately, to avoid a breaking change for anyone already using it — not because
`confuse` lacks list support outright. Lesson recorded in agent memory
(`confuse-library-notes.md`).

## Architectural drift review (epic-level, work_type=CODE)

Single sprint, so epic-level scope matches sprint-level review already performed. The fix
follows the existing settings-loading pattern (module-level `confuse.Configuration`,
leaf-level `.get()` calls) with no new abstraction introduced. No new ADR required.

## Epic security review (work_type=CODE)

No secrets or new attack surface introduced; the PKCS12 passphrase CLI flag reuses Epic 1's
existing name-pattern-based redaction with no code change. No CRITICAL/HIGH/MEDIUM findings.

## Issue triage

0 new issues logged — both defects were fully fixed within the sprint, not deferred.
