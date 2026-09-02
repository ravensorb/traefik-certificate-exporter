"""Deterministic, secret-free publication evidence contracts.

The composite action at ``.github/actions/publication-contract`` is a thin
adapter over this package's ``publication-contract`` console script.
"""

from __future__ import annotations

from .contract import (
    CONTRACTS,
    SECRET_FIELD_RE,
    SECRET_FIELD_SCHEMA_PATTERN,
    SECRET_FIELD_TERMS,
    ContractError,
    build_manifest,
    canonical_json_bytes,
    identity_outputs,
    image_plan_fingerprint,
    is_secret_field,
    load_json,
    load_json_value,
    load_schema,
    reject_secret_fields,
    secret_field_name_schema,
    sha256_file,
    validate_contract,
    write_checksums,
    write_contract,
)

__all__ = [
    "CONTRACTS",
    "SECRET_FIELD_RE",
    "SECRET_FIELD_SCHEMA_PATTERN",
    "SECRET_FIELD_TERMS",
    "ContractError",
    "build_manifest",
    "canonical_json_bytes",
    "identity_outputs",
    "image_plan_fingerprint",
    "is_secret_field",
    "load_json",
    "load_json_value",
    "load_schema",
    "reject_secret_fields",
    "secret_field_name_schema",
    "sha256_file",
    "validate_contract",
    "write_checksums",
    "write_contract",
]
