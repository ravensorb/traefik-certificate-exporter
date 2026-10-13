"""Opt-in: the built image keeps `/config` LinuxServer-owned and root out of its reach.

E015-S01-001 (BL-E014-119 / RT-1, arch gate AG-1, ADR-0049). `/config` is owned by
`PUID`/`PGID`, as LinuxServer's `init-adduser` makes it on every start, and stays that way.
What changes is what a root exporter takes from a file there: no `postexportcommand`, no
`outputpath`, no `datapath`, and a `filespec` only as a file-name glob inside the data path.
These tests replay both attacks against the real image, base-image init included:

    just image && TCE_DOCKER_INTEGRATION=1 poetry run pytest -q -m integration -rs tests/test_container_root_trust.py

The image under test is `${TCE_IMAGE:-traefik-certificate-exporter:local}`. Every container
runs with `PUID=1000 PGID=1000`, named volumes for `/config` and `/certs`, `/data` bound
read-only, and in run-once mode. Edits "as uid 1000" go through helper containers started
with `--user 1000:1000 --entrypoint sh` on the same volumes, so no host `chown` is needed.
"""

import base64
import contextlib
import json
import os
import uuid
from pathlib import Path

import pytest

from traefik_certificate_exporter.libs.docker import DEFAULT_DOCKER_ENDPOINT

from .fixtures.acme_fixtures import RealChain, real_chain, real_chain_expiring_in

IMAGE = os.environ.get("TCE_IMAGE") or "traefik-certificate-exporter:local"
EXIT_TIMEOUT_SECONDS = 90
DOMAIN = "root-trust.example.test"
HOOK = '/bin/sh -c "id > /certs/pwned.txt"'
HOOK_ENV = "TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_POSTEXPORTCOMMAND"
RESTART_ENV = "TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_RESTARTCONTAINERS"
ROOT_WARNING = "running as root because settings.restartcontainers is enabled"
PYTHON = "/app/.venv/bin/python"

# Opt-in, but once opted in nothing is skipped: this is required release evidence, and a
# skipped run exits 0 having tested nothing. A missing socket or image FAILS instead.
OPTED_IN = os.environ.get("TCE_DOCKER_INTEGRATION") == "1"

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not OPTED_IN, reason="image test is opt-in: set TCE_DOCKER_INTEGRATION=1"
    ),
]


def _store(chain: RealChain) -> str:
    return json.dumps(
        {
            "myresolver": {
                "Account": {
                    "Registration": {
                        "uri": "https://acme-v02.api.letsencrypt.org/directory"
                    }
                },
                "Certificates": [
                    {
                        "domain": {"main": DOMAIN, "sans": []},
                        "key": base64.b64encode(chain.key_pem).decode("ascii"),
                        "certificate": base64.b64encode(chain.fullchain_pem).decode(
                            "ascii"
                        ),
                    }
                ],
            }
        }
    )


class _Deployment:
    """One container deployment: its two named volumes and a read-only `/data` bind."""

    def __init__(self, tmp_path: Path) -> None:
        import docker

        endpoint = os.environ.get("DOCKER_HOST") or DEFAULT_DOCKER_ENDPOINT
        if endpoint.startswith("unix://") and not Path(endpoint[7:]).exists():
            pytest.fail(
                f"TCE_DOCKER_INTEGRATION=1 but there is no Docker socket at {endpoint[7:]}"
            )
        self.client = docker.from_env()
        try:
            self.client.images.get(IMAGE)
        except docker.errors.ImageNotFound:
            pytest.fail(f"image {IMAGE} not found; build it with `just image`")

        self.suffix = uuid.uuid4().hex[:8]
        self.data = tmp_path / "data"
        self.data.mkdir()
        # Readable by the PUID account, so only `restartcontainers` decides root mode.
        self.data.chmod(0o755)
        self.volumes: list = []
        self.config = self._volume("config")
        self.certs = self._volume("certs")

    def _volume(self, role: str):
        volume = self.client.volumes.create(
            name=f"tce-root-trust-it-{self.suffix}-{role}"
        )
        self.volumes.append(volume)
        return volume

    def _mounts(self) -> dict:
        return {
            self.config.name: {"bind": "/config", "mode": "rw"},
            self.certs.name: {"bind": "/certs", "mode": "rw"},
            str(self.data): {"bind": "/data", "mode": "ro"},
        }

    def write_store(self, chain: RealChain) -> None:
        store = self.data / "acme.json"
        store.write_text(_store(chain), encoding="utf-8")
        store.chmod(0o644)

    def boot(self, extra_env: "dict[str, str] | None" = None) -> str:
        """Start the image once in run-once mode; return its log. Requires exit 0."""
        import requests

        environment = {
            "PUID": "1000",
            "PGID": "1000",
            "TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_WATCHFORCHANGES": "false",
        }
        environment.update(extra_env or {})
        container = self.client.containers.run(
            IMAGE,
            name=f"tce-root-trust-it-{uuid.uuid4().hex[:8]}",
            detach=True,
            environment=environment,
            volumes=self._mounts(),
            network_mode="none",
        )
        try:
            try:
                status = container.wait(timeout=EXIT_TIMEOUT_SECONDS)
            except requests.exceptions.RequestException:
                logs = container.logs().decode("utf-8", errors="replace")
                pytest.fail(
                    f"container still running after {EXIT_TIMEOUT_SECONDS}s:\n{logs}"
                )
            logs = container.logs().decode("utf-8", errors="replace")
            assert status["StatusCode"] == 0, logs
            return logs
        finally:
            container.remove(force=True)

    def run_as(self, user: str, script: str, env: "dict | None" = None) -> str:
        """Run `sh -c script` as `user` on the deployment's volumes; fail on non-zero."""
        output = self.client.containers.run(
            IMAGE,
            entrypoint=["sh", "-c", script],
            user=user,
            environment=env or {},
            volumes=self._mounts(),
            network_mode="none",
            remove=True,
            stdout=True,
            stderr=True,
        )
        return output.decode("utf-8", errors="replace")

    def replace_config_as_puid(self, text: str) -> None:
        """uid 1000 replaces `/config/config.yaml` by rename, as RT-1 did."""
        self.run_as(
            "1000:1000",
            'printf "%s" "$CFG" > /config/.tce-new && mv -f /config/.tce-new '
            "/config/config.yaml",
            {"CFG": text},
        )

    def pwned(self) -> "str | None":
        out = self.run_as(
            "0:0",
            "if [ -e /certs/pwned.txt ]; then cat /certs/pwned.txt; else echo ABSENT; fi",
        )
        return None if out.strip() == "ABSENT" else out

    def cert_files(self) -> dict:
        """`{path: [inode, mtime_ns, sha256]}` of every exported `.pem` under `/certs`."""
        script = (
            "import hashlib, json, os\n"
            "out = {}\n"
            "for d, _, fs in os.walk('/certs'):\n"
            "    for f in fs:\n"
            "        if f in ('privkey.pem', 'cert.pem'):\n"
            "            p = os.path.join(d, f)\n"
            "            s = os.stat(p)\n"
            "            h = hashlib.sha256(open(p, 'rb').read()).hexdigest()\n"
            "            out[p] = [s.st_ino, s.st_mtime_ns, h]\n"
            "print(json.dumps(out, sort_keys=True))\n"
        )
        out = self.run_as("0:0", f'{PYTHON} -c "$SCRIPT"', {"SCRIPT": script})
        return json.loads(out.strip().splitlines()[-1])

    def close(self) -> None:
        # Every volume is removed even if one removal fails; a failure is still raised.
        with contextlib.ExitStack() as stack:
            for volume in self.volumes:
                stack.callback(volume.remove, force=True)


@pytest.fixture
def deployment(tmp_path):
    deployed = _Deployment(tmp_path)
    try:
        yield deployed
    finally:
        deployed.close()


def test_rt1_replay_cannot_make_the_root_exporter_run_a_service_account_hook(
    deployment,
):
    """AC 7 (i): uid 1000 renames a config with `restartcontainers: true` and a hook into
    `/config`. Root mode is still forced, but the hook does not run, and the log says why."""
    deployment.boot()
    deployment.replace_config_as_puid(
        f"settings:\n  restartcontainers: true\n  postexportcommand: '{HOOK}'\n"
    )
    deployment.write_store(real_chain())

    logs = deployment.boot()

    assert ROOT_WARNING in logs, logs
    assert deployment.pwned() is None, logs
    assert (
        "Ignoring settings.postexportcommand from configuration file "
        "'/config/config.yaml'" in logs
    ), logs
    assert "Post-export command: not set" in logs, logs
    assert "runs as uid 0" in logs, logs


def test_an_environment_hook_still_runs_as_root_in_root_mode(deployment):
    """AC 7 (ii): the operator's own hook, from the container's environment, is unchanged."""
    deployment.write_store(real_chain())

    logs = deployment.boot({HOOK_ENV: HOOK, RESTART_ENV: "true"})

    pwned = deployment.pwned()
    assert pwned is not None and pwned.startswith("uid=0(root)"), logs
    assert "Post-export command: set (source: environment), runs as uid 0" in logs


def test_a_config_file_hook_runs_as_the_puid_account_in_dropped_mode(deployment):
    """AC 7 (iii): unprivileged, a `config.yaml` hook keeps working -- as `PUID`."""
    deployment.boot()
    deployment.replace_config_as_puid(
        f"settings:\n  restartcontainers: false\n  postexportcommand: '{HOOK}'\n"
    )
    deployment.write_store(real_chain())

    logs = deployment.boot()

    pwned = deployment.pwned()
    assert pwned is not None and pwned.startswith("uid=1000"), logs
    assert "runs as uid 1000" in logs, logs


def test_config_stays_puid_owned_and_editable_by_the_puid_account(deployment):
    """AC 7 (iv): LinuxServer's ownership convention is untouched."""
    deployment.write_store(real_chain())
    deployment.boot()

    owner = deployment.run_as("0:0", "stat -c '%u:%g' /config").strip()
    assert owner == "1000:1000"

    deployment.run_as(
        "1000:1000",
        "touch /config/probe && echo edited > /config/probe && "
        "cp /config/config.yaml /config/.tce-new && "
        "mv -f /config/.tce-new /config/config.yaml",
    )
    assert deployment.run_as("1000:1000", "cat /config/probe").strip() == "edited"


def test_a_forged_store_named_by_a_config_file_filespec_is_not_exported_by_root(
    deployment,
):
    """AC 7 (v), AG-1: uid 1000 plants a store in `/config` and names it with `filespec`.
    Root must neither export it over the genuine files nor even process it."""
    deployment.boot()
    deployment.replace_config_as_puid("settings:\n  restartcontainers: true\n")
    deployment.write_store(real_chain())
    first = deployment.boot()
    assert ROOT_WARNING in first, first
    genuine = deployment.cert_files()
    assert any(p.endswith(f"{DOMAIN}/privkey.pem") for p in genuine), (genuine, first)
    assert any(p.endswith(f"{DOMAIN}/cert.pem") for p in genuine), (genuine, first)

    deployment.run_as(
        "1000:1000",
        'printf "%s" "$STORE" > /config/forged.json',
        {"STORE": _store(real_chain_expiring_in(7))},
    )
    deployment.replace_config_as_puid(
        "settings:\n  restartcontainers: true\n  filespec: /config/forged.json\n"
    )

    logs = deployment.boot()

    assert ROOT_WARNING in logs, logs
    assert deployment.cert_files() == genuine, logs
    assert (
        "Ignoring settings.filespec from configuration file '/config/config.yaml'"
        in logs
    ), logs
    assert "Processing file: /config/" not in logs, logs
