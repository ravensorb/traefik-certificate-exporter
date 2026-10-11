# Overview

[![Github Tags](https://img.shields.io/github/v/tag/ravensorb/traefik-certificate-exporter?logo=github&logoColor=white)](https://github.com/ravensorb/traefik-certificate-exporter) [![Docker Pulls](https://img.shields.io/docker/pulls/ravensorb/traefik-certificate-exporter?logo=docker&logoColor=white)](https://hub.docker.com/r/ravensorb/traefik-certificate-exporter)

This tool can be used to extract acme certificates (ex: lets encrypt) from traefik json files. The tool is design to watch for changes to a folder for any files that match a filespec (defaults to *.json however can be set to a specific file name) and when changes are detected it will process the file and extract any certificates that are in it to the specified output path

## Docker

### Build the exact-wheel image locally

The supported local build starts at the repository root:

```bash
just image
```

This runs `just build` (exactly one wheel and one source distribution in `dist/`), then
`docker build` with `docker/Dockerfile`, target `runtime`, and loads the result as
`traefik-certificate-exporter:local`. It performs no registry login, push, or publication.
CI builds the image the same way, through `docker/build-push-action`, with the same build
arguments (AD-17):

| Build argument | Contract |
|---|---|
| `POETRY_VERSION` | The pinned builder Poetry version. |
| `WHEEL_PATH` | Repository-relative path to the one `.whl` in `dist/`. |
| `WHEEL_SHA256` | SHA-256 of that wheel as 64 lowercase hexadecimal characters. |
| `VERSION` | The wheel's version; PEP 440 (`1.4.1.dev3`) and SemVer (`1.4.1-dev.3`) spellings both match. |
| `REVISION` | Full lowercase source Git SHA. |

The Dockerfile installs runtime dependencies only from `pyproject.toml` and `poetry.lock`, verifies
the selected wheel hash, and installs it with `pip install --no-deps --no-index`. There is no
application package-index lookup or fallback: fetching a same-version package later could put bytes
in the image other than the artifact that was tested.

Inspect the locally loaded image and run both smoke paths with:

```bash
docker image inspect traefik-certificate-exporter:local \
  --format '{{ index .Config.Labels "org.opencontainers.image.version" }} {{ index .Config.Labels "org.opencontainers.image.revision" }}'
docker run --rm --entrypoint traefik-certificate-exporter \
  traefik-certificate-exporter:local --help
docker run --rm --name traefik-certificate-exporter-smoke \
  -e TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_WATCHFORCHANGES=false \
  traefik-certificate-exporter:local
echo "exit code: $?"
```

The direct entrypoint checks the installed CLI. The final command starts through LinuxServer/s6
in run-once mode: it initializes the packaged configuration, runs one export pass over the
image's empty `/data`, and the container exits on its own with code 0 (see
[Run once](#run-once)). The automated form of this check is
`TCE_DOCKER_INTEGRATION=1 poetry run pytest -m integration tests/test_container_run_once.py`.

```bash
docker pull ravensorb/traefik-certificate-exporter:latest
```

### Run once

With `-e TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_WATCHFORCHANGES=false` (or any YAML false
spelling, such as `no` or `False`) the container runs one export pass and then **exits**. The
mode is resolved once at start-up by the installed package, with the same precedence the
exporter uses, so the service and the exporter cannot disagree about it.

Use the environment variable, not the config file, to select run-once in the image: the image
sets `TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_WATCHFORCHANGES=true` as an environment default, and
environment variables outrank `/config/config.yaml`, so `watchforchanges: false` in the file
alone leaves the container in watch mode.

- **Exit code: start-up failures only.** The container exits 0 after the pass, or 1 when the
  data path is missing. Export failures are logged at ERROR and do **not** change the exit
  code, so a scheduler cannot detect a failed export from it — read the logs.
- **Use `restart: "no"`** (the `docker run` default), or start the container from cron, a
  systemd timer or a Kubernetes Job. With `restart: always` or `unless-stopped`, Docker
  restarts the exited container, which turns run-once into a container-level loop that
  repeats every export, hook and notification.
- If `runatstart` is also false there is nothing to do: the exporter logs one WARNING saying so
  and the container exits 0.

```bash
docker run --rm \
  -e TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_WATCHFORCHANGES=false \
  -v /path/to/traefik/acme:/data:ro \
  -v /path/to/certs:/certs \
  ravensorb/traefik-certificate-exporter:latest
```

### Which user does the exporter run as?

The exporter runs as the unprivileged `PUID`/`PGID` account (`abc`) only when the container can
prove at start-up that this account can read every ACME store file and write the output path,
and `settings.restartcontainers` is off. Otherwise it runs as root and logs one WARNING saying
why. Traefik writes `acme.json` mode `0600` owned by the user it runs as, so with a stock
(root) Traefik the exporter runs as root; to run it unprivileged, run Traefik as a non-root
user and set `PUID`/`PGID` to that user's uid/gid. Unprivileged mode requires `/data` mounted
read-only (`:ro`). See "Container privileges" in
[docs/operational.md](../docs/operational.md) for the full decision table.

### docker run (using env vars)

Then to run it via docker.  This will only watch json file that start with "acme" and container the resolver name "resolver-http"

```bash
docker run -it ravensorb/traefik-certificate-exporter:latest \
                -v /mnt/traefik-data/letsencrypt:/data:ro \
                -v /mnt/certs:/certs \
                -e "TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_TRAEFIKRESOLVERID=resolver-http" \
                -e "TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_FILESPEC=acme-*.json" 
```

### Export notifications (Apprise)

Set `appriseurls` in the config file to be notified when an export pass completes:

```yaml
settings:
  appriseurls:
    - "tgram://<bot-token>/<chat-id>"
    - "mailto://user:pass@example.com"
    - "json://my-service.internal/hook"      # generic webhook
```

Any [Apprise](https://github.com/caronc/apprise) URL works — email, Slack, Discord, ntfy,
Gotify, Telegram, Matrix and around a hundred others.

From the environment, use **indexed keys** rather than a comma-separated list — a comma is
legal inside an Apprise URL and splitting on it would corrupt the destination:

```yaml
- TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_APPRISEURLS_0=tgram://<bot-token>/<chat-id>
- TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_APPRISEURLS_1=mailto://user:pass@example.com
```

Two things worth knowing before you rely on it:

- **A notification means "a certificate changed": it is sent only on change.** A pass
  notifies, and runs `postexportcommand`, only when at least one domain's exported files
  changed, and lists only those domains. A container restart or redeploy over an unchanged
  store (the image ships `RUNATSTART=true`) sends nothing, and logs
  `No certificate changed; no hook or notification` instead
  ([ADR-0045](../docs/adr/0045-restart-policy-only-on-change-defer-not-drop.md)). In 0.2.x
  every pass sent one.
- **Delivery is fire-and-forget.** A failed notification is logged and stops nothing. If
  you need something that *must* succeed, use `postexportcommand`, which blocks and
  reports a non-zero exit.

These URLs are credentials. They are redacted from every settings dump, including at
DEBUG (`TRAEFIK_CERTIFICATE_EXPORTER_LOGGING_LEVEL=DEBUG` in the container, `-ll DEBUG` on
the CLI).

### docker run (using config file)

This will run the container and maps the local ./data/config into the container.  This folder should contain the config.yml file that the application will use.

```bash
docker run -it ravensorb/traefik-certificate-exporter:latest \
                -v ${PWD}/data/config:/config \
                -v /mnt/traefik-data/letsencrypt:/data:ro
```

### docker-compose (using env vars)

```bash
docker compose up -d 
```

```yaml
services:
  traefik-certificate-exporter:
    image: ravensorb/traefik-certificate-exporter:latest
    environment:      
      # - TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_DATAPATH="/data"                # The base path to look for traefik certificate json files
      # - TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_FILESPEC="*.json"               # Default filespec to search for (can be set to a specific file)
      # - TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_OUTPUTPATH="/certs"             # The base path to export the certificates to
      # - TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_TRAEFIKRESOLVERID=              # Specify a specific resolver id to match against (optional)
      # - TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_FLAT=false                      # Indicates if certificates are exported in sub folders or a single folder
      # - TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_RESTARTCONTAINERS=false         # Indicates of the containers should be restarted after the export
      # - TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_DRYRUN=false                    # Set this to show what wil le exported (files will not actually be created)
      # - TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_RUNATSTART=true                 # Set this to run the export immediately on startup
      - TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_RESOLVERINPATHNAME=true           # Include the resolver name in the path when exporting
      # - TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_PKCS12PASSPHRASE=              # Passphrase used to encrypt the exported PKCS12 (.pfx) file (default: unencrypted)
      # - TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_POSTEXPORTCOMMAND=             # Command run after a successful export pass (see below); receives exported domains via TRAEFIK_CERTIFICATE_EXPORTER_EXPORTED_DOMAINS
      - TRAEFIK_CERTIFICATE_EXPORTER_LOGGING_LEVEL=INFO                         # Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL; the container cannot take -ll)
      # - TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_DOMAINS_INCLUDE=                # comma separated list of domain names to only export (mutually exclusive with DOMAINS_EXCLUDE)
      # - TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_DOMAINS_EXCLUDE=                # comma separated list of domain names to exclude from exporting (mutually exclusive with DOMAINS_INCLUDE)
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro  # Only needed if restarting containers. WARNING: `ro` does NOT limit API calls over the socket -- any mount (ro or rw) grants host-root-equivalent control. Prefer a restart-only socket proxy (e.g. Tecnativa/docker-socket-proxy) in production.
      - ./data/config:/config:rw                      # Only needed if you are going to set a config file to load
      - ./data/letsencrypt:/data:ro                   # Location of your acme files. Keep `:ro` -- required for the unprivileged
                                                      # (PUID/PGID) mode, which also needs the files readable by PUID/PGID; Traefik keeps them 0600
      - ./data/certs:/certs:rw                        # Location you want to export certificates to      
```

### docker-compose (using config file)

This will start the container and look in the ./data/config path that is mapped to /config for the configuration file

```bash
docker compose up -d 
```

```yaml
services:
  traefik-certificate-exporter:
    image: ravensorb/traefik-certificate-exporter:latest
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro  # Only needed if restarting containers. WARNING: `ro` does NOT limit API calls over the socket -- any mount (ro or rw) grants host-root-equivalent control. Prefer a restart-only socket proxy (e.g. Tecnativa/docker-socket-proxy) in production.
      - ./data/config:/config:rw                      # Only needed if you are going to set a config file to load
      - ./data/letsencrypt:/data:ro                   # Location of your acme files. Keep `:ro` -- required for the unprivileged
                                                      # (PUID/PGID) mode, which also needs the files readable by PUID/PGID; Traefik keeps them 0600
      - ./data/certs:/certs:rw                        # Location you want to export certificates to      
```

## Credits

This tool is HEAVILY influenced by the excellent work of [DanielHuisman](https://github.com/DanielHuisman) and [Marc Brückner](https://github.com/SnowMB)
