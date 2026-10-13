# traefik-certificate-exporter

## Overview

[![Github Tags](https://img.shields.io/github/v/tag/ravensorb/traefik-certificate-exporter?logo=github&logoColor=white)](https://github.com/ravensorb/traefik-certificate-exporter) [![PyPi Version](https://img.shields.io/pypi/v/traefik-certificate-exporter?color=g&label=pypi%20package&logo=pypi&logoColor=white)](https://pypi.org/project/traefik-certificate-exporter/) [![Docker](https://badgen.net/badge/icon/docker?icon=docker&label)](https://hub.docker.com/r/ravensorb/traefik-certificate-exporter)

This tool can be used to extract acme certificates (ex: lets encrupt) from traefik json files. The tool is design to watch for changes to a folder for any files that match a filespec (defaults to *.json; a file name or glob, without a directory part) and when changes are detected it will process the file and extract any certificates that are in it to the specified output path

Supported stores: `acme.json` from any RFC 8555 CA (Let's Encrypt, ZeroSSL, Google Trust Services, step-ca, ...) written by Traefik v1.7, v2 or v3; the shape is detected from the file's keys, not the CA URL, and each resolver is exported independently.

## Installation

### Python Script/Tool

Installation can be done via the python package installer tool pip

```basah
pip install traefik-certificate-exporter
```

## Usage

```bash
usage: traefik-certificate-exporter [-h] [-c PATH] [-d PATH] [-w] [-fs GLOB] [-o PATH] [--traefik-resolver-id RESOLVER] [--flat] [--restart-container] [--dry-run] [-r] [--include-resolvername-in-outputpath]
                                    [--pkcs12-passphrase PASSPHRASE] [--no-validate-keys] [--post-export-command COMMAND] [-ll LEVEL] [-id [DOMAIN ...] | -xd [DOMAIN ...]]

Extract traefik letsencrypt certificates.

options:
  -h, --help            show this help message and exit
  -c PATH, --config-file PATH
                        the configuration file to load (default: config.yaml)
  -d PATH, --data-path PATH
                        the path that contains the acme json files
  -w, --watch-for-changes
                        If specified, monitor and watch for changes to acme files
  -fs GLOB, --file-spec GLOB
                        file-name glob of the ACME store inside the data path
                        (no directory part); default `*.json`
  -o PATH, --output-path PATH
                        The folder to exports the certificates in to
  --traefik-resolver-id RESOLVER
                        Traefik certificate-resolver-id.
  --flat                If specified, all certificates into a single folder
  --restart-container   If specified, any container that are labeled with 'com.github.ravensorb.traefik-certificate-exporter.domain-restart=<DOMAIN>' will be restarted, only on change: when an exported certificate file
                        for one of its domains is newer than the container's start. Multiple domains can be separated by ','
  --dry-run             Don't write files and do not restart docker containers.
  -r, --run-at-start    Runs Export immediately on start (used with watch-for-changes).
  --include-resolvername-in-outputpath
                        Added the resolvername in the path used to export the certificates (ignored if flat is specified).
  --pkcs12-passphrase PASSPHRASE
                        Passphrase used to encrypt the exported PKCS12 (.pfx) file with AES-256/SHA-256 (readable by Windows 10 1709+/Server 2019+, OpenSSL 3, current macOS). The .pfx always includes the intermediates.
                        Empty or unset: unencrypted.
  --no-validate-keys    If specified, skip RSA private-key validation when a .pfx is built (~0.5 s per RSA-4096 key). Only when the ACME store is written by your own Traefik: the keys are then trusted, not
                        checked. The key/certificate match is always checked.
  --post-export-command COMMAND
                        Shell-like command line to run after an export pass, only on change: when at least one domain's exported files changed (no shell involved -- parsed with shlex, run via subprocess with a fixed
                        30s timeout). The changed domain names are exposed to it as a comma-separated TRAEFIK_CERTIFICATE_EXPORTER_EXPORTED_DOMAINS environment variable. Treated as a secret: log lines name only its
                        program. Skipped entirely when --dry-run is set.
  -ll LEVEL, --log-level LEVEL
                        Set the logging level, one of: DEBUG, INFO, WARNING, ERROR, CRITICAL. When not given, TRAEFIK_CERTIFICATE_EXPORTER_LOGGING_LEVEL is used (case-insensitive); otherwise the default is INFO.
  -id [DOMAIN ...], --include-domains [DOMAIN ...]
                        If specified, only certificates that match domains in this list will be extracted
  -xd [DOMAIN ...], --exclude-domains [DOMAIN ...]
                        If specified. certificates that match domains in this list will be ignored
```

Settings come from four layers, and for every setting the order is
`CLI > env > config file > defaults`: a CLI flag beats a `TRAEFIK_CERTIFICATE_EXPORTER_*`
environment variable, which beats the config file, which beats the packaged default. In the
image this makes the environment the run-mode switch: the image sets
`TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_WATCHFORCHANGES=true`, so `watchforchanges: false` in
`/config/config.yaml` alone does not select run-once ([docker/README.md](docker/README.md#run-once)).

Argument parsing is strict: an unrecognised flag (or a stray positional argument) exits
immediately with **code 2**, naming the closest valid flag when there is one
(`Did you mean '--data-path'?`) and pointing at `--help`. This happens before logging is
configured, so nothing is written to the log file. If the container crash-loops
at start-up with no log output, check your `command:`/`args:` override for a typo and read
the container's stderr.

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
runs a shell-like command line after an export pass, **only on change**: when at least
one domain's exported files changed in that pass -- useful for copying/chowning/moving an
exported certificate into another service's expected location. A pass that changed
nothing (including an exporter restart over an unchanged store) runs no hook and logs
`No certificate changed; no hook or notification` once at INFO
([ADR-0045](docs/adr/0045-restart-policy-only-on-change-defer-not-drop.md)). It is unset
by default (purely additive; no behavior change if you don't set it).

- The command is parsed with Python's `shlex` and executed directly (never through a
  shell), so it is not vulnerable to shell injection, but it also doesn't support shell
  features like pipes, globs, or `$VAR` expansion.
- The changed domain names (only those) are exposed to it as a comma-separated
  `TRAEFIK_CERTIFICATE_EXPORTER_EXPORTED_DOMAINS` environment variable; it is never empty,
  because the hook does not run when nothing changed.
- The command is treated as a secret, because it often carries a credential (an
  `Authorization` header, a webhook token): it is redacted in the DEBUG settings dumps,
  and the hook's log lines name only the program (`argv[0]`), never its arguments. When
  the hook fails, only the last line of its stderr is logged, with its arguments masked
  and control characters stripped; it is not redacted beyond that, so keep credentials out
  of what it prints in any other form.
- The export pass's `TRAEFIK_CERTIFICATE_EXPORTER_CORRELATION_ID` is exposed too, so a
  hook that logs elsewhere can be joined to the exporter's own log lines for that pass.
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

## Logging and tracing an export pass

Each export pass (the start-up sweep, and each debounced pass the watcher runs) is tagged
with a `correlation_id` — a UUID4 shared by every log line that pass produces, from the
detected file change through the export, the post-export hook and the notification. Grep
one value to see the whole pass.

The rotating log file is JSON, so `correlation_id` is a field there already. Console output
is coloured human-readable text by default, with the id in brackets after the level; set
`TRAEFIK_CERTIFICATE_EXPORTER_LOGGING_CONSOLEJSON=true` to emit the console stream as JSON
instead (useful when `docker logs` is being shipped to a log aggregator). A `-` means the
line was emitted outside any export pass.

The log level is `-ll/--log-level`; when that is not given,
`TRAEFIK_CERTIFICATE_EXPORTER_LOGGING_LEVEL` (case-insensitive: `DEBUG`, `INFO`, `WARNING`,
`ERROR`, `CRITICAL`) is used, and otherwise `INFO`. The container's command line is fixed,
so the environment variable is how to change verbosity there
(`-e TRAEFIK_CERTIFICATE_EXPORTER_LOGGING_LEVEL=DEBUG`). An invalid value falls back to
`INFO` with one WARNING, and one INFO line at start-up names the effective level and its
source (`cli`, `env` or `default`).

See [docs/operational.md](docs/operational.md#tracing-one-export-pass-correlation_id).

## Releases and images

- **Versions come from git tags.** A release is a `vX.Y.Z` tag on `main`; the package
  and the image carry that version. Every push to `main` between releases publishes a
  dev build (`X.Y.Z.devN` for the package, `X.Y.Z-dev.N` and `dev` for the image).
- **Python package:** PyPI (releases), TestPyPI (dev builds) and the Gitea package index.
- **Image:** GitHub Container Registry, Docker Hub and the Gitea container registry,
  built for `amd64` and `arm64`. `latest` and `X.Y.Z` / `X.Y` follow releases (and `X`
  from 1.0.0 on; no bare `0` tag is written);
  `dev` follows `main`.
- A destination is enabled only when its `PUBLISH_*` token secret and every `PUBLISH_*`
  variable it needs are set, so a fork or a mirror publishes only where it has been
  configured to. A partly configured destination is skipped with one warning naming what
  is missing; an unconfigured one is silent. The Gitea package index and the Gitea
  container registry share `PUBLISH_GITEA_TOKEN` but can be enabled separately.
- **Where the publish secrets live.** One forge's run publishes a whole release. On GitHub
  the `PUBLISH_*` secrets live in the `dev` or `release` environment, never at repository
  level ([ADR-0039](docs/adr/0039-publish-credentials-in-forge-environments.md)). On Gitea
  they are repository-level secrets, present only when Gitea is the publishing forge, with
  the mitigations of CI spine AD-13: protected `main` and `v*` tags, project-scoped tokens,
  rotation after any untrusted push. The forge settings to apply are the checklist in
  [docs/ci/pipeline-walkthrough.md](docs/ci/pipeline-walkthrough.md#forge-settings-the-maintainer-applies).

How the pipeline works, and how to set it up: [docs/ci/pipeline-walkthrough.md](docs/ci/pipeline-walkthrough.md).

Upgrading from an earlier release (what changes in each version and what to do about it): [docs/upgrading.md](docs/upgrading.md).

## Credits

This tool is HEAVLY influenced by the excellent work of [DanielHuisman](https://github.com/DanielHuisman) and [Marc Brückner](https://github.com/SnowMB)

## Export notifications

Set `appriseurls` in your config file to be notified when a certificate changes — email,
chat, or a generic webhook, via [Apprise](https://github.com/caronc/apprise):

```yaml
settings:
  appriseurls:
    - "tgram://<bot-token>/<chat-id>"
    - "mailto://user:pass@example.com"
```

There is no command-line flag for this setting, matching `domains` — the other list-valued
setting — and from the environment it takes indexed keys
(`..._APPRISEURLS_0`, `..._APPRISEURLS_1`) rather than a comma-separated string, because a
comma is legal inside an Apprise URL.

A notification means **a certificate changed**: it is sent **only on change**, when at least
one domain's exported files changed in the pass, and it lists only those domains. Each built
file is compared with the one on disk and an unchanged file is not rewritten, so its
modification time stays stable
([ADR-0043](docs/adr/0043-export-commit-and-reporting-contract.md)). A pass that changed
nothing — an exporter restart over an unchanged store, or a pass that only recovers a lost
container restart — sends nothing
([ADR-0045](docs/adr/0045-restart-policy-only-on-change-defer-not-drop.md)). Delivery is
fire-and-forget — a failure is logged and stops nothing. For something that must succeed,
use `postexportcommand`, which blocks and reports its exit code.

See [docker/README.md](docker/README.md) for the container setup.
