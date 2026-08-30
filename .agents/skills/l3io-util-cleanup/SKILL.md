---
name: l3io-util-cleanup
description: Deprecated — renamed to l3io-util-doctor. Forwards every argument to it unchanged.
---

# l3io-util-cleanup (deprecated)

Communicate all responses in `{communication_language}`.

This skill was renamed to **`l3io-util-doctor`**. "Cleanup" described about three of its
sixteen modes; the default behavior is a diagnose-report-repair health check, and `stats` is
now the plan-aware progress dashboard.

## Execution

Print exactly this once, before anything else:

```
/l3io-util-cleanup has been renamed to /l3io-util-doctor. Running it for you now — please
use the new name from here on.
```

Then load `l3io-util-doctor`'s `SKILL.md` and execute it with the arguments you received,
unchanged and in the same order. Resolve it in this order, using the first that exists:

1. `{project-root}/.claude/skills/l3io-util-doctor/SKILL.md` (installed plugin copy)
2. `{project-root}/skills/l3io-util-doctor/SKILL.md` (working inside this package's repo)

If neither exists, stop with:

```
l3io-util-doctor is not installed. Reinstall the l3io-util module from the
bmad-l3io-extensions marketplace, then run /l3io-util-doctor.
```

**Do not reimplement any mode here, and do not read project state yourself.** Every mode,
including its config resolution and layout detection, belongs to `l3io-util-doctor`. This file
exists only so the old command name keeps working; duplicating any logic into it would create a
second copy that silently drifts from the real one.

This forwarder will be removed in a future release.
