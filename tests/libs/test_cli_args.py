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
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

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


# ---------------------------------------------------------------------------
# Every `settings.*` dest must name a key the settings loader reads (M1, E014-S01-004).
# `--restart-container` wrote `settings.restartcontainer` while the loader reads
# `settings.restartcontainers`, so the flag parsed fine and changed nothing.
# ---------------------------------------------------------------------------

_CONFIG_DEFAULT = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "traefik_certificate_exporter"
    / "config_default.yaml"
)


def test_restart_container_flag_enables_restart_containers(tmp_path, monkeypatch):
    from traefik_certificate_exporter.libs.settings import SettingsManager

    for name in list(os.environ):
        if name.startswith("TRAEFIK_CERTIFICATE_EXPORTER_"):
            monkeypatch.delenv(name)
    monkeypatch.chdir(tmp_path)

    args = globalArgParser.parse_args(
        ["--restart-container", "--data-path", str(tmp_path)]
    )
    manager = SettingsManager()
    manager.loadFromFile(fileName=str(tmp_path / "absent.yaml"), cmdLineArgs=args)

    assert manager.settings.restartContainers is True


def test_every_settings_dest_is_a_key_in_config_default():
    """Scope is the parser's own action list, so a new flag is covered with no edit here."""
    registry = yaml.safe_load(_CONFIG_DEFAULT.read_text(encoding="utf-8"))
    dests = [
        action.dest
        for action in globalArgParser._actions
        if action.dest.startswith("settings.")
    ]
    assert dests, "no settings.* dest found; this guard examined nothing"

    missing = []
    for dest in dests:
        node = registry
        for segment in dest.split("."):
            if not isinstance(node, dict) or segment not in node:
                missing.append(dest)
                break
            node = node[segment]
        else:
            if isinstance(node, dict):
                # A section such as `settings.domains` is not a setting (only leaves and
                # lists are), matching the env-name check in tests/test_settings_surface.py.
                missing.append(dest)

    assert not missing, (
        f"CLI dest(s) name keys absent from config_default.yaml, so nothing reads "
        f"them: {missing}"
    )


# ---------------------------------------------------------------------------
# Strict-parse error text and readable metavars (BL-E011-034, BL-E011-035,
# BL-E014-002, E014-S01-008).
# ---------------------------------------------------------------------------


def _strict_parse_error(monkeypatch, capsys, *argv: str) -> str:
    monkeypatch.setattr(sys, "argv", ["traefik-certificate-exporter", *argv])
    with pytest.raises(SystemExit) as excinfo:
        parse_args_strict()
    assert excinfo.value.code == 2
    return capsys.readouterr().err


def test_flag_typo_suggests_nearest_and_points_to_help(monkeypatch, capsys):
    err = _strict_parse_error(monkeypatch, capsys, "--dtaa-path", "/x")

    assert "unrecognized arguments: --dtaa-path /x" in err
    assert "Did you mean '--data-path'?" in err
    assert "Try '--help' for full usage." in err


def test_dissimilar_flag_typo_gets_help_pointer_only(monkeypatch, capsys):
    err = _strict_parse_error(monkeypatch, capsys, "--zzzzzz")

    assert "unrecognized arguments: --zzzzzz" in err
    assert "Did you mean" not in err
    assert "Try '--help' for full usage." in err


def test_stray_positional_argument_still_exits_two(monkeypatch, capsys):
    """BL-E014-002: a non-dash leftover is still an error under the strict parse, not
    silently dropped because no `-`-token triggered the suggestion path."""
    err = _strict_parse_error(monkeypatch, capsys, "-d", "/acme", "stray")

    assert "unrecognized arguments: stray" in err
    assert "Did you mean" not in err


def test_flag_and_env_suggestions_share_nearest_name(monkeypatch, capsys):
    """C-04: one helper computes both suggestions, so patching it once changes both."""
    from traefik_certificate_exporter.libs import legacy_settings, suggest

    sentinel = "SENTINEL_FROM_NEAREST_NAME"
    monkeypatch.setattr(suggest, "nearest_name", lambda candidate, options: sentinel)

    err = _strict_parse_error(monkeypatch, capsys, "--dtaa-path", "/x")
    assert f"Did you mean '{sentinel}'?" in err

    findings = legacy_settings.find_legacy_settings(
        {"TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_DTAAPATH": "/x"}, None
    )
    assert [f.suggestion for f in findings if f.kind == "unknown"] == [
        legacy_settings.ENV_PREFIX + sentinel
    ]


def _value_taking_options() -> list[argparse.Action]:
    return [
        action
        for action in globalArgParser._actions
        if action.option_strings
        and action.nargs != 0
        and not isinstance(action, argparse._HelpAction)
    ]


def test_every_value_taking_action_has_dotless_metavar():
    actions = _value_taking_options()

    # Non-vacuity: the parser has value-taking flags, and they were all examined.
    assert any("--data-path" in action.option_strings for action in actions)
    for action in actions:
        assert action.metavar, action.option_strings
        assert "." not in action.metavar, action.option_strings


def test_help_contains_no_settings_paths():
    assert "SETTINGS." not in globalArgParser.format_help()
    assert "SETTINGS." not in globalArgParser.format_usage()


def test_no_validate_keys_flag_sets_false():
    flagged = globalArgParser.parse_args(["--no-validate-keys"])
    absent = globalArgParser.parse_args([])

    assert getattr(flagged, "settings.validatekeys") is False
    assert getattr(absent, "settings.validatekeys") is None
