#!/usr/bin/env bash

# Always run from the repo root, regardless of the caller's cwd -- act's checkout scope
# follows its working directory, and the build needs pyproject.toml/poetry.lock/src/ at
# the root (build-container.yaml's Docker context is the repo root, not docker/).
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)" || exit 1

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
#
# -P ubuntu-24.04=... is required: act ships no default image mapping for that runner
# label (only older ubuntu-latest/-22.04/-20.04 are pre-mapped), so build-container.yaml's
# `runs-on: ubuntu-24.04` job is silently skipped ("Skipping unsupported platform")
# without it.
act \
    --env-file .pipeline.env.traefik-certificate-exporter \
    --env GITHUB_TAG=${GITHUB_TAG#v} \
    -P ubuntu-24.04=catthehacker/ubuntu:act-latest \
    -a ${EVENT_NAME} \
    | tee act-build-traefik-certificate-exporter.log
