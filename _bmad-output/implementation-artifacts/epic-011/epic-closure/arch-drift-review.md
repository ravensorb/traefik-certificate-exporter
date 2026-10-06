# Epic E011 — Epic-Level Architectural Drift Review (Mode B)

Date: 2026-10-06
Skill: `l3io-arch-review` Mode B, standards `references/standards-core.md` §1–10 +
`references/standards-python.md` overlay.
Scope: **epic-level** drift only — the 5 epic ADRs (0023–0027) against the final committed
diff `2213e42..434dc87` (`src`, `tests`, `docs`), which includes the sprint-01 closure fix
passes (`sprint-01-postfix.diff`) layered on top of the diff the sprint-01 closure's own
`arch-drift-review.md` reviewed. That sprint review (8 findings: 2 MAJOR, 6 MINOR, all
dispositioned in `drift-dispositions.yaml`) is **not re-litigated** here; this review looks
specifically for drift the fix passes introduced or left behind *after* that review was
written, and for cross-story integration effects visible only once all 4 stories' final
code is read together against the full ADR set.

## Executive summary

The shipped code is materially more correct and more heavily hardened than the 5 ADRs
describe: the fix passes that closed sprint-01's red-team/arch-drift findings (SIGTERM
routing, a TOCTOU-safe shutdown latch with a `drainsRun` counter, and removal of the
`./logging.yaml` auto-discovery RCE path) rewrote exactly the subsystems ADR-0023, ADR-0026,
and ADR-0003 exist to govern, and none of those ADRs was amended to match. This is the
single epic-level thread worth flagging: the epic's own governing decision records no
longer describe the mechanism that ships, even though the sprint's own closure review
praised "every load-bearing call made during the gate is ADR-recorded" — a claim that was
true of the pre-fix diff and has since lapsed. **2 MAJOR, 0 MINOR** (beyond the already-known
sprint-01 set, which is not re-raised). No BLOCKERs.

## Findings table

| # | Severity | Principle | Location | Finding | Remediation |
|---|----------|-----------|----------|---------|-------------|
| AD-1 | MAJOR | Core decision-making hook / Core §3 Design by Contract (ADR as contract) | `docs/adr/0023-export-pipeline-correlation-id-and-atomic-writes.md` (ends at Amendment 4a, line 123), `docs/adr/0026-none-safe-timer-cancellation-on-shutdown.md` (Decision, line ~45) vs. `src/traefik_certificate_exporter/libs/certificate_exporter.py::AcmeCertificateFileHandler.cancel/doTheWork/__drainWindow` (lines 794–983) and `src/traefik_certificate_exporter/app.py::install_shutdown_signal_handlers` (lines 47–71) | ADR-0023 Amendment 4a and ADR-0026's Decision describe `cancel()` as a simple `if self.timer is not None: self.timer.cancel()` no-op guard, reachable only from `KeyboardInterrupt`. The shipped mechanism is substantially different and was built during sprint-01 closure's fix passes (confirmed absent from `sprint-01.diff`, present only in `sprint-01-postfix.diff`) to close two closure findings: (1) `install_shutdown_signal_handlers` routes **SIGTERM** into the same path by raising `KeyboardInterrupt` from a signal handler — `docker stop`/`kubectl delete`/s6, not just Ctrl-C, now drive shutdown, a decision with real implications (re-raising from signal-handler context, interrupting `time.sleep`) that is not discussed in any ADR; (2) `cancel()` now reads `timer`/`draining`/`drainsRun` under a lock, decides its log message from an **observed `drainsRun` delta** taken before and after acting (not from the `armed` boolean alone), and bounds its wait with a module constant `SHUTDOWN_JOIN_TIMEOUT_SECONDS = 5` — none of `drainsRun`, the delta-based message logic, or the 5s bound appears in ADR-0023 or ADR-0026. A reader who (per this review's own scoping) treats the 5 ADRs as the governing record of this epic's shutdown/correlation design is given a materially stale and incomplete picture of the one subsystem the epic's own closure flagged as safety-critical. | Add a dated amendment to ADR-0023 (after Amendment 4a) and/or ADR-0026 recording: the SIGTERM-via-`KeyboardInterrupt` routing and its rationale, the TOCTOU fix (lock-held `drainsRun` delta replacing a plain `armed` check), and the `SHUTDOWN_JOIN_TIMEOUT_SECONDS` bound — the same discipline already used for Amendment 4a itself. |
| AD-2 | MAJOR | Core decision-making hook (boundary/trust decision unrecorded) | `docs/adr/0003-logging-stack-and-secret-redaction.md` (42 lines, no mention), `docs/adr/0023-export-pipeline-correlation-id-and-atomic-writes.md` Decision 2 (JSON console formatter) vs. `src/traefik_certificate_exporter/libs/logging_utils.py::setup_logging` (lines ~205–225) | `setup_logging` no longer auto-discovers `./logging.yaml` from the process's working directory (the container's operator-writable `/config` volume); only an explicitly-set env var or the packaged copy is honored. The in-code comment names the reason precisely: the old behavior let a single write into the mounted volume reach `logging.config.dictConfig`, which resolves arbitrary dotted names for `class:`/`()` keys — remote code execution. This is a genuine trust-boundary decision (closing an RCE path) made in the same function, and adjacent to the same env-var-selection mechanism, that ADR-0023 Decision 2 already amends — but it is recorded only in a code comment and in `docs/operational.md`'s operator-facing prose, not in any ADR. `docs/adr/0003`, the ADR that already owns "logging stack," has no reference to it at all. Confirmed absent from `sprint-01.diff`; added only in the closure fix pass (`sprint-01-postfix.diff`). | Record this as an amendment to ADR-0003 (the file that owns the logging stack's trust model) or as a new decision point under ADR-0023 Decision 2, naming the options considered (keep CWD fallback vs. remove it vs. gate it behind a flag) and the RCE rationale already present in the code comment — the content exists, it only needs to move into the ADR home. |

## Per-principle walkthrough (epic-level delta only, since standards-core §1–10 and the Python
overlay were already walked exhaustively by the sprint-01 closure review against the same
code)

- **Core §1–2, §4–8** — no new epic-level drift beyond the sprint-01 set; the fix-pass
  content (SIGTERM routing, `drainsRun` latch, logging-discovery removal) stays inside the
  module/class boundaries the sprint review already found compliant, duplicates nothing new,
  and adds no dependency.
- **Core §3 Design by Contract** — AD-1: the ADR *is* the contract for this subsystem per the
  epic's own convention (amendments 4/4a), and the final mechanism exceeds what the contract
  states.
- **Core §9 structured logging/correlation** — PASS at the epic level; SIGTERM routing and
  the `drainsRun` fix do not touch the correlation-id mechanism itself, which remains as
  ADR-0023 describes.
- **Core §10 Documentation / decision-making hook** — AD-1, AD-2. Positives: `docs/operational.md`
  documents both the SIGTERM behavior and the logging-discovery removal in operator-facing
  terms, so operators are not left in the dark — only the ADR layer, specifically, has
  lapsed behind the code.

## Gate

- **BLOCKER:** none.
- **MAJOR (must be resolved or ADR-justified before sign-off):** AD-1, AD-2. Both are
  documentation-only fixes (write the amendment) — neither requires a code change, since the
  shipped behavior in both cases is correct and tested; the gap is that the epic's ADR set no
  longer describes it.
- **MINOR:** none beyond the sprint-01 set, which is not re-raised here.

## Recommended ADRs

- **ADR-0023 amendment (AD-1)** — record the SIGTERM-to-`KeyboardInterrupt` routing decision
  and the `drainsRun`-delta/`SHUTDOWN_JOIN_TIMEOUT_SECONDS` shutdown mechanism as the actual,
  final state of Amendment 4a's subject.
- **ADR-0026 amendment (AD-1, same code, narrower ADR)** — alternatively or additionally,
  since ADR-0026 is the ADR specifically scoped to `cancel()`'s behavior.
- **ADR-0003 amendment, or a new decision point under ADR-0023 Decision 2 (AD-2)** — record
  the removal of `./logging.yaml` CWD auto-discovery and the RCE rationale.

Sections read:

- `docs/adr/0023-export-pipeline-correlation-id-and-atomic-writes.md` (full, 123 lines)
- `docs/adr/0024-atomic-write-helper-covers-pkcs12-exports.md` (full, 65 lines)
- `docs/adr/0025-strict-cli-parse-without-import-time-regression.md` (full, 62 lines)
- `docs/adr/0026-none-safe-timer-cancellation-on-shutdown.md` (full, 61 lines)
- `docs/adr/0027-vendored-tree-framing-lives-in-codeowners.md` (full, 68 lines)
- `docs/adr/0003-logging-stack-and-secret-redaction.md` (full, 42 lines — read to check for an
  AD-2-covering amendment; none found)
- `docs/adr/0014-post-export-notifications-via-apprise.md` (Status field only, per E011-S01-003)
- `_bmad-output/implementation-artifacts/epic-011/sprint-01/stories/E011-S01-001.md` (full)
- `_bmad-output/implementation-artifacts/epic-011/sprint-01/stories/E011-S01-002.md` (full)
- `_bmad-output/implementation-artifacts/epic-011/sprint-01/stories/E011-S01-003.md` (full)
- `_bmad-output/implementation-artifacts/epic-011/sprint-01/stories/E011-S01-004.md` (full)
- `_bmad-output/implementation-artifacts/epic-011/sprint-01/closure/arch-drift-review.md` (full
  — prior sprint-level findings SD-01-1…8, not re-raised)
- `_bmad-output/implementation-artifacts/epic-011/sprint-01/closure/closure-report.md` (full)
- `_bmad-output/implementation-artifacts/epic-011/sprint-01/closure/drift-dispositions.yaml` (full)
- `git diff 2213e42 434dc87 -- src tests docs` (`--stat`: 27 files, +3,567/−105)
- `src/traefik_certificate_exporter/libs/certificate_exporter.py` (full, 1,041 lines)
- `src/traefik_certificate_exporter/app.py` (full, 201 lines)
- `src/traefik_certificate_exporter/libs/cli_args.py` (full, 167 lines)
- `src/traefik_certificate_exporter/libs/logging_utils.py` (full, 280 lines)
- `_bmad-output/implementation-artifacts/epic-011/sprint-01/closure/sprint-01.diff` and
  `sprint-01-postfix.diff` (grepped for `SIGTERM`/`install_shutdown_signal_handlers` to confirm
  AD-1/AD-2's mechanisms are fix-pass additions, absent from the diff the sprint-01 arch-drift
  review scoped itself to)
- `config.sample.yml`, `docker/Dockerfile` (grepped for `CONSOLEONLY`/`CONSOLEJSON`, to confirm
  SD-01-8 is unchanged and therefore correctly not re-raised)

Blocker: 0, Major: 2, Minor: 0
