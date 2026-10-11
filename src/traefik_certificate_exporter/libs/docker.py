import datetime
import os
import threading
import time
from collections.abc import Callable
from typing import NamedTuple

# Submodule imports bind `docker` too; they are explicit because both are used below.
import docker.constants
import docker.errors
from dateutil.parser import isoparse

from .logging_utils import (
    get_correlation_id,
    globalLogger,
    reset_correlation_id,
    set_correlation_id,
)
from .settings import Settings

# `artifactMtime(domain)`: the newest exported-artifact mtime for a domain (epoch seconds),
# or None when none is on disk. `AcmeCertificateExporter.artifactMtime` is the production one.
ArtifactMtime = Callable[[str], "float | None"]

###########################################################################################################

DOCKER_LABEL = "com.github.ravensorb.traefik-certificate-exporter.domain-restart"

# Restart only on change (ADR-0045). Change detection happens at export time, by comparing
# the built artifacts with the files already on disk: unchanged files are not rewritten, so
# their mtimes stay put (E014-S01-002, ADR-0043). The restart trigger is therefore "exported
# files newer than the container's start": a labeled container is restarted when the newest
# mtime among its labeled domains' artifacts is later than its `State.StartedAt` (plus the
# slack below). The files and `StartedAt` are the only restart state -- nothing is persisted
# -- and both survive a crash, so a restart lost to a crash, a failure or a shutdown is
# recovered on the next pass by the same rule.
#
# The cooldown is the rate floor on top of that trigger. The domain names that reach this
# module come from Traefik's ACME store, which an operator does not fully control; without a
# floor a noisy or hostile store could drive restarts of every labeled container over the
# host-root-equivalent Docker socket (BL-E011-016 / RT-009). A restart the floor denies is
# deferred, not dropped: one trailing restart per container is scheduled for the end of the
# window, and later requests inside the window coalesce into it.
#
# Five minutes is far longer than any legitimate renewal cadence (days) and short enough that
# an operator does not perceive the delayed restart. Fixed here, not configurable.
RESTART_COOLDOWN_SECONDS = 300

# A restart that fails (Engine unreachable, daemon restarting, an APIError) is retried
# through the deferred-restart path, one cooldown window later, at most this many times
# (ADV-1). Without it, watch mode would not retry until the ACME store next changes, which
# can be weeks. Each retry re-checks everything a deferred restart does. Fixed here.
RESTART_RETRY_LIMIT = 3

# A file must be more than this many seconds newer than the container's start to trigger a
# restart. In the supported setup (local daemon, output directory on a local filesystem) the
# mtime and `StartedAt` come from the same clock; the slack absorbs small drift where the
# output sits on a network filesystem whose server stamps the mtime, which would otherwise
# restart a container a second time on the pass after every rotation. Accepted cost: a
# container started less than this long before the write is not restarted. Larger skew is
# unsupported. Fixed here, not configurable.
RESTART_MTIME_SLACK_SECONDS = 2

# The failures an operator can cause and fix: a missing or unreadable socket, an unreachable
# `DOCKER_HOST`, an Engine older than the SDK's API floor, an Engine-side refusal. They are
# reported as one ERROR line naming the endpoint, without a traceback. `OSError` covers the
# transport layer: `requests.RequestException` subclasses `IOError` (= `OSError`), so
# connection errors are caught here without this module importing `requests`, which is not a
# declared dependency of its own (E014-S01-007). Anything else is a defect and keeps its
# traceback.
EXPECTED_ENGINE_ERRORS = (docker.errors.DockerException, OSError)

# What docker-py connects to when `DOCKER_HOST` is unset, spelled the way an operator would
# write it in `DOCKER_HOST` (the SDK's constant carries its internal `http+` adapter prefix).
DEFAULT_DOCKER_ENDPOINT = docker.constants.DEFAULT_UNIX_SOCKET.removeprefix("http+")


def _labeledDomains(container) -> "set[str]":
    """The domains a container's restart label names."""
    raw = (getattr(container, "labels", None) or {}).get(DOCKER_LABEL) or ""
    return {d.strip() for d in str(raw).split(",") if d.strip()}


def _utc(epoch: "float | None") -> str:
    if epoch is None:
        return "unknown"
    return datetime.datetime.fromtimestamp(epoch, tz=datetime.timezone.utc).isoformat()


class _Verdict(NamedTuple):
    """The restart rule evaluated for one container."""

    restart: bool
    domain: "str | None"  # the labeled domain with the newest artifact
    mtime: "float | None"  # that artifact's mtime
    startedAt: "float | None"


class _Pending(NamedTuple):
    """One armed deferred restart."""

    timer: threading.Timer
    domains: "set[str]"  # union of the labeled domains that requested it
    artifactMtime: ArtifactMtime
    generation: int  # `cancel()` generation it was armed in
    retries: int = 0  # how many failed-restart retries this one is (ADV-1)


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
        # container id -> its one pending trailing restart (guarded by `__lock`). At most
        # one per container, so memory is bounded by labeled containers, not store events.
        self.__pending: dict[str, _Pending] = {}
        # Bumped by `cancel()`. A deferred restart already past its pending check when
        # `cancel()` runs sees the change and does not restart.
        self.__generation = 0

    # --------------------------------------------------------------------------------------
    def _create_client(self) -> docker.DockerClient:
        """The single place a Docker client is built.

        `use_context=False`: since docker-py 7.2, `from_env` falls back to the active
        Docker CLI context when `DOCKER_HOST` is unset. The socket is host-root-equivalent,
        so a `~/.docker` planted in the service's HOME must not be able to redirect restarts
        to a different daemon. `DOCKER_HOST` is still honoured; otherwise the default socket.
        """
        return docker.from_env(use_context=False)

    # --------------------------------------------------------------------------------------
    @staticmethod
    def _endpoint() -> str:
        """The endpoint `_create_client()` targets, for log lines -- not a secret."""
        return os.environ.get("DOCKER_HOST") or DEFAULT_DOCKER_ENDPOINT

    # --------------------------------------------------------------------------------------
    def check(self) -> bool:
        """Ping the Engine once and log the outcome. Never raises.

        Run at start-up when restarts are enabled, so an unreachable socket is one ERROR an
        operator sees immediately rather than a failure discovered at the first renewal.
        """
        client = None
        try:
            client = self._create_client()
            client.ping()
            apiVersion = client.version().get("ApiVersion", "unknown")
            self.__logger.info(f"Docker Engine reachable (API {apiVersion})")
            return True
        except EXPECTED_ENGINE_ERRORS as e:
            self.__logger.error(
                f"Docker Engine check against {self._endpoint()} failed; labeled "
                f"containers will not be restarted until it succeeds: {e}"
            )
        except Exception:
            self.__logger.exception(
                f"Docker Engine reachability check failed for {self._endpoint()}"
            )
        finally:
            if client is not None:
                client.close()
        return False

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
    @staticmethod
    def _startedAt(container) -> "float | None":
        """`State.StartedAt` as UTC epoch seconds, or None when missing, empty,
        unparsable, or the zero value of a container that never started.

        Docker writes RFC 3339 with nanoseconds and a `Z`; `isoparse` truncates the
        fraction to microseconds (python-dateutil, ADR-0045).
        """
        try:
            raw = container.attrs["State"]["StartedAt"]
        except (AttributeError, KeyError, TypeError):
            return None
        if not isinstance(raw, str) or not raw:
            return None
        try:
            parsed = isoparse(raw)
        except (ValueError, OverflowError):
            return None
        if parsed.year <= 1:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=datetime.timezone.utc)
        try:
            return parsed.astimezone(datetime.timezone.utc).timestamp()
        except (ValueError, OverflowError, OSError):
            return None

    # --------------------------------------------------------------------------------------
    def _verdict(self, container, artifactMtime: ArtifactMtime) -> "_Verdict | None":
        """The restart rule for one container, or None when it is not a candidate (no
        labeled domain has an artifact on disk)."""
        newestDomain = None
        newest: float | None = None
        for domain in sorted(_labeledDomains(container)):
            mtime = artifactMtime(domain)
            if mtime is not None and (newest is None or mtime > newest):
                newestDomain, newest = domain, mtime
        if newest is None:
            return None

        startedAt = self._startedAt(container)
        if startedAt is None:
            raw = None
            try:
                raw = container.attrs["State"].get("StartedAt")
            except (AttributeError, KeyError, TypeError):
                pass
            self.__logger.debug(
                f"Container {container.id}: StartedAt missing or unparsable ({raw!r}); "
                "not restarting"
            )
            return _Verdict(False, newestDomain, newest, None)

        if newest > startedAt + RESTART_MTIME_SLACK_SECONDS:
            return _Verdict(True, newestDomain, newest, startedAt)

        self.__logger.debug(
            f"Container {container.id}: newest artifact {_utc(newest)}, started "
            f"{_utc(startedAt)}; no restart needed"
        )
        return _Verdict(False, newestDomain, newest, startedAt)

    # --------------------------------------------------------------------------------------
    def _needsRestart(self, container, artifactMtime: ArtifactMtime) -> bool:
        """The rule: the newest artifact of the container's labeled domains is more than
        `RESTART_MTIME_SLACK_SECONDS` later than its `State.StartedAt` (ADR-0045)."""
        verdict = self._verdict(container, artifactMtime)
        return verdict is not None and verdict.restart

    # --------------------------------------------------------------------------------------
    def restartLabeledContainers(self, artifactMtime: ArtifactMtime) -> None:
        """Evaluate the restart rule for every running labeled container.

        Called on every pass, after its writes, whether or not anything changed: the rule
        reads the files and each container's start, so a pass that changed nothing still
        recovers a restart lost earlier. A restart the cooldown denies is deferred.
        """
        if not self.__settings.restartContainers:
            return

        correlationId = get_correlation_id()
        client = None
        try:
            client = self._create_client()
            # Running containers only. `ignore_removed`: `list` fetches each container
            # after listing it, and one removed in between would otherwise abort the pass.
            containers = client.containers.list(
                filters={"label": DOCKER_LABEL}, ignore_removed=True
            )
            for c in containers:
                verdict = self._verdict(c, artifactMtime)
                if verdict is None or not verdict.restart:
                    continue

                now = time.time()
                allowed, _reason, previousAt = self._reserveRestart(c.id, now)  # type: ignore
                if not allowed:
                    remaining = max(
                        0.0, (previousAt or now) + RESTART_COOLDOWN_SECONDS - now
                    )
                    if self.__settings.dryRun:
                        self.__logger.info(
                            f"[DRYRUN] would schedule deferred restart of {c.id} in "
                            f"{int(remaining) + 1}s"
                        )
                        continue
                    self._scheduleDeferredRestart(
                        c.id,  # type: ignore
                        _labeledDomains(c),
                        remaining,
                        correlationId,
                        artifactMtime,
                    )
                    continue

                if self.__settings.dryRun:
                    self.__logger.info(f"[DRYRUN] would restart {c.id}")
                    self._releaseRestart(c.id, previousAt)  # type: ignore
                    continue

                self.__logger.info(
                    f"Restarting container {c.id}: exported files for {verdict.domain} "
                    f"({_utc(verdict.mtime)}) are newer than its start "
                    f"({_utc(verdict.startedAt)})"
                )
                self.__restart(c, previousAt, _labeledDomains(c), artifactMtime)

        except EXPECTED_ENGINE_ERRORS as e:
            self.__logger.error(
                f"Failed restarting containers: Docker Engine request to "
                f"{self._endpoint()} failed: {e}"
            )
        except Exception:
            self.__logger.exception("Failed restarting containers")
        finally:
            if client is not None:
                client.close()

    # --------------------------------------------------------------------------------------
    def __restart(
        self,
        container,
        previousAt: "float | None",
        domains: "set[str]",
        artifactMtime: ArtifactMtime,
        retries: int = 0,
    ) -> None:
        """Restart one container whose slot is reserved; release the slot on failure,
        because a restart that did not happen has not earned a cooldown, and arm a bounded
        retry (ADV-1)."""
        try:
            container.restart()
        except docker.errors.NotFound:
            # Removed between lookup and restart: nothing left to restart.
            self.__logger.info(
                f"Skipping restart of container {container.id}: container gone"
            )
            self._releaseRestart(container.id, previousAt)
        except EXPECTED_ENGINE_ERRORS as e:
            self.__logger.error(
                f"Failed restarting container {container.id} via Docker Engine at "
                f"{self._endpoint()}: {e}"
            )
            self._releaseRestart(container.id, previousAt)
            self._armRetry(container.id, domains, artifactMtime, retries)
        except Exception:
            self.__logger.exception(f"Failed restarting container: {container.id}")
            self._releaseRestart(container.id, previousAt)
            self._armRetry(container.id, domains, artifactMtime, retries)

    # --------------------------------------------------------------------------------------
    def _armRetry(
        self,
        containerId: str,
        domains: "set[str]",
        artifactMtime: ArtifactMtime,
        retries: int,
    ) -> None:
        """After a failed restart, schedule another attempt through the deferred path, a
        full cooldown window later, unless `RESTART_RETRY_LIMIT` is spent (ADV-1)."""
        if retries >= RESTART_RETRY_LIMIT:
            self.__logger.warning(
                f"Giving up retrying restart of container {containerId} after "
                f"{retries} retries; the next pass restarts it if its files are still "
                "newer than its start"
            )
            return
        self._scheduleDeferredRestart(
            containerId,
            domains,
            RESTART_COOLDOWN_SECONDS,
            get_correlation_id(),
            artifactMtime,
            retries=retries + 1,
        )

    # --------------------------------------------------------------------------------------
    def _scheduleDeferredRestart(
        self,
        containerId: str,
        domains: "set[str]",
        remaining: float,
        correlationId: "str | None",
        artifactMtime: ArtifactMtime,
        retries: int = 0,
    ) -> bool:
        """Arm one trailing restart for the end of the cooldown window.

        Returns True if a timer was armed, False if one was already pending -- then the
        request is coalesced into it and its domains are added to the pending set.
        `retries` > 0 marks a retry of a failed restart (ADV-1).
        """
        with self.__lock:
            pending = self.__pending.get(containerId)
            if pending is not None:
                pending.domains.update(domains)
                self.__logger.debug(
                    f"Restart of container {containerId} already scheduled"
                )
                return False
            # Daemon, like the drain timer (ADR-0026): a pending restart must not keep the
            # interpreter alive at shutdown. `contextvars` do not reach a manually started
            # thread, so the arming pass's correlation id is handed over explicitly.
            timer = threading.Timer(
                remaining + 1,
                self._deferredRestart,
                args=(containerId, correlationId),
            )
            timer.daemon = True
            self.__pending[containerId] = _Pending(
                timer, set(domains), artifactMtime, self.__generation, retries
            )
            timer.start()
        if retries:
            self.__logger.info(
                f"Retrying restart of container {containerId} in {int(remaining) + 1}s "
                f"(retry {retries} of {RESTART_RETRY_LIMIT})"
            )
        else:
            self.__logger.info(
                f"Deferring restart of container {containerId}: cooldown active, "
                f"{int(remaining) + 1}s remaining; one restart scheduled"
            )
        return True

    # --------------------------------------------------------------------------------------
    def _deferredRestart(self, containerId: str, correlationId: "str | None") -> None:
        """Timer target: re-check, then restart. Never raises into the timer thread.

        The pending entry is popped under the lock, and the Docker work runs outside it.
        A popped-then-cancelled entry, a container that is gone or no longer running, a
        label that no longer names a requesting domain, or a container that started after
        the files were written are all skipped -- never restarted on stale authority.
        """
        with self.__lock:
            pending = self.__pending.pop(containerId, None)
        if pending is None:
            # Cancelled, or already handled.
            return

        token = set_correlation_id(correlationId)
        client = None
        try:
            client = self._create_client()
            try:
                container = client.containers.get(containerId)
            except docker.errors.NotFound:
                self.__logger.info(
                    f"Skipping deferred restart of container {containerId}: gone"
                )
                return

            # Docker's restart endpoint starts a stopped container; one the operator
            # stopped inside the window stays stopped (ADR-0045 §2, §8; SD-01-2).
            if getattr(container, "status", None) != "running":
                self.__logger.info(
                    f"Skipping deferred restart of container {containerId}: not running"
                )
                return

            if _labeledDomains(container).isdisjoint(pending.domains):
                self.__logger.info(
                    f"Skipping deferred restart of container {containerId}: label no "
                    "longer matches"
                )
                return

            if not self._needsRestart(container, pending.artifactMtime):
                self.__logger.info(
                    f"Skipping deferred restart of container {containerId}: already "
                    "started after the certificate was written"
                )
                return

            with self.__lock:
                if self.__generation != pending.generation:
                    # `cancel()` ran while this was re-checking: shutdown wins, and the
                    # next pass recovers the restart by the same rule.
                    return
                previousAt = self.__lastRestart.get(containerId)
                now = time.time()
                floored = (
                    previousAt is not None
                    and now - previousAt < RESTART_COOLDOWN_SECONDS
                )
                if not floored:
                    # The trailing restart starts a new window, so a further request
                    # inside it is deferred again: the floor holds across deferrals.
                    self.__lastRestart[containerId] = now

            if floored:
                # Another pass claimed the slot after this was armed (its restart may
                # still be in flight, so `StartedAt` has not moved yet). The floor wins;
                # if that restart fails, its release lets the next pass recover this one.
                self.__logger.info(
                    f"Skipping deferred restart of container {containerId}: restarted "
                    "within the window"
                )
                return

            self.__logger.info(f"Restarting container: {containerId} (deferred)")
            self.__restart(
                container,
                previousAt,
                pending.domains,
                pending.artifactMtime,
                pending.retries,
            )
        except EXPECTED_ENGINE_ERRORS as e:
            self.__logger.error(
                f"Deferred restart of container {containerId} failed: Docker Engine "
                f"request to {self._endpoint()} failed: {e}"
            )
            self._armRetry(
                containerId, pending.domains, pending.artifactMtime, pending.retries
            )
        except Exception:
            self.__logger.exception(
                f"Deferred restart of container {containerId} failed"
            )
            self._armRetry(
                containerId, pending.domains, pending.artifactMtime, pending.retries
            )
        finally:
            if client is not None:
                client.close()
            reset_correlation_id(token)

    # --------------------------------------------------------------------------------------
    def cancel(self) -> None:
        """Cancel every pending deferred restart. Idempotent; safe before any exists.

        Called on every exit path of `app._run`. Nothing is saved: the cancelled
        containers' files are still newer than their start, so the next pass restarts
        them by the same rule.
        """
        with self.__lock:
            pending = list(self.__pending.values())
            self.__pending.clear()
            self.__generation += 1
        for entry in pending:
            entry.timer.cancel()
        message = (
            f"Cancelled {len(pending)} pending deferred restart(s); the next pass "
            "restarts them"
        )
        if pending:
            self.__logger.info(message)
        else:
            self.__logger.debug(message)
