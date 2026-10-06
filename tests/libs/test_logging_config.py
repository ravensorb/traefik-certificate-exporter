import contextlib
import json
import logging
import logging.config

import importlib_resources
import pytest
import yaml

from traefik_certificate_exporter.libs.logging_utils import (
    CORRELATION_ID_UNSET,
    reset_correlation_id,
    set_correlation_id,
    setup_logging,
)


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


###########################################################################################
# Structured console output (ADR-0023 Decision 2) and the correlation_id field.


def test_console_output_is_coloured_text_by_default(tmp_path, monkeypatch, capsys):
    """Opt-in means opt-in: an operator who sets nothing sees what they saw before."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv(
        "TRAEFIK_CERTIFICATE_EXPORTER_LOGGING_CONSOLEJSON", raising=False
    )

    setup_logging(default_level=logging.INFO)
    logging.getLogger("traefik_certificate_exporter_consoleonly").info("hello")

    line = capsys.readouterr().out.splitlines()[-1]
    with pytest.raises(json.JSONDecodeError):
        json.loads(line)
    assert "hello" in line


def test_console_output_becomes_structured_json_when_opted_in(
    tmp_path, monkeypatch, capsys
):
    """The container ships CONSOLEONLY=true, so a correlation_id that only reaches the
    file handler is useless to anyone reading `docker logs`."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TRAEFIK_CERTIFICATE_EXPORTER_LOGGING_CONSOLEJSON", "true")

    setup_logging(default_level=logging.INFO)
    token = set_correlation_id("11111111-2222-3333-4444-555555555555")
    try:
        logging.getLogger("traefik_certificate_exporter_consoleonly").info("exported")
    finally:
        reset_correlation_id(token)

    parsed = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert parsed["message"] == "exported"
    assert parsed["correlation_id"] == "11111111-2222-3333-4444-555555555555"


def test_the_file_handler_carries_correlation_id_as_a_field(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    logging.config.dictConfig(_load_logging_config())

    logger = logging.getLogger("traefik_certificate_exporter")
    logger.setLevel(logging.DEBUG)
    token = set_correlation_id("abc-123")
    try:
        logger.info("export finished")
    finally:
        reset_correlation_id(token)

    parsed = json.loads(
        (tmp_path / "traefik-certificate-exporter.log").read_text().splitlines()[0]
    )
    assert parsed["correlation_id"] == "abc-123"


def test_a_record_outside_any_pass_still_formats(tmp_path, monkeypatch):
    """A formatter referencing a missing attribute raises -- so the field must be present
    on every record in the process, pass or no pass."""
    monkeypatch.chdir(tmp_path)
    logging.config.dictConfig(_load_logging_config())

    logger = logging.getLogger("traefik_certificate_exporter")
    logger.setLevel(logging.DEBUG)
    logger.info("startup")

    parsed = json.loads(
        (tmp_path / "traefik-certificate-exporter.log").read_text().splitlines()[0]
    )
    assert parsed["correlation_id"] == CORRELATION_ID_UNSET


###########################################################################################
# RT-004: `/config` is the container's working directory AND an operator-writable volume.
# `logging.config.dictConfig` resolves and CALLS arbitrary dotted names for its `class:`
# and `()` keys, so preferring `./logging.yaml` made a single file write into that volume
# arbitrary code execution. `yaml.safe_load` does not make `dictConfig` safe.


_MARKER = {"loaded": False}


@contextlib.contextmanager
def _preserved_logging_state():
    """Restore every logger this test touched.

    `dictConfig` defaults to `disable_existing_loggers: True`, so applying a hostile
    config -- which is the whole point of these tests -- would otherwise leave the
    application loggers disabled for every test that runs afterwards.
    """
    names = [
        None,
        "traefik_certificate_exporter",
        "traefik_certificate_exporter_consoleonly",
    ]
    saved = []
    for name in names:
        logger = logging.getLogger(name) if name else logging.getLogger()
        saved.append(
            (
                logger,
                list(logger.handlers),
                logger.level,
                logger.propagate,
                logger.disabled,
            )
        )
    try:
        yield
    finally:
        for logger, handlers, level, propagate, disabled in saved:
            logger.handlers[:] = handlers
            logger.setLevel(level)
            logger.propagate = propagate
            logger.disabled = disabled


def _marker_formatter(*args, **kwargs):
    _MARKER["loaded"] = True
    return logging.Formatter("%(message)s")


def _hostile_config() -> dict:
    return {
        "version": 1,
        "formatters": {
            "pwned": {"()": "tests.libs.test_logging_config._marker_formatter"}
        },
        "handlers": {
            "h": {"class": "logging.StreamHandler", "formatter": "pwned"},
        },
        "root": {"handlers": ["h"], "level": "ERROR"},
    }


def test_a_planted_logging_yaml_in_the_working_directory_is_not_loaded(
    tmp_path, monkeypatch
):
    """Injected fault: the exact file an attacker who can write to /config would plant."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("TRAEFIK_CERTIFICATE_EXPORTER_LOGGING_CFGFILE", raising=False)
    (tmp_path / "logging.yaml").write_text(yaml.safe_dump(_hostile_config()))

    _MARKER["loaded"] = False
    with _preserved_logging_state():
        try:
            setup_logging(cfg_file_name="logging.yaml", default_level=logging.INFO)
        finally:
            loaded = _MARKER["loaded"]
            _MARKER["loaded"] = False

    assert loaded is False, (
        "a logging.yaml planted in the working directory was loaded and executed"
    )


def test_an_explicitly_pointed_logging_config_is_still_honoured(tmp_path, monkeypatch):
    """Removing auto-discovery must not remove the operator's deliberate override."""
    monkeypatch.chdir(tmp_path)
    explicit = tmp_path / "elsewhere" / "mine.yaml"
    explicit.parent.mkdir()
    explicit.write_text(yaml.safe_dump(_hostile_config()))
    monkeypatch.setenv("TRAEFIK_CERTIFICATE_EXPORTER_LOGGING_CFGFILE", str(explicit))

    _MARKER["loaded"] = False
    with _preserved_logging_state():
        try:
            setup_logging(cfg_file_name="logging.yaml", default_level=logging.INFO)
        finally:
            loaded = _MARKER["loaded"]
            _MARKER["loaded"] = False

    assert loaded is True, "the explicitly configured logging config was ignored"


def test_the_packaged_config_formats_without_the_record_factory(tmp_path, monkeypatch):
    """AD-11: a copy of logging.yaml handed to `dictConfig` by something that never
    imported `logging_utils` must not raise `ValueError` on every single record."""
    monkeypatch.chdir(tmp_path)
    config = _load_logging_config()

    for formatter in config["formatters"].values():
        assert formatter.get("defaults", {}).get("correlation_id") == (
            CORRELATION_ID_UNSET
        )

    previous = logging.getLogRecordFactory()
    with _preserved_logging_state():
        try:
            logging.config.dictConfig(config)
            logging.setLogRecordFactory(logging.LogRecord)
            record = logging.LogRecord(
                "t", logging.WARNING, __file__, 1, "bare record", None, None
            )
            rendered = []
            for handler in logging.getLogger("traefik_certificate_exporter").handlers:
                rendered.append(handler.format(record))
        finally:
            logging.setLogRecordFactory(previous)

    # UX-001: the console sink rendered the sentinel and the JSON sink rendered `null`
    # for the same absent attribute. Both sink types are exercised here, so both must
    # spell the absent case the same way.
    assert rendered, "no handler formatted the bare record"
    for text in rendered:
        if text.lstrip().startswith("{"):
            assert json.loads(text)["correlation_id"] == CORRELATION_ID_UNSET, text
        else:
            assert f"[{CORRELATION_ID_UNSET}]" in text, text
