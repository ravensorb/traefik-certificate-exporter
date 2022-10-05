import os
import json
import glob
import threading
from argparse import ArgumentTypeError as err
from base64 import b64decode
import watchdog.events
import watchdog.observers
from pathlib import Path
import logging
from typing import Optional
from .docker import DockerManager

###########################################################################################################
class AcmeCertificateExporter:
    def __init__(self, settings : dict):

        self.__settings = settings

    # --------------------------------------------------------------------------------------
    def __exportCertificate(self, data : dict, resolverName : Optional[str] = None, keys : str = "lowercase") -> Optional[list]:
        names = []

        # Determine ACME version
        acme_version = 2 if 'acme-v02' in data['Account']['Registration']['uri'] else 1

        # Find certificates
        certs = []
        if acme_version == 1:
            certs = data['DomainsCertificate']['Certs']
        elif acme_version == 2:
            certs = data['Certificates']

        # Loop over all certificates
        for c in certs:
            name = ""
            privatekey = ""
            fullchain = ""
            sans = ""
            
            if acme_version == 1:
                name = c['Certificate']['Domain']
                privatekey = c['Certificate']['PrivateKey']
                fullchain = c['Certificate']['Certificate']
                sans = c['Domains']['SANs']
            elif acme_version == 2:
                if keys == "uppercase":
                    name = c['Domain']['Main']
                    privatekey = c['Key']
                    fullchain = c['Certificate']
                    sans = c['Domain']['SANs']
                else:
                    name = c['domain']['main']
                    privatekey = c['key']
                    fullchain = c['certificate']
                    sans = c['domain']['sans'] if'sans' in c['domain'] else []  # not sure what this is - can't find any here...
            else:
                # Thios should NEVER happen
                logging.error("CRITICAL ERROR - Unknown ACME version detected: {}".format(acme_version))
                continue
            
            if name.startswith("*."):
                name = name[2:]

            if (self.__settings["domains"]["include"] and name not in self.__settings["domains"]["include"]) or (self.__settings["domains"]["exclude"] and name in self.__settings["domains"]["exclude"]):
                continue

            if len(privatekey) <= 0 or len(fullchain) <= 0:
                logging.warning("Unable to find private key or full chain for cert domain: {}".format(name))
                continue

            # Decode private key, certificate and chain
            privatekey = b64decode(privatekey).decode('utf-8')
            fullchain = b64decode(fullchain).decode('utf-8')
            start = fullchain.find('-----BEGIN CERTIFICATE-----', 1)
            cert = fullchain[0:start]
            chain = fullchain[start:]

            if not self.__settings["dryRun"]:
                # Create domain     directory if it doesn't exist
                directory = Path(self.__settings["outputPath"])
                if "resolverInPathName" in self.__settings and self.__settings["resolverInPathName"] and resolverName and len(resolverName) > 0:
                    directory = directory / resolverName

                if not directory.exists():
                    directory.mkdir(parents=True, exist_ok=True)

                if self.__settings["flat"]:
                    # Write private key, certificate and chain to flat files
                    with (directory / (str(name) + '.key')).open('w') as f:
                        f.write(privatekey)

                    with (directory / (str(name) + '.crt')).open('w') as f:
                        f.write(fullchain)

                    with (directory / (str(name) + '.chain.pem')).open('w') as f:
                        f.write(chain)

                    # if sans:
                    #     for name in sans:
                    #         with (directory / (str(name) + '.key')).open('w') as f:
                    #             f.write(privatekey)
                    #         with (directory / (str(name) + '.crt')).open('w') as f:
                    #             f.write(fullchain)
                    #         with (directory / (str(name) + '.chain.pem')).open('w') as f:
                    #             f.write(chain)
                else:
                    directory = directory / name
                    if not directory.exists():
                        directory.mkdir(parents=True, exist_ok=True)

                    # Write private key, certificate and chain to file
                    with (directory / 'privkey.pem').open('w') as f:
                        f.write(privatekey)

                    with (directory / 'cert.pem').open('w') as f:
                        f.write(cert)

                    with (directory / 'chain.pem').open('w') as f:
                        f.write(chain)

                    with (directory / 'fullchain.pem').open('w') as f:
                        f.write(fullchain)

            logging.info("Extracted certificate for: {} ({})".format(name, ', '.join(sans) if sans else ''))

            names.append(name)

    # --------------------------------------------------------------------------------------
    def exportCertificatesForFile(self, sourceFile : str) -> 'Optional[list[str]]':
        data = json.loads(open(sourceFile).read())

        resolversToProcess = []
        keys = "uppercase"
        if self.__settings["traefikResolverId"] and len(self.__settings["traefikResolverId"]) > 0:
            if self.__settings["traefikResolverId"] in data:
                resolversToProcess.append(self.__settings["traefikResolverId"])
                keys = "lowercase"
            else:
                logging.warning("Specified traefik resolver id '{}' is not found in acme file '{}'. Skipping file".format(self.__settings["traefikResolverId"], sourceFile))
                return []
        else:
            # Should we try to get the first resolver if it is there?
            elementNames = list(data.keys())
            logging.debug("[DEBUG] Checking node '{}' to see if it is a resolver node".format(elementNames[0]))
            if "Account" in data[elementNames[0]]:
                resolversToProcess = elementNames
                keys = "lowercase"

        names = []

        if len(resolversToProcess) > 0:
            logging.info("Resolvers to process: {}".format(resolversToProcess))

            for resolver in resolversToProcess:
                names.append(self.__exportCertificate(data[resolver], resolverName=resolver, keys=keys))
        else:
            names = self.__exportCertificate(data, keys=keys)

        return names

    # --------------------------------------------------------------------------------------
    def exportCertificates(self) -> list:
        processedDomains = []

        for name in glob.glob(os.path.join(self.__settings["dataPath"], self.__settings["fileSpec"])):
            domains = self.exportCertificatesForFile(name)
            if domains and len(domains) > 0:
                processedDomains.extend(x for x in domains if x not in processedDomains)

        return processedDomains

###########################################################################################################
class AcmeCertificateFileHandler(watchdog.events.PatternMatchingEventHandler):
    # --------------------------------------------------------------------------------------
    def __init__(self, exporter : AcmeCertificateExporter, dockerManager : DockerManager, settings : dict):
        self.__exporter = exporter
        self.__dockerManager = dockerManager
        self.__settings = settings

        self.isWaiting = False
        self.lock = threading.Lock()

        # Set the patterns for PatternMatchingEventHandler
        watchdog.events.PatternMatchingEventHandler.__init__(self, patterns = [ self.__settings["fileSpec"] ],
                                                                    ignore_directories = True, 
                                                                    case_sensitive = False)

    # --------------------------------------------------------------------------------------
    def on_created(self, event):
        logging.debug("Watchdog received created event - % s." % event.src_path)
        self.handleEvent(event)

    # --------------------------------------------------------------------------------------
    def on_modified(self, event):
        logging.debug("Watchdog received modified event - % s." % event.src_path)
        self.handleEvent(event)

    # --------------------------------------------------------------------------------------
    def handleEvent(self, event):

        if not event.is_directory:
            logging.info("Certificates changed found in file: {}".format(event.src_path))

            with self.lock:
                if not self.isWaiting:
                    self.isWaiting = True # trigger the work just once (multiple events get fired)
                    self.timer = threading.Timer(2, self.doTheWork, args=[event])
                    self.timer.start()

    # --------------------------------------------------------------------------------------
    def doTheWork(self, *args, **kwargs):
        ''' 
        This is a workaround to handle multiple events for the same file
        '''
        logging.debug("[DEBUG] SStarting the work")

        if not args or len(args) == 0:
            logging.error("No event passed to worker")
            self.isWaiting = False

            return

        domains = self.__exporter.exportCertificatesForFile(args[0].src_path)

        if (self.__settings["restartContainers"]):
            self.__dockerManager.restartLabeledContainers(domains)

        with self.lock:
            self.isWaiting = False
        
        logging.debug('[DEBUG] Finished')
