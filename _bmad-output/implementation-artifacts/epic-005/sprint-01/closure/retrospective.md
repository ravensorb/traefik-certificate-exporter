# Epic 5 / Sprint 1 — Retrospective

## What happened

Single story, done, no carry-over.

- **E005-S01-001** (Configurable Post-Export Command): the architecture spine explicitly
  left the exact interface (env var name aside) as a story-level decision. Implemented
  `settings.postExportCommand` as a single shell-like command-line string, parsed with
  Python's standard `shlex` module (not a hand-rolled parser) into argv for
  `subprocess.run(shell=False)` -- this keeps the setting representation consistent with
  the project's other single-string settings (`pkcs12passphrase`) rather than introducing
  a second, differently-shaped list-type setting alongside `domains.include/exclude`.
  A fixed 30s timeout, dry-run suppression, and non-zero-exit/timeout handling (logged,
  never crashes the watch loop) are all covered by a dedicated test module using real
  subprocess invocations (a temp Python script as the hook), not mocks, for the behavioral
  assertions -- mocking was reserved for the two "never invoked" cases (no command
  configured, dry-run).

## Learnings

- When an architecture doc explicitly defers an implementation-shape decision to story
  level, that's a signal to actively choose the option most consistent with the existing
  codebase's conventions (single-string + `shlex.split`, matching `pkcs12passphrase`)
  rather than defaulting to whatever the story's acceptance criteria examples suggest
  most literally.
- Testing subprocess-invoking code with real (not mocked) subprocess calls, via a
  temporary throwaway script, catches real behavior (actual env var propagation, actual
  timeout/kill semantics) that mocking `subprocess.run` cannot -- reserved mocking only for
  the "must never be called" assertions.
