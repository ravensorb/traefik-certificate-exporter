import threading
import time

import docker

from .logging_utils import globalLogger
from .settings import Settings

###########################################################################################################

DOCKER_LABEL = "com.github.ravensorb.traefik-certificate-exporter.domain-restart"

# A restart is driven by domain strings read out of Traefik's ACME store, which an operator
# does not fully control: anyone who can get a certificate issued into that store can get a
# domain name into this list. Without a floor on the restart rate, a noisy or hostile store
# turns every drain pass into a restart of every labeled container over the Docker socket --
# a denial of service with host-root-equivalent reach (BL-E011-016 / RT-009).
#
# The floor is the ONLY suppression applied here. Suppressing on "the matched domain set did
# not change" was tried and reverted: a drain pass reports every domain it exported, changed
# or not, so a renewal -- which keeps the domain name and replaces only the key material --
# looks identical to the previous pass and would be suppressed forever, which is the entire
# feature. Real change detection needs a per-domain fingerprint from the export path
# (BL-E012-xxx follow-up), not a comparison of names.
#
# Five minutes is far longer than any legitimate renewal cadence (days) and short enough that
# an operator does not perceive a delayed restart.
RESTART_COOLDOWN_SECONDS = 300


###########################################################################################################
class DockerManager:
    def __init__(self, settings: Settings):
        self.__settings = settings
        self.__logger = globalLogger
        # container id -> when this process last restarted it. Process-local and deliberately
        # not persisted: a fresh process has no prior observation, so the first pass after a
        # start is always eligible and a rotation during downtime is never swallowed.
        self.__lastRestart: dict[str, float] = {}
        # Drains run on `threading.Timer` threads while the run-at-start pass runs on the main
        # thread, so the check and the record have to be one indivisible step -- two
        # overlapping passes that both read "no prior restart" would both restart, which is
        # the storm the cooldown exists to prevent.
        self.__lock = threading.Lock()

    # --------------------------------------------------------------------------------------
    def _reserveRestart(self, containerId: str, now: float):
        """Claim this container's restart slot, or report why it is not available.

        Returns `(allowed, reason, previousAt)`. The slot is *reserved* (the timestamp is
        written before the restart is attempted) so the lock is never held across a Docker
        round trip; a caller that does not go through with the restart must hand
        `previousAt` back to `_releaseRestart`.
        """
        with self.__lock:
            previousAt = self.__lastRestart.get(containerId)

            if previousAt is not None:
                elapsed = now - previousAt
                if elapsed < RESTART_COOLDOWN_SECONDS:
                    remaining = int(RESTART_COOLDOWN_SECONDS - elapsed)
                    return (
                        False,
                        f"restart cooldown active, {remaining}s remaining",
                        previousAt,
                    )

            self.__lastRestart[containerId] = now
            return True, None, previousAt

    # --------------------------------------------------------------------------------------
    def _releaseRestart(self, containerId: str, previousAt: "float | None"):
        """Undo a reservation the caller did not use, restoring the prior state exactly.

        A failed restart, and a dry run, must both leave the container as eligible as it was
        before -- neither has earned a cooldown.
        """
        with self.__lock:
            if previousAt is None:
                self.__lastRestart.pop(containerId, None)
            else:
                self.__lastRestart[containerId] = previousAt

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
                if set(domains).isdisjoint(restartDomains):
                    continue

                allowed, reason, previousAt = self._reserveRestart(c.id, time.time())  # type: ignore
                if not allowed:
                    # INFO, not DEBUG: this is the answer to "why did my container not
                    # restart?", and the shipped image does not log at DEBUG. It is rare by
                    # construction -- at most once per container per cooldown window.
                    self.__logger.info(
                        f"Skipping restart of container {c.id}: {reason}"
                    )
                    continue

                self.__logger.info(f"Restarting container: {c.id}")
                if not self.__settings.dryRun:
                    try:
                        c.restart()  # type: ignore
                    except Exception:
                        self.__logger.exception(f"Failed restarting container: {c.id}")
                        self._releaseRestart(c.id, previousAt)  # type: ignore
                else:
                    self.__logger.info(f"[DRYRUN] restarting container: {c.id}")
                    self._releaseRestart(c.id, previousAt)  # type: ignore

        except Exception:
            self.__logger.exception("Failed restarting containers")
