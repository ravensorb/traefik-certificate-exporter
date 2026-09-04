"""What a governed definition is allowed to call, and on what reference.

BL-E008-010 phase 3. Owner allowlist, pin policy, and the reach of a credential -- which
follows what an action RECEIVES, not what its name suggests. A step named "login" that is
handed no secret is not credential-handling; a step named "upload" that is handed one is.

The act-environment guards belong here for the same reason: `if ! env.ACT` is a branch on
the caller's identity, and a definition that takes one is not the definition CI runs.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml

from tests.ci.support import (
    ACT_BRANCH,
    APPROVED_RELEASE_ACTION,
    CREDENTIAL_ACTIONS_ON_MOVING_REFS,
    GOVERNED_DEFINITIONS,
    PROJECT_ROOT,
    REGISTRY_LOGIN_ACTION,
    SCRIPTS,
    SETUP_ACTION,
    SHA_PINNED_ACTIONS,
    VERIFY_WORKFLOW,
    _action_references,
    _governed_step_groups,
    _jobs,
    _load_document,
    _steps,
    _uncommented,
    committed_versions,
)

APPROVED_ACTION_OWNERS = {
    "actions",
    "docker",
    "pypa",
    "LiquidLogicLabs",
}


# A maintained floating major alias, so a fix ships without a manifest edit. Most
# owners publish it as a `vN` tag; pypa publishes it as the `release/vN` branch, which
# is the same guarantee spelled differently. A pinned patch tag is not an alias.
FLOATING_MAJOR_ALIAS = re.compile(r"\A(?:release/)?v[0-9]+\Z")


REVIEWED_COMMIT_SHA = re.compile(r"\A[0-9a-f]{40}\Z")


def _external_action_references(path: Path) -> list[str]:
    return [
        reference
        for reference in _action_references(path)
        if not reference.startswith("./")
    ]


def test_tier_one_actions_use_approved_owners_and_floating_major_aliases() -> None:
    examined = 0
    for path in GOVERNED_DEFINITIONS:
        for reference in _external_action_references(path):
            examined += 1
            action, _, version = reference.rpartition("@")
            owner = action.split("/", 1)[0]
            assert owner in APPROVED_ACTION_OWNERS, (
                f"{path}: {owner} requires an approved ADR or architecture update"
            )
            if action in SHA_PINNED_ACTIONS:
                assert REVIEWED_COMMIT_SHA.fullmatch(version), (
                    f"{path}: {reference} is handed a publication credential, so it must "
                    f"be pinned to a reviewed full 40-character commit SHA (CI-AR38), not "
                    f"a floating alias whose branch can be moved under it"
                )
            else:
                assert FLOATING_MAJOR_ALIAS.fullmatch(version), (
                    f"{path}: {reference} must use the maintained floating major alias"
                )
    assert examined, "no external action references were examined"


def _definition_step_lists(document: dict[str, Any]) -> list[dict[str, Any]]:
    """Every ordered step list in a workflow or a composite action.

    A composite action holds one list under `runs.steps`; a workflow holds one per job.
    Composite actions are in scope because they run inside the credential-bearing job
    and see the same runner state.
    """
    if "jobs" in document:
        return list(_jobs(document).values())
    runs = document.get("runs") or {}
    # A composite action has no permissions of its own; it runs with the calling job's.
    # The caller is examined separately, so an empty mapping here is correct rather than
    # a gap -- it avoids attributing an ambient credential to a file that cannot hold one.
    return [{"steps": runs.get("steps") or [], "permissions": {}}]


def _credential_handling_actions(
    definitions: dict[str, dict[str, Any]] | None = None,
) -> dict[str, set[str]]:
    """External actions handed a publication credential, and why -- derived.

    Two mechanically checkable ways an action receives one:

    * a `secrets.*` expression reaches it, through its own `with:`/`env:` or through a
      `secrets:` block on the job that calls it;
    * it runs *after* a registry login in the same job, so the runner's
      `~/.docker/config.json` holds credentials for it to read. Nothing is passed to it
      and it has them anyway, which is why "what is passed" alone is not the test.

    The rule this replaces matched `pypi|publish` against the action's *repository
    name*. That is a hand-enumerated scope wearing a derivation's clothes: four actions
    shipped this sprint are handed a credential and match neither word, so the guard
    skipped them and the floating-major branch passed them (redteam H1).
    """
    if definitions is None:
        definitions = {
            str(path.relative_to(PROJECT_ROOT)): _load_document(path)
            for path in GOVERNED_DEFINITIONS
        }
    found: dict[str, set[str]] = {}
    for document in definitions.values():
        for job in _definition_step_lists(document):
            # The third mechanism, and the one this epic introduced the job for. An OIDC
            # identity is not *passed* to a step -- it is ambient in the job, as
            # ACTIONS_ID_TOKEN_REQUEST_URL/_TOKEN in every step's environment -- so every
            # action in a job holding `id-token: write` can mint one. The same is true of
            # `packages: write`, `attestations: write` and `contents: write` against the
            # automatic token. Recognising only what is handed over made the derivation
            # blind to the newest and most consequential job in the repository.
            permissions = job.get("permissions")
            ambient = (
                sorted(
                    scope
                    for scope in ("contents", "packages", "id-token", "attestations")
                    if permissions.get(scope) == "write"
                )
                if isinstance(permissions, dict)
                else []
            )
            after_login = False
            for step in job.get("steps") or []:
                used = str(step.get("uses", ""))
                if used and not used.startswith("./"):
                    action = used.rpartition("@")[0]
                    handed = json.dumps({key: step.get(key) for key in ("with", "env")})
                    reasons = set()
                    if "secrets." in handed:
                        reasons.add("a secret is passed to it")
                    if job.get("secrets") is not None:
                        reasons.add("its job receives secrets")
                    if after_login:
                        reasons.add("it runs after a registry login")
                    if ambient:
                        reasons.add(f"its job holds {', '.join(ambient)}")
                    if reasons:
                        found.setdefault(action, set()).update(reasons)
                    if action.startswith(REGISTRY_LOGIN_ACTION):
                        after_login = True
    return found


def test_every_credential_handling_action_is_pinned_or_its_risk_is_recorded() -> None:
    """ADR-0009's reach half, over a set derived from what an action is handed.

    An action on a floating major is one moved ref away from exfiltrating whatever it
    receives, and nothing in this repository would change. So each candidate is either
    SHA-pinned or its acceptance is written down with a reason -- silence is the one
    outcome the registry does not allow.
    """
    candidates = _credential_handling_actions()
    assert candidates, "no action receives a credential; this guard examined nothing"
    for action, reasons in sorted(candidates.items()):
        assert (
            action in SHA_PINNED_ACTIONS or action in CREDENTIAL_ACTIONS_ON_MOVING_REFS
        ), (
            f"{action} is handed a publication credential ({'; '.join(sorted(reasons))}) "
            f"and rides a moving ref. Register it in SHA_PINNED_ACTIONS, or record the "
            f"accepted risk in CREDENTIAL_ACTIONS_ON_MOVING_REFS with an ADR (CI-AR38)."
        )
    assert not (SHA_PINNED_ACTIONS & set(CREDENTIAL_ACTIONS_ON_MOVING_REFS)), (
        "an action cannot be both SHA-pinned and recorded as accepted on a moving ref"
    )
    stale = set(CREDENTIAL_ACTIONS_ON_MOVING_REFS) - set(candidates)
    assert not stale, (
        f"{sorted(stale)} accept a risk this repository no longer takes; a registry that "
        f"outlives its entries stops being read"
    )


def test_the_credential_reach_follows_what_an_action_receives_not_its_name() -> None:
    """The scope attack. Neither planted action's name says `pypi` or `publish`, which
    is precisely how four real ones went unexamined for the whole sprint."""
    planted = {
        "plant.yaml": {
            "on": {"push": {}},
            "jobs": {
                "ship": {
                    "runs-on": "ubuntu-24.04",
                    "steps": [
                        {
                            "uses": "vendor/upload-thing@v1",
                            "with": {"token": "${{ secrets.VENDOR_TOKEN }}"},
                        },
                        {
                            "uses": "docker/login-action@v3",
                            "with": {"password": "${{ secrets.REGISTRY_TOKEN }}"},
                        },
                        {"uses": "vendor/smoke-test@v2"},
                    ],
                }
            },
        }
    }
    found = _credential_handling_actions(planted)
    assert found["vendor/upload-thing"] == {"a secret is passed to it"}
    assert found["vendor/smoke-test"] == {"it runs after a registry login"}, (
        "an action that reads the runner's docker config is handed a credential too, "
        "even though nothing is passed to it"
    )


# The one Python module the pipeline may call, and why it is the only one. It answers
# "what version is committed", which is a fact about the repository rather than a
# publication decision, and it has a single implementation so the channels cannot
# disagree about it.
PERMITTED_PIPELINE_MODULE = "committed_versions.py"


def _pipeline_python_modules() -> set[str]:
    """Modules under `scripts/` that a governed definition actually invokes.

    Both sides come from disk: the candidate names from `scripts/`, the invocations from
    the parsed `run:` bodies with comments stripped. Every workflow *mentions*
    `committed_versions.py` in a comment, so a raw text scan would report invocations
    that are not there.
    """
    modules = {path.name for path in SCRIPTS.glob("*.py")}
    invoked = set()
    for _, _, steps in _governed_step_groups():
        for step in steps:
            command = _uncommented(str(step.get("run", "")))
            invoked |= {name for name in modules if f"scripts/{name}" in command}
    return invoked


def test_no_publication_decision_lives_in_a_python_module() -> None:
    """The maintainer's rule for this pipeline: actions and workflow steps, not scripts.

    E008 deleted `forge_coordinates.py`, `stable_tags.py` and `finalizer_gate.py` --
    535, 301 and 213 lines deciding forge coordinates, alias ordering and whether a
    release may finalize. Each is now a step in the workflow that owns the decision, and
    each has an ADR recording why the module form was wrong: a decision in a module is
    testable only against the module, while a decision in a `run:` body is executed by
    the contract suite with the real environment substituted in.

    The rule is derived rather than kept as a list of dead filenames. What matters is
    not that a file is absent -- an unwired file decides nothing -- but that no
    publication decision is *reached* through one again. A resurrected module fails here
    the moment a workflow calls it, which is the moment it starts mattering.
    """
    invoked = _pipeline_python_modules()
    assert invoked == {PERMITTED_PIPELINE_MODULE}, (
        f"the pipeline invokes {sorted(invoked)}; only {PERMITTED_PIPELINE_MODULE!r} is "
        f"permitted. A publication decision belongs in the workflow step that owns it "
        f"(ADR-0011), where the contract suite executes it."
    )


def test_no_governed_definition_branches_on_the_act_environment_variable() -> None:
    """Guidelines §7: one pipeline, three runners, and no conditional on which one is
    executing. A workflow that behaves differently under `act` is not the workflow CI
    runs, so a green local verification proves nothing about the real one.

    The rule was enforced for `verify-build.yaml` alone, by substring, while §7 recorded
    a live violation in a workflow that no longer exists. Scope is every governed
    definition, composite actions included -- a composite is where an `env.ACT` branch
    would most naturally be hidden, since it is shared by every caller.
    """
    for path in GOVERNED_DEFINITIONS:
        assert not ACT_BRANCH.search(path.read_text(encoding="utf-8")), (
            f"{path}: branches on the `ACT` environment variable. One pipeline, three "
            f"runners (guidelines §7); a runner-agnostic mechanism instead."
        )


def test_tier_one_forbids_expression_interpolated_action_references() -> None:
    for path in GOVERNED_DEFINITIONS:
        for reference in _action_references(path):
            assert "${{" not in reference, f"{path}: {reference}"


def test_no_third_party_action_creates_a_release() -> None:
    """`APPROVED_RELEASE_ACTION` was a dead constant -- defined, named in an error
    message, and asserted nowhere. So `actions/create-release@v1` in a finalizer passed
    every guard, silently losing the Gitea path ADR-0010 exists to secure: that action
    speaks GitHub's API only, and E009's premise is that the same YAML works on Gitea.

    Forbidding the hand-rolled `curl` was never enough. The likelier shortcut is a
    different action, and it fails in exactly the place nobody is testing yet.
    """
    release_shaped = re.compile(r"(?:^|[-/])release(?:[-/]|$)", re.IGNORECASE)
    for path in GOVERNED_DEFINITIONS:
        for reference in _external_action_references(path):
            action, _, _ = reference.rpartition("@")
            if action.startswith(APPROVED_RELEASE_ACTION):
                continue
            # The changelog builder is release-shaped but creates nothing.
            if action.startswith(f"{APPROVED_RELEASE_ACTION}-changelog-builder"):
                continue
            assert not release_shaped.search(action.split("/", 1)[-1]), (
                f"{path}: {action} is release-creating. Releases go through "
                f"{APPROVED_RELEASE_ACTION}@v2, which speaks both GitHub's and Gitea's "
                f"APIs from one step (ADR-0010). A GitHub-only action loses E009."
            )


# Every bot that decides a version number for you. ADR-0006 puts that authority in the
# guarded local transaction, and a second one is not a redundancy -- it is two answers.
VERSION_BOT = re.compile(
    r"release-please|semantic-release|release-drafter|standard-version|changesets/action",
    re.IGNORECASE,
)


# Their configuration files. A bot that is configured but whose action has not landed yet
# is the state just before this rule breaks.
VERSION_BOT_ARTEFACTS = (
    ".release-please-manifest.json",
    "release-please-config.json",
    ".releaserc",
    ".releaserc.json",
    ".releaserc.yaml",
    ".versionrc",
    ".versionrc.json",
    ".changeset",
)


def test_no_workflow_delegates_versioning_to_an_external_release_bot() -> None:
    """ADR-0006: the committed version has one authority, the guarded local transaction.

    This was `"release-please" not in <raw file text>`, which is wrong in both
    directions. A comment explaining *why* release-please is not used would fail it --
    prose about a rule breaking the rule -- and every other version bot passed it,
    including `semantic-release`, which does the same thing under another name.

    Actions are matched as parsed references; configuration files are matched on disk,
    because a bot that is configured but whose workflow step has not landed yet is the
    state immediately before this rule is broken.
    """
    for path in GOVERNED_DEFINITIONS:
        for reference in _action_references(path):
            action = reference.rpartition("@")[0] or reference
            assert not VERSION_BOT.search(action), (
                f"{path}: {action} is a competing version authority (ADR-0006)"
            )
    for artefact in VERSION_BOT_ARTEFACTS:
        assert not (PROJECT_ROOT / artefact).exists(), (
            f"{artefact} configures an external version bot; the committed version has "
            f"one authority (ADR-0006)"
        )


def test_setup_action_owns_interpreter_and_poetry_installation() -> None:
    action = _load_document(SETUP_ACTION)
    assert action["runs"]["using"] == "composite"
    # Exact equality, so a new input cannot be added without this line being reconsidered.
    # `development-distance` was added by story E008-S01-001: the development version
    # X.Y.(Z+1).devN comes from scripts/committed_versions.py through this action, so no
    # plan job has to know how a development version is spelled (F12).
    assert set(action["inputs"]) == {
        "python-version",
        "poetry",
        "dependencies",
        "development-distance",
    }
    assert {"package-version", "poetry-version", "development-version"} <= set(
        action["outputs"]
    )

    setup_python = action["runs"]["steps"][0]
    assert setup_python["uses"] == "actions/setup-python@v7"
    assert setup_python["with"]["python-version"] == "${{ inputs.python-version }}"

    # Every job that needs an interpreter goes through the action, so the interpreter
    # is pinned everywhere and the Poetry pin is resolved in exactly one place.
    for path in GOVERNED_DEFINITIONS:
        if path == SETUP_ACTION:
            continue
        source = path.read_text(encoding="utf-8")
        assert "actions/setup-python@" not in source, path
        assert "pipx install" not in source, path


def test_the_poetry_pin_has_one_authority_every_location_agrees_with() -> None:
    pin = committed_versions.poetry_version()
    assert re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", pin)

    # The composite action resolves the pin at run time from that authority; it does
    # not restate it.
    action_source = SETUP_ACTION.read_text(encoding="utf-8")
    assert "scripts/committed_versions.py" in action_source
    for path in GOVERNED_DEFINITIONS:
        assert re.search(r"poetry==[0-9]", path.read_text(encoding="utf-8")) is None, (
            path
        )

    # Locations consumed outside the workflow runtime still carry the literal. Each is
    # bound to the same authority here.
    bake = (PROJECT_ROOT / "docker-bake.hcl").read_text(encoding="utf-8")
    assert re.findall(r'POETRY_VERSION\s*=\s*"([^"]+)"', bake) == [pin]

    verify_source = VERIFY_WORKFLOW.read_text(encoding="utf-8")
    assert re.findall(r'"POETRY_VERSION":"([^"]+)"', verify_source) == [pin]

    developer = (PROJECT_ROOT / "docs" / "developer.md").read_text(encoding="utf-8")
    assert set(re.findall(r"Poetry ([0-9]+\.[0-9]+\.[0-9]+)", developer)) == {pin}


# `ACT` as a whole token, not a substring. A bare `"ACT" in text` check matches
# `PC_CONTRACT` and `GITHUB_ACTION_PATH`, so it fails on steps that never mention act --
# and a guard that cries wolf gets deleted rather than fixed.
_ACT_TOKEN = re.compile(r"(?<![A-Z_])ACT(?![A-Z_])")


def test_all_governed_steps_are_independent_of_the_act_environment() -> None:
    """No step may branch on act. The same YAML must run on GitHub, Gitea and locally;
    platform selection is data, not an `if:` on the emulator."""
    for path in GOVERNED_DEFINITIONS:
        for step in _steps(_load_document(path)):
            for field in ("if", "run"):
                assert not _ACT_TOKEN.search(str(step.get(field, ""))), (
                    f"{path}: step branches on the act environment via `{field}:`"
                )


ARTIFACT_ACTIONS = ("actions/upload-artifact", "actions/download-artifact")


def test_artifact_actions_remain_on_the_both_forge_v4_pair() -> None:
    """Deliberately NOT on the latest major, and the only such exception.

    Gitea's act_runner implements the v4 artifact protocol; v5+ are GitHub-only. The
    inherited invariant is that the same workflow YAML runs on GitHub, Gitea and local
    act, and Epic 9 is Certified Gitea Portability -- so forge compatibility wins over
    currency here. `actions/upload-artifact@v7` exists; taking it would drop Gitea.

    Revisit when Gitea's runner supports a newer artifact protocol.
    """
    # Scope is every governed definition, not just the verifier (gate finding F11).
    # dev.yaml and release.yaml will use actions/download-artifact, and tier one happily
    # accepts @v7 -- so the Gitea pin could be broken in the new workflows with every test
    # green, surfacing only in Epic 9.
    examined = 0
    for path in GOVERNED_DEFINITIONS:
        for reference in _external_action_references(path):
            for action in ARTIFACT_ACTIONS:
                if not reference.startswith(f"{action}@"):
                    continue
                examined += 1
                assert reference == f"{action}@v4", (
                    f"{path}: {reference} drops Gitea's act_runner, which implements the "
                    f"v4 artifact protocol only"
                )
    assert examined, "no artifact action references were examined"


def test_dependabot_protects_the_artifact_pin_it_would_otherwise_undo() -> None:
    """A pin a bot reverts weekly is not a pin.

    Dependabot is what keeps every other action on its latest major, so left alone it
    proposes upload-artifact v7 until someone merges it and Gitea silently stops working.
    The exception above is only real if Dependabot is told about it.
    """
    dependabot = yaml.load(
        (PROJECT_ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8"),
        Loader=yaml.BaseLoader,
    )
    actions_entry = next(
        entry
        for entry in dependabot["updates"]
        if entry["package-ecosystem"] == "github-actions"
    )
    ignored = {
        rule["dependency-name"]
        for rule in actions_entry.get("ignore", [])
        if "version-update:semver-major" in rule.get("update-types", [])
    }
    assert set(ARTIFACT_ACTIONS) <= ignored, (
        "the forge-compatible artifact pin is not protected from Dependabot: "
        f"missing {sorted(set(ARTIFACT_ACTIONS) - ignored)}"
    )


def test_dependency_maintenance_covers_actions_python_and_docker() -> None:
    dependabot = yaml.load(
        (PROJECT_ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8"),
        Loader=yaml.BaseLoader,
    )
    configured = {
        (update["package-ecosystem"], update["directory"])
        for update in dependabot["updates"]
    }
    assert configured == {
        ("github-actions", "/"),
        ("pip", "/"),
        ("docker", "/docker"),
    }

    # The reach half. Asserting the entry exists proves the rule, not that the rule can
    # do anything: Dependabot resolves `FROM $VAR` only through an ARG default, so an
    # undefaulted `ARG BASE_IMAGE` leaves the watched directory unupdatable while this
    # config still reports coverage. That exact regression reached main once already.
    #
    # Parsed with dockerfile-parse rather than a hand-rolled scanner; only the
    # Dependabot-specific ARG-default resolution is local.
    from dockerfile_parse import DockerfileParser

    bake = (PROJECT_ROOT / "docker-bake.hcl").read_text(encoding="utf-8")
    watched_bases: set[str] = set()
    for ecosystem, directory in configured:
        if ecosystem != "docker":
            continue
        target = PROJECT_ROOT / directory.lstrip("/")
        assert target.is_dir(), f"dependabot watches {directory}, which does not exist"
        dockerfiles = sorted(target.glob("Dockerfile*"))
        assert dockerfiles, f"dependabot watches {directory} with no Dockerfile in it"
        for dockerfile in dockerfiles:
            parser = DockerfileParser(path=str(dockerfile))
            # Walked in order, accumulating ARG defaults as they appear. `parser.args` is
            # the build-arg context, not the declared defaults, so the structure is the
            # authority. Order matters and is not incidental: Dependabot resolves a
            # variable in FROM only against an ARG that PRECEDES that FROM, so an ARG
            # declared after the stage it is meant to serve resolves to nothing.
            defaults: dict[str, str] = {}
            for line in parser.structure:
                if line["instruction"] == "ARG":
                    name, _, value = line["value"].partition("=")
                    if value:
                        defaults[name.strip()] = value.strip()
                    continue
                if line["instruction"] != "FROM":
                    continue
                image = line["value"].split(" AS ")[0].split(" as ")[0].strip()
                if not image.startswith("$"):
                    watched_bases.add(image)
                    continue
                name = image.lstrip("${").rstrip("}")
                resolved = defaults.get(name)
                assert resolved, (
                    f"{dockerfile}: FROM {image} has no ARG default, so the dependabot "
                    f"docker entry for {directory} can update nothing"
                )
                watched_bases.add(resolved)

    bake_bases = {value for value in re.findall(r'BASE_IMAGE\s*=\s*"([^"]+)"', bake)}
    assert watched_bases == bake_bases, (
        f"docker-bake.hcl and the Dockerfile ARG default disagree: "
        f"bake={sorted(bake_bases)}, dockerfile={sorted(watched_bases)}"
    )


def test_every_sha_pinned_publisher_records_the_date_it_was_reviewed() -> None:
    """ADR-0009 requires implementation to resolve, review and RECORD the real SHA.

    The shipped guard enforces the shape -- 40 lowercase hex -- which a copied-from-
    anywhere SHA also satisfies. What makes the pin meaningful is that somebody looked
    at that commit and said when. Scope is derived from the SHA-pinned registry and from
    disk, so a second pinned publisher is covered without editing this.
    """
    # Anchored to the word. Both pinned references also carry the upstream COMMIT
    # date, so an unanchored date pattern passes with the review record deleted.
    reviewed = re.compile(r"reviewed\s+20[0-9]{2}-[01][0-9]-[0-3][0-9]\b")
    examined = 0
    for path in GOVERNED_DEFINITIONS:
        lines = path.read_text(encoding="utf-8").splitlines()
        for index, line in enumerate(lines):
            if not any(f"{action}@" in line for action in SHA_PINNED_ACTIONS):
                continue
            examined += 1
            preceding = "\n".join(lines[max(0, index - 12) : index])
            assert reviewed.search(preceding), (
                f"{path.name}:{index + 1}: a SHA-pinned publication credential handler "
                f"must record the date its commit was reviewed beside the `uses:` line "
                f"(ADR-0009)"
            )
    assert examined, "no SHA-pinned publisher was examined"
