# Build stage: install the locked dependency set with Poetry, never a hand-maintained list
FROM ghcr.io/linuxserver/baseimage-alpine:3.24@sha256:e17494fc7ec17c64f1b502d52705aa99d7a1cd8ccf59bb7b36003db89d97d2c6 AS builder

RUN \
 echo "**** install build packages ****" && \
 apk add --no-cache \
    python3 \
    py3-pip \
    gcc \
    musl-dev \
    libffi-dev \
    openssl-dev \
    cargo && \
 python3 -m pip install --break-system-packages poetry

# Build the venv at the same absolute path (/app/.venv) it will live at in the final stage --
# a venv's console-script shebangs bake in the build-time path, so a mismatched path here
# leaves every entry point (including traefik-certificate-exporter itself) dangling.
WORKDIR /app

# Copy only the dependency manifests first so this layer caches independently of source changes.
# A real venv (not virtualenvs.create=false) sidesteps PEP 668's externally-managed-environment
# restriction on Alpine's system Python.
COPY pyproject.toml poetry.lock ./
RUN poetry config virtualenvs.in-project true && \
    poetry install --only main --no-root --no-directory

# Poetry's venv doesn't bundle pip; ensurepip (stdlib) bootstraps it so the application
# package itself (not a locked dependency, so not covered by `poetry install` above) can be
# installed from PyPI/a custom index, same as the image always has.
ARG PACKAGE_REPO_URL
RUN /app/.venv/bin/python -m ensurepip --upgrade && \
    if [ -z ${PACKAGE_REPO_URL+x} ]; then \
	echo "**** install traefik-certificate-exporter from pypi ****" && \
	/app/.venv/bin/python -m pip install --no-deps \
		traefik-certificate-exporter; \
    else \
	echo "**** install traefik-certificate-exporter from ${PACKAGE_REPO_URL} ****" && \
	/app/.venv/bin/python -m pip install --no-deps --extra-index-url ${PACKAGE_REPO_URL} \
		traefik-certificate-exporter; \
    fi

# Image to start from
FROM ghcr.io/linuxserver/baseimage-alpine:3.24@sha256:e17494fc7ec17c64f1b502d52705aa99d7a1cd8ccf59bb7b36003db89d97d2c6

# environment settings
ENV \
    DOCKER_PLATFORMS="linux/amd64,linux/arm64"  \
	TRAEFIK_CERTIFICATE_EXPORTER_LOGGING_CONSOLEONLY=true \
	TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_DATAPATH=/data \
	TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_OUTPUTPATH=/certs \
	TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_WATCHFORCHANGES=true \
	TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_RUNATSTART=true \
	PATH="/app/.venv/bin:$PATH"

# Labels
LABEL org.opencontainers.image.description="Utility to export certificates from traefik and is based on the linuxserver.io container baseimage for alpine"

# Copy files into container
COPY docker/root /

# Run commands
RUN \
 echo "**** update and upgrade system packages ****" && \
 apk -U upgrade && \
 echo "**** install base packages ****" && \
 apk add --no-cache \
    python3 \
	py3-pip && \
 echo "**** creating folders ****" && \
 mkdir -p \
	/config /data /certs && \
 echo "**** cleanup ****" && \
 rm -rf \
	/tmp/* \
	/var/cache/apk/* \
	/var/tmp/* || true

# Copy the fully-populated venv (locked dependencies + the application package) built above --
# nothing left to install in the final stage, so the final image never needs poetry or pip.
# Symlinked into /usr/local/bin rather than relying on PATH, since s6-overlay's with-contenv
# does not reliably propagate a Dockerfile-level PATH override into service run scripts.
COPY --from=builder /app/.venv /app/.venv
RUN ln -s /app/.venv/bin/traefik-certificate-exporter /usr/local/bin/traefik-certificate-exporter

# volumes
VOLUME /config /data /certs

# Working directory
WORKDIR /config
