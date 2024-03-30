#!/usr/bin/env bash

EVENT_NAME={$1:-push}

echo "--------------------------------------------------------------------------------------"
echo "Building images (Triggering Event: $EVENT_NAME)"
echo "--------------------------------------------------------------------------------------"

echo "Building traefik-certificate-exporter"
act \
    --env-file .pipeline.env.traefik-certificate-exporter ${ACT_BUILD_OPTIONS_EXTRA} \
    -a ${EVENT_NAME} \
    | tee act-build-traefik-certificate-exporter.log