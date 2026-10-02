#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.11"
# ///
"""
check-pm-status.py -- verify the installed pm-status.py matches this doctor's module_version.

Why this exists
---------------
`pm-status.py` self-installs at each PM/doctor activation (see CLAUDE.md), which normally
keeps the installed copy fresh. But between an extension upgrade and the next activation, or
when a project's activation cadence lags, the installed copy can drift behind the source
copy the extension ships. `pm-help` used to inline a `pm-status.py --version` check against
its own module.yaml, but pm-help no longer owns a module.yaml -- so the freshness check
lives here (the doctor's module.yaml is one of the four whose `module_version` is bumped
together at postbump, so its value is the source of truth for pm-status.py's expected
version at this extension level).

Single-consumer (l3io-doctor), so it ships in doctor's own scripts/ per ADR-0001,
peer to bmad-deps.py and audit-backlog.py -- not synced or shared.

Usage
-----
  check-pm-status.py --project-root R [--format {text,json}]

Exit 0 -- installed pm-status.py matches module_version (or a strictly newer version).
Exit 3 -- installed pm-status.py is older than module_version (stale).
Exit 4 -- installed pm-status.py is absent (never self-installed here yet).
Exit 2 -- usage error, or the doctor's module.yaml is unreadable.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_MODULE_YAML = _HERE.parent / "assets" / "module.yaml"

_VERSION_RE = re.compile(r"^module_version:\s*(\S+)", re.MULTILINE)
_INSTALLED_PATH = "_bmad/scripts/pm-status.py"


_VERSION_TOKEN_RE = re.compile(r"\b(\d+(?:\.\d+)+)\b")


def _parse_version(text: str) -> tuple[int, ...] | None:
    """(2, 5, 2) from '2.5.2' OR 'pm-status.py 2.5.2'. Returns None on garbage."""
    m = _VERSION_TOKEN_RE.search(text or "")
    if not m:
        return None
    parts = m.group(1).split(".")
    return tuple(int(p) for p in parts)


def _expected_version() -> str | None:
    try:
        text = _MODULE_YAML.read_text(encoding="utf-8")
    except OSError:
        return None
    m = _VERSION_RE.search(text)
    return m.group(1).strip().strip("'\"") if m else None


def _installed_version(project_root: Path) -> tuple[str | None, int | None]:
    """Returns (version_string, exit_code_of_the_probe)."""
    p = project_root / _INSTALLED_PATH
    if not p.is_file():
        return None, None
    try:
        proc = subprocess.run(
            ["uv", "run", str(p), "--version"],
            capture_output=True, text=True, check=False, timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return None, None
    return proc.stdout.strip() or proc.stderr.strip() or None, proc.returncode


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="verify the installed pm-status.py is current")
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--format", choices=["text", "json"], default="text")
    args = parser.parse_args(argv)

    expected = _expected_version()
    if expected is None:
        sys.stderr.write(f"check-pm-status.py: cannot read module_version from {_MODULE_YAML}\n")
        return 2

    installed_raw, _ = _installed_version(Path(args.project_root))

    if installed_raw is None:
        result = {"status": "absent", "expected": expected, "installed": None}
        if args.format == "json":
            json.dump(result, sys.stdout)
            sys.stdout.write("\n")
        else:
            sys.stdout.write(
                f"pm-status.py absent -- expected {expected}, no installed copy at "
                f"{args.project_root}/{_INSTALLED_PATH}\n"
                f"Fix: run any l3io-pm or l3io-doctor skill; self-install runs at "
                f"activation.\n"
            )
        return 4

    exp_tuple = _parse_version(expected)
    inst_tuple = _parse_version(installed_raw)

    # A stale installed copy is one strictly older than expected. Newer or equal is fine --
    # a newer installed copy usually means the user is testing an unreleased build; the
    # self-install guard refuses to downgrade, and this check honours the same rule.
    if exp_tuple and inst_tuple and inst_tuple < exp_tuple:
        result = {"status": "stale", "expected": expected, "installed": installed_raw}
        if args.format == "json":
            json.dump(result, sys.stdout)
            sys.stdout.write("\n")
        else:
            sys.stdout.write(
                f"pm-status.py stale -- installed {installed_raw}, expected {expected}\n"
                f"Fix: run /l3io-doctor; its activation self-install refreshes the copy.\n"
            )
        return 3

    result = {"status": "current", "expected": expected, "installed": installed_raw}
    if args.format == "json":
        json.dump(result, sys.stdout)
        sys.stdout.write("\n")
    else:
        sys.stdout.write(f"pm-status.py current -- {installed_raw} (expected {expected})\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
