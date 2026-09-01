"""Command-line adapter for the publication evidence contracts."""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

from .contract import (
    CONTRACTS,
    ContractError,
    build_manifest,
    identity_outputs,
    load_json,
    validate_contract,
    write_checksums,
    write_contract,
)


def emit_outputs(outputs: Mapping[str, str]) -> None:
    # A newline in a value terminates the `key=value` line early and lets the remainder
    # parse as further keys -- the injection GitHub's heredoc delimiter syntax exists to
    # prevent. The invariant belongs in the writer every caller goes through.
    for key, value in outputs.items():
        if "\n" in value or "\r" in value:
            raise SystemExit(f"output {key!r} contains a newline and cannot be emitted")
    output_path = os.environ.get("GITHUB_OUTPUT")
    if output_path:
        with Path(output_path).open("a", encoding="utf-8", newline="\n") as stream:
            stream.writelines(f"{key}={value}\n" for key, value in outputs.items())
    for key, value in outputs.items():
        print(f"{key}={value}")


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        prog="publication-contract",
        description=__doc__,
    )
    subparsers = result.add_subparsers(dest="operation", required=True)

    validate = subparsers.add_parser("validate")
    validate.add_argument("--contract", choices=CONTRACTS, required=True)
    validate.add_argument("--input", type=Path, required=True)
    validate.add_argument("--artifact-directory", type=Path)

    write = subparsers.add_parser("write")
    write.add_argument("--contract", choices=CONTRACTS, required=True)
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
            outputs = identity_outputs(document, args.input)
        elif args.operation == "write":
            document = load_json(args.input)
            outputs = write_contract(
                args.contract,
                document,
                args.output,
                artifact_root=args.artifact_directory,
            )
        elif args.operation == "build-manifest":
            document, root = build_manifest(
                artifact_directory=args.artifact_directory,
                package_version=args.package_version,
                source_sha=args.source_sha,
                development_distance=args.development_distance,
                image_context=args.image_context,
                dockerfile=args.dockerfile,
                target=args.target,
                base_digest=args.base_digest,
                build_args_json=args.build_args_json,
                labels_json=args.labels_json,
            )
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
