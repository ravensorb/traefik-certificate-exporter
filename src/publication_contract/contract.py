"""Create and validate deterministic, secret-free publication evidence contracts."""

from __future__ import annotations

import hashlib
import json
import re
import tempfile
from collections.abc import Mapping, Sequence
from importlib import resources
from pathlib import Path
from typing import Any, Final, NoReturn
from urllib.parse import urlsplit

from jsonschema import Draft202012Validator, FormatChecker
from packaging.utils import (
    InvalidSdistFilename,
    InvalidWheelFilename,
    parse_sdist_filename,
    parse_wheel_filename,
)
from packaging.version import InvalidVersion, Version

PACKAGE = "publication_contract"
SCHEMA_DIRECTORY = "schemas"
SCHEMA_FILENAMES: Final[Mapping[str, str]] = {
    "build-manifest": "build-manifest-v1.schema.json",
    "publication-plan": "publication-plan-v1.schema.json",
    "release-receipt": "release-receipt-v1.schema.json",
}
CONTRACTS: Final[tuple[str, ...]] = tuple(sorted(SCHEMA_FILENAMES))

# The "no secret-bearing fields in evidence" rule is expressed exactly once, here.
# A field name is forbidden when any of its underscore-delimited components is one
# of these terms, compared case-insensitively. `secret_field_name_schema()` derives
# the equivalent JSON Schema fragment from the same tuple, and
# `tests/ci/test_publication_contract.py` proves the checked-in schemas carry
# nothing but that generated fragment, so the two cannot drift.
SECRET_FIELD_TERMS: Final[tuple[str, ...]] = (
    "credential_hint",
    "credential_value",
    "key",
    "passwd",
    "password",
    "secret",
    "token",
)
# `credential_mode` names which credential mechanism a publication uses; it carries
# no credential material and is therefore the one allowed `credential_*` field.
SECRET_FIELD_EXEMPTIONS: Final[frozenset[str]] = frozenset({"credential_mode"})
SECRET_FIELD_RE: Final[re.Pattern[str]] = re.compile(
    rf"(?:^|_)(?:{'|'.join(SECRET_FIELD_TERMS)})(?:_|$)",
    re.IGNORECASE,
)


class ContractError(ValueError):
    """A field-addressable contract violation."""


def _fail(path: str, message: str) -> NoReturn:
    raise ContractError(f"{path}: {message}")


def _ecma_case_insensitive(term: str) -> str:
    """Render one term case-insensitively without an inline regex flag.

    JSON Schema's ECMA-262 ``pattern`` dialect has no inline ``(?i)`` flag, so
    case insensitivity has to be spelled out as explicit character classes.
    """
    return "".join(
        f"[{character.upper()}{character.lower()}]"
        if character.isalpha()
        else re.escape(character)
        for character in term
    )


SECRET_FIELD_SCHEMA_PATTERN: Final[str] = (
    "(?:^|_)"
    f"(?:{'|'.join(_ecma_case_insensitive(term) for term in SECRET_FIELD_TERMS)})"
    "(?:_|$)"
)


def secret_field_name_schema() -> dict[str, Any]:
    """Return the JSON Schema fragment equivalent to :func:`is_secret_field`."""
    return {
        "anyOf": [
            {"enum": sorted(SECRET_FIELD_EXEMPTIONS)},
            {"not": {"pattern": SECRET_FIELD_SCHEMA_PATTERN}},
        ]
    }


def is_secret_field(name: str) -> bool:
    """Return whether ``name`` is a forbidden secret-bearing evidence field."""
    if name in SECRET_FIELD_EXEMPTIONS:
        return False
    return SECRET_FIELD_RE.search(name) is not None


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            _fail(f"$.{key}", "duplicate JSON object key")
        result[key] = value
    return result


def load_json(path: Path) -> Any:
    """Load JSON while rejecting duplicate keys and non-standard numeric values."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        _fail(str(path), str(error))
    try:
        return json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=lambda value: _fail("$", f"invalid numeric value {value}"),
        )
    except json.JSONDecodeError as error:
        _fail(f"{path}:{error.lineno}:{error.colno}", error.msg)


def load_json_value(value: str, field: str) -> Any:
    try:
        return json.loads(
            value,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=lambda item: _fail(field, f"invalid numeric value {item}"),
        )
    except json.JSONDecodeError as error:
        _fail(field, f"invalid JSON: {error.msg}")


def load_schema(contract: str) -> Any:
    """Load one packaged contract schema as data owned by this package."""
    if contract not in SCHEMA_FILENAMES:
        _fail("contract", f"unsupported contract {contract!r}")
    resource = (
        resources.files(PACKAGE)
        .joinpath(SCHEMA_DIRECTORY)
        .joinpath(SCHEMA_FILENAMES[contract])
    )
    return load_json_value(resource.read_text(encoding="utf-8"), f"schema.{contract}")


def canonical_json_bytes(document: Any) -> bytes:
    """Return the canonical on-disk representation used for every contract."""
    try:
        payload = json.dumps(
            document,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as error:
        _fail("$", f"cannot serialize contract: {error}")
    return f"{payload}\n".encode()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _field_path(error: Any) -> str:
    path = "$"
    for part in error.absolute_path:
        path += f"[{part}]" if isinstance(part, int) else f".{part}"
    if error.validator == "required":
        missing = sorted(set(error.validator_value) - set(error.instance))
        if missing:
            path += f".{missing[0]}"
    elif error.validator == "additionalProperties":
        extras = sorted(set(error.instance) - set(error.schema.get("properties", {})))
        if extras:
            path += f".{extras[0]}"
    return path


def reject_secret_fields(document: Any, path: str = "$") -> None:
    """Raise :class:`ContractError` for any secret-bearing field in ``document``.

    Deliberately a plain recursive function rather than a generator: the guard has
    to fire when it is called, not when a caller happens to exhaust it.
    """
    if isinstance(document, Mapping):
        for key, value in document.items():
            if is_secret_field(key):
                _fail(f"{path}.{key}", "secret-bearing fields are forbidden")
            reject_secret_fields(value, f"{path}.{key}")
    elif isinstance(document, Sequence) and not isinstance(document, (str, bytes)):
        for index, value in enumerate(document):
            reject_secret_fields(value, f"{path}[{index}]")


def _require_normalized_version(value: str, path: str) -> None:
    try:
        normalized = str(Version(value))
    except InvalidVersion:
        _fail(path, "must be a valid PEP 440 package version")
    if normalized != value:
        _fail(path, f"must be normalized as {normalized!r}")


def _require_safe_url(value: str, path: str) -> None:
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.netloc:
        _fail(path, "must be an absolute https URL")
    if parsed.username is not None or parsed.password is not None:
        _fail(path, "must not contain credentials")
    if parsed.query or parsed.fragment:
        _fail(path, "must not contain a query or fragment")


def image_plan_fingerprint(image_plan: Mapping[str, Any], wheel_sha256: str) -> str:
    covered = {
        "base_digest": image_plan["base_digest"],
        "build_args": image_plan["build_args"],
        "context": image_plan["context"],
        "dockerfile": image_plan["dockerfile"],
        "labels": image_plan["labels"],
        "target": image_plan["target"],
        "wheel_sha256": wheel_sha256,
    }
    return hashlib.sha256(canonical_json_bytes(covered)).hexdigest()


def _validate_build_manifest(
    document: Mapping[str, Any], artifact_root: Path | None
) -> None:
    _require_normalized_version(document["package_version"], "$.package_version")
    distributions = document["distributions"]
    wheel_sha = distributions["wheel"]["sha256"]
    image_plan = document["image_plan"]
    build_args = image_plan["build_args"]
    labels = image_plan["labels"]
    expected_values = {
        "REVISION": document["source_sha"],
        "VERSION": document["package_version"],
        "WHEEL_SHA256": wheel_sha,
    }
    for key, expected_value in expected_values.items():
        if build_args[key] != expected_value:
            _fail(
                f"$.image_plan.build_args.{key}",
                f"must equal {expected_value!r}",
            )
    wheel_path = Path(build_args["WHEEL_PATH"])
    if (
        wheel_path.is_absolute()
        or ".." in wheel_path.parts
        or "\\" in build_args["WHEEL_PATH"]
    ):
        _fail("$.image_plan.build_args.WHEEL_PATH", "must be a safe relative path")
    if wheel_path.name != distributions["wheel"]["filename"]:
        _fail(
            "$.image_plan.build_args.WHEEL_PATH",
            "must identify the manifest wheel filename",
        )
    if labels["org.opencontainers.image.version"] != document["package_version"]:
        _fail(
            "$.image_plan.labels.org.opencontainers.image.version",
            "must equal package_version",
        )
    if labels["org.opencontainers.image.revision"] != document["source_sha"]:
        _fail(
            "$.image_plan.labels.org.opencontainers.image.revision",
            "must equal source_sha",
        )
    _require_safe_url(
        labels["org.opencontainers.image.source"],
        "$.image_plan.labels.org.opencontainers.image.source",
    )
    expected = image_plan_fingerprint(image_plan, wheel_sha)
    actual = image_plan["fingerprint"]
    if actual != expected:
        _fail(
            "$.image_plan.fingerprint",
            f"does not match covered image inputs ({expected})",
        )

    if artifact_root is None:
        return
    root = artifact_root.resolve()
    for kind in ("wheel", "sdist"):
        item = distributions[kind]
        filename = item["filename"]
        artifact = root / filename
        if artifact.parent != root or artifact.name != filename:
            _fail(f"$.distributions.{kind}.filename", "must name a root-level artifact")
        if not artifact.is_file() or artifact.is_symlink():
            _fail(
                f"$.distributions.{kind}.filename",
                "does not identify a regular artifact",
            )
        digest = sha256_file(artifact)
        if digest != item["sha256"]:
            _fail(
                f"$.distributions.{kind}.sha256",
                f"does not match {filename} ({digest})",
            )


def _validate_publication_plan(document: Mapping[str, Any]) -> None:
    _require_normalized_version(document["package_version"], "$.package_version")
    _require_safe_url(document["package_endpoint"], "$.package_endpoint")
    if document["registry"] != document["registry"].lower():
        _fail("$.registry", "must be lowercase normalized coordinates")
    if document["repository"] != document["repository"].lower():
        _fail("$.repository", "must be lowercase normalized coordinates")

    immutable = set(document["tags"]["immutable"])
    aliases = set(document["tags"]["aliases"])
    overlap = sorted(immutable & aliases)
    if overlap:
        _fail("$.tags", f"immutable and alias tag sets overlap: {', '.join(overlap)}")


def _validate_release_receipt(document: Mapping[str, Any]) -> None:
    _require_normalized_version(document["package_version"], "$.package_version")
    _require_safe_url(document["package"]["endpoint"], "$.package.endpoint")
    if document["forge_release"]["url"] is not None:
        _require_safe_url(document["forge_release"]["url"], "$.forge_release.url")


def validate_contract(
    contract: str,
    document: Any,
    *,
    artifact_root: Path | None = None,
) -> None:
    """Validate schema and cross-field/disk invariants for one contract."""
    schema = load_schema(contract)
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = sorted(
        validator.iter_errors(document), key=lambda error: list(error.absolute_path)
    )
    if errors:
        error = errors[0]
        _fail(_field_path(error), error.message)

    reject_secret_fields(document)

    if contract == "build-manifest":
        _validate_build_manifest(document, artifact_root)
    elif contract == "publication-plan":
        _validate_publication_plan(document)
    elif contract == "release-receipt":
        _validate_release_receipt(document)


def _write_atomically(payload: bytes, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=output.parent, delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(payload)
    temporary.replace(output)


def write_contract(
    contract: str,
    document: Any,
    output: Path,
    *,
    artifact_root: Path | None = None,
) -> dict[str, str]:
    validate_contract(contract, document, artifact_root=artifact_root)
    _write_atomically(canonical_json_bytes(document), output)
    return identity_outputs(document, output)


def identity_outputs(document: Mapping[str, Any], path: Path) -> dict[str, str]:
    outputs = {
        "file": str(path),
        "file-sha256": sha256_file(path),
        "schema-version": str(document.get("schema_version", "")),
        "package-version": str(document.get("package_version", "")),
        "source-sha": str(document.get("source_sha", "")),
        "image-plan-fingerprint": "",
        "wheel-filename": "",
        "wheel-sha256": "",
        "sdist-filename": "",
        "sdist-sha256": "",
    }
    if document.get("schema_version") == "build-manifest-v1":
        outputs["image-plan-fingerprint"] = document["image_plan"]["fingerprint"]
        outputs["wheel-filename"] = document["distributions"]["wheel"]["filename"]
        outputs["wheel-sha256"] = document["distributions"]["wheel"]["sha256"]
        outputs["sdist-filename"] = document["distributions"]["sdist"]["filename"]
        outputs["sdist-sha256"] = document["distributions"]["sdist"]["sha256"]
    return outputs


def _regular_root_artifacts(root: Path) -> tuple[Path, Path]:
    wheel = sorted(root.glob("*.whl"))
    sdist = sorted(root.glob("*.tar.gz"))
    if len(wheel) != 1:
        _fail(
            "$.distributions.wheel",
            "artifact directory must contain exactly one root-level wheel",
        )
    if len(sdist) != 1:
        _fail(
            "$.distributions.sdist",
            "artifact directory must contain exactly one root-level sdist",
        )
    for artifact in (*wheel, *sdist):
        if artifact.is_symlink() or not artifact.is_file():
            _fail("$.distributions", f"{artifact.name} must be a regular file")
    return wheel[0], sdist[0]


def build_manifest(
    *,
    artifact_directory: Path,
    package_version: str,
    source_sha: str,
    image_context: str,
    dockerfile: str,
    target: str,
    base_digest: str,
    build_args_json: str,
    labels_json: str,
    development_distance: int | None = None,
) -> tuple[dict[str, Any], Path]:
    """Build a manifest document bound to the artifacts in ``artifact_directory``."""
    root = artifact_directory.resolve()
    wheel, sdist = _regular_root_artifacts(root)
    build_args = load_json_value(build_args_json, "image_plan.build_args")
    labels = load_json_value(labels_json, "image_plan.labels")
    if not isinstance(build_args, dict):
        _fail("$.image_plan.build_args", "must be a JSON object")
    if not isinstance(labels, dict):
        _fail("$.image_plan.labels", "must be a JSON object")
    try:
        _wheel_name, wheel_version, _build, _tags = parse_wheel_filename(wheel.name)
    except InvalidWheelFilename as error:
        _fail("$.distributions.wheel.filename", str(error))
    try:
        _sdist_name, sdist_version = parse_sdist_filename(sdist.name)
    except InvalidSdistFilename as error:
        _fail("$.distributions.sdist.filename", str(error))
    try:
        requested_version = Version(package_version)
    except InvalidVersion:
        _fail("$.package_version", "must be a valid PEP 440 package version")
    if wheel_version != requested_version:
        _fail(
            "$.distributions.wheel.filename",
            "embedded version does not match package_version",
        )
    if sdist_version != requested_version:
        _fail(
            "$.distributions.sdist.filename",
            "embedded version does not match package_version",
        )

    wheel_sha = sha256_file(wheel)
    protected_args = {
        "WHEEL_PATH": str(wheel.relative_to(Path.cwd()))
        if wheel.is_relative_to(Path.cwd())
        else wheel.name,
        "WHEEL_SHA256": wheel_sha,
    }
    overlap = sorted(protected_args.keys() & build_args.keys())
    if overlap:
        _fail(
            "$.image_plan.build_args",
            f"reserved build arguments supplied: {', '.join(overlap)}",
        )
    build_args.update(protected_args)
    image_plan: dict[str, Any] = {
        "context": image_context,
        "dockerfile": dockerfile,
        "target": target,
        "base_digest": base_digest,
        "build_args": build_args,
        "labels": labels,
    }
    image_plan["fingerprint"] = image_plan_fingerprint(image_plan, wheel_sha)
    document: dict[str, Any] = {
        "schema_version": "build-manifest-v1",
        "package_version": package_version,
        "source_sha": source_sha,
        "distributions": {
            "wheel": {"filename": wheel.name, "sha256": wheel_sha},
            "sdist": {"filename": sdist.name, "sha256": sha256_file(sdist)},
        },
        "image_plan": image_plan,
    }
    if development_distance is not None:
        document["development_distance"] = development_distance
    return document, root


def write_checksums(root: Path, output: Path) -> dict[str, str]:
    root = root.resolve()
    artifacts = [*_regular_root_artifacts(root)]
    lines = [
        f"{sha256_file(path)}  {path.name}"
        for path in sorted(artifacts, key=lambda p: p.name)
    ]
    _write_atomically(("\n".join(lines) + "\n").encode(), output)
    return {
        "file": str(output),
        "file-sha256": sha256_file(output),
        "schema-version": "",
        "package-version": "",
        "source-sha": "",
        "image-plan-fingerprint": "",
        "wheel-filename": "",
        "wheel-sha256": "",
        "sdist-filename": "",
        "sdist-sha256": "",
    }
