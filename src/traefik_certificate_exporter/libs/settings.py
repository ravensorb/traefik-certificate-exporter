#######################################################################


import functools
import json
import os
import re
import stat
import sys
import warnings
from pathlib import Path

import confuse
import importlib_resources
import jsonpickle
from confuse.util import build_dict
from dotenv import load_dotenv

from .legacy_settings import check_setting_names, find_legacy_settings
from .logging_utils import globalLogger, sanitize_for_log
from .object import ObjectBase

#######################################################################

# The one place a secret-bearing setting is declared. Redaction and its guard both derive
# from this, so adding a credential-shaped setting is one entry here rather than an edit in
# each sink and one more case in the test.
#
# Each entry is a CONFIG KEY -- a walk into the config tree, `settings.appriseurls` --
# and not a filesystem path, which is what `dataPath` and `outputPath` in this same
# module mean. confuse redacts on exactly this shape. The name-pattern
# below stays as a second, independent net for anything shaped like a credential that
# nobody remembered to declare -- but it is a backstop, not the mechanism: a credential
# held as a VALUE (an Apprise destination URL inside a list) has no matching key anywhere
# on its path, so no pattern over key names can ever reach it. That is BL-E001-005, and
# the path registry is the answer to it.
SECRET_CONFIG_KEYS: tuple[tuple[str, ...], ...] = (
    ("settings", "pkcs12passphrase"),
    # An Apprise destination URL usually IS the credential -- the token sits in the
    # path (`tgram://<token>/…`) or the userinfo (`mailto://user:pw@host`). It is also
    # a VALUE inside a list, which is precisely what no key-name pattern can reach;
    # declaring the path is the only mechanism that covers it.
    ("settings", "appriseurls"),
    # The post-export hook's command line often carries a credential -- an
    # `Authorization` header, a webhook token -- in its arguments. Declared so both dumps
    # mask it; the hook's own log lines name only the program (ADR-0045).
    ("settings", "postexportcommand"),
)

# The one place a setting's trust class is declared (ADR-0049). Three classes:
# - `environment-only-when-root`: when the process runs as root, the key is taken only from
#   the environment, the command line or the packaged default. A value from a configuration
#   file or a `.env` file is withheld with one ERROR, because the account that owns
#   `/config` (LinuxServer's PUID) must not choose what root runs, where root writes, or
#   which store root trusts as the source of what it writes.
# - `environment-only-in-every-mode`: the same rule for every euid, and a file value is
#   withheld even when it would not have won (ADR-0049, amendment E015-S02-005).
# - `any-source`: every source, every euid.
# Every leaf of `config_default.yaml` has an entry; `tests/test_settings_surface.py` fails
# on a missing, extra or unknown one.
#
# The `any-source` rationales below are REVIEWED CLAIMS, not mechanically checked: no test
# proves that an `any-source` key cannot change what root executes or where or what it
# writes. Review this map when a key is added, or when how an existing key is used changes
# in `certificate_exporter.py`, `docker.py`, `notify.py` or the init resolver
# (`init-traefik-certificate-exporter-config/run`) (ADR-0049, "What is and is not
# mechanically checked").
ROOT_TRUST_ENVIRONMENT_ONLY = "environment-only-when-root"
ROOT_TRUST_ENVIRONMENT_ONLY_EVERY_MODE = "environment-only-in-every-mode"
ROOT_TRUST_ANY_SOURCE = "any-source"
ROOT_SETTING_TRUST: dict[tuple[str, ...], str] = {
    # Decides whether a .env file is read; no file may choose it.
    ("settings", "loaddotenv"): ROOT_TRUST_ENVIRONMENT_ONLY_EVERY_MODE,
    # Root executes it.
    ("settings", "postexportcommand"): ROOT_TRUST_ENVIRONMENT_ONLY,
    # Root writes there; init chowns everything under it in dropped mode.
    ("settings", "outputpath"): ROOT_TRUST_ENVIRONMENT_ONLY,
    # Root trusts the store it reads there as the source of the keys it writes (AG-1).
    ("settings", "datapath"): ROOT_TRUST_ENVIRONMENT_ONLY,
    # Validated as a file-name glob at load (AC 1a, ADR-0049, AG-1).
    ("settings", "filespec"): ROOT_TRUST_ANY_SOURCE,
    # Path component, whitelisted; output containment checked.
    ("settings", "traefikresolverid"): ROOT_TRUST_ANY_SOURCE,
    # Path layout only; components whitelisted, output containment checked.
    ("settings", "resolverinpathname"): ROOT_TRUST_ANY_SOURCE,
    # Path layout only; components whitelisted, output containment checked.
    ("settings", "flat"): ROOT_TRUST_ANY_SOURCE,
    # Availability only, no read/write/execute reach.
    ("settings", "dryrun"): ROOT_TRUST_ANY_SOURCE,
    # Bounded Docker API: ping, list by label, get, restart; endpoint from DOCKER_HOST.
    ("settings", "restartcontainers"): ROOT_TRUST_ANY_SOURCE,
    # Domain filter; path components whitelisted, output containment checked.
    ("settings", "domains", "include"): ROOT_TRUST_ANY_SOURCE,
    # Domain filter; path components whitelisted, output containment checked.
    ("settings", "domains", "exclude"): ROOT_TRUST_ANY_SOURCE,
    # Availability only, no read/write/execute reach.
    ("settings", "watchforchanges"): ROOT_TRUST_ANY_SOURCE,
    # Availability only, no read/write/execute reach.
    ("settings", "runatstart"): ROOT_TRUST_ANY_SOURCE,
    # Availability only, no read/write/execute reach.
    ("settings", "watchinterval"): ROOT_TRUST_ANY_SOURCE,
    # Availability only, no read/write/execute reach (changes the .pfx passphrase).
    ("settings", "pkcs12passphrase"): ROOT_TRUST_ANY_SOURCE,
    # Availability only, no read/write/execute reach: it changes how a store's keys are checked, never what root executes, where it writes or which store it reads.
    ("settings", "validatekeys"): ROOT_TRUST_ANY_SOURCE,
    # Outbound requests to any host the container reaches: json/xml/form can choose method,
    # path and headers (RT-4). Accepted residual risk, MD-25; no local file or process reach.
    ("settings", "appriseurls"): ROOT_TRUST_ANY_SOURCE,
}

# The switch that decides whether a `.env` file is read (MD-24). Named only where the
# decision is taken; the file-source enforcement reads its class from the map above.
_LOAD_DOTENV_KEY = ("settings", "loaddotenv")

# Command-line option per argparse `dest`, registered by `cli_args` (a higher layer, AD-13,
# so this module cannot import it). The every-mode ERROR names the flag argparse actually
# defines; without a registration it says "the command line".
_COMMAND_LINE_OPTIONS: dict[str, str] = {}


def register_command_line_options(options: dict[str, str]) -> None:
    """Record the command-line option of each argparse `dest` (`cli_args` calls this)."""
    _COMMAND_LINE_OPTIONS.update(options)


# The environment prefix confuse's `set_env` reads, and the one `_env_name` derives from.
_ENV_PREFIX = "TRAEFIK_CERTIFICATE_EXPORTER_"


def _env_name(keyPath: tuple[str, ...]) -> str:
    """The environment variable confuse's `set_env(prefix=_ENV_PREFIX, sep="_")` maps to
    `keyPath`: `("settings", "outputpath")` -> `..._SETTINGS_OUTPUTPATH`."""
    return _ENV_PREFIX + "_".join(keyPath).upper()


def _env_key_path(name: str) -> tuple[str, ...] | None:
    """The config key path confuse's `set_env(prefix=_ENV_PREFIX, sep="_")` assigns the
    environment variable `name`, or None when the name lacks the prefix (compared
    case-insensitively). Derived with confuse's own `build_dict`, the splitter
    `EnvSource.load` applies to the lower-cased tail, not a re-implementation of it:
    `..._SETTINGS_APPRISEURLS_0` -> `("settings", "appriseurls", "0")`. Turning an
    all-integer level into a list (`EnvSource._convert_dict_lists`) is left to the caller,
    which decides per key whether an index is admissible."""
    if not name.upper().startswith(_ENV_PREFIX):
        return None
    node: object = build_dict(
        {name[len(_ENV_PREFIX) :].lower(): None}, sep="_", keep_none=True
    )
    path: list[str] = []
    while isinstance(node, dict) and len(node) == 1:
        ((segment, node),) = node.items()
        path.append(segment)
    return tuple(path)


def _is_file_source(source) -> bool:
    """A confuse source read from a file that is not the packaged default: the config
    file or the confuse user config (ADR-0049 Decision 3)."""
    return getattr(source, "filename", None) is not None and not getattr(
        source, "default", False
    )


def _is_root() -> bool:
    """The root-mode trust rule is active only for euid 0, and never without `geteuid`."""
    return hasattr(os, "geteuid") and os.geteuid() == 0


def _is_legacy_env_name(name: str) -> bool:
    """Whether `name` is a legacy environment name (`legacy_settings`' one table)."""
    return any(f.kind == "legacy" for f in find_legacy_settings({name: ""}, None))


def _is_file_name_glob(value: str) -> bool:
    """Is `value` a file-name glob that cannot leave the directory it is joined to?

    Checks the pattern text only, never resolved paths: `glob` cannot synthesise `..`, and
    a `realpath` containment check would reject legitimate symlinked stores (ADR-0049
    Decision 5). Both separators are refused on every platform.
    """
    if not value or "/" in value or "\\" in value or value in (".", ".."):
        return False
    return not os.path.isabs(value) and not os.path.splitdrive(value)[0]


def _every_mode_keys() -> list[tuple[str, ...]]:
    """Every key the trust map puts in `environment-only-in-every-mode`."""
    return [
        keyPath
        for keyPath, trust in ROOT_SETTING_TRUST.items()
        if trust == ROOT_TRUST_ENVIRONMENT_ONLY_EVERY_MODE
    ]


def _every_mode_key_of_env_name(name: str) -> tuple[str, ...] | None:
    """The every-mode key the environment variable `name` sets, or None. A name below the
    key (an indexed `..._0`) sets it too, so it counts."""
    keyPath = _env_key_path(name)
    if not keyPath:
        return None
    for key in _every_mode_keys():
        if keyPath[: len(key)] == key:
            return key
    return None


def _unread_dotenv_paths(fileName: str) -> list[str]:
    """The `.env` files a run with `settings.loaddotenv` false leaves unread: the one in
    the working directory and the one beside the configuration file, whether or not that
    file exists (the s6 service's cwd is its service directory, not `/config`). Existence
    only -- nothing is opened. De-duplicated by `realpath`, first spelling kept."""
    found: list[str] = []
    seen: set[str] = set()
    for path in (Path(os.getcwd(), ".env"), Path(fileName).parent / ".env"):
        if not os.path.isfile(path):
            continue
        real = os.path.realpath(path)
        if real in seen:
            continue
        seen.add(real)
        found.append(str(path))
    return found


_ROOT_WITHHELD_MESSAGE = (
    "Ignoring settings.{key} from {origin}: this process runs as root, and a file can be "
    "rewritten by an account that must not choose what root runs, where it writes, or "
    "which store it trusts. Using the {fallback} value instead. Set {env} in the "
    "container's environment, or pass the command-line flag (ADR-0049)."
)

_EVERY_MODE_WITHHELD_MESSAGE = (
    "Ignoring settings.{key} from {origin}: it decides whether a .env file is read, so it "
    "is taken only from the environment ({env}) or {flag}. Using the {fallback} value "
    "(ADR-0049)."
)

_UNREAD_DOTENV_MESSAGE = (
    "Not reading .env file(s) {paths}: settings.loaddotenv is false (the container image "
    "sets TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_LOADDOTENV=false). Set variables in the "
    "container's environment: or env_file:, and settings in config.yaml."
)

# Backstop only -- see above. Retained because it catches an undeclared field, and because
# it is what redacts objects that are not the confuse config (the Settings dataclass, and
# the raw argparse namespace).
_SECRET_FIELD_PATTERN = re.compile(
    r"(secret|password|passphrase|token|api[_-]?key)", re.IGNORECASE
)
_REDACTED_VALUE = "***REDACTED***"

# An absent credential is not a credential. Masking by key alone told an operator who
# raised `-ll DEBUG` to answer "is my notification config actually loading?" that both
# `pkcs12passphrase` and `appriseurls` were populated when neither was set -- while every
# neighbouring unset field rendered honestly as `null`. Emitting the real empty shape
# discloses nothing and is the one question the dump exists to answer.
_EMPTY_SECRET_VALUES: tuple = (None, "", [], {}, ())

# RFC 3986 section 3.1 scheme grammar, anchored, followed by `://`. Captures only the scheme;
# nothing after it -- userinfo, host, token, path, query -- is ever emitted.
# `urllib.parse.urlsplit` is not used: Apprise URLs carry tokens with `:` in the netloc
# (`tgram://123:abc/...`), which it reads as a port and can raise `ValueError` on.
_URL_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*(?=://)")


def _is_empty_secret(value) -> bool:
    """Is this credential absent? `None`, or any empty container/string.

    Deliberately not `not value`: `0` and `False` are not credential-shaped emptiness and
    must not be reported as absent.
    """
    if value is None:
        return True
    if isinstance(value, (str, bytes, list, tuple, dict, set)):
        return len(value) == 0
    return False


def _redact_url_like(item) -> object:
    """Mask one element of a declared-secret list, keeping only its scheme.

    `tgram://123:abc/456` -> `tgram://***REDACTED***`, so a DEBUG reader still sees how
    many targets are configured and of what kind (BL-E011-033). An element with no scheme,
    or one that is not a string, is masked whole; an empty one is passed through, as
    `_is_empty_secret` passes through an empty secret.
    """
    if _is_empty_secret(item):
        return item
    if isinstance(item, str):
        match = _URL_SCHEME.match(item)
        if match:
            return f"{match.group(0)}://{_REDACTED_VALUE}"
    return _REDACTED_VALUE


def _redact_secret_value(value) -> object:
    """A present secret is masked; a list one per element (see `_redact_url_like`)."""
    if _is_empty_secret(value):
        return value
    if isinstance(value, list):
        return [_redact_url_like(item) for item in value]
    return _REDACTED_VALUE


@functools.cache
def _secret_leaf_names() -> frozenset[str]:
    """The last segment of every declared secret config key, lowercased.

    `_dump_settings` serialises the `Settings` dataclass rather than the confuse config,
    so confuse's path-based redaction cannot reach it (BL-E010-003). Matching the declared
    leaf names against attribute names -- case-insensitively, since the dataclass is
    camelCase and the config keys are flat lowercase -- keeps that sink deriving from the
    same registry instead of from a second hand-kept list.
    """
    return frozenset(key[-1].lower() for key in SECRET_CONFIG_KEYS)


def _is_declared_secret(key) -> bool:
    """Is this key the last segment of a declared secret config key?

    Compares the last DOTTED segment, because the same value reaches this function under
    two spellings: `pkcs12Passphrase` from the Settings dataclass, and
    `settings.pkcs12passphrase` from argparse's namespace, whose keys are the flattened
    `dest=` strings. Matching the bare leaf only would have covered the first and missed
    the second -- which is the sink that was leaking in the first place.
    """
    return str(key).rsplit(".", 1)[-1].lower() in _secret_leaf_names()


def _redact_secrets(value):
    """Recursively mask dict values whose key looks like a credential, or is declared.

    Value-aware: only a value that is actually PRESENT is masked. An unset one is passed
    through as its real empty shape -- see `_is_empty_secret`. A secret list keeps its
    length and each element's scheme -- see `_redact_url_like`.
    """
    if isinstance(value, dict):
        return {
            key: (
                _redact_secret_value(val)
                if (_SECRET_FIELD_PATTERN.search(str(key)) or _is_declared_secret(key))
                else _redact_secrets(val)
            )
            for key, val in value.items()
        }
    if isinstance(value, list):
        return [_redact_secrets(item) for item in value]
    return value


def _parse_apprise_urls(value) -> list:
    """Normalize the configured destination list.

    Deliberately NOT comma-split, unlike `_parse_domain_list`. A comma is legal and
    idiomatic inside an Apprise URL (`mailto://u:pw@host?to=a@x.com,b@y.com`), so applying
    this project's comma convention here would fragment one destination into two malformed
    ones. From the environment the supported form is confuse's own indexed keys --
    `…_APPRISEURLS_0`, `…_APPRISEURLS_1` -- which yield a real list with no in-band
    separator to collide with (ADR-0014 §3).
    """
    if value is None:
        return []
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    return [str(item).strip() for item in value if str(item).strip()]


def _parse_domain_list(value) -> list:
    """Normalize a domains.include/exclude value into a list of domain strings.

    A config file/CLI source yields a real list already. confuse does support env-var
    arrays natively via indexed keys (`..._INCLUDE_0`, `..._INCLUDE_1`, ...), but this
    project's documented, already-in-use convention (docker/README.md) is a single
    comma-separated env var -- confuse never parses that shape into a list on its own, so
    it's split by hand here to keep that convention working, not because confuse can't
    represent lists at all.
    """
    if value is None:
        return []
    if isinstance(value, str):
        return [v.strip() for v in value.split(",") if v.strip()]
    return [str(v).strip() for v in value if str(v).strip()]


#######################################################################


class Settings:
    dataPath: str | None
    fileSpec: str
    outputPath: str | None
    resolverInPathName: bool
    traefikResolverId: str
    flat: bool
    dryRun: bool
    restartContainers: bool
    # Set per instance in __init__; as a class attribute this dict was shared by every
    # Settings object, so mutating settings.domains['include'] leaked across instances.
    domains: dict
    watchForChanges: bool
    runAtStart: bool
    watchInterval: int
    pkcs12Passphrase: str | None
    postExportCommand: str | None
    appriseUrls: list
    validateKeys: bool
    loadDotenv: bool

    def __init__(
        self,
        dataPath: str | Path | None,
        fileSpec: str,
        outputPath: str | Path | None,
        resolverInPathName: bool,
        traefikResolverId: str,
        flat: bool,
        dryRun: bool,
        restartContainers: bool,
        domains: dict,
        watchForChanges: bool,
        runAtStart: bool,
        watchInterval: int,
        pkcs12Passphrase: str | None,
        postExportCommand: str | None = None,
        appriseUrls: list | None = None,
        validateKeys: bool = True,
        loadDotenv: bool = True,
    ) -> None:
        """
        Initialize the class with the provided parameters.

        Parameters:
            dataPath (str | Path | None): The path to the data.
            fileSpec (str): The specification of the file.
            outputPath (str | Path | None): The path to the output.
            resolverInPathName (bool): Flag indicating if the resolver is in the path name.
            traefikResolverId (str): The ID of the Traefik resolver.
            flat (bool): Flag indicating if the structure is flat.
            dryRun (bool): Flag indicating if it's a dry run.
            restartContainers (bool): Flag indicating if containers need to be restarted.
            domains (dict): Dictionary of domains.
            watchForChanges (bool): Flag indicating if changes should be watched.
            runAtStart (bool): Flag indicating if it should run at start.
            watchInterval (int): The interval to watch for changes.
            pkcs12Passphrase (str | None): Passphrase for PKCS12, if needed.
            appriseUrls (list): Apprise destination URLs notified after a pass.
            postExportCommand (str | None): Shell-like command line run after a
                successful export pass, or None to disable (default).
            validateKeys (bool): Validate RSA private keys when a .pfx is built
                (default). False skips the check for keys from a trusted store; the
                key/certificate match is still checked (ADR-0051).
            loadDotenv (bool): Whether a `.env` file in the working directory was read
                (`settings.loaddotenv`; environment or command line only, MD-24).

        Returns:
            None
        """
        # str(None) == "None" would turn an unset path into a truthy, non-existent path
        # string, defeating the `is None` check callers rely on to detect "not configured".
        self.dataPath = str(dataPath) if dataPath is not None else None
        self.fileSpec = fileSpec
        self.outputPath = str(outputPath) if outputPath is not None else None
        self.resolverInPathName = resolverInPathName
        self.traefikResolverId = traefikResolverId
        self.flat = flat
        self.dryRun = dryRun
        self.restartContainers = restartContainers
        self.domains = domains
        self.watchForChanges = watchForChanges
        self.runAtStart = runAtStart
        self.watchInterval = watchInterval
        self.pkcs12Passphrase = pkcs12Passphrase
        self.postExportCommand = postExportCommand
        self.appriseUrls = appriseUrls or []
        self.validateKeys = validateKeys
        self.loadDotenv = loadDotenv


#######################################################################


def _warn_if_group_or_world_writable(logger, path: Path) -> None:
    """Log a WARNING, naming the file and the mode found, if ``path`` is group- or
    world-writable. This is a trusted-input boundary (the documented ``/config`` mount
    invariant) that this project chose not to enforce in code -- this converts a silent
    assumption into an observable one, mirroring the pattern `_inheritable_metadata`
    already uses for export targets, without changing default behaviour.
    """
    try:
        mode = os.stat(path).st_mode
    except OSError:
        return
    if mode & (stat.S_IWGRP | stat.S_IWOTH):
        logger.warning(
            f"Trust-boundary check: '{path}' is group- or world-writable "
            f"(mode {oct(stat.S_IMODE(mode))}). This file is read as a trusted "
            "configuration source -- a writable mount here is equivalent to granting "
            "write access to this process's configuration and, if "
            "'postexportcommand' is set, to arbitrary command execution. Review the "
            "mount's permissions."
        )


#######################################################################


class SettingsManager(ObjectBase):
    _config: confuse.Configuration
    settings: Settings
    modulePath: Path

    def __init__(self) -> None:
        super().__init__()

        self.__logger = globalLogger
        self.modulePath = Path(
            str(importlib_resources.files("traefik_certificate_exporter"))
        )

    def loadFromFile(self, fileName: str, cmdLineArgs=None) -> None:
        super()._raise_on_progress("Loading Configuration")

        self._config = confuse.Configuration(
            "traefik_certificate_exporter", "traefik_certificate_exporter"
        )

        self.__logger.debug("Loading Configuration from Default Source")
        self._config._add_default_source()
        self.__logger.debug("Loading Configuration from User Source")
        self._config._add_user_source()

        # Order matters: confuse gives a later-added source higher priority. This project is
        # Docker-first, so env vars (the standard vehicle for per-deployment overrides in
        # containerized deploys) must outrank a static/mounted config file, matching
        # CLI > env var > config file > packaged default.
        # `.env` values withheld in root mode, reported once every source is merged.
        self._withheldDotenv: list[tuple[tuple[str, ...], Path]] = []
        # Other `.env` variable names removed in root mode, per file (names only).
        self._removedDotenv: list[tuple[Path, list[str]]] = []
        # Legacy names removed from a `.env` in root mode, reported by the legacy check.
        self._legacyDotenv: list[str] = []
        # Every-mode keys a `.env` set, removed in every mode, reported once merged.
        self._everyModeDotenv: list[tuple[tuple[str, ...], Path]] = []
        isRoot = _is_root()

        # Decided before any `.env` is read, from the environment and the command line
        # only (MD-24). Only the working directory's `.env` is ever read: the one in the
        # installed package's folder is not (MD-24 item 5).
        self._loadDotenvDecided = self._decideLoadDotenv(cmdLineArgs)
        cwdDotenv = Path(os.getcwd(), ".env")
        if not self._loadDotenvDecided:
            unread = _unread_dotenv_paths(fileName)
            if unread:
                self.__logger.warning(
                    _UNREAD_DOTENV_MESSAGE.format(
                        paths=", ".join(f"'{sanitize_for_log(p)}'" for p in unread)
                    )
                )
        elif os.path.exists(cwdDotenv):
            self.__logger.debug("Loading Configuration from Local Environment File")
            _warn_if_group_or_world_writable(self.__logger, cwdDotenv)
            if isRoot:
                self._loadDotenvAsRoot(cwdDotenv)
            else:
                self._loadDotenv(cwdDotenv)

        if os.path.exists(fileName):
            self.__logger.debug(f"Loading Configuration from File: '{fileName}'")
            _warn_if_group_or_world_writable(self.__logger, Path(fileName))
            self._config.set_file(fileName)

        self._config.set_env(prefix=_ENV_PREFIX, sep="_")

        if cmdLineArgs is not None:
            self.__logger.debug("Loading Configuration from Command Line")
            # Redacted, because argparse's namespace carries whatever was typed on the
            # command line -- and `--pkcs12-passphrase` is one of the flags. This printed
            # the passphrase verbatim at DEBUG while both dump helpers a few lines below
            # were carefully masking it, so the redaction the settings dump performs was
            # undone by the line that logged the raw source.
            self.__logger.debug(
                f"Command Line Args: {_redact_secrets(vars(cmdLineArgs))}"
            )
            self._config.set_args(cmdLineArgs, dots=True)

        self.__logger.debug(f"Configuration Directory: {self._config.config_dir()}")
        self.__logger.debug(
            f"User Configuration Path: {self._config.user_config_path()}"
        )

        # Every source is merged, so the winning source of each key is known (ADR-0049).
        self._withholdEveryModeSettings()
        if isRoot:
            self._withholdFileSourcedRootSettings()

        # Every source is now located (the .env files are in os.environ, the config file
        # is known), so legacy and misspelled names can be reported before the first pass.
        # A legacy name a root-mode `.env` added was removed again, but it is reported here
        # with its replacement rather than in the root-mode ERROR (E015-S01-004). Names
        # only: the check never reads a value.
        check_setting_names(
            {**os.environ, **dict.fromkeys(self._legacyDotenv, "")},
            fileName if os.path.exists(fileName) else None,
            self.__logger,
        )

        self._mark_present_secrets()

        self._dump_config()

        self.__logger.debug("Generating Active Configuration")

        # Queried as two independent leaf keys, not `["domains"].get(dict)` -- confuse
        # only merges a nested dict across sources when every source defines the same
        # shape at that path. A source that sets only "domains.include" (env var or a
        # config file overriding one key) would otherwise make "domains.exclude" vanish
        # entirely instead of falling back to the packaged default's `[]` (GitHub #5).
        includeDomains = _parse_domain_list(
            self._config["settings"]["domains"]["include"].get()
        )
        excludeDomains = _parse_domain_list(
            self._config["settings"]["domains"]["exclude"].get()
        )

        if includeDomains and excludeDomains:
            self.__logger.error(
                "settings.domains.include and settings.domains.exclude are mutually "
                "exclusive -- set only one, via any combination of CLI, config file, "
                "or environment variable. Exiting..."
            )
            sys.exit(1)

        self.settings = Settings(
            dataPath=self._config["settings"]["datapath"].as_str(),  # type: ignore
            fileSpec=self._validatedFileSpec(),
            outputPath=self._config["settings"]["outputpath"].as_str(),  # type: ignore
            resolverInPathName=self._config["settings"]["resolverinpathname"].get(bool),  # type: ignore
            flat=self._config["settings"]["flat"].get(bool),  # type: ignore
            traefikResolverId=self._config["settings"]["traefikresolverid"].get(
                confuse.Optional(str)
            ),  # type: ignore
            dryRun=self._config["settings"]["dryrun"].get(bool),  # type: ignore
            restartContainers=self._config["settings"]["restartcontainers"].get(bool),  # type: ignore
            domains={"include": includeDomains, "exclude": excludeDomains},
            watchForChanges=self._config["settings"]["watchforchanges"].get(bool),  # type: ignore
            runAtStart=self._config["settings"]["runatstart"].get(bool),  # type: ignore
            watchInterval=self._config["settings"]["watchinterval"].get(int),  # type: ignore
            pkcs12Passphrase=self._config["settings"]["pkcs12passphrase"].get(
                confuse.Optional(str)
            ),  # type: ignore
            postExportCommand=self._config["settings"]["postexportcommand"].get(
                confuse.Optional(str)
            ),  # type: ignore
            appriseUrls=_parse_apprise_urls(
                self._config["settings"]["appriseurls"].get(confuse.Optional(list))  # type: ignore
            ),
            validateKeys=self._config["settings"]["validatekeys"].get(bool),  # type: ignore
            # Equals the value decided before any `.env` was read, because every file
            # source of it has been withheld; a malformed one raises here as any boolean.
            loadDotenv=self._config["settings"]["loaddotenv"].get(bool),  # type: ignore
        )

        self._dump_settings()

    def sourceOf(self, keyPath: tuple[str, ...]) -> str:
        """Where the effective value of `keyPath` comes from: `environment`,
        `command line`, `configuration file '<path>'` or `default`.

        Classifies the first pair of confuse's own `resolve()`. "command line" is exact
        only because nothing in this loader adds a filename-less source except `set_args`
        (confuse's `set()` inserts one); withholding removes a file's entry rather than
        overlaying a value for the same reason.
        """
        view: confuse.ConfigView = self._config
        for segment in keyPath:
            view = view[segment]
        first = next(iter(view.resolve()), None)
        if first is None:
            return "default"
        source = first[1]
        if isinstance(source, confuse.EnvSource):
            return "environment"
        if source.default:
            return "default"
        if source.filename is not None:
            return f"configuration file '{source.filename}'"
        return "command line"

    def _loadDotenvAsRoot(self, path: Path) -> None:
        """`load_dotenv`, keeping only the variables of `any-source` settings that it newly
        added (ADR-0049 Decision 4, amended 2026-10-12). Every other name it added -- an
        environment-only setting, a logging key, `LD_PRELOAD`, `DOCKER_HOST`, anything --
        is removed again, because root's environment is inherited by the hook root runs.
        A variable the real environment already held is untouched, because `load_dotenv`
        does not override. Names are compared case-insensitively. `interpolate=False`
        (AR-1/RT-2, closure 2026-10-12): a `${VAR}` in a value stays literal, so a file the
        service account writes cannot copy root's environment into an admitted value."""
        before = set(os.environ)
        load_dotenv(path, interpolate=False)
        environmentOnly = {
            _env_name(keyPath): keyPath
            for keyPath, trust in ROOT_SETTING_TRUST.items()
            if trust == ROOT_TRUST_ENVIRONMENT_ONLY
        }
        removed: list[str] = []
        for name in sorted(set(os.environ) - before):
            if self._isAnySourceEnvName(name):
                continue
            del os.environ[name]
            everyMode = _every_mode_key_of_env_name(name)
            keyPath = environmentOnly.get(name.upper())
            if everyMode is not None:
                # Reported by the every-mode ERROR, as in a non-root run (MD-24).
                self._everyModeDotenv.append((everyMode, path))
            elif keyPath is not None:
                self._withheldDotenv.append((keyPath, path))
            elif _is_legacy_env_name(name):
                # It sets nothing in any mode; moving it to the container's environment,
                # as the ERROR below advises, would not help. The legacy warning names
                # the replacement instead.
                self._legacyDotenv.append(name)
            else:
                removed.append(name)
        if removed:
            self._removedDotenv.append((path, removed))

    def _loadDotenv(self, path: Path) -> None:
        """`load_dotenv` for a non-root run, unchanged except that a variable of an
        every-mode environment-only key it newly added is removed again (MD-24): the
        `.env` loading switch was decided before this file was read, and no file may
        choose it. A variable the real environment already held is untouched."""
        before = set(os.environ)
        load_dotenv(path)
        for name in sorted(set(os.environ) - before):
            keyPath = _every_mode_key_of_env_name(name)
            if keyPath is not None:
                del os.environ[name]
                self._everyModeDotenv.append((keyPath, path))

    def _decideLoadDotenv(self, cmdLineArgs) -> bool:
        """Whether a `.env` file is read, decided before any is (MD-24). confuse evaluates
        it over a throwaway view of exactly three sources -- the packaged default, the
        environment as it is now, and the command line -- so no file can take part, and
        the boolean parsing and the precedence are confuse's own. A value confuse rejects
        fails closed: no `.env` is read, and one ERROR names the variable, never its
        value."""
        default = next(s for s in self._config.sources if s.default)
        view = confuse.RootView([confuse.EnvSource(_ENV_PREFIX, sep="_"), default])
        if cmdLineArgs is not None:
            view.set_args(cmdLineArgs, dots=True)
        node: confuse.ConfigView = view
        for segment in _LOAD_DOTENV_KEY:
            node = node[segment]
        try:
            return bool(node.get(bool))
        except confuse.ConfigError:
            self.__logger.error(
                f"Ignoring {_env_name(_LOAD_DOTENV_KEY)}: not a boolean. No .env file "
                "is read (ADR-0049)."
            )
            return False

    def _withholdEveryModeSettings(self) -> None:
        """Remove every `environment-only-in-every-mode` key from every file source that
        carries it, in every mode, with one ERROR per file (MD-24, ADR-0049). Unlike the
        root rule, whether the file value would have won does not matter: a file value
        for such a key is always a misconfiguration, and the image's `ENV` would otherwise
        hide it silently. The keys come from the trust map, never named here.

        Then reports the variables a `.env` file set for such a key, which the loader
        already removed from the environment."""
        for keyPath in _every_mode_keys():
            origins: list[str] = []
            for source in self._config.sources:
                if not _is_file_source(source):
                    continue
                node: object = source
                for segment in keyPath[:-1]:
                    node = node.get(segment) if isinstance(node, dict) else None
                if isinstance(node, dict) and keyPath[-1] in node:
                    node.pop(keyPath[-1])
                    # confuse can hold one file twice (`Configuration()` already reads
                    # the user config that `_add_user_source` adds again): one ERROR.
                    origin = f"configuration file '{source.filename}'"
                    if origin not in origins:
                        origins.append(origin)
            for origin in origins:
                self._logEveryModeWithheld(keyPath, origin)
        for keyPath, path in self._everyModeDotenv:
            self._logEveryModeWithheld(keyPath, f".env file '{path}'")

    def _logEveryModeWithheld(self, keyPath: tuple[str, ...], origin: str) -> None:
        option = _COMMAND_LINE_OPTIONS.get(".".join(keyPath))
        self.__logger.error(
            _EVERY_MODE_WITHHELD_MESSAGE.format(
                key=".".join(keyPath[1:]),
                origin=sanitize_for_log(origin),
                env=_env_name(keyPath),
                flag=f"the command line ({option})" if option else "the command line",
                fallback=self.sourceOf(keyPath),
            )
        )

    def _isAnySourceEnvName(self, name: str) -> bool:
        """Whether confuse's `EnvSource` maps `name` onto an `any-source` setting (F9,
        review E015-S01-001): the setting's own name, or -- for a setting whose packaged
        default is a list -- that name plus `_<digits>`, the indexed form confuse turns
        into a list element and `config_default.yaml` documents for `appriseurls`.
        Anything deeper (`..._APPRISEURLS_0_X`) or an index under a scalar setting is not
        admitted."""
        keyPath = _env_key_path(name)
        if not keyPath:
            return False
        if ROOT_SETTING_TRUST.get(keyPath) == ROOT_TRUST_ANY_SOURCE:
            return True
        parent, index = keyPath[:-1], keyPath[-1]
        if ROOT_SETTING_TRUST.get(parent) != ROOT_TRUST_ANY_SOURCE:
            return False
        if not (index.isascii() and index.isdigit()):
            return False
        return isinstance(self._packagedDefault(parent), list)

    def _packagedDefault(self, keyPath: tuple[str, ...]) -> object:
        """The value of `keyPath` in the packaged `config_default.yaml` source, or None."""
        for source in self._config.sources:
            if not source.default:
                continue
            node: object = source
            for segment in keyPath:
                node = node.get(segment) if isinstance(node, dict) else None
            return node
        return None

    def _withholdFileSourcedRootSettings(self) -> None:
        """Remove every environment-only key whose winning source is a file from every
        file source, so confuse resolves the next admissible source (ADR-0049 Decision 3).

        Never `view.set(...)`: that inserts a filename-less source indistinguishable from
        the command line, and `sourceOf` would misreport the fallback.
        """
        for keyPath, trust in ROOT_SETTING_TRUST.items():
            if trust != ROOT_TRUST_ENVIRONMENT_ONLY:
                continue
            view: confuse.ConfigView = self._config
            for segment in keyPath:
                view = view[segment]
            try:
                winner = next(iter(view.resolve()), None)
            except confuse.ConfigError:
                # A malformed tree; the Settings build below reports it as before.
                continue
            if winner is None or not _is_file_source(winner[1]):
                continue
            origin = f"configuration file '{winner[1].filename}'"
            for source in self._config.sources:
                if not _is_file_source(source):
                    continue
                node: object = source
                for segment in keyPath[:-1]:
                    node = node.get(segment) if isinstance(node, dict) else None
                if isinstance(node, dict):
                    node.pop(keyPath[-1], None)
            self._logWithheld(keyPath, origin)

        # After the file entries are gone, so each names its real fallback source.
        for keyPath, path in self._withheldDotenv:
            self._logWithheld(keyPath, f".env file '{path}'")
        for path, names in self._removedDotenv:
            self.__logger.error(
                f"Ignoring {len(names)} variable(s) from .env file '{path}': this process "
                "runs as root, and a .env file may set only settings that cannot change "
                "what root runs, where it writes, or which store it trusts. Removed: "
                f"{', '.join(names)}. Set them in the container's environment instead "
                "(ADR-0049)."
            )

    def _logWithheld(self, keyPath: tuple[str, ...], origin: str) -> None:
        fallback = self.sourceOf(keyPath)
        self.__logger.error(
            _ROOT_WITHHELD_MESSAGE.format(
                key=".".join(keyPath[1:]),
                origin=origin,
                fallback=fallback,
                env=_env_name(keyPath),
            )
        )

    def _validatedFileSpec(self) -> str:
        """`settings.filespec`, or the packaged default if it is not a file-name glob
        (ADR-0049 Decision 5). Every source, every euid; the value is never logged."""
        keyPath = ("settings", "filespec")
        value = self._config["settings"]["filespec"].as_str()
        if _is_file_name_glob(value):  # type: ignore[arg-type]
            return value  # type: ignore[return-value]
        default = next(s for s in self._config.sources if s.default)["settings"][
            "filespec"
        ]
        self.__logger.error(
            f"Ignoring settings.filespec from {self.sourceOf(keyPath)}: it must be a "
            "file-name glob inside settings.datapath (no directory separator, no '..', "
            f"not absolute). Using the default '{default}' instead (ADR-0049)."
        )
        return default

    def _mark_present_secrets(self):
        """Mark every declared secret path that actually HOLDS a value.

        `Configuration.dump(redact=True)` consults these and masks by path, so this is the
        one place a sink has to be told. Run after every source is merged -- a passphrase
        typed on the command line is as much a credential as one in the file.

        Only PRESENT values are marked. confuse masks a marked path unconditionally, so
        marking an unset one printed `appriseurls: REDACTED` for a key nobody had
        configured, and disagreed with the settings dump about the very same field.
        Leaving an empty path unmarked makes both sinks render absence identically.
        """
        for config_key in SECRET_CONFIG_KEYS:
            view: confuse.ConfigView = self._config
            for segment in config_key:
                view = view[segment]
            try:
                current = view.get()
            except confuse.ConfigError:
                current = None
            if not _is_empty_secret(current):
                view.redact = True

    def _dump_settings(self):
        self.__logger.debug("Current Settings (active)...")
        # `keys=False` pins the pre-5.0 output (a non-string key stays a plain string, not
        # a "json://" one); jsonpickle 4 warns on any falsy `keys`, even an explicit one.
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore", "keys will default to True", DeprecationWarning
            )
            flattened = jsonpickle.dumps(self.settings, unpicklable=False, keys=False)
        safe = _redact_secrets(json.loads(flattened))
        # Indented, like the adjacent block-YAML config dump (BL-E011-036). jsonpickle only
        # flattens the Settings object above; `default=str` keeps a stray non-JSON value
        # from raising inside a DEBUG log call.
        self.__logger.debug(json.dumps(safe, indent=2, default=str))

    def _dump_config(self):
        self.__logger.debug("Current Config (from file)...")
        # confuse's own facility, not a redactor of ours. `dump(redact=True)` masks by
        # config PATH, which is the one mechanism that reaches a credential held as a
        # value inside a list -- the case the key-name pattern cannot see at all. Writing
        # a second redactor beside a library one that already works is what global rule 1
        # forbids, and an earlier draft of ADR-0014 proposed exactly that.
        self.__logger.debug(self._config.dump(redact=True))

    def _handle_on_progress(self, message):
        self.__logger.info(message)


#######################################################################

globalSettingsMgr = SettingsManager()
