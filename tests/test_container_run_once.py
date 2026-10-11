"""Opt-in: the real image in run-once mode exits with the pass's code (E014-S01-005, AC 7).

In 0.2.x, `TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_WATCHFORCHANGES=false` made the s6 service
print "Skipping start of application..." and exit, which s6 respawned every second: the
container never exited. This test runs the built image under s6 and requires it to stop on
its own. It is required 0.3.0 release evidence (AC 12); E014-S02-005 runs it against the
release-commit image:

    just image && TCE_DOCKER_INTEGRATION=1 poetry run pytest -m integration tests/test_container_run_once.py

The image under test is `${TCE_IMAGE:-traefik-certificate-exporter:local}`. The exit code
reflects start-up failures only (ADR-0044): 0, or 1 for a missing data path.
"""

import os
import uuid
from pathlib import Path

import pytest

from traefik_certificate_exporter.libs.docker import DEFAULT_DOCKER_ENDPOINT

IMAGE = os.environ.get("TCE_IMAGE") or "traefik-certificate-exporter:local"
EXIT_TIMEOUT_SECONDS = 60
START_LINE = "Traefik Certificate Exporter v"


# Opt-in, but once opted in nothing is skipped: this is required release evidence, and a
# skipped run exits 0 having tested nothing. A missing socket or image FAILS instead.
OPTED_IN = os.environ.get("TCE_DOCKER_INTEGRATION") == "1"

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not OPTED_IN, reason="image test is opt-in: set TCE_DOCKER_INTEGRATION=1"
    ),
]


def _run_once(tmp_path: Path, extra_env: "dict[str, str]") -> "tuple[int, str]":
    """Start the image in run-once mode; return (container exit code, its logs)."""
    import requests

    import docker

    endpoint = os.environ.get("DOCKER_HOST") or DEFAULT_DOCKER_ENDPOINT
    if endpoint.startswith("unix://") and not Path(endpoint[7:]).exists():
        pytest.fail(
            f"TCE_DOCKER_INTEGRATION=1 but there is no Docker socket at {endpoint[7:]}"
        )
    client = docker.from_env()
    try:
        client.images.get(IMAGE)
    except docker.errors.ImageNotFound:
        pytest.fail(f"image {IMAGE} not found; build it with `just image`")

    dataPath = tmp_path / "data"
    dataPath.mkdir()
    environment = {"TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_WATCHFORCHANGES": "false"}
    environment.update(extra_env)

    container = client.containers.run(
        IMAGE,
        name=f"tce-run-once-it-{uuid.uuid4().hex[:8]}",
        detach=True,
        environment=environment,
        volumes={str(dataPath): {"bind": "/data", "mode": "ro"}},
    )
    try:
        try:
            status = container.wait(timeout=EXIT_TIMEOUT_SECONDS)
        except requests.exceptions.RequestException:
            logs = container.logs().decode("utf-8", errors="replace")
            pytest.fail(
                f"container still running after {EXIT_TIMEOUT_SECONDS}s:\n{logs}"
            )
        logs = container.logs().decode("utf-8", errors="replace")
        return status["StatusCode"], logs
    finally:
        container.remove(force=True)


def test_run_once_container_exits_zero_after_one_pass(tmp_path):
    code, logs = _run_once(tmp_path, {})

    assert code == 0, logs
    assert logs.count(START_LINE) == 1, logs
    assert "Starting application (run-once mode)" in logs, logs
    assert "Skipping" not in logs, logs


def test_run_once_container_exits_one_for_a_missing_data_path(tmp_path):
    # The image always creates /data, so the missing path has to be named explicitly.
    code, logs = _run_once(
        tmp_path, {"TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_DATAPATH": "/nonexistent"}
    )

    assert code == 1, logs
    assert logs.count(START_LINE) == 1, logs
