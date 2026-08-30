#!/usr/bin/env python3
###################################################################################################

import argparse

from .docker import DOCKER_LABEL

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
    help="the path to watch for changes (default: %(default)s)",
)
globalArgParser.add_argument(
    "-d",
    "--data-path",
    dest="settings.datapath",
    default=None,
    type=str,
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
    help="file that contains the traefik certificates",
)
globalArgParser.add_argument(
    "-o",
    "--output-path",
    dest="settings.outputpath",
    default=None,
    type=str,
    help="The folder to exports the certificates in to",
)
globalArgParser.add_argument(
    "--traefik-resolver-id",
    dest="settings.traefikresolverid",
    default=None,
    type=str,
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
    dest="settings.restartcontainer",
    default=None,
    help="If specified, any container that are labeled with '"
    + DOCKER_LABEL
    + "=<DOMAIN>' will be restarted if the domain name of a generated certificates matches the value of the label. Multiple domains can be separated by ','",
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
    help="Passphrase used to encrypt the exported PKCS12 (.pfx) file (default: unencrypted).",
)
globalArgParser.add_argument(
    "--post-export-command",
    dest="settings.postexportcommand",
    default=None,
    type=str,
    help="Shell-like command line to run after a successful export pass (no shell "
    "involved -- parsed with shlex, run via subprocess with a fixed 30s timeout). The "
    "just-exported domain names are exposed to it as a comma-separated "
    "TRAEFIK_CERTIFICATE_EXPORTER_EXPORTED_DOMAINS environment variable. Skipped "
    "entirely when --dry-run is set.",
)

globalArgParser.add_argument(
    "-ll",
    "--log-level",
    choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
    dest="logginglevel",
    default="INFO",
    help="Set the logging level (default: %(default)s)",
)

group = globalArgParser.add_mutually_exclusive_group()
group.add_argument(
    "-id",
    "--include-domains",
    nargs="*",
    dest="settings.domains.include",
    help="If specified, only certificates that match domains in this list will be extracted",
)
group.add_argument(
    "-xd",
    "--exclude-domains",
    nargs="*",
    dest="settings.domains.exclude",
    help="If specified. certificates that match domains in this list will be ignored",
)

###################################################################################################

# parse_known_args (not parse_args) so importing this module never crashes on an
# unrecognized flag belonging to the host process (pytest, a REPL, etc.) — the console
# script entry point only ever sees its own argv in production, so behavior there is
# unchanged.
globalArgs, _ = globalArgParser.parse_known_args()

# import jsonpickle
# print(jsonpickle.dumps(globalArgs))
