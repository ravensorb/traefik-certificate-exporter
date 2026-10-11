# syntax=docker/dockerfile:1

# Digest-pinned default. Dependabot resolves `FROM $VAR` only through an ARG default,
# so without one the `docker` ecosystem entry watching /docker can update nothing while
# still reporting coverage.
ARG BASE_IMAGE=ghcr.io/linuxserver/baseimage-alpine:3.24@sha256:d2deff7a9aff1388bd79ded33a4efda6bd4b26358f9234a23deccba724738fea

# Build stage: install the locked dependency set and the caller-supplied wheel.
FROM ${BASE_IMAGE} AS builder

ARG POETRY_VERSION

# The POETRY_VERSION contract is asserted as its own statement, ahead of the install.
# Chained after the package install the `||` bound to the entire preceding `&&` chain, so
# a failed `apk add` reported "POETRY_VERSION is required" -- the wrong diagnostic for the
# wrong fault. Kept out of the RUN body: a comment inside a line continuation is fragile.
RUN \
 test -n "${POETRY_VERSION}" || \
    { echo >&2 "build contract: POETRY_VERSION is required"; exit 1; }; \
 echo "**** install build packages ****" && \
 apk add --no-cache \
    python3 \
    py3-pip \
    gcc \
    musl-dev \
    libffi-dev \
    openssl-dev \
    cargo && \
 python3 -m pip install --break-system-packages --no-cache-dir \
    "poetry==${POETRY_VERSION}"

# Build the venv at the same absolute path (/app/.venv) it will have at runtime.
# Console-script shebangs contain this path, so the builder and runtime must agree.
WORKDIR /app

# Dependency layers depend only on Poetry's authoritative manifest and lock file.
# The builder has no .git, so strict dynamic versioning (AD-7) would fail; the bypass is
# safe because this installs dependencies only -- the application version comes from the
# hashed wheel below (ADR-0036).
COPY pyproject.toml poetry.lock ./
RUN poetry config virtualenvs.in-project true && \
    POETRY_DYNAMIC_VERSIONING_BYPASS=0.0.0 \
    poetry install --only main --no-root --no-directory

# The BuildKit bind mount makes a missing wheel observable by this validation step instead
# of failing in COPY with an opaque cache-key error. The contract accepts one exact path.
ARG WHEEL_PATH
ARG WHEEL_SHA256
RUN --mount=type=bind,source=.,target=/build-context,ro \
    set -eu; \
    case "${WHEEL_PATH}" in \
        ""|/*|*".."*) \
            echo >&2 "wheel contract: WHEEL_PATH must be a non-empty path inside the build context"; \
            exit 1; \
            ;; \
    esac; \
    set -- /build-context/${WHEEL_PATH}; \
    if [ "$#" -ne 1 ] || [ ! -f "$1" ]; then \
        echo >&2 "wheel contract: WHEEL_PATH must select exactly one existing wheel"; \
        exit 1; \
    fi; \
    case "$1" in \
        *.whl) ;; \
        *) \
            echo >&2 "wheel contract: WHEEL_PATH must select a .whl file"; \
            exit 1; \
            ;; \
    esac; \
    if ! printf '%s\n' "${WHEEL_SHA256}" | grep -Eq '^[0-9a-f]{64}$'; then \
        echo >&2 "wheel contract: WHEEL_SHA256 must be 64 lowercase hexadecimal characters"; \
        exit 1; \
    fi; \
    actual_sha256="$(sha256sum "$1" | awk '{print $1}')"; \
    if [ "${actual_sha256}" != "${WHEEL_SHA256}" ]; then \
        echo >&2 "wheel contract: WHEEL_SHA256 does not match the supplied wheel"; \
        exit 1; \
    fi; \
    rm -rf /tmp/verified-wheel; \
    mkdir /tmp/verified-wheel; \
    cp "$1" "/tmp/verified-wheel/$(basename "$1")"

# Ensure pip is available only long enough to install the exact verified wheel, without
# dependencies or index access, then remove pip from the venv before the stage is copied.
# VERSION may be the wheel's PEP 440 version (`just image`) or its SemVer image-version
# (CI), so it is compared under PEP 440 normalisation (AD-17 as amended by ADR-0036):
# 1.4.1-dev.3 and 1.4.1.dev3 both equal 1.4.1.dev3. The parser is pip's vendored
# `packaging`, already in the venv for this install and removed with pip, so the image
# gains no dependency; a pip release that moves it fails this build loudly.
ARG VERSION
ARG REVISION
RUN set -eu; \
    if ! printf '%s\n' "${REVISION}" | grep -Eq '^([0-9a-f]{40}|[0-9a-f]{64})$'; then \
        echo >&2 "image contract: REVISION must be a full lowercase source SHA"; \
        exit 1; \
    fi; \
    /app/.venv/bin/python -m ensurepip --upgrade; \
    set -- /tmp/verified-wheel/*.whl; \
    if [ "$#" -ne 1 ] || [ ! -f "$1" ]; then \
        echo >&2 "wheel contract: verified wheel staging must contain exactly one wheel"; \
        exit 1; \
    fi; \
    verified_wheel="$1"; \
    /app/.venv/bin/python -m pip install --no-deps --no-index "${verified_wheel}"; \
    installed_version="$(/app/.venv/bin/python -c \
        'from importlib.metadata import version; print(version("traefik-certificate-exporter"))')"; \
    if [ -z "${VERSION}" ] || { [ "${installed_version}" != "${VERSION}" ] && \
        ! /app/.venv/bin/python -c \
            'import sys; from pip._vendor.packaging.version import Version; sys.exit(Version(sys.argv[1]) != Version(sys.argv[2]))' \
            "${installed_version}" "${VERSION}"; }; then \
        echo >&2 "image contract: VERSION must equal the supplied wheel metadata"; \
        exit 1; \
    fi; \
    /app/.venv/bin/python -m pip check; \
    /app/.venv/bin/python -m pip uninstall --yes pip; \
    rm -rf /tmp/verified-wheel

# Runtime stage: retain the digest-pinned LinuxServer/s6 base and its PUID/PGID model.
FROM ${BASE_IMAGE} AS runtime

# CONSOLEJSON leaves the console as coloured human-readable text by default; set it to
# true to emit that stream as JSON instead, so `correlation_id` reaches `docker logs` as a
# real field rather than interpolated into a string (ADR-0023 Decision 2).
ENV \
    TRAEFIK_CERTIFICATE_EXPORTER_LOGGING_CONSOLEONLY=true \
    TRAEFIK_CERTIFICATE_EXPORTER_LOGGING_CONSOLEJSON=false \
    TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_DATAPATH=/data \
    TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_OUTPUTPATH=/certs \
    TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_WATCHFORCHANGES=true \
    TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_RUNATSTART=true \
    PATH="/app/.venv/bin:$PATH"

# Preserve the packaged defaults and s6 service definitions.
COPY docker/root /

RUN \
 echo "**** update and upgrade system packages ****" && \
 apk -U upgrade && \
 echo "**** install runtime packages ****" && \
 apk add --no-cache \
    python3 && \
 echo "**** creating folders ****" && \
 mkdir -p \
    /config /data /certs && \
 echo "**** cleanup ****" && \
 rm -rf \
    /tmp/* \
    /var/cache/apk/* \
    /var/tmp/* || true

# Only the populated application venv crosses the stage boundary. Poetry, compilers, Cargo,
# headers, and pip stay behind in the builder.
COPY --from=builder /app/.venv /app/.venv
RUN ln -s /app/.venv/bin/traefik-certificate-exporter \
    /usr/local/bin/traefik-certificate-exporter

VOLUME /config /data /certs

WORKDIR /config
