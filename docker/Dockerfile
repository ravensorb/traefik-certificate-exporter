FROM ghcr.io/linuxserver/baseimage-alpine:3.11

# set version label
ARG BUILD_DATE
ARG VERSION
ARG TEST_VERSION
LABEL build_version="Custom Linuxserver.io version:- ${VERSION} Build-date:- ${BUILD_DATE}"
LABEL maintainer="ravensorb"

RUN \
 echo "**** update and upgrade system packages ****" && \
 apk -U upgrade && \
 echo "**** install base packages ****" && \
 apk add --no-cache \
    python3 \
	py3-pip && \
 echo "**** install packages ****"  && \
 python3 -m pip install  \
	wheel \
	watchdog \
	docker \
	requests \
	docker-pycreds \
	pyyaml && \
 if [ -z ${TEST_VERSION+x} ]; then \
	python3 -m pip install \
		traefik-certificate-exporter; \
 else \
	python3 -m pip install --index-url https://test.pypi.org/simple/ \
		traefik-certificate-exporter\
 fi && \
 echo "**** creating folders ****" && \
 mkdir -p \
	/data /certs && \
 echo "**** cleanup ****" && \
 rm -rf \
	/tmp/*

COPY root /
# volumes
VOLUME /data /certs
