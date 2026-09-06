"""The watch handler's debounce window: what it coalesces, and what it must not lose.

Both properties here were found by the Epic 10 architecture gate as defects in shipping
code, and neither had a test. They are asserted by driving the real handler, because what
matters is the interaction between `handleEvent`'s lock and `doTheWork`'s exit paths.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from traefik_certificate_exporter.libs.certificate_exporter import (
    AcmeCertificateFileHandler,
)


def _event(path: str):
    return SimpleNamespace(src_path=path, is_directory=False)


def _handler(exporter, *, restart=False):
    settings = SimpleNamespace(
        fileSpec="*.json",
        postExportCommand=None,
        dryRun=False,
        restartContainers=restart,
    )
    return AcmeCertificateFileHandler(
        exporter=exporter, dockerManager=MagicMock(), settings=settings
    )


def test_a_consumer_exception_does_not_strand_the_debounce_flag():
    """`doTheWork` runs on a `threading.Timer` thread, so an exception kills that thread
    silently. Without a `finally`, `isWaiting` stays True for the life of the process and
    `handleEvent` discards every later change -- logging "Certificates changed found in
    file" each time, which reads like the work is happening.
    """
    exporter = MagicMock()
    exporter.exportCertificatesForFile.side_effect = RuntimeError("consumer blew up")
    handler = _handler(exporter)

    handler.handleEvent(_event("/data/acme.json"))
    handler.timer.cancel()
    handler.doTheWork()

    assert handler.isWaiting is False, (
        "isWaiting survived an exception; every subsequent certificate change would be "
        "discarded for the life of the process"
    )

    exporter.exportCertificatesForFile.side_effect = None
    exporter.exportCertificatesForFile.return_value = ["example.com"]
    handler.handleEvent(_event("/data/acme.json"))
    handler.timer.cancel()
    handler.doTheWork()
    assert exporter.exportCertificatesForFile.call_count == 2


def test_a_second_file_changing_in_the_window_is_not_discarded():
    """`handleEvent` matches `fileSpec` across the whole data directory while the worker
    took a single `src_path`, so a change to a *different* acme file during the window was
    dropped outright -- and would not be exported until that file changed again. The
    multi-resolver setup this project documents is exactly multiple files.
    """
    exporter = MagicMock()
    exporter.exportCertificatesForFile.return_value = ["example.com"]
    handler = _handler(exporter)

    handler.handleEvent(_event("/data/acme-http.json"))
    handler.handleEvent(_event("/data/acme-dns.json"))
    handler.timer.cancel()
    handler.doTheWork()

    exported = {c.args[0] for c in exporter.exportCertificatesForFile.call_args_list}
    assert exported == {"/data/acme-http.json", "/data/acme-dns.json"}, (
        f"a distinct acme file was dropped by the debounce: exported {exported}"
    )


def test_the_same_file_twice_in_the_window_is_still_coalesced():
    """The debounce must keep doing its job -- watchdog fires several events per write."""
    exporter = MagicMock()
    exporter.exportCertificatesForFile.return_value = ["example.com"]
    handler = _handler(exporter)

    for _ in range(4):
        handler.handleEvent(_event("/data/acme.json"))
    handler.timer.cancel()
    handler.doTheWork()

    assert exporter.exportCertificatesForFile.call_count == 1


def test_a_change_arriving_during_the_pass_is_drained_not_lost():
    """The tail case. An event arriving while the worker is running cannot schedule a timer,
    because `isWaiting` is still set -- so if the worker does not drain what accumulated, the
    change waits for an unrelated future event to carry it.
    """
    exporter = MagicMock()
    handler = _handler(exporter)
    seen = []

    def export(path):
        seen.append(path)
        if len(seen) == 1:
            handler.handleEvent(_event("/data/late.json"))
        return ["example.com"]

    exporter.exportCertificatesForFile.side_effect = export

    handler.handleEvent(_event("/data/first.json"))
    handler.timer.cancel()
    handler.doTheWork()

    assert seen == ["/data/first.json", "/data/late.json"], (
        f"a change arriving mid-pass was not drained: {seen}"
    )
    assert handler.isWaiting is False


def test_a_directory_event_is_ignored():
    exporter = MagicMock()
    handler = _handler(exporter)
    handler.handleEvent(SimpleNamespace(src_path="/data", is_directory=True))
    assert handler.isWaiting is False
    assert not hasattr(handler, "timer") or handler.timer is None


@pytest.mark.parametrize("restart", [True, False])
def test_container_restart_follows_its_setting_on_the_watch_path(restart):
    exporter = MagicMock()
    exporter.exportCertificatesForFile.return_value = ["example.com"]
    handler = _handler(exporter, restart=restart)
    handler.handleEvent(_event("/data/acme.json"))
    handler.timer.cancel()
    handler.doTheWork()
    assert (
        handler._AcmeCertificateFileHandler__dockerManager.restartLabeledContainers.called
        is restart
    )
