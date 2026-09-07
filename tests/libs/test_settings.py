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
