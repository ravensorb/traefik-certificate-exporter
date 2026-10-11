import logging
import os
from argparse import Namespace

import pytest

from traefik_certificate_exporter.libs.settings import SettingsManager

PREFIX = "TRAEFIK_CERTIFICATE_EXPORTER_"


def _clear_tce_env(monkeypatch):
    for name in list(os.environ):
        if name.startswith(PREFIX):
            monkeypatch.delenv(name)


def _warnings(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]


def test_settings_load_warns_about_legacy_env_name_and_config_key(
    caplog, tmp_path, monkeypatch
):
    """An operator who copied a 0.2.x sample is told, at load, which name to use instead."""
    _clear_tce_env(monkeypatch)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv(PREFIX + "RESTART_CONTAINERS", "true")
    config_file = tmp_path / "config.yaml"
    config_file.write_text("settings:\n  restartcontainer: true\n", "utf-8")
    config_file.chmod(0o600)

    with caplog.at_level(logging.INFO):
        SettingsManager().loadFromFile(
            fileName=str(config_file),
            cmdLineArgs=Namespace(**{"settings.datapath": str(tmp_path)}),
        )
    warnings = _warnings(caplog)

    assert (
        f"Legacy setting {PREFIX}RESTART_CONTAINERS in environment is ignored; "
        f"use {PREFIX}SETTINGS_RESTARTCONTAINERS"
    ) in warnings, warnings
    assert (
        f"Legacy key settings.restartcontainer in config file {config_file} is "
        "ignored; use settings.restartcontainers"
    ) in warnings, warnings


# ---------------------------------------------------------------------------
# Detection and message shape, against the pure functions.
# ---------------------------------------------------------------------------

LOGGER = logging.getLogger("tests.legacy_settings")


def _concrete(entry) -> str:
    """A variable name the entry matches: a prefix entry gets an index appended."""
    return entry.name[:-1] + "0" if entry.name.endswith("*") else entry.name


def _run(caplog, environ, config_tree=None, config_path=None) -> list[str]:
    from traefik_certificate_exporter.libs.legacy_settings import (
        find_legacy_settings,
        warn_legacy_settings,
    )

    with caplog.at_level(logging.DEBUG, logger=LOGGER.name):
        warn_legacy_settings(
            find_legacy_settings(environ, config_tree, config_path), LOGGER
        )
    return [r.getMessage() for r in caplog.records if r.name == LOGGER.name]


def _env_rows():
    from traefik_certificate_exporter.libs.legacy_settings import LEGACY_SETTING_NAMES

    return [e for e in LEGACY_SETTING_NAMES if e.source == "env"]


@pytest.mark.parametrize("entry", _env_rows(), ids=lambda e: e.name)
def test_each_legacy_env_name_warns_once_with_replacement(caplog, entry):
    name = _concrete(entry)

    messages = _run(caplog, {name: "x"})

    assert len(messages) == 1, messages
    fix = f"use {entry.replacement}" if entry.replacement else entry.hint
    assert fix
    assert messages[0] == f"Legacy setting {name} in environment is ignored; {fix}"


def test_legacy_config_key_warns_once_with_replacement(caplog):
    messages = _run(
        caplog,
        {},
        {"settings": {"restartcontainer": True, "datapath": "/data"}},
        "/config/config.yaml",
    )

    assert messages == [
        (
            "Legacy key settings.restartcontainer in config file /config/config.yaml "
            "is ignored; use settings.restartcontainers"
        )
    ]


def test_unknown_env_name_suggests_nearest(caplog):
    messages = _run(caplog, {PREFIX + "SETTINGS_OUTPUTPAHT": "/certs"})

    assert messages == [
        (
            f"Unknown setting {PREFIX}SETTINGS_OUTPUTPAHT in environment; "
            f"did you mean {PREFIX}SETTINGS_OUTPUTPATH?"
        )
    ]


def test_unknown_env_name_without_close_match_points_to_usage(caplog):
    messages = _run(caplog, {PREFIX + "FOO": "1"})

    assert len(messages) == 1, messages
    assert messages[0].startswith(
        f"Unknown setting {PREFIX}FOO in environment matches no setting;"
    )
    assert "did you mean" not in messages[0]
    assert '"## Usage" section of README.md' in messages[0]


def test_legacy_and_unknown_values_are_never_logged(caplog, tmp_path):
    from traefik_certificate_exporter.libs.legacy_settings import check_setting_names

    secret = "tgram://123456:PLANTED-SECRET-TOKEN/987"
    config_file = tmp_path / "config.yaml"
    config_file.write_text(f"settings:\n  restartcontainer: '{secret}'\n", "utf-8")
    environ = {
        PREFIX + "NOTIFY_0": secret,
        PREFIX + "SETTINGS_APPRISEURL": secret,
    }

    with caplog.at_level(logging.DEBUG):
        check_setting_names(environ, config_file, LOGGER)

    assert len(caplog.records) == 3, [r.getMessage() for r in caplog.records]
    for record in caplog.records:
        assert "PLANTED-SECRET-TOKEN" not in record.getMessage()
        assert "PLANTED-SECRET-TOKEN" not in repr(record.args)


def test_legacy_and_new_name_both_set_warns_only_for_legacy(caplog):
    messages = _run(
        caplog,
        {
            PREFIX + "RESTART_CONTAINERS": "true",
            PREFIX + "SETTINGS_RESTARTCONTAINERS": "true",
        },
    )

    assert messages == [
        (
            f"Legacy setting {PREFIX}RESTART_CONTAINERS in environment is ignored; "
            f"use {PREFIX}SETTINGS_RESTARTCONTAINERS"
        )
    ]


def test_prefix_legacy_entry_warns_once_per_variable(caplog):
    messages = _run(caplog, {PREFIX + "NOTIFY_0": "a", PREFIX + "NOTIFY_1": "b"})

    assert messages == [
        f"Legacy setting {PREFIX}NOTIFY_{n} in environment is ignored; "
        f"use {PREFIX}SETTINGS_APPRISEURLS_<n>"
        for n in (0, 1)
    ]


def test_indexed_valid_name_is_not_warned(caplog):
    messages = _run(
        caplog,
        {
            PREFIX + "SETTINGS_APPRISEURLS_3": "x",
            PREFIX + "SETTINGS_DOMAINS_INCLUDE_0": "example.com",
        },
    )

    assert messages == []


def test_an_index_on_a_scalar_setting_is_unknown(caplog):
    """An index only addresses a list: `..._DATAPATH_0` sets nothing."""
    messages = _run(caplog, {PREFIX + "SETTINGS_DATAPATH_0": "/data"})

    assert len(messages) == 1, messages
    assert messages[0].startswith(f"Unknown setting {PREFIX}SETTINGS_DATAPATH_0 ")


def test_detection_failure_is_logged_once_and_startup_continues(
    caplog, tmp_path, monkeypatch
):
    from traefik_certificate_exporter.libs import legacy_settings

    def explode(*_args, **_kwargs):
        raise RuntimeError("boom")

    _clear_tce_env(monkeypatch)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(legacy_settings, "find_legacy_settings", explode)

    with caplog.at_level(logging.INFO):
        manager = SettingsManager()
        manager.loadFromFile(
            fileName=str(tmp_path / "absent.yaml"),
            cmdLineArgs=Namespace(**{"settings.datapath": str(tmp_path)}),
        )
    warnings = _warnings(caplog)

    assert manager.settings.dataPath == str(tmp_path)
    assert warnings == [
        "Setting-name check failed and was skipped (RuntimeError); start-up continues"
    ]


def test_no_findings_logs_nothing(caplog, tmp_path):
    from traefik_certificate_exporter.libs.legacy_settings import check_setting_names

    config_file = tmp_path / "config.yaml"
    config_file.write_text("settings:\n  restartcontainers: true\n", "utf-8")
    environ = {
        PREFIX + "SETTINGS_RESTARTCONTAINERS": "true",
        PREFIX + "LOGGING_LEVEL": "DEBUG",
        PREFIX + "SETTINGS_APPRISEURLS_0": "json://localhost",
        "PATH": "/usr/bin",
    }

    with caplog.at_level(logging.DEBUG):
        check_setting_names(environ, config_file, LOGGER)

    assert caplog.records == []


def test_mixed_case_name_confuse_honours_is_not_warned(caplog):
    """confuse lowercases everything after the prefix, so this name sets
    `settings.datapath`; reporting it as unknown would be a false WARNING (review M1)."""
    messages = _run(caplog, {PREFIX + "settings_DataPath": "/data"})

    assert messages == []


def test_mixed_case_source_name_is_unknown_because_getenv_is_case_sensitive(caplog):
    messages = _run(caplog, {PREFIX + "logging_level": "DEBUG"})

    assert messages == [
        (
            f"Unknown setting {PREFIX}logging_level in environment; "
            f"did you mean {PREFIX}LOGGING_LEVEL?"
        )
    ]


def test_hook_output_names_are_never_suggested(caplog):
    """`..._EXPORTED_DOMAINS` is set for the post-export command, not read: suggesting it
    would steer an operator from one dead name to another (review M2)."""
    from traefik_certificate_exporter.libs.legacy_settings import HOOK_OUTPUT_ENV_NAMES

    messages = _run(
        caplog,
        {
            PREFIX + "DOMAINS": "a",
            PREFIX + "EXPORT_DOMAINS": "b",
            PREFIX + "CORRELATIONID": "c",
        },
    )

    assert len(messages) == 3, messages
    for message in messages:
        assert not any(name in message for name in HOOK_OUTPUT_ENV_NAMES), message
