"""ADR-0015/ADR-0018: runner trust-class routing and CA-import placement, statically.

ADR-0015's own proof obligation is entirely behavioral: a concrete Gitea scheduling
primitive, a sanitized eligibility matrix, and a credential-free sentinel job run
against a real registration pair. None of that exists to parse here -- there is no
pinned Gitea tuple, no registration pair, and no scheduler to observe. What this module
proves instead is the part of ADR-0015/ADR-0018 that is a fact about the committed
workflow text: the topology has not silently grown a second trust-class label ahead of
the later ADR that decision requires (ADR-0015's own fallback), and the job-level CA
import this story adds (ADR-0018) is placed where egress separation requires it --
after the checkout that needs only bootstrap trust, strictly inside the job it serves,
and never inside a job that holds no downstream forge credential to protect.
"""

from __future__ import annotations

import pytest

from tests.ci.support import (
    DEV_WORKFLOW,
    RELEASE_WORKFLOW,
    VERIFY_WORKFLOW,
    _is_credential_bearing,
    _jobs,
    _load_workflow,
)

# The action this story introduces for the job-level CA import (ADR-0018). Matched by
# name rather than hand-listing the jobs that carry it, so a future addition or removal
# of the step is examined by the same derivation instead of a second maintained list.
CA_IMPORT_ACTION = "LiquidLogicLabs/git-action-ca-certificate-import"

# The shared label every runner registration in this topology uses today (ADR-0015).
# Not a registry of a DECISION this module makes -- it is the one value the ADR permits
# until a later ADR introduces a split, and is asserted against directly rather than
# derived, the same way a prohibited string is asserted against directly elsewhere in
# this package.
SHARED_RUNNER_LABEL = "ubuntu-24.04"


def _workflow_paths() -> tuple:
    return (DEV_WORKFLOW, RELEASE_WORKFLOW, VERIFY_WORKFLOW)


def test_no_second_trust_class_label_has_been_introduced() -> None:
    """ADR-0015: a label split is a later-ADR decision, not an implementation shortcut.

    Every `runs-on` in the governed workflows must still be the one shared label (or an
    expression built only from it), or this story has silently introduced the topology
    change ADR-0015 explicitly defers.
    """
    examined = 0
    for path in _workflow_paths():
        document = _load_workflow(path)
        for job_name, job in _jobs(document).items():
            runs_on = job.get("runs-on")
            if runs_on is None:
                continue
            examined += 1
            assert SHARED_RUNNER_LABEL in str(runs_on), (
                f"{path.name}:{job_name}: runs-on={runs_on!r} does not reference the "
                f"shared label {SHARED_RUNNER_LABEL!r}; a second trust-class label "
                f"requires its own ADR (ADR-0015)"
            )
    assert examined, "no runs-on value was examined; this guard is vacuous"


def _ca_import_steps(job: dict) -> list[tuple[int, dict]]:
    return [
        (index, step)
        for index, step in enumerate(job.get("steps") or [])
        if str(step.get("uses", "")).split("@", 1)[0] == CA_IMPORT_ACTION
    ]


def _checkout_indices(job: dict) -> list[int]:
    return [
        index
        for index, step in enumerate(job.get("steps") or [])
        if str(step.get("uses", "")).split("@", 1)[0] == "actions/checkout"
    ]


def test_ca_import_steps_follow_checkout_and_precede_the_credentialed_call() -> None:
    """Egress separation (ADR-0018): bootstrap trust from the runner-host checkout
    covers `git`/OS tooling only. The downstream forge CA must be imported strictly
    after that checkout completes (so it layers on top of bootstrap trust rather than
    substituting for it) and strictly before the job's last step (the one actually
    making the credentialed call the import exists to protect) -- never first, and
    never last.
    """
    found_any = False
    for path in _workflow_paths():
        document = _load_workflow(path)
        for job_name, job in _jobs(document).items():
            steps = job.get("steps") or []
            for index, _step in _ca_import_steps(job):
                found_any = True
                checkouts = _checkout_indices(job)
                if checkouts:
                    assert index > max(checkouts), (
                        f"{path.name}:{job_name}: CA import at step {index} does not "
                        f"follow the job's checkout step (ADR-0018 ordering)"
                    )
                assert index != 0, (
                    f"{path.name}:{job_name}: CA import is the first step; bootstrap "
                    f"trust must already be established before downstream trust is "
                    f"imported (ADR-0018)"
                )
                assert index < len(steps) - 1, (
                    f"{path.name}:{job_name}: CA import is the job's last step, so it "
                    f"protects nothing that runs after it (ADR-0018)"
                )
    assert found_any, (
        "no CA import step was found in any governed workflow; this story is expected "
        "to have added at least one (ADR-0018)"
    )


def test_ca_import_steps_are_gated_on_a_secret_and_absent_otherwise() -> None:
    """The import must be inert by construction wherever the destination secret does
    not exist (e.g. every job on GitHub, since no Gitea CA secret is ever configured
    there) -- gated on the secret's own presence, not on a forge-identity branch that
    could drift from which secrets are actually configured.
    """
    for path in _workflow_paths():
        document = _load_workflow(path)
        for job_name, job in _jobs(document).items():
            for _index, step in _ca_import_steps(job):
                condition = str(step.get("if", ""))
                assert "secrets." in condition and "!=" in condition, (
                    f"{path.name}:{job_name}: CA import step has no secret-presence "
                    f"gate ({condition!r}); it must stay inert wherever the secret is "
                    f"unconfigured (ADR-0018)"
                )


def test_ca_import_never_appears_in_a_job_with_no_downstream_credential() -> None:
    """A verifier or otherwise secret-free job has no downstream forge credential to
    protect; a CA import step there would import trust material into a job that never
    reaches the destination it is scoped to, which is the inverse of least privilege.
    """
    for path in _workflow_paths():
        document = _load_workflow(path)
        for job_name, job in _jobs(document).items():
            if _ca_import_steps(job):
                assert _is_credential_bearing(job), (
                    f"{path.name}:{job_name}: has a CA import step but holds no "
                    f"publication-capable credential; egress separation (ADR-0018) "
                    f"does not call for downstream trust material here"
                )


def test_each_destinations_ca_import_uses_a_distinct_certificate_name() -> None:
    """A shared `certificate-name` across two destinations would let a later import
    silently overwrite the trust material the first installed -- the same
    cross-destination isolation `test_credential_matrix.py` checks for secrets, applied
    to the installed material's own identity on disk.
    """
    for path in _workflow_paths():
        names = []
        document = _load_workflow(path)
        for job in _jobs(document).values():
            for _index, step in _ca_import_steps(job):
                with_block = step.get("with") or {}
                name = with_block.get("certificate-name")
                assert name, f"{path.name}: CA import step has no certificate-name set"
                names.append(name)
        # Compared within one workflow file, not globally: `dev.yaml` and
        # `release.yaml` legitimately reuse the SAME destination's name
        # (`gitea-package-index`) for the same channel's package-forge job -- it is
        # two channels' copies of one destination, not two destinations sharing a
        # name. What must never collide is two DIFFERENT destinations within the
        # same file.
        assert len(names) == len(set(names)), (
            f"{path.name}: certificate-name values are not all distinct across "
            f"destinations: {names}"
        )


@pytest.mark.requires_live_gitea
def test_protected_registration_is_mechanically_ineligible_for_untrusted_jobs() -> None:
    """ADR-0015's actual proof obligation: identify the concrete Gitea scheduling
    primitive, capture the sanitized eligibility matrix showing the protected
    registration ineligible for every untrusted context, and submit a credential-free
    sentinel job that records the selected runner identity and the scheduler's
    denial/ineligibility evidence for the protected registration -- including the
    planted-overlapping-scope negative case. This requires a pinned, running Gitea
    server and a registered runner pair; none exists in this environment.
    """
    pytest.skip(
        "requires a live Gitea server and registered runner pair to exercise the "
        "scheduling primitive and sentinel job; see docs/ci/gitea-runners.md"
    )
