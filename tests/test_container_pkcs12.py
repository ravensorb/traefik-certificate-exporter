"""Opt-in: a passphrase-protected `.pfx` produced by the real image (E014-S01-002, AC 11).

In 0.2.x, setting `pkcs12passphrase` made every PKCS12 export fail inside the image while
the unit suite stayed green. This test runs the built image in its default watch mode
against a real chain and opens the `.pfx` it wrote. It is required 0.3.0 release evidence;
E014-S02-005 runs it against the release-commit image:

    just image && TCE_DOCKER_INTEGRATION=1 poetry run pytest -m integration tests/test_container_pkcs12.py

The image under test is `${TCE_IMAGE:-traefik-certificate-exporter:local}`.
"""

import base64
import io
import json
import os
import tarfile
import time
import uuid
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.serialization import pkcs12

from traefik_certificate_exporter.libs.docker import DEFAULT_DOCKER_ENDPOINT

from .fixtures.acme_fixtures import real_chain

IMAGE = os.environ.get("TCE_IMAGE") or "traefik-certificate-exporter:local"
DOMAIN = "pkcs12.example.test"
PASSPHRASE = "s3cret"
# The image's default output path (Dockerfile ENV and the packaged config).
OUTPUT_PATH = "/certs"
POLL_SECONDS = 60


def _skip_reason() -> "str | None":
    if os.environ.get("TCE_DOCKER_INTEGRATION") != "1":
        return "image test is opt-in: set TCE_DOCKER_INTEGRATION=1"
    endpoint = os.environ.get("DOCKER_HOST") or DEFAULT_DOCKER_ENDPOINT
    if endpoint.startswith("unix://") and not Path(endpoint[7:]).exists():
        return f"no Docker socket at {endpoint[7:]}"
    return None


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(_skip_reason() is not None, reason=_skip_reason() or ""),
]


def _store() -> dict:
    chain = real_chain()
    return {
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


def _find_pfx(container) -> "bytes | None":
    """The exported `cert.pfx`, read through the Engine's archive API.

    The tar stream does not depend on the file's owner or mode, which matters here: the
    `.pfx` is 0600 and may be root-owned inside a volume the test process cannot read.
    """
    try:
        stream, _ = container.get_archive(OUTPUT_PATH)
    except Exception:  # noqa: BLE001 - not there yet; the caller polls
        return None
    with tarfile.open(fileobj=io.BytesIO(b"".join(stream))) as archive:
        for member in archive.getmembers():
            if member.isfile() and member.name.endswith(f"{DOMAIN}/cert.pfx"):
                handle = archive.extractfile(member)
                return handle.read() if handle else None
    return None


def test_the_image_exports_a_passphrase_protected_pfx_with_its_intermediate(tmp_path):
    import docker

    client = docker.from_env()
    try:
        client.images.get(IMAGE)
    except docker.errors.ImageNotFound:
        pytest.skip(f"image {IMAGE} not found; build it with `just image`")

    dataPath = tmp_path / "data"
    dataPath.mkdir()
    (dataPath / "acme.json").write_text(json.dumps(_store()))

    suffix = uuid.uuid4().hex[:8]
    volume = client.volumes.create(name=f"tce-pkcs12-it-{suffix}")
    container = None
    try:
        container = client.containers.run(
            IMAGE,
            name=f"tce-pkcs12-it-{suffix}",
            detach=True,
            environment={
                "TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_PKCS12PASSPHRASE": PASSPHRASE
            },
            volumes={
                str(dataPath): {"bind": "/data", "mode": "ro"},
                volume.name: {"bind": OUTPUT_PATH, "mode": "rw"},
            },
        )

        pfx = None
        deadline = time.monotonic() + POLL_SECONDS
        while pfx is None and time.monotonic() < deadline:
            time.sleep(1)
            pfx = _find_pfx(container)

        assert pfx is not None, (
            f"no cert.pfx within {POLL_SECONDS}s; container log tail:\n"
            + container.logs(tail=40).decode("utf-8", "replace")
        )

        chain = real_chain()
        key, leaf, cas = pkcs12.load_key_and_certificates(pfx, PASSPHRASE.encode())
        assert key is not None
        assert key.private_bytes(
            serialization.Encoding.DER,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ) == serialization.load_pem_private_key(chain.key_pem, None).private_bytes(
            serialization.Encoding.DER,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
        assert leaf is not None
        assert leaf == x509.load_pem_x509_certificate(chain.leaf_pem)
        assert cas == [x509.load_pem_x509_certificate(chain.intermediate_pem)]
    finally:
        try:
            if container is not None:
                container.remove(force=True)
        finally:
            volume.remove(force=True)
