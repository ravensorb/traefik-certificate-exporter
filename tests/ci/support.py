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
