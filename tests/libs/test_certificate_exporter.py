import base64
import datetime
import hashlib
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
    real_rsa4096_chain,
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
        "flat.example.test.pfx.fingerprint.json",
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
# The `.pfx` fingerprint sidecar (ADR-0051): written beside the `.pfx`, never an artifact.
_SIDECAR = "cert.pfx.fingerprint.json"


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
        sorted((*_DEFAULT_ARTIFACTS, _SIDECAR))
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
    assert rewritten == ["cert.pem", "cert.pfx", _SIDECAR, "fullchain.pem"]


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
        assert sorted(n for n in after if after[n] != before[n]) == [
            "cert.pfx",
            _SIDECAR,
        ]
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
        sorted((*_DEFAULT_ARTIFACTS, _SIDECAR))
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
    # Plus the `.pfx` fingerprint sidecar, which is not an artifact (ADR-0051).
    sidecar = certificate_exporter._pfx_fingerprint_path(written[4])
    assert _files(outputPath) == sorted([*written, sidecar])
    os.utime(sidecar, (1_800_000_000, 1_800_000_000))
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
    # The `.pfx` fingerprint sidecar is not an artifact (ADR-0051).
    artifacts = [p for p in files if p.name != _SIDECAR]
    assert len(artifacts) == len(files) - 1 == 5
    assert exporter.artifactMtime("u.example.test") == max(
        p.stat().st_mtime for p in artifacts
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


# ---------------------------------------------------------------------------
# Fast export on RSA-4096 stores (E015-S01-002, ADR-0051): `settings.validatekeys` and
# the `.pfx` fingerprint sidecar. The load counts are the gate; wall time is asserted only
# relative to another pass in the same test (AG-4).
# ---------------------------------------------------------------------------

_RSA_DOMAINS = tuple(f"rsa{i}.example.test" for i in range(5))


def _rsa4096_store() -> dict:
    chain = real_rsa4096_chain()
    return _v2_store(*(acme_v2_certificate(d, chain) for d in _RSA_DOMAINS))


def _spy_loads(monkeypatch) -> dict[str, list]:
    """Record every key load and every PKCS#12 load the exporter makes, and delegate."""
    calls: dict[str, list] = {"key": [], "pkcs12": []}
    realKey = certificate_exporter.serialization.load_pem_private_key
    realPkcs12 = certificate_exporter.pkcs12.load_key_and_certificates

    def key(*args, **kwargs):
        calls["key"].append((args, kwargs))
        return realKey(*args, **kwargs)

    def bundle(*args, **kwargs):
        calls["pkcs12"].append((args, kwargs))
        return realPkcs12(*args, **kwargs)

    monkeypatch.setattr(certificate_exporter.serialization, "load_pem_private_key", key)
    monkeypatch.setattr(
        certificate_exporter.pkcs12, "load_key_and_certificates", bundle
    )
    return calls


def _timed_export(tmp_path, store: dict, **overrides):
    start = time.perf_counter()
    names, outputPath = _export(tmp_path, store, **overrides)
    return names, outputPath, time.perf_counter() - start


def _artifacts_only(snapshot: dict) -> dict:
    return {k: v for k, v in snapshot.items() if k != _SIDECAR}


def _sidecar_of(directory: Path) -> Path:
    return directory / _SIDECAR


@pytest.mark.parametrize("passphrase", [None, "s3cret"], ids=["plain", "passphrase"])
def test_unchanged_rsa4096_pass_loads_no_key_and_no_pfx(
    tmp_path, monkeypatch, passphrase
):
    store = _rsa4096_store()
    names, outputPath, firstPass = _timed_export(
        tmp_path, store, pkcs12Passphrase=passphrase
    )
    assert names == list(_RSA_DOMAINS)
    before = {d: _snapshot(outputPath / d) for d in _RSA_DOMAINS}
    calls = _spy_loads(monkeypatch)

    names, _, unchangedPass = _timed_export(
        tmp_path, store, pkcs12Passphrase=passphrase
    )

    assert names == []
    assert len(calls["key"]) == 0
    assert len(calls["pkcs12"]) == 0
    assert {d: _snapshot(outputPath / d) for d in _RSA_DOMAINS} == before
    assert all(_SIDECAR in before[d] for d in _RSA_DOMAINS)
    assert unchangedPass < firstPass / 4, (unchangedPass, firstPass)


@pytest.mark.parametrize("validateKeys", [True, False], ids=["validate", "skip"])
def test_first_rsa4096_pass_loads_each_key_once(tmp_path, monkeypatch, validateKeys):
    store = _rsa4096_store()
    baseline = None
    if not validateKeys:
        _, _, baseline = _timed_export(tmp_path / "validating", store)
    calls = _spy_loads(monkeypatch)

    names, _, elapsed = _timed_export(
        tmp_path / "measured", store, validateKeys=validateKeys
    )

    assert names == list(_RSA_DOMAINS)
    assert len(calls["key"]) == 5
    assert [kw.get("unsafe_skip_rsa_key_validation") for _a, kw in calls["key"]] == [
        not validateKeys
    ] * 5
    if baseline is not None:
        assert elapsed < baseline / 2, (elapsed, baseline)


def test_passphrase_check_is_cached_on_hashable_values_only():
    chain = real_chain()
    certs = x509.load_pem_x509_certificates(chain.fullchain_pem)
    record = certificate_exporter._pfx_fingerprint(
        b"pfx bytes", chain.key_pem, certs, "s3cret"
    )["passphrase"]
    verifies = certificate_exporter._scrypt_verifies
    verifies.cache_clear()

    assert certificate_exporter._passphrase_matches(b"s3cret", record) is True
    first = verifies.cache_info()
    assert certificate_exporter._passphrase_matches(b"s3cret", record) is True
    second = verifies.cache_info()
    assert (second.hits, second.misses) == (first.hits + 1, first.misses)
    assert certificate_exporter._passphrase_matches(b"other", record) is False

    size = verifies.cache_info().currsize
    shortSalt = base64.b64encode(b"x" * 8).decode("ascii")
    for malformed in (
        {**record, "kdf": "pbkdf2"},
        {**record, "n": "16384"},
        {**record, "n": True},
        {**record, "p": 0},
        {**record, "salt": shortSalt},
        {**record, "digest": "not base64!"},
        {k: v for k, v in record.items() if k != "r"},
        "scrypt",
        None,
    ):
        assert (
            certificate_exporter._passphrase_matches(b"s3cret", malformed) is False
        ), malformed
    assert verifies.cache_info().currsize == size


@pytest.mark.parametrize("validateKeys", [True, False], ids=["validate", "skip"])
def test_mismatched_key_and_certificate_is_refused_in_both_validation_modes(
    tmp_path, caplog, validateKeys
):
    chain = real_chain()
    store = _v2_store(acme_v2_certificate("mismatch.example.test", chain))
    _, outputPath = _export(tmp_path, store, validateKeys=validateKeys)
    directory = outputPath / "mismatch.example.test"
    before = _snapshot(directory)
    foreignKey = real_chain_expiring_in(5).key_pem
    mismatched = _v2_store(
        acme_v2_certificate("mismatch.example.test", chain._replace(key_pem=foreignKey))
    )

    with caplog.at_level(logging.ERROR):
        names, _ = _export(tmp_path, mismatched, validateKeys=validateKeys)

    assert names == []
    assert _snapshot(directory) == before
    errors = _messages(caplog, logging.ERROR)
    assert len(errors) == 1, errors
    assert "mismatch.example.test" in errors[0] and "pkcs12" in errors[0]


def test_passphrase_change_is_detected_from_the_sidecar_alone(tmp_path, monkeypatch):
    store = _v2_store(acme_v2_certificate("phrase.example.test"))
    _, outputPath = _export(tmp_path, store)
    directory = outputPath / "phrase.example.test"
    calls = _spy_loads(monkeypatch)

    for passphrase in ("s3cret", "other", None):
        before = _snapshot(directory)
        calls["pkcs12"].clear()

        names, _ = _export(tmp_path, store, pkcs12Passphrase=passphrase)

        assert calls["pkcs12"] == [], passphrase
        assert names == ["phrase.example.test"], passphrase
        after = _snapshot(directory)
        assert sorted(n for n in after if after[n] != before[n]) == [
            "cert.pfx",
            _SIDECAR,
        ]
        key, _, _ = pkcs12.load_key_and_certificates(
            (directory / "cert.pfx").read_bytes(),
            passphrase.encode() if passphrase else None,
        )
        assert key is not None


@pytest.mark.parametrize("damage", ["truncated", "flipped", "deleted"])
def test_damaged_pfx_is_rebuilt_and_reported(tmp_path, damage):
    """Regression guard: content compare already catches each of these (E015-S01-002)."""
    chain = real_chain()
    store = _v2_store(acme_v2_certificate("damaged.example.test"))
    _, outputPath = _export(tmp_path, store, pkcs12Passphrase="s3cret")
    directory = outputPath / "damaged.example.test"
    before = _snapshot(directory)
    pfxPath = directory / "cert.pfx"
    if damage == "truncated":
        pfxPath.write_bytes(b"")
    elif damage == "flipped":
        data = bytearray(pfxPath.read_bytes())
        data[len(data) // 2] ^= 0x01
        pfxPath.write_bytes(bytes(data))
    else:
        pfxPath.unlink()

    names, _ = _export(tmp_path, store, pkcs12Passphrase="s3cret")

    assert names == ["damaged.example.test"]
    after = _snapshot(directory)
    pems = [n for n in _DEFAULT_ARTIFACTS if n.endswith(".pem")]
    assert {n: after[n] for n in pems} == {n: before[n] for n in pems}
    key, leaf, cas = pkcs12.load_key_and_certificates(pfxPath.read_bytes(), b"s3cret")
    assert key is not None and leaf is not None
    assert _key_der(key) == _key_der(
        serialization.load_pem_private_key(chain.key_pem, None)
    )
    assert [_der(leaf), *(_der(c) for c in cas)] == [
        _der(c) for c in x509.load_pem_x509_certificates(chain.fullchain_pem)
    ]
    assert _export(tmp_path, store, pkcs12Passphrase="s3cret")[0] == []


def test_upgrade_from_0_3_0_output_verifies_once_and_rewrites_nothing(
    tmp_path, monkeypatch
):
    domains = ("up1.example.test", "up2.example.test")
    store = _v2_store(*(acme_v2_certificate(d) for d in domains))
    _, outputPath = _export(tmp_path, store, pkcs12Passphrase="s3cret")
    for sidecar in outputPath.rglob("*.fingerprint.json"):
        sidecar.unlink()  # what 0.3.0 left behind: the five artifacts, no sidecar
    before = {d: _snapshot(outputPath / d) for d in domains}
    calls = _spy_loads(monkeypatch)

    names, _ = _export(tmp_path, store, pkcs12Passphrase="s3cret")

    assert names == []
    for d in domains:
        after = _snapshot(outputPath / d)
        assert _artifacts_only(after) == before[d], d
        assert _SIDECAR in after, d
    assert calls["pkcs12"], "the upgrade pass verifies each .pfx by content"

    calls["pkcs12"].clear()
    calls["key"].clear()
    settled = {d: _snapshot(outputPath / d) for d in domains}
    assert _export(tmp_path, store, pkcs12Passphrase="s3cret")[0] == []
    assert calls["pkcs12"] == []
    assert calls["key"] == []
    assert {d: _snapshot(outputPath / d) for d in domains} == settled


@pytest.mark.parametrize("kind", ["garbage", "unknown-version", "oversize", "symlink"])
def test_unusable_sidecar_falls_back_to_content_verification(
    tmp_path, monkeypatch, kind
):
    store = _v2_store(acme_v2_certificate("unusable.example.test"))
    _, outputPath = _export(tmp_path, store)
    directory = outputPath / "unusable.example.test"
    sidecar = _sidecar_of(directory)
    valid = sidecar.read_bytes()
    elsewhere = tmp_path / "elsewhere.json"
    if kind == "garbage":
        sidecar.write_bytes(b"not json {")
    elif kind == "unknown-version":
        sidecar.write_bytes(
            (json.dumps({**json.loads(valid), "version": 99}) + "\n").encode()
        )
    elif kind == "oversize":
        sidecar.write_bytes(valid + b" " * (64 * 1024))  # still valid JSON
    else:
        elsewhere.write_bytes(valid)
        sidecar.unlink()
        sidecar.symlink_to(elsewhere)
    artifacts = _artifacts_only(_snapshot(directory))
    calls = _spy_loads(monkeypatch)

    names, _ = _export(tmp_path, store)

    assert names == []
    assert _artifacts_only(_snapshot(directory)) == artifacts
    assert len(calls["pkcs12"]) >= 1, "the verify path loads the .pfx"
    info = sidecar.lstat()
    assert stat.S_ISREG(info.st_mode)
    assert info.st_mode & 0o777 == 0o600
    pfxHash = hashlib.sha256((directory / "cert.pfx").read_bytes()).hexdigest()
    assert json.loads(sidecar.read_bytes())["pfx_sha256"] == pfxHash
    if kind == "symlink":
        assert elsewhere.read_bytes() == valid


def test_stale_sidecar_after_a_crash_is_repaired_without_reporting(
    tmp_path, monkeypatch
):
    chain = real_chain()
    _, outputPath = _export(
        tmp_path, _v2_store(acme_v2_certificate("crash.example.test", chain))
    )
    directory = outputPath / "crash.example.test"
    staleSidecar = _sidecar_of(directory).read_bytes()
    renewed = _v2_store(
        acme_v2_certificate("crash.example.test", _one_byte_changed(chain))
    )
    assert _export(tmp_path, renewed)[0] == ["crash.example.test"]
    # The crash: the new `.pfx` was written, its sidecar was not.
    _sidecar_of(directory).write_bytes(staleSidecar)
    os.chmod(_sidecar_of(directory), 0o600)
    artifacts = _artifacts_only(_snapshot(directory))

    assert _export(tmp_path, renewed)[0] == []

    assert _artifacts_only(_snapshot(directory)) == artifacts
    repaired = json.loads(_sidecar_of(directory).read_bytes())
    pfxHash = hashlib.sha256((directory / "cert.pfx").read_bytes()).hexdigest()
    assert repaired["pfx_sha256"] == pfxHash
    calls = _spy_loads(monkeypatch)
    assert _export(tmp_path, renewed)[0] == []
    assert calls["pkcs12"] == []


@pytest.mark.parametrize("resolverInPathName, flat", _LAYOUTS)
def test_sidecar_is_written_0600_beside_the_pfx_in_every_layout(
    tmp_path, resolverInPathName, flat
):
    exporter, fixture, outputPath = _lookup_env(
        tmp_path,
        {"le": _resolver(acme_v2_certificate("a.example.test"))},
        resolverInPathName=resolverInPathName,
        flat=flat,
    )
    exporter.exportCertificatesForFile(fixture)

    paths = certificate_exporter._artifact_paths(
        outputPath,
        "le",
        "a.example.test",
        flat=flat,
        resolverInPathName=resolverInPathName,
    )
    pfxPath = paths[4]
    sidecar = pfxPath.with_name(pfxPath.name + ".fingerprint.json")
    assert certificate_exporter._pfx_fingerprint_path(pfxPath) == sidecar
    assert _files(outputPath) == sorted([*paths, sidecar])
    info = sidecar.lstat()
    assert stat.S_ISREG(info.st_mode)
    assert info.st_mode & 0o777 == 0o600


def test_sidecar_holds_no_secret(tmp_path):
    chain = real_chain()
    passphrase = "correct-horse-battery-staple"
    _, outputPath = _export(
        tmp_path,
        _v2_store(acme_v2_certificate("secret.example.test", chain)),
        pkcs12Passphrase=passphrase,
    )
    directory = outputPath / "secret.example.test"
    raw = _sidecar_of(directory).read_bytes()
    keyDer = _key_der(serialization.load_pem_private_key(chain.key_pem, None))
    keyBody = b"".join(
        line for line in chain.key_pem.splitlines() if not line.startswith(b"-----")
    )

    for secret in (
        passphrase.encode(),
        chain.key_pem,
        keyBody,
        keyBody[:48],
        keyDer,
        keyDer.hex().encode(),
        base64.b64encode(keyDer),
        base64.b64encode(chain.key_pem),
    ):
        assert secret not in raw
    record = json.loads(raw)
    assert raw.endswith(b"\n")
    assert raw == (json.dumps(record, sort_keys=True) + "\n").encode()
    assert record["format"] == "traefik-certificate-exporter/pfx-fingerprint"
    assert record["version"] == 1
    assert record["passphrase"]["kdf"] == "scrypt"
    assert record["key_sha256"] == hashlib.sha256(chain.key_pem).hexdigest()
    assert record["certificates_sha256"] == [
        c.fingerprint(hashes.SHA256()).hex()
        for c in x509.load_pem_x509_certificates(chain.fullchain_pem)
    ]
    assert (
        record["pfx_sha256"]
        == hashlib.sha256((directory / "cert.pfx").read_bytes()).hexdigest()
    )


def test_sidecar_does_not_move_artifact_mtime(tmp_path):
    exporter, fixture, outputPath = _lookup_env(
        tmp_path, {"le": _resolver(acme_v2_certificate("a.example.test"))}
    )
    exporter.exportCertificatesForFile(fixture)
    directory = outputPath / "a.example.test"
    for name in _DEFAULT_ARTIFACTS:
        os.utime(directory / name, (1_700_000_000, 1_700_000_000))
    os.utime(_sidecar_of(directory), (1_800_000_000, 1_800_000_000))

    assert exporter.artifactMtime("a.example.test") == 1_700_000_000

    # Writing only a sidecar never makes a domain "changed".
    _sidecar_of(directory).unlink()
    assert exporter.exportCertificatesForFile(fixture) == []
    assert _sidecar_of(directory).exists()
    assert exporter.artifactMtime("a.example.test") == 1_700_000_000


def test_dry_run_writes_no_sidecar(tmp_path):
    store = _v2_store(acme_v2_certificate("drysc.example.test"))
    _, outputPath = _export(tmp_path, store)
    directory = outputPath / "drysc.example.test"
    _sidecar_of(directory).unlink(missing_ok=True)
    before = _snapshot(directory)

    assert _export(tmp_path, store, dryRun=True)[0] == []
    assert _snapshot(directory) == before

    assert _export(tmp_path, store)[0] == []
    assert _sidecar_of(directory).exists()


def test_pkcs12_debug_details_do_not_reload_the_bundle(tmp_path, monkeypatch, caplog):
    calls = _spy_loads(monkeypatch)

    with caplog.at_level(logging.DEBUG, logger=certificate_exporter.globalLogger.name):
        names, _ = _export(
            tmp_path,
            _v2_store(acme_v2_certificate("debug.example.test")),
            pkcs12Passphrase="s3cret",
        )

    assert names == ["debug.example.test"]
    assert calls["pkcs12"] == []
    debug = _messages(caplog, logging.DEBUG)
    assert any(m.startswith("Created PKCS12 file:") for m in debug), debug
    assert any("Subject:" in m and "leaf.example.test" in m for m in debug)
    assert "  Intermediates: 1" in debug


# ---------------------------------------------------------------------------
# Sprint closure 2026-10-12, RT-1: the in-place policy tighten must not follow a symlink
# swapped in between the check and the chmod. The window is injected deterministically:
# `os.lstat` is wrapped so the planted regular file becomes a symlink to a victim right
# after it is examined. Every caller that tightens in place is driven.
# ---------------------------------------------------------------------------
def _tighten_callers():
    chain = real_chain()
    certs = x509.load_pem_x509_certificates(chain.fullchain_pem)
    return {
        "file_differs": lambda p: certificate_exporter._file_differs(
            p, b"data", mode=0o600
        ),
        "pfx_differs": lambda p: certificate_exporter._pfx_differs(
            p, serialization.load_pem_private_key(chain.key_pem, None), certs, None
        ),
        "read_pfx_fingerprint": lambda p: certificate_exporter._read_pfx_fingerprint(
            p, False
        ),
        "pfx_state": lambda p: certificate_exporter._pfx_state(
            p, chain.key_pem, certs, None, False
        ),
    }


@pytest.mark.parametrize(
    "caller", ["file_differs", "pfx_differs", "read_pfx_fingerprint", "pfx_state"]
)
def test_policy_tighten_does_not_follow_a_symlink_swapped_in_after_lstat(
    tmp_path, monkeypatch, caller
):
    call = _tighten_callers()[caller]
    victim = tmp_path / "victim"
    victim.write_bytes(b"root-only")
    victim.chmod(0o640)
    planted = tmp_path / "cert.pfx.fingerprint.json"
    planted.write_bytes(b"{}")
    planted.chmod(0o004)  # wider than 0600 in a bit the policy removes
    realLstat = os.lstat
    swapped: list[bool] = []

    def swappingLstat(path, *args, **kwargs):
        info = realLstat(path, *args, **kwargs)
        if not swapped and os.fspath(path) == os.fspath(planted):
            swapped.append(True)
            os.unlink(planted)
            os.symlink(victim, planted)
        return info

    monkeypatch.setattr(certificate_exporter.os, "lstat", swappingLstat)

    call(planted)

    assert swapped, "the swap window was never reached"
    assert stat.S_IMODE(realLstat(victim).st_mode) == 0o640
    assert victim.read_bytes() == b"root-only"


# ---------------------------------------------------------------------------
# BL-E015-068: a filesystem with a fixed mode (CIFS `file_mode=0755`, nounix) accepts
# `fchmod` and changes nothing. The pass must not claim a tighten per file on every pass;
# it reports the files once, and rewrites nothing.
# ---------------------------------------------------------------------------
def _loosen(directory: Path, mode: int = 0o644) -> None:
    for name in ("privkey.pem", "cert.pfx"):
        (directory / name).chmod(mode)


def _summaries(caplog) -> list[str]:
    return [
        m for m in _messages(caplog, logging.WARNING) if "exported file(s) from" in m
    ]


def test_a_filesystem_that_ignores_chmod_gets_one_summary_per_pass(
    tmp_path, monkeypatch, caplog
):
    store = _v2_store(acme_v2_certificate("cifs.example.test"))
    _, outputPath = _export(tmp_path, store)
    directory = outputPath / "cifs.example.test"
    _loosen(directory)
    before = _snapshot(directory)
    monkeypatch.setattr(certificate_exporter.os, "fchmod", lambda fd, mode: None)

    for _ in range(2):
        caplog.clear()
        with caplog.at_level(logging.WARNING):
            names, _ = _export(tmp_path, store)

        assert names == []
        assert not [
            m for m in _messages(caplog, logging.WARNING) if "Tightened mode" in m
        ]
        summaries = _summaries(caplog)
        assert len(summaries) == 1, summaries
        assert summaries[0].startswith("2 exported file(s)"), summaries[0]
        example = summaries[0].split("for example '", 1)[1].split("'", 1)[0]
        assert example.endswith(("/privkey.pem", "/cert.pfx")), example
        assert "kept a wider mode" in summaries[0]
        assert _snapshot(directory) == before
        assert stat.S_IMODE((directory / "privkey.pem").stat().st_mode) == 0o644


def test_a_pfx_checked_twice_on_the_verify_path_is_counted_once(
    tmp_path, monkeypatch, caplog
):
    store = _v2_store(acme_v2_certificate("verify.example.test"))
    _, outputPath = _export(tmp_path, store)
    directory = outputPath / "verify.example.test"
    _loosen(directory)
    (directory / "cert.pfx.fingerprint.json").unlink()
    monkeypatch.setattr(certificate_exporter.os, "fchmod", lambda fd, mode: None)

    with caplog.at_level(logging.WARNING):
        names, _ = _export(tmp_path, store)

    assert names == []
    summaries = _summaries(caplog)
    assert len(summaries) == 1, summaries
    assert summaries[0].startswith("2 exported file(s)"), summaries[0]


def test_a_filesystem_that_keeps_modes_is_tightened_without_a_summary(tmp_path, caplog):
    store = _v2_store(acme_v2_certificate("local.example.test"))
    _, outputPath = _export(tmp_path, store)
    directory = outputPath / "local.example.test"
    _loosen(directory)

    with caplog.at_level(logging.WARNING):
        names, _ = _export(tmp_path, store)

    assert names == []
    tightened = [m for m in _messages(caplog, logging.WARNING) if "Tightened mode" in m]
    assert any("privkey.pem" in m for m in tightened), tightened
    assert _summaries(caplog) == []
    assert stat.S_IMODE((directory / "privkey.pem").stat().st_mode) == 0o600
    assert stat.S_IMODE((directory / "cert.pfx").stat().st_mode) == 0o600


# ---------------------------------------------------------------------------
# Sprint closure 2026-10-12, AR-4: the sidecar records the PKCS12 build recipe, so a
# change to `_serialize_pkcs12` reaches every existing `.pfx` once.
# ---------------------------------------------------------------------------
# Pin of `_serialize_pkcs12`'s source per recipe value. A change to that function fails
# this test until it is either recorded as a new recipe (bump `_PFX_BUILD_RECIPE`, add its
# pin) or the pin is updated for a change that does not alter the bundle built.
_PFX_BUILD_RECIPE_SOURCE_SHA256 = {
    1: "58b571a3accb9eafd4761d762f7f7b4ab065cb8d36c5d60e01db50180c1cb56e",
}


def test_pfx_build_recipe_is_pinned_to_the_serializer_source():
    import inspect

    source = inspect.getsource(certificate_exporter._serialize_pkcs12)
    assert (
        hashlib.sha256(source.encode()).hexdigest()
        == _PFX_BUILD_RECIPE_SOURCE_SHA256[certificate_exporter._PFX_BUILD_RECIPE]
    ), "_serialize_pkcs12 changed: bump _PFX_BUILD_RECIPE or re-pin (ADR-0051)"


@pytest.mark.parametrize("kind", ["absent", "older"])
def test_sidecar_with_another_build_recipe_rebuilds_the_pfx_once(
    tmp_path, monkeypatch, kind
):
    domain = "recipe.example.test"
    store = _v2_store(acme_v2_certificate(domain))
    _, outputPath = _export(tmp_path, store)
    sidecar = _sidecar_of(outputPath / domain)
    record = json.loads(sidecar.read_bytes())
    assert record["builder"] == certificate_exporter._PFX_BUILD_RECIPE
    if kind == "absent":
        del record["builder"]
    else:
        record["builder"] = certificate_exporter._PFX_BUILD_RECIPE - 1
    sidecar.write_bytes((json.dumps(record, sort_keys=True) + "\n").encode())
    pfxBefore = (outputPath / domain / "cert.pfx").stat().st_ino

    names, _ = _export(tmp_path, store)

    assert names == [domain]
    assert (outputPath / domain / "cert.pfx").stat().st_ino != pfxBefore
    rewritten = json.loads(sidecar.read_bytes())
    assert rewritten["builder"] == certificate_exporter._PFX_BUILD_RECIPE
    names, _ = _export(tmp_path, store)
    assert names == []
