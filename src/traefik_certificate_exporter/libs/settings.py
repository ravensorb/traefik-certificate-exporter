#!/usr/bin/env python3

#######################################################################

from typing import List
from enum import Enum

import logging
import os
from pathlib import Path

import confuse
import importlib_resources
import jsonpickle
from dotenv import load_dotenv
from expandvars import expandvars

from .object import ObjectBase
from .logging_utils import globalLogger

#######################################################################

class Settings:
    dataPath : str | None
    fileSpec : str
    outputPath : str | None
    resolverInPathName : bool
    traefikResolverId : str
    flat : bool
    dryRun : bool
    restartContainers : bool
    domains : dict = { "include": [], "exclude": [] }
    watchForChanges : bool
    runAtStart : bool
    watchInterval : int
    pkcs12Passphrase : str | None
    
    def __init__(self, dataPath : str | Path | None, fileSpec : str, outputPath : str | Path | None, resolverInPathName : bool, traefikResolverId: str,flat : bool, dryRun : bool, restartContainers : bool, domains : dict, watchForChanges : bool, runAtStart : bool, watchInterval : int, pkcs12Passphrase : str | None) -> None:
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

        Returns:
            None
        """
        self.dataPath = str(dataPath)
        self.fileSpec = fileSpec
        self.outputPath = str(outputPath)
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

#######################################################################

class SettingsManager(ObjectBase):
    _config: confuse.Configuration
    settings: Settings
    modulePath: Path

    def __init__(self) -> None:
        super().__init__()
        
        self.__logger = globalLogger
        self.modulePath = Path(str(importlib_resources.files("traefik_certificate_exporter")))

    def loadFromFile(self, fileName: str, cmdLineArgs=None) -> None:
        super()._raise_on_progress("Loading Configuration")

        self._config = confuse.Configuration("traefik_certificate_exporter", "traefik_certificate_exporter")

        self.__logger.debug("Loading Configuration from Default Source")
        self._config._add_default_source()
        self.__logger.debug("Loading Configuration from User Source")
        self._config._add_user_source()

        # if os.path.exists(self.modulePath.joinpath("config_default.yaml")):
        #     self.__logger.debug("Loading Configuration from Default Configuration")
        #     self._config.set_file(self.modulePath.joinpath("config_default.yaml"))

        if os.path.exists(fileName):
            self.__logger.debug("Loading Configuration from File: '{}'".format(fileName))
            self._config.set_file(fileName)

        if os.path.exists(self.modulePath.joinpath(".env")):
            self.__logger.debug("Loading Configuration from Module Environment File")
            load_dotenv(self.modulePath.joinpath(".env"))

        if os.path.exists(Path(os.getcwd(), ".env")):
            self.__logger.debug("Loading Configuration from Local Environment File")
            load_dotenv(Path(os.getcwd(), ".env"))

        self._config.set_env(prefix="TRAEFIK_CERTIFICATE_EXPORTER_", sep='_')

        if cmdLineArgs is not None:
            self.__logger.debug("Loading Configuration from Command Line")
            self.__logger.debug("Command Line Args: {}".format(cmdLineArgs))
            self._config.set_args(cmdLineArgs, dots=True)

        self.__logger.debug("Configuration Directory: {}".format(self._config.config_dir()))
        self.__logger.debug("User Configuration Path: {}".format(self._config.user_config_path()))

        self._dump_config()

        self.__logger.debug("Generating Active Configuration")
        
        self.settings = Settings(
            dataPath=self._config['settings']['datapath'].as_str(),                                     # type: ignore
            fileSpec=self._config['settings']['filespec'].as_str(),                                     # type: ignore
            outputPath=self._config['settings']['outputpath'].as_str(),                                 # type: ignore
            resolverInPathName=self._config['settings']['resolverinpathname'].get(bool),                # type: ignore
            flat=self._config['settings']['flat'].get(bool),                                            # type: ignore
            traefikResolverId=self._config['settings']['traefikresolverid'].get(confuse.Optional(str)), # type: ignore
            dryRun=self._config['settings']['dryrun'].get(bool),                                        # type: ignore
            restartContainers=self._config['settings']['restartcontainers'].get(bool),                  # type: ignore
            domains=self._config['settings']['domains'].get(confuse.Optional(dict)),                    # type: ignore
            watchForChanges=self._config['settings']['watchforchanges'].get(bool),                      # type: ignore
            runAtStart=self._config['settings']['runatstart'].get(bool),                                # type: ignore
            watchInterval=self._config['settings']['watchinterval'].get(int),                           # type: ignore
            pkcs12Passphrase=self._config['settings']['pkcs12passphrase'].get(confuse.Optional(str)),   # type: ignore
        )

        self._dump_settings()

    def _dump_settings(self):
        self.__logger.debug("Current Settings (active)...")
        self.__logger.debug(jsonpickle.dumps(self.settings, unpicklable=False))

        # super()._raise_on_progress("Current Settings (active):")
        # super()._raise_on_progress(jsonpickle.dumps(self.settings, unpicklable=False))

    def _dump_config(self):
        self.__logger.debug("Current Config (from file)...")
        self.__logger.debug(jsonpickle.dumps(self._config, unpicklable=False))

        # super()._raise_on_progress("Current Config (from file):")
        # super()._raise_on_progress(jsonpickle.dumps(self._config, unpicklable=False))

    def _handle_on_progress(self, message):
        self.__logger.info(message)
        # print(message)

#######################################################################

globalSettingsMgr = SettingsManager()
