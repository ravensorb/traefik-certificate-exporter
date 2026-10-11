"""Opt-in: `restartLabeledContainers` against a real Docker Engine.

Every test in `test_docker.py` replaces the client, which is how B1 (an SDK that could not
talk to any Engine) shipped with a green suite. This one does not: it restarts a real
container and reads the Engine's own `StartedAt`. It is required 0.3.0 release evidence.

    TCE_DOCKER_INTEGRATION=1 poetry run pytest -m integration tests/libs/test_docker_engine.py
"""

import os
import time
import uuid
from pathlib import Path

import pytest

from traefik_certificate_exporter.libs.docker import (
    DEFAULT_DOCKER_ENDPOINT,
    DOCKER_LABEL,
    DockerManager,
)
from traefik_certificate_exporter.libs.settings import Settings

# Pinned by digest so the test's behaviour cannot change under a moved tag. Multi-arch
# index digest of busybox:1.37, resolved 2026-10-11 with
# `docker buildx imagetools inspect busybox:1.37`.
BUSYBOX_IMAGE = (
    "busybox:1.37"
    "@sha256:bdf57e528e45e4433820e045b29b4597825a1c9e38353532d90a01445013f82e"
)
DOMAIN = "it.example.test"


def _socket_path() -> "str | None":
    """The unix socket the exporter's client will use, or None for a non-unix endpoint."""
    endpoint = os.environ.get("DOCKER_HOST") or DEFAULT_DOCKER_ENDPOINT
    return endpoint.removeprefix("unix://") if endpoint.startswith("unix://") else None


def _skip_reason() -> "str | None":
    if os.environ.get("TCE_DOCKER_INTEGRATION") != "1":
        return "real-Engine test is opt-in: set TCE_DOCKER_INTEGRATION=1"
    socket = _socket_path()
    if socket is not None and not Path(socket).exists():
        return f"no Docker socket at {socket}"
    return None


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(_skip_reason() is not None, reason=_skip_reason() or ""),
]


def _settings() -> Settings:
    return Settings(
        dataPath="/data",
        fileSpec="*.json",
        outputPath="/certs",
        resolverInPathName=False,
        traefikResolverId=None,
        flat=False,
        dryRun=False,
        restartContainers=True,
        domains={"include": [], "exclude": []},
        watchForChanges=False,
        runAtStart=False,
        watchInterval=60,
        pkcs12Passphrase=None,
    )


def test_restart_labeled_container_against_a_real_engine():
    manager = DockerManager(settings=_settings())
    client = manager._create_client()
    container = None
    try:
        container = client.containers.run(
            BUSYBOX_IMAGE,
            ["sleep", "300"],
            detach=True,
            # PID 1 `sleep` ignores SIGTERM; tini forwards it, so a restart does not sit
            # out the 10 s stop timeout.
            init=True,
            labels={DOCKER_LABEL: DOMAIN},
            name=f"tce-it-{uuid.uuid4().hex[:12]}",
        )
        container.reload()
        startedBefore = container.attrs["State"]["StartedAt"]
        # `StartedAt` has sub-second resolution, but keep the two starts clearly apart.
        time.sleep(1)

        assert manager.check() is True
        # Since E014-S01-006 a restart needs an exported file newer than the container's
        # start (ADR-0045). The stub reports one 3 s after the Engine's own `StartedAt`,
        # beyond the 2 s slack, so this still proves the call really reaches the Engine.
        startedAt = DockerManager._startedAt(container)
        assert startedAt is not None, startedAt

        def artifactMtime(domain):
            return startedAt + 3 if domain == DOMAIN else None

        manager.restartLabeledContainers(artifactMtime)

        container.reload()
        assert container.attrs["State"]["Running"] is True
        assert container.attrs["State"]["StartedAt"] != startedBefore
    finally:
        if container is not None:
            container.remove(force=True)
        client.close()
