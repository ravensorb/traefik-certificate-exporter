import os
import shlex
import subprocess

from .logging_utils import globalLogger

POST_EXPORT_COMMAND_TIMEOUT_SECONDS = 30


def run_post_export_command(command: str | None, domains: list, dryRun: bool) -> None:
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
