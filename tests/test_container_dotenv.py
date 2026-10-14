"""Opt-in: the built image reads no `.env` file, `/config/.env` included.

E015-S02-005 (MD-24, ADR-0049 amendment 2026-10-14). The image sets
`TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_LOADDOTENV=false`, so no exporter process in it -- the
s6 service, the init resolver, a `docker exec` from `WORKDIR /config` -- reads a `.env`
file. A leftover `/config/.env` gives one WARNING and changes no setting. Docker's own
`--env-file` is the environment and keeps working. LinuxServer's init, `/config` ownership
and s6 are unchanged.

    just image && TCE_DOCKER_INTEGRATION=1 poetry run pytest -q -m integration -rs tests/test_container_dotenv.py

The image under test is `${TCE_IMAGE:-traefik-certificate-exporter:local}`. Conventions are
those of `tests/test_container_root_trust.py`: `PUID=1000 PGID=1000`, named volumes for
`/config` and `/certs`, `/data` bound read-only, edits "as uid 1000" through helper
containers, and cleanup in `finally`.
"""

import collections
import contextlib
import re
import subprocess
import time
import uuid

import pytest

from .fixtures.acme_fixtures import real_chain
from .test_container_root_trust import DOMAIN, IMAGE, OPTED_IN, _Deployment

LOADDOTENV_ENV = "TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_LOADDOTENV"
RESTART_ENV = "TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_RESTARTCONTAINERS"
WATCH_ENV = "TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_WATCHFORCHANGES"
MARKER = "dotenv-marker"
# What uid 1000 writes into `/config/.env`. Each would change a start-up line, the log
# level, or the loader of every process, if the file were read.
PLANTED_DOTENV = (
    f"TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_FILESPEC={MARKER}.json\n"
    "TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_DRYRUN=true\n"
    "TRAEFIK_CERTIFICATE_EXPORTER_LOGGING_LEVEL=DEBUG\n"
    "LD_PRELOAD=/config/x.so\n"
)
UNREAD_WARNING = (
    "Not reading .env file(s) '/config/.env': settings.loaddotenv is false (the container "
    f"image sets {LOADDOTENV_ENV}=false). Set variables in the container's environment: "
    "or env_file:, and settings in config.yaml."
)
STARTUP_PREFIXES = (
    "Data Path:",
    "File Spec:",
    "Output Path:",
    "RSA key validation:",
    "Post-export command:",
)
# The console formats, after ANSI colour codes are stripped: the image's logging config
# (`<date> <time> [   <LEVEL>] [<correlation id>] : <message>`), and the fallback the
# exporter uses when that config cannot be applied
# (`<date> <time> <host> <logger>[<pid>] <LEVEL> <message>`).
_ANSI = re.compile(r"\x1b\[[0-9;]*m")
_LOG_LINES = (
    re.compile(r"^\S+ \S+ \[\s*(?P<level>[A-Z]+)\] \[[^\]]*\] : (?P<message>.*)$"),
    re.compile(r"^\S+ \S+ \S+ \S+\[\d+\] (?P<level>[A-Z]+) (?P<message>.*)$"),
)
READY_TIMEOUT_SECONDS = 90

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not OPTED_IN, reason="image test is opt-in: set TCE_DOCKER_INTEGRATION=1"
    ),
]

MODES = {"dropped": {}, "root": {RESTART_ENV: "true"}}


def _match(line: str) -> "re.Match[str] | None":
    """An exporter log line, colour codes stripped, or None for any other line."""
    line = _ANSI.sub("", line)
    for pattern in _LOG_LINES:
        match = pattern.match(line)
        if match:
            return match
    return None


def _records(logs: str) -> "list[tuple[str, str]]":
    """`(level, message)` of every exporter log line; no timestamp or correlation id."""
    out = []
    for line in logs.splitlines():
        match = _match(line)
        if match:
            out.append((match["level"], match["message"]))
    return out


def _startup(logs: str) -> "list[str]":
    return [m for _, m in _records(logs) if m.startswith(STARTUP_PREFIXES)]


def _problems(logs: str) -> "collections.Counter[str]":
    """Every WARNING/ERROR line, as a multiset: exporter lines without their prefix, and
    any other line (the s6 init scripts) that says WARNING or ERROR."""
    found: collections.Counter[str] = collections.Counter()
    for line in logs.splitlines():
        match = _match(line)
        if match:
            if match["level"] in ("WARNING", "ERROR", "CRITICAL"):
                found[f"{match['level']} {match['message']}"] += 1
        elif "WARNING" in line or "ERROR" in line:
            found[_ANSI.sub("", line).strip()] += 1
    return found


def _plant_dotenv(deployment: _Deployment) -> None:
    deployment.run_as(
        "1000:1000", 'printf "%s" "$DOTENV" > /config/.env', {"DOTENV": PLANTED_DOTENV}
    )


def _clear_certs(deployment: _Deployment) -> None:
    deployment.run_as("0:0", "rm -rf /certs/* && ls -A /certs | wc -l")


def _cert_exists(deployment: _Deployment) -> bool:
    """`cert.pem` of the fixture domain exists anywhere under `/certs` (the layout depends
    on `resolverinpathname`)."""
    out = deployment.run_as(
        "0:0", f"find /certs -path '*/{DOMAIN}/cert.pem' -type f | wc -l"
    )
    return out.strip() == "1"


@pytest.fixture
def deployment(tmp_path):
    deployed = _Deployment(tmp_path)
    try:
        yield deployed
    finally:
        deployed.close()


@pytest.mark.parametrize("mode", list(MODES))
def test_a_planted_config_dotenv_changes_no_setting_and_logs_one_warning(
    deployment, mode
):
    """AC 10 (i): a `/config/.env` that uid 1000 wrote gives the WARNING and nothing else."""
    env = MODES[mode]
    deployment.write_store(real_chain())
    # A warm-up boot seeds `/config` (first-start init output is not part of the compare).
    deployment.boot(env)
    _clear_certs(deployment)
    first = deployment.boot(env)
    _clear_certs(deployment)
    _plant_dotenv(deployment)

    second = deployment.boot(env)

    assert _startup(first), first
    assert _startup(second) == _startup(first), (first, second)
    added = _problems(second) - _problems(first)
    missing = _problems(first) - _problems(second)
    assert added == collections.Counter({f"WARNING {UNREAD_WARNING}": 1}), second
    assert not missing, (first, second)
    assert MARKER not in second, second
    assert "x.so" not in second, second
    assert _cert_exists(deployment), second


def test_a_docker_exec_from_the_config_workdir_reads_no_dotenv(deployment):
    """AC 10 (ii): a one-off `docker exec` runs in `WORKDIR /config` as root and, before
    E015-S02-005, read `/config/.env` (`dryRun: true`, probe 2026-10-14)."""
    deployment.write_store(real_chain())
    deployment.boot()
    _plant_dotenv(deployment)
    container = deployment.client.containers.run(
        IMAGE,
        name=f"tce-dotenv-it-{uuid.uuid4().hex[:8]}",
        detach=True,
        environment={"PUID": "1000", "PGID": "1000"},
        volumes=deployment._mounts(),
        network_mode="none",
    )
    try:
        deadline = time.monotonic() + READY_TIMEOUT_SECONDS
        logs = ""
        while "starting...." not in logs:
            if time.monotonic() > deadline:
                pytest.fail(
                    f"the service did not start in {READY_TIMEOUT_SECONDS}s:\n{logs}"
                )
            time.sleep(1)
            logs = container.logs().decode("utf-8", errors="replace")

        # The probe is only meaningful from `/config`, where a cwd `.env` would be found.
        cwd = container.exec_run(["pwd"])
        assert cwd.output.decode().strip() == "/config", cwd.output

        result = container.exec_run(
            ["traefik-certificate-exporter", "-c", "/config/config.yaml"],
            environment={WATCH_ENV: "false"},
        )
        output = result.output.decode("utf-8", errors="replace")
    finally:
        container.remove(force=True)

    assert result.exit_code == 0, output
    assert "File Spec: *.json" in output, output
    assert UNREAD_WARNING in output, output
    assert MARKER not in output, output


def test_docker_env_file_still_sets_variables(deployment, tmp_path):
    """AC 10 (iii): `--env-file` is applied by Docker, not by the exporter, so it still
    sets variables in the image. Regression guard: passes before and after."""
    deployment.write_store(real_chain())
    envFile = tmp_path / "exporter.env"
    envFile.write_text(
        "TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_FILESPEC=acme.json\n", encoding="utf-8"
    )
    name = f"tce-dotenv-it-{uuid.uuid4().hex[:8]}"
    command = ["docker", "run", "--name", name, "--network", "none"]
    command += ["-e", "PUID=1000", "-e", "PGID=1000", "-e", f"{WATCH_ENV}=false"]
    command += ["--env-file", str(envFile)]
    for source, mount in deployment._mounts().items():
        command += ["-v", f"{source}:{mount['bind']}:{mount['mode']}"]
    command.append(IMAGE)
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, timeout=120, check=False
        )
    finally:
        with contextlib.suppress(Exception):
            deployment.client.containers.get(name).remove(force=True)

    logs = result.stdout + result.stderr
    assert result.returncode == 0, logs
    assert "File Spec: acme.json" in logs, logs
    assert "Not reading .env file" not in logs, logs


def test_the_image_sets_loaddotenv_false(deployment):
    """AC 10 (iv): the switch is declared by the image, beside DATAPATH/OUTPUTPATH."""
    env = deployment.client.images.get(IMAGE).attrs["Config"]["Env"]

    assert f"{LOADDOTENV_ENV}=false" in env, env


def test_config_stays_puid_owned_with_a_dotenv_present(deployment):
    """AC 10 (v): LinuxServer's ownership convention is untouched."""
    deployment.write_store(real_chain())
    deployment.boot()
    _plant_dotenv(deployment)
    deployment.boot()

    owner = deployment.run_as("0:0", "stat -c '%u:%g' /config").strip()
    assert owner == "1000:1000"
