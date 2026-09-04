"""Finalization: the gate, the aliases, and the Release -- proven by running them.

BL-E008-010 phase 3. What may be written once every publisher has reported, in what
order, and what stops the writing. Every guard here was proven by planting the violation
it forbids -- the rule AND the scope.

The gate and the annotated-stable-tag relation used to be Python modules with their own
test files. They are workflow steps now, and the properties those files proved are proven
here by EXECUTING the real `run:` bodies against real git and real `jq`, which is strictly
stronger: a module test proves the module, and this proves what the workflow runs.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

import pytest

from tests.ci.support import (
    ALIAS_MOVE_COMMANDS,
    APPROVED_ALIAS_ACTION,
    APPROVED_RELEASE_ACTION,
    BUNDLE_ACTION,
    DEV_WORKFLOW,
    GATE_MARKER,
    PROJECT_ROOT,
    REGISTRY_LOGIN_ACTION,
    RELEASE_FINALIZER_JOBS,
    RELEASE_WORKFLOW,
    STABLE_RECHECK_MARKER,
    TAG_MEMBERSHIP_MARKER,
    WORKFLOWS,
    _alias_moving_jobs,
    _finalizers,
    _gate_steps,
    _git,
    _governed_step_groups,
    _is_credential_bearing,
    _is_publishing_step,
    _jobs,
    _load_document,
    _load_workflow,
    _publishers,
    _publishing_workflows,
    _run_step,
    _step_with_id,
    _transitive_needs,
    _uncommented,
    _workflow_documents,
)

# git's own version ordering, which is what makes the alias decision a delegation rather
# than a second implementation. A step that reached for `sort` instead is not found here.
ALIAS_ORDER_MARKER = "--sort=v:refname"


# What a finalizer must never do. It attaches names to an artifact set that already
# exists; a build here would produce a *different* artifact under a name the release
# already promised (CI-AR39, ADR-0008).
BUILD_COMMANDS = (
    r"\bbuildx\s+(?:bake|build)\b",
    r"\bdocker\s+build\b",
    r"\bpython\s+-m\s+build\b",
    r"\bpoetry\s+build\b",
)


BUILD_ACTIONS = ("docker/build-push-action", "docker/bake-action")


EXPRESSION = re.compile(r"\$\{\{\s*(.+?)\s*\}\}")


def _ordering_steps(job: dict[str, Any]) -> set[str]:
    """Step ids in this job that read the Git tag order."""
    return {
        str(step["id"])
        for step in job.get("steps", []) or []
        if step.get("id")
        and ALIAS_ORDER_MARKER in _uncommented(str(step.get("run", "")))
    }


def _ordering_outputs(document: dict[str, Any]) -> dict[str, set[str]]:
    """Job name -> the job outputs that carry an ordering decision out of it.

    Derived by following each job's `outputs:` mapping back to the step that produced
    it, so a renamed output or a new one is covered without editing anything here.
    """
    produced: dict[str, set[str]] = {}
    for job_name, job in _jobs(document).items():
        step_ids = _ordering_steps(job)
        if not step_ids:
            continue
        names = {
            output
            for output, value in (job.get("outputs") or {}).items()
            if any(f"steps.{step_id}.outputs." in str(value) for step_id in step_ids)
        }
        if names:
            produced[job_name] = names
    return produced


def test_every_alias_ordering_decision_is_the_same_body() -> None:
    """One ordering rule, one implementation, however many places read it.

    `finalize` decides and `finalize-image-aliases` re-decides; two copies of a
    `--sort=v:refname` comparison that drift are two answers to "which tag is
    greatest", and the copy nobody updated is the one that moves `latest`.
    """
    bodies = {
        _uncommented(str(step.get("run", "")))
        for document in _workflow_documents().values()
        for job in _jobs(document).values()
        for step in job.get("steps", []) or []
        if ALIAS_ORDER_MARKER in _uncommented(str(step.get("run", "")))
    }
    assert bodies, "no step reads the tag order; this guard examined nothing"
    assert len(bodies) == 1, (
        f"{len(bodies)} different alias-ordering bodies are in use; they must be one"
    )


def test_no_alias_move_consumes_an_ordering_decision_taken_in_another_job() -> None:
    """The alias inversion, closed at its source.

    `finalize` decided `advance-major` and `finalize-image-aliases` applied it a job
    later. Two stable tags are two refs and run fully in parallel by design, so a
    slower `v1.2.3` run applied a decision that was true when taken and false when
    used, dragging `latest` and `v1` back off `v1.3.0` -- both runs green. The same
    inversion happened inside one run whenever a tag landed between the two jobs.

    So the rule is structural rather than temporal: the ordering authority is read in
    the job that writes, never handed across a job boundary. Derived from each job's
    own `outputs:` mapping, so an ordering output added or renamed later is covered.
    """
    examined = 0
    for name, document in sorted(_workflow_documents().items()):
        ordering = _ordering_outputs(document)
        if not ordering:
            continue
        movers = {job for workflow, job in _alias_moving_jobs() if workflow == name}
        for job_name in sorted(movers):
            rendered = json.dumps(_jobs(document)[job_name])
            examined += 1
            for producer, outputs in sorted(ordering.items()):
                if producer == job_name:
                    continue
                for output in sorted(outputs):
                    assert f"needs.{producer}.outputs.{output}" not in rendered, (
                        f"{name}: job {job_name!r} moves an alias using "
                        f"{output!r} decided in job {producer!r}. The tag set is read "
                        f"where the write happens, or the answer can be stale by the "
                        f"time it is used (F4)."
                    )
    assert examined, "no alias mover shares a file with an ordering decision"


def test_an_alias_concurrency_group_queues_rather_than_cancels() -> None:
    """A concurrency group on an alias job is a hazard unless it is told to queue.

    Sprint closure added `concurrency: {group: <workflow>-aliases, cancel-in-progress:
    false}` to both stable finalizers and ADR-0011 recorded that "every stable run
    queues behind every other". **GitHub does not do that.** Its documented default is
    `queue: single`: at most one run is pending per group, and "any existing pending job
    or workflow run in the same group is canceled and replaced". `cancel-in-progress`
    governs the *running* member only.

    So the group did the opposite of its purpose. Three overlapping tags cancelled a
    middle finalizer that had already published to PyPI and the registry irreversibly --
    creating no Release and moving no alias -- and `release-evidence`'s `!cancelled()`
    meant no run summary was written either. Anyone able to push a tag could freeze
    `latest` by pushing a throwaway one.

    The groups are gone. Ordering is carried entirely by re-deriving the tag set in the
    job that writes (`test_no_alias_move_consumes_an_ordering_decision_taken_in_another_job`),
    which the epic-closure red team confirmed it could not break. This guard keeps the
    hazard from returning: an alias-deciding job may carry a group only with
    `queue: max`, the option that actually queues. `actionlint` v1.7.12 does not know
    that key yet (upstream PR #661 adds it, unreleased), and its behaviour on Gitea is
    unknown, which is why the group was removed rather than corrected in place.
    """
    examined = 0
    for name, document in sorted(_workflow_documents().items()):
        for job_name, job in sorted(_jobs(document).items()):
            if not _ordering_steps(job):
                continue
            examined += 1
            concurrency = job.get("concurrency")
            if not isinstance(concurrency, dict):
                continue
            assert str(concurrency.get("queue", "")) == "max", (
                f"{name}: job {job_name!r} decides alias order behind a concurrency "
                f"group without `queue: max`. GitHub cancels the pending member of a "
                f"group rather than queueing it, so this loses a finalizer that has "
                f"already published irreversibly -- worse than no group at all."
            )
    assert examined, "no job decides alias order; this guard examined nothing"


# The scopes the finalizer authority split depends on, in both directions: the
# ref-writing job must not hold them, and the registry job must not hold `contents:
# write`. Denial is stated, never inferred.
AUTHORITY_SCOPES = ("contents", "packages", "id-token", "attestations")


def test_every_privileged_job_states_the_scopes_it_relies_on_being_denied() -> None:
    """ADR-0006's split is enforced by `permissions:`, and on GitHub an unlisted scope
    is `none`. That semantic is what the whole split rests on, and it is platform
    behaviour rather than something this repository states.

    Gitea does not document it and ships `TokenPermissionMode` permissive by default,
    so on the forge E009 targets, omission grants where GitHub denies -- and the
    ref-writing finalizer would silently acquire the registry authority the split
    exists to keep away from it. An explicit `none` needs no inference from any runner.

    Gitea's granular `code:`/`releases:` spellings are deliberately absent: they are
    not valid GitHub scopes, actionlint rejects the file outright, and the remaining
    platform requirement is a precondition recorded in ADR-0006 rather than YAML.
    """
    examined = 0
    for name, document in sorted(_workflow_documents().items()):
        for job_name, job in sorted(_jobs(document).items()):
            # Every job that holds or can hold a credential, not the three registered
            # finalizers. The premise the explicit denials rest on -- that a permissive
            # runner grants what is omitted -- applies to all of them, and scoping the
            # requirement to the finalizers left seven privileged jobs relying on the
            # inference the declarations exist to remove. `publish-image.yaml`'s job
            # declared no `permissions:` at all.
            if not _is_credential_bearing(job):
                continue
            declared = job.get("permissions")
            assert isinstance(declared, dict), (
                f"{name}: job {job_name!r} can hold a credential and declares no "
                f"job-level permissions at all, which is the widest reading a "
                f"permissive runner can take"
            )
            examined += 1
            for scope in AUTHORITY_SCOPES:
                assert scope in declared, (
                    f"{name}: job {job_name!r} omits {scope!r}. Omission denies on "
                    f"GitHub and grants on a permissive Gitea; state it as `none`."
                )
    assert examined, "no job can hold a credential; this guard examined nothing"


# Everything a finalizer does that cannot be undone: the Release, a Git alias, a
# registry alias. Derived from the same constants the ownership guard uses, so a new
# spelling of "move an alias" reaches the ordering guard below without a second edit.
def _writing_steps(job: dict[str, Any]) -> list[int]:
    indices = []
    for index, step in enumerate(job.get("steps", []) or []):
        uses = str(step.get("uses", ""))
        command = _uncommented(str(step.get("run", "")))
        if uses.startswith((APPROVED_RELEASE_ACTION, APPROVED_ALIAS_ACTION)) or any(
            re.search(probe, command) for probe in ALIAS_MOVE_COMMANDS
        ):
            indices.append(index)
    return indices


# Every refusal this story owns, by the mechanism that performs it rather than by a step
# name: the enabled-set gate, the `vX.Y.Z` immutability re-check, the alias-ordering
# decision, and the development channel's just-in-time head proof.
REFUSAL_MARKERS = (
    GATE_MARKER,
    TAG_MEMBERSHIP_MARKER,
    ALIAS_ORDER_MARKER,
    "rev-parse HEAD",
)


def _refusing_steps(job: dict[str, Any]) -> list[int]:
    return [
        index
        for index, step in enumerate(job.get("steps", []) or [])
        if any(
            marker in _uncommented(str(step.get("run", "")))
            for marker in REFUSAL_MARKERS
        )
    ]


def _gate_step(path: Path) -> dict[str, Any]:
    gates = _gate_steps(path)
    assert len(gates) == 1, (
        f"{path.name} has {len(gates)} finalization gates ({sorted(gates)}); the "
        f"executable anchors below assume one and would silently check only some"
    )
    return next(iter(gates.values()))


def _render(step: dict[str, Any], bindings: dict[str, str]) -> dict[str, str]:
    """The step's real `env:` block with its expressions resolved.

    A binding the workflow does not ask for is never consulted, and an expression with
    no binding raises -- so this is a wiring assertion as well as a fixture: renaming a
    job breaks the render rather than silently supplying the old value.
    """
    rendered = {}
    for name, value in (step.get("env") or {}).items():
        rendered[str(name)] = EXPRESSION.sub(
            lambda match: bindings[match.group(1)], str(value)
        )
    return rendered


def test_only_registered_finalizers_move_an_alias() -> None:
    """The definition-of-done clause: this story is the sole owner of every alias job.

    Equality, not containment, in both directions. Containment one way lets a publisher
    grow an alias step; containment the other way lets a registered grant sit unused,
    which is a `contents: write` nobody is watching.
    """
    moving = _alias_moving_jobs()
    assert moving == RELEASE_FINALIZER_JOBS, (
        f"alias-moving jobs {sorted(moving)} are not the registered finalizer set "
        f"{sorted(RELEASE_FINALIZER_JOBS)}. Moving a ref, tag or registry alias is the "
        f"grant ADR-0006 governs; register the job, or move the step into a finalizer."
    )


# The composite action that is the trust boundary between the secret-free verifier and
# the credentialed publishers (CI-AR36). Matched on the path a `uses:` ends with, so a
# publisher cannot satisfy the rule with a similarly-named action of its own.
BOUNDARY_ACTION = "/verified-bundle"


def test_the_bundle_action_refuses_an_empty_artifact_name_before_downloading(
    tmp_path: Path,
) -> None:
    """An explicitly-passed empty string overrides a default rather than falling back to
    it, and every publisher passes `artifact-name: ${{ needs.verify.outputs.… }}`.

    With an empty `name`, `actions/download-artifact@v4` downloads *every* artifact in
    the run into one directory. The bundle revalidation then fails several steps later
    with "expected exactly one wheel", which reads as a packaging fault rather than a
    missing input -- so the diagnosis lands nowhere near the cause. Executed, and
    asserted to come first: a refusal after the download has already fetched the run.
    """
    steps = (_load_document(BUNDLE_ACTION).get("runs") or {}).get("steps") or []
    refusal = next(
        (
            index
            for index, step in enumerate(steps)
            if "artifact-name is empty" in str(step.get("run", ""))
        ),
        None,
    )
    assert refusal is not None, "the bundle action no longer refuses an empty name"
    download = next(
        index
        for index, step in enumerate(steps)
        if str(step.get("uses", "")).startswith("actions/download-artifact")
    )
    assert refusal < download, (
        "the empty-name refusal runs after the download it exists to prevent"
    )
    for empty in ("", "   "):
        completed, _ = _run_step(
            str(steps[refusal]["run"]), {"ARTIFACT_NAME": empty}, tmp_path
        )
        assert completed.returncode != 0, f"accepted an empty artifact name {empty!r}"
    completed, _ = _run_step(
        str(steps[refusal]["run"]), {"ARTIFACT_NAME": "verified-dist-v1"}, tmp_path
    )
    assert completed.returncode == 0, completed.stderr


ATTESTATION_ACTION = "actions/attest-build-provenance"


ATTESTATION_CAPABILITY = "attestation-supported"


def test_the_irrevocable_destination_names_an_environment() -> None:
    """PyPI is the one destination nothing can be withdrawn from: a version number is
    spent the moment it is accepted. Every mitigation around it is an identity re-check,
    and identity re-checks prove the tag still names the commit -- never that a person
    meant to release it.

    An `environment:` is where a human can be required, and it is also what lets the
    PyPI trusted publisher be constrained to one workflow: without an environment claim
    to match on, *any* workflow in this repository that obtains `id-token: write` can
    mint a PyPI-scoped token.

    **What this cannot check**: whether that environment has required reviewers, and
    whether PyPI is configured to demand the claim. Both are settings outside the tree
    and this guard passes with neither set. Reviewers were declined at E008 closure
    (sole-developer project); binding the trusted publisher to the environment claim was
    not, and it is the half that costs nothing operationally -- it is latent only because
    PyPI publication is currently disabled. `docs/operational.md` records both decisions
    rather than leaving this declaration to imply protection it does not yet have.
    """
    examined = 0
    for name, job in sorted(_jobs(_load_workflow(RELEASE_WORKFLOW)).items()):
        if not any(
            str(step.get("uses", "")).startswith("pypa/gh-action-pypi-publish")
            and not (step.get("with") or {}).get("repository-url")
            for step in job.get("steps") or []
        ):
            continue
        examined += 1
        assert job.get("environment"), (
            f"release.yaml: {name!r} uploads to PyPI without naming an environment, so "
            f"there is nowhere to require a reviewer and nothing for the trusted "
            f"publisher to constrain on"
        )
    assert examined, "no job uploads to PyPI; this guard examined nothing"


def test_the_released_distributions_are_attested_on_every_release() -> None:
    """The Release's own evidence proves nothing against whoever can write the Release.

    `SHA256SUMS` and `build-manifest.json` are attached with `allow-updates: true` by a
    job holding `contents: write` -- which is right, because a stranded run must be
    resumable at an immutable identity -- so the evidence has no authority independent
    of the authority that could forge it. An attestation does.

    **The property this asserts is reachability, and that is the correction.** The first
    version of this fix put the attestation inside `publish-package-pypi`, which is
    gated on `PUBLISH_PACKAGE_PYPI` -- default `false`. In the shipped default
    configuration nothing was attested, and the guard passed, because it proved the step
    existed, was ordered before the upload and held the right scope. It never asked
    whether the step runs. Setting the attesting job to `if: false` left the suite green.
    That is the epic's signature defect -- a correct rule over the wrong set -- appearing
    inside the remediation written to close it.

    So: the attesting job may be gated on a HOST CAPABILITY and on nothing else. Not a
    `PUBLISH_*` toggle, not a destination's enabled state, not a forge name. Gitea has no
    attestation store, and that is the only reason a release may go unattested.
    """
    document = _load_workflow(RELEASE_WORKFLOW)
    jobs = _jobs(document)
    attesting = {
        name: job
        for name, job in jobs.items()
        if any(
            str(step.get("uses", "")).startswith(ATTESTATION_ACTION)
            for step in job.get("steps") or []
        )
    }
    assert attesting, (
        "no job attests the released distributions; the Release evidence has no "
        "authority independent of the `contents: write` that could replace it"
    )
    for name, job in sorted(attesting.items()):
        condition = str(job.get("if", ""))
        assert ATTESTATION_CAPABILITY in condition, (
            f"release.yaml: {name!r} gates attestation on {condition!r}. Only the host "
            f"capability may gate it -- Gitea has no attestation store."
        )
        assert (
            "PUBLISH_" not in condition and "enabled-destinations" not in condition
        ), (
            f"release.yaml: {name!r} gates attestation on a publication toggle "
            f"({condition!r}), so a release with that destination off is unattested. "
            f"An attestation is evidence, not a destination that can be switched off."
        )
        assert (job.get("permissions") or {}).get("attestations") == "write", (
            f"release.yaml: {name!r} runs the attestation action without the scope it "
            f"needs, so it fails at the point of use"
        )
        # And nothing irreversible may precede it in its own job: an attestation made
        # after an upload cannot protect the upload.
        steps = job.get("steps") or []
        attest_at = next(
            index
            for index, step in enumerate(steps)
            if str(step.get("uses", "")).startswith(ATTESTATION_ACTION)
        )
        shipping = next(
            (index for index, step in enumerate(steps) if _is_publishing_step(step)),
            None,
        )
        assert shipping is None or attest_at < shipping, (
            f"release.yaml: {name!r} ships at step {shipping} before attesting at "
            f"{attest_at}"
        )

    # Reachability is not only about the `if:`. The Release must wait for it, or a
    # failed attestation would leave a Release published with unsigned evidence.
    for finalizer in sorted(_finalizers(RELEASE_WORKFLOW)):
        if "alias" in finalizer:
            continue
        waits_on = set(jobs[finalizer].get("needs") or [])
        assert waits_on & set(attesting), (
            f"release.yaml: {finalizer!r} creates the Release without waiting for "
            f"{sorted(attesting)}, so the Release can carry evidence never signed"
        )


def test_a_package_upload_never_authenticates_as_the_pusher() -> None:
    """A token upload's identity must come from the credential, not from whoever pushed.

    Both forge index publishers passed `user: ${{ github.actor }}` alongside
    `FORGE_PACKAGE_TOKEN`. It works -- Gitea's basic auth resolves a token supplied as
    the password and ignores the username -- but the value varies per push and is
    unrelated to whoever minted the token, so the upload's apparent identity became a
    property of who triggered the run. `__token__` is the convention every Python index
    uses for this, and it is a constant.

    Scope is every package-upload step in every governed definition, so a third index
    added later is covered without editing this.
    """
    examined = 0
    for definition, container, steps in _governed_step_groups():
        for step in steps:
            if not str(step.get("uses", "")).startswith("pypa/gh-action-pypi-publish"):
                continue
            supplied = str((step.get("with") or {}).get("user", ""))
            if not supplied:
                continue  # trusted publishing passes no user at all, which is stronger
            examined += 1
            assert "github.actor" not in supplied, (
                f"{definition}: {container!r} uploads a package as `{supplied}`. The "
                f"identity of a token upload is the token's, not the pusher's; use "
                f"`__token__`."
            )
    assert examined, "no package upload supplies a user; this guard examined nothing"


def test_every_publisher_revalidates_the_bundle_before_it_logs_in_or_uploads() -> None:
    """CI-AR36, over every publisher rather than the one that attaches the Release.

    "Every publisher downloads the verified bundle, checks SHA256SUMS, revalidates
    build-manifest.json, and matches the source SHA and version it believes it is
    publishing -- before any login or upload" is the boundary between the secret-free
    verifier and the jobs holding credentials. Six publishers implement it and, until
    this guard, one was checked: the arch review replaced `dev.yaml`'s
    `publish-package-forge` revalidation with a bare `actions/download-artifact`, so the
    wheel reached the forge index with no checksum recheck, no manifest validation and
    no identity match -- and the suite was unchanged.

    Ordering is asserted, not just presence. Revalidating *after* the login satisfies
    "the step exists" while the credential is already on the runner when the unverified
    artifact arrives, which is the property the boundary is for.

    Scope is derived from capability: any step-based publisher that reaches an upload.
    The two alias finalizers are excluded because they ship no artifact -- they point a
    name at a digest that is already published.
    """
    examined = 0
    for path in sorted(WORKFLOWS.glob("*.yaml")):
        for job_name, job in sorted(_publishers(_load_workflow(path)).items()):
            steps = job.get("steps") or []

            def _first(
                predicate: Any, steps: list[dict[str, Any]] = steps
            ) -> int | None:
                return next(
                    (index for index, step in enumerate(steps) if predicate(step)), None
                )

            upload = _first(_is_publishing_step)
            if upload is None:
                continue
            examined += 1
            bundle = _first(
                lambda step: (
                    str(step.get("uses", "")).rstrip("/").endswith(BOUNDARY_ACTION)
                )
            )
            assert bundle is not None, (
                f"{path.name}: publisher {job_name!r} uploads without revalidating the "
                f"verified bundle. CI-AR36 is the trust boundary; a publisher that "
                f"skips it ships whatever the artifact store handed it."
            )
            assert bundle < upload, (
                f"{path.name}: publisher {job_name!r} revalidates the bundle at step "
                f"{bundle} but uploads at step {upload}"
            )
            login = _first(
                lambda step: str(step.get("uses", "")).startswith(REGISTRY_LOGIN_ACTION)
            )
            assert login is None or bundle < login, (
                f"{path.name}: publisher {job_name!r} logs in at step {login} before "
                f"revalidating at step {bundle}. The credential is on the runner before "
                f"the artifact is known to be the verified one."
            )
    assert examined, "no publisher uploads anything; this guard examined nothing"


def test_no_finalizer_builds_anything() -> None:
    """A finalizer names artifacts that already exist. Building one here would ship a
    different artifact under a name the run has already promised, and the difference is
    invisible: same tag, same version, other bits."""
    examined = 0
    for path in sorted(WORKFLOWS.glob("*.yaml")):
        for job_name in sorted(_finalizers(path)):
            job = _jobs(_load_workflow(path))[job_name]
            for step in job.get("steps", []) or []:
                examined += 1
                command = _uncommented(str(step.get("run", "")))
                for pattern in BUILD_COMMANDS:
                    assert not re.search(pattern, command), (
                        f"{path.name}: finalizer {job_name!r} builds an artifact. It "
                        f"may only name what the publishers already shipped (CI-AR39)."
                    )
                action = str(step.get("uses", "")).split("@", 1)[0]
                assert action not in BUILD_ACTIONS, (
                    f"{path.name}: finalizer {job_name!r} runs {action}, which builds"
                )
    assert examined, "no finalizer step was examined"


def test_ref_writing_and_registry_alias_privileges_never_meet() -> None:
    """Least privilege, per job, from the parsed `permissions:` and the parsed steps.

    Two planted violations, in opposite directions: a registry credential on the job
    that writes refs, and `contents: write` on the job that moves registry aliases.
    Either one recreates the single over-privileged finalizer the split exists to avoid
    -- one compromised step that can both rewrite history and publish an image.
    """
    ref_writers = 0
    alias_movers = 0
    for path in sorted(WORKFLOWS.glob("*.yaml")):
        for job_name, job in _jobs(_load_workflow(path)).items():
            steps = job.get("steps", []) or []
            permissions = job.get("permissions") or {}
            writes_refs = any(
                str(step.get("uses", "")).startswith(
                    (APPROVED_RELEASE_ACTION, APPROVED_ALIAS_ACTION)
                )
                for step in steps
            )
            moves_registry_alias = any(
                re.search(probe, _uncommented(str(step.get("run", ""))))
                for step in steps
                for probe in ALIAS_MOVE_COMMANDS
            )
            if writes_refs:
                ref_writers += 1
                assert permissions.get("packages") != "write", (
                    f"{path.name}: {job_name!r} writes refs and takes `packages: write`"
                )
                body = json.dumps(job)
                assert "docker/login-action" not in body, (
                    f"{path.name}: {job_name!r} writes refs and logs into a registry"
                )
                registry_secrets = {
                    secret
                    for secret in re.findall(
                        r"secrets\.([A-Za-z_][A-Za-z0-9_-]*)", body
                    )
                    if "DOCKER" in secret or "REGISTRY" in secret
                }
                assert not registry_secrets, (
                    f"{path.name}: {job_name!r} writes refs and holds registry "
                    f"credentials {sorted(registry_secrets)}; each finalizer holds one "
                    f"kind of authority"
                )
            if moves_registry_alias:
                alias_movers += 1
                assert permissions.get("contents") != "write", (
                    f"{path.name}: {job_name!r} moves a registry alias and takes "
                    f"`contents: write`; ref authority belongs to the Release finalizer"
                )
    assert ref_writers, "no job writes a ref; this guard examined nothing"
    assert alias_movers, "no job moves a registry alias; this guard examined nothing"


DESTINATION_KEY = re.compile(r'"([a-z][a-z-]*)"\s*:\s*"')


def _destination_vocabulary(path: Path) -> set[str]:
    """The destination keys this workflow's plan job actually emits.

    Read from the `enabled-destinations=` line the step prints, which is the single
    producer of the set (ADR-0011). Everything downstream spells these keys by hand --
    three times in release.yaml, and dozens of times in this module -- and nothing
    derived them from here until now.
    """
    for job in _jobs(_load_workflow(path)).values():
        for step in job.get("steps") or []:
            body = str(step.get("run", ""))
            if "enabled-destinations=" not in body:
                continue
            emitted = body.split("enabled-destinations=", 1)[1].split("}", 1)[0]
            return set(DESTINATION_KEY.findall(emitted))
    return set()


def test_the_finalizer_gate_binds_every_destination_to_the_job_that_serves_it() -> None:
    """Two defects, one coupling.

    The gate's `PUBLISHER_RESULTS` maps each destination key to a `needs.<job>.result` by
    hand, and the vocabulary itself is spelled by hand everywhere downstream of the one
    step that emits it. The existing guard asserted each publisher's result appears
    *somewhere* in the gate's env, never that a key is bound to the job that ships that
    destination: rebinding `image-dockerhub` to `needs.publish-package-forge.result`
    left the suite green.

    So: the gate's keys must be exactly the vocabulary the plan job emits, and where a
    job's own definition gates on a destination key -- `fromJSON(...)['package-pypi']` in
    its `if:`, or in an input it passes down -- the gate must bind that key to that job.
    That covers every toggle-gated destination, which are the ones a mis-binding can
    actually hide. `image-forge` and `attestation` are unconstrained here because no job
    gates on them: the first is the channel and the second is a host capability.
    """
    examined = 0
    for path in sorted(WORKFLOWS.glob("*.yaml")):
        vocabulary = _destination_vocabulary(path)
        if not vocabulary:
            continue
        gates = _gate_steps(path)
        assert gates, f"{path.name}: emits a destination set and no gate reads it"
        for job_name, step in gates.items():
            results = str((step.get("env") or {}).get("PUBLISHER_RESULTS", ""))
            bound = set(DESTINATION_KEY.findall(results))
            examined += 1
            assert bound == vocabulary, (
                f"{path.name}: the gate in {job_name!r} binds {sorted(bound)} but the "
                f"plan job emits {sorted(vocabulary)}. The set has one producer."
            )
            # And each key must name the job that actually serves it.
            for key in sorted(vocabulary):
                serving = {
                    name
                    for name, job in _jobs(_load_workflow(path)).items()
                    if f"['{key}']" in json.dumps(job)
                }
                if not serving:
                    continue
                match = re.search(
                    rf'"{re.escape(key)}"\s*:\s*"\$\{{\{{\s*needs\.([a-z0-9-]+)\.result',
                    results,
                )
                assert match and match.group(1) in serving, (
                    f"{path.name}: the gate binds {key!r} to "
                    f"{match.group(1) if match else 'nothing'!r}, but the job that gates "
                    f"on that destination is {sorted(serving)}"
                )
    assert examined, "no workflow has both a destination set and a gate"


def test_every_finalizer_waits_for_every_publisher_and_reads_every_result() -> None:
    """ADR-0011: `needs:` is static, so the finalizer depends on ALL of them and then
    evaluates their results against the enabled set.

    Both halves, because either alone is satisfiable while the other is broken: a
    `needs:` entry can be deleted, and a publisher can be added that the gate's env
    never mentions. Both sets are derived from `_publishers()`, so the scope attack --
    a new publisher nothing depends on -- fails without anyone editing a list.
    """
    channel_workflows = _publishing_workflows()
    assert channel_workflows, "no workflow calls the image publisher"
    for path in channel_workflows:
        document = _load_workflow(path)
        jobs = _jobs(document)
        finalizers = _finalizers(path)
        assert finalizers, f"{path.name}: no registered finalizer"
        destinations = set(_publishers(document)) - finalizers
        assert destinations, f"{path.name}: no destination publisher; nothing examined"

        for name in sorted(finalizers):
            missing = destinations - _transitive_needs(jobs, name)
            assert not missing, (
                f"{path.name}: finalizer {name!r} does not depend on {sorted(missing)}, "
                f"so it could create a Release and move aliases while that destination "
                f"was still running (ADR-0011)"
            )

        gates = _gate_steps(path)
        assert gates, f"{path.name}: no finalizer evaluates the enabled set (ADR-0011)"
        for gated_job, step in sorted(gates.items()):
            gate = json.dumps(step.get("env") or {})
            assert "needs.plan.outputs.enabled-destinations" in gate, (
                f"{path.name}: {gated_job!r}'s gate never reads the enabled set, so a "
                f"skipped destination cannot be told from a disabled one (ADR-0011)"
            )
            for publisher in sorted(destinations):
                assert f"needs.{publisher}.result" in gate, (
                    f"{path.name}: {gated_job!r}'s gate never reads "
                    f"`needs.{publisher}.result`, so that destination's failure would "
                    f"not block the Release or the aliases (ADR-0011)"
                )

        # And every finalizer that writes is behind a gate -- its own, or one in a job
        # it transitively depends on. Without this a second finalizer could be added
        # with no gate at all and the coverage assertion above would pass, having
        # examined only the gate that does exist.
        for name in sorted(finalizers):
            if not _writing_steps(jobs[name]):
                continue
            reachable = _transitive_needs(jobs, name) | {name}
            assert reachable & set(gates), (
                f"{path.name}: finalizer {name!r} writes a Release or moves an alias "
                f"without a finalization gate in itself or in anything it needs "
                f"(ADR-0011)"
            )


def test_every_finalization_gate_is_the_same_body() -> None:
    """The sprint's third copied body, and the only one that shipped without a same-body
    guard.

    The forge-coordinate derivation (two copies) and the stable-tag re-check (four and
    three copies) each carry one. The finalization gate is the largest copied body and
    the one that decides whether an alias moves, and its twelve input-validation tests
    are all bound to `release.yaml`. Deleting the "enabled set names no destination at
    all", "no publisher result was supplied" and "results were supplied for" refusals
    from `dev.yaml`'s copy alone left the suite unchanged.

    That also made ADR-0011's "every property the deleted pytest files proved is now
    proven the same way" true of the stable channel and false of the development one --
    prose overstating its own coverage. With the bodies pinned identical, executing one
    copy is a proof about both, and the sentence is true again.
    """
    bodies = {
        (path.name, job_name): _uncommented(str(step.get("run", "")))
        for path in sorted(WORKFLOWS.glob("*.yaml"))
        for job_name, step in _gate_steps(path).items()
    }
    assert bodies, "no finalization gate on disk; this guard examined nothing"
    distinct = set(bodies.values())
    assert len(distinct) == 1, (
        f"{len(distinct)} different finalization gates are in use across "
        f"{sorted(bodies)}. The channel bindings differ; the decision must not."
    )


def _run_gate(path: Path, bindings: dict[str, str], summary: Path | None = None) -> Any:
    step = _gate_step(path)
    environment = _render(step, bindings)
    if summary is not None:
        summary.touch()
        environment["GITHUB_STEP_SUMMARY"] = str(summary)
    completed, _ = _run_step(str(step["run"]), environment, cwd=PROJECT_ROOT)
    return completed


def _stable_bindings(**results: str) -> dict[str, str]:
    """Every expression release.yaml's gate step resolves, with results overridable."""
    defaults = {
        "attest": "success",
        "publish-image": "success",
        "publish-package-forge": "success",
        "publish-package-pypi": "success",
        "verify": "success",
    }
    defaults.update(results)
    return {f"needs.{job}.result": result for job, result in defaults.items()} | {
        "needs.plan.outputs.enabled-destinations": json.dumps(
            {
                "image-forge": "enabled",
                "image-dockerhub": "disabled",
                "package-forge": "unsupported",
                "package-pypi": "enabled",
                # Enabled here because the GitHub case is the one with an attestation
                # store; the unsupported (Gitea) case has its own test below.
                "attestation": "enabled",
            }
        )
    }


def test_an_attestation_that_did_not_happen_stops_finalization() -> None:
    """The attestation is a destination in ADR-0011's sense, and this is why.

    It began as a step inside `publish-package-pypi`, which is gated on
    PUBLISH_PACKAGE_PYPI -- default false -- so by default nothing was attested and the
    guard covering it still passed, because it asserted the step existed rather than
    that it runs. Modelling the attestation as a destination puts it under the gate that
    already knows the difference between "skipped because this host has none" and
    "skipped because something upstream died".
    """
    completed = _run_gate(RELEASE_WORKFLOW, _stable_bindings(attest="skipped"))
    assert completed.returncode != 0, "an enabled attestation that never ran finalized"
    assert "attestation" in completed.stderr

    # And absent by host capability is legitimate: Gitea has no attestation store, so a
    # skip there must finalize exactly as an absent forge package index does.
    bindings = _stable_bindings(attest="skipped")
    enabled = json.loads(bindings["needs.plan.outputs.enabled-destinations"])
    enabled["attestation"] = "unsupported"
    bindings["needs.plan.outputs.enabled-destinations"] = json.dumps(enabled)
    completed = _run_gate(RELEASE_WORKFLOW, bindings)
    assert completed.returncode == 0, completed.stderr


def test_a_disabled_optional_destination_still_finalizes() -> None:
    """ADR-0011's first mandatory anchor.

    Docker Hub off by toggle and the forge index absent by host capability: both report
    `skipped`, both are legitimate, and a release with either of them off must still get
    its Release and its aliases. The literal reading of "a required failure or skip
    blocks" would leave that release green with nothing finalized and nothing reported,
    which is the failure nobody notices until they look for the Release.
    """
    completed = _run_gate(
        RELEASE_WORKFLOW,
        _stable_bindings(**{"publish-package-forge": "skipped"}),
    )
    assert completed.returncode == 0, completed.stderr


def test_an_enabled_destination_that_skipped_stops_finalization() -> None:
    """ADR-0011's second mandatory anchor, and the one the first makes possible to get
    wrong: `skipped` is also what a job reports when its upstream died, so ignoring
    every skip would advance `latest` over a release whose PyPI upload never happened."""
    completed = _run_gate(
        RELEASE_WORKFLOW, _stable_bindings(**{"publish-package-pypi": "skipped"})
    )
    assert completed.returncode != 0
    assert "package-pypi" in completed.stderr


@pytest.mark.parametrize("blocking", ["failure", "cancelled"])
def test_a_failed_or_cancelled_publisher_stops_finalization(blocking: str) -> None:
    completed = _run_gate(
        RELEASE_WORKFLOW, _stable_bindings(**{"publish-image": blocking})
    )
    assert completed.returncode != 0
    assert "image-forge" in completed.stderr


def test_a_failed_verifier_stops_finalization_whatever_the_destinations_did() -> None:
    completed = _run_gate(RELEASE_WORKFLOW, _stable_bindings(verify="failure"))
    assert completed.returncode != 0
    assert "verify" in completed.stderr


def test_the_development_gate_reads_its_own_channels_destinations() -> None:
    """The same module, a different enabled set -- and the pair registry is why that is
    safe: `finalize` in dev.yaml would have been granted by a bare-name registry."""
    bindings = {
        "needs.publish-image.result": "success",
        "needs.publish-package-forge.result": "success",
        "needs.publish-package-testpypi.result": "skipped",
        "needs.verify.result": "success",
        "needs.stable-tag-guard.result": "success",
        "needs.plan.outputs.enabled-destinations": json.dumps(
            {
                "image-forge": "enabled",
                "package-forge": "unsupported",
                "package-testpypi": "disabled",
            }
        ),
    }
    completed = _run_gate(DEV_WORKFLOW, bindings)
    assert completed.returncode == 0, completed.stderr
    bindings["needs.plan.outputs.enabled-destinations"] = json.dumps(
        {
            "image-forge": "enabled",
            "package-forge": "unsupported",
            "package-testpypi": "enabled",
        }
    )
    completed = _run_gate(DEV_WORKFLOW, bindings)
    assert completed.returncode != 0
    assert "package-testpypi" in completed.stderr


@pytest.fixture
def alias_repository(tmp_path: Path) -> Path:
    """A repository whose tag set makes every ordering decision distinguishable.

    Real git, and real annotated tags, because git's own version comparison is the
    ordering authority the workflow delegates to. `v1.2.10` is here so a lexicographic
    sort -- what a hand-rolled comparison degrades to -- gives a different answer from
    the correct one.
    """
    root = tmp_path / "ordered"
    root.mkdir()
    _git(root, "init", "--initial-branch=main")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "Test")
    for index, tags in enumerate(
        [
            ("v1.2.3",),
            ("v1.2.10",),
            ("v1.3.0",),
            ("v1.4.0-rc1", "v9.9.9-lightweight", "v1.2", "1.2.3"),
        ]
    ):
        (root / "file.txt").write_text(f"{index}\n", encoding="utf-8")
        _git(root, "add", ".")
        _git(root, "commit", "-m", f"commit {index}")
        for tag in tags:
            if tag.endswith("-lightweight"):
                _git(root, "tag", tag)
            else:
                _git(root, "tag", "-a", tag, "-m", tag)
    # An annotated stable tag on history the protected default branch never took. It is
    # the greatest tag in the repository and must count for nothing: without the
    # `--merged` scope every release after it becomes the *second* greatest, so `vMAJOR`
    # and `latest` stop advancing while every run still finishes green. Every ordering
    # expectation below is therefore also a scope attack on that scoping.
    _git(root, "checkout", "-b", "abandoned")
    (root / "file.txt").write_text("abandoned\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "abandoned")
    _git(root, "tag", "-a", "v9.0.0", "-m", "v9.0.0")
    _git(root, "checkout", "main")
    return root


@pytest.fixture
def major_boundary_repository(tmp_path: Path) -> Path:
    """`v1.2.3`, `v1.20.0`, `v2.0.0` -- the two cases prefix arithmetic gets wrong.

    `v1.2.` must not prefix `v1.20.0` (or a patch release would think a neighbouring
    minor superseded it), and the first release of a new major is greatest within a
    `MAJOR.MINOR` that contains only itself.
    """
    root = tmp_path / "boundary"
    root.mkdir()
    _git(root, "init", "--initial-branch=main")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "Test")
    for index, tag in enumerate(["v1.2.3", "v1.20.0", "v2.0.0"]):
        (root / "file.txt").write_text(f"{index}\n", encoding="utf-8")
        _git(root, "add", ".")
        _git(root, "commit", "-m", f"commit {index}")
        _git(root, "tag", "-a", tag, "-m", tag)
    return root


def _alias_plan(
    repository: Path, tag: str, branch: str = "main"
) -> tuple[Any, dict[str, str]]:
    step = _step_with_id(RELEASE_WORKFLOW, "aliases")
    commit = _git(repository, "rev-parse", f"{tag}^{{commit}}")
    return _run_step(
        str(step["run"]),
        {
            "DEFAULT_BRANCH_REF": branch,
            "RELEASE_TAG": tag,
            "SOURCE_SHA": commit,
        },
        cwd=repository,
    )


def test_the_newest_stable_release_advances_both_aliases(
    alias_repository: Path,
) -> None:
    completed, emitted = _alias_plan(alias_repository, "v1.3.0")
    assert completed.returncode == 0, completed.stderr
    assert emitted["advance-major"] == "true"
    assert emitted["advance-minor"] == "true"
    assert emitted["major-alias"] == "v1"
    assert emitted["minor-alias"] == "v1.3"


def test_a_back_port_patch_never_drags_the_major_alias_backwards(
    alias_repository: Path,
) -> None:
    """Gate finding F4, executed rather than described.

    `git-action-tag-floating-version` moves an alias unconditionally: hand it `v1.2.10`
    with `v1.3.0` already published and `v1` follows it backwards. The refusal has to
    come from the workflow, and the workflow's authority is the Git tag set alone.

    `v1.2.10` is also the case a lexicographic comparison gets wrong in the *other*
    direction -- it sorts below `v1.2.3` -- so this asserts the minor alias may still
    advance, not only that the major may not.
    """
    completed, emitted = _alias_plan(alias_repository, "v1.2.10")
    assert completed.returncode == 0, completed.stderr
    assert emitted["advance-major"] == "false"
    assert emitted["advance-minor"] == "true"
    assert emitted["greatest-stable"] == "v1.3.0"


def test_a_superseded_patch_advances_nothing(alias_repository: Path) -> None:
    completed, emitted = _alias_plan(alias_repository, "v1.2.3")
    assert completed.returncode == 0, completed.stderr
    assert emitted["advance-major"] == "false"
    assert emitted["advance-minor"] == "false"


@pytest.mark.parametrize("tag", ["v1.4.0-rc1", "v9.9.9-lightweight", "v1.2", "1.2.3"])
def test_no_alias_plan_exists_for_a_tag_that_is_not_an_exact_stable_release(
    alias_repository: Path, tag: str
) -> None:
    """A prerelease, a lightweight tag, a two-part tag and an unprefixed one. The action
    skips prereleases itself; every other shape has to be refused here, and refusing is
    the same operation as refusing an ordering violation -- the step exits non-zero and
    `set -e` stops the job before any alias is touched."""
    completed, _ = _alias_plan(alias_repository, tag)
    assert completed.returncode != 0


def _stub_docker(tmp_path: Path) -> tuple[Path, Path]:
    """A `docker` on PATH that records its arguments instead of contacting a registry."""
    directory = tmp_path / "bin"
    directory.mkdir()
    log = tmp_path / "docker.log"
    stub = directory / "docker"
    stub.write_text(
        f'#!/usr/bin/env bash\nprintf "%s\\n" "$*" >> "{log}"\n', encoding="utf-8"
    )
    stub.chmod(0o755)
    return directory, log


def _run_alias_step(
    path: Path, tmp_path: Path, **environment: str
) -> tuple[Any, list[str]]:
    directory, log = _stub_docker(tmp_path)
    summary = tmp_path / "summary.md"
    summary.touch()
    step = _step_with_id(path, "image-alias")
    completed, _ = _run_step(
        str(step["run"]),
        {
            "PATH": f"{directory}:{os.environ['PATH']}",
            "GITHUB_STEP_SUMMARY": str(summary),
            **environment,
        },
        cwd=tmp_path,
    )
    invocations = log.read_text(encoding="utf-8").splitlines() if log.exists() else []
    return completed, invocations


DIGEST = "sha256:" + "ab" * 32


def _moved(invocations: list[str]) -> set[str]:
    """Every reference the alias step actually named, across every invocation."""
    arguments = " ".join(invocations).split()
    return {
        arguments[index + 1]
        for index, token in enumerate(arguments)
        if token == "--tag"
    }


@pytest.mark.parametrize("workflow", [RELEASE_WORKFLOW, DEV_WORKFLOW])
@pytest.mark.parametrize("digest", ["", "latest", "sha256:short", DIGEST[:-1] + "z"])
def test_an_absent_or_malformed_digest_halts_before_any_name_moves(
    workflow: Path, tmp_path: Path, digest: str
) -> None:
    """The alias step is handed the publisher's `digest` output. When the publisher was
    skipped that output is the empty string, and `repo@` with nothing after it is either
    an obscure failure or -- if anything ever coerces it back to a tag -- a copy of
    whatever `repo:` resolves to. Halting is the only safe reading."""
    completed, invocations = _run_alias_step(
        workflow,
        tmp_path,
        ADVANCE_MAJOR="true",
        ADVANCE_MINOR="true",
        DOCKERHUB_REPOSITORY="",
        IMAGE_DIGEST=digest,
        IMAGE_REPOSITORY="ghcr.io/owner/name",
        MAJOR_ALIAS="v1",
        MINOR_ALIAS="v1.3",
    )
    assert completed.returncode != 0, completed.stdout
    assert not invocations, f"a name was moved onto {digest!r}"


def test_a_stable_alias_step_moves_only_the_names_the_tag_set_permits(
    tmp_path: Path,
) -> None:
    completed, invocations = _run_alias_step(
        RELEASE_WORKFLOW,
        tmp_path,
        ADVANCE_MAJOR="false",
        ADVANCE_MINOR="true",
        DOCKERHUB_REPOSITORY="docker.io/owner/name",
        IMAGE_DIGEST=DIGEST,
        IMAGE_REPOSITORY="ghcr.io/owner/name",
        MAJOR_ALIAS="v1",
        MINOR_ALIAS="v1.2",
    )
    assert completed.returncode == 0, completed.stderr
    assert _moved(invocations) == {
        "ghcr.io/owner/name:1.2",
        "docker.io/owner/name:1.2",
    }
    assert all("imagetools create" in line for line in invocations)
    assert all("@" + DIGEST in line for line in invocations)


def test_the_stable_alias_step_moves_latest_only_with_the_major(tmp_path: Path) -> None:
    completed, invocations = _run_alias_step(
        RELEASE_WORKFLOW,
        tmp_path,
        ADVANCE_MAJOR="true",
        ADVANCE_MINOR="true",
        DOCKERHUB_REPOSITORY="",
        IMAGE_DIGEST=DIGEST,
        IMAGE_REPOSITORY="ghcr.io/owner/name",
        MAJOR_ALIAS="v1",
        MINOR_ALIAS="v1.3",
    )
    assert completed.returncode == 0, completed.stderr
    assert _moved(invocations) == {
        "ghcr.io/owner/name:1.3",
        "ghcr.io/owner/name:1",
        "ghcr.io/owner/name:latest",
    }
    # `latest` and `MAJOR` mean the same thing, so they must not be two writes that can
    # disagree: one repository, one `imagetools create`.
    assert len(invocations) == 1, invocations


def test_a_superseded_release_moves_no_image_alias_at_all(tmp_path: Path) -> None:
    completed, invocations = _run_alias_step(
        RELEASE_WORKFLOW,
        tmp_path,
        ADVANCE_MAJOR="false",
        ADVANCE_MINOR="false",
        DOCKERHUB_REPOSITORY="docker.io/owner/name",
        IMAGE_DIGEST=DIGEST,
        IMAGE_REPOSITORY="ghcr.io/owner/name",
        MAJOR_ALIAS="v1",
        MINOR_ALIAS="v1.2",
    )
    assert completed.returncode == 0, completed.stderr
    assert not invocations


def test_a_disabled_docker_hub_receives_no_alias_request(tmp_path: Path) -> None:
    """The credentials half is gated on the enabled set; this is the requests half. An
    alias pushed at a destination the run declared disabled is a request to a registry
    it never logged into."""
    completed, invocations = _run_alias_step(
        RELEASE_WORKFLOW,
        tmp_path,
        ADVANCE_MAJOR="true",
        ADVANCE_MINOR="true",
        DOCKERHUB_REPOSITORY="",
        IMAGE_DIGEST=DIGEST,
        IMAGE_REPOSITORY="ghcr.io/owner/name",
        MAJOR_ALIAS="v1",
        MINOR_ALIAS="v1.3",
    )
    assert completed.returncode == 0, completed.stderr
    assert not any("docker.io" in line for line in invocations)


def test_a_stale_development_candidate_halts_without_moving_dev(
    tmp_path: Path, alias_repository: Path
) -> None:
    """The just-in-time head re-read. Concurrency cancels a superseded run, but the
    cancellation is not instantaneous and the push events are unordered, so the head is
    proven again immediately before the alias moves."""
    step = _step_with_id(DEV_WORKFLOW, "recheck-head")
    summary = tmp_path / "summary.md"
    summary.touch()
    head = _git(alias_repository, "rev-parse", "HEAD")
    stale = _git(alias_repository, "rev-parse", "HEAD~1")

    completed, _ = _run_step(
        str(step["run"]),
        {"GITHUB_STEP_SUMMARY": str(summary), "SOURCE_SHA": head},
        cwd=alias_repository,
    )
    assert completed.returncode == 0, completed.stderr

    completed, _ = _run_step(
        str(step["run"]),
        {"GITHUB_STEP_SUMMARY": str(summary), "SOURCE_SHA": stale},
        cwd=alias_repository,
    )
    assert completed.returncode != 0
    assert "no longer the head" in completed.stderr


def test_the_git_alias_action_runs_only_behind_the_ordering_gate() -> None:
    """F4's wiring half, which the behavioural tests above cannot see.

    They prove the ordering decision is correct. Nothing yet proved the action is
    actually *gated* on it -- and the action moves unconditionally, so an alias step
    that stopped consulting the decision would pass every ordering test in this file
    while dragging `vMAJOR` backwards on the next back-port release.

    The deciding step is found by the flag it passes, never by a step name, and the
    condition must name that step's own output.
    """
    examined = 0
    for path in sorted(WORKFLOWS.glob("*.yaml")):
        for job_name, job in _jobs(_load_workflow(path)).items():
            steps = job.get("steps", []) or []
            deciders = {
                str(step["id"])
                for step in steps
                if step.get("id")
                and ALIAS_ORDER_MARKER in _uncommented(str(step.get("run", "")))
            }
            for step in steps:
                if not str(step.get("uses", "")).startswith(APPROVED_ALIAS_ACTION):
                    continue
                examined += 1
                assert deciders, (
                    f"{path.name}: job {job_name!r} moves Git aliases without deciding "
                    f"from the tag set whether they may advance. The action compares "
                    f"nothing; the refusal is the workflow's (F4)."
                )
                condition = str(step.get("if", "")).replace(" ", "")
                assert any(
                    f"steps.{decider}.outputs.advance-major" in condition
                    for decider in deciders
                ), (
                    f"{path.name}: job {job_name!r} runs {APPROVED_ALIAS_ACTION} without "
                    f"gating on the ordering decision ({sorted(deciders)}); releasing an "
                    f"older patch would drag the major alias backwards (F4)"
                )
                inputs = step.get("with") or {}
                # The action's own input spelling AT `@v2`, which renamed every one of
                # them. The camelCase pair `@v1` took -- `updateMinor`,
                # `ignorePrerelease` -- is not an input here at all: Actions passes an
                # undeclared input through as an unread `INPUT_*` variable, the action
                # falls back to its defaults, and `update-minor` defaults to `false`.
                # The visible result is a `vMAJOR.MINOR` alias that silently never
                # moves. That camelCase pair is this guard's planted violation.
                # `ref-tag` is what the aliases are computed *from*. ADR-0006 claimed
                # this guard asserted the hyphenated inputs, and it asserted two of the
                # three: a step passing `update-minor` and `ignore-prerelease` and no
                # `ref-tag` passed, and the action would then move aliases against
                # whatever it defaults to. It must also resolve through the plan job's
                # released tag rather than a literal, or the alias is computed from
                # something other than the identity this run is publishing.
                # `tag` is the action's REQUIRED input at `@v2` -- the tag the major
                # and minor are extracted from. An earlier version of this guard
                # required `ref-tag`, which is the OPTIONAL override for what the
                # floating tags point at and whose documented default is the value of
                # `tag`. So it demanded the optional input and never the mandatory one,
                # and the first release to reach this step died on `Input required and
                # not supplied: tag` -- after the Release had already been created.
                #
                # Reading the manifest confirmed both names exist. Existing is not the
                # same as being the one that is required; that distinction is what this
                # release path has now cost twice.
                release_tag = str(inputs.get("tag", ""))
                assert release_tag, (
                    f"{path.name}: {job_name!r} moves aliases without passing `tag`, "
                    f"which `{APPROVED_ALIAS_ACTION}@v2` requires"
                )
                assert "needs.plan.outputs.release-tag" in release_tag, (
                    f"{path.name}: {job_name!r} passes tag={release_tag!r}, which is "
                    f"not the release tag the plan job resolved"
                )
                assert inputs.get("update-minor") == "true", (
                    f"{path.name}: {job_name!r} does not ask for the minor alias"
                )
                assert inputs.get("ignore-prerelease") == "true", (
                    f"{path.name}: {job_name!r} does not skip prereleases"
                )
                assert not (
                    set(inputs) & {"updateMinor", "ignorePrerelease", "refTag"}
                ), (
                    f"{path.name}: {job_name!r} passes the camelCase inputs of "
                    f"`{APPROVED_ALIAS_ACTION}@v1`; at `@v2` those are undeclared, "
                    f"silently ignored, and `update-minor` then defaults to false"
                )
                # And its OUTPUT names, for the same reason the inputs are asserted:
                # `@v2` renamed those too, and a wrong one renders `none` in the summary
                # on a fully successful move -- the same silent failure the input
                # spelling would have caused, one step further on.
                consumed = json.dumps(_jobs(_load_workflow(path))[job_name])
                for output in ("major-tag", "minor-tag"):
                    assert f"steps.{step['id']}.outputs.{output}" in consumed, (
                        f"{path.name}: {job_name!r} never reads the alias action's "
                        f"{output!r} output, so a successful move is reported as none"
                    )
    assert examined, "no workflow moves a Git alias; this guard examined nothing"


def test_the_release_step_never_asks_the_forge_to_create_its_own_trigger() -> None:
    """`commit:` makes the Release action create the tag at that SHA.

    This workflow is triggered by the tag push, so `refs/tags/vX.Y.Z` exists before the
    job starts. Passing `commit:` asks the forge to create a ref the run depends on
    already existing, and the first real release died on exactly that:
    `HTTP 422 Unprocessable Entity: {"message":"Reference already exists"}` -- after the
    image had been published and attested, with the Release and every alias unmade.

    Nothing is lost by omitting it: the tag identifies the Release, it already points at
    the released commit, and the re-check immediately above re-proves that it still
    peels to `source-sha`.
    """
    steps = _jobs(_load_workflow(RELEASE_WORKFLOW))["finalize"]["steps"]
    creating = [
        step
        for step in steps
        if str(step.get("uses", "")).startswith(APPROVED_RELEASE_ACTION)
    ]
    assert creating, "no step creates the Release"
    for step in creating:
        inputs = step.get("with") or {}
        assert "commit" not in inputs, (
            "the Release step passes `commit:`, which creates the tag. The tag is this "
            "workflow's trigger and already exists; the forge answers 422."
        )
        assert inputs.get("tag"), "the Release must name the tag it attaches to"


def test_the_release_carries_the_whole_verified_bundle_and_is_traceable(
    tmp_path: Path,
) -> None:
    """ADR-0010 and CI-AR41.

    Four files, because two of them are what makes the other two checkable: the wheel
    and the sdist are the distributions, `SHA256SUMS` and `build-manifest.json` are how
    someone reading the Release proves the attached wheel is the one the verifier saw.

    Every path is resolved through the revalidated bundle's own step -- found by the
    action it calls, not by a hand-kept step name -- so attaching a distribution from
    anywhere else fails here. And the Release's identity outputs must reach the run
    summary: a Release nobody can find from the run is evidence that does not exist.
    """
    examined = 0
    for path in sorted(WORKFLOWS.glob("*.yaml")):
        document = _load_workflow(path)
        for job_name, job in _jobs(document).items():
            steps = job.get("steps", []) or []
            release_steps = [
                step
                for step in steps
                if str(step.get("uses", "")).startswith(APPROVED_RELEASE_ACTION)
            ]
            if not release_steps:
                continue
            assert len(release_steps) == 1, f"{path.name}: {job_name!r} releases twice"
            step = release_steps[0]
            examined += 1
            assert str(step["uses"]).endswith("@v2"), (
                f"{path.name}: {APPROVED_RELEASE_ACTION} must be pinned @v2; @v2.0 is "
                f"stale and a patch tag forfeits the floating-major guarantee (ADR-0010)"
            )
            bundle = next(
                (
                    str(candidate["id"])
                    for candidate in steps
                    if str(candidate.get("uses", "")).endswith("/verified-bundle")
                    and candidate.get("id")
                ),
                None,
            )
            assert bundle, (
                f"{path.name}: {job_name!r} attaches a Release without revalidating the "
                f"bundle first, so the distributions were never proven to be the ones "
                f"the verifier saw"
            )
            artifacts = str((step.get("with") or {}).get("artifacts", ""))
            attached = [
                entry.strip() for entry in artifacts.split(",") if entry.strip()
            ]
            for required in (
                f"steps.{bundle}.outputs.wheel-filename",
                f"steps.{bundle}.outputs.sdist-filename",
                "SHA256SUMS",
                "build-manifest.json",
            ):
                assert any(required in entry for entry in attached), (
                    f"{path.name}: the Release does not attach {required!r}; the "
                    f"evidence half of the bundle is what makes the distributions "
                    f"checkable (ADR-0010, CI-AR41)"
                )
            # Every entry, not merely one of them: a wheel taken from `dist/` beside a
            # bundle-path sdist satisfies "the bundle appears somewhere" while shipping
            # a distribution the revalidation never saw.
            for entry in attached:
                assert f"steps.{bundle}.outputs.bundle-path" in entry, (
                    f"{path.name}: the Release attaches {entry!r} from outside the "
                    f"revalidated bundle"
                )

            # Recorded twice, because the two readers are different: the job output is
            # what the aggregator surfaces, and the step `env:` is what reaches this
            # job's own summary. Asserting only that the expression appears *somewhere*
            # in the file lets the summary row degrade to a literal while the job output
            # keeps the guard green -- which is exactly what the planted violation did.
            job_outputs = json.dumps(job.get("outputs") or {})
            step_environments = json.dumps(
                [candidate.get("env") or {} for candidate in steps]
            )
            for output in ("html-url", "assets"):
                reference = f"steps.{step['id']}.outputs.{output}"
                assert reference in job_outputs, (
                    f"{path.name}: the Release's {output!r} is not a job output, so the "
                    f"run aggregator cannot report it (CI-AR41)"
                )
                assert reference in step_environments, (
                    f"{path.name}: the Release's {output!r} never reaches this job's "
                    f"run summary (CI-AR41)"
                )
            # And the alias outcome beside it: a run that moved nothing and a run that
            # moved everything must not look the same in the summary.
            decider = next(
                (
                    str(candidate["id"])
                    for candidate in steps
                    if candidate.get("id")
                    and ALIAS_ORDER_MARKER
                    in _uncommented(str(candidate.get("run", "")))
                ),
                None,
            )
            assert decider, (
                f"{path.name}: {job_name!r} creates a Release without deciding which "
                f"aliases the tag set permits, so the run summary cannot say what "
                f"moved (F4, CI-AR41)"
            )
            summaries = "\n".join(
                _uncommented(str(candidate.get("run", ""))) for candidate in steps
            )
            assert "GITHUB_STEP_SUMMARY" in summaries, (
                f"{path.name}: {job_name!r} writes no run summary"
            )
            for advance in ("advance-major", "advance-minor"):
                reference = f"steps.{decider}.outputs.{advance}"
                assert reference in step_environments, (
                    f"{path.name}: {job_name!r} never records {advance!r}, so a release "
                    f"that moved no alias reads exactly like one that moved every alias"
                )
                assert reference in job_outputs, (
                    f"{path.name}: {advance!r} is not a job output, so the image alias "
                    f"job cannot consume the same decision (F4)"
                )
    assert examined, "no workflow creates a Release; this guard examined nothing"


def test_every_refusal_a_finalizer_makes_precedes_everything_it_writes() -> None:
    """The story's central invariant, and the one every other finalizer guard assumed.

    Each of the four refusals -- the enabled-set gate, the `vX.Y.Z` immutability
    re-check, the alias-ordering decision, the development channel's just-in-time head
    proof -- is asserted *present* elsewhere, and its behaviour is executed. Nothing
    asserted it runs **first**. Moving the gate step to the end of `finalize` left every
    guard green while a release with an enabled destination missing would get its
    Release, its `vMAJOR`, its `latest` and its `dev`, and only then go red: strictly
    worse than not gating at all, because the run is now half-finalized and the Release
    has to be deleted by hand before it can be retried.

    Both sets are derived -- writes from the approved actions and the alias commands,
    refusals from the mechanisms that perform them -- so a new way to write, or a new
    refusal, is ordered by this guard without an edit here.
    """
    examined = 0
    for path in sorted(WORKFLOWS.glob("*.yaml")):
        for job_name in sorted(_finalizers(path)):
            job = _jobs(_load_workflow(path))[job_name]
            writes = _writing_steps(job)
            if not writes:
                continue
            examined += 1
            refusals = _refusing_steps(job)
            assert refusals, (
                f"{path.name}: finalizer {job_name!r} writes without refusing anything "
                f"first; the gate, the tag re-check and the ordering decision are what "
                f"make the write conditional"
            )
            assert max(refusals) < min(writes), (
                f"{path.name}: finalizer {job_name!r} performs a refusal at step "
                f"{max(refusals)} but has already written at step {min(writes)}. A "
                f"refusal after the write reports the damage instead of preventing it."
            )
    assert examined, "no finalizer writes anything; this guard examined nothing"


def test_a_finalizer_never_leaves_a_credential_in_the_workspace() -> None:
    """`persist-credentials: false` is a repository-wide invariant, and a job that needs
    to push has to supply the credential some other way. Writing it into `.git/config`
    -- a remote URL carrying userinfo, or an `http.*.extraheader` -- defeats the
    invariant rather than working within it: the token then outlives the step that
    needed it, and on the reused `act_runner` workspace E009 targets it outlives the
    job. git's own `GIT_CONFIG_COUNT`/`KEY`/`VALUE` protocol scopes it to one process
    environment, which is what a job-scoped grant means.
    """
    persisted = (
        r"git\s+remote\s+(?:set-url|add)[^\n]*\$\{?[A-Za-z_]*(?:TOKEN|PASSWORD)",
        r"git\s+config[^\n]*extraheader",
        r"credential\.helper\s+store",
    )
    for path in sorted(WORKFLOWS.glob("*.yaml")):
        for job_name, job in _jobs(_load_workflow(path)).items():
            for step in job.get("steps", []) or []:
                command = _uncommented(str(step.get("run", "")))
                for pattern in persisted:
                    assert not re.search(pattern, command), (
                        f"{path.name}: job {job_name!r} writes a credential into the "
                        f"workspace's git configuration, where it outlives the step "
                        f"that needed it. Pass it through GIT_CONFIG_* on the step "
                        f"instead."
                    )


def test_a_disabled_docker_hub_is_addressed_by_no_alias_step() -> None:
    """CI-AR40's "no credentials **or requests**", at the second place it now has to
    hold.

    `test_a_disabled_docker_hub_receives_no_alias_request` executes the bash with an
    empty repository supplied by the test, which proves the bash copes -- not that the
    workflow ever produces an empty value. Deleting the login step's `if:`, or making
    the `DOCKERHUB_REPOSITORY` expression unconditional, left every guard green; the
    runtime was safe only because the plan job happens to emit an empty
    `dockerhub-repository` when the toggle is off, which is two independently-edited
    derivations agreeing by luck.

    The step set is derived -- anything mentioning Docker Hub in a job that moves an
    alias -- so a third way of addressing that destination is covered without an edit.
    """
    examined = 0
    for path, job_name in sorted(_alias_moving_jobs()):
        # `_alias_moving_jobs` keys composite actions by their repo-relative path, not
        # by a workflow filename, so composing `WORKFLOWS / path` raised
        # `FileNotFoundError: .../.github/workflows/.github/actions/...` -- a crash that
        # reads as a broken test rather than a caught violation, which is how a real one
        # gets triaged as flake. Composite actions carry no Docker Hub condition of
        # their own; the job that calls them does, and that job is examined here.
        if job_name == "runs":
            continue
        job = _jobs(_load_workflow(WORKFLOWS / path))[job_name]
        for step in job.get("steps", []) or []:
            body = json.dumps({k: v for k, v in step.items() if k != "run"})
            if not re.search(r"docker\.io|DOCKERHUB", body):
                continue
            examined += 1
            condition = str(step.get("if", ""))
            assert (
                "enabled-destinations" in condition or "enabled-destinations" in body
            ), (
                f"{path}: job {job_name!r} addresses Docker Hub from a step that never "
                f"consults the enabled set, so a run with the destination disabled "
                f"would still send it credentials or requests (CI-AR40, ADR-0011)"
            )
    assert examined, "no alias step addresses Docker Hub; this guard examined nothing"


def test_a_failing_registry_write_still_reports_which_names_moved(
    tmp_path: Path,
) -> None:
    """H2: `set -e` aborts the step at the first failing `imagetools create`, and a
    summary written after the loop is then written never -- leaving a partially aliased
    registry with no record of which names moved, in exactly the situation an operator
    needs that record to reconcile by hand (CI-AR41)."""
    directory = tmp_path / "bin"
    directory.mkdir()
    log = tmp_path / "docker.log"
    stub = directory / "docker"
    # Succeeds for the forge registry, fails for Docker Hub: the ordinary transient
    # registry error, half way through the fan-out.
    stub.write_text(
        "#!/usr/bin/env bash\n"
        f'printf "%s\\n" "$*" >> "{log}"\n'
        'case "$*" in *docker.io*) exit 1 ;; esac\n',
        encoding="utf-8",
    )
    stub.chmod(0o755)
    summary = tmp_path / "summary.md"
    summary.touch()
    step = _step_with_id(RELEASE_WORKFLOW, "image-alias")
    completed, _ = _run_step(
        str(step["run"]),
        {
            "PATH": f"{directory}:{os.environ['PATH']}",
            "GITHUB_STEP_SUMMARY": str(summary),
            "ADVANCE_MAJOR": "true",
            "ADVANCE_MINOR": "true",
            "DOCKERHUB_REPOSITORY": "docker.io/owner/name",
            "IMAGE_DIGEST": DIGEST,
            "IMAGE_REPOSITORY": "ghcr.io/owner/name",
            "MAJOR_ALIAS": "v1",
            "MINOR_ALIAS": "v1.3",
        },
        cwd=tmp_path,
    )
    assert completed.returncode != 0, "a failing registry write finished green"
    rendered = summary.read_text(encoding="utf-8")
    moved = [line for line in rendered.splitlines() if line.startswith("- Moved:")]
    unconfirmed = [
        line for line in rendered.splitlines() if line.startswith("- **Unconfirmed**:")
    ]
    assert any("ghcr.io/owner/name:latest" in line for line in moved), (
        f"the aliases that DID move are unreported: {rendered!r}"
    )
    assert not any("docker.io/owner/name" in line for line in moved), (
        "an alias that failed is reported as moved"
    )
    # MEDIUM-1: `imagetools create -t a -t b` writes each tag in turn, so a failure part
    # way leaves names this step may have moved and cannot confirm. Absent from the
    # record they read as untouched, which is the reconciliation reporting the opposite
    # of the truth -- so they are named as unconfirmed rather than omitted.
    assert any("docker.io/owner/name" in line for line in unconfirmed), (
        f"a name this step may have written is missing from the record: {rendered!r}"
    )


def test_the_release_is_idempotent_for_the_identity_it_already_created() -> None:
    """M3: the Release is the FIRST irreversible write and every alias move comes after
    it, so the one step that cannot be retried is the one that runs first.

    With `allow-updates: false` a re-run of the finalizer -- after a transient registry
    error, an expired token, anything at all in the alias fan-out -- dies at the Release
    step, and the operator has to delete the Release from the forge UI before the run
    can be resumed. Updating is safe for this identity and only this one:
    `refs/tags/vX.Y.Z` is immutable (ADR-0006) and the step immediately before re-proves
    that the tag still peels to this commit, so a second run of this job is the same
    release by construction rather than a different one wearing the same name.
    """
    examined = 0
    for path in sorted(WORKFLOWS.glob("*.yaml")):
        for job_name, job in _jobs(_load_workflow(path)).items():
            for step in job.get("steps", []) or []:
                if not str(step.get("uses", "")).startswith(APPROVED_RELEASE_ACTION):
                    continue
                examined += 1
                inputs = step.get("with") or {}
                assert inputs.get("allow-updates") == "true", (
                    f"{path.name}: {job_name!r} cannot re-create the Release for an "
                    f"identity it already published, so any failure in the alias moves "
                    f"that follow strands the run until someone deletes the Release by "
                    f"hand (ADR-0006)"
                )
                # Idempotent is not the same as permissive: the identity re-check has to
                # still be in front of it, or "update the existing Release" becomes
                # "overwrite whatever is at that tag now".
                refusals = _refusing_steps(job)
                writes = _writing_steps(job)
                assert refusals and max(refusals) < min(writes), (
                    f"{path.name}: {job_name!r} updates an existing Release without "
                    f"re-proving the tag still names this commit first"
                )
    assert examined, "no workflow creates a Release; this guard examined nothing"


def _membership_steps(path: Path) -> dict[str, list[str]]:
    """Every step deciding annotated-stable-tag membership, split by what it does.

    Located by the mechanism (`%(objecttype)`), never by a step name or an `id:`: a
    re-check whose body was gutted stops being found, and the count assertions below
    then fail loudly rather than examining nothing. `emitters` publish the conclusion
    as a step output; `refusers` exit non-zero instead.
    """
    found: dict[str, list[str]] = {"emitters": [], "refusers": []}
    for job in _jobs(_load_workflow(path)).values():
        for step in job.get("steps") or []:
            body = _uncommented(str(step.get("run", "")))
            if TAG_MEMBERSHIP_MARKER not in body:
                continue
            found["emitters" if "GITHUB_OUTPUT" in body else "refusers"].append(body)
    return found


def _irreversible_jobs(path: Path) -> set[str]:
    """Jobs doing something no later step can undo: ship an artifact, create the
    Release, or point a mutable name at one.

    The count of these is what "one re-check before each irreversible act" means, so it
    is derived rather than written down. The two guards below asserted 4 and 3 by hand:
    an irreversible act added *without* a re-check left the count unchanged and passed,
    which is the reach the literal was supposed to supply, and the number went red for
    the wrong reason the day a destination was added.
    """
    document = _load_workflow(path)
    shipping = {
        name
        for name, job in _jobs(document).items()
        if any(_is_publishing_step(step) for step in job.get("steps") or [])
        # An attestation is a signed public statement about an identity, written to a
        # store this repository cannot retract. It is as irreversible as an upload, and
        # it therefore re-reads the identity immediately before making it.
        or (job.get("permissions") or {}).get("attestations") == "write"
    }
    aliases = {job for workflow, job in _alias_moving_jobs() if workflow == path.name}
    return shipping | aliases


def test_every_stable_tag_recheck_is_the_same_body() -> None:
    """One relation, copied into four steps, asserted to be one copy.

    The stable channel re-reads the tag immediately before each irreversible act: the
    two package uploads, the Release, and the image aliases. Duplication is the price
    of keeping the decision in the workflow -- so the guard is that the copies cannot
    diverge. A single edited copy fails here rather than reaching a registry.
    """
    refusers = _membership_steps(RELEASE_WORKFLOW)["refusers"]
    expected = _irreversible_jobs(RELEASE_WORKFLOW)
    assert len(refusers) == len(expected), (
        f"release.yaml has {len(refusers)} pre-write tag re-checks for "
        f"{len(expected)} irreversible acts ({', '.join(sorted(expected))}); there is "
        f"one before each"
    )
    assert len(set(refusers)) == 1, "the stable tag re-checks have diverged"
    assert all(STABLE_RECHECK_MARKER in body for body in refusers)


def test_every_suppression_recheck_is_the_same_body() -> None:
    """The development channel's copies of the same relation, under the same rule."""
    steps = _membership_steps(DEV_WORKFLOW)
    assert len(steps["emitters"]) == 1, "the suppression conclusion has one producer"
    expected = _irreversible_jobs(DEV_WORKFLOW)
    assert len(steps["refusers"]) == len(expected), (
        f"dev.yaml has {len(steps['refusers'])} pre-write suppression re-checks for "
        f"{len(expected)} irreversible acts ({', '.join(sorted(expected))}); there is "
        f"one before each"
    )
    assert len(set(steps["refusers"])) == 1, "the suppression re-checks have diverged"


def _run_stable_recheck(
    repository: Path,
    tag: str,
    commit: str | None = None,
    default_branch_ref: str = "main",
) -> Any:
    body = _membership_steps(RELEASE_WORKFLOW)["refusers"][0]
    completed, _ = _run_step(
        body,
        {
            "DEFAULT_BRANCH_REF": default_branch_ref,
            "RELEASE_TAG": tag,
            "SOURCE_SHA": commit or _git(repository, "rev-parse", "HEAD"),
        },
        cwd=repository,
    )
    return completed


def test_the_stable_recheck_refuses_a_tag_that_left_the_default_branch(
    tagged_repository: Path,
) -> None:
    """The reachability leg, which the pre-upload re-check did not carry.

    The plan job proves the commit is reachable from the protected default branch, and
    every re-check then re-proved only the tag relation: the tag is annotated, exact,
    and still peels to this commit. All three survive a force-push to the branch that
    removes the history the release was cut from -- the tag object is untouched, so the
    old body passed and the publisher uploaded from history the branch no longer has.

    `v2.0.0` in the fixture is exactly that shape: annotated, exact, peeling correctly,
    and on a side branch `main` never took.
    """
    side_commit = _git(tagged_repository, "rev-parse", "v2.0.0^{commit}")
    completed = _run_stable_recheck(tagged_repository, "v2.0.0", commit=side_commit)
    assert completed.returncode != 0, (
        "a tag on history the default branch never took was accepted for publication"
    )
    assert "no longer reachable" in completed.stderr, completed.stderr


def test_the_stable_recheck_accepts_the_annotated_tag_that_names_the_commit(
    tagged_repository: Path,
) -> None:
    completed = _run_stable_recheck(tagged_repository, "v1.2.3")
    assert completed.returncode == 0, completed.stderr


@pytest.mark.parametrize(
    ("tag", "reason"),
    [
        ("v9.9.9", "a lightweight tag of the right name is not the release identity"),
        ("v1.2", "a floating alias is not an exact version"),
        ("v1.2.3-rc1", "a prerelease is not a stable release"),
        ("1.2.3", "the stable spelling carries the v prefix"),
        ("v01.2.3", "a zero-padded component is malformed"),
        ("v1.2.3.4", "a fourth component is not the release spelling"),
        ("release-1.2.3", "a prefixed name is not the release spelling"),
        ("v0.9.0", "this tag peels to another commit"),
        ("v4.5.6", "this tag does not exist at all"),
    ],
)
def test_the_stable_recheck_refuses_anything_that_is_not_that_tag(
    tagged_repository: Path, tag: str, reason: str
) -> None:
    """The pre-upload refusal, run against real git rather than described.

    `v9.9.9` is the anchor the maintainer named: it is spelled exactly right and it
    peels to exactly this commit, and it is refused solely because it is lightweight.
    Dropping the `%(objecttype)` filter makes this case pass and this test fail --
    which is the release-breaking defect story 002 recorded as HIGH-1.
    """
    completed = _run_stable_recheck(tagged_repository, tag)
    assert completed.returncode != 0, f"{tag} was accepted, but {reason}"


def _run_suppression_guard(repository: Path, commit: str) -> tuple[Any, dict[str, str]]:
    body = _membership_steps(DEV_WORKFLOW)["emitters"][0]
    return _run_step(body, {"SOURCE_SHA": commit}, cwd=repository)


def test_only_an_annotated_exact_stable_tag_suppresses_development(
    tagged_repository: Path,
) -> None:
    """Every rejection in one execution, because the commit carries every shape.

    On this commit sit `v1.2.3` (annotated, exact), `v9.9.9` (exact but lightweight),
    `v1.2`, `v1.2.3-rc1`, `1.2.3` and `v01.2.3` (annotated, wrong spelling). Only the
    first may suppress a development publication, and the emitted list says which did.
    Deleting the annotated-object filter adds `v9.9.9`; loosening the spelling adds the
    rest; each fails here.
    """
    head = _git(tagged_repository, "rev-parse", "HEAD")
    completed, emitted = _run_suppression_guard(tagged_repository, head)
    assert completed.returncode == 0, completed.stderr
    assert emitted["suppressed"] == "true"
    assert emitted["stable-tags"] == "v1.2.3"


def test_a_stable_tag_on_an_ancestor_does_not_suppress_the_new_head(
    tagged_repository: Path,
) -> None:
    """The peel is compared to THIS commit, not asked "is a release in my history".

    Every commit after a release has a release in its history, so the reachability
    reading would suppress every development publication this project ever makes.
    """
    (tagged_repository / "file.txt").write_text("three\n", encoding="utf-8")
    _git(tagged_repository, "add", ".")
    _git(tagged_repository, "commit", "-m", "three")
    head = _git(tagged_repository, "rev-parse", "HEAD")
    completed, emitted = _run_suppression_guard(tagged_repository, head)
    assert completed.returncode == 0, completed.stderr
    assert emitted["suppressed"] == "false"
    assert emitted["stable-tags"] == ""


def test_the_suppression_recheck_refuses_a_tag_that_landed_after_the_guard(
    tagged_repository: Path,
) -> None:
    """F16's cheap hardening, executed: the window is narrowed, and the refusal is real.

    The guard job answered before the verifier finished. A tag that lands afterwards
    must stop the upload, because an immutable `X.Y.Z.devN` published for a release
    commit cannot be withdrawn.
    """
    body = _membership_steps(DEV_WORKFLOW)["refusers"][0]
    head = _git(tagged_repository, "rev-parse", "HEAD")
    completed, _ = _run_step(body, {"SOURCE_SHA": head}, cwd=tagged_repository)
    assert completed.returncode != 0
    assert "v1.2.3" in completed.stderr

    (tagged_repository / "file.txt").write_text("four\n", encoding="utf-8")
    _git(tagged_repository, "add", ".")
    _git(tagged_repository, "commit", "-m", "four")
    untagged = _git(tagged_repository, "rev-parse", "HEAD")
    completed, _ = _run_step(body, {"SOURCE_SHA": untagged}, cwd=tagged_repository)
    assert completed.returncode == 0, completed.stderr


def test_a_release_that_never_reached_the_default_branch_has_no_alias_plan(
    alias_repository: Path,
) -> None:
    """`v9.0.0` is annotated, exactly spelled, and the greatest tag in the repository.

    It is still not a release this project made: it sits on history the protected
    default branch never took. `--merged` is both the reachability answer and the
    membership test, so the ordering step refuses rather than handing `v9` an alias.
    """
    completed, _ = _alias_plan(alias_repository, "v9.0.0")
    assert completed.returncode != 0
    assert "v9.0.0" in completed.stderr


def test_a_neighbouring_minor_is_not_mistaken_for_this_one(
    major_boundary_repository: Path,
) -> None:
    """`v1.2.` cannot prefix `v1.20.0`, and the trailing separator is why.

    Without it `v1.20.0` would count as the greatest release within `v1.2`, and the
    `v1.2` alias would stop advancing on runs that all finish green.
    """
    completed, emitted = _alias_plan(major_boundary_repository, "v1.2.3")
    assert completed.returncode == 0, completed.stderr
    assert emitted["minor-alias"] == "v1.2"
    assert emitted["advance-minor"] == "true"
    assert emitted["advance-major"] == "false"
    assert emitted["greatest-stable"] == "v2.0.0"


def test_the_first_release_of_a_new_major_advances_its_own_aliases(
    major_boundary_repository: Path,
) -> None:
    """Greatest overall, and greatest within a `MAJOR.MINOR` containing only itself."""
    completed, emitted = _alias_plan(major_boundary_repository, "v2.0.0")
    assert completed.returncode == 0, completed.stderr
    assert emitted["major-alias"] == "v2"
    assert emitted["minor-alias"] == "v2.0"
    assert emitted["advance-major"] == "true"
    assert emitted["advance-minor"] == "true"


def test_the_ordering_is_gits_version_order_never_a_lexicographic_one(
    alias_repository: Path,
) -> None:
    """`v1.2.10` sorts BELOW `v1.2.3` under every string comparison and above it under
    git's `v:refname`. The greatest tag reported is the whole ordering assertion."""
    completed, emitted = _alias_plan(alias_repository, "v1.2.10")
    assert completed.returncode == 0, completed.stderr
    assert emitted["greatest-stable"] == "v1.3.0"


# --- the finalization gate's input validation (gate finding F7) -------------
def test_a_destination_with_no_result_is_a_wiring_defect() -> None:
    """The finalizer did not `needs:` everything, so a destination reported nothing.

    Treating that as absent is the silent failure: the release finalizes while a
    destination nobody watched was still running, or had died.
    """
    bindings = _stable_bindings()
    bindings["needs.plan.outputs.enabled-destinations"] = json.dumps(
        {
            "image-forge": "enabled",
            "image-dockerhub": "disabled",
            "package-forge": "unsupported",
            "package-pypi": "enabled",
            "package-testpypi": "enabled",
        }
    )
    completed = _run_gate(RELEASE_WORKFLOW, bindings)
    assert completed.returncode != 0
    # The wiring refusal specifically, not merely "something failed". Deleting the
    # check leaves the destination with a `null` result, which the unknown-result
    # branch also refuses -- green for the wrong reason, and silent the day a result
    # of `null` becomes representable.
    assert "no publisher result was supplied for package-testpypi" in completed.stderr


def test_a_result_for_a_destination_nobody_planned_is_a_wiring_defect() -> None:
    """The other direction: the static job graph and the runtime set have drifted."""
    bindings = _stable_bindings()
    bindings["needs.plan.outputs.enabled-destinations"] = json.dumps(
        {"image-forge": "enabled", "image-dockerhub": "disabled"}
    )
    completed = _run_gate(RELEASE_WORKFLOW, bindings)
    assert completed.returncode != 0
    assert (
        "results were supplied for attestation, package-forge, package-pypi"
        in completed.stderr
    )


def test_an_empty_enabled_set_blocks_rather_than_finalizing_nothing() -> None:
    bindings = {
        f"needs.{job}.result": "skipped"
        for job in (
            "publish-image",
            "publish-package-forge",
            "publish-package-pypi",
            "attest",
        )
    }
    bindings["needs.verify.result"] = "success"
    bindings["needs.plan.outputs.enabled-destinations"] = "{}"
    completed = _run_gate(RELEASE_WORKFLOW, bindings)
    assert completed.returncode != 0
    assert "names no destination at all" in completed.stderr


@pytest.mark.parametrize("raw", ["", "   ", "not json", "[]", '"a string"'])
def test_a_malformed_enabled_set_blocks(raw: str) -> None:
    """An upstream job that failed before emitting the set must block finalization,
    never fall through to an empty one."""
    bindings = _stable_bindings()
    bindings["needs.plan.outputs.enabled-destinations"] = raw
    completed = _run_gate(RELEASE_WORKFLOW, bindings)
    assert completed.returncode != 0


@pytest.mark.parametrize("state", ["on", "true", "ENABLED", ""])
def test_an_unrecognised_destination_state_blocks(state: str) -> None:
    bindings = _stable_bindings()
    bindings["needs.plan.outputs.enabled-destinations"] = json.dumps(
        {
            "image-forge": state,
            "image-dockerhub": "disabled",
            "package-forge": "unsupported",
            "package-pypi": "enabled",
            "attestation": "enabled",
        }
    )
    completed = _run_gate(RELEASE_WORKFLOW, bindings)
    assert completed.returncode != 0
    assert "image-forge" in completed.stderr


@pytest.mark.parametrize("result", ["succeeded", "SUCCESS", "", "neutral"])
def test_an_unrecognised_job_result_blocks(result: str) -> None:
    completed = _run_gate(
        RELEASE_WORKFLOW, _stable_bindings(**{"publish-image": result})
    )
    assert completed.returncode != 0


def test_every_blocking_destination_is_reported_not_only_the_first() -> None:
    """An operator reading one line and re-running into the second failure is the
    experience this avoids."""
    completed = _run_gate(
        RELEASE_WORKFLOW,
        _stable_bindings(
            **{"publish-package-pypi": "skipped", "publish-image": "failure"}
        ),
    )
    assert completed.returncode != 0
    assert "package-pypi" in completed.stderr
    assert "image-forge" in completed.stderr


def test_the_gate_writes_its_evidence_table_where_it_is_told(tmp_path: Path) -> None:
    """Every planned state and every job result, in the run summary, on success and on
    refusal alike -- a refusal that says nothing about the other destinations leaves an
    operator guessing which ones were fine."""
    summary = tmp_path / "summary.md"
    completed = _run_gate(RELEASE_WORKFLOW, _stable_bindings(), summary)
    assert completed.returncode == 0, completed.stderr
    rendered = summary.read_text(encoding="utf-8")
    assert "### Finalization gate" in rendered
    for destination in (
        "image-forge",
        "image-dockerhub",
        "package-forge",
        "package-pypi",
        "attestation",
        "verify",
    ):
        assert f"`{destination}`" in rendered
    assert "`blocks`" not in rendered

    blocked = tmp_path / "blocked.md"
    completed = _run_gate(
        RELEASE_WORKFLOW,
        _stable_bindings(**{"publish-package-pypi": "skipped"}),
        blocked,
    )
    assert completed.returncode != 0
    rendered = blocked.read_text(encoding="utf-8")
    assert "| `package-pypi` | `enabled` | `skipped` | `blocks` |" in rendered
    assert "| `image-forge` | `enabled` | `success` | `ok` |" in rendered


@pytest.mark.parametrize("blocking", ["failure", "cancelled"])
def test_a_failure_blocks_even_on_a_destination_the_plan_says_is_off(
    blocking: str,
) -> None:
    """`disabled` and `unsupported` excuse a SKIP, never a failure.

    A destination that was switched off cannot fail; if its job reports one, something
    ran that nobody planned, and finalizing over it is exactly the state ADR-0011 keeps
    the finalizer away from. `package-forge` is `unsupported` in these bindings.
    """
    completed = _run_gate(
        RELEASE_WORKFLOW, _stable_bindings(**{"publish-package-forge": blocking})
    )
    assert completed.returncode != 0
    assert f"package-forge reported {blocking}" in completed.stderr
