#!/usr/bin/env python3
"""Single implementation of the committed version identity read from pyproject.toml.

Three consumers previously each re-derived this: ``scripts/release_version.py`` and
``docker/act-build.sh`` shell out to ``poetry version --short``, and ``ci.yaml``'s
``plan`` job carried an inline ``tomllib`` heredoc on an unpinned interpreter. This
module is the shared implementation for every consumer that cannot assume Poetry is
already installed -- notably the workflow ``plan`` jobs and the
``setup-poetry-python`` composite action, which must know the pinned Poetry version
*before* Poetry exists on the runner.

It exposes two authorities, both read from ``pyproject.toml``:

* ``tool.poetry.version``      -- the committed package version.
* ``tool.poetry.group.dev.dependencies.poetry`` -- the pinned Poetry version used by
  CI, the container build and the documented developer baseline.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

try:  # tomllib is stdlib from 3.11; the supported floor is 3.10.
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - exercised only on Python 3.10
    import tomli as tomllib  # type: ignore[no-redef]

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = PROJECT_ROOT / "pyproject.toml"

# Only the exact caret form is accepted. Widening the accepted constraint syntax is a
# deliberate decision -- an unrecognised form must fail loudly rather than silently
# resolve to a different Poetry than the one CI, the image and the docs claim.
_CARET_PIN = re.compile(r"\A\^(?P<version>[0-9]+\.[0-9]+\.[0-9]+)\Z")

# PEP 440 public release segment, restricted to the plain three-part form this project
# commits. Anything else is rejected rather than reformatted.
_PACKAGE_VERSION = re.compile(r"\A[0-9]+(?:\.[0-9]+)*\Z")


def load_metadata(pyproject: Path = PYPROJECT) -> dict[str, Any]:
    """Parse ``pyproject.toml`` with the standard library TOML reader."""
    return tomllib.loads(pyproject.read_text(encoding="utf-8"))


def package_version(metadata: dict[str, Any] | None = None) -> str:
    """Return the committed ``tool.poetry.version``."""
    document = load_metadata() if metadata is None else metadata
    value = document["tool"]["poetry"]["version"]
    if not isinstance(value, str) or not _PACKAGE_VERSION.fullmatch(value):
        raise SystemExit(
            f"tool.poetry.version must be a plain dotted release version, got {value!r}"
        )
    return value


def poetry_version(metadata: dict[str, Any] | None = None) -> str:
    """Return the pinned Poetry version behind the dev-group constraint."""
    document = load_metadata() if metadata is None else metadata
    constraint = document["tool"]["poetry"]["group"]["dev"]["dependencies"]["poetry"]
    if not isinstance(constraint, str):
        raise SystemExit(
            "tool.poetry.group.dev.dependencies.poetry must be a version string, "
            f"got {constraint!r}"
        )
    matched = _CARET_PIN.fullmatch(constraint)
    if matched is None:
        raise SystemExit(
            "tool.poetry.group.dev.dependencies.poetry must use the exact caret form "
            f"'^X.Y.Z' so the pinned Poetry version is unambiguous, got {constraint!r}"
        )
    return matched.group("version")


def development_version(distance: int, metadata: dict[str, Any] | None = None) -> str:
    """Return the normalized PEP 440 development version for a branch build.

    ``distance`` is the first-parent commit count, which makes the version unique per
    commit. No arithmetic is performed on the committed version itself: the release
    number is owned by ``scripts/release_version.py`` and release-please, and a
    development build must never invent one.
    """
    if distance < 0:
        raise SystemExit(f"development distance must be non-negative, got {distance}")
    return f"{package_version(metadata)}.dev{distance}"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser(
        "package-version", help="print the committed tool.poetry.version"
    )
    subcommands.add_parser("poetry-version", help="print the pinned Poetry version")
    development = subcommands.add_parser(
        "development-version",
        help="print the normalized PEP 440 development version for a branch build",
    )
    development.add_argument("--distance", type=int, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _build_parser().parse_args(argv)
    if arguments.command == "package-version":
        print(package_version())
    elif arguments.command == "poetry-version":
        print(poetry_version())
    else:
        print(development_version(arguments.distance))
    return 0


if __name__ == "__main__":
    sys.exit(main())
