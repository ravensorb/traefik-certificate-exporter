import glob
import json
import logging
import os
import re
import stat
import tempfile
import threading
import time
from base64 import b64decode
from pathlib import Path

import watchdog.events
import watchdog.observers
from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.types import PrivateKeyTypes
from cryptography.hazmat.primitives.serialization import pkcs12

from .docker import DockerManager
from .logging_utils import (
    get_correlation_id,
    globalLogger,
    new_correlation_id,
    reset_correlation_id,
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


_LOG_CONTROL_CHARS_PATTERN = re.compile(r"[\r\n\x1b]")


def _sanitize_for_log(value: str | None) -> str:
    """Strip characters that let an untrusted, rejected domain/resolver name forge log
    lines or terminal output: CR/LF (log-line injection) and ESC (ANSI/CSI terminal-escape
    injection). Applied only to values interpolated into a log *message*, separately from
    -- and in addition to -- `_is_safe_path_component`'s filesystem-path safety check,
    which this does not replace.
    """
    return _LOG_CONTROL_CHARS_PATTERN.sub("", str(value)) if value is not None else ""


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


###########################################################################################################
class AcmeCertificateExporter:
    def __init__(self, settings: Settings):

        self.__settings = settings
        self.__logger = globalLogger

    # --------------------------------------------------------------------------------------
    def __exportCertificate(
        self, data: dict, resolverName: str | None = None, keys: str = "lowercase"
    ) -> list | None:
        names = []
        sweptDirectories: set[Path] = set()

        # Determine ACME version
        acme_version = 2 if "acme-v02" in data["Account"]["Registration"]["uri"] else 1

        if (
            self.__settings.resolverInPathName
            and resolverName
            and not _is_safe_path_component(resolverName)
        ):
            # The resolver name is joined into the output path exactly like the domain
            # name is, and comes from the same untrusted acme store.
            self.__logger.error(
                f"Refusing to export: resolver name '{_sanitize_for_log(resolverName)}' "
                "is not a valid path component"
            )
            return names

        # Find certificates
        certs = []
        if acme_version == 1:
            certs = data["DomainsCertificate"]["Certs"]
        elif acme_version == 2:
            certs = data["Certificates"]

        # Loop over all certificates
        for c in certs:
            try:
                name = ""
                privatekey = ""
                fullchain = ""
                sans = ""

                if acme_version == 1:
                    name = c["Certificate"]["Domain"]
                    privatekey = c["Certificate"]["PrivateKey"]
                    fullchain = c["Certificate"]["Certificate"]
                    sans = c["Domains"]["SANs"]
                elif acme_version == 2:
                    if keys == "uppercase":
                        name = c["Domain"]["Main"]
                        privatekey = c["Key"]
                        fullchain = c["Certificate"]
                        sans = c["Domain"]["SANs"]
                    else:
                        name = c["domain"]["main"]
                        privatekey = c["key"]
                        fullchain = c["certificate"]
                        # not sure what this is - can't find any here...
                        sans = c["domain"].get("sans", [])
                else:
                    # This should NEVER happen
                    self.__logger.error(
                        f"CRITICAL ERROR - Unknown ACME version detected: {acme_version}"
                    )
                    continue

                name = name.removeprefix("*.")

                if not _is_safe_path_component(name):
                    # This value is joined into a filesystem path (a directory in the
                    # default layout, a filename in flat mode). An absolute `name`
                    # discards `outputPath` entirely and `../` walks out of it, so a
                    # crafted `domain.main` chooses where the private key lands.
                    self.__logger.error(
                        f"Refusing to export domain '{_sanitize_for_log(name)}': not a "
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

                if len(privatekey) <= 0 or len(fullchain) <= 0:
                    self.__logger.warning(
                        f"Unable to find private key or full chain for cert domain: {name}"
                    )
                    continue

                # Decode private key, certificate and chain
                privatekey = b64decode(privatekey).decode("utf-8")
                fullchain = b64decode(fullchain).decode("utf-8")
                start = fullchain.find("-----BEGIN CERTIFICATE-----", 1)
                cert = fullchain[0:start]
                chain = fullchain[start:]

                if not self.__settings.dryRun:
                    # Create domain     directory if it doesn't exist
                    basePath = (
                        Path(self.__settings.outputPath)
                        if self.__settings.outputPath
                        else Path.cwd()
                    )
                    directory = basePath
                    if (
                        self.__settings.resolverInPathName
                        and resolverName
                        and len(resolverName) > 0
                    ):
                        directory = directory / resolverName

                    if not self.__settings.flat:
                        directory = directory / name

                    if not _is_contained_within(basePath, directory):
                        # Containment is the property that matters; the name pattern above
                        # is how it is normally kept, this is the assertion of it.
                        self.__logger.error(
                            f"Refusing to export domain '{name}': resolved output "
                            f"directory '{directory}' escapes '{basePath}'"
                        )
                        continue

                    if not directory.exists():
                        directory.mkdir(parents=True, exist_ok=True)

                    if directory not in sweptDirectories:
                        _sweep_stale_temp_files(directory)
                        sweptDirectories.add(directory)

                    if self.__settings.flat:
                        # Write private key, certificate and chain to flat files
                        self.__logger.debug(f"Exporting private key for: {name}")
                        _atomic_write_text(
                            directory / (str(name) + ".key"),
                            privatekey,
                            mode=_SECRET_FILE_MODE,
                        )

                        self.__logger.debug(f"Exporting cert for: {name}")
                        _atomic_write_text(directory / (str(name) + ".crt"), fullchain)

                        self.__logger.debug(f"Exporting chain for: {name}")
                        _atomic_write_text(
                            directory / (str(name) + ".chain.pem"), chain
                        )

                        self.__logger.debug(f"Exporting full chain for: {name}")
                        _atomic_write_text(
                            directory / (str(name) + ".fullchain.pem"), fullchain
                        )

                        self.__logger.debug(f"Exporting pfx for: {name}")
                        PemToPfxConverter.export_to_pkcs12(
                            (directory / (str(name) + ".pfx")),
                            privatekey,
                            cert,
                            self.__settings.pkcs12Passphrase,
                        )
                    else:
                        # Write private key, certificate and chain to file
                        self.__logger.debug(f"Exporting private key for: {name}")
                        _atomic_write_text(
                            directory / "privkey.pem",
                            privatekey,
                            mode=_SECRET_FILE_MODE,
                        )

                        self.__logger.debug(f"Exporting cert for: {name}")
                        _atomic_write_text(directory / "cert.pem", cert)

                        self.__logger.debug(f"Exporting chain for: {name}")
                        _atomic_write_text(directory / "chain.pem", chain)

                        self.__logger.debug(f"Exporting full chain for: {name}")
                        _atomic_write_text(directory / "fullchain.pem", fullchain)

                        self.__logger.debug(f"Exporting pfx for: {name}")
                        PemToPfxConverter.export_to_pkcs12(
                            directory / "cert.pfx",
                            privatekey,
                            cert,
                            self.__settings.pkcs12Passphrase,
                        )

                names.append(name)

                self.__logger.info(
                    "Extracted certificate for: {} ({})".format(
                        name, ", ".join(sans) if sans else ""
                    )
                )
            except Exception as e:  # noqa: BLE001 - one bad domain must not stop the rest
                self.__logger.error(f"Error processing domain: {e}")

        return names

    # --------------------------------------------------------------------------------------
    def exportCertificatesForFile(self, sourceFile: str) -> "list[str] | None":
        self.__logger.info(f"Processing file: {sourceFile}")

        try:
            # does the file exist
            if not os.path.isfile(sourceFile):
                self.__logger.error(f"File not found: {sourceFile}")
                return []

            # is the file size greater than 0
            if os.stat(sourceFile).st_size == 0:
                self.__logger.error(f"File is empty: {sourceFile}")
                return []

            data = json.loads(Path(sourceFile).read_text())

            resolversToProcess = []
            keys = "uppercase"
            if (
                self.__settings.traefikResolverId
                and len(self.__settings.traefikResolverId) > 0
            ):
                if self.__settings.traefikResolverId in data:
                    resolversToProcess.append(self.__settings.traefikResolverId)
                    keys = "lowercase"
                else:
                    self.__logger.warning(
                        f"Specified traefik resolver id '{self.__settings.traefikResolverId}' is not found in acme file '{sourceFile}'. Skipping file"
                    )
                    return []
            else:
                # Should we try to get the first resolver if it is there?
                elementNames = list(data.keys())
                self.__logger.debug(
                    f"[DEBUG] Checking node '{elementNames[0]}' to see if it is a resolver node"
                )
                if "Account" in data[elementNames[0]]:
                    resolversToProcess = elementNames
                    keys = "lowercase"

            names = []

            if len(resolversToProcess) > 0:
                self.__logger.info(f"Resolvers to process: {resolversToProcess}")

                for resolver in resolversToProcess:
                    names.extend(
                        self.__exportCertificate(
                            data[resolver], resolverName=resolver, keys=keys
                        )
                        or []
                    )
            else:
                names = self.__exportCertificate(data, keys=keys) or []

            return names
        except Exception as e:  # noqa: BLE001 - one bad file must not stop the sweep
            self.__logger.error(f"Error processing file '{sourceFile}': {e}")

    # --------------------------------------------------------------------------------------
    def exportCertificates(self) -> list:
        processedDomains = []

        for name in glob.glob(
            os.path.join(str(self.__settings.dataPath), self.__settings.fileSpec)
        ):
            domains = self.exportCertificatesForFile(name)
            if domains and len(domains) > 0:
                processedDomains.extend(x for x in domains if x not in processedDomains)

        return processedDomains


class PemToPfxConverter:
    @staticmethod
    def export_to_pkcs12(
        filename,
        key_data: str | bytes | PrivateKeyTypes,
        cert_data: str | bytes | x509.Certificate,
        passphrase: str | bytes | None = None,
    ):

        # if passphrase is a string, convert to bytes
        if isinstance(passphrase, str):
            passphrase = passphrase.encode("utf-8")

        # if data is a string, convert to bytes, if it is a private key leave it alone for now
        if isinstance(key_data, str):
            key_data = key_data.encode("utf-8")

        # if data is a string, convert to bytes, if it is a certificate leave it alone for now
        if isinstance(cert_data, str):
            cert_data = cert_data.encode("utf-8")

        # if the private key is bytes lets load it, otherwise assume it is a private key object
        if isinstance(key_data, bytes):
            key = serialization.load_pem_private_key(key_data, password=passphrase)
        else:
            key = key_data

        # if the certificate is bytes lets load it, otherwise assume it is a certificate object
        if isinstance(cert_data, bytes):
            cert = x509.load_pem_x509_certificate(cert_data)
        else:
            cert = cert_data

        # get the common name from the certificate
        try:
            cert_subject_common_name = str(
                cert.subject.get_attributes_for_oid(x509.oid.NameOID.COMMON_NAME)[
                    0
                ].value
            )  # type: ignore
        except Exception:  # noqa: BLE001 - fall back to an unnamed certificate
            globalLogger.error("Failed to get common name from certificate")
            globalLogger.debug(
                f"File: '{filename}', Certificate Subject: '{cert.subject!s}'"
            )  # type: ignore

            cert_subject_common_name = None

        # format the common name if it is a wildcard
        if cert_subject_common_name is not None:
            if "*." in cert_subject_common_name:
                cert_subject_common_name = "{} (wildcard)".format(
                    cert_subject_common_name.split("*.")[1]
                )
        else:
            cert_subject_common_name = "LetsEncrypt Certificate"

        pkcs12_encryption = (
            serialization.BestAvailableEncryption(passphrase)
            if passphrase is not None
            else serialization.NoEncryption()
        )
        pkcs12_bytes = pkcs12.serialize_key_and_certificates(
            cert_subject_common_name.encode("utf-8"),
            key,  # type: ignore
            cert,  # type: ignore
            None,
            pkcs12_encryption,
        )

        # Atomic for the same reason the PEM siblings are: a `.pfx` is a certificate
        # file a service loads directly, and truncate-then-write leaves it zero-length
        # if the process dies mid-write (ADR-0024).
        #
        # 0600 unconditionally: the bundle embeds the private key, and `NoEncryption()` is
        # what it gets whenever `pkcs12passphrase` is unset -- the documented default. A
        # world-readable `.pfx` is a world-readable private key.
        _atomic_write_bytes(Path(filename), pkcs12_bytes, mode=_SECRET_FILE_MODE)

        if globalLogger.isEnabledFor(logging.DEBUG):
            (_pkcs12_key, pkcs12_cert, _pkcs12_chain) = (
                pkcs12.load_key_and_certificates(pkcs12_bytes, passphrase)
            )

            globalLogger.debug(f"Creating PKCS12 file: {filename}")
            globalLogger.debug(f"  Name: {cert_subject_common_name}")
            globalLogger.debug(
                f"  Subject: {pkcs12_cert.subject.get_attributes_for_oid(x509.oid.NameOID.COMMON_NAME)[0].value!s}"
            )  # type: ignore
            globalLogger.debug(
                f"  Issuer: {pkcs12_cert.issuer.get_attributes_for_oid(x509.oid.NameOID.COMMON_NAME)[0].value!s}"
            )  # type: ignore
            globalLogger.debug(
                f"  Not Before: {pkcs12_cert.not_valid_before_utc.date()}"
            )  # type: ignore
            globalLogger.debug(f"  Not After: {pkcs12_cert.not_valid_after_utc.date()}")  # type: ignore


###########################################################################################################
# Seconds between the first change in a burst and the export pass. Named rather than
# inline so the watch tests can drive the handler without waiting on wall-clock time.
WATCH_DEBOUNCE_SECONDS = 2

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
        self.timer = None
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
    def handleEvent(self, event):

        if not event.is_directory:
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
                    self.__logger.debug(
                        f"Shutting down; ignoring change to {event.src_path}"
                    )
                    return

                self.pendingPaths.add(event.src_path)

                if self.isWaiting:
                    # Belongs to the window already open, so it is reported under that
                    # window's id rather than opening a second one.
                    self.__logEvent(event.src_path, self.correlationId)
                    return

                # Coalescing is still the point: watchdog fires several events per write,
                # and adding the same path to the set again is what absorbs them.
                self.isWaiting = True
                self.correlationId = new_correlation_id()
                self.__logEvent(event.src_path, self.correlationId)
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
        domains = self.__exporter.exportCertificatesForFile(path)

        run_post_export_command(
            self.__settings.postExportCommand,
            domains or [],
            self.__settings.dryRun,
            correlationId=correlationId,
        )
        # Scope: this file's domains, once per file per drain -- not the pass total.
        # app.py's run-at-start notifies once for the union of every file instead. The two
        # differ because the two passes differ, and ADR-0014 requires each to be stated
        # rather than left for an operator to infer from message counts.
        send_export_notifications(
            self.__settings.appriseUrls,
            domains or [],
            self.__settings.dryRun,
            correlationId=correlationId,
        )

        if self.__settings.restartContainers:
            self.__dockerManager.restartLabeledContainers(domains)
