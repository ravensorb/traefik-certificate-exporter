"""The container's privilege decision, exercised where it is actually written.

The s6 run scripts cannot be executed outside the image (no `with-contenv`, no s6 tooling,
no `/app/.venv`), so these tests do the next-best thing and assert against the scripts'
*source*: the embedded Python that resolves the settings is extracted and run with this
interpreter, and the shell around it is checked for the properties that make the fallback
safe. A rewrite that moves the decision elsewhere will fail these loudly rather than
silently ship a container that keeps root — or one that drops to an account that cannot
start.
"""

import re
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
S6_ROOT = PROJECT_ROOT / "docker" / "root" / "etc" / "s6-overlay" / "s6-rc.d"
INIT_SCRIPT = S6_ROOT / "init-traefik-certificate-exporter-config" / "run"
SVC_SCRIPT = S6_ROOT / "svc-traefik-certificate-exporter" / "run"


def _embedded_python() -> str:
    lines = INIT_SCRIPT.read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(lines) if "<<'PY'" in line) + 1
    end = next(i for i, line in enumerate(lines) if i >= start and line == "PY")
    return "\n".join(lines[start:end])


def _resolve(tmp_path: Path, config: str | None, env: dict | None = None):
    """Run the init script's own resolver and return (exit code, written lines)."""
    configFile = tmp_path / "config.yaml"
    if config is not None:
        configFile.write_text(config, encoding="utf-8")
    resolved = tmp_path / "resolved-settings"

    childEnv = {
        "TCE_CONFIG_FILE": str(configFile),
        "TCE_RESOLVED_OUT": str(resolved),
        "PATH": "/usr/bin:/bin",
        # Keep confuse's application directory inside the test's own tmp tree.
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
    written = (
        resolved.read_text(encoding="utf-8").splitlines() if resolved.exists() else []
    )
    return result.returncode, written


@pytest.mark.parametrize(
    ("config", "expected"),
    [
        ("settings:\n  restartcontainers: true\n", "true"),
        ("settings:\n  restartcontainers: false\n", "false"),
        ("settings:\n  datapath: /data\n", "false"),
        ("", "false"),
    ],
)
def test_config_file_drives_the_privilege_decision(tmp_path, config, expected):
    code, written = _resolve(tmp_path, config)

    assert code == 0
    assert written[0] == expected


@pytest.mark.parametrize(
    ("env_value", "expected"), [("true", "true"), ("yes", "true"), ("false", "false")]
)
def test_environment_overlays_the_config_file(tmp_path, env_value, expected):
    code, written = _resolve(
        tmp_path,
        "settings:\n  restartcontainers: false\n",
        env={"TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_RESTARTCONTAINERS": env_value},
    )

    assert code == 0
    assert written[0] == expected


def test_environment_can_enable_root_without_a_config_file(tmp_path):
    code, written = _resolve(
        tmp_path,
        config=None,
        env={"TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_RESTARTCONTAINERS": "true"},
    )

    assert code == 0
    assert written[0] == "true"


def test_the_resolver_is_the_application_not_a_second_parser():
    """Finding 6: a value the application reads as true and the init script as false drops
    privileges out from under a configuration that needs the Docker socket. The only way to
    be sure the two agree is for there to be one of them."""
    body = INIT_SCRIPT.read_text(encoding="utf-8")

    assert "SettingsManager" in body
    assert "import yaml" not in body and "safe_load" not in body, (
        "the init script must ask the installed package, not parse the config itself"
    )


def test_the_output_and_data_paths_are_resolved_not_assumed(tmp_path):
    """Findings 4 and 5: /certs and /data are the image's defaults, not its values."""
    code, written = _resolve(
        tmp_path,
        "settings:\n  outputpath: /elsewhere/certs\n  datapath: /elsewhere/acme\n"
        "  filespec: 'acme-*.json'\n",
    )

    assert code == 0
    assert written[1] == "/elsewhere/certs"
    assert written[2] == "/elsewhere/acme"
    assert written[3] == "acme-*.json"


@pytest.mark.parametrize(
    "config",
    [
        "settings:\n  restartcontainers: [unclosed\n",
        # `settings:` with no mapping under it is rejected by the application too; the
        # container must not paper over a config the exporter itself will refuse.
        "settings:\n",
    ],
)
def test_malformed_config_writes_nothing_rather_than_true(tmp_path, config):
    code, written = _resolve(tmp_path, config)

    assert code != 0
    assert written == [], (
        "a failed resolution must leave no answer at all, so the shell keeps the "
        "already-written safe default"
    )


def test_init_script_writes_the_safe_default_before_consulting_the_config():
    body = INIT_SCRIPT.read_text(encoding="utf-8")

    safeDefault = body.index("printf 'false\\n' > \"${PRIV_STATE}\"")
    resolution = body.index("/app/.venv/bin/python")

    assert safeDefault < resolution, (
        "the drop-privileges default must already be on disk before the settings are "
        "resolved, so any failure between the two leaves the safe answer"
    )
    assert 'rm -f "${RESOLVED}"' in body, (
        "a stale resolution from a previous boot must not be read as this boot's answer"
    )


def test_init_script_never_dereferences_a_symlink_when_taking_ownership():
    """Finding 3: `chown -R`/`lsiown -R` over an operator-writable volume is an
    arbitrary-chown primitive, because both follow symlinks."""
    body = INIT_SCRIPT.read_text(encoding="utf-8")

    assert not re.search(r"^\s*lsiown\b", body, re.MULTILINE), (
        "lsiown dereferences symlinks; it must not be invoked here"
    )
    assert not re.search(r"chown\s+(-\w*R\w*\s)", body), (
        "recursive chown must go through find, which can exclude symlinks"
    )
    assert "! -type l" in body and "-xdev" in body
    assert "chown -h" in body


def test_init_script_gives_the_dropped_account_a_usable_home():
    """Finding 1: s6-setuidgid changes the uid only, and confuse unconditionally creates
    its application directory under $HOME — which is root-owned 0700 in the base image."""
    body = INIT_SCRIPT.read_text(encoding="utf-8")

    assert 'mkdir -p "${SERVICE_HOME}"' in body
    assert 'chown "${SERVICE_USER}:${SERVICE_USER}" "${SERVICE_HOME}"' in body


def test_init_script_warns_when_the_dropped_account_cannot_read_the_acme_store():
    body = INIT_SCRIPT.read_text(encoding="utf-8")

    assert "PUID/PGID" in body
    assert "not readable by that account" in body


def test_service_script_drops_privileges_unless_the_state_file_says_root():
    body = SVC_SCRIPT.read_text(encoding="utf-8")

    assert "s6-setuidgid abc" in body
    assert body.index("s6-setuidgid root") < body.index("s6-setuidgid abc"), (
        "the root branch must be the guarded one and the abc exec the fall-through"
    )
    assert 'cat "$PRIV_STATE" 2> /dev/null' in body, (
        "a missing state file must read as empty (not root) rather than erroring"
    )
    assert "settings.restartcontainers" in body, (
        "the root branch must name the condition that caused it"
    )


def test_service_script_exports_a_home_the_dropped_account_owns():
    body = SVC_SCRIPT.read_text(encoding="utf-8")

    assert 'export HOME="${SERVICE_HOME}"' in body
    assert body.index('export HOME="${SERVICE_HOME}"') < body.index(
        "s6-setuidgid abc"
    ), "HOME has to be set before the exec that uses it"


def test_the_two_scripts_agree_on_the_state_paths():
    initBody = INIT_SCRIPT.read_text(encoding="utf-8")
    svcBody = SVC_SCRIPT.read_text(encoding="utf-8")

    for line in ("STATE_DIR=/run/traefik-certificate-exporter",):
        assert line in initBody and line in svcBody

    assert 'PRIV_STATE="${STATE_DIR}/run-as-root"' in initBody
    assert 'PRIV_STATE="${STATE_DIR}/run-as-root"' in svcBody
    assert 'SERVICE_HOME="${STATE_DIR}/home"' in initBody
    assert 'SERVICE_HOME="${STATE_DIR}/home"' in svcBody
