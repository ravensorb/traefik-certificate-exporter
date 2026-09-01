#######################################################################


import json
import os
import re
import sys
from pathlib import Path

import confuse
import importlib_resources
import jsonpickle
from dotenv import load_dotenv

from .logging_utils import globalLogger
from .object import ObjectBase

#######################################################################

# Name/allowlist-based: any key shaped like a credential is masked regardless of which
# object it comes from, so a new secret-shaped field is redacted with no code change here.
_SECRET_FIELD_PATTERN = re.compile(
    r"(secret|password|passphrase|token|api[_-]?key)", re.IGNORECASE
)
_REDACTED_VALUE = "***REDACTED***"


def _redact_secrets(value):
    """Recursively mask dict values whose key looks like a credential."""
    if isinstance(value, dict):
        return {
            key: (
                _REDACTED_VALUE
                if _SECRET_FIELD_PATTERN.search(str(key))
                else _redact_secrets(val)
            )
            for key, val in value.items()
        }
    if isinstance(value, list):
        return [_redact_secrets(item) for item in value]
    return value


def _parse_domain_list(value) -> list:
    """Normalize a domains.include/exclude value into a list of domain strings.

    A config file/CLI source yields a real list already. confuse does support env-var
    arrays natively via indexed keys (`..._INCLUDE_0`, `..._INCLUDE_1`, ...), but this
    project's documented, already-in-use convention (docker/README.md) is a single
    comma-separated env var -- confuse never parses that shape into a list on its own, so
    it's split by hand here to keep that convention working, not because confuse can't
    represent lists at all.
    """
    if value is None:
        return []
    if isinstance(value, str):
        return [v.strip() for v in value.split(",") if v.strip()]
    return [str(v).strip() for v in value if str(v).strip()]


#######################################################################


class Settings:
    dataPath: str | None
    fileSpec: str
    outputPath: str | None
    resolverInPathName: bool
    traefikResolverId: str
    flat: bool
    dryRun: bool
    restartContainers: bool
    # Set per instance in __init__; as a class attribute this dict was shared by every
    # Settings object, so mutating settings.domains['include'] leaked across instances.
    domains: dict
    watchForChanges: bool
    runAtStart: bool
    watchInterval: int
    pkcs12Passphrase: str | None
    postExportCommand: str | None

    def __init__(
        self,
        dataPath: str | Path | None,
        fileSpec: str,
        outputPath: str | Path | None,
        resolverInPathName: bool,
        traefikResolverId: str,
        flat: bool,
        dryRun: bool,
        restartContainers: bool,
        domains: dict,
        watchForChanges: bool,
        runAtStart: bool,
        watchInterval: int,
        pkcs12Passphrase: str | None,
        postExportCommand: str | None = None,
    ) -> None:
        """
        Initialize the class with the provided parameters.

        Parameters:
            dataPath (str | Path | None): The path to the data.
            fileSpec (str): The specification of the file.
            outputPath (str | Path | None): The path to the output.
            resolverInPathName (bool): Flag indicating if the resolver is in the path name.
            traefikResolverId (str): The ID of the Traefik resolver.
            flat (bool): Flag indicating if the structure is flat.
            dryRun (bool): Flag indicating if it's a dry run.
            restartContainers (bool): Flag indicating if containers need to be restarted.
            domains (dict): Dictionary of domains.
            watchForChanges (bool): Flag indicating if changes should be watched.
            runAtStart (bool): Flag indicating if it should run at start.
            watchInterval (int): The interval to watch for changes.
            pkcs12Passphrase (str | None): Passphrase for PKCS12, if needed.
            postExportCommand (str | None): Shell-like command line run after a
                successful export pass, or None to disable (default).

        Returns:
            None
        """
        # str(None) == "None" would turn an unset path into a truthy, non-existent path
        # string, defeating the `is None` check callers rely on to detect "not configured".
        self.dataPath = str(dataPath) if dataPath is not None else None
        self.fileSpec = fileSpec
        self.outputPath = str(outputPath) if outputPath is not None else None
        self.resolverInPathName = resolverInPathName
        self.traefikResolverId = traefikResolverId
        self.flat = flat
        self.dryRun = dryRun
        self.restartContainers = restartContainers
        self.domains = domains
        self.watchForChanges = watchForChanges
        self.runAtStart = runAtStart
        self.watchInterval = watchInterval
        self.pkcs12Passphrase = pkcs12Passphrase
        self.postExportCommand = postExportCommand


#######################################################################


class SettingsManager(ObjectBase):
    _config: confuse.Configuration
    settings: Settings
    modulePath: Path

    def __init__(self) -> None:
        super().__init__()

        self.__logger = globalLogger
        self.modulePath = Path(
            str(importlib_resources.files("traefik_certificate_exporter"))
        )

    def loadFromFile(self, fileName: str, cmdLineArgs=None) -> None:
        super()._raise_on_progress("Loading Configuration")

        self._config = confuse.Configuration(
            "traefik_certificate_exporter", "traefik_certificate_exporter"
        )

        self.__logger.debug("Loading Configuration from Default Source")
        self._config._add_default_source()
        self.__logger.debug("Loading Configuration from User Source")
        self._config._add_user_source()

        # Order matters: confuse gives a later-added source higher priority. This project is
        # Docker-first, so env vars (the standard vehicle for per-deployment overrides in
        # containerized deploys) must outrank a static/mounted config file, matching
        # CLI > env var > config file > packaged default.
        if os.path.exists(self.modulePath.joinpath(".env")):
            self.__logger.debug("Loading Configuration from Module Environment File")
            load_dotenv(self.modulePath.joinpath(".env"))

        if os.path.exists(Path(os.getcwd(), ".env")):
            self.__logger.debug("Loading Configuration from Local Environment File")
            load_dotenv(Path(os.getcwd(), ".env"))

        if os.path.exists(fileName):
            self.__logger.debug(f"Loading Configuration from File: '{fileName}'")
            self._config.set_file(fileName)

        self._config.set_env(prefix="TRAEFIK_CERTIFICATE_EXPORTER_", sep="_")

        if cmdLineArgs is not None:
            self.__logger.debug("Loading Configuration from Command Line")
            self.__logger.debug(f"Command Line Args: {cmdLineArgs}")
            self._config.set_args(cmdLineArgs, dots=True)

        self.__logger.debug(f"Configuration Directory: {self._config.config_dir()}")
        self.__logger.debug(
            f"User Configuration Path: {self._config.user_config_path()}"
        )

        self._dump_config()

        self.__logger.debug("Generating Active Configuration")

        # Queried as two independent leaf keys, not `["domains"].get(dict)` -- confuse
        # only merges a nested dict across sources when every source defines the same
        # shape at that path. A source that sets only "domains.include" (env var or a
        # config file overriding one key) would otherwise make "domains.exclude" vanish
        # entirely instead of falling back to the packaged default's `[]` (GitHub #5).
        includeDomains = _parse_domain_list(
            self._config["settings"]["domains"]["include"].get()
        )
        excludeDomains = _parse_domain_list(
            self._config["settings"]["domains"]["exclude"].get()
        )

        if includeDomains and excludeDomains:
            self.__logger.error(
                "settings.domains.include and settings.domains.exclude are mutually "
                "exclusive -- set only one, via any combination of CLI, config file, "
                "or environment variable. Exiting..."
            )
            sys.exit(1)

        self.settings = Settings(
            dataPath=self._config["settings"]["datapath"].as_str(),  # type: ignore
            fileSpec=self._config["settings"]["filespec"].as_str(),  # type: ignore
            outputPath=self._config["settings"]["outputpath"].as_str(),  # type: ignore
            resolverInPathName=self._config["settings"]["resolverinpathname"].get(bool),  # type: ignore
            flat=self._config["settings"]["flat"].get(bool),  # type: ignore
            traefikResolverId=self._config["settings"]["traefikresolverid"].get(
                confuse.Optional(str)
            ),  # type: ignore
            dryRun=self._config["settings"]["dryrun"].get(bool),  # type: ignore
            restartContainers=self._config["settings"]["restartcontainers"].get(bool),  # type: ignore
            domains={"include": includeDomains, "exclude": excludeDomains},
            watchForChanges=self._config["settings"]["watchforchanges"].get(bool),  # type: ignore
            runAtStart=self._config["settings"]["runatstart"].get(bool),  # type: ignore
            watchInterval=self._config["settings"]["watchinterval"].get(int),  # type: ignore
            pkcs12Passphrase=self._config["settings"]["pkcs12passphrase"].get(
                confuse.Optional(str)
            ),  # type: ignore
            postExportCommand=self._config["settings"]["postexportcommand"].get(
                confuse.Optional(str)
            ),  # type: ignore
        )

        self._dump_settings()

    def _dump_settings(self):
        self.__logger.debug("Current Settings (active)...")
        safe = _redact_secrets(
            json.loads(jsonpickle.dumps(self.settings, unpicklable=False))
        )
        self.__logger.debug(jsonpickle.dumps(safe, unpicklable=False))

    def _dump_config(self):
        self.__logger.debug("Current Config (from file)...")
        safe = _redact_secrets(
            json.loads(jsonpickle.dumps(self._config, unpicklable=False))
        )
        self.__logger.debug(jsonpickle.dumps(safe, unpicklable=False))

    def _handle_on_progress(self, message):
        self.__logger.info(message)


#######################################################################

globalSettingsMgr = SettingsManager()
