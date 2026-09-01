#!/usr/bin/env python3
"""Prepare and atomically publish one guarded semantic release identity."""

from __future__ import annotations

import argparse
import hashlib
import re
import shlex
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

STABLE_VERSION = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
BUMP_KINDS = ("major", "minor", "patch")


@dataclass(frozen=True)
class CommandResult:
    args: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str


class ReleaseError(RuntimeError):
    """A release invariant failed without requiring destructive cleanup."""


class CommandFailure(ReleaseError):
    def __init__(self, result: CommandResult) -> None:
        self.result = result
        detail = (
            result.stderr.strip() or result.stdout.strip() or "no diagnostic output"
        )
        super().__init__(
            f"command failed ({result.returncode}): {_display_command(result.args)}\n{detail}"
        )


class RecoveryRequired(ReleaseError):
    """Automatic restoration could not return the repository to its original state."""


class PublicationUnconfirmed(ReleaseError):
    """The atomic remote mutation did not complete or could not be confirmed."""


class CommandRunner:
    """Run checked argument-array subprocesses in one repository."""

    def __init__(self, cwd: Path) -> None:
        self.cwd = Path(cwd)

    def run(
        self,
        args: Sequence[str],
        *,
        check: bool = True,
    ) -> CommandResult:
        command = tuple(str(argument) for argument in args)
        completed = subprocess.run(
            list(command),
            cwd=self.cwd,
            text=True,
            capture_output=True,
            check=False,
        )
        result = CommandResult(
            args=command,
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )
        if check and result.returncode != 0:
            raise CommandFailure(result)
        return result


@dataclass(frozen=True)
class RemoteState:
    default_branch: str
    branch_tip: str
    stable_tags: dict[str, str]


@dataclass(frozen=True)
class PreparationBaseline:
    default_branch: str
    remote_tip: str
    current_version: str


@dataclass(frozen=True)
class ReleaseIdentity:
    version: str
    tag: str
    branch: str
    parent: str
    commit: str | None
    commit_message: str
    tag_message: str
    push_command: tuple[str, ...]


def _display_command(args: Sequence[str]) -> str:
    return shlex.join(tuple(args))


def _stable_version(value: str, *, label: str) -> tuple[int, int, int]:
    match = STABLE_VERSION.fullmatch(value)
    if match is None:
        raise ReleaseError(
            f"{label} must be an exact stable MAJOR.MINOR.PATCH version: {value!r}"
        )
    return tuple(int(part) for part in match.groups())


class ReleaseTransaction:
    def __init__(self, root: Path, runner: CommandRunner) -> None:
        self.root = Path(root).resolve()
        self.runner = runner

    def prepare(self, bump: str, *, dry_run: bool, push: bool) -> ReleaseIdentity:
        if bump not in BUMP_KINDS:
            raise ReleaseError(
                f"unsupported bump {bump!r}; choose exactly one of: {', '.join(BUMP_KINDS)}"
            )
        if dry_run and push:
            raise ReleaseError("--dry-run and --push are mutually exclusive")

        baseline = self._validate_preparation_preconditions()
        if dry_run:
            next_version = self._poetry_bump(bump, dry_run=True)
            identity = self._identity(
                version=next_version,
                branch=baseline.default_branch,
                parent=baseline.remote_tip,
                commit=None,
            )
            self._report_dry_run(identity)
            return identity

        proposed_version = self._poetry_bump(bump, dry_run=True)
        tag = f"v{proposed_version}"
        self._ensure_new_tag_absent(tag)
        try:
            next_version = self._poetry_bump(bump, dry_run=False)
        except ReleaseError:
            if not self._is_clean():
                self._restore_after_failed_mutation(
                    baseline.current_version,
                    context="the Poetry bump command failed after changing the tree",
                )
            raise
        if next_version != proposed_version:
            self._restore_after_failed_mutation(
                baseline.current_version,
                context="Poetry returned a different version during the real bump",
            )
            raise ReleaseError(
                f"Poetry proposed {proposed_version} but wrote {next_version}; "
                "the original version was restored"
            )
        try:
            changed_paths = self._poetry_changed_paths()
            changed_digests = self._path_digests(changed_paths)
        except RecoveryRequired as error:
            self._restore_after_failed_mutation(
                baseline.current_version,
                context="Poetry did not produce an isolated version-file change",
            )
            raise ReleaseError(
                "Poetry produced an unexpected change; the original version was restored"
            ) from error

        gate = self.runner.run(("just", "check"), check=False)
        try:
            gate_mutated_tree = (
                self._current_changed_paths() != changed_paths
                or self._path_digests(changed_paths) != changed_digests
            )
        except RecoveryRequired:
            gate_mutated_tree = True
        if gate.returncode != 0 or gate_mutated_tree:
            self._restore_after_failed_mutation(
                baseline.current_version,
                context="just check did not leave the expected version-only working tree",
            )
            if gate.returncode != 0:
                detail = (
                    gate.stderr.strip() or gate.stdout.strip() or "no diagnostic output"
                )
                raise ReleaseError(
                    f"just check failed; the original Poetry version was restored\n{detail}"
                )
            raise ReleaseError(
                "just check changed the release working tree; the original Poetry version was restored"
            )

        commit_message = f"chore(release): {tag}"
        tag_message = f"Release {tag}"
        self.runner.run(("git", "add", "--", *changed_paths))
        self._require_staged_release_paths(changed_paths)
        self.runner.run(("git", "commit", "-m", commit_message, "--", *changed_paths))
        commit = self._git_output("rev-parse", "HEAD")
        parent = self._single_parent(commit)
        if parent != baseline.remote_tip:
            raise RecoveryRequired(
                "RECOVERY REQUIRED: the release commit does not have the validated remote tip "
                "as its parent; inspect the local commit before proceeding"
            )
        self.runner.run(("git", "tag", "-a", tag, "-m", tag_message, commit))
        self._verify_annotated_tag(tag, commit)
        self._ensure_clean()

        identity = self._identity(
            version=next_version,
            branch=baseline.default_branch,
            parent=baseline.remote_tip,
            commit=commit,
        )
        if push:
            self._publish(identity)
        else:
            print(f"Prepared local release commit: {commit}")
            print(f"Prepared annotated tag: {tag}")
            print("Remote publication was not requested.")
            print(f"Atomic push command: {_display_command(identity.push_command)}")
        return identity

    def resume_push(self) -> ReleaseIdentity:
        self._ensure_clean()
        self._fetch_origin()
        remote = self._remote_state()
        self._require_current_branch(remote.default_branch)
        version = self._poetry_version()
        _stable_version(version, label="Poetry version")
        tag = f"v{version}"
        if tag in remote.stable_tags:
            raise ReleaseError(
                f"{tag} already exists on origin; resume will not publish anything"
            )

        head = self._git_output("rev-parse", "HEAD")
        parent = self._single_parent(head)
        if parent != remote.branch_tip:
            raise ReleaseError(
                f"the local release commit parent is no longer origin/{remote.default_branch}; "
                "recovery state is not safe to resume"
            )
        if self._rev_count(f"{remote.branch_tip}..HEAD") != 1:
            raise ReleaseError(
                "resume requires exactly one unpushed release commit at HEAD"
            )
        if self._rev_count(f"HEAD..{remote.branch_tip}") != 0:
            raise ReleaseError(
                "local and remote history is ambiguous; resume will not publish"
            )

        identity = self._validate_local_release_identity(
            remote=remote,
            version=version,
            expected_parent=parent,
        )
        self._publish(identity)
        return identity

    def _validate_preparation_preconditions(self) -> PreparationBaseline:
        self._ensure_clean()
        self.runner.run(("git", "var", "GIT_AUTHOR_IDENT"))
        self.runner.run(("git", "var", "GIT_COMMITTER_IDENT"))
        remote = self._remote_state()
        self._require_current_branch(remote.default_branch)
        head = self._git_output("rev-parse", "HEAD")
        if head != remote.branch_tip:
            raise ReleaseError(
                f"local HEAD {head} does not equal origin/{remote.default_branch} "
                f"{remote.branch_tip}; local/remote divergence is not allowed"
            )

        local_tags = self._local_stable_tags()
        if not remote.stable_tags:
            raise ReleaseError("origin has no exact stable-tag history")
        if local_tags != remote.stable_tags:
            raise ReleaseError(
                "local stable-tag history is incomplete or differs from origin; "
                "preconditions are read-only, so reconcile tags before retrying"
            )
        for tag in local_tags:
            ancestry = self.runner.run(
                ("git", "merge-base", "--is-ancestor", f"{tag}^{{}}", "HEAD"),
                check=False,
            )
            if ancestry.returncode != 0:
                raise ReleaseError(
                    f"stable tag {tag} is not contained in the checked-out history"
                )

        latest_tag = max(
            remote.stable_tags,
            key=lambda candidate: _stable_version(candidate[1:], label="stable tag"),
        )
        poetry_version = self._poetry_version()
        _stable_version(poetry_version, label="Poetry version")
        if latest_tag != f"v{poetry_version}":
            raise ReleaseError(
                f"latest exact stable tag {latest_tag} does not match Poetry version "
                f"{poetry_version}"
            )
        return PreparationBaseline(
            default_branch=remote.default_branch,
            remote_tip=remote.branch_tip,
            current_version=poetry_version,
        )

    def _remote_state(self) -> RemoteState:
        head_result = self.runner.run(
            ("git", "ls-remote", "--symref", "origin", "HEAD")
        )
        default_ref: str | None = None
        branch_tip: str | None = None
        for line in head_result.stdout.splitlines():
            if line.startswith("ref: "):
                target, separator, name = line.removeprefix("ref: ").partition("\t")
                if separator and name == "HEAD":
                    default_ref = target
            else:
                oid, separator, name = line.partition("\t")
                if separator and name == "HEAD":
                    branch_tip = oid
        prefix = "refs/heads/"
        if (
            default_ref is None
            or not default_ref.startswith(prefix)
            or branch_tip is None
        ):
            raise ReleaseError(
                "origin does not advertise a symbolic default branch and HEAD tip"
            )

        direct: dict[str, str] = {}
        peeled: dict[str, str] = {}
        tags_result = self.runner.run(("git", "ls-remote", "--tags", "origin"))
        for line in tags_result.stdout.splitlines():
            oid, separator, reference = line.partition("\t")
            if not separator or not reference.startswith("refs/tags/"):
                continue
            tag_reference = reference.removeprefix("refs/tags/")
            is_peeled = tag_reference.endswith("^{}")
            tag = tag_reference.removesuffix("^{}")
            if STABLE_VERSION.fullmatch(
                tag.removeprefix("v")
            ) is None or not tag.startswith("v"):
                continue
            if is_peeled:
                peeled[tag] = oid
            else:
                direct[tag] = oid
        stable_tags = {tag: peeled.get(tag, oid) for tag, oid in direct.items()}
        return RemoteState(
            default_branch=default_ref.removeprefix(prefix),
            branch_tip=branch_tip,
            stable_tags=stable_tags,
        )

    def _local_stable_tags(self) -> dict[str, str]:
        tags: dict[str, str] = {}
        for tag in self._git_output("tag", "--list").splitlines():
            if not tag.startswith("v") or STABLE_VERSION.fullmatch(tag[1:]) is None:
                continue
            peeled = self._git_output("rev-parse", f"{tag}^{{}}")
            if self._git_output("cat-file", "-t", peeled) != "commit":
                raise ReleaseError(f"stable tag {tag} does not peel to a commit")
            tags[tag] = peeled
        return tags

    def _poetry_version(self) -> str:
        return self._command_output(("poetry", "version", "--short"))

    def _poetry_bump(self, bump: str, *, dry_run: bool) -> str:
        command = ["poetry", "version", bump]
        if dry_run:
            command.append("--dry-run")
        command.append("--short")
        version = self._command_output(command)
        _stable_version(version, label="proposed Poetry version")
        return version

    def _poetry_changed_paths(self) -> tuple[str, ...]:
        staged = self._zero_paths("diff", "--cached", "--name-only", "-z", "--")
        untracked = self._zero_paths("ls-files", "--others", "--exclude-standard", "-z")
        changed = self._zero_paths("diff", "--name-only", "-z", "--")
        if staged or untracked or not changed:
            raise RecoveryRequired(
                "RECOVERY REQUIRED: Poetry version did not produce one isolated tracked-file "
                "working-tree change; inspect the repository before proceeding"
            )
        if "pyproject.toml" not in changed:
            raise RecoveryRequired(
                "RECOVERY REQUIRED: Poetry version did not modify pyproject.toml; "
                "inspect the repository before proceeding"
            )
        return changed

    def _current_changed_paths(self) -> tuple[str, ...]:
        staged = self._zero_paths("diff", "--cached", "--name-only", "-z", "--")
        untracked = self._zero_paths("ls-files", "--others", "--exclude-standard", "-z")
        changed = self._zero_paths("diff", "--name-only", "-z", "--")
        return tuple(sorted(set(staged + untracked + changed)))

    def _path_digests(self, paths: Sequence[str]) -> dict[str, str]:
        digests: dict[str, str] = {}
        for relative_path in paths:
            path = self.root / relative_path
            if not path.is_file():
                raise RecoveryRequired(
                    f"RECOVERY REQUIRED: expected release file is missing: {relative_path}"
                )
            digests[relative_path] = hashlib.sha256(path.read_bytes()).hexdigest()
        return digests

    def _restore_after_failed_mutation(
        self, original_version: str, *, context: str
    ) -> None:
        try:
            self.runner.run(("poetry", "version", original_version, "--short"))
        except ReleaseError as error:
            raise RecoveryRequired(
                f"RECOVERY REQUIRED: {context}, and Poetry could not restore version "
                f"{original_version}; no commit or tag was created. Inspect pyproject.toml and "
                "git status before making any manual change.\n"
                f"Restoration error: {error}"
            ) from error
        if not self._is_clean():
            raise RecoveryRequired(
                f"RECOVERY REQUIRED: {context}, and restoring the Poetry version did not "
                "return the working tree to clean. No commit or tag was created; inspect git "
                "status and the changed files without resetting them."
            )

    def _require_staged_release_paths(self, paths: Sequence[str]) -> None:
        staged = self._zero_paths("diff", "--cached", "--name-only", "-z", "--")
        unstaged = self._zero_paths("diff", "--name-only", "-z", "--")
        untracked = self._zero_paths("ls-files", "--others", "--exclude-standard", "-z")
        if staged != tuple(sorted(paths)) or unstaged or untracked:
            raise RecoveryRequired(
                "RECOVERY REQUIRED: the index no longer contains exactly the files changed by "
                "Poetry version; inspect the staged and working-tree changes"
            )

    def _ensure_new_tag_absent(self, tag: str) -> None:
        local = self.runner.run(
            ("git", "show-ref", "--verify", "--quiet", f"refs/tags/{tag}"),
            check=False,
        )
        if local.returncode == 0:
            raise ReleaseError(f"local tag {tag} already exists")
        if local.returncode not in (0, 1):
            raise CommandFailure(local)
        remote = self._remote_state()
        if tag in remote.stable_tags:
            raise ReleaseError(f"tag {tag} already exists on origin")

    def _fetch_origin(self) -> None:
        self.runner.run(("git", "fetch", "--prune", "--tags", "origin"))

    def _publish(self, identity: ReleaseIdentity) -> None:
        self._fetch_origin()
        remote = self._remote_state()
        if remote.default_branch != identity.branch:
            raise ReleaseError(
                f"origin default branch changed from {identity.branch} to "
                f"{remote.default_branch}; no push was attempted"
            )
        if remote.branch_tip != identity.parent:
            raise ReleaseError(
                f"remote default branch changed from {identity.parent} to {remote.branch_tip}; "
                "no push was attempted"
            )
        if identity.tag in remote.stable_tags:
            raise ReleaseError(
                f"{identity.tag} already exists on origin; no push was attempted"
            )

        validated = self._validate_local_release_identity(
            remote=remote,
            version=identity.version,
            expected_parent=identity.parent,
        )
        if validated != identity:
            raise ReleaseError(
                "local release identity changed before publication; no push attempted"
            )

        result = self.runner.run(identity.push_command, check=False)
        if result.returncode != 0:
            detail = (
                result.stderr.strip() or result.stdout.strip() or "no diagnostic output"
            )
            raise PublicationUnconfirmed(
                "atomic push failed; remote publication is unconfirmed. The local release "
                f"commit and annotated tag remain available for inspection. Resume only with:\n"
                "  python scripts/release_version.py --resume-push\n"
                f"Git diagnostic: {detail}"
            )

        published = self._remote_state()
        if (
            published.branch_tip != identity.commit
            or published.stable_tags.get(identity.tag) != identity.commit
        ):
            raise PublicationUnconfirmed(
                "atomic push returned success but the exact branch and tag refs could not be "
                "confirmed. Inspect origin before attempting resume."
            )
        print(f"Published {identity.tag} atomically to origin/{identity.branch}.")

    def _validate_local_release_identity(
        self,
        *,
        remote: RemoteState,
        version: str,
        expected_parent: str,
    ) -> ReleaseIdentity:
        self._ensure_clean()
        self._require_current_branch(remote.default_branch)
        if self._poetry_version() != version:
            raise ReleaseError(
                "the committed Poetry version changed; release identity is invalid"
            )

        tag = f"v{version}"
        head = self._git_output("rev-parse", "HEAD")
        parent = self._single_parent(head)
        if parent != expected_parent:
            raise ReleaseError(
                "the release commit parent changed; release identity is invalid"
            )
        if self._rev_count(f"{expected_parent}..HEAD") != 1:
            raise ReleaseError(
                "HEAD is not exactly one release commit above the remote parent"
            )

        expected_subject = f"chore(release): {tag}"
        subject = self._git_output("show", "-s", "--format=%s", "HEAD")
        if subject != expected_subject:
            raise ReleaseError(
                f"release commit subject must be exactly {expected_subject!r}; found {subject!r}"
            )
        changed_paths = self._git_output(
            "diff-tree",
            "--no-commit-id",
            "--name-only",
            "-r",
            "HEAD",
        ).splitlines()
        if changed_paths != ["pyproject.toml"]:
            raise ReleaseError(
                "release commit must contain only the Poetry version change in pyproject.toml"
            )

        tags = tuple(
            tag_name
            for tag_name in self._git_output("tag", "--points-at", "HEAD").splitlines()
        )
        if tags != (tag,):
            raise ReleaseError(
                f"release HEAD must have exactly one tag ({tag}); found: "
                f"{', '.join(tags) if tags else 'none'}"
            )
        self._verify_annotated_tag(tag, head)
        return self._identity(
            version=version,
            branch=remote.default_branch,
            parent=parent,
            commit=head,
        )

    def _verify_annotated_tag(self, tag: str, expected_commit: str) -> None:
        object_type = self._git_output("cat-file", "-t", tag)
        if object_type != "tag":
            raise ReleaseError(
                f"{tag} must be an annotated tag object, found {object_type!r}"
            )
        peeled = self._git_output("rev-parse", f"{tag}^{{}}")
        if peeled != expected_commit:
            raise ReleaseError(
                f"annotated tag {tag} peels to {peeled}, not release commit {expected_commit}"
            )

    def _identity(
        self,
        *,
        version: str,
        branch: str,
        parent: str,
        commit: str | None,
    ) -> ReleaseIdentity:
        tag = f"v{version}"
        return ReleaseIdentity(
            version=version,
            tag=tag,
            branch=branch,
            parent=parent,
            commit=commit,
            commit_message=f"chore(release): {tag}",
            tag_message=f"Release {tag}",
            push_command=(
                "git",
                "push",
                "--atomic",
                "origin",
                f"HEAD:{branch}",
                f"refs/tags/{tag}",
            ),
        )

    def _report_dry_run(self, identity: ReleaseIdentity) -> None:
        print(
            "Release dry-run: all checks passed; no file or Git reference was changed."
        )
        print(f"Proposed version: {identity.version}")
        print(f"Commit message: {identity.commit_message}")
        print(f"Annotated tag: {identity.tag} ({identity.tag_message})")
        print(f"Atomic push command: {_display_command(identity.push_command)}")

    def _require_current_branch(self, expected: str) -> None:
        result = self.runner.run(
            ("git", "symbolic-ref", "--quiet", "--short", "HEAD"),
            check=False,
        )
        branch = result.stdout.strip() if result.returncode == 0 else "detached HEAD"
        if result.returncode != 0 or branch != expected:
            raise ReleaseError(
                f"checked-out branch must be origin's default branch {expected!r}; found {branch!r}"
            )

    def _single_parent(self, commit: str) -> str:
        fields = self._git_output("rev-list", "--parents", "-n", "1", commit).split()
        if len(fields) != 2:
            raise ReleaseError("release commit must have exactly one parent")
        return fields[1]

    def _rev_count(self, revision_range: str) -> int:
        value = self._git_output("rev-list", "--count", revision_range)
        try:
            return int(value)
        except ValueError as error:
            raise ReleaseError(
                f"Git returned an invalid revision count: {value!r}"
            ) from error

    def _is_clean(self) -> bool:
        return (
            self._git_output("status", "--porcelain=v1", "--untracked-files=all") == ""
        )

    def _ensure_clean(self) -> None:
        if not self._is_clean():
            raise ReleaseError("release preparation requires a clean working tree")

    def _zero_paths(self, *args: str) -> tuple[str, ...]:
        output = self.runner.run(("git", *args)).stdout
        return tuple(sorted(path for path in output.split("\0") if path))

    def _git_output(self, *args: str) -> str:
        return self._command_output(("git", *args))

    def _command_output(self, args: Sequence[str]) -> str:
        return self.runner.run(args).stdout.strip()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Prepare or resume one guarded Poetry release transaction."
    )
    parser.add_argument("bump", nargs="?", choices=BUMP_KINDS)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--dry-run", action="store_true", help="check and report without mutation"
    )
    mode.add_argument(
        "--push", action="store_true", help="prepare and atomically publish"
    )
    mode.add_argument(
        "--resume-push",
        action="store_true",
        help="validate and atomically publish an existing local release identity",
    )
    return parser


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.resume_push and args.bump is not None:
        parser.error("--resume-push does not accept a bump kind")
    if not args.resume_push and args.bump is None:
        parser.error("choose exactly one bump kind: major, minor, or patch")
    return args


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    bootstrap = CommandRunner(Path.cwd())
    try:
        root = Path(
            bootstrap.run(("git", "rev-parse", "--show-toplevel")).stdout.strip()
        )
        runner = CommandRunner(root)
        transaction = ReleaseTransaction(root, runner)
        if args.resume_push:
            transaction.resume_push()
        else:
            transaction.prepare(args.bump, dry_run=args.dry_run, push=args.push)
    except ReleaseError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
