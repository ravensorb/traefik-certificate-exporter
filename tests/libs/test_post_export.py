import json
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
