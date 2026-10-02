# Engineering Standards — Shell Scripting Overlay

Loaded on top of `standards-core.md` when the project (or the component under review) contains
shell scripts.

## The opening three lines, and why each is not the default

**Rule.** Every script starts with a portable shebang and strict mode.

```bash
#!/usr/bin/env bash
set -euo pipefail
```

- **`-e`** — stop on an unchecked failure. Without it a failed step is invisible and the script
  carries on against state that no longer holds.
- **`-u`** — an unset variable is an error, not an empty string. This is the one that turns
  `rm -rf "$PREFIX/"` with an unset `PREFIX` from a catastrophe into a stopped script.
- **`-o pipefail`** — a pipeline fails if *any* stage fails, not just the last. Without it
  `curl … | tar …` reports success when the download failed and the tar got nothing.
- `#!/usr/bin/env bash`, not `#!/bin/bash` — bash is not at the same path everywhere.
- **Review** — Flag any production script missing these. **BLOCKER** where a script both lacks
  `-u` and interpolates a path into a destructive command.

## Quoting, and the failure it prevents

**Rule.** Quote every expansion: `"$var"`, `"$@"`, `"${arr[@]}"`.

- Unquoted `$var` is word-split and glob-expanded. A path with a space becomes two arguments; a
  value containing `*` becomes a directory listing. Both are silent until the input changes.
- `"$@"` — never bare `$@` or `"$*"` — is the only form that passes arguments through intact.
- Prefer `[[ ]]` over `[ ]` in bash: it does not word-split its operands.

## Temporary files and cleanup

**Rule.** Temporary paths come from `mktemp`, and the `trap` is registered on the next line.

```bash
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
```

- **Not a predictable `/tmp` name** — a fixed path is a symlink-attack surface and collides
  between concurrent runs.
- **Register the trap immediately** — any line between creating the resource and trapping it is
  a window where an error leaves the resource behind. This applies to mounts, background PIDs
  and file descriptors as much as to directories.
- Trap `EXIT`, which covers both the normal and the `set -e` path.

## Structure — and when to stop writing shell

**Rule.** Beyond a handful of linear steps, a script has `main()`, `usage()`, `log()` and a
`cleanup()` registered with `trap`, with `main "$@"` as the last line.

- **Know when to escalate.** Once a script grows non-trivial branching, data structures, or
  anything that wants a test suite, it should become a real program (core §5). Shell has no
  types, no exceptions and hostile error handling; a 400-line bash script with nested
  conditionals is a maintenance liability, not a thrifty choice.
- Functions over copy-paste (core §2). Small units so the logic is testable (core §4).
- **POSIX `sh`** only where portability genuinely requires it — and then say so in the header,
  because `set -o pipefail` and `[[ ]]` are not POSIX (core §10).

## Quality toolchain

- **ShellCheck clean in CI**, not just locally. Each suppression carries a comment saying why
  (core §6) — an unexplained `# shellcheck disable=SC2086` is a finding.
- **`shfmt`** for formatting, so diffs are about behaviour rather than whitespace.
- `bash -n` as a cheap syntax gate before anything slower runs.

## Secrets and logging

- Never a secret in `argv` — the process table is world-readable. Use a file descriptor, an
  env var read once, or stdin.
- Structured, correlated output where the script feeds a pipeline (core §9); plain text is
  fine for a script a human runs and reads.
- Errors to stderr, data to stdout, so the script composes.

## Review checklist (shell-specific)

- [ ] `#!/usr/bin/env bash` and `set -euo pipefail`.
- [ ] Every expansion quoted; `"$@"` not `$@`.
- [ ] `mktemp` for temporaries, with `trap … EXIT` on the following line.
- [ ] `main()`/`usage()`/`log()`/`cleanup()` structure once past a few linear steps.
- [ ] ShellCheck clean in CI; every suppression justified.
- [ ] `shfmt`-formatted; `bash -n` passes.
- [ ] No secret in argv; errors to stderr, data to stdout.
- [ ] Escalated to a real language if branching or data handling has outgrown shell (core §5).
