from __future__ import annotations

import argparse
import importlib.util
import json
import re
from pathlib import Path
from types import ModuleType

import pytest
import tomllib
from packaging.specifiers import SpecifierSet

PROJECT_ROOT = Path(__file__).parents[2]
ACTION_SCRIPT = (
    PROJECT_ROOT
    / ".github"
    / "actions"
    / "publication-contract"
    / "publication_contract.py"
)
FIXTURES = Path(__file__).parent / "fixtures" / "publication-contract"
VERIFY_WORKFLOW = PROJECT_ROOT / ".github" / "workflows" / "verify-build.yaml"
DOCKER_BAKE = PROJECT_ROOT / "docker-bake.hcl"
SOURCE_SHA = "d" * 40
BASE_DIGEST = f"sha256:{'c' * 64}"


def _load_contract_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("publication_contract", ACTION_SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


contract = _load_contract_module()


@pytest.mark.parametrize(
    ("contract_name", "fixture"),
    [
        ("build-manifest", "valid-build-manifest.json"),
        ("publication-plan", "valid-publication-plan.json"),
        ("release-receipt", "valid-release-receipt-incomplete.json"),
    ],
)
def test_valid_fixtures_round_trip_deterministically(
    tmp_path: Path,
    contract_name: str,
    fixture: str,
) -> None:
    document = contract.load_json(FIXTURES / fixture)
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"

    contract.write_contract(contract_name, document, first)
    contract.write_contract(contract_name, document, second)

    assert first.read_bytes() == second.read_bytes()
    assert first.read_bytes().endswith(b"\n")
    assert not first.read_bytes().endswith(b"\n\n")
    assert json.loads(first.read_bytes()) == document


@pytest.mark.parametrize(
    ("contract_name", "fixture", "field"),
    [
        (
            "build-manifest",
            "invalid-traversal-build-manifest.json",
            "$.distributions.wheel.filename",
        ),
        (
            "build-manifest",
            "invalid-hash-build-manifest.json",
            "$.distributions.wheel.sha256",
        ),
        ("publication-plan", "invalid-missing-schema-version.json", "$.schema_version"),
        ("publication-plan", "invalid-schema-publication-plan.json", "$.password_hint"),
    ],
)
def test_invalid_fixtures_fail_with_field_specific_errors(
    contract_name: str,
    fixture: str,
    field: str,
) -> None:
    document = contract.load_json(FIXTURES / fixture)

    with pytest.raises(contract.ContractError, match=rf"^{re.escape(field)}"):
        contract.validate_contract(contract_name, document)


def test_duplicate_json_key_is_rejected_at_the_field() -> None:
    with pytest.raises(contract.ContractError, match=r"^\$\.source_sha: duplicate"):
        contract.load_json(FIXTURES / "invalid-duplicate-publication-plan.json")


def test_malformed_json_reports_its_source_location() -> None:
    fixture = FIXTURES / "invalid-malformed-publication-plan.json"
    with pytest.raises(
        contract.ContractError, match=r"invalid-malformed-publication-plan\.json:4:1"
    ):
        contract.load_json(fixture)


def _manifest_args(artifact_directory: Path, output: Path) -> argparse.Namespace:
    return argparse.Namespace(
        artifact_directory=artifact_directory,
        output=output,
        package_version="1.2.3",
        source_sha=SOURCE_SHA,
        development_distance=None,
        image_context=".",
        dockerfile="docker/Dockerfile",
        target="runtime",
        base_digest=BASE_DIGEST,
        build_args_json=json.dumps(
            {
                "POETRY_VERSION": "2.4.2",
                "REVISION": SOURCE_SHA,
                "VERSION": "1.2.3",
            }
        ),
        labels_json=json.dumps(
            {
                "org.opencontainers.image.title": "traefik-certificate-exporter",
                "org.opencontainers.image.description": "fixture",
                "org.opencontainers.image.source": (
                    "https://github.com/ravensorb/traefik-certificate-exporter"
                ),
                "org.opencontainers.image.version": "1.2.3",
                "org.opencontainers.image.revision": SOURCE_SHA,
            }
        ),
    )


def test_build_manifest_binds_artifacts_and_all_image_inputs(tmp_path: Path) -> None:
    wheel = tmp_path / "package-1.2.3-py3-none-any.whl"
    sdist = tmp_path / "package-1.2.3.tar.gz"
    wheel.write_bytes(b"wheel")
    sdist.write_bytes(b"sdist")
    args = _manifest_args(tmp_path, tmp_path / "build-manifest.json")

    document, root = contract.build_manifest(args)
    contract.write_contract("build-manifest", document, args.output, artifact_root=root)

    assert document["distributions"]["wheel"]["sha256"] == contract.sha256_file(wheel)
    assert document["distributions"]["sdist"]["sha256"] == contract.sha256_file(sdist)
    assert document["image_plan"]["fingerprint"] == contract.image_plan_fingerprint(
        document["image_plan"],
        contract.sha256_file(wheel),
    )


def test_artifact_hash_mismatch_is_rejected_at_hash_field(tmp_path: Path) -> None:
    wheel = tmp_path / "package-1.2.3-py3-none-any.whl"
    sdist = tmp_path / "package-1.2.3.tar.gz"
    wheel.write_bytes(b"wheel")
    sdist.write_bytes(b"sdist")
    document, _root = contract.build_manifest(
        _manifest_args(tmp_path, tmp_path / "manifest.json")
    )
    wheel.write_bytes(b"tampered")

    with pytest.raises(
        contract.ContractError, match=r"^\$\.distributions\.wheel\.sha256"
    ):
        contract.validate_contract("build-manifest", document, artifact_root=tmp_path)


def test_distribution_cardinality_is_enforced(tmp_path: Path) -> None:
    (tmp_path / "first.whl").write_bytes(b"first")
    (tmp_path / "second.whl").write_bytes(b"second")
    (tmp_path / "package.tar.gz").write_bytes(b"sdist")

    with pytest.raises(contract.ContractError, match=r"exactly one root-level wheel"):
        contract.write_checksums(tmp_path, tmp_path / "SHA256SUMS")


def test_checksums_are_sorted_and_have_exact_posix_format(tmp_path: Path) -> None:
    wheel = tmp_path / "z-package.whl"
    sdist = tmp_path / "a-package.tar.gz"
    wheel.write_bytes(b"wheel")
    sdist.write_bytes(b"sdist")
    output = tmp_path / "SHA256SUMS"

    contract.write_checksums(tmp_path, output)

    assert (
        output.read_bytes()
        == (
            f"{contract.sha256_file(sdist)}  {sdist.name}\n"
            f"{contract.sha256_file(wheel)}  {wheel.name}\n"
        ).encode()
    )


def test_checksum_revalidation_detects_distribution_mutation(tmp_path: Path) -> None:
    wheel = tmp_path / "package.whl"
    sdist = tmp_path / "package.tar.gz"
    wheel.write_bytes(b"wheel")
    sdist.write_bytes(b"sdist")
    expected = tmp_path / "SHA256SUMS"
    observed = tmp_path / "observed"
    contract.write_checksums(tmp_path, expected)

    wheel.write_bytes(b"tampered")
    contract.write_checksums(tmp_path, observed)

    assert observed.read_bytes() != expected.read_bytes()


def test_complete_receipt_cannot_hide_pending_mutations() -> None:
    document = contract.load_json(FIXTURES / "valid-release-receipt-incomplete.json")
    document["status"] = "complete"

    with pytest.raises(contract.ContractError):
        contract.validate_contract("release-receipt", document)


def test_secret_derived_hint_is_rejected() -> None:
    document = contract.load_json(FIXTURES / "valid-publication-plan.json")
    document["credential_hint"] = "derived"

    with pytest.raises(contract.ContractError, match="credential_hint"):
        contract.validate_contract("publication-plan", document)


def test_verify_workflow_interface_is_minimal_and_credential_free() -> None:
    workflow = VERIFY_WORKFLOW.read_text(encoding="utf-8")
    workflow_call = workflow.split("  workflow_call:\n", 1)[1].split(
        "\npermissions:", 1
    )[0]
    workflow_inputs, workflow_outputs = workflow_call.split("    outputs:\n", 1)
    input_names = set(
        re.findall(r"^      ([a-z][a-z-]+):$", workflow_inputs, re.MULTILINE)
    )
    output_names = set(
        re.findall(r"^      ([a-z0-9][a-z0-9-]+):$", workflow_outputs, re.MULTILINE)
    )

    assert input_names == {"channel", "package-version", "source-sha"}
    assert output_names == {
        "build-manifest-sha256",
        "dist-artifact-name",
        "package-version",
        "source-sha",
    }
    assert "secrets:" not in workflow
    assert "continue-on-error" not in workflow
    assert "permissions:\n  contents: read" in workflow
    assert workflow.count("persist-credentials: false") == workflow.count(
        "uses: actions/checkout@"
    )
    assert workflow.count("fetch-depth: 0") == workflow.count("uses: actions/checkout@")
    assert workflow.count("fetch-tags: true") == workflow.count(
        "uses: actions/checkout@"
    )


def test_verify_workflow_exposes_only_one_canonical_promotable_set() -> None:
    workflow = VERIFY_WORKFLOW.read_text(encoding="utf-8")

    assert workflow.count("run: poetry build") == 1
    assert "poetry run twine check --" in workflow
    assert workflow.count("operation: verify-checksums") == 2
    assert "LiquidLogicLabs/git-action-docker-test@v2" in workflow
    assert workflow.count("uses: actions/upload-artifact@") == 1
    assert "name: verified-dist-v1" in workflow
    assert "path: verified-dist-v1/" in workflow
    assert "retention-days: 30" in workflow
    assert "if-no-files-found: error" in workflow
    assert "docker/login-action@" not in workflow
    assert re.search(r"\bdocker\s+(?:login|push)\b", workflow) is None
    assert "poetry publish" not in workflow
    assert '"LABELS_JSON": json.dumps(' in workflow
    assert "jsondecode(LABELS_JSON)" in DOCKER_BAKE.read_text(encoding="utf-8")
    assert workflow.count("ORIGINAL_MANIFEST_SHA256:") == 2
    assert workflow.count("ORIGINAL_CHECKSUMS_SHA256:") == 2


def test_verify_matrix_exactly_matches_declared_supported_python_range() -> None:
    metadata = tomllib.loads(
        (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )
    python_constraint = SpecifierSet(
        metadata["tool"]["poetry"]["dependencies"]["python"]
    )
    workflow = VERIFY_WORKFLOW.read_text(encoding="utf-8")
    matrix_block = workflow.split("      matrix:\n", 1)[1].split("    steps:\n", 1)[0]
    matrix_versions = re.findall(
        r'^          - "([0-9]+\.[0-9]+)"$', matrix_block, re.MULTILINE
    )

    assert matrix_versions == ["3.10", "3.11", "3.12", "3.13", "3.14"]
    assert all(f"{version}.0" in python_constraint for version in matrix_versions)
    assert "3.9.0" not in python_constraint
    assert "3.15.0" not in python_constraint


def test_manifest_inputs_match_the_image_build_plan() -> None:
    workflow = VERIFY_WORKFLOW.read_text(encoding="utf-8")
    bake = DOCKER_BAKE.read_text(encoding="utf-8")
    base_image = re.search(r'BASE_IMAGE\s*=\s*"[^"@]+@(sha256:[0-9a-f]{64})"', bake)

    assert base_image is not None
    assert f"base-digest: {base_image.group(1)}" in workflow
    assert 'context    = "."' in bake
    assert "image-context: ." in workflow
    assert 'dockerfile = "docker/Dockerfile"' in bake
    assert "dockerfile: docker/Dockerfile" in workflow
    assert 'target     = "runtime"' in bake
    assert "target: runtime" in workflow
    assert 'POETRY_VERSION = "2.4.2"' in bake
    assert '"POETRY_VERSION":"2.4.2"' in workflow
