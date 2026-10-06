# Epic 011 — Sprint 01 Architectural Drift Review (Mode B)

Date: 2026-10-06
Skill: `l3io-arch-review` Mode B, standards `references/standards-core.md` §1–10 +
`references/standards-python.md` overlay.
Scope: the sprint-01 closure diff (30 files, +2,285/−63), the four sprint-01 story files, the
five epic ADRs (0023–0027), the Epic 011 arch-gate record, `docs/guidelines.md` §1/§2/§3/§5/§11,
and one spec section chosen from the spec index for an uncovered hunk
(`ARCHITECTURE-SPINE.md#ad-3--logging-structured-file-output-secrets-never-logged`).
Resolved gate items AG-1…AG-7 were read and are **not** re-raised.

## Executive summary

The sprint lands well against the standards: the correlation-id propagation (core §9) and the
atomic-write helper (core §1/§3) are single, shared mechanisms rather than duplicated ones,
every load-bearing call made during the gate is ADR-recorded (0024–0027), no dependency was
added, and the planted-failure test discipline is real rather than decorative. Drift is in the
margins: **2 MAJOR** — a shutdown latch that does not cover the one path ADR-0023 Amendment 4a
claims it covers, and a promoted finding (BL-E007-002) recorded closed while its own stated
closure condition is unmet and the required follow-up is untracked — plus **6 MINOR**. The
single most important action is to close the `doTheWork` shutdown-latch gap (SD-01-1), because
the ADR amendment written this sprint asserts the property the code does not enforce.

## Findings table

| # | Severity | Principle | Location | Finding | Remediation |
|---|----------|-----------|----------|---------|-------------|
| SD-01-1 | MAJOR | Core §3 Design by Contract (invariant asserted but not enforced); Core §4 | `src/traefik_certificate_exporter/libs/certificate_exporter.py` — `cancel()` and `doTheWork()` (sprint-01.diff, `certificate_exporter.py` hunks @@ -461,7 / @@ -476,29) | ADR-0023 Amendment 4a states `cancel()` "latches a shutdown flag, so neither a late watchdog event nor the drain's own re-arm path can start a new pass after shutdown has begun." Two of three paths are guarded (`handleEvent` checks `shuttingDown`; `__rearm` checks it). The third is not: `cancel()` reads `timer`/`draining`/`armed` inside one critical section and then acts **outside** the lock, so an armed timer that fires in that window makes `timer.cancel()` a documented no-op, and `doTheWork` — which performs no `shuttingDown` check at entry — runs a full export pass (export + 30s hook + Apprise delivery) after shutdown began, while `cancel()` logs "cancelled the pending export drain" for a pass that in fact ran. That log line is exactly the "truncated run distinguishable from a clean exit" signal E011-S01-004's Observability AC asks for, and in this race it is wrong. Blast radius is bounded by the atomic writes and by the drain thread now being a daemon, so this is a correctness/observability gap, not a corruption one. | Have `doTheWork` re-check `shuttingDown` under `self.lock` at entry (it already takes the lock to set `draining`) and return without draining when the latch is set; log that abandonment at WARNING with the window's id. Alternatively hold `self.lock` across the `timer.cancel()` call in `cancel()` so the arm/fire transition cannot interleave. Add a test that fires the timer concurrently with `cancel()` and asserts no export ran. |
| SD-01-2 | MAJOR | Core §10 Documentation (docs vs. reality; a closed item must be traceable to its closure condition) | `_bmad-output/.../stories/E011-S01-001.md` (`status: done`, Context → BL-E007-002); `docs/operational.md` new section "What a local `docker/act-build.sh` run reports (BL-E007-002)" (sprint-01.diff, `docs/operational.md` @@ -422,6) | BL-E007-002's own closure condition, quoted in the story's Context, is "an actual green run whose result is retained." The retained evidence records a run that failed at the **first step of the first job** (`actions/checkout` rejecting the local-clone `origin`), states the verifier is "not yet green end to end," and states "Closing that needs a change to the wrapper's clone/mount strategy, not a rerun." No change to `docker/act-build.sh` is in the diff, and the diff records no backlog/issue id for the wrapper change the evidence says is required. The story is nevertheless `status: done`. A reader of the closure record cannot tell that an identified, unscheduled repository change still stands between this sprint and the finding's stated closure. | Either reopen/retitle the BL-E007-002 half as partially closed, or (preferred, cheaper) record the wrapper clone/mount change as a numbered backlog item (`BL-E011-xxx`) referenced from both `docs/operational.md`'s new section and the story's completion record, so the residue is tracked rather than narrated. |
| SD-01-3 | MINOR | Core §2 Reuse over copy-paste | `libs/post_export.py` (`run_post_export_command`), `libs/notify.py` (`send_export_notifications`), `libs/certificate_exporter.py` (`__logEvent`, `doTheWork`, `cancel`) | The same five-line `token = set_correlation_id(... or get_correlation_id()) / try: ... / finally: reset_correlation_id(token)` bind-and-restore block is now written out at five call sites (three modules). Two occurrences may wait; five is the duplication smell §2 names, and each copy is an independent chance to forget the `finally`. | Add one `@contextlib.contextmanager correlation_context(correlation_id: str | None)` to `logging_utils.py` beside `set_/reset_correlation_id` and use `with correlation_context(...):` at all five sites. The primitive is already there; only the wrapper is missing. |
| SD-01-4 | MINOR | Core §3 Design by Contract; Core §4 Testability (hidden process-global state) | `libs/certificate_exporter.py` — `_default_file_mode()` (sprint-01.diff, new helper block) | The helper probes the umask with `current = os.umask(0o022); os.umask(current)`. `os.umask` is process-global, so on the very first call any other thread creating a file in that window gets `0o022` applied rather than the real umask — the exact hazard the surrounding comment identifies and then only partially mitigates (the lock serialises *this* function, not unrelated file creation). Also `except (PermissionError, OSError)` on the `os.chown` restore is redundant (`PermissionError` is an `OSError`), reading as a wider contract than it is. | Prefer a non-mutating source for the target mode — e.g. derive the mode from an `open(..., "w")`-created probe file in the destination directory once, or accept `0o644`/`0o600` as an explicit declared default recorded in ADR-0023's security bullet — and narrow the `chown` handler to `OSError`. |
| SD-01-5 | MINOR | Core §10 Documentation (spec contradicts shipped code) | Spec section opened for the uncovered logging hunks: `_bmad-output/planning-artifacts/architecture/architecture-traefik-certificate-exporter-2026-08-30/ARCHITECTURE-SPINE.md#ad-3--logging-structured-file-output-secrets-never-logged` (L73–83) vs. `libs/logging_utils.py`, `logging.yaml`, `libs/post_export.py` | AD-3's rule, which "binds every logging call site," still states: "No cross-process correlation ID — single-process tool, nothing to correlate across." This sprint adds a correlation id to every record *and* exports it across a process boundary into the post-export hook as `TRAEFIK_CERTIFICATE_EXPORTER_CORRELATION_ID`. The decision is properly recorded (ADR-0023), so this is not an unjustified deviation — but the binding spine section now asserts the opposite of the shipped behaviour, and the spine is what a future story reads first. (Distinct from deferred AG-6/BL-E011-001, which concerns the ADR-0003 reciprocal amendment, not the spine.) | Amend AD-3's rule text to record the intra-process-plus-hook correlation id and cite ADR-0023, keeping the cross-process/distributed-tracing deferral explicit as a separate clause. |
| SD-01-6 | MINOR | Core §4 Testability / §5 Readability (I/O under a lock) | `libs/certificate_exporter.py` — `handleEvent` (sprint-01.diff, @@ -400,8 / @@ -411,25) | The "Certificates changed found in file" INFO line used to be emitted before `with self.lock:`; it is now emitted from `__logEvent` **inside** the critical section, on watchdog's dispatcher thread, and the handler's sink includes a rotating file handler (rotation can block). Every other event in a burst, plus `cancel()`'s state read, now waits behind that I/O. The correlation requirement did not force this: the id is available before the lock is needed for the `pendingPaths` mutation. | Capture `(path, correlationId)` inside the lock and emit the log line after releasing it, or document in the method why logging must be serialised with the pending-path mutation. |
| SD-01-7 | MINOR | Core §6 Comments describe current state (stale/contradicting number) | `tests/ci/test_gates.py` — vendored-tree section header comment ("They are 2,354 tracked files…") vs. `.github/CODEOWNERS` header ("142 of the 2,364 files… The other 2,222") | Two numbers for the same trees, 10 apart, land in the same commit. The CODEOWNERS figures are recomputed and gate-enforced by `test_the_vendored_integrity_guard_records_what_it_cannot_verify`; the test-module comment's figure is enforced by nothing, so it is a stale comment from the moment the trees change — the drift `docs/guidelines.md` §11's "it expires" clause explicitly warns against. | Drop the literal count from the test comment (say "every file in both trees") or make it say which population it counts (tracked vs. on-disk) and point at the gate that keeps CODEOWNERS honest. |
| SD-01-8 | MINOR | Core §10 Documentation (docs contradict shipped configuration) | `config.sample.yml` new trailing comment vs. `docker/Dockerfile` runtime `ENV` block (both in sprint-01.diff) | The sample config, which is what the image seeds into `/config`, tells the reader "Both switches are opt-in and default to off" and lists `…LOGGING_CONSOLEONLY=true`. The shipped container sets `TRAEFIK_CERTIFICATE_EXPORTER_LOGGING_CONSOLEONLY=true` in the same diff, so for every container user exactly one of the two switches is on by default. Related: the new `CONSOLEJSON` switch is read directly via `os.getenv` in `logging_utils.py` and never reaches the `confuse` layer, so unlike every other setting it cannot be set in `config.yaml` or via a CLI flag (`docs/guidelines.md` §5 "all three input modes are first-class"). The reason — logging is configured before the config file is read — is sound and is stated in the comment; the precedence exception is not recorded anywhere decision-shaped. | Reword the sample comment to "off by default in the PyPI/console invocation; the container image sets `CONSOLEONLY=true`", and add one sentence to ADR-0023 Decision 2 recording that the logging switches are deliberately env-only and therefore outside the §5 CLI/env/file precedence rule. |

## Per-principle walkthrough

**Core §1 Separation of concerns** — PASS. `app.py` stays a thin orchestrator: the sprint
explicitly moved the `timer is None` invariant into the class that owns it (`cancel()`,
ADR-0026) rather than guarding at the call site. Correlation-id plumbing lives in
`logging_utils.py`; the exporter imports it rather than re-implementing a thread-local. The
atomic-write helper is private to the module that writes certificates. No transport/ORM type
crosses a boundary. Module-level `globalLogger`/`globalArgs`/`globalSettingsMgr` are the
project's recorded convention, not drift.

**Core §2 Reuse over copy-paste** — SD-01-3. Counter-evidence in the sprint's favour: the ten
write sites collapse to one helper (`_atomic_write`) with two one-line wrappers rather than ten
copies, and `_vendored_trees()`/`_pre_commit_exclude()` derive the excluded trees from
`.pre-commit-config.yaml` instead of restating them a third time.

**Core §3 Design by contract** — SD-01-1 (primary), SD-01-4. Positives: `parse_args_strict()`
has an explicitly documented contract (`SystemExit(2)`, names the flag) and is tested end-to-end
through a real subprocess; `_atomic_write`'s docstring states the same-filesystem precondition
and the test `test_the_temp_file_is_created_next_to_its_target` asserts it; the degrade-never-fail
contract for a missing correlation id is stated and tested on both downstream hops.

**Core §4 Testability** — SD-01-1, SD-01-4, SD-01-6. Otherwise strong: every safety property
added this sprint is proved by an injected fault rather than a clean run (`os.replace` and
`os.fsync` made to raise, a planted untracked file in a throwaway real git repo, a planted
CODEOWNERS count drift, a slow drain released by an `Event`), which is the repo's own stated
rule honoured rather than cited.

**Core §5 Brevity without sacrificing readability** — PASS with the SD-01-4 redundancy noted.
Comment density is high but §11 of `docs/guidelines.md` makes defect-provenance comments a
recorded deviation, and each one here leads with the invariant before the history, which is the
limit §11 sets.

**Core §6 Comments explain current state** — SD-01-7. No changelog-in-comments beyond what §11
sanctions; the `# noqa: F401 -- see main()` and the `global globalArgs` comment in `app.py`
explain a genuinely non-obvious import that would otherwise be "cleaned up" into a regression.

**Core §7 Dependency selection** — PASS. Zero dependencies added. Everything new is stdlib
(`contextvars`, `uuid`, `tempfile`, `hashlib`, `json`); the story's existing-library check
explicitly rejected `atomicwrites` and `deepdiff` in favour of stdlib equivalents.

**Core §8 GA over alpha/beta** — PASS. No preview/RC dependency, no preview runtime feature;
`contextvars` and `logging.setLogRecordFactory` are long-GA, and `_apply_console_json` is
documented as deliberately avoiding any API newer than the project's 3.10 floor.

**Core §9 Unified structured logging with correlation** — PASS, and this is the sprint's
subject. One UUID4 per pass, stamped on **every** record via a record factory (chosen over a
handler filter precisely so a formatter can never raise on a missing attribute), carried across
the three hops `contextvars` cannot cross on its own (timer thread via an explicit argument,
subprocess via env var, notification via parameter), with the re-arm case minting a new id and
logging both so the halves stay joinable. The `-` placeholder marks out-of-pass lines. The one
residue is SD-01-5 (the spine still denies this exists) and SD-01-1 (one log line can mislabel a
race).

**Core §10 Documentation** — SD-01-2, SD-01-5, SD-01-8. Positives: `README.md` gains a
"Logging and tracing an export pass" section, `docs/operational.md` gains a runnable `jq`
recipe, an explicit shutdown-semantics section and a frank negative-result record for the local
verifier, and five ADRs carry the decisions. No new diagram was warranted — the sprint adds no
new component or boundary, only a field and a write primitive.

**Python overlay — packaging & environment** — PASS. Poetry unchanged, `poetry.lock` untouched
and still the single source (ADR-0001/AD-1); no `pip install`, no `requirements.txt`, no
`setup.py`. The new pre-commit text is a comment on the existing `workflow-policy` hook, not a
parallel install path.

**Python overlay — version & runtime** — PASS. Nothing added requires above the declared 3.10
floor; `_apply_console_json`'s comment shows that floor was actively checked.

**Python overlay — quality toolchain** — PASS with a note. `ruff` clean per the story
verification records; type hints are present on the new public surfaces
(`parse_args_strict() -> argparse.Namespace`, `_atomic_write(target: Path, data: str | bytes)
-> None`, `cancel(self) -> None`). `mypy`/`pyright` remains unwired — `docs/guidelines.md` §1
records that as a deliberate "not yet," so it is not drift introduced here. `set_correlation_id`
and `doTheWork` return/accept untyped tokens and `*args, **kwargs`; acceptable, but they are the
two places a future strict-typing pass will have to start.

**Python overlay — logging** — PASS. stdlib `logging` + `pythonjsonlogger` + `contextvars`, i.e.
exactly the overlay's prescribed shape; no `print` anywhere in the diff; secret redaction is
extended, not weakened (two new nested-list redaction cases).

## Gate

- **BLOCKER:** none.
- **MAJOR (must be resolved or ADR-justified before sign-off):** SD-01-1, SD-01-2.
  SD-01-1 is a code change, not an ADR candidate — ADR-0023 Amendment 4a already decided the
  behaviour; the code is short of it. SD-01-2 is closable with a tracked backlog id.
- **MINOR (auto-defer to backlog):** SD-01-3, SD-01-4, SD-01-5, SD-01-6, SD-01-7, SD-01-8.

## Recommended ADRs

- **None required for SD-01-1** — ADR-0023 Amendment 4a is the governing record; it needs
  enforcement, not a new decision. If the race is instead *accepted* (on the grounds that atomic
  writes bound the damage), that acceptance must be written into Amendment 4a, since its current
  wording asserts the stronger property.
- **ADR-0023 Decision 2, one-sentence amendment (SD-01-8)** — record that the logging switches
  (`LOGGING_CONSOLEONLY`, `LOGGING_CONSOLEJSON`) are deliberately env-var-only and therefore sit
  outside the CLI > env > file precedence that `docs/guidelines.md` §5 and the spine's
  Consistency Conventions make universal, because logging is configured before the config file
  is read.
- **Spine amendment, not an ADR (SD-01-5)** — AD-3's "no cross-process correlation ID" clause is
  stale; the decision already exists in ADR-0023 and only needs to be reflected in the binding
  spine section.

Sections read:

- `.claude/skills/l3io-arch-review/SKILL.md` (full, 101 lines)
- `.claude/skills/l3io-arch-review/references/review-report.md` (full, 31 lines)
- `.claude/skills/l3io-arch-review/references/standards-core.md` (full, §1–10, 169 lines)
- `.claude/skills/l3io-arch-review/references/standards-python.md` (full, 43 lines)
- `_bmad-output/implementation-artifacts/epic-011/sprint-01/closure/sprint-01.diff` (full, 2,927 lines, 30 files)
- `_bmad-output/implementation-artifacts/epic-011/sprint-01/stories/E011-S01-001.md` (full, 160 lines)
- `_bmad-output/implementation-artifacts/epic-011/sprint-01/stories/E011-S01-002.md` (full, 245 lines)
- `_bmad-output/implementation-artifacts/epic-011/sprint-01/stories/E011-S01-003.md` (full, 206 lines)
- `_bmad-output/implementation-artifacts/epic-011/sprint-01/stories/E011-S01-004.md` (full, 215 lines)
- `docs/adr/0023-export-pipeline-correlation-id-and-atomic-writes.md` (Amendment 4a + Consequences, via diff hunk @@ -83,6; 123 lines total)
- `docs/adr/0024-atomic-write-helper-covers-pkcs12-exports.md` (full, 65 lines)
- `docs/adr/0025-strict-cli-parse-without-import-time-regression.md` (full, 62 lines)
- `docs/adr/0026-none-safe-timer-cancellation-on-shutdown.md` (full, 61 lines)
- `docs/adr/0027-vendored-tree-framing-lives-in-codeowners.md` (full, 68 lines)
- `_bmad-output/implementation-artifacts/epic-011/arch/arch-gate-review.md` (full, 53 lines — AG-1…AG-7 and the resolution record, read to avoid re-raising resolved items)
- `docs/guidelines.md` lines 1–60 (§1 Python best practices, §2 Package management, §3 Logging, §5 Configuration) and lines 188–213 (§11 Defect provenance deviation); heading index for the full file
- `_bmad-output/implementation-artifacts/spec/spec-index.md` lines 1–3 and 24–51 (architecture + prd section listings)
- `_bmad-output/planning-artifacts/architecture/architecture-traefik-certificate-exporter-2026-08-30/ARCHITECTURE-SPINE.md` lines 40–116 (Invariants & Rules, AD-1…AD-5, Consistency Conventions) — the one spec section opened for the otherwise-uncovered logging/correlation-id hunks, selected from the spec index as `#ad-3--logging-structured-file-output-secrets-never-logged`

Blocker: 0, Major: 2, Minor: 6
