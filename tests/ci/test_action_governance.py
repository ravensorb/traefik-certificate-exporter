"""ADR-0022: per-action governance over the observed transitive closure.

Story 9.1 (this story's own epic/sprint numbering) extends the pinned tuple record
beyond reference and resolved commit to publisher/trust class, maintenance status,
license compatibility, GA status, and supported major version, per action in the
closure (ADR-0022). Credential-bearing actions and any unapproved third-party action
require a full-SHA pin; any non-GA/preview action requires its own accepting ADR.

What this module can prove without a live Gitea: the governance registry below covers
every external action actually referenced by a governed definition (derived from the
parsed workflows/composites, not a hand-copied list), every entry's claimed pin
requirement matches what `tests/ci/test_action_policy.py`'s registries actually
enforce, and a planted non-GA action with no accepting ADR is rejected.

What it cannot prove: that `git-action-release@v2`'s Gitea-path platform detection
makes (or does not make) a network request, or which trust boundary covers it -- ADR-22
calls this a Story 9.1 predecessor probe, and it requires executing the action against
a real Gitea runner. That probe, and the live/offline evidence for the resulting
release-fallback decision, are not executed here; see `docs/ci/gitea-runners.md`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import pytest

from tests.ci.support import (
    CREDENTIAL_ACTIONS_ON_MOVING_REFS,
    GOVERNED_DEFINITIONS,
    SHA_PINNED_ACTIONS,
    _action_references,
)

TrustClass = Literal["first-party", "approved-third-party", "unapproved-third-party"]
GAStatus = Literal["ga", "preview"]
PinKind = Literal["full-sha", "floating-major"]


@dataclass(frozen=True)
class ActionGovernance:
    """One ADR-0022 tuple-record row for an action in the observed closure."""

    publisher: str
    trust_class: TrustClass
    maintenance_status: str
    license_spdx: str
    license_compatible: bool
    ga_status: GAStatus
    supported_major: int
    pin_kind: PinKind
    # Required only when ga_status == "preview": the ADR accepting the risk and the
    # exit plan it must carry (ADR-0022). None otherwise, and a schema check below
    # requires that absence/presence match ga_status exactly.
    accepting_adr: str | None = None


# One row per action actually referenced by a governed definition (`actions/checkout`,
# `docker/login-action`, etc.), derived by name below rather than discovered fresh here
# so a new action in the closure is flagged for a row instead of silently passing.
# Every entry here is maintained, OSI/permissive-licensed, GA, and on its current major
# -- the closure this repository actually has, checked against public registry state at
# the time this story was implemented.
ACTION_GOVERNANCE: dict[str, ActionGovernance] = {
    "actions/checkout": ActionGovernance(
        publisher="GitHub (first-party)",
        trust_class="first-party",
        maintenance_status="actively maintained",
        license_spdx="MIT",
        license_compatible=True,
        ga_status="ga",
        supported_major=7,
        pin_kind="floating-major",
    ),
    "actions/setup-python": ActionGovernance(
        publisher="GitHub (first-party)",
        trust_class="first-party",
        maintenance_status="actively maintained",
        license_spdx="MIT",
        license_compatible=True,
        ga_status="ga",
        supported_major=7,
        pin_kind="floating-major",
    ),
    "actions/upload-artifact": ActionGovernance(
        publisher="GitHub (first-party)",
        trust_class="first-party",
        maintenance_status="actively maintained",
        license_spdx="MIT",
        license_compatible=True,
        ga_status="ga",
        supported_major=4,
        pin_kind="floating-major",
    ),
    "actions/download-artifact": ActionGovernance(
        publisher="GitHub (first-party)",
        trust_class="first-party",
        maintenance_status="actively maintained",
        license_spdx="MIT",
        license_compatible=True,
        ga_status="ga",
        supported_major=4,
        pin_kind="floating-major",
    ),
    "actions/attest-build-provenance": ActionGovernance(
        publisher="GitHub (first-party)",
        trust_class="first-party",
        maintenance_status="actively maintained",
        license_spdx="MIT",
        license_compatible=True,
        ga_status="ga",
        supported_major=3,
        pin_kind="floating-major",
    ),
    "docker/login-action": ActionGovernance(
        publisher="Docker, Inc. (approved third party)",
        trust_class="approved-third-party",
        maintenance_status="actively maintained",
        license_spdx="Apache-2.0",
        license_compatible=True,
        ga_status="ga",
        supported_major=3,
        pin_kind="floating-major",
    ),
    "docker/setup-buildx-action": ActionGovernance(
        publisher="Docker, Inc. (approved third party)",
        trust_class="approved-third-party",
        maintenance_status="actively maintained",
        license_spdx="Apache-2.0",
        license_compatible=True,
        ga_status="ga",
        supported_major=3,
        pin_kind="floating-major",
    ),
    "docker/setup-qemu-action": ActionGovernance(
        publisher="Docker, Inc. (approved third party)",
        trust_class="approved-third-party",
        maintenance_status="actively maintained",
        license_spdx="Apache-2.0",
        license_compatible=True,
        ga_status="ga",
        supported_major=3,
        pin_kind="floating-major",
    ),
    "pypa/gh-action-pypi-publish": ActionGovernance(
        publisher="Python Packaging Authority (approved third party)",
        trust_class="approved-third-party",
        maintenance_status="actively maintained",
        license_spdx="BSD-3-Clause",
        license_compatible=True,
        ga_status="ga",
        supported_major=1,
        # Receives the OIDC-derived publication credential directly; already
        # SHA_PINNED_ACTIONS-governed (CI-AR38), and the two registries are checked
        # for consistency below rather than duplicated as a separate fact.
        pin_kind="full-sha",
    ),
    "LiquidLogicLabs/git-action-release": ActionGovernance(
        publisher="LiquidLogicLabs (maintainer-owned org; first-party in practice, ADR-0010)",
        trust_class="first-party",
        maintenance_status="actively maintained",
        license_spdx="MIT",
        license_compatible=True,
        ga_status="ga",
        supported_major=2,
        pin_kind="floating-major",
    ),
    "LiquidLogicLabs/git-action-tag-floating-version": ActionGovernance(
        publisher="LiquidLogicLabs (maintainer-owned org; first-party in practice, ADR-0010)",
        trust_class="first-party",
        maintenance_status="actively maintained",
        license_spdx="MIT",
        license_compatible=True,
        ga_status="ga",
        supported_major=2,
        pin_kind="floating-major",
    ),
    "LiquidLogicLabs/git-action-docker-test": ActionGovernance(
        publisher="LiquidLogicLabs (maintainer-owned org; first-party in practice, ADR-0010)",
        trust_class="first-party",
        maintenance_status="actively maintained",
        license_spdx="MIT",
        license_compatible=True,
        ga_status="ga",
        supported_major=1,
        pin_kind="floating-major",
    ),
    "LiquidLogicLabs/git-action-docker-metadata": ActionGovernance(
        publisher="LiquidLogicLabs (maintainer-owned org; first-party in practice, ADR-0010)",
        trust_class="first-party",
        maintenance_status="actively maintained",
        license_spdx="MIT",
        license_compatible=True,
        ga_status="ga",
        supported_major=1,
        pin_kind="floating-major",
    ),
    "LiquidLogicLabs/git-action-ca-certificate-import": ActionGovernance(
        publisher="LiquidLogicLabs (maintainer-owned org; first-party in practice, ADR-0010)",
        trust_class="first-party",
        maintenance_status="actively maintained",
        license_spdx="MIT",
        license_compatible=True,
        ga_status="ga",
        supported_major=3,
        pin_kind="floating-major",
    ),
}


def _referenced_external_actions() -> set[str]:
    referenced: set[str] = set()
    for path in GOVERNED_DEFINITIONS:
        for reference in _action_references(path):
            if reference.startswith("./"):
                continue
            referenced.add(reference.split("@", 1)[0])
    return referenced


def test_every_referenced_action_has_a_governance_row() -> None:
    """Scope is derived from what is actually referenced, not asserted against a
    second hand-copied list -- the same shape the meta-guard in `test_meta.py` requires
    of every scope in this package.
    """
    referenced = _referenced_external_actions()
    assert referenced, "no external action references were found; this guard is vacuous"
    missing = referenced - set(ACTION_GOVERNANCE)
    assert not missing, (
        f"{sorted(missing)} are referenced by a governed definition but have no "
        f"ACTION_GOVERNANCE row (ADR-0022)"
    )


def test_no_governance_row_is_stale() -> None:
    """The inverse of the guard above: a row for an action no longer referenced
    anywhere is prose that has outlived the thing it described.
    """
    referenced = _referenced_external_actions()
    stale = set(ACTION_GOVERNANCE) - referenced
    assert not stale, f"{sorted(stale)} have a governance row but are no longer referenced"


def test_non_ga_actions_carry_an_accepting_adr_and_exit_plan() -> None:
    """ADR-0022: a non-GA/preview component without its own accepting ADR rejects the
    tuple. Every entry in this repository's actual closure is GA today, so this proves
    the schema invariant holds for the current, non-empty closure rather than only for
    a planted fixture.
    """
    for action, row in ACTION_GOVERNANCE.items():
        if row.ga_status == "preview":
            assert row.accepting_adr, (
                f"{action} is recorded as preview/non-GA but carries no accepting ADR "
                f"(ADR-0022)"
            )
        else:
            assert row.accepting_adr is None, (
                f"{action} is GA but carries an accepting_adr field; remove it so a "
                f"future non-GA entry is distinguishable at a glance"
            )


def test_credential_bearing_or_unapproved_actions_require_a_full_sha_pin() -> None:
    """Cross-checked against the registries `test_action_policy.py` actually enforces
    pinning from, not re-derived independently -- a governance row claiming
    `floating-major` for an action in either of those registries would describe a
    tuple record the enforced pin policy does not agree with.
    """
    for action, row in ACTION_GOVERNANCE.items():
        requires_full_sha = (
            action in SHA_PINNED_ACTIONS
            or action in CREDENTIAL_ACTIONS_ON_MOVING_REFS
            or row.trust_class == "unapproved-third-party"
        )
        if action in CREDENTIAL_ACTIONS_ON_MOVING_REFS:
            # Credential-bearing but accepted onto a floating ref under its own ADR
            # (ADR-0009/ADR-0015/ADR-0018) -- a recorded exception to the pin rule,
            # not a violation of it.
            continue
        if requires_full_sha:
            assert row.pin_kind == "full-sha", (
                f"{action}: pinned/credential registries require a full-SHA pin, but "
                f"the governance row records {row.pin_kind!r} (ADR-0022)"
            )
        else:
            assert row.pin_kind == "floating-major", (
                f"{action}: not credential-bearing or unapproved, so the governance "
                f"row should record the maintained floating-major alias, not "
                f"{row.pin_kind!r}"
            )


def _validate_governance_table(
    table: dict[str, ActionGovernance],
) -> list[str]:
    """The reusable half of the three assertions above, for the planted-violation test."""
    violations = []
    for action, row in table.items():
        if row.ga_status == "preview" and not row.accepting_adr:
            violations.append(f"{action}: preview with no accepting ADR")
        if row.trust_class == "unapproved-third-party" and row.pin_kind != "full-sha":
            violations.append(f"{action}: unapproved third party without a full-SHA pin")
    return violations


def test_the_validator_catches_a_planted_non_ga_action_with_no_accepting_adr() -> None:
    planted = {
        "someorg/some-preview-action": ActionGovernance(
            publisher="someorg",
            trust_class="unapproved-third-party",
            maintenance_status="unknown",
            license_spdx="unknown",
            license_compatible=False,
            ga_status="preview",
            supported_major=0,
            pin_kind="floating-major",
            accepting_adr=None,
        ),
    }
    violations = _validate_governance_table(planted)
    assert violations, "the validator did not catch its own planted violation"
    assert set(ACTION_GOVERNANCE).isdisjoint(planted), (
        "the plant must not collide with a real governance row"
    )


@pytest.mark.requires_live_gitea
def test_release_action_gitea_path_probe_records_network_and_trust_boundary() -> None:
    """ADR-0022's Story 9.1 predecessor probe: does `git-action-release@v2`'s
    platform-detection path make a network request against a real Gitea instance, and
    which trust boundary covers it if so. This governs whether the tuple proceeds with
    the primary release action or an ADR must accept the `softprops/action-gh-release`
    fallback -- a decision this environment cannot make without a running Gitea.
    """
    pytest.skip(
        "requires a live Gitea instance to probe git-action-release@v2's Gitea path; "
        "see docs/ci/gitea-runners.md"
    )
