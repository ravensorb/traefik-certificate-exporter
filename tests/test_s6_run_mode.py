"""The container's run mode -- watch or run-once -- executed where it is actually written.

The init resolver decides the mode with the installed package's `SettingsManager` (the same
answer the exporter will reach, across every source confuse merges and with confuse's own
truthiness) and writes it to `watch-for-changes`. The service `run` script reads that file,
never the raw environment, and always execs the exporter; its `finish` script ends the
container with the pass's exit code in run-once mode and lets s6 respawn it in watch mode
(ADR-0044, amending ADR-0030).

The idioms follow `tests/test_s6_privilege_drop.py`: the embedded resolver is extracted and
run with this interpreter, and the shell scripts run as copies with their fixed paths
substituted and stub binaries first on PATH.
"""

import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
S6_ROOT = PROJECT_ROOT / "docker" / "root" / "etc" / "s6-overlay" / "s6-rc.d"
INIT_SCRIPT = S6_ROOT / "init-traefik-certificate-exporter-config" / "run"
SVC_DIR = S6_ROOT / "svc-traefik-certificate-exporter"
SVC_SCRIPT = SVC_DIR / "run"
FINISH_SCRIPT = SVC_DIR / "finish"

STATE_DIR_LINE = "STATE_DIR=/run/traefik-certificate-exporter"
WATCH_ENV = "TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_WATCHFORCHANGES"


def _embedded_python() -> str:
    lines = INIT_SCRIPT.read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(lines) if "<<'PY'" in line) + 1
    end = next(i for i, line in enumerate(lines) if i >= start and line == "PY")
    return "\n".join(lines[start:end])


def _executable(path: Path, body: str) -> Path:
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)
    return path


def _copy_with(script: Path, target: Path, substitutions: dict[str, str]) -> Path:
    body = script.read_text(encoding="utf-8")
    for old, new in substitutions.items():
        assert old in body, f"{script.name} no longer contains {old!r}"
        body = body.replace(old, new)
    return _executable(target, body)


# --------------------------------------------------------------------------------------
# AC 1: the init resolver emits the mode.
# --------------------------------------------------------------------------------------


def _resolve_mode(tmp_path: Path, config: str, env: dict | None = None):
    """Run the init script's own resolver; return (exit code, mode file text or None)."""
    configFile = tmp_path / "config.yaml"
    configFile.write_text(config, encoding="utf-8")
    modeFile = tmp_path / "watch-for-changes"

    childEnv = {
        "TCE_CONFIG_FILE": str(configFile),
        "TCE_RESOLVED_OUT": str(tmp_path / "resolved-settings"),
        "TCE_RUN_MODE_OUT": str(modeFile),
        "PATH": "/usr/bin:/bin",
        "HOME": str(tmp_path),
        "TRAEFIK_CERTIFICATE_EXPORTER_LOGGING_CONSOLEONLY": "true",
    }
    childEnv.update(env or {})

    result = subprocess.run(
        [sys.executable, "-c", _embedded_python()],
        capture_output=True,
        text=True,
        env=childEnv,
        cwd=tmp_path,
        check=False,
    )
    text = modeFile.read_text(encoding="utf-8") if modeFile.exists() else None
    return result, text


@pytest.mark.parametrize(
    ("config", "env"),
    [
        ("settings: {}\n", {WATCH_ENV: "false"}),
        ("settings: {}\n", {WATCH_ENV: "no"}),
        ("settings: {}\n", {WATCH_ENV: "False"}),
        ("settings:\n  watchforchanges: false\n", {}),
    ],
    ids=["env-false", "env-no", "env-False", "config-file-false"],
)
def test_resolver_writes_watch_mode_false_for_falsy_spellings(tmp_path, config, env):
    result, text = _resolve_mode(tmp_path, config, env)

    assert result.returncode == 0, result.stderr
    assert text == "false\n"
    assert list(tmp_path.glob(".run-mode-*")) == [], "the write is atomic"


@pytest.mark.parametrize(
    ("config", "env"),
    [
        ("settings:\n  watchforchanges: false\n", {WATCH_ENV: "yes"}),
        ("settings:\n  watchforchanges: false\n", {WATCH_ENV: "True"}),
        ("settings:\n  watchforchanges: false\n", {WATCH_ENV: "on"}),
        ("settings:\n  watchforchanges: true\n", {}),
    ],
    ids=["env-yes", "env-True", "env-on", "config-file-true"],
)
def test_resolver_writes_watch_mode_true_for_truthy_spellings(tmp_path, config, env):
    result, text = _resolve_mode(tmp_path, config, env)

    assert result.returncode == 0, result.stderr
    assert text == "true\n"


def test_resolver_writes_no_mode_for_a_value_the_application_rejects(tmp_path):
    """`1` is a YAML int, and confuse's `get(bool)` rejects it -- so the exporter itself
    refuses `WATCHFORCHANGES=1` at start-up (it did in 0.2.x too, after the shell's own
    `== "1"` test had let it through). The resolver reaches the application's answer, which
    is "no valid mode", and the service falls back to watch mode with a WARNING."""
    result, text = _resolve_mode(tmp_path, "settings: {}\n", {WATCH_ENV: "1"})

    assert result.returncode != 0
    assert "must be a bool" in result.stderr
    assert text is None


def test_resolver_mode_output_is_optional(tmp_path):
    """`tests/test_s6_privilege_drop.py` sets only `TCE_RESOLVED_OUT`; it must keep working."""
    configFile = tmp_path / "config.yaml"
    configFile.write_text("settings: {}\n", encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-c", _embedded_python()],
        capture_output=True,
        text=True,
        env={
            "TCE_CONFIG_FILE": str(configFile),
            "TCE_RESOLVED_OUT": str(tmp_path / "resolved-settings"),
            "PATH": "/usr/bin:/bin",
            "HOME": str(tmp_path),
            "TRAEFIK_CERTIFICATE_EXPORTER_LOGGING_CONSOLEONLY": "true",
        },
        cwd=tmp_path,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert (tmp_path / "resolved-settings").exists()


def test_resolver_writes_no_mode_for_a_malformed_config(tmp_path):
    result, text = _resolve_mode(
        tmp_path, "settings:\n  watchforchanges: [unclosed\n", {}
    )

    assert result.returncode != 0
    assert text is None, (
        "a failed resolution leaves no mode, which the service reads as watch"
    )


def test_init_removes_a_stale_mode_before_resolving(tmp_path):
    """A previous boot's answer must never be read as this boot's."""
    state = tmp_path / "state"
    state.mkdir()
    (state / "watch-for-changes").write_text("false\n", encoding="utf-8")
    config = tmp_path / "config.yaml"
    config.write_text("settings: {}\n", encoding="utf-8")
    fakePython = _executable(
        tmp_path / "fake-python", "#!/bin/sh\ncat > /dev/null\nexit 1\n"
    )
    copy = _copy_with(
        INIT_SCRIPT,
        tmp_path / "init-run",
        {
            "CONFIG_FILE=/config/config.yaml": f"CONFIG_FILE={config}",
            STATE_DIR_LINE: f"STATE_DIR={state}",
            "PRIV_HELPER=/usr/local/lib/traefik-certificate-exporter/privilege-decision.sh": f"PRIV_HELPER={tmp_path / 'absent-helper.sh'}",
            "PYTHON=/app/.venv/bin/python": f"PYTHON={fakePython}",
        },
    )

    result = subprocess.run(
        ["bash", str(copy)],
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin"},
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert not (state / "watch-for-changes").exists()


def test_init_passes_the_mode_path_to_the_resolver():
    body = INIT_SCRIPT.read_text(encoding="utf-8")

    assert 'RUN_MODE="${STATE_DIR}/watch-for-changes"' in body
    assert 'TCE_RUN_MODE_OUT="${RUN_MODE}"' in body


# --------------------------------------------------------------------------------------
# AC 2 and AC 4: the service always execs the exporter.
# --------------------------------------------------------------------------------------


def _run_service(tmp_path: Path, mode: str | None, env: dict | None = None):
    """Run a copy of the service script; return (result, exporter invocation lines)."""
    state = tmp_path / "state"
    state.mkdir()
    if mode is not None:
        (state / "watch-for-changes").write_text(mode, encoding="utf-8")
    binDir = tmp_path / "bin"
    binDir.mkdir()
    log = tmp_path / "exporter.log"
    # `s6-setuidgid USER PROG...` execs PROG; the stub does the same, minus the uid change.
    _executable(binDir / "s6-setuidgid", '#!/bin/sh\nshift\nexec "$@"\n')
    _executable(
        binDir / "traefik-certificate-exporter",
        f'#!/bin/sh\necho "$*" >> "{log}"\nexit 0\n',
    )
    copy = _copy_with(
        SVC_SCRIPT, tmp_path / "svc-run", {STATE_DIR_LINE: f"STATE_DIR={state}"}
    )

    childEnv = {"PATH": f"{binDir}:/usr/bin:/bin", "HOME": "/root"}
    childEnv.update(env or {})
    result = subprocess.run(
        ["bash", str(copy)], capture_output=True, text=True, env=childEnv, check=False
    )
    calls = log.read_text(encoding="utf-8").splitlines() if log.exists() else []
    return result, calls


def test_service_execs_exporter_once_in_run_once_mode(tmp_path):
    """0.2.x printed "Skipping start of application..." and exited, which s6 respawned at 1 Hz."""
    result, calls = _run_service(tmp_path, "false\n")

    assert result.returncode == 0, result.stderr
    assert calls == ["-c /config/config.yaml"]
    assert "Starting application (run-once mode)" in result.stdout
    assert "Skipping" not in result.stdout + result.stderr


def test_service_execs_exporter_in_watch_mode(tmp_path):
    result, calls = _run_service(tmp_path, "true\n")

    assert result.returncode == 0, result.stderr
    assert calls == ["-c /config/config.yaml"]
    assert "Starting application (watch mode)" in result.stdout
    assert "WARNING" not in result.stdout + result.stderr


def test_service_ignores_the_raw_environment(tmp_path):
    """The resolved mode wins; the shell never parses a settings env var itself."""
    result, calls = _run_service(tmp_path, "false\n", env={WATCH_ENV: "true"})

    assert calls == ["-c /config/config.yaml"]
    assert "Starting application (run-once mode)" in result.stdout


def test_service_defaults_to_watch_when_mode_file_missing(tmp_path):
    result, calls = _run_service(tmp_path, None)

    assert result.returncode == 0, result.stderr
    assert calls == ["-c /config/config.yaml"]
    assert "Starting application (watch mode)" in result.stdout
    output = result.stdout + result.stderr
    assert output.count("WARNING: run mode unresolved; defaulting to watch mode") == 1


@pytest.mark.parametrize("mode", ["", "yes\n", "false\nfalse\n"])
def test_service_treats_an_invalid_mode_as_missing(tmp_path, mode):
    result, calls = _run_service(tmp_path, mode)

    assert calls == ["-c /config/config.yaml"]
    assert "Starting application (watch mode)" in result.stdout
    assert "WARNING: run mode unresolved" in result.stdout + result.stderr


def test_service_script_reads_no_settings_env_var():
    assert "TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_" not in SVC_SCRIPT.read_text(
        encoding="utf-8"
    )


# --------------------------------------------------------------------------------------
# AC 3: `finish` ends the container in run-once mode only.
# --------------------------------------------------------------------------------------


def _run_finish(
    tmp_path: Path,
    mode: str | None,
    *args: str,
    halt: bool = True,
    results_dir: bool = True,
):
    """Run a copy of `finish`; return (result, exit-code file text or None, halted)."""
    state = tmp_path / "state"
    state.mkdir()
    if mode is not None:
        (state / "watch-for-changes").write_text(mode, encoding="utf-8")
    results = tmp_path / "results"
    if results_dir:
        results.mkdir()
    exitcodeFile = results / "exitcode"
    haltLog = tmp_path / "halt.log"
    haltPath = tmp_path / "halt"
    if halt:
        _executable(haltPath, f'#!/bin/sh\necho halt >> "{haltLog}"\nexit 0\n')

    copy = _copy_with(
        FINISH_SCRIPT,
        tmp_path / "svc-finish",
        {
            STATE_DIR_LINE: f"STATE_DIR={state}",
            "EXITCODE_FILE=/run/s6-linux-init-container-results/exitcode": f"EXITCODE_FILE={exitcodeFile}",
            "HALT=/run/s6/basedir/bin/halt": f"HALT={haltPath}",
        },
    )
    result = subprocess.run(
        ["bash", str(copy), *args],
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin"},
        check=False,
    )
    written = (
        exitcodeFile.read_text(encoding="utf-8") if exitcodeFile.exists() else None
    )
    return result, written, haltLog.exists()


def test_finish_run_once_writes_exit_code_and_halts(tmp_path):
    result, written, halted = _run_finish(tmp_path, "false\n", "3", "0")

    assert result.returncode == 0, result.stderr
    assert written == "3\n"
    assert halted
    assert (
        "run-once pass finished with exit code 3; stopping container" in result.stdout
    )


def test_finish_signal_exit_writes_128_plus_signal(tmp_path):
    _result, written, halted = _run_finish(tmp_path, "false\n", "256", "15")

    assert written == "143\n"
    assert halted


@pytest.mark.parametrize(
    ("args", "expected"),
    [(("256",), "1\n"), (("256", "x"), "1\n"), (("300", "0"), "1\n"), ((), "1\n")],
)
def test_finish_never_reports_a_malformed_status_as_success(tmp_path, args, expected):
    """256 without a signal number, or any value above 255, would wrap to exit 0."""
    _result, written, halted = _run_finish(tmp_path, "false\n", *args)

    assert written == expected
    assert halted


def test_finish_watch_mode_does_not_halt(tmp_path):
    result, written, halted = _run_finish(tmp_path, "true\n", "3", "0")

    assert result.returncode == 0
    assert written is None
    assert not halted


def test_finish_missing_mode_does_not_halt(tmp_path):
    result, written, halted = _run_finish(tmp_path, None, "3", "0")

    assert result.returncode == 0
    assert written is None
    assert not halted


def test_finish_still_halts_when_the_exit_code_cannot_be_written(tmp_path):
    result, written, halted = _run_finish(
        tmp_path, "false\n", "1", "0", results_dir=False
    )

    assert written is None
    assert halted
    assert "WARNING" in result.stdout + result.stderr


def test_finish_without_halt_stays_down_rather_than_looping(tmp_path):
    """Exit 125 tells s6-supervise not to restart the service: idle beats a 1 Hz loop."""
    result, written, halted = _run_finish(tmp_path, "false\n", "0", "0", halt=False)

    assert result.returncode == 125
    assert written == "0\n"
    assert not halted
    assert (result.stdout + result.stderr).count("WARNING") == 1


def test_finish_is_strict_but_never_aborts_early():
    lines = FINISH_SCRIPT.read_text(encoding="utf-8").splitlines()

    assert lines[0] == "#!/usr/bin/with-contenv bash"
    assert lines[1] == "# shellcheck shell=bash"
    assert "set -uo pipefail" in lines
    assert not any(line.startswith("set -e") for line in lines)
    assert FINISH_SCRIPT.stat().st_mode & 0o777 == 0o755


def test_the_three_scripts_agree_on_the_mode_path():
    for script in (INIT_SCRIPT, SVC_SCRIPT, FINISH_SCRIPT):
        body = script.read_text(encoding="utf-8")
        assert STATE_DIR_LINE in body, script
        assert 'RUN_MODE="${STATE_DIR}/watch-for-changes"' in body, script
