#!/usr/bin/env python3

import os
import signal
import sys
import time

import watchdog.events
import watchdog.observers

from ._version import __version__
from .libs.certificate_exporter import (
    NO_CHANGE_MESSAGE,
    AcmeCertificateExporter,
    AcmeCertificateFileHandler,
)
from .libs.cli_args import (
    globalArgs,
    parse_args_strict,
)
from .libs.docker import DockerManager
from .libs.logging_utils import (
    DEFAULT_LOG_LEVEL,
    LOG_LEVEL_CHOICES,
    LOG_LEVEL_ENV,
    globalLogger,
    new_correlation_id,
    reset_correlation_id,
    sanitize_for_log,
    set_correlation_id,
    setup_logging,
)
from .libs.notify import send_export_notifications
from .libs.post_export import run_post_export_command
from .libs.settings import globalSettingsMgr

###########################################################################################################
###########################################################################################################


def require_existing_path(logger, path: str | None, label: str) -> None:
    """Exit(1) if `path` is unset or does not exist on disk, logging why either way."""
    if path is None:
        logger.error(f"{label} is not configured. Exiting...")
        sys.exit(1)
    if not os.path.exists(path):
        logger.error(f"{label} '{path}' does not exist. Exiting...")
        sys.exit(1)


def install_shutdown_signal_handlers(logger) -> None:
    """Route SIGTERM (and SIGINT) into the shutdown path that already exists.

    SIGINT arrives as `KeyboardInterrupt` for free; SIGTERM does not. Its default
    disposition terminates the interpreter outright, so `event_handler.cancel()` -- which
    only ever ran from `except KeyboardInterrupt` -- was unreachable under every way this
    process is actually stopped: `docker stop`, `kubectl delete`, systemd, s6. The
    documented shutdown behaviour was therefore true of Ctrl-C alone.

    Raising `KeyboardInterrupt` from the handler rather than setting a flag is deliberate:
    the handler body below is already written, already tested, and already correct. This
    makes the signal reach it unchanged, and it also breaks the `time.sleep` the watch
    loop is parked in.
    """

    def raiseKeyboardInterrupt(signum, _frame):
        raise KeyboardInterrupt(f"signal {signum}")

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(sig, raiseKeyboardInterrupt)
        except (ValueError, OSError, AttributeError, RuntimeError) as e:
            # `signal.signal` only works on the main thread of the main interpreter, and
            # not every platform defines every signal. Losing the handler must not stop
            # the exporter from running.
            logger.debug(f"Could not install a shutdown handler for {sig!r}: {e}")


def _log_level_with_source(cli_value: str | None) -> tuple[str, str, str | None]:
    """Resolve the effective log level: `-ll` > `LOGGING_LEVEL` env > INFO.

    Returns `(level, source, rejected)`: `source` is `cli`, `env` or `default`, and
    `rejected` is the raw env value when it was set but is not a level (None otherwise).

    Read with `os.getenv` rather than through confuse because logging is configured before
    settings load -- the same reason the other `LOGGING_*` variables are read this way. One
    pair of surrounding quotes is stripped: Compose passes `- FOO="DEBUG"` through with the
    quotes, and the documented samples historically quoted values. An empty value counts as
    unset. An invalid value does not exit: verbosity is not a correctness setting, and
    exiting would put a watch-mode container into an s6 respawn loop.
    """
    if cli_value:
        return cli_value.upper(), "cli", None
    raw = os.getenv(LOG_LEVEL_ENV)
    value = (raw or "").strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1].strip()
    if not value:
        return DEFAULT_LOG_LEVEL, "default", None
    if value.upper() in LOG_LEVEL_CHOICES:
        return value.upper(), "env", None
    return DEFAULT_LOG_LEVEL, "default", raw


def _resolve_log_level(cli_value: str | None) -> str:
    """The effective level name (upper case) -- see `_log_level_with_source`."""
    return _log_level_with_source(cli_value)[0]


def main():
    # The imported `globalArgs` was parsed leniently so that importing this module can
    # never die on somebody else's argv -- it stays as `app.globalArgs`' safe default for
    # anything that imports without calling `main()`, which is why the import above is
    # kept even though every read below happens after the rebind. Here argv is this
    # process's own, so an unrecognized flag is a typo and must fail loudly: rebind the
    # module-level name to the strict parse before any attribute of it is read
    # (ADR-0025, BL-E001-006).
    global globalArgs
    globalArgs = parse_args_strict()

    logLevel, logLevelSource, rejectedLogLevel = _log_level_with_source(
        globalArgs.logginglevel
    )

    setup_logging(
        cfg_file_name="logging.yaml",
        default_level=logLevel,
        env_key="TRAEFIK_CERTIFICATE_EXPORTER_LOGGING_CFGFILE",
    )

    logger = globalLogger
    logger.setLevel(logLevel)

    # Both only once logging exists, so neither is lost to an unconfigured logger.
    if rejectedLogLevel is not None:
        logger.warning(
            f"Ignoring {LOG_LEVEL_ENV}='{sanitize_for_log(rejectedLogLevel)}': not one "
            f"of {', '.join(LOG_LEVEL_CHOICES)}. Using {DEFAULT_LOG_LEVEL}."
        )
    logger.info(f"Log level: {logLevel} (source: {logLevelSource})")

    install_shutdown_signal_handlers(logger)

    # One handling point for the whole run. The handler raises `KeyboardInterrupt`
    # unconditionally, so a signal can land anywhere -- the start-up sweep, a post-export
    # hook, a one-shot pass with no watch loop at all -- not only in the watch block that
    # used to be the sole `except`. Without this, SIGTERM outside the watch loop surfaced
    # as an uncaught traceback and a signal exit status instead of a clean stop.
    try:
        _run(logger)
    except KeyboardInterrupt:
        pass

    logger.info("Traefik Certificate Exporter stopping....")


def _run(logger) -> None:
    """Everything `main()` does once logging and the signal handlers are in place.

    Separated so the interrupt boundary is a single `try` in `main()` rather than one
    `except` per phase.
    """
    globalSettingsMgr.loadFromFile(
        fileName=globalArgs.configfile, cmdLineArgs=globalArgs
    )
    settings = globalSettingsMgr.settings

    logger.info(f"Traefik Certificate Exporter v{__version__} starting....")

    ###########################################################################################################

    # Lets validate the path we are being asked to watch actually exists
    require_existing_path(logger, settings.dataPath, "Data Path")

    logger.info(f"Data Path: {settings.dataPath}")
    logger.info(f"File Spec: {settings.fileSpec}")
    logger.info(f"Output Path: {settings.outputPath}")

    dockerManager = DockerManager(settings=settings)
    # Every exit path below -- a normal return, an exception, an interrupt -- cancels the
    # pending deferred restarts. Nothing is lost by it: the next pass restarts those
    # containers by the same rule, because their files are still newer than their start
    # (ADR-0045).
    try:
        _run_passes(logger, settings, dockerManager)
    finally:
        dockerManager.cancel()


def _run_passes(logger, settings, dockerManager: DockerManager) -> None:
    """The start-up pass and the watch loop, after the `DockerManager` exists."""
    if not settings.runAtStart and not settings.watchForChanges:
        # Neither a start-up pass nor a watcher: say so instead of exiting silently. In the
        # container this ends a run-once start with exit 0 (ADR-0044).
        logger.warning("neither runatstart nor watchforchanges is set; nothing to do")
        return

    exporter = AcmeCertificateExporter(settings=settings)
    if settings.restartContainers:
        # One reachability check up front: an unreachable Engine is reported once, by
        # endpoint, and exporting carries on -- it has value even when restarts cannot happen.
        dockerManager.check()

    if settings.runAtStart:
        # The start-up sweep is a pass like any other, so it gets its own id: every line
        # it emits -- export, hook, notification -- joins on the same value.
        startupCorrelationId = new_correlation_id()
        token = set_correlation_id(startupCorrelationId)
        try:
            logger.info("Exporting certificates....")
            domainsChanged = exporter.exportCertificates() or []
            # Only for the domains whose artifacts changed; a start over an unchanged
            # store runs neither (ADR-0045, amending ADR-0014 §7).
            if domainsChanged:
                run_post_export_command(
                    settings.postExportCommand,
                    domainsChanged,
                    settings.dryRun,
                    correlationId=startupCorrelationId,
                )
                # Scope: the union of every acme file, once per process start. The watch
                # path notifies per file instead; see the note at that call site.
                send_export_notifications(
                    settings.appriseUrls,
                    domainsChanged,
                    settings.dryRun,
                    correlationId=startupCorrelationId,
                )
            else:
                logger.info(NO_CHANGE_MESSAGE)
            if settings.restartContainers:
                # Every pass, whether or not a domain changed: the rule compares the
                # exported files with each container's start, so an unchanged store
                # restarts nothing and a restart lost to a crash is recovered (ADR-0045).
                dockerManager.restartLabeledContainers(exporter.artifactMtime)
        finally:
            reset_correlation_id(token)

    if settings.watchForChanges:
        observer = watchdog.observers.Observer()
        event_handler = None
        observerStarted = False

        # The try opens BEFORE the handler and observer are built, not just around the
        # sleep loop. A signal is delivered whenever it arrives, and an operator who stops
        # the container during start-up is entitled to the same clean exit as one who
        # stops it an hour later -- not a traceback and a non-zero status.
        try:
            logger.info("Watching for changes to files....")
            event_handler = AcmeCertificateFileHandler(
                exporter=exporter, dockerManager=dockerManager, settings=settings
            )

            observer.schedule(event_handler, path=settings.dataPath, recursive=False)
            observer.start()
            observerStarted = True

            while True:
                time.sleep(settings.watchInterval)
        except KeyboardInterrupt:
            observer.stop()
            # Not `event_handler.timer.cancel()`: the timer is `None` until the first
            # watched-file event ever fires, and "start, then Ctrl-C" is the common path.
            # The guard lives in the handler, which owns the invariant (ADR-0026).
            if event_handler is not None:
                event_handler.cancel()

        if observerStarted:
            # `Thread.join` on a thread that was never started raises, and shutdown
            # during start-up is now a reachable path.
            observer.join()


if __name__ == "__main__":
    main()
