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


@pytest.fixture(autouse=True)
def _restore_global_logger_level():
    """`main()` calls `globalLogger.setLevel(...)`; without a restore, the level a test
    leaves behind filters DEBUG records out of every later test in the session that
    captures them (the settings-dump redaction tests among them)."""
    original = app.globalLogger.level
    yield
    app.globalLogger.setLevel(original)


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
        SimpleNamespace(
            loadFromFile=lambda **kwargs: None,
            settings=settings,
            sourceOf=lambda keyPath: "default",
        ),
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

    import json

    from .fixtures.acme_fixtures import acme_v2_lowercase_fixture

    dataPath = tmp_path / "data"
    dataPath.mkdir()
    outputPath = tmp_path / "certs"
    outputPath.mkdir()
    # One certificate into an empty output directory, so the pass changes a domain and the
    # hook runs: since E014-S01-010 a pass that changes nothing runs no hook (ADR-0045).
    (dataPath / "acme.json").write_text(json.dumps(acme_v2_lowercase_fixture()))

    configFile = tmp_path / "config.yml"
    configFile.write_text(
        "settings:\n"
        # No watch loop at all: the one-shot path has to exit cleanly too.
        "  watchforchanges: false\n"
        "  runatstart: true\n"
    )

    env = dict(os.environ)
    env["TRAEFIK_CERTIFICATE_EXPORTER_LOGGING_CONSOLEONLY"] = "1"
    env["PYTHONUNBUFFERED"] = "1"
    # The paths and the hook come from the environment, not the file: a root process
    # ignores those settings from a configuration file (ADR-0049), and this test runs as
    # root under act (BL-E015-055). The environment is honoured for any euid, so the
    # test exercises the same sweep either way.
    env["TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_DATAPATH"] = str(dataPath)
    env["TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_OUTPUTPATH"] = str(outputPath)
    # Holds the process inside the sweep's try block long enough to be signalled
    # there deterministically, rather than racing an empty data directory.
    env["TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_POSTEXPORTCOMMAND"] = "sleep 20"

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


def _run_once_with_restarts(
    monkeypatch, client=None, clientError=None, restartContainers=True
):
    """Drive `app._run` through one run-at-start pass with restarts on, using the real
    `DockerManager` with only its client factory replaced."""
    from traefik_certificate_exporter.libs.docker import DockerManager

    settings = _make_settings(dataPath="/data", outputPath="/certs")
    settings.restartContainers = restartContainers
    settings.runAtStart = True
    settings.watchForChanges = False

    exporter = MagicMock()
    exporter.exportCertificates.return_value = []

    monkeypatch.setattr(app, "globalArgs", SimpleNamespace(configfile=None))
    monkeypatch.setattr(
        app,
        "globalSettingsMgr",
        SimpleNamespace(
            loadFromFile=lambda **kwargs: None,
            settings=settings,
            sourceOf=lambda keyPath: "default",
        ),
    )
    monkeypatch.setattr(app, "require_existing_path", lambda *a, **k: None)
    monkeypatch.setattr(app, "AcmeCertificateExporter", lambda **kwargs: exporter)
    monkeypatch.setattr(app, "run_post_export_command", lambda *a, **k: None)
    monkeypatch.setattr(app, "send_export_notifications", lambda *a, **k: None)
    if clientError is not None:
        factory = MagicMock(side_effect=clientError)
    else:
        factory = MagicMock(return_value=client)
    monkeypatch.setattr(DockerManager, "_create_client", factory)

    app._run(logging.getLogger("test_app"))
    return exporter, factory


def test_startup_reachability_check_logs_info_on_success(monkeypatch, caplog):
    client = MagicMock()
    client.ping.return_value = True
    client.version.return_value = {"ApiVersion": "1.47"}

    with caplog.at_level(logging.INFO):
        _exporter, factory = _run_once_with_restarts(monkeypatch, client=client)

    # The check, then the pass's restart evaluation: since E014-S01-006 every pass
    # evaluates restarts, even one that changed nothing (ADR-0045).
    assert factory.call_count == 2
    client.ping.assert_called_once()
    assert "Docker Engine reachable (API 1.47)" in caplog.text


def test_startup_reachability_check_failure_logs_error_and_continues(
    monkeypatch, caplog
):
    import docker

    monkeypatch.setenv("DOCKER_HOST", "tcp://engine.invalid:2375")

    with caplog.at_level(logging.INFO):
        exporter, _factory = _run_once_with_restarts(
            monkeypatch, clientError=docker.errors.DockerException("refused")
        )

    # One ERROR from the check and one from the pass's restart evaluation, which since
    # E014-S01-006 runs on every pass (ADR-0045); each names the endpoint.
    errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert len(errors) == 2, [r.getMessage() for r in errors]
    assert "Docker Engine check against" in errors[0].getMessage()
    for error in errors:
        assert "tcp://engine.invalid:2375" in error.getMessage()
        assert "refused" in error.getMessage()
    # Exporting still has value when restarts cannot happen.
    exporter.exportCertificates.assert_called_once()


def test_startup_reachability_check_is_skipped_when_restarts_are_off(
    monkeypatch, caplog
):
    """A deployment without a Docker socket and without restarts must not see an ERROR."""
    exporter, factory = _run_once_with_restarts(
        monkeypatch, client=MagicMock(), restartContainers=False
    )

    factory.assert_not_called()
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]
    exporter.exportCertificates.assert_called_once()


def test_nothing_to_do_logs_one_warning(monkeypatch, caplog):
    """E014-S01-005 AC 5: with both `runatstart` and `watchforchanges` off, `_run` used
    to return having done nothing and said nothing."""
    settings = _make_settings(dataPath="/data", outputPath="/certs")
    settings.runAtStart = False
    settings.watchForChanges = False
    exporter = MagicMock()

    monkeypatch.setattr(app, "globalArgs", SimpleNamespace(configfile=None))
    monkeypatch.setattr(
        app,
        "globalSettingsMgr",
        SimpleNamespace(
            loadFromFile=lambda **kwargs: None,
            settings=settings,
            sourceOf=lambda keyPath: "default",
        ),
    )
    monkeypatch.setattr(app, "require_existing_path", lambda *a, **k: None)
    monkeypatch.setattr(app, "AcmeCertificateExporter", lambda **kwargs: exporter)

    with caplog.at_level(logging.DEBUG):
        app._run(logging.getLogger("test_app"))

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert [r.getMessage() for r in warnings] == [
        "neither runatstart nor watchforchanges is set; nothing to do"
    ]
    exporter.exportCertificates.assert_not_called()


def _run_with_manager(monkeypatch, *, runAtStart, watchForChanges, exportError=None):
    """Drive `app._run` with a recording `DockerManager`; return (manager, exporter)."""
    settings = _make_settings(dataPath="/data", outputPath="/certs")
    settings.restartContainers = True
    settings.runAtStart = runAtStart
    settings.watchForChanges = watchForChanges
    settings.watchInterval = 60

    exporter = MagicMock()
    exporter.exportCertificates.return_value = []  # nothing changed in this pass
    if exportError is not None:
        exporter.exportCertificates.side_effect = exportError
    manager = MagicMock()

    monkeypatch.setattr(app, "globalArgs", SimpleNamespace(configfile=None))
    monkeypatch.setattr(
        app,
        "globalSettingsMgr",
        SimpleNamespace(
            loadFromFile=lambda **kwargs: None,
            settings=settings,
            sourceOf=lambda keyPath: "default",
        ),
    )
    monkeypatch.setattr(app, "require_existing_path", lambda *a, **k: None)
    monkeypatch.setattr(app, "AcmeCertificateExporter", lambda **kwargs: exporter)
    monkeypatch.setattr(app, "DockerManager", lambda **kwargs: manager)
    monkeypatch.setattr(app, "run_post_export_command", lambda *a, **k: None)
    monkeypatch.setattr(app, "send_export_notifications", lambda *a, **k: None)
    monkeypatch.setattr(app, "AcmeCertificateFileHandler", lambda **kwargs: MagicMock())
    monkeypatch.setattr(app.watchdog.observers, "Observer", lambda: MagicMock())

    def interrupt(_seconds):
        raise KeyboardInterrupt

    monkeypatch.setattr(app.time, "sleep", interrupt)
    return manager, exporter, settings


def test_run_at_start_evaluates_restarts_every_pass(monkeypatch):
    """E014-S01-006: the start-up pass evaluates restarts even when nothing changed --
    the rule reads the files, so a restart lost to a crash is recovered (ADR-0045)."""
    manager, exporter, _settings = _run_with_manager(
        monkeypatch, runAtStart=True, watchForChanges=False
    )

    app._run(logging.getLogger("test_app"))

    manager.restartLabeledContainers.assert_called_once_with(exporter.artifactMtime)


@pytest.mark.parametrize(
    "case", ["run-once", "nothing-to-do", "export-raises", "watch-interrupted"]
)
def test_run_cancels_pending_restarts_on_every_exit_path(monkeypatch, case):
    manager, _exporter, _settings = _run_with_manager(
        monkeypatch,
        runAtStart=case in ("run-once", "export-raises"),
        watchForChanges=case == "watch-interrupted",
        exportError=RuntimeError("boom") if case == "export-raises" else None,
    )

    if case == "export-raises":
        with pytest.raises(RuntimeError):
            app._run(logging.getLogger("test_app"))
    else:
        app._run(logging.getLogger("test_app"))

    manager.cancel.assert_called_once_with()


# ---------------------------------------------------------------------------
# E014-S01-010: the hook and notifications run only for domains whose artifacts changed
# in the pass; a pass that changed nothing runs neither and says so once (ADR-0045,
# amending ADR-0014 §7). The restart evaluation still runs on every pass.
# ---------------------------------------------------------------------------

_QUIET_PASS_LINE = "No certificate changed; no hook or notification"


def _patch_run_environment(monkeypatch, settings, exporter=None):
    monkeypatch.setattr(app, "globalArgs", SimpleNamespace(configfile=None))
    monkeypatch.setattr(
        app,
        "globalSettingsMgr",
        SimpleNamespace(
            loadFromFile=lambda **kwargs: None,
            settings=settings,
            sourceOf=lambda keyPath: "default",
        ),
    )
    monkeypatch.setattr(app, "require_existing_path", lambda *a, **k: None)
    if exporter is not None:
        monkeypatch.setattr(app, "AcmeCertificateExporter", lambda **kwargs: exporter)


def _record_hook_and_notifications(monkeypatch):
    """Replace both hops with recorders; return (hook calls, notification calls)."""
    hookCalls: list = []
    notifyCalls: list = []
    monkeypatch.setattr(
        app,
        "run_post_export_command",
        lambda command, domains, dryRun, **kwargs: hookCalls.append(list(domains)),
    )
    monkeypatch.setattr(
        app,
        "send_export_notifications",
        lambda urls, domains, dryRun, **kwargs: notifyCalls.append(list(domains)),
    )
    return hookCalls, notifyCalls


def _run_start_pass(monkeypatch, changed, *, dryRun=False, record=True):
    """One run-at-start pass whose exporter reports `changed`; hook and Apprise set."""
    settings = _make_settings(dataPath="/data", outputPath="/certs")
    settings.runAtStart = True
    settings.dryRun = dryRun
    settings.restartContainers = True
    settings.postExportCommand = "/usr/local/bin/reload-proxy --now"
    settings.appriseUrls = ["json://hook.example.test/"]

    exporter = MagicMock()
    exporter.exportCertificates.return_value = list(changed)
    manager = MagicMock()

    _patch_run_environment(monkeypatch, settings, exporter)
    monkeypatch.setattr(app, "DockerManager", lambda **kwargs: manager)
    recorders = _record_hook_and_notifications(monkeypatch) if record else None

    app._run(logging.getLogger("test_app"))
    return recorders, manager, exporter


def test_run_at_start_with_no_changed_domain_runs_no_hook_or_notification(
    monkeypatch,
):
    (hookCalls, notifyCalls), manager, exporter = _run_start_pass(monkeypatch, [])

    assert hookCalls == []
    assert notifyCalls == []
    # The restart evaluation is unchanged: it runs on every pass (E014-S01-006).
    manager.restartLabeledContainers.assert_called_once_with(exporter.artifactMtime)


def test_run_at_start_with_one_changed_domain_runs_hook_and_notification_with_that_domain(
    monkeypatch,
):
    (hookCalls, notifyCalls), manager, exporter = _run_start_pass(
        monkeypatch, ["a.example.test"]
    )

    assert hookCalls == [["a.example.test"]]
    assert notifyCalls == [["a.example.test"]]
    manager.restartLabeledContainers.assert_called_once_with(exporter.artifactMtime)


def test_quiet_pass_logs_no_change_info_once(monkeypatch, caplog):
    with caplog.at_level(logging.INFO):
        _run_start_pass(monkeypatch, [])

    quiet = [r for r in caplog.records if r.getMessage() == _QUIET_PASS_LINE]
    assert len(quiet) == 1, [r.getMessage() for r in caplog.records]
    assert quiet[0].levelno == logging.INFO


def test_dry_run_keeps_hook_and_notification_skip_lines(monkeypatch, caplog):
    """The real hops, unpatched: a dry run reports the domains that WOULD change, and the
    hook and notifications log their existing skip lines for them and run nothing."""
    import apprise

    from traefik_certificate_exporter.libs import post_export

    ran = MagicMock()
    monkeypatch.setattr(post_export.subprocess, "run", ran)
    monkeypatch.setattr(apprise, "Apprise", ran)

    with caplog.at_level(logging.INFO):
        _run_start_pass(monkeypatch, ["a.example.test"], dryRun=True, record=False)

    messages = [r.getMessage() for r in caplog.records]
    assert "Dry run: skipping post-export command" in messages
    assert "Dry run: skipping export notifications" in messages
    assert _QUIET_PASS_LINE not in messages
    ran.assert_not_called()


def test_restart_recovery_pass_runs_no_hook_or_notification(monkeypatch, tmp_path):
    """S01-006's crash case from the hook's side: the files were written and the process
    died before restarting. A fresh process's pass over the unchanged store restarts the
    container (the files are newer than its start) and runs no hook and no notification,
    because no domain changed in this pass."""
    from traefik_certificate_exporter.libs.certificate_exporter import (
        AcmeCertificateExporter,
    )
    from traefik_certificate_exporter.libs.docker import DockerManager

    from .fixtures.acme_fixtures import acme_v2_certificate
    from .libs.test_docker import (
        FakeClient,
        FakeContainer,
        _domain_files,
        _env,
        _set_mtime,
        _store,
    )

    settings = _env(tmp_path, _store(acme_v2_certificate("a.example.test")))
    settings.postExportCommand = "/usr/local/bin/reload-proxy --now"
    settings.appriseUrls = ["json://hook.example.test/"]
    # The previous process: exported, then died before restarting anything.
    AcmeCertificateExporter(settings).exportCertificates()
    now = time.time()
    container = FakeContainer("c1", "a.example.test", startedAt=now - 60)
    _set_mtime(_domain_files(tmp_path, "a.example.test"), now - 10)

    class _ReachableClient(FakeClient):
        def ping(self):
            return True

        def version(self):
            return {"ApiVersion": "1.47"}

    _patch_run_environment(monkeypatch, settings)
    monkeypatch.setattr(
        DockerManager, "_create_client", lambda self: _ReachableClient(container)
    )
    hookCalls, notifyCalls = _record_hook_and_notifications(monkeypatch)

    app._run(logging.getLogger("test_app"))

    assert container.restarts == 1
    assert hookCalls == []
    assert notifyCalls == []


# ---------------------------------------------------------------------------
# Log level from the environment (E014-S01-004). The container cannot pass `-ll` (the s6
# service fixes argv), so `TRAEFIK_CERTIFICATE_EXPORTER_LOGGING_LEVEL` is its verbosity
# switch. Precedence: `-ll` > env > INFO.
# ---------------------------------------------------------------------------

_LOG_LEVEL_ENV = "TRAEFIK_CERTIFICATE_EXPORTER_LOGGING_LEVEL"


def _run_main_for_log_level(monkeypatch, cli_level, env_value):
    """Run `main()` up to the point `_run` would start; return what logging was given."""
    if env_value is None:
        monkeypatch.delenv(_LOG_LEVEL_ENV, raising=False)
    else:
        monkeypatch.setenv(_LOG_LEVEL_ENV, env_value)

    seen = {}
    monkeypatch.setattr(
        app,
        "parse_args_strict",
        lambda: SimpleNamespace(configfile=None, logginglevel=cli_level),
    )
    monkeypatch.setattr(
        app, "setup_logging", lambda **kwargs: seen.update(setup=kwargs)
    )
    monkeypatch.setattr(app, "install_shutdown_signal_handlers", lambda logger: None)
    monkeypatch.setattr(
        app, "_run", lambda logger: seen.update(logger_level=logger.level)
    )

    app.main()
    return seen


def test_log_level_from_env_when_no_cli_flag(monkeypatch):
    seen = _run_main_for_log_level(monkeypatch, None, "debug")

    assert seen["setup"]["default_level"] == "DEBUG"
    assert seen["logger_level"] == logging.DEBUG


def test_cli_log_level_overrides_env(monkeypatch):
    seen = _run_main_for_log_level(monkeypatch, "WARNING", "DEBUG")

    assert seen["setup"]["default_level"] == "WARNING"
    assert seen["logger_level"] == logging.WARNING


def test_invalid_env_log_level_falls_back_to_info_with_one_warning(monkeypatch, caplog):
    with caplog.at_level(logging.DEBUG):
        seen = _run_main_for_log_level(monkeypatch, None, "verbose\n\x1b[31mforged")

    assert seen["setup"]["default_level"] == "INFO"
    assert seen["logger_level"] == logging.INFO
    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1, warnings
    assert _LOG_LEVEL_ENV in warnings[0]
    assert "verbose" in warnings[0]
    assert "DEBUG, INFO, WARNING, ERROR, CRITICAL" in warnings[0]
    assert "\n" not in warnings[0] and "\x1b" not in warnings[0], warnings[0]


def test_empty_env_log_level_is_unset_without_a_warning(monkeypatch, caplog):
    with caplog.at_level(logging.DEBUG):
        seen = _run_main_for_log_level(monkeypatch, None, "")

    assert seen["setup"]["default_level"] == "INFO"
    assert not [r for r in caplog.records if r.levelno == logging.WARNING]


@pytest.mark.parametrize("quoted", ['"DEBUG"', "'debug'"])
def test_quoted_env_log_level_is_accepted(monkeypatch, quoted):
    seen = _run_main_for_log_level(monkeypatch, None, quoted)

    assert seen["setup"]["default_level"] == "DEBUG"


@pytest.mark.parametrize(
    ("cli_level", "env_value", "expected"),
    [
        ("ERROR", "DEBUG", "Log level: ERROR (source: cli)"),
        (None, "DEBUG", "Log level: DEBUG (source: env)"),
        (None, None, "Log level: INFO (source: default)"),
        (None, "bogus", "Log level: INFO (source: default)"),
    ],
)
def test_effective_log_level_and_source_logged_at_info(
    monkeypatch, caplog, cli_level, env_value, expected
):
    # Captured below the effective level on purpose: the line is emitted at INFO, so at
    # `-ll ERROR` it is filtered by the logger itself -- the record is asserted on the
    # handler-independent capture of what `main()` tried to log.
    emitted = []
    monkeypatch.setattr(
        app.globalLogger,
        "info",
        lambda msg, *a, **k: emitted.append(msg % a if a else msg),
    )

    _run_main_for_log_level(monkeypatch, cli_level, env_value)

    assert expected in emitted, emitted


# ---------------------------------------------------------------------------
# E015-S01-001 AC 4 (ADR-0049): one start-up INFO line says whether a post-export command
# is set, where it came from and which uid runs it -- never the command itself.
# ---------------------------------------------------------------------------


def test_start_up_logs_the_post_export_command_source_and_uid(
    monkeypatch, caplog, tmp_path
):
    from argparse import Namespace

    from traefik_certificate_exporter.libs.settings import SettingsManager

    hookEnv = "TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_POSTEXPORTCOMMAND"
    command = "/usr/local/bin/reload --token s3cr3t-hook-token"
    configFile = tmp_path / "config.yaml"
    configFile.write_text(f'settings:\n  postexportcommand: "{command}"\n')
    cases = [
        # (euid, hook in the environment?, expected line)
        (0, True, "Post-export command: set (source: environment), runs as uid 0"),
        (0, False, "Post-export command: not set (source: default), runs as uid 0"),
        (
            1000,
            False,
            (
                f"Post-export command: set (source: configuration file '{configFile}'), "
                "runs as uid 1000"
            ),
        ),
    ]

    for name in list(os.environ):
        if name.startswith("TRAEFIK_CERTIFICATE_EXPORTER_"):
            monkeypatch.delenv(name)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_DATAPATH", str(tmp_path))
    monkeypatch.setattr(app, "DockerManager", lambda **kwargs: MagicMock())

    for euid, fromEnv, expected in cases:
        if fromEnv:
            monkeypatch.setenv(hookEnv, command)
        else:
            monkeypatch.delenv(hookEnv, raising=False)
        monkeypatch.setattr(app.os, "geteuid", lambda euid=euid: euid, raising=False)
        manager = SettingsManager()
        manager.modulePath = tmp_path / "module"
        monkeypatch.setattr(app, "globalSettingsMgr", manager)
        monkeypatch.setattr(app, "globalArgs", Namespace(configfile=str(configFile)))

        caplog.clear()
        with caplog.at_level(logging.INFO):
            app._run(logging.getLogger("test_app"))

        lines = [
            r.getMessage()
            for r in caplog.records
            if r.getMessage().startswith("Post-export command:")
        ]
        assert lines == [expected], (euid, fromEnv, lines)
        assert r"s3cr3t-hook-token" not in caplog.text


@pytest.mark.parametrize(
    "validateKeys, line",
    [
        (True, "RSA key validation: on"),
        (
            False,
            (
                "RSA key validation: off (settings.validatekeys=false: keys are "
                "trusted, not checked)"
            ),
        ),
    ],
    ids=["on", "off"],
)
def test_startup_logs_rsa_key_validation_setting(
    monkeypatch, caplog, validateKeys, line
):
    settings = _make_settings(dataPath="/data", outputPath="/certs")
    settings.runAtStart = True
    settings.validateKeys = validateKeys
    exporter = MagicMock()
    exporter.exportCertificates.return_value = []
    _patch_run_environment(monkeypatch, settings, exporter)
    monkeypatch.setattr(app, "DockerManager", lambda **kwargs: MagicMock())
    _record_hook_and_notifications(monkeypatch)

    with caplog.at_level(logging.INFO):
        app._run(logging.getLogger("test_app"))

    messages = [r.getMessage() for r in caplog.records]
    matching = [
        r for r in caplog.records if r.getMessage().startswith("RSA key validation:")
    ]
    assert [r.getMessage() for r in matching] == [line]
    assert matching[0].levelno == logging.INFO
    assert messages.index(line) == messages.index("Output Path: /certs") + 1
