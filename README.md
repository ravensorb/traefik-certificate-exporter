# traefik-certificate-exporter

## Overview

[![Github Tags](https://img.shields.io/github/v/tag/ravensorb/traefik-certificate-exporter?logo=github&logoColor=white)](https://github.com/ravensorb/traefik-certificate-exporter) [![PyPi Version](https://img.shields.io/pypi/v/traefik-certificate-exporter?color=g&label=pypi%20package&logo=pypi&logoColor=white)](https://pypi.org/project/traefik-certificate-exporter/) [![Docker](https://badgen.net/badge/icon/docker?icon=docker&label)](https://hub.docker.com/r/ravensorb/traefik-certificate-exporter)

This tool can be used to extract acme certificates (ex: lets encrupt) from traefik json files. The tool is design to watch for changes to a folder for any files that match a filespec (defaults to *,json however can be set to a specific file name) and when changes are detected it will process the file and extract any certificates that are in it to the specified output path

## Installation

### Python Script/Tool

Installation can be done via the python package installer tool pip

```basah
pip install traefik-certificate-exporter
```

## Usage

```bash
usage: traefik-certificate-exporter [-h] [-c CONFIGFILE] [-d SETTINGS.DATAPATH] [-w] [-fs SETTINGS.FILESPEC] [-o SETTINGS.OUTPUTPATH] [--traefik-resolver-id SETTINGS.TRAEFIKRESOLVERID] [--flat] [--restart-container]
                                    [--dry-run] [-r] [--include-resolvername-in-outputpath] [--pkcs12-passphrase SETTINGS.PKCS12PASSPHRASE] [--post-export-command SETTINGS.POSTEXPORTCOMMAND] [-ll {DEBUG,INFO,WARNING,ERROR,CRITICAL}] [-id [SETTINGS.DOMAINS.INCLUDE ...] | -xd [SETTINGS.DOMAINS.EXCLUDE ...]]

Extract traefik letsencrypt certificates.

options:
  -h, --help            show this help message and exit
  -c CONFIGFILE, --config-file CONFIGFILE
                        the path to watch for changes (default: config.yaml)
  -d SETTINGS.DATAPATH, --data-path SETTINGS.DATAPATH
                        the path that contains the acme json files
  -w, --watch-for-changes
                        If specified, monitor and watch for changes to acme files
  -fs SETTINGS.FILESPEC, --file-spec SETTINGS.FILESPEC
                        file that contains the traefik certificates
  -o SETTINGS.OUTPUTPATH, --output-path SETTINGS.OUTPUTPATH
                        The folder to exports the certificates in to
  --traefik-resolver-id SETTINGS.TRAEFIKRESOLVERID
                        Traefik certificate-resolver-id.
  --flat                If specified, all certificates into a single folder
  --restart-container   If specified, any container that are labeled with 'com.github.ravensorb.traefik-certificate-exporter.domain-restart=<DOMAIN>' will be restarted if the domain name of a generated certificates
                        matches the value of the lable. Multiple domains can be seperated by ','
  --dry-run             Don't write files and do not restart docker containers.
  -r, --run-at-start    Runs Export immediately on start (used with watch-for-changes).
  --include-resolvername-in-outputpath
                        Added the resolvername in the path used to export the certificates (ignored if flat is specified).
  --pkcs12-passphrase SETTINGS.PKCS12PASSPHRASE
                        Passphrase used to encrypt the exported PKCS12 (.pfx) file (default: unencrypted).
  --post-export-command SETTINGS.POSTEXPORTCOMMAND
                        Shell-like command line to run after a successful export pass (no shell involved -- parsed with shlex, run via subprocess with a fixed 30s
                        timeout). The just-exported domain names are exposed to it as a comma-separated TRAEFIK_CERTIFICATE_EXPORTER_EXPORTED_DOMAINS environment
                        variable. Skipped entirely when --dry-run is set.
  -ll {DEBUG,INFO,WARNING,ERROR,CRITICAL}, --log-level {DEBUG,INFO,WARNING,ERROR,CRITICAL}
                        Set the logging level (default: INFO)
  -id [SETTINGS.DOMAINS.INCLUDE ...], --include-domains [SETTINGS.DOMAINS.INCLUDE ...]
                        If specified, only certificates that match domains in this list will be extracted
  -xd [SETTINGS.DOMAINS.EXCLUDE ...], --exclude-domains [SETTINGS.DOMAINS.EXCLUDE ...]
                        If specified. certificates that match domains in this list will be ignored
```

## Examples

Watch the letsencrypt folder for any changes to files matching acme-*.json and export any certs managed by the resolver called "resolver-http"

### Script

Run it once and then exit

```bash
traefik-certificate-exporter \
                            -d /mnt/traefik-data/letsencrypt \
                            -o /mnt/certs \
                            -fs "acme-*.json" \
                            -r
```

Run it and watch for changes to the files

```bash
traefik-certificate-exporter \
                            -d /mnt/traefik-data/letsencrypt \
                            -o /mnt/certs \
                            -fs "acme-*.json" 
                            -w
```

## Post-Export Hook

`--post-export-command` (or `settings.postexportcommand` / `TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_POSTEXPORTCOMMAND`)
runs a shell-like command line after every successful export pass -- useful for
copying/chowning/moving an exported certificate into another service's expected
location. It is unset by default (purely additive; no behavior change if you don't set
it).

- The command is parsed with Python's `shlex` and executed directly (never through a
  shell), so it is not vulnerable to shell injection, but it also doesn't support shell
  features like pipes, globs, or `$VAR` expansion.
- The just-exported domain names are exposed to it as a comma-separated
  `TRAEFIK_CERTIFICATE_EXPORTER_EXPORTED_DOMAINS` environment variable (empty string if
  no domains were processed).
- A fixed 30 second timeout applies; a command that doesn't return in time is killed and
  the timeout is logged as an error.
- Skipped entirely when `--dry-run` is set, consistent with dry-run suppressing file
  writes and container restarts.
- A non-zero exit or timeout is logged as an error but never crashes the watch loop.

```bash
traefik-certificate-exporter \
                            -d /mnt/traefik-data/letsencrypt \
                            -o /mnt/certs \
                            -w \
                            --post-export-command "/usr/local/bin/notify-service.sh"
```

## Credits

This tool is HEAVLY influenced by the excellent work of [DanielHuisman](https://github.com/DanielHuisman) and [Marc Brückner](https://github.com/SnowMB)
