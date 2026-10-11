import json
import logging
import shlex
import subprocess
import sys
from unittest.mock import patch

import pytest

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


# ---------------------------------------------------------------------------
# E014-S01-010 (review-product m4): `postexportcommand` often carries a credential, so a
# hook log line names only the program, `argv[0]` -- never the arguments or the command.
# ---------------------------------------------------------------------------

_CREDENTIAL_COMMAND = 'curl -H "Authorization: Bearer s3cr3t" https://x.example.test'


def _assert_credential_not_logged(caplog):
    assert caplog.records, "the hook logged nothing at all"
    for record in caplog.records:
        message = record.getMessage()
        assert "s3cr3t" not in message, message
        assert "Authorization" not in message, message


def test_nonzero_exit_log_names_only_the_program(caplog):
    failed = subprocess.CompletedProcess(["curl"], 7, stdout="", stderr="refused")
    with (
        caplog.at_level(logging.DEBUG),
        patch.object(post_export.subprocess, "run", return_value=failed),
    ):
        run_post_export_command(_CREDENTIAL_COMMAND, ["example.com"], dryRun=False)

    _assert_credential_not_logged(caplog)
    assert any(
        "Post-export command curl exited 7: refused" in m for m in caplog.messages
    ), caplog.messages


def test_timeout_log_names_only_the_program(caplog):
    timeout = subprocess.TimeoutExpired(cmd=["curl"], timeout=30)
    with (
        caplog.at_level(logging.DEBUG),
        patch.object(post_export.subprocess, "run", side_effect=timeout),
    ):
        run_post_export_command(_CREDENTIAL_COMMAND, ["example.com"], dryRun=False)

    _assert_credential_not_logged(caplog)
    assert any(
        m.startswith("Post-export command curl timed out") for m in caplog.messages
    ), caplog.messages


def test_start_failure_log_names_only_the_program(caplog):
    missing = FileNotFoundError(2, "No such file or directory", "curl")
    with (
        caplog.at_level(logging.DEBUG),
        patch.object(post_export.subprocess, "run", side_effect=missing),
    ):
        run_post_export_command(_CREDENTIAL_COMMAND, ["example.com"], dryRun=False)

    _assert_credential_not_logged(caplog)
    assert any(
        m.startswith("Post-export command curl failed to start")
        for m in caplog.messages
    ), caplog.messages


def test_unparsable_command_log_names_neither_command_nor_parser_message(caplog):
    """`shlex`'s message can echo a fragment of the command, so it is not logged either."""
    unterminated = 'curl -H "Authorization: Bearer s3cr3t https://x.example.test'
    with pytest.raises(ValueError) as parserError:
        shlex.split(unterminated)

    with caplog.at_level(logging.DEBUG):
        run_post_export_command(unterminated, ["example.com"], dryRun=False)

    _assert_credential_not_logged(caplog)
    for message in caplog.messages:
        assert "curl" not in message, message
        assert str(parserError.value) not in message, message
    assert any("could not be parsed" in m for m in caplog.messages), caplog.messages


def test_post_export_without_an_id_logs_rather_than_failing(caplog):
    """A missing correlation id must never take down the pass it exists to observe."""
    with caplog.at_level(logging.INFO):
        run_post_export_command("/bin/true", ["foo.com"], dryRun=True)

    assert caplog.records
    assert all(getattr(r, "correlation_id", None) for r in caplog.records)


# ---------------------------------------------------------------------------
# ADV-3: a failing hook's stderr is untrusted and may echo the hook's own (secret)
# arguments. Only its last line is logged: arguments masked, control characters
# stripped, truncated.
# ---------------------------------------------------------------------------


def test_failing_hook_stderr_is_masked_sanitized_and_reduced_to_its_last_line(caplog):
    script = (
        "import sys; "
        "sys.stderr.write('earlier line ' + sys.argv[1] + '\\n'); "
        "sys.stderr.write('curl: (6) Could not resolve ' + sys.argv[1] + "
        "' \\x1b[31mFORGED\\r\\n'); "
        "sys.exit(6)"
    )
    command = shlex.join([sys.executable, "-c", script, "https://h.test/?token=s3cr3t"])

    with caplog.at_level(logging.DEBUG):
        run_post_export_command(command, ["example.com"], dryRun=False)

    errors = [r.getMessage() for r in caplog.records if r.levelno == logging.ERROR]
    assert len(errors) == 1, caplog.messages
    message = errors[0]
    assert "s3cr3t" not in message
    assert "earlier line" not in message
    assert "\x1b" not in message and "\r" not in message and "\n" not in message
    assert "Could not resolve ***" in message
    assert "exited 6" in message


def test_failing_hook_stderr_last_line_is_truncated(caplog):
    failed = subprocess.CompletedProcess(["hook"], 1, stdout="", stderr="x" * 5000)
    with (
        caplog.at_level(logging.DEBUG),
        patch.object(post_export.subprocess, "run", return_value=failed),
    ):
        run_post_export_command("hook --flag", ["example.com"], dryRun=False)

    (message,) = [r.getMessage() for r in caplog.records if r.levelno == logging.ERROR]
    assert len(message) < 400
    assert "x" * post_export.HOOK_STDERR_LOG_LIMIT in message
    assert "x" * (post_export.HOOK_STDERR_LOG_LIMIT + 1) not in message
