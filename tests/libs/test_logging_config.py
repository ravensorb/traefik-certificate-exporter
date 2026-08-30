import json
import logging
import logging.config

import importlib_resources
import yaml


def _load_logging_config() -> dict:
    path = importlib_resources.files("traefik_certificate_exporter").joinpath(
        "logging.yaml"
    )
    return yaml.safe_load(path.read_text())


def test_logging_config_is_valid_dictconfig():
    logging.config.dictConfig(_load_logging_config())


def test_file_handler_emits_valid_json_with_required_keys(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    logging.config.dictConfig(_load_logging_config())

    logger = logging.getLogger("traefik_certificate_exporter")
    logger.setLevel(logging.DEBUG)
    logger.info("export finished")

    log_file = tmp_path / "traefik-certificate-exporter.log"
    line = log_file.read_text().splitlines()[0]
    parsed = json.loads(line)

    assert parsed["message"] == "export finished"
    assert parsed["levelname"] == "INFO"
    assert parsed["name"] == "traefik_certificate_exporter"
    assert "asctime" in parsed


def test_file_handler_json_does_not_break_redaction(tmp_path, monkeypatch):
    """A pre-redacted message (Epic 1) must not be re-exposed by the JSON envelope."""
    monkeypatch.chdir(tmp_path)
    logging.config.dictConfig(_load_logging_config())

    logger = logging.getLogger("traefik_certificate_exporter")
    logger.setLevel(logging.DEBUG)
    logger.debug('{"pkcs12Passphrase": "***REDACTED***"}')

    log_file = tmp_path / "traefik-certificate-exporter.log"
    line = log_file.read_text().splitlines()[0]
    parsed = json.loads(line)

    assert "***REDACTED***" in parsed["message"]
    assert "hunter2" not in line
