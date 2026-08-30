#!/usr/bin/env python3

import os
import sys
import time

import watchdog.events
import watchdog.observers

from ._version import __version__
from .libs.certificate_exporter import (
    AcmeCertificateExporter,
    AcmeCertificateFileHandler,
)
from .libs.cli_args import globalArgs
from .libs.docker import DockerManager
from .libs.logging_utils import globalLogger, setup_logging
from .libs.post_export import run_post_export_command
from .libs.settings import globalSettingsMgr

###########################################################################################################
###########################################################################################################


def require_existing_path(logger, path: str | None, label: str) -> None:
    """Exit(1) if `path` is unset or does not exist on disk, logging why either way."""
    if path is None:
        logger.error(f"{label} is not configured. Exiting...")
        sys.exit(1)
    if not os.path.exists(path):
        logger.error(f"{label} '{path}' does not exist. Exiting...")
        sys.exit(1)


def main():
    setup_logging(
        cfg_file_name="logging.yaml",
        default_level=globalArgs.logginglevel,
        env_key="TRAEFIK_CERTIFICATE_EXPORTER_LOGGING_CFGFILE",
    )

    logger = globalLogger
    logger.setLevel(globalArgs.logginglevel)

    globalSettingsMgr.loadFromFile(
        fileName=globalArgs.configfile, cmdLineArgs=globalArgs
    )
    settings = globalSettingsMgr.settings

    logger.info(f"Traefik Certificate Exporter v{__version__} starting....")

    ###########################################################################################################

    # Lets validate the path we are being asked to watch actually exists
    require_existing_path(logger, settings.dataPath, "Data Path")

    logger.info(f"Data Path: {settings.dataPath}")
    logger.info(f"File Spec: {settings.fileSpec}")
    logger.info(f"Output Path: {settings.outputPath}")

    exporter = AcmeCertificateExporter(settings=settings)
    dockerManager = DockerManager(settings=settings)

    if settings.runAtStart:
        logger.info("Exporting certificates....")
        domainsProcessed = exporter.exportCertificates()
        run_post_export_command(
            settings.postExportCommand, domainsProcessed or [], settings.dryRun
        )
        if (
            domainsProcessed
            and len(domainsProcessed) > 0
            and settings.restartContainers
        ):
            dockerManager.restartLabeledContainers(domainsProcessed)

    if settings.watchForChanges:
        logger.info("Watching for changes to files....")
        event_handler = AcmeCertificateFileHandler(
            exporter=exporter, dockerManager=dockerManager, settings=settings
        )

        observer = watchdog.observers.Observer()
        observer.schedule(event_handler, path=settings.dataPath, recursive=False)

        observer.start()
        try:
            while True:
                time.sleep(settings.watchInterval)
        except KeyboardInterrupt:
            observer.stop()
        observer.join()

    logger.info("Traefik Certificate Exporter stopping....")


if __name__ == "__main__":
    main()
