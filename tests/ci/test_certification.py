"""F20 / ADR-0016 / ADR-0017 / ADR-0020: the Gitea certification gate itself.

Story 9.2 declared mechanical anchors ("the gate derives its required cases from the
declared negative-case set and demands a run URL and conclusion for each; plant a
removed case") while its Files in scope held only markdown. This module is F20's
remediation: `REQUIRED_GITEA_CASES` is the requirements registry -- independent of
`docs/ci/gitea-certification.md`'s prose -- and the functions below are the mechanical
gate that resolves a certification report against it and against a retained ADR-0017
evidence export.

No live Gitea exists in this environment, so there is no real certification run and no
real evidence export to validate. What is built and tested here is the schema and the
validator: every fixture below is clearly marked SYNTHETIC FIXTURE DATA, constructed by
this test file, never a claim about an actual Gitea run. The validators are written so
that a real collector and a real report need only produce data of this shape, and so
that the four shapes of tampering the story names (missing row, extra row, duplicate
row, cross-tuple/source/workflow row) are mechanically rejected today, against fixtures,
rather than left for the day a live Gitea exists.

Everything that requires an actual certification run, a real evidence export, or a live
recovery rehearsal is `@pytest.mark.requires_live_gitea` and is not executed here; see
`docs/ci/gitea-certification.md` for the manual runbook each one anchors to.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Literal

import pytest

# ---------------------------------------------------------------------------
# F20: the required-case registry.
#
# This is the single source of required case IDs (TAC: "`tests/ci/`'s
# `REQUIRED_GITEA_CASES` registry is the single source of required case IDs,
# independent of `docs/ci/gitea-certification.md`'s prose"). It enumerates
# REQUIREMENTS this story declares, not repository contents -- there is no action,
# job, or filename this set could be derived from, which is exactly why ADR-0016's
# meta-guard treats a requirements registry differently from a hand-copied list of
# things the tree contains (`tests/ci/test_meta.py` and this story's own note: "The
# registry enumerates requirements, not repository contents").
# ---------------------------------------------------------------------------

REQUIRED_GITEA_CASES: frozenset[str] = frozenset(
    {
        # Positive scenarios (Acceptance Criteria paragraph 1; CI-AR35).
        "pr-verification-secret-free",
        "protected-dev-delivery",
        "protected-stable-delivery",
        "artifact-round-trip",
        "private-ca-boundary-package-index",
        "private-ca-boundary-forge-api",
        "multi-arch-image-linux-amd64-arm64",
        "forge-package-channel",
        "forge-release",
        "reusable-workflow-dev-release-shared",
        "reusable-workflow-publish-image",
        "aliases-last-behavior",
        # Recovery (ADR-0020).
        "failed-jobs-only-recovery",
        # Negative cases (Definition of Done / Technical ACs "Error and edge case
        # handling").
        "wrong-ca",
        "missing-credential-or-scope",
        "unknown-forge",
        "malformed-registry",
        "absent-default-branch-context",
        "restricted-permission-write-refusal",
        "endpoint-scope-omission",
        "artifact-output-loss-across-rerun",
        "package-image-failure",
        "stale-dev-candidate",
        "failed-jobs-only-unsupported",
    }
)


# Cases this environment cannot execute or fabricate evidence for, and why. This is the
# cross-check `docs/ci/gitea-certification.md` points back at: every one of these names
# a live-Gitea backlog item, never a static plant. A case absent from this mapping is
# claimed as statically resolvable by the validators in this module and exercised by a
# synthetic-fixture test below.
CASE_REQUIRES_LIVE_GITEA: dict[str, str] = {
    "pr-verification-secret-free": "requires a real PR run on the pinned runners",
    "protected-dev-delivery": "requires an actual protected dev publication run",
    "protected-stable-delivery": "requires an actual protected stable publication run",
    "artifact-round-trip": "requires a real upload/download cycle against the forge",
    "private-ca-boundary-package-index": "requires the pinned Gitea's private CA",
    "private-ca-boundary-forge-api": "requires the pinned Gitea's private CA",
    "multi-arch-image-linux-amd64-arm64": "requires a real Buildx push to the forge registry",
    "forge-package-channel": "requires a real forge package-index upload",
    "forge-release": "requires a real forge Release creation",
    "reusable-workflow-dev-release-shared": "requires executing the reusable workflow on Gitea",
    "reusable-workflow-publish-image": "requires executing publish-image.yaml on Gitea",
    "aliases-last-behavior": "requires a real multi-run alias-ordering observation",
    "failed-jobs-only-recovery": "requires a real per-job rerun against a live Gitea",
    "absent-default-branch-context": (
        "requires observing github.event.repository.default_branch on a live Gitea run"
    ),
    "restricted-permission-write-refusal": (
        "requires a live TokenPermissionMode=restricted denial, not a settings read-back"
    ),
    "failed-jobs-only-unsupported": "requires probing the pinned Gitea's rerun API directly",
}


def test_the_registry_is_non_empty_and_every_live_gated_case_is_a_real_requirement() -> (
    None
):
    """A registry with nothing in it would make every gate below vacuous."""
    assert REQUIRED_GITEA_CASES, "REQUIRED_GITEA_CASES is empty; nothing is required"
    unknown = set(CASE_REQUIRES_LIVE_GITEA) - REQUIRED_GITEA_CASES
    assert not unknown, (
        f"CASE_REQUIRES_LIVE_GITEA names case(s) not in REQUIRED_GITEA_CASES: "
        f"{sorted(unknown)}"
    )


def test_at_least_one_case_is_statically_resolvable_without_live_gitea() -> None:
    """If every case required a live Gitea, the validators below would have nothing to
    prove against a synthetic fixture and this module would be pure assertion.
    """
    statically_resolvable = REQUIRED_GITEA_CASES - set(CASE_REQUIRES_LIVE_GITEA)
    assert statically_resolvable, (
        "every required case is marked requires_live_gitea; the mechanical gate has "
        "nothing left to exercise against a synthetic fixture"
    )


# ---------------------------------------------------------------------------
# ADR-0017: the retained evidence export and the report-projection gate.
# ---------------------------------------------------------------------------

TrustBoundary = Literal["runner-bootstrap", "job-level-downstream"]

_TRUST_BOUNDARIES: frozenset[str] = frozenset(
    {"runner-bootstrap", "job-level-downstream"}
)


@dataclass(frozen=True)
class EvidenceRecord:
    """One source-native, API-sourced record backing one certification case.

    Field set is exactly ADR-0017's list: immutable run/attempt/job identity,
    timestamps and conclusion, source SHA, workflow path and revision SHA, the tuple
    fingerprint, and artifact hashes/digests.
    """

    case_id: str
    run_id: str
    run_attempt: int
    job_ids: tuple[str, ...]
    source_sha: str
    workflow_path: str
    workflow_revision_sha: str
    tuple_fingerprint: str
    artifact_hashes: tuple[str, ...]
    digests: tuple[str, ...]
    conclusion: str
    trust_boundary: TrustBoundary


@dataclass(frozen=True)
class EvidenceExport:
    """The retained ADR-0017 bundle.

    `files` holds every retained artifact's bytes (raw API responses, the tuple record,
    downloaded evidence, destination observations) keyed by its relative path;
    `checksum_lines` is the deterministic `SHA256SUMS` content as hex digests keyed by
    the same relative path; `digest` is the SHA-256 of the checksum file itself -- the
    evidence-export digest ADR-0017 names.
    """

    records: Mapping[str, EvidenceRecord]
    files: Mapping[str, bytes]
    checksum_lines: Mapping[str, str]
    digest: str


def _sha256sums_content(checksum_lines: Mapping[str, str]) -> bytes:
    lines = [f"{digest}  {path}\n" for path, digest in sorted(checksum_lines.items())]
    return "".join(lines).encode("utf-8")


def build_evidence_export(
    records: Mapping[str, EvidenceRecord], files: Mapping[str, bytes]
) -> EvidenceExport:
    """Construct a well-formed export: checksums and digest derived from `files`,
    never hand-typed, so a passing synthetic fixture proves the validator's arithmetic
    rather than an author's claim that two numbers happen to agree.
    """
    checksum_lines = {
        path: hashlib.sha256(content).hexdigest() for path, content in files.items()
    }
    digest = hashlib.sha256(_sha256sums_content(checksum_lines)).hexdigest()
    return EvidenceExport(
        records=records, files=files, checksum_lines=checksum_lines, digest=digest
    )


@dataclass(frozen=True)
class ReportRow:
    """One certification-report row: an exact projection of a retained `EvidenceRecord`
    plus the evidence-export digest it is bound to (ADR-0017, CI-AR41).
    """

    case_id: str
    run_id: str
    run_attempt: int
    job_ids: tuple[str, ...]
    source_sha: str
    workflow_path: str
    workflow_revision_sha: str
    tuple_fingerprint: str
    artifact_hashes: tuple[str, ...]
    digests: tuple[str, ...]
    conclusion: str
    evidence_export_digest: str
    trust_boundary: TrustBoundary


class CertificationGateError(AssertionError):
    """Raised by `resolve_certification_report` for any F20/ADR-0017 violation."""


_PROJECTED_FIELDS: tuple[str, ...] = (
    "run_id",
    "run_attempt",
    "job_ids",
    "source_sha",
    "workflow_path",
    "workflow_revision_sha",
    "tuple_fingerprint",
    "artifact_hashes",
    "digests",
    "conclusion",
    "trust_boundary",
)

# Credential-shaped value patterns the export and the report are scanned for (Security
# considerations: "The export and the report are both scanned for credential-shaped
# values; a planted echoed token or similar value in either must fail the gate.").
# Deliberately pattern-based rather than an allowlist of known secret names: the
# requirement is to catch the SHAPE of a credential, including one this project has
# never declared.
_CREDENTIAL_SHAPE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"glpat-[A-Za-z0-9_-]{20,}"),
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"[Aa]uthorization:\s*Bearer\s+[A-Za-z0-9._~+/=-]{16,}"),
    re.compile(r"[Bb]asic\s+[A-Za-z0-9+/=]{16,}"),
)


def _scan_for_credential_shapes(text: str) -> list[str]:
    hits: list[str] = []
    for pattern in _CREDENTIAL_SHAPE_PATTERNS:
        hits.extend(match.group(0) for match in pattern.finditer(text))
    return hits


def resolve_certification_report(
    report_rows: tuple[ReportRow, ...],
    export: EvidenceExport,
    required_cases: frozenset[str] = REQUIRED_GITEA_CASES,
) -> None:
    """The F20/ADR-0017 mechanical gate.

    Raises `CertificationGateError` on: a missing required case, an extra undeclared
    case, a duplicate row for one case, a row whose evidence-export digest or any
    projected field does not exactly match the retained export's record for that case
    (stale/cross-tuple/cross-source/cross-workflow evidence), a tampered or incomplete
    export (checksum mismatch), an invalid trust-boundary value, or a credential-shaped
    value anywhere in the rows or the retained files.
    """
    seen: dict[str, ReportRow] = {}
    for row in report_rows:
        if row.case_id in seen:
            raise CertificationGateError(
                f"duplicate report row for case {row.case_id!r}"
            )
        if row.case_id not in required_cases:
            raise CertificationGateError(
                f"report row for case {row.case_id!r}, which is not in "
                f"REQUIRED_GITEA_CASES -- an undeclared/extra case"
            )
        if row.trust_boundary not in _TRUST_BOUNDARIES:
            raise CertificationGateError(
                f"case {row.case_id!r}: trust_boundary {row.trust_boundary!r} is not "
                f"one of {sorted(_TRUST_BOUNDARIES)}"
            )
        seen[row.case_id] = row

    missing = required_cases - seen.keys()
    if missing:
        raise CertificationGateError(
            f"missing export-backed report row(s) for required case(s): {sorted(missing)}"
        )

    recomputed_checksum = {
        path: hashlib.sha256(content).hexdigest()
        for path, content in export.files.items()
    }
    if recomputed_checksum != dict(export.checksum_lines):
        raise CertificationGateError(
            "retained evidence file content does not match SHA256SUMS -- tampered or "
            "corrupted export"
        )
    recomputed_digest = hashlib.sha256(
        _sha256sums_content(export.checksum_lines)
    ).hexdigest()
    if recomputed_digest != export.digest:
        raise CertificationGateError(
            "the evidence-export digest does not match the SHA-256 of its own "
            "SHA256SUMS content"
        )

    for case_id, row in seen.items():
        if row.evidence_export_digest != export.digest:
            raise CertificationGateError(
                f"case {case_id!r}: report row's evidence-export digest does not match "
                f"the retained export (stale evidence)"
            )
        record = export.records.get(case_id)
        if record is None:
            raise CertificationGateError(
                f"case {case_id!r}: report row has no backing record in the retained "
                f"export -- a locally synthesized or Markdown-only row"
            )
        for projected_field in _PROJECTED_FIELDS:
            if getattr(row, projected_field) != getattr(record, projected_field):
                raise CertificationGateError(
                    f"case {case_id!r}: report field {projected_field!r} "
                    f"({getattr(row, projected_field)!r}) does not match the retained "
                    f"export's {getattr(record, projected_field)!r} -- cross-tuple, "
                    f"cross-source, cross-workflow, or stale report evidence"
                )

    corpus_parts = [repr(row) for row in seen.values()]
    corpus_parts.extend(
        content.decode("utf-8", errors="replace") for content in export.files.values()
    )
    hits = _scan_for_credential_shapes("\n".join(corpus_parts))
    if hits:
        raise CertificationGateError(
            f"credential-shaped value(s) found in the report or retained export: {hits}"
        )

    # One certification attempt certifies exactly one pinned Gitea tuple (ADR-0015).
    # `tuple_fingerprint` is that attempt's non-secret correlation identifier joining
    # every case's evidence into a single attempt. Every row above has already been
    # proven to match its own retained record, so a fingerprint split here means the
    # retained *export* itself mixes evidence from more than one attempt/tuple, not
    # merely that one row was tampered (resolves BL-E009-005 / AG-9).
    fingerprints = {row.tuple_fingerprint for row in seen.values()}
    if len(fingerprints) > 1:
        raise CertificationGateError(
            "retained evidence does not share one tuple_fingerprint across required "
            f"cases -- {sorted(seen)} span {sorted(fingerprints)}, so this export is "
            "not one certification attempt against one pinned tuple"
        )


# ---------------------------------------------------------------------------
# Synthetic fixtures. Clearly marked: none of this is real Gitea output.
# ---------------------------------------------------------------------------


def _synthetic_record(case_id: str, **overrides: object) -> EvidenceRecord:
    """SYNTHETIC FIXTURE DATA -- not a real Gitea API response. One deterministic,
    internally-consistent record per case, used only to exercise the validator above.
    """
    defaults: dict[str, object] = {
        "case_id": case_id,
        "run_id": f"run-{case_id}",
        "run_attempt": 1,
        "job_ids": (f"job-{case_id}-1",),
        "source_sha": "a" * 40,
        "workflow_path": ".gitea/workflows/dev.yaml",
        "workflow_revision_sha": "b" * 40,
        "tuple_fingerprint": "sha256:" + "c" * 64,
        "artifact_hashes": ("sha256:" + "d" * 64,),
        "digests": ("sha256:" + "e" * 64,),
        "conclusion": "success",
        "trust_boundary": "job-level-downstream",
    }
    defaults.update(overrides)
    return EvidenceRecord(**defaults)  # type: ignore[arg-type]


def _synthetic_row_from_record(record: EvidenceRecord, export_digest: str) -> ReportRow:
    return ReportRow(
        case_id=record.case_id,
        run_id=record.run_id,
        run_attempt=record.run_attempt,
        job_ids=record.job_ids,
        source_sha=record.source_sha,
        workflow_path=record.workflow_path,
        workflow_revision_sha=record.workflow_revision_sha,
        tuple_fingerprint=record.tuple_fingerprint,
        artifact_hashes=record.artifact_hashes,
        digests=record.digests,
        conclusion=record.conclusion,
        evidence_export_digest=export_digest,
        trust_boundary=record.trust_boundary,
    )


def _statically_resolvable_cases() -> frozenset[str]:
    return REQUIRED_GITEA_CASES - set(CASE_REQUIRES_LIVE_GITEA)


def _complete_synthetic_fixture() -> tuple[tuple[ReportRow, ...], EvidenceExport]:
    """A fully-resolved, internally-consistent SYNTHETIC export+report pair covering
    every statically-resolvable required case. The baseline every corruption test below
    mutates one property of.
    """
    cases = sorted(_statically_resolvable_cases())
    records = {case_id: _synthetic_record(case_id) for case_id in cases}
    files = {
        f"records/{case_id}.json": repr(record).encode("utf-8")
        for case_id, record in records.items()
    }
    files["tuple-record.json"] = b'{"tuple": "SYNTHETIC FIXTURE DATA"}'
    export = build_evidence_export(records, files)
    rows = tuple(
        _synthetic_row_from_record(record, export.digest) for record in records.values()
    )
    return rows, export


def test_a_fully_resolved_synthetic_fixture_passes_the_gate() -> None:
    """The baseline: a complete, internally-consistent, checksummed export with one
    export-backed row per statically-resolvable required case resolves cleanly. Every
    test below plants exactly one deviation from this fixture and requires the gate to
    reject it.
    """
    rows, export = _complete_synthetic_fixture()
    resolve_certification_report(
        rows, export, required_cases=_statically_resolvable_cases()
    )


def test_a_missing_report_row_fails_resolution() -> None:
    """Plant: delete one required case's report row."""
    rows, export = _complete_synthetic_fixture()
    with pytest.raises(
        CertificationGateError, match="missing export-backed report row"
    ):
        resolve_certification_report(
            rows[1:], export, required_cases=_statically_resolvable_cases()
        )


def test_an_extra_undeclared_case_fails_resolution() -> None:
    """Plant: a scope addition -- a report row for a case REQUIRED_GITEA_CASES does not
    declare -- the F20 scope-plant anchor in reverse (adding evidence instead of a
    requirement).
    """
    rows, export = _complete_synthetic_fixture()
    extra_record = _synthetic_record("undeclared-case")
    extra_row = _synthetic_row_from_record(extra_record, export.digest)
    with pytest.raises(CertificationGateError, match="not in REQUIRED_GITEA_CASES"):
        resolve_certification_report(
            rows + (extra_row,), export, required_cases=_statically_resolvable_cases()
        )


def test_a_duplicate_case_row_fails_resolution() -> None:
    """Plant: two rows claiming the same case."""
    rows, export = _complete_synthetic_fixture()
    with pytest.raises(CertificationGateError, match="duplicate report row"):
        resolve_certification_report(
            rows + (rows[0],), export, required_cases=_statically_resolvable_cases()
        )


def test_a_cross_tuple_row_fails_resolution() -> None:
    """Plant: a report row whose tuple fingerprint does not match the retained export's
    record for that case -- cross-tuple evidence substitution.
    """
    rows, export = _complete_synthetic_fixture()
    tampered = replace(rows[0], tuple_fingerprint="sha256:" + "0" * 64)
    with pytest.raises(
        CertificationGateError, match="cross-tuple, cross-source, cross-workflow"
    ):
        resolve_certification_report(
            (tampered,) + rows[1:],
            export,
            required_cases=_statically_resolvable_cases(),
        )


def test_a_cross_source_sha_row_fails_resolution() -> None:
    """Plant: a stale run from another source SHA."""
    rows, export = _complete_synthetic_fixture()
    tampered = replace(rows[0], source_sha="f" * 40)
    with pytest.raises(
        CertificationGateError, match="cross-tuple, cross-source, cross-workflow"
    ):
        resolve_certification_report(
            (tampered,) + rows[1:],
            export,
            required_cases=_statically_resolvable_cases(),
        )


def test_a_cross_workflow_row_fails_resolution() -> None:
    """Plant: a row whose workflow path/revision does not match its case's record."""
    rows, export = _complete_synthetic_fixture()
    tampered = replace(rows[0], workflow_path=".gitea/workflows/release.yaml")
    with pytest.raises(
        CertificationGateError, match="cross-tuple, cross-source, cross-workflow"
    ):
        resolve_certification_report(
            (tampered,) + rows[1:],
            export,
            required_cases=_statically_resolvable_cases(),
        )


def test_an_export_mixing_two_tuple_fingerprints_fails_resolution() -> None:
    """Plant: two records, each internally consistent (its row matches its own
    retained record), but drawn from two different pinned tuples -- an export that
    mixes evidence from two certification attempts with no single shared correlation
    identifier. Per-row cross-tuple corruption (above) is a different, already-covered
    case; this is the gap AG-9 / BL-E009-005 found: nothing previously required every
    case in one report to agree on `tuple_fingerprint`.
    """
    cases = sorted(_statically_resolvable_cases())
    other_fingerprint = "sha256:" + "9" * 64
    records = {
        case_id: _synthetic_record(
            case_id,
            tuple_fingerprint=(
                other_fingerprint if case_id == cases[0] else "sha256:" + "c" * 64
            ),
        )
        for case_id in cases
    }
    files = {
        f"records/{case_id}.json": repr(record).encode("utf-8")
        for case_id, record in records.items()
    }
    files["tuple-record.json"] = b'{"tuple": "SYNTHETIC FIXTURE DATA"}'
    export = build_evidence_export(records, files)
    rows = tuple(
        _synthetic_row_from_record(record, export.digest) for record in records.values()
    )
    with pytest.raises(
        CertificationGateError, match="does not share one tuple_fingerprint"
    ):
        resolve_certification_report(
            rows, export, required_cases=_statically_resolvable_cases()
        )


def test_a_stale_evidence_export_digest_fails_resolution() -> None:
    """Plant: a report row bound to an export digest that is not this export's digest --
    a plausible-looking row whose backing export was swapped out from under it."""
    rows, export = _complete_synthetic_fixture()
    tampered = replace(rows[0], evidence_export_digest="0" * 64)
    with pytest.raises(CertificationGateError, match="stale evidence"):
        resolve_certification_report(
            (tampered,) + rows[1:],
            export,
            required_cases=_statically_resolvable_cases(),
        )


def test_a_changed_api_response_after_checksumming_fails_resolution() -> None:
    """Plant: the retained export's file content is mutated after SHA256SUMS was
    computed -- the checksum no longer matches, which is exactly the tamper-evidence
    property ADR-0017 requires.
    """
    rows, export = _complete_synthetic_fixture()
    mutated_files = dict(export.files)
    some_path = next(iter(mutated_files))
    mutated_files[some_path] = mutated_files[some_path] + b"tampered"
    tampered_export = replace(export, files=mutated_files)
    with pytest.raises(CertificationGateError, match="tampered or corrupted export"):
        resolve_certification_report(
            rows, tampered_export, required_cases=_statically_resolvable_cases()
        )


def test_incomplete_pagination_is_an_unhashed_or_absent_file_and_fails_resolution() -> (
    None
):
    """Plant: a retained file referenced by `checksum_lines` is missing from `files`
    entirely -- the shape incomplete API pagination would leave behind (some pages
    never retained, so their listed checksum resolves against nothing).
    """
    rows, export = _complete_synthetic_fixture()
    missing_path = next(iter(export.files))
    truncated_files = {
        path: content for path, content in export.files.items() if path != missing_path
    }
    truncated_export = replace(export, files=truncated_files)
    with pytest.raises(CertificationGateError, match="tampered or corrupted export"):
        resolve_certification_report(
            rows, truncated_export, required_cases=_statically_resolvable_cases()
        )


def test_a_locally_synthesized_record_with_no_export_backing_fails_resolution() -> None:
    """Plant: a report row for a required case for which the export carries no backing
    record at all -- "a plausible Markdown row with no API record".
    """
    rows, export = _complete_synthetic_fixture()
    orphan_records = dict(export.records)
    some_case = rows[0].case_id
    del orphan_records[some_case]
    orphan_export = replace(export, records=orphan_records)
    with pytest.raises(CertificationGateError, match="no backing record"):
        resolve_certification_report(
            rows, orphan_export, required_cases=_statically_resolvable_cases()
        )


def test_a_credential_shaped_value_in_the_export_fails_redaction() -> None:
    """Plant: a planted echoed token inside a retained file. SYNTHETIC -- this string is
    shaped like a GitHub PAT and is not a real credential.
    """
    rows, export = _complete_synthetic_fixture()
    poisoned_files = dict(export.files)
    some_path = next(iter(poisoned_files))
    poisoned_files[some_path] = poisoned_files[some_path] + (
        b"\nSYNTHETIC FIXTURE DATA echoed-token=ghp_" + b"a" * 36
    )
    poisoned_export = build_evidence_export(export.records, poisoned_files)
    poisoned_rows = tuple(
        replace(row, evidence_export_digest=poisoned_export.digest) for row in rows
    )
    with pytest.raises(CertificationGateError, match="credential-shaped value"):
        resolve_certification_report(
            poisoned_rows,
            poisoned_export,
            required_cases=_statically_resolvable_cases(),
        )


def test_a_credential_shaped_value_in_the_report_fails_redaction() -> None:
    """Plant: the report projection itself -- not the export -- carries a credential
    shape, e.g. echoed into a job ID. SYNTHETIC -- not a real credential."""
    rows, export = _complete_synthetic_fixture()
    poisoned = replace(rows[0], job_ids=("job-1", "Authorization: Bearer " + "x" * 32))
    with pytest.raises(CertificationGateError):
        resolve_certification_report(
            (poisoned,) + rows[1:],
            export,
            required_cases=_statically_resolvable_cases(),
        )


def test_an_invalid_trust_boundary_value_fails_resolution() -> None:
    """DoD: "the certification report distinguishes runner bootstrap trust from
    job-level downstream trust" -- enforced here as a closed, non-empty vocabulary
    rather than a free-text field a row could leave blank or misspell.
    """
    rows, export = _complete_synthetic_fixture()
    tampered = replace(rows[0], trust_boundary="unspecified")  # type: ignore[arg-type]
    with pytest.raises(CertificationGateError, match="trust_boundary"):
        resolve_certification_report(
            (tampered,) + rows[1:],
            export,
            required_cases=_statically_resolvable_cases(),
        )


def test_missing_artifact_hash_is_a_projection_mismatch() -> None:
    """DoD: "a missing artifact or evidence-export digest field" -- a row that drops an
    artifact hash the record carries no longer projects it exactly and fails.
    """
    rows, export = _complete_synthetic_fixture()
    tampered = replace(rows[0], artifact_hashes=())
    with pytest.raises(
        CertificationGateError, match="cross-tuple, cross-source, cross-workflow"
    ):
        resolve_certification_report(
            (tampered,) + rows[1:],
            export,
            required_cases=_statically_resolvable_cases(),
        )


# ---------------------------------------------------------------------------
# ADR-0016: preflight-versus-full-scenario action closure comparison.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ActionClosureRecord:
    """One closure record -- Story 9.1's bounded preflight record, or Story 9.2's
    full-scenario record -- bound to the retained evidence by its digest.
    """

    digest: str
    actions: frozenset[str]


class ClosureDriftError(AssertionError):
    """Raised by `compare_action_closures` for unexplained closure drift (ADR-0016)."""


def compare_action_closures(
    preflight: ActionClosureRecord,
    full_scenario: ActionClosureRecord,
    explained: Mapping[str, str] = {},
) -> None:
    """Compare Story 9.1's preflight closure against Story 9.2's full-scenario closure.

    Any addition or omission not present in `explained` (action -> reason, e.g. "only
    reached by the failed-jobs-only rerun path") fails -- ADR-0016's "Any unexplained
    addition, omission, or resolution drift fails certification."
    """
    added = full_scenario.actions - preflight.actions
    omitted = preflight.actions - full_scenario.actions
    unexplained_added = added - explained.keys()
    unexplained_omitted = omitted - explained.keys()
    if unexplained_added:
        raise ClosureDriftError(
            f"full-scenario closure contains action(s) not in the Story 9.1 preflight "
            f"closure and not explained: {sorted(unexplained_added)} (ADR-0016)"
        )
    if unexplained_omitted:
        raise ClosureDriftError(
            f"Story 9.1 preflight closure contains action(s) absent from the "
            f"full-scenario closure and not explained: {sorted(unexplained_omitted)} "
            f"(ADR-0016)"
        )


def test_identical_closures_pass() -> None:
    actions = frozenset({"actions/checkout", "docker/login-action"})
    preflight = ActionClosureRecord(digest="p" * 64, actions=actions)
    full_scenario = ActionClosureRecord(digest="f" * 64, actions=actions)
    compare_action_closures(preflight, full_scenario)


def test_an_explained_addition_passes() -> None:
    """The action named in the Test anchor: "an action used only by a failure/rerun
    path", here declared with its reason -- the passing half of that anchor.
    """
    preflight = ActionClosureRecord(
        digest="p" * 64, actions=frozenset({"actions/checkout"})
    )
    full_scenario = ActionClosureRecord(
        digest="f" * 64,
        actions=frozenset({"actions/checkout", "actions/download-artifact"}),
    )
    compare_action_closures(
        preflight,
        full_scenario,
        explained={
            "actions/download-artifact": (
                "only reached by the failed-jobs-only rerun path, which Story 9.1's "
                "smoke scenarios never exercise"
            )
        },
    )


def test_an_unexplained_addition_fails() -> None:
    """Plant: the same action as above, this time undeclared -- the Test anchor's
    required failure: "Plant an action used only by a failure/rerun path and require
    unexplained drift to fail."
    """
    preflight = ActionClosureRecord(
        digest="p" * 64, actions=frozenset({"actions/checkout"})
    )
    full_scenario = ActionClosureRecord(
        digest="f" * 64,
        actions=frozenset({"actions/checkout", "actions/download-artifact"}),
    )
    with pytest.raises(ClosureDriftError, match="not explained"):
        compare_action_closures(preflight, full_scenario)


def test_an_unexplained_omission_fails() -> None:
    """An action the preflight observed but the full-scenario closure no longer reaches
    is drift too -- resolution drift, not only addition.
    """
    preflight = ActionClosureRecord(
        digest="p" * 64, actions=frozenset({"actions/checkout", "actions/setup-python"})
    )
    full_scenario = ActionClosureRecord(
        digest="f" * 64, actions=frozenset({"actions/checkout"})
    )
    with pytest.raises(ClosureDriftError, match="not explained"):
        compare_action_closures(preflight, full_scenario)


# ---------------------------------------------------------------------------
# ADR-0020: fault-injection and cleanup-postcondition contract.
# ---------------------------------------------------------------------------

_STAGING_ONLY_DESTINATION_LOCAL_MECHANISMS: tuple[str, ...] = (
    "revoke-destination-credential",
    "unreachable-destination-endpoint",
)

RESOURCE_CLASSES: frozenset[str] = frozenset(
    {"package", "image", "release", "alias", "token", "artifact", "workspace"}
)


@dataclass(frozen=True)
class DestinationObservation:
    """A publication destination's recorded conclusion, start time, and outputs --
    exactly the three properties ADR-0020 requires to be unchanged across a rerun.
    """

    conclusion: str
    start_time: str
    outputs: Mapping[str, str]


@dataclass(frozen=True)
class RecoveryPreState:
    """Recorded before rerun (ADR-0020): which destinations already succeeded and their
    observations, which destination is expected to fail and why, the staging-only
    destination-local fault-injection mechanism used, and that it was injected only
    after at least one other destination's immutable publication.
    """

    destinations: Mapping[str, DestinationObservation]
    expected_to_fail: str
    fault_injection_mechanism: str
    injected_after: tuple[str, ...]


@dataclass(frozen=True)
class ResourceCleanupState:
    """Cleanup postconditions for every touched resource class (ADR-0020): nonempty
    entries here are the orphaned/stale residue the contract forbids after success.
    """

    orphaned_partial_uploads: tuple[str, ...] = ()
    stale_credentials: tuple[str, ...] = ()
    stale_workspaces: tuple[str, ...] = ()


@dataclass(frozen=True)
class RecoveryPostState:
    """Recorded after rerun (ADR-0020): which job(s) actually reran, the post-rerun
    observation per destination, any destination against which a second upload/publish
    request was recorded, and the cleanup postconditions.
    """

    rerun_job_names: tuple[str, ...]
    destinations: Mapping[str, DestinationObservation]
    second_upload_requests: tuple[str, ...]
    cleanup: ResourceCleanupState


class RecoveryContractError(AssertionError):
    """Raised by `assert_recovery_contract` for any ADR-0020 violation."""


def assert_recovery_contract(pre: RecoveryPreState, post: RecoveryPostState) -> None:
    if pre.fault_injection_mechanism not in _STAGING_ONLY_DESTINATION_LOCAL_MECHANISMS:
        raise RecoveryContractError(
            f"fault_injection_mechanism {pre.fault_injection_mechanism!r} is not one of "
            f"the staging-only, destination-local mechanisms ADR-0020 names: "
            f"{_STAGING_ONLY_DESTINATION_LOCAL_MECHANISMS}"
        )
    if not pre.injected_after:
        raise RecoveryContractError(
            "the fault was not recorded as injected after at least one other "
            "destination's successful immutable publication (ADR-0020); without that, "
            "the scenario is a total failure, not a partial one"
        )
    for name in pre.injected_after:
        if name not in pre.destinations:
            raise RecoveryContractError(
                f"{name!r} is recorded as already-succeeded-before-injection but has no "
                f"pre-state observation"
            )

    if set(post.rerun_job_names) != {pre.expected_to_fail}:
        raise RecoveryContractError(
            f"rerun targeted {sorted(post.rerun_job_names)}; ADR-0020 rerun identity "
            f"requires exactly the one failed destination, {pre.expected_to_fail!r}"
        )

    for name in pre.injected_after:
        before = pre.destinations[name]
        after = post.destinations.get(name)
        if after is None:
            raise RecoveryContractError(
                f"{name!r} has no post-rerun observation to compare against its pre-state"
            )
        if before != after:
            raise RecoveryContractError(
                f"{name!r}'s conclusion/start_time/outputs changed across rerun "
                f"(before={before!r}, after={after!r}); ADR-0020 preservation requires "
                f"them unchanged"
            )
        if name in post.second_upload_requests:
            raise RecoveryContractError(
                f"a second upload/publish request was recorded against the "
                f"already-successful destination {name!r}"
            )

    if post.cleanup.orphaned_partial_uploads:
        raise RecoveryContractError(
            f"orphaned partial upload(s) remain after rerun: "
            f"{post.cleanup.orphaned_partial_uploads}"
        )
    if post.cleanup.stale_credentials:
        raise RecoveryContractError(
            f"stale credential(s) remain after rerun: {post.cleanup.stale_credentials}"
        )
    if post.cleanup.stale_workspaces:
        raise RecoveryContractError(
            f"stale workspace(s) remain after rerun: {post.cleanup.stale_workspaces}"
        )


def _clean_recovery_fixture() -> tuple[RecoveryPreState, RecoveryPostState]:
    """SYNTHETIC FIXTURE DATA: two destinations, one succeeds, one is fault-injected
    after the first succeeds, and recovers cleanly.
    """
    forge_package = DestinationObservation(
        conclusion="success",
        start_time="2026-10-06T10:00:00Z",
        outputs={"plan-identity": "p1", "build-manifest-sha256": "d" * 64},
    )
    pre = RecoveryPreState(
        destinations={"forge-package": forge_package},
        expected_to_fail="publish-image",
        fault_injection_mechanism="revoke-destination-credential",
        injected_after=("forge-package",),
    )
    post = RecoveryPostState(
        rerun_job_names=("publish-image",),
        destinations={"forge-package": forge_package},
        second_upload_requests=(),
        cleanup=ResourceCleanupState(),
    )
    return pre, post


def test_a_clean_recovery_satisfies_the_adr_0020_contract() -> None:
    pre, post = _clean_recovery_fixture()
    assert_recovery_contract(pre, post)


def test_rerunning_a_successful_destination_fails_rerun_identity() -> None:
    """Plant: the rerun targets more than the one failed destination."""
    pre, post = _clean_recovery_fixture()
    tampered = replace(post, rerun_job_names=("publish-image", "forge-package"))
    with pytest.raises(RecoveryContractError, match="rerun identity"):
        assert_recovery_contract(pre, tampered)


def test_empty_needs_outputs_on_a_successful_destination_fails_preservation() -> None:
    """Plant: empty `needs` outputs on the already-successful destination -- the Test
    anchor's named plant ("Plant empty `needs` outputs and lost artifact scope").
    """
    pre, post = _clean_recovery_fixture()
    emptied = DestinationObservation(
        conclusion="success", start_time="2026-10-06T10:00:00Z", outputs={}
    )
    tampered = replace(post, destinations={"forge-package": emptied})
    with pytest.raises(RecoveryContractError, match="preservation"):
        assert_recovery_contract(pre, tampered)


def test_lost_artifact_scope_fails_preservation() -> None:
    """Plant: `build-manifest-sha256` dropped from the successful destination's
    outputs -- lost artifact scope across the rerun."""
    pre, post = _clean_recovery_fixture()
    narrowed = DestinationObservation(
        conclusion="success",
        start_time="2026-10-06T10:00:00Z",
        outputs={"plan-identity": "p1"},
    )
    tampered = replace(post, destinations={"forge-package": narrowed})
    with pytest.raises(RecoveryContractError, match="preservation"):
        assert_recovery_contract(pre, tampered)


def test_a_second_upload_request_against_a_successful_destination_fails() -> None:
    """ADR-0020 preservation is "no second upload/publish request", checked
    independently of whether the recorded state happens to still match."""
    pre, post = _clean_recovery_fixture()
    tampered = replace(post, second_upload_requests=("forge-package",))
    with pytest.raises(RecoveryContractError, match="second upload/publish request"):
        assert_recovery_contract(pre, tampered)


def test_an_orphaned_partial_upload_fails_cleanup() -> None:
    pre, post = _clean_recovery_fixture()
    tampered = replace(
        post, cleanup=ResourceCleanupState(orphaned_partial_uploads=("image-blob-1",))
    )
    with pytest.raises(RecoveryContractError, match="orphaned partial upload"):
        assert_recovery_contract(pre, tampered)


def test_a_stale_credential_fails_cleanup() -> None:
    pre, post = _clean_recovery_fixture()
    tampered = replace(
        post, cleanup=ResourceCleanupState(stale_credentials=("revoked-token",))
    )
    with pytest.raises(RecoveryContractError, match="stale credential"):
        assert_recovery_contract(pre, tampered)


def test_a_stale_workspace_fails_cleanup() -> None:
    pre, post = _clean_recovery_fixture()
    tampered = replace(
        post, cleanup=ResourceCleanupState(stale_workspaces=("runner-workspace-7",))
    )
    with pytest.raises(RecoveryContractError, match="stale workspace"):
        assert_recovery_contract(pre, tampered)


def test_the_fault_injection_mechanism_must_be_staging_only_and_destination_local() -> (
    None
):
    """Plant: a mechanism that is neither of ADR-0020's two named forms (e.g. disabling
    the whole Gitea instance would be total failure, not destination-local partial
    failure).
    """
    pre, post = _clean_recovery_fixture()
    tampered = replace(pre, fault_injection_mechanism="disable-the-gitea-instance")
    with pytest.raises(RecoveryContractError, match="staging-only, destination-local"):
        assert_recovery_contract(tampered, post)


def test_the_fault_must_be_injected_after_another_destination_already_succeeded() -> (
    None
):
    """Plant: no destination had yet published when the fault was injected -- this
    would be total failure, not the partial-failure scenario ADR-0020 requires.
    """
    pre, post = _clean_recovery_fixture()
    tampered = replace(pre, injected_after=())
    with pytest.raises(
        RecoveryContractError, match="injected after at least one other"
    ):
        assert_recovery_contract(tampered, post)


def test_the_immutable_index_rejection_is_not_accepted_in_place_of_the_assertions_above() -> (
    None
):
    """ADR-0020: "An immutable-index rejection observed during the scenario is recorded
    as a defense-in-depth signal, not accepted in place of the preservation and cleanup
    assertions above." Modeled here as: recording a rejection signal alongside an
    otherwise-broken contract does not make `assert_recovery_contract` pass.
    """
    pre, post = _clean_recovery_fixture()
    tampered_cleanup = ResourceCleanupState(orphaned_partial_uploads=("image-blob-1",))
    tampered = replace(post, cleanup=tampered_cleanup)
    # A rejection signal would be carried as a destination output; adding one changes
    # nothing about whether cleanup passed, which is the point being modeled.
    rejection_recorded = replace(
        tampered,
        destinations={
            **tampered.destinations,
            "forge-package": replace(
                tampered.destinations["forge-package"],
                outputs={
                    **tampered.destinations["forge-package"].outputs,
                    "immutable-index-rejection-observed": "true",
                },
            ),
        },
    )
    with pytest.raises(RecoveryContractError):
        assert_recovery_contract(pre, rejection_recorded)


# ---------------------------------------------------------------------------
# Observability requirement: step-summary rendering is an observation, never a
# pass/fail criterion; job outputs are the durable, authoritative signal.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CaseOutcome:
    job_output_conclusion: str
    step_summary_text: str


def case_passed(outcome: CaseOutcome) -> bool:
    """The gate's pass/fail predicate reads only the job output; the step summary is
    rendered for a human and is never consulted here, however it reads.
    """
    return outcome.job_output_conclusion == "success"


def test_a_misleading_step_summary_does_not_change_the_outcome_a_job_output_gives() -> (
    None
):
    """Plant: a step summary that reads 'FAILED' while the job output says success --
    the step summary must not flip the result.
    """
    outcome = CaseOutcome(
        job_output_conclusion="success", step_summary_text="FAILED (stale render)"
    )
    assert case_passed(outcome) is True


def test_a_reassuring_step_summary_does_not_change_the_outcome_a_job_output_gives() -> (
    None
):
    """The converse plant: a step summary claiming success while the job output
    recorded failure must not be read as a pass.
    """
    outcome = CaseOutcome(
        job_output_conclusion="failure", step_summary_text="All green!"
    )
    assert case_passed(outcome) is False


# ---------------------------------------------------------------------------
# Cases this module does not and cannot resolve statically.
# ---------------------------------------------------------------------------


@pytest.mark.requires_live_gitea
def test_a_real_certification_run_resolves_against_a_real_evidence_export() -> None:
    """The one test this module cannot run: collecting a real ADR-0017 evidence export
    from a live Gitea instance and resolving a real certification report against it and
    against `REQUIRED_GITEA_CASES`. Every validator exercised above is the mechanism
    that run would use; only the live collection and the live forge responses are
    missing here. See `docs/ci/gitea-certification.md` for the manual runbook.
    """
    pytest.skip("requires a live Gitea instance; see docs/ci/gitea-certification.md")
