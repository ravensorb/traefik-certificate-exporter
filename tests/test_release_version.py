from __future__ import annotations

import re
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

import pytest

from scripts import release_version
from tests.support import tracked_text_files


def _run(
    cwd: Path,
    *args: str,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        list(args),
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )
    if check and result.returncode != 0:
        raise AssertionError(
            f"command failed ({result.returncode}): {' '.join(args)}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    return result


def _git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return _run(cwd, "git", *args, check=check)


@dataclass(frozen=True)
class Repositories:
    work: Path
    remote: Path


def _create_repositories(tmp_path: Path) -> Repositories:
    remote = tmp_path / "remote.git"
    work = tmp_path / "work"
    remote.mkdir()
    work.mkdir()

    _git(remote, "init", "--bare", "--initial-branch=main")
    _git(work, "init", "--initial-branch=main")
    _git(work, "config", "user.name", "Release Test")
    _git(work, "config", "user.email", "release@example.invalid")
    (work / "pyproject.toml").write_text(
        """[tool.poetry]
name = "release-fixture"
version = "1.2.3"
description = "Release fixture"
authors = ["Release Test <release@example.invalid>"]
""",
        encoding="utf-8",
    )
    _git(work, "add", "pyproject.toml")
    _git(work, "commit", "-m", "Initial release")
    _git(work, "tag", "-a", "v1.2.3", "-m", "Release v1.2.3")
    _git(work, "remote", "add", "origin", str(remote))
    _git(work, "push", "--set-upstream", "origin", "main", "refs/tags/v1.2.3")
    return Repositories(work=work, remote=remote)


@pytest.fixture
def repositories(tmp_path: Path) -> Repositories:
    return _create_repositories(tmp_path)


def _refs(repo: Path) -> str:
    return _git(repo, "show-ref", "--head", check=False).stdout


def _snapshot(repositories: Repositories) -> tuple[bytes, str, str, str, str]:
    return (
        (repositories.work / "pyproject.toml").read_bytes(),
        _git(repositories.work, "status", "--porcelain=v1").stdout,
        _git(repositories.work, "rev-parse", "HEAD").stdout,
        _refs(repositories.work),
        _refs(repositories.remote),
    )


def _result(args: Sequence[str], returncode: int = 0, stderr: str = ""):
    return release_version.CommandResult(
        args=tuple(args),
        returncode=returncode,
        stdout="",
        stderr=stderr,
    )


class RecordingRunner(release_version.CommandRunner):
    def __init__(
        self,
        cwd: Path,
        *,
        gate_returncode: int = 0,
        after_gate: Callable[[], None] | None = None,
        before_push: Callable[[], None] | None = None,
        push_failure: str | None = None,
        restoration_failure: bool = False,
    ) -> None:
        super().__init__(cwd)
        self.gate_returncode = gate_returncode
        self.after_gate = after_gate
        self.before_push = before_push
        self.push_failure = push_failure
        self.restoration_failure = restoration_failure
        self.commands: list[tuple[str, ...]] = []

    def run(
        self,
        args: Sequence[str],
        *,
        check: bool = True,
    ) -> release_version.CommandResult:
        command = tuple(args)
        self.commands.append(command)

        if command == ("just", "check"):
            result = _result(
                command,
                self.gate_returncode,
                "configured gate failure" if self.gate_returncode else "",
            )
            if self.after_gate is not None:
                callback, self.after_gate = self.after_gate, None
                callback()
            return result

        if self.restoration_failure and command == (
            "poetry",
            "version",
            "1.2.3",
            "--short",
        ):
            result = _result(command, 1, "configured restoration failure")
            if check:
                raise release_version.CommandFailure(result)
            return result

        if command[:4] == ("git", "push", "--atomic", "origin"):
            if self.before_push is not None:
                callback, self.before_push = self.before_push, None
                callback()
            if self.push_failure is not None:
                return _result(command, 1, self.push_failure)

        return super().run(command, check=check)


def _transaction(
    repositories: Repositories,
    runner: RecordingRunner | None = None,
) -> tuple[release_version.ReleaseTransaction, RecordingRunner]:
    command_runner = runner or RecordingRunner(repositories.work)
    return (
        release_version.ReleaseTransaction(repositories.work, command_runner),
        command_runner,
    )


def _push_commands(runner: RecordingRunner) -> list[tuple[str, ...]]:
    return [command for command in runner.commands if command[:2] == ("git", "push")]


def _assert_only_atomic_release_pushes(runner: RecordingRunner) -> None:
    for command in _push_commands(runner):
        assert command[:4] == ("git", "push", "--atomic", "origin")
        assert len(command) == 6
        assert command[4].startswith("HEAD:")
        assert command[5].startswith("refs/tags/v")
        assert "--tags" not in command
        assert "--force" not in command
        assert not any("*" in argument for argument in command)


@pytest.mark.parametrize(
    "argv",
    [[], ["banana"], ["patch", "minor"], ["patch", "--resume-push"]],
)
def test_invalid_or_ambiguous_bump_fails_before_any_command(
    argv: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def unexpected_command(*_args, **_kwargs):
        raise AssertionError("argument errors must not execute a subprocess")

    monkeypatch.setattr(subprocess, "run", unexpected_command)

    with pytest.raises(SystemExit) as exc_info:
        release_version.main(argv)

    assert exc_info.value.code == 2


def test_dirty_tree_precondition_is_read_only(repositories: Repositories) -> None:
    (repositories.work / "dirty.txt").write_text("not committed\n", encoding="utf-8")
    before = _snapshot(repositories)
    transaction, _ = _transaction(repositories)

    with pytest.raises(release_version.ReleaseError, match="clean working tree"):
        transaction.prepare("patch", dry_run=True, push=False)

    assert _snapshot(repositories) == before


def test_wrong_branch_precondition_is_read_only(repositories: Repositories) -> None:
    _git(repositories.work, "switch", "-c", "feature")
    before = _snapshot(repositories)
    transaction, _ = _transaction(repositories)

    with pytest.raises(release_version.ReleaseError, match="default branch"):
        transaction.prepare("patch", dry_run=True, push=False)

    assert _snapshot(repositories) == before


def test_diverged_branch_precondition_is_read_only(repositories: Repositories) -> None:
    (repositories.work / "local.txt").write_text("local only\n", encoding="utf-8")
    _git(repositories.work, "add", "local.txt")
    _git(repositories.work, "commit", "-m", "Local-only commit")
    before = _snapshot(repositories)
    transaction, _ = _transaction(repositories)

    with pytest.raises(
        release_version.ReleaseError, match="does not equal origin/main"
    ):
        transaction.prepare("patch", dry_run=True, push=False)

    assert _snapshot(repositories) == before


def test_missing_stable_tag_precondition_is_read_only(
    repositories: Repositories,
) -> None:
    _git(repositories.work, "tag", "-d", "v1.2.3")
    before = _snapshot(repositories)
    transaction, _ = _transaction(repositories)

    with pytest.raises(release_version.ReleaseError, match="stable-tag history"):
        transaction.prepare("patch", dry_run=True, push=False)

    assert _snapshot(repositories) == before


def test_mismatched_stable_tag_and_poetry_version_is_read_only(
    repositories: Repositories,
) -> None:
    _run(repositories.work, "poetry", "version", "1.2.2", "--short")
    _git(repositories.work, "add", "pyproject.toml")
    _git(repositories.work, "commit", "-m", "Set mismatched version")
    _git(repositories.work, "push", "origin", "main")
    before = _snapshot(repositories)
    transaction, _ = _transaction(repositories)

    with pytest.raises(release_version.ReleaseError, match="Poetry version 1.2.2"):
        transaction.prepare("patch", dry_run=True, push=False)

    assert _snapshot(repositories) == before


def test_dry_run_reports_transaction_and_changes_nothing(
    repositories: Repositories, capsys: pytest.CaptureFixture[str]
) -> None:
    before = _snapshot(repositories)
    transaction, runner = _transaction(repositories)

    identity = transaction.prepare("patch", dry_run=True, push=False)

    output = capsys.readouterr().out
    assert identity.version == "1.2.4"
    assert "Proposed version: 1.2.4" in output
    assert "Commit message: chore(release): v1.2.4" in output
    assert "Annotated tag: v1.2.4 (Release v1.2.4)" in output
    assert "git push --atomic origin HEAD:main refs/tags/v1.2.4" in output
    assert _snapshot(repositories) == before
    assert ("poetry", "version", "patch", "--dry-run", "--short") in runner.commands
    assert ("just", "check") not in runner.commands


def test_gate_success_creates_only_version_commit_and_annotated_tag(
    repositories: Repositories, capsys: pytest.CaptureFixture[str]
) -> None:
    remote_before = _refs(repositories.remote)
    parent = _git(repositories.work, "rev-parse", "HEAD").stdout.strip()
    transaction, runner = _transaction(repositories)

    identity = transaction.prepare("patch", dry_run=False, push=False)

    head = _git(repositories.work, "rev-parse", "HEAD").stdout.strip()
    output = capsys.readouterr().out
    assert identity.version == "1.2.4"
    assert head != parent
    assert _git(
        repositories.work, "show", "-s", "--format=%s", "HEAD"
    ).stdout.strip() == ("chore(release): v1.2.4")
    assert _git(
        repositories.work,
        "diff-tree",
        "--no-commit-id",
        "--name-only",
        "-r",
        "HEAD",
    ).stdout.splitlines() == ["pyproject.toml"]
    assert _git(repositories.work, "cat-file", "-t", "v1.2.4").stdout.strip() == "tag"
    assert _git(repositories.work, "rev-parse", "v1.2.4^{}").stdout.strip() == head
    assert _git(repositories.work, "status", "--porcelain=v1").stdout == ""
    assert _refs(repositories.remote) == remote_before
    assert "git push --atomic origin HEAD:main refs/tags/v1.2.4" in output
    assert ("just", "check") in runner.commands
    assert _push_commands(runner) == []


def test_gate_failure_restores_original_version_and_clean_tree(
    repositories: Repositories,
) -> None:
    before = _snapshot(repositories)
    runner = RecordingRunner(repositories.work, gate_returncode=1)
    transaction, runner = _transaction(repositories, runner)

    with pytest.raises(release_version.ReleaseError, match="just check failed"):
        transaction.prepare("patch", dry_run=False, push=False)

    assert _snapshot(repositories) == before
    assert ("poetry", "version", "1.2.3", "--short") in runner.commands
    assert _push_commands(runner) == []


def test_restoration_failure_stops_in_explicit_recovery_state(
    repositories: Repositories,
) -> None:
    original_head = _git(repositories.work, "rev-parse", "HEAD").stdout
    runner = RecordingRunner(
        repositories.work,
        gate_returncode=1,
        restoration_failure=True,
    )
    transaction, runner = _transaction(repositories, runner)

    with pytest.raises(release_version.RecoveryRequired, match="RECOVERY REQUIRED"):
        transaction.prepare("patch", dry_run=False, push=False)

    assert _git(repositories.work, "rev-parse", "HEAD").stdout == original_head
    assert (
        _run(repositories.work, "poetry", "version", "--short").stdout.strip()
        == "1.2.4"
    )
    assert _git(repositories.work, "status", "--porcelain=v1").stdout != ""
    assert "v1.2.4" not in _git(repositories.work, "tag", "--list").stdout.splitlines()
    assert _push_commands(runner) == []


def test_successful_atomic_push_publishes_branch_and_exact_tag(
    repositories: Repositories,
) -> None:
    transaction, runner = _transaction(repositories)

    identity = transaction.prepare("patch", dry_run=False, push=True)

    head = _git(repositories.work, "rev-parse", "HEAD").stdout.strip()
    assert identity.tag == "v1.2.4"
    assert (
        _git(repositories.remote, "rev-parse", "refs/heads/main").stdout.strip() == head
    )
    assert (
        _git(repositories.remote, "rev-parse", "refs/tags/v1.2.4^{}").stdout.strip()
        == head
    )
    assert _push_commands(runner) == [
        (
            "git",
            "push",
            "--atomic",
            "origin",
            "HEAD:main",
            "refs/tags/v1.2.4",
        )
    ]
    _assert_only_atomic_release_pushes(runner)


def _advance_remote(repositories: Repositories, clone_path: Path) -> str:
    _git(clone_path.parent, "clone", str(repositories.remote), str(clone_path))
    _git(clone_path, "config", "user.name", "Remote Racer")
    _git(clone_path, "config", "user.email", "racer@example.invalid")
    (clone_path / "race.txt").write_text("remote advanced\n", encoding="utf-8")
    _git(clone_path, "add", "race.txt")
    _git(clone_path, "commit", "-m", "Remote advancement")
    _git(clone_path, "push", "origin", "main")
    return _git(clone_path, "rev-parse", "HEAD").stdout.strip()


def _create_remote_tag(
    repositories: Repositories,
    clone_path: Path,
    tag: str,
) -> str:
    _git(clone_path.parent, "clone", str(repositories.remote), str(clone_path))
    _git(clone_path, "config", "user.name", "Remote Racer")
    _git(clone_path, "config", "user.email", "racer@example.invalid")
    target = _git(clone_path, "rev-parse", "HEAD").stdout.strip()
    _git(clone_path, "tag", "-a", tag, "-m", f"Racing {tag}")
    _git(clone_path, "push", "origin", f"refs/tags/{tag}")
    return target


def test_remote_advancement_before_pre_push_validation_attempts_no_push(
    repositories: Repositories, tmp_path: Path
) -> None:
    remote_head = ""

    def advance() -> None:
        nonlocal remote_head
        remote_head = _advance_remote(repositories, tmp_path / "advance-clone")

    runner = RecordingRunner(repositories.work, after_gate=advance)
    transaction, runner = _transaction(repositories, runner)

    with pytest.raises(
        release_version.ReleaseError, match="remote default branch changed"
    ):
        transaction.prepare("patch", dry_run=False, push=True)

    assert (
        _git(repositories.remote, "rev-parse", "refs/heads/main").stdout.strip()
        == remote_head
    )
    assert _git(repositories.remote, "tag", "--list", "v1.2.4").stdout == ""
    assert _push_commands(runner) == []


def test_remote_tag_creation_race_is_rejected_atomically(
    repositories: Repositories, tmp_path: Path
) -> None:
    original_remote_head = _git(repositories.remote, "rev-parse", "main").stdout.strip()
    racing_target = ""

    def create_tag() -> None:
        nonlocal racing_target
        racing_target = _create_remote_tag(
            repositories,
            tmp_path / "tag-race-clone",
            "v1.2.4",
        )

    runner = RecordingRunner(repositories.work, before_push=create_tag)
    transaction, runner = _transaction(repositories, runner)

    with pytest.raises(release_version.PublicationUnconfirmed, match="resume"):
        transaction.prepare("patch", dry_run=False, push=True)

    assert (
        _git(repositories.remote, "rev-parse", "main").stdout.strip()
        == original_remote_head
    )
    assert (
        _git(repositories.remote, "rev-parse", "v1.2.4^{}").stdout.strip()
        == racing_target
    )
    _assert_only_atomic_release_pushes(runner)


def test_unsupported_atomic_push_has_no_non_atomic_fallback(
    repositories: Repositories,
) -> None:
    remote_before = _refs(repositories.remote)
    runner = RecordingRunner(
        repositories.work,
        push_failure="the receiving end does not support --atomic push",
    )
    transaction, runner = _transaction(repositories, runner)

    with pytest.raises(
        release_version.PublicationUnconfirmed, match="not support --atomic"
    ):
        transaction.prepare("patch", dry_run=False, push=True)

    assert _refs(repositories.remote) == remote_before
    assert "v1.2.4" in _git(repositories.work, "tag", "--list").stdout.splitlines()
    _assert_only_atomic_release_pushes(runner)
    assert len(_push_commands(runner)) == 1


def test_atomic_push_failure_preserves_local_identity_and_remote_refs(
    repositories: Repositories,
) -> None:
    hook = repositories.remote / "hooks" / "pre-receive"
    hook.write_text(
        "#!/bin/sh\necho configured rejection >&2\nexit 1\n", encoding="utf-8"
    )
    hook.chmod(0o755)
    remote_before = _refs(repositories.remote)
    transaction, runner = _transaction(repositories)

    with pytest.raises(
        release_version.PublicationUnconfirmed, match="publication is unconfirmed"
    ):
        transaction.prepare("patch", dry_run=False, push=True)

    head = _git(repositories.work, "rev-parse", "HEAD").stdout.strip()
    assert _git(repositories.work, "rev-parse", "v1.2.4^{}").stdout.strip() == head
    assert _refs(repositories.remote) == remote_before
    _assert_only_atomic_release_pushes(runner)


def test_valid_resume_pushes_existing_identity_without_repreparing(
    repositories: Repositories,
) -> None:
    prepare_transaction, _ = _transaction(repositories)
    identity = prepare_transaction.prepare("patch", dry_run=False, push=False)
    resume_transaction, runner = _transaction(repositories)

    resumed = resume_transaction.resume_push()

    head = _git(repositories.work, "rev-parse", "HEAD").stdout.strip()
    assert resumed == identity
    assert _git(repositories.remote, "rev-parse", "main").stdout.strip() == head
    assert _git(repositories.remote, "rev-parse", "v1.2.4^{}").stdout.strip() == head
    assert not any(
        command[:2] == ("poetry", "version")
        and command != ("poetry", "version", "--short")
        for command in runner.commands
    )
    assert not any(command[:2] == ("git", "commit") for command in runner.commands)
    assert not any(command[:3] == ("git", "tag", "-a") for command in runner.commands)
    _assert_only_atomic_release_pushes(runner)


def test_resume_rejects_changed_remote_parent_without_push(
    repositories: Repositories, tmp_path: Path
) -> None:
    prepare_transaction, _ = _transaction(repositories)
    prepare_transaction.prepare("patch", dry_run=False, push=False)
    remote_head = _advance_remote(repositories, tmp_path / "resume-advance-clone")
    resume_transaction, runner = _transaction(repositories)

    with pytest.raises(release_version.ReleaseError, match="parent is no longer"):
        resume_transaction.resume_push()

    assert _git(repositories.remote, "rev-parse", "main").stdout.strip() == remote_head
    assert _git(repositories.remote, "tag", "--list", "v1.2.4").stdout == ""
    assert _push_commands(runner) == []


def test_resume_rejects_multiple_tags_without_push(
    repositories: Repositories,
) -> None:
    prepare_transaction, _ = _transaction(repositories)
    prepare_transaction.prepare("patch", dry_run=False, push=False)
    _git(repositories.work, "tag", "-a", "extra-marker", "-m", "Ambiguous marker")
    resume_transaction, runner = _transaction(repositories)

    with pytest.raises(release_version.ReleaseError, match="exactly one tag"):
        resume_transaction.resume_push()

    assert _push_commands(runner) == []


def test_resume_rejects_lightweight_tag_without_push(
    repositories: Repositories,
) -> None:
    prepare_transaction, _ = _transaction(repositories)
    prepare_transaction.prepare("patch", dry_run=False, push=False)
    _git(repositories.work, "tag", "-d", "v1.2.4")
    _git(repositories.work, "tag", "v1.2.4")
    resume_transaction, runner = _transaction(repositories)

    with pytest.raises(release_version.ReleaseError, match="annotated tag"):
        resume_transaction.resume_push()

    assert _push_commands(runner) == []


def test_resume_rejects_already_present_remote_tag_without_push(
    repositories: Repositories,
) -> None:
    prepare_transaction, _ = _transaction(repositories)
    prepare_transaction.prepare("patch", dry_run=False, push=False)
    _git(repositories.work, "push", "origin", "refs/tags/v1.2.4")
    original_remote_branch = _git(
        repositories.remote, "rev-parse", "main"
    ).stdout.strip()
    resume_transaction, runner = _transaction(repositories)

    with pytest.raises(release_version.ReleaseError, match="already exists on origin"):
        resume_transaction.resume_push()

    assert (
        _git(repositories.remote, "rev-parse", "main").stdout.strip()
        == original_remote_branch
    )
    assert _push_commands(runner) == []


def test_justfile_release_recipes_are_thin_delegates() -> None:
    justfile = (Path(__file__).parents[1] / "justfile").read_text(encoding="utf-8")

    assert "release-dry-run bump:" in justfile
    assert re.search(
        r"poetry run python scripts/release_version\.py \{\{\s*bump\s*\}\} --dry-run",
        justfile,
    )
    assert "release bump:" in justfile
    assert re.search(
        r"poetry run python scripts/release_version\.py \{\{\s*bump\s*\}\} --push",
        justfile,
    )
    assert "release-resume:" in justfile
    assert "python scripts/release_version.py --resume-push" in justfile


def test_legacy_release_script_is_retired() -> None:
    """The unsafe path is gone, not merely stubbed (story E008-S01-004's cutover).

    It was a refusal stub for two epics, which was the right holding position while the
    replacement was being built. A stub is still a file an operator can find and a script
    another script can call, so the cutover deletes it -- and the guard becomes reach
    rather than content: the file is absent, and nothing git tracks invokes it. Prose
    that *names* it, as ADR-0006 does when explaining why it went, is not an invocation:
    the pattern matches a command position, and a leading backtick -- how prose cites a
    path -- is excluded. An invocation in documentation lives in a fenced block, where
    no backtick precedes it, and is still caught.
    """
    root = Path(__file__).parents[1]
    assert not (root / "scripts" / "git-increment-version.sh").exists(), (
        "scripts/git-increment-version.sh is retired; releases go through "
        "`just release`, which drives scripts/release_version.py"
    )

    invocation = re.compile(
        r"(?<![\w./$`-])(?:[\w.${}-]+/)*git-increment-version\.sh(?![\w.-])"
    )
    # This module names the retired script as data, so its own source is the one file
    # the scan cannot read -- skipped by identity, and asserted to be the only one.
    exempt = str(Path(__file__).relative_to(root))
    assert exempt == "tests/test_release_version.py"

    examined = 0
    for relative, text in tracked_text_files():
        if relative == exempt:
            continue
        examined += 1
        match = invocation.search(text)
        assert match is None, f"{relative} invokes the retired {match.group(0)!r}"
    assert examined, "no tracked file was examined"


def test_release_helper_never_uses_shell_execution() -> None:
    source = (Path(__file__).parents[1] / "scripts" / "release_version.py").read_text(
        encoding="utf-8"
    )

    assert "shell=True" not in source
    assert "os.system" not in source
