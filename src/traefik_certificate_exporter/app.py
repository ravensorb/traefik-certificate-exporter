#!/usr/bin/env python3

import sys
import os
import time
import json
import argparse
from argparse import ArgumentTypeError as err
import watchdog.events
import watchdog.observers
import time
import logging
from ._version import __version__
from .certificate_exporter import AcmeCertificateExporter, AcmeCertificateFileHandler
from .docker import DockerManager, DOCKER_LABLE

###########################################################################################################
###########################################################################################################
_settings = {
    "dataPath": "./",
    "fileSpec": "*.json",
    "outputPath": "./certs",
    "traefikResolverId": None,
    "resolverInPathName": True,
    "flat": False,
    "dryRun": False,
    "restartContainers": False,
    "domains": {
        "include": [],
        "exclude": []
    }
}

###########################################################################################################

def main(settings = None):
    if settings is None:
        settings = _settings
    
    logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.DEBUG)

    logging.info("Traefik Cretificate Exporter v{} starting....".format(__version__))

    ###########################################################################################################
    parser = argparse.ArgumentParser(description="Extract traefik letsencrypt certificates.")

    parser.add_argument("-c", "--config-file", dest="configFile", default=None, type=str,
                                help="the path to watch for changes (default: %(default)s)")
    parser.add_argument("-d", "--data-path", dest="dataPath", default=settings["dataPath"], type=str, 
                                help="the path that contains the acme json files (default: %(default)s)")
    parser.add_argument("-w", "--watch-for-changes", action="store_true", dest="watch",
                                help="If specified, monitor and watch for changes to acme files")
    parser.add_argument("-fs", "--file-spec", dest="fileSpec", default=settings["fileSpec"], type=str, 
                                help="file that contains the traefik certificates (default: %(default)s)")
    parser.add_argument("-o", "--output-path", dest="outputPath", default=settings["outputPath"], type=str, 
                                help="The folder to exports the certificates in to (default: %(default)s)")
    parser.add_argument("--traefik-resolver-id", dest="traefikResolverId", default=settings["traefikResolverId"],
                                help="Traefik certificate-resolver-id.")
    parser.add_argument("-f", "--flat", action="store_true", dest="flat",
                                help="If specified, all certificates into a single folder")
    parser.add_argument("-r", "--restart_container", action="store_true", dest="restartContainer",
                                help="If specified, any container that are labeled with '" + DOCKER_LABLE + "=<DOMAIN>' will be restarted if the domain name of a generated certificates matches the value of the lable. Multiple domains can be seperated by ','")
    parser.add_argument("--dry-run", action="store_true", dest="dry", 
                                help="Don't write files and do not restart docker containers.")
    parser.add_argument("--run-at-start", action="store_true", dest="runAtStart", 
                                help="Runs Export immediately on start (used with watch-for-changes).")
    parser.add_argument("--include-resolvername-in-outputpath", action="store_true", dest="resolverInPathName", 
                                help="Added the resolvername in the path used to export the certificates (ignored if flat is specified).")

    group = parser.add_mutually_exclusive_group()
    group.add_argument("-id", "--include-domains", nargs="*", dest="includeDomains", default=None,
                                help="If specified, only certificates that match domains in this list will be extracted")
    group.add_argument("-xd", "--exclude-domains", nargs="*", dest="excludeDomains", default=None,
                                help="If specified. certificates that match domains in this list will be ignored")
    
    ###########################################################################################################

    args = parser.parse_args()

    # Do we need to load settings from a config file
    if args.configFile and os.path.exists(args.configFile):
        logging.info("Loading Confgile: {}".format(args.configFile))
        settings = json.loads(open(args.configFile).read())

    # Letts override the settings from the dommain line
    settings["dataPath"] = args.dataPath
    settings["fileSpec"] = args.fileSpec
    settings["outputPath"] = args.outputPath
    settings["traefikResolverId"] = args.traefikResolverId
    settings["resolverInPathName"] = args.resolverInPathName

    settings["flat"] = args.flat
    settings["restartContainers"] = args.restartContainer
    settings["dryRun"] = args.dry

    if args.includeDomains:
        settings["domains"]["include"] = args.includeDomains
    if args.excludeDomains:
        settings["domains"]["exclude"] = args.excludeDomains

    # Lets validate the path we are being asked to watch actually exists
    if not os.path.exists(settings["dataPath"]):
        logging.error("Data Path does not exist. Exiting...")
        sys.exit(-1)

    logging.info("Data Path: {}".format(settings["dataPath"]))
    logging.info("File Spec: {}".format(settings["fileSpec"]))
    logging.info("Output Path: {}".format(settings["outputPath"]))

    exporter = AcmeCertificateExporter(settings=settings)
    dockerManager = DockerManager(settings=settings)

    if not args.watch or args.runAtStart:
        logging.info("Exporting certificates....")
        domainsProcessed = exporter.exportCertificates()
        if domainsProcessed and len(domainsProcessed) > 0 and settings["restartContainers"]:
            dockerManager.restartLabeledContainers(domainsProcessed)
    
    if args.watch:
        logging.info("Watching for changes to files....")
        event_handler = AcmeCertificateFileHandler(exporter=exporter, 
                                                    dockerManager=dockerManager,
                                                    settings=settings)

        observer = watchdog.observers.Observer()
        observer.schedule(event_handler, path=settings["dataPath"], recursive=False)

        observer.start()
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            observer.stop()
        observer.join()

    logging.info("Traefik Cretificate Exporter stopping....")

if __name__ == "__main__":
    main(_settings)