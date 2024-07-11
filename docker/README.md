# Overview

[![Github Tags](https://img.shields.io/github/v/tag/ravensorb/traefik-certificate-exporter?logo=github&logoColor=white)](https://github.com/ravensorb/traefik-certificate-exporter) [![Docker Pulls](https://img.shields.io/docker/pulls/ravensorb/traefik-certificate-exporter?logo=docker&logoColor=white)](https://hub.docker.com/r/ravensorb/traefik-certificate-exporter)

This tool can be used to extract acme certificates (ex: lets encrypt) from traefik json files. The tool is design to watch for changes to a folder for any files that match a filespec (defaults to *.json however can be set to a specific file name) and when changes are detected it will process the file and extract any certificates that are in it to the specified output path

## Docker

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
      # - TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS.RESTARTCONTAINER=false          # Indicates of the containers should be restarted after the export
      # - TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_DRYRUN=false                    # Set this to show what wil le exported (files will not actually be created)
      # - TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_RUNATSTART=true                 # Set this to run the export immediately on startup
      - TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_RESOLVERINPATHNAME=true           # Include the resolver name in the path when exporting
      - TRAEFIK_CERTIFICATE_EXPORTER_LOGGINGLEVEL=INFO                          # Logging level 
      # - TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_INCLUDE_DOMAINS=                # comma separated list of domain names to only export
      # - TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_EXCLUDE_DOMAINS=               # comma separated list of domain names to exclude from exporting
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
