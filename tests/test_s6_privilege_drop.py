"""The container's privilege decision, executed where it is actually written.

The decision is EXECUTED, not grepped: the decision helper the init script sources
(`privilege-decision.sh`) runs under bash with a stub `s6-setuidgid` first on PATH; the init
script and the service script run as copies with their state directory, helper path and
interpreter substituted; and the embedded Python resolver is extracted and run with this
interpreter. The stub decides from fixture-controlled lists rather than real permission bits,
so the results do not depend on the uid running the suite (CI may be root, where every file
is readable) — and it fails the test if the helper probes as the wrong user or with the wrong
test operator. A few properties that only exist as script text (symlink-safe chown, the
fail-safe written before the resolver runs) are still asserted against the source.

The rule under test (ADR-0030, amended 2026-10-10): the service drops to `abc` only when it
is proven able to read every ACME store file and write the output path; anything unproven
keeps root with exactly one WARNING.
"""

import os
import re
import stat
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
S6_ROOT = PROJECT_ROOT / "docker" / "root" / "etc" / "s6-overlay" / "s6-rc.d"
INIT_SCRIPT = S6_ROOT / "init-traefik-certificate-exporter-config" / "run"
SVC_SCRIPT = S6_ROOT / "svc-traefik-certificate-exporter" / "run"
HELPER = (
    PROJECT_ROOT
    / "docker"
    / "root"
    / "usr"
    / "local"
    / "lib"
    / "traefik-certificate-exporter"
    / "privilege-decision.sh"
)


def _embedded_python() -> str:
    lines = INIT_SCRIPT.read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(lines) if "<<'PY'" in line) + 1
    end = next(i for i, line in enumerate(lines) if i >= start and line == "PY")
    return "\n".join(lines[start:end])


def _resolve(tmp_path: Path, config: str | None, env: dict | None = None):
    """Run the init script's own resolver and return (exit code, written lines)."""
    configFile = tmp_path / "config.yaml"
    if config is not None:
        configFile.write_text(config, encoding="utf-8")
    resolved = tmp_path / "resolved-settings"

    childEnv = {
        "TCE_CONFIG_FILE": str(configFile),
        "TCE_RESOLVED_OUT": str(resolved),
        "PATH": "/usr/bin:/bin",
        # Keep confuse's application directory inside the test's own tmp tree.
        "HOME": str(tmp_path),
        "TRAEFIK_CERTIFICATE_EXPORTER_LOGGING_CONSOLEONLY": "true",
    }
    childEnv.update(env or {})

    result = subprocess.run(
        [sys.executable, "-c", _embedded_python()],
        capture_output=True,
        text=True,
        env=childEnv,
        cwd=tmp_path,
        check=False,
    )
    written = (
        resolved.read_text(encoding="utf-8").splitlines() if resolved.exists() else []
    )
    return result.returncode, written


@pytest.mark.parametrize(
    ("config", "expected"),
    [
        ("settings:\n  restartcontainers: true\n", "true"),
        ("settings:\n  restartcontainers: false\n", "false"),
        ("settings:\n  datapath: /data\n", "false"),
        ("", "false"),
    ],
)
def test_config_file_drives_the_privilege_decision(tmp_path, config, expected):
    code, written = _resolve(tmp_path, config)

    assert code == 0
    assert written[0] == expected


@pytest.mark.parametrize(
    ("env_value", "expected"), [("true", "true"), ("yes", "true"), ("false", "false")]
)
def test_environment_overlays_the_config_file(tmp_path, env_value, expected):
    code, written = _resolve(
        tmp_path,
        "settings:\n  restartcontainers: false\n",
        env={"TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_RESTARTCONTAINERS": env_value},
    )

    assert code == 0
    assert written[0] == expected


def test_environment_can_enable_root_without_a_config_file(tmp_path):
    code, written = _resolve(
        tmp_path,
        config=None,
        env={"TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_RESTARTCONTAINERS": "true"},
    )

    assert code == 0
    assert written[0] == "true"


def test_the_resolver_is_the_application_not_a_second_parser():
    """Finding 6: a value the application reads as true and the init script as false drops
    privileges out from under a configuration that needs the Docker socket. The only way to
    be sure the two agree is for there to be one of them."""
    body = INIT_SCRIPT.read_text(encoding="utf-8")

    assert "SettingsManager" in body
    assert "import yaml" not in body and "safe_load" not in body, (
        "the init script must ask the installed package, not parse the config itself"
    )


def test_the_output_and_data_paths_are_resolved_not_assumed(tmp_path):
    """Findings 4 and 5: /certs and /data are the image's defaults, not its values."""
    code, written = _resolve(
        tmp_path,
        "settings:\n  outputpath: /elsewhere/certs\n  datapath: /elsewhere/acme\n"
        "  filespec: 'acme-*.json'\n",
    )

    assert code == 0
    assert written[1] == "/elsewhere/certs"
    assert written[2] == "/elsewhere/acme"
    assert written[3] == "acme-*.json"


def test_resolver_emits_the_applications_own_glob_matches(tmp_path):
    """Lines 5+ are what `glob.glob(datapath/filespec)` returns — sorted, absolute, no
    dotfiles — so the shell never re-derives the match set with its own glob."""
    data = tmp_path / "acme"
    data.mkdir()
    for name in ("b.json", "a.json", ".hidden.json", "note.txt"):
        (data / name).write_text("{}", encoding="utf-8")

    code, written = _resolve(
        tmp_path, f"settings:\n  datapath: {data}\n  filespec: '*.json'\n"
    )

    assert code == 0
    assert written[4:] == [str(data / "a.json"), str(data / "b.json")]


def test_resolver_writes_exactly_four_lines_when_nothing_matches(tmp_path):
    data = tmp_path / "acme"
    data.mkdir()

    code, written = _resolve(tmp_path, f"settings:\n  datapath: {data}\n")

    assert code == 0
    assert len(written) == 4


def test_resolver_writes_nothing_for_a_path_containing_a_newline(tmp_path):
    data = tmp_path / "acme"
    data.mkdir()
    (data / "bad\nname.json").write_text("{}", encoding="utf-8")

    code, written = _resolve(tmp_path, f"settings:\n  datapath: {data}\n")

    assert code != 0
    assert written == []
    assert list(tmp_path.glob(".resolved-*")) == [], "no partial file is left behind"


@pytest.mark.parametrize(
    "config",
    [
        "settings:\n  restartcontainers: [unclosed\n",
        # `settings:` with no mapping under it is rejected by the application too; the
        # container must not paper over a config the exporter itself will refuse.
        "settings:\n",
    ],
)
def test_malformed_config_writes_nothing_so_the_container_keeps_root(tmp_path, config):
    code, written = _resolve(tmp_path, config)

    assert code != 0
    assert written == [], (
        "a failed resolution must leave no answer at all, so the decision helper reads it "
        "as unresolved and the container keeps the already-written root default"
    )


# --------------------------------------------------------------------------------------
# The decision helper, executed.
# --------------------------------------------------------------------------------------

# Records every invocation, then answers from fixture lists. It also polices the probe:
# wrong user, wrong shape, `-x` on a file, or anything but `-w` on the output path is
# recorded as a VIOLATION and exits 99.
STUB_S6_SETUIDGID = r"""#!/bin/bash
user="$1"
shift
{ printf '%s' "$user"; printf '\t%s' "$@"; printf '\n'; } >> "$TCE_TEST_STUB_LOG"
if [ "${TCE_TEST_MODE-}" = passthrough ]; then
    exec "$@"
fi
violation() {
    printf 'VIOLATION %s\n' "$*" >> "$TCE_TEST_STUB_LOG"
    exit 99
}
if [ -n "${TCE_TEST_UNKNOWN_USER-}" ]; then
    echo "s6-envuidgid: fatal: unknown user: $user" >&2
    exit 1
fi
[ "$user" = "$TCE_TEST_EXPECT_USER" ] || violation "user $user"
{ [ "$#" -eq 3 ] && [ "$1" = test ]; } || violation "shape $*"
op="$2"
path="$3"
listed() { [ -f "$1" ] && grep -Fxq -- "$path" "$1"; }
case "$op" in
    -r)
        [ "$path" != "${TCE_TEST_OUTPUT-}" ] || violation "-r on output path"
        listed "$TCE_TEST_UNREADABLE" && exit 1
        exit 0
        ;;
    -x)
        [ -d "$path" ] || violation "-x on non-directory $path"
        listed "$TCE_TEST_UNREADABLE" && exit 1
        exit 0
        ;;
    -w)
        if [ "$path" = "${TCE_TEST_OUTPUT-}" ]; then
            listed "$TCE_TEST_UNWRITABLE" && exit 1
            exit 0
        fi
        listed "$TCE_TEST_WRITABLE" && exit 0
        exit 1
        ;;
    -O)
        [ "$path" != "${TCE_TEST_OUTPUT-}" ] || violation "-O on output path"
        listed "$TCE_TEST_OWNED" && exit 0
        exit 1
        ;;
    *)
        violation "op $op"
        ;;
esac
"""


@pytest.fixture(autouse=True)
def _no_probe_violations(tmp_path):
    """The stub answers a malformed probe with exit 99, which the helper reads as "keep
    root" -- the very outcome most tests expect. So every test's stub log is checked here,
    not only where a test remembers to: a wrong-user or wrong-operator probe fails the test
    instead of passing as a correct root decision."""
    yield
    if (tmp_path / "stub.log").exists():
        _assert_no_violation(tmp_path)


def _stub_bin(tmp_path: Path) -> Path:
    binDir = tmp_path / "bin"
    binDir.mkdir(exist_ok=True)
    stub = binDir / "s6-setuidgid"
    stub.write_text(STUB_S6_SETUIDGID, encoding="utf-8")
    stub.chmod(stub.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return binDir


def _write_list(path: Path, entries) -> str:
    path.write_text("".join(f"{entry}\n" for entry in entries), encoding="utf-8")
    return str(path)


def _stub_env(
    tmp_path: Path, *, unreadable=(), writable=(), unwritable=(), owned=(), output=""
):
    env = {
        "PATH": f"{_stub_bin(tmp_path)}:/usr/bin:/bin",
        "TCE_TEST_STUB_LOG": str(tmp_path / "stub.log"),
        "TCE_TEST_EXPECT_USER": "abc",
        "TCE_TEST_UNREADABLE": _write_list(tmp_path / "unreadable", unreadable),
        "TCE_TEST_WRITABLE": _write_list(tmp_path / "writable", writable),
        "TCE_TEST_UNWRITABLE": _write_list(tmp_path / "unwritable", unwritable),
        "TCE_TEST_OWNED": _write_list(tmp_path / "owned", owned),
        "TCE_TEST_OUTPUT": output,
    }
    (tmp_path / "stub.log").touch()
    return env


def _probes(tmp_path: Path) -> list[list[str]]:
    return [
        line.split("\t")
        for line in (tmp_path / "stub.log").read_text(encoding="utf-8").splitlines()
    ]


def _decide(
    tmp_path: Path,
    *,
    restart="false",
    files=("acme.json",),
    unreadable=(),
    writable=(),
    owned=(),
    data_exists=True,
    resolved_lines=None,
    trailing_newline=True,
    extra_env=None,
):
    """Run tce_privilege_decision against a fixture tree; return (rc, stdout, stderr)."""
    data = tmp_path / "data"
    if data_exists:
        data.mkdir()
    paths = []
    for name in files:
        (data / name).write_text("{}", encoding="utf-8")
        paths.append(str(data / name))

    if resolved_lines is None:
        resolved_lines = [restart, str(tmp_path / "certs"), str(data), "*.json", *paths]
    resolved = tmp_path / "resolved-settings"
    body = "\n".join(resolved_lines) + ("\n" if trailing_newline else "")
    if resolved_lines:
        resolved.write_text(body, encoding="utf-8")

    def expand(names):
        return [n if n.startswith("/") else str(data / n) for n in names]

    env = _stub_env(
        tmp_path,
        unreadable=expand(unreadable),
        writable=expand(writable),
        owned=expand(owned),
    )
    env.update(extra_env or {})
    result = subprocess.run(
        [
            "bash",
            "-c",
            'source "$1"; tce_privilege_decision "$2" abc',
            "_",
            str(HELPER),
            str(resolved),
        ],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    return result.returncode, result.stdout, result.stderr


def _assert_no_violation(tmp_path: Path) -> None:
    log = (tmp_path / "stub.log").read_text(encoding="utf-8")
    assert "VIOLATION" not in log, log
    for probe in _probes(tmp_path):
        assert probe[0] == "abc", probe


def _assert_root(stdout: str, stderr: str, *anchors: str) -> None:
    assert stdout == "true\n"
    warnings = [line for line in stderr.splitlines() if line.startswith("WARNING:")]
    assert len(warnings) == 1, stderr
    assert warnings[0].startswith("WARNING: running as root"), stderr
    for anchor in anchors:
        assert anchor in warnings[0], (anchor, stderr)
    assert "relax" not in stderr.lower()
    assert "group permission" not in stderr.lower()


def test_drop_when_every_store_file_is_readable(tmp_path):
    rc, out, err = _decide(tmp_path, files=("acme.json", "other.json"))

    assert rc == 0
    assert out == "false\n"
    assert err == ""
    _assert_no_violation(tmp_path)
    reads = [p[3] for p in _probes(tmp_path) if p[1:3] == ["test", "-r"]]
    data = str(tmp_path / "data")
    assert reads == [
        data,
        str(tmp_path / "data/acme.json"),
        str(tmp_path / "data/other.json"),
    ]
    dirOps = {p[2] for p in _probes(tmp_path) if p[3] == data}
    assert {"-r", "-x"} <= dirOps, "the data path must be probed as listable (r and x)"


def test_root_when_one_store_file_is_unreadable(tmp_path):
    rc, out, err = _decide(
        tmp_path, files=("acme.json", "other.json"), unreadable=("acme.json",)
    )

    assert rc == 0
    _assert_root(out, err, "not readable by", "PUID/PGID", "0600", "restartcontainers")
    assert f"'{tmp_path / 'data/acme.json'}'" in err
    assert "other.json" not in err
    _assert_no_violation(tmp_path)


@pytest.mark.parametrize(
    ("case", "kwargs", "anchors"),
    [
        ("no matches", {"files": ()}, ("no file matches", "PUID/PGID")),
        (
            "data path absent",
            {"files": (), "data_exists": False},
            ("cannot list", "PUID/PGID"),
        ),
        ("data path denied", {"unreadable": ("/DATA",)}, ("cannot list", "PUID/PGID")),
        ("restartcontainers", {"restart": "true"}, ("restartcontainers", "socket")),
        ("resolved file missing", {"resolved_lines": []}, ("could not resolve",)),
        (
            "two-line file",
            {"resolved_lines": ["false", "/certs"]},
            ("could not resolve",),
        ),
        (
            "line 1 garbage",
            {"resolved_lines": ["maybe", "/c", "/d", "*.json"]},
            ("could not resolve",),
        ),
        (
            "relative data path",
            {"resolved_lines": ["false", "/certs", "data", "*.json"]},
            ("could not resolve",),
        ),
        (
            "relative output path",
            {"resolved_lines": ["false", "certs", "/data", "*.json"]},
            ("could not resolve", "settings.outputpath"),
        ),
        (
            "restartcontainers outranks a relative data path",
            {"resolved_lines": ["true", "/certs", "data", "*.json"]},
            ("settings.restartcontainers is enabled",),
        ),
        (
            "unknown user",
            {"extra_env": {"TCE_TEST_UNKNOWN_USER": "1"}},
            ("cannot list",),
        ),
    ],
)
def test_every_unproven_case_keeps_root_with_one_warning(
    tmp_path, case, kwargs, anchors
):
    if kwargs.get("unreadable") == ("/DATA",):
        kwargs = {**kwargs, "unreadable": (str(tmp_path / "data"),)}

    rc, out, err = _decide(tmp_path, **kwargs)

    assert rc == 0, case
    _assert_root(out, err, *anchors)
    if "TCE_TEST_UNKNOWN_USER" not in (kwargs.get("extra_env") or {}):
        _assert_no_violation(tmp_path)


def test_restartcontainers_wins_even_when_the_store_is_readable(tmp_path):
    rc, out, err = _decide(tmp_path, restart="true")

    assert rc == 0
    _assert_root(out, err, "settings.restartcontainers is enabled")
    assert _probes(tmp_path) == [], "the socket path needs root; nothing else is probed"


def test_a_file_name_with_a_space_is_probed_once_and_reported_whole(tmp_path):
    rc, out, err = _decide(
        tmp_path, files=("my store.json",), unreadable=("my store.json",)
    )
    assert rc == 0

    _assert_root(out, err, "not readable by")
    assert f"'{tmp_path / 'data/my store.json'}'" in err
    reads = [p for p in _probes(tmp_path) if p[1:3] == ["test", "-r"]]
    assert [p[3] for p in reads][1:] == [str(tmp_path / "data/my store.json")]


def test_the_last_path_is_probed_without_a_trailing_newline(tmp_path):
    rc, out, err = _decide(
        tmp_path,
        files=("a.json", "z.json"),
        unreadable=("z.json",),
        trailing_newline=False,
    )
    assert rc == 0

    _assert_root(out, err, "not readable by")
    assert "z.json" in err


def test_a_writable_store_is_noted_as_info_when_dropping(tmp_path):
    rc, out, err = _decide(tmp_path, writable=("acme.json",))
    assert rc == 0

    assert out == "false\n"
    lines = err.splitlines()
    assert len(lines) == 1, err
    assert lines[0].startswith("INFO:")
    assert "writable by abc" in lines[0] and ":ro" in lines[0]
    assert "WARNING" not in err


def test_an_owned_store_on_a_writable_mount_counts_as_writable(tmp_path):
    """An owner can chmod a 0400 file back to writable, so ownership is a lever too --
    unless the mount is read-only, which the root-side `[ -w ]` detects."""
    rc, out, err = _decide(tmp_path, owned=("acme.json",))

    assert rc == 0
    assert out == "false\n"
    assert err.startswith("INFO:") and ":ro" in err and "acme.json" in err
    owners = [p for p in _probes(tmp_path) if p[2] == "-O"]
    assert owners, "ownership must be probed as the service account"


def test_a_writable_store_is_appended_to_the_root_warning(tmp_path):
    rc, out, err = _decide(
        tmp_path,
        files=("a.json", "b.json"),
        unreadable=("a.json",),
        writable=("b.json",),
    )
    assert rc == 0

    _assert_root(out, err, "not readable by")
    lines = err.splitlines()
    assert len(lines) == 2, err
    assert "writable by abc" in lines[1] and ":ro" in lines[1]
    assert "INFO" not in err


def test_output_path_probe_decides_row_six(tmp_path):
    output = tmp_path / "certs"
    output.mkdir()
    env = _stub_env(tmp_path, unwritable=[str(output)], output=str(output))
    script = 'source "$1"; tce_output_writable "$2" abc; echo "rc=$?"'

    denied = subprocess.run(
        ["bash", "-c", script, "_", str(HELPER), str(output)],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    env["TCE_TEST_UNWRITABLE"] = _write_list(tmp_path / "unwritable", [])
    allowed = subprocess.run(
        ["bash", "-c", script, "_", str(HELPER), str(output)],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )

    assert denied.stdout == "rc=1\n"
    assert denied.stderr.startswith("WARNING: running as root")
    assert "cannot write" in denied.stderr and "PUID/PGID" in denied.stderr
    assert allowed.stdout == "rc=0\n" and allowed.stderr == ""
    _assert_no_violation(tmp_path)
    assert {p[2] for p in _probes(tmp_path)} == {"-w"}


def test_the_helper_leaves_the_callers_shell_options_alone(tmp_path):
    _decide(tmp_path)  # builds the fixture tree
    env = _stub_env(tmp_path)
    script = (
        'before="$-|$(shopt -p)"; source "$1"; tce_privilege_decision "$2" abc > /dev/null'
        ' 2>&1; after="$-|$(shopt -p)"; [ "$before" = "$after" ] && echo same'
    )
    result = subprocess.run(
        ["bash", "-c", script, "_", str(HELPER), str(tmp_path / "resolved-settings")],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )

    assert result.stdout == "same\n", result.stderr


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads mode-000 files")
def test_real_permissions_an_unreadable_file_keeps_root(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    store = data / "acme.json"
    store.write_text("{}", encoding="utf-8")
    store.chmod(0)
    resolved = tmp_path / "resolved-settings"
    resolved.write_text(
        f"false\n{tmp_path / 'certs'}\n{data}\n*.json\n{store}\n", encoding="utf-8"
    )
    env = _stub_env(tmp_path)
    env["TCE_TEST_MODE"] = "passthrough"
    try:
        result = subprocess.run(
            [
                "bash",
                "-c",
                'source "$1"; tce_privilege_decision "$2" abc',
                "_",
                str(HELPER),
                str(resolved),
            ],
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )
    finally:
        store.chmod(0o600)

    _assert_root(result.stdout, result.stderr, "not readable by")


# --------------------------------------------------------------------------------------
# The init script and the service script, executed as substituted copies.
# --------------------------------------------------------------------------------------


def _run_init(
    tmp_path: Path, *, helper: Path, resolved_fixture: str | None, unwritable=()
):
    """Run a copy of the init script with its paths moved under tmp_path.

    The embedded resolver's interpreter is replaced by a script that copies
    `resolved_fixture` into place (or fails when it is None)."""
    state = tmp_path / "state"
    output = tmp_path / "certs"
    output.mkdir(exist_ok=True)
    config = tmp_path / "config.yaml"
    config.write_text("settings: {}\n", encoding="utf-8")
    binDir = _stub_bin(tmp_path)
    chown = binDir / "chown"
    chown.write_text(
        f'#!/bin/sh\necho "chown $*" >> "{tmp_path / "chown.log"}"\n', encoding="utf-8"
    )
    chown.chmod(0o755)
    fakePython = binDir / "fake-python"
    if resolved_fixture is None:
        fakePython.write_text("#!/bin/sh\ncat > /dev/null\nexit 1\n", encoding="utf-8")
    else:
        fixture = tmp_path / "resolved-fixture"
        fixture.write_text(resolved_fixture, encoding="utf-8")
        fakePython.write_text(
            f'#!/bin/sh\ncat > /dev/null\ncp "{fixture}" "$TCE_RESOLVED_OUT"\n',
            encoding="utf-8",
        )
    fakePython.chmod(0o755)

    body = INIT_SCRIPT.read_text(encoding="utf-8")
    substitutions = {
        "CONFIG_FILE=/config/config.yaml": f"CONFIG_FILE={config}",
        "STATE_DIR=/run/traefik-certificate-exporter": f"STATE_DIR={state}",
        "PRIV_HELPER=/usr/local/lib/traefik-certificate-exporter/privilege-decision.sh": f"PRIV_HELPER={helper}",
        "PYTHON=/app/.venv/bin/python": f"PYTHON={fakePython}",
    }
    for old, new in substitutions.items():
        assert old in body, old
        body = body.replace(old, new)
    copy = tmp_path / "init-run"
    copy.write_text(body, encoding="utf-8")

    env = _stub_env(tmp_path, unwritable=unwritable, output=str(output))
    result = subprocess.run(
        ["bash", str(copy)], capture_output=True, text=True, env=env, check=False
    )
    return result, state


@pytest.mark.parametrize(
    "helper_body", [None, "tce_privilege_decision() { echo maybe; }\n"]
)
def test_init_keeps_root_when_the_decision_fails(tmp_path, helper_body):
    helper = tmp_path / "helper.sh"
    if helper_body is not None:
        helper.write_text(helper_body, encoding="utf-8")

    result, state = _run_init(tmp_path, helper=helper, resolved_fixture="false\n")

    assert result.returncode == 0
    assert (state / "run-as-root").read_text() == "true\n"
    assert "WARNING: running as root (privilege decision failed)" in result.stdout
    assert not (state / "run-as-root.tmp").exists()


def test_init_drops_when_the_real_helper_proves_the_store_readable(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    (data / "acme.json").write_text("{}", encoding="utf-8")
    fixture = f"false\n{tmp_path / 'certs'}\n{data}\n*.json\n{data / 'acme.json'}\n"

    result, state = _run_init(tmp_path, helper=HELPER, resolved_fixture=fixture)

    assert result.returncode == 0
    assert (state / "run-as-root").read_text() == "false\n"
    assert "WARNING" not in result.stdout + result.stderr
    assert (state / "home").is_dir()
    assert "chown -h abc:abc" in (tmp_path / "chown.log").read_text()
    _assert_no_violation(tmp_path)


def test_init_keeps_root_when_the_output_path_stays_unwritable(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    (data / "acme.json").write_text("{}", encoding="utf-8")
    fixture = f"false\n{tmp_path / 'certs'}\n{data}\n*.json\n{data / 'acme.json'}\n"

    result, state = _run_init(
        tmp_path,
        helper=HELPER,
        resolved_fixture=fixture,
        unwritable=[str(tmp_path / "certs")],
    )

    assert result.returncode == 0
    assert (state / "run-as-root").read_text() == "true\n"
    output = result.stdout + result.stderr
    assert output.count("WARNING:") == 1 and "cannot write" in output


def test_init_keeps_root_when_the_resolver_fails(tmp_path):
    result, state = _run_init(tmp_path, helper=HELPER, resolved_fixture=None)

    assert result.returncode == 0
    assert (state / "run-as-root").read_text() == "true\n"
    output = result.stdout + result.stderr
    assert output.count("WARNING:") == 1 and "could not resolve" in output


@pytest.mark.parametrize(
    ("state_value", "user", "dropped"),
    [
        (None, "root", False),
        ("true\n", "root", False),
        ("", "root", False),
        ("false\n", "abc", True),
    ],
)
def test_service_script_runs_as_root_unless_the_state_file_says_false(
    tmp_path, state_value, user, dropped
):
    state = tmp_path / "state"
    state.mkdir()
    if state_value is not None:
        (state / "run-as-root").write_text(state_value, encoding="utf-8")
    binDir = tmp_path / "bin"
    binDir.mkdir()
    log = tmp_path / "svc.log"
    stub = binDir / "s6-setuidgid"
    stub.write_text(f'#!/bin/sh\necho "$1 $HOME" >> "{log}"\n', encoding="utf-8")
    stub.chmod(0o755)
    exporter = binDir / "traefik-certificate-exporter"
    exporter.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    exporter.chmod(0o755)

    body = SVC_SCRIPT.read_text(encoding="utf-8")
    old = "STATE_DIR=/run/traefik-certificate-exporter"
    assert old in body
    copy = tmp_path / "svc-run"
    copy.write_text(body.replace(old, f"STATE_DIR={state}"), encoding="utf-8")

    result = subprocess.run(
        ["bash", str(copy)],
        capture_output=True,
        text=True,
        env={
            "PATH": f"{binDir}:/usr/bin:/bin",
            "HOME": "/root",
            "TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_WATCHFORCHANGES": "true",
        },
        check=False,
    )

    assert result.returncode == 0, result.stderr
    recordedUser, recordedHome = log.read_text().split()
    assert recordedUser == user
    assert (recordedHome == str(state / "home")) is dropped
    assert "WARNING" not in result.stdout, (
        "init owns the one privilege WARNING per start"
    )


# --------------------------------------------------------------------------------------
# Properties that exist only as script or document text.
# --------------------------------------------------------------------------------------


def test_init_script_writes_the_safe_default_before_consulting_the_config():
    body = INIT_SCRIPT.read_text(encoding="utf-8")

    safeDefault = body.index("printf 'true\\n' > \"${PRIV_STATE}\"")
    resolution = body.index('"${PYTHON}" -')

    assert safeDefault < resolution, (
        "the keep-root default must already be on disk before the settings are resolved, "
        "so any failure between the two leaves root, never an unproven drop"
    )
    assert 'rm -f "${RESOLVED}"' in body, (
        "a stale resolution from a previous boot must not be read as this boot's answer"
    )


def test_init_script_never_dereferences_a_symlink_when_taking_ownership():
    """Finding 3: `chown -R`/`lsiown -R` over an operator-writable volume is an
    arbitrary-chown primitive, because both follow symlinks."""
    body = INIT_SCRIPT.read_text(encoding="utf-8")

    assert not re.search(r"^\s*lsiown\b", body, re.MULTILINE), (
        "lsiown dereferences symlinks; it must not be invoked here"
    )
    assert not re.search(r"chown\s+(-\w*R\w*\s)", body), (
        "recursive chown must go through find, which can exclude symlinks"
    )
    assert "! -type l" in body and "-xdev" in body
    assert "chown -h" in body


def test_init_script_gives_the_dropped_account_a_usable_home():
    """Finding 1: s6-setuidgid changes the uid only, and confuse unconditionally creates
    its application directory under $HOME — which is root-owned 0700 in the base image."""
    body = INIT_SCRIPT.read_text(encoding="utf-8")

    assert 'mkdir -p "${SERVICE_HOME}"' in body
    assert 'chown "${SERVICE_USER}:${SERVICE_USER}" "${SERVICE_HOME}"' in body


def _shipped_text_files():
    """Every shipped file a user might read: the whole docker/ tree, README.md and
    docs/operational.md — walked, not listed, so a new file is covered automatically."""
    yield PROJECT_ROOT / "README.md"
    yield PROJECT_ROOT / "docs" / "operational.md"
    for path in sorted((PROJECT_ROOT / "docker").rglob("*")):
        if path.is_file():
            yield path


def test_no_shipped_file_recommends_relaxing_the_acme_store_permissions():
    """Traefik refuses an acme.json with any group/other bit set, so "relax their group
    permissions" is a remedy that breaks Traefik. `docs/adr/` is excluded on purpose:
    ADRs are historical records, and ADR-0030's amendment quotes the withdrawn
    "relax the group permission" remedy precisely in order to supersede it."""
    body = INIT_SCRIPT.read_text(encoding="utf-8")
    assert '. "${PRIV_HELPER}"' in body, (
        "the init script must source the decision helper"
    )

    pattern = re.compile(r"relax\w*\s+(their|the|its)?\s*group", re.IGNORECASE)
    offenders = []
    for path in _shipped_text_files():
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if pattern.search(text):
            offenders.append(str(path.relative_to(PROJECT_ROOT)))

    assert offenders == []


@pytest.mark.parametrize("doc", ["docs/operational.md", "docker/README.md"])
def test_docs_require_a_read_only_data_mount_for_unprivileged_mode(doc):
    paragraphs = (PROJECT_ROOT / doc).read_text(encoding="utf-8").split("\n\n")

    assert any(":ro" in p and "unprivileged" in p.lower() for p in paragraphs), doc


def test_the_two_scripts_agree_on_the_state_paths():
    initBody = INIT_SCRIPT.read_text(encoding="utf-8")
    svcBody = SVC_SCRIPT.read_text(encoding="utf-8")

    for line in ("STATE_DIR=/run/traefik-certificate-exporter",):
        assert line in initBody and line in svcBody

    assert 'PRIV_STATE="${STATE_DIR}/run-as-root"' in initBody
    assert 'PRIV_STATE="${STATE_DIR}/run-as-root"' in svcBody
    assert 'SERVICE_HOME="${STATE_DIR}/home"' in initBody
    assert 'SERVICE_HOME="${STATE_DIR}/home"' in svcBody
