# Overview

This tool can be used to extract acme certificates (ex: lets encrupt) from traefik json files. The tool is design to watch for changes to a folder for any files that match a filespec (defaults to *,json however can be set to a specific file name) and when changes are detected it will process the file and extract any certificates that are in it to the specified output path

# Installation

## Python Script/Tool
Installation can be done via the python package installer tool pip
```
$ pip install traefik-certificate-exporter
```

## Docker
```
docker pull ravensorb/traefik-certificate-exporter:latest
```

# Usage

```bash
usage: traefik-certificate-exporter [-h] [-wp WATCHPATH] [-fs FILEPATTERN] [--traefik-resolver-id TRAEFIKRESOLVERID] [-od OUTPUTPATH] [-f] [-r] [--dry-run] [-id [INCLUDEDOMAINS [INCLUDEDOMAINS ...]] | -xd
                                     [EXCLUDEDOMAINS [EXCLUDEDOMAINS ...]]]

Extract traefik letsencrypt certificates.

optional arguments:
  -h, --help            show this help message and exit
  -wp WATCHPATH, --watch-path WATCHPATH
                        the path to watch for changes (default: .)
  -fs FILEPATTERN, --file-spec FILEPATTERN
                        file that contains the traefik certificates (default: *.json)
  --traefik-resolver-id TRAEFIKRESOLVERID
                        Traefik certificate-resolver-id.
  -od OUTPUTPATH, --output-directory OUTPUTPATH
                        The folder to exports the certificates in to (default: ./certs)
  -f, --flat            If specified, all certificates into a single folder
  -r, --restart_container
                        If specified, any container that are labeled with 'com.github.ravensorb.traefik-certificate-exporter.domain-restart=<DOMAIN>' will be restarted if the domain name of a generated certificates matches the value
                        of the lable. Multiple domains can be seperated by ','
  --dry-run             Don't write files and do not restart docker containers.
  -id [INCLUDEDOMAINS [INCLUDEDOMAINS ...]], --include-domains [INCLUDEDOMAINS [INCLUDEDOMAINS ...]]
                        If specified, only certificates that match domains in this list will be extracted
  -xd [EXCLUDEDOMAINS [EXCLUDEDOMAINS ...]], --exclude-domains [EXCLUDEDOMAINS [EXCLUDEDOMAINS ...]]
                        If specified. certificates that match domains in this list will be ignored
```

## Examples
Watch the letsencrypt folder for any changes to files matching acme-*.json and export any certs managed by the resolver called "resolver-http"

## Script
```bash
traefik-certificate-exporter -wp /mnt/traefik-data/letsencrypt -od /mnt/certs -fs "acme-*.json" --traefik-resolver-id "resolver-http" 
```

## Docker
```bash
docker run -it ravensorb/traefik-certificate-exporter:latest -v /mnt/traefik-data/letsencrypt:/data -v /mnt/certs:/certs -e "TRAEFIK_RESOLVERID=resolver-http" -e "TRAEFIK_FILESPEC=acme-*.json"
```

# Credits
This tool is HEAVLY influenced by the excellent work of [DanielHuisman](https://github.com/DanielHuisman) and [Marc Brückner](https://github.com/SnowMB)