# Overview

[![Github Tags](https://img.shields.io/github/v/tag/ravensorb/traefik-certificate-exporter?logo=github&logoColor=white)](https://github.com/ravensorb/traefik-certificate-exporter) [![Docker Pulls](https://img.shields.io/docker/pulls/ravensorb/traefik-certificate-exporter?logo=docker&logoColor=white)](https://hub.docker.com/r/ravensorb/traefik-certificate-exporter)

This tool can be used to extract acme certificates (ex: lets encrypt) from traefik json files. The tool is design to watch for changes to a folder for any files that match a filespec (defaults to *.json however can be set to a specific file name) and when changes are detected it will process the file and extract any certificates that are in it to the specified output path

## Docker

### Build the exact-wheel image locally

The supported local build starts at the repository root and uses the same declarative Bake target
that CI consumes:

```bash
just image
```

This runs local checks, creates exactly one wheel and one source distribution in `dist/`, validates
both distributions, and locally loads `traefik-certificate-exporter:local`. It performs no registry
login, push, or publication.

Container contributors can invoke Bake directly after `just build`. The following dynamic inputs
are required and must describe the exact wheel being installed:

| Input | Contract |
|---|---|
| `WHEEL_PATH` | Repository-relative path or glob selecting exactly one `.whl` file. |
| `WHEEL_SHA256` | SHA-256 of that wheel as 64 lowercase hexadecimal characters. |
| `VERSION` | Package version in the wheel metadata. |
| `REVISION` | Full lowercase source Git SHA. |

For example:

```bash
mapfile -d '' -t wheels < <(find dist -maxdepth 1 -type f -name '*.whl' -print0)
if (( ${#wheels[@]} != 1 )); then
  echo >&2 "wheel contract: dist must contain exactly one wheel"
  exit 1
fi
wheel="${wheels[0]}"
WHEEL_PATH="$wheel" \
WHEEL_SHA256="$(poetry run python -c 'import hashlib, pathlib, sys; print(hashlib.sha256(pathlib.Path(sys.argv[1]).read_bytes()).hexdigest())' "$wheel")" \
VERSION="$(poetry run python -c 'import sys, zipfile; archive = zipfile.ZipFile(sys.argv[1]); metadata = archive.read(next(name for name in archive.namelist() if name.endswith(".dist-info/METADATA"))).decode(); print(next(line.removeprefix("Version: ") for line in metadata.splitlines() if line.startswith("Version: ")))' "$wheel")" \
REVISION="$(git rev-parse HEAD)" \
docker buildx bake image
```

`docker-bake.hcl` also accepts `LABELS` (map), `TAGS`, `PLATFORMS`, `OUTPUTS`, and
`ATTESTATIONS` (lists) as explicit environment overrides. Use CSV for simple list values or append
`_JSON` to the variable name for JSON values, such as `PLATFORMS_JSON='["linux/amd64",
"linux/arm64"]'`. Its local defaults select the native platform, load the image into Docker, apply
the local tag, and emit no attestations. CI can override those values without copying the Docker
context, Dockerfile, target, pinned base, pinned Poetry version, or build-argument mapping into a
second build command.

The default `OUTPUTS=["type=docker"]` is a single-platform local-load exporter. A multi-platform
`PLATFORMS` override must also select a compatible output, for example:

```bash
PLATFORMS_JSON='["linux/amd64","linux/arm64"]' \
OUTPUTS_JSON='["type=oci,dest=dist/traefik-certificate-exporter.oci.tar"]' \
docker buildx bake image
```

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

### docker run (using env vars)

Then to run it via docker.  This will only watch json file that start with "acme" and container the resolver name "resolver-http"

```bash
docker run -it ravensorb/traefik-certificate-exporter:latest \
                -v /mnt/traefik-data/letsencrypt:/data \
                -v /mnt/certs:/certs \
                -e "TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_TRAEFIKRESOLVERID=resolver-http" \
                -e "TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_FILESPEC=acme-*.json" 
```

### docker run (using config file)

This will run the container and maps the local ./data/config into the container.  This folder should contain the config.yml file that the application will use.

```bash
docker run -it ravensorb/traefik-certificate-exporter:latest \
                -v ${PWD}/data/config:/config \
                -v /mnt/traefik-data/letsencrypt:/data 
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
      - /var/run/docker.sock:/var/run/docker.sock:ro  # Only needed if you are going to be restarting containers
      - ./data/config:/config:rw                      # Only needed if you are going to set a config file to load
      - ./data/letsencrypt:/data:ro                   # Location of your acme files
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
      - /var/run/docker.sock:/var/run/docker.sock:ro  # Only needed if you are going to be restarting containers
      - ./data/config:/config:rw                      # Only needed if you are going to set a config file to load
      - ./data/letsencrypt:/data:ro                   # Location of your acme files
      - ./data/certs:/certs:rw                        # Location you want to export certificates to      
```

## Credits

This tool is HEAVILY influenced by the excellent work of [DanielHuisman](https://github.com/DanielHuisman) and [Marc Brückner](https://github.com/SnowMB)
