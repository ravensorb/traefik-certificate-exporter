"""The gates themselves: what runs, over what, and whether it can fail.

BL-E008-010 phase 3. These guards do not examine the pipeline -- they examine the checks
that examine it, which is why they sit apart from every subject module.

Two of this project's worst defects lived here and both were green throughout. The secret
scanner ran the upstream `--staged` invocation under `--all-files`, so it read
`~0 bytes (0)` on every commit of the project's history; and the interpreter matrix
declared five versions while installing one, interpolating the dimension into the job name
so CI displayed five and ran one. A gate whose scope is empty reports success, which is
indistinguishable from a gate that looked and found nothing -- so these ask whether each
gate examines a non-empty set, actually runs in CI, and can be made to fail on demand.
"""

from __future__ import annotations

import re
import subprocess
import sys
from typing import Any

import yaml

from tests.ci.support import (
    PROJECT_ROOT,
    VERIFY_WORKFLOW,
    _jobs,
    _load_workflow,
    _uncommented,
)

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - exercised only on the oldest supported interpreter
    import tomli as tomllib

PRE_COMMIT_CONFIG = PROJECT_ROOT / ".pre-commit-config.yaml"


GITLEAKS_CONFIG = PROJECT_ROOT / ".gitleaks.toml"


def _gitleaks_hook() -> dict[str, Any]:
    config = yaml.safe_load(PRE_COMMIT_CONFIG.read_text(encoding="utf-8"))
    for repository in config["repos"]:
        for hook in repository["hooks"]:
            if hook["id"] == "gitleaks":
                return hook
    raise AssertionError("no gitleaks hook is configured")


def test_the_secret_scanner_reads_content_rather_than_the_index() -> None:
    """The gate passed over every commit of this project without reading any of it.

    The upstream hook's entry is `gitleaks git --pre-commit --redact --staged
    --verbose`, which scans the git *index*. `pre-commit run gitleaks --all-files` --
    what CI runs, and what `just check` runs -- stages nothing, so it read
    `~0 bytes (0)`, reported `no leaks found` and exited 0. Reproduced against a
    repository holding a live-format GitHub PAT and Slack bot token: the staged form
    exits 0, `gitleaks dir` finds both and exits 1.

    A green secret scanner that reads nothing is worse than no scanner, because it is
    the control everyone assumes has looked. The real proof is in verify-build.yaml,
    which runs the configured invocation against a planted credential on every CI run
    (`test_the_secret_scanner_proves_itself_in_ci` requires that step to exist). This
    guard covers the shape, so the defect cannot come back by editing one word.
    """
    entry = str(_gitleaks_hook()["entry"])
    assert "--staged" not in entry, (
        f"the secret scanner is back on the index rather than content: {entry}"
    )
    assert entry.split()[1] == "dir", (
        f"the secret scanner must scan a directory of content: {entry}"
    )
    assert _gitleaks_hook().get("pass_filenames") is False, (
        "`gitleaks dir` takes exactly one path; pre-commit must not append the changed "
        "file list to it"
    )


# Hooks that deliberately never run in CI, and why. Same registry shape as everywhere
# else here: an entry IS the acceptance of a coverage gap, and silence is not allowed.
LOCAL_ONLY_HOOKS: dict[str, str] = {
    "justfile-fmt": (
        "CI installs no `just`, so no workflow can run it. A real coverage limit, "
        "recorded rather than left to be discovered: the drift it catches -- one story "
        "formatting the shared justfile and a later one unformatting it -- happened."
    ),
}


def _configured_hooks() -> list[dict[str, Any]]:
    config = yaml.safe_load(PRE_COMMIT_CONFIG.read_text(encoding="utf-8"))
    return [hook for repository in config["repos"] for hook in repository["hooks"]]


def _hook_id(hook: dict[str, Any]) -> str:
    """A hook's addressable name -- its alias where it has one, since two hooks here
    share an `id` and differ only by alias."""
    return str(hook.get("alias", hook["id"]))


def _tracked_paths() -> list[str]:
    return subprocess.run(
        ["git", "ls-files"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()


def test_no_configured_gate_examines_an_empty_set() -> None:
    """The generalisation of this epic's worst gate defect.

    The secret scanner ran a correctly-configured hook over an empty file set --
    `~0 bytes (0)`, exit 0, on every commit of this project's history -- and the pytest
    matrix installed one interpreter under five names. Both were green throughout, and
    both are the same failure: **a gate whose scope is empty reports success**, which is
    indistinguishable from a gate that looked and found nothing.

    A `files:` pattern that matches no tracked file is the cheapest way back into that
    state, and it arrives by ordinary means -- moving a directory, renaming a module.
    `mypy` here is scoped to `^(src/publication_contract/|scripts/(committed_versions|
    release_version)\\.py)`; relocate either and the type checker silently checks
    nothing while its job still reports green.

    A hook passing no filenames is exempt from the pattern check and must instead be
    `always_run`, or pre-commit may not invoke it at all.
    """
    config = yaml.safe_load(PRE_COMMIT_CONFIG.read_text(encoding="utf-8"))
    excluded = re.compile(str(config["exclude"]))
    tracked = [path for path in _tracked_paths() if not excluded.match(path)]
    assert tracked, "no tracked files outside the excluded trees; nothing was examined"

    hooks = _configured_hooks()
    assert hooks, "no hooks are configured; this guard examined nothing"
    for hook in hooks:
        name = _hook_id(hook)
        pattern = hook.get("files")
        if pattern:
            matched = [path for path in tracked if re.search(str(pattern), path)]
            assert matched, (
                f"the {name!r} gate is scoped to files: {pattern!r}, which matches no "
                f"tracked file. It runs, it reports success, and it examines nothing."
            )
        elif hook.get("pass_filenames") is False:
            assert hook.get("always_run") is True, (
                f"the {name!r} gate passes no filenames and is not `always_run`, so "
                f"pre-commit may never invoke it"
            )


def test_every_gate_runs_in_ci_or_is_recorded_as_local_only() -> None:
    """A hook nobody runs is a gate in name only.

    `justfile-fmt` is the honest case -- CI installs no `just` -- and it is registered
    with that reason. Everything else configured for the commit stage must be run by a
    job in the governed verifier, because "it is in .pre-commit-config.yaml" is exactly
    the kind of assurance this epic kept finding to be empty.

    Manual-stage hooks are excluded: they are the non-mutating twins `just lint` runs,
    and their mutating counterparts are what CI executes.
    """
    ci = "\n".join(
        _uncommented(str(step.get("run", "")))
        for job in _jobs(_load_workflow(VERIFY_WORKFLOW)).values()
        for step in job.get("steps") or []
    )
    assert "pre-commit run" in ci, "the verifier runs no hooks; nothing was examined"
    examined = 0
    for hook in _configured_hooks():
        name = _hook_id(hook)
        if "manual" in (hook.get("stages") or []):
            continue
        examined += 1
        if re.search(rf"pre-commit run {re.escape(name)}\b", ci):
            continue
        # Or the hook's own `entry`, run directly. `poetry-lock` has to take this route:
        # it validates that the manifest and the lock agree without installing from the
        # lock, and running it through pre-commit would require installing the dev
        # dependencies -- from the lock this job exists to doubt. Comparing the entry
        # string keeps drift impossible either way: change the hook and this line stops
        # matching.
        entry = str(hook.get("entry", "")).strip()
        if entry and entry in ci:
            continue
        assert name in LOCAL_ONLY_HOOKS, (
            f"the {name!r} gate is configured but no verifier job runs it, so it gates "
            f"nothing that reaches the default branch. Run it in CI, or record why it "
            f"cannot be in LOCAL_ONLY_HOOKS."
        )
    assert examined, "every hook is manual-stage; this guard examined nothing"
    stale = set(LOCAL_ONLY_HOOKS) - {_hook_id(hook) for hook in _configured_hooks()}
    assert not stale, (
        f"{sorted(stale)} are recorded as local-only but are no longer configured"
    )


def test_the_python_formatter_never_rewrites_a_markdown_record() -> None:
    """A mutating gate must not edit the records this project keeps.

    Upstream's `ruff-format` hook declares `types_or: [python, pyi, jupyter, markdown]`,
    so it reformats Python code fences inside `.md`. It was doing that to this epic's
    closure reports -- reindenting and rewrapping the code a reviewer had quoted as
    evidence of what the file said at the time. A report is a record; a formatter that
    edits it makes the record describe the present rather than the moment it was
    written, and nothing in the diff explains why.

    ADRs and guides would merely be tidied, and that is a real benefit given up here.
    It is not worth the class of change it also permits.
    """
    config = yaml.safe_load(PRE_COMMIT_CONFIG.read_text(encoding="utf-8"))
    formatters = [
        hook
        for repository in config["repos"]
        for hook in repository["hooks"]
        if hook["id"] in {"ruff-format", "ruff-check"}
    ]
    assert formatters, "no Python formatter is configured; this guard examined nothing"
    for hook in formatters:
        declared = hook.get("types_or")
        assert declared is not None, (
            f"{hook.get('alias', hook['id'])} inherits upstream's file types, which "
            f"include markdown; declare `types_or` explicitly"
        )
        assert "markdown" not in declared, (
            f"{hook.get('alias', hook['id'])} would rewrite Python fences inside .md "
            f"records: {declared}"
        )


def test_the_secret_scanner_and_pre_commit_exclude_the_same_vendored_trees() -> None:
    """`gitleaks dir` takes no notice of pre-commit's `exclude:`, so the vendored trees
    are allowlisted a second time in .gitleaks.toml. Two hand-kept copies of one list
    drift, and the copy nobody updated is the one that decides what goes unscanned --
    so the two are derived from each other here rather than trusted to agree.
    """
    config = yaml.safe_load(PRE_COMMIT_CONFIG.read_text(encoding="utf-8"))
    excluded = re.fullmatch(r"\^\((?P<alternatives>.+)\)/", str(config["exclude"]))
    assert excluded, (
        f"the pre-commit exclude is no longer an alternation: {config['exclude']}"
    )
    expected = {
        f"^{alternative}/" for alternative in excluded["alternatives"].split("|")
    }

    scanner = tomllib.loads(GITLEAKS_CONFIG.read_text(encoding="utf-8"))
    allowlisted = {
        path for entry in scanner["allowlists"] for path in entry.get("paths", [])
    }
    assert allowlisted == expected, (
        f"the scanner allowlists {sorted(allowlisted)} while pre-commit excludes "
        f"{sorted(expected)}; one tree is linted by neither or scanned by neither"
    )
    assert scanner["extend"]["useDefault"] is True, (
        "the allowlist must extend the default rule set, not replace it"
    )


def test_the_secret_scanner_covers_both_the_tree_and_the_history() -> None:
    """Two domains, and fixing one of them changed which was covered.

    Sprint closure replaced `gitleaks git --staged` (which read nothing) with
    `gitleaks dir` (which reads the checked-out tree). That also moved the domain:
    `git` walks commit objects, `dir` walks the tip. A credential committed and removed
    in a later commit of the same pull request is live in the history and in
    `refs/pull/*`, and after the fix it was read by no gate at all -- while
    `.gitleaks.toml` said the gate "had been passing over every commit without reading
    any of it", which invites the reader to assume it now reads every commit.

    The hook keeps the tree, and the CI job that already fetches the full history scans
    it too. Asserted here so the two cannot drift back to one.
    """
    steps = _jobs(_load_workflow(VERIFY_WORKFLOW))["gitleaks"]["steps"]
    bodies = [_uncommented(str(step.get("run", ""))) for step in steps]
    assert any("pre-commit run gitleaks" in body for body in bodies), (
        "the gitleaks job no longer runs the configured hook over the tree"
    )
    # The `git` subcommand, however the binary is named at the call site -- the history
    # step resolves it into a variable rather than hard-coding `gitleaks`.
    history = re.compile(r"(?:gitleaks|scanner)\S*\"?\s+git\b")
    assert any(history.search(body) for body in bodies), (
        "nothing scans the repository history; a credential removed in a later commit "
        "is live in the history and read by no gate"
    )


def test_the_secret_scanner_proves_itself_in_ci() -> None:
    """The guard above reads configuration; this requires the job that reads *behaviour*.

    Asserting "a gitleaks hook is configured" is exactly the guard this repository
    already had, and it passed throughout the period the scanner read nothing.

    Two properties, because the first version of this probe had only half of one. It
    located the binary with `find | head -1`, spliced the configured entry's argv to
    point at a temp directory, and accepted any non-zero exit -- but gitleaks exits
    non-zero for a usage error too, so a change to the entry's flag order would have made
    the probe fail to parse and report success while exercising nothing. And the fixture
    sat in a temp directory, where `.gitleaks.toml`'s anchored `^_bmad/` patterns cannot
    match, so widening the allowlist to `^src/` was invisible to it.

    Now: plant inside the repository and run the hook itself, which removes the argv
    surgery entirely; and plant a second fixture inside an allowlisted tree, which makes
    this a test of the allowlist's shape rather than of the binary's existence.
    """
    steps = _jobs(_load_workflow(VERIFY_WORKFLOW))["gitleaks"]["steps"]
    proof = [
        _uncommented(str(step.get("run", "")))
        for step in steps
        if "planted" in str(step.get("run", ""))
    ]
    assert proof, (
        "the gitleaks job no longer proves the scanner reads content. A configuration "
        "check cannot replace it: the defect it exists for was a correctly configured "
        "hook scanning an empty index."
    )
    body = proof[0]
    assert body.count("pre-commit run gitleaks") >= 2, (
        "the proof must exercise the configured hook in both directions -- a planted "
        "credential must fail it, and an allowlisted tree must not"
    )
    allowlisted = {
        entry.split("/")[0].lstrip("^").replace("\\", "")
        for pattern in tomllib.loads(GITLEAKS_CONFIG.read_text(encoding="utf-8"))[
            "allowlists"
        ]
        for entry in pattern.get("paths", [])
    }
    assert any(tree in body for tree in allowlisted), (
        f"the proof plants nothing inside an allowlisted tree ({sorted(allowlisted)}), "
        f"so widening the allowlist would not be caught by it"
    )
