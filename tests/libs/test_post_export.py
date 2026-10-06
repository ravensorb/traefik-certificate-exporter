import json
import logging
import sys
from unittest.mock import patch

from traefik_certificate_exporter.libs import post_export
from traefik_certificate_exporter.libs.post_export import run_post_export_command


def test_no_command_configured_is_a_noop():
    with patch("subprocess.run") as mock_run:
        run_post_export_command(None, ["example.com"], dryRun=False)

    mock_run.assert_not_called()


def test_dry_run_skips_execution_even_with_a_command_configured():
    with patch("subprocess.run") as mock_run:
        run_post_export_command("/bin/true", ["example.com"], dryRun=True)

    mock_run.assert_not_called()


def test_successful_command_receives_comma_separated_domains_env_var(tmp_path):
    output_file = tmp_path / "hook-output.json"
    script = tmp_path / "hook.py"
    script.write_text(
        "import json, os, sys\n"
        f"with open({str(output_file)!r}, 'w') as f:\n"
        "    json.dump({'env': os.environ.get("
        "'TRAEFIK_CERTIFICATE_EXPORTER_EXPORTED_DOMAINS')}, f)\n"
    )

    run_post_export_command(
        f"{sys.executable} {script}", ["foo.com", "bar.com"], dryRun=False
    )

    result = json.loads(output_file.read_text())
    assert result["env"] == "foo.com,bar.com"


def test_no_domains_processed_yields_empty_env_var(tmp_path):
    output_file = tmp_path / "hook-output.json"
    script = tmp_path / "hook.py"
    script.write_text(
        "import json, os\n"
        f"with open({str(output_file)!r}, 'w') as f:\n"
        "    json.dump({'env': os.environ.get("
        "'TRAEFIK_CERTIFICATE_EXPORTER_EXPORTED_DOMAINS')}, f)\n"
    )

    run_post_export_command(f"{sys.executable} {script}", [], dryRun=False)

    result = json.loads(output_file.read_text())
    assert result["env"] == ""


def test_non_zero_exit_is_logged_but_does_not_raise(caplog):
    run_post_export_command(
        f'{sys.executable} -c "import sys; sys.exit(3)"', ["example.com"], dryRun=False
    )

    assert any("exited 3" in message for message in caplog.messages)


def test_timeout_is_logged_but_does_not_raise(monkeypatch, caplog):
    monkeypatch.setattr(post_export, "POST_EXPORT_COMMAND_TIMEOUT_SECONDS", 0.2)

    run_post_export_command(
        f'{sys.executable} -c "import time; time.sleep(5)"',
        ["example.com"],
        dryRun=False,
    )

    assert any("timed out" in message for message in caplog.messages)


def test_unparseable_command_is_logged_but_does_not_raise(caplog):
    run_post_export_command('unterminated "quote', ["example.com"], dryRun=False)

    assert any("could not be parsed" in message for message in caplog.messages)


def test_the_hook_receives_the_correlation_id_of_the_pass_that_ran_it(tmp_path):
    """A hook that logs somewhere else can still be joined back to this export pass."""
    output_file = tmp_path / "hook-correlation.json"
    script = tmp_path / "hook.py"
    script.write_text(
        "import json, os\n"
        f"with open({str(output_file)!r}, 'w') as f:\n"
        "    json.dump({'id': os.environ.get("
        "'TRAEFIK_CERTIFICATE_EXPORTER_CORRELATION_ID')}, f)\n"
    )

    run_post_export_command(
        f"{sys.executable} {script}",
        ["foo.com"],
        dryRun=False,
        correlationId="pass-1234",
    )

    assert json.loads(output_file.read_text())["id"] == "pass-1234"


def test_post_export_log_lines_carry_the_passed_correlation_id(caplog):
    with caplog.at_level(logging.INFO):
        run_post_export_command(
            "/bin/true", ["foo.com"], dryRun=True, correlationId="pass-5678"
        )

    assert [r.correlation_id for r in caplog.records] == ["pass-5678"]


def test_post_export_without_an_id_logs_rather_than_failing(caplog):
    """A missing correlation id must never take down the pass it exists to observe."""
    with caplog.at_level(logging.INFO):
        run_post_export_command("/bin/true", ["foo.com"], dryRun=True)

    assert caplog.records
    assert all(getattr(r, "correlation_id", None) for r in caplog.records)
