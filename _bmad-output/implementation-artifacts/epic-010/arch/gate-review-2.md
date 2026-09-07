# Epic 010 — Architecture Gate Review (second pass, ADR-0014)

- **Date:** 2026-09-06
- **Reviewed:** ADR-0014 (Proposed), story E010-S01-001, and the `fix(watch):` commit
- **Reviewers run:** `l3io-arch-review` (Mode B), alone — the other two remain uninstalled
- **Verdict:** **BLOCKED** — 3 BLOCKER, 10 MAJOR, 10 MINOR

## What the reduction achieved

Eight of the first gate's eighteen blocking findings are **genuinely gone**, because the
feature that caused them is gone: the two-contract split, the `cert-export` payload contract,
the duration test, the image-guard scope, the thread model, the dry-run gap, the ceiling
rationale, the env-var hyphen grammar. The reviewer accepted those as legitimately closed
rather than relocated, and separately verified ADR-0014's optional-extra reasoning as correct.

Five survive in a new shape, and are counted below rather than claimed as wins.

## Independently re-verified before acceptance

| Claim | Verdict | Evidence |
|---|---|---|
| The new drain has a lost-wakeup race | **CONFIRMED** | `break` exits the `with` — releasing the lock — before `finally` re-acquires it to clear `isWaiting`. An event in that gap is recorded, sees the flag set, arms no timer, and is orphaned when the flag clears. Reproduced deterministically by a test that now fails against the previous commit. **My defect, one hour old.** |
| `settings.py` logs the raw argparse namespace | **CONFIRMED** | `Command Line Args: {cmdLineArgs}` at DEBUG, and `--pkcs12-passphrase` is a flag. Printed verbatim a few lines above the dump helpers that mask that exact field. A live credential leak, older than this epic. |
| `confuse` already ships a path-based redactor | **CONFIRMED** | `c['settings']['appriseurls'].redact = True` then `c.dump(redact=True)` emits `appriseurls: REDACTED`. This is exactly the value-shaped mechanism ADR-0014 declares unreachable — **the library ships the answer and the ADR proposed superseding a hand-rolled one without checking.** Global rule 1, missed by me again. |

## Fixed in this pass — shipping code, not epic work

Two of the three BLOCKERs were defects in code that ships today and do not depend on the
design, so they were fixed as bugs — the same split that was correct for the first gate's two.
Commit `fix(watch,settings):`, ten new tests, all failing against the previous commit.

Getting the race test right took two attempts. The first fired its injection immediately after
`clear()`, where the next drain iteration legitimately collects it — so it passed against the
buggy code and proved nothing. **That is the same "asserts a proxy" fault the reviewer had just
found in the earlier tests, repeated while fixing it.** It now fires on the release following a
genuinely empty observation.

## Outstanding — plan-level, not yet actioned

**BLOCKER 2 — ADR-0014 Decision 3 is false.** "The current `config.yaml` and the
`TRAEFIK_CERTIFICATE_EXPORTER_` env convention address it unchanged" does not hold for a
list-valued setting: `_parse_domain_list` exists in this repository *because* confuse does not
parse that shape from the environment, and its own comment says so. Worse, the documented
comma-separated convention is unsafe here — a comma is legal inside an Apprise URL
(`mailto://…?to=a@x.com,b@y.com`), so splitting on it silently fragments one destination into
two malformed ones. This is the first gate's "re-derive §5 against the code" item, asserted
again rather than re-derived.

**MAJOR (10), in brief.** Delivery is unbounded where the analogous hook has an explicit 30s
timeout — "fire-and-forget" is being used to mean "non-blocking", and it is not · the payload is
"every domain in the file", never "what changed", and the image defaults mean every container
restart notifies · two emission sites with different pass scopes remain, un-ACed · `issues.yaml`
still tells an implementer to extend the pattern list that ADR-0014 says needs superseding —
prose and machine-readable record now disagree, and the record is what gets read · no version
floor or licence recorded for a dependency that now genuinely ships, and Apprise was **GPLv3**
through 1.8.x before relicensing at 1.9.0, which matters for an MIT project shipping an image ·
the redaction guard's scope is hand-enumerated, the repository's signature defect · one story is
now too small, because the redaction half is a security fix plus a mechanism replacement folded
into a single AC · no correlation identifier, and the container's only sink is the unstructured
formatter · `confuse.redact` unevaluated (above) · tests assert a proxy (fixed).

## Reviewer's ordered path

1. Fix the drain race and its missing tests as a bug — **done**
2. Split redaction into its own story and land the passphrase leak with it — **leak fixed**;
   the split is a maintainer decision
3. Re-derive Decision 3 against `settings.py:44-58`; record the Apprise floor and licence

## Recommended ADRs

Watch-handler drain and debounce invariant (settles the queuing decision the first gate asked
to be settled rather than deferred) · secret redaction for value-shaped credentials, with
`confuse.redact` as an adopt-or-reject under global rule 1 · list-valued configuration encoding
where the value may contain the separator · the Apprise dependency record · notification
semantics: export-pass versus certificate-change, pass scope per site, delivery timeout, and
ordering against `restartContainers`.

## Note on the pattern

Two gates, two designs, and in both the reviewer's most valuable findings were **factual claims
I asserted without checking** — three in ADR-0013, three more here, one of them a library
facility that made a whole section of the ADR unnecessary. The reduction from 145 hours to 10
was right and the gate confirmed it. What the gate keeps catching is not scope. It is that I
write confident sentences about code and libraries without running them first.

---

## Re-validation (2026-09-06) — narrow, per §6

Not a re-gate. The reviewer received only the changed items and the finding each was resolving.

**6 RESOLVED · 1 PARTIAL · 0 NOT RESOLVED · 0 BLOCKER remaining.**

Resolved: the drain race (flag now published in the same critical section that observes the queue
empty; both tests confirmed genuine reproductions rather than proxies) · the argparse passphrase
leak (asserted over all captured records, not one call site) · Decision 3, re-derived and
re-run by the reviewer against `confuse 2.2.1` — a comma-bearing `mailto://` URL survives indexed
env keys intact · `confuse.redact` adopted with a registry-derived guard scope · the Apprise
record · the story split · `issues.yaml` now agreeing with the ADR.

**The reviewer retracted its own GPLv3 finding** after checking PyPI: MIT through ~1.2.x, BSD from
~1.6.0, never copyleft. Recorded because a review that cannot correct itself is not worth running
twice.

**The PARTIAL, now closed.** Decision 6 said "a fixed delivery timeout is set" while naming no
value and no mechanism — the same fault that forced Decision 3's rewrite, committed again in the
same document. Read at 1.13.1: `Apprise.notify()` takes no timeout at all; bounding is per
destination via `request_timeout` → `(socket_connect_timeout, socket_read_timeout)`, defaulting
to 4.0 s each and settable as `cto`/`rto` per URL, with the SMTP plugin overriding connect to
15 s. Decision 6 now relies on those bounds and states the arithmetic rather than a number.

**Two new defects in the drain I had just rewritten**, both fixed: `index` was initialised once
outside the loop, so a second batch unwinding before its first iteration sliced by the previous
batch's last index; and the `"Finished"` debug line had landed at the tail of `__rearm`, emitting
only when re-arming.

## Gate outcome

**CLEAR to proceed.** No BLOCKER, no MAJOR outstanding. The remaining MINORs and the two
known-open items are filed rather than carried as prose:

| | |
|---|---|
| `BL-E010-001` | Medium — no correlation identifier across the hops; unstructured container sink |
| `BL-E010-002` | Medium — shutdown cancels no timer; truncate-then-write exposure |
| `BL-E010-003` | Low — `_dump_settings` serialises the object, so path redaction needs a translation |

Neither Medium is created by this epic; both are pre-existing and were raised by both gates.
They are deliberately not blocking a story that does not worsen them.
