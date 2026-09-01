"""Create and validate deterministic, secret-free publication evidence contracts."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, NoReturn
from urllib.parse import urlsplit

from jsonschema import Draft202012Validator, FormatChecker
from packaging.utils import (
    InvalidSdistFilename,
    InvalidWheelFilename,
    parse_sdist_filename,
    parse_wheel_filename,
)
from packaging.version import InvalidVersion, Version

ACTION_ROOT = Path(__file__).resolve().parent
SCHEMA_ROOT = ACTION_ROOT / "schemas"
SCHEMAS = {
    "publication-plan": SCHEMA_ROOT / "publication-plan-v1.schema.json",
    "build-manifest": SCHEMA_ROOT / "build-manifest-v1.schema.json",
    "release-receipt": SCHEMA_ROOT / "release-receipt-v1.schema.json",
}
SECRET_FIELD_RE = re.compile(
    r"(?:^|_)(?:secret|password|passwd|token|credential_value|credential_hint)(?:_|$)",
    re.IGNORECASE,
)


class ContractError(ValueError):
    """A field-addressable contract violation."""


def _fail(path: str, message: str) -> NoReturn:
    raise ContractError(f"{path}: {message}")


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
        return json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=lambda value: _fail("$", f"invalid numeric value {value}"),
        )
    except OSError as error:
        _fail(str(path), str(error))
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


def _walk(document: Any, path: str = "$") -> Any:
    if isinstance(document, Mapping):
        for key, value in document.items():
            if SECRET_FIELD_RE.search(key) and key != "credential_mode":
                _fail(f"{path}.{key}", "secret-bearing fields are forbidden")
            yield from _walk(value, f"{path}.{key}")
    elif isinstance(document, Sequence) and not isinstance(document, (str, bytes)):
        for index, value in enumerate(document):
            yield from _walk(value, f"{path}[{index}]")
    yield path, document


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
    if contract not in SCHEMAS:
        _fail("contract", f"unsupported contract {contract!r}")
    schema = load_json(SCHEMAS[contract])
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = sorted(
        validator.iter_errors(document), key=lambda error: list(error.absolute_path)
    )
    if errors:
        error = errors[0]
        _fail(_field_path(error), error.message)

    for _path, _value in _walk(document):
        pass

    if contract == "build-manifest":
        _validate_build_manifest(document, artifact_root)
    elif contract == "publication-plan":
        _validate_publication_plan(document)
    elif contract == "release-receipt":
        _validate_release_receipt(document)


def write_contract(
    contract: str,
    document: Any,
    output: Path,
    *,
    artifact_root: Path | None = None,
) -> dict[str, str]:
    validate_contract(contract, document, artifact_root=artifact_root)
    payload = canonical_json_bytes(document)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=output.parent, delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(payload)
    temporary.replace(output)
    return _identity_outputs(document, output)


def _identity_outputs(document: Mapping[str, Any], path: Path) -> dict[str, str]:
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


def build_manifest(args: argparse.Namespace) -> tuple[dict[str, Any], Path]:
    root = args.artifact_directory.resolve()
    wheel, sdist = _regular_root_artifacts(root)
    build_args = load_json_value(args.build_args_json, "image_plan.build_args")
    labels = load_json_value(args.labels_json, "image_plan.labels")
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
        requested_version = Version(args.package_version)
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
        "context": args.image_context,
        "dockerfile": args.dockerfile,
        "target": args.target,
        "base_digest": args.base_digest,
        "build_args": build_args,
        "labels": labels,
    }
    image_plan["fingerprint"] = image_plan_fingerprint(image_plan, wheel_sha)
    document: dict[str, Any] = {
        "schema_version": "build-manifest-v1",
        "package_version": args.package_version,
        "source_sha": args.source_sha,
        "distributions": {
            "wheel": {"filename": wheel.name, "sha256": wheel_sha},
            "sdist": {"filename": sdist.name, "sha256": sha256_file(sdist)},
        },
        "image_plan": image_plan,
    }
    if args.development_distance is not None:
        document["development_distance"] = args.development_distance
    return document, root


def write_checksums(root: Path, output: Path) -> dict[str, str]:
    root = root.resolve()
    artifacts = [*_regular_root_artifacts(root)]
    lines = [
        f"{sha256_file(path)}  {path.name}"
        for path in sorted(artifacts, key=lambda p: p.name)
    ]
    payload = ("\n".join(lines) + "\n").encode()
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=output.parent, delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(payload)
    temporary.replace(output)
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


def emit_outputs(outputs: Mapping[str, str]) -> None:
    output_path = os.environ.get("GITHUB_OUTPUT")
    if output_path:
        with Path(output_path).open("a", encoding="utf-8", newline="\n") as stream:
            stream.writelines(f"{key}={value}\n" for key, value in outputs.items())
    for key, value in outputs.items():
        print(f"{key}={value}")


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    subparsers = result.add_subparsers(dest="operation", required=True)

    validate = subparsers.add_parser("validate")
    validate.add_argument("--contract", choices=sorted(SCHEMAS), required=True)
    validate.add_argument("--input", type=Path, required=True)
    validate.add_argument("--artifact-directory", type=Path)

    write = subparsers.add_parser("write")
    write.add_argument("--contract", choices=sorted(SCHEMAS), required=True)
    write.add_argument("--input", type=Path, required=True)
    write.add_argument("--output", type=Path, required=True)
    write.add_argument("--artifact-directory", type=Path)

    manifest = subparsers.add_parser("build-manifest")
    manifest.add_argument("--artifact-directory", type=Path, required=True)
    manifest.add_argument("--output", type=Path, required=True)
    manifest.add_argument("--package-version", required=True)
    manifest.add_argument("--source-sha", required=True)
    manifest.add_argument("--development-distance", type=int)
    manifest.add_argument("--image-context", required=True)
    manifest.add_argument("--dockerfile", required=True)
    manifest.add_argument("--target", required=True)
    manifest.add_argument("--base-digest", required=True)
    manifest.add_argument("--build-args-json", required=True)
    manifest.add_argument("--labels-json", required=True)

    checksums = subparsers.add_parser("checksums")
    checksums.add_argument("--artifact-directory", type=Path, required=True)
    checksums.add_argument("--output", type=Path, required=True)
    return result


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = parser().parse_args(argv)
        if args.operation == "validate":
            document = load_json(args.input)
            validate_contract(
                args.contract, document, artifact_root=args.artifact_directory
            )
            outputs = _identity_outputs(document, args.input)
        elif args.operation == "write":
            document = load_json(args.input)
            outputs = write_contract(
                args.contract,
                document,
                args.output,
                artifact_root=args.artifact_directory,
            )
        elif args.operation == "build-manifest":
            document, root = build_manifest(args)
            outputs = write_contract(
                "build-manifest", document, args.output, artifact_root=root
            )
        else:
            outputs = write_checksums(args.artifact_directory, args.output)
        emit_outputs(outputs)
        return 0
    except ContractError as error:
        print(f"publication contract error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
