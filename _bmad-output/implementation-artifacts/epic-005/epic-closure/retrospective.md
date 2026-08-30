# Epic Closure Retrospective — E005: Extended Integration Capability (Post-Export Hook)

**Velocity:** 1/1 story done in a single sprint (S01) — no carry-over.

**What this epic actually validated:** the architecture spine deferred this feature's
exact interface shape to story level; the decision made was single-string + `shlex.split`
(matching the project's existing `pkcs12passphrase` single-string convention), not a
list-typed setting like `domains.include/exclude`. `subprocess.run(shell=False)` with
`shlex`-parsed argv gives shell-injection-proof execution without sacrificing the ability
to quote arguments containing spaces.

## Architectural drift review (epic-level, work_type=CODE)

Single sprint, so epic-level scope matches sprint-level review already performed. New
capability, additive only (unset = no behavior change). No new ADR required — the
architecture spine already flagged this as a story-level, not architectural, decision.

## Epic security review (work_type=CODE)

`shell=False` + `shlex.split` closes off shell-injection entirely. The command itself is
operator-configured (trusted config input), not attacker- or network-controllable, so
inheriting the full process environment is expected/intended behavior (matches cron,
systemd `ExecStartPost`), not a new exposure. Fixed 30s timeout prevents an unresponsive
hook from hanging the watch loop indefinitely. No CRITICAL/HIGH/MEDIUM findings.

## Issue triage

0 new issues logged — closes GitHub issue #2 directly, no deferred follow-up.
