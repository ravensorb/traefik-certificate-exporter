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
from cryptography.hazmat.primitives.serialization import pkcs12

from traefik_certificate_exporter.libs import certificate_exporter, logging_utils
from traefik_certificate_exporter.libs.certificate_exporter import (
    AcmeCertificateExporter,
    PemToPfxConverter,
)
from traefik_certificate_exporter.libs.settings import Settings

from ..fixtures.acme_fixtures import (
    RealChain,
    acme_legacy_v1_under_account,
    acme_mixed_case,
    acme_null_account,
    acme_null_certificates_resolver,
    acme_v1_fixture,
    acme_v2_certificate,
    acme_v2_lowercase_fixture,
    acme_v2_uppercase_fixture,
    acme_v3_fixture,
    acme_v17_single_store,
    real_chain,
    real_chain_expiring_in,
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


def test_a_real_export_writes_every_artifact_atomically(tmp_path):
    """End-to-end over the exporter: all 10 sites go through the helper, so none of the
    emitted files may be left as a `.tmp`, and each must be complete."""
    fixture_path = _write_fixture(
        tmp_path / "data", acme_v1_fixture("flat.example.test")
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
    refusal_records = [
        r for r in caplog.records if "Refusing to export" in r.getMessage()
    ]
    assert refusal_records, "expected a refusal log record"
    for record in refusal_records:
        message = record.getMessage()
        assert "\x1b" not in message, "ESC/CSI sequence reached the log sink"
        assert "\n" not in message, (
            "embedded newline reached the log sink (log forging)"
        )
        assert "\r" not in message


def test_sanitize_for_log_strips_control_characters_and_passes_through_the_rest():
    assert (
        logging_utils.sanitize_for_log("evil\x1b[31mFAKE\x1b[0m\ninjected\r\n")
        == "evil[31mFAKE[0minjected"
    )
    assert logging_utils.sanitize_for_log(None) == ""
    assert logging_utils.sanitize_for_log("plain.example.test") == (
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
        tmp_path / "data", acme_v1_fixture("sweep.example.test")
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


###########################################################################################
# PKCS12 export, chain parsing, build-before-replace and the per-domain change signal
# (E014-S01-002, ADR-0043). Every fixture below is real key material from `real_chain()`.

_DEFAULT_ARTIFACTS = (
    "privkey.pem",
    "cert.pem",
    "chain.pem",
    "fullchain.pem",
    "cert.pfx",
)


def _v2_store(*certificates: dict) -> dict:
    return {
        "myresolver": {
            "Account": {
                "Registration": {
                    "uri": "https://acme-v02.api.letsencrypt.org/directory"
                }
            },
            "Certificates": list(certificates),
        }
    }


def _export(tmp_path, store: dict, **overrides):
    """Write `store`, run one pass with a FRESH exporter, return (names, outputPath)."""
    fixture_path = _write_fixture(tmp_path / "data", store)
    outputPath = tmp_path / "certs"
    settings = _make_settings(
        **{"dryRun": False, "outputPath": str(outputPath), **overrides}
    )
    names = AcmeCertificateExporter(settings=settings).exportCertificatesForFile(
        fixture_path
    )
    return names, outputPath


def _snapshot(directory: Path) -> dict:
    """(inode, mtime_ns, bytes) per file: an unchanged artifact keeps all three."""
    return {
        p.name: (p.stat().st_ino, p.stat().st_mtime_ns, p.read_bytes())
        for p in sorted(directory.iterdir())
    }


def _der(cert: x509.Certificate) -> bytes:
    return cert.public_bytes(serialization.Encoding.DER)


def _key_der(key) -> bytes:
    return key.private_bytes(
        serialization.Encoding.DER,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )


def _one_byte_changed(chain: RealChain) -> RealChain:
    """The same chain with ONE byte of the leaf's DER changed.

    The last DER byte is the low byte of the ECDSA signature's `s` integer, so the
    certificate still parses (nothing here verifies signatures) and differs by exactly
    one byte -- the smallest change the store can carry.
    """
    der = bytearray(_der(x509.load_pem_x509_certificate(chain.leaf_pem)))
    der[-1] ^= 0x01
    leaf_pem = x509.load_der_x509_certificate(bytes(der)).public_bytes(
        serialization.Encoding.PEM
    )
    return chain._replace(
        leaf_pem=leaf_pem, fullchain_pem=leaf_pem + chain.intermediate_pem
    )


def _second_ca_pem() -> bytes:
    """A second, distinct CA-shaped certificate, to prove intermediate ORDER."""
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name(
        [x509.NameAttribute(x509.oid.NameOID.COMMON_NAME, "Second Intermediate")]
    )
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=30))
        .sign(key, hashes.SHA256())
    )
    return cert.public_bytes(serialization.Encoding.PEM)


def test_pkcs12_with_passphrase_round_trips_and_reports_the_domain(tmp_path):
    """B2: the ACME key is unencrypted PEM, so loading it WITH the passphrase raised
    `TypeError` after the PEMs were already rotated, and the domain went unreported."""
    chain = real_chain()
    names, outputPath = _export(
        tmp_path,
        _v2_store(acme_v2_certificate("pass.example.test")),
        pkcs12Passphrase="s3cret",
    )

    assert names == ["pass.example.test"]
    pfx = (outputPath / "pass.example.test" / "cert.pfx").read_bytes()
    key, leaf, cas = pkcs12.load_key_and_certificates(pfx, b"s3cret")
    assert key is not None and leaf is not None
    assert _key_der(key) == _key_der(
        serialization.load_pem_private_key(chain.key_pem, None)
    )
    assert _der(leaf) == _der(x509.load_pem_x509_certificate(chain.leaf_pem))
    assert len(cas) == 1


def test_pfx_includes_intermediates_in_order(tmp_path):
    """The PFX carried `cas=None`, so IIS/Java consumers had to fetch intermediates."""
    chain = real_chain()
    extra = x509.load_pem_x509_certificate(_second_ca_pem())
    fullchain = chain.fullchain_pem + extra.public_bytes(serialization.Encoding.PEM)
    store = _v2_store(
        acme_v2_certificate(
            "inter.example.test", chain._replace(fullchain_pem=fullchain)
        )
    )

    names, outputPath = _export(tmp_path, store)

    assert names == ["inter.example.test"]
    loaded = pkcs12.load_pkcs12(
        (outputPath / "inter.example.test" / "cert.pfx").read_bytes(), None
    )
    assert [_der(c.certificate) for c in loaded.additional_certs] == [
        _der(x509.load_pem_x509_certificate(chain.intermediate_pem)),
        _der(extra),
    ]


def test_single_certificate_fullchain_keeps_cert_pem_byte_for_byte(tmp_path):
    """`find(BEGIN, 1)` returned -1 for a one-certificate chain: `cert.pem` lost its final
    newline and `chain.pem` became a lone newline."""
    chain = real_chain()
    single = chain._replace(fullchain_pem=chain.leaf_pem)

    names, outputPath = _export(
        tmp_path, _v2_store(acme_v2_certificate("single.example.test", single))
    )

    directory = outputPath / "single.example.test"
    assert names == ["single.example.test"]
    assert (directory / "cert.pem").read_bytes() == chain.leaf_pem
    assert (directory / "chain.pem").read_bytes() == b""
    assert (directory / "fullchain.pem").read_bytes() == chain.leaf_pem


def test_a_two_certificate_fullchain_splits_into_leaf_and_chain(tmp_path):
    chain = real_chain()

    _, outputPath = _export(
        tmp_path, _v2_store(acme_v2_certificate("split.example.test"))
    )

    directory = outputPath / "split.example.test"
    assert (directory / "cert.pem").read_bytes() == chain.leaf_pem
    assert (directory / "chain.pem").read_bytes() == chain.intermediate_pem
    assert (directory / "fullchain.pem").read_bytes() == chain.fullchain_pem
    assert (directory / "privkey.pem").read_bytes() == chain.key_pem


def test_malformed_domain_leaves_existing_files_byte_identical(tmp_path, caplog):
    """M4: the PFX was built LAST, so a domain that could not be exported still had its
    four PEM files rotated -- a new key next to a stale PFX, never reported."""
    badCert = acme_v2_certificate("bad-cert.example.test")
    badCert["certificate"] = base64.b64encode(
        b"-----BEGIN CERTIFICATE-----\nbm90IGEgY2VydGlmaWNhdGU=\n"
        b"-----END CERTIFICATE-----\n"
    ).decode()
    badKey = acme_v2_certificate("bad-key.example.test")
    badKey["key"] = base64.b64encode(b"not a PEM private key\n").decode()

    outputPath = tmp_path / "certs"
    seeded = {}
    for domain in ("bad-cert.example.test", "bad-key.example.test"):
        directory = outputPath / domain
        directory.mkdir(parents=True)
        for artifact in _DEFAULT_ARTIFACTS:
            (directory / artifact).write_bytes(f"OLD {artifact}\n".encode())
        seeded[domain] = _snapshot(directory)

    with caplog.at_level(logging.ERROR):
        names, _ = _export(
            tmp_path,
            _v2_store(badCert, badKey, acme_v2_certificate("good.example.test")),
        )

    assert names == ["good.example.test"]
    for domain, before in seeded.items():
        assert _snapshot(outputPath / domain) == before, domain
    assert sorted(p.name for p in (outputPath / "good.example.test").iterdir()) == (
        sorted(_DEFAULT_ARTIFACTS)
    )
    messages = [r.getMessage() for r in caplog.records if r.levelno == logging.ERROR]
    assert any(
        "bad-cert.example.test" in m and "certificate chain" in m for m in messages
    )
    assert any("bad-key.example.test" in m and "key" in m for m in messages)


def test_second_export_of_unchanged_store_rewrites_and_reports_nothing(tmp_path):
    fixture_path = _write_fixture(
        tmp_path / "data", _v2_store(acme_v2_certificate("same.example.test"))
    )
    outputPath = tmp_path / "certs"
    exporter = AcmeCertificateExporter(
        settings=_make_settings(dryRun=False, outputPath=str(outputPath))
    )

    assert exporter.exportCertificatesForFile(fixture_path) == ["same.example.test"]
    before = _snapshot(outputPath / "same.example.test")

    assert exporter.exportCertificatesForFile(fixture_path) == []
    assert _snapshot(outputPath / "same.example.test") == before


def test_fresh_exporter_over_existing_output_reports_nothing(tmp_path):
    """The files on disk are the state: nothing in the exporter instance is."""
    store = _v2_store(acme_v2_certificate("restart.example.test"))
    names, outputPath = _export(tmp_path, store, pkcs12Passphrase="s3cret")
    assert names == ["restart.example.test"]
    before = _snapshot(outputPath / "restart.example.test")

    names, _ = _export(tmp_path, store, pkcs12Passphrase="s3cret")

    assert names == []
    assert _snapshot(outputPath / "restart.example.test") == before


def test_one_byte_change_reports_only_that_domain(tmp_path):
    chain = real_chain()
    store = _v2_store(
        acme_v2_certificate("stays.example.test"),
        acme_v2_certificate("moves.example.test"),
    )
    _, outputPath = _export(tmp_path, store)
    stays = _snapshot(outputPath / "stays.example.test")
    moves = _snapshot(outputPath / "moves.example.test")

    store = _v2_store(
        acme_v2_certificate("stays.example.test"),
        acme_v2_certificate("moves.example.test", _one_byte_changed(chain)),
    )
    names, _ = _export(tmp_path, store)

    assert names == ["moves.example.test"]
    assert _snapshot(outputPath / "stays.example.test") == stays
    after = _snapshot(outputPath / "moves.example.test")
    rewritten = sorted(name for name in after if after[name] != moves[name])
    assert rewritten == ["cert.pem", "cert.pfx", "fullchain.pem"]


def test_deleted_output_file_is_rewritten_and_reported(tmp_path):
    store = _v2_store(acme_v2_certificate("deleted.example.test"))
    _, outputPath = _export(tmp_path, store)
    directory = outputPath / "deleted.example.test"
    before = _snapshot(directory)
    (directory / "chain.pem").unlink()

    names, _ = _export(tmp_path, store)

    assert names == ["deleted.example.test"]
    after = _snapshot(directory)
    assert after["chain.pem"][2] == before["chain.pem"][2]
    assert {k: v for k, v in after.items() if k != "chain.pem"} == {
        k: v for k, v in before.items() if k != "chain.pem"
    }


def test_changed_passphrase_rewrites_only_the_pfx(tmp_path):
    store = _v2_store(acme_v2_certificate("rekey.example.test"))
    _, outputPath = _export(tmp_path, store)
    directory = outputPath / "rekey.example.test"

    # unencrypted -> encrypted, then one passphrase -> another, then no change at all.
    for passphrase in ("s3cret", "other"):
        before = _snapshot(directory)

        names, _ = _export(tmp_path, store, pkcs12Passphrase=passphrase)

        assert names == ["rekey.example.test"], passphrase
        after = _snapshot(directory)
        assert sorted(n for n in after if after[n] != before[n]) == ["cert.pfx"]
        pkcs12.load_key_and_certificates(
            (directory / "cert.pfx").read_bytes(), passphrase.encode()
        )

    before = _snapshot(directory)
    assert _export(tmp_path, store, pkcs12Passphrase="other")[0] == []
    assert _snapshot(directory) == before


def test_encrypted_pfx_builds_differ_byte_for_byte():
    """Design-premise evidence (ADR-0043): PKCS12 encryption draws a fresh salt and IV
    per build, so the PFX cannot be change-tested by bytes and is compared by content."""
    chain = real_chain()
    certs = x509.load_pem_x509_certificates(chain.fullchain_pem)

    first = PemToPfxConverter.build_pkcs12(chain.key_pem, certs, "s3cret")
    second = PemToPfxConverter.build_pkcs12(chain.key_pem, certs, "s3cret")

    assert first != second
    for pfx in (first, second):
        _, leaf, cas = pkcs12.load_key_and_certificates(pfx, b"s3cret")
        assert leaf is not None
        assert [_der(leaf), *(_der(c) for c in cas)] == [_der(c) for c in certs]


def test_write_failure_mid_set_reports_domain_with_error(tmp_path, monkeypatch, caplog):
    """Two artifacts already replaced when the third write fails: the domain's files DID
    change, so it is reported, and the ERROR says exactly what was and was not written."""
    calls = {"n": 0}
    realText = certificate_exporter._atomic_write_text
    realBytes = certificate_exporter._atomic_write_bytes

    def failing(real):
        def write(target, data, mode=None):
            calls["n"] += 1
            if calls["n"] == 3:
                raise OSError(28, "No space left on device")
            return real(target, data, mode=mode)

        return write

    monkeypatch.setattr(certificate_exporter, "_atomic_write_text", failing(realText))
    monkeypatch.setattr(certificate_exporter, "_atomic_write_bytes", failing(realBytes))

    with caplog.at_level(logging.ERROR):
        names, outputPath = _export(
            tmp_path, _v2_store(acme_v2_certificate("partial.example.test"))
        )

    assert names == ["partial.example.test"]
    assert sorted(p.name for p in (outputPath / "partial.example.test").iterdir()) == [
        "cert.pem",
        "privkey.pem",
    ]
    errors = [r.getMessage() for r in caplog.records if r.levelno == logging.ERROR]
    assert len(errors) == 1
    assert "partial.example.test" in errors[0]
    for artifact in _DEFAULT_ARTIFACTS:
        assert artifact in errors[0]

    # The files are the state: the next pass writes what the failed one did not.
    monkeypatch.setattr(certificate_exporter, "_atomic_write_text", realText)
    monkeypatch.setattr(certificate_exporter, "_atomic_write_bytes", realBytes)
    names, _ = _export(tmp_path, _v2_store(acme_v2_certificate("partial.example.test")))
    assert names == ["partial.example.test"]
    assert sorted(p.name for p in (outputPath / "partial.example.test").iterdir()) == (
        sorted(_DEFAULT_ARTIFACTS)
    )


def test_empty_passphrase_yields_unencrypted_pfx(tmp_path):
    chain = real_chain()
    certs = x509.load_pem_x509_certificates(chain.fullchain_pem)

    for empty in (None, "", b""):
        pfx = PemToPfxConverter.build_pkcs12(chain.key_pem, certs, empty)
        key, _, _ = pkcs12.load_key_and_certificates(pfx, None)
        assert key is not None, repr(empty)

    for secret in ("s3cret", b"s3cret"):
        pfx = PemToPfxConverter.build_pkcs12(chain.key_pem, certs, secret)
        with pytest.raises(ValueError):
            pkcs12.load_key_and_certificates(pfx, None)

    names, outputPath = _export(
        tmp_path,
        _v2_store(acme_v2_certificate("empty.example.test")),
        pkcs12Passphrase="",
    )
    assert names == ["empty.example.test"]
    pkcs12.load_key_and_certificates(
        (outputPath / "empty.example.test" / "cert.pfx").read_bytes(), None
    )


def test_dry_run_reports_build_errors_and_writes_nothing(tmp_path, caplog):
    badCert = acme_v2_certificate("bad.example.test")
    badCert["certificate"] = base64.b64encode(b"no certificate here\n").decode()

    with caplog.at_level(logging.ERROR):
        names, outputPath = _export(
            tmp_path,
            _v2_store(badCert, acme_v2_certificate("good.example.test")),
            dryRun=True,
        )

    assert names == ["good.example.test"]
    assert not outputPath.exists() or list(outputPath.rglob("*")) == []
    assert any(
        "bad.example.test" in r.getMessage() and r.levelno == logging.ERROR
        for r in caplog.records
    )


def test_dry_run_over_unchanged_output_reports_nothing(tmp_path):
    store = _v2_store(acme_v2_certificate("dry.example.test"))
    _, outputPath = _export(tmp_path, store)
    before = _snapshot(outputPath / "dry.example.test")

    assert _export(tmp_path, store, dryRun=True)[0] == []
    assert _snapshot(outputPath / "dry.example.test") == before


def test_flat_layout_is_change_tested_by_its_own_names(tmp_path):
    chain = real_chain()
    store = _v2_store(acme_v2_certificate("flat2.example.test"))

    names, outputPath = _export(tmp_path, store, flat=True)

    assert names == ["flat2.example.test"]
    assert (outputPath / "flat2.example.test.crt").read_bytes() == chain.fullchain_pem
    assert (outputPath / "flat2.example.test.chain.pem").read_bytes() == (
        chain.intermediate_pem
    )
    before = _snapshot(outputPath)
    assert _export(tmp_path, store, flat=True)[0] == []
    assert _snapshot(outputPath) == before


def test_a_permissive_unchanged_key_is_repaired_in_place_not_counted_as_changed(
    tmp_path, caplog
):
    """ADV-2: skipping unchanged files must not freeze a loosened key at its loose mode,
    but a mode-only difference is a policy repair, not a certificate change. A hook that
    runs `chmod 0640 privkey.pem` must not cause a rewrite, a hook run, a notification and
    a restart on every pass: the mode is put back with `os.chmod` (mtime and inode kept),
    one WARNING is logged, and the domain is not reported as changed."""
    store = _v2_store(acme_v2_certificate("mode.example.test"))
    _, outputPath = _export(tmp_path, store)
    domainDir = outputPath / "mode.example.test"
    key = domainDir / "privkey.pem"
    secrets = [key, *domainDir.glob("*.pfx")]
    assert len(secrets) == 2
    for path in secrets:
        os.chmod(path, 0o640)
    before = {
        n: (ino, mtime, data) for n, (ino, mtime, data) in _snapshot(domainDir).items()
    }

    with caplog.at_level(logging.WARNING):
        names, _ = _export(tmp_path, store)

    assert names == [], "a mode-only difference must not count as a change"
    for path in secrets:
        assert (path.stat().st_mode & 0o7777) == 0o600
    assert _snapshot(domainDir) == before, "repaired in place: no rewrite"
    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 2 and all("0640" in w and "0600" in w for w in warnings)


def test_a_permissive_key_is_not_repaired_in_a_dry_run(tmp_path, caplog):
    store = _v2_store(acme_v2_certificate("drymode.example.test"))
    _, outputPath = _export(tmp_path, store)
    key = outputPath / "drymode.example.test" / "privkey.pem"
    os.chmod(key, 0o644)

    with caplog.at_level(logging.WARNING):
        names, _ = _export(tmp_path, store, dryRun=True)

    assert names == []
    assert (key.stat().st_mode & 0o7777) == 0o644
    assert any("[DRYRUN]" in r.getMessage() for r in caplog.records)


def test_a_leaf_without_a_common_name_exports_quietly(tmp_path, caplog):
    """A CN-less leaf is valid (Let's Encrypt shortlived/tlsserver profiles). The PKCS12
    is built on every pass, so its friendly-name fallback must not log an ERROR each time."""
    chain = real_chain()
    key = serialization.load_pem_private_key(chain.key_pem, None)
    assert isinstance(key, ec.EllipticCurvePrivateKey)
    issuer = x509.load_pem_x509_certificate(chain.intermediate_pem)
    signer = ec.generate_private_key(ec.SECP256R1())
    now = datetime.datetime.now(datetime.timezone.utc)
    leaf = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([]))
        .issuer_name(issuer.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=30))
        .sign(signer, hashes.SHA256())
    )
    leafPem = leaf.public_bytes(serialization.Encoding.PEM)
    noCn = chain._replace(
        leaf_pem=leafPem, fullchain_pem=leafPem + chain.intermediate_pem
    )
    store = _v2_store(acme_v2_certificate("nocn.example.test", noCn))

    with caplog.at_level(logging.ERROR):
        assert _export(tmp_path, store)[0] == ["nocn.example.test"]
        assert _export(tmp_path, store)[0] == []

    assert [r for r in caplog.records if r.levelno >= logging.ERROR] == []


###########################################################################################
# Store shapes (E014-S01-003): detected by the keys present, never by the CA's URI;
# null-safe; each resolver isolated from the others; strict base64 (BL-E011-018).


def _resolver(*certificates: dict, account: object = "default") -> dict:
    """One resolver node with the given `Certificates` entries."""
    if account == "default":
        account = {"Registration": {"uri": "https://ca.example.test/acct/1"}}
    return {"Account": account, "Certificates": list(certificates)}


def _messages(caplog, level: int) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.levelno == level]


def test_invalid_base64_key_fails_only_that_certificate(tmp_path, caplog):
    """`b64decode` without `validate=True` discards non-alphabet bytes: a corrupt value
    decoded to garbage (or, smuggled into a valid one, to the original bytes)."""
    chain = real_chain()
    valid = base64.b64encode(chain.key_pem).decode("ascii")
    notBase64 = acme_v2_certificate("not-base64.example.test")
    notBase64["key"] = "!!!not-base64"
    smuggled = acme_v2_certificate("smuggled.example.test")
    smuggled["key"] = valid[:8] + "!*" + valid[8:]

    with caplog.at_level(logging.ERROR):
        names, outputPath = _export(
            tmp_path,
            _v2_store(acme_v2_certificate("good.example.test"), notBase64, smuggled),
        )

    assert names == ["good.example.test"]
    assert sorted(p.name for p in outputPath.iterdir()) == ["good.example.test"]
    errors = _messages(caplog, logging.ERROR)
    for domain in ("not-base64.example.test", "smuggled.example.test"):
        mine = [m for m in errors if domain in m]
        assert len(mine) == 1 and "the key could not be built" in mine[0]


def test_zerossl_v3_store_is_exported(tmp_path):
    names, outputPath = _export(tmp_path, acme_v3_fixture("zerossl.example.test"))

    assert names == ["zerossl.example.test"]
    assert (outputPath / "zerossl.example.test" / "fullchain.pem").is_file()


def test_null_account_store_exports(tmp_path, caplog):
    with caplog.at_level(logging.WARNING):
        names, _ = _export(tmp_path, acme_null_account("null-account.example.test"))

    assert names == ["null-account.example.test"]
    assert _messages(caplog, logging.ERROR) == []


def test_null_registration_and_missing_uri_export(tmp_path, caplog):
    store = {
        "nullreg": _resolver(
            acme_v2_certificate("null-reg.example.test"),
            account={"Email": "ops@example.test", "Registration": None},
        ),
        "nouri": _resolver(
            acme_v2_certificate("no-uri.example.test"),
            account={"Registration": {"body": {"status": "valid"}}},
        ),
    }
    with caplog.at_level(logging.DEBUG):
        names, _ = _export(tmp_path, store)

    assert names == ["null-reg.example.test", "no-uri.example.test"]
    assert _messages(caplog, logging.ERROR) == []


def test_two_resolvers_second_broken_returns_first_resolvers_domains(tmp_path, caplog):
    for broken in (
        acme_null_certificates_resolver("second")["second"],
        {"Account": None, "Certificates": "not-a-list"},
    ):
        store = {
            "first": _resolver(acme_v2_certificate("first.example.test")),
            "second": broken,
        }
        caplog.clear()
        with caplog.at_level(logging.WARNING):
            names, _ = _export(tmp_path / str(len(str(broken))), store)

        assert names is not None
        assert names == ["first.example.test"]


def test_empty_store_returns_empty_list_with_warning(tmp_path, caplog):
    for data in ({}, [], {"foo": 1}):
        caplog.clear()
        path = tmp_path / "acme.json"
        path.write_text(json.dumps(data))
        exporter = AcmeCertificateExporter(settings=_make_settings())

        with caplog.at_level(logging.WARNING):
            names = exporter.exportCertificatesForFile(str(path))

        assert names == []
        assert (
            len(
                [
                    m
                    for m in _messages(caplog, logging.WARNING)
                    if "no resolver node found" in m
                ]
            )
            == 1
        )


def test_non_resolver_top_level_key_is_skipped_with_warning(tmp_path, caplog):
    """The first key used to decide the shape of the whole file."""
    store = {"foo": 1, **acme_v2_lowercase_fixture("after-foo.example.test")}

    with caplog.at_level(logging.WARNING):
        names, _ = _export(tmp_path, store)

    assert names == ["after-foo.example.test"]
    assert any("'foo'" in m for m in _messages(caplog, logging.WARNING))


def test_mixed_case_entries_export_both(tmp_path):
    names, outputPath = _export(
        tmp_path, acme_mixed_case("lower.example.test", "upper.example.test")
    )

    assert names == ["lower.example.test", "upper.example.test"]
    assert (outputPath / "upper.example.test" / "cert.pfx").is_file()


def test_v17_single_store_and_legacy_v1_under_account_export(tmp_path):
    names, _ = _export(tmp_path / "v17", acme_v17_single_store("v17.example.test"))
    assert names == ["v17.example.test"]

    names, _ = _export(
        tmp_path / "legacy", acme_legacy_v1_under_account("legacy.example.test")
    )
    assert names == ["legacy.example.test"]


def test_file_level_failures_return_empty_list(tmp_path, caplog):
    exporter = AcmeCertificateExporter(settings=_make_settings())
    cases = {
        "missing.json": None,
        "empty.json": "",
        "invalid.json": "{not json",
        "deep.json": "[" * 200_000 + "]" * 200_000,
    }
    for name, content in cases.items():
        path = tmp_path / name
        if content is not None:
            path.write_text(content)
        caplog.clear()

        with caplog.at_level(logging.ERROR):
            names = exporter.exportCertificatesForFile(str(path))

        assert names == [], name
        assert len(_messages(caplog, logging.ERROR)) == 1, name


def test_n_of_m_resolvers_failed_warning(tmp_path, caplog):
    store = {
        "good": _resolver(acme_v2_certificate("good.example.test")),
        "broken1": {"Account": None, "Certificates": "x"},
        "broken2": {"Account": None, "Certificates": 5},
    }
    with caplog.at_level(logging.WARNING):
        names, _ = _export(tmp_path, store)

    assert names == ["good.example.test"]
    errors = _messages(caplog, logging.ERROR)
    assert len([m for m in errors if "broken1" in m]) == 1
    assert len([m for m in errors if "broken2" in m]) == 1
    assert [
        m for m in _messages(caplog, logging.WARNING) if "resolvers failed" in m
    ] == [f"2 of 3 resolvers failed in {tmp_path / 'data' / 'acme.json'}"]


def test_missing_named_resolver_warns_and_returns_empty(tmp_path, caplog):
    store = {
        "myresolver": _resolver(acme_v2_certificate("mine.example.test")),
        "other": _resolver(acme_v2_certificate("other.example.test")),
    }
    with caplog.at_level(logging.WARNING):
        names, _ = _export(tmp_path / "absent", store, traefikResolverId="absent")
    assert names == []
    assert any("'absent'" in m for m in _messages(caplog, logging.WARNING))

    names, _ = _export(tmp_path / "named", store, traefikResolverId="myresolver")
    assert names == ["mine.example.test"]


def _two_resolver_store(first: RealChain, second: RealChain) -> dict:
    return {
        "first": _resolver(acme_v2_certificate("first.example.test", first)),
        "second": _resolver(acme_v2_certificate("second.example.test", second)),
    }


def test_unchanged_two_resolver_store_second_call_returns_nothing(tmp_path):
    chain = real_chain()
    store = _two_resolver_store(chain, chain)

    names, _ = _export(tmp_path, store)
    assert names == ["first.example.test", "second.example.test"]

    names, _ = _export(tmp_path, store)
    assert names == []


def test_change_in_second_resolver_returns_only_its_domain(tmp_path):
    chain = real_chain()
    _export(tmp_path, _two_resolver_store(chain, chain))

    names, _ = _export(tmp_path, _two_resolver_store(chain, _one_byte_changed(chain)))

    assert names == ["second.example.test"]


def test_changed_first_resolver_and_broken_second_returns_first(tmp_path):
    chain = real_chain()
    _export(tmp_path, _two_resolver_store(chain, chain))
    store = _two_resolver_store(_one_byte_changed(chain), chain)
    store["second"]["Certificates"] = "structurally broken"

    names, _ = _export(tmp_path, store)

    assert names == ["first.example.test"]


def test_resolver_name_traversal_writes_nothing_outside_output(tmp_path, caplog):
    store = {
        **acme_v3_fixture("escape.example.test", resolver="../escape"),
        **acme_v3_fixture("safe.example.test", resolver="safe"),
    }
    with caplog.at_level(logging.ERROR):
        names, outputPath = _export(tmp_path, store, resolverInPathName=True)

    assert names == ["safe.example.test"]
    assert not (tmp_path / "escape").exists()
    assert sorted(
        str(p.relative_to(outputPath)) for p in outputPath.rglob("*") if p.is_dir()
    ) == ["safe", "safe/safe.example.test"]
    assert any("resolver name" in m for m in _messages(caplog, logging.ERROR))


def test_domain_held_by_two_resolvers_is_exported_once_and_stays_quiet(
    tmp_path, caplog
):
    """BL-E014-012: without the resolver in the path both resolvers target the same
    files. The first in store order keeps them; the second is skipped with a WARNING
    instead of overwriting them on every pass."""
    chain = real_chain()
    store = {
        "dns": _resolver(acme_v2_certificate("both.example.test", chain)),
        "http": _resolver(
            acme_v2_certificate("both.example.test", _one_byte_changed(chain))
        ),
    }
    with caplog.at_level(logging.WARNING):
        names, outputPath = _export(tmp_path, store)
    assert names == ["both.example.test"]
    directory = outputPath / "both.example.test"
    assert (directory / "cert.pem").read_bytes() == chain.leaf_pem
    assert any(
        "'dns'" in m and "'http'" in m for m in _messages(caplog, logging.WARNING)
    )
    before = _snapshot(directory)

    names, _ = _export(tmp_path, store)

    assert names == []
    assert _snapshot(directory) == before

    names, outputPath = _export(tmp_path / "split", store, resolverInPathName=True)
    assert names == ["both.example.test"]
    assert (outputPath / "http" / "both.example.test" / "cert.pem").is_file()


def test_the_entry_that_expires_last_owns_shared_files(tmp_path, caplog):
    """A stale resolver left in the store must not win just by sorting first, and a
    wildcard and its apex in one resolver (same directory once `*.` is stripped) must
    not overwrite each other on every pass. A wildcard that does not cover the apex
    loses to the apex entry even when it expires later (ADV-4)."""
    stale = real_chain()
    fresh = real_chain_expiring_in(60)
    store = {
        "le": _resolver(acme_v2_certificate("moved.example.test", stale)),
        "le-dns": _resolver(acme_v2_certificate("moved.example.test", fresh)),
        "wild": _resolver(
            acme_v2_certificate("*.pair.example.test", fresh),
            acme_v2_certificate("pair.example.test", stale),
        ),
    }
    with caplog.at_level(logging.WARNING):
        names, outputPath = _export(tmp_path, store)

    assert names == ["moved.example.test", "pair.example.test"]
    assert (outputPath / "moved.example.test" / "cert.pem").read_bytes() == (
        fresh.leaf_pem
    )
    assert (outputPath / "pair.example.test" / "cert.pem").read_bytes() == (
        stale.leaf_pem
    )
    warnings = _messages(caplog, logging.WARNING)
    moved = [m for m in warnings if "'le'" in m and "'le-dns'" in m]
    assert len(moved) == 1 and "resolverinpathname" in moved[0]
    pair = [m for m in warnings if "'*.pair.example.test'" in m]
    assert len(pair) == 1 and "resolverinpathname" not in pair[0]

    before = {d: _snapshot(outputPath / d) for d in names}
    names, _ = _export(tmp_path, store)
    assert names == []
    assert {d: _snapshot(outputPath / d) for d in before} == before


def _with_sans(entry: dict, *sans: str) -> dict:
    entry["domain"]["sans"] = list(sans)
    return entry


def test_apex_files_come_from_a_certificate_that_covers_the_apex(tmp_path, caplog):
    """ADV-4: `*.cover.example.test` and `cover.example.test` share one directory. A
    later-expiring wildcard whose SANs lack the apex must not become the apex's files;
    name coverage decides first, expiry only breaks a tie."""
    apex = real_chain()
    wildcard = real_chain_expiring_in(80)
    store = {
        "le": _resolver(
            acme_v2_certificate("*.cover.example.test", wildcard),
            acme_v2_certificate("cover.example.test", apex),
        )
    }
    with caplog.at_level(logging.WARNING):
        names, outputPath = _export(tmp_path / "nocover", store)

    assert names == ["cover.example.test"]
    assert (outputPath / "cover.example.test" / "cert.pem").read_bytes() == (
        apex.leaf_pem
    )
    skipped = [
        m for m in _messages(caplog, logging.WARNING) if "'*.cover.example.test'" in m
    ]
    assert len(skipped) == 1 and "does not cover" in skipped[0]

    # Both cover the apex (the wildcard lists it as a SAN): expiry breaks the tie.
    store = {
        "le": _resolver(
            _with_sans(
                acme_v2_certificate("*.cover.example.test", wildcard),
                "cover.example.test",
            ),
            acme_v2_certificate("cover.example.test", apex),
        )
    }
    names, outputPath = _export(tmp_path / "bothcover", store)
    assert names == ["cover.example.test"]
    assert (outputPath / "cover.example.test" / "cert.pem").read_bytes() == (
        wildcard.leaf_pem
    )


# ---------------------------------------------------------------------------
# Artifact paths and the restart lookup (E014-S01-006, ADR-0040). The writer takes its
# paths from `_artifact_paths`, records what it produced per store file, and
# `artifactMtime` reads only that record.
# ---------------------------------------------------------------------------

_LAYOUTS = [
    pytest.param(True, False, id="resolverinpathname-perdomain"),
    pytest.param(True, True, id="resolverinpathname-flat"),
    pytest.param(False, False, id="noresolver-perdomain"),
    pytest.param(False, True, id="noresolver-flat"),
]


@pytest.mark.parametrize("resolverInPathName, flat", _LAYOUTS)
@pytest.mark.parametrize("resolverName", ["le", None], ids=["wrapped", "unwrapped"])
def test_artifact_paths_layouts(resolverInPathName, flat, resolverName):
    base = Path("/out")
    paths = certificate_exporter._artifact_paths(
        base,
        resolverName,
        "a.example.test",
        flat=flat,
        resolverInPathName=resolverInPathName,
    )

    directory = base / "le" if resolverInPathName and resolverName else base
    if flat:
        expected = [
            directory / "a.example.test.key",
            directory / "a.example.test.crt",
            directory / "a.example.test.chain.pem",
            directory / "a.example.test.fullchain.pem",
            directory / "a.example.test.pfx",
        ]
    else:
        directory = directory / "a.example.test"
        expected = [
            directory / n
            for n in (
                "privkey.pem",
                "cert.pem",
                "chain.pem",
                "fullchain.pem",
                "cert.pfx",
            )
        ]
    assert paths == expected


def _lookup_env(tmp_path, store, name="acme.json", **overrides):
    fixture = _write_fixture(tmp_path / "data", store, name=name)
    outputPath = tmp_path / "certs"
    settings = _make_settings(
        **{
            "dryRun": False,
            "outputPath": str(outputPath),
            "dataPath": str(tmp_path / "data"),
            **overrides,
        }
    )
    return AcmeCertificateExporter(settings=settings), fixture, outputPath


def _files(directory: Path) -> list[Path]:
    return sorted(p for p in directory.rglob("*") if p.is_file())


@pytest.mark.parametrize("resolverInPathName, flat", _LAYOUTS)
def test_artifact_mtime_finds_every_layout(tmp_path, resolverInPathName, flat):
    exporter, fixture, outputPath = _lookup_env(
        tmp_path,
        {"le": _resolver(acme_v2_certificate("a.example.test", real_chain()))},
        resolverInPathName=resolverInPathName,
        flat=flat,
    )
    exporter.exportCertificatesForFile(fixture)

    written = certificate_exporter._artifact_paths(
        outputPath,
        "le",
        "a.example.test",
        flat=flat,
        resolverInPathName=resolverInPathName,
    )
    assert _files(outputPath) == sorted(written)
    for offset, path in enumerate(written):
        os.utime(path, (1_700_000_000 + offset, 1_700_000_000 + offset))
    assert exporter.artifactMtime("a.example.test") == 1_700_000_000 + 4


@pytest.mark.parametrize(
    "store",
    [
        acme_v17_single_store("u.example.test"),
        acme_v2_uppercase_fixture("u.example.test"),
    ],
    ids=["v17-single-storeddata", "v2-uppercase-unwrapped"],
)
def test_artifact_mtime_unwrapped_store_default_settings(tmp_path, store):
    # The shipped defaults: resolverinpathname true, flat false.
    exporter, fixture, outputPath = _lookup_env(
        tmp_path, store, resolverInPathName=True, flat=False
    )
    exporter.exportCertificatesForFile(fixture)

    directory = outputPath / "u.example.test"
    files = _files(outputPath)
    assert files and all(p.parent == directory for p in files)
    assert exporter.artifactMtime("u.example.test") == max(
        p.stat().st_mtime for p in files
    )


def test_artifact_mtime_two_resolvers_same_domain_newest_wins(tmp_path):
    exporter, fixture, outputPath = _lookup_env(
        tmp_path,
        {
            "r1": _resolver(acme_v2_certificate("a.example.test", real_chain())),
            "r2": _resolver(acme_v2_certificate("a.example.test", real_chain())),
        },
        resolverInPathName=True,
    )
    exporter.exportCertificatesForFile(fixture)
    for path in _files(outputPath / "r1"):
        os.utime(path, (1_700_000_000, 1_700_000_000))
    for path in _files(outputPath / "r2"):
        os.utime(path, (1_700_000_500, 1_700_000_500))

    assert exporter.artifactMtime("a.example.test") == 1_700_000_500


def test_artifact_mtime_covers_previously_processed_store_files(tmp_path):
    """AR-3: the lookup answers for every store file this process has processed."""
    exporter, first, _ = _lookup_env(
        tmp_path,
        {"le": _resolver(acme_v2_certificate("a.example.test"))},
        name="a.json",
    )
    second = _write_fixture(
        tmp_path / "data",
        {"le": _resolver(acme_v2_certificate("b.example.test"))},
        "b.json",
    )
    exporter.exportCertificates()

    exporter.exportCertificatesForFile(first)  # a drain over file A alone

    assert exporter.artifactMtime("a.example.test") is not None
    assert exporter.artifactMtime("b.example.test") is not None
    assert second.endswith("b.json")


def test_artifact_mtime_ignores_files_not_written_by_exporter(tmp_path):
    exporter, fixture, outputPath = _lookup_env(
        tmp_path, {"le": _resolver(acme_v2_certificate("a.example.test"))}
    )
    planted = outputPath / "other" / "x.example.test" / "cert.pem"
    planted.parent.mkdir(parents=True)
    planted.write_text("not ours")
    exporter.exportCertificatesForFile(fixture)

    assert exporter.artifactMtime("x.example.test") is None


def test_artifact_mtime_is_newest_of_layout_files(tmp_path):
    exporter, fixture, outputPath = _lookup_env(
        tmp_path, {"le": _resolver(acme_v2_certificate("a.example.test"))}
    )
    exporter.exportCertificatesForFile(fixture)
    files = _files(outputPath)
    for offset, path in enumerate(files):
        os.utime(path, (1_700_000_000 + 10 * offset, 1_700_000_000 + 10 * offset))
    assert exporter.artifactMtime("a.example.test") == 1_700_000_000 + 10 * (
        len(files) - 1
    )

    # A partly present set: the newest of what is left.
    files[-1].unlink()
    files[-2].unlink()
    assert exporter.artifactMtime("a.example.test") == 1_700_000_000 + 10 * (
        len(files) - 3
    )


def test_artifact_mtime_missing_domain_is_none(tmp_path):
    exporter, fixture, outputPath = _lookup_env(
        tmp_path, {"le": _resolver(acme_v2_certificate("a.example.test"))}
    )
    assert exporter.artifactMtime("a.example.test") is None  # nothing processed yet
    exporter.exportCertificatesForFile(fixture)

    assert exporter.artifactMtime("unknown.example.test") is None
    for path in _files(outputPath):
        path.unlink()
    assert exporter.artifactMtime("a.example.test") is None


def test_artifact_mtime_oserror_counts_as_missing(tmp_path, monkeypatch, caplog):
    exporter, fixture, outputPath = _lookup_env(
        tmp_path, {"le": _resolver(acme_v2_certificate("a.example.test"))}
    )
    exporter.exportCertificatesForFile(fixture)
    files = _files(outputPath)
    for path in files:
        os.utime(path, (1_700_000_000, 1_700_000_000))
    unreadable = outputPath / "a.example.test" / "cert.pfx"
    os.utime(unreadable, (1_700_009_999, 1_700_009_999))
    realStat = os.stat

    def stat(path, *args, **kwargs):
        if Path(path) == unreadable:
            raise PermissionError(13, "Permission denied", str(path))
        return realStat(path, *args, **kwargs)

    monkeypatch.setattr(certificate_exporter.os, "stat", stat)
    with caplog.at_level(logging.DEBUG, logger=certificate_exporter.globalLogger.name):
        assert exporter.artifactMtime("a.example.test") == 1_700_000_000

    assert any(
        f"Cannot stat {unreadable}" in m and "treated as missing" in m
        for m in _messages(caplog, logging.DEBUG)
    )


def test_artifact_index_rebuild_during_lookup_is_safe(tmp_path, monkeypatch):
    """AG-13: a drain rebuilds the index while a deferred-restart thread iterates it.
    Published by single assignment, so the reader keeps a consistent snapshot."""
    exporter, first, _ = _lookup_env(
        tmp_path,
        {
            "le": _resolver(
                *[acme_v2_certificate(f"d{i}.example.test") for i in range(3)]
            )
        },
        name="a.json",
    )
    second = _write_fixture(
        tmp_path / "data",
        {"le": _resolver(acme_v2_certificate("b.example.test"))},
        "b.json",
    )
    exporter.exportCertificatesForFile(first)
    realStat = os.stat
    rebuilt = []

    def statThenRebuild(path, *args, **kwargs):
        # Mid-iteration: a new store file's entry and a replaced one are published.
        if not rebuilt:
            rebuilt.append(True)
            monkeypatch.setattr(certificate_exporter.os, "stat", realStat)
            exporter.exportCertificatesForFile(second)
            exporter.exportCertificatesForFile(first)
        return realStat(path, *args, **kwargs)

    monkeypatch.setattr(certificate_exporter.os, "stat", statThenRebuild)
    assert exporter.artifactMtime("d2.example.test") is not None  # no RuntimeError
    assert rebuilt
    assert exporter.artifactMtime("b.example.test") is not None


def test_failed_rebuild_keeps_previous_artifact_paths(tmp_path):
    """RV-1: a certificate whose rebuild fails, and a resolver that fails as a whole, keep
    their previous paths, so a crash-lost restart is still recovered on the next pass."""
    exporter, fixture, _ = _lookup_env(
        tmp_path,
        {
            "le": _resolver(
                acme_v2_certificate("a.example.test"),
                acme_v2_certificate("b.example.test"),
            ),
            "other": _resolver(acme_v2_certificate("c.example.test")),
        },
        resolverInPathName=True,
    )
    exporter.exportCertificatesForFile(fixture)
    before = {
        d: exporter.artifactMtime(d)
        for d in ("a.example.test", "b.example.test", "c.example.test")
    }
    assert all(v is not None for v in before.values())

    corrupt = acme_v2_certificate("b.example.test")
    corrupt["key"] = "!!!not-base64"
    _write_fixture(
        tmp_path / "data",
        {
            "le": _resolver(acme_v2_certificate("a.example.test"), corrupt),
            "other": _resolver(acme_v2_certificate("c.example.test")),
        },
    )
    realCandidates = (
        AcmeCertificateExporter._AcmeCertificateExporter__certificateCandidates
    )

    def candidates(self, node, resolverName=None):
        if resolverName == "other":
            raise RuntimeError("broken resolver")
        return realCandidates(self, node, resolverName)

    with patch.object(
        AcmeCertificateExporter,
        "_AcmeCertificateExporter__certificateCandidates",
        candidates,
    ):
        exporter.exportCertificatesForFile(fixture)

    assert {d: exporter.artifactMtime(d) for d in before} == before
