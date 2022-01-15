# Overview

This tool can be used to extract acme certificates (ex: lets encrupt) from traefik json files. The tool is design to watch for changes to a folder for any files that match a filespec (defaults to *,json however can be set to a specific file name) and when changes are detected it will process the file and extract any certificates that are in it to the specified output path

## Docker
```
docker pull ravensorb/traefik-certificate-exporter:latest
```
or to run it
```bash
docker run -it ravensorb/traefik-certificate-exporter:latest -v /mnt/traefik-data/letsencrypt:/data -v /mnt/certs:/certs -e "TRAEFIK_RESOLVERID=resolver-http" -e "TRAEFIK_FILESPEC=acme-*.json"
```
or with docker-compose
```yaml
version: "3.7"

services:
  traefik-certificate-exporter:
    image: ravensorb/traefik-certificate-exporter:latest
    build:
      context: .
      args:
        - BUILD_DATE=2022/01/14
        - VERSION=0.0.1
        - TEST_VERSION=Yes
    environment:
      - CONFIG_FILE="/config/settings.json" # Define this to set the config file
      - TRAEFIK_FILESPEC="*.json"           # Define this to set the file space to watch for changes
      - TRAEFIK_RESOLVERID="resolver-http"  # Define this to set the resolver id to match against
      - DRYRUN=                             # Define this to indicate you want to do a dry run (don't actually export or restart)
      - FLAT=                               # Define this to export all certificates in a single flat folder
      - RESTART_CONTAINERS=                 # Define this to indicate if containers with label set should be restarted
      - DOMAINS_INCLUDE=                    # comma seperated list of domain names to only export
      - DOMAINS_EXCLUDE=                    # comma seperated list of domain names to exlude from exporting
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro  # Only needed if you are going to be restarting containers
      - ./data/config:/config:rw                      # Only needed if you are going to set a config file to load
      - ./data/letsencrypt:/data:ro                   # Location of your acme files
      - ./data/certs:/certs:rw                        # Location you want to export certificates to
```

# Credits
This tool is HEAVLY influenced by the excellent work of [DanielHuisman](https://github.com/DanielHuisman) and [Marc Brückner](https://github.com/SnowMB)