"""Opt-in: the real image restarts a labeled container only on change (E014-S01-006).

Required 0.3.0 release evidence (FR-15, ADR-0045); E014-S02-005 runs it against the
release-commit image:

    just image && TCE_DOCKER_INTEGRATION=1 poetry run pytest -m integration tests/test_container_restart.py

Three run-once starts of `${TCE_IMAGE:-traefik-certificate-exporter:local}` over one
resolver-wrapped store, with the image's default layout (`resolverinpathname: true`,
`flat: false`, so the artifacts land under `/output/<resolver>/it.example.test/`):

1. the first export is newer than the labeled busybox container, which restarts;
2. the unchanged store rewrites nothing, so the second run restarts nothing;
3. the files are touched (an exporter that wrote them and died before restarting), so the
   third run over the unchanged store restarts the container again.
"""

import base64
import json
import os
import time
import uuid
from pathlib import Path

import pytest

from traefik_certificate_exporter.libs.docker import (
    DEFAULT_DOCKER_ENDPOINT,
    DOCKER_LABEL,
    RESTART_MTIME_SLACK_SECONDS,
    DockerManager,
)

from .fixtures.acme_fixtures import real_chain

IMAGE = os.environ.get("TCE_IMAGE") or "traefik-certificate-exporter:local"
# The digest E014-S01-001 recorded (`tests/libs/test_docker_engine.py`).
BUSYBOX_IMAGE = (
    "busybox:1.37"
    "@sha256:bdf57e528e45e4433820e045b29b4597825a1c9e38353532d90a01445013f82e"
)
DOMAIN = "it.example.test"
RESOLVER = "myresolver"
OUTPUT_PATH = "/output"
EXIT_TIMEOUT_SECONDS = 120

# Opt-in, but once opted in nothing is skipped: a skipped release-evidence run exits 0
# having tested nothing. A missing socket or image FAILS instead.
OPTED_IN = os.environ.get("TCE_DOCKER_INTEGRATION") == "1"

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not OPTED_IN, reason="image test is opt-in: set TCE_DOCKER_INTEGRATION=1"
    ),
]


def _socket_path() -> str:
    endpoint = os.environ.get("DOCKER_HOST") or DEFAULT_DOCKER_ENDPOINT
    if not endpoint.startswith("unix://"):
        pytest.fail(f"the image test mounts a unix socket; DOCKER_HOST is {endpoint}")
    socket = endpoint.removeprefix("unix://")
    if not Path(socket).exists():
        pytest.fail(
            f"TCE_DOCKER_INTEGRATION=1 but there is no Docker socket at {socket}"
        )
    return socket


def _store() -> dict:
    """The stock Traefik v2/v3 shape: `{"<resolver>": {"Account": …, "Certificates": […]}}`."""
    chain = real_chain()
    return {
        RESOLVER: {
            "Account": {
                "Registration": {
                    "uri": "https://acme-v02.api.letsencrypt.org/directory"
                }
            },
            "Certificates": [
                {
                    "domain": {"main": DOMAIN, "sans": []},
                    "key": base64.b64encode(chain.key_pem).decode("ascii"),
                    "certificate": base64.b64encode(chain.fullchain_pem).decode(
                        "ascii"
                    ),
                }
            ],
        }
    }


def _started_at(container) -> float:
    container.reload()
    startedAt = DockerManager._startedAt(container)
    assert startedAt is not None, container.attrs["State"]
    return startedAt


def _run_exporter(client, socket, dataPath: Path, volume, suffix: str, n: int) -> str:
    """One run-once start of the image; returns its logs once it has exited 0."""
    import requests

    container = client.containers.run(
        IMAGE,
        name=f"tce-restart-it-{suffix}-{n}",
        detach=True,
        environment={
            "TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_WATCHFORCHANGES": "false",
            "TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_RUNATSTART": "true",
            "TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_RESTARTCONTAINERS": "true",
            "TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_OUTPUTPATH": OUTPUT_PATH,
        },
        volumes={
            str(dataPath): {"bind": "/data", "mode": "ro"},
            volume.name: {"bind": OUTPUT_PATH, "mode": "rw"},
            socket: {"bind": "/var/run/docker.sock", "mode": "rw"},
        },
    )
    try:
        try:
            status = container.wait(timeout=EXIT_TIMEOUT_SECONDS)
        except requests.exceptions.RequestException:
            pytest.fail(
                f"exporter run {n} still running after {EXIT_TIMEOUT_SECONDS}s:\n"
                + container.logs().decode("utf-8", "replace")
            )
        logs = container.logs().decode("utf-8", "replace")
        assert status["StatusCode"] == 0, f"exporter run {n} failed:\n{logs}"
        return logs
    finally:
        container.remove(force=True)


def test_the_image_restarts_only_on_change_and_recovers_a_lost_restart(tmp_path):
    import docker

    socket = _socket_path()
    client = docker.from_env()
    try:
        client.images.get(IMAGE)
    except docker.errors.ImageNotFound:
        pytest.fail(f"image {IMAGE} not found; build it with `just image`")

    dataPath = tmp_path / "data"
    dataPath.mkdir()
    (dataPath / "acme.json").write_text(json.dumps(_store()))

    suffix = uuid.uuid4().hex[:8]
    volume = client.volumes.create(name=f"tce-restart-it-{suffix}")
    containers = []
    try:
        target = client.containers.run(
            BUSYBOX_IMAGE,
            ["sleep", "300"],
            detach=True,
            # PID 1 `sleep` ignores SIGTERM; tini forwards it, so a restart does not sit
            # out the 10 s stop timeout.
            init=True,
            labels={DOCKER_LABEL: DOMAIN},
            name=f"tce-restart-it-{suffix}-target",
        )
        containers.append(target)
        started0 = _started_at(target)
        # Keep the first export clearly beyond the slack after the container's start.
        time.sleep(RESTART_MTIME_SLACK_SECONDS + 1)

        # 1. The first export into an empty output directory restarts the container.
        logs1 = _run_exporter(client, socket, dataPath, volume, suffix, 1)
        started1 = _started_at(target)
        assert started1 != started0, (
            f"first run did not restart the container:\n{logs1}"
        )

        # 2. An unchanged store rewrites nothing: the files stay older than the container.
        logs2 = _run_exporter(client, socket, dataPath, volume, suffix, 2)
        started2 = _started_at(target)
        assert started2 == started1, (
            f"an unchanged run restarted the container:\n{logs2}"
        )

        # 3. Crash recovery: files newer than the container's start (as left by an
        #    exporter that wrote them and died before restarting) restart it next run.
        while time.time() <= started2 + RESTART_MTIME_SLACK_SECONDS + 1:
            time.sleep(0.5)
        artifacts = f"{OUTPUT_PATH}/{RESOLVER}/{DOMAIN}"
        toucher = client.containers.run(
            BUSYBOX_IMAGE,
            ["sh", "-c", f"ls {artifacts}/cert.pem >/dev/null && touch {artifacts}/*"],
            detach=True,
            volumes={volume.name: {"bind": OUTPUT_PATH, "mode": "rw"}},
            name=f"tce-restart-it-{suffix}-touch",
        )
        containers.append(toucher)
        touched = toucher.wait(timeout=60)
        assert touched["StatusCode"] == 0, toucher.logs().decode("utf-8", "replace")

        logs3 = _run_exporter(client, socket, dataPath, volume, suffix, 3)
        started3 = _started_at(target)
        assert started3 != started2, (
            f"touched files did not restart the container on the next run:\n{logs3}"
        )
    finally:
        try:
            for container in containers:
                container.remove(force=True)
        finally:
            volume.remove(force=True)
