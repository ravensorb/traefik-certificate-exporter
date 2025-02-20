#!/usr/bin/env bash

EVENT_NAME=${1:-push}
GITHUB_TAG=$(git describe --tags --abbrev=0)

echo "--------------------------------------------------------------------------------------"
echo "Building image (Triggering Event: $EVENT_NAME)"
echo "Version: $GITHUB_TAG"
echo "--------------------------------------------------------------------------------------"

echo "Building traefik-certificate-exporter"
act \
    --env-file .pipeline.env.traefik-certificate-exporter \
    --env GITHUB_TAG=${GITHUB_TAG#v} \
    -a ${EVENT_NAME} \
    --container-options "-v /mnt/certificates-home/Ravenwolf/ca-ravenwolf.org/2020:/mnt/certificates/" \
    | tee act-build-traefik-certificate-exporter.log