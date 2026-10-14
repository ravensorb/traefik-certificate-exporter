import json
import logging
import re
import shlex
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from traefik_certificate_exporter.libs import post_export
from traefik_certificate_exporter.libs.post_export import run_post_export_command


def test_no_command_configured_is_a_noop():
    with patch("subprocess.run") as mock_run:
        run_post_export_command(None, ["example.com"], dryRun=False)

    mock_run.assert_not_called()


def test_dry_run_skips_execution_even_with_a_command_configured():
    with patch("subprocess.run") as mock_run:
        run_post_export_command("/bin/true", ["example.com"], dryRun=True)

    mock_run.assert_not_called()


def test_successful_command_receives_comma_separated_domains_env_var(tmp_path):
    output_file = tmp_path / "hook-output.json"
    script = tmp_path / "hook.py"
    script.write_text(
        "import json, os, sys\n"
        f"with open({str(output_file)!r}, 'w') as f:\n"
        "    json.dump({'env': os.environ.get("
        "'TRAEFIK_CERTIFICATE_EXPORTER_EXPORTED_DOMAINS')}, f)\n"
    )

    run_post_export_command(
        f"{sys.executable} {script}", ["foo.com", "bar.com"], dryRun=False
    )

    result = json.loads(output_file.read_text())
    assert result["env"] == "foo.com,bar.com"


def test_no_domains_processed_yields_empty_env_var(tmp_path):
    output_file = tmp_path / "hook-output.json"
    script = tmp_path / "hook.py"
    script.write_text(
        "import json, os\n"
        f"with open({str(output_file)!r}, 'w') as f:\n"
        "    json.dump({'env': os.environ.get("
        "'TRAEFIK_CERTIFICATE_EXPORTER_EXPORTED_DOMAINS')}, f)\n"
    )

    run_post_export_command(f"{sys.executable} {script}", [], dryRun=False)

    result = json.loads(output_file.read_text())
    assert result["env"] == ""


def test_non_zero_exit_is_logged_but_does_not_raise(caplog):
    run_post_export_command(
        f'{sys.executable} -c "import sys; sys.exit(3)"', ["example.com"], dryRun=False
    )

    assert any("exited 3" in message for message in caplog.messages)


def test_timeout_is_logged_but_does_not_raise(monkeypatch, caplog):
    monkeypatch.setattr(post_export, "POST_EXPORT_COMMAND_TIMEOUT_SECONDS", 0.2)

    run_post_export_command(
        f'{sys.executable} -c "import time; time.sleep(5)"',
        ["example.com"],
        dryRun=False,
    )

    assert any("timed out" in message for message in caplog.messages)


def test_unparseable_command_is_logged_but_does_not_raise(caplog):
    run_post_export_command('unterminated "quote', ["example.com"], dryRun=False)

    assert any("could not be parsed" in message for message in caplog.messages)


def test_the_hook_receives_the_correlation_id_of_the_pass_that_ran_it(tmp_path):
    """A hook that logs somewhere else can still be joined back to this export pass."""
    output_file = tmp_path / "hook-correlation.json"
    script = tmp_path / "hook.py"
    script.write_text(
        "import json, os\n"
        f"with open({str(output_file)!r}, 'w') as f:\n"
        "    json.dump({'id': os.environ.get("
        "'TRAEFIK_CERTIFICATE_EXPORTER_CORRELATION_ID')}, f)\n"
    )

    run_post_export_command(
        f"{sys.executable} {script}",
        ["foo.com"],
        dryRun=False,
        correlationId="pass-1234",
    )

    assert json.loads(output_file.read_text())["id"] == "pass-1234"


def test_post_export_log_lines_carry_the_passed_correlation_id(caplog):
    with caplog.at_level(logging.INFO):
        run_post_export_command(
            "/bin/true", ["foo.com"], dryRun=True, correlationId="pass-5678"
        )

    assert [r.correlation_id for r in caplog.records] == ["pass-5678"]


# ---------------------------------------------------------------------------
# E014-S01-010 (review-product m4): `postexportcommand` often carries a credential, so a
# hook log line names only the program, `argv[0]` -- never the arguments or the command.
# ---------------------------------------------------------------------------

_CREDENTIAL_COMMAND = 'curl -H "Authorization: Bearer s3cr3t" https://x.example.test'


def _assert_credential_not_logged(caplog):
    assert caplog.records, "the hook logged nothing at all"
    for record in caplog.records:
        message = record.getMessage()
        assert "s3cr3t" not in message, message
        assert "Authorization" not in message, message


def test_nonzero_exit_log_names_only_the_program(caplog):
    failed = subprocess.CompletedProcess(["curl"], 7, stdout="", stderr="refused")
    with (
        caplog.at_level(logging.DEBUG),
        patch.object(post_export.subprocess, "run", return_value=failed),
    ):
        run_post_export_command(_CREDENTIAL_COMMAND, ["example.com"], dryRun=False)

    _assert_credential_not_logged(caplog)
    assert any(
        "Post-export command curl exited 7: refused" in m for m in caplog.messages
    ), caplog.messages


def test_timeout_log_names_only_the_program(caplog):
    timeout = subprocess.TimeoutExpired(cmd=["curl"], timeout=30)
    with (
        caplog.at_level(logging.DEBUG),
        patch.object(post_export.subprocess, "run", side_effect=timeout),
    ):
        run_post_export_command(_CREDENTIAL_COMMAND, ["example.com"], dryRun=False)

    _assert_credential_not_logged(caplog)
    assert any(
        m.startswith("Post-export command curl timed out") for m in caplog.messages
    ), caplog.messages


def test_start_failure_log_names_only_the_program(caplog):
    missing = FileNotFoundError(2, "No such file or directory", "curl")
    with (
        caplog.at_level(logging.DEBUG),
        patch.object(post_export.subprocess, "run", side_effect=missing),
    ):
        run_post_export_command(_CREDENTIAL_COMMAND, ["example.com"], dryRun=False)

    _assert_credential_not_logged(caplog)
    assert any(
        m.startswith("Post-export command curl failed to start")
        for m in caplog.messages
    ), caplog.messages


def test_unparsable_command_log_names_neither_command_nor_parser_message(caplog):
    """`shlex`'s message can echo a fragment of the command, so it is not logged either."""
    unterminated = 'curl -H "Authorization: Bearer s3cr3t https://x.example.test'
    with pytest.raises(ValueError) as parserError:
        shlex.split(unterminated)

    with caplog.at_level(logging.DEBUG):
        run_post_export_command(unterminated, ["example.com"], dryRun=False)

    _assert_credential_not_logged(caplog)
    for message in caplog.messages:
        assert "curl" not in message, message
        assert str(parserError.value) not in message, message
    assert any("could not be parsed" in m for m in caplog.messages), caplog.messages


def test_post_export_without_an_id_logs_rather_than_failing(caplog):
    """A missing correlation id must never take down the pass it exists to observe."""
    with caplog.at_level(logging.INFO):
        run_post_export_command("/bin/true", ["foo.com"], dryRun=True)

    assert caplog.records
    assert all(getattr(r, "correlation_id", None) for r in caplog.records)


# ---------------------------------------------------------------------------
# ADV-3: a failing hook's stderr is untrusted and may echo the hook's own (secret)
# arguments. Only its last line is logged: arguments masked, control characters
# stripped, truncated.
# ---------------------------------------------------------------------------


def test_failing_hook_stderr_is_masked_sanitized_and_reduced_to_its_last_line(caplog):
    script = (
        "import sys; "
        "sys.stderr.write('earlier line ' + sys.argv[1] + '\\n'); "
        "sys.stderr.write('curl: (6) Could not resolve ' + sys.argv[1] + "
        "' \\x1b[31mFORGED\\r\\n'); "
        "sys.exit(6)"
    )
    command = shlex.join([sys.executable, "-c", script, "https://h.test/?token=s3cr3t"])

    with caplog.at_level(logging.DEBUG):
        run_post_export_command(command, ["example.com"], dryRun=False)

    errors = [r.getMessage() for r in caplog.records if r.levelno == logging.ERROR]
    assert len(errors) == 1, caplog.messages
    message = errors[0]
    assert "s3cr3t" not in message
    assert "earlier line" not in message
    assert "\x1b" not in message and "\r" not in message and "\n" not in message
    assert "Could not resolve ***" in message
    assert "exited 6" in message


def test_failing_hook_stderr_last_line_is_truncated(caplog):
    failed = subprocess.CompletedProcess(["hook"], 1, stdout="", stderr="x" * 5000)
    with (
        caplog.at_level(logging.DEBUG),
        patch.object(post_export.subprocess, "run", return_value=failed),
    ):
        run_post_export_command("hook --flag", ["example.com"], dryRun=False)

    (message,) = [r.getMessage() for r in caplog.records if r.levelno == logging.ERROR]
    assert len(message) < 400
    assert "x" * post_export.HOOK_STDERR_LOG_LIMIT in message
    assert "x" * (post_export.HOOK_STDERR_LOG_LIMIT + 1) not in message


# ---------------------------------------------------------------------------
# The hook is the only process the package spawns (E015-S01-001 AC 5, ADR-0050). ruff's
# TID251 banned-api table is the guard; these tests check the table's hand-kept names
# against their source of truth (`dir(os)`, `dir(posix)` / `dir(nt)`, `dir(asyncio)`), the
# one allowed `noqa`, and the ruff configuration that could switch the rule off.
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[2]
# Banned whole: each spawns, or reaches the spawn primitives without going through `os`
# (ADR-0050, amendment 2026-10-12).
_SPAWN_MODULES = (
    "subprocess",
    "pty",
    "multiprocessing",
    "posix",
    "nt",
    "_posixsubprocess",
    "asyncio.subprocess",
    "concurrent.futures.process",
    "ctypes",
    "webbrowser",
)
# Sprint closure 2026-10-12 (AR-2, AR-3): stdlib code that spawns inside a function the
# package could call, verified by source or by an audit hook; and the re-export of the one
# admitted `subprocess` import. Required in the table, so deleting one fails the test below.
_INDIRECT_SPAWN_NAMES = (
    "_aix_support",
    "_bootsubprocess",
    "_osx_support",
    "_pyrepl.pager",
    "asyncio.base_subprocess",
    "asyncio.windows_utils",
    "distutils",
    "ensurepip",
    "mailcap",
    "pipes",
    "platform",
    "pydoc",
    "venv",
    "http.server.CGIHTTPRequestHandler",
    "imaplib.IMAP4_stream",
    "socketserver.ForkingMixIn",
    "socketserver.ForkingTCPServer",
    "socketserver.ForkingUDPServer",
    "socketserver.ForkingUnixStreamServer",
    "socketserver.ForkingUnixDatagramServer",
    "uuid.getnode",
    "uuid.uuid1",
    "uuid.uuid6",
    "traefik_certificate_exporter.libs.post_export.subprocess",
)


def _pyproject(pyproject: Path = PROJECT_ROOT / "pyproject.toml") -> dict:
    try:
        import tomllib
    except ModuleNotFoundError:  # Python 3.10
        import tomli as tomllib  # type: ignore[no-redef]

    return tomllib.loads(pyproject.read_text(encoding="utf-8"))


def _banned_api(pyproject: Path = PROJECT_ROOT / "pyproject.toml") -> dict:
    lint = _pyproject(pyproject).get("tool", {}).get("ruff", {}).get("lint", {})
    return lint.get("flake8-tidy-imports", {}).get("banned-api", {})


def _is_spawn_name(name: str) -> bool:
    return name.startswith(("exec", "spawn", "posix_spawn", "fork")) or name in (
        "system",
        "popen",
    )


def _spawn_capable_names() -> set[str]:
    """`os` re-exports its spawn primitives from `posix` (`nt` on Windows), so both are
    the source of truth for the `os.<name>` entries; the modules themselves are banned
    whole through `_SPAWN_MODULES`."""
    import asyncio
    import importlib
    import os

    primitives = [os]
    for platformModule in ("posix", "nt"):
        try:
            primitives.append(importlib.import_module(platformModule))
        except ImportError:
            continue
    names = {
        f"os.{name}"
        for module in primitives
        for name in dir(module)
        if _is_spawn_name(name)
    }
    names |= {
        f"asyncio.{name}"
        for name in dir(asyncio)
        if name.startswith("create_subprocess_")
    }
    return names | set(_SPAWN_MODULES) | set(_INDIRECT_SPAWN_NAMES)


def _unbanned_spawn_names(banned: dict) -> list[str]:
    return sorted(_spawn_capable_names() - set(banned))


def test_every_spawn_capable_name_is_banned_for_ruff():
    banned = _banned_api()

    assert "os.posix_spawn" in _spawn_capable_names()
    assert _unbanned_spawn_names(banned) == []
    for name, entry in banned.items():
        assert "ADR-0050" in entry.get("msg", ""), name


def test_the_banned_name_check_reports_a_planted_gap():
    banned = dict(_banned_api())
    banned.pop("os.posix_spawn", None)
    banned.pop("os.posix_spawnp", None)
    banned.pop("posix", None)
    banned.pop("concurrent.futures.process", None)

    assert _unbanned_spawn_names(banned) == [
        "concurrent.futures.process",
        "os.posix_spawn",
        "os.posix_spawnp",
        "posix",
    ]


def test_the_spawn_names_include_those_only_posix_or_nt_exports(monkeypatch):
    """The scope, not only the rule: a primitive the platform module exports and `os` does
    not re-export is still required as `os.<name>`."""
    import importlib
    import types

    fake = types.ModuleType("posix")
    fake.spawn_planted = lambda: None  # type: ignore[attr-defined]
    realImport = importlib.import_module

    def importing(name, *args, **kwargs):
        return fake if name == "posix" else realImport(name, *args, **kwargs)

    monkeypatch.setattr(importlib, "import_module", importing)

    assert "os.spawn_planted" in _unbanned_spawn_names(_banned_api())


# F10 (review E015-S01-001): which comments suppress a TID251 report is ruff's to say, not a
# regex's -- the pinned ruff also honours a range `ruff: disable[...]`. So ask ruff: lint with
# only TID251 selected and every suppression comment ignored (`--ignore-noqa` disregards
# line `noqa`, file-level `ruff: noqa` / `flake8: noqa` and range `ruff: disable` alike),
# under the project's pyproject. The gate's own run has no TID251 report, so every report
# here is one a comment suppresses. Configuration (`per-file-ignores`, `ignore`) is not
# a comment and stays the job of `_tid251_config_gaps` below.
def _ruff() -> str:
    """The ruff the dev group installs into this venv (pinned to the pre-commit hook's)."""
    import shutil

    ruff = shutil.which("ruff", path=str(Path(sys.executable).parent))
    assert ruff is not None, "ruff is not installed in the venv; run `poetry sync`"
    return ruff


def _tid251_reports_ignoring_suppressions(root: Path) -> list[str]:
    result = subprocess.run(
        [
            _ruff(),
            "check",
            "--config",
            str(PROJECT_ROOT / "pyproject.toml"),
            "--select",
            "TID251",
            "--ignore-noqa",
            "--no-cache",
            "--exit-zero",
            "--output-format",
            "json",
            str(root),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    reports = []
    for diagnostic in json.loads(result.stdout):
        path = Path(diagnostic["filename"]).resolve().relative_to(root.resolve())
        line = diagnostic["location"]["row"]
        reports.append(f"{path.as_posix()}:{line}:{diagnostic['code']}")
    return sorted(reports)


def test_the_ruff_used_here_is_the_pre_commit_hooks_ruff():
    """The scope: the answer above is only the gate's answer if it is the gate's ruff."""
    config = (PROJECT_ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    frozen = re.search(
        r"astral-sh/ruff-pre-commit\s*\n(?:\s*#.*\n)*\s*rev:\s*\S+\s*#\s*frozen:\s*v(\S+)",
        config,
    )
    assert frozen is not None
    version = subprocess.run(
        [_ruff(), "--version"], capture_output=True, text=True, check=True
    ).stdout.split()[-1]
    assert version == frozen.group(1)


def test_tid251_is_suppressed_only_at_the_post_export_import(tmp_path):
    import shutil

    package = Path(post_export.__file__).resolve().parents[1]
    importLine = next(
        number
        for number, line in enumerate(
            Path(post_export.__file__).read_text("utf-8").splitlines(), start=1
        )
        if line.startswith("import subprocess")
    )
    expected = [f"libs/post_export.py:{importLine}:TID251"]

    assert _tid251_reports_ignoring_suppressions(package) == expected

    # The scope, not only the rule: a spawn suppressed anywhere else in a copy of the
    # package tree is reported, by each suppression mechanism ruff has.
    # Named as the package, so ruff resolves a relative import to the banned re-export.
    copy = tmp_path / "traefik_certificate_exporter"
    shutil.copytree(package, copy, ignore=shutil.ignore_patterns("__pycache__"))
    (copy / "libs" / "planted.py").write_text(
        "import os\n\nos.system('id')  # noqa: TID251\n", encoding="utf-8"
    )
    (copy / "libs" / "planted_file_level.py").write_text(
        "# ruff: noqa: TID251\nimport os\n\nos.system('id')\n", encoding="utf-8"
    )
    (copy / "libs" / "planted_range.py").write_text(
        "import os\n\n# ruff: disable[TID251]\nos.system('id')\n", encoding="utf-8"
    )
    # AR-2 (closure 2026-10-12): the admitted import, reached through a re-export.
    (copy / "libs" / "planted_reexport.py").write_text(
        "from .post_export import subprocess as sp\n"
        "from . import post_export\n"
        "from traefik_certificate_exporter.libs import post_export as pe\n"
        "post_export.subprocess.Popen(['id'])\n"
        "pe.subprocess.run(['id'])\n",
        encoding="utf-8",
    )
    assert _tid251_reports_ignoring_suppressions(copy) == sorted(
        [
            "libs/planted.py:3:TID251",
            "libs/planted_file_level.py:4:TID251",
            "libs/planted_range.py:4:TID251",
            "libs/planted_reexport.py:1:TID251",
            "libs/planted_reexport.py:4:TID251",
            "libs/planted_reexport.py:5:TID251",
            *expected,
        ]
    )


_TID251_PREFIXES = {"TID", "TID2", "TID25", "TID251"}


def _tid251_config_gaps(data: dict) -> list[str]:
    """Every place in a parsed pyproject where ruff could switch TID251 off for a path
    other than `tests/**`: `per-file-ignores` and `ignore` / `extend-ignore`, at the top
    level of `[tool.ruff]` and under `[tool.ruff.lint]`."""
    ruff = data.get("tool", {}).get("ruff", {})
    gaps = []
    for tableName, table in (
        ("tool.ruff", ruff),
        ("tool.ruff.lint", ruff.get("lint", {})),
    ):
        for key in ("ignore", "extend-ignore"):
            for code in table.get(key, []):
                if code.upper() in _TID251_PREFIXES:
                    gaps.append(f"{tableName}.{key}: {code}")
        for key in ("per-file-ignores", "extend-per-file-ignores"):
            for pattern, codes in table.get(key, {}).items():
                if pattern == "tests/**":
                    continue
                for code in codes:
                    if code.upper() in _TID251_PREFIXES:
                        gaps.append(f"{tableName}.{key}[{pattern}]: {code}")
    return sorted(gaps)


def test_tid251_is_switched_off_by_configuration_only_for_tests():
    data = _pyproject()
    lint = data["tool"]["ruff"]["lint"]

    assert lint["per-file-ignores"]["tests/**"] == ["TID251"]
    assert "TID251" in lint["extend-select"]
    assert _tid251_config_gaps(data) == []


def test_the_configuration_check_reports_a_planted_ignore():
    import copy

    data = copy.deepcopy(_pyproject())
    ruff = data["tool"]["ruff"]
    ruff["lint"]["per-file-ignores"]["src/**"] = ["E501", "TID251"]
    ruff["lint"].setdefault("extend-ignore", []).append("TID25")
    ruff.setdefault("ignore", []).append("tid")

    assert _tid251_config_gaps(data) == [
        "tool.ruff.ignore: tid",
        "tool.ruff.lint.extend-ignore: TID25",
        "tool.ruff.lint.per-file-ignores[src/**]: TID251",
    ]


# ---------------------------------------------------------------------------
# AR-3 (sprint closure 2026-10-12): the stdlib modules that can spawn are derived from the
# runner's stdlib sources, not listed by hand. A module is accounted for when it (or a
# parent) is banned whole, when the table bans at least one of its names, or when it is in
# the reviewed list below with the reason it is not banned. This proves the MODULE is
# accounted for; which of its functions are banned by name is review.
# ---------------------------------------------------------------------------
_REVIEWED_STDLIB_SPAWNERS = {
    "os": "spawn primitives derived from dir(os)/dir(posix) above",
    "asyncio": "create_subprocess_* derived from dir(asyncio) above",
    "asyncio.base_events": "event-loop methods: runtime-object gap (pyproject)",
    "asyncio.events": "event-loop methods: runtime-object gap (pyproject)",
    "asyncio.unix_events": "event-loop methods: runtime-object gap (pyproject)",
}
_STDLIB_SKIP_PARTS = {
    "test",
    "tests",
    "idlelib",
    "lib2to3",
    "turtledemo",
    "site-packages",
}


def _stdlib_spawning_modules() -> set[str]:
    """Dotted names of stdlib modules that import `subprocess` / `_posixsubprocess` or
    use an `os.<spawn primitive>` attribute, scanned from the runner's stdlib sources."""
    import ast
    import sysconfig

    stdlib = Path(sysconfig.get_paths()["stdlib"])
    modules = set()
    for path in stdlib.rglob("*.py"):
        relative = path.relative_to(stdlib)
        if _STDLIB_SKIP_PARTS & set(relative.parts) or relative.name.startswith(
            "test_"
        ):
            continue
        try:
            tree = ast.parse(path.read_bytes())
        except (SyntaxError, ValueError):
            continue
        for node in ast.walk(tree):
            if (
                (
                    isinstance(node, ast.Import)
                    and any(
                        a.name in ("subprocess", "_posixsubprocess") for a in node.names
                    )
                )
                or (
                    isinstance(node, ast.ImportFrom)
                    and node.module in ("subprocess", "_posixsubprocess")
                )
                or (
                    isinstance(node, ast.Attribute)
                    and isinstance(node.value, ast.Name)
                    and node.value.id == "os"
                    and _is_spawn_name(node.attr)
                )
            ):
                name = ".".join(relative.with_suffix("").parts)
                modules.add(name.removesuffix(".__init__"))
                break
    return modules


def _unaccounted_stdlib_spawners(modules: set[str], banned: dict) -> list[str]:
    def accounted(module: str) -> bool:
        parts = module.split(".")
        if any(".".join(parts[:i]) in banned for i in range(1, len(parts) + 1)):
            return True
        if any(name.startswith(module + ".") for name in banned):
            return True
        return module in _REVIEWED_STDLIB_SPAWNERS

    return sorted(m for m in modules if not accounted(m))


def test_every_stdlib_module_that_spawns_is_banned_or_reviewed():
    modules = _stdlib_spawning_modules()

    assert {"subprocess", "imaplib", "platform"} <= modules  # the scan found something
    assert _unaccounted_stdlib_spawners(modules, _banned_api()) == []


def test_the_stdlib_spawner_check_reports_a_planted_gap():
    banned = dict(_banned_api())
    banned.pop("imaplib.IMAP4_stream", None)
    modules = _stdlib_spawning_modules() | {"planted_spawner"}

    assert _unaccounted_stdlib_spawners(modules, banned) == [
        "imaplib",
        "planted_spawner",
    ]
