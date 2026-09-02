"""Behavioural cases for annotated stable-tag suppression.

Run against a real temporary repository rather than a mocked `subprocess`. The whole
point of delegating peeling and reachability to git is that git's answers are the
authority; asserting against a fake would test the fake (story E008-S01-001, F9).
"""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path
from typing import Any

import pytest

PROJECT_ROOT = Path(__file__).parents[1]


def _load() -> Any:
    location = PROJECT_ROOT / "scripts" / "stable_tags.py"
    spec = importlib.util.spec_from_file_location("stable_tags", location)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


stable_tags = _load()


def _git(repository: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repository), *arguments],
        capture_output=True,
        text=True,
        check=True,
    )
    return completed.stdout.strip()


@pytest.fixture
def repository(tmp_path: Path) -> Path:
    root = tmp_path / "repository"
    root.mkdir()
    _git(root, "init", "--initial-branch=main")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "Test")
    (root / "file.txt").write_text("one\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "one")
    return root


def _commit(repository: Path, content: str) -> str:
    (repository / "file.txt").write_text(content, encoding="utf-8")
    _git(repository, "add", ".")
    _git(repository, "commit", "-m", content)
    return _git(repository, "rev-parse", "HEAD")


def test_an_untagged_commit_does_not_suppress_development(repository: Path) -> None:
    head = _git(repository, "rev-parse", "HEAD")
    assert stable_tags.stable_tags_at(head, repository) == []
    assert stable_tags.suppresses_development(head, repository) is False


def test_an_annotated_stable_tag_on_the_commit_suppresses_development(
    repository: Path,
) -> None:
    head = _git(repository, "rev-parse", "HEAD")
    _git(repository, "tag", "-a", "v1.2.3", "-m", "release 1.2.3")
    assert stable_tags.stable_tags_at(head, repository) == ["v1.2.3"]
    assert stable_tags.suppresses_development(head, repository) is True


def test_the_tag_object_is_peeled_rather_than_compared_directly(
    repository: Path,
) -> None:
    # An annotated tag's own object name is the tag object, never the commit. Comparing
    # `%(objectname)` to the commit SHA -- the shortcut this module exists to avoid --
    # would report "no stable tag" for every release this project has ever made.
    head = _git(repository, "rev-parse", "HEAD")
    _git(repository, "tag", "-a", "v2.0.0", "-m", "release 2.0.0")
    tag_object = _git(repository, "rev-parse", "v2.0.0")
    assert tag_object != head
    assert stable_tags.peel("v2.0.0", repository) == head


def test_a_stable_tag_on_an_ancestor_does_not_suppress_the_new_head(
    repository: Path,
) -> None:
    _git(repository, "tag", "-a", "v1.0.0", "-m", "release 1.0.0")
    head = _commit(repository, "two")
    assert stable_tags.stable_tags_at(head, repository) == []
    assert stable_tags.suppresses_development(head, repository) is False


def test_a_lightweight_tag_is_not_the_release_identity(repository: Path) -> None:
    head = _git(repository, "rev-parse", "HEAD")
    _git(repository, "tag", "v3.0.0")
    assert stable_tags.stable_tags_at(head, repository) == []


@pytest.mark.parametrize(
    "name", ["v1.2.3-rc1", "v1.2", "1.2.3", "v1.2.3.4", "release-1.2.3", "v01.2.3"]
)
def test_only_the_exact_stable_spelling_suppresses(repository: Path, name: str) -> None:
    head = _git(repository, "rev-parse", "HEAD")
    _git(repository, "tag", "-a", name, "-m", name)
    assert stable_tags.stable_tags_at(head, repository) == []


def test_reachability_is_answered_by_git_not_by_a_pattern(repository: Path) -> None:
    first = _git(repository, "rev-parse", "HEAD")
    second = _commit(repository, "two")
    assert stable_tags.is_ancestor(first, second, repository) is True
    assert stable_tags.is_ancestor(second, first, repository) is False


def test_the_cli_reports_suppression_and_the_tags_that_caused_it(
    repository: Path, tmp_path: Path
) -> None:
    _git(repository, "tag", "-a", "v4.5.6", "-m", "release 4.5.6")
    output = tmp_path / "github-output"
    exit_code = stable_tags.main(
        [
            "--commit",
            "HEAD",
            "--repository",
            str(repository),
            "--output",
            str(output),
        ]
    )
    assert exit_code == 0
    lines = output.read_text(encoding="utf-8").splitlines()
    assert "suppressed=true" in lines
    assert "stable-tags=v4.5.6" in lines


def test_the_cli_refuses_a_commit_that_left_the_protected_branch(
    repository: Path,
) -> None:
    orphan = _git(repository, "rev-parse", "HEAD")
    _commit(repository, "two")
    _git(repository, "branch", "protected")
    _git(repository, "checkout", "--detach", orphan)
    unreachable = _commit(repository, "sidebranch")
    with pytest.raises(SystemExit) as failure:
        stable_tags.main(
            [
                "--commit",
                unreachable,
                "--repository",
                str(repository),
                "--reachable-from",
                "protected",
                "--output",
                "",
            ]
        )
    assert "not reachable" in str(failure.value)


def test_an_unknown_commit_fails_loudly(repository: Path) -> None:
    with pytest.raises(SystemExit):
        stable_tags.stable_tags_at("0" * 40, repository)
