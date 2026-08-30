#!/usr/bin/env bash

EVENT_NAME=${1:-push}
GITHUB_TAG=$(git describe --tags --abbrev=0)

echo "--------------------------------------------------------------------------------------"
echo "Building image (Triggering Event: $EVENT_NAME)"
echo "Version: $GITHUB_TAG"
echo "--------------------------------------------------------------------------------------"

echo "Building traefik-certificate-exporter"
# CI_CA_CERTIFICATE (only needed if a custom CA cert is required locally) is supplied via
# act's --secret-file, e.g. --secret-file .pipeline.secrets.traefik-certificate-exporter
# containing CI_CA_CERTIFICATE=<path-or-url-or-inline-pem> -- the workflow itself is
# runner-agnostic now (see build-container.yaml's "Install custom CA certificate" step) and
# no longer requires a bind-mounted certificate path specific to this machine.
act \
    --env-file .pipeline.env.traefik-certificate-exporter \
    --env GITHUB_TAG=${GITHUB_TAG#v} \
    -a ${EVENT_NAME} \
    | tee act-build-traefik-certificate-exporter.log
