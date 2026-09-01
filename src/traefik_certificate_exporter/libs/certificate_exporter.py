import glob
import json
import logging
import os
import threading
from base64 import b64decode
from pathlib import Path

import watchdog.events
import watchdog.observers
from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.types import PrivateKeyTypes
from cryptography.hazmat.primitives.serialization import pkcs12

from .docker import DockerManager
from .logging_utils import globalLogger
from .post_export import run_post_export_command
from .settings import Settings


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

        # Determine ACME version
        acme_version = 2 if "acme-v02" in data["Account"]["Registration"]["uri"] else 1

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
                    directory = (
                        Path(self.__settings.outputPath)
                        if self.__settings.outputPath
                        else Path.cwd()
                    )
                    if (
                        self.__settings.resolverInPathName
                        and resolverName
                        and len(resolverName) > 0
                    ):
                        directory = directory / resolverName

                    if not directory.exists():
                        directory.mkdir(parents=True, exist_ok=True)

                    if self.__settings.flat:
                        # Write private key, certificate and chain to flat files
                        self.__logger.debug(f"Exporting private key for: {name}")
                        with (directory / (str(name) + ".key")).open("w") as f:
                            f.write(privatekey)

                        self.__logger.debug(f"Exporting cert for: {name}")
                        with (directory / (str(name) + ".crt")).open("w") as f:
                            f.write(fullchain)

                        self.__logger.debug(f"Exporting chain for: {name}")
                        with (directory / (str(name) + ".chain.pem")).open("w") as f:
                            f.write(chain)

                        self.__logger.debug(f"Exporting full chain for: {name}")
                        with (directory / (str(name) + ".fullchain.pem")).open(
                            "w"
                        ) as f:
                            f.write(fullchain)

                        self.__logger.debug(f"Exporting pfx for: {name}")
                        PemToPfxConverter.export_to_pkcs12(
                            (directory / (str(name) + ".pfx")),
                            privatekey,
                            cert,
                            self.__settings.pkcs12Passphrase,
                        )
                    else:
                        directory = directory / name
                        if not directory.exists():
                            directory.mkdir(parents=True, exist_ok=True)

                        # Write private key, certificate and chain to file
                        self.__logger.debug(f"Exporting private key for: {name}")
                        with (directory / "privkey.pem").open("w") as f:
                            f.write(privatekey)

                        self.__logger.debug(f"Exporting cert for: {name}")
                        with (directory / "cert.pem").open("w") as f:
                            f.write(cert)

                        self.__logger.debug(f"Exporting chain for: {name}")
                        with (directory / "chain.pem").open("w") as f:
                            f.write(chain)

                        self.__logger.debug(f"Exporting full chain for: {name}")
                        with (directory / "fullchain.pem").open("w") as f:
                            f.write(fullchain)

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

        Path(filename).write_bytes(pkcs12_bytes)

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
            self.__logger.info(f"Certificates changed found in file: {event.src_path}")

            with self.lock:
                if not self.isWaiting:
                    self.isWaiting = (
                        True  # trigger the work just once (multiple events get fired)
                    )
                    self.timer = threading.Timer(2, self.doTheWork, args=[event])
                    self.timer.start()

    # --------------------------------------------------------------------------------------
    def doTheWork(self, *args, **kwargs):
        """
        This is a workaround to handle multiple events for the same file
        """
        self.__logger.debug("[DEBUG] SStarting the work")

        if not args or len(args) == 0:
            self.__logger.error("No event passed to worker")
            self.isWaiting = False

            return

        domains = self.__exporter.exportCertificatesForFile(args[0].src_path)

        run_post_export_command(
            self.__settings.postExportCommand, domains or [], self.__settings.dryRun
        )

        if self.__settings.restartContainers:
            self.__dockerManager.restartLabeledContainers(domains)

        with self.lock:
            self.isWaiting = False

        self.__logger.debug("[DEBUG] Finished")
