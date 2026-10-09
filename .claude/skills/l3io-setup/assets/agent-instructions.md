## LiquidLogicLabs Extensions (l3io)

This project has the l3io BMad extensions installed: sprint/epic orchestration, architecture
review, red-team security review, and project-state utilities.

**PM state is machine-written. Never hand-edit a file under the state tree.** Every status,
estimate and actuals write goes through `pm-status.py`, one atomic, comment-preserving,
locked operation. Free-form edits were dropped and malformed under parallel runs.

**Invocation is conversational.** These skills take plain intent, or a positional scope token
like `E007` or `E007-S02`. None of them parse `--flags`.

- `/l3io-help` — what to do next, from current project state
- `/l3io-plan` — validate readiness, elaborate stories, estimate, build the plan
- `/l3io-execute` — run the plan: dev, review, QA, fix loop, closure
- `/l3io-doctor` — diagnostics and housekeeping; no argument runs a health check
- `/l3io-arch-review`, `/l3io-sec-redteam` — architecture and security review
- `/l3io-sync` — mirror state to GitHub Issues

**Estimates and actuals are both mandatory** at story, sprint and epic level, across five
metrics. `cost` is never entered: it is derived from recorded tokens and the model's rates.

**The system learns from what you record.** Calibration derives its ratios from actuals, so
inaccurate actuals degrade every future estimate here. Record what happened, not what was
expected.

**Rate cards go stale.** Cost is `tokens × the model's per-class rates`. `pm-status.py rates`
prints the table in force; `modules.l3io-pm.token_rates` overrides it per model. Check current
pricing whenever you see a model the table does not name.
