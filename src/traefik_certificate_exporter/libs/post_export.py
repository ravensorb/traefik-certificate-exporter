import os
import shlex
import subprocess

from .logging_utils import (
    get_correlation_id,
    globalLogger,
    reset_correlation_id,
    sanitize_for_log,
    set_correlation_id,
)

POST_EXPORT_COMMAND_TIMEOUT_SECONDS = 30

# A failing hook's stderr is untrusted: tools echo their arguments (a `?token=` URL) and can
# emit CR/LF/ESC. Only its last non-empty line is logged, with every argument of at least
# `HOOK_ARG_MASK_MIN_LENGTH` characters masked, control characters stripped, and cut to
# this many characters (ADV-3). Shorter arguments (`-c`, `-H`) are not masked: masking them
# would mangle ordinary words without hiding anything secret.
HOOK_STDERR_LOG_LIMIT = 200
HOOK_ARG_MASK_MIN_LENGTH = 4
HOOK_ARG_MASK = "***"

# Set for the hook's process only; `legacy_settings.valid_env_names()` reads them from here.
EXPORTED_DOMAINS_ENV = "TRAEFIK_CERTIFICATE_EXPORTER_EXPORTED_DOMAINS"
CORRELATION_ID_ENV = "TRAEFIK_CERTIFICATE_EXPORTER_CORRELATION_ID"


def run_post_export_command(
    command: str | None,
    domains: list,
    dryRun: bool,
    correlationId: str | None = None,
) -> None:
    """Run the configured post-export hook, if any, after a pass that changed something.

    Both call sites call this only when at least one domain's exported artifacts changed
    in the pass, and pass exactly those domains (ADR-0045, amending ADR-0014 §7).

    `domains` (the changed domain names) is exposed to the command as
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

    # The command is a declared secret (ADR-0045): it often carries a credential
    # (`curl -H "Authorization: …"`), so no line below logs it or its arguments -- only
    # the program, `argv[0]`. Not even the parser's message, which can echo a fragment.
    try:
        argv = shlex.split(command)
    except ValueError:
        logger.error("Post-export command could not be parsed; check its quoting")
        return

    if not argv:
        return
    program = argv[0]

    env = os.environ.copy()
    env[EXPORTED_DOMAINS_ENV] = ",".join(domains or [])
    # The hook's own output can be joined to this pass's log lines. Safe to export: a
    # UUID4 carries nothing derived from a domain, a path, or a secret.
    env[CORRELATION_ID_ENV] = get_correlation_id()

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
                f"Post-export command {program} exited {result.returncode}: "
                f"{_stderr_summary(result.stderr, argv[1:])}"
            )
        else:
            logger.debug(f"Post-export command {program} completed successfully")
    except subprocess.TimeoutExpired:
        logger.error(
            f"Post-export command {program} timed out after "
            f"{POST_EXPORT_COMMAND_TIMEOUT_SECONDS}s and was killed"
        )
    except OSError as e:
        logger.error(f"Post-export command {program} failed to start: {e}")


def _stderr_summary(stderr: str | None, arguments: list[str]) -> str:
    """The last non-empty line of a failing hook's stderr, safe to log (ADV-3).

    Every argument of at least `HOOK_ARG_MASK_MIN_LENGTH` characters is replaced by
    `HOOK_ARG_MASK` (longest first, so an argument containing another is masked whole),
    CR/LF/ESC are stripped, and the result is cut to `HOOK_STDERR_LOG_LIMIT` characters.
    Not redacted beyond that: a secret the hook derives or prints in another form than the
    argument it was given is not recognised.
    """
    text = stderr or ""
    for argument in sorted(set(arguments), key=len, reverse=True):
        if len(argument) >= HOOK_ARG_MASK_MIN_LENGTH:
            text = text.replace(argument, HOOK_ARG_MASK)
    lines = [line for line in text.splitlines() if line.strip()]
    last = sanitize_for_log(lines[-1].strip()) if lines else ""
    if len(last) > HOOK_STDERR_LOG_LIMIT:
        last = last[:HOOK_STDERR_LOG_LIMIT] + "…"
    return last
