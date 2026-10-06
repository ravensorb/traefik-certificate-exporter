"""Guards for the two-path CLI parse (ADR-0025, BL-E001-006).

The import-time parse must stay lenient -- it runs whenever anything imports the package,
including under pytest, where argv belongs to pytest and not to us. The production parse
must be strict -- there argv is this process's own, so an unrecognized flag is a typo.
Both halves are asserted here, because fixing either one alone reintroduces the other's
bug.

argparse objects are first-class and parse an explicit list, so none of this needs a
subprocess or any argv monkeypatching.
"""

import argparse
import subprocess
import sys

import pytest

from traefik_certificate_exporter.libs.cli_args import (
    globalArgParser,
    globalArgs,
    parse_args_strict,
)


def test_import_time_parse_is_lenient_about_foreign_argv():
    """The guarantee the import-time assignment exists for.

    This test module was itself imported by pytest, whose argv (`-x`, `-v`, a node id)
    `cli_args` has already parsed at import time. Reaching this assertion at all means no
    SystemExit was raised during that import -- which is the regression BL-E001-006's fix
    must not reintroduce.
    """
    assert isinstance(globalArgs, argparse.Namespace)
    assert globalArgs.configfile == "config.yaml"


def test_lenient_parse_silently_ignores_a_typo():
    """`--dtaa-path` is a typo for `--data-path`, and the lenient path keeps going."""
    parsed, unknown = globalArgParser.parse_known_args(["--dtaa-path", "/x"])

    assert unknown == ["--dtaa-path", "/x"]
    assert getattr(parsed, "settings.datapath") is None


def test_strict_parse_rejects_a_typo(capsys):
    """The behavior BL-E001-006 asks for: a typo is an error, not a silent no-op."""
    with pytest.raises(SystemExit) as excinfo:
        globalArgParser.parse_args(["--dtaa-path", "/x"])

    assert excinfo.value.code == 2
    assert "--dtaa-path" in capsys.readouterr().err


def test_strict_parse_accepts_a_valid_invocation():
    """Strictness must not cost a correct command line its parse."""
    parsed = globalArgParser.parse_args(
        ["--data-path", "/acme", "--log-level", "DEBUG"]
    )

    assert getattr(parsed, "settings.datapath") == "/acme"
    assert parsed.logginglevel == "DEBUG"


def test_strict_parse_still_prints_help_and_exits_zero(capsys):
    """`-h` is handled by argparse's own action, before unrecognized-arg handling."""
    with pytest.raises(SystemExit) as excinfo:
        globalArgParser.parse_args(["-h"])

    assert excinfo.value.code == 0
    assert "usage:" in capsys.readouterr().out


def test_parse_args_strict_reads_process_argv(monkeypatch):
    """`parse_args_strict()` is `parse_args()` over `sys.argv` -- nothing in between.

    Asserted through `sys.argv` rather than by passing a list, because the production
    call in `main()` takes no argument and the thing worth guarding is that it reads the
    real invocation.
    """
    monkeypatch.setattr(sys, "argv", ["traefik-certificate-exporter", "-d", "/acme"])

    parsed = parse_args_strict()

    assert getattr(parsed, "settings.datapath") == "/acme"


def test_parse_args_strict_exits_on_an_unrecognized_flag(monkeypatch):
    monkeypatch.setattr(
        sys, "argv", ["traefik-certificate-exporter", "--dtaa-path", "/x"]
    )

    with pytest.raises(SystemExit) as excinfo:
        parse_args_strict()

    assert excinfo.value.code == 2


def test_importing_app_under_foreign_argv_does_not_exit(monkeypatch):
    """Importing never parses strictly -- only `main()` does.

    `app.py` holds the only production call to `parse_args_strict()`, so a future edit
    that hoists it to module scope would turn every import of the package into a
    SystemExit under any host that owns argv. Re-importing with hostile argv present is
    what catches that.
    """
    monkeypatch.setattr(sys, "argv", ["pytest", "--dtaa-path", "/x", "-k", "something"])
    monkeypatch.delitem(sys.modules, "traefik_certificate_exporter.app", raising=False)
    monkeypatch.delitem(
        sys.modules, "traefik_certificate_exporter.libs.cli_args", raising=False
    )

    import importlib

    module = importlib.import_module("traefik_certificate_exporter.app")

    assert callable(module.main)


def test_main_hard_fails_on_a_typo_end_to_end():
    """The whole point, exercised through the real entry point in a real process.

    Every other assertion here works on parser objects; this one proves the wiring --
    that `main()` actually calls the strict parse, and does it before reading any
    attribute of `globalArgs` or touching the filesystem.
    """
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from traefik_certificate_exporter.app import main; main()",
            "--dtaa-path",
            "/x",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    assert "--dtaa-path" in result.stderr
