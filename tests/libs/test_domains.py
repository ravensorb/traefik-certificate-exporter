from argparse import Namespace

import pytest

from traefik_certificate_exporter.libs.settings import SettingsManager


def _namespace(**dotted_kwargs) -> Namespace:
    ns = Namespace()
    for key, value in dotted_kwargs.items():
        setattr(ns, key, value)
    return ns


def test_env_var_include_only_works_without_setting_exclude(tmp_path, monkeypatch):
    """GitHub #5: setting only INCLUDE via env var must not require a dummy EXCLUDE."""
    monkeypatch.setenv(
        "TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_DOMAINS_INCLUDE", "foo.com,bar.com"
    )
    monkeypatch.delenv(
        "TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_DOMAINS_EXCLUDE", raising=False
    )
    manager = SettingsManager()

    manager.loadFromFile(
        fileName=str(tmp_path / "does-not-exist.yaml"), cmdLineArgs=_namespace()
    )

    assert manager.settings.domains["include"] == ["foo.com", "bar.com"]
    assert manager.settings.domains["exclude"] == []


def test_env_var_exclude_only_works_without_setting_include(tmp_path, monkeypatch):
    monkeypatch.setenv(
        "TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_DOMAINS_EXCLUDE", "foo.com"
    )
    monkeypatch.delenv(
        "TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_DOMAINS_INCLUDE", raising=False
    )
    manager = SettingsManager()

    manager.loadFromFile(
        fileName=str(tmp_path / "does-not-exist.yaml"), cmdLineArgs=_namespace()
    )

    assert manager.settings.domains["include"] == []
    assert manager.settings.domains["exclude"] == ["foo.com"]


def test_config_file_include_only_works_without_setting_exclude(tmp_path, monkeypatch):
    monkeypatch.delenv(
        "TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_DOMAINS_INCLUDE", raising=False
    )
    monkeypatch.delenv(
        "TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_DOMAINS_EXCLUDE", raising=False
    )
    config_file = tmp_path / "config.yaml"
    config_file.write_text("settings:\n  domains:\n    include:\n      - foo.com\n")
    manager = SettingsManager()

    manager.loadFromFile(fileName=str(config_file), cmdLineArgs=_namespace())

    assert manager.settings.domains["include"] == ["foo.com"]
    assert manager.settings.domains["exclude"] == []


def test_both_set_across_surfaces_raises_clear_error(tmp_path, monkeypatch, capsys):
    """A CLI-set include plus an env-var-set exclude must fail loudly, not silently mix."""
    monkeypatch.setenv(
        "TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_DOMAINS_EXCLUDE", "bar.com"
    )
    manager = SettingsManager()

    with pytest.raises(SystemExit) as exc_info:
        manager.loadFromFile(
            fileName=str(tmp_path / "does-not-exist.yaml"),
            cmdLineArgs=_namespace(**{"settings.domains.include": ["foo.com"]}),
        )

    assert exc_info.value.code == 1


def test_neither_set_defaults_to_empty_lists(tmp_path, monkeypatch):
    monkeypatch.delenv(
        "TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_DOMAINS_INCLUDE", raising=False
    )
    monkeypatch.delenv(
        "TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_DOMAINS_EXCLUDE", raising=False
    )
    manager = SettingsManager()

    manager.loadFromFile(
        fileName=str(tmp_path / "does-not-exist.yaml"), cmdLineArgs=_namespace()
    )

    assert manager.settings.domains == {"include": [], "exclude": []}
