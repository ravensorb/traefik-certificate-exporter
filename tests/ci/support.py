"""Shared machinery for the CI contract suite.

Extracted from `test_workflow_contracts.py` (BL-E008-010 phase 2): 96 of its 165 guards
depend on these eighteen names, and the dependency closure over them is exactly these
eighteen -- nothing else was pulled in. No guard moved in this commit and no behaviour
changed; the point is a boundary, not a rewrite.

Deliberately `tests/ci/support.py` rather than `tests/support.py`. That module is shared
with `tests/test_release_version.py`, which is not a CI-contract test, and workflow
concepts do not belong in it.
"""

from __future__ import annotations

import ast
import copy
import functools
import importlib.util
import json
import os
import re
import subprocess
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import yaml
from markdown_it import MarkdownIt

PROJECT_ROOT = Path(__file__).parents[2]


WORKFLOWS = PROJECT_ROOT / ".github" / "workflows"


ACTIONS = PROJECT_ROOT / ".github" / "actions"


FIXTURES = Path(__file__).parent / "fixtures" / "workflows"


# Every module of the contract suite. Derived from the directory rather than listed, so a
# module added by the BL-E008-010 split is covered the moment it exists -- which is the
# whole point: the three guards below read their own module today, and each would SILENTLY
# NARROW rather than fail if the suite were split beneath them.
CONTRACT_PACKAGE = Path(__file__).parent


def _contract_modules() -> tuple[Path, ...]:
    return tuple(sorted(CONTRACT_PACKAGE.glob("*.py")))


@functools.cache
def _contract_definitions() -> frozenset[str]:
    """Every top-level name defined anywhere in the contract suite.

    Read with `ast` rather than by importing, so this stays a fact about the source and
    cannot be perturbed by import order or by a module that fails to load.
    """
    names: set[str] = set()
    for module in _contract_modules():
        for node in ast.parse(module.read_text(encoding="utf-8")).body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names.add(node.name)
            elif isinstance(node, ast.Assign):
                names |= {
                    target.id for target in node.targets if isinstance(target, ast.Name)
                }
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                names.add(node.target.id)
    return frozenset(names)


@functools.cache
def _parsed_definition(path: Path) -> dict[str, Any]:
    # BaseLoader keeps GitHub's `on` key as a string instead of applying YAML 1.1's
    # obsolete yes/no boolean coercion.
    document = yaml.load(path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    assert isinstance(document, dict), path
    return document


def _load_document(path: Path) -> dict[str, Any]:
    """A parsed definition, parsed once per session and copied per caller.

    The copy is what makes the cache safe: several guards plant a violation by mutating
    the document they were handed, and a shared object would leak that into whichever
    test ran next -- a false green in the suite whose job is finding false greens.
    """
    return copy.deepcopy(_parsed_definition(path))


def _load_workflow(path: Path) -> dict[str, Any]:
    return _load_document(path)


def _load_fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _jobs(document: dict[str, Any]) -> dict[str, Any]:
    jobs = document.get("jobs") or {}
    assert isinstance(jobs, dict)
    return jobs


def _steps(document: dict[str, Any]) -> Iterator[dict[str, Any]]:
    """Yield every step of a workflow or of a composite action definition."""
    for job in _jobs(document).values():
        for step in job.get("steps") or []:
            yield step
    runs = document.get("runs")
    if isinstance(runs, dict):
        for step in runs.get("steps") or []:
            yield step


def _uncommented(command: str) -> str:
    """A `run:` body with its shell comment lines removed.

    Used only by the POSITIVE half of a guard -- "this mechanism is present". A
    commented-out `imagetools inspect` is text, not a mechanism, and satisfied the
    existence check before this. Prohibitions deliberately keep the raw body: a
    commented-out forbidden command is not a violation, and stripping there would
    weaken the rule rather than sharpen it.
    """
    return "\n".join(
        line for line in command.splitlines() if not line.lstrip().startswith("#")
    )


def _emitted(output: Path) -> dict[str, str]:
    """Parse a `GITHUB_OUTPUT` file, including the `key<<DELIMITER` heredoc form.

    The stable identity emits a newline-separated tag list, which the flat
    `line.split("=", 1)` parse silently mangles into three unusable entries.
    """
    values: dict[str, str] = {}
    lines = output.read_text(encoding="utf-8").splitlines()
    index = 0
    while index < len(lines):
        line = lines[index]
        index += 1
        if not line:
            continue
        name, _, value = line.partition("=")
        if "<<" in name:
            name, _, delimiter = name.partition("<<")
            collected = []
            while index < len(lines) and lines[index] != delimiter:
                collected.append(lines[index])
                index += 1
            index += 1
            values[name] = "\n".join(collected)
            continue
        values[name] = value
    return values


def _run_step(
    body: str, environment: dict[str, str], cwd: Path
) -> tuple[Any, dict[str, str]]:
    """Execute a workflow step's real `run:` body and return its emitted outputs."""
    output = Path(tempfile.mkdtemp()) / "github-output"
    output.touch()
    completed = subprocess.run(
        ["bash", "-c", body],
        cwd=cwd,
        env={
            "PATH": os.environ["PATH"],
            "GITHUB_OUTPUT": str(output),
            "GITHUB_WORKSPACE": str(PROJECT_ROOT),
            **environment,
        },
        capture_output=True,
        text=True,
        check=False,
    )
    return completed, _emitted(output)


def _step_with_id(path: Path, step_id: str) -> dict[str, Any]:
    step = next(
        (step for step in _steps(_load_workflow(path)) if step.get("id") == step_id),
        None,
    )
    # A bare `next()` raises StopIteration with no message, so deleting the step a guard
    # exists to examine reads as a broken test rather than as a caught violation -- and
    # a broken test gets "fixed" by deleting it.
    assert step is not None, (
        f"{path.name} has no step with id {step_id!r}; a guard that examines it was "
        f"about to examine nothing"
    )
    return step


def _git(repository: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repository), *arguments],
        capture_output=True,
        text=True,
        check=True,
    )
    return completed.stdout.strip()


VERIFIER_REFERENCE = "./.github/workflows/verify-build.yaml"


def _is_credential_bearing(job: dict[str, Any]) -> bool:
    """A job that holds, or can hold, a publication credential.

    Derived from capability rather than from job name or shape: any `secrets.*`
    expression anywhere in the job, or a permission that lets it push somewhere.
    """
    permissions = job.get("permissions")
    if isinstance(permissions, dict):
        for scope in ("packages", "id-token", "attestations"):
            if permissions.get(scope) == "write":
                return True
    if job.get("secrets") is not None:
        return True
    return "secrets." in json.dumps(job)


def _publishers(document: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Jobs that ship or can ship, derived from capability rather than from name.

    The same derivation `test_any_push_triggered_workflow_verifies_before_it_ships`
    uses, so a publisher added later is covered by the guards below without editing
    them -- which is the whole point of the scope attack in each anchor.
    """
    jobs = _jobs(document)
    called = {name: job.get("uses") for name, job in jobs.items()}
    return {
        name: job
        for name, job in jobs.items()
        if (
            isinstance(called.get(name), str)
            and called[name].startswith("./.github/workflows/")
            and called[name] != VERIFIER_REFERENCE
        )
        or _is_credential_bearing(job)
    }


RECOVERY_HEADING = "## Publication recovery"


# Events that start a run without a person or another workflow asking for it. These are
# the only ones that can race each other, and "each event has one owner" is a statement
# about exactly this set. `workflow_call` is excluded because a caller decides, and
# `workflow_dispatch` because a person does -- the verifier's direct dispatch entry point
# is governed by `test_verifier_supports_call_and_direct_dispatch_with_the_same_graph`.
NON_AUTOMATIC_EVENTS = frozenset({"workflow_call", "workflow_dispatch"})


# The only filter keys that divide the ref namespace, and therefore the only ones that
# can make two claims on the same event genuinely disjoint. `paths`, `paths-ignore` and
# `types` narrow *when* a workflow fires, never *which refs* it owns: two workflows
# filtered on different paths still both fire on a push that touches both. Letting them
# separate two claims is how a second owner of `push` slips past (review HIGH-1).
REF_NAMESPACE_KEYS = {
    "branches": "branches",
    "branches-ignore": "branches",
    "tags": "tags",
    "tags-ignore": "tags",
}


def _trigger_surface(document: dict[str, Any]) -> dict[str, dict[str, tuple[str, ...]]]:
    """The automatic event surface a workflow claims, as `{event: {namespace: globs}}`.

    Derived from the parsed `on:` block, never from the file's name. A name list is the
    hand-enumerated scope global rule 4 forbids, and it would have to be edited again by
    Epic 9; the trigger surface is the property that actually matters, and it is read
    from the same text GitHub reads.

    An event with no ref-namespace filter -- or filtered only by `paths`/`types`, or by
    an `-ignore` form, which describes what it does *not* take and so bounds nothing --
    claims every namespace, spelled as an empty pattern tuple.
    """
    triggers = document["on"]
    if isinstance(triggers, str):
        triggers = {triggers: None}
    if isinstance(triggers, list):
        triggers = dict.fromkeys(triggers)
    assert isinstance(triggers, dict), document
    surface: dict[str, dict[str, tuple[str, ...]]] = {}
    for event, configuration in triggers.items():
        if event in NON_AUTOMATIC_EVENTS:
            continue
        claimed: dict[str, list[str]] = {}
        if isinstance(configuration, dict):
            for key, namespace in REF_NAMESPACE_KEYS.items():
                values = configuration.get(key) or []
                if not values:
                    continue
                # An `-ignore` list names what is excluded, so what remains is the whole
                # namespace minus an unknown set: treat it as unbounded.
                patterns = [] if key.endswith("-ignore") else [str(v) for v in values]
                claimed.setdefault(namespace, []).extend(patterns)
        surface[event] = (
            {name: tuple(globs) for name, globs in claimed.items()}
            if claimed
            else dict.fromkeys(set(REF_NAMESPACE_KEYS.values()), ())
        )
    return surface


# The four actions CI-AR38 permits the operations guide to name only as prohibited,
# matched at the width of the vocabulary an operator would actually use. Review HIGH-2
# demonstrated the first draft's narrower patterns accepting `remove the published
# version`, `yank the version`, `replace the published image tag`, `push the tag again
# with -f` and `re-run the workflow from the start` -- every one of them the prohibited
# action under a different verb. Each row below is proven by a plant.
PROHIBITED_RECOVERY_ACTIONS = (
    (
        "whole-workflow rerun",
        re.compile(
            r"re-?run(?:ning)?\s+(?:all\b|every\b"
            r"|the\s+(?:whole|entire|full|complete)\b"
            r"|the\s+(?:run|workflow|pipeline|job list)\b)"
            r"|whole[- ](?:workflow|run)\s+re-?run"
            r"|re-?(?:trigger|dispatch|launch)\s+the\s+(?:run|workflow)"
            r"|trigger\s+the\s+workflow\s+again",
            re.IGNORECASE,
        ),
    ),
    (
        "force update",
        re.compile(
            r"--force|(?<![\w-])-f(?![\w-])|force[- ](?:push|updat|overwrit|mov|creat)"
            r"|\bforce-?(?:push|updat)\w*",
            re.IGNORECASE,
        ),
    ),
    (
        "deletion",
        re.compile(
            r"\b(?:delet(?:e|es|ed|ing|ion)|remov(?:e|es|ed|ing|al)|purg(?:e|es|ed|ing)"
            r"|yank(?:s|ed|ing)?|drop(?:s|ped|ping)?)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "overwrite",
        re.compile(
            r"\b(?:overwrit(?:e|es|ing|ten)|replac(?:e|es|ed|ing)"
            r"|re-?(?:upload|push|publish)(?:es|ed|ing)?)\b",
            re.IGNORECASE,
        ),
    ),
)


# What makes a mention a prohibition rather than an instruction. Deliberately narrow:
# review MEDIUM-1 showed that admitting the ordinary negations (`is not`, `does not`,
# `cannot`) lets an unrelated conditional excuse an instruction -- "If the release is not
# yet consumed, delete it and republish" passed. Every marker here is prohibitive on its
# own, whatever the rest of the sentence says.
PROHIBITION_MARKER = re.compile(
    r"\b(?:never|not\s+a\s+recovery|prohibited|forbidden|must\s+not|may\s+not"
    r"|do(?:es)?\s+not\s+prescribe|refus\w*|unsupported|instead\s+of"
    r"|rather\s+than)\b",
    re.IGNORECASE,
)


def _statements(text: str) -> list[str]:
    """The units a prohibition has to attach to.

    Block structure comes from `markdown-it-py`, the CommonMark parser already in this
    project's dependency tree -- global rule 1, and the first draft's hand-written block
    splitter treated a line inside a fenced block as prose (review MEDIUM-3). A table
    *row* is one unit rather than one cell, because the prohibition lives in the row's
    other columns.

    Within a block, statements are split on sentence punctuation by a deliberately naive
    rule. It gets abbreviations wrong -- `e.g. ` splits early -- and that is a knowingly
    accepted limitation because its failure direction is safe: a statement split too
    early is a *smaller* unit, so a marker in the discarded half no longer excuses a
    matched verb. It can make this guard stricter, never laxer.
    """
    tokens = MarkdownIt("commonmark").enable("table").parse(text)
    blocks: list[str] = []
    row: list[str] | None = None
    for token in tokens:
        if token.type == "tr_open":
            row = []
        elif token.type == "tr_close" and row is not None:
            blocks.append(" ".join(row))
            row = None
        elif token.type == "inline":
            if row is not None:
                row.append(token.content)
            else:
                blocks.append(token.content)
        # `fence` and `code_block` carry their content on the token itself and are
        # skipped outright: a shell transcript is not a runbook instruction.
    statements: list[str] = []
    for block in blocks:
        collapsed = " ".join(block.split())
        statements.extend(
            part for part in re.split(r"(?<=[.!?])\s+", collapsed) if part.strip()
        )
    return statements


def _runbook_findings(text: str) -> list[str]:
    return [
        f"{name} appears as an instruction, not a prohibition: {statement!r}"
        for statement in _statements(text)
        for name, pattern in PROHIBITED_RECOVERY_ACTIONS
        if pattern.search(statement) and not PROHIBITION_MARKER.search(statement)
    ]


# The governed definitions by name. Every subject module addresses some of these,
# so they live with the loaders rather than in whichever module happened to need
# one first (BL-E008-010 phase 3).
CI_WORKFLOW = WORKFLOWS / "ci.yaml"


VERIFY_WORKFLOW = WORKFLOWS / "verify-build.yaml"


SETUP_ACTION = ACTIONS / "setup-poetry-python" / "action.yml"


BUNDLE_ACTION = ACTIONS / "verified-bundle" / "action.yml"


CODEOWNERS = PROJECT_ROOT / ".github" / "CODEOWNERS"


SCRIPTS = PROJECT_ROOT / "scripts"


DEV_WORKFLOW = WORKFLOWS / "dev.yaml"


PUBLISH_IMAGE_WORKFLOW = WORKFLOWS / "publish-image.yaml"


RELEASE_WORKFLOW = WORKFLOWS / "release.yaml"


# The governed scope, and the three registries of granted privilege. Data rather than
# rules: the action-policy guards, the finalization guards and the meta-guard all read
# them, so they sit here rather than in whichever subject module reads them most.
def _governed_definitions() -> tuple[Path, ...]:
    """Tier 1 scope, derived from the filesystem rather than enumerated by hand.

    The previous hand-kept 2-tuple examined ci.yaml and verify-build.yaml only, so the
    four credential-bearing workflows and every composite action were governed by
    nothing. `test_governance_scope_is_derived_from_disk` attacks this scope directly.
    """
    return tuple(sorted(WORKFLOWS.glob("*.yaml")) + sorted(ACTIONS.rglob("action.yml")))


GOVERNED_DEFINITIONS = _governed_definitions()


# Jobs permitted to write repository contents -- push refs, or create a forge Release.
# A registry of granted exceptions, not a derived scope: adding a name here IS the grant,
# and each needs an ADR. ADR-0006 draws the line at *identity* -- the committed version
# and the exact vX.Y.Z tag are chosen only by the local guarded transaction. A finalizer
# attaching a Release, its assets, or moving aliases to an identity already decided is not
# a second version authority. Empty until Epic 8 registers one.
# `(workflow filename, job name)` pairs, NOT bare job names. A bare-name registry matches
# across every workflow, so granting `finalize` for release.yaml would silently grant the
# same name in dev.yaml -- and Epic 8 creates a finalizer in both files (gate finding F6).
# Widened before the first entry is added, while the set is still empty and the change is
# free.
#
# Epic 8 story E008-S01-003 registers three, and each entry is a deliberate grant:
#
# * `("release.yaml", "finalize")` -- creates the forge Release through
#   `LiquidLogicLabs/git-action-release@v2` (ADR-0010) and advances `vMAJOR` /
#   `vMAJOR.MINOR` through `LiquidLogicLabs/git-action-tag-floating-version@v2`
#   (ADR-0006 as amended). It is the only job in the repository declaring
#   `contents: write`, and it holds no registry credential at all.
# * `("release.yaml", "finalize-image-aliases")` -- points the `MAJOR.MINOR`, `MAJOR`
#   and `latest` image names at the digest that was already published. It writes no
#   ref and declares no `contents: write`; it is registered because it moves an alias,
#   and alias ownership is what the sole-ownership guard below asserts.
# * `("dev.yaml", "finalize-dev-alias")` -- points the `dev` image name at the
#   published digest, after proving the candidate is still the protected default
#   branch's head. Also no ref write.
#
# ADR-0006 draws the line at identity, and none of the three chooses a version: the
# committed version and the exact `vX.Y.Z` tag are still the local guarded
# transaction's alone. A Release and an alias attach to an identity already decided.
RELEASE_FINALIZER_JOBS: frozenset[tuple[str, str]] = frozenset(
    {
        ("release.yaml", "finalize"),
        ("release.yaml", "finalize-image-aliases"),
        ("dev.yaml", "finalize-dev-alias"),
    }
)


# The exception to the floating-major default, and a registry of granted exceptions
# rather than a derived scope: adding an entry here IS the grant, and each needs an ADR.
#
# A floating major is a *moving* ref. For most actions that is the right trade -- a
# security fix ships without a manifest edit. For an action handed a publication
# credential it inverts: whoever can move the branch can exfiltrate the token on the next
# run. CI-AR4 sets floating-major as the default for approved owners; CI-AR38 requires a
# reviewed full commit SHA for the PyPI publisher. Both hold, because they are answering
# different questions -- convenience of upgrade versus blast radius of compromise -- and
# the split is per action, not per owner. `pypa` stays an approved owner; only this one
# action of theirs is pinned harder.
SHA_PINNED_ACTIONS = frozenset({"pypa/gh-action-pypi-publish"})


# The inverse registry: actions that ARE handed a publication credential and stay on a
# floating major anyway. Not a claim that they are safe -- a registry of accepted risk,
# and the reason is the entry. Whoever can move one of these refs can exfiltrate the
# credential it receives on the next run, with no diff in this repository to review.
#
# Adding an entry IS the acceptance, and each needs an ADR, exactly as adding to
# SHA_PINNED_ACTIONS is the grant (ADR-0009). Every entry here was found by
# `_credential_handling_actions`, which derives candidates from what a step is handed;
# the previous reach guard matched the words "pypi" or "publish" in an action's name and
# saw none of them.
CREDENTIAL_ACTIONS_ON_MOVING_REFS: dict[str, str] = {
    # Maintainer-owned org (confirmed with the maintainer at E008 sprint closure; ADR-0010
    # called this "first-party in practice" and that is accurate). The residual risk is
    # the maintainer's own account rather than a third party's, and the floating major is
    # what makes an upstream fix reach this repository without a manifest edit.
    "LiquidLogicLabs/git-action-release": (
        "receives contents: write GITHUB_TOKEN as `token`; maintainer-owned org"
    ),
    "LiquidLogicLabs/git-action-tag-floating-version": (
        "receives GITHUB_TOKEN through GIT_CONFIG_VALUE_0; maintainer-owned org"
    ),
    "LiquidLogicLabs/git-action-docker-test": (
        "runs after both registry logins, so it can read ~/.docker/config.json; "
        "maintainer-owned org"
    ),
    # An approved owner under CI-AR4, and the one action here nobody in this project
    # controls. Kept floating on the ordinary CI-AR4 grounds -- a large, widely audited
    # owner whose security fixes should arrive without a manifest edit.
    "docker/login-action": "receives DOCKERHUB_USERNAME and DOCKERHUB_TOKEN",
    # Ambient holders, added at epic closure when the derivation learned to see them.
    # None of these is *passed* a credential; each runs in a job whose token or OIDC
    # identity it could use. All four are from approved owners on the platform's own
    # namespaces, and all four are the most-audited actions in the ecosystem -- but the
    # policy says pinned or recorded, and silence is the one outcome it does not allow.
    "actions/checkout": (
        "runs in every credentialed job, so it holds that job's token ambiently; "
        "first-party GitHub"
    ),
    "actions/attest-build-provenance": (
        "runs in the attest job, which holds id-token: write and attestations: write; "
        "first-party GitHub"
    ),
    "docker/setup-buildx-action": (
        "runs in registry jobs holding packages: write; approved owner"
    ),
    "docker/setup-qemu-action": (
        "runs in the image job holding packages: write; approved owner"
    ),
}


# Tier 2 scope. Tier 1 (approved owners, floating major aliases, no interpolated
# `uses:`) applies to every governed definition. The credential prohibitions below
# apply only to definitions that can execute fork-authored code, because those must
# never hold a publishing capability -- the publisher workflows legitimately do.
#
# This was a hand-kept `(CI_WORKFLOW, VERIFY_WORKFLOW)` tuple: the *same* 2-tuple that
# tier 1 replaced with a filesystem derivation, left eight lines below the derivation
# that replaced it, carrying the rules that matter more. A second `pull_request`
# workflow on a disjoint branch filter -- a shape the topology guard asserts lawful --
# ran fork code on a self-hosted runner with `packages: write` and a registry login,
# and not one guard fired. The set is now derived; the seed is the event.
FORK_EVENTS = frozenset({"pull_request", "pull_request_target"})


def _action_references(path: Path) -> list[str]:
    """Every `uses:` value in a definition, read from the parsed document.

    Reading these with a line regex silently misses the `- uses:` list form, which is
    how most steps in this repository are written -- and therefore misses most of what
    the policy is supposed to examine.
    """
    document = _load_document(path)
    references = [
        str(job["uses"]) for job in _jobs(document).values() if "uses" in job
    ] + [str(step["uses"]) for step in _steps(document) if "uses" in step]
    return references


def _local_references(path: Path) -> set[Path]:
    """Every local workflow or composite action a definition names with `uses: ./...`.

    Resolved from the file's own text, so a directory reference picks up its
    `action.yml` the way the runner does.
    """
    found: set[Path] = set()
    for reference in _action_references(path):
        if not reference.startswith("./"):
            continue
        target = PROJECT_ROOT / reference.removeprefix("./")
        found.add(target / "action.yml" if target.is_dir() else target)
    return found


def _fork_facing_workflow_names(documents: dict[str, dict[str, Any]]) -> set[str]:
    """Workflow filenames that can execute fork-authored code.

    Seeded from whoever owns a `pull_request*` event and closed over local
    `workflow_call`s, because a reusable workflow inherits its caller's trust boundary.
    Pure over parsed documents so the scope attack below runs through this exact code.
    """
    reachable = {
        name
        for name, document in documents.items()
        if _declared_events(document) & FORK_EVENTS
    }
    frontier = list(reachable)
    while frontier:
        document = documents.get(frontier.pop())
        if document is None:
            continue
        for job in _jobs(document).values():
            used = job.get("uses")
            if isinstance(used, str) and used.startswith("./.github/workflows/"):
                name = used.rsplit("/", 1)[-1]
                if name not in reachable:
                    reachable.add(name)
                    frontier.append(name)
    return reachable


def _fork_facing_definitions() -> tuple[Path, ...]:
    """The fork-facing workflows plus every composite action they reach, from disk."""
    documents = {path.name: _load_workflow(path) for path in WORKFLOWS.glob("*.yaml")}
    resolved: set[Path] = set()
    frontier = [WORKFLOWS / name for name in _fork_facing_workflow_names(documents)]
    while frontier:
        path = frontier.pop()
        if path in resolved or not path.exists():
            continue
        resolved.add(path)
        frontier.extend(_local_references(path))
    return tuple(sorted(resolved))


def _declared_events(document: dict[str, Any]) -> set[str]:
    triggers = document["on"]
    if isinstance(triggers, str):
        return {triggers}
    return set(triggers)


def _transitive_needs(jobs: dict[str, Any], job_name: str) -> set[str]:
    """Every job `job_name` depends on, directly or through another job."""
    resolved: set[str] = set()
    pending = [job_name]
    while pending:
        current = pending.pop()
        needs = jobs.get(current, {}).get("needs") or []
        if isinstance(needs, str):
            needs = [needs]
        for dependency in needs:
            if dependency not in resolved:
                resolved.add(dependency)
                pending.append(dependency)
    return resolved


def _workflow_documents() -> dict[str, dict[str, Any]]:
    """Every governed workflow, parsed, keyed by filename."""
    return {
        path.name: _load_workflow(path) for path in sorted(WORKFLOWS.glob("*.yaml"))
    }


# `ACT` as a whole word. `\b` is what keeps `GITHUB_ACTIONS` and `actions/checkout` out
# of it; the previous form was a bare `"ACT" not in text` substring test on one file.
ACT_BRANCH = re.compile(r"\bACT\b")


def _load_committed_versions() -> Any:
    """Load the committed-version authority shared with the workflow plan jobs."""
    location = PROJECT_ROOT / "scripts" / "committed_versions.py"
    spec = importlib.util.spec_from_file_location("committed_versions", location)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


committed_versions = _load_committed_versions()


# The one action permitted to create a forge Release (ADR-0010). It speaks GitHub's and
# Gitea's release APIs from a single step, so `release.yaml` carries no forge branch and
# E009 inherits the Gitea path unchanged. Pinned `@v2` -- never `@v2.0`, which is stale.
APPROVED_RELEASE_ACTION = "LiquidLogicLabs/git-action-release"


def _governed_step_groups() -> list[tuple[str, str, list[dict[str, Any]]]]:
    """(definition, job-or-`runs`, steps) across every governed definition.

    A composite action's steps run *inside* the calling job and hold that job's
    authority, so any prohibition that examines only `.github/workflows/*.yaml` is
    defeated by moving the forbidden step one file across. `release.yaml`'s `finalize`
    holds `contents: write` and calls `./.github/actions/verified-bundle`, so a
    `git push --force`, a `gh release create` or an `imagetools create` planted in that
    composite ran with the finalizer's authority and left the suite green.

    A composite action can never be a registered finalizer -- registration is
    `(workflow, job)` -- so for these guards its steps are always outside the grant.
    """
    groups: list[tuple[str, str, list[dict[str, Any]]]] = []
    for path in GOVERNED_DEFINITIONS:
        name = str(path.relative_to(PROJECT_ROOT))
        document = _load_document(path)
        if "jobs" in document:
            for job_name, job in _jobs(document).items():
                groups.append((name, job_name, list(job.get("steps") or [])))
        else:
            runs = document.get("runs") or {}
            groups.append((name, "runs", list(runs.get("steps") or [])))
    return groups


REGISTRY_LOGIN_ACTION = "docker/login-action"


def _is_publishing_step(step: dict[str, Any]) -> bool:
    """The step that actually ships. Everything before it is 'pre-upload'."""
    uses = str(step.get("uses", ""))
    if uses.startswith(("pypa/gh-action-pypi-publish", APPROVED_RELEASE_ACTION)):
        return True
    command = str(step.get("run", ""))
    return bool(
        re.search(
            r"(?:buildx\s+bake|docker\s+push|buildx\s+build[^\n]*--push|twine\s+upload)",
            command,
        )
    )


# Every spelling of "ask a registry what is there". One authority, consumed by the alias
# ordering guard below and by the placement guard story E008-S01-001 added: two hand-kept
# copies of the same pattern list would drift, and the copy nobody updated would be the
# one still reporting success.
REGISTRY_READ_COMMANDS = (
    r"\bdocker\s+manifest\s+inspect\b",
    r"\bbuildx\s+imagetools\s+inspect\b",
    r"\bskopeo\s+(?:inspect|list-tags)\b",
    r"\bcrane\s+(?:ls|digest|manifest)\b",
)


# Moving a floating major is a non-fast-forward ref update, and
# LiquidLogicLabs/git-action-tag-floating-version does it. Unlike git-action-release it
# needs no forge backend: a tag is a git concept, not a forge one, so the action pushes
# refs with plain git and is portable to Gitea for free. A Release is the opposite -- a
# forge object -- which is why that one needs per-API handling (ADR-0010).
APPROVED_ALIAS_ACTION = "LiquidLogicLabs/git-action-tag-floating-version"


PUBLISH_IMAGE_REFERENCE = "./.github/workflows/publish-image.yaml"


REQUIRED_IMAGE_PLATFORMS = ("linux/amd64", "linux/arm64")


STEP_OUTPUT_REFERENCE = re.compile(r"steps\.([A-Za-z0-9_-]+)\.outputs\.")


def _producing_step(
    path: Path, job_name: str, job: dict[str, Any], output_name: str
) -> dict[str, Any]:
    """The step a job's named output is taken from, resolved through the expression."""
    reference = STEP_OUTPUT_REFERENCE.search(
        str((job.get("outputs") or {})[output_name])
    )
    assert reference, (
        f"{path.name}: job {job_name!r} does not take {output_name!r} from a step output"
    )
    step = next(
        (
            candidate
            for candidate in (job.get("steps") or [])
            if candidate.get("id") == reference.group(1)
        ),
        None,
    )
    assert step is not None, (
        f"{path.name}: job {job_name!r} takes {output_name!r} from step "
        f"{reference.group(1)!r}, which does not exist"
    )
    return step


def _publishing_workflows() -> list[Path]:
    """Every workflow that owns an automatic event and publishes something.

    The scope for the destination-agnostic rules: full-history checkouts, credential
    disjointness, re-reading the tag set before upload, gating optional credentials,
    the evidence job, the finalizer, the run summary.

    Those rules used to take their scope from `_image_channel_workflows` below, which
    derives from *whether the workflow publishes a container image*. A `nightly.yaml`
    with a single PyPI job -- `id-token: write`, `fetch-depth: 1`, no tag re-read, no
    finalizer, ungated optional credentials -- ships no image, so none of the seven
    looked at it and the suite stayed green. Publishing is the property that matters
    here, not what is published.
    """
    return [
        path
        for path in sorted(WORKFLOWS.glob("*.yaml"))
        # Any entry point that publishes. `_trigger_surface` excludes
        # `workflow_dispatch`, which is right for the event-ownership partition -- a
        # person asked for it, so it races nothing -- and wrong here: a
        # manually-dispatched publisher holding `id-token: write` and running
        # `twine upload` escaped all seven of these rules. `workflow_call` is the one
        # exemption, because a reusable file's caller owns the gate.
        if (_declared_events(_load_workflow(path)) - {"workflow_call"})
        and _publishers(_load_workflow(path))
    ]


def _image_channel_workflows() -> list[Path]:
    """The subset that publishes an image through the shared reusable publisher.

    Derived from who calls it, never enumerated: release.yaml is covered the day it
    lands, without an edit here. Kept narrow deliberately -- it is the right scope for
    rules about the image wiring (platform inputs, digest and platform outputs,
    consuming an inspection rather than performing one) and the wrong scope for
    anything that is true of publishing in general.
    """
    return [
        path
        for path in sorted(WORKFLOWS.glob("*.yaml"))
        if any(
            job.get("uses") == PUBLISH_IMAGE_REFERENCE
            for job in _jobs(_load_workflow(path)).values()
        )
    ]


# How the annotated-tag membership decision is LOCATED in a `run:` body. `%(objecttype)`
# is the annotated-object filter itself: a step that peels tags without it accepts a
# lightweight `v1.2.3` pushed by hand, which is the release-breaking defect story 002
# recorded as HIGH-1. Matching the mechanism rather than a step name means a re-check
# that was gutted is no longer found at all.
TAG_MEMBERSHIP_MARKER = "%(objecttype)"


# The stable channel's re-check names the tag it was handed; the development channel's
# enumerates every tag on the commit. Two spellings of one relation, and each is the
# marker for its own channel.
STABLE_RECHECK_MARKER = "refs/tags/$RELEASE_TAG"
