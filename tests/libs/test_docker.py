from unittest.mock import MagicMock, patch

from traefik_certificate_exporter.libs.docker import DOCKER_LABEL, DockerManager
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
