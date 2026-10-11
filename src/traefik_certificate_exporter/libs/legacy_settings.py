"""Start-up detection of legacy and misspelled setting names (FR-16, product AD-6).

Policy: a legacy name is warned about and ignored. There are no aliases -- the names in
`LEGACY_SETTING_NAMES` never worked, so nobody depends on them, and an alias would be a
compatibility contract (it would need an ADR). The warnings carry the name only, never the
value: `..._NOTIFY_*` held Apprise URLs with embedded tokens.

tce-settings-scan: legacy-names-listed
This marker lets this file quote legacy names. `tests/test_settings_surface.py` keeps it
honest: the src env-literal scan skips marked files, and a marked file must quote at least
one `LEGACY_SETTING_NAMES` name.
"""

import functools
import logging
import os
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import importlib_resources
import yaml

# The module, not the function: both suggestion paths (this one and the strict CLI parse)
# resolve `suggest.nearest_name` at call time, so they share one definition (C-04).
from . import suggest
from .logging_utils import (
    LOG_LEVEL_ENV,
    LOGGING_CFGFILE_ENV,
    LOGGING_CONSOLEJSON_ENV,
    LOGGING_CONSOLEONLY_ENV,
    sanitize_for_log,
)
from .post_export import CORRELATION_ID_ENV, EXPORTED_DOMAINS_ENV

ENV_PREFIX = "TRAEFIK_CERTIFICATE_EXPORTER_"

# The env names the source reads (or sets) directly instead of through confuse.
# `tests/test_settings_surface.py::test_runtime_valid_env_names_equal_source_scan` asserts
# that `valid_env_names()` equals the registry-derived names plus a scan of every env-name
# literal in `src`, so a new `os.getenv` literal without a constant here fails the gate.
# They are matched exactly: `os.getenv` is case-sensitive, unlike confuse.
#
# The hook-output names are set by the exporter for the post-export command and never read
# by it. They stay valid (documented for hook authors) but are never offered as a "did you
# mean" target, or `..._DOMAINS` would be steered to `..._EXPORTED_DOMAINS`, another name
# that does nothing for the exporter.
HOOK_OUTPUT_ENV_NAMES: frozenset[str] = frozenset(
    {EXPORTED_DOMAINS_ENV, CORRELATION_ID_ENV}
)
SOURCE_ENV_NAMES: frozenset[str] = (
    frozenset(
        {
            LOG_LEVEL_ENV,
            LOGGING_CFGFILE_ENV,
            LOGGING_CONSOLEJSON_ENV,
            LOGGING_CONSOLEONLY_ENV,
        }
    )
    | HOOK_OUTPUT_ENV_NAMES
)

USAGE_POINTER = 'see the "## Usage" section of README.md for the valid names'


@dataclass(frozen=True)
class LegacyName:
    """One name that the docs or samples once used and that maps to no setting."""

    source: Literal["env", "config"]
    # A trailing `*` means prefix match.
    name: str
    replacement: str | None
    # The fix in words, used when `replacement` is None.
    hint: str = ""


_NO_CONFIG_FILE_ENV = (
    "the container always reads /config/config.yaml; outside the container pass "
    "-c/--config-file on the command line"
)

# The single legacy -> replacement table, written as full literals so the file quotes the
# names it lists (the stale-marker check reads them). Derived from the names the docs and samples
# historically used (`git log -p HEAD` over the documentation scan scope);
# `test_legacy_map_covers_documented_names` fails if a documented name is missing.
LEGACY_SETTING_NAMES: tuple[LegacyName, ...] = (
    LegacyName(
        "env", "TRAEFIK_CERTIFICATE_EXPORTER_CONFIG_FILE", None, _NO_CONFIG_FILE_ENV
    ),
    LegacyName(
        "env", "TRAEFIK_CERTIFICATE_EXPORTER_CONFIGFILE", None, _NO_CONFIG_FILE_ENV
    ),
    LegacyName(
        "env",
        "TRAEFIK_CERTIFICATE_EXPORTER_FILESPEC",
        "TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_FILESPEC",
    ),
    LegacyName(
        "env",
        "TRAEFIK_CERTIFICATE_EXPORTER_RESOLVERID",
        "TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_TRAEFIKRESOLVERID",
    ),
    LegacyName(
        "env",
        "TRAEFIK_CERTIFICATE_EXPORTER_RESOLVERID_INOUTPUTPATHNAME",
        "TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_RESOLVERINPATHNAME",
    ),
    LegacyName(
        "env",
        "TRAEFIK_CERTIFICATE_EXPORTER_DRYRUN",
        "TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_DRYRUN",
    ),
    LegacyName(
        "env",
        "TRAEFIK_CERTIFICATE_EXPORTER_FLAT",
        "TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_FLAT",
    ),
    LegacyName(
        "env",
        "TRAEFIK_CERTIFICATE_EXPORTER_RESTART_CONTAINERS",
        "TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_RESTARTCONTAINERS",
    ),
    LegacyName(
        "env",
        "TRAEFIK_CERTIFICATE_EXPORTER_INCLUDE_DOMAINS",
        "TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_DOMAINS_INCLUDE",
    ),
    LegacyName(
        "env",
        "TRAEFIK_CERTIFICATE_EXPORTER_EXCLUDE_DOMAINS",
        "TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_DOMAINS_EXCLUDE",
    ),
    LegacyName(
        "env",
        "TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_RESTARTCONTAINER",
        "TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_RESTARTCONTAINERS",
    ),
    LegacyName(
        "env",
        "TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS.RESTARTCONTAINER",
        "TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_RESTARTCONTAINERS",
    ),
    LegacyName(
        "env",
        "TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_INCLUDE_DOMAINS",
        "TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_DOMAINS_INCLUDE",
    ),
    LegacyName(
        "env",
        "TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_EXCLUDE_DOMAINS",
        "TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_DOMAINS_EXCLUDE",
    ),
    LegacyName(
        "env",
        "TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_XCLUDE_DOMAINS",
        "TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_DOMAINS_EXCLUDE",
    ),
    LegacyName(
        "env",
        "TRAEFIK_CERTIFICATE_EXPORTER_LOGGINGLEVEL",
        "TRAEFIK_CERTIFICATE_EXPORTER_LOGGING_LEVEL",
    ),
    LegacyName(
        "env",
        "TRAEFIK_CERTIFICATE_EXPORTER_NOTIFY_*",
        "TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_APPRISEURLS_<n>",
    ),
    LegacyName("config", "settings.restartcontainer", "settings.restartcontainers"),
)


@dataclass(frozen=True)
class Finding:
    """One legacy or unknown name found at start-up. Never carries the value."""

    kind: Literal["legacy", "unknown"]
    source: Literal["env", "config"]
    name: str
    replacement: str | None = None
    hint: str = ""
    suggestion: str | None = None
    config_path: str | None = None


#######################################################################


@functools.cache
def _config_leaves() -> dict[tuple[str, ...], object]:
    """Every leaf path of the packaged key registry, with its default."""
    registry = importlib_resources.files("traefik_certificate_exporter").joinpath(
        "config_default.yaml"
    )
    leaves: dict[tuple[str, ...], object] = {}

    def walk(node: object, path: tuple[str, ...]) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                walk(value, (*path, str(key)))
        elif path:
            leaves[path] = node

    walk(yaml.safe_load(registry.read_text("utf-8")), ())
    return leaves


def _env_name(path: tuple[str, ...]) -> str:
    """confuse's `EnvSource(prefix, sep="_")` rule, inverted: the env name for a key path."""
    return ENV_PREFIX + "_".join(path).upper()


@functools.cache
def valid_env_names() -> frozenset[str]:
    """Every env name that sets something: each `config_default.yaml` leaf through the
    confuse rule, plus the names the source reads directly (`SOURCE_ENV_NAMES`)."""
    return frozenset(_env_name(path) for path in _config_leaves()) | SOURCE_ENV_NAMES


def _canonical(name: str) -> str:
    """The name as confuse sees it: the prefix is matched case-sensitively and the rest is
    lowercased (`lower=True`), so `..._settings_DataPath` sets `settings.datapath`. Upper
    case is the spelling the table and the valid set use."""
    return ENV_PREFIX + name[len(ENV_PREFIX) :].upper()


def _is_valid_env_name(name: str) -> bool:
    if name in valid_env_names():
        return True
    confuse_names = valid_env_names() - SOURCE_ENV_NAMES
    canonical = _canonical(name)
    if canonical in confuse_names:
        return True
    # confuse turns a trailing integer segment into a list index; it only addresses a list.
    stem, _, last = canonical.rpartition("_")
    if not last.isdigit() or stem not in confuse_names:
        return False
    path = tuple(stem[len(ENV_PREFIX) :].lower().split("_"))
    return isinstance(_config_leaves().get(path), list)


def _matches(entry: LegacyName, name: str) -> bool:
    if entry.name.endswith("*"):
        return name.startswith(entry.name[:-1])
    return name == entry.name


def _legacy_entry(source: str, name: str) -> LegacyName | None:
    return next(
        (e for e in LEGACY_SETTING_NAMES if e.source == source and _matches(e, name)),
        None,
    )


def _nearest_env_name(name: str) -> str | None:
    """The nearest valid env name, compared without the shared prefix: 29 common
    characters would make every name "close" to every other (`..._FOO` would match
    `..._CORRELATION_ID`)."""
    options = valid_env_names() - HOOK_OUTPUT_ENV_NAMES
    tail = suggest.nearest_name(
        _canonical(name)[len(ENV_PREFIX) :],
        sorted(valid[len(ENV_PREFIX) :] for valid in options),
    )
    return ENV_PREFIX + tail if tail is not None else None


def _dotted_key_paths(tree: Mapping, prefix: str = "") -> Iterator[str]:
    for key, value in tree.items():
        path = f"{prefix}.{key}" if prefix else str(key)
        yield path
        if isinstance(value, Mapping):
            yield from _dotted_key_paths(value, path)


def find_legacy_settings(
    environ: Mapping[str, str],
    config_tree: Mapping | None,
    config_path: str | None = None,
) -> list[Finding]:
    """One finding per legacy or unknown name, environment first. Pure; reads only names.

    Unknown config-file keys are not reported (non-goal): only legacy config keys are.
    """
    findings: list[Finding] = []
    for name in sorted(n for n in environ if n.startswith(ENV_PREFIX)):
        entry = _legacy_entry("env", _canonical(name))
        if entry is not None:
            findings.append(
                Finding("legacy", "env", name, entry.replacement, entry.hint)
            )
        elif not _is_valid_env_name(name):
            findings.append(
                Finding("unknown", "env", name, suggestion=_nearest_env_name(name))
            )
    if isinstance(config_tree, Mapping):
        for key_path in _dotted_key_paths(config_tree):
            entry = _legacy_entry("config", key_path)
            if entry is not None:
                findings.append(
                    Finding(
                        "legacy",
                        "config",
                        key_path,
                        entry.replacement,
                        entry.hint,
                        config_path=config_path,
                    )
                )
    return findings


def _message(finding: Finding) -> str:
    name = sanitize_for_log(finding.name)
    if finding.kind == "unknown":
        if finding.suggestion:
            return (
                f"Unknown setting {name} in environment; "
                f"did you mean {finding.suggestion}?"
            )
        return (
            f"Unknown setting {name} in environment matches no setting; {USAGE_POINTER}"
        )
    if finding.source == "config":
        where = (
            f"Legacy key {name} in config file {sanitize_for_log(finding.config_path)}"
        )
    else:
        where = f"Legacy setting {name} in environment"
    fix = f"use {finding.replacement}" if finding.replacement else finding.hint
    return f"{where} is ignored; {fix}"


def warn_legacy_settings(findings: list[Finding], logger: logging.Logger) -> None:
    """One WARNING per finding. Names only -- a finding holds no value to leak."""
    for finding in findings:
        logger.warning(_message(finding))


def _read_config_tree(config_file: str | os.PathLike | None) -> Mapping | None:
    """The raw config file, `yaml.safe_load` only; None when absent or unreadable (the
    loader's own error handling for the file is unchanged)."""
    if config_file is None or not os.path.isfile(config_file):
        return None
    try:
        tree = yaml.safe_load(Path(config_file).read_text("utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError):
        return None
    return tree if isinstance(tree, Mapping) else None


def check_setting_names(
    environ: Mapping[str, str],
    config_file: str | os.PathLike | None,
    logger: logging.Logger,
) -> None:
    """Detect and warn, once per settings load. Advisory: it never raises -- a failure is
    logged once at WARNING and start-up continues."""
    try:
        config_path = str(config_file) if config_file is not None else None
        findings = find_legacy_settings(
            environ, _read_config_tree(config_file), config_path
        )
        warn_legacy_settings(findings, logger)
    except Exception as e:  # noqa: BLE001 -- advisory check must not stop start-up
        logger.warning(
            f"Setting-name check failed and was skipped ({type(e).__name__}); "
            "start-up continues"
        )
