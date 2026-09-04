"""Fixtures shared across the CI contract modules.

BL-E008-010 phase 3. A fixture used by more than one module belongs here, which is
pytest's own mechanism for it -- importing one from `support` into a module namespace
happens to work, but conftest is the thing the framework provides.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.ci.support import _git


@pytest.fixture
def tagged_repository(tmp_path: Path) -> Path:
    """A real repository carrying every ref shape the stable guard must judge.

    Real git, never a mocked `subprocess`: the whole point of delegating peeling and
    reachability to git is that git's answers are the authority, and asserting against
    a fake would test the fake (F9).
    """
    root = tmp_path / "repository"
    root.mkdir()
    _git(root, "init", "--initial-branch=main")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "Test")
    (root / "file.txt").write_text("one\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "one")
    _git(root, "tag", "-a", "v0.9.0", "-m", "release 0.9.0")
    (root / "file.txt").write_text("two\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "two")
    for annotated in ("v1.2.3", "v1.2", "v1.2.3-rc1", "1.2.3", "v01.2.3"):
        _git(root, "tag", "-a", annotated, "-m", f"tag {annotated}")
    _git(root, "tag", "v9.9.9")
    # A release tag on history that never reached the protected default branch.
    _git(root, "checkout", "-b", "sidebranch")
    (root / "file.txt").write_text("side\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "side")
    _git(root, "tag", "-a", "v2.0.0", "-m", "release 2.0.0")
    _git(root, "checkout", "main")
    return root
