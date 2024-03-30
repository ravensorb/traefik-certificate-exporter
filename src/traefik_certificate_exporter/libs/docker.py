import docker
import logging
from typing import Optional
from .settings import Settings
from .logging_utils import globalLogger

###########################################################################################################

DOCKER_LABLE = "com.github.ravensorb.traefik-certificate-exporter.domain-restart"

###########################################################################################################
class DockerManager:
    def __init__(self, settings : Settings):
        self.__settings = settings
        self.__logger = globalLogger

    # --------------------------------------------------------------------------------------
    def restartLabeledContainers(self, domains : 'Optional[list[str]]'):
        if not self.__settings.restartContainers:
            return

        if domains is None:
            domains = []

        try:
            client = docker.from_env()
            container = client.containers.list(filters = {"label" : DOCKER_LABLE})
            for c in container:
                restartDomains = str.split(c.labels[ DOCKER_LABLE ], ',')  # type: ignore
                if not set(domains).isdisjoint(restartDomains):
                    self.__logger .info("Restarting container: {}".format(c.id))
                    if not self.__settings.dryRun:
                        try:
                            c.restart()  # type: ignore
                        except Exception as ex:
                            self.__logger .error("Failed restarting container: {}".format(c.id))
                    else:
                        self.__logger .info("[DRYRUN] restarting container: {}".format(c.id))
                            
        except Exception as ex:
            self.__logger .error("Failed restarting containers", exc_info=True)
