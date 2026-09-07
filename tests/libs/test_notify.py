"""Export notifications: delivery, isolation, dry run, and what they claim to mean."""

from unittest.mock import MagicMock, patch

from traefik_certificate_exporter.libs.notify import send_export_notifications


def test_no_destinations_configured_is_a_noop():
    with patch("apprise.Apprise") as client:
        send_export_notifications(None, ["example.com"], dryRun=False)
        send_export_notifications([], ["example.com"], dryRun=False)
    client.assert_not_called()


def test_dry_run_sends_nothing():
    """Consistent with dry run suppressing file writes, container restarts and the
    post-export command. An operator validating a new config must not page a channel."""
    with patch("apprise.Apprise") as client:
        send_export_notifications(["json://localhost/"], ["example.com"], dryRun=True)
    client.assert_not_called()


def test_every_destination_is_notified_with_the_domain_list():
    instance = MagicMock()
    instance.add.return_value = True
    instance.__len__.return_value = 2
    instance.notify.return_value = True

    with patch("apprise.Apprise", return_value=instance):
        send_export_notifications(
            ["json://a/", "json://b/"], ["one.com", "two.com"], dryRun=False
        )

    assert [c.args[0] for c in instance.add.call_args_list] == [
        "json://a/",
        "json://b/",
    ]
    body = instance.notify.call_args.kwargs["body"]
    assert "one.com" in body and "two.com" in body


def test_a_pass_that_exported_nothing_still_says_so_rather_than_sending_an_empty_list():
    instance = MagicMock()
    instance.add.return_value = True
    instance.__len__.return_value = 1
    instance.notify.return_value = True

    with patch("apprise.Apprise", return_value=instance):
        send_export_notifications(["json://a/"], [], dryRun=False)

    assert "no certificates were written" in instance.notify.call_args.kwargs["body"]


def test_a_delivery_failure_is_logged_and_never_propagates(caplog):
    """Fire-and-forget by contract. On the watch path this runs inside the drain, whose
    per-path handler would otherwise log a delivery fault as an EXPORT failure."""
    instance = MagicMock()
    instance.add.return_value = True
    instance.__len__.return_value = 1
    instance.notify.side_effect = RuntimeError("smtp exploded")

    with patch("apprise.Apprise", return_value=instance):
        send_export_notifications(["json://a/"], ["example.com"], dryRun=False)

    assert "Export notification delivery raised" in caplog.text
    assert "Unhandled error processing" not in caplog.text


def test_a_failed_delivery_is_reported_without_raising(caplog):
    instance = MagicMock()
    instance.add.return_value = True
    instance.__len__.return_value = 1
    instance.notify.return_value = False

    with patch("apprise.Apprise", return_value=instance):
        send_export_notifications(["json://a/"], ["example.com"], dryRun=False)

    assert "failed to deliver" in caplog.text


def test_a_rejected_destination_is_named_by_position_never_echoed(caplog):
    """The URL is the credential, so a malformed one cannot simply be logged back."""
    instance = MagicMock()
    instance.add.return_value = False
    instance.__len__.return_value = 0

    with patch("apprise.Apprise", return_value=instance):
        send_export_notifications(["tgram://SECRETTOKEN/1"], ["a.com"], dryRun=False)

    assert "SECRETTOKEN" not in caplog.text
    assert "index 0" in caplog.text
    assert "nothing was notified" in caplog.text
