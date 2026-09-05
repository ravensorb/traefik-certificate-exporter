# Project context for orchestrated runs

Facts a PM/orchestration run should know about *this* repository before it plans anything. Listed
because each cost real rework at least once, with what it cost.

## 1. Run the adversarial pass per story, not per sprint

The per-story loop runs `bmad-code-review` only; the adversarial, red-team and arch-drift passes run
at sprint closure. For E008 that meant a defect written in story 001 was found after stories 002,
003 and 004 had copied its shape — the same finding, four times, with three stories of work built on
top of it. Closure remediation came to **24 commits against 3 implementation commits**, and roughly
half the epic's man-hours landed in the closure attribution band.

Dispatch an adversarial pass alongside the code review for each story. It costs the same review
tokens; it removes the rework multiplier. (There is no `customize.toml` knob for this — it is an
orchestration choice at dispatch time.)

## 2. Estimate closure from the guard count, not the story count

E008 estimated 74.6–77.4 man-hours and actualled 210. The story scope was estimated roughly right;
what the estimate did not carry is that **closure cost more than implementation**. This project's
deliverable is largely a contract suite (34 → 313 guards, most of them in one epic), and guards fail *silently* by
construction — a broken guard reports success — so they can only be validated by planting the
violation they forbid. That validation is the cost, and it is proportional to guards written.

## 3. The signature defect, and what now catches it

A guard whose **rule** is correct over a **set** that is hand-written. Eleven instances at E008
sprint closure, four more inside the fixes for those eleven, after being named twenty times across
three reviews.

`test_no_guard_takes_its_scope_from_a_hand_written_list_of_what_the_repo_contains` is the mechanical
check (retrospective item A1). It refuses a module-level literal that enumerates names the
repository contains, and `SCOPE_REGISTRIES` is the declared escape hatch. Validated against history:
it refuses the real defect as it stood at `6a76559` and `df6e5ed`.

**A plant must attack the scope, not the rule.** Add a file or a job; do not edit the one the guard
names. Every guard defeated by a reviewer in E008 had a plant that edited the named file.

## 4. A gate must prove it examined something

Two gates in this repository had never done anything and were green throughout: the secret scanner
ran over an empty file set (`~0 bytes`, exit 0, every commit of the project's history), and the
pytest matrix installed one interpreter under five names. Both are now guarded, and the CI gitleaks
job proves itself against a planted credential on every run. Prefer that shape for any new gate: a
gate that cannot demonstrate failure is not a gate.

## 5. Two mechanical habits that cost time when skipped

- **Order: hooks → stage → test → commit.** Mutating hooks (`ruff-format`) rewrite files *after* a
  test run, so testing before staging verifies a different tree than the one committed. This
  produced a red commit in E008, and three near-misses.
- **Never replace a text region by index anywhere in `tests/ci/`.** Doing so deleted adjacent
  definitions twice, once silently — a guard vanished while an ADR still cited it as the
  enforcement. Operate on named definitions, and diff the definition set before and after.
  `test_every_guard_a_document_cites_still_exists` is the mechanical backstop.
- **Cite a guard as `tests/ci/<module>.py::<guard>`, never by line.** BL-E008-010 split the
  suite into nine modules and every line-numbered citation in ADR-0007 went on resolving to
  unrelated code — a wrong pointer that looks right, which is worse than a dead one.
  `test_no_document_cites_the_test_suite_by_line_number` and
  `test_every_addressed_citation_names_the_module_that_holds_the_guard` enforce both halves.

## 6. Work-type classification is load-bearing

E007 was classified CONFIG, which skips the adversarial and red-team phases — over 3,482 lines of
Python. E008 inherited that debt and reclassified to MIXED mid-epic, which is what surfaced most of
its findings. If a "CONFIG" epic is shipping code, it is MIXED.

## 7. Confirming an input exists is not confirming it is the input to pass

Reading an action's `action.yml` before adopting it is this project's rule (ADR-0006, ADR-0010,
ADR-0012) and it is a good one. It establishes the **vocabulary**. It does not establish the
**grammar**, and the first three stable releases were spent learning the difference:

- `git-action-release@v2` declares `commit`. We passed it. It tells the action to *create* the tag
  at that SHA — and this workflow is *triggered by* the tag push, so the ref always already exists.
  `HTTP 422: Reference already exists`, after the image was published and attested.
- `git-action-tag-floating-version@v2` declares `ref-tag`. We passed it. It is the *optional*
  override for what the floating tags point at, defaulting to `tag` — which is the **required**
  input, and was never supplied. `Input required and not supplied: tag`, after the Release was
  created.

Both inputs exist. Both were verified to exist. Both were wrong to pass. When adopting an action,
read `required:` and the description of what each input *does*, not just the list of names — and
check the **outputs** you consume the same way.

**And a guard written from the same misreading as the code is an echo, not a check.** The
sprint-closure guard for the alias action asserted `ref-tag` was passed, demanding the optional
input and never the mandatory one. Code and guard were wrong in the same direction, so neither could
catch the other. When a guard is written from the same reading that produced the code, it verifies
nothing; the plant has to come from somewhere else — the manifest, the platform docs, or a run.

## 8. Only running it finds some things

Six CI runs against a pipeline that six review phases and ~70 findings had already been through
turned up five defects, none reachable by static analysis:

| defect | why static analysis could not see it |
|---|---|
| CPython 3.13 rewrote JSON diagnostics | a test pinned a stdlib implementation detail |
| `poetry-lock` ran a hook it could not install | the job installs `dependencies: none` deliberately |
| the bake target's `output` beat `--push` | the guard asserted the command *said* push, and it did |
| fixtures pinned to the committed version | made the project unreleasable **at any version** |
| `commit:` / `ref-tag:` | see section 7 |

Budget for this. A pipeline that has never executed is not verified, however many guards it has, and
the first runs of a new channel should be expected to cost a few cycles. What the static work buys is
that each failure is *legible* and lands somewhere recoverable — which held every time here: every
partial application stopped after an immutable artifact and before any mutable name.

## 9. Spent versions, for anyone reading the tag list later

- **v0.1.4** — image published and attested; no Release, no aliases (the `commit:` defect).
- **v0.1.5** — Release created with all four assets; no aliases (the `ref-tag:` defect).
- **v0.1.6** — first complete stable release: Release, image, and `latest`/`0`/`0.1` plus `v0`/`v0.1`
  all resolving to one digest.

Neither stranded version was repaired in place. `refs/tags/vX.Y.Z` is immutable (ADR-0006), deleting
or re-creating a published tag is a prohibited recovery action (`docs/operational.md`), and re-running
the failed job would re-run the workflow *as of that tag* — which still contains the defect. Rolling
forward was the only correct move, and it is what the runbook prescribes.
