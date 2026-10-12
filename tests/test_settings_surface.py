"""The product's documented settings surface maps to settings the product reads.

Every `TRAEFIK_CERTIFICATE_EXPORTER_*` name an operator can copy out of the documentation
must reach a setting: a key path in `config_default.yaml` (through confuse's env rule), or
one of the env names the source reads directly. A name that maps to nothing is a setting
an operator turns on and silently never gets (M2, BL-E013-042, E014-S01-004).

These are product tests: they check the product's own documented surface against the
product source. Checks that police workflows, pins or the supply chain do not live here.

Global rule 4 -- the scope is derived, never listed by hand:

- the files come from `git ls-files` over `_scan_pathspecs()`, minus the vendored trees
  named by the top-level `exclude:` of `.pre-commit-config.yaml`;
- the valid names come from `config_default.yaml` (the single key registry) and from the
  complete env-name string literals in `src/**/*.py`.

The helpers are module-level so later tests can reuse them (the git-history scan and the
README check pass the same pathspecs; there is no second list).

Files that list legacy names by design (`libs/legacy_settings.py`, `docs/upgrading.md`) are
found by a marker token, not a path list: a file containing
`tce-settings-scan: legacy-names-listed` may quote `LEGACY_SETTING_NAMES` names, and a marked
file must quote at least one (E014-S01-009). In a marked documentation file every other name
is still checked. A marked `.py` file is outside the documentation scan and skipped by the
literal scan; for `libs/legacy_settings.py` the non-legacy names are the replacement column,
which `test_legacy_replacements_are_valid` checks.
"""

import os
import re
import subprocess
from pathlib import Path

import confuse
import pytest
import yaml

from traefik_certificate_exporter.libs import legacy_settings
from traefik_certificate_exporter.libs.legacy_settings import LEGACY_SETTING_NAMES

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = PROJECT_ROOT / "src"
CONFIG_DEFAULT = SOURCE_ROOT / "traefik_certificate_exporter" / "config_default.yaml"
PRE_COMMIT_CONFIG = PROJECT_ROOT / ".pre-commit-config.yaml"

ENV_PREFIX = "TRAEFIK_CERTIFICATE_EXPORTER_"
# The dotted tail captures a historic `..._SETTINGS.RESTARTCONTAINER` whole, so it is
# reported as itself rather than truncated to a valid-looking non-leaf.
ENV_NAME_PATTERN = re.compile(
    r"TRAEFIK_CERTIFICATE_EXPORTER_[A-Z0-9_]+(?:\.[A-Z0-9_]+)*"
)
_SOURCE_LITERAL_PATTERN = re.compile(
    r"[\"'](TRAEFIK_CERTIFICATE_EXPORTER_[A-Z0-9_]+)[\"']"
)

LEGACY_MARKER = "tce-settings-scan: legacy-names-listed"

_SCAN_INCLUDE = ("*.md", "*.yml", "*.yaml", "*.sample", "*Dockerfile")
# Planning artifacts, immutable decision records that may quote old names, and CI (not
# operator config).
_SCAN_EXCLUDE = ("_bmad-output/**", "docs/adr/**", ".github/**")


def _scan_pathspecs() -> list[str]:
    """The git pathspecs that define which files document the settings surface."""
    return [*_SCAN_INCLUDE, *(f":(exclude){p}" for p in _SCAN_EXCLUDE)]


def _vendored_exclude_pattern(root: Path = PROJECT_ROOT) -> re.Pattern[str]:
    """The top-level `exclude:` regex of `.pre-commit-config.yaml` -- the one definition of
    "vendored" every hook already uses."""
    config = yaml.safe_load((root / ".pre-commit-config.yaml").read_text("utf-8"))
    pattern = config.get("exclude") if isinstance(config, dict) else None
    assert pattern, f"{root / '.pre-commit-config.yaml'} declares no top-level exclude:"
    return re.compile(pattern)


def _scan_files(root: Path = PROJECT_ROOT) -> list[str]:
    """Repository-relative paths in scope: tracked and untracked-but-not-ignored, so a new,
    unstaged file is checked too."""
    listed = subprocess.run(
        [
            "git",
            "ls-files",
            "--cached",
            "--others",
            "--exclude-standard",
            "--",
            *_scan_pathspecs(),
        ],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()
    vendored = _vendored_exclude_pattern(root)
    return sorted(
        {
            path
            for path in listed
            if not vendored.search(path) and (root / path).is_file()
        }
    )


def _config_key_paths(
    config_file: Path = CONFIG_DEFAULT,
) -> dict[tuple[str, ...], object]:
    """Every leaf (non-mapping) path in the key registry, with its default value."""
    leaves: dict[tuple[str, ...], object] = {}

    def walk(node: object, path: tuple[str, ...]) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                walk(value, (*path, str(key)))
        else:
            leaves[path] = node

    walk(yaml.safe_load(config_file.read_text("utf-8")), ())
    return leaves


def _env_name_to_key_path(name: str) -> tuple[str, ...] | None:
    """confuse's `EnvSource` rule as this project configures it (`sep="_"`, lower=True):
    strip the prefix, lowercase, split on `_`. A trailing integer segment is a list index
    and is dropped. Returns None for a name that cannot map at all."""
    if "." in name or not name.startswith(ENV_PREFIX):
        return None
    segments = name[len(ENV_PREFIX) :].lower().split("_")
    if segments and segments[-1].isdigit():
        segments = segments[:-1]
    if not segments or any(segment == "" for segment in segments):
        return None
    return tuple(segments)


def _valid_env_names_from_source(source_root: Path = SOURCE_ROOT) -> frozenset[str]:
    """Complete env-name string literals in the product source -- the names read with
    `os.getenv` before settings load, and the ones set for the post-export hook.

    Marked files are skipped: `libs/legacy_settings.py` quotes legacy names by design and
    must not make them valid."""
    names: set[str] = set()
    for path in source_root.rglob("*.py"):
        text = path.read_text("utf-8")
        if not _is_marked(text):
            names.update(_SOURCE_LITERAL_PATTERN.findall(text))
    return frozenset(names)


def _is_marked(text: str) -> bool:
    return LEGACY_MARKER in text


def _is_legacy_env_name(name: str) -> bool:
    """Matched by an env row of `LEGACY_SETTING_NAMES` (exact, or a `*` prefix row), by the
    runtime's own matcher -- one rule, not a restatement."""
    return legacy_settings._legacy_entry("env", name) is not None


def _is_valid_full_name(
    name: str,
    leaves: dict[tuple[str, ...], object],
    source_names: frozenset[str],
) -> bool:
    if name in source_names:
        return True
    path = _env_name_to_key_path(name)
    if path is None or path not in leaves:
        # Not a leaf: a dict prefix such as `..._SETTINGS_DOMAINS` sets nothing.
        return False
    has_index = name[len(ENV_PREFIX) :].split("_")[-1].isdigit()
    # An index only addresses a list.
    return not has_index or isinstance(leaves[path], list)


def _all_valid_names(
    leaves: dict[tuple[str, ...], object], source_names: frozenset[str]
) -> frozenset[str]:
    return frozenset(
        {ENV_PREFIX + "_".join(path).upper() for path in leaves} | set(source_names)
    )


def _is_valid_env_name(
    name: str,
    leaves: dict[tuple[str, ...], object] | None = None,
    source_names: frozenset[str] | None = None,
) -> bool:
    """A full name must map to a leaf or be a source literal. A match ending in `_` is a
    placeholder prefix (`..._SETTINGS_<KEY>`, `..._APPRISEURLS_<n>`, a grep pattern): it
    is valid when, stripped of the trailing `_`, it is a strict `_`-boundary prefix of a
    valid name, or it names a list setting (what follows is an index). A placeholder after
    a scalar setting (`..._SETTINGS_DATAPATH_<n>`) is invalid, as `..._DATAPATH_0` is."""
    leaves = _config_key_paths() if leaves is None else leaves
    source_names = (
        _valid_env_names_from_source() if source_names is None else source_names
    )
    if not name.endswith("_"):
        return _is_valid_full_name(name, leaves, source_names)
    if "." in name:
        return False
    stem = name.rstrip("_")
    stem_path = _env_name_to_key_path(stem)
    if stem_path in leaves and isinstance(leaves[stem_path], list):
        return True
    return any(
        valid.startswith(stem + "_") for valid in _all_valid_names(leaves, source_names)
    )


def _unmapped_env_names(root: Path = PROJECT_ROOT) -> list[str]:
    """`path:line: NAME` for every documented env name in scope that maps to nothing."""
    leaves = _config_key_paths()
    source_names = _valid_env_names_from_source()
    problems = []
    for rel in _scan_files(root):
        text = (root / rel).read_text("utf-8", errors="replace")
        marked = _is_marked(text)
        for lineno, line in enumerate(text.splitlines(), start=1):
            for match in ENV_NAME_PATTERN.finditer(line):
                name = match.group(0)
                if marked and _is_legacy_env_name(name):
                    continue
                if not _is_valid_env_name(name, leaves, source_names):
                    problems.append(f"{rel}:{lineno}: {name}")
    return problems


def _marked_files(root: Path = PROJECT_ROOT) -> list[str]:
    """Every file in scope that carries the marker: the documentation scan scope plus the
    product source (where `libs/legacy_settings.py` lives)."""
    candidates = set(_scan_files(root))
    candidates.update(
        str(path.relative_to(root)) for path in (root / "src").rglob("*.py")
    )
    return sorted(
        rel
        for rel in candidates
        if _is_marked((root / rel).read_text("utf-8", errors="replace"))
    )


def _stale_marked_files(root: Path = PROJECT_ROOT) -> list[str]:
    """Marked files that quote no legacy name: a marker with nothing to permit is an
    opt-out waiting to hide something."""
    return [
        rel
        for rel in _marked_files(root)
        if not any(
            _is_legacy_env_name(name)
            for name in ENV_NAME_PATTERN.findall(
                (root / rel).read_text("utf-8", errors="replace")
            )
        )
    ]


def _history_names(root: Path = PROJECT_ROOT) -> set[str]:
    """Every name ever committed in scope, reachable from HEAD.

    `git log -p HEAD` over `_scan_pathspecs()` -- the same pathspecs as the tree scan, so
    deleted files are covered too. A pathspec cannot express the vendored `exclude:` regex,
    so hunks are attributed to their file by the `diff --git` header and vendored files are
    dropped with the same `_vendored_exclude_pattern()` the tree scan uses (BL-E014-007).
    Commit messages are not documentation and are left out (`--format=`).
    """
    log = subprocess.run(
        [
            "git",
            "-c",
            "core.quotePath=false",
            "log",
            "-p",
            "--no-color",
            "--no-ext-diff",
            "--format=",
            "HEAD",
            "--",
            *_scan_pathspecs(),
        ],
        cwd=root,
        capture_output=True,
        text=True,
        errors="replace",
        check=True,
    ).stdout
    vendored = _vendored_exclude_pattern(root)
    names: set[str] = set()
    skip = False
    for line in log.splitlines():
        if line.startswith("diff --git "):
            header = _DIFF_HEADER.match(line)
            if header is None:
                # A C-quoted path (`"b/..."`) or a path containing " b/" cannot be
                # attributed; carrying the previous file's state over would be a silent
                # scope error, so refuse instead.
                pytest.fail(f"cannot attribute history hunk to a file: {line!r}")
            skip = bool(vendored.search(header.group(2)))
            continue
        if not skip:
            names.update(ENV_NAME_PATTERN.findall(line))
    return names


# Only an unambiguous header: no quoting, and exactly one " b/" separator.
_DIFF_HEADER = re.compile(r"^diff --git a/((?:(?! b/).)+) b/((?:(?! b/).)+)$")


def _undocumented_history_names(root: Path = PROJECT_ROOT) -> list[str]:
    """Names in the history that are neither valid, a valid placeholder, nor legacy."""
    shallow = subprocess.run(
        ["git", "rev-parse", "--is-shallow-repository"],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    if shallow == "true":
        pytest.fail(
            "shallow clone: the legacy-name history check needs full history "
            "(CI checks out with fetch-depth: 0); refusing to pass on a partial history"
        )
    leaves = _config_key_paths()
    source_names = _valid_env_names_from_source()
    return sorted(
        name
        for name in _history_names(root)
        if not _is_valid_env_name(name, leaves, source_names)
        and not _is_legacy_env_name(name)
    )


# ---------------------------------------------------------------------------


def test_documented_env_names_map_to_settings():
    files = _scan_files()
    # Non-vacuity, not a scope list: the scan must at least see the two operator READMEs.
    assert {"README.md", "docker/README.md"} <= set(files), files

    problems = _unmapped_env_names()

    assert not problems, (
        "documented environment variable(s) map to no setting -- an operator who copies "
        "one gets the setting silently off:\n  " + "\n  ".join(problems)
    )


@pytest.mark.parametrize(
    ("text", "valid"),
    [
        ("TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_<KEY>", True),
        ("TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_APPRISEURLS_<n>", True),
        ("TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_{KEY}", True),
        ("entry: 'TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_'", True),
        ("TRAEFIK_CERTIFICATE_EXPORTER_SETTINGZ_<KEY>", False),
        ("TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_DATAPATH_<n>", False),
    ],
)
def test_placeholder_prefixes_are_recognised(text, valid):
    names = ENV_NAME_PATTERN.findall(text)
    assert len(names) == 1, names
    assert names[0].endswith("_"), f"{names[0]!r} is not a placeholder prefix"
    assert _is_valid_env_name(names[0]) is valid


@pytest.mark.parametrize(
    ("name", "valid"),
    [
        ("TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_RESTARTCONTAINERS", True),
        ("TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_APPRISEURLS_0", True),
        ("TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_DOMAINS_INCLUDE", True),
        ("TRAEFIK_CERTIFICATE_EXPORTER_LOGGING_CONSOLEONLY", True),
        ("TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_RESTARTCONTAINER", False),
        ("TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS.RESTARTCONTAINER", False),
        ("TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_DOMAINS", False),
        ("TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_DATAPATH_0", False),
        ("TRAEFIK_CERTIFICATE_EXPORTER_CONFIGFILE", False),
    ],
)
def test_env_name_mapping_rules(name, valid):
    assert ENV_NAME_PATTERN.fullmatch(name), name
    assert _is_valid_env_name(name) is valid


def test_vendored_paths_are_excluded_but_docs_are_scanned(tmp_path):
    """The vendored set is the pre-commit `exclude:` regex, read from the real config."""
    (tmp_path / ".pre-commit-config.yaml").write_text(
        PRE_COMMIT_CONFIG.read_text("utf-8")
    )
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)

    planted_name = "TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_RESTARTCONTAINER"
    vendored_rel = ".claude/skills/x.md"
    assert _vendored_exclude_pattern(tmp_path).search(vendored_rel), (
        "the pre-commit exclude: no longer covers .claude/; pick a path it does cover"
    )
    (tmp_path / vendored_rel).parent.mkdir(parents=True)
    (tmp_path / vendored_rel).write_text(f"{planted_name}=true\n")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "planted.md").write_text(f"{planted_name}=true\n")

    problems = _unmapped_env_names(tmp_path)

    assert problems == [f"docs/planted.md:1: {planted_name}"], problems


# ---------------------------------------------------------------------------
# Legacy names (E014-S01-009).
# ---------------------------------------------------------------------------


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@example.invalid",
            "-c",
            "commit.gpgsign=false",
            *args,
        ],
        cwd=root,
        check=True,
        capture_output=True,
    )


def _repo_with_precommit_config(root: Path) -> None:
    (root / ".pre-commit-config.yaml").write_text(PRE_COMMIT_CONFIG.read_text("utf-8"))
    _git(root, "init", "-q")


def test_legacy_map_covers_documented_names():
    """Every name ever documented in scope is valid, a valid placeholder, or a legacy row.

    The history is `git log -p HEAD` -- what is reachable from the commit under test, so
    local branches and stashes cannot make `just check` and CI disagree -- over the same
    pathspecs and vendored exclusion as the tree scan. It FAILS (never skips) on a shallow
    clone, because a partial history would be a false green.

    Coverage limit (global rule 3): history is immutable, so a committed name that is
    neither valid nor in `LEGACY_SETTING_NAMES` keeps `main` red until a row is added.
    That is the intended pressure. The name was documented, so operators may be using it:
    the remedy is a table row, never a scope exclusion.
    """
    names = _history_names()
    # Non-vacuity: the history must at least show the names the table exists for.
    assert "TRAEFIK_CERTIFICATE_EXPORTER_RESTART_CONTAINERS" in names, sorted(names)

    missing = _undocumented_history_names()

    assert not missing, (
        "name(s) documented in the history map to no setting and have no "
        "LEGACY_SETTING_NAMES row -- an operator who copied one gets no warning:\n  "
        + "\n  ".join(missing)
    )


def test_history_scan_drops_vendored_paths(tmp_path):
    """Scope attack on the history scan (BL-E014-007): a name committed under a vendored
    tree is ignored, the same name under docs/ is reported."""
    _repo_with_precommit_config(tmp_path)
    planted = "TRAEFIK_CERTIFICATE_EXPORTER_PLANTED_LEGACY"
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "x.md").write_text(f"{planted}=1\n")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "vendored")

    assert _undocumented_history_names(tmp_path) == []

    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "y.md").write_text(f"{planted}=1\n")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "docs")

    assert _undocumented_history_names(tmp_path) == [planted]


def test_no_legacy_name_is_valid():
    leaves = _config_key_paths()
    source_names = _valid_env_names_from_source()
    runtime_valid = legacy_settings.valid_env_names()
    clashes = []
    for entry in LEGACY_SETTING_NAMES:
        if entry.source == "config":
            if tuple(entry.name.split(".")) in leaves:
                clashes.append(entry.name)
            continue
        names = (
            [entry.name[:-1], entry.name[:-1] + "0"]
            if entry.name.endswith("*")
            else [entry.name]
        )
        for name in names:
            if _is_valid_env_name(name, leaves, source_names) or name in runtime_valid:
                clashes.append(name)

    assert not clashes, f"legacy names that are also valid: {clashes}"


def test_marked_file_permits_only_legacy_names(tmp_path):
    _repo_with_precommit_config(tmp_path)
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "upgrading.md").write_text(
        f"<!-- {LEGACY_MARKER} -->\n"
        "TRAEFIK_CERTIFICATE_EXPORTER_RESTART_CONTAINERS -> "
        "TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_RESTARTCONTAINERS\n"
        "TRAEFIK_CERTIFICATE_EXPORTER_NOTIFY_0 -> "
        "TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_APPRISEURLS_<n>\n"
        "TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_RESTARTCONTAINRES\n"
    )
    (tmp_path / "docs" / "unmarked.md").write_text(
        "TRAEFIK_CERTIFICATE_EXPORTER_RESTART_CONTAINERS\n"
    )

    problems = _unmapped_env_names(tmp_path)

    assert problems == [
        "docs/unmarked.md:1: TRAEFIK_CERTIFICATE_EXPORTER_RESTART_CONTAINERS",
        "docs/upgrading.md:4: TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_RESTARTCONTAINRES",
    ], problems


def test_stale_marker_fails(tmp_path):
    marked = _marked_files()
    # Non-vacuity: the table's own module is the marker's first user.
    assert "src/traefik_certificate_exporter/libs/legacy_settings.py" in marked, marked

    stale = _stale_marked_files()

    assert not stale, (
        f"file(s) carry the '{LEGACY_MARKER}' marker but quote no LEGACY_SETTING_NAMES "
        "name -- remove the marker:\n  " + "\n  ".join(stale)
    )

    # And the rule itself: a marker over no legacy name is reported.
    _repo_with_precommit_config(tmp_path)
    (tmp_path / "src").mkdir()
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "x.md").write_text(f"<!-- {LEGACY_MARKER} -->\nno names\n")
    assert _stale_marked_files(tmp_path) == ["docs/x.md"]


# The upgrade notes' legacy table is rendered from `LEGACY_SETTING_NAMES`, never typed
# (E014-S02-005). `legacy_settings` exposes no renderer, and this test is the only
# consumer, so the renderer lives here. Regenerate the block with
# `poetry run python -m tests.test_settings_surface`.
UPGRADING = PROJECT_ROOT / "docs" / "upgrading.md"
LEGACY_BLOCK_BEGIN = "<!-- legacy-settings:begin -->"
LEGACY_BLOCK_END = "<!-- legacy-settings:end -->"


def render_legacy_table() -> str:
    """One Markdown row per `LEGACY_SETTING_NAMES` entry, in table order."""
    rows = [
        "| Source | Legacy name | Replacement or fix |",
        "| --- | --- | --- |",
    ]
    for entry in LEGACY_SETTING_NAMES:
        fix = f"`{entry.replacement}`" if entry.replacement else entry.hint
        fix = fix.replace("|", "\\|")
        rows.append(f"| {entry.source} | `{entry.name}` | {fix} |")
    return "\n".join(rows)


def _legacy_block(text: str) -> str:
    """The text between the two markers, which must each appear exactly once, in order."""
    assert text.count(LEGACY_BLOCK_BEGIN) == 1, f"need one {LEGACY_BLOCK_BEGIN}"
    assert text.count(LEGACY_BLOCK_END) == 1, f"need one {LEGACY_BLOCK_END}"
    _, _, rest = text.partition(LEGACY_BLOCK_BEGIN)
    block, _, _ = rest.partition(LEGACY_BLOCK_END)
    return block.strip()


def test_upgrading_lists_every_legacy_name():
    """The block between the markers in `docs/upgrading.md` equals a fresh rendering of
    `LEGACY_SETTING_NAMES`, so the table cannot drift from the code (global rule 3)."""
    # Non-vacuity: the rendering holds one row per entry plus the two header rows.
    rendered = render_legacy_table()
    assert len(rendered.splitlines()) == len(LEGACY_SETTING_NAMES) + 2
    assert LEGACY_SETTING_NAMES, "LEGACY_SETTING_NAMES is empty"

    block = _legacy_block(UPGRADING.read_text("utf-8"))

    assert block == rendered, (
        f"{UPGRADING.relative_to(PROJECT_ROOT)}: the legacy-settings block differs from "
        "LEGACY_SETTING_NAMES; regenerate it with "
        "`poetry run python -m tests.test_settings_surface`"
    )


def test_valid_env_names_match_confuse_envsource(monkeypatch):
    """A-11: the restated mapping rule is checked against confuse itself, so a change in
    confuse's rule fails here instead of the two diverging silently."""
    leaves = _config_key_paths()
    mapped = sorted(
        legacy_settings.valid_env_names() - legacy_settings.SOURCE_ENV_NAMES
    )
    assert mapped, "valid_env_names() derived nothing from config_default.yaml"
    list_names = [
        f"{name}_0"
        for name in mapped
        if isinstance(leaves.get(_env_name_to_key_path(name)), list)
    ]
    assert list_names, "no list setting exercised the index rule"

    for name in list(os.environ):
        if name.startswith(ENV_PREFIX):
            monkeypatch.delenv(name)

    mismatches = []
    # confuse lowercases after the prefix (`lower=True`); the runtime relies on that to
    # accept a mixed-case name, so one is pinned here.
    mixed_case = ENV_PREFIX + "settings_DataPath"
    for name in [*mapped, *list_names, mixed_case]:
        monkeypatch.setenv(name, "x")
        try:
            tree = dict(confuse.EnvSource(ENV_PREFIX, sep="_"))
        finally:
            monkeypatch.delenv(name)
        path: tuple[str, ...] = ()
        node: object = tree
        while isinstance(node, dict) and len(node) == 1:
            key, node = next(iter(node.items()))
            path = (*path, key)
        expected = _env_name_to_key_path(ENV_PREFIX + name[len(ENV_PREFIX) :].upper())
        if path != expected or expected not in leaves:
            mismatches.append(f"{name}: confuse {path}, derived {expected}")
        elif name in list_names and node != ["x"]:
            mismatches.append(f"{name}: confuse gave {node!r}, not a list")

    assert not mismatches, "\n".join(mismatches)


def test_runtime_valid_env_names_equal_source_scan():
    """AG-5 / BL-E014-001: the runtime set is the registry plus module constants; this
    ties it to the registry plus a scan of every env-name literal in `src`, so an
    `os.getenv` literal without its constant fails here instead of producing a false
    "Unknown setting" WARNING for every operator who sets it."""
    derived = _all_valid_names(_config_key_paths(), _valid_env_names_from_source())

    assert legacy_settings.valid_env_names() == derived


def test_legacy_replacements_are_valid():
    """The replacement column is what every legacy WARNING tells an operator to use; a
    typo there would send them to another dead name (review M3)."""
    leaves = _config_key_paths()
    source_names = _valid_env_names_from_source()
    bad = []
    for entry in LEGACY_SETTING_NAMES:
        if entry.replacement is None:
            if not entry.hint:
                bad.append(f"{entry.name}: no replacement and no hint")
            continue
        if entry.source == "config":
            if tuple(entry.replacement.split(".")) not in leaves:
                bad.append(f"{entry.name} -> {entry.replacement}")
            continue
        names = ENV_NAME_PATTERN.findall(entry.replacement)
        if len(names) != 1 or not _is_valid_env_name(names[0], leaves, source_names):
            bad.append(f"{entry.name} -> {entry.replacement}")

    assert not bad, (
        "legacy rows whose replacement is not a valid name:\n  " + "\n  ".join(bad)
    )


def test_history_scan_refuses_an_unattributable_header(tmp_path):
    """A C-quoted path cannot be attributed to a file; the scan fails rather than carry
    the previous file's vendored/in-scope state over to it (review L3)."""
    _repo_with_precommit_config(tmp_path)
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / 'quo"ted.md').write_text("TRAEFIK_CERTIFICATE_EXPORTER_X=1\n")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "quoted")

    with pytest.raises(pytest.fail.Exception, match="cannot attribute"):
        _history_names(tmp_path)


def test_every_long_option_is_in_readme():
    """The README usage block is a copy of `--help`; every long flag must be in it.

    Derived from the parser itself, so a new flag is covered without editing this test.
    """
    from traefik_certificate_exporter.libs.cli_args import globalArgParser

    readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
    long_options = [
        option
        for action in globalArgParser._actions
        for option in action.option_strings
        if option.startswith("--")
    ]

    assert "--data-path" in long_options
    missing = [option for option in long_options if option not in readme]
    assert not missing, missing


# A Docker socket bind mount in any shipped sample must carry the host-root warning
# (EC-001, RT-3 of E014-S01 closure). The scope is every text file under docker/ plus
# the repo's own markdown, globbed rather than listed, so a new sample is covered too.
_SOCKET_MOUNT = re.compile(r"[\w/.-]*docker\.sock:/var/run/docker\.sock")
_SOCKET_WARNING = "host-root-equivalent"


def _socket_mount_scope() -> list[Path]:
    files = [p for p in (PROJECT_ROOT / "docker").rglob("*") if p.is_file()]
    files += list(PROJECT_ROOT.glob("*.md"))
    files += list((PROJECT_ROOT / "docs").rglob("*.md"))
    return files


def test_every_docker_socket_mount_carries_the_host_root_warning():
    scope = _socket_mount_scope()
    mounts = []
    for path in scope:
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for number, line in enumerate(text.splitlines(), start=1):
            if _SOCKET_MOUNT.search(line):
                mounts.append((path.relative_to(PROJECT_ROOT), number, line))

    # Guards the guard: the samples are known to mount the socket, so an empty match
    # means the scope or pattern broke, not that the rule holds.
    assert any(str(p) == "docker/docker-compose.yml" for p, _, _ in mounts), mounts
    unwarned = [f"{p}:{n}" for p, n, line in mounts if _SOCKET_WARNING not in line]
    assert not unwarned, unwarned


if __name__ == "__main__":
    # The regeneration command named above `LEGACY_BLOCK_BEGIN`.
    print(render_legacy_table())
