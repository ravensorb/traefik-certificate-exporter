import logging
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from traefik_certificate_exporter import app
from traefik_certificate_exporter.app import require_existing_path
from traefik_certificate_exporter.libs.settings import Settings


def _make_settings(dataPath=None, outputPath=None) -> Settings:
    return Settings(
        dataPath=dataPath,
        fileSpec="*.json",
        outputPath=outputPath,
        resolverInPathName=False,
        traefikResolverId="myresolver",
        flat=False,
        dryRun=False,
        restartContainers=False,
        domains={"include": [], "exclude": []},
        watchForChanges=False,
        runAtStart=False,
        watchInterval=60,
        pkcs12Passphrase=None,
    )


def test_unset_data_path_stays_none_not_the_string_none():
    settings = _make_settings(dataPath=None)

    assert settings.dataPath is None


def test_unset_output_path_stays_none_not_the_string_none():
    settings = _make_settings(outputPath=None)

    assert settings.outputPath is None


def test_configured_data_path_is_still_stringified():
    settings = _make_settings(dataPath="/data")

    assert settings.dataPath == "/data"


def test_require_existing_path_exits_when_path_is_none(caplog):
    with caplog.at_level(logging.ERROR), pytest.raises(SystemExit) as exc_info:
        require_existing_path(logging.getLogger("test"), None, "Data Path")

    assert exc_info.value.code == 1
    assert "not configured" in caplog.text


def test_require_existing_path_exits_when_path_does_not_exist(caplog, tmp_path):
    missing = tmp_path / "does-not-exist"

    with caplog.at_level(logging.ERROR), pytest.raises(SystemExit) as exc_info:
        require_existing_path(logging.getLogger("test"), str(missing), "Data Path")

    assert exc_info.value.code == 1
    assert "does not exist" in caplog.text


def test_require_existing_path_does_not_exit_when_path_exists(tmp_path):
    require_existing_path(logging.getLogger("test"), str(tmp_path), "Data Path")


###########################################################################################
# Shutdown (BL-E010-002): Ctrl-C must cancel the pending debounce, not leave an orphaned
# non-daemon Timer thread for the container runtime's grace period to kill.


def _run_main_until_interrupt(monkeypatch, handler):
    settings = _make_settings(dataPath="/data", outputPath="/certs")
    settings.watchForChanges = True
    settings.runAtStart = False
    settings.watchInterval = 60

    observer = MagicMock()
    calls = []

    monkeypatch.setattr(
        app,
        "parse_args_strict",
        lambda: SimpleNamespace(configfile=None, logginglevel="INFO"),
    )
    monkeypatch.setattr(app, "setup_logging", lambda **kwargs: None)
    monkeypatch.setattr(
        app,
        "globalSettingsMgr",
        SimpleNamespace(loadFromFile=lambda **kwargs: None, settings=settings),
    )
    monkeypatch.setattr(app, "require_existing_path", lambda *a, **k: None)
    monkeypatch.setattr(app, "AcmeCertificateExporter", lambda **kwargs: MagicMock())
    monkeypatch.setattr(app, "DockerManager", lambda **kwargs: MagicMock())
    monkeypatch.setattr(app, "AcmeCertificateFileHandler", lambda **kwargs: handler)
    monkeypatch.setattr(app.watchdog.observers, "Observer", lambda: observer)

    def interrupt(_seconds):
        raise KeyboardInterrupt

    monkeypatch.setattr(app.time, "sleep", interrupt)

    handler.cancel.side_effect = lambda: calls.append("cancel")
    observer.join.side_effect = lambda *a, **k: calls.append("join")

    app.main()
    return observer, calls


def test_ctrl_c_cancels_the_pending_drain_before_joining_the_observer(monkeypatch):
    handler = MagicMock()

    observer, calls = _run_main_until_interrupt(monkeypatch, handler)

    observer.stop.assert_called_once()
    handler.cancel.assert_called_once()
    assert calls == ["cancel", "join"], (
        "the observer was joined before the debounce timer was cancelled, so the pending "
        f"drain outlived shutdown: {calls}"
    )


def test_ctrl_c_before_any_event_does_not_raise(monkeypatch):
    """`timer` is None until the first watched-file event; `main()` must call the
    handler's own guarded `cancel()`, never `handler.timer.cancel()` (ADR-0026)."""
    from traefik_certificate_exporter.libs.certificate_exporter import (
        AcmeCertificateFileHandler,
    )

    settings = _make_settings(dataPath="/data", outputPath="/certs")
    handler = AcmeCertificateFileHandler(
        exporter=MagicMock(), dockerManager=MagicMock(), settings=settings
    )
    assert handler.timer is None

    handler.cancel()


###########################################################################################
# RT-005 / AD-01: SIGTERM is how this process is actually stopped. Its default disposition
# kills the interpreter without raising, so the entire shutdown path -- cancel(), the
# "stopping...." line, every guarantee docs/operational.md documents -- was reachable from
# an interactive Ctrl-C only.


def test_sigterm_reaches_the_shutdown_path_and_exits_cleanly(tmp_path):
    """Injected fault: a real SIGTERM at a real process, not a simulated KeyboardInterrupt."""
    script = shutil.which(
        "traefik-certificate-exporter", path=str(Path(sys.executable).parent)
    )
    assert script, "the console script is not installed in this environment"

    dataPath = tmp_path / "data"
    dataPath.mkdir()
    outputPath = tmp_path / "certs"
    outputPath.mkdir()

    configFile = tmp_path / "config.yml"
    configFile.write_text(
        "settings:\n"
        f"  datapath: {dataPath}\n"
        f"  outputpath: {outputPath}\n"
        "  watchforchanges: true\n"
        "  runatstart: false\n"
        "  watchinterval: 1\n"
    )

    env = dict(os.environ)
    env["TRAEFIK_CERTIFICATE_EXPORTER_LOGGING_CONSOLEONLY"] = "1"
    env["PYTHONUNBUFFERED"] = "1"

    proc = subprocess.Popen(
        [script, "-c", str(configFile)],
        cwd=str(tmp_path),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    try:
        deadline = time.monotonic() + 30
        watching = False
        captured = ""
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                break
            line = proc.stdout.readline()
            captured += line
            if "Watching for changes" in line:
                watching = True
                break
        assert watching, f"the exporter never reached the watch loop:\n{captured}"

        proc.send_signal(signal.SIGTERM)
        output = captured + proc.communicate(timeout=30)[0]
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.communicate()

    assert "Traefik Certificate Exporter stopping" in output, (
        f"SIGTERM killed the interpreter before the shutdown path ran:\n{output}"
    )
    assert "Traceback" not in output, output
    assert proc.returncode == 0, f"exit was not clean: {proc.returncode}\n{output}"


###########################################################################################
# R1: the SIGTERM handler raises `KeyboardInterrupt` from wherever the signal lands, but
# only the watch block used to catch it. A stop during the start-up sweep -- the default
# `runAtStart: true` path, and the window a `docker stop` is most likely to hit on a slow
# first pass -- died with an uncaught traceback and a signal exit status.


def test_sigterm_during_the_run_at_start_sweep_exits_cleanly(tmp_path):
    """Injected fault: a real SIGTERM at a real process, parked inside the start-up
    sweep (not the watch loop) by a post-export hook that sleeps."""
    script = shutil.which(
        "traefik-certificate-exporter", path=str(Path(sys.executable).parent)
    )
    assert script, "the console script is not installed in this environment"

    dataPath = tmp_path / "data"
    dataPath.mkdir()
    outputPath = tmp_path / "certs"
    outputPath.mkdir()

    configFile = tmp_path / "config.yml"
    configFile.write_text(
        "settings:\n"
        f"  datapath: {dataPath}\n"
        f"  outputpath: {outputPath}\n"
        # No watch loop at all: the one-shot path has to exit cleanly too.
        "  watchforchanges: false\n"
        "  runatstart: true\n"
        # Holds the process inside the sweep's try block long enough to be signalled
        # there deterministically, rather than racing an empty data directory.
        "  postexportcommand: sleep 20\n"
    )

    env = dict(os.environ)
    env["TRAEFIK_CERTIFICATE_EXPORTER_LOGGING_CONSOLEONLY"] = "1"
    env["PYTHONUNBUFFERED"] = "1"

    proc = subprocess.Popen(
        [script, "-c", str(configFile)],
        cwd=str(tmp_path),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    try:
        deadline = time.monotonic() + 30
        exporting = False
        captured = ""
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                break
            line = proc.stdout.readline()
            captured += line
            if "Exporting certificates" in line:
                exporting = True
                break
        assert exporting, f"the exporter never reached the start-up sweep:\n{captured}"
        assert "Watching for changes" not in captured, captured

        # The hook is still sleeping, so the signal lands inside the sweep.
        time.sleep(1)
        assert proc.poll() is None, f"the sweep finished before SIGTERM:\n{captured}"
        proc.send_signal(signal.SIGTERM)
        output = captured + proc.communicate(timeout=30)[0]
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.communicate()

    assert "Traceback" not in output, (
        f"SIGTERM in the start-up sweep died with a traceback:\n{output}"
    )
    assert "Traefik Certificate Exporter stopping" in output, (
        f"SIGTERM in the start-up sweep never reached the shutdown path:\n{output}"
    )
    assert proc.returncode == 0, f"exit was not clean: {proc.returncode}\n{output}"
