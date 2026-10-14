import apprise

from .logging_utils import (
    get_correlation_id,
    globalLogger,
    reset_correlation_id,
    set_correlation_id,
)


def send_export_notifications(
    urls: "list[str] | None",
    domains: list,
    dryRun: bool,
    correlationId: str | None = None,
) -> None:
    """Notify every configured Apprise destination that certificates changed.

    "A certificate changed", not "an export pass completed": both call sites call this
    only when at least one domain's exported artifacts changed on disk in the pass, and
    `domains` is exactly those domains. A pass that changed nothing -- an exporter restart
    over an unchanged store, a pass that only recovers a lost container restart -- sends
    nothing, so an operator can leave the channel unmuted. ADR-0045 records this; it
    amends ADR-0014 §7, which predates change detection.

    Fire-and-forget by contract (ADR-0014 §2): a delivery failure is logged and never
    propagates. An operator who needs something to *succeed* uses `postexportcommand`,
    which blocks and reports a non-zero exit.

    No overall `timeout=` is passed to `Apprise.notify()`. Apprise 2 notifies destinations
    in parallel and bounds each one itself -- `socket_connect_timeout` /
    `socket_read_timeout`, 4.0s each by default and settable per URL as `cto`/`rto`, with
    the SMTP plugin overriding connect to 15s, and a 60s per-destination cap over all of it.
    ADR-0014 §6 carries the arithmetic that follows from that.
    """
    logger = globalLogger

    if not urls:
        return

    # Same contract as the post-export hop: bind what the caller passed, fall back to
    # whatever is already in flight, and never fail the pass over a missing id.
    token = set_correlation_id(correlationId or get_correlation_id())
    try:
        _notify(logger, urls, domains, dryRun)
    finally:
        reset_correlation_id(token)


def _notify(logger, urls: list, domains: list, dryRun: bool) -> None:

    if dryRun:
        logger.info("Dry run: skipping export notifications")
        return

    client = apprise.Apprise()
    for url in urls:
        # Added one at a time so a malformed destination is named. `Apprise.add` accepts a
        # list and returns a single bool for the batch, which would report "something was
        # wrong" without saying which -- and the URL is a credential, so it cannot simply
        # be logged back.
        if not client.add(url):
            logger.error(
                "Apprise rejected a configured destination (index "
                f"{urls.index(url)}); it is not a recognised URL"
            )

    if not len(client):
        logger.error("No usable Apprise destinations; nothing was notified")
        return

    body = (
        "Exported certificates for: " + ", ".join(domains)
        if domains
        else "Export pass completed; no certificates were written."
    )

    try:
        # Falsy when ANY destination failed (an `AppriseResult` since apprise 2.0, which
        # keeps the old boolean contract), and Apprise logs the specifics itself.
        if not client.notify(title="Traefik certificate export", body=body):
            logger.error("One or more export notifications failed to deliver")
        else:
            logger.debug(f"Notified {len(client)} destination(s)")
    except Exception:
        # A delivery fault must never reach the caller: on the watch path this runs inside
        # the drain, whose per-path handler would log it as "Unhandled error processing
        # <file>" -- an export failure, which it is not.
        logger.exception("Export notification delivery raised")
