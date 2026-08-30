import logging

import pytest

from traefik_certificate_exporter.app import require_existing_path
from traefik_certificate_exporter.libs.settings import Settings


def _make_settings(dataPath=None, outputPath=None) -> Settings:
    return Settings(
        dataPath=dataPath,
        fileSpec="*.json",
        outputPath=outputPath,
        resolverInPathName=False,
        traefikResolverId="myresolver",
        flat=False,
        dryRun=False,
        restartContainers=False,
        domains={"include": [], "exclude": []},
        watchForChanges=False,
        runAtStart=False,
        watchInterval=60,
        pkcs12Passphrase=None,
    )


def test_unset_data_path_stays_none_not_the_string_none():
    settings = _make_settings(dataPath=None)

    assert settings.dataPath is None


def test_unset_output_path_stays_none_not_the_string_none():
    settings = _make_settings(outputPath=None)

    assert settings.outputPath is None


def test_configured_data_path_is_still_stringified():
    settings = _make_settings(dataPath="/data")

    assert settings.dataPath == "/data"


def test_require_existing_path_exits_when_path_is_none(caplog):
    with caplog.at_level(logging.ERROR), pytest.raises(SystemExit) as exc_info:
        require_existing_path(logging.getLogger("test"), None, "Data Path")

    assert exc_info.value.code == 1
    assert "not configured" in caplog.text


def test_require_existing_path_exits_when_path_does_not_exist(caplog, tmp_path):
    missing = tmp_path / "does-not-exist"

    with caplog.at_level(logging.ERROR), pytest.raises(SystemExit) as exc_info:
        require_existing_path(logging.getLogger("test"), str(missing), "Data Path")

    assert exc_info.value.code == 1
    assert "does not exist" in caplog.text


def test_require_existing_path_does_not_exit_when_path_exists(tmp_path):
    require_existing_path(logging.getLogger("test"), str(tmp_path), "Data Path")
