# Progress Mode — forwards to `/l3io-doctor stats`

`stats` is the one plan-aware progress view. It renders the same phase → epic → sprint →
story tree from `pm-status.py report` — including the live-view hint, the stale-lock
`clear-lock` remedy, and the dwell-time explanation this mode used to add on its own — and
additionally reports backlog size by severity, last closed sprint/epic, and calibration
state.

Invoke `skill:l3io-doctor` with `stats`, passing through any scope argument the user
gave (`active`, `queued`, `everything`). Report its output unchanged; add no second summary.

`l3io-doctor` is a required module of this extension (see `CLAUDE.md` Dependencies), so
a missing doctor is an install anomaly rather than an expected condition. If the invocation
fails with "skill not found," report the install error and suggest `/l3io-doctor
check-deps` (which itself needs the doctor — the user needs to reinstall the module).
