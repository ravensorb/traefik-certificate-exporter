# Epic 011 — Architecture Gate Review

Date: 2026-10-06
Scope: 4 story files (E011-S01-001..004), ADR-0023
Reviewers run: `l3io-arch-review` (Mode B), `bmad-agent-architect` (escalated — first pass
raised 2 MAJOR findings; per §4 escalation rule, both reviewers ran on the same bounded inputs)

## Consolidated findings

| ID | Severity | Finding | Source(s) |
|----|----------|---------|-----------|
| AG-1 | MAJOR (confirmed) | E011-S01-004's Technical AC enumerates exactly 8 `Path.open("w")` call sites in `certificate_exporter.py` to convert to atomic `tempfile`+`os.replace` writes, but omits the two PKCS12 `.pfx` export sites (`PemToPfxConverter.export_to_pkcs12` → `Path(filename).write_bytes(pkcs12_bytes)`, line 334, fed from the `.pfx` path construction at lines 143/172). That call is truncate-then-write with no atomicity — exactly the hazard the story's own Business AC ("every certificate file on disk either fully in its previous state or fully in its new state — never zero-length or partial") and BL-E010-002 describe. `.pfx` is a certificate file by the story's own definition. | l3io-arch-review, bmad-agent-architect |
| AG-2 | MAJOR (confirmed) | E011-S01-003's Interface Contracts instruct relocating `globalArgs, _ = globalArgParser.parse_known_args()` out of module-import scope in `cli_args.py` into a `main()`-only strict call. `app.py` line 15 does `from .libs.cli_args import globalArgs` at module-import time, used inside `main()` at lines 39/44/47. A literal implementation of the stated interface contract removes the import-time assignment and makes that import raise `ImportError` before `main()` ever runs. The story does not address updating `app.py`'s import to match the new strict/lenient split. | l3io-arch-review, bmad-agent-architect |
| AG-3 | MAJOR (flagged, single-source) | E011-S01-004's planned `app.py` change (`event_handler.timer.cancel()` in the `KeyboardInterrupt` handler) raises `AttributeError` on `None.cancel()` whenever shutdown occurs before any watched-file event has fired: `AcmeCertificateFileHandler.__init__` sets `self.timer = None` (line 377), only reassigned inside `handleEvent`/`__rearm` (lines 422, 486). The story's Error/Edge-Case section reasons about the "already fired" `Timer.cancel()` no-op case but never the "never armed" (`None`) case — the common manual-test path (start, Ctrl-C immediately) — directly contradicting the story's own "must not raise" requirement. Independently verified against source (`self.timer = None` at line 377, handler at app.py lines 93-97). | bmad-agent-architect |
| AG-4 | MAJOR (flagged, single-source) | E011-S01-002's Context quotes `docs/guidelines.md` as currently stating the vendored `.agents/`/`.claude/` trees are skills "this project neither authors nor maintains." That exact phrase does not exist in `docs/guidelines.md` (verified: no match). The matching language ("READ its entire contents and follow its directions exactly", "excluded from the linting gates") actually lives in `.github/CODEOWNERS`'s header comment. The story's Interface Contracts instruct updating "the vendored skills, not maintained by us" framing specifically in `docs/guidelines.md` — an implementer searching that file for the cited prose will not find it; the AC's target file is wrong. Independently verified (grep confirms absence in guidelines.md, presence in CODEOWNERS). | bmad-agent-architect |
| AG-5 | MINOR (confirmed, deferred) | E011-S01-003 and E011-S01-004 both edit `app.py`'s `main()` (disjoint regions today — arg-parsing near the top, `KeyboardInterrupt` handler near the bottom) despite the epic's "no cross-story dependencies" framing. Low-risk sequencing/merge-order note. | l3io-arch-review, bmad-agent-architect |
| AG-6 | MINOR (single-source, deferred) | ADR-0023 states it "amends ADR-0003's threading-model assumption," but neither E011-S01-004's Interface Contracts nor Non-goals lists `docs/adr/0003-logging-stack-and-secret-redaction.md` as a file to touch, despite E011-S01-001 establishing the repo's own reciprocal-amendment convention (an "## Amended at <date>" subsection in the amended ADR itself, per ADR-0008 line 107). | bmad-agent-architect |
| AG-7 | MINOR (single-source, deferred) | E011-S01-001 and E011-S01-002 both cite `tests/ci/test_gates.py` in their Interface Contracts without stating which (if either) actually adds a function there — low risk, worth a one-line sequencing note. | bmad-agent-architect |

## Gate outcome

4 blocking findings (AG-1..AG-4, all MAJOR — 2 confirmed, 2 single-source-flagged; none
downgraded per the consolidation rule). Execution blocked pending ADR resolution.

3 MINOR findings (AG-5..AG-7) deferred to the issues file — not gate-blocking.

## ADR resolution and re-validation (2026-10-06)

ADR numbers 0024-0027 reserved as a single batch and pre-assigned 1:1 to AG-1..AG-4 before
dispatch (per the no-self-selection rule). All 4 ADRs written and the affected story files
patched:

| Finding | ADR | Story patch |
|---------|-----|--------------|
| AG-1 (pfx atomicity) | `docs/adr/0024-atomic-write-helper-covers-pkcs12-exports.md` | E011-S01-004 |
| AG-2 (globalArgs ImportError) | `docs/adr/0025-strict-cli-parse-without-import-time-regression.md` | E011-S01-003 |
| AG-3 (timer None) | `docs/adr/0026-none-safe-timer-cancellation-on-shutdown.md` | E011-S01-004 |
| AG-4 (guidelines.md misattribution) | `docs/adr/0027-vendored-tree-framing-lives-in-codeowners.md` | E011-S01-002 |

Re-validation dispatched to both original reviewers, narrowed to only the 4 ADRs + patched
story sections (not a full re-review). Both reviewers independently returned
`RESOLVED` for all 4 findings. `bmad-agent-architect` additionally flagged a residual
inconsistency: E011-S01-002's Business-AC Outcome bullet (not the Interface Contracts
bullet ADR-0027 explicitly scoped the original patch to) still cited `docs/guidelines.md`
post-patch. Corrected directly (one-line fix, same file) to cite `.github/CODEOWNERS` per
ADR-0027 — no new ADR needed, this was a same-finding completeness gap, not a new finding.

3 MINOR findings (AG-5..AG-7) appended to the issues file as BL-E011-003 (AG-5, app.py
`main()` sequencing), BL-E011-001 (AG-6, ADR-0023/0003 reciprocal-amendment gap), and
BL-E011-002 (AG-7, `test_gates.py` ambiguous citation).

**Gate status: CLEAR.** All 4 blocking MAJOR findings resolved and re-confirmed resolved
by both reviewers. 0 blocking findings remain.
