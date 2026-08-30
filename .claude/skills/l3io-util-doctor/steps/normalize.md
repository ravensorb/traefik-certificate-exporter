## Normalize Mode

Invoked with `normalize` argument. Convenience shortcut that runs `steps/reconcile-status.md` (Reconcile Status Mode) (if the legacy split layout is present) and the naming check from `steps/sort-status.md` (Sort Status Mode) (if sharded state is present) in one pass. The two operate on different, unrelated layouts — reconcile on the legacy split status files, naming-check on the current sharded `{pm_state_root}` tree — so normalize simply runs whichever applies and reports both; a fully-migrated project with no split files left still gets a useful naming check. Use for routine maintenance instead of running the two commands separately.

### Steps

**Step NM1 — Load config and detect layouts present**

Load config (same as layout cleanup). Determine what's present:
- Split layout: any of `sprint-status.yaml`, `sprint-status-backlog.yaml`, `sprint-status-archived.yaml` exists in `{implementation_artifacts}/`.
- Sharded state: `{pm_state_root}` (`{implementation_artifacts}/state`) exists.

If neither is present:
```
No split layout and no sharded state found — nothing to normalize.
```
Exit.

**Step NM2 — Reconcile (only if split layout present)**

If the split layout is present: run the full Reconcile Status Mode (Steps RC1–RC7) with one modification: **present the dry-run report but defer confirmation** — print the reconcile findings and the naming-check findings together in Step NM4 before asking to proceed.

If the split layout is absent, skip reconcile and carry forward "Reconcile: — (no split layout present)" for Step NM4/NM6.

**Step NM3 — Naming analysis (only if sharded state present)**

If `{pm_state_root}` is present: run Sort Status Mode's naming validation (Steps SO1–SO2). Collect `{naming_issues}`.

If `{pm_state_root}` is absent, carry forward "Naming check: — (no sharded state present)".

**Step NM4 — Combined dry-run and confirm**

Print the reconcile dry-run output (or its not-applicable note) followed by the naming-check
report (or its not-applicable note). Naming issues are report-only — there is nothing to
confirm for them, only reconcile changes need a confirmation:

```
Apply {reconcile_total} reconciliation change(s)?
  Y — proceed
  n — exit, no changes
```

If `n`: print `Normalize cancelled — no changes made.` and exit.

If `{reconcile_total}` is 0 (nothing to apply — regardless of any naming issues found, which
were already shown above and need no confirmation): print `✓ Nothing to reconcile.` and exit
without prompting.

**Step NM5 — Execute reconcile**

If reconcile has changes: apply Steps RC5–RC7 (execute, verify, report). On failure, stop and report.

**Step NM6 — Summary**

```
DONE — Normalize complete.
  Reconcile: {reconcile summary line, or "not applicable — no split layout"}
  Naming:    {N} issue(s) found (or "✓ clean", or "not applicable — no sharded state")
```

---
