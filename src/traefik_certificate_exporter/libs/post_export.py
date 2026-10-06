import os
import shlex
import subprocess

from .logging_utils import (
    get_correlation_id,
    globalLogger,
    reset_correlation_id,
    set_correlation_id,
)

POST_EXPORT_COMMAND_TIMEOUT_SECONDS = 30


def run_post_export_command(
    command: str | None,
    domains: list,
    dryRun: bool,
    correlationId: str | None = None,
) -> None:
    """Run the configured post-export hook, if any, after a completed export pass.

    `domains` (the just-processed domain names) is exposed to the command as
    TRAEFIK_CERTIFICATE_EXPORTER_EXPORTED_DOMAINS, comma-separated, matching this
    project's existing env-var naming/list convention. Runs via subprocess.run in list
    form (shell=False) -- shlex.split honors quoting so an argument can still contain a
    space, without ever invoking a shell.
    """
    logger = globalLogger

    if not command:
        return

    # The caller normally has the id already bound on this thread; the parameter is for
    # the hop that does not (a future call site reached from another thread). Neither
    # being present is not an error -- the line is logged without a join key rather than
    # the pass failing over its own observability.
    token = set_correlation_id(correlationId or get_correlation_id())
    try:
        _run(logger, command, domains, dryRun)
    finally:
        reset_correlation_id(token)


def _run(logger, command: str, domains: list, dryRun: bool) -> None:

    if dryRun:
        logger.info("Dry run: skipping post-export command")
        return

    try:
        argv = shlex.split(command)
    except ValueError as e:
        logger.error(f"Post-export command could not be parsed: {e}")
        return

    if not argv:
        return

    env = os.environ.copy()
    env["TRAEFIK_CERTIFICATE_EXPORTER_EXPORTED_DOMAINS"] = ",".join(domains or [])
    # The hook's own output can be joined to this pass's log lines. Safe to export: a
    # UUID4 carries nothing derived from a domain, a path, or a secret.
    env["TRAEFIK_CERTIFICATE_EXPORTER_CORRELATION_ID"] = get_correlation_id()

    try:
        result = subprocess.run(
            argv,
            shell=False,
            check=False,
            env=env,
            timeout=POST_EXPORT_COMMAND_TIMEOUT_SECONDS,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            logger.error(
                f"Post-export command '{command}' exited {result.returncode}: "
                f"{result.stderr.strip()}"
            )
        else:
            logger.debug(f"Post-export command '{command}' completed successfully")
    except subprocess.TimeoutExpired:
        logger.error(
            f"Post-export command '{command}' timed out after "
            f"{POST_EXPORT_COMMAND_TIMEOUT_SECONDS}s and was killed"
        )
    except OSError as e:
        logger.error(f"Post-export command '{command}' failed to start: {e}")
