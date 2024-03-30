# Image to start from
FROM ghcr.io/linuxserver/baseimage-alpine:3.19

# environment settings
ENV \
    DOCKER_PLATFORMS="linux/amd64,linux/arm64"  \
    LLL_EX_PATH_BASE="/opt/l3io"  \
    LLL_EX_PATH_COMMON_SCRIPTS="/opt/l3io/common/scripts"  \
    LLL_EX_PATH_CONFIG="/opt/l3io/build/config"  \
    LLL_EX_PATH_SCRIPTS="/opt/l3io/build/scripts" \
	TRAEFIK_CERTIFICATE_EXPORTER_LOGGING_CONSOLEONLY=true \
	TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_DATAPATH=/data \
	TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_OUTPUTPATH=/certs \
	TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_WATCHFORCHANGES=true \
	TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_RUNATSTART=true

# arguments for build process (after from)
ARG PACKAGE_REPO_URL

# Labels
LABEL org.opencontainers.image.description "utility to export certificates 	from traefik and is based on the linuxserver.io container baseimage for alpine"
LABEL maintainer="ravensorb"

# Copy files into container
COPY root /

# Run commands
RUN \
 echo "**** update and upgrade system packages ****" && \
 apk -U upgrade && \
 echo "**** install base packages ****" && \
 apk add --no-cache \
    python3 \
	py3-pip && \
 echo "**** install packages ****"  && \
 python3 -m pip install --break-system-packages  \
	wheel \
	watchdog \
	docker \
	requests \
	docker-pycreds \
	confuse \
	python-dotenv \
	importlib-resources \
	jsonpickle \
	coloredlogs \
	logging-tree \
	expandvars \
	pyyaml && \
 if [ -z ${PACKAGE_REPO_URL+x} ]; then \
	echo "**** install traefik-certificate-exporter from pypi ****" && \
	python3 -m pip install --break-system-packages \
		traefik-certificate-exporter; \
 else \
	echo "**** install traefik-certificate-exporter from ${PACKAGE_REPO_URL} ****" && \
	python3 -m pip install --break-system-packages --extra-index-url ${PACKAGE_REPO_URL} \
		traefik-certificate-exporter; \
 fi && \
 echo "**** creating folders ****" && \
 mkdir -p \
	/data /certs && \
 echo "**** cleanup ****" && \
 rm -rf \
	/tmp/* \
	/var/cache/apk/* \
	/var/tmp/* || true

# volumes
VOLUME /data /certs

# Working directory
WORKDIR /config
