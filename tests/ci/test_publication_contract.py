from __future__ import annotations

import inspect
import json
import re
from collections.abc import Callable
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
        ("publication-plan", "valid-dev-publication-plan.json"),
        ("release-receipt", "valid-release-receipt-incomplete.json"),
        ("release-receipt", "valid-release-receipt-complete.json"),
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


# --------------------------------------------------------------------------
# Publication plan and release receipt: multi-destination shape (Epic 8)
# --------------------------------------------------------------------------

STABLE_PLAN = "valid-publication-plan.json"
DEV_PLAN = "valid-dev-publication-plan.json"
INCOMPLETE_RECEIPT = "valid-release-receipt-incomplete.json"
COMPLETE_RECEIPT = "valid-release-receipt-complete.json"


def _fixture(name: str) -> Any:
    return contract.load_json(FIXTURES / name)


def _mutated(name: str, mutate: Callable[[Any], None]) -> Any:
    document = _fixture(name)
    mutate(document)
    return document


def _plan_target_arrays() -> dict[str, str]:
    """Map each plan target array to the ``$defs`` name describing its items.

    Derived from the packaged schema rather than enumerated: a third target
    array added later is covered by every test below on the day it lands.
    """
    schema = contract.load_schema("publication-plan")
    return {
        name: definition["items"]["$ref"].rsplit("/", 1)[-1]
        for name, definition in schema["properties"].items()
        if isinstance(definition, dict)
        and definition.get("type") == "array"
        and "contains" in definition
    }


def _receipt_complete_branch() -> dict[str, Any]:
    (conditional,) = contract.load_schema("release-receipt")["allOf"]
    assert conditional["if"]["properties"]["status"]["const"] == "complete"
    branch: dict[str, Any] = conditional["then"]["properties"]
    return branch


def _receipt_destination_arrays() -> list[tuple[str, str]]:
    """Return the ``(group, array)`` pairs the complete branch pins a forge entry in."""
    return [
        (group, array)
        for group, group_schema in _receipt_complete_branch().items()
        for array, array_schema in group_schema.get("properties", {}).items()
        if "contains" in array_schema
    ]


def _forge_index(entries: list[dict[str, Any]]) -> int:
    return next(
        index
        for index, entry in enumerate(entries)
        if entry["name"] == contract.ALWAYS_ENABLED_TARGET_NAME
    )


def test_the_always_on_forge_rule_is_spelled_from_one_name() -> None:
    # CI-AR20/CI-AR21a live in two schemas and four arrays. The name is written
    # once in `contract.py`; this proves every packaged fragment agrees with it,
    # with the fragment set derived from the schemas rather than listed here.
    forge = contract.ALWAYS_ENABLED_TARGET_NAME
    plan = contract.load_schema("publication-plan")
    arrays = _plan_target_arrays()

    assert set(arrays) == {"package_targets", "image_targets"}
    for array, definition_name in arrays.items():
        contains = plan["properties"][array]["contains"]
        assert contains["properties"]["name"]["const"] == forge, array
        (conditional, *_rest) = plan["$defs"][definition_name]["allOf"]
        assert conditional["if"]["properties"]["name"]["const"] == forge
        assert conditional["then"]["properties"]["enabled"]["const"] is True

    pairs = _receipt_destination_arrays()
    assert {group for group, _array in pairs} == {"package", "oci"}
    branch = _receipt_complete_branch()
    for group, array in pairs:
        contains = branch[group]["properties"][array]["contains"]
        assert contains["properties"]["name"]["const"] == forge, group


@pytest.mark.parametrize("array", sorted(_plan_target_arrays()))
def test_every_target_array_must_carry_an_enabled_forge_entry(array: str) -> None:
    forge = contract.ALWAYS_ENABLED_TARGET_NAME

    def drop_forge(document: Any) -> None:
        document[array] = [entry for entry in document[array] if entry["name"] != forge]

    def disable_forge(document: Any) -> None:
        document[array][_forge_index(document[array])]["enabled"] = False

    with pytest.raises(contract.ContractError, match=rf"^\$\.{array}: "):
        contract.validate_contract(
            "publication-plan", _mutated(STABLE_PLAN, drop_forge)
        )
    index = _forge_index(_fixture(STABLE_PLAN)[array])
    with pytest.raises(
        contract.ContractError,
        match=rf"^\$\.{array}\[{index}\]\.enabled: ",
    ):
        contract.validate_contract(
            "publication-plan", _mutated(STABLE_PLAN, disable_forge)
        )


def _drop_distance(document: Any) -> None:
    del document["development_distance"]


def _add_distance(document: Any) -> None:
    document["development_distance"] = 3


def _short_sha_segment(document: Any) -> None:
    document["tags"]["immutable"] = ["dev-ddddddddddd"]


def _foreign_sha_segment(document: Any) -> None:
    document["tags"]["immutable"] = ["dev-abcdefabcdef"]


def _extra_dev_alias(document: Any) -> None:
    document["tags"]["aliases"] = ["dev", "edge"]


def _image_claims_absent_by_host(document: Any) -> None:
    document["image_targets"][0]["absent_by_host"] = True


def _pypi_claims_absent_by_host(document: Any) -> None:
    document["package_targets"][1]["absent_by_host"] = True


def _absent_by_host_with_endpoint(document: Any) -> None:
    document["package_targets"][0]["endpoint"] = "https://pypi.example.com/"


def _present_forge_without_endpoint(document: Any) -> None:
    document["package_targets"][0]["endpoint"] = None


def _testpypi_on_stable(document: Any) -> None:
    document["package_targets"].append(
        {
            "name": "testpypi",
            "enabled": True,
            "endpoint": "https://test.pypi.org/legacy/",
            "credential_mode": "oidc",
        }
    )


def _pypi_on_dev(document: Any) -> None:
    document["package_targets"].append(
        {
            "name": "pypi",
            "enabled": True,
            "endpoint": "https://upload.pypi.org/legacy/",
            "credential_mode": "oidc",
        }
    )


def _drop_git_aliases(document: Any) -> None:
    del document["git_aliases"]


def _drop_forge_release_destination(document: Any) -> None:
    document["destinations"] = ["package", "oci"]


def _drop_run(document: Any) -> None:
    del document["run"]


def _secret_in_run(document: Any) -> None:
    document["run"]["token"] = "not-a-real-value"


def _duplicate_package_target(document: Any) -> None:
    document["package_targets"].append(dict(document["package_targets"][1]))


def _uppercase_registry(document: Any) -> None:
    document["image_targets"][0]["registry"] = "GHCR.io"


def _credentialled_endpoint(document: Any) -> None:
    document["package_targets"][1]["endpoint"] = "https://u:p@test.pypi.org/legacy/"


def _credential_mode_that_names_a_secret(document: Any) -> None:
    document["image_targets"][1]["credential_mode"] = "password"


@pytest.mark.parametrize(
    ("fixture", "mutate", "field"),
    [
        (DEV_PLAN, _drop_distance, "$.development_distance"),
        (STABLE_PLAN, _add_distance, "$.development_distance"),
        (DEV_PLAN, _short_sha_segment, "$.tags.immutable[0]"),
        (DEV_PLAN, _foreign_sha_segment, "$.tags.immutable[0]"),
        (DEV_PLAN, _extra_dev_alias, "$.tags.aliases"),
        (
            STABLE_PLAN,
            _image_claims_absent_by_host,
            "$.image_targets[0].absent_by_host",
        ),
        (DEV_PLAN, _pypi_claims_absent_by_host, "$.package_targets[1].absent_by_host"),
        (STABLE_PLAN, _absent_by_host_with_endpoint, "$.package_targets[0].endpoint"),
        (DEV_PLAN, _present_forge_without_endpoint, "$.package_targets[0].endpoint"),
        (STABLE_PLAN, _testpypi_on_stable, "$.package_targets[2].name"),
        (DEV_PLAN, _pypi_on_dev, "$.package_targets[2].name"),
        (STABLE_PLAN, _drop_git_aliases, "$.git_aliases"),
        (STABLE_PLAN, _drop_forge_release_destination, "$.destinations"),
        (STABLE_PLAN, _drop_run, "$.run"),
        (STABLE_PLAN, _secret_in_run, "$.run.token"),
        (STABLE_PLAN, _duplicate_package_target, "$.package_targets[2].name"),
        (STABLE_PLAN, _uppercase_registry, "$.image_targets[0].registry"),
        (DEV_PLAN, _credentialled_endpoint, "$.package_targets[1].endpoint"),
        (
            STABLE_PLAN,
            _credential_mode_that_names_a_secret,
            "$.image_targets[1].credential_mode",
        ),
    ],
)
def test_plan_rejections_are_addressed_at_the_offending_field(
    fixture: str,
    mutate: Callable[[Any], None],
    field: str,
) -> None:
    with pytest.raises(contract.ContractError, match=rf"^{re.escape(field)}: "):
        contract.validate_contract("publication-plan", _mutated(fixture, mutate))


def _forge_package_disabled(document: Any) -> None:
    # An endpoint is supplied so the *only* defect is the disabled outcome: the
    # always-on destination has no disabled state, whatever else is well formed.
    document["package"]["destinations"][0].update(
        {"outcome": "disabled", "endpoint": "https://gitea.example.com/pypi"}
    )


def _forge_image_disabled(document: Any) -> None:
    document["oci"]["images"][0]["outcome"] = "disabled"


def _image_absent_by_host(document: Any) -> None:
    document["oci"]["images"][0]["outcome"] = "absent-by-host"


def _external_package_absent_by_host(document: Any) -> None:
    document["package"]["destinations"][1].update(
        {"outcome": "absent-by-host", "endpoint": None, "artifacts": []}
    )


def _absent_by_host_receipt_endpoint(document: Any) -> None:
    document["package"]["destinations"][0]["endpoint"] = "https://pypi.example.com/"


def _drop_receipt_run(document: Any) -> None:
    del document["run"]


def _duplicate_image_destination(document: Any) -> None:
    document["oci"]["images"].append(dict(document["oci"]["images"][1]))


def _published_package_missing_a_file(document: Any) -> None:
    document["package"]["destinations"][1]["artifacts"].pop()


def _published_image_without_a_digest(document: Any) -> None:
    document["oci"]["images"][0]["digest"] = None


@pytest.mark.parametrize(
    ("fixture", "mutate", "field"),
    [
        (
            INCOMPLETE_RECEIPT,
            _forge_package_disabled,
            "$.package.destinations[0].outcome",
        ),
        (INCOMPLETE_RECEIPT, _forge_image_disabled, "$.oci.images[0].outcome"),
        (INCOMPLETE_RECEIPT, _image_absent_by_host, "$.oci.images[0].outcome"),
        (
            INCOMPLETE_RECEIPT,
            _external_package_absent_by_host,
            "$.package.destinations[1].outcome",
        ),
        (
            INCOMPLETE_RECEIPT,
            _absent_by_host_receipt_endpoint,
            "$.package.destinations[0].endpoint",
        ),
        (INCOMPLETE_RECEIPT, _drop_receipt_run, "$.run"),
        (INCOMPLETE_RECEIPT, _duplicate_image_destination, "$.oci.images[2].name"),
        (
            COMPLETE_RECEIPT,
            _published_package_missing_a_file,
            "$.package.destinations[1].artifacts",
        ),
        (COMPLETE_RECEIPT, _published_image_without_a_digest, "$.oci.images[0].digest"),
    ],
)
def test_receipt_rejections_are_addressed_at_the_offending_field(
    fixture: str,
    mutate: Callable[[Any], None],
    field: str,
) -> None:
    with pytest.raises(contract.ContractError, match=rf"^{re.escape(field)}: "):
        contract.validate_contract("release-receipt", _mutated(fixture, mutate))


@pytest.mark.parametrize(("group", "array"), _receipt_destination_arrays())
def test_a_complete_receipt_needs_an_entry_for_every_always_on_destination(
    group: str,
    array: str,
) -> None:
    forge = contract.ALWAYS_ENABLED_TARGET_NAME

    def drop_forge(document: Any) -> None:
        document[group][array] = [
            entry for entry in document[group][array] if entry["name"] != forge
        ]

    with pytest.raises(contract.ContractError, match=rf"^\$\.{group}\.{array}: "):
        contract.validate_contract(
            "release-receipt", _mutated(COMPLETE_RECEIPT, drop_forge)
        )


def _unreconciled_statuses() -> list[str]:
    """Every reconciliation status that is not `matched`, taken from the schema.

    The enum is what widened; deriving the case list from it is what proves the
    widening cannot outrun the `complete` conditional that has to reject them.
    """
    schema = contract.load_schema("release-receipt")
    values = schema["$defs"]["reconciliationStatus"]["enum"]
    return [value for value in values if value != "matched"]


def test_the_reconciliation_enum_expresses_the_four_way_classification() -> None:
    assert set(_unreconciled_statuses()) | {"matched"} == {
        "failed",
        "matched",
        "mismatched",
        "missing",
        "pending",
        "unverifiable",
    }


@pytest.mark.parametrize("alias_array", ["git_aliases", "oci_aliases"])
@pytest.mark.parametrize("status", _unreconciled_statuses())
def test_a_complete_receipt_cannot_carry_an_unreconciled_alias(
    alias_array: str,
    status: str,
) -> None:
    def set_status(document: Any) -> None:
        document["reconciliation"][alias_array][0]["status"] = status

    with pytest.raises(
        contract.ContractError,
        match=rf"^\$\.reconciliation\.{alias_array}\[0\]\.status: ",
    ):
        contract.validate_contract(
            "release-receipt", _mutated(COMPLETE_RECEIPT, set_status)
        )


@pytest.mark.parametrize("status", ["mismatched", "missing", "unverifiable"])
def test_an_incomplete_receipt_accepts_every_new_reconciliation_status(
    status: str,
) -> None:
    def set_status(document: Any) -> None:
        document["reconciliation"]["oci_aliases"][0]["status"] = status

    contract.validate_contract(
        "release-receipt", _mutated(INCOMPLETE_RECEIPT, set_status)
    )


def test_a_run_that_never_reached_the_image_publisher_still_serializes() -> None:
    def never_attempted(document: Any) -> None:
        document["oci"]["images"] = []

    contract.validate_contract(
        "release-receipt", _mutated(INCOMPLETE_RECEIPT, never_attempted)
    )


def test_the_dev_plan_binds_its_immutable_tag_to_the_planned_source_sha() -> None:
    document = _fixture(DEV_PLAN)

    assert document["tags"]["immutable"] == [f"dev-{document['source_sha'][:12]}"]
    assert document["tags"]["aliases"] == ["dev"]


def test_run_correlation_is_carried_by_the_plan_and_the_receipt_only() -> None:
    # BL-E007-003: the manifest must stay byte-identical for identical source, so
    # a run id belongs in the two documents that are allowed to vary per run.
    correlated = ("publication-plan", "release-receipt")
    for name in correlated:
        assert "run" in contract.load_schema(name)["required"], name
    manifest = contract.load_schema("build-manifest")
    assert "run" not in manifest["properties"]
    assert "run" not in manifest["required"]
