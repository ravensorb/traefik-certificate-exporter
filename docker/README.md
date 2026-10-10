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
docker run --rm --name traefik-certificate-exporter-smoke -d \
  -e TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_WATCHFORCHANGES=false \
  traefik-certificate-exporter:local
docker logs traefik-certificate-exporter-smoke
docker stop traefik-certificate-exporter-smoke
```

The direct entrypoint checks the installed CLI. The final commands start through LinuxServer/s6,
confirm packaged configuration initialization while the watcher is disabled, and stop the
temporary smoke container.

```bash
docker pull ravensorb/traefik-certificate-exporter:latest
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

- **A notification means "an export pass completed", not "a certificate changed."** This
  tool rewrites every certificate on every pass and does not compare them, and the image
  ships `RUNATSTART=true` — so a container restart, a redeploy, and any Traefik write to
  `acme.json` each send one, renewal or not.
- **Delivery is fire-and-forget.** A failed notification is logged and stops nothing. If
  you need something that *must* succeed, use `postexportcommand`, which blocks and
  reports a non-zero exit.

These URLs are credentials. They are redacted from every settings dump, including at
`--log-level DEBUG`.

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
      # - TRAEFIK_CERTIFICATE_EXPORTER_CONFIGFILE="/config/config.yaml"         # Config file to load for settings 
      # - TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_DATAPATH="/data"                # The base path to look for traefik certificate json files
      # - TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_FILESPEC="*.json"               # Default filespec to search for (can be set to a specific file)
      # - TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_OUTPUTPATH="/certs"             # The base path to export the certificates to
      # - TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_TRAEFIKRESOLVERID=              # Specify a specific resolver id to match against (optional)
      # - TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_FLAT=false                      # Indicates if certificates are exported in sub folders or a single folder
      # - TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_RESTARTCONTAINER=false          # Indicates of the containers should be restarted after the export
      # - TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_DRYRUN=false                    # Set this to show what wil le exported (files will not actually be created)
      # - TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_RUNATSTART=true                 # Set this to run the export immediately on startup
      - TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_RESOLVERINPATHNAME=true           # Include the resolver name in the path when exporting
      # - TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_PKCS12PASSPHRASE=              # Passphrase used to encrypt the exported PKCS12 (.pfx) file (default: unencrypted)
      # - TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_POSTEXPORTCOMMAND=             # Command run after a successful export pass (see below); receives exported domains via TRAEFIK_CERTIFICATE_EXPORTER_EXPORTED_DOMAINS
      - TRAEFIK_CERTIFICATE_EXPORTER_LOGGINGLEVEL=INFO                          # Logging level 
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
