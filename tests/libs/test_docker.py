import datetime
import hashlib
import json
import logging
import os
import threading
import time
from importlib import resources
from unittest.mock import MagicMock, patch

import pytest
import yaml

import docker
from traefik_certificate_exporter.libs import docker as docker_module
from traefik_certificate_exporter.libs.certificate_exporter import (
    AcmeCertificateExporter,
)
from traefik_certificate_exporter.libs.docker import (
    DOCKER_LABEL,
    RESTART_COOLDOWN_SECONDS,
    RESTART_MTIME_SLACK_SECONDS,
    DockerManager,
)
from traefik_certificate_exporter.libs.logging_utils import (
    globalLogger,
    reset_correlation_id,
    set_correlation_id,
)
from traefik_certificate_exporter.libs.settings import Settings

from ..fixtures.acme_fixtures import (
    acme_v2_certificate,
    real_chain_expiring_in,
)

CREATE_CLIENT = "traefik_certificate_exporter.libs.docker.DockerManager._create_client"
SCHEME_ERROR = "Not supported URL scheme"


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


# --------------------------------------------------------------------------------------
# Fakes. A recording client and container, not MagicMocks: the rule reads
# `attrs["State"]["StartedAt"]`, and a MagicMock would answer every lookup with another
# MagicMock. `restart()` advances `StartedAt` to now, as the Engine does.


def _rfc3339(epoch: float) -> str:
    """Docker's form: RFC 3339, nanoseconds, `Z`."""
    moment = datetime.datetime.fromtimestamp(epoch, tz=datetime.timezone.utc)
    return moment.strftime("%Y-%m-%dT%H:%M:%S.%f") + "123Z"


class FakeContainer:
    def __init__(self, cid, domains, startedAt=None, restartErrors=None):
        self.id = cid
        self.labels = {DOCKER_LABEL: domains} if domains is not None else {}
        if startedAt is None:
            startedAt = time.time() - 3600
        if isinstance(startedAt, (int, float)):
            startedAt = _rfc3339(startedAt)
        self.attrs = {"State": {"StartedAt": startedAt}}
        self.status = "running"
        self.restarts = 0
        self._errors = list(restartErrors or [])

    def restart(self):
        if self._errors:
            error = self._errors.pop(0)
            if error is not None:
                raise error
        self.restarts += 1
        self.attrs["State"]["StartedAt"] = _rfc3339(time.time())


class FakeContainers:
    def __init__(self, containers):
        self.items = list(containers)
        self.gone: set[str] = set()
        self.listCalls: list = []

    def list(self, filters=None, ignore_removed=False):
        self.listCalls.append({"filters": filters, "ignore_removed": ignore_removed})
        return [
            c for c in self.items if DOCKER_LABEL in c.labels and c.id not in self.gone
        ]

    def get(self, cid):
        for c in self.items:
            if c.id == cid and cid not in self.gone:
                return c
        raise docker.errors.NotFound(f"No such container: {cid}")


class FakeClient:
    def __init__(self, *containers):
        self.containers = FakeContainers(containers)
        self.closed = 0

    def close(self):
        self.closed += 1


class FakeTimer:
    """Records what would have been scheduled; `fire()` runs the target synchronously."""

    def __init__(self, interval, function, args=None, kwargs=None):
        self.interval = interval
        self.function = function
        self.args = tuple(args or ())
        self.kwargs = dict(kwargs or {})
        self.daemon = False
        self.started = False
        self.cancelled = False

    def start(self):
        self.started = True

    def cancel(self):
        self.cancelled = True

    def fire(self):
        self.function(*self.args, **self.kwargs)


@pytest.fixture
def timers(monkeypatch):
    created: list[FakeTimer] = []

    class _Recording(FakeTimer):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            created.append(self)

    monkeypatch.setattr(docker_module.threading, "Timer", _Recording)
    return created


@pytest.fixture
def clock():
    """A settable `time.time`, patched in the existing `…docker.time.time` style."""
    now = [1_800_000_000.0]
    with patch(
        "traefik_certificate_exporter.libs.docker.time.time", side_effect=lambda: now[0]
    ):
        yield now


def _always_newer(_domain):
    """An artifact newer than any start so far: models a fresh rotation before each call."""
    return time.time() + 10


def _at(mtime):
    return lambda _domain: mtime


def _debug_logs(caplog):
    return caplog.at_level(logging.DEBUG, logger=globalLogger.name)


# --------------------------------------------------------------------------------------
# Real exporter over a temporary output directory (BL-E012-008 cases 1-9).


def _default_layout() -> dict:
    """`resolverinpathname`/`flat` as shipped in `config_default.yaml`."""
    text = (
        resources.files("traefik_certificate_exporter")
        .joinpath("config_default.yaml")
        .read_text()
    )
    shipped = yaml.safe_load(text)["settings"]
    assert shipped["resolverinpathname"] is True and shipped["flat"] is False
    return {
        "resolverInPathName": shipped["resolverinpathname"],
        "flat": shipped["flat"],
    }


def _store(*certificates) -> dict:
    """A resolver-wrapped (Traefik v2/v3) store."""
    return {
        "myresolver": {
            "Account": {"Registration": {"uri": "https://acme.example.test/acct/1"}},
            "Certificates": list(certificates),
        }
    }


def _env(tmp_path, store, **layout):
    data = tmp_path / "data"
    data.mkdir(exist_ok=True)
    (data / "acme.json").write_text(json.dumps(store))
    return _make_settings(
        dataPath=str(data),
        outputPath=str(tmp_path / "out"),
        runAtStart=True,
        **(layout or _default_layout()),
    )


def _pass(exporter, manager, client):
    """One pass: export, then evaluate restarts, as both call sites do."""
    exporter.exportCertificates()
    with patch(CREATE_CLIENT, return_value=client):
        manager.restartLabeledContainers(exporter.artifactMtime)


def _domain_files(tmp_path, domain):
    return sorted(
        p for p in (tmp_path / "out").rglob("*") if domain in str(p) and p.is_file()
    )


def _set_mtime(paths, mtime):
    for path in paths:
        os.utime(path, (mtime, mtime))


def test_only_on_change_first_pass_into_empty_output_restarts(tmp_path, timers):
    settings = _env(tmp_path, _store(acme_v2_certificate("a.example.test")))
    container = FakeContainer("c1", "a.example.test")
    client = FakeClient(container)

    _pass(AcmeCertificateExporter(settings), DockerManager(settings), client)

    assert container.restarts == 1
    # Default layout over a resolver-wrapped store: `<output>/<resolver>/<domain>/`.
    assert (tmp_path / "out" / "myresolver" / "a.example.test" / "cert.pem").is_file()


def test_only_on_change_unchanged_second_pass_restarts_nothing(tmp_path, timers):
    settings = _env(tmp_path, _store(acme_v2_certificate("a.example.test")))
    container = FakeContainer("c1", "a.example.test")
    client = FakeClient(container)
    exporter, manager = AcmeCertificateExporter(settings), DockerManager(settings)

    _pass(exporter, manager, client)
    _pass(exporter, manager, client)

    assert container.restarts == 1
    assert timers == [], "an unchanged pass must not even schedule a restart"


def test_only_on_change_fresh_process_over_same_output_restarts_nothing(
    tmp_path, timers
):
    settings = _env(tmp_path, _store(acme_v2_certificate("a.example.test")))
    container = FakeContainer("c1", "a.example.test")
    client = FakeClient(container)
    _pass(AcmeCertificateExporter(settings), DockerManager(settings), client)

    # An exporter restart: no in-memory state survives.
    _pass(AcmeCertificateExporter(settings), DockerManager(settings), client)

    assert container.restarts == 1
    assert timers == []


def test_only_on_change_restarts_only_containers_of_changed_domain(tmp_path, timers):
    settings = _env(
        tmp_path,
        _store(
            acme_v2_certificate("a.example.test"), acme_v2_certificate("b.example.test")
        ),
    )
    AcmeCertificateExporter(settings).exportCertificates()
    now = time.time()
    _set_mtime(_domain_files(tmp_path, "example.test"), now - 120)
    first = FakeContainer("ca", "a.example.test", startedAt=now - 60)
    second = FakeContainer("cb", "b.example.test", startedAt=now - 60)

    # b.example.test is renewed: its certificate changes, a's does not.
    _env(
        tmp_path,
        _store(
            acme_v2_certificate("a.example.test"),
            acme_v2_certificate("b.example.test", real_chain_expiring_in(10)),
        ),
    )
    _pass(
        AcmeCertificateExporter(settings),
        DockerManager(settings),
        FakeClient(first, second),
    )

    assert (first.restarts, second.restarts) == (0, 1)


def test_only_on_change_crash_recovery_restarts_from_file_mtimes(tmp_path, timers):
    """The exporter wrote the files and died before restarting: the next process's pass
    over the unchanged store finds the files newer than the container and restarts it."""
    settings = _env(tmp_path, _store(acme_v2_certificate("a.example.test")))
    AcmeCertificateExporter(settings).exportCertificates()
    now = time.time()
    container = FakeContainer("c1", "a.example.test", startedAt=now - 60)
    _set_mtime(_domain_files(tmp_path, "a.example.test"), now - 10)

    _pass(
        AcmeCertificateExporter(settings),
        DockerManager(settings),
        FakeClient(container),
    )

    assert container.restarts == 1


def test_only_on_change_artifacts_older_than_start_do_not_restart(tmp_path, timers):
    settings = _env(tmp_path, _store(acme_v2_certificate("a.example.test")))
    AcmeCertificateExporter(settings).exportCertificates()
    now = time.time()
    container = FakeContainer("c1", "a.example.test", startedAt=now - 60)
    _set_mtime(_domain_files(tmp_path, "a.example.test"), now - 120)

    _pass(
        AcmeCertificateExporter(settings),
        DockerManager(settings),
        FakeClient(container),
    )

    assert container.restarts == 0


@pytest.mark.parametrize(
    "startedAt",
    ["<absent>", "", "not-a-timestamp", "0001-01-01T00:00:00Z"],
    ids=["absent", "empty", "unparsable", "zero"],
)
def test_only_on_change_missing_or_zero_started_at_does_not_restart(
    tmp_path, timers, caplog, startedAt
):
    settings = _env(tmp_path, _store(acme_v2_certificate("a.example.test")))
    container = FakeContainer("c-missing-start", "a.example.test")
    if startedAt == "<absent>":
        del container.attrs["State"]["StartedAt"]
    else:
        container.attrs["State"]["StartedAt"] = startedAt

    with _debug_logs(caplog):
        _pass(
            AcmeCertificateExporter(settings),
            DockerManager(settings),
            FakeClient(container),
        )

    assert container.restarts == 0
    records = [
        r
        for r in caplog.records
        if r.levelno == logging.DEBUG
        and "c-missing-start" in r.getMessage()
        and "StartedAt missing or unparsable" in r.getMessage()
    ]
    assert len(records) == 1, [r.getMessage() for r in caplog.records]


@pytest.mark.parametrize("ahead, restarts", [(1, 0), (3, 1)])
def test_only_on_change_mtime_slack(tmp_path, timers, ahead, restarts):
    assert RESTART_MTIME_SLACK_SECONDS == 2
    settings = _env(tmp_path, _store(acme_v2_certificate("a.example.test")))
    AcmeCertificateExporter(settings).exportCertificates()
    startedAt = float(int(time.time()) - 100)
    container = FakeContainer("c1", "a.example.test", startedAt=startedAt)
    _set_mtime(_domain_files(tmp_path, "a.example.test"), startedAt + ahead)

    _pass(
        AcmeCertificateExporter(settings),
        DockerManager(settings),
        FakeClient(container),
    )

    assert container.restarts == restarts


def test_only_on_change_missing_files(tmp_path, timers):
    settings = _env(tmp_path, _store(acme_v2_certificate("a.example.test")))
    exporter = AcmeCertificateExporter(settings)
    exporter.exportCertificates()
    now = time.time()
    startedAt = now - 60
    # No artifact for this one's domain anywhere: not a candidate.
    orphan = FakeContainer("c-orphan", "nofiles.example.test", startedAt=startedAt)
    # Only two of five artifacts present: the newer of the two decides.
    partial = FakeContainer("c-partial", "a.example.test", startedAt=startedAt)
    files = _domain_files(tmp_path, "a.example.test")
    keep = {p.name: p for p in files}
    for path in files:
        if path.name not in ("cert.pem", "privkey.pem"):
            path.unlink()
    _set_mtime([keep["cert.pem"]], now - 120)
    _set_mtime([keep["privkey.pem"]], now - 10)

    # Evaluated without a re-export, which would rewrite the deleted files.
    with patch(CREATE_CLIENT, return_value=FakeClient(orphan, partial)):
        DockerManager(settings).restartLabeledContainers(exporter.artifactMtime)

    assert orphan.restarts == 0
    assert partial.restarts == 1


# --------------------------------------------------------------------------------------
# The rule, the cooldown and its deferral, against a stub lookup.


def test_restart_disabled_never_touches_docker_client():
    settings = _make_settings(restartContainers=False)
    manager = DockerManager(settings=settings)

    with patch(CREATE_CLIENT) as from_env:
        manager.restartLabeledContainers(_always_newer)

    from_env.assert_not_called()


def test_client_factory_builds_from_env_with_the_cli_context_switched_off():
    manager = DockerManager(settings=_make_settings())

    with patch("traefik_certificate_exporter.libs.docker.docker.from_env") as from_env:
        client = manager._create_client()

    from_env.assert_called_once_with(use_context=False)
    assert client is from_env.return_value


def test_restarts_container_whose_label_matches_a_processed_domain():
    """Updated for ADR-0045: "matches" now means a labeled domain's artifact is newer
    than the container's start; the lookup replaces the domain list."""
    manager = DockerManager(settings=_make_settings())
    matching = FakeContainer("abc123", "example.test,other.test")
    client = FakeClient(matching)

    with patch(CREATE_CLIENT, return_value=client):
        manager.restartLabeledContainers(
            lambda d: time.time() if d == "example.test" else None
        )

    # `ignore_removed`: a container removed between list and inspect must not abort the pass.
    assert client.containers.listCalls == [
        {"filters": {"label": DOCKER_LABEL}, "ignore_removed": True}
    ]
    assert matching.restarts == 1


def test_does_not_restart_container_whose_label_does_not_match():
    """Updated for ADR-0045: a container none of whose labeled domains has an artifact
    is not a candidate."""
    manager = DockerManager(settings=_make_settings())
    non_matching = FakeContainer("def456", "unrelated.test")

    with patch(CREATE_CLIENT, return_value=FakeClient(non_matching)):
        manager.restartLabeledContainers(
            lambda d: time.time() if d == "example.test" else None
        )

    assert non_matching.restarts == 0


def test_dry_run_does_not_call_restart():
    manager = DockerManager(settings=_make_settings(dryRun=True))
    matching = FakeContainer("abc123", "example.test")

    with patch(CREATE_CLIENT, return_value=FakeClient(matching)):
        manager.restartLabeledContainers(_always_newer)

    assert matching.restarts == 0


def test_a_lookup_that_knows_no_domain_restarts_nothing():
    """Was `test_none_domains_is_treated_as_empty_list_without_raising`. The domain-list
    parameter is gone (ADR-0045); its empty case is now a lookup that finds nothing."""
    manager = DockerManager(settings=_make_settings())
    container = FakeContainer("abc123", "example.test")

    with patch(CREATE_CLIENT, return_value=FakeClient(container)):
        manager.restartLabeledContainers(lambda _d: None)

    assert container.restarts == 0


def test_docker_client_error_is_caught_and_logged_not_raised(caplog):
    manager = DockerManager(settings=_make_settings())

    with patch(CREATE_CLIENT, side_effect=RuntimeError("daemon unreachable")):
        manager.restartLabeledContainers(_always_newer)

    assert "Failed restarting containers" in caplog.text


def test_second_pass_inside_the_cooldown_window_does_not_restart_again(timers):
    """Not *immediately*; one deferred (ADR-0045: defer, don't drop)."""
    manager = DockerManager(settings=_make_settings())
    matching = FakeContainer("abc123", "example.test,other.test")

    with patch(CREATE_CLIENT, return_value=FakeClient(matching)):
        manager.restartLabeledContainers(_always_newer)
        manager.restartLabeledContainers(_always_newer)

    assert matching.restarts == 1
    assert len(timers) == 1


def test_a_renewal_after_the_cooldown_restarts_again_even_with_identical_domains(
    clock, timers
):
    """The regression that killed name-based change detection.

    A renewal replaces key material and keeps the domain name. With the file-mtime rule a
    renewal is a newer file, so the container restarts again once the window is over.
    """
    manager = DockerManager(settings=_make_settings())
    matching = FakeContainer("abc123", "example.test", startedAt=clock[0] - 100)

    with patch(CREATE_CLIENT, return_value=FakeClient(matching)):
        manager.restartLabeledContainers(_always_newer)
        clock[0] += RESTART_COOLDOWN_SECONDS + 1
        manager.restartLabeledContainers(_always_newer)

    assert matching.restarts == 2
    assert timers == []


def test_cooldown_skip_is_logged_at_info_so_an_operator_can_see_it(caplog, timers):
    """The message now says "deferred": the restart is scheduled, not skipped."""
    manager = DockerManager(settings=_make_settings())
    matching = FakeContainer("abc123", "example.test")

    with (
        caplog.at_level("INFO"),
        patch(CREATE_CLIENT, return_value=FakeClient(matching)),
    ):
        manager.restartLabeledContainers(_always_newer)
        manager.restartLabeledContainers(_always_newer)

    infos = [r.getMessage() for r in caplog.records if r.levelno == logging.INFO]
    assert any(
        "Deferring restart of container abc123: cooldown active" in m
        and "one restart scheduled" in m
        for m in infos
    ), infos


def test_the_cooldown_is_per_container_not_global():
    manager = DockerManager(settings=_make_settings())
    first = FakeContainer("abc123", "example.test")
    second = FakeContainer("def456", "example.test")

    with patch(CREATE_CLIENT, return_value=FakeClient(first, second)):
        manager.restartLabeledContainers(_always_newer)

    assert (first.restarts, second.restarts) == (1, 1)


def test_failed_restart_does_not_start_a_cooldown(timers):
    manager = DockerManager(settings=_make_settings())
    matching = FakeContainer(
        "abc123", "example.test", restartErrors=[RuntimeError("boom")]
    )

    with patch(CREATE_CLIENT, return_value=FakeClient(matching)):
        manager.restartLabeledContainers(_always_newer)
        manager.restartLabeledContainers(_always_newer)

    assert matching.restarts == 1, (
        "the second request restarted at once: the failure earned no floor"
    )
    assert len(timers) == 1, "only the retry armed by the failure (ADV-1)"


def test_restart_failure_does_not_abort_the_remaining_containers():
    manager = DockerManager(settings=_make_settings())
    failing = FakeContainer(
        "abc123", "example.test", restartErrors=[RuntimeError("boom")]
    )
    healthy = FakeContainer("def456", "example.test")

    with patch(CREATE_CLIENT, return_value=FakeClient(failing, healthy)):
        manager.restartLabeledContainers(_always_newer)

    assert healthy.restarts == 1


def test_dry_run_never_records_state_so_it_never_suppresses_a_real_restart(timers):
    manager = DockerManager(settings=_make_settings(dryRun=True))
    matching = FakeContainer("abc123", "example.test")

    with patch(CREATE_CLIENT, return_value=FakeClient(matching)):
        manager.restartLabeledContainers(_always_newer)
        manager.restartLabeledContainers(_always_newer)

    assert matching.restarts == 0
    assert manager._DockerManager__lastRestart == {}
    assert timers == []


def test_concurrent_passes_never_restart_the_same_container_twice(timers):
    """The reserve-then-restart step has to be indivisible: drains run on timer threads
    while the run-at-start pass runs on the main thread. The losers defer; they coalesce
    into one trailing restart."""
    manager = DockerManager(settings=_make_settings())
    started = threading.Event()

    class _SlowContainer(FakeContainer):
        def restart(self):
            # Hold the call open long enough that every other thread has made its
            # decision while this one is still in flight.
            started.set()
            time.sleep(0.2)
            super().restart()

    matching = _SlowContainer("abc123", "example.test")
    lookup = _at(time.time() + 3600)

    with patch(CREATE_CLIENT, return_value=FakeClient(matching)):
        threads = [
            threading.Thread(target=manager.restartLabeledContainers, args=(lookup,))
            for _ in range(4)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)

    assert started.is_set()
    assert matching.restarts == 1
    assert len(timers) == 1


def test_vanished_container_is_logged_at_info_and_the_loop_continues(caplog):
    manager = DockerManager(settings=_make_settings())
    gone = FakeContainer(
        "abc123",
        "example.test",
        restartErrors=[docker.errors.NotFound("No such container: abc123")],
    )
    healthy = FakeContainer("def456", "example.test")

    with (
        caplog.at_level("INFO"),
        patch(CREATE_CLIENT, return_value=FakeClient(gone, healthy)),
    ):
        manager.restartLabeledContainers(_always_newer)

    assert healthy.restarts == 1
    assert "container gone" in caplog.text
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]
    # The vanished container never earned a cooldown.
    assert "abc123" not in manager._DockerManager__lastRestart


def test_expected_engine_errors_are_logged_without_traceback(caplog, monkeypatch):
    """AC 8: `DockerException` and `OSError` (which `requests.RequestException` subclasses)
    are expected operational failures: one ERROR naming the endpoint, no traceback."""
    endpoint = "tcp://engine.invalid:2375"
    monkeypatch.setenv("DOCKER_HOST", endpoint)

    for error in (
        docker.errors.DockerException("engine said no"),
        OSError("connection refused"),
    ):
        caplog.clear()
        manager = DockerManager(settings=_make_settings())

        with patch(CREATE_CLIENT, side_effect=error):
            manager.restartLabeledContainers(_always_newer)

        errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
        assert len(errors) == 1, [r.getMessage() for r in errors]
        assert endpoint in errors[0].getMessage()
        assert str(error) in errors[0].getMessage()
        assert errors[0].exc_info is None, f"traceback logged for {error!r}"


def test_unexpected_errors_keep_the_traceback(caplog):
    manager = DockerManager(settings=_make_settings())

    with patch(CREATE_CLIENT, side_effect=RuntimeError("bug")):
        manager.restartLabeledContainers(_always_newer)

    errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert len(errors) == 1
    assert errors[0].exc_info is not None


def test_started_at_parses_docker_nanosecond_utc_form():
    container = FakeContainer("c1", "a", startedAt="2026-10-11T08:15:30.123456789Z")
    expected = datetime.datetime(
        2026, 10, 11, 8, 15, 30, 123456, tzinfo=datetime.timezone.utc
    ).timestamp()

    assert DockerManager._startedAt(container) == expected


# --------------------------------------------------------------------------------------
# Defer, don't drop.


def test_restart_inside_cooldown_is_deferred_coalesced_and_fires(timers, clock):
    manager = DockerManager(settings=_make_settings())
    container = FakeContainer("c1", "a.example.test", startedAt=clock[0] - 100)
    client = FakeClient(container)

    with patch(CREATE_CLIENT, return_value=client):
        manager.restartLabeledContainers(_always_newer)
        clock[0] += 30
        manager.restartLabeledContainers(_always_newer)

        assert container.restarts == 1
        assert len(timers) == 1
        timer = timers[0]
        assert timer.started and timer.daemon
        assert timer.interval == pytest.approx(RESTART_COOLDOWN_SECONDS - 30 + 1)

        clock[0] += 30
        manager.restartLabeledContainers(_always_newer)
        assert len(timers) == 1, "a third request inside the window must coalesce"

        clock[0] = clock[0] - 60 + RESTART_COOLDOWN_SECONDS + 1
        timer.fire()

    assert container.restarts == 2


def test_rate_floor_applies_after_deferred_restart(timers, clock):
    manager = DockerManager(settings=_make_settings())
    container = FakeContainer("c1", "a.example.test", startedAt=clock[0] - 100)

    with patch(CREATE_CLIENT, return_value=FakeClient(container)):
        manager.restartLabeledContainers(_always_newer)  # immediate
        clock[0] += 10
        manager.restartLabeledContainers(_always_newer)  # deferred
        clock[0] += timers[0].interval
        timers[0].fire()
        assert container.restarts == 2
        assert manager._DockerManager__lastRestart["c1"] == clock[0]

        clock[0] += 10
        manager.restartLabeledContainers(_always_newer)

    assert container.restarts == 2, (
        "the request after a trailing restart was not floored"
    )
    assert len(timers) == 2


def test_deferred_restart_skipped_when_slot_reserved_since_arming(
    timers, clock, caplog
):
    """The floor holds at fire time: a pass that claimed the slot after the timer was
    armed (its restart still in flight, `StartedAt` not yet moved) wins."""
    manager = DockerManager(settings=_make_settings())
    container = FakeContainer("c1", "a.example.test", startedAt=clock[0] - 100)

    with (
        caplog.at_level("INFO"),
        patch(CREATE_CLIENT, return_value=FakeClient(container)),
    ):
        manager.restartLabeledContainers(_always_newer)
        manager.restartLabeledContainers(_always_newer)
        clock[0] += RESTART_COOLDOWN_SECONDS
        allowed, _reason, _previous = manager._reserveRestart("c1", clock[0])
        assert allowed
        clock[0] += 0.5
        timers[0].fire()

    assert container.restarts == 1
    assert "restarted within the window" in caplog.text


def test_deferred_restart_skipped_when_label_removed(timers, clock, caplog):
    manager = DockerManager(settings=_make_settings())
    container = FakeContainer("c1", "a.example.test", startedAt=clock[0] - 100)

    with (
        caplog.at_level("INFO"),
        patch(CREATE_CLIENT, return_value=FakeClient(container)),
    ):
        manager.restartLabeledContainers(_always_newer)
        manager.restartLabeledContainers(_always_newer)
        container.labels = {DOCKER_LABEL: "unrelated.example.test"}
        timers[0].fire()

    assert container.restarts == 1
    assert "label no longer matches" in caplog.text


def test_deferred_restart_skipped_when_container_restarted_externally(
    timers, clock, caplog
):
    manager = DockerManager(settings=_make_settings())
    container = FakeContainer("c1", "a.example.test", startedAt=clock[0] - 100)
    filesWritten = _at(clock[0] + 10)

    with (
        caplog.at_level("INFO"),
        patch(CREATE_CLIENT, return_value=FakeClient(container)),
    ):
        manager.restartLabeledContainers(filesWritten)
        clock[0] += 20
        manager.restartLabeledContainers(filesWritten)
        assert len(timers) == 1
        # Someone else restarted it after the files were written.
        container.attrs["State"]["StartedAt"] = _rfc3339(clock[0] + 30)
        timers[0].fire()

    assert container.restarts == 1
    assert "already started after the certificate was written" in caplog.text


def test_deferred_restart_skipped_when_container_no_longer_running(
    timers, clock, caplog
):
    """SD-01-2: Docker's restart endpoint starts a stopped container, so a trailing
    restart must not fire for a container the operator stopped inside the window."""
    manager = DockerManager(settings=_make_settings())
    container = FakeContainer("c1", "a.example.test", startedAt=clock[0] - 100)
    filesWritten = _at(clock[0] + 10)

    with (
        caplog.at_level("INFO"),
        patch(CREATE_CLIENT, return_value=FakeClient(container)),
    ):
        manager.restartLabeledContainers(_always_newer)
        clock[0] += 20
        manager.restartLabeledContainers(filesWritten)
        assert len(timers) == 1
        container.status = "exited"  # stopped by the operator; StartedAt unchanged
        clock[0] += timers[0].interval
        timers[0].fire()

    assert container.restarts == 1
    assert "Skipping deferred restart of container c1: not running" in caplog.text


def test_failed_restart_is_retried_without_a_further_store_event(timers, clock, caplog):
    """ADV-1: a failed restart arms a retry through the deferred path, one cooldown
    window later, with no new pass needed."""
    manager = DockerManager(settings=_make_settings())
    container = FakeContainer(
        "c1",
        "a.example.test",
        startedAt=clock[0] - 100,
        restartErrors=[docker.errors.APIError("daemon restarting")],
    )
    filesWritten = _at(clock[0] - 50)

    with (
        caplog.at_level("INFO"),
        patch(CREATE_CLIENT, return_value=FakeClient(container)),
    ):
        manager.restartLabeledContainers(filesWritten)  # fails
        assert container.restarts == 0
        assert len(timers) == 1
        assert timers[0].interval == pytest.approx(RESTART_COOLDOWN_SECONDS + 1)
        clock[0] += timers[0].interval
        timers[0].fire()  # no store event in between

    assert container.restarts == 1
    assert len(timers) == 1
    assert "Retrying restart of container c1" in caplog.text


def test_failed_restart_retries_are_bounded(timers, clock, caplog):
    manager = DockerManager(settings=_make_settings())
    container = FakeContainer(
        "c1",
        "a.example.test",
        startedAt=clock[0] - 100,
        restartErrors=[docker.errors.APIError("down")] * 20,
    )
    filesWritten = _at(clock[0] - 50)

    with (
        caplog.at_level("INFO"),
        patch(CREATE_CLIENT, return_value=FakeClient(container)),
    ):
        manager.restartLabeledContainers(filesWritten)
        fired = 0
        while fired < len(timers):
            clock[0] += timers[fired].interval
            timers[fired].fire()
            fired += 1

    assert container.restarts == 0
    assert len(timers) == docker_module.RESTART_RETRY_LIMIT
    assert "Giving up retrying restart of container c1" in caplog.text
    assert manager._DockerManager__pending == {}


def test_failed_restart_retry_skips_a_stopped_container(timers, clock, caplog):
    manager = DockerManager(settings=_make_settings())
    container = FakeContainer(
        "c1",
        "a.example.test",
        startedAt=clock[0] - 100,
        restartErrors=[docker.errors.APIError("down")],
    )

    with (
        caplog.at_level("INFO"),
        patch(CREATE_CLIENT, return_value=FakeClient(container)),
    ):
        manager.restartLabeledContainers(_at(clock[0] - 50))
        container.status = "exited"
        clock[0] += timers[0].interval
        timers[0].fire()

    assert container.restarts == 0
    assert "not running" in caplog.text


def test_deferred_restart_container_gone_is_info(timers, clock, caplog):
    manager = DockerManager(settings=_make_settings())
    container = FakeContainer("c1", "a.example.test", startedAt=clock[0] - 100)
    client = FakeClient(container)

    with caplog.at_level("INFO"), patch(CREATE_CLIENT, return_value=client):
        manager.restartLabeledContainers(_always_newer)
        manager.restartLabeledContainers(_always_newer)
        client.containers.gone.add("c1")
        timers[0].fire()  # must not raise

    assert "c1: gone" in caplog.text
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert manager._DockerManager__pending == {}


def test_failed_deferred_restart_releases_and_next_pass_recovers(timers, clock, caplog):
    manager = DockerManager(settings=_make_settings())
    container = FakeContainer(
        "c1",
        "a.example.test",
        startedAt=clock[0] - 100,
        restartErrors=[None, docker.errors.APIError("engine refused")],
    )
    filesWritten = _at(clock[0] + 10)

    with patch(CREATE_CLIENT, return_value=FakeClient(container)):
        manager.restartLabeledContainers(_always_newer)  # immediate, succeeds
        firstRestartAt = manager._DockerManager__lastRestart["c1"]
        clock[0] += 20
        manager.restartLabeledContainers(filesWritten)  # deferred
        clock[0] += timers[0].interval
        timers[0].fire()  # fails

        assert container.restarts == 1
        errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
        assert len(errors) == 1 and "engine refused" in errors[0].getMessage()
        # Released exactly as the immediate path does; a bounded retry is armed (ADV-1).
        assert manager._DockerManager__lastRestart["c1"] == firstRestartAt
        assert len(timers) == 2

        # The failed restart left `StartedAt` older than the files: the next pass
        # (outside the window) restarts it by the same rule.
        manager.restartLabeledContainers(filesWritten)

    assert container.restarts == 2


def test_dry_run_logs_would_restart_and_arms_nothing(timers, clock, caplog):
    manager = DockerManager(settings=_make_settings(dryRun=True))
    fresh = FakeContainer("c-fresh", "a.example.test", startedAt=clock[0] - 100)
    floored = FakeContainer("c-floored", "a.example.test", startedAt=clock[0] - 100)
    manager._DockerManager__lastRestart["c-floored"] = clock[0] - 10

    with (
        caplog.at_level("INFO"),
        patch(CREATE_CLIENT, return_value=FakeClient(fresh, floored)),
    ):
        manager.restartLabeledContainers(_always_newer)

    assert "[DRYRUN] would restart c-fresh" in caplog.text
    assert (
        "[DRYRUN] would schedule deferred restart of c-floored in 291s" in caplog.text
    )
    assert (fresh.restarts, floored.restarts) == (0, 0)
    assert timers == []
    assert manager._DockerManager__lastRestart == {"c-floored": clock[0] - 10}


def test_cancel_prevents_captured_callback_from_restarting(timers, clock, caplog):
    manager = DockerManager(settings=_make_settings())
    container = FakeContainer("c1", "a.example.test", startedAt=clock[0] - 100)
    manager.cancel()  # safe before any timer exists

    with (
        caplog.at_level("INFO"),
        patch(CREATE_CLIENT, return_value=FakeClient(container)),
    ):
        manager.restartLabeledContainers(_always_newer)
        manager.restartLabeledContainers(_always_newer)
        captured = timers[0]
        manager.cancel()
        manager.cancel()  # idempotent
        captured.fire()

    assert captured.cancelled
    assert container.restarts == 1
    assert (
        "Cancelled 1 pending deferred restart(s); the next pass restarts them"
        in caplog.text
    )


def test_next_pass_recovers_cancelled_deferral(tmp_path, timers):
    settings = _env(tmp_path, _store(acme_v2_certificate("a.example.test")))
    container = FakeContainer("c1", "a.example.test")
    client = FakeClient(container)
    exporter, manager = AcmeCertificateExporter(settings), DockerManager(settings)
    _pass(exporter, manager, client)
    assert container.restarts == 1

    # Another rotation inside the window: deferred, then cancelled at shutdown.
    _set_mtime(_domain_files(tmp_path, "a.example.test"), time.time() + 10)
    _pass(exporter, manager, client)
    assert len(timers) == 1
    manager.cancel()

    # The next process's start-up pass.
    _pass(AcmeCertificateExporter(settings), DockerManager(settings), client)

    assert container.restarts == 2


def test_cancel_racing_fire_does_not_restart(timers, clock):
    """`cancel()` lands while the timer thread is already re-checking the container."""
    manager = DockerManager(settings=_make_settings())
    container = FakeContainer("c1", "a.example.test", startedAt=clock[0] - 100)
    client = FakeClient(container)

    with patch(CREATE_CLIENT, return_value=client):
        manager.restartLabeledContainers(_always_newer)
        manager.restartLabeledContainers(_always_newer)
        realGet = client.containers.get

        def getThenShutdown(cid):
            manager.cancel()
            return realGet(cid)

        client.containers.get = getThenShutdown
        clock[0] += timers[0].interval
        timers[0].fire()

    assert container.restarts == 1


def test_deferred_restart_carries_arming_correlation_id(timers, clock, caplog):
    manager = DockerManager(settings=_make_settings())
    container = FakeContainer("c1", "a.example.test", startedAt=clock[0] - 100)

    with (
        caplog.at_level("INFO"),
        patch(CREATE_CLIENT, return_value=FakeClient(container)),
    ):
        token = set_correlation_id("arming-pass")
        try:
            manager.restartLabeledContainers(_always_newer)
            manager.restartLabeledContainers(_always_newer)
        finally:
            reset_correlation_id(token)
        other = set_correlation_id("some-other-pass")
        try:
            clock[0] += timers[0].interval
            timers[0].fire()
        finally:
            reset_correlation_id(other)

    fired = [
        r
        for r in caplog.records
        if "Restarting container: c1 (deferred)" in r.getMessage()
    ]
    assert len(fired) == 1
    assert fired[0].correlation_id == "arming-pass"


def test_real_timer_fires_deferred_restart_end_to_end(monkeypatch):
    monkeypatch.setattr(docker_module, "RESTART_COOLDOWN_SECONDS", 0.05)
    manager = DockerManager(settings=_make_settings())
    restarted = threading.Event()

    class _Signalling(FakeContainer):
        def restart(self):
            super().restart()
            if self.restarts == 2:
                restarted.set()

    container = _Signalling("c1", "a.example.test")

    with patch(CREATE_CLIENT, return_value=FakeClient(container)):
        manager.restartLabeledContainers(_always_newer)
        manager.restartLabeledContainers(_always_newer)
        pending = manager._DockerManager__pending["c1"]
        assert pending.timer.daemon is True
        assert restarted.wait(timeout=10), "the real timer never fired the restart"

    assert container.restarts == 2
    assert manager._DockerManager__pending == {}


def test_check_logs_info_with_the_api_version_when_the_engine_answers(caplog):
    manager = DockerManager(settings=_make_settings())
    client = MagicMock()
    client.ping.return_value = True
    client.version.return_value = {"ApiVersion": "1.47"}

    with caplog.at_level("INFO"), patch(CREATE_CLIENT, return_value=client):
        assert manager.check() is True

    assert "Docker Engine reachable (API 1.47)" in caplog.text
    client.close.assert_called_once()


def test_check_logs_one_error_naming_the_endpoint_and_never_raises(caplog, monkeypatch):
    monkeypatch.delenv("DOCKER_HOST", raising=False)
    manager = DockerManager(settings=_make_settings())

    with patch(CREATE_CLIENT, side_effect=docker.errors.DockerException("boom")):
        assert manager.check() is False

    errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert len(errors) == 1
    assert "unix:///var/run/docker.sock" in errors[0].getMessage()
    assert "boom" in errors[0].getMessage()
    assert errors[0].exc_info is None


# --------------------------------------------------------------------------------------
# Unmocked: these exercise the real SDK against a socket that does not exist. They are
# the tests that would have caught B1 -- every mocked test above was green while the
# shipped SDK could not talk to any Engine at all.


def test_sdk_ping_on_missing_socket_raises_docker_exception_not_scheme_error(tmp_path):
    # With the default `version=None` the client negotiates the API version while it is
    # constructed, and that is where docker-py wraps the transport failure in a
    # `DockerException` -- so construction sits inside the block. (A client built with a fixed
    # version reaches `ping()`, which raises the raw transport error instead: a
    # `requests.ConnectionError`, i.e. an `OSError`. That is why the product catches both.)
    with pytest.raises(docker.errors.DockerException) as excinfo:
        client = docker.DockerClient(base_url=f"unix://{tmp_path}/missing.sock")
        client.ping()

    assert SCHEME_ERROR not in str(excinfo.value)


def test_restart_with_unreachable_engine_logs_one_error_naming_the_endpoint(
    caplog, monkeypatch, tmp_path
):
    endpoint = f"unix://{tmp_path}/missing.sock"
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("DOCKER_CONFIG", raising=False)
    monkeypatch.delenv("DOCKER_CONTEXT", raising=False)
    monkeypatch.setenv("DOCKER_HOST", endpoint)
    manager = DockerManager(settings=_make_settings(restartContainers=True))

    manager.restartLabeledContainers(_always_newer)  # must not raise

    errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert len(errors) == 1, [r.getMessage() for r in errors]
    assert endpoint in errors[0].getMessage()
    assert SCHEME_ERROR not in caplog.text


def test_client_ignores_docker_cli_context(monkeypatch, tmp_path):
    """A `~/.docker` planted in the service's HOME must not redirect restarts (AC 5)."""
    elsewhere = f"unix://{tmp_path}/elsewhere.sock"
    dockerDir = tmp_path / ".docker"
    metaDir = dockerDir / "contexts" / "meta" / hashlib.sha256(b"elsewhere").hexdigest()
    metaDir.mkdir(parents=True)
    (dockerDir / "config.json").write_text(json.dumps({"currentContext": "elsewhere"}))
    (metaDir / "meta.json").write_text(
        json.dumps(
            {
                "Name": "elsewhere",
                "Metadata": {},
                "Endpoints": {"docker": {"Host": elsewhere, "SkipTLSVerify": False}},
            }
        )
    )
    monkeypatch.setenv("HOME", str(tmp_path))
    for name in ("DOCKER_HOST", "DOCKER_CONFIG", "DOCKER_CONTEXT", "DOCKER_TLS_VERIFY"):
        monkeypatch.delenv(name, raising=False)

    manager = DockerManager(settings=_make_settings())
    # Only the API-version probe is stubbed, so construction does not need a live Engine;
    # endpoint resolution -- the thing under test -- is the real SDK's.
    with patch(
        "docker.api.client.APIClient._retrieve_server_version", return_value="1.44"
    ):
        client = manager._create_client()

    try:
        socketPath = client.api._custom_adapter.socket_path
        assert "elsewhere.sock" not in socketPath
        assert socketPath == "/var/run/docker.sock"
    finally:
        client.close()


def test_logged_endpoint_is_the_endpoint_the_client_targets(monkeypatch, tmp_path):
    """`_endpoint()` restates docker-py's env-or-default rule for log lines; pin the two
    together so a log line can never name a different daemon than the one contacted."""
    for name in ("DOCKER_CONFIG", "DOCKER_CONTEXT", "DOCKER_TLS_VERIFY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    manager = DockerManager(settings=_make_settings())

    for dockerHost in (f"unix://{tmp_path}/configured.sock", None):
        if dockerHost is None:
            monkeypatch.delenv("DOCKER_HOST", raising=False)
        else:
            monkeypatch.setenv("DOCKER_HOST", dockerHost)
        with patch(
            "docker.api.client.APIClient._retrieve_server_version",
            return_value="1.44",
        ):
            client = manager._create_client()
        try:
            assert manager._endpoint() == (
                "unix://" + client.api._custom_adapter.socket_path
            )
        finally:
            client.close()
