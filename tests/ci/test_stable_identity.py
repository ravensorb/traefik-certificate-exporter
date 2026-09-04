"""What a stable release IS, and what may act on it once it is proven.

BL-E008-010 phase 3. The release guard, the identity relation the whole channel agrees on,
and the destination set derived from the toggles. Every guard here was proven by planting
the violation it forbids -- rule AND scope.

The identity is asserted as a RELATION between fields, never against a literal version:
fixtures pinned to a committed version made the project unreleasable once, because the
guard passed only for the version that happened to be checked in when it was written.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import pytest

from tests.ci.support import (
    PROJECT_ROOT,
    PUBLISH_IMAGE_REFERENCE,
    PUBLISH_IMAGE_WORKFLOW,
    RELEASE_WORKFLOW,
    REQUIRED_IMAGE_PLATFORMS,
    VERIFIER_REFERENCE,
    _git,
    _image_channel_workflows,
    _jobs,
    _load_fixture,
    _load_workflow,
    _producing_step,
    _publishers,
    _publishing_workflows,
    _run_step,
    _step_with_id,
    _transitive_needs,
    _uncommented,
    committed_versions,
)


def _executable_text(document: dict[str, Any]) -> str:
    """Everything a workflow actually executes, with shell comments removed.

    A prohibition read off the raw file cannot tell "this workflow publishes to X" from
    "this comment explains why it never publishes to X" -- and a guard that fires on the
    explanation gets deleted rather than fixed.
    """
    parts = []
    for job in _jobs(document).values():
        parts.append(json.dumps({k: v for k, v in job.items() if k != "steps"}))
        for step in job.get("steps") or []:
            parts.append(json.dumps({k: v for k, v in step.items() if k != "run"}))
            parts.append(_uncommented(str(step.get("run", ""))))
    return "\n".join(parts)


def test_the_stable_channel_owns_exact_tag_pushes() -> None:
    """The residual left on BL-E008-001: `v*` tag pushes reached nothing.

    `test_any_push_triggered_workflow_verifies_before_it_ships` asserts the conditional
    invariant and would pass vacuously with no stable workflow at all, exactly as it did
    before dev.yaml. This one asserts the workflow exists and is shaped as ADR-0011
    requires, so deleting release.yaml reopens the finding loudly.
    """
    document = _load_workflow(RELEASE_WORKFLOW)
    triggers = document["on"]
    assert set(triggers) == {"push"}
    assert set(triggers["push"]) == {"tags"}
    assert triggers["push"]["tags"] == ["v*"]
    assert document["permissions"] == {"contents": "read"}
    # The deliberate difference from dev.yaml: two tag pushes are two distinct immutable
    # identities, so the second queues rather than cancelling a half-finished fan-out.
    assert document["concurrency"]["cancel-in-progress"] == "false"

    # Exactly one verifier call for the tagged SHA. Counted from the parsed document, so
    # a second call added anywhere in the file -- another job, another spelling of the
    # same `uses:` -- fails here.
    verifier_calls = [
        name
        for name, job in _jobs(document).items()
        if job.get("uses") == VERIFIER_REFERENCE
    ]
    assert verifier_calls == ["verify"]
    verify = _jobs(document)["verify"]
    assert verify["with"]["channel"] == "stable"
    assert verify["with"]["source-sha"] == "${{ needs.plan.outputs.source-sha }}"

    # TestPyPI is development-only, and this is the channel, not a toggle (ADR-0011).
    # Asserted over what the file EXECUTES -- job configuration, step inputs and
    # uncommented `run:` bodies -- so the prose explaining why TestPyPI is absent does
    # not read as the destination being present.
    executable = _executable_text(document)
    assert "TESTPYPI" not in executable.upper(), (
        "release.yaml reaches TestPyPI; that destination is development-only (ADR-0011)"
    )
    assert "test.pypi.org" not in executable


def test_the_release_tag_fixture_is_internally_consistent() -> None:
    """The relations the identity guard reads, not the repository's current version.

    Same deadlock as the dispatch fixture above: pinning this to the committed version
    meant `just release` could never pass its own `just check`, because the bump lands
    before the check and the fixture still names the previous release. What the guards
    that consume this fixture actually need is that `ref`, `ref_name` and the exact
    stable spelling agree with each other, and that the SHA is a real object name.
    """
    event = _load_fixture("push-tag.json")
    assert event["event_name"] == "push"
    assert event["ref"] == f"refs/tags/{event['ref_name']}"
    assert re.fullmatch(r"v\d+\.\d+\.\d+", str(event["ref_name"])), event["ref_name"]
    assert re.fullmatch(r"[0-9a-f]{40}", event["sha"])


@pytest.mark.parametrize(
    ("ref", "reason"),
    [
        ("refs/tags/v9.9.9", "a lightweight tag is not the release identity"),
        ("refs/tags/v1.2", "a floating alias is not an exact version"),
        ("refs/tags/v1.2.3-rc1", "a prerelease is not a stable release"),
        ("refs/tags/1.2.3", "the stable spelling carries the v prefix"),
        ("refs/tags/v01.2.3", "a zero-padded component is malformed"),
        ("refs/tags/v1.2.3.4", "a fourth component is not the release spelling"),
        ("refs/tags/release-1.2.3", "a prefixed name is not the release spelling"),
        ("refs/heads/main", "a branch ref is not a tag at all"),
        (
            "refs/heads/v1.2.3",
            "a branch that shares a release tag's name is still not the tag",
        ),
        ("refs/tags/v0.9.0", "the peeled commit is not the event SHA"),
    ],
)
def test_the_release_guard_rejects_every_ref_that_is_not_an_exact_stable_tag(
    tagged_repository: Path, ref: str, reason: str
) -> None:
    """The ref table, run against the guard's real `run:` body and real git.

    Planted to prove it: delete the
    `[[ "$(git for-each-ref --format='%(objecttype)' ...)" == tag ]]` line from the
    `tag` step's body in release.yaml (`:391`) and the lightweight case passes, so this
    test fails. The instruction used to name `stable_tags.annotated_tags`, a module
    E008-S01-003 deleted -- an unfollowable plant is a claim with no evidence behind it.
    """
    head = _git(tagged_repository, "rev-parse", "HEAD")
    completed, _ = _run_step(
        str(_step_with_id(RELEASE_WORKFLOW, "tag")["run"]),
        {"DEFAULT_BRANCH_REF": "main", "EVENT_REF": ref, "EVENT_OBJECT": head},
        tagged_repository,
    )
    assert completed.returncode != 0, f"{ref} was accepted, but {reason}"


def test_the_release_guard_accepts_the_annotated_exact_tag_on_the_event_commit(
    tagged_repository: Path,
) -> None:
    head = _git(tagged_repository, "rev-parse", "HEAD")
    completed, emitted = _run_step(
        str(_step_with_id(RELEASE_WORKFLOW, "tag")["run"]),
        {
            "DEFAULT_BRANCH_REF": "main",
            "EVENT_REF": "refs/tags/v1.2.3",
            "EVENT_OBJECT": head,
        },
        tagged_repository,
    )
    assert completed.returncode == 0, completed.stderr
    assert emitted["tag"] == "v1.2.3"
    assert emitted["version"] == "1.2.3"
    assert emitted["tag-commit"] == head


def test_the_release_guard_refuses_a_tag_that_never_reached_the_default_branch(
    tagged_repository: Path,
) -> None:
    """Reachability is git's answer, not a pattern: `v2.0.0` is annotated, exactly
    spelled, and peels to the event commit. It is still not publishable, because that
    commit is on history the protected default branch never took."""
    side = _git(tagged_repository, "rev-parse", "sidebranch")
    _git(tagged_repository, "checkout", "--detach", side)
    completed, _ = _run_step(
        str(_step_with_id(RELEASE_WORKFLOW, "tag")["run"]),
        {
            "DEFAULT_BRANCH_REF": "main",
            "EVENT_REF": "refs/tags/v2.0.0",
            "EVENT_OBJECT": side,
        },
        tagged_repository,
    )
    assert completed.returncode != 0, "an unreachable release tag was accepted"


def test_the_release_guard_refuses_a_checkout_that_is_not_the_event_commit(
    tagged_repository: Path,
) -> None:
    """The guard peels tags out of the checked-out repository, so a checkout that is not
    the event commit would have it answering about the wrong history entirely."""
    ancestor = _git(tagged_repository, "rev-parse", "HEAD~1")
    completed, _ = _run_step(
        str(_step_with_id(RELEASE_WORKFLOW, "tag")["run"]),
        {
            "DEFAULT_BRANCH_REF": "main",
            "EVENT_REF": "refs/tags/v0.9.0",
            "EVENT_OBJECT": ancestor,
        },
        tagged_repository,
    )
    assert completed.returncode != 0, "a checkout that is not the event commit passed"


def _release_identity_environment(**overrides: str) -> dict[str, str]:
    event = _load_fixture("push-tag.json")
    version = committed_versions.package_version()
    environment = {
        "COMMITTED_VERSION": version,
        "IMAGE_REPOSITORY": f"ghcr.io/{event['repository']}",
        "RELEASE_TAG": f"v{version}",
        "RELEASE_VERSION": version,
        "RESOLVED_PYTHON": "3.14.0",
        "TAG_COMMIT": event["sha"],
    }
    environment.update(overrides)
    return environment


def test_the_stable_identity_is_a_relation_between_fields_never_a_literal(
    tmp_path: Path,
) -> None:
    """CI-AR11, asserted by RUNNING the identity step rather than by reading it.

    The step compares the tag, the version it spells, the committed Poetry version, the
    peeled tag commit and the event SHA against each other. Nothing in it names a
    version, which is the property that makes the next release use the same code path as
    this one -- so the literal check is part of the guard, not a separate style rule.
    """
    identity = _step_with_id(RELEASE_WORKFLOW, "identity")
    body = str(identity["run"])
    assert not re.search(r"[0-9]+\.[0-9]+\.[0-9]+", _uncommented(body)), (
        "the stable identity step names a version literal; it must compare fields"
    )

    completed, emitted = _run_step(body, _release_identity_environment(), tmp_path)
    assert completed.returncode == 0, completed.stderr
    version = committed_versions.package_version()
    event = _load_fixture("push-tag.json")
    assert emitted["package-version"] == version
    assert emitted["source-sha"] == event["sha"]
    assert emitted["python-version"] == "3.14.0"
    # Exactly one immutable tag per enabled destination, and no alias: `latest`, `vX`
    # and `vX.Y` all belong to the finalizer story. The value is decided here; rendering
    # it against each enabled repository is the metadata action's job, asserted by
    # `test_image_references_are_rendered_by_the_metadata_action_never_hand_joined` and,
    # for the Docker Hub leg, by
    # `test_docker_hub_enabled_with_a_well_formed_repository_reaches_the_image_job`.
    assert emitted["image-tag-value"] == version
    assert not emitted.get("image-tags"), (
        "the identity step composes image references itself; it decides the tag value "
        "and the metadata action renders it"
    )


@pytest.mark.parametrize(
    "mismatch",
    [
        {"COMMITTED_VERSION": "9.9.9"},
        {"RELEASE_TAG": "v9.9.9"},
        {"RELEASE_VERSION": "9.9.9"},
        {"TAG_COMMIT": "not-a-sha"},
        {"TAG_COMMIT": ""},
        {"RELEASE_TAG": ""},
        {"RELEASE_VERSION": ""},
        {"COMMITTED_VERSION": ""},
        {"RESOLVED_PYTHON": ""},
        {"IMAGE_REPOSITORY": ""},
    ],
)
def test_one_mismatched_identity_field_stops_the_run_before_any_publisher(
    tmp_path: Path, mismatch: dict[str, str]
) -> None:
    """One field planted per run, because a relation that only fails when everything
    disagrees is not a relation. Each of these would otherwise publish an artifact whose
    version identity nobody chose."""
    completed, _ = _run_step(
        str(_step_with_id(RELEASE_WORKFLOW, "identity")["run"]),
        _release_identity_environment(**mismatch),
        tmp_path,
    )
    assert completed.returncode != 0, f"{mismatch} was accepted as a stable identity"


def test_every_stable_consumer_reads_the_planned_identity_rather_than_its_own() -> None:
    """The plan job proves the identity once; everything downstream is handed that value.

    Scope is derived from the parsed jobs -- every job that is not the producer -- so a
    publisher added later that re-derives a version, or restates one, fails here. That
    is the scope attack: the rule is trivial, the reach is the whole point.
    """
    document = _load_workflow(RELEASE_WORKFLOW)
    jobs = _jobs(document)
    producers = {
        name
        for name, job in jobs.items()
        if any("version" in output for output in (job.get("outputs") or {}))
    }
    assert producers == {"plan"}, f"the planned identity has {len(producers)} producers"

    # Matched on the lowercased key, and over `env:` as well as `with:`. `env:` is
    # where a workflow actually carries identity into a `run:` body, so a guard blind to
    # it would pass a publisher that took `PACKAGE_VERSION` from `github.ref_name` --
    # the most natural spelling available to whoever adds one.
    identity_input = re.compile(r"(?:\A|[-_])(?:ref|sha|tags?|version)\Z")
    examined = 0
    for name, job in jobs.items():
        if name in producers:
            continue
        blocks = [job.get("with") or {}, job.get("env") or {}]
        for step in job.get("steps") or []:
            blocks += [step.get("with") or {}, step.get("env") or {}]
        for block in blocks:
            for key, value in block.items():
                key = str(key).lower()
                # `fetch-depth` and `fetch-tags` configure git's transport, not the
                # identity being published; the checkout's `ref:` beside them is the
                # identity, and it is asserted.
                if key.startswith("fetch") or not identity_input.search(key):
                    continue
                examined += 1
                assert "needs.plan.outputs." in str(value), (
                    f"release.yaml: job {name!r} takes {key!r} from {value!r} instead of "
                    f"the single planned identity (CI-AR11)"
                )
    assert examined, (
        "no downstream job consumes an identity value; nothing was examined"
    )


def test_the_run_evidence_job_blocks_on_every_publisher() -> None:
    """ADR-0011's finalizer aggregation: a destination that is not in the aggregator's
    `needs` is a destination whose failure finishes the run green and unreported.

    Both sets are derived from the parsed jobs -- publishers from capability, the
    aggregator from "depends on a publisher and ships nothing" -- so the planted
    violation is the scope attack: a new publisher absent from the aggregator's needs
    fails here without anyone remembering to edit a list.
    """
    channel_workflows = _publishing_workflows()
    assert channel_workflows, "no workflow calls the image publisher"
    for path in channel_workflows:
        document = _load_workflow(path)
        jobs = _jobs(document)
        publishers = set(_publishers(document))
        assert publishers, f"{path.name} has no publishers; this guard examined nothing"
        aggregators = {
            name
            for name in jobs
            if name not in publishers and _transitive_needs(jobs, name) & publishers
        }
        assert aggregators, (
            f"{path.name}: no job aggregates the publishers, so a failed destination is "
            f"reported nowhere (ADR-0011)"
        )
        for name in sorted(aggregators):
            missing = publishers - _transitive_needs(jobs, name)
            assert not missing, (
                f"{path.name}: job {name!r} aggregates publication outcomes but does not "
                f"depend on {sorted(missing)}; their failure would finish the run green "
                f"and unreported (ADR-0011)"
            )


def test_the_published_index_assertion_rejects_an_index_that_lost_a_platform(
    tmp_path: Path,
) -> None:
    """ADR-0008's platform assertion, run rather than read.

    `test_the_published_index_is_asserted_by_annotation_never_by_descriptor_count`
    proves the filter is spelled on the annotation. It cannot prove the comparison
    fires: with the `!=` branch deleted the annotation is still mentioned and that guard
    stays green. Here the real code judges real indexes -- including the one the story
    asks to plant, a published index carrying a single platform.
    """
    body = str(_step_with_id(PUBLISH_IMAGE_WORKFLOW, "index")["run"])
    heredoc = re.search(r"<<'PY'[^\n]*\n(.*?)\nPY\n", body, re.DOTALL)
    assert heredoc, "the index assertion is no longer an inline Python heredoc"
    script = tmp_path / "assert_index.py"
    script.write_text(heredoc.group(1), encoding="utf-8")

    def judge(manifests: Any) -> Any:
        (tmp_path / "published-index.json").write_text(
            json.dumps({"manifests": manifests}), encoding="utf-8"
        )
        return subprocess.run(
            [sys.executable, str(script)],
            cwd=tmp_path,
            env={
                "PATH": os.environ["PATH"],
                "PLATFORMS": ",".join(REQUIRED_IMAGE_PLATFORMS),
            },
            capture_output=True,
            text=True,
            check=False,
        )

    def platform(os_name: str, architecture: str) -> dict[str, Any]:
        return {"platform": {"os": os_name, "architecture": architecture}}

    def attestation(architecture: str) -> dict[str, Any]:
        entry = platform("unknown", architecture)
        entry["annotations"] = {
            "vnd.docker.reference.type": "attestation-manifest",
        }
        return entry

    published = [
        platform("linux", "amd64"),
        platform("linux", "arm64"),
        attestation("unknown"),
        attestation("unknown"),
    ]
    completed = judge(published)
    assert completed.returncode == 0, completed.stderr
    assert "platforms=linux/amd64,linux/arm64" in completed.stdout
    # Four descriptors, not two -- reported, never asserted on (ADR-0008 as amended).
    assert "descriptors=4" in completed.stdout

    # The planted violation: a published index carrying one platform.
    completed = judge([platform("linux", "amd64"), attestation("unknown")])
    assert completed.returncode != 0, "an index missing a platform was accepted"

    # And the filter is load-bearing: an attestation manifest must not be counted as the
    # platform it is annotated for.
    completed = judge(
        [
            platform("linux", "amd64"),
            {
                "platform": {"os": "linux", "architecture": "arm64"},
                "annotations": {
                    "vnd.docker.reference.type": "attestation-manifest",
                },
            },
        ]
    )
    assert completed.returncode != 0, "an attestation manifest was read as a platform"

    completed = judge("not-an-index")
    assert completed.returncode != 0, "a single-platform reference was accepted"


def test_the_release_guard_peels_the_pushed_object_before_comparing_it(
    tagged_repository: Path,
) -> None:
    """A push event reports the ref's new object id, and an annotated tag's ref points
    at the tag object, not at the commit.

    This channel accepts *only* annotated tags, so a comparison that never peels is a
    channel that never publishes -- failing closed on the one path it has, and doing it
    for the first time on a release day. `git rev-parse HEAD` after checking out a tag
    object is the commit, so the two values differ by construction.
    """
    tag_object = _git(tagged_repository, "rev-parse", "v1.2.3")
    commit = _git(tagged_repository, "rev-parse", "v1.2.3^{commit}")
    assert tag_object != commit, "v1.2.3 is not annotated; this test proves nothing"

    completed, emitted = _run_step(
        str(_step_with_id(RELEASE_WORKFLOW, "tag")["run"]),
        {
            "DEFAULT_BRANCH_REF": "main",
            "EVENT_REF": "refs/tags/v1.2.3",
            "EVENT_OBJECT": tag_object,
        },
        tagged_repository,
    )
    assert completed.returncode == 0, completed.stderr
    # And the peeled commit is what flows downstream: every checkout, the verifier and
    # every bundle revalidation are handed this, never the tag object.
    assert emitted["tag-commit"] == commit


def _release_destinations(**environment: str) -> tuple[Any, dict[str, str]]:
    defaults = {
        "DOCKERHUB_ORG": "",
        "DOCKERHUB_TOGGLE": "",
        "FORGE": "github",
        # The namespace is the knob; the name follows the built image, so the harness
        # supplies it the way the forge coordinate does rather than letting a test invent
        # a name Docker Hub and the forge registry could disagree on.
        "FORGE_OWNER": "ravensorb",
        "IMAGE_NAME": "traefik-certificate-exporter",
        "ATTESTATION_SUPPORTED": "true",
        "PACKAGE_INDEX_SUPPORTED": "false",
        "PYPI_TOGGLE": "",
    }
    defaults.update(environment)
    return _run_step(
        str(_step_with_id(RELEASE_WORKFLOW, "destinations")["run"]),
        defaults,
        Path(tempfile.mkdtemp()),
    )


def test_the_enabled_destination_set_distinguishes_disabled_from_unsupported() -> None:
    """ADR-0011 section 2, executed rather than described.

    Every decision this story takes about destinations lives in one step, and the
    distinction it exists to preserve -- an operator turned it off, versus the host
    never had it -- is invisible when it regresses: both spellings produce a run that
    publishes nothing there and reports success.
    """
    completed, emitted = _release_destinations()
    assert completed.returncode == 0, completed.stderr
    destinations = json.loads(emitted["enabled-destinations"])
    assert destinations["image-forge"] == "enabled", "the channel is not a toggle"
    assert destinations["image-dockerhub"] == "disabled"
    assert destinations["package-pypi"] == "disabled"
    # GitHub has no forge Python index, and no toggle can create one.
    assert destinations["package-forge"] == "unsupported"
    assert emitted["dockerhub-repository"] == ""
    assert "package-testpypi" not in destinations, "TestPyPI is development-only"

    completed, emitted = _release_destinations(PACKAGE_INDEX_SUPPORTED="true")
    assert completed.returncode == 0, completed.stderr
    assert json.loads(emitted["enabled-destinations"])["package-forge"] == "enabled"

    # Trusted publishing needs a GitHub OIDC identity; on Gitea there is none, and the
    # toggle cannot conjure one. `unsupported`, never `disabled`, and never a failed job.
    completed, emitted = _release_destinations(FORGE="gitea", PYPI_TOGGLE="true")
    assert completed.returncode == 0, completed.stderr
    assert json.loads(emitted["enabled-destinations"])["package-pypi"] == "unsupported"

    completed, emitted = _release_destinations(PYPI_TOGGLE="true")
    assert completed.returncode == 0, completed.stderr
    assert json.loads(emitted["enabled-destinations"])["package-pypi"] == "enabled"


@pytest.mark.parametrize(
    "toggle", ["yes", "1", "True", "enabled", "TRUE", " true", "on"]
)
def test_a_publication_toggle_is_never_coerced(toggle: str) -> None:
    """`true`, `false` or absent. Anything else fails the plan job, because the
    alternative is `PUBLISH_PACKAGE_PYPI=yes` reading as "off" for a year."""
    completed, _ = _release_destinations(PYPI_TOGGLE=toggle)
    assert completed.returncode != 0, f"PYPI_TOGGLE={toggle!r} was coerced"
    completed, _ = _release_destinations(DOCKERHUB_TOGGLE=toggle)
    assert completed.returncode != 0, f"DOCKERHUB_TOGGLE={toggle!r} was coerced"


@pytest.mark.parametrize(
    "namespace",
    # The empty string is deliberately ABSENT: it now means "derive from the forge owner"
    # and is the documented default, covered by the test below. These are the values that
    # are supplied and unusable.
    ["Foo", "acme/exporter", "docker.io/acme", "acme/", "/x", "ac me", "-acme"],
)
def test_docker_hub_is_never_enabled_without_a_namespace_to_publish_to(
    namespace: str,
) -> None:
    """An enabled toggle with an unusable namespace would push an *immutable* tag
    somewhere nobody chose, so it fails closed exactly as an unrecognised forge does.

    Only the namespace is validated now, because only the namespace is supplied. The
    image name comes from the forge coordinate, so it cannot be malformed independently
    -- and a namespace carrying a slash is rejected rather than silently composing a
    three-segment reference."""
    completed, _ = _release_destinations(
        DOCKERHUB_TOGGLE="true", DOCKERHUB_ORG=namespace
    )
    assert completed.returncode != 0, f"DOCKERHUB_ORG={namespace!r} was accepted"


def test_docker_hub_enabled_with_a_well_formed_repository_reaches_the_image_job() -> (
    None
):
    # The namespace is the only knob. The image name follows the built image, so no
    # override can make Docker Hub ship a different name from the forge registry.
    completed, emitted = _release_destinations(
        DOCKERHUB_TOGGLE="true", DOCKERHUB_ORG="acme"
    )
    assert completed.returncode == 0, completed.stderr
    assert json.loads(emitted["enabled-destinations"])["image-dockerhub"] == "enabled"
    assert emitted["dockerhub-repository"] == "acme/traefik-certificate-exporter"

    # With no override it derives from the forge owner rather than failing closed, which
    # is what made this destination unusable until an operator set a variable nobody knew
    # about. Fork-correct: a fork resolves its own namespace.
    completed, derived = _release_destinations(DOCKERHUB_TOGGLE="true")
    assert completed.returncode == 0, completed.stderr
    assert derived["dockerhub-repository"] == "ravensorb/traefik-certificate-exporter"

    # And the value reaches the reference renderer as a second `images:` entry. Without
    # this the destination is "enabled" and no Docker Hub tag is ever produced for it --
    # a disabled publication that reports itself enabled, which is the failure the
    # enabled set exists to make visible.
    jobs = _jobs(_load_workflow(RELEASE_WORKFLOW))
    plan = jobs["plan"]
    destinations_step = _producing_step(
        RELEASE_WORKFLOW, "plan", plan, "enabled-destinations"
    )["id"]
    images = str(
        (
            _producing_step(RELEASE_WORKFLOW, "plan", plan, "image-tags").get("with")
            or {}
        ).get("images", "")
    )
    assert f"steps.{destinations_step}.outputs.dockerhub-repository" in images, (
        "release.yaml: the accepted Docker Hub repository never reaches `images:`, so "
        "the enabled destination receives no tag"
    )
    assert "docker.io/" in images, (
        "release.yaml: the Docker Hub repository is not qualified with its registry"
    )


def test_optional_destination_credentials_are_gated_on_the_enabled_set() -> None:
    """ "Disabled destinations receive no credentials **or requests**."

    The requests half is publish-image.yaml's permitted-authority check. This is the
    credentials half: a secret handed to a called workflow is materialised in its
    context whether or not the destination is enabled.

    Which credentials are optional is read from the CALLEE's own `workflow_call.secrets`
    declaration -- `required: false` is exactly "this destination may be absent" -- so a
    new optional destination is covered the day the reusable workflow declares it, with
    no list here to keep.
    """
    examined = 0
    for path in _publishing_workflows():
        for job_name, job in _jobs(_load_workflow(path)).items():
            called = str(job.get("uses", ""))
            if not called.startswith("./.github/workflows/"):
                continue
            callee = _load_workflow(PROJECT_ROOT / called.removeprefix("./"))
            declared = (callee.get("on") or {}).get("workflow_call") or {}
            optional = {
                name
                for name, specification in (declared.get("secrets") or {}).items()
                if str((specification or {}).get("required", "false")).lower() != "true"
            }
            supplied = job.get("secrets")
            if not isinstance(supplied, dict):
                continue
            for name in sorted(optional & set(supplied)):
                examined += 1
                assert "enabled-destinations" in str(supplied[name]), (
                    f"{path.name}: job {job_name!r} hands {name!r} to {called} "
                    f"unconditionally. A destination the plan job reported disabled "
                    f"receives no credentials (CI-AR24, ADR-0011)."
                )
    assert examined, "no optional destination credential was examined"


def test_channel_workflows_surface_the_published_digest_and_platforms() -> None:
    """The third clause of prep finding P1, which nothing else asserts.

    `test_channel_workflows_consume_image_inspection_rather_than_performing_it` proves
    the registry read is not in the channel workflow and is in the image publisher. It
    says nothing about the result being consumed -- so deleting the digest and platform
    rows from the evidence table satisfies every other guard and CI-AR41's evidence
    disappears silently.
    """
    examined = 0
    for path in _image_channel_workflows():
        document = _load_workflow(path)
        body = json.dumps(document)
        image_jobs = [
            name
            for name, job in _jobs(document).items()
            if job.get("uses") == PUBLISH_IMAGE_REFERENCE
        ]
        assert image_jobs, f"{path.name}: no image publisher call"
        for name in image_jobs:
            for output in ("digest", "platforms"):
                examined += 1
                assert f"needs.{name}.outputs.{output}" in body, (
                    f"{path.name}: the published {output} is never surfaced. One digest "
                    f"and both inspected platforms are this channel's evidence, "
                    f"consumed from the image publisher's outputs (CI-AR41, P1)."
                )
    assert examined, "no channel workflow consumes the image publisher's outputs"
