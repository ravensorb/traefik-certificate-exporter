import base64
import datetime
import json
import logging
import os
import stat
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from traefik_certificate_exporter.libs import certificate_exporter
from traefik_certificate_exporter.libs.certificate_exporter import (
    AcmeCertificateExporter,
)
from traefik_certificate_exporter.libs.settings import Settings

from ..fixtures.acme_fixtures import (
    acme_v1_fixture,
    acme_v2_lowercase_fixture,
    acme_v2_uppercase_fixture,
)


def _make_settings(**overrides) -> Settings:
    defaults = {
        "dataPath": "/data",
        "fileSpec": "*.json",
        "outputPath": "/certs",
        "resolverInPathName": False,
        "traefikResolverId": None,
        "flat": False,
        "dryRun": True,  # never touch disk for exported cert files in these tests
        "restartContainers": False,
        "domains": {"include": [], "exclude": []},
        "watchForChanges": False,
        "runAtStart": False,
        "watchInterval": 60,
        "pkcs12Passphrase": None,
    }
    defaults.update(overrides)
    return Settings(**defaults)


def _write_fixture(tmp_path, data: dict, name: str = "acme.json"):
    Path(tmp_path).mkdir(parents=True, exist_ok=True)
    path = Path(tmp_path) / name
    path.write_text(json.dumps(data))
    return str(path)


def test_acme_v1_shape_is_parsed(tmp_path):
    fixture_path = _write_fixture(tmp_path, acme_v1_fixture("v1.example.test"))
    exporter = AcmeCertificateExporter(settings=_make_settings())

    names = exporter.exportCertificatesForFile(fixture_path)

    assert names == ["v1.example.test"]


def test_acme_v2_lowercase_shape_is_parsed(tmp_path):
    fixture_path = _write_fixture(
        tmp_path, acme_v2_lowercase_fixture("v2-lower.example.test")
    )
    exporter = AcmeCertificateExporter(settings=_make_settings())

    names = exporter.exportCertificatesForFile(fixture_path)

    assert names == ["v2-lower.example.test"]


def test_acme_v2_uppercase_shape_is_parsed(tmp_path):
    fixture_path = _write_fixture(
        tmp_path, acme_v2_uppercase_fixture("v2-upper.example.test")
    )
    exporter = AcmeCertificateExporter(settings=_make_settings())

    names = exporter.exportCertificatesForFile(fixture_path)

    assert names == ["v2-upper.example.test"]


def test_domains_include_filters_out_non_matching_domain(tmp_path):
    fixture_path = _write_fixture(tmp_path, acme_v1_fixture("v1.example.test"))
    settings = _make_settings(
        domains={"include": ["other.example.test"], "exclude": []}
    )
    exporter = AcmeCertificateExporter(settings=settings)

    names = exporter.exportCertificatesForFile(fixture_path)

    assert names == []


def test_domains_exclude_filters_out_matching_domain(tmp_path):
    fixture_path = _write_fixture(tmp_path, acme_v1_fixture("v1.example.test"))
    settings = _make_settings(domains={"include": [], "exclude": ["v1.example.test"]})
    exporter = AcmeCertificateExporter(settings=settings)

    names = exporter.exportCertificatesForFile(fixture_path)

    assert names == []


def test_missing_file_returns_empty_list_not_an_exception(tmp_path):
    exporter = AcmeCertificateExporter(settings=_make_settings())

    names = exporter.exportCertificatesForFile(str(tmp_path / "does-not-exist.json"))

    assert names == []


def test_empty_file_returns_empty_list_not_an_exception(tmp_path):
    path = tmp_path / "empty.json"
    path.write_text("")
    exporter = AcmeCertificateExporter(settings=_make_settings())

    names = exporter.exportCertificatesForFile(str(path))

    assert names == []


def test_export_certificates_globs_data_path(tmp_path):
    _write_fixture(tmp_path, acme_v1_fixture("v1.example.test"), name="acme.json")
    settings = _make_settings(dataPath=str(tmp_path), fileSpec="*.json")
    exporter = AcmeCertificateExporter(settings=settings)

    processed = exporter.exportCertificates()

    assert processed == ["v1.example.test"]


###########################################################################################
# Atomic writes (ADR-0023 Decision 3, ADR-0024): a consumer must never observe a
# half-written certificate, whatever kills the process mid-pass.


def test_an_interrupted_write_leaves_the_previous_file_intact(tmp_path, monkeypatch):
    """The property, proved by injecting the failure rather than by a clean run.

    `Path.open("w")` truncates first, so the old content was gone before a single byte of
    the new content landed. The helper writes beside the target and renames, so a failure
    anywhere before the rename leaves the previous file exactly as it was.
    """
    target = tmp_path / "fullchain.pem"
    target.write_text("PREVIOUS CONTENT")

    def explode(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", explode)

    with pytest.raises(OSError):
        certificate_exporter._atomic_write_text(target, "NEW CONTENT")

    assert target.read_text() == "PREVIOUS CONTENT"


def test_an_interrupted_write_leaves_no_file_where_there_was_none(
    tmp_path, monkeypatch
):
    target = tmp_path / "fullchain.pem"

    def explode(*args, **kwargs):
        raise OSError("disk full")

    # Fails after the temp file holds the new bytes and before the rename -- the window
    # that `Path.open("w")` had no answer for.
    monkeypatch.setattr(os, "fsync", explode)

    with pytest.raises(OSError):
        certificate_exporter._atomic_write_text(target, "NEW CONTENT")

    assert not target.exists()


def test_an_interrupted_write_leaves_no_temp_file_behind(tmp_path, monkeypatch):
    """An orphaned `.tmp` sits in the directory a consumer globs for certificates."""
    target = tmp_path / "cert.pem"

    monkeypatch.setattr(
        os, "replace", lambda *a, **k: (_ for _ in ()).throw(OSError("boom"))
    )

    with pytest.raises(OSError):
        certificate_exporter._atomic_write_text(target, "NEW CONTENT")

    assert list(tmp_path.iterdir()) == []


def test_an_interrupted_pkcs12_write_leaves_the_previous_pfx_intact(
    tmp_path, monkeypatch
):
    """ADR-0024: the bytes path gets the same guarantee as the text one."""
    target = tmp_path / "cert.pfx"
    target.write_bytes(b"PREVIOUS PFX")

    monkeypatch.setattr(
        os, "replace", lambda *a, **k: (_ for _ in ()).throw(OSError("boom"))
    )

    with pytest.raises(OSError):
        certificate_exporter._atomic_write_bytes(target, b"NEW PFX")

    assert target.read_bytes() == b"PREVIOUS PFX"
    assert list(tmp_path.iterdir()) == [target]


def test_an_atomic_write_replaces_content_completely(tmp_path):
    target = tmp_path / "chain.pem"
    target.write_text("old")

    certificate_exporter._atomic_write_text(target, "new")

    assert target.read_text() == "new"
    assert list(tmp_path.iterdir()) == [target]


def test_an_atomic_write_matches_what_open_w_would_have_produced(tmp_path):
    """Permission parity for PUBLIC material: the tempfile default is 0o600, so without
    an explicit chmod every exported chain would become unreadable to the service that
    consumes it. Key-bearing artifacts are covered by the sibling below instead -- mode
    is split by content, not by umask."""
    reference = tmp_path / "reference.pem"
    with reference.open("w") as f:
        f.write("x")

    expected = reference.stat().st_mode & 0o7777

    for name in ("cert.pem", "chain.pem", "fullchain.pem"):
        target = tmp_path / name
        certificate_exporter._atomic_write_text(target, "x")

        assert (target.stat().st_mode & 0o7777) == expected


def test_key_bearing_artifacts_are_never_group_or_world_readable(tmp_path):
    """A 0o644 private key is a private key anyone on the host can read, and the default
    umask in the shipped image produces exactly that."""
    for name in ("privkey.pem", "example.test.key"):
        target = tmp_path / name
        certificate_exporter._atomic_write_text(
            target, "KEY", mode=certificate_exporter._SECRET_FILE_MODE
        )

        assert (target.stat().st_mode & 0o7777) == 0o600, name

    pfx = tmp_path / "cert.pfx"
    certificate_exporter._atomic_write_bytes(
        pfx, b"PFX", mode=certificate_exporter._SECRET_FILE_MODE
    )

    assert (pfx.stat().st_mode & 0o7777) == 0o600


def test_an_atomic_write_preserves_an_existing_files_permissions(tmp_path):
    """A re-export must not undo a hardening an operator applied to the key file."""
    target = tmp_path / "privkey.pem"
    target.write_text("old")
    os.chmod(target, 0o600)

    certificate_exporter._atomic_write_text(target, "new")

    assert (target.stat().st_mode & 0o7777) == 0o600


def test_the_temp_file_is_created_next_to_its_target(tmp_path):
    """`os.replace` is only atomic within one filesystem, and `outputPath` is commonly a
    bind mount -- so the temp file must never land in the system temp directory."""
    target = tmp_path / "nested" / "fullchain.pem"
    target.parent.mkdir()
    seen = {}

    real = tempfile.NamedTemporaryFile

    def record(*args, **kwargs):
        seen["dir"] = kwargs.get("dir")
        return real(*args, **kwargs)

    with patch.object(tempfile, "NamedTemporaryFile", record):
        certificate_exporter._atomic_write_text(target, "data")

    assert Path(seen["dir"]) == target.parent


def _real_material(domain: str):
    """A genuine key/cert pair, because the shared fixtures carry placeholder PEM text
    that `PemToPfxConverter` cannot load -- and the `.pfx` sites are half of what the
    end-to-end assertion below exists to cover (ADR-0024)."""
    key = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, domain)])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=30))
        .sign(key, hashes.SHA256())
    )
    keyPem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    certPem = cert.public_bytes(serialization.Encoding.PEM).decode()
    return keyPem, certPem + certPem


def _real_acme_fixture(domain: str) -> dict:
    keyPem, fullchainPem = _real_material(domain)
    data = acme_v1_fixture(domain)
    certificate = data["myresolver"]["DomainsCertificate"]["Certs"][0]["Certificate"]
    certificate["PrivateKey"] = base64.b64encode(keyPem.encode()).decode()
    certificate["Certificate"] = base64.b64encode(fullchainPem.encode()).decode()
    return data


def test_a_real_export_writes_every_artifact_atomically(tmp_path):
    """End-to-end over the exporter: all 10 sites go through the helper, so none of the
    emitted files may be left as a `.tmp`, and each must be complete."""
    fixture_path = _write_fixture(
        tmp_path / "data", _real_acme_fixture("flat.example.test")
    )
    outputPath = tmp_path / "certs"
    settings = _make_settings(
        dryRun=False, flat=True, outputPath=str(outputPath), pkcs12Passphrase=None
    )
    exporter = AcmeCertificateExporter(settings=settings)

    names = exporter.exportCertificatesForFile(fixture_path)

    assert names == ["flat.example.test"]
    written = sorted(p.name for p in outputPath.iterdir())
    assert written == [
        "flat.example.test.chain.pem",
        "flat.example.test.crt",
        "flat.example.test.fullchain.pem",
        "flat.example.test.key",
        "flat.example.test.pfx",
    ]
    assert all(p.stat().st_size > 0 for p in outputPath.iterdir())


def test_an_atomic_write_preserves_the_previous_owner_and_group(tmp_path):
    """`Path.open("w")` re-opened the existing inode, so owner/group survived a
    re-export. Replacing the inode does not -- and in the container profile (PUID/PGID,
    bind-mounted /certs) a key chowned to `root:traefik` silently losing its group is how
    the consuming service loses read access at the next renewal."""
    target = tmp_path / "privkey.pem"
    target.write_text("old")
    before = target.stat()
    attempted = {}

    real_chown = os.chown

    def spy(path, uid, gid):
        attempted["ids"] = (uid, gid)
        return real_chown(path, uid, gid)

    with patch.object(os, "chown", spy):
        certificate_exporter._atomic_write_text(target, "new")

    after = target.stat()
    assert attempted["ids"] == (before.st_uid, before.st_gid)
    assert (after.st_uid, after.st_gid) == (before.st_uid, before.st_gid)


def test_an_atomic_write_survives_being_unable_to_restore_ownership(tmp_path):
    """An unprivileged process cannot give a file away; failing to chown must not fail
    the export."""
    target = tmp_path / "cert.pem"
    target.write_text("old")

    def deny(*args, **kwargs):
        raise PermissionError("not permitted")

    with patch.object(os, "chown", deny):
        certificate_exporter._atomic_write_text(target, "new")

    assert target.read_text() == "new"


###########################################################################################
# Untrusted names reaching a filesystem path (RT-001). Each case is an INJECTED fault --
# a crafted acme store -- not a clean run that happens not to traverse.


@pytest.mark.parametrize(
    "domain",
    [
        "../escaped.example.test",
        "..",
        "a/../../b",
        "/tmp/absolute.example.test",
        "nul\x00byte.example.test",
        "sub/dir.example.test",
        "-leading-hyphen.example.test",
        # `$` matches before a trailing newline; `\Z` does not. Not a traversal, but it
        # created a directory whose name ended in a newline.
        "nl.example.test\n",
    ],
)
def test_a_crafted_domain_name_cannot_escape_the_output_path(tmp_path, caplog, domain):
    fixture_path = _write_fixture(tmp_path / "data", acme_v1_fixture(domain))
    outputPath = tmp_path / "certs"
    outputPath.mkdir()
    settings = _make_settings(dryRun=False, outputPath=str(outputPath))
    exporter = AcmeCertificateExporter(settings=settings)

    with caplog.at_level(logging.ERROR):
        names = exporter.exportCertificatesForFile(fixture_path)

    assert names == []
    assert list(outputPath.rglob("*")) == [], (
        "a crafted domain name chose where the private key landed"
    )
    assert any("Refusing to export" in r.getMessage() for r in caplog.records)


def test_a_rejected_domains_control_characters_do_not_reach_the_log_sink(
    tmp_path, caplog
):
    """EC-003: a rejected name is still interpolated into the refusal log message --
    CR/LF (log-line injection) and ESC/CSI (terminal-escape injection) must not survive
    into the rendered log record, even though the name itself was correctly refused as a
    path component and no file was written.
    """
    domain = "evil\x1b[31mFAKE ERROR\x1b[0m\ninjected-line"
    fixture_path = _write_fixture(tmp_path / "data", acme_v1_fixture(domain))
    outputPath = tmp_path / "certs"
    outputPath.mkdir()
    settings = _make_settings(dryRun=False, outputPath=str(outputPath))
    exporter = AcmeCertificateExporter(settings=settings)

    with caplog.at_level(logging.ERROR):
        names = exporter.exportCertificatesForFile(fixture_path)

    assert names == []
    refusal_records = [r for r in caplog.records if "Refusing to export" in r.getMessage()]
    assert refusal_records, "expected a refusal log record"
    for record in refusal_records:
        message = record.getMessage()
        assert "\x1b" not in message, "ESC/CSI sequence reached the log sink"
        assert "\n" not in message, "embedded newline reached the log sink (log forging)"
        assert "\r" not in message


def test_sanitize_for_log_strips_control_characters_and_passes_through_the_rest():
    assert (
        certificate_exporter._sanitize_for_log("evil\x1b[31mFAKE\x1b[0m\ninjected\r\n")
        == "evil[31mFAKE[0minjected"
    )
    assert certificate_exporter._sanitize_for_log(None) == ""
    assert certificate_exporter._sanitize_for_log("plain.example.test") == (
        "plain.example.test"
    )


def test_a_rejected_domain_does_not_stop_the_rest_of_the_sweep(tmp_path, caplog):
    """The per-domain `except` already establishes the shape: skip the one, keep going."""
    data = acme_v1_fixture("good.example.test")
    certs = data["myresolver"]["DomainsCertificate"]["Certs"]
    bad = json.loads(json.dumps(certs[0]))
    bad["Certificate"]["Domain"] = "../evil.example.test"
    certs.insert(0, bad)

    fixture_path = _write_fixture(tmp_path / "data", data)
    settings = _make_settings(dryRun=True, outputPath=str(tmp_path / "certs"))
    exporter = AcmeCertificateExporter(settings=settings)

    with caplog.at_level(logging.ERROR):
        names = exporter.exportCertificatesForFile(fixture_path)

    assert names == ["good.example.test"]


def test_a_crafted_domain_name_cannot_escape_in_flat_mode(tmp_path, caplog):
    """In flat mode the name becomes a FILENAME, which traverses just as well."""
    fixture_path = _write_fixture(
        tmp_path / "data", acme_v1_fixture("../../escaped.example.test")
    )
    outputPath = tmp_path / "certs"
    outputPath.mkdir()
    settings = _make_settings(dryRun=False, flat=True, outputPath=str(outputPath))
    exporter = AcmeCertificateExporter(settings=settings)

    with caplog.at_level(logging.ERROR):
        names = exporter.exportCertificatesForFile(fixture_path)

    assert names == []
    assert list(tmp_path.glob("**/escaped.example.test*")) == []


def test_a_crafted_resolver_name_cannot_escape_the_output_path(tmp_path, caplog):
    """`resolverName` is joined into the same path and comes from the same store."""
    data = acme_v1_fixture("resolver.example.test")
    data["../evil"] = data.pop("myresolver")

    fixture_path = _write_fixture(tmp_path / "data", data)
    outputPath = tmp_path / "certs"
    outputPath.mkdir()
    settings = _make_settings(
        dryRun=False, outputPath=str(outputPath), resolverInPathName=True
    )
    exporter = AcmeCertificateExporter(settings=settings)

    with caplog.at_level(logging.ERROR):
        names = exporter.exportCertificatesForFile(fixture_path)

    assert names == []
    assert list(outputPath.rglob("*")) == []
    assert any("resolver name" in r.getMessage() for r in caplog.records)


###########################################################################################
# Metadata inheritance (RT-003 / AD-05). The shipped image runs as root, so the chown
# restore SUCCEEDS -- which is what turns a planted placeholder into a handover.


def test_a_symlink_at_the_target_does_not_donate_its_metadata(tmp_path, caplog):
    elsewhere = tmp_path / "elsewhere.pem"
    elsewhere.write_text("decoy")
    os.chmod(elsewhere, 0o666)

    target = tmp_path / "privkey.pem"
    target.symlink_to(elsewhere)

    certificate_exporter._SYMLINK_WARNED.clear()
    with caplog.at_level(logging.WARNING):
        certificate_exporter._atomic_write_text(
            target, "KEY", mode=certificate_exporter._SECRET_FILE_MODE
        )

    assert not target.is_symlink(), "os.replace replaced the link, not its destination"
    assert target.read_text() == "KEY"
    assert (target.stat().st_mode & 0o7777) == 0o600
    assert elsewhere.read_text() == "decoy"
    assert any("symlink" in r.getMessage() for r in caplog.records)


def test_a_permissive_placeholder_does_not_dictate_the_key_mode(tmp_path, caplog):
    target = tmp_path / "privkey.pem"
    target.write_text("planted")
    os.chmod(target, 0o666)

    with caplog.at_level(logging.WARNING):
        certificate_exporter._atomic_write_text(
            target, "KEY", mode=certificate_exporter._SECRET_FILE_MODE
        )

    assert (target.stat().st_mode & 0o7777) == 0o600
    assert any(
        "refusing to inherit permissive mode" in r.getMessage() for r in caplog.records
    )


def test_a_placeholder_owned_by_another_uid_is_not_inherited(tmp_path, caplog):
    target = tmp_path / "privkey.pem"
    target.write_text("planted")
    os.chmod(target, 0o600)

    real_lstat = os.lstat

    def foreign(path, *args, **kwargs):
        info = real_lstat(path, *args, **kwargs)
        if str(path) == str(target):
            return os.stat_result(
                tuple(info)[:4] + (os.geteuid() + 4242, info.st_gid) + tuple(info)[6:]
            )
        return info

    attempted = []
    with (
        patch.object(os, "lstat", foreign),
        patch.object(os, "chown", lambda *a: attempted.append(a)),
        caplog.at_level(logging.WARNING),
    ):
        certificate_exporter._atomic_write_text(
            target, "KEY", mode=certificate_exporter._SECRET_FILE_MODE
        )

    assert attempted == [], "a fresh private key was handed to a foreign uid"
    assert (target.stat().st_mode & 0o7777) == 0o600
    assert any(
        "refusing to inherit ownership" in r.getMessage() for r in caplog.records
    )


def test_an_operators_tighter_mode_still_wins(tmp_path):
    """The reason inheritance exists at all: 0o640 under a 0o644 policy must survive."""
    target = tmp_path / "cert.pem"
    target.write_text("old")
    os.chmod(target, 0o640)

    certificate_exporter._atomic_write_text(target, "new")

    assert (target.stat().st_mode & 0o7777) == 0o640


###########################################################################################
# Durability and staging hygiene (AD-04/AD-06/AD-07).


def test_the_rename_is_followed_by_a_directory_fsync(tmp_path):
    """`fsync` on the file commits its content; the directory entry lives in the parent."""
    target = tmp_path / "cert.pem"
    synced = []
    real_fsync = os.fsync

    def spy(fd):
        try:
            if stat.S_ISDIR(os.fstat(fd).st_mode):
                synced.append(fd)
        except OSError:
            pass
        return real_fsync(fd)

    with patch.object(os, "fsync", spy):
        certificate_exporter._atomic_write_text(target, "data")

    assert synced, "the rename was never made durable"


def test_a_filesystem_that_rejects_a_directory_fsync_does_not_fail_the_export(
    tmp_path, caplog
):
    target = tmp_path / "cert.pem"
    real_open = os.open

    def deny(path, flags, *args, **kwargs):
        if os.path.isdir(path):
            raise OSError("not supported")
        return real_open(path, flags, *args, **kwargs)

    with patch.object(os, "open", deny), caplog.at_level(logging.DEBUG):
        certificate_exporter._atomic_write_text(target, "data")

    assert target.read_text() == "data"


def test_the_staging_file_holds_key_material_at_0600_until_it_is_complete(tmp_path):
    """SIGKILL mid-write must not leave a world-readable key behind under a 0o644 policy."""
    target = tmp_path / "cert.pem"
    observed = {}

    class Recorder(str):
        pass

    real_chmod = os.chmod
    seen_modes = []

    def spy_chmod(path, mode):
        observed["mode_at_chmod"] = Path(path).stat().st_mode & 0o7777
        seen_modes.append(mode)
        return real_chmod(path, mode)

    with patch.object(os, "chmod", spy_chmod):
        certificate_exporter._atomic_write_text(target, "x" * 1000)

    assert observed["mode_at_chmod"] == 0o600, (
        "the staging file carried the final, looser mode while it was still being written"
    )


def test_a_stale_staging_file_is_reaped_by_the_next_export_pass(tmp_path):
    """SIGKILL between create and `os.replace` leaves a full private key behind, and
    nothing else ever collects it."""
    fixture_path = _write_fixture(
        tmp_path / "data", _real_acme_fixture("sweep.example.test")
    )
    outputPath = tmp_path / "certs" / "sweep.example.test"
    outputPath.mkdir(parents=True)

    stale = outputPath / ".privkey.pem.abcd1234.tmp"
    stale.write_text("-----BEGIN PRIVATE KEY-----")
    old = time.time() - 7200
    os.utime(stale, (old, old))

    fresh = outputPath / ".cert.pem.efgh5678.tmp"
    fresh.write_text("still in flight")

    settings = _make_settings(dryRun=False, outputPath=str(tmp_path / "certs"))
    AcmeCertificateExporter(settings=settings).exportCertificatesForFile(fixture_path)

    assert not stale.exists(), "a stale staging file still holds key material"
    assert fresh.exists(), (
        "a staging file from a live write was reaped out from under it"
    )


def test_the_default_file_mode_is_probed_once_at_import(monkeypatch):
    """AD-07: `os.umask` is a process-wide mutation with no read-only form. Probing it
    lazily meant probing it after the observer and timer threads existed."""
    calls = []
    monkeypatch.setattr(os, "umask", lambda mask: calls.append(mask) or 0o022)

    first = certificate_exporter._default_file_mode()
    second = certificate_exporter._default_file_mode()

    assert calls == [], "the umask was mutated at export time, not at import"
    assert first == second == certificate_exporter._DEFAULT_FILE_MODE
