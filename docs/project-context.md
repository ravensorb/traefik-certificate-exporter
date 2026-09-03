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
deliverable is largely a contract suite (34 → 298 guards in one epic), and guards fail *silently* by
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
- **Never replace a text region by index in `tests/ci/test_workflow_contracts.py`.** Doing so
  deleted adjacent definitions twice, once silently — a guard vanished while an ADR still cited it
  as the enforcement. Operate on named definitions, and diff the definition set before and after.
  `test_every_guard_a_document_cites_still_exists` is the mechanical backstop.

## 6. Work-type classification is load-bearing

E007 was classified CONFIG, which skips the adversarial and red-team phases — over 3,482 lines of
Python. E008 inherited that debt and reclassified to MIXED mid-epic, which is what surfaced most of
its findings. If a "CONFIG" epic is shipping code, it is MIXED.
