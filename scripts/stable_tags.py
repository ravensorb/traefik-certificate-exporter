#!/usr/bin/env python3
"""Annotated stable-tag detection for development-publication suppression.

`just release` pushes the branch and the annotated `vX.Y.Z` tag atomically (ADR-0006),
so one operation fires a `push` event on the default branch *and* a tag event. The
development channel must not publish a `X.Y.(Z+1).devN` for a commit that is a release,
so `dev.yaml` asks this module whether the pushed commit carries an exact stable tag.

Two operations do the real work, and both are delegated to git rather than reimplemented:

* **Peeling.** An annotated tag is an object in its own right; `refs/tags/v1.2.3` points
  at a tag object which points at the commit. `git rev-parse <tag>^{commit}` performs
  that dereference, including the chain of nested tags git permits. Comparing
  `%(objectname)` to a commit SHA -- the obvious shortcut -- silently never matches an
  annotated tag, which is the only kind this project creates.
* **Reachability.** `git merge-base --is-ancestor` answers "is this commit in that
  history" with git's own commit graph. Its exit status is the answer: 0 yes, 1 no.

The tag *name* still needs a pattern, because "is this the stable release spelling"
is a naming convention rather than a git fact. Nothing else is pattern-matched.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

# The exact stable spelling ADR-0006 creates. `v1.2.3-rc1`, `v1.2` and `1.2.3` are not
# stable release tags and must not suppress a development publication.
STABLE_TAG = re.compile(r"\Av(?:0|[1-9][0-9]*)(?:\.(?:0|[1-9][0-9]*)){2}\Z")


class GitError(SystemExit):
    def __init__(self, message: str) -> None:
        super().__init__(f"stable tag error: {message}")


def _git(arguments: list[str], *, repository: Path | None = None) -> str:
    command = ["git"]
    if repository is not None:
        command += ["-C", str(repository)]
    completed = subprocess.run(
        command + arguments,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise GitError(
            f"`git {' '.join(arguments)}` failed ({completed.returncode}): "
            f"{completed.stderr.strip()}"
        )
    return completed.stdout.strip()


def annotated_tags(repository: Path | None = None) -> list[str]:
    """Every annotated tag in the repository, in git's own ordering.

    Lightweight tags are excluded here rather than filtered later: `just release`
    creates annotated tags, and a lightweight `v1.2.3` pushed by hand is not the
    release identity ADR-0006 governs.
    """
    listing = _git(
        ["for-each-ref", "--format=%(objecttype) %(refname:short)", "refs/tags"],
        repository=repository,
    )
    tags = []
    for line in listing.splitlines():
        object_type, _, name = line.partition(" ")
        if object_type == "tag" and name:
            tags.append(name)
    return tags


def peel(tag: str, repository: Path | None = None) -> str:
    """Resolve a tag to the commit it ultimately names."""
    return _git(["rev-parse", "--verify", f"{tag}^{{commit}}"], repository=repository)


def is_ancestor(
    candidate: str, descendant: str, repository: Path | None = None
) -> bool:
    """True when ``candidate`` is reachable from ``descendant``."""
    command = ["git"]
    if repository is not None:
        command += ["-C", str(repository)]
    completed = subprocess.run(
        command + ["merge-base", "--is-ancestor", candidate, descendant],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode not in {0, 1}:
        raise GitError(
            f"`git merge-base --is-ancestor` failed ({completed.returncode}): "
            f"{completed.stderr.strip()}"
        )
    return completed.returncode == 0


def stable_tags_at(commit: str, repository: Path | None = None) -> list[str]:
    """Annotated stable tags whose peeled commit is exactly ``commit``."""
    resolved = _git(
        ["rev-parse", "--verify", f"{commit}^{{commit}}"], repository=repository
    )
    return sorted(
        tag
        for tag in annotated_tags(repository)
        if STABLE_TAG.fullmatch(tag) and peel(tag, repository) == resolved
    )


def suppresses_development(commit: str, repository: Path | None = None) -> bool:
    """True when a development publication for ``commit`` must be suppressed."""
    return bool(stable_tags_at(commit, repository))


def stable_tag_order(
    repository: Path | None = None, reachable_from: str | None = None
) -> list[str]:
    """Every annotated exact stable tag, ascending, in git's own version order.

    Ordering is `git for-each-ref --sort=v:refname`, which is the same delegation the
    rest of this module makes: git owns peeling, git owns reachability, and git owns
    version comparison. A tuple-of-integers comparison written here would be a second
    ordering implementation, and the only thing that could test it is a copy of itself.

    `v:refname` understands that `v1.10.0` is newer than `v1.9.0`, which a plain
    lexicographic sort does not -- and lexicographic is what a hand-rolled sort silently
    degrades to the first time someone reaches for `sorted()`.

    ``reachable_from`` scopes the set with `--merged`, and callers deciding an alias
    must pass it. Publication is limited to the protected default branch, so a tag on
    history that never reached it is not a release this project made -- and counting it
    is worse than harmless: one annotated `v9.9.9` left on an abandoned branch would
    make every later release the *second* greatest, so `vMAJOR` and `latest` would stop
    advancing while every run still finished green. Silent, and discovered by a user.
    """
    selector = ["--merged", reachable_from] if reachable_from else []
    listing = _git(
        [
            "for-each-ref",
            *selector,
            "--sort=v:refname",
            "--format=%(objecttype) %(refname:short)",
            "refs/tags",
        ],
        repository=repository,
    )
    order = []
    for line in listing.splitlines():
        object_type, _, name = line.partition(" ")
        if object_type == "tag" and STABLE_TAG.fullmatch(name):
            order.append(name)
    return order


def alias_plan(
    tag: str, repository: Path | None = None, reachable_from: str | None = None
) -> dict[str, str]:
    """Which floating aliases ``tag`` is permitted to advance.

    `LiquidLogicLabs/git-action-tag-floating-version` moves an alias
    **unconditionally**: it extracts the major and minor from the tag it is handed,
    points them at the reference commit and force-pushes. It compares nothing. So
    releasing `v1.2.4` while `v1.3.0` exists would drag `v1` backwards, and the refusal
    has to come from the caller (gate finding F4).

    The Git tag set is the only authority consulted. No registry is read: a registry tag
    is a publication side effect, and asking it "what does `latest` point at" is
    per-destination remote state under a new name.

    - ``advance-major`` -- ``tag`` is the greatest annotated stable tag in the repository.
    - ``advance-minor`` -- ``tag`` is the greatest within its own ``MAJOR.MINOR``.

    ``advance-major`` implies ``advance-minor``; the converse is a back-port release,
    where the minor alias may move forward and the major must not.
    """
    if not STABLE_TAG.fullmatch(tag):
        raise GitError(
            f"{tag!r} is not an exact vX.Y.Z stable tag, so no alias may point at it"
        )
    order = stable_tag_order(repository, reachable_from)
    if tag not in order:
        raise GitError(
            f"{tag!r} is not an annotated stable tag reachable from "
            f"{reachable_from or 'anywhere in this repository'}; annotated stable tags "
            f"there: {', '.join(order) or 'none'}"
        )
    major, minor, _ = tag[1:].split(".")
    # The trailing separator is what makes prefix membership exact: `v1.2.` cannot
    # prefix `v1.20.3`, and `v1.` cannot prefix `v10.0.0`. STABLE_TAG's ban on leading
    # zeros is a separate guarantee, and it is needed for a different reason -- without
    # it `v1.02.3` and `v1.2.3` would be one minor wearing two alias names.
    within_minor = [name for name in order if name.startswith(f"v{major}.{minor}.")]
    return {
        "major-alias": f"v{major}",
        "minor-alias": f"v{major}.{minor}",
        "advance-major": "true" if tag == order[-1] else "false",
        "advance-minor": "true" if tag == within_minor[-1] else "false",
        "greatest-stable": order[-1],
    }


def require_tag(name: str, commit: str, repository: Path | None = None) -> list[str]:
    """The stable tags on ``commit``, provided ``name`` is one of them.

    "Is the ref I was handed an annotated exact ``vX.Y.Z`` tag whose peeled commit is
    this one" is a single question, and this module already owns every part of the
    answer -- the annotated-object filter, the spelling and the peel. Answering it in a
    caller's shell means a third copy of the relation, in the one place that has no
    tests: a publisher's pre-upload refusal. Membership is decided here, and the caller
    branches on the exit status.
    """
    tags = stable_tags_at(commit, repository)
    if name not in tags:
        raise GitError(
            f"{name!r} is not an annotated exact vX.Y.Z tag whose peeled commit is "
            f"{commit}; annotated stable tags there: {', '.join(tags) or 'none'}"
        )
    return tags


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--repository", default=None)
    parser.add_argument(
        "--reachable-from",
        default=None,
        help=(
            "Fail unless --commit is reachable from this ref. Publication is limited to "
            "the protected default branch on both channels, and an event whose SHA has "
            "already left that history must not produce an immutable artifact."
        ),
    )
    parser.add_argument(
        "--expect-tag",
        default=None,
        help=(
            "Fail unless this tag name is one of the annotated exact stable tags whose "
            "peeled commit is --commit. The stable channel publishes from the tag it "
            "was handed, and the publishers re-check it immediately before uploading; "
            "both ask this question, and neither re-derives the answer."
        ),
    )
    parser.add_argument(
        "--alias-plan",
        action="store_true",
        help=(
            "Also emit which floating aliases the tag may advance, decided from the "
            "Git tag set alone. Requires --expect-tag, because the plan is about a "
            "released identity rather than about a commit."
        ),
    )
    parser.add_argument(
        "--output",
        default=os.environ.get("GITHUB_OUTPUT", ""),
        help="File to append `name=value` lines to; stdout when empty.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _build_parser().parse_args(argv)
    repository = Path(arguments.repository) if arguments.repository else None
    if arguments.reachable_from is not None and not is_ancestor(
        arguments.commit, arguments.reachable_from, repository
    ):
        raise GitError(
            f"{arguments.commit} is not reachable from {arguments.reachable_from}; "
            f"publication is limited to the protected default branch"
        )
    if arguments.expect_tag is not None:
        tags = require_tag(arguments.expect_tag, arguments.commit, repository)
    else:
        tags = stable_tags_at(arguments.commit, repository)
    lines = [
        f"suppressed={'true' if tags else 'false'}",
        f"stable-tags={','.join(tags)}",
    ]
    if arguments.alias_plan:
        if arguments.expect_tag is None:
            raise GitError("--alias-plan requires --expect-tag")
        plan = alias_plan(arguments.expect_tag, repository, arguments.reachable_from)
        lines += [f"{name}={value}" for name, value in plan.items()]
    rendered = "\n".join(lines)
    if arguments.output:
        with Path(arguments.output).open("a", encoding="utf-8") as stream:
            stream.write(f"{rendered}\n")
    else:
        print(rendered)
    return 0


if __name__ == "__main__":
    sys.exit(main())
