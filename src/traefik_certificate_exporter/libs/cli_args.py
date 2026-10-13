###################################################################################################

import argparse

from . import suggest
from .docker import DOCKER_LABEL
from .logging_utils import DEFAULT_LOG_LEVEL, LOG_LEVEL_CHOICES, LOG_LEVEL_ENV

###################################################################################################

globalArgParser = argparse.ArgumentParser(
    description="Extract traefik letsencrypt certificates."
)

globalArgParser.add_argument(
    "-c",
    "--config-file",
    dest="configfile",
    default="config.yaml",
    type=str,
    metavar="PATH",
    help="the configuration file to load (default: %(default)s)",
)
globalArgParser.add_argument(
    "-d",
    "--data-path",
    dest="settings.datapath",
    default=None,
    type=str,
    metavar="PATH",
    help="the path that contains the acme json files",
)
globalArgParser.add_argument(
    "-w",
    "--watch-for-changes",
    action="store_const",
    const=True,
    default=None,
    dest="settings.watchforchanges",
    help="If specified, monitor and watch for changes to acme files",
)
globalArgParser.add_argument(
    "-fs",
    "--file-spec",
    dest="settings.filespec",
    default=None,
    type=str,
    metavar="GLOB",
    help=(
        "file-name glob of the ACME store inside the data path (no directory part); "
        "default `*.json`"
    ),
)
globalArgParser.add_argument(
    "-o",
    "--output-path",
    dest="settings.outputpath",
    default=None,
    type=str,
    metavar="PATH",
    help="The folder to exports the certificates in to",
)
globalArgParser.add_argument(
    "--traefik-resolver-id",
    dest="settings.traefikresolverid",
    default=None,
    type=str,
    metavar="RESOLVER",
    help="Traefik certificate-resolver-id.",
)
globalArgParser.add_argument(
    "--flat",
    action="store_const",
    const=True,
    dest="settings.flat",
    default=None,
    help="If specified, all certificates into a single folder",
)
globalArgParser.add_argument(
    "--restart-container",
    action="store_const",
    const=True,
    dest="settings.restartcontainers",
    default=None,
    help="If specified, any container that are labeled with '"
    + DOCKER_LABEL
    + "=<DOMAIN>' will be restarted, only on change: when an exported certificate file for one of its domains is newer than the container's start. Multiple domains can be separated by ','",
)
globalArgParser.add_argument(
    "--dry-run",
    action="store_const",
    const=True,
    dest="settings.dryrun",
    default=None,
    help="Don't write files and do not restart docker containers.",
)
globalArgParser.add_argument(
    "-r",
    "--run-at-start",
    action="store_const",
    const=True,
    dest="settings.runatstart",
    default=None,
    help="Runs Export immediately on start (used with watch-for-changes).",
)
globalArgParser.add_argument(
    "--include-resolvername-in-outputpath",
    action="store_const",
    const=True,
    dest="settings.resolverinpathname",
    default=None,
    help="Added the resolvername in the path used to export the certificates (ignored if flat is specified).",
)
globalArgParser.add_argument(
    "--pkcs12-passphrase",
    dest="settings.pkcs12passphrase",
    default=None,
    type=str,
    metavar="PASSPHRASE",
    help=(
        "Passphrase used to encrypt the exported PKCS12 (.pfx) file with AES-256/SHA-256 "
        "(readable by Windows 10 1709+/Server 2019+, OpenSSL 3, current macOS). The .pfx "
        "always includes the intermediates. Empty or unset: unencrypted."
    ),
)
globalArgParser.add_argument(
    "--no-validate-keys",
    action="store_const",
    const=False,
    dest="settings.validatekeys",
    default=None,
    help="If specified, skip RSA private-key validation when a .pfx is built "
    "(~0.5 s per RSA-4096 key). Only when the ACME store is written by your own "
    "Traefik: the keys are then trusted, not checked. The key/certificate match is "
    "always checked.",
)
globalArgParser.add_argument(
    "--post-export-command",
    dest="settings.postexportcommand",
    default=None,
    type=str,
    metavar="COMMAND",
    help="Shell-like command line to run after an export pass, only on change: when at "
    "least one domain's exported files changed (no shell involved -- parsed with shlex, "
    "run via subprocess with a fixed 30s timeout). The changed domain names are exposed "
    "to it as a comma-separated TRAEFIK_CERTIFICATE_EXPORTER_EXPORTED_DOMAINS "
    "environment variable. Treated as a secret: log lines name only its program. "
    "On failure only the last line of its stderr is logged, with its arguments masked; "
    "output it prints in any other form is not redacted. "
    "Skipped entirely when --dry-run is set.",
)

globalArgParser.add_argument(
    "-ll",
    "--log-level",
    choices=LOG_LEVEL_CHOICES,
    dest="logginglevel",
    metavar="LEVEL",
    # None, not "INFO", so `app.py` can tell "not given" apart and fall back to the env.
    default=None,
    help=(
        "Set the logging level, one of: %(choices)s. "
        f"When not given, {LOG_LEVEL_ENV} is used "
        f"(case-insensitive); otherwise the default is {DEFAULT_LOG_LEVEL}."
    ),
)

group = globalArgParser.add_mutually_exclusive_group()
group.add_argument(
    "-id",
    "--include-domains",
    nargs="*",
    dest="settings.domains.include",
    metavar="DOMAIN",
    help="If specified, only certificates that match domains in this list will be extracted",
)
group.add_argument(
    "-xd",
    "--exclude-domains",
    nargs="*",
    dest="settings.domains.exclude",
    metavar="DOMAIN",
    help="If specified. certificates that match domains in this list will be ignored",
)

###################################################################################################

# parse_known_args (not parse_args) so importing this module never crashes on an
# unrecognized flag belonging to the host process (pytest, a REPL, etc.) — the console
# script entry point only ever sees its own argv in production, so behavior there is
# unchanged.
globalArgs, _ = globalArgParser.parse_known_args()


HELP_POINTER = "Try '--help' for full usage."


def _unrecognized_arguments_message(leftover: list[str]) -> str:
    """argparse's own `unrecognized arguments:` line, plus a near-match per dash token
    and a `--help` pointer (BL-E011-034).

    Only a `-`-token gets a suggestion; a value that followed it (`/x` in
    `--dtaa-path /x`) and a stray positional are listed but never matched. `--flag=value`
    is matched on its flag part. The suggestion comes from `suggest.nearest_name`, the
    one helper the env-name suggestions also use (C-04) -- looked up on the module at
    call time, so both paths share a single definition.
    """
    options = [
        opt for action in globalArgParser._actions for opt in action.option_strings
    ]
    lines = [f"unrecognized arguments: {' '.join(leftover)}"]
    for token in leftover:
        if not token.startswith("-"):
            continue
        match = suggest.nearest_name(token.split("=", 1)[0], options)
        if match is not None:
            lines.append(f"Did you mean '{match}'?")
    lines.append(HELP_POINTER)
    return "\n".join(lines)


def parse_args_strict() -> argparse.Namespace:
    """Parse this process's argv strictly, failing on any unrecognized flag.

    The module-level `globalArgs` above deliberately tolerates foreign argv so that
    importing this module from pytest, a REPL or an embedding host can never raise.
    That leniency is wrong for a real invocation, where `--dtaa-path` is a typo and not
    somebody else's flag, so `main()` calls this instead: `parse_args()` exits 2 with a
    usage message naming the offending argument. Nothing here runs at import time --
    only when a caller asks for it (ADR-0025).

    `parse_known_args()` plus `error()` instead of `parse_args()`, so the message can
    carry a `Did you mean` line and a `--help` pointer. ANY leftover token is an error,
    dash or not: a stray positional (`... stray`) still exits 2 exactly as `parse_args()`
    did (BL-E014-002), it just gets no suggestion.
    """
    args, leftover = globalArgParser.parse_known_args()
    if leftover:
        globalArgParser.error(_unrecognized_arguments_message(leftover))
    return args
