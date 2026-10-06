"""The watch handler's debounce window: what it coalesces, and what it must not lose.

Both properties here were found by the Epic 10 architecture gate as defects in shipping
code, and neither had a test. They are asserted by driving the real handler, because what
matters is the interaction between `handleEvent`'s lock and `doTheWork`'s exit paths.
"""

import logging
import threading
import time
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from traefik_certificate_exporter.libs import certificate_exporter
from traefik_certificate_exporter.libs.certificate_exporter import (
    AcmeCertificateFileHandler,
)


def _event(path: str):
    return SimpleNamespace(src_path=path, is_directory=False)


def _handler(exporter, *, restart=False, **overrides):
    """Build the handler against a REAL `Settings`, not a hand-listed namespace.

    An earlier version listed the four fields the handler happened to read, so adding a
    setting it reads broke every test in this file with an `AttributeError` rather than at
    a designed seam. Deriving the defaults from the dataclass signature means a new field
    arrives with its own default and only a test that cares has to mention it.
    """
    import inspect

    from traefik_certificate_exporter.libs.settings import Settings

    blank = {
        "dataPath": None,
        "fileSpec": "*.json",
        "outputPath": None,
        "resolverInPathName": False,
        "traefikResolverId": "",
        "flat": False,
        "dryRun": False,
        "restartContainers": restart,
        "domains": {"include": [], "exclude": []},
        "watchForChanges": False,
        "runAtStart": False,
        "watchInterval": 60,
        "pkcs12Passphrase": None,
    }
    required = {
        name
        for name, param in inspect.signature(Settings.__init__).parameters.items()
        if param.default is inspect.Parameter.empty and name != "self"
    }
    missing = required - blank.keys()
    assert not missing, (
        f"Settings gained required fields this fixture does not supply: {sorted(missing)}"
    )

    settings = Settings(**blank, **overrides)
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


class _InjectingLock:
    """A real lock that delivers a queued event each time it is RELEASED.

    The defect these tests exist for lives in the gap between releasing the lock and
    re-acquiring it, so the injection point has to be the release itself. Nothing about
    the handler is faked -- this is the real `threading.Lock` with a probe around it.
    """

    def __init__(self, real, deliver, path, queue_is_empty):
        self._real = real
        self._deliver = deliver
        self._path = path
        self._queue_is_empty = queue_is_empty
        self._fired = False

    def __enter__(self):
        return self._real.__enter__()

    def __exit__(self, *exc):
        # Fire on the release that follows observing the queue EMPTY -- the only window
        # where the old code had cleared nothing yet and had already stopped looping.
        # Firing on any earlier release just gets drained by the next iteration, which is
        # the drain working correctly and proves nothing.
        should_fire = not self._fired and self._queue_is_empty()
        # Guarded by `_queue_is_empty` alone this fires right after `clear()`, while the
        # drain is still about to process what it just popped -- and the next iteration
        # collects the injected path correctly, proving nothing. It has to be the release
        # that follows observing the queue genuinely empty, which is only distinguishable
        # once at least one export has completed.
        result = self._real.__exit__(*exc)
        if should_fire:
            self._fired = True
            self._deliver(self._path)
        return result


def test_no_path_is_left_pending_with_nothing_scheduled_to_collect_it():
    """The invariant: never "work outstanding and no drain running or armed".

    The first version of this fix broke out of the `with` block when it found the queue
    empty and cleared `isWaiting` in a `finally` -- releasing the lock in between. An
    event delivered in that window was recorded, saw the flag still set, armed no timer,
    and was then orphaned when the flag cleared. It is the same "never exported until an
    unrelated future event" outcome the drain was written to remove, in a smaller window.
    """
    exporter = MagicMock()
    exporter.exportCertificatesForFile.return_value = ["example.com"]
    handler = _handler(exporter)

    handler.handleEvent(_event("/data/first.json"))
    handler.timer.cancel()

    handler.lock = _InjectingLock(
        handler.lock,
        lambda p: handler.handleEvent(_event(p)),
        "/data/racy.json",
        lambda: (
            not handler.pendingPaths
            and exporter.exportCertificatesForFile.call_count >= 1
        ),
    )
    handler.doTheWork()
    if handler.timer is not None:
        handler.timer.cancel()

    assert not (handler.pendingPaths and not handler.isWaiting), (
        f"orphaned: {handler.pendingPaths} pending, isWaiting={handler.isWaiting}, "
        "so nothing is running or armed to collect them"
    )


def test_a_base_exception_clears_the_flag_and_re_arms_for_what_is_left():
    """`Exception` is swallowed per path, so only a `BaseException` reaches the unwinding
    path -- which is exactly why the earlier test of this property proved nothing. A
    KeyboardInterrupt on the Timer thread must not strand the flag, and the paths already
    taken off the queue must go back on it.
    """
    exporter = MagicMock()
    handler = _handler(exporter)
    exporter.exportCertificatesForFile.side_effect = KeyboardInterrupt

    handler.handleEvent(_event("/data/a.json"))
    handler.handleEvent(_event("/data/b.json"))
    handler.timer.cancel()

    with pytest.raises(KeyboardInterrupt):
        handler.doTheWork()
    if handler.timer is not None:
        handler.timer.cancel()

    assert handler.pendingPaths == {"/data/a.json", "/data/b.json"}, (
        f"paths taken off the queue were lost on unwind: {handler.pendingPaths}"
    )
    assert handler.isWaiting is True, "re-armed work must leave the flag set"


def test_the_real_timer_thread_runs_a_drain_end_to_end(monkeypatch):
    """Every other test drives `doTheWork` on the main thread. This one lets the actual
    `threading.Timer` fire, which is the only place the production path runs.
    """
    monkeypatch.setattr(certificate_exporter, "WATCH_DEBOUNCE_SECONDS", 0.05)

    exporter = MagicMock()
    exporter.exportCertificatesForFile.return_value = ["example.com"]
    handler = _handler(exporter)

    handler.handleEvent(_event("/data/acme.json"))
    handler.timer.join(5)

    assert exporter.exportCertificatesForFile.call_args_list[0].args[0] == (
        "/data/acme.json"
    )
    assert handler.isWaiting is False
    assert handler.pendingPaths == set()


###########################################################################################
# Correlation id (BL-E010-001) and shutdown cancellation (BL-E010-002).


def test_one_drain_tags_every_hop_with_the_same_correlation_id(caplog):
    """The join key an operator greps for: the watch event, the export, the post-export
    command and the notification must all carry one value for one drain pass."""
    exporter = MagicMock()
    exporter.exportCertificatesForFile.return_value = ["example.com"]
    handler = _handler(
        exporter, postExportCommand=None, appriseUrls=["json://localhost/"]
    )

    seen = {}

    def capture(urls, domains, dryRun, correlationId=None):
        seen["notify"] = correlationId

    with (
        caplog.at_level(logging.DEBUG),
        patch.object(certificate_exporter, "send_export_notifications", capture),
    ):
        handler.handleEvent(_event("/data/acme.json"))
        armed = handler.correlationId
        handler.timer.cancel()
        handler.doTheWork(armed)

    assert armed, "arming a debounce window must mint a correlation id"
    assert seen["notify"] == armed, (
        "the notification hop ran under a different id than the drain that caused it"
    )

    tagged = {
        r.correlation_id
        for r in caplog.records
        if r.name.startswith("traefik_certificate_exporter")
    }
    assert tagged == {armed}, (
        f"log lines for one pass carried more than one correlation id: {tagged}"
    )


def test_the_correlation_id_is_a_plain_uuid_carrying_no_domain_or_path():
    """It is logged everywhere and exported to the post-export hook, so it must not be
    derived from anything a log sink should not see."""
    exporter = MagicMock()
    handler = _handler(exporter)

    handler.handleEvent(_event("/data/secret-customer.json"))
    handler.timer.cancel()

    uuid.UUID(handler.correlationId)
    assert "secret-customer" not in handler.correlationId


def test_events_coalesced_into_one_window_share_that_windows_id():
    exporter = MagicMock()
    handler = _handler(exporter)

    handler.handleEvent(_event("/data/a.json"))
    first = handler.correlationId
    handler.handleEvent(_event("/data/b.json"))
    handler.timer.cancel()

    assert handler.correlationId == first, (
        "a second file joining the open window started a second pass id"
    )


def test_a_drain_run_without_an_id_still_runs(caplog):
    """Degrade, never fail: a call site that forgets to thread the id through must not
    take the export pass down with it."""
    exporter = MagicMock()
    exporter.exportCertificatesForFile.return_value = ["example.com"]
    handler = _handler(exporter)

    handler.handleEvent(_event("/data/acme.json"))
    handler.timer.cancel()
    with caplog.at_level(logging.DEBUG):
        handler.doTheWork()

    assert exporter.exportCertificatesForFile.called
    assert all(getattr(r, "correlation_id", None) for r in caplog.records), (
        "a record was emitted with no correlation_id attribute at all"
    )


def test_re_armed_work_gets_a_new_id_that_names_the_interrupted_one(caplog):
    exporter = MagicMock()
    exporter.exportCertificatesForFile.side_effect = KeyboardInterrupt
    handler = _handler(exporter)

    handler.handleEvent(_event("/data/a.json"))
    interrupted = handler.correlationId
    handler.timer.cancel()

    with caplog.at_level(logging.INFO), pytest.raises(KeyboardInterrupt):
        handler.doTheWork(interrupted)
    if handler.timer is not None:
        handler.timer.cancel()

    assert handler.correlationId != interrupted
    assert any(
        interrupted in r.getMessage() and handler.correlationId in r.getMessage()
        for r in caplog.records
    ), "the re-armed pass cannot be joined back to the one it inherited work from"


def test_cancel_is_a_no_op_before_any_event_has_fired(caplog):
    """`self.timer` is None until the first watched-file event -- the "start it, then
    Ctrl-C to check it came up" path. It must not raise (ADR-0026)."""
    handler = _handler(MagicMock())
    assert handler.timer is None

    with caplog.at_level(logging.INFO):
        handler.cancel()

    assert any("no export drain was pending" in r.getMessage() for r in caplog.records)


def test_cancel_stops_an_armed_drain_before_it_fires(caplog):
    exporter = MagicMock()
    handler = _handler(exporter)

    handler.handleEvent(_event("/data/acme.json"))
    armed = handler.correlationId

    with caplog.at_level(logging.INFO):
        handler.cancel()

    handler.timer.join(5)
    assert not handler.timer.is_alive()
    assert not exporter.exportCertificatesForFile.called, (
        "a cancelled drain still ran; shutdown left work in flight"
    )
    cancelled = [
        r
        for r in caplog.records
        if "cancelled the pending export drain" in r.getMessage()
    ]
    assert cancelled, (
        "a truncated run is indistinguishable from a clean exit in the logs"
    )
    assert cancelled[0].levelno == logging.INFO
    assert cancelled[0].correlation_id == armed


def test_cancel_after_a_completed_drain_reports_a_clean_exit(caplog):
    """`Timer.cancel()` after firing is a documented no-op, so the code falls through --
    and must not then label the ordinary clean shutdown as a truncated run, stamped with
    the correlation id of a pass that actually succeeded."""
    exporter = MagicMock()
    exporter.exportCertificatesForFile.return_value = ["example.com"]
    handler = _handler(exporter)

    handler.handleEvent(_event("/data/acme.json"))
    handler.timer.cancel()
    handler.doTheWork(handler.correlationId)

    with caplog.at_level(logging.INFO):
        handler.cancel()

    messages = [r.getMessage() for r in caplog.records]
    assert any("no export drain was pending" in m for m in messages), messages
    assert not any("cancelled the pending export drain" in m for m in messages), (
        "a pass that ran to completion was logged as cancelled"
    )


def test_drain_threads_are_daemons_so_shutdown_is_actually_bounded():
    """Bounding `cancel()`'s own join bounds nothing on its own: CPython joins every
    non-daemon thread at interpreter exit, so a drain inside its 30s post-export hook
    would hold the process well past `docker stop`'s grace and be SIGKILLed anyway.
    Abandoning it is safe only because every certificate file is written atomically."""
    handler = _handler(MagicMock())

    handler.handleEvent(_event("/data/acme.json"))
    try:
        assert handler.timer.daemon is True
    finally:
        handler.cancel()


def test_an_event_arriving_after_cancel_does_not_arm_a_new_drain(caplog):
    """watchdog's dispatcher can still deliver an event it had in hand. Arming for it
    reinstates the orphaned thread shutdown just removed, and runs a full export pass
    after the process said it was stopping."""
    exporter = MagicMock()
    exporter.exportCertificatesForFile.return_value = ["example.com"]
    handler = _handler(exporter)

    handler.handleEvent(_event("/data/acme.json"))
    handler.timer.cancel()
    handler.doTheWork(handler.correlationId)
    handler.cancel()
    timerAtShutdown = handler.timer

    with caplog.at_level(logging.DEBUG):
        handler.handleEvent(_event("/data/late.json"))

    assert handler.isWaiting is False
    assert handler.pendingPaths == set()
    assert handler.timer is timerAtShutdown, (
        "shutdown was followed by a fresh drain thread"
    )
    assert any("ignoring change to" in r.getMessage() for r in caplog.records)


def test_an_interrupted_drain_does_not_re_arm_during_shutdown(caplog):
    """The unwind path re-arms whatever the interrupted drain did not finish -- but a
    KeyboardInterrupt mid-drain IS the shutdown, and nothing would cancel the new timer."""
    exporter = MagicMock()
    handler = _handler(exporter)

    def interrupt(_path):
        # The Ctrl-C lands DURING the drain, which is exactly the case the unwind guard
        # exists for: the latch re-check at drain entry cannot have seen it yet.
        handler.shuttingDown = True
        raise KeyboardInterrupt

    exporter.exportCertificatesForFile.side_effect = interrupt

    handler.handleEvent(_event("/data/a.json"))
    handler.handleEvent(_event("/data/b.json"))
    handler.timer.cancel()
    timerAtShutdown = handler.timer

    with caplog.at_level(logging.WARNING), pytest.raises(KeyboardInterrupt):
        handler.doTheWork(handler.correlationId)

    assert handler.isWaiting is False
    assert handler.timer is timerAtShutdown, (
        "the unwind path re-armed a drain during shutdown"
    )
    assert any(
        "will not be exported by this process" in r.getMessage() for r in caplog.records
    ), "work abandoned at shutdown was dropped without saying so"


def test_cancel_does_not_wait_forever_on_a_slow_drain(monkeypatch, caplog):
    """A non-daemon Timer thread stuck in a slow export must not hold the process open
    past the container runtime's grace period."""
    monkeypatch.setattr(certificate_exporter, "WATCH_DEBOUNCE_SECONDS", 0.01)
    monkeypatch.setattr(certificate_exporter, "SHUTDOWN_JOIN_TIMEOUT_SECONDS", 0.1)

    release = threading.Event()
    started = threading.Event()

    def slow(path):
        started.set()
        release.wait(10)
        return ["example.com"]

    exporter = MagicMock()
    exporter.exportCertificatesForFile.side_effect = slow
    handler = _handler(exporter)

    handler.handleEvent(_event("/data/acme.json"))
    assert started.wait(5)

    began = time.monotonic()
    with caplog.at_level(logging.WARNING):
        handler.cancel()
    elapsed = time.monotonic() - began

    release.set()
    handler.timer.join(10)

    assert elapsed < 5, f"shutdown blocked on an in-flight drain for {elapsed:.1f}s"
    assert any("abandoning it" in r.getMessage() for r in caplog.records)


###########################################################################################
# SD-01-1 / AD-02: ADR-0023 Amendment 4a asserts shutdown can tell an armed window from a
# running one. `draining` used to be published part-way into `doTheWork`, so `cancel()`
# could report a pass that in fact ran as "cancelled". Both halves are driven by an
# injected fault -- a drain fired deliberately into the shutdown window.


def test_a_drain_that_starts_after_the_shutdown_latch_exports_nothing(caplog):
    """The latch is set, THEN the timer target runs. Nothing may be exported."""
    exporter = MagicMock()
    exporter.exportCertificatesForFile.return_value = ["example.test"]
    handler = _handler(exporter)

    handler.handleEvent(_event("/data/acme.json"))
    handler.timer.cancel()  # the timer must not also fire on its own
    correlationId = handler.correlationId

    handler.cancel()
    exporter.exportCertificatesForFile.reset_mock()

    with caplog.at_level(logging.WARNING):
        # Exactly what a timer that had already fired would do.
        handler._AcmeCertificateFileHandler__drainWindow(correlationId)

    exporter.exportCertificatesForFile.assert_not_called()
    assert handler.draining is False
    abandoned = [r for r in caplog.records if "abandoning it" in r.getMessage()]
    assert abandoned, "a drain abandoned at the latch said nothing about it"
    assert abandoned[0].correlation_id == correlationId


def test_cancel_never_claims_cancelled_for_a_drain_that_actually_ran(monkeypatch):
    """The race, driven through the REAL timer: `cancel()` lands around the moment the
    debounce fires, over enough iterations that both orderings occur.

    The window is jittered on BOTH sides -- the debounce length and how long the caller
    waits before cancelling -- because an unjittered `cancel()` issued immediately after
    `handleEvent` always wins on a fast machine, which left the drain-already-ran half of
    the race untested.
    """
    monkeypatch.setattr(certificate_exporter, "SHUTDOWN_JOIN_TIMEOUT_SECONDS", 5)

    sawRan = False
    sawCancelled = False

    for i in range(60):
        monkeypatch.setattr(
            certificate_exporter, "WATCH_DEBOUNCE_SECONDS", (i % 10) * 0.002
        )
        delayBeforeCancel = (i // 10) * 0.004

        exporter = MagicMock()
        exporter.exportCertificatesForFile.return_value = ["example.test"]
        handler = _handler(exporter)

        messages: list[str] = []
        handler._AcmeCertificateFileHandler__logger = SimpleNamespace(
            info=lambda m, _s=messages: _s.append(m),
            warning=lambda m, _s=messages: _s.append(m),
            debug=lambda *a, **k: None,
            exception=lambda *a, **k: None,
        )

        handler.handleEvent(_event("/data/acme.json"))
        if delayBeforeCancel:
            time.sleep(delayBeforeCancel)
        handler.cancel()
        handler.timer.join(10)

        ran = exporter.exportCertificatesForFile.called
        saidCancelled = any("cancelled the pending export drain" in m for m in messages)

        assert not (ran and saidCancelled), (
            "cancel() reported a drain that ran as cancelled: " + "; ".join(messages)
        )
        assert handler.drainsRun == (1 if ran else 0), (
            "the drain counter disagrees with whether an export happened"
        )
        sawRan = sawRan or ran
        sawCancelled = sawCancelled or saidCancelled

    assert sawCancelled, "the cancel-before-fire ordering never occurred; test is inert"
    assert sawRan, "the drain-already-ran ordering never occurred; test is inert"
