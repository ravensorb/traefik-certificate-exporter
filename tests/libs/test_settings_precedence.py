from argparse import Namespace

import pytest

from traefik_certificate_exporter.libs.settings import SettingsManager


def _namespace(**dotted_kwargs) -> Namespace:
    ns = Namespace()
    for key, value in dotted_kwargs.items():
        setattr(ns, key, value)
    return ns


def test_packaged_default_applies_when_nothing_else_is_set(tmp_path, monkeypatch):
    monkeypatch.delenv("TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_DATAPATH", raising=False)
    manager = SettingsManager()

    manager.loadFromFile(
        fileName=str(tmp_path / "does-not-exist.yaml"), cmdLineArgs=_namespace()
    )

    assert manager.settings.dataPath == "./data"  # config_default.yaml packaged default


def test_env_var_overrides_packaged_default(tmp_path, monkeypatch):
    monkeypatch.setenv("TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_DATAPATH", "/from-env")
    manager = SettingsManager()

    manager.loadFromFile(
        fileName=str(tmp_path / "does-not-exist.yaml"), cmdLineArgs=_namespace()
    )

    assert manager.settings.dataPath == "/from-env"


def test_env_var_overrides_config_file(tmp_path, monkeypatch):
    monkeypatch.setenv("TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_DATAPATH", "/from-env")
    config_file = tmp_path / "config.yaml"
    config_file.write_text("settings:\n  datapath: /from-config-file\n")
    manager = SettingsManager()

    manager.loadFromFile(fileName=str(config_file), cmdLineArgs=_namespace())

    assert manager.settings.dataPath == "/from-env"


def test_cli_arg_overrides_everything(tmp_path, monkeypatch):
    monkeypatch.setenv("TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_DATAPATH", "/from-env")
    config_file = tmp_path / "config.yaml"
    config_file.write_text("settings:\n  datapath: /from-config-file\n")
    manager = SettingsManager()

    manager.loadFromFile(
        fileName=str(config_file),
        cmdLineArgs=_namespace(**{"settings.datapath": "/from-cli"}),
    )

    assert manager.settings.dataPath == "/from-cli"


def test_pkcs12_passphrase_cli_flag_populates_settings(tmp_path, monkeypatch):
    monkeypatch.delenv(
        "TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_PKCS12PASSPHRASE", raising=False
    )
    manager = SettingsManager()

    manager.loadFromFile(
        fileName=str(tmp_path / "does-not-exist.yaml"),
        cmdLineArgs=_namespace(**{"settings.pkcs12passphrase": "from-cli-flag"}),
    )

    assert manager.settings.pkcs12Passphrase == "from-cli-flag"


@pytest.mark.parametrize(
    "source, expected",
    [("default", True), ("file", False), ("env", False), ("cli", False)],
)
def test_validatekeys_precedence(tmp_path, monkeypatch, source, expected):
    """CLI > env > config file > packaged default; each layer below the winner says
    the opposite, so a layer that is ignored or wins wrongly flips the result."""
    envName = "TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_VALIDATEKEYS"
    monkeypatch.delenv(envName, raising=False)
    configFile = tmp_path / "config.yaml"
    cli = {}
    if source == "file":
        configFile.write_text("settings:\n  validatekeys: false\n")
    elif source == "env":
        configFile.write_text("settings:\n  validatekeys: true\n")
        monkeypatch.setenv(envName, "false")
    elif source == "cli":
        configFile.write_text("settings:\n  validatekeys: true\n")
        monkeypatch.setenv(envName, "true")
        cli = {"settings.validatekeys": False}
    manager = SettingsManager()

    manager.loadFromFile(fileName=str(configFile), cmdLineArgs=_namespace(**cli))

    assert manager.settings.validateKeys is expected
