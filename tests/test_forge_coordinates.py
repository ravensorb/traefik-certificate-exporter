"""Behavioural cases for the forge-coordinate validator.

These exist because the rule they check is *not* checkable any other way. Left inline in
a workflow `run:` block the only available "test" would be grepping the workflow for its
own regex, which asserts nothing about what that regex accepts (story E008-S01-001, F9).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

PROJECT_ROOT = Path(__file__).parents[1]


def _load() -> Any:
    location = PROJECT_ROOT / "scripts" / "forge_coordinates.py"
    spec = importlib.util.spec_from_file_location("forge_coordinates", location)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Registered before execution: `@dataclass` resolves annotations through
    # `sys.modules[cls.__module__]`, which is absent for a module loaded by spec alone.
    sys.modules["forge_coordinates"] = module
    spec.loader.exec_module(module)
    return module


forge_coordinates = _load()

GITEA = "https://git.example.com"
GITEA_ACTIONS = "true"


def test_github_context_derives_ghcr_and_no_forge_package_index() -> None:
    coordinates = forge_coordinates.derive(
        server_url="https://github.com",
        repository="ravensorb/Traefik-Certificate-Exporter",
    )
    assert coordinates.forge == "github"
    assert coordinates.registry == "ghcr.io"
    assert (
        coordinates.image_repository == "ghcr.io/ravensorb/traefik-certificate-exporter"
    )
    # Absent by host capability, not disabled by toggle. The two are recorded distinctly
    # because conflating them hides a regression (ADR-0011 §2).
    assert coordinates.package_index_supported is False
    assert coordinates.package_index_url == ""


def test_gitea_context_derives_the_server_registry_and_a_package_index() -> None:
    coordinates = forge_coordinates.derive(
        server_url=GITEA, repository="ravensorb/exporter", gitea_actions=GITEA_ACTIONS
    )
    assert coordinates.forge == "gitea"
    assert coordinates.registry == "git.example.com"
    assert coordinates.package_index_supported is True
    assert coordinates.package_index_url == (
        "https://git.example.com/api/packages/ravensorb/pypi"
    )


def test_an_unknown_forge_fails_closed_rather_than_guessing_a_registry() -> None:
    with pytest.raises(SystemExit) as failure:
        forge_coordinates.derive(
            server_url="https://github.enterprise.example/", repository="owner/name"
        )
    assert "unknown forge" in str(failure.value)


def test_a_gitea_runner_is_recognised_by_its_own_environment_flag() -> None:
    assert (
        forge_coordinates.detect_forge("https://git.example.com", gitea_actions="TRUE")
        == "gitea"
    )
    assert forge_coordinates.detect_forge("https://github.com") == "github"


@pytest.mark.parametrize(
    "override",
    [
        "user@git.example.com",  # userinfo
        "user:secret@git.example.com",  # userinfo with a password
        "git.example.com/v2",  # path
        "git.example.com/",  # bare trailing path
        "git.example.com?token=1",  # query
        "git.example.com#fragment",  # fragment
        "https://git.example.com",  # scheme
        "registry.evil.example",  # foreign host
        "git.example.com:notaport",  # unparseable port
        "git.example.com 1",  # embedded whitespace
    ],
)
def test_the_registry_override_rejects_everything_that_is_not_a_bare_authority(
    override: str,
) -> None:
    with pytest.raises(SystemExit):
        forge_coordinates.derive(
            server_url=GITEA,
            repository="owner/name",
            registry_override=override,
            gitea_actions=GITEA_ACTIONS,
        )


def test_an_override_that_is_present_but_empty_is_rejected_by_the_validator() -> None:
    # `derive` treats an empty string as absence, because that is what an unset
    # repository variable interpolates to. The validator itself still refuses it, so a
    # caller that passes an empty override deliberately gets an error, not a default.
    with pytest.raises(SystemExit):
        forge_coordinates.validate_registry_override(
            "  ", permitted_hosts=frozenset({"git.example.com"})
        )


def test_the_registry_override_accepts_a_same_forge_host_and_port() -> None:
    coordinates = forge_coordinates.derive(
        server_url=GITEA,
        repository="owner/name",
        registry_override="git.example.com:3000",
        gitea_actions=GITEA_ACTIONS,
    )
    assert coordinates.registry == "git.example.com:3000"
    assert coordinates.image_repository == "git.example.com:3000/owner/name"


def test_the_override_is_anchored_so_a_suffix_match_is_not_a_same_forge_match() -> None:
    # `notgit.example.com` ends with the forge host. An unanchored pattern accepts it;
    # this is the violation planted against the coordinate rule.
    with pytest.raises(SystemExit):
        forge_coordinates.derive(
            server_url=GITEA,
            repository="owner/name",
            registry_override="notgit.example.com",
            gitea_actions=GITEA_ACTIONS,
        )
    with pytest.raises(SystemExit):
        forge_coordinates.derive(
            server_url=GITEA,
            repository="owner/name",
            registry_override="git.example.com.evil.net",
            gitea_actions=GITEA_ACTIONS,
        )


def test_github_may_only_be_overridden_to_its_own_registry() -> None:
    coordinates = forge_coordinates.derive(
        server_url="https://github.com",
        repository="owner/name",
        registry_override="ghcr.io",
    )
    assert coordinates.registry == "ghcr.io"
    with pytest.raises(SystemExit):
        forge_coordinates.derive(
            server_url="https://github.com",
            repository="owner/name",
            registry_override="docker.io",
        )


def test_an_absent_override_leaves_the_derived_registry_untouched() -> None:
    for absent in (None, "", "   "):
        coordinates = forge_coordinates.derive(
            server_url=GITEA,
            repository="owner/name",
            registry_override=absent,
            gitea_actions=GITEA_ACTIONS,
        )
        assert coordinates.registry == "git.example.com"


def test_a_malformed_repository_is_rejected() -> None:
    for repository in ("", "name", "owner/name/extra", "/name", "owner/"):
        with pytest.raises(SystemExit):
            forge_coordinates.derive(
                server_url="https://github.com", repository=repository
            )


def test_output_lines_carry_every_coordinate_a_publisher_consumes() -> None:
    coordinates = forge_coordinates.derive(
        server_url="https://github.com", repository="owner/name"
    )
    rendered = dict(line.split("=", 1) for line in coordinates.as_output_lines())
    assert rendered == {
        "forge": "github",
        "server-host": "github.com",
        "registry": "ghcr.io",
        "image-repository": "ghcr.io/owner/name",
        "package-index-supported": "false",
        "package-index-url": "",
    }


def test_the_cli_appends_outputs_to_the_named_file(tmp_path: Path) -> None:
    output = tmp_path / "github-output"
    exit_code = forge_coordinates.main(
        [
            "--server-url",
            "https://github.com",
            "--repository",
            "owner/name",
            "--output",
            str(output),
        ]
    )
    assert exit_code == 0
    assert "registry=ghcr.io" in output.read_text(encoding="utf-8").splitlines()


def test_an_ipv6_forge_keeps_its_brackets_and_can_still_be_overridden() -> None:
    # `::1` splits on its own colons under any `partition(":")` treatment of an
    # authority, so hostname and authority are kept as separate things.
    coordinates = forge_coordinates.derive(
        server_url="https://[::1]:3000",
        repository="owner/name",
        gitea_actions=GITEA_ACTIONS,
    )
    assert coordinates.registry == "[::1]:3000"
    assert coordinates.image_repository == "[::1]:3000/owner/name"
    overridden = forge_coordinates.derive(
        server_url="https://[::1]:3000",
        repository="owner/name",
        registry_override="[::1]:5000",
        gitea_actions=GITEA_ACTIONS,
    )
    assert overridden.registry == "[::1]:5000"


def test_a_ported_forge_may_be_overridden_to_another_port_on_the_same_host() -> None:
    coordinates = forge_coordinates.derive(
        server_url="https://git.example.com:8443",
        repository="owner/name",
        registry_override="git.example.com:3000",
        gitea_actions=GITEA_ACTIONS,
    )
    assert coordinates.registry == "git.example.com:3000"
