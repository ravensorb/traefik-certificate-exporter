"""Helpers shared by more than one test module.

Only things two suites genuinely need. A helper that one module uses belongs in that
module, where its contract is visible next to its only caller.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).parents[1]

# The one file whose absence would mean the corpus is not this repository. Cheaper and
# more honest than a magic "more than N files were examined" floor: it names the source
# of truth instead of a number somebody chose once.
CORPUS_LANDMARK = "pyproject.toml"


def tracked_text_files() -> list[tuple[str, str]]:
    """Every UTF-8-decodable file git tracks, as `(path relative to the root, text)`.

    The scope of a "nothing in this repository does X" guard, derived from git rather
    than from a walk with hand-kept exclusions -- a walk sees build output, virtualenvs
    and caches, and an exclusion list drifts from what is actually committed.
    """
    listing = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split("\0")
    files: list[tuple[str, str]] = []
    for relative in listing:
        if not relative:
            continue
        path = PROJECT_ROOT / relative
        if not path.is_file():
            continue
        try:
            files.append((relative, path.read_text(encoding="utf-8")))
        except (UnicodeDecodeError, OSError):
            # A binary blob cannot invoke anything, and an unreadable one is a
            # filesystem problem rather than a policy violation.
            continue
    assert any(relative == CORPUS_LANDMARK for relative, _ in files), (
        f"{CORPUS_LANDMARK} is not in the tracked corpus; the scan is not looking at "
        f"this repository"
    )
    return files
