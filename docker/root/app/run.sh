#!/usr/bin/with-contenv bash

if [ ! -f /config/settings.sample.json ]; then
    cp /app/settings.sample.json /config
fi

appParams=""

if [ ! -z ${CONFIG_FILE+x} ]; then appParams+= " --config-file ${CONFIG_FILE}"
if [ ! -z ${TRAEFIK_FILESPEC+x} ]; then appParams+= " -file-spec ${TRAEFIK_FILESPEC:-*.json}"
if [ ! -z ${TRAEFIK_RESOLVERID+x} ]; then appParams+= " --traefik-resolver-id ${TRAEFIK_RESOLVERID:-}"
if [ ! -z ${DRYRUN+x} ]; then appParams+= " --dry-run"
if [ ! -z ${FLAT+x} ]; then appParams+= " --flat"
if [ ! -z ${RESTART_CONTAINERS+x} ]; then appParams+= " -restart_container"
if [ ! -z ${DOMAINS_INCLUDE+x} ]; then appParams+= " -id ${DOMAINS_INCLUDE}"
if [ ! -z ${DOMAINS_EXCLUDE+x} ]; then appParams+= " -id ${DOMAINS_EXCLUDE}"

traefik-certificate-exporter $appParams