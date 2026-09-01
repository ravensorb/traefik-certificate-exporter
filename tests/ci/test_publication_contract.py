from __future__ import annotations

import inspect
import json
import re
from pathlib import Path
from typing import Any

import pytest
import tomllib
import yaml
from jsonschema import Draft202012Validator
from packaging.specifiers import SpecifierSet

import publication_contract as contract

PROJECT_ROOT = Path(__file__).parents[2]
FIXTURES = Path(__file__).parent / "fixtures" / "publication-contract"
VERIFY_WORKFLOW = PROJECT_ROOT / ".github" / "workflows" / "verify-build.yaml"
DOCKER_BAKE = PROJECT_ROOT / "docker-bake.hcl"
SOURCE_SHA = "d" * 40
BASE_DIGEST = f"sha256:{'c' * 64}"


def _load_workflow(path: Path) -> dict[str, Any]:
    # BaseLoader keeps GitHub's `on` key as a string instead of applying YAML 1.1's
    # obsolete yes/no boolean coercion, and leaves every scalar a string.
    document = yaml.load(path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    assert isinstance(document, dict)
    return document


def _jobs(workflow: dict[str, Any]) -> dict[str, Any]:
    jobs = workflow["jobs"]
    assert isinstance(jobs, dict)
    return jobs


def _steps(workflow: dict[str, Any]) -> list[dict[str, Any]]:
    return [step for job in _jobs(workflow).values() for step in job.get("steps", [])]


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


def test_unsupported_contract_is_named_before_any_schema_is_loaded() -> None:
    with pytest.raises(contract.ContractError, match=r"^contract: unsupported"):
        contract.validate_contract("not-a-contract", {})


def test_every_declared_contract_ships_a_valid_packaged_schema() -> None:
    assert set(contract.CONTRACTS) == {
        "build-manifest",
        "publication-plan",
        "release-receipt",
    }
    for name in contract.CONTRACTS:
        schema = contract.load_schema(name)
        Draft202012Validator.check_schema(schema)


def test_duplicate_json_key_is_rejected_at_the_field() -> None:
    with pytest.raises(contract.ContractError, match=r"^\$\.source_sha: duplicate"):
        contract.load_json(FIXTURES / "invalid-duplicate-publication-plan.json")


def test_malformed_json_reports_its_source_location() -> None:
    fixture = FIXTURES / "invalid-malformed-publication-plan.json"
    with pytest.raises(
        contract.ContractError, match=r"invalid-malformed-publication-plan\.json:4:1"
    ):
        contract.load_json(fixture)


def _manifest_inputs(artifact_directory: Path) -> dict[str, Any]:
    return {
        "artifact_directory": artifact_directory,
        "package_version": "1.2.3",
        "source_sha": SOURCE_SHA,
        "development_distance": None,
        "image_context": ".",
        "dockerfile": "docker/Dockerfile",
        "target": "runtime",
        "base_digest": BASE_DIGEST,
        "build_args_json": json.dumps(
            {
                "POETRY_VERSION": "2.4.2",
                "REVISION": SOURCE_SHA,
                "VERSION": "1.2.3",
            }
        ),
        "labels_json": json.dumps(
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
    }


def _distributions(directory: Path) -> tuple[Path, Path]:
    wheel = directory / "package-1.2.3-py3-none-any.whl"
    sdist = directory / "package-1.2.3.tar.gz"
    wheel.write_bytes(b"wheel")
    sdist.write_bytes(b"sdist")
    return wheel, sdist


def test_build_manifest_binds_artifacts_and_all_image_inputs(tmp_path: Path) -> None:
    wheel, sdist = _distributions(tmp_path)
    output = tmp_path / "build-manifest.json"

    document, root = contract.build_manifest(**_manifest_inputs(tmp_path))
    contract.write_contract("build-manifest", document, output, artifact_root=root)

    assert document["distributions"]["wheel"]["sha256"] == contract.sha256_file(wheel)
    assert document["distributions"]["sdist"]["sha256"] == contract.sha256_file(sdist)
    assert document["image_plan"]["fingerprint"] == contract.image_plan_fingerprint(
        document["image_plan"],
        contract.sha256_file(wheel),
    )


def test_artifact_hash_mismatch_is_rejected_at_hash_field(tmp_path: Path) -> None:
    wheel, _sdist = _distributions(tmp_path)
    document, _root = contract.build_manifest(**_manifest_inputs(tmp_path))
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


def test_secret_guard_fires_on_call_rather_than_on_exhaustion() -> None:
    # A generator would only raise once a caller exhausted it, so the guard must
    # not be one: calling it is what enforces the invariant.
    assert not inspect.isgeneratorfunction(contract.reject_secret_fields)
    assert "yield" not in inspect.getsource(contract.reject_secret_fields)

    with pytest.raises(contract.ContractError, match=r"^\$\.a\[1\]\.api_token"):
        contract.reject_secret_fields({"a": [{}, {"api_token": "x"}]})


def test_both_guards_reject_a_secret_bearing_build_arg(tmp_path: Path) -> None:
    inputs = _manifest_inputs(tmp_path)
    _distributions(tmp_path)
    inputs["build_args_json"] = json.dumps(
        {
            "POETRY_VERSION": "2.4.2",
            "REVISION": SOURCE_SHA,
            "VERSION": "1.2.3",
            "REGISTRY_TOKEN": "s3cret",
        }
    )
    document, root = contract.build_manifest(**inputs)

    # The generated schema fragment rejects it first, ...
    with pytest.raises(contract.ContractError, match=r"^\$\.image_plan\.build_args:"):
        contract.validate_contract("build-manifest", document, artifact_root=root)
    # ... and the Python guard rejects it on its own, at the exact field.
    with pytest.raises(
        contract.ContractError,
        match=(
            r"^\$\.image_plan\.build_args\.REGISTRY_TOKEN: "
            r"secret-bearing fields are forbidden"
        ),
    ):
        contract.reject_secret_fields(document)


def _property_names_schemas(node: Any) -> list[Any]:
    if isinstance(node, dict):
        found = [node["propertyNames"]] if "propertyNames" in node else []
        for key, value in node.items():
            if key != "propertyNames":
                found.extend(_property_names_schemas(value))
        return found
    if isinstance(node, list):
        return [item for value in node for item in _property_names_schemas(value)]
    return []


def test_no_schema_carries_a_forbidden_field_rule_of_its_own() -> None:
    # Scope is derived from the packaged schemas, not a hand-kept path list: any
    # new or moved copy of the rule has to be the generated fragment or fail here.
    generated = contract.secret_field_name_schema()
    found = [
        fragment
        for name in contract.CONTRACTS
        for fragment in _property_names_schemas(contract.load_schema(name))
    ]

    assert found, "the generated forbidden-field fragment is no longer in any schema"
    assert all(fragment == generated for fragment in found), found
    # ECMA-262 `pattern` has no inline flags, so the generated pattern must not use
    # one; case insensitivity is spelled out as explicit character classes.
    assert re.search(r"\(\?[a-zA-Z]", contract.SECRET_FIELD_SCHEMA_PATTERN) is None


@pytest.mark.parametrize(
    "name",
    [
        "POETRY_VERSION",
        "REVISION",
        "VERSION",
        "WHEEL_PATH",
        "WHEEL_SHA256",
        "credential_mode",
        "monkey",
        "keys",
        "REGISTRY_TOKEN",
        "aws_secret_key",
        "password",
        "Passwd",
        "credential_hint",
        "credential_value",
        "signing_key",
    ],
)
def test_schema_fragment_and_python_guard_agree_field_by_field(name: str) -> None:
    validator = Draft202012Validator(contract.secret_field_name_schema())

    assert contract.is_secret_field(name) is not validator.is_valid(name), name


def test_verify_workflow_interface_is_minimal_and_credential_free() -> None:
    workflow = _load_workflow(VERIFY_WORKFLOW)
    raw = VERIFY_WORKFLOW.read_text(encoding="utf-8")
    workflow_call = workflow["on"]["workflow_call"]

    assert set(workflow_call) == {"inputs", "outputs"}
    assert set(workflow_call["inputs"]) == {"channel", "package-version", "source-sha"}
    assert set(workflow_call["outputs"]) == {
        "build-manifest-sha256",
        "dist-artifact-name",
        "package-version",
        "source-sha",
    }
    assert workflow["permissions"] == {"contents": "read"}
    # Deliberately textual: `secrets:` must be absent everywhere in the file,
    # including inside `run:` scripts and comments, where the parsed structure
    # would no longer show it as a key.
    assert "secrets:" not in raw

    for name, job in _jobs(workflow).items():
        assert "continue-on-error" not in job, name
        assert "secrets" not in job, name
    for step in _steps(workflow):
        assert "continue-on-error" not in step, step.get("name")

    checkouts = [
        step
        for step in _steps(workflow)
        if step.get("uses", "").startswith("actions/checkout@")
    ]
    assert checkouts
    for step in checkouts:
        assert step["with"]["persist-credentials"] == "false"
        assert step["with"]["fetch-depth"] == "0"
        assert step["with"]["fetch-tags"] == "true"


def test_verify_workflow_exposes_only_one_canonical_promotable_set() -> None:
    workflow = _load_workflow(VERIFY_WORKFLOW)
    steps = _steps(workflow)
    runs = [step["run"] for step in steps if "run" in step]
    contract_steps = [
        step
        for step in steps
        if step.get("uses") == "./.github/actions/publication-contract"
    ]
    uploads = [
        step
        for step in steps
        if step.get("uses", "").startswith("actions/upload-artifact@")
    ]

    assert [run for run in runs if run.strip() == "poetry build"]
    assert sum(run.strip() == "poetry build" for run in runs) == 1
    assert any("poetry run twine check --" in run for run in runs)
    assert (
        sum(step["with"]["operation"] == "verify-checksums" for step in contract_steps)
        == 2
    )
    assert any(
        step.get("uses") == "LiquidLogicLabs/git-action-docker-test@v2"
        for step in steps
    )
    assert len(uploads) == 1
    assert uploads[0]["with"] == {
        "name": "verified-dist-v1",
        "if-no-files-found": "error",
        "path": "verified-dist-v1/",
        "retention-days": "30",
    }
    assert not any(
        step.get("uses", "").startswith("docker/login-action@") for step in steps
    )
    assert not any(re.search(r"\bdocker\s+(?:login|push)\b", run) for run in runs)
    assert not any("poetry publish" in run for run in runs)
    assert any('"LABELS_JSON": json.dumps(' in run for run in runs)
    assert "jsondecode(LABELS_JSON)" in DOCKER_BAKE.read_text(encoding="utf-8")
    assert sum("ORIGINAL_MANIFEST_SHA256" in step.get("env", {}) for step in steps) == 2
    assert (
        sum("ORIGINAL_CHECKSUMS_SHA256" in step.get("env", {}) for step in steps) == 2
    )


def test_verify_matrix_exactly_matches_declared_supported_python_range() -> None:
    metadata = tomllib.loads(
        (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )
    python_constraint = SpecifierSet(
        metadata["tool"]["poetry"]["dependencies"]["python"]
    )
    supported = [
        f"{major}.{minor}"
        for major in range(2, 5)
        for minor in range(100)
        if f"{major}.{minor}.0" in python_constraint
    ]
    workflow = _load_workflow(VERIFY_WORKFLOW)
    matrix_versions = _jobs(workflow)["pytest"]["strategy"]["matrix"]["python"]

    assert supported
    assert matrix_versions == supported
    assert "3.9.0" not in python_constraint
    assert "3.15.0" not in python_constraint


def test_manifest_inputs_match_the_image_build_plan() -> None:
    workflow = _load_workflow(VERIFY_WORKFLOW)
    bake = DOCKER_BAKE.read_text(encoding="utf-8")
    base_image = re.search(r'BASE_IMAGE\s*=\s*"[^"@]+@(sha256:[0-9a-f]{64})"', bake)
    manifest_step = next(
        step
        for step in _steps(workflow)
        if step.get("uses") == "./.github/actions/publication-contract"
        and step["with"]["operation"] == "build-manifest"
    )
    inputs = manifest_step["with"]

    assert base_image is not None
    assert inputs["base-digest"] == base_image.group(1)
    assert 'context    = "."' in bake
    assert inputs["image-context"] == "."
    assert 'dockerfile = "docker/Dockerfile"' in bake
    assert inputs["dockerfile"] == "docker/Dockerfile"
    assert 'target     = "runtime"' in bake
    assert inputs["target"] == "runtime"
    assert 'POETRY_VERSION = "2.4.2"' in bake
    assert '"POETRY_VERSION":"2.4.2"' in inputs["build-args-json"]
