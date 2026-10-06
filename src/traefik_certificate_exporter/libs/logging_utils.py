###################################################################################################

import contextvars
import logging
import logging.config
import logging.handlers
import os
import traceback
import uuid
from pathlib import Path

import coloredlogs
import importlib_resources
import logging_tree
import pythonjsonlogger.json
import yaml

###################################################################################################

# The join key an operator greps for. One value per drain pass, carried across the
# watch event -> debounce timer -> export -> post-export command -> notification hops
# (ADR-0023). `contextvars` rather than a thread-local because it is the stdlib facility
# for exactly this, and because the value has to survive being rebound per pass without
# leaking into whatever ran before it -- `set()` returns a token that `reset()` undoes.
#
# It does NOT propagate across `threading.Timer` on its own (only `asyncio` tasks and an
# explicit `copy_context().run(...)` do), which is why the drain receives the id as an
# argument and re-binds it on the timer thread.
CORRELATION_ID_UNSET = "-"

_correlation_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "traefik_certificate_exporter_correlation_id", default=CORRELATION_ID_UNSET
)


def new_correlation_id() -> str:
    """A fresh, informationless pass id (stdlib UUID4 -- never derived from a domain)."""
    return str(uuid.uuid4())


def get_correlation_id() -> str:
    """The id in flight, or `CORRELATION_ID_UNSET` outside any pass."""
    return _correlation_id_var.get()


def set_correlation_id(correlation_id: str | None):
    """Bind `correlation_id` for this context; returns the token `reset` undoes."""
    return _correlation_id_var.set(correlation_id or CORRELATION_ID_UNSET)


def reset_correlation_id(token) -> None:
    """Undo a `set_correlation_id`, tolerating a token from another context."""
    try:
        _correlation_id_var.reset(token)
    except ValueError:
        # The token was created in a different context (e.g. the drain re-bound on the
        # timer thread). Losing the restore is harmless; raising out of a `finally` in
        # the export path is not.
        _correlation_id_var.set(CORRELATION_ID_UNSET)


class CorrelationIdColoredFormatter(coloredlogs.ColoredFormatter):
    """`coloredlogs.ColoredFormatter` that honours `defaults` the way 3.10's does.

    `logging.Formatter` has accepted a `defaults` mapping since 3.10, but
    `ColoredFormatter.__init__` does not forward it, so a console format string
    referencing `%(correlation_id)s` had no fallback at all: a record created before the
    record factory was installed -- or by anything that loaded a COPY of logging.yaml
    without importing this module -- raised `ValueError` on every single line.

    The record factory remains the mechanism that supplies the real id. This is only the
    floor underneath it.
    """

    def __init__(self, *args, defaults=None, **kwargs):
        super().__init__(*args, **kwargs)
        if defaults:
            self._style._defaults = {**(self._style._defaults or {}), **defaults}


class CorrelationIdJsonFormatter(pythonjsonlogger.json.JsonFormatter):
    """`JsonFormatter` that honours `defaults` for attributes a record does not carry.

    `pythonjsonlogger` reads its fields straight off the record and emits `null` for a
    missing one, so a record created before the record factory was installed rendered
    `"correlation_id": null` on the JSON sinks while the console sink rendered the
    `CORRELATION_ID_UNSET` sentinel for the same record. Neither raises, but an operator
    joining console and file output should not have to know that the absent case has two
    spellings. Filling the attribute from `defaults` before formatting gives both sinks
    one answer.
    """

    def __init__(self, *args, defaults=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._field_defaults = dict(defaults or {})

    def format(self, record):
        for field, value in self._field_defaults.items():
            if not hasattr(record, field):
                setattr(record, field, value)
        return super().format(record)


class _CorrelationIdRecordFactory:
    """Stamps `correlation_id` onto every record, whichever logger emitted it.

    A handler-level `logging.Filter` would only reach records routed through handlers that
    declare it, and a formatter referencing `%(correlation_id)s` on a record that lacks the
    attribute raises. The requirement is the opposite: a missing correlation id must never
    break the export pass it exists to observe, so the attribute is set at record creation
    and is therefore present on every record in the process.
    """

    def __init__(self, inner):
        self.inner = inner

    def __call__(self, *args, **kwargs):
        record = self.inner(*args, **kwargs)
        if not hasattr(record, "correlation_id"):
            try:
                record.correlation_id = _correlation_id_var.get()
            except Exception:  # noqa: BLE001 - logging must never raise into the caller
                record.correlation_id = CORRELATION_ID_UNSET
        return record


def install_correlation_id_record_factory() -> None:
    """Idempotently wrap the record factory so `correlation_id` is always present."""
    current = logging.getLogRecordFactory()
    if isinstance(current, _CorrelationIdRecordFactory):
        return
    logging.setLogRecordFactory(_CorrelationIdRecordFactory(current))


# Console handlers use the coloredlogs formatters on the left; opting into structured
# console output swaps each for the JSON formatter on the right, both declared in
# logging.yaml. Selected by its OWN env switch, never inferred from CONSOLEONLY: an
# operator watching `docker logs` by eye still wants colour (ADR-0023 Decision 2).
_CONSOLE_JSON_FORMATTERS = {
    "standard_formatter": "standard_json_formatter",
    "extended_formatter": "extended_json_formatter",
}

_TRUTHY = ("true", "1", "t", "y", "yes")


def _env_flag(env_key: str, default: str = "0") -> bool:
    return str(os.getenv(env_key, default)).lower() in _TRUTHY


def _apply_console_json(config: dict) -> dict:
    """Point every console handler at its JSON formatter, in the loaded config dict.

    Done on the dict before `dictConfig` rather than by rebuilding handlers afterwards:
    the formatters stay declared in logging.yaml (one place to audit), and it needs no
    API newer than the project's 3.10 floor.
    """
    formatters = config.get("formatters") or {}
    for handler in (config.get("handlers") or {}).values():
        if not isinstance(handler, dict):
            continue
        if "StreamHandler" not in str(handler.get("class", "")):
            continue
        replacement = _CONSOLE_JSON_FORMATTERS.get(handler.get("formatter"))
        if replacement and replacement in formatters:
            handler["formatter"] = replacement
    return config


###################################################################################################


class RollingFileHanderEx(logging.handlers.RotatingFileHandler):
    def __init__(
        self,
        filename,
        mode: str = "a",
        maxBytes: int = 0,
        backupCount: int = 0,
        encoding: str | None = None,
        delay: bool = False,
        errors: str | None = None,
    ) -> None:
        os.makedirs(os.path.dirname(filename), exist_ok=True)

        super().__init__(filename, mode, maxBytes, backupCount, encoding, delay, errors)


###################################################################################################


def setup_logging(
    cfg_file_name: str = "logging.yaml",
    default_level=logging.INFO,
    env_key: str = "TRAEFIK_CERTIFICATE_EXPORTER_LOGGING_CFGFILE",
    console_json_env_key: str = "TRAEFIK_CERTIFICATE_EXPORTER_LOGGING_CONSOLEJSON",
):
    """
    | **@author:** Prathyush SP
    | Logging Setup
    """

    install_correlation_id_record_factory()

    console_json = _env_flag(console_json_env_key)

    if isinstance(default_level, str):
        # default_level = getattr(logging, default_level.upper())
        default_level = logging.getLevelName(default_level.upper())

    path: str | None = None
    value = os.getenv(env_key, None)
    if value:
        path = value

    if path is None:
        # The PACKAGED copy only. An earlier version preferred `./logging.yaml`, and the
        # container's working directory is `/config` -- an operator-writable volume. The
        # file is handed to `logging.config.dictConfig`, which resolves arbitrary dotted
        # names for `class:` and `()` keys and calls them, so `yaml.safe_load` buys
        # nothing: a single write into the mounted volume was arbitrary code execution in
        # this process. Auto-discovery from the working directory is gone; an operator who
        # wants their own config says so explicitly via the env var above, which is a
        # deliberate act rather than a side effect of where a file happened to land.
        modulePath = Path(
            str(importlib_resources.files("traefik_certificate_exporter")),
            cfg_file_name,
        )

        if Path.exists(modulePath):
            path = str(modulePath)

    if path is None:
        # No relative fallback: `cfg_file_name` would resolve against the working
        # directory, which is the very discovery path removed above.
        coloredlogs.install(level=default_level)
        if default_level == logging.DEBUG:
            print("No logging configuration file found. Using default logging configs")
    elif os.path.exists(path):
        if default_level == logging.DEBUG:
            print(f"Loading logging configuration from {path}")

        with open(path, "rt") as f:
            try:
                config = yaml.safe_load(f.read())
                if console_json:
                    config = _apply_console_json(config)
                logging.config.dictConfig(config)
                logging.getLogger().setLevel(default_level)
            except Exception:  # noqa: BLE001 - logging setup must never abort startup
                print("Error in Logging Configuration. Using default configs")
                traceback.print_exc()

                coloredlogs.install(level=default_level)
    else:
        coloredlogs.install(level=default_level)
        if default_level == logging.DEBUG:
            print("No logging configuration file found. Using default logging configs")

    for handler in logging.getLogger().handlers:
        if isinstance(handler, type(logging.StreamHandler())):
            handler.setLevel(logging.DEBUG)

    if logging.getLogger().getEffectiveLevel() == logging.DEBUG:
        logging_tree.printout()


# Installed at import, not only from `setup_logging`: the formatters in logging.yaml
# reference `%(correlation_id)s`, so any caller that applies that config directly --
# the logging tests do -- must also get the attribute, or every record would fail to
# format. Idempotent, so the call in `setup_logging` stays harmless.
install_correlation_id_record_factory()

globalLoggerName = (
    "traefik_certificate_exporter_consoleonly"
    if str(os.getenv("TRAEFIK_CERTIFICATE_EXPORTER_LOGGING_CONSOLEONLY", "0")).lower()
    in ["true", "1", "t", "y", "yes"]
    else "traefik_certificate_exporter"
)
globalLogger = logging.getLogger(globalLoggerName)
