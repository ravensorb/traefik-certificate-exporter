import threading
import time
from unittest.mock import MagicMock, patch

from traefik_certificate_exporter.libs.docker import (
    DOCKER_LABEL,
    RESTART_COOLDOWN_SECONDS,
    DockerManager,
)
from traefik_certificate_exporter.libs.settings import Settings


def _make_settings(**overrides) -> Settings:
    defaults = {
        "dataPath": "/data",
        "fileSpec": "*.json",
        "outputPath": "/certs",
        "resolverInPathName": False,
        "traefikResolverId": None,
        "flat": False,
        "dryRun": False,
        "restartContainers": True,
        "domains": {"include": [], "exclude": []},
        "watchForChanges": False,
        "runAtStart": False,
        "watchInterval": 60,
        "pkcs12Passphrase": None,
    }
    defaults.update(overrides)
    return Settings(**defaults)


def _make_container(container_id: str, labeled_domains: str):
    container = MagicMock()
    container.id = container_id
    container.labels = {DOCKER_LABEL: labeled_domains}
    return container


def test_restart_disabled_never_touches_docker_client():
    settings = _make_settings(restartContainers=False)
    manager = DockerManager(settings=settings)

    with patch("traefik_certificate_exporter.libs.docker.docker.from_env") as from_env:
        manager.restartLabeledContainers(["example.test"])

    from_env.assert_not_called()


def test_restarts_container_whose_label_matches_a_processed_domain():
    settings = _make_settings(restartContainers=True, dryRun=False)
    manager = DockerManager(settings=settings)
    matching = _make_container("abc123", "example.test,other.test")
    client = MagicMock()
    client.containers.list.return_value = [matching]

    with patch(
        "traefik_certificate_exporter.libs.docker.docker.from_env", return_value=client
    ):
        manager.restartLabeledContainers(["example.test"])

    client.containers.list.assert_called_once_with(filters={"label": DOCKER_LABEL})
    matching.restart.assert_called_once()


def test_does_not_restart_container_whose_label_does_not_match():
    settings = _make_settings(restartContainers=True, dryRun=False)
    manager = DockerManager(settings=settings)
    non_matching = _make_container("def456", "unrelated.test")
    client = MagicMock()
    client.containers.list.return_value = [non_matching]

    with patch(
        "traefik_certificate_exporter.libs.docker.docker.from_env", return_value=client
    ):
        manager.restartLabeledContainers(["example.test"])

    non_matching.restart.assert_not_called()


def test_dry_run_does_not_call_restart():
    settings = _make_settings(restartContainers=True, dryRun=True)
    manager = DockerManager(settings=settings)
    matching = _make_container("abc123", "example.test")
    client = MagicMock()
    client.containers.list.return_value = [matching]

    with patch(
        "traefik_certificate_exporter.libs.docker.docker.from_env", return_value=client
    ):
        manager.restartLabeledContainers(["example.test"])

    matching.restart.assert_not_called()


def test_none_domains_is_treated_as_empty_list_without_raising():
    settings = _make_settings(restartContainers=True)
    manager = DockerManager(settings=settings)
    client = MagicMock()
    client.containers.list.return_value = []

    with patch(
        "traefik_certificate_exporter.libs.docker.docker.from_env", return_value=client
    ):
        manager.restartLabeledContainers(None)


def test_docker_client_error_is_caught_and_logged_not_raised(caplog):
    settings = _make_settings(restartContainers=True)
    manager = DockerManager(settings=settings)

    with patch(
        "traefik_certificate_exporter.libs.docker.docker.from_env",
        side_effect=RuntimeError("daemon unreachable"),
    ):
        manager.restartLabeledContainers(["example.test"])

    assert "Failed restarting containers" in caplog.text


def test_second_pass_inside_the_cooldown_window_does_not_restart_again():
    settings = _make_settings(restartContainers=True, dryRun=False)
    manager = DockerManager(settings=settings)
    matching = _make_container("abc123", "example.test,other.test")
    client = MagicMock()
    client.containers.list.return_value = [matching]

    with patch(
        "traefik_certificate_exporter.libs.docker.docker.from_env", return_value=client
    ):
        manager.restartLabeledContainers(["example.test"])
        manager.restartLabeledContainers(["example.test"])

    matching.restart.assert_called_once()


def test_a_renewal_after_the_cooldown_restarts_again_even_with_identical_domains():
    """The regression that killed name-based change detection.

    A renewal replaces key material and keeps the domain name, so a pass after a renewal is
    indistinguishable from a repeat pass by name alone. Suppressing on "same domains" made
    every labeled container restart exactly once per process lifetime and then never again.
    """
    settings = _make_settings(restartContainers=True, dryRun=False)
    manager = DockerManager(settings=settings)
    matching = _make_container("abc123", "example.test")
    client = MagicMock()
    client.containers.list.return_value = [matching]

    base = 1_000_000.0
    with (
        patch(
            "traefik_certificate_exporter.libs.docker.docker.from_env",
            return_value=client,
        ),
        patch(
            "traefik_certificate_exporter.libs.docker.time.time",
            side_effect=[base, base + RESTART_COOLDOWN_SECONDS + 1],
        ),
    ):
        manager.restartLabeledContainers(["example.test"])
        manager.restartLabeledContainers(["example.test"])

    assert matching.restart.call_count == 2


def test_cooldown_skip_is_logged_at_info_so_an_operator_can_see_it(caplog):
    settings = _make_settings(restartContainers=True, dryRun=False)
    manager = DockerManager(settings=settings)
    matching = _make_container("abc123", "example.test")
    client = MagicMock()
    client.containers.list.return_value = [matching]

    with (
        caplog.at_level("INFO"),
        patch(
            "traefik_certificate_exporter.libs.docker.docker.from_env",
            return_value=client,
        ),
    ):
        manager.restartLabeledContainers(["example.test"])
        manager.restartLabeledContainers(["example.test"])

    assert "cooldown" in caplog.text


def test_the_cooldown_is_per_container_not_global():
    settings = _make_settings(restartContainers=True, dryRun=False)
    manager = DockerManager(settings=settings)
    first = _make_container("abc123", "example.test")
    second = _make_container("def456", "example.test")
    client = MagicMock()
    client.containers.list.return_value = [first, second]

    with patch(
        "traefik_certificate_exporter.libs.docker.docker.from_env", return_value=client
    ):
        manager.restartLabeledContainers(["example.test"])

    first.restart.assert_called_once()
    second.restart.assert_called_once()


def test_failed_restart_does_not_start_a_cooldown():
    settings = _make_settings(restartContainers=True, dryRun=False)
    manager = DockerManager(settings=settings)
    matching = _make_container("abc123", "example.test")
    matching.restart.side_effect = [RuntimeError("boom"), None]
    client = MagicMock()
    client.containers.list.return_value = [matching]

    with patch(
        "traefik_certificate_exporter.libs.docker.docker.from_env", return_value=client
    ):
        manager.restartLabeledContainers(["example.test"])
        manager.restartLabeledContainers(["example.test"])

    assert matching.restart.call_count == 2


def test_restart_failure_does_not_abort_the_remaining_containers():
    settings = _make_settings(restartContainers=True, dryRun=False)
    manager = DockerManager(settings=settings)
    failing = _make_container("abc123", "example.test")
    failing.restart.side_effect = RuntimeError("boom")
    healthy = _make_container("def456", "example.test")
    client = MagicMock()
    client.containers.list.return_value = [failing, healthy]

    with patch(
        "traefik_certificate_exporter.libs.docker.docker.from_env", return_value=client
    ):
        manager.restartLabeledContainers(["example.test"])

    healthy.restart.assert_called_once()


def test_dry_run_never_records_state_so_it_never_suppresses_a_real_restart():
    settings = _make_settings(restartContainers=True, dryRun=True)
    manager = DockerManager(settings=settings)
    matching = _make_container("abc123", "example.test")
    client = MagicMock()
    client.containers.list.return_value = [matching]

    with patch(
        "traefik_certificate_exporter.libs.docker.docker.from_env", return_value=client
    ):
        manager.restartLabeledContainers(["example.test"])
        manager.restartLabeledContainers(["example.test"])

    matching.restart.assert_not_called()
    assert manager._DockerManager__lastRestart == {}


def test_concurrent_passes_never_restart_the_same_container_twice():
    """The reserve-then-restart step has to be indivisible: drains run on timer threads
    while the run-at-start pass runs on the main thread."""
    settings = _make_settings(restartContainers=True, dryRun=False)
    manager = DockerManager(settings=settings)
    started = threading.Event()

    def _restart():
        # Hold the call open long enough that every other thread has made its decision
        # while this one is still in flight.
        started.set()
        time.sleep(0.2)

    matching = _make_container("abc123", "example.test")
    matching.restart.side_effect = _restart
    client = MagicMock()
    client.containers.list.return_value = [matching]

    with patch(
        "traefik_certificate_exporter.libs.docker.docker.from_env", return_value=client
    ):
        threads = [
            threading.Thread(
                target=manager.restartLabeledContainers, args=(["example.test"],)
            )
            for _ in range(4)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)

    assert started.is_set()
    assert matching.restart.call_count == 1
