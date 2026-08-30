# Engineering Standards — Shell Scripting Overlay (COMING NEXT — stub)

> **Status: placeholder.** Scaffolded, not yet authored. Apply `standards-core.md` meanwhile.

Planned rules (draft):

- `#!/usr/bin/env bash`; `set -euo pipefail`; quote all expansions.
- ShellCheck clean in CI; functions over copy-paste (core §2); small, testable units (core §4).
- Prefer a real language once a script grows non-trivial branching (readability, core §5).
- No secrets in argv/env-echo; structured/correlated logging where it drives pipelines (core §9).
- POSIX where portability is required; document the target shell (core §10).

TODO: promote to full standard.
