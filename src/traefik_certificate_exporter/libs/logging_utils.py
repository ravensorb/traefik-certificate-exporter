#!/usr/bin/env python3
###################################################################################################

import logging
import logging.config
import logging.handlers
import os
from pathlib import Path

import coloredlogs
import importlib_resources
import yaml
import traceback

import logging_tree

###################################################################################################

class RollingFileHanderEx(logging.handlers.RotatingFileHandler):
    def __init__(
        self,
        filename,
        mode: str = "a",
        maxBytes: int = 0,
        backupCount: int = 0,
        encoding: str | None = None,
        delay: bool = False,
        errors: str | None = None,
    ) -> None:
        os.makedirs(os.path.dirname(filename), exist_ok=True)

        super().__init__(filename, mode, maxBytes, backupCount, encoding, delay, errors)

###################################################################################################

def setup_logging(
    cfg_file_name: str = "logging.yaml", default_level = logging.INFO, env_key : str = "TRAEFIK_CERTIFICATE_EXPORTER_LOGGING_CFGFILE"
):
    """
    | **@author:** Prathyush SP
    | Logging Setup
    """

    path : str | None = None
    value = os.getenv(env_key, None)
    if value:
        path = value

    if path is None:
        modulePath = Path(str(importlib_resources.files("traefik_certificate_exporter")), cfg_file_name)
        cwdPath = Path(os.getcwd(), cfg_file_name)

        if Path.exists(modulePath):
            path = str(modulePath)

        if Path.exists(cwdPath):
            path = str(cwdPath)

    if path is None:
        path = cfg_file_name
        
    if os.path.exists(path):
        print(f"Loading logging configuration from {path}")
        with open(path, "rt") as f:
            try:
                config = yaml.safe_load(f.read())
                logging.config.dictConfig(config)
                logging.getLogger().setLevel(default_level)
                #coloredlogs.install()
            except Exception as e:
                print("Error in Logging Configuration. Using default configs")
                traceback.print_exc() 
                #print(f"\tType: {type(e).__name__}\n\tMessage: {e}\n\tTrace: {e.__traceback__}")

                #logging.basicConfig(level=default_level)
                coloredlogs.install(level=default_level)
    else:
        #logging.basicConfig(level=default_level)
        coloredlogs.install(level=default_level)
        print("Failed to load loogging configuration file. Using default logging configs")

    for handler in logging.getLogger().handlers:
        if isinstance(handler, type(logging.StreamHandler())):
            handler.setLevel(logging.DEBUG)

    if logging.getLogger().getEffectiveLevel() == logging.DEBUG:
        #print(logging.getLogger().__dict__)
        logging_tree.printout()
    