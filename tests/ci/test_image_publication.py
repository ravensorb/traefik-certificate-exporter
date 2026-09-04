"""The development channel, and the one image publisher both channels call.

BL-E008-010 phase 3. Where a container image gets its coordinates, its tag list and its
credentials, and what a publisher is allowed to push once it has them. Every guard here was
proven by planting the violation it forbids -- the rule AND the scope.

The tag guards run the real `run:` bodies against a fixture rather than reading them, which
is what caught a publisher that re-rendered its tag list after the membership check.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import pytest

from tests.ci.support import (
    APPROVED_ALIAS_ACTION,
    APPROVED_RELEASE_ACTION,
    DEV_WORKFLOW,
    GOVERNED_DEFINITIONS,
    PROJECT_ROOT,
    PUBLISH_IMAGE_REFERENCE,
    PUBLISH_IMAGE_WORKFLOW,
    REGISTRY_READ_COMMANDS,
    REQUIRED_IMAGE_PLATFORMS,
    STABLE_RECHECK_MARKER,
    TAG_MEMBERSHIP_MARKER,
    VERIFIER_REFERENCE,
    WORKFLOWS,
    _declared_events,
    _image_channel_workflows,
    _is_publishing_step,
    _jobs,
    _load_fixture,
    _load_workflow,
    _producing_step,
    _publishers,
    _publishing_workflows,
    _run_step,
    _steps,
    _transitive_needs,
    _trigger_surface,
    _uncommented,
)

# "How many descriptors does the index carry" in every spelling that reaches for a
# number. ATTESTATIONS=[] does not disable attestations, so the answer is four today,
# two under `type=provenance,disabled=true`, and four again with `type=sbom` -- which is
# why the count is never the thing to assert.
DESCRIPTOR_COUNT_ASSERTIONS = (
    r"len\(\s*[^()]*manifests[^()]*\)\s*(?:==|!=|<=|>=|<|>)",
    r"(?:==|!=|<=|>=|<|>)\s*len\(\s*[^()]*manifests",
    r"\.manifests\s*\|\s*length",
)


# The coordinates every publishing workflow addresses a forge with. Used to LOCATE the
# derivation from what a job emits rather than from a filename, so a third channel
# workflow that derives its own registry is examined the day it lands.
FORGE_COORDINATE_OUTPUTS = frozenset(
    {
        "forge",
        "registry",
        "image-repository",
        "package-index-supported",
        "package-index-url",
    }
)


# The fork of docker/metadata-action with the GitHub API dependency removed, so the same
# YAML renders the same references on GitHub and on Gitea (docs/guidelines.md section 6).
IMAGE_METADATA_ACTION = "LiquidLogicLabs/git-action-docker-metadata@v6"


def test_the_publishing_scope_is_derived_from_publishing_not_from_images() -> None:
    """The scope attack for `_publishing_workflows`, as a classification proof.

    The seven destination-agnostic guards used to key on "calls publish-image.yaml".
    A push-triggered workflow holding one PyPI job satisfies none of their rules and
    was examined by none of them, because it ships no image. Planted on disk it now
    fails nine guards; here the classification itself is pinned, so the derivation
    cannot quietly narrow again.
    """
    assert set(_image_channel_workflows()) <= set(_publishing_workflows()), (
        "a workflow that publishes an image must also count as publishing"
    )
    nightly = {
        "on": {"push": {"branches": ["nightly"]}},
        "jobs": {
            "publish-package-pypi": {
                "runs-on": "ubuntu-24.04",
                "permissions": {"id-token": "write"},
                "steps": [{"uses": "pypa/gh-action-pypi-publish@" + "0" * 40}],
            }
        },
    }
    assert _trigger_surface(nightly), "a push-triggered workflow owns an event"
    assert _publishers(nightly), "an `id-token: write` job can ship"
    assert not any(
        job.get("uses") == PUBLISH_IMAGE_REFERENCE for job in _jobs(nightly).values()
    ), "and it ships no image -- which is exactly how it escaped the seven guards"


def test_the_development_channel_owns_protected_default_branch_pushes() -> None:
    """BL-E008-001: since the legacy publish path was deleted nothing reacted to `push`.

    `test_any_push_triggered_workflow_verifies_before_it_ships` asserts the conditional
    invariant and passes vacuously with no push workflow at all. This one asserts the
    workflow exists and is shaped as ADR-0011 requires, so deleting dev.yaml reopens the
    finding loudly instead of turning that guard vacuous again.
    """
    document = _load_workflow(DEV_WORKFLOW)
    triggers = document["on"]
    assert set(triggers) == {"push"}
    assert triggers["push"] == {"branches": ["main"]}
    assert document["permissions"] == {"contents": "read"}
    # Stale candidates are superseded, not raced (definition of done).
    assert document["concurrency"]["cancel-in-progress"] == "true"

    # Exactly one verifier call for the event SHA. Counted from the parsed document, so
    # a second call added anywhere in the file -- another job, another spelling of the
    # same `uses:` -- fails here.
    verifier_calls = [
        name
        for name, job in _jobs(document).items()
        if job.get("uses") == VERIFIER_REFERENCE
    ]
    assert verifier_calls == ["verify"]
    verify = _jobs(document)["verify"]
    assert verify["with"]["channel"] == "dev"
    assert verify["with"]["source-sha"] == "${{ needs.plan.outputs.source-sha }}"


def test_every_channel_checkout_keeps_full_history_and_tags() -> None:
    """The development version is a first-parent commit count, suppression peels tag
    objects, and the stable guard peels one tag and asks git whether its commit is
    reachable from the protected default branch. A shallow checkout derives `.dev1` for
    every commit, sees no tags at all, and has no `origin/main` to be reachable from --
    and it fails silently, publishing a plausible wrong version.

    Scope is every checkout of every channel workflow, derived from the parsed document
    and from who calls the image publisher, so neither a job added later nor a channel
    added later can quietly take a shallow one.
    """
    channel_workflows = _publishing_workflows()
    assert channel_workflows, "no workflow calls the image publisher"
    checkouts = 0
    for path in channel_workflows:
        for job_name, job in _jobs(_load_workflow(path)).items():
            for step in job.get("steps", []) or []:
                if not str(step.get("uses", "")).startswith("actions/checkout@"):
                    continue
                checkouts += 1
                options = step.get("with") or {}
                assert options.get("fetch-depth") == "0", (
                    f"{path.name}: {job_name}: shallow checkout"
                )
                assert options.get("fetch-tags") == "true", (
                    f"{path.name}: {job_name}: no tags fetched"
                )
                assert options.get("persist-credentials") == "false", (
                    f"{path.name}: {job_name}"
                )
    assert checkouts, (
        "no channel workflow checks anything out; this guard examined nothing"
    )


def test_every_development_publisher_is_gated_on_stable_tag_suppression() -> None:
    """An exact stable tag on the pushed commit suppresses development publication.

    Both halves are asserted: the suppression job must be a transitive dependency of
    every publisher, AND each publisher's own `if:` must read its conclusion. `needs:`
    alone is not a gate -- a job that depends on the guard and ignores its output
    publishes anyway.

    The publisher set is derived from capability, so a new publisher that forgets the
    gate fails here rather than being silently ungoverned (the scope attack).
    """
    document = _load_workflow(DEV_WORKFLOW)
    jobs = _jobs(document)
    suppressors = {
        name for name, job in jobs.items() if "suppressed" in (job.get("outputs") or {})
    }
    assert suppressors, "no job emits a suppression conclusion"

    publishers = _publishers(document)
    assert publishers, "dev.yaml has no publishers; this guard examined nothing"
    for name, job in publishers.items():
        needs = _transitive_needs(jobs, name)
        assert suppressors <= needs, (
            f"dev.yaml: publisher {name!r} does not depend on the suppression job"
        )
        condition = str(job.get("if", "")).replace(" ", "")
        assert any(
            f"needs.{suppressor}.outputs.suppressed" in condition
            for suppressor in suppressors
        ), (
            f"dev.yaml: publisher {name!r} depends on the suppression job but ignores "
            f"its conclusion, so a stable-tagged commit still publishes"
        )


def _coordinate_derivations() -> list[tuple[Path, str, dict[str, Any]]]:
    """Every job that derives forge coordinates, and the one step it derives them in.

    Scope is derived from what a job EMITS, never from a list of filenames: a channel
    workflow added later that resolves its own registry is examined here without an edit,
    and a job that split the derivation across two steps fails rather than being examined
    in half.
    """
    located: list[tuple[Path, str, dict[str, Any]]] = []
    for path in sorted(WORKFLOWS.glob("*.yaml")):
        for job_name, job in _jobs(_load_workflow(path)).items():
            outputs = job.get("outputs") or {}
            emitted = FORGE_COORDINATE_OUTPUTS & set(outputs)
            if not emitted:
                continue
            # Not every coordinate is exposed as a job output -- `package-index-supported`
            # is consumed inside the job -- so the completeness of the set is asserted by
            # EXECUTING the step below, where a missing coordinate cannot hide.
            steps = {
                _producing_step(path, job_name, job, name)["id"] for name in emitted
            }
            assert len(steps) == 1, (
                f"{path.name}: job {job_name!r} derives its forge coordinates in "
                f"{sorted(steps)}; there is one derivation or there are two answers"
            )
            # Resolved through one of the names this job actually emits. Hard-coding
            # `"registry"` meant a channel emitting, say, `image-repository` and
            # `package-index-url` but not `registry` raised a bare KeyError from inside
            # `_producing_step` -- which reads as a broken test rather than as a caught
            # violation, the failure mode `_step_with_id` exists to avoid.
            assert "registry" in emitted, (
                f"{path.name}: job {job_name!r} derives forge coordinates but emits no "
                f"`registry`; it emits {sorted(emitted)}. Every channel resolves the "
                f"registry from action context (CI-AR6)."
            )
            located.append(
                (path, job_name, _producing_step(path, job_name, job, "registry"))
            )
    return located


def test_forge_coordinates_are_derived_from_action_context_and_fail_closed(
    tmp_path: Path,
) -> None:
    """CI-AR6, asserted by RUNNING the derivation rather than by reading it.

    Every coordinate is a projection of `github.server_url` and `github.repository`, so
    there is no operator-supplied value to validate -- the composite action and the
    ``scripts/forge_coordinates.py`` module it called were 535 lines producing six
    template expressions, and `FORGE_REGISTRY` is retired with them.

    The one behaviour worth keeping is the fail-closed branch: an unrecognised forge must
    stop the run rather than guess a registry, because a guess publishes an immutable
    artifact somewhere nobody chose. A textual check ("the word `exit` appears") passes
    with that branch deleted, so each case below is executed.
    """
    derivations = _coordinate_derivations()
    assert derivations, "no workflow derives forge coordinates; nothing was examined"
    for path, job_name, step in derivations:
        body = str(step["run"])
        where = f"{path.name}: job {job_name!r}"

        # https, before the value is used for anything. Every coordinate this step emits
        # ends up carrying a credential: the package index URL takes FORGE_PACKAGE_TOKEN,
        # and release.yaml reassembles the same server URL into
        # `https://x-access-token:<contents-write-token>@host/...`. Over plain HTTP both
        # are cleartext Basic auth. Latent on GitHub, where `github.server_url` is always
        # https; live the moment E009 reaches a self-hosted Gitea, which is the
        # deployment shape where an operator can choose http.
        #
        # Each case below is one the derivation would otherwise ACCEPT, so only the
        # scheme check can reject it. `http://gitea.internal` would not do: it reaches
        # the fail-closed branch on its own and the assertion would pass with the scheme
        # check deleted -- which it did, on the first draft of this test.
        for insecure, environment in (
            ("http://github.com", {}),
            ("ftp://github.com", {}),
            ("github.com", {}),
            ("http://gitea.internal", {"GITEA_ACTIONS": "true"}),
        ):
            completed, _ = _run_step(
                body,
                {
                    "FORGE_SERVER_URL": insecure,
                    "FORGE_REPOSITORY": "Owner/Name",
                    **environment,
                },
                tmp_path,
            )
            assert completed.returncode != 0, (
                f"{where}: accepted {insecure!r}, so a publication credential would "
                f"cross the network in cleartext"
            )

        # GitHub: ghcr.io, no forge Python index, and a lowercased repository -- a forge
        # owner need not be lowercase, and a registry reference must be.
        completed, emitted = _run_step(
            body,
            {
                "FORGE_SERVER_URL": "https://github.com",
                "FORGE_REPOSITORY": "Owner/Name",
            },
            tmp_path,
        )
        assert completed.returncode == 0, f"{where}: {completed.stderr}"
        assert emitted == {
            "forge": "github",
            "registry": "ghcr.io",
            "image-name": "name",
            "image-repository": "ghcr.io/owner/name",
            "package-index-supported": "false",
            "package-index-url": "",
            # GitHub has an attestation store; Gitea does not. A capability of the host,
            # emitted here so no publisher ever compares a forge name (ADR-0011 s2).
            "attestation-supported": "true",
        }, where

        # Gitea: the registry is the forge's own authority, port included, and the
        # package index is a capability of the host rather than a toggle.
        completed, emitted = _run_step(
            body,
            {
                "GITEA_ACTIONS": "true",
                "FORGE_SERVER_URL": "https://git.example.com:3000",
                "FORGE_REPOSITORY": "Owner/Name",
            },
            tmp_path,
        )
        assert completed.returncode == 0, f"{where}: {completed.stderr}"
        assert emitted == {
            "forge": "gitea",
            "registry": "git.example.com:3000",
            "image-name": "name",
            "image-repository": "git.example.com:3000/owner/name",
            "package-index-supported": "true",
            "package-index-url": "https://git.example.com:3000/api/packages/owner/pypi",
            # The mirror image of the GitHub case above: each forge supports one of the
            # two, and neither is a toggle an operator can set.
            "attestation-supported": "false",
        }, where

        # Fail closed. `github.enterprise.example` ends with neither the GitHub host nor
        # a Gitea flag, and a suffix or substring comparison accepts the first two.
        for unknown in (
            "https://github.enterprise.example",
            "https://notgithub.com",
            "https://github.com.evil.example",
            "https://git.example.com",
        ):
            completed, emitted = _run_step(
                body,
                {"FORGE_SERVER_URL": unknown, "FORGE_REPOSITORY": "owner/name"},
                tmp_path,
            )
            assert completed.returncode != 0, (
                f"{where}: {unknown} was accepted as a known forge, so a registry was "
                f"guessed for it"
            )
            assert not emitted, f"{where}: {unknown} emitted {emitted} before failing"

        # `GITEA_ACTIONS` is Gitea's flag, and only its exact value means Gitea. Anything
        # else on an unrecognised host still fails closed.
        for flag in ("false", "TRUE ", "1", ""):
            completed, _ = _run_step(
                body,
                {
                    "GITEA_ACTIONS": flag,
                    "FORGE_SERVER_URL": "https://git.example.com",
                    "FORGE_REPOSITORY": "owner/name",
                },
                tmp_path,
            )
            assert completed.returncode != 0, (
                f"{where}: GITEA_ACTIONS={flag!r} was read as a Gitea runner"
            )


def test_image_references_are_rendered_by_the_metadata_action_never_hand_joined() -> (
    None
):
    """The plan job proves the tag VALUE; joining it to each enabled repository is the
    metadata action's job.

    `git-action-docker-metadata` is a fork of `docker/metadata-action` with the GitHub
    API dependency removed, so it renders the same references on GitHub and on Gitea. It
    has no registry input and derives no registry: `images:` is handed the fully
    qualified repository the forge coordinates already derived.

    Scope is every job emitting `image-tags`, and the step examined is resolved through
    that output's own expression -- so a channel that goes back to composing references
    in a `run:` body fails here because the producing step has no `uses:` at all. That is
    the scope attack: the rule is trivial, its reach is the point.
    """
    examined = 0
    for path in sorted(WORKFLOWS.glob("*.yaml")):
        for job_name, job in _jobs(_load_workflow(path)).items():
            if "image-tags" not in (job.get("outputs") or {}):
                continue
            examined += 1
            where = f"{path.name}: job {job_name!r}"
            step = _producing_step(path, job_name, job, "image-tags")
            assert step.get("uses") == IMAGE_METADATA_ACTION, (
                f"{where} composes image references itself instead of delegating to "
                f"{IMAGE_METADATA_ACTION}"
            )
            inputs = step.get("with") or {}

            # `images:` is the derived repository, never a registry the step names.
            repository_step = _producing_step(path, job_name, job, "image-repository")[
                "id"
            ]
            images = str(inputs.get("images", ""))
            assert f"steps.{repository_step}.outputs.image-repository" in images, (
                f"{where}: the metadata action is not handed the derived image "
                f"repository as `images:` (got {images!r})"
            )

            # The rendered value is the proven identity, resolved through the job's own
            # version producer rather than a hand-kept step name.
            identity_step = _producing_step(path, job_name, job, "package-version")[
                "id"
            ]
            tags = str(inputs.get("tags", ""))
            assert tags.startswith("type=raw,value="), (
                f"{where}: the metadata action derives the tag itself ({tags!r}); the "
                f"identity step decides it and this step renders it"
            )
            assert f"steps.{identity_step}.outputs.image-tag-value" in tags, (
                f"{where}: the rendered tag {tags!r} is not the identity the plan job "
                f"proved, so the publication would carry a second version authority"
            )

            # `latest=auto` is the action's default, and it adds a mutable alias on a
            # tag push. Every alias belongs to the finalizer story.
            assert "latest=false" in str(inputs.get("flavor", "")), (
                f"{where}: the metadata action may move `latest`; aliases belong to the "
                f"finalizer, not to a publisher"
            )
    assert examined, "no job emits an image tag set; nothing was examined"


def test_the_image_fan_out_is_one_buildx_invocation_carrying_every_tag() -> None:
    """CI-AR39: one channel-run image job, one multi-platform Buildx invocation, every
    destination tagged inside it. A second `bake` per registry produces a *different*
    image for each destination, which is the defect this forbids -- and it is the
    cheapest thing to reach for when a second registry is added.

    Counted across every job of the file, so a per-registry build added to a new job
    fails here too.
    """
    # Every reusable workflow that builds an image, not the one file that does today.
    # Counting inside a literal path meant a second reusable publisher -- a copy with
    # its own `bake`, correctly wired -- carried a second build that nothing examined.
    building = {
        path.name: [
            step
            for step in _steps(_load_workflow(path))
            if re.search(r"buildx\s+(?:bake|build)\b", str(step.get("run", "")))
        ]
        for path in sorted(WORKFLOWS.glob("*.yaml"))
        # Reusable AND publishing. The verifier builds an image too -- that is its
        # smoke test -- and it holds no credential and pushes nothing, so it is not
        # what CI-AR39 is counting.
        if "workflow_call" in _declared_events(_load_workflow(path))
        and _publishers(_load_workflow(path))
    }
    building = {name: builds for name, builds in building.items() if builds}
    assert building, "no reusable workflow builds an image; this guard examined nothing"
    total = sum(len(builds) for builds in building.values())
    assert total == 1, (
        f"{total} image builds across {sorted(building)}; CI-AR39 allows one per "
        f"channel run, so every destination is tagged inside the same invocation"
    )
    # And nowhere else. A per-registry "just push it to Docker Hub too" step added to a
    # publishing workflow is the cheapest way to break this rule, and scoping the count
    # to one hand-named file would not see it.
    #
    # The scope is every publishing workflow, not every caller of the image publisher.
    # Keying it on "calls publish-image.yaml" was circular: a workflow that built and
    # pushed an image inline was, by that derivation, not a channel workflow, so the
    # one rule forbidding exactly that could not see it.
    for path in _publishing_workflows():
        for step in _steps(_load_workflow(path)):
            assert not re.search(
                r"buildx\s+(?:bake|build)\b", str(step.get("run", ""))
            ), (
                f"{path.name} builds an image itself. One channel run, one Buildx "
                f"invocation, every destination tagged inside it (CI-AR39)."
            )
        # A caller may pass a narrower platform list and satisfy every other guard while
        # shipping a single-platform development image.
        for job_name, job in _jobs(_load_workflow(path)).items():
            if job.get("uses") != PUBLISH_IMAGE_REFERENCE:
                continue
            supplied = (job.get("with") or {}).get("platforms")
            if supplied is None:
                continue
            assert set(str(supplied).split(",")) >= set(REQUIRED_IMAGE_PLATFORMS), (
                f"{path.name}: job {job_name!r} narrows the published platform set to "
                f"{supplied!r}; CI-AR39 requires {list(REQUIRED_IMAGE_PLATFORMS)}"
            )
    # The one build, reached through the derived set rather than a named file.
    builder, builds = next(iter(building.items()))
    command = str(builds[0]["run"])
    assert "--push" in command
    environment = builds[0].get("env") or {}
    assert "TAGS" in environment and "PLATFORMS" in environment, (
        f"{builder}: the single invocation must receive every tag and every platform as "
        f"bake variables; a tag applied outside it is a second build"
    )
    # `--push` states the intent and this asserts the mechanism, because the first CI
    # run showed the two can disagree. docker-bake.hcl's target sets `output = OUTPUTS`,
    # defaulting to `type=docker` for local single-platform builds, and that attribute
    # beat `--push`: the run died on `docker exporter does not currently support
    # exporting manifest lists`. The docker exporter cannot hold a multi-platform index,
    # so the push was impossible -- while this guard, asserting only that the command
    # said `--push`, was satisfied. The rule held and the outcome did not.
    exporter = str(environment.get("OUTPUTS", ""))
    assert "type=registry" in exporter, (
        f"{builder}: the multi-platform build exports {exporter!r}. Only the registry "
        f"exporter can hold a manifest list -- `--push` alone does not override the "
        f"bake target's own `output`."
    )

    triggers = _load_workflow(WORKFLOWS / builder)["on"]
    platforms = triggers["workflow_call"]["inputs"]["platforms"]["default"]
    assert set(platforms.split(",")) == set(REQUIRED_IMAGE_PLATFORMS)


def test_the_published_index_is_asserted_by_annotation_never_by_descriptor_count() -> (
    None
):
    """ADR-0008 as amended: `ATTESTATIONS = []` does NOT disable attestations.

    BuildKit emits SLSA provenance `mode=min` regardless, so the index carries four
    descriptors -- two platforms plus two attestation manifests. Adding `type=sbom`
    keeps it at four; only `type=provenance,disabled=true` drops it to two. A count
    assertion is wrong in three directions, so the filter keys on the authoritative
    annotation instead.
    """
    document = _load_workflow(PUBLISH_IMAGE_WORKFLOW)
    commands = [str(step.get("run", "")) for step in _steps(document)]
    assertions = [
        command
        for command in commands
        if "vnd.docker.reference.type" in command and "attestation-manifest" in command
    ]
    assert assertions, (
        "the published index is never filtered on vnd.docker.reference.type, so the "
        "platform assertion is reading attestation manifests as platforms"
    )
    # The prohibition's reach, not only its rule. `len(manifests) == 2` is one spelling;
    # the likelier one is `len(index["manifests"]) != 2`, and `jq '.manifests | length'`
    # is the same assertion in shell. Scope is every governed definition plus the helper
    # scripts, because F9 pushes non-trivial logic out of `run:` blocks -- so that is
    # exactly where a count assertion would come to rest.
    counted = 0
    for path in [
        *GOVERNED_DEFINITIONS,
        *sorted((PROJECT_ROOT / "scripts").glob("*.py")),
    ]:
        source = path.read_text(encoding="utf-8")
        counted += 1
        for pattern in DESCRIPTOR_COUNT_ASSERTIONS:
            assert not re.search(pattern, source), (
                f"{path.name}: the published index is asserted by descriptor count; the "
                f"count is 4, not 2, and changes with the attestation set (ADR-0008)"
            )
    assert counted, "no definition was examined for a descriptor-count assertion"
    # The expected set is the same platform list the single build was given, not a
    # second literal: two hand-kept copies drift, and the copy nobody updated is the one
    # still reporting success.
    inspecting = [
        step
        for step in _steps(document)
        if "vnd.docker.reference.type" in str(step.get("run", ""))
    ]
    for step in inspecting:
        environment = step.get("env") or {}
        assert "PLATFORMS" in environment, (
            "the platform assertion must compare against the platform list the build "
            "was given, not a literal restated beside it"
        )


def test_channel_workflows_consume_image_inspection_rather_than_performing_it() -> None:
    """Prep finding P1, enforced before the collision can happen.

    `test_alias_ordering_is_decided_from_git_never_from_a_registry` forbids a registry
    read in EVERY job of a file that moves an alias. Story E008-S01-003 puts an alias
    finalizer into dev.yaml and release.yaml; from that moment the `imagetools inspect`
    this epic mandates would fail that guard inside the same file. The resolution is
    placement: every published-image read lives in publish-image.yaml, which moves no
    alias, and the callers consume its `digest`/`platforms` outputs.

    Waiting for story 003 to discover this as a red test is the failure mode this guard
    removes. Scope is derived: any workflow that calls the image publisher is a channel
    workflow, so release.yaml is covered the day it lands.
    """
    channel_workflows = _image_channel_workflows()
    assert channel_workflows, "no workflow calls the image publisher"
    for path in channel_workflows:
        for job_name, job in _jobs(_load_workflow(path)).items():
            for step in job.get("steps", []) or []:
                command = str(step.get("run", ""))
                for probe in REGISTRY_READ_COMMANDS:
                    assert not re.search(probe, command), (
                        f"{path.name}: job {job_name!r} reads a registry. Story 003 adds "
                        f"an alias finalizer to this file, and that read must live in "
                        f"publish-image.yaml with its result consumed as an output (P1)."
                    )
    # And the reads really are somewhere: a guard that only forbids would pass over a
    # publisher that inspects nothing at all, losing CI-AR39's platform evidence.
    published = [
        _uncommented(str(step.get("run", "")))
        for step in _steps(_load_workflow(PUBLISH_IMAGE_WORKFLOW))
    ]
    assert any(
        re.search(probe, command)
        for probe in REGISTRY_READ_COMMANDS
        for command in published
    ), "publish-image.yaml inspects nothing, so CI-AR39's platform evidence is missing"


# The credential every job on a forge is issued automatically, whose authority is set
# per job by `permissions:` rather than by which secret it was handed. It is excluded
# from the cross-destination comparison below for that reason -- two jobs each holding
# it under different `permissions:` scopes is the least-privilege pattern, not a shared
# destination credential -- and the exclusion is compensated: the same guard asserts no
# package publisher may take `packages: write`, which is the only way the automatic
# token becomes a registry credential.
AMBIENT_FORGE_TOKEN = "GITHUB_TOKEN"


# What a job addresses, derived from what it actually does rather than from its name.
# A job may belong to exactly one, which is itself asserted below.
DESTINATION_CLASSES: dict[str, tuple[str, ...]] = {
    # A container registry: the reusable image publisher, a registry login, or any
    # tool that writes to one.
    "image": (
        re.escape(PUBLISH_IMAGE_REFERENCE),
        r"docker/login-action",
        r"docker/setup-buildx-action",
        r"docker/build-push-action",
        r"buildx\s+(?:bake|build|imagetools)",
        r"\bdocker\s+(?:push|tag)\b",
        r"\bcrane\s+(?:copy|tag|push|append)\b",
        r"\bskopeo\s+copy\b",
        r"\bregctl\s+(?:index|image|artifact)\s+(?:copy|put)\b",
    ),
    # A Python package index, by token or by trusted publishing.
    "package": (
        r"pypa/gh-action-pypi-publish",
        r'"id-token":\s*"write"',
        r"\btwine\s+upload\b",
        r"\buv\s+publish\b",
        r"\bpoetry\s+publish\b",
        r"\bflit\s+publish\b",
    ),
    # Repository refs and forge Releases.
    "refs": (
        re.escape(APPROVED_RELEASE_ACTION),
        re.escape(APPROVED_ALIAS_ACTION),
    ),
}


def _destination_classes(job: dict[str, Any]) -> set[str]:
    body = json.dumps(job)
    return {
        name
        for name, patterns in DESTINATION_CLASSES.items()
        if any(re.search(pattern, body) for pattern in patterns)
    }


def test_publisher_credentials_stay_disjoint_between_destinations() -> None:
    """CI-AR24 / CI-AR40: each publisher receives only its own destination's credentials.

    Package OIDC and tokens are isolated from image jobs, and the job that writes refs
    holds neither. Derived from the parsed job, so a registry credential added to the
    package job -- the planted violation -- fails regardless of where in the job it
    appears.

    **Amended by story E008-S01-003.** The original comparison was pairwise across every
    publisher in the file, which encodes "one publisher per destination". That stopped
    being true the moment a finalizer moved image aliases: the alias job and the image
    publisher address *the same registry*, so they necessarily present the same
    credential to it, and the pairwise form rejected the correct arrangement while the
    rule it documents was satisfied. The rule is per **destination**, so the comparison
    is now per destination class -- and it gained two obligations the pairwise form never
    expressed:

    * a publisher belongs to exactly one destination class, so a job that both logs into
      a registry and uploads a package fails here rather than being compared against
      itself;
    * a package publisher may not declare `packages: write`, which is the only way the
      automatic forge token becomes a registry credential -- and the reason that token
      can be excluded from the comparison at all.
    """
    secret_reference = re.compile(r"secrets\.([A-Za-z_][A-Za-z0-9_-]*)")
    channel_workflows = _publishing_workflows()
    assert channel_workflows, "no workflow calls the image publisher"
    for path in channel_workflows:
        used: dict[str, set[str]] = {}
        classes: dict[str, set[str]] = {}
        for name, job in _publishers(_load_workflow(path)).items():
            # The reusable image publisher passes its caller's secrets through a
            # `secrets:` block, so the caller job is where they are named.
            used[name] = set(secret_reference.findall(json.dumps(job))) - {
                AMBIENT_FORGE_TOKEN
            }
            classes[name] = _destination_classes(job)
        assert used, f"{path.name} has no publishers; this guard examined nothing"
        # Per file, never folded across files: disjointness over a set of publishers
        # that reference no secret at all proves nothing, and a global vacuity check
        # lets one channel pass on another's behalf.
        assert any(used.values()), (
            f"{path.name}: no publisher references a named secret; the guard is vacuous"
        )
        assert any(classes.values()), (
            f"{path.name}: no publisher addresses a recognised destination; the class "
            f"derivation has stopped seeing this file"
        )

        for name, addressed in sorted(classes.items()):
            # Exactly one, never "at most one". A publisher that matches no pattern
            # satisfied `<= 1` while escaping the `packages: write` obligation below --
            # the compensation this amendment was paid for going quietly vacuous on the
            # first destination written a way `DESTINATION_CLASSES` has not seen. An
            # unclassifiable publisher is a vocabulary that needs extending, and that is
            # a thing to be told about.
            assert len(addressed) == 1, (
                f"{path.name}: publisher {name!r} addresses "
                f"{sorted(addressed) or 'no recognised destination'}. A job serving two "
                f"destinations hands each the other's credentials; a job serving none "
                f"means DESTINATION_CLASSES no longer describes how this repository "
                f"publishes -- extend it (CI-AR24)."
            )
            permissions = _load_workflow(path)["jobs"][name].get("permissions")
            if addressed == {"package"} and isinstance(permissions, dict):
                assert permissions.get("packages") != "write", (
                    f"{path.name}: package publisher {name!r} takes `packages: write`, "
                    f"which makes the automatic forge token a registry credential "
                    f"(CI-AR24)"
                )

        # The comparison the rule actually states: a named credential must not cross a
        # destination boundary. Two jobs addressing the SAME registry present the same
        # credential to it by construction, and that is not a leak.
        by_class: dict[str, set[str]] = {}
        for name, secrets in used.items():
            for addressed in classes[name]:
                by_class.setdefault(addressed, set()).update(secrets)
        names = sorted(by_class)
        for index, first in enumerate(names):
            for second in names[index + 1 :]:
                shared = by_class[first] & by_class[second]
                assert not shared, (
                    f"{path.name}: destinations {first!r} and {second!r} share "
                    f"credentials {sorted(shared)}; each destination gets only its own "
                    f"(CI-AR24)"
                )


def test_the_push_fixture_drives_the_real_identity_step(tmp_path: Path) -> None:
    """Runs dev.yaml's identity step, not a restatement of the fixture's own literals.

    An assertion that re-reads a constant out of the file it just loaded is a checksum of
    that file: it passes whatever the production code does. This extracts the step's
    actual `run:` body, executes it against the fixture event, and asserts the immutable
    tag value it produces -- so changing the `:0:12` slice, or the `dev-` composition,
    fails here. Joining that value to the image repository is the metadata action's job
    and is asserted by
    `test_image_references_are_rendered_by_the_metadata_action_never_hand_joined`.
    """
    event = _load_fixture("push-main.json")
    assert event["event_name"] == "push"
    assert event["ref"] == "refs/heads/main"
    assert re.fullmatch(r"[0-9a-f]{40}", event["sha"])
    assert event["forced"] is False

    identity = next(
        step
        for step in _steps(_load_workflow(DEV_WORKFLOW))
        if step.get("id") == "identity"
    )
    output = tmp_path / "github-output"
    output.touch()
    completed = subprocess.run(
        ["bash", "-c", str(identity["run"])],
        env={
            "PATH": os.environ["PATH"],
            "GITHUB_OUTPUT": str(output),
            "DEVELOPMENT_VERSION": "0.1.4.dev37",
            "RESOLVED_PYTHON": "3.14.0",
            "SOURCE_SHA": event["sha"],
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    emitted = dict(
        line.split("=", 1)
        for line in output.read_text(encoding="utf-8").splitlines()
        if line
    )
    short = event["sha"][:12]
    assert emitted["package-version"] == "0.1.4.dev37"
    assert emitted["short-sha"] == short
    assert emitted["image-tag-value"] == f"dev-{short}"

    # The empty-version guard is the one branch that must not be silently lost: an empty
    # development version would tag an image `:dev-` and publish it.
    empty = subprocess.run(
        ["bash", "-c", str(identity["run"])],
        env={
            "PATH": os.environ["PATH"],
            "GITHUB_OUTPUT": str(output),
            "DEVELOPMENT_VERSION": "",
            "RESOLVED_PYTHON": "3.14.0",
            "SOURCE_SHA": event["sha"],
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert empty.returncode != 0


def test_step_based_publishers_re_read_the_tag_set_before_they_upload() -> None:
    """F16's hardening, which nothing else asserts.

    The suppression job's conclusion is read at job level by every publisher. That is the
    guard job's answer, taken at guard-job time. The story's anchor is narrower and is
    the one that matters: a tag arriving between the guard job and the upload must still
    suppress. Without this test both re-check steps can be deleted with all 198 tests
    green, the runbook still claiming the behaviour, and the window silently back at
    "guard job start -> upload".

    Scope is derived from `_publishers()` over every channel workflow, restricted to jobs
    that HAVE steps: the image publisher is reached through `uses:` and a called workflow
    takes no caller steps, so it is protected at job granularity and legitimately cannot
    re-read inline. The stable channel is covered by the same rule for a different
    reason: `vX.Y.Z` is immutable (ADR-0006), so a tag that no longer peels to the
    commit being published means the identity moved under a run about to publish it.

    The key each file must branch on is derived from the file, never hand-kept: a
    channel with a suppression job consumes `suppressed`, one without it consumes the
    tag set itself.
    """
    examined = 0
    for path in _publishing_workflows():
        document = _load_workflow(path)
        suppressors = {
            name
            for name, job in _jobs(document).items()
            if "suppressed" in (job.get("outputs") or {})
        }
        # How the re-read reaches its refusal, derived from the file rather than
        # hand-kept: a channel with a suppression job branches on that job's
        # `suppressed` conclusion; one without it hands the whole membership decision
        # to the tested module, whose non-zero exit is the refusal under `set -e`.
        # Grepping only for the script name accepts a step that runs it and throws the
        # answer away, which is the guard-that-cannot-fail shape (F9).
        refusal = "suppressed" if suppressors else STABLE_RECHECK_MARKER
        for name, job in _publishers(document).items():
            steps = job.get("steps") or []
            if not steps:
                continue
            examined += 1
            upload_at = next(
                (i for i, step in enumerate(steps) if _is_publishing_step(step)),
                len(steps),
            )
            # Uncommented, on both halves. The prose beside a mechanism names it, so a
            # raw-body check is satisfied by the comment explaining the call that was
            # deleted -- a guard that reads its own documentation and reports success.
            rechecks = [
                _uncommented(str(step.get("run", "")))
                for step in steps[:upload_at]
                if TAG_MEMBERSHIP_MARKER in _uncommented(str(step.get("run", "")))
            ]
            assert rechecks, (
                f"{path.name}: publisher {name!r} never re-reads the tag set before "
                f"uploading. The job-level gate is the plan or guard job's answer, taken "
                f"before the verifier finished; F16 requires the re-read immediately "
                f"before the credentialed step."
            )
            assert any(refusal in command for command in rechecks), (
                f"{path.name}: publisher {name!r} runs the tag check without reaching a "
                f"refusal from it (expected `{refusal}`)"
            )
    assert examined, "no channel workflow has a step-based publisher; nothing examined"


def _compose_tag_list(
    tags: str,
    registry: str = "ghcr.io",
    dockerhub: str = "false",
    repositories: str = "ghcr.io/owner/name\ndocker.io/owner/name",
) -> Any:
    """Execute publish-image.yaml's real tag-composition body with a planted input.

    Shared by the two guards that own opposite directions of the same rule, so both
    run the shipped step rather than a paraphrase of it.
    """
    document = _load_workflow(PUBLISH_IMAGE_WORKFLOW)
    compose = next(step for step in _steps(document) if step.get("id") == "plan")
    output = Path(tempfile.mkdtemp()) / "github-output"
    output.touch()
    completed = subprocess.run(
        ["bash", "-c", str(compose["run"])],
        env={
            "PATH": os.environ["PATH"],
            "GITHUB_OUTPUT": str(output),
            "DOCKERHUB_ENABLED": dockerhub,
            "IMAGE_TAGS": tags,
            "PERMITTED_REPOSITORIES": repositories,
            "PLATFORMS": ",".join(REQUIRED_IMAGE_PLATFORMS),
            "REGISTRY": registry,
        },
        capture_output=True,
        text=True,
        check=False,
    )
    emitted = dict(
        line.split("=", 1)
        for line in output.read_text(encoding="utf-8").splitlines()
        if line
    )
    return completed, emitted


@pytest.mark.parametrize(
    "alias",
    [
        "ghcr.io/owner/name:latest",
        "ghcr.io/owner/name:1",
        "ghcr.io/owner/name:1.2",
        # The development channel's alias, moved by dev.yaml's own finalizer. The first
        # version of this refusal enumerated the *stable* channel's alias shapes and
        # accepted `dev`, so the publisher could have taken it outside the grant --
        # skipping the just-in-time default-branch-head proof and the stable-tag
        # suppression re-check (epic redteam E1).
        "ghcr.io/owner/name:dev",
        "ghcr.io/owner/name:main",
        "ghcr.io/owner/name:stable",
        "ghcr.io/owner/name:dev-nothex12345",
        "ghcr.io/owner/name:1.2.3.4",
        "ghcr.io/owner/name:v1.2.3",
    ],
)
def test_a_publisher_refuses_to_push_an_alias_however_the_tag_list_was_rendered(
    alias: str,
) -> None:
    """CI-AR29: an alias is the finalizer's sole property, enforced where the tag list
    is real rather than where it is requested.

    The list comes from `LiquidLogicLabs/git-action-docker-metadata@v6`, a fork of
    `docker/metadata-action` on its own major line, and the neighbouring guard asserts
    `flavor: latest=false` is *passed* -- not that it is *honoured*. If the renderer
    ever emitted `latest`, or a bare major or major.minor, the publisher would move an
    alias from outside the grant and every alias-ownership guard would still pass,
    because they read the workflow and not the rendered list. Executed against the
    shipped step, so the refusal is proven rather than described.
    """
    completed, _ = _compose_tag_list(alias)
    assert completed.returncode != 0, f"the publisher accepted the alias {alias!r}"
    assert "not an immutable publication tag" in completed.stderr, completed.stderr


def test_the_exact_version_a_publisher_does_push_is_still_accepted() -> None:
    """The other half: the refusal above must not reject what a release actually
    publishes -- an exact `X.Y.Z`, or the development channel's `dev-<sha>`."""
    for permitted in (
        "ghcr.io/owner/name:1.2.3",
        "ghcr.io/owner/name:10.20.30",
        "ghcr.io/owner/name:dev-0123456789ab",
        "ghcr.io/owner/name:dev-abcdef012345",
    ):
        completed, _ = _compose_tag_list(permitted)
        assert completed.returncode == 0, completed.stderr


@pytest.mark.parametrize(
    ("tag", "why"),
    [
        (
            "ghcr.io/owner/name:a,b",
            "a comma splits into two tags under bake's CSV parse",
        ),
        (
            "ghcr.io/owner/na me:1.2.3",
            "interior whitespace was silently deleted, not refused",
        ),
        ("ghcr.io/owner/name\u200b:1.2.3", "a zero-width space survives normalisation"),
        (
            "ghcr.io/оwner/name:1.2.3",
            "a Cyrillic homoglyph reads as the proven repository",
        ),
        ("ghcr.io/owner/name;evil:1.2.3", "a separator other than the comma"),
    ],
)
def test_a_tag_outside_the_oci_character_grammar_is_refused(tag: str, why: str) -> None:
    """Refused, never repaired.

    The normalisation was `tr -d '[:space:]'`, which deletes *interior* whitespace too --
    so `ghcr.io/a b:1` became `ghcr.io/ab:1`, a different image reference, published
    without complaint. And the separator defence named only the comma, while the
    repository comparison it feeds is byte-exact: a homoglyph or zero-width character
    passes normalisation and then compares unequal to the repository the plan job proved.

    An OCI reference is ASCII by construction, so one character-class refusal subsumes
    all three. The multi-byte cases are caught because every UTF-8 continuation byte is
    outside the class.
    """
    completed, _ = _compose_tag_list(
        f"ghcr.io/owner/name:1.2.3\n{tag}", repositories="ghcr.io/owner/name"
    )
    assert completed.returncode != 0, f"accepted {tag!r}: {why}"


def test_the_digest_reference_is_the_forge_repository_never_the_first_tag() -> None:
    """`primary` is the reference the digest is resolved from, and therefore the target
    every alias the finalizer moves will follow.

    It was taken positionally -- the first tag in the rendered list -- which made an
    alias target a property of a third-party metadata action's output ORDER. With two
    enabled destinations the choice between them was the renderer's, not this
    repository's. The forge registry is the one destination that is never optional
    (ADR-0011), so it is the only stable anchor.
    """
    permitted = "ghcr.io/owner/name\ndocker.io/owner/name"
    # Docker Hub first in the rendered list, forge second: `primary` must still be the
    # forge repository.
    completed, emitted = _compose_tag_list(
        "docker.io/owner/name:1.2.3\nghcr.io/owner/name:1.2.3",
        dockerhub="true",
        repositories=permitted,
    )
    assert completed.returncode == 0, completed.stderr
    assert emitted["primary"] == "ghcr.io/owner/name", (
        f"the digest reference followed the first tag ({emitted['primary']}) rather "
        f"than the forge repository"
    )
    # And the reverse order gives the same answer, which is the point.
    completed, emitted = _compose_tag_list(
        "ghcr.io/owner/name:1.2.3\ndocker.io/owner/name:1.2.3",
        dockerhub="true",
        repositories=permitted,
    )
    assert completed.returncode == 0, completed.stderr
    assert emitted["primary"] == "ghcr.io/owner/name"


def test_a_tag_may_not_address_a_repository_the_plan_job_never_proved() -> None:
    """The permission check tested the *authority* and never the *repository*.

    A Docker Hub credential is account-scoped, so every repository that account can
    write shares one authority. A tag list naming `docker.io/<elsewhere>/x` passed --
    `buildx` pushes whatever it is handed, with the real token -- publishing this
    project's verified image under a name nobody chose, and `primary` (the digest
    reference the aliases then follow) is whichever tag came first. The list is rendered
    by a third-party action on a floating ref, which is exactly the input not to trust.

    The plan job already proved both repositories and handed them to that action; they
    are now handed to the publisher too, and every tag is checked against them.
    """
    permitted = "ghcr.io/owner/name\ndocker.io/owner/name"
    completed, _ = _compose_tag_list(
        "docker.io/elsewhere/x:1.2.3", dockerhub="true", repositories=permitted
    )
    assert completed.returncode != 0, "a tag for an unproven repository was accepted"
    assert "which the plan job did" in completed.stderr, completed.stderr

    # The forge authority is no different: same host, unproven name.
    completed, _ = _compose_tag_list(
        "ghcr.io/elsewhere/x:1.2.3", repositories="ghcr.io/owner/name"
    )
    assert completed.returncode != 0, completed.stderr

    # A run that proves nothing publishes nothing, rather than defaulting to open.
    completed, _ = _compose_tag_list("ghcr.io/owner/name:1.2.3", repositories="  \n ")
    assert completed.returncode != 0, "an empty permitted set was treated as permissive"


@pytest.mark.parametrize(
    "spelling",
    [
        "docker.io/owner/name:1.2.3",
        "index.docker.io/owner/name:1.2.3",
        "owner/name:1.2.3",
    ],
)
def test_the_three_spellings_of_one_docker_hub_repository_are_one_destination(
    spelling: str,
) -> None:
    """`docker.io/owner/name`, `index.docker.io/owner/name` and a bare `owner/name` are
    the same place. Comparing the rendered string against the proven string would refuse
    two of the three, so both sides are normalised -- and the refusal above still has to
    hold, which is what the neighbouring test keeps honest."""
    completed, _ = _compose_tag_list(
        f"ghcr.io/owner/name:1.2.3\n{spelling}",
        dockerhub="true",
        repositories="ghcr.io/owner/name\ndocker.io/owner/name",
    )
    assert completed.returncode == 0, completed.stderr


def test_an_enabled_destination_that_receives_no_tag_halts_before_anything_ships() -> (
    None
):
    """The symmetric direction of the permission check, and the one that was missing.

    The forbidden direction -- a tag for a destination the run did not log into -- was
    enforced. Its mirror was enforced nowhere, and nothing downstream can recover it: a
    job result carries no evidence of *which* destinations it addressed, which the
    finalizer gate says of itself. So `PUBLISH_IMAGE_DOCKERHUB=true` with a tag list
    that renders forge-only pushed to the forge alone, passed the permission check,
    succeeded, let the gate join `image-dockerhub: enabled` with `success` -> ok,
    created the Release, advanced the Git aliases, and only then failed inside
    `imagetools create` against a Docker Hub digest that was never pushed.

    Run against the shipped step, like its mirror: a textual check would pass with the
    refusal deleted and the accumulator left behind.
    """
    completed, _ = _compose_tag_list("ghcr.io/owner/name:1.2.3", dockerhub="true")
    assert completed.returncode != 0, (
        "dockerhub was enabled and no tag addressed it, and the step composed a "
        "forge-only push anyway"
    )
    assert "no tag addresses docker.io" in completed.stderr, completed.stderr

    # The forge registry is never optional, so a Docker-Hub-only list is the same defect.
    completed, _ = _compose_tag_list(
        "docker.io/owner/name:1.2.3", registry="ghcr.io", dockerhub="true"
    )
    assert completed.returncode != 0, "no tag addressed the forge registry"
    assert "no tag addresses it" in completed.stderr, completed.stderr

    # Both addressed, in either Docker Hub spelling, and it goes through.
    for hub in ("docker.io/owner/name:1.2.3", "index.docker.io/owner/name:1.2.3"):
        completed, emitted = _compose_tag_list(
            f"ghcr.io/owner/name:1.2.3\n{hub}", dockerhub="true"
        )
        assert completed.returncode == 0, completed.stderr
        assert emitted["tags"].count(",") == 1

    # And with Docker Hub off, a forge-only list is correct rather than a drift.
    completed, _ = _compose_tag_list("ghcr.io/owner/name:1.2.3")
    assert completed.returncode == 0, completed.stderr


def test_every_published_tag_addresses_a_destination_the_run_logged_into() -> None:
    """ "Disabled destinations receive no credentials **or requests**."

    Buildx pushes whatever tag list it is handed. A Docker Hub tag passed with
    `dockerhub: false` issues a request to a destination the run declared disabled -- it
    fails, so nothing ships wrong, but the AC is about the request. `dev.yaml` is safe
    today only because its plan job emits a single forge tag; `release.yaml` will make
    that list conditional.

    Asserted by RUNNING the step, not by reading it. A textual check ("the word
    `permitted` appears") passes with the rejection branch deleted and the variable left
    behind, which is exactly the shape of guard this repository keeps finding.
    """
    run = _compose_tag_list

    completed, emitted = run("ghcr.io/owner/name:dev-0123456789ab")
    assert completed.returncode == 0, completed.stderr
    assert emitted["tags"] == "ghcr.io/owner/name:dev-0123456789ab"
    assert emitted["primary"] == "ghcr.io/owner/name"
    assert set(emitted["platforms"].split(",")) == set(REQUIRED_IMAGE_PLATFORMS)

    # A registry with a port must not be mistaken for a repository with a tag.
    completed, emitted = run(
        "git.example.com:3000/owner/name:dev-0123456789ab",
        registry="git.example.com:3000",
        repositories="git.example.com:3000/owner/name",
    )
    assert completed.returncode == 0, completed.stderr
    assert emitted["primary"] == "git.example.com:3000/owner/name"

    # Docker Hub, disabled: the request must never be issued.
    completed, _ = run(
        "ghcr.io/owner/name:dev-0123456789ab\ndocker.io/owner/name:dev-0123456789ab"
    )
    assert completed.returncode != 0, "a tag for a disabled destination was accepted"
    # Docker Hub's implicit authority is the same violation without the hostname.
    completed, _ = run("owner/name:dev-0123456789ab")
    assert completed.returncode != 0

    # Enabled, and it goes through.
    completed, emitted = run(
        "ghcr.io/owner/name:dev-0123456789ab\ndocker.io/owner/name:dev-0123456789ab",
        dockerhub="true",
    )
    assert completed.returncode == 0, completed.stderr
    assert emitted["tags"].count(",") == 1

    for malformed in (
        "ghcr.io/owner/name:a,b",  # a comma splits into two tags under bake's CSV parse
        "ghcr.io/owner/name",  # no tag at all
        "",  # nothing to publish
        "   ",
    ):
        completed, _ = run(malformed)
        assert completed.returncode != 0, f"accepted malformed tag list {malformed!r}"
