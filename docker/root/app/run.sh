#!/usr/bin/with-contenv bash

if [ ! -f /config/settings.sample.json ]; then
    cp /app/settings.sample.json /config
fi

appParams="--data-path /data -o /certs --watch-for-changes"

if [ ! -z ${CONFIG_FILE+x} ]; then 
    appParams+=" --config-file ${CONFIG_FILE}"
fi

if [ ! -z ${TRAEFIK_FILESPEC+x} ]; then 
    appParams+=" --file-spec ${TRAEFIK_FILESPEC}"
fi

if [ ! -z ${TRAEFIK_RESOLVERID+x} ]; then 
    appParams+=" --traefik-resolver-id ${TRAEFIK_RESOLVERID}"
fi

if [ ! -z ${TRAEFIK_RESOLVERID_INOUTPUTPATHNAME+x} ]; then
    appParams+=" --include-resolvername-in-outputpath"
fi

if [ ! -z ${DRYRUN+x} ]; then 
    appParams+=" --dry-run"
fi

if [ ! -z ${FLAT+x} ]; then 
    appParams+=" --flat"
fi

if [ ! -z ${RESTART_CONTAINERS+x} ]; then 
    appParams+=" --restart_container"
fi

if [ ! -z ${DOMAINS_INCLUDE+x} ]; then 
    appParams+=" --include-domains ${DOMAINS_INCLUDE}"
fi

if [ ! -z ${DOMAINS_EXCLUDE+x} ]; then 
    appParams+=" --exclude-domains ${DOMAINS_EXCLUDE}"
fi

if [ ! -z ${RUN_AT_START+x} ]; then
    appParams+=" --run-at-start"
fi

if [ ! -z ${TEST_VERSION+x} ]; then 
    echo "[DEBUG] Commandline Arguments: $appParams"
fi

#echo traefik-certificate-exporter $appParams
traefik-certificate-exporter $appParams