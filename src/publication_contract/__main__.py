"""Allow ``python -m publication_contract`` for callers without the console script."""

from __future__ import annotations

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
