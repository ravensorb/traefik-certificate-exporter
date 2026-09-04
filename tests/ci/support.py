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
import subprocess
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import yaml

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
