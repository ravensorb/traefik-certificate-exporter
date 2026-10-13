import datetime
import functools
import glob
import hashlib
import json
import logging
import os
import re
import stat
import tempfile
import threading
import time
from base64 import b64decode, b64encode
from collections.abc import Iterator
from pathlib import Path
from typing import Literal, NamedTuple

import watchdog.events
import watchdog.observers
from cryptography import x509
from cryptography.exceptions import InvalidKey
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.types import PrivateKeyTypes
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
from cryptography.hazmat.primitives.serialization import pkcs12
from watchdog.utils.patterns import match_any_paths

from .docker import DockerManager
from .logging_utils import (
    get_correlation_id,
    globalLogger,
    new_correlation_id,
    reset_correlation_id,
    sanitize_for_log,
    set_correlation_id,
)
from .notify import send_export_notifications
from .post_export import run_post_export_command
from .settings import Settings

###########################################################################################################


# What `open(path, "w")` would have produced: 0o666 masked by the process umask. The
# helper below creates its temp file through `tempfile`, which deliberately uses 0o600,
# so the mode has to be restored explicitly or every exported certificate would silently
# change permissions (ADR-0023's security consideration cuts both ways -- a private key
# must not be loosened, and a public chain must not be tightened into something the
# consuming service cannot read).
#
# Probed exactly ONCE, at module import, while the process is still single-threaded.
# `os.umask` is process-wide and has no read-only form, so the set/restore pair is a
# momentary mutation of global process state; doing it lazily meant doing it after the
# watchdog observer and the debounce timer threads existed, where a concurrent
# file-creating thread could observe the 0o022 window and create a file with the wrong
# mode. A umask changed at RUNTIME is therefore deliberately not picked up: a stable,
# race-free export mode is worth more than honouring a mutation nothing in this process
# performs.
def _probe_default_file_mode() -> int:
    current = os.umask(0o022)
    os.umask(current)
    return 0o666 & ~current


_DEFAULT_FILE_MODE: int = _probe_default_file_mode()

# Key-bearing artifacts are not umask policy. A private key, and a `.pfx` that embeds one
# (unencrypted whenever `pkcs12passphrase` is unset, which is the documented default),
# must never be world- or group-readable regardless of how permissive the process umask
# is. Mode is split by CONTENT, not by umask.
_SECRET_FILE_MODE = 0o600

# A staged `.tmp` holds complete key material. SIGKILL between create and `os.replace`
# leaves it behind, so each export pass reaps the ones that are plainly abandoned.
_STALE_TEMP_AGE_SECONDS = 3600

_SYMLINK_WARNED: set[str] = set()
_SYMLINK_WARNED_LOCK = threading.Lock()


def _default_file_mode() -> int:
    return _DEFAULT_FILE_MODE


def _sweep_stale_temp_files(directory: Path) -> None:
    """Remove abandoned `.{name}.{random}.tmp` staging files older than an hour.

    They carry a full private key at 0600 and nothing else ever collects them: the
    `finally` in `_atomic_write` only runs when the process survives the write.
    Best-effort by design -- a sweep that raised would fail an export over litter.
    """
    cutoff = time.time() - _STALE_TEMP_AGE_SECONDS

    try:
        entries = list(directory.glob(".*.tmp"))
    except OSError:
        return

    for entry in entries:
        try:
            info = entry.lstat()
            if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
                continue
            if info.st_mtime >= cutoff:
                continue
            entry.unlink()
        except OSError:
            continue
        globalLogger.debug(f"Removed stale export staging file: {entry}")


def _inheritable_metadata(target: Path, policyMode: int):
    """The existing file's metadata, but only when it is safe to carry forward.

    Three refusals, each a real exposure in the shipped container (which runs as root, so
    the `os.chown` below SUCCEEDS rather than failing harmlessly):

    * a symlink at the target -- `stat()` follows it, so the metadata probed belongs to
      somewhere else entirely while `os.replace` replaces the link itself;
    * a file owned by another UID -- inheriting it hands a freshly written private key to
      whoever planted the placeholder;
    * a mode more permissive than the policy floor for this artifact -- a 0o666 placeholder
      would otherwise dictate the mode of the key that replaces it.

    An operator's own TIGHTER choice (0640 root:traefik on a key under a 0644 policy) is
    still honoured, which is the whole reason this inheritance exists.
    """
    try:
        existing = os.lstat(target)
    except OSError:
        return None

    if stat.S_ISLNK(existing.st_mode):
        key = str(target)
        with _SYMLINK_WARNED_LOCK:
            firstTime = key not in _SYMLINK_WARNED
            _SYMLINK_WARNED.add(key)
        if firstTime:
            globalLogger.warning(
                f"Export target '{target}' is a symlink; replacing the link itself and "
                "refusing to inherit metadata through it"
            )
        return None

    if existing.st_uid != os.geteuid():
        globalLogger.warning(
            f"refusing to inherit ownership (uid {existing.st_uid}) from an existing "
            f"export at {target}"
        )
        return None

    existingMode = existing.st_mode & 0o7777
    if existingMode & ~policyMode:
        globalLogger.warning(
            f"refusing to inherit permissive mode {oct(existingMode)} from an existing "
            f"export at {target}"
        )
        return None

    return existing


def _atomic_write(target: Path, data: str | bytes, mode: int | None = None) -> None:
    """Write `data` to `target` so a reader never observes a partial file.

    `tempfile.NamedTemporaryFile(dir=target.parent)` keeps the temp file on the SAME
    filesystem as the target -- `os.replace` is only atomic within one, and `outputPath`
    is commonly a bind mount -- then `os.replace` swaps it in one step. A kill at any
    point leaves either the previous file or the complete new one (ADR-0023 Decision 3,
    extended to the PKCS12 outputs by ADR-0024).

    `mode` is the policy floor for this artifact: omitted for public material (umask
    derived), `_SECRET_FILE_MODE` for anything that carries a private key.

    **A symlink at `target` is replaced, not written through** (BL-E011-009). `os.replace`
    swaps the link itself for the new regular file, where a plain `open(target, "w")` would
    have followed it and written wherever it pointed. That difference is the control, not a
    regression: the container has historically run as root, so a link planted at an export
    path by anyone who can write the output directory would otherwise be a write primitive
    aimed anywhere on the filesystem -- and a `lstat`-then-`open` guard could not close it,
    because the link can be swapped in between the two. Replacing the link needs no such
    check to be TOCTOU-safe. `_inheritable_metadata` makes the matching refusal on the
    metadata side and warns once per path. Do not "fix" either into following the link.
    """
    target = Path(target)
    directory = target.parent
    binary = isinstance(data, bytes)

    policyMode = _default_file_mode() if mode is None else mode

    existing = _inheritable_metadata(target, policyMode)
    fileMode = existing.st_mode & 0o7777 if existing else policyMode

    tmp = tempfile.NamedTemporaryFile(  # noqa: SIM115 - closed in the try/finally below
        mode="wb" if binary else "w",
        encoding=None if binary else "utf-8",
        dir=directory,
        prefix=f".{target.name}.",
        suffix=".tmp",
        delete=False,
    )
    tmpPath = tmp.name

    try:
        # `tempfile` creates at 0600 and the final mode is applied immediately before
        # `os.replace` below -- never earlier. A staging file that carried a private key
        # at the public 0644 policy mode for the duration of the write would be readable
        # by anything that globbed the directory, and would stay that way if the process
        # were killed mid-write.
        with tmp as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())

        if existing is not None:
            # `Path.open("w")` re-opened the EXISTING inode, so owner and group survived a
            # re-export untouched. Replacing the inode does not, and the container profile
            # this ships in (LinuxServer PUID/PGID, bind-mounted /certs) is exactly where
            # that matters: a key an operator chowned to `root:traefik` 0640 would keep
            # its mode and lose its group, so the consuming service loses access at the
            # next renewal. Only reached when the existing file is already ours and no
            # more permissive than policy -- see `_inheritable_metadata`.
            try:
                os.chown(tmpPath, existing.st_uid, existing.st_gid)
            except OSError:
                # `PermissionError` is an `OSError`; naming both was redundant.
                pass

        os.chmod(tmpPath, fileMode)
        os.replace(tmpPath, target)
        _fsync_directory(directory)
    except BaseException:
        # Includes KeyboardInterrupt/SystemExit: an abandoned `.tmp` beside a
        # certificate would be collected by any glob a consumer runs over the directory.
        try:
            os.unlink(tmpPath)
        except OSError:
            pass
        raise


def _fsync_directory(directory: Path) -> None:
    """Make the rename itself durable, not just the bytes it renamed.

    `os.fsync` on the file commits its CONTENT; the directory entry that `os.replace`
    created lives in the parent and survives a power loss only once the parent is synced
    too. Without it the atomicity guarantee holds against a process crash but not against
    a host crash -- the window ADR-0023 Decision 3 exists to close.

    Best-effort: some filesystems (and every Windows build) reject `O_DIRECTORY` or
    `fsync` on a directory handle, and an export must not fail over a durability upgrade.
    """
    try:
        fd = os.open(directory, getattr(os, "O_DIRECTORY", os.O_RDONLY))
    except OSError as e:
        globalLogger.debug(f"Could not open '{directory}' to fsync the rename: {e}")
        return

    try:
        os.fsync(fd)
    except OSError as e:
        globalLogger.debug(f"Could not fsync '{directory}' after the rename: {e}")
    finally:
        os.close(fd)


def _atomic_write_text(target: Path, text: str, mode: int | None = None) -> None:
    _atomic_write(target, text, mode=mode)


def _atomic_write_bytes(target: Path, data: bytes, mode: int | None = None) -> None:
    _atomic_write(target, data, mode=mode)


###########################################################################################################
# Build, then compare, then write (ADR-0043, amended by ADR-0051). A domain's artifact set
# is built in memory before the first write, so a domain that cannot be exported keeps
# every file it had. The PEMs are compared with the files on disk byte for byte. The `.pfx`
# cannot be (PKCS12 encryption draws a fresh salt and IV per build), so it is checked
# against its fingerprint sidecar, `<pfx>.fingerprint.json`: hashes of the `.pfx` file, the
# key PEM and the certificates, and a salted scrypt hash of the passphrase. The sidecar is
# never authoritative alone -- "current" requires its recorded `.pfx` hash to equal the file
# on disk -- and a missing, unusable or mismatched sidecar falls back to the content compare
# (`_pfx_differs`). The private key is loaded only when the `.pfx` must be rebuilt or
# verified. Only changed artifacts are replaced: an unchanged artifact keeps its inode and
# mtime, which the restart rule (newest artifact mtime vs the container's StartedAt)
# depends on. The sidecar is not an artifact and never moves that mtime. The files on disk
# are the only state, so the answer survives an exporter restart.


def _parse_fullchain(fullchain_pem: bytes) -> list[x509.Certificate]:
    """Every certificate in the store's full chain, leaf first, in store order.

    The library parser, not string slicing: `find(BEGIN, 1)` returned -1 for a
    one-certificate chain and cut the leaf's final newline off.
    """
    certs = x509.load_pem_x509_certificates(fullchain_pem)
    if not certs:
        raise ValueError("the full chain holds no certificate")
    return certs


def _normalize_passphrase(passphrase: str | bytes | None) -> bytes | None:
    """`None`, `""` and `b""` all mean "no passphrase" -- an unencrypted PFX.

    `BestAvailableEncryption(b"")` raises, and an empty passphrase must never produce a
    file that merely looks encrypted.
    """
    if isinstance(passphrase, str):
        passphrase = passphrase.encode("utf-8")
    return passphrase or None


def _breaks_write_policy(path: Path, policyMode: int, dryRun: bool = False) -> bool:
    """Would the write path refuse to keep this file as it is?

    Skipping an unchanged file must not freeze a state the rewrite used to correct: a
    symlink (or any non-regular file) at the export path counts as changed, and
    `_atomic_write` then replaces it under its usual refusals. A regular file whose mode is
    more permissive than the artifact's floor (a 0644 key stays world-readable for as long
    as it is not rewritten) is a policy repair, not a content change (ADV-2): the mode is
    tightened in place with `os.chmod`, which leaves the mtime alone, a WARNING is logged,
    and the file does not count as changed -- so a hook that loosens a key does not cause a
    rewrite, hook run, notification and restart on every pass. A dry run only logs. A
    failed `chmod` falls back to the rewrite. Raises `OSError` when the path cannot be
    examined.

    The tighten goes through one descriptor (RT-1, closure 2026-10-12): the name is opened
    `O_NOFOLLOW`, the descriptor is `fstat`ed and must still be a regular file, and the
    mode is set with `fchmod`. A symlink swapped in after the `lstat` gives `ELOOP` and
    counts as changed; `chmod` by name would have followed it to another file.
    """
    info = os.lstat(path)
    if not stat.S_ISREG(info.st_mode):
        return True
    current = info.st_mode & 0o7777
    if not current & ~policyMode:
        return False
    logPath = sanitize_for_log(str(path))
    if dryRun:
        globalLogger.warning(
            f"[DRYRUN] would tighten mode of {logPath} from {current:04o} to "
            f"{current & policyMode:04o}"
        )
        return False
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    except OSError:
        # ELOOP (a symlink swapped in), a non-openable type, or a mode the owner
        # cannot read: rewrite it, as a failed `chmod` did.
        return True
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            return True
        current = info.st_mode & 0o7777
        tightened = current & policyMode
        if current != tightened:
            os.fchmod(fd, tightened)
    except OSError:
        return True
    finally:
        os.close(fd)
    globalLogger.warning(
        f"Tightened mode of {logPath} from {current:04o} to {tightened:04o}: wider than "
        "the export policy allows; not counted as a certificate change"
    )
    return False


def _file_differs(
    path: Path, data: bytes, mode: int | None = None, dryRun: bool = False
) -> bool:
    """Does writing `data` to `path` change anything? Absent or unreadable counts as yes."""
    try:
        if _breaks_write_policy(
            path, _default_file_mode() if mode is None else mode, dryRun
        ):
            return True
        return path.read_bytes() != data
    except OSError:
        return True


def _der(cert: x509.Certificate) -> bytes:
    return cert.public_bytes(serialization.Encoding.DER)


def _pkcs8_der(key: PrivateKeyTypes) -> bytes:
    return key.private_bytes(
        serialization.Encoding.DER,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )


def _loads_without_passphrase(pkcs12_bytes: bytes) -> bool:
    """Is this PFX unencrypted? Only an unencrypted bundle loads with `password=None`."""
    try:
        pkcs12.load_key_and_certificates(pkcs12_bytes, None)
    except Exception:  # noqa: BLE001 - any failure: it is encrypted (or unreadable)
        return False
    return True


def _pfx_differs(
    path: Path,
    key: PrivateKeyTypes,
    certs: list[x509.Certificate],
    passphrase: str | bytes | None,
    dryRun: bool = False,
) -> bool:
    """Does the PFX on disk differ in CONTENT from what would be built now?

    Not a byte comparison: PKCS12 encryption draws a fresh salt and IV on every build, so
    two builds of the same input never match. Compared instead: the encryption state
    (loads with the configured passphrase, and loads without one exactly when none is
    configured), the private key, the leaf, and the ordered intermediates. The encryption
    algorithm and iteration count are deliberately not compared. Never raises: any
    failure to examine or load the existing file counts as different.
    """
    try:
        if _breaks_write_policy(path, _SECRET_FILE_MODE, dryRun):
            return True
        existing = path.read_bytes()
        password = _normalize_passphrase(passphrase)
        existingKey, existingLeaf, existingCas = pkcs12.load_key_and_certificates(
            existing, password
        )
        if password is not None and _loads_without_passphrase(existing):
            return True
        if existingKey is None or existingLeaf is None:
            return True
        return _pkcs8_der(existingKey) != _pkcs8_der(key) or [
            _der(c) for c in (existingLeaf, *existingCas)
        ] != [_der(c) for c in certs]
    except Exception:  # noqa: BLE001 - any load failure means "rewrite it"
        return True


def _log_pkcs12_details(filename, certs: list[x509.Certificate]) -> None:
    """DEBUG introspection of a written PFX: subject, issuer and dates -- never key
    material or the passphrase. Taken from the in-memory certificates the bundle was
    built from, so the written file is not loaded again. Best-effort: a certificate
    without a CN must not turn a successful write into a reported failure."""
    if not globalLogger.isEnabledFor(logging.DEBUG):
        return
    try:
        cert = certs[0]
        globalLogger.debug(f"Created PKCS12 file: {filename}")
        globalLogger.debug(f"  Subject: {cert.subject.rfc4514_string()}")
        globalLogger.debug(f"  Issuer: {cert.issuer.rfc4514_string()}")
        globalLogger.debug(f"  Not Before: {cert.not_valid_before_utc.date()}")
        globalLogger.debug(f"  Not After: {cert.not_valid_after_utc.date()}")
        globalLogger.debug(f"  Intermediates: {len(certs) - 1}")
    except Exception as e:  # noqa: BLE001 - diagnostics only
        globalLogger.debug(f"Could not introspect PKCS12 file '{filename}': {e}")


def _load_private_key(keyPem: bytes, validate: bool) -> PrivateKeyTypes:
    """The only private-key loader in the export path (ADR-0051).

    `validate=False` (`settings.validatekeys: false`) skips cryptography's RSA key
    validation, ~0.5 s per RSA-4096 key; it is safe only for keys from a trusted source --
    the operator's own Traefik. The key/certificate match is not part of that validation:
    `pkcs12.serialize_key_and_certificates` checks it in both modes.
    """
    return serialization.load_pem_private_key(
        keyPem, password=None, unsafe_skip_rsa_key_validation=not validate
    )


def _serialize_pkcs12(
    key: PrivateKeyTypes,
    certs: list[x509.Certificate],
    passphrase: str | bytes | None,
) -> bytes:
    """The PKCS12 bundle for a loaded key and its chain (leaf first). Pure: no I/O.

    The intermediates are included, in order. A non-empty passphrase selects
    `BestAvailableEncryption` (AES-256/SHA-256); `None` or empty means an unencrypted
    bundle. Raises `ValueError` when the key does not match the leaf.
    """
    leaf = certs[0]

    # get the common name from the certificate
    try:
        cert_subject_common_name: str | None = str(
            leaf.subject.get_attributes_for_oid(x509.oid.NameOID.COMMON_NAME)[0].value
        )
    except Exception:  # noqa: BLE001 - fall back to an unnamed certificate
        # DEBUG, not ERROR: a CN-less leaf (Let's Encrypt's shortlived/tlsserver
        # profiles) is valid.
        globalLogger.debug(
            f"Certificate has no subject common name ('{leaf.subject!s}'); using "
            "the default PKCS12 friendly name"
        )

        cert_subject_common_name = None

    # format the common name if it is a wildcard
    if cert_subject_common_name is not None:
        if "*." in cert_subject_common_name:
            cert_subject_common_name = "{} (wildcard)".format(
                cert_subject_common_name.split("*.")[1]
            )
    else:
        cert_subject_common_name = "LetsEncrypt Certificate"

    password = _normalize_passphrase(passphrase)
    pkcs12_encryption = (
        serialization.BestAvailableEncryption(password)
        if password is not None
        else serialization.NoEncryption()
    )
    return pkcs12.serialize_key_and_certificates(
        cert_subject_common_name.encode("utf-8"),
        key,  # type: ignore[arg-type]
        leaf,
        certs[1:] or None,
        pkcs12_encryption,
    )


###########################################################################################################
# The `.pfx` fingerprint sidecar (ADR-0051). One JSON object per `.pfx`, written 0600 after
# the `.pfx`. It holds no secret: SHA-256 hashes of the `.pfx` file, of the store's key PEM
# and of each certificate, and the passphrase only as a salted scrypt hash.
_PFX_FINGERPRINT_FORMAT = "traefik-certificate-exporter/pfx-fingerprint"
_PFX_FINGERPRINT_VERSION = 1
# How the `.pfx` is built (AR-4, closure 2026-10-12): bump it whenever `_serialize_pkcs12`
# changes the bundle it produces -- friendly name, encryption, intermediates. A sidecar
# that records another value, or none, rebuilds the `.pfx` once. A test pins this value to
# a hash of `_serialize_pkcs12`'s source.
_PFX_BUILD_RECIPE = 1
_PFX_FINGERPRINT_MAX_BYTES = 64 * 1024
_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_LENGTH = 32
_SCRYPT_SALT_BYTES = 16
# A record is read back from disk, so its cost parameters are bounded: a planted sidecar
# must not make the check allocate unbounded memory (scrypt needs 128 * n * r bytes).
_SCRYPT_MAX_MEMORY = 64 * 1024 * 1024
_SCRYPT_MAX_P = 16


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _certificate_fingerprints(certs: list[x509.Certificate]) -> list[str]:
    return [c.fingerprint(hashes.SHA256()).hex() for c in certs]


def _scrypt_params(record: object) -> tuple[int, int, int, bytes, bytes] | None:
    """`(n, r, p, salt, digest)` of a passphrase record, or `None` when it is unknown or
    malformed. No derive happens here."""
    if not isinstance(record, dict) or record.get("kdf") != "scrypt":
        return None
    n, r, p = record.get("n"), record.get("r"), record.get("p")
    # `type(...) is int`, not `isinstance`: `True` is an `int` too.
    if type(n) is not int or type(r) is not int or type(p) is not int:
        return None
    if n <= 0 or r <= 0 or p <= 0 or 128 * n * r > _SCRYPT_MAX_MEMORY:
        return None
    if p > _SCRYPT_MAX_P:
        return None
    salt, digest = record.get("salt"), record.get("digest")
    if not isinstance(salt, str) or not isinstance(digest, str):
        return None
    try:
        saltBytes = b64decode(salt, validate=True)
        digestBytes = b64decode(digest, validate=True)
    except ValueError:
        return None
    if len(saltBytes) != _SCRYPT_SALT_BYTES or len(digestBytes) != _SCRYPT_LENGTH:
        return None
    return n, r, p, saltBytes, digestBytes


@functools.lru_cache(maxsize=4096)
def _scrypt_verifies(
    passphrase: bytes, salt: bytes, n: int, r: int, p: int, digest: bytes
) -> bool:
    """Does `passphrase` derive `digest`? Constant-time (`Scrypt.verify`). Cached on
    hashable primitives only, so each sidecar costs one derive per process (AG-3)."""
    try:
        Scrypt(salt=salt, length=len(digest), n=n, r=r, p=p).verify(passphrase, digest)
    except (InvalidKey, ValueError, MemoryError):
        return False
    return True


def _passphrase_matches(passphrase: bytes, record: dict) -> bool:
    """Does the configured passphrase match a sidecar's passphrase record? Not cached:
    the record is a `dict`, which `lru_cache` cannot hash; the derive is cached below."""
    params = _scrypt_params(record)
    if params is None:
        return False
    n, r, p, salt, digest = params
    return _scrypt_verifies(passphrase, salt, n, r, p, digest)


def _pfx_fingerprint(
    pfxBytes: bytes,
    keyPem: bytes,
    certs: list[x509.Certificate],
    passphrase: str | bytes | None,
) -> dict:
    """The sidecar object for a `.pfx` (a new salt when a passphrase is set)."""
    password = _normalize_passphrase(passphrase)
    passphraseRecord: dict | None = None
    if password is not None:
        salt = os.urandom(_SCRYPT_SALT_BYTES)
        digest = Scrypt(
            salt=salt, length=_SCRYPT_LENGTH, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P
        ).derive(password)
        passphraseRecord = {
            "kdf": "scrypt",
            "n": _SCRYPT_N,
            "r": _SCRYPT_R,
            "p": _SCRYPT_P,
            "salt": b64encode(salt).decode("ascii"),
            "digest": b64encode(digest).decode("ascii"),
        }
    return {
        "builder": _PFX_BUILD_RECIPE,
        "certificates_sha256": _certificate_fingerprints(certs),
        "format": _PFX_FINGERPRINT_FORMAT,
        "key_sha256": _sha256_hex(keyPem),
        "passphrase": passphraseRecord,
        "pfx_sha256": _sha256_hex(pfxBytes),
        "version": _PFX_FINGERPRINT_VERSION,
    }


def _read_pfx_fingerprint(path: Path, dryRun: bool) -> dict | None:
    """The sidecar at `path`, or `None` when it is unusable: absent, not a regular file
    (a symlink included), still wider than 0600 after the in-place tighten, larger than
    64 KiB, not UTF-8 JSON, or of an unknown format/version or field type. Never raises.
    """
    try:
        if _breaks_write_policy(path, _SECRET_FILE_MODE, dryRun):
            return None
        if path.lstat().st_size > _PFX_FINGERPRINT_MAX_BYTES:
            return None
        raw = path.read_bytes()
        if len(raw) > _PFX_FINGERPRINT_MAX_BYTES:
            return None
        record = json.loads(raw.decode("utf-8"))
    except (OSError, ValueError, RecursionError):
        return None
    if not isinstance(record, dict):
        return None
    certificates = record.get("certificates_sha256")
    passphrase = record.get("passphrase")
    if (
        record.get("format") != _PFX_FINGERPRINT_FORMAT
        or type(record.get("version")) is not int
        or record.get("version") != _PFX_FINGERPRINT_VERSION
        or not isinstance(record.get("key_sha256"), str)
        or not isinstance(record.get("pfx_sha256"), str)
        or not isinstance(certificates, list)
        or not all(isinstance(c, str) for c in certificates)
        or (passphrase is not None and _scrypt_params(passphrase) is None)
    ):
        return None
    return record


def _pfx_state(
    pfxPath: Path,
    keyPem: bytes,
    certs: list[x509.Certificate],
    passphrase: str | bytes | None,
    dryRun: bool,
) -> Literal["current", "rebuild", "verify"]:
    """Is the `.pfx` on disk current for these inputs (ADR-0051)?

    `current`: it passes the write policy, its sidecar is usable, the sidecar's `.pfx` hash
    equals the file's, and the key, the certificates and the passphrase state all match.
    `rebuild`: the `.pfx` is absent or not a regular file, or the sidecar is usable and an
    input or the build recipe differs. `verify`: the sidecar is missing or unusable, its
    `.pfx` hash does not match the file, or the file cannot be examined -- the content
    compare decides. Never raises.
    """
    try:
        try:
            if _breaks_write_policy(pfxPath, _SECRET_FILE_MODE, dryRun):
                return "rebuild"
        except FileNotFoundError:
            return "rebuild"
        except OSError:
            return "verify"

        record = _read_pfx_fingerprint(_pfx_fingerprint_path(pfxPath), dryRun)
        if record is None:
            return "verify"
        # Built by another recipe (or recorded before the recipe was): rebuild once.
        # `type(...) is int`: `True` must not pass as recipe 1.
        builder = record.get("builder")
        if type(builder) is not int or builder != _PFX_BUILD_RECIPE:
            return "rebuild"
        try:
            pfxHash = _sha256_hex(pfxPath.read_bytes())
        except OSError:
            return "verify"
        if record["pfx_sha256"] != pfxHash:
            return "verify"

        if record["key_sha256"] != _sha256_hex(keyPem):
            return "rebuild"
        if record["certificates_sha256"] != _certificate_fingerprints(certs):
            return "rebuild"

        password = _normalize_passphrase(passphrase)
        stored = record["passphrase"]
        if password is None or stored is None:
            return "current" if password is None and stored is None else "rebuild"
        return "current" if _passphrase_matches(password, stored) else "rebuild"
    except Exception:  # noqa: BLE001 - never raises: anything unexpected verifies
        return "verify"


###########################################################################################################
# A domain name (or resolver name) out of the acme store is UNTRUSTED input that is joined
# straight into a filesystem path. `Path(outputPath) / name` discards `outputPath`
# entirely when `name` is absolute, and `../` walks out of it -- which is how a crafted
# `domain.main` got a private key written to an arbitrary directory. Validated AFTER the
# wildcard prefix is stripped, because that is the value that actually reaches the join.
_PATH_COMPONENT_PATTERN = re.compile(
    # `\Z`, not `$`: `$` also matches just BEFORE a trailing newline, so "example.test\n"
    # validated and produced a directory whose name ended in a newline -- contained, but
    # an odd on-disk name and a free line of log injection.
    r"^(?!-)[A-Za-z0-9_-]{1,63}(\.(?!-)[A-Za-z0-9_-]{1,63})*\Z"
)


def _is_safe_path_component(value: str | None) -> bool:
    """Is `value` a plain DNS-style label sequence, safe to use as one path segment?

    A whitelist, not a blacklist: anything carrying a separator, a drive letter, a NUL, a
    leading `/`, or a `..` segment fails to match at all.
    """
    return bool(value) and _PATH_COMPONENT_PATTERN.match(str(value)) is not None


def _is_contained_within(base: Path, candidate: Path) -> bool:
    """Is `candidate` `base` itself, or a descendant of it, once both are resolved?

    The regex above already rejects traversal, but containment is the property that
    actually matters, so it is asserted directly rather than inferred -- symlinked output
    directories and future call sites included.
    """
    try:
        resolvedBase = Path(base).resolve()
        resolvedCandidate = Path(candidate).resolve()
    except OSError:
        return False

    return (
        resolvedCandidate == resolvedBase or resolvedBase in resolvedCandidate.parents
    )


def _artifact_paths(
    base: Path,
    resolverName: str | None,
    name: str,
    *,
    flat: bool,
    resolverInPathName: bool,
) -> list[Path]:
    """The five artifact paths of one certificate: key, certificate, chain, full chain,
    PKCS12 (ADR-0040).

    The only place a base, a resolver name and a domain name are joined into a path. The
    writer takes its targets from here and the restart lookup reads the paths the writer
    recorded, so the two cannot disagree about the layout. Pure: no settings object, no
    filesystem access.
    """
    directory = Path(base)
    if resolverInPathName and resolverName:
        directory = directory / resolverName
    if flat:
        return [
            directory / f"{name}.key",
            directory / f"{name}.crt",
            directory / f"{name}.chain.pem",
            directory / f"{name}.fullchain.pem",
            directory / f"{name}.pfx",
        ]
    directory = directory / name
    return [
        directory / "privkey.pem",
        directory / "cert.pem",
        directory / "chain.pem",
        directory / "fullchain.pem",
        directory / "cert.pfx",
    ]


def _pfx_fingerprint_path(pfxPath: Path) -> Path:
    """The fingerprint sidecar of a `.pfx` (ADR-0051): `cert.pfx.fingerprint.json`, or
    `<name>.pfx.fingerprint.json` in the flat layout. Pure, and the only place this path is
    derived. It is not one of the five artifact paths, so the restart rule never sees it.
    """
    return pfxPath.with_name(pfxPath.name + ".fingerprint.json")


# One store file's recorded artifacts: `(resolverName, name) -> paths`. Keyed by resolver
# as well as name so a failed resolver can keep exactly its own previous record (RV-1).
_ArtifactEntry = dict[tuple[str | None, str], tuple[Path, ...]]


###########################################################################################################
# Reading Traefik's ACME store (AD-7, ADR-0043). The file is Go's encoding of
# `map[resolverName]*StoredData{Account; Certificates}` -- or, for Traefik v1.7, one unkeyed
# `StoredData` -- with no JSON tags, so a nil slice or pointer is `null`. The shape is
# detected from the keys present, never from `Registration.uri`: that is the account URL
# at whichever CA issued it (Let's Encrypt, ZeroSSL, Google, step-ca), not a protocol
# version. The store is trusted Traefik output and is read whole, without a size limit;
# whoever can write `/data` can already replace the certificates being exported.
_RESOLVER_NODE_KEYS = ("certificates", "account")


def _ci_get(node: object, key: str) -> object:
    """`node[key]`, matched exactly first and then case-insensitively; `None` when
    `node` is not a dict or holds no such key."""
    if not isinstance(node, dict):
        return None
    if key in node:
        return node[key]
    lowered = key.lower()
    for candidate, value in node.items():
        if isinstance(candidate, str) and candidate.lower() == lowered:
            return value
    return None


def _is_resolver_node(node: object) -> bool:
    """A `StoredData`: a dict with an `Account` or `Certificates` key, in either case."""
    return isinstance(node, dict) and any(
        isinstance(k, str) and k.lower() in _RESOLVER_NODE_KEYS for k in node
    )


def _is_unwrapped_store(data: dict) -> bool:
    """Is the top level itself one `StoredData` (v1.7, or an unwrapped v2)?

    Its `Account`/`Certificates` values are an account object, a list or `null` -- never a
    resolver node -- which is what tells it apart from a wrapped store whose resolver
    happens to be called `account` or `certificates`.
    """
    return _is_resolver_node(data) and not any(
        isinstance(k, str)
        and k.lower() in _RESOLVER_NODE_KEYS
        and _is_resolver_node(value)
        for k, value in data.items()
    )


def _iter_resolver_nodes(data: dict) -> Iterator[tuple[str | None, dict]]:
    """Every resolver node in a parsed store, as `(resolver name, node)`.

    The name is the top-level key of a resolver-wrapped store and `None` for an unwrapped
    one; it is never replaced by a synthetic name, because it is what the exported paths
    are derived from (ADR-0040). A top-level value that is not a resolver node is skipped
    with a WARNING. Nothing else is checked here: names are validated where they are
    joined into a path.
    """
    if not isinstance(data, dict):
        return
    if _is_unwrapped_store(data):
        yield (None, data)
        return
    for name, node in data.items():
        if _is_resolver_node(node):
            yield (str(name), node)
        else:
            globalLogger.warning(
                f"Skipping top-level key '{sanitize_for_log(str(name))}': not an ACME "
                "resolver node"
            )


def _certificate_entries(node: dict) -> list[dict]:
    """The certificate entries of one resolver node.

    `Certificates` (v2/v3, v1.7) when it is a list, or the legacy ACME-v1
    `DomainsCertificate.Certs`, at node level or under `Account`. `null` anywhere on the
    way means "no certificates". A `Certificates` value that is neither a list nor `null`
    is a structurally broken node and raises `ValueError`; an entry that is not a dict is
    skipped with a WARNING.
    """
    certificates = _ci_get(node, "Certificates")
    if certificates is not None and not isinstance(certificates, list):
        raise ValueError(
            f"'Certificates' is a {type(certificates).__name__}, not a list"
        )

    entries: list = list(certificates or [])
    legacy = _ci_get(node, "DomainsCertificate") or _ci_get(
        _ci_get(node, "Account"), "DomainsCertificate"
    )
    legacyCerts = _ci_get(legacy, "Certs")
    if isinstance(legacyCerts, list):
        entries.extend(legacyCerts)

    valid: list[dict] = []
    for index, entry in enumerate(entries):
        if isinstance(entry, dict):
            valid.append(entry)
        else:
            globalLogger.warning(
                f"Skipping certificate entry {index}: a {type(entry).__name__}, not an "
                "object"
            )
    return valid


def _entry_fields(entry: dict) -> tuple[object, object, object, object]:
    """`(main domain, key, full chain, SANs)` of one entry, each case chosen by the keys
    that entry has. A legacy v1 entry nests them under `Certificate` (`Domain`,
    `PrivateKey`, `Certificate`) with SANs under `Domains`."""
    nested = _ci_get(entry, "Certificate")
    if isinstance(nested, dict):
        return (
            _ci_get(nested, "Domain"),
            _ci_get(nested, "PrivateKey"),
            _ci_get(nested, "Certificate"),
            _ci_get(_ci_get(entry, "Domains"), "SANs"),
        )
    domain = _ci_get(entry, "Domain")
    return (
        _ci_get(domain, "Main"),
        _ci_get(entry, "Key"),
        nested,
        _ci_get(domain, "SANs"),
    )


class _Candidate(NamedTuple):
    """One exportable certificate entry, as read from the store."""

    resolverName: str | None
    storeName: str  # `domain.main` as stored, wildcard prefix included
    name: str  # the name the artifacts are written under
    privatekey: str
    fullchain: str
    sans: list[str]


def _covers_name(candidate: _Candidate) -> bool:
    """Does the entry's certificate cover the name its files are written under? True when
    the stored main domain is that name, or a stored SAN is. A wildcard main domain whose
    prefix was stripped covers only its subdomains, never the bare name (ADV-4)."""
    name = candidate.name.lower()
    return candidate.storeName.lower() == name or any(
        san.lower() == name for san in candidate.sans
    )


_NO_EXPIRY = datetime.datetime.min.replace(tzinfo=datetime.timezone.utc)


def _leaf_not_after(fullchainB64: str) -> datetime.datetime | None:
    """The leaf's `notAfter`, or `None` when the chain cannot be decoded or parsed."""
    try:
        return _parse_fullchain(b64decode(fullchainB64, validate=True))[
            0
        ].not_valid_after_utc
    except Exception:  # noqa: BLE001 - an unparsable chain simply never wins
        return None


def _format_expiry(value: datetime.datetime | None) -> str:
    return value.isoformat() if value is not None else "unknown"


def _log_resolver(resolverName: str | None) -> str:
    """A resolver name fit for a log line; `(unnamed)` for an unwrapped store."""
    return (
        f"'{sanitize_for_log(resolverName)}'"
        if resolverName is not None
        else "(unnamed)"
    )


def _read_store(path: str) -> dict:
    """The parsed store, read whole (no size limit: it is Traefik's own output).

    Raises `FileNotFoundError` when absent, and `ValueError` when empty, not valid JSON
    (including undecodable bytes), or nested deeply enough to exhaust the parser.
    """
    text = Path(path).read_text(encoding="utf-8")
    if not text.strip():
        raise ValueError("the file is empty")
    try:
        return json.loads(text)
    except RecursionError as e:
        raise ValueError("the JSON is nested too deeply to parse") from e


###########################################################################################################
class AcmeCertificateExporter:
    def __init__(self, settings: Settings):

        self.__settings = settings
        self.__logger = globalLogger
        # store file -> what its last pass recorded (ADR-0040 §4). Read by the restart
        # lookup, which can run on a deferred-restart timer thread while a drain rebuilds
        # an entry. So the published mapping is never mutated: a writer builds a new one
        # and publishes it with one assignment, and a reader takes one reference and
        # iterates that (AG-13). The lock only serialises writers.
        self.__artifactIndex: dict[str, _ArtifactEntry] = {}
        self.__artifactIndexLock = threading.Lock()

    # --------------------------------------------------------------------------------------
    def artifactMtime(self, domain: str) -> float | None:
        """The newest mtime of the artifacts recorded for `domain`, or `None`.

        Covers every store file this process has processed (ADR-0040 §6), so a domain
        exported under two resolvers yields its newest file. Only recorded paths are
        examined: nothing is re-derived from settings and the output directory is never
        globbed, so a file the exporter did not write cannot make a container a candidate.
        A path that cannot be stat'ed counts as missing.
        """
        index = self.__artifactIndex
        newest: float | None = None
        for entry in index.values():
            for (_resolverName, name), paths in entry.items():
                if name != domain:
                    continue
                for path in paths:
                    try:
                        mtime = os.stat(path).st_mtime
                    except OSError as e:
                        self.__logger.debug(
                            f"Cannot stat {path}: {e}; treated as missing"
                        )
                        continue
                    if newest is None or mtime > newest:
                        newest = mtime
        return newest

    # --------------------------------------------------------------------------------------
    def __recordArtifacts(
        self,
        sourceFile: str,
        recorded: _ArtifactEntry,
        keepNames: set[tuple[str | None, str]],
        keepResolvers: set[str | None],
    ) -> None:
        """Publish `sourceFile`'s new entry (ADR-0040 §4).

        `keepNames` are certificates whose rebuild failed and `keepResolvers` resolvers
        that failed as a whole: their previous paths are carried over rather than dropped,
        so a restart lost to a crash is still recovered on the next pass (RV-1).
        """
        with self.__artifactIndexLock:
            previous = self.__artifactIndex.get(sourceFile, {})
            entry: _ArtifactEntry = {
                key: paths
                for key, paths in previous.items()
                if key in keepNames or key[0] in keepResolvers
            }
            entry.update(recorded)
            index = dict(self.__artifactIndex)
            index[sourceFile] = entry
            self.__artifactIndex = index

    # --------------------------------------------------------------------------------------
    def __certificateCandidates(
        self, data: dict, resolverName: str | None = None
    ) -> list[_Candidate]:
        """The exportable certificate entries of one resolver node.

        Raises only for a structurally broken node (the caller isolates resolvers from one
        another); every per-entry problem is logged here and the next entry continues.
        """
        candidates: list[_Candidate] = []
        logResolver = _log_resolver(resolverName)

        if (
            self.__settings.resolverInPathName
            and resolverName
            and not _is_safe_path_component(resolverName)
        ):
            # The resolver name is joined into the output path exactly like the domain
            # name is, and comes from the same untrusted acme store.
            self.__logger.error(
                f"Refusing to export: resolver name {logResolver} "
                "is not a valid path component"
            )
            return candidates

        entries = _certificate_entries(data)
        self.__logger.info(
            f"Resolver {logResolver}: {len(entries)} certificate entries"
        )
        if self.__logger.isEnabledFor(logging.DEBUG):
            # Informational only: the CA is never used to decide the store's shape.
            uri = _ci_get(_ci_get(_ci_get(data, "Account"), "Registration"), "uri")
            self.__logger.debug(
                f"Resolver {logResolver}: CA account "
                f"'{sanitize_for_log(uri) if isinstance(uri, str) else '(none)'}'"
            )

        for c in entries:
            try:
                storeName, privatekey, fullchain, sans = _entry_fields(c)

                if not isinstance(storeName, str) or not storeName:
                    self.__logger.warning(
                        f"Skipping a certificate entry of resolver {logResolver}: it "
                        "has no main domain"
                    )
                    continue

                name = storeName.removeprefix("*.")

                if not _is_safe_path_component(name):
                    # This value is joined into a filesystem path (a directory in the
                    # default layout, a filename in flat mode). An absolute `name`
                    # discards `outputPath` entirely and `../` walks out of it, so a
                    # crafted `domain.main` chooses where the private key lands.
                    self.__logger.error(
                        f"Refusing to export domain '{sanitize_for_log(name)}': not a "
                        "valid certificate name for a filesystem path"
                    )
                    continue

                if (
                    len(self.__settings.domains["include"]) > 0
                    and name not in self.__settings.domains["include"]
                ) or (
                    len(self.__settings.domains["exclude"]) > 0
                    and name in self.__settings.domains["exclude"]
                ):
                    self.__logger.warning(f"Skipping domain: {name}")

                    continue

                if (
                    not isinstance(privatekey, str)
                    or not isinstance(fullchain, str)
                    or len(privatekey) <= 0
                    or len(fullchain) <= 0
                ):
                    self.__logger.warning(
                        f"Unable to find private key or full chain for cert domain: {name}"
                    )
                    continue

                candidates.append(
                    _Candidate(
                        resolverName=resolverName,
                        storeName=storeName,
                        name=name,
                        privatekey=privatekey,
                        fullchain=fullchain,
                        sans=[str(x) for x in sans] if isinstance(sans, list) else [],
                    )
                )
            except Exception as e:  # noqa: BLE001 - one bad domain must not stop the rest
                self.__logger.error(
                    f"Error processing domain: {sanitize_for_log(str(e))}"
                )

        return candidates

    # --------------------------------------------------------------------------------------
    def __artifactPaths(
        self, name: str, resolverName: str | None
    ) -> tuple[Path, list[Path]]:
        """`(base, paths)`: the output base and a domain's five artifact paths."""
        basePath = (
            Path(self.__settings.outputPath)
            if self.__settings.outputPath
            else Path.cwd()
        )
        return basePath, _artifact_paths(
            basePath,
            resolverName,
            name,
            flat=self.__settings.flat,
            resolverInPathName=self.__settings.resolverInPathName,
        )

    # --------------------------------------------------------------------------------------
    def __owners(self, candidates: list[_Candidate]) -> list[_Candidate]:
        """One candidate per set of artifact files, in store order.

        Two entries map onto the same files when two resolvers hold one domain and the
        resolver is not in the path, or when one resolver holds both `example.test` and
        `*.example.test` (the wildcard prefix is stripped from the name). Exporting both
        made them overwrite each other on every pass (BL-E014-012). An entry that covers
        the name the files are written under (its stored main domain is that name, or its
        SANs list it) beats one that does not, so a wildcard without an apex SAN never
        becomes the apex's files (ADV-4). Among equals, the entry whose leaf expires last
        owns the files; on a tie, the first in store order does (Traefik writes the
        resolver map with sorted keys, so the order is stable). Each other entry is
        skipped with a WARNING.
        """
        groups: dict[Path, list[int]] = {}
        for index, c in enumerate(candidates):
            _base, paths = self.__artifactPaths(c.name, c.resolverName)
            # The key file stands for the set: two candidates share one iff they share it.
            groups.setdefault(paths[0], []).append(index)

        owners: set[int] = set()
        for target, indices in groups.items():
            if len(indices) == 1:
                owners.add(indices[0])
                continue
            expiry = {i: _leaf_not_after(candidates[i].fullchain) for i in indices}
            covers = {i: _covers_name(candidates[i]) for i in indices}
            # max() keeps the first of equal keys, so ties go to store order.
            owner = max(indices, key=lambda i: (covers[i], expiry[i] or _NO_EXPIRY))
            owners.add(owner)
            kept = candidates[owner]
            for i in indices:
                if i == owner:
                    continue
                skipped = candidates[i]
                hint = (
                    "; set resolverinpathname to export both"
                    if skipped.resolverName != kept.resolverName
                    else ""
                )
                if covers[owner] and not covers[i]:
                    hint += (
                        f"; '{sanitize_for_log(skipped.storeName)}' does not cover "
                        f"'{sanitize_for_log(skipped.name)}'"
                    )
                self.__logger.warning(
                    f"Not exporting '{sanitize_for_log(skipped.storeName)}' (resolver "
                    f"{_log_resolver(skipped.resolverName)}, expires "
                    f"{_format_expiry(expiry[i])}): '{target}' is exported from "
                    f"'{sanitize_for_log(kept.storeName)}' (resolver "
                    f"{_log_resolver(kept.resolverName)}, expires "
                    f"{_format_expiry(expiry[owner])}){hint}"
                )

        return [c for i, c in enumerate(candidates) if i in owners]

    # --------------------------------------------------------------------------------------
    def __exportDomain(
        self,
        name: str,
        privatekeyB64: str,
        fullchainB64: str,
        resolverName: str | None,
        sweptDirectories: set[Path],
    ) -> tuple[bool, list[Path] | None]:
        """Build, compare and write one domain's artifact set (ADR-0043).

        Returns `(changed, paths)`. `changed` is True if and only if at least one of the
        domain's files changed on disk in this pass (in a dry run: would have changed).
        That is the per-domain change signal: a domain whose artifacts all match the files
        already on disk is neither rewritten nor reported. `paths` are the domain's
        artifact paths once it reached the write step, rewritten or not (ADR-0040 §4), and
        `None` when it did not: its build failed or its directory was refused.
        """
        logName = sanitize_for_log(name)
        passphrase = self.__settings.pkcs12Passphrase
        dryRun = self.__settings.dryRun

        # 1. Decode the key and chain strictly and parse the chain: the cheap inputs every
        #    pass needs. Nothing touches the output directory until every artifact that
        #    will be written exists, so a domain that cannot be exported keeps its files.
        stage = "key"
        try:
            # Strict: a non-alphabet byte is an error, never silently dropped.
            keyPem = b64decode(privatekeyB64, validate=True)
            stage = "certificate chain"
            fullchainPem = b64decode(fullchainB64, validate=True)
            certs = _parse_fullchain(fullchainPem)
        except Exception as e:  # noqa: BLE001 - one bad domain must not stop the rest
            self.__logBuildFailure(logName, stage, e)
            return False, None

        leafPem = certs[0].public_bytes(serialization.Encoding.PEM)
        chainPem = b"".join(
            c.public_bytes(serialization.Encoding.PEM) for c in certs[1:]
        )

        basePath, paths = self.__artifactPaths(name, resolverName)
        directory = paths[0].parent

        # 2. Containment and the directory sweep.
        if not _is_contained_within(basePath, directory):
            # Containment is the property that matters; the name pattern is how it is
            # normally kept, this is the assertion of it.
            self.__logger.error(
                f"Refusing to export domain '{logName}': resolved output "
                f"directory '{directory}' escapes '{basePath}'"
            )
            return False, None

        # (path, bytes, policy mode). The flat `.crt` keeps holding the full chain; the
        # per-domain `cert.pem` holds the leaf alone.
        keyPath, certPath, chainPath, fullchainPath, pfxPath = paths
        pems = [
            (keyPath, keyPem, _SECRET_FILE_MODE),
            (certPath, fullchainPem if self.__settings.flat else leafPem, None),
            (chainPath, chainPem, None),
            (fullchainPath, fullchainPem, None),
        ]

        if not dryRun:
            if not directory.exists():
                directory.mkdir(parents=True, exist_ok=True)
            if directory not in sweptDirectories:
                _sweep_stale_temp_files(directory)
                sweptDirectories.add(directory)

        # 3. Byte-compare the PEMs; keep only what would change.
        changed = [
            (path, data, mode)
            for (path, data, mode) in pems
            if _file_differs(path, data, mode=mode, dryRun=dryRun)
        ]

        # 4. Is the `.pfx` current (ADR-0051)? Decided from its sidecar, with no key load.
        state = _pfx_state(pfxPath, keyPem, certs, passphrase, dryRun)

        # 5. Only a `.pfx` that must be rebuilt or verified pays for loading the key (at
        #    most once per pass) and building the bundle. Built before the first write.
        pfx: bytes | None = None
        verifiedPfx: bytes | None = None
        if state == "current":
            self.__logger.debug(f".pfx for {logName} current (fingerprint)")
        else:
            stage = "key"
            try:
                key = _load_private_key(keyPem, self.__settings.validateKeys)
                stage = "pkcs12"
                pfx = _serialize_pkcs12(key, certs, passphrase)
            except Exception as e:  # noqa: BLE001 - one bad domain must not stop the rest
                self.__logBuildFailure(logName, stage, e)
                return False, None

            reason: str | None
            if state == "rebuild":
                reason = (
                    "fingerprint mismatch" if os.path.lexists(pfxPath) else "missing"
                )
            else:
                try:
                    existing = pfxPath.read_bytes()
                except OSError:
                    reason = "unreadable"
                else:
                    # The content compare, once: its answer is recorded in the sidecar.
                    if _pfx_differs(pfxPath, key, certs, passphrase, dryRun=dryRun):
                        reason = "content differs"
                    else:
                        reason = None
                        verifiedPfx = existing
            if reason is not None:
                self.__logger.debug(f".pfx for {logName} rebuilt: {reason}")
                changed.append((pfxPath, pfx, _SECRET_FILE_MODE))

        if not changed:
            if verifiedPfx is not None:
                if dryRun:
                    self.__logger.debug(
                        f".pfx for {logName} verified by content; dry run: fingerprint "
                        "not recorded"
                    )
                else:
                    self.__writeFingerprint(
                        logName, pfxPath, verifiedPfx, keyPem, certs, passphrase
                    )
                    self.__logger.debug(
                        f".pfx for {logName} verified by content; fingerprint recorded"
                    )
            self.__logger.debug(f"Certificate for {logName} unchanged; nothing written")
            return False, paths

        changedNames = [path.name for (path, _data, _mode) in changed]
        if dryRun:
            self.__logger.debug(
                f"Dry run: would write {', '.join(changedNames)} for {logName}"
            )
            return True, paths

        # 6. Write only the changed artifacts, each atomically: the PEMs, then the `.pfx`,
        #    then its sidecar. Per-file atomicity plus build-first is the contract; the
        #    set as a whole is not transactional.
        written: list[str] = []
        for path, data, mode in changed:
            try:
                _atomic_write_bytes(path, data, mode=mode)
            except Exception as e:  # noqa: BLE001 - reported below, never swallowed
                unwritten = [n for n in changedNames if n not in written]
                if not written:
                    self.__logger.error(
                        f"Failed to export certificate for '{logName}': nothing was "
                        f"written ({e})"
                    )
                    return False, paths
                # Files on disk changed, so the domain IS reported. The next pass sees
                # the remaining differences and writes them.
                self.__logger.error(
                    f"Partial export for '{logName}': wrote {', '.join(written)}; did "
                    f"not write {', '.join(unwritten)} ({e})"
                )
                return True, paths
            written.append(path.name)

        if pfx is not None and pfxPath.name in written:
            _log_pkcs12_details(pfxPath, certs)
            self.__writeFingerprint(logName, pfxPath, pfx, keyPem, certs, passphrase)
        elif verifiedPfx is not None:
            self.__writeFingerprint(
                logName, pfxPath, verifiedPfx, keyPem, certs, passphrase
            )
        self.__logger.debug(
            f"Exported {logName}: {len(certs) - 1} intermediate(s); changed: "
            f"{', '.join(written)}"
        )
        return True, paths

    # --------------------------------------------------------------------------------------
    def __logBuildFailure(self, logName: str, stage: str, e: Exception) -> None:
        # The exception type and message only: never key bytes or the passphrase.
        self.__logger.error(
            f"Not exporting certificate for '{logName}': the {stage} could not be "
            f"built ({type(e).__name__}: {sanitize_for_log(str(e))}); its existing "
            "files are left as they were"
        )

    # --------------------------------------------------------------------------------------
    def __writeFingerprint(
        self,
        logName: str,
        pfxPath: Path,
        pfxBytes: bytes,
        keyPem: bytes,
        certs: list[x509.Certificate],
        passphrase: str | bytes | None,
    ) -> None:
        """Write the `.pfx`'s sidecar (ADR-0051), atomically at 0600. A failure is one
        WARNING and changes nothing else: the next pass verifies the `.pfx` by content."""
        sidecar = _pfx_fingerprint_path(pfxPath)
        try:
            record = _pfx_fingerprint(pfxBytes, keyPem, certs, passphrase)
            data = (json.dumps(record, sort_keys=True) + "\n").encode("utf-8")
            _atomic_write_bytes(sidecar, data, mode=_SECRET_FILE_MODE)
        except Exception as e:  # noqa: BLE001 - the sidecar is an optimisation only
            self.__logger.warning(
                f"Could not write the .pfx fingerprint file "
                f"'{sanitize_for_log(str(sidecar))}' for {logName} "
                f"({type(e).__name__}: {sanitize_for_log(str(e))}); the next pass "
                "verifies the .pfx by content"
            )

    # --------------------------------------------------------------------------------------
    def exportCertificatesForFile(self, sourceFile: str) -> list[str]:
        """Export every resolver in one store file (ADR-0043).

        Returns the de-duplicated union of the domains whose artifacts changed, in any
        resolver -- never `None`. A file that cannot be read or parsed returns `[]` with
        an ERROR; a resolver that fails is logged and skipped without discarding the
        others' domains.

        Also replaces this file's entry in the artifact index the restart lookup reads
        (ADR-0040 §4). A file-level failure leaves the previous entry in place.
        """
        indexKey = os.path.abspath(sourceFile)
        self.__logger.info(f"Processing file: {sourceFile}")

        try:
            data = _read_store(sourceFile)
        except FileNotFoundError:
            self.__logger.error(f"File not found: {sourceFile}")
            return []
        except (OSError, ValueError, MemoryError) as e:
            self.__logger.error(
                f"Error reading file '{sourceFile}': {type(e).__name__}: "
                f"{sanitize_for_log(str(e))}"
            )
            return []

        resolverId = self.__settings.traefikResolverId
        if resolverId:
            node = data.get(resolverId) if isinstance(data, dict) else None
            if not isinstance(node, dict) or not _is_resolver_node(node):
                self.__logger.warning(
                    f"Specified traefik resolver id '{sanitize_for_log(resolverId)}' "
                    f"is not found in acme file '{sourceFile}'. Skipping file"
                )
                return []
            resolvers: list[tuple[str | None, dict]] = [(resolverId, node)]
        else:
            resolvers = list(_iter_resolver_nodes(data))

        if not resolvers:
            self.__logger.warning(f"Skipping '{sourceFile}': no resolver node found")
            return []

        candidates: list[_Candidate] = []
        failed = 0
        failedResolvers: set[str | None] = set()
        for resolverName, node in resolvers:
            try:
                candidates.extend(self.__certificateCandidates(node, resolverName))
            except Exception as e:  # noqa: BLE001 - one resolver must not stop the rest
                failed += 1
                failedResolvers.add(resolverName)
                self.__logger.error(
                    f"Resolver {_log_resolver(resolverName)} failed in "
                    f"'{sourceFile}': {type(e).__name__}: {sanitize_for_log(str(e))}"
                )

        names: list[str] = []
        sweptDirectories: set[Path] = set()
        recorded: _ArtifactEntry = {}
        notRebuilt: set[tuple[str | None, str]] = set()
        for c in self.__owners(candidates):
            try:
                changed, paths = self.__exportDomain(
                    c.name, c.privatekey, c.fullchain, c.resolverName, sweptDirectories
                )
            except Exception as e:  # noqa: BLE001 - one bad domain must not stop the rest
                self.__logger.error(
                    f"Error processing domain '{sanitize_for_log(c.name)}': "
                    f"{sanitize_for_log(str(e))}"
                )
                notRebuilt.add((c.resolverName, c.name))
                continue
            if paths is None:
                notRebuilt.add((c.resolverName, c.name))
            else:
                recorded[(c.resolverName, c.name)] = tuple(paths)
            if not changed:
                continue
            if c.name not in names:
                names.append(c.name)
            self.__logger.info(
                "Extracted certificate for: {} ({})".format(
                    c.name, sanitize_for_log(", ".join(c.sans))
                )
            )

        if failed:
            self.__logger.warning(
                f"{failed} of {len(resolvers)} resolvers failed in {sourceFile}"
            )

        self.__recordArtifacts(indexKey, recorded, notRebuilt, failedResolvers)
        return names

    # --------------------------------------------------------------------------------------
    def exportCertificates(self) -> list:
        processedDomains: list[str] = []

        for name in glob.glob(
            os.path.join(str(self.__settings.dataPath), self.__settings.fileSpec)
        ):
            domains = self.exportCertificatesForFile(name)
            if domains and len(domains) > 0:
                processedDomains.extend(x for x in domains if x not in processedDomains)

        return processedDomains


class PemToPfxConverter:
    @staticmethod
    def build_pkcs12(
        key_pem: bytes,
        certs: list[x509.Certificate],
        passphrase: str | bytes | None,
    ) -> bytes:
        """The PKCS12 bundle for a key and its chain (leaf first). Pure: no I/O.

        The key is loaded with `password=None`: the ACME store's key is unencrypted PEM,
        and the passphrase protects the OUTPUT only (loading the key with it raised
        `TypeError` for every domain -- B2). The key is always validated here: this is the
        public API, and `settings.validatekeys` applies to the export path only. The
        intermediates are included, in order. A non-empty passphrase selects
        `BestAvailableEncryption` (AES-256/SHA-256); `None` or empty means an unencrypted
        bundle.
        """
        key = _load_private_key(key_pem, validate=True)
        return _serialize_pkcs12(key, certs, passphrase)

    @staticmethod
    def export_to_pkcs12(
        filename,
        key_data: str | bytes | PrivateKeyTypes,
        cert_data: str | bytes | x509.Certificate | list[x509.Certificate],
        passphrase: str | bytes | None = None,
    ):
        """`build_pkcs12` plus an atomic 0600 write, kept for external callers.

        `cert_data` is a full-chain PEM (leaf first), one certificate, or a list.
        """
        if isinstance(key_data, str):
            key_data = key_data.encode("utf-8")
        if not isinstance(key_data, bytes):
            key_data = key_data.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )

        if isinstance(cert_data, str):
            cert_data = cert_data.encode("utf-8")
        if isinstance(cert_data, bytes):
            certs = _parse_fullchain(cert_data)
        elif isinstance(cert_data, x509.Certificate):
            certs = [cert_data]
        else:
            certs = list(cert_data)

        pkcs12_bytes = PemToPfxConverter.build_pkcs12(key_data, certs, passphrase)

        # Atomic for the same reason the PEM siblings are (ADR-0024). 0600
        # unconditionally: the bundle embeds the private key, and an unset passphrase --
        # the documented default -- means `NoEncryption()`.
        _atomic_write_bytes(Path(filename), pkcs12_bytes, mode=_SECRET_FILE_MODE)

        _log_pkcs12_details(filename, certs)


###########################################################################################################
# Seconds between the first change in a burst and the export pass. Named rather than
# inline so the watch tests can drive the handler without waiting on wall-clock time.
WATCH_DEBOUNCE_SECONDS = 2

# INFO, once per pass that changed nothing: the hook and notifications are skipped then
# (ADR-0045), and a quiet pass must still be visible. Shared with app.py's start-up pass.
NO_CHANGE_MESSAGE = "No certificate changed; no hook or notification"

# How long shutdown waits for an in-flight drain to finish before giving up on it.
#
# The wait is bounded AND the drain threads are daemons (see `__arm`). Bounding alone does
# not bound shutdown: CPython joins every non-daemon thread at interpreter exit, so a drain
# still inside its 30s post-export hook or an Apprise delivery would hold the process open
# well past `docker stop`'s 10s grace and be SIGKILLed anyway -- the exposure BL-E010-002
# asks this code to close itself. Abandoning a mid-flight drain is only safe because every
# certificate file this process writes is written atomically (ADR-0023/ADR-0024): a dropped
# drain loses an export, never leaves a half-written one.
SHUTDOWN_JOIN_TIMEOUT_SECONDS = 5


class AcmeCertificateFileHandler(watchdog.events.PatternMatchingEventHandler):
    # --------------------------------------------------------------------------------------
    def __init__(
        self,
        exporter: AcmeCertificateExporter,
        dockerManager: DockerManager,
        settings: Settings,
    ):
        self.__exporter = exporter
        self.__dockerManager = dockerManager
        self.__settings = settings

        self.isWaiting = False
        # Every path seen since the window opened, not just the one that opened it. See
        # handleEvent for why a set rather than a single event.
        self.pendingPaths: set[str] = set()
        self.timer: threading.Timer | None = None
        # The id of the drain this window will run under. Generated when the window
        # OPENS, not when it fires, so the "certificates changed" line that opened it
        # already carries the key an operator greps for (ADR-0023 Decision 1).
        self.correlationId: str | None = None
        # Latched by `cancel()`. Once set, no new drain may be armed -- by a late event
        # from watchdog's dispatcher, or by the unwind path's re-arm.
        self.shuttingDown = False
        # True only while `doTheWork` is actually running. `isWaiting` covers armed AND
        # running, and `Timer.finished` is not set until the target RETURNS, so neither
        # can tell shutdown which of the two it is looking at.
        self.draining = False
        # Monotonic count of drains that got PAST the shutdown latch and actually ran.
        # `cancel()` reports from the delta across its own call rather than from a
        # separately-derived "armed" boolean, so it can never label a pass that ran as
        # cancelled.
        self.drainsRun = 0
        self.lock = threading.Lock()
        self.__logger = globalLogger

        # Set the patterns for PatternMatchingEventHandler
        watchdog.events.PatternMatchingEventHandler.__init__(
            self,
            patterns=[self.__settings.fileSpec],
            ignore_directories=True,
            case_sensitive=False,
        )

    # --------------------------------------------------------------------------------------
    def on_created(self, event):
        self.__logger.debug(f"Watchdog received created event - {event.src_path}.")
        self.handleEvent(event)

    # --------------------------------------------------------------------------------------
    def on_modified(self, event):
        self.__logger.debug(f"Watchdog received modified event - {event.src_path}.")
        self.handleEvent(event)

    # --------------------------------------------------------------------------------------
    def on_moved(self, event):
        """A file renamed onto, away from, or between watched names.

        `PatternMatchingEventHandler.dispatch` delivers a moved event when EITHER path
        matches, so which of the three cases this is has to be decided here. Without this
        override every rename went to the base class's no-op: a store replaced atomically
        (write a temporary file, rename it onto the store -- restores, `cp`-then-`mv`,
        editors) was never exported until some later in-place write.
        """
        if event.is_directory:
            return

        srcPath = os.fsdecode(event.src_path)
        destPath = os.fsdecode(event.dest_path)
        self.__logger.debug(
            "Watchdog received moved event - "
            f"{sanitize_for_log(srcPath)} -> {sanitize_for_log(destPath)}."
        )

        srcMatches = self.__matches(srcPath)
        correlationId: str | None = None
        if srcMatches:
            with self.lock:
                # The source no longer exists under that name, so exporting it would log a
                # spurious `File not found` ERROR -- and for a matching temporary file
                # renamed onto the store, that ERROR is all the pass would have produced.
                # Residual race, accepted: if the drain already took the source off the
                # queue (the rename landed more than one debounce window after the source's
                # own event), that pass still logs `File not found` for the vanished name.
                # Suppressing it would also hide a store that genuinely vanished mid-pass;
                # the destination is queued below for the next drain either way.
                self.pendingPaths.discard(srcPath)
                correlationId = self.correlationId if self.isWaiting else None

        if self.__matches(destPath):
            self.__queuePath(destPath)
            return
        if not srcMatches:
            # Unreachable through `dispatch`, which filters out a move matching neither.
            return

        token = set_correlation_id(correlationId)
        try:
            self.__logger.info(
                f"Store file {sanitize_for_log(srcPath)} was renamed to "
                f"{sanitize_for_log(destPath)}, which does not match the watched file "
                "pattern; not exported, exported certificates left in place"
            )
        finally:
            reset_correlation_id(token)

    # --------------------------------------------------------------------------------------
    def __matches(self, path: str) -> bool:
        # The same function, on the same inputs, that `dispatch` uses -- so the handler and
        # dispatch cannot disagree about what a watched name is.
        return match_any_paths(
            [path],
            included_patterns=self.patterns,
            excluded_patterns=self.ignore_patterns,
            case_sensitive=self.case_sensitive,
        )

    # --------------------------------------------------------------------------------------
    def handleEvent(self, event):

        if not event.is_directory:
            self.__queuePath(event.src_path)

    # --------------------------------------------------------------------------------------
    def __queuePath(self, path: str) -> None:
        with self.lock:
            # Record the path before deciding whether to arm a timer. This handler is
            # registered with `patterns=[fileSpec]` -- `*.json` by default -- across the
            # whole data directory, while the worker used to process one `src_path`. A
            # change to a *second* acme file during the window was therefore discarded
            # outright and never exported, and would stay unexported until that file
            # happened to change again. It is a distinct file, not a duplicate to
            # coalesce, and the multi-resolver setup this project documents is exactly
            # several acme files in one directory.
            if self.shuttingDown:
                # Shutdown has already cancelled the pending drain. watchdog's
                # dispatcher can still deliver an event it had in hand, and arming a
                # timer for it would reinstate exactly the orphaned thread `cancel()`
                # just removed -- and run a full export pass after "stopping...".
                self.__logger.debug(f"Shutting down; ignoring change to {path}")
                return

            self.pendingPaths.add(path)

            if self.isWaiting:
                # Belongs to the window already open, so it is reported under that
                # window's id rather than opening a second one.
                self.__logEvent(path, self.correlationId)
                return

            # Coalescing is still the point: watchdog fires several events per write,
            # and adding the same path to the set again is what absorbs them.
            self.isWaiting = True
            self.correlationId = new_correlation_id()
            self.__logEvent(path, self.correlationId)
            self.__arm()

    # --------------------------------------------------------------------------------------
    def __logEvent(self, path: str, correlationId: str | None) -> None:
        token = set_correlation_id(correlationId)
        try:
            self.__logger.info(f"Certificates changed found in file: {path}")
        finally:
            reset_correlation_id(token)

    # --------------------------------------------------------------------------------------
    def cancel(self) -> None:
        """Stop any pending drain and refuse to arm another. Safe to call at any time.

        The `self.timer is None` guard lives here rather than at the call site because
        this class is what creates the timer and what leaves the attribute `None` until
        the first watched-file event ever fires -- "start the process, Ctrl-C before
        anything happens" is the common path, and it must not raise (ADR-0026).
        """
        with self.lock:
            self.shuttingDown = True
            timer = self.timer
            correlationId = self.correlationId
            # Three states, read in ONE critical section. Neither `Timer.finished` (not
            # set until the target RETURNS) nor `Thread.is_alive()` (lags a finished run
            # by a scheduling quantum) can separate "armed" from "running", so the drain
            # publishes `draining` itself.
            draining = self.draining
            drainsRunBefore = self.drainsRun
            armed = timer is not None and self.isWaiting and not draining

        token = set_correlation_id(correlationId)
        try:
            if timer is None:
                self.__logger.info("Shutdown requested; no export drain was pending")
                return

            if draining:
                self.__logger.info(
                    "Shutdown requested; waiting up to "
                    f"{SHUTDOWN_JOIN_TIMEOUT_SECONDS}s for the in-flight export drain"
                )
                timer.join(SHUTDOWN_JOIN_TIMEOUT_SECONDS)
                if timer.is_alive():
                    self.__logger.warning(
                        "An export drain was still running after "
                        f"{SHUTDOWN_JOIN_TIMEOUT_SECONDS}s; abandoning it. Certificate "
                        "files are written atomically, so none is left partially written"
                    )
                return

            if armed:
                # Cancelling before it fires is the whole point: the debounce window dies
                # with the process instead of running an export during shutdown. But
                # `Timer.cancel()` is a no-op once the target has started, and the latch
                # set above is what actually stops a drain that is already on its way in.
                # So the message is decided from what was OBSERVED afterwards, never from
                # `armed` alone -- the boolean was read before the cancel and cannot know
                # which of the two happened.
                timer.cancel()
                timer.join(SHUTDOWN_JOIN_TIMEOUT_SECONDS)

                with self.lock:
                    ran = self.drainsRun > drainsRunBefore
                    stillDraining = self.draining

                if stillDraining or timer.is_alive():
                    self.__logger.warning(
                        "An export drain was still running after "
                        f"{SHUTDOWN_JOIN_TIMEOUT_SECONDS}s; abandoning it. Certificate "
                        "files are written atomically, so none is left partially written"
                    )
                    return

                if ran:
                    self.__logger.info(
                        "Shutdown requested; the pending export drain had already "
                        "started and has completed"
                    )
                    return

                self.__logger.info(
                    "Shutdown requested; cancelled the pending export drain"
                )
                return

            # It fired and finished. Saying "cancelled" here would label the common,
            # completely clean shutdown as a truncated run -- and attach that label to the
            # correlation id of a pass that succeeded.
            self.__logger.info("Shutdown requested; no export drain was pending")
        finally:
            reset_correlation_id(token)

    # --------------------------------------------------------------------------------------
    def doTheWork(self, correlationId: str | None = None, *args, **kwargs):
        """Drain every path that accumulated during the debounce window.

        Drains in a loop rather than taking one snapshot: a change arriving while this is
        running cannot arm a timer, because `isWaiting` is still set. Without the loop that
        change would wait for an unrelated future event to carry it.
        """
        # Re-bound on THIS thread: the timer target runs outside the context the id was
        # set in, so every log line below (and everything the export calls) would
        # otherwise be unjoinable. A missing id degrades to the unset placeholder rather
        # than raising -- a correlation id must never break the pass it observes.
        token = set_correlation_id(correlationId or new_correlation_id())

        paths: list[str] = []
        index = 0

        try:
            with self.lock:
                if self.shuttingDown:
                    # The latch was set between the timer firing and this entry. Running
                    # a full export pass after "stopping..." has been logged is exactly
                    # what `cancel()` exists to prevent, and `Timer.cancel()` cannot
                    # reach a target that has already started -- so the check belongs
                    # here, under the same lock that publishes `draining`.
                    self.isWaiting = False
                    self.__logger.warning(
                        "Shutdown latched before this export drain began; abandoning it. "
                        f"{len(self.pendingPaths)} path(s) will not be exported by this "
                        "process"
                    )
                    return

                self.draining = True
                self.drainsRun += 1

            self.__logger.debug("Starting the work")

            while True:
                with self.lock:
                    if not self.pendingPaths:
                        # Publish the flag in the SAME critical section that observes the
                        # queue empty. An earlier version broke out of the `with` here and
                        # cleared `isWaiting` in a `finally`, which releases the lock in
                        # between: an event delivered in that gap was recorded, saw
                        # `isWaiting` still set, and armed no timer -- then the flag was
                        # cleared and its path sat unprocessed with nothing scheduled to
                        # collect it. A lost wakeup, and the same "never exported until an
                        # unrelated future event" outcome the drain exists to remove.
                        self.isWaiting = False
                        self.__logger.debug("Finished")
                        return

                    paths = sorted(self.pendingPaths)
                    self.pendingPaths.clear()
                    # Reset with the batch, not once before the loop. `index` is only
                    # rebound by the `for` below, so a second batch that unwound before
                    # its first iteration would have been sliced by the PREVIOUS batch's
                    # last index -- dropping paths, or yielding [] and re-arming nothing.
                    index = 0

                for index, path in enumerate(paths):
                    try:
                        self.__processPath(path, get_correlation_id())
                    except Exception:
                        self.__logger.exception(f"Unhandled error processing '{path}'")
        except BaseException:
            # Reached by KeyboardInterrupt, SystemExit, or anything the per-path handler
            # above does not catch. This runs on a `threading.Timer` thread, where an
            # escaping exception goes to `threading.excepthook` and the thread dies
            # silently -- so the flag must be cleared here or it stays set for the life of
            # the process. Paths already taken off the queue but not yet processed go back
            # on it, and a timer is re-armed, because nothing else will collect them.
            with self.lock:
                self.pendingPaths.update(paths[index:])
                self.isWaiting = False
                self.__rearm()
            raise
        finally:
            with self.lock:
                self.draining = False
            reset_correlation_id(token)

    # --------------------------------------------------------------------------------------
    def __rearm(self) -> None:
        """Arm a drain if work is outstanding. Caller must hold `self.lock`."""
        if not self.pendingPaths or self.isWaiting:
            return
        if self.shuttingDown:
            # The unwind path reaches here on a KeyboardInterrupt during a drain -- which
            # is the shutdown itself. Re-arming would hand back the orphaned thread
            # `cancel()` exists to remove.
            self.__logger.warning(
                f"Shutting down; {len(self.pendingPaths)} path(s) will not be exported "
                "by this process"
            )
            return
        self.isWaiting = True
        # A new window, so a new id: what is re-armed here is work that the interrupted
        # drain did not do. The line below names both, so the two passes can be joined by
        # hand when one has to be traced across the interruption.
        previousCorrelationId = self.correlationId
        self.correlationId = new_correlation_id()
        self.__logger.info(
            f"Re-arming export drain as {self.correlationId} for work left by "
            f"{previousCorrelationId}"
        )
        self.__arm()

    # --------------------------------------------------------------------------------------
    def __arm(self) -> None:
        """Start the debounce timer for the current window. Caller must hold `self.lock`.

        Daemon by design: a drain that is still running when the process is told to stop
        must not keep the interpreter alive (CPython joins non-daemon threads at exit, so
        a bounded `join` in `cancel()` would bound nothing). Safe only because every
        certificate file is written atomically -- the worst an abandoned drain costs is an
        export that did not happen, never a half-written file.
        """
        # `contextvars` does not reach a manually started thread, so the id is handed to
        # the timer's target explicitly and re-bound there.
        self.timer = threading.Timer(
            WATCH_DEBOUNCE_SECONDS, self.__drainWindow, args=(self.correlationId,)
        )
        self.timer.daemon = True
        self.timer.start()

    # --------------------------------------------------------------------------------------
    def __drainWindow(self, correlationId: str | None = None) -> None:
        """Timer target. Publishes `draining` BEFORE anything else can be observed.

        ADR-0023 Amendment 4a states that shutdown can tell an armed window from a running
        one. It could not: `draining` used to be published part-way into `doTheWork`, so a
        drain that had already begun still looked "armed" to `cancel()`, which then
        reported a pass that in fact ran as cancelled. Setting the flag as the first
        statement on the timer thread is what closes that window; the latch re-check at
        the top of `doTheWork` is what makes the other half of the race harmless.
        """
        with self.lock:
            self.draining = True

        self.doTheWork(correlationId)

    # --------------------------------------------------------------------------------------
    def __processPath(self, path: str, correlationId: str | None = None) -> None:
        domains = self.__exporter.exportCertificatesForFile(path) or []

        # Only for the domains whose artifacts changed; a file whose export changed
        # nothing runs neither (ADR-0045, amending ADR-0014 §7).
        if domains:
            run_post_export_command(
                self.__settings.postExportCommand,
                domains,
                self.__settings.dryRun,
                correlationId=correlationId,
            )
            # Scope: this file's changed domains, once per file per drain -- not the pass
            # total. app.py's run-at-start notifies once for the union of every file
            # instead. The two differ because the two passes differ, and ADR-0014 requires
            # each to be stated rather than left for an operator to infer from counts.
            send_export_notifications(
                self.__settings.appriseUrls,
                domains,
                self.__settings.dryRun,
                correlationId=correlationId,
            )
        else:
            self.__logger.info(NO_CHANGE_MESSAGE)

        if self.__settings.restartContainers:
            # Every pass, whether or not a domain changed: the rule compares the exported
            # files with each container's start, so a restart lost to a crash or a
            # shutdown is recovered here (ADR-0045).
            self.__dockerManager.restartLabeledContainers(self.__exporter.artifactMtime)
