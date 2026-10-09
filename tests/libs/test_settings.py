import logging

import pytest

from traefik_certificate_exporter.libs.settings import (
    Settings,
    SettingsManager,
    _redact_secrets,
)


def _make_settings(passphrase: str | None = "super-secret-value") -> Settings:
    return Settings(
        dataPath="/data",
        fileSpec="*.json",
        outputPath="/certs",
        resolverInPathName=False,
        traefikResolverId="myresolver",
        flat=False,
        dryRun=False,
        restartContainers=False,
        domains={"include": [], "exclude": []},
        watchForChanges=False,
        runAtStart=False,
        watchInterval=60,
        pkcs12Passphrase=passphrase,
    )


def test_redact_secrets_masks_known_secret_keys():
    redacted = _redact_secrets({"pkcs12Passphrase": "hunter2", "dataPath": "/data"})

    assert redacted["pkcs12Passphrase"] == "***REDACTED***"
    assert redacted["dataPath"] == "/data"


def test_redact_secrets_matches_by_name_not_a_hardcoded_field_list():
    # A brand-new secret-shaped field (never referenced by settings.py) must still be
    # redacted, proving the match is name/allowlist-based rather than per-field.
    redacted = _redact_secrets({"someFutureApiToken": "abc123", "count": 3})

    assert redacted["someFutureApiToken"] == "***REDACTED***"
    assert redacted["count"] == 3


def test_an_unset_secret_renders_as_null_rather_than_redacted():
    """UX-001: masking by key alone told an operator a credential they never configured
    was populated. The absence of a credential is not a credential."""
    redacted = _redact_secrets({"pkcs12Passphrase": None})

    assert redacted["pkcs12Passphrase"] is None


def test_redact_secrets_handles_absent_key_without_raising():
    redacted = _redact_secrets({"dataPath": "/data"})

    assert "pkcs12Passphrase" not in redacted


def test_dump_settings_never_logs_passphrase_verbatim(caplog):
    passphrase = "s3cr3t-passphrase-value"
    manager = SettingsManager()
    manager.settings = _make_settings(passphrase=passphrase)

    with caplog.at_level(logging.DEBUG):
        manager._dump_settings()

    assert passphrase not in caplog.text
    assert "***REDACTED***" in caplog.text


def test_dump_settings_with_no_passphrase_does_not_raise(caplog):
    manager = SettingsManager()
    manager.settings = _make_settings(passphrase=None)

    with caplog.at_level(logging.DEBUG):
        manager._dump_settings()


def test_command_line_args_are_redacted_before_they_reach_the_log(caplog, tmp_path):
    """The raw argparse namespace was logged verbatim at DEBUG.

    `--pkcs12-passphrase` is a command-line flag, so the credential appeared in full in
    the log line that announces the CLI source -- a few lines above the dump helpers that
    take care to mask exactly that field. Redacting one source and printing another is a
    leak, not a partial win.
    """
    import logging
    from argparse import Namespace

    from traefik_certificate_exporter.libs.settings import SettingsManager

    args = Namespace(
        configfile=str(tmp_path / "absent.yaml"),
        **{"settings.pkcs12passphrase": "hunter2", "settings.datapath": str(tmp_path)},
    )

    with caplog.at_level(logging.DEBUG):
        SettingsManager().loadFromFile(
            fileName=str(tmp_path / "absent.yaml"), cmdLineArgs=args
        )

    leaked = [r.getMessage() for r in caplog.records if "hunter2" in r.getMessage()]
    assert not leaked, f"the passphrase reached the log: {leaked}"


# ---------------------------------------------------------------------------
# /config trust-boundary invariant has no runtime enforcement (EC-002, epic-011 closure
# red-team). `loadFromFile` documents the mount as trusted but never checked; these prove
# the WARNING fires on an actually-writable file and stays silent on a safe one.
# ---------------------------------------------------------------------------


def test_loadfromfile_warns_when_the_config_file_is_world_writable(tmp_path, caplog):
    import logging
    import os
    import stat

    from traefik_certificate_exporter.libs.settings import SettingsManager

    cfg = tmp_path / "config.yaml"
    cfg.write_text("settings:\n  datapath: /data\n")
    os.chmod(cfg, stat.S_IRUSR | stat.S_IWUSR | stat.S_IWOTH)

    with caplog.at_level(logging.WARNING):
        SettingsManager().loadFromFile(fileName=str(cfg))

    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert any("group- or world-writable" in m and str(cfg) in m for m in warnings), (
        f"expected a writable-mount warning naming {cfg}, got: {warnings}"
    )


def test_loadfromfile_does_not_warn_when_the_config_file_is_not_writable_by_others(
    tmp_path, caplog
):
    import logging
    import os
    import stat

    from traefik_certificate_exporter.libs.settings import SettingsManager

    cfg = tmp_path / "config.yaml"
    cfg.write_text("settings:\n  datapath: /data\n")
    os.chmod(cfg, stat.S_IRUSR | stat.S_IWUSR)

    with caplog.at_level(logging.WARNING):
        SettingsManager().loadFromFile(fileName=str(cfg))

    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert not any("group- or world-writable" in m for m in warnings)


def _capture_all_records(caplog, tmp_path, config_text, cli_overrides):
    """Run a full load at DEBUG and return every message emitted.

    Asserted over everything captured rather than over named dump functions, because the
    leak this closes was in neither of them -- it was the raw argparse namespace, logged a
    few lines above the helpers that redact.
    """
    import logging
    from argparse import Namespace

    from traefik_certificate_exporter.libs.settings import SettingsManager

    cfg = tmp_path / "config.yaml"
    cfg.write_text(config_text)
    args = Namespace(configfile=str(cfg), **cli_overrides)

    with caplog.at_level(logging.DEBUG):
        manager = SettingsManager()
        manager.loadFromFile(fileName=str(cfg), cmdLineArgs=args)
        manager._dump_config()
        manager._dump_settings()

    return "\n".join(r.getMessage() for r in caplog.records)


def test_every_declared_secret_key_is_redacted_in_every_sink(caplog, tmp_path):
    """Scope comes from the registry, so a new declaration is covered with no edit here."""
    from traefik_certificate_exporter.libs.settings import SECRET_CONFIG_KEYS

    assert SECRET_CONFIG_KEYS, "no secret paths declared; this guard examined nothing"

    for config_key in SECRET_CONFIG_KEYS:
        assert config_key[0] == "settings", f"unhandled key shape: {config_key}"
        key = config_key[-1]
        planted = f"PLANTED-{key.upper()}"
        captured = _capture_all_records(
            caplog,
            tmp_path,
            f"settings:\n  {key}: {planted}\n  datapath: {tmp_path}\n",
            {f"settings.{key}": planted, "settings.datapath": str(tmp_path)},
        )
        assert planted not in captured, (
            f"{'.'.join(config_key)} reached a log record at DEBUG"
        )
        caplog.clear()


def test_a_newly_declared_secret_is_covered_without_touching_the_guard(
    caplog, tmp_path, monkeypatch
):
    """The plant attacks the SCOPE, not the rule.

    `destinationlist` matches none of `_SECRET_FIELD_PATTERN`'s words, so nothing about
    its *name* makes it a secret -- only its presence in the registry does. If redaction
    ever stops deriving from that registry, this fails while a name-shaped case would
    still pass, which is the whole point.
    """
    from traefik_certificate_exporter.libs import settings as settings_module

    monkeypatch.setattr(
        settings_module,
        "SECRET_CONFIG_KEYS",
        (*settings_module.SECRET_CONFIG_KEYS, ("settings", "destinationlist")),
    )
    settings_module._secret_leaf_names.cache_clear()

    planted = "PLANTED-BY-PATH-NOT-BY-NAME"
    captured = _capture_all_records(
        caplog,
        tmp_path,
        f"settings:\n  destinationlist: {planted}\n  datapath: {tmp_path}\n",
        # Passed on the command line as well, so the argparse-namespace sink -- the one
        # that was actually leaking -- is exercised. Through the config file alone this
        # test is satisfied by confuse's own path redaction and proves nothing about
        # whether `_redact_secrets` consults the registry.
        {"settings.destinationlist": planted, "settings.datapath": str(tmp_path)},
    )
    settings_module._secret_leaf_names.cache_clear()

    assert not settings_module._SECRET_FIELD_PATTERN.search("destinationlist"), (
        "pick a name the pattern cannot catch, or this proves nothing about the registry"
    )
    assert planted not in captured, (
        "a declared secret path was not redacted -- redaction is not deriving its scope "
        "from SECRET_CONFIG_KEYS"
    )


def test_a_secret_nested_in_a_list_of_objects_is_redacted():
    """The shape neither existing guard exercises (BL-E010-003).

    `_dump_config` redacts by config PATH, which reaches `appriseurls` -- a list of raw
    strings -- without ever descending into it. `_dump_settings` serialises the `Settings`
    dataclass instead, so it redacts by where a declared leaf name sits in the walked
    structure. A declared secret held one level deeper, inside objects *within* a list,
    is the position that tests neither: the list recursion has to run, and then the
    declared-key check has to fire on the dict inside it.
    """
    from traefik_certificate_exporter.libs.settings import (
        _REDACTED_VALUE,
        _redact_secrets,
    )

    redacted = _redact_secrets(
        {
            "destinations": [
                {"name": "primary", "pkcs12Passphrase": "PLANTED-IN-A-LIST"},
                {"name": "secondary", "appriseUrls": ["tgram://PLANTED-TOKEN/chat"]},
            ]
        }
    )

    assert redacted["destinations"][0]["pkcs12Passphrase"] == _REDACTED_VALUE
    assert redacted["destinations"][1]["appriseUrls"] == _REDACTED_VALUE
    assert redacted["destinations"][0]["name"] == "primary", (
        "redaction must not flatten non-secret siblings"
    )


def test_an_undeclared_credential_shaped_name_in_a_nested_list_is_still_caught():
    """The backstop pattern has to survive the same nesting the registry check does."""
    from traefik_certificate_exporter.libs.settings import (
        _REDACTED_VALUE,
        _redact_secrets,
    )

    redacted = _redact_secrets([[{"api_key": "PLANTED-UNDECLARED"}]])

    assert redacted[0][0]["api_key"] == _REDACTED_VALUE


# ---------------------------------------------------------------------------
# UX-001: redaction is value-aware. An operator who raises `-ll DEBUG` to answer "is my
# notification/passphrase config actually loading?" was told, falsely, that both were
# populated -- and the two sinks disagreed with each other about the same unset field.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("key", ["pkcs12passphrase", "appriseurls"])
def test_an_unset_declared_secret_is_not_reported_as_configured(caplog, tmp_path, key):
    captured = _capture_all_records(
        caplog,
        tmp_path,
        f"settings:\n  datapath: {tmp_path}\n",
        {"settings.datapath": str(tmp_path)},
    )

    assert "REDACTED" not in captured, (
        f"an unconfigured '{key}' was reported as a populated credential:\n{captured}"
    )


@pytest.mark.parametrize("key", ["pkcs12passphrase", "appriseurls"])
def test_an_empty_declared_secret_is_not_reported_as_configured(caplog, tmp_path, key):
    """Explicitly present but empty -- `pkcs12passphrase: ""` / `appriseurls: []`."""
    empty = '""' if key == "pkcs12passphrase" else "[]"
    captured = _capture_all_records(
        caplog,
        tmp_path,
        f"settings:\n  {key}: {empty}\n  datapath: {tmp_path}\n",
        {
            f"settings.{key}": "" if key == "pkcs12passphrase" else [],
            "settings.datapath": str(tmp_path),
        },
    )

    assert "REDACTED" not in captured, (
        f"an empty '{key}' was reported as a populated credential:\n{captured}"
    )


@pytest.mark.parametrize("key", ["pkcs12passphrase", "appriseurls"])
def test_a_set_declared_secret_is_still_masked_in_every_sink(caplog, tmp_path, key):
    planted = f"PLANTED-{key.upper()}"
    value = planted if key == "pkcs12passphrase" else f"[{planted}]"
    captured = _capture_all_records(
        caplog,
        tmp_path,
        f"settings:\n  {key}: {value}\n  datapath: {tmp_path}\n",
        {
            f"settings.{key}": planted if key == "pkcs12passphrase" else [planted],
            "settings.datapath": str(tmp_path),
        },
    )

    assert planted not in captured, f"settings.{key} reached a log record at DEBUG"
    assert "REDACTED" in captured, "a configured credential was not masked at all"


def test_both_dump_sinks_agree_that_an_unset_secret_is_absent(caplog, tmp_path):
    """They disagreed: confuse omitted the unset passphrase while the settings dump
    printed `***REDACTED***` for it, so the operator read "absent here, set there"."""
    import logging as _logging
    from argparse import Namespace

    from traefik_certificate_exporter.libs.settings import SettingsManager

    cfg = tmp_path / "config.yaml"
    cfg.write_text(f"settings:\n  datapath: {tmp_path}\n")

    with caplog.at_level(_logging.DEBUG):
        manager = SettingsManager()
        manager.loadFromFile(
            fileName=str(cfg),
            cmdLineArgs=Namespace(
                configfile=str(cfg), **{"settings.datapath": str(tmp_path)}
            ),
        )
        caplog.clear()
        manager._dump_config()
        configDump = "\n".join(r.getMessage() for r in caplog.records)
        caplog.clear()
        manager._dump_settings()
        settingsDump = "\n".join(r.getMessage() for r in caplog.records)

    assert "REDACTED" not in configDump, configDump
    assert "REDACTED" not in settingsDump, settingsDump
    assert manager.settings.pkcs12Passphrase is None
    assert manager.settings.appriseUrls == []


def test_an_empty_secret_value_is_recognised_but_zero_is_not():
    from traefik_certificate_exporter.libs.settings import _is_empty_secret

    assert _is_empty_secret(None)
    assert _is_empty_secret("")
    assert _is_empty_secret([])
    assert not _is_empty_secret("hunter2")
    assert not _is_empty_secret(["tgram://token/"])
    assert not _is_empty_secret(0), "0 is not credential-shaped emptiness"
    assert not _is_empty_secret(False)
