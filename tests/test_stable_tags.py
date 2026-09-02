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


def test_require_tag_accepts_the_annotated_tag_that_names_the_commit(
    repository: Path,
) -> None:
    head = _git(repository, "rev-parse", "HEAD")
    _git(repository, "tag", "-a", "v1.2.3", "-m", "release 1.2.3")
    assert stable_tags.require_tag("v1.2.3", head, repository) == ["v1.2.3"]


@pytest.mark.parametrize(
    "name",
    ["v1.2.4", "v1.2", "v1.2.3-rc1", "1.2.3", "v01.2.3", "", "refs/tags/v1.2.3"],
)
def test_require_tag_refuses_anything_that_is_not_that_tag(
    repository: Path, name: str
) -> None:
    """The membership relation lives here, so the publishers' pre-upload refusal is one
    call rather than a third hand-written copy of it in shell."""
    head = _git(repository, "rev-parse", "HEAD")
    _git(repository, "tag", "-a", "v1.2.3", "-m", "release 1.2.3")
    with pytest.raises(SystemExit):
        stable_tags.require_tag(name, head, repository)


def test_require_tag_refuses_a_lightweight_tag_of_the_right_name(
    repository: Path,
) -> None:
    head = _git(repository, "rev-parse", "HEAD")
    _git(repository, "tag", "v1.2.3")
    with pytest.raises(SystemExit):
        stable_tags.require_tag("v1.2.3", head, repository)


def test_require_tag_refuses_a_tag_that_peels_to_another_commit(
    repository: Path,
) -> None:
    _git(repository, "tag", "-a", "v1.2.3", "-m", "release 1.2.3")
    head = _commit(repository, "two")
    with pytest.raises(SystemExit):
        stable_tags.require_tag("v1.2.3", head, repository)


def test_the_cli_refuses_a_tag_that_does_not_name_the_commit(repository: Path) -> None:
    head = _git(repository, "rev-parse", "HEAD")
    _git(repository, "tag", "-a", "v1.2.3", "-m", "release 1.2.3")
    with pytest.raises(SystemExit):
        stable_tags.main(
            [
                "--commit",
                head,
                "--repository",
                str(repository),
                "--expect-tag",
                "v1.2.4",
                "--output",
                "",
            ]
        )
    assert (
        stable_tags.main(
            [
                "--commit",
                head,
                "--repository",
                str(repository),
                "--expect-tag",
                "v1.2.3",
                "--output",
                "",
            ]
        )
        == 0
    )


# ---------------------------------------------------------------------------
# Alias ordering (story E008-S01-003, gate finding F4). The Git tag set is the only
# authority: `git-action-tag-floating-version` moves an alias unconditionally, so the
# comparison it does not make has to be made here.
# ---------------------------------------------------------------------------


@pytest.fixture
def released(repository: Path) -> Path:
    for content, tags in (
        ("one", ("v0.9.0",)),
        ("two", ("v1.2.3",)),
        ("three", ("v1.2.10",)),
        ("four", ("v1.3.0", "v1.4.0-rc1")),
        ("five", ()),
    ):
        if content != "one":
            _commit(repository, content)
        for tag in tags:
            _git(repository, "tag", "-a", tag, "-m", tag)
    _git(repository, "tag", "v2.0.0-lightweight")
    return repository


def test_the_tag_order_is_gits_version_order_not_a_lexicographic_one(
    released: Path,
) -> None:
    """`v1.2.10` sorts BELOW `v1.2.3` under every string comparison and above it under
    git's `v:refname`. That single pair is the whole reason this delegates."""
    assert stable_tags.stable_tag_order(released) == [
        "v0.9.0",
        "v1.2.3",
        "v1.2.10",
        "v1.3.0",
    ]


def test_the_newest_release_may_advance_both_aliases(released: Path) -> None:
    plan = stable_tags.alias_plan("v1.3.0", released)
    assert plan["advance-major"] == "true"
    assert plan["advance-minor"] == "true"
    assert plan["major-alias"] == "v1"
    assert plan["minor-alias"] == "v1.3"
    assert plan["greatest-stable"] == "v1.3.0"


def test_a_back_port_may_advance_its_minor_but_never_the_major(released: Path) -> None:
    plan = stable_tags.alias_plan("v1.2.10", released)
    assert plan["advance-major"] == "false"
    assert plan["advance-minor"] == "true"


def test_a_superseded_patch_advances_nothing(released: Path) -> None:
    plan = stable_tags.alias_plan("v1.2.3", released)
    assert plan["advance-major"] == "false"
    assert plan["advance-minor"] == "false"


def test_the_first_release_of_a_new_major_advances_its_own_aliases(
    released: Path,
) -> None:
    """A major with exactly one release is greatest within itself and, here, greatest
    overall -- the case a "compare against the previous tag" implementation gets wrong
    because there is no previous tag in that major."""
    _commit(released, "six")
    _git(released, "tag", "-a", "v2.0.0", "-m", "v2.0.0")
    plan = stable_tags.alias_plan("v2.0.0", released)
    assert plan == {
        "major-alias": "v2",
        "minor-alias": "v2.0",
        "advance-major": "true",
        "advance-minor": "true",
        "greatest-stable": "v2.0.0",
    }


def test_a_neighbouring_minor_is_not_mistaken_for_this_one(released: Path) -> None:
    """`v1.2.` cannot prefix `v1.20.x` only because the spelling forbids leading zeros.
    Asserted rather than assumed: a `startswith` that was one character short would make
    `v1.2.3` the greatest "within its minor" while `v1.20.0` existed."""
    _commit(released, "seven")
    _git(released, "tag", "-a", "v1.20.0", "-m", "v1.20.0")
    assert stable_tags.alias_plan("v1.2.10", released)["advance-minor"] == "true"
    assert stable_tags.alias_plan("v1.20.0", released)["advance-minor"] == "true"
    assert stable_tags.alias_plan("v1.20.0", released)["advance-major"] == "true"


@pytest.mark.parametrize(
    "tag", ["v1.4.0-rc1", "v2.0.0-lightweight", "v1.2", "1.2.3", "v01.2.3"]
)
def test_no_alias_may_point_at_anything_but_an_exact_stable_release(
    released: Path, tag: str
) -> None:
    with pytest.raises(SystemExit):
        stable_tags.alias_plan(tag, released)


def test_a_stable_tag_that_is_not_in_this_repository_is_refused(
    released: Path,
) -> None:
    """Ordering is decided from the tag set, so a tag absent from it has no position in
    that set -- and answering "greatest" for a tag git has never seen would be a
    decision made from the caller's input rather than from the repository."""
    with pytest.raises(SystemExit):
        stable_tags.alias_plan("v7.7.7", released)


def test_the_cli_emits_the_alias_plan_only_alongside_an_expected_tag(
    released: Path, tmp_path: Path
) -> None:
    output = tmp_path / "github-output"
    output.touch()
    commit = _git(released, "rev-parse", "v1.3.0^{commit}")
    assert (
        stable_tags.main(
            [
                "--commit",
                commit,
                "--repository",
                str(released),
                "--expect-tag",
                "v1.3.0",
                "--alias-plan",
                "--output",
                str(output),
            ]
        )
        == 0
    )
    emitted = dict(
        line.split("=", 1)
        for line in output.read_text(encoding="utf-8").splitlines()
        if line
    )
    assert emitted["advance-major"] == "true"
    assert emitted["minor-alias"] == "v1.3"

    with pytest.raises(SystemExit):
        stable_tags.main(
            ["--commit", commit, "--repository", str(released), "--alias-plan"]
        )


def test_a_tag_that_never_reached_the_default_branch_is_not_in_the_order(
    released: Path,
) -> None:
    """Publication is limited to the protected default branch, so the ordering question
    is "greatest among the tags this project actually released".

    Counting an unreachable tag is not merely untidy: one annotated `v9.9.9` left on an
    abandoned release attempt makes every later release the *second* greatest forever.
    `advance-major` is then permanently `false`, so `vMAJOR`, `latest` and both image
    aliases silently stop advancing while every run finishes green -- discovered months
    later by a user, not by CI.
    """
    _git(released, "checkout", "-b", "abandoned")
    _commit(released, "abandoned")
    _git(released, "tag", "-a", "v9.9.9", "-m", "abandoned release attempt")
    _git(released, "checkout", "main")

    assert "v9.9.9" in stable_tags.stable_tag_order(released)
    assert "v9.9.9" not in stable_tags.stable_tag_order(released, "main")

    unscoped = stable_tags.alias_plan("v1.3.0", released)
    assert unscoped["advance-major"] == "false"
    scoped = stable_tags.alias_plan("v1.3.0", released, "main")
    assert scoped["advance-major"] == "true"
    assert scoped["greatest-stable"] == "v1.3.0"


def test_a_release_that_is_not_on_the_scoped_branch_has_no_alias_plan(
    released: Path,
) -> None:
    _git(released, "checkout", "-b", "abandoned")
    _commit(released, "abandoned")
    _git(released, "tag", "-a", "v9.9.9", "-m", "abandoned release attempt")
    _git(released, "checkout", "main")
    with pytest.raises(SystemExit) as raised:
        stable_tags.alias_plan("v9.9.9", released, "main")
    assert "main" in str(raised.value)
