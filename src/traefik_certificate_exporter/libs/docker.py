import docker

from .logging_utils import globalLogger
from .settings import Settings

###########################################################################################################

DOCKER_LABEL = "com.github.ravensorb.traefik-certificate-exporter.domain-restart"


###########################################################################################################
class DockerManager:
    def __init__(self, settings: Settings):
        self.__settings = settings
        self.__logger = globalLogger

    # --------------------------------------------------------------------------------------
    def restartLabeledContainers(self, domains: "list[str] | None"):
        if not self.__settings.restartContainers:
            return

        if domains is None:
            domains = []

        try:
            client = docker.from_env()
            container = client.containers.list(filters={"label": DOCKER_LABEL})
            for c in container:
                restartDomains = str.split(c.labels[DOCKER_LABEL], ",")  # type: ignore
                if not set(domains).isdisjoint(restartDomains):
                    self.__logger.info(f"Restarting container: {c.id}")
                    if not self.__settings.dryRun:
                        try:
                            c.restart()  # type: ignore
                        except Exception:
                            self.__logger.exception(
                                f"Failed restarting container: {c.id}"
                            )
                    else:
                        self.__logger.info(f"[DRYRUN] restarting container: {c.id}")

        except Exception:
            self.__logger.exception("Failed restarting containers")
