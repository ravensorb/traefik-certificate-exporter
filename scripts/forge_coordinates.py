#!/usr/bin/env python3
"""Host-neutral forge coordinate derivation and override validation (CI-AR6).

Every publishing workflow needs the same three answers: which forge is this, which
container registry does it publish images to, and does it host a Python package index.
On GitHub two of those are constants; on Gitea all three depend on the server the run
is executing against. ``FORGE_REGISTRY`` is the documented override for the one case
where safe derivation is impossible -- a Gitea deployment whose registry answers on a
different port from its web UI.

The override is a ``host[:port]`` authority, and validating it is URL parsing, not
pattern matching. A hand-written regex for "host, optional port, nothing else" is the
kind of thing that accepts ``registry.example.com@evil.example.net`` because the author
forgot userinfo exists. ``urllib.parse.urlsplit`` already knows about userinfo, ports,
paths, queries, fragments and IPv6 literals, so it does the parsing and this module
decides only which of its findings are acceptable.

Fail-closed is the whole point: an unrecognised forge raises rather than guessing a
registry, because guessing means publishing an immutable artifact to the wrong place.
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

GITHUB_HOST = "github.com"
GITHUB_REGISTRY = "ghcr.io"

FORGE_GITHUB = "github"
FORGE_GITEA = "gitea"


class ForgeError(SystemExit):
    """Raised for every unusable coordinate. Exits non-zero rather than defaulting."""

    def __init__(self, message: str) -> None:
        super().__init__(f"forge coordinates error: {message}")


@dataclass(frozen=True)
class ForgeCoordinates:
    """Everything a publisher needs to address the active forge."""

    forge: str
    server_host: str
    registry: str
    image_repository: str
    package_index_supported: bool
    package_index_url: str

    def as_output_lines(self) -> list[str]:
        """``name=value`` lines for ``$GITHUB_OUTPUT``."""
        return [
            f"forge={self.forge}",
            f"server-host={self.server_host}",
            f"registry={self.registry}",
            f"image-repository={self.image_repository}",
            f"package-index-supported={str(self.package_index_supported).lower()}",
            f"package-index-url={self.package_index_url}",
        ]


def _server_authority(server_url: str) -> tuple[str, str]:
    """``(hostname, authority)`` of the forge web server.

    The two are different for an IPv6 literal and for a non-default port, and conflating
    them is how a host comparison ends up splitting ``::1`` on its first colon. The
    hostname is what "same forge" is decided against; the authority is what a registry
    reference is written with.
    """
    if not server_url:
        raise ForgeError("server URL is empty; coordinates cannot be derived")
    parts = urlsplit(server_url)
    if parts.scheme not in {"http", "https"}:
        raise ForgeError(f"server URL must be http(s), got {server_url!r}")
    if parts.hostname is None:
        raise ForgeError(f"server URL has no host: {server_url!r}")
    hostname = parts.hostname.lower()
    authority = f"[{hostname}]" if ":" in hostname else hostname
    if parts.port is not None:
        authority = f"{authority}:{parts.port}"
    return hostname, authority


def _server_host(server_url: str) -> str:
    """Authority (host, with port and IPv6 brackets when present) of the forge server."""
    return _server_authority(server_url)[1]


def detect_forge(server_url: str, *, gitea_actions: str | None = None) -> str:
    """Name the forge, or fail closed.

    ``GITEA_ACTIONS`` is set by Gitea's act_runner and by nothing else; ``github.com``
    identifies GitHub. Anything else -- a GitHub Enterprise host, an unrecognised
    self-hosted forge, a runner whose environment was not what we assumed -- raises.
    Defaulting to "probably Gitea" here would publish immutable artifacts against a
    registry nobody chose.
    """
    if (gitea_actions or "").strip().lower() == "true":
        return FORGE_GITEA
    host = _server_host(server_url)
    if host == GITHUB_HOST:
        return FORGE_GITHUB
    raise ForgeError(
        f"unknown forge for server {server_url!r}: expected {GITHUB_HOST} or a Gitea "
        f"runner setting GITEA_ACTIONS=true"
    )


def validate_registry_override(value: str, *, permitted_hosts: frozenset[str]) -> str:
    """Return the normalised ``host[:port]`` authority, or raise.

    Accepts a bare authority only. A scheme, userinfo, path, query or fragment is
    rejected outright rather than stripped: an override that was meant to carry one is
    an override whose author expected different behaviour from the one they will get.
    """
    candidate = value.strip()
    if not candidate:
        raise ForgeError("FORGE_REGISTRY is set but empty")
    if "://" in candidate:
        raise ForgeError(
            f"FORGE_REGISTRY must be a bare host[:port], not a URL: {value!r}"
        )
    if any(character.isspace() for character in candidate):
        raise ForgeError(f"FORGE_REGISTRY must contain no whitespace: {value!r}")
    parts = urlsplit(f"//{candidate}")
    if parts.path or parts.query or parts.fragment:
        raise ForgeError(
            f"FORGE_REGISTRY must carry no path, query or fragment: {value!r}"
        )
    if parts.username is not None or parts.password is not None:
        raise ForgeError(f"FORGE_REGISTRY must carry no userinfo: {value!r}")
    try:
        port = parts.port
    except ValueError as error:
        raise ForgeError(f"FORGE_REGISTRY has an invalid port: {value!r}") from error
    if parts.hostname is None or not parts.hostname:
        raise ForgeError(f"FORGE_REGISTRY has no host: {value!r}")
    host = parts.hostname.lower()
    if host not in permitted_hosts:
        raise ForgeError(
            f"FORGE_REGISTRY {value!r} names {host!r}, which is not part of this forge "
            f"(permitted: {', '.join(sorted(permitted_hosts))})"
        )
    if ":" in host:  # IPv6 literal; urlsplit strips the brackets it was given.
        host = f"[{host}]"
    return host if port is None else f"{host}:{port}"


def _split_repository(repository: str) -> tuple[str, str]:
    owner, separator, name = repository.partition("/")
    if not separator or not owner or not name or "/" in name:
        raise ForgeError(f"repository must be 'owner/name', got {repository!r}")
    return owner.lower(), name.lower()


def derive(
    *,
    server_url: str,
    repository: str,
    registry_override: str | None = None,
    gitea_actions: str | None = None,
) -> ForgeCoordinates:
    """Derive every coordinate from action context, honouring the documented override."""
    forge = detect_forge(server_url, gitea_actions=gitea_actions)
    server_hostname, server_host = _server_authority(server_url)
    owner, name = _split_repository(repository)

    if forge == FORGE_GITHUB:
        default_registry = GITHUB_REGISTRY
        default_registry_hostname = GITHUB_REGISTRY
        package_index_supported = False
        package_index_url = ""
    else:
        default_registry = server_host
        default_registry_hostname = server_hostname
        package_index_supported = True
        package_index_url = f"{server_url.rstrip('/')}/api/packages/{owner}/pypi"

    registry = default_registry
    if registry_override is not None and registry_override.strip():
        # Hostnames, never authorities: the port may legitimately differ, which is the
        # whole reason FORGE_REGISTRY exists.
        permitted = frozenset({server_hostname, default_registry_hostname})
        registry = validate_registry_override(
            registry_override, permitted_hosts=permitted
        )

    return ForgeCoordinates(
        forge=forge,
        server_host=server_host,
        registry=registry,
        image_repository=f"{registry}/{owner}/{name}",
        package_index_supported=package_index_supported,
        package_index_url=package_index_url,
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server-url", required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--registry-override", default="")
    parser.add_argument(
        "--output",
        default=os.environ.get("GITHUB_OUTPUT", ""),
        help="File to append `name=value` lines to; stdout when empty.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _build_parser().parse_args(argv)
    coordinates = derive(
        server_url=arguments.server_url,
        repository=arguments.repository,
        registry_override=arguments.registry_override,
        gitea_actions=os.environ.get("GITEA_ACTIONS"),
    )
    rendered = "\n".join(coordinates.as_output_lines())
    if arguments.output:
        with Path(arguments.output).open("a", encoding="utf-8") as stream:
            stream.write(f"{rendered}\n")
    else:
        print(rendered)
    return 0


if __name__ == "__main__":
    sys.exit(main())
