import logging

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


def test_redact_secrets_handles_none_value_without_raising():
    redacted = _redact_secrets({"pkcs12Passphrase": None})

    assert redacted["pkcs12Passphrase"] == "***REDACTED***"


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
# Secret redaction (E010-S01-001). The guard derives its scope from
# SECRET_CONFIG_KEYS rather than naming fields, so a declared setting is covered
# without editing anything here -- which is the property the scope plant below attacks.
# ---------------------------------------------------------------------------


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
