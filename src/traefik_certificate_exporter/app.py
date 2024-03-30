#!/usr/bin/env python3

import sys
import os
import time
import watchdog.events
import watchdog.observers
import time
import logging
from ._version import __version__
from .libs.certificate_exporter import AcmeCertificateExporter, AcmeCertificateFileHandler
from .libs.docker import DockerManager

from .libs.logging_utils import setup_logging
from .libs.cli_args import globalArgs
from .libs.settings import globalSettingsMgr

###########################################################################################################
###########################################################################################################

def main():
    setup_logging()

    logger = logging.getLogger("traefik_certificate_exporter")
    
    globalSettingsMgr.loadFromFile(fileName=globalArgs.configfile, cmdLineArgs=globalArgs)
    settings = globalSettingsMgr.settings

    logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.DEBUG)

    logger.info("Traefik Cretificate Exporter v{} starting....".format(__version__))

    ###########################################################################################################

    # Lets validate the path we are being asked to watch actually exists
    if settings.dataPath is None or not os.path.exists(settings.dataPath):
        logger.error("Data Path does not exist. Exiting...")

    logger.info("Data Path: {}".format(settings.dataPath))
    logger.info("File Spec: {}".format(settings.fileSpec))
    logger.info("Output Path: {}".format(settings.outputPath))

    exporter = AcmeCertificateExporter(settings=settings)
    dockerManager = DockerManager(settings=settings)

    if settings.runAtStart:
        logger.info("Exporting certificates....")
        domainsProcessed = exporter.exportCertificates()
        if domainsProcessed and len(domainsProcessed) > 0 and settings.restartContainers:
            dockerManager.restartLabeledContainers(domainsProcessed)
    
    if settings.watchForChanges:
        logger.info("Watching for changes to files....")
        event_handler = AcmeCertificateFileHandler(exporter=exporter, 
                                                    dockerManager=dockerManager,
                                                    settings=settings)

        observer = watchdog.observers.Observer()
        observer.schedule(event_handler, path=settings.dataPath, recursive=False)

        observer.start()
        try:
            while True:
                time.sleep(settings.watchInterval)
        except KeyboardInterrupt:
            observer.stop()
        observer.join()

    logger.info("Traefik Cretificate Exporter stopping....")

if __name__ == "__main__":
    main()