import apprise

from .logging_utils import globalLogger


def send_export_notifications(
    urls: "list[str] | None", domains: list, dryRun: bool
) -> None:
    """Notify every configured Apprise destination that an export pass completed.

    Deliberately "an export pass completed" and not "a certificate changed": nothing in
    this project detects change -- every certificate is rewritten on every pass -- and the
    image ships `RUNATSTART=true`, so a container restart is a pass. ADR-0014 §7 records
    that, and the documentation states it, because an operator who believes otherwise will
    mute the channel the first time a redeploy notifies.

    Fire-and-forget by contract (ADR-0014 §2): a delivery failure is logged and never
    propagates. An operator who needs something to *succeed* uses `postexportcommand`,
    which blocks and reports a non-zero exit.

    No timeout is passed here because `Apprise.notify()` accepts none. Delivery is bounded
    per destination by Apprise itself -- `socket_connect_timeout` / `socket_read_timeout`,
    4.0s each by default and settable per URL as `cto`/`rto`, with the SMTP plugin
    overriding connect to 15s. ADR-0014 §6 carries the arithmetic that follows from that.
    """
    logger = globalLogger

    if not urls:
        return

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
        # Returns False when ANY destination failed, and logs the specifics itself.
        if not client.notify(title="Traefik certificate export", body=body):
            logger.error("One or more export notifications failed to deliver")
        else:
            logger.debug(f"Notified {len(client)} destination(s)")
    except Exception:
        # A delivery fault must never reach the caller: on the watch path this runs inside
        # the drain, whose per-path handler would log it as "Unhandled error processing
        # <file>" -- an export failure, which it is not.
        logger.exception("Export notification delivery raised")
