"""Guards over the guards: is a scope derived, and is a privilege written down.

BL-E008-010 phase 3. This module holds the mechanical answer to the defect that dominated
Epic 8 -- a guard whose rule is right and whose SET is a hand-written list. Eleven
instances at sprint closure, four more inside the fixes for those eleven, after the class
had been named twenty times across three reviews. Global rule 4 was the one rule in this
project with nothing but attention behind it.

`_module_scope_literals` reads every module in this package rather than its own file, and
that is load-bearing: the version that read `__file__` would have passed while examining a
fraction of the suite the moment the split it now supervises took place.
"""

from __future__ import annotations

import ast
import functools
from pathlib import Path

from tests.ci.support import (
    ACTIONS,
    CODEOWNERS,
    CREDENTIAL_ACTIONS_ON_MOVING_REFS,
    GOVERNED_DEFINITIONS,
    PROJECT_ROOT,
    RELEASE_FINALIZER_JOBS,
    SHA_PINNED_ACTIONS,
    WORKFLOWS,
    _contract_modules,
    _fork_facing_definitions,
    _load_document,
)
from tests.support import tracked_text_files

# ---------------------------------------------------------------------------
# The meta-guard (retrospective action item A1).
#
# This epic's dominant defect was a guard whose RULE is correct and whose SET is a
# hand-written list: eleven instances at sprint closure, four more inside the fixes for
# those eleven, and it recurred after being named twenty times across three reviews.
# Global rule 4 was the one rule in this project with nothing mechanical behind it,
# which is exactly the outcome global rule 3 predicts for a rule that lives in prose.
#
# The distinction it enforces is not "no literals". Most literals here are vocabulary --
# forbidden substrings, required platforms, command patterns -- and those are the rule
# itself rather than the set it runs over. What must never be hand-written is a list of
# things THE REPOSITORY CONTAINS, because the filesystem can produce that list and a
# hand-written copy of it goes stale silently.
#
# `SCOPE_REGISTRIES` is the escape hatch, and it is the same shape as
# `SHA_PINNED_ACTIONS` and `CREDENTIAL_ACTIONS_ON_MOVING_REFS`: an entry IS the decision,
# it carries its reason, an ADR must name it, and a stale entry fails. The difference
# between a deliberate registry and an accidental one becomes declared instead of
# inferred -- which is precisely what `SECRET_FREE_WORKFLOWS` needed and did not have.
SCOPE_REGISTRIES: dict[str, str] = {
    "RELEASE_FINALIZER_JOBS": (
        "ADR-0006: adding a (workflow, job) pair IS the grant to write refs or create a "
        "Release. It records a decision rather than a fact about the tree, so it cannot "
        "be derived -- deriving it from 'jobs that write refs' would make every new "
        "writer self-authorising, which is the opposite of a grant."
    ),
}


def _module_scope_literals(source: str | None = None) -> dict[str, list[str]]:
    """Module-level literals that enumerate names this repository contains.

    Pure over source text so the plants below run through this exact code.

    A value built by calling a function is derived and never appears here; only literal
    displays, and `frozenset(...)`/`tuple(...)` wrapping one, are candidates. Every
    string reachable from the value is collected, including through a reference to
    another module-level constant -- `(CI_WORKFLOW, VERIFY_WORKFLOW)` is a list of two
    filenames however indirectly it spells them, and that indirection is what made the
    original instance read as principled.
    """
    if source is None:
        # Every module, not this one. Reading `__file__` here would leave the guard
        # green while examining a fraction of the suite the moment it is split.
        flagged: dict[str, list[str]] = {}
        for module in _contract_modules():
            flagged |= _module_scope_literals(module.read_text(encoding="utf-8"))
        return flagged

    def literal_strings(node: ast.AST, bindings: dict[str, ast.AST]) -> set[str]:
        found = {
            child.value
            for child in ast.walk(node)
            if isinstance(child, ast.Constant) and isinstance(child.value, str)
        }
        for child in ast.walk(node):
            if isinstance(child, ast.Name) and child.id in bindings:
                found |= {
                    inner.value
                    for inner in ast.walk(bindings[child.id])
                    if isinstance(inner, ast.Constant) and isinstance(inner.value, str)
                }
        return found

    bindings: dict[str, ast.AST] = {}
    for statement in ast.parse(source).body:
        targets = (
            statement.targets
            if isinstance(statement, ast.Assign)
            else [statement.target]
            if isinstance(statement, ast.AnnAssign)
            else []
        )
        for target in targets:
            if isinstance(target, ast.Name) and statement.value is not None:
                bindings[target.id] = statement.value

    strong, weak = _repository_names()
    flagged: dict[str, list[str]] = {}
    for name, value in bindings.items():
        if not name.isupper():
            continue
        display = value
        if (
            isinstance(display, ast.Call)
            and isinstance(display.func, ast.Name)
            and display.func.id in {"frozenset", "set", "tuple", "list"}
        ):
            display = display.args[0] if display.args else None
        if not isinstance(display, (ast.Set, ast.Tuple, ast.List, ast.Dict)):
            continue
        strings = literal_strings(display, bindings)
        if not strings:
            continue
        paths = sorted(strings & strong)
        jobs = sorted(strings & weak)
        # A path names a file the filesystem could have listed. A set made ENTIRELY of
        # job names is a job scope. A stray word that merely collides with a job name --
        # "image" is both a destination class and a job -- is neither, which is why the
        # weak signal requires the whole collection rather than one element.
        if paths:
            flagged[name] = paths
        elif jobs and set(jobs) == strings:
            flagged[name] = jobs
    return flagged


@functools.cache
def _repository_names() -> tuple[frozenset[str], frozenset[str]]:
    """(paths and filenames, job names) -- everything the filesystem could enumerate."""
    strong = {str(path.relative_to(PROJECT_ROOT)) for path in GOVERNED_DEFINITIONS}
    strong |= {path.name for path in GOVERNED_DEFINITIONS}
    weak: set[str] = set()
    for path in GOVERNED_DEFINITIONS:
        document = _load_document(path)
        if isinstance(document.get("jobs"), dict):
            weak |= set(document["jobs"])
    for relative, _ in tracked_text_files():
        strong.add(relative)
        strong.add(Path(relative).name)
    return frozenset(strong), frozenset(weak - strong)


def test_no_guard_takes_its_scope_from_a_hand_written_list_of_what_the_repo_contains() -> (
    None
):
    """Retrospective action item A1, and the reason it stopped being deferred.

    Validated against history rather than asserted: run over
    `tests/ci/test_workflow_contracts.py` at `6a76559` and at `df6e5ed` this flags
    `SECRET_FREE_WORKFLOWS: ['ci.yaml', 'verify-build.yaml']` -- the tuple that carried
    the fork-safety prohibitions, sitting eight lines below the filesystem derivation
    that had replaced its twin, and which took a reviewer's planted violation to find.
    At `df6e5ed` it also flags `INVOCATION_SCAN_EXEMPTIONS`. Both would have been
    refused at the moment they were written.
    """
    flagged = _module_scope_literals()
    for name, enumerated in sorted(flagged.items()):
        assert name in SCOPE_REGISTRIES, (
            f"{name} = {enumerated} is a hand-written list of things this repository "
            f"contains, and something takes its scope from it. Derive it from the "
            f"filesystem or the parsed documents, or -- if it records a DECISION rather "
            f"than a fact about the tree -- register it in SCOPE_REGISTRIES with the "
            f"reason and an ADR that names it."
        )
    stale = set(SCOPE_REGISTRIES) - set(flagged)
    assert not stale, (
        f"{sorted(stale)} are registered as deliberate scopes but no longer enumerate "
        f"anything in this repository; a registry that outlives its entries stops "
        f"being read"
    )
    decisions = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted((PROJECT_ROOT / "docs" / "adr").glob("*.md"))
    )
    for name in sorted(SCOPE_REGISTRIES):
        assert name in decisions, (
            f"{name} is registered as a deliberate hand-kept scope and no ADR names it"
        )


def test_the_meta_guard_catches_the_defect_it_was_written_for() -> None:
    """The plant, and it is the epic's own defect in its original spelling.

    A tuple of two `Path` constants, each built from a workflow filename -- exactly how
    `SECRET_FREE_WORKFLOWS` was written, and the indirection through a `Path` is what
    made it read as principled rather than as a hand-written list.
    """
    planted = _module_scope_literals(
        'WORKFLOWS = PROJECT_ROOT / ".github" / "workflows"\n'
        'CI_WORKFLOW = WORKFLOWS / "ci.yaml"\n'
        'VERIFY_WORKFLOW = WORKFLOWS / "verify-build.yaml"\n'
        "SECRET_FREE_WORKFLOWS = (CI_WORKFLOW, VERIFY_WORKFLOW)\n"
    )
    assert "SECRET_FREE_WORKFLOWS" in planted, planted
    assert planted["SECRET_FREE_WORKFLOWS"] == ["ci.yaml", "verify-build.yaml"]

    # A bare list of job names is the same defect without a filename in sight.
    planted = _module_scope_literals('GATES = ("finalize", "finalize-image-aliases")\n')
    assert "GATES" in planted, planted

    # Vocabulary is not a scope. These are the rule, not the set it runs over.
    for benign in (
        'SECRET_FREE_PROHIBITIONS = ("secrets:", "id-token: write")\n',
        'REQUIRED_IMAGE_PLATFORMS = ("linux/amd64", "linux/arm64")\n',
        'DESTINATION_CLASSES = ("image", "package")\n',
    ):
        assert not _module_scope_literals(benign), benign

    # And a derived value never reaches the check at all.
    assert not _module_scope_literals("GOVERNED = _governed_definitions()\n")


def test_governance_scope_is_derived_from_disk() -> None:
    """The guard must prove its reach, not only its rule.

    Adding a workflow or composite action must not be able to leave it ungoverned, so
    the scope is compared against the on-disk listing rather than a literal list.
    """
    assert GOVERNED_DEFINITIONS

    workflow_files = {path for path in WORKFLOWS.iterdir() if path.is_file()}
    action_files = {
        path
        for path in ACTIONS.rglob("*")
        if path.is_file() and path.name in {"action.yml", "action.yaml"}
    }
    # A `.yml` workflow, or an `action.yaml`, would be on disk yet outside the globs
    # that build the governed set. Either must fail here rather than pass unexamined.
    assert set(GOVERNED_DEFINITIONS) == workflow_files | action_files

    # Tier 2 is a proper subset of tier 1: every fork-facing definition is also
    # governed, and the tier-2 set is smaller because publishers are excluded.
    assert set(_fork_facing_definitions()) < set(GOVERNED_DEFINITIONS)
    for path in GOVERNED_DEFINITIONS:
        assert _load_document(path), path


def _codeowner_patterns() -> set[str]:
    return {
        line.split()[0]
        for line in CODEOWNERS.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }


def test_the_authority_surfaces_are_owned() -> None:
    """Every privilege in this system is a hand-kept list, and the lists live in files
    the same commit can edit alongside the guards that read them.

    `RELEASE_FINALIZER_JOBS` decides which job may write a ref or create a Release.
    `SHA_PINNED_ACTIONS` and `CREDENTIAL_ACTIONS_ON_MOVING_REFS` decide how much of the
    supply chain is pinned. The workflows decide which credentials exist at all. Until
    CODEOWNERS existed, one approval could widen a grant and relax the guard reporting
    on it in the same diff.

    **The required set below is a registry, not a derivation, and the entries are
    literals.** An earlier version of this docstring claimed the set was "derived from
    where those things actually live, so a registry moved to a new file is covered" --
    it was not: only `tests/` is computed, and moving `RELEASE_FINALIZER_JOBS` to
    `scripts/` would satisfy this guard while leaving the registry unowned. Each entry
    is here because someone decided that surface grants authority; adding one is that
    decision, the same way adding to `SHA_PINNED_ACTIONS` is.

    **This file enforces nothing, deliberately.** Branch protection requiring code-owner
    review was declined at E008 closure: a sole-developer project has no second reviewer,
    so the control would either block every change or be self-approved. What CODEOWNERS
    is here for is the record of which surfaces grant authority, and this guard keeps
    that record complete. No test can see the branch-protection setting either way
    (BL-E008-007, resolved as accepted).
    """
    patterns = _codeowner_patterns()
    assert patterns, "CODEOWNERS assigns no owners"
    required = {
        f"/{Path(__file__).relative_to(PROJECT_ROOT).parts[0]}/",  # the registries' home
        "/.github/",  # every workflow and composite action
        "/docs/adr/",  # the decisions the registries point at
        "/.pre-commit-config.yaml",  # which gates run
    }
    # The trees the agents are told to follow verbatim, which no linting gate examines.
    required |= {"/.agents/", "/.claude/", "/AGENTS.md"}
    missing = {
        entry
        for entry in required
        if not any(
            pattern.startswith(entry) or entry.startswith(pattern)
            for pattern in patterns
        )
    }
    assert not missing, f"authority surfaces with no code owner: {sorted(missing)}"


def test_every_granted_privilege_points_at_a_decision() -> None:
    """ADR-0006 and ADR-0009 both say an entry in their registry needs an ADR. Neither
    said it in a way anything could check, so an entry added without one read exactly
    like an entry with one.

    Scope is the registries themselves, so a fourth entry is covered without an edit
    here. The check is that *some* ADR names it -- a weak claim deliberately: it catches
    the entry nobody wrote down, and does not pretend to judge whether the reasoning is
    good.
    """
    decisions = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted((PROJECT_ROOT / "docs" / "adr").glob("*.md"))
    )
    assert decisions, "no ADRs on disk; this guard examined nothing"
    granted = (
        {job for _, job in RELEASE_FINALIZER_JOBS}
        | set(SHA_PINNED_ACTIONS)
        | set(CREDENTIAL_ACTIONS_ON_MOVING_REFS)
    )
    assert granted, "no privilege is granted; this guard examined nothing"
    for entry in sorted(granted):
        assert entry in decisions, (
            f"{entry!r} is a granted privilege that no ADR names. Adding the entry IS "
            f"the grant, and a grant with no recorded decision is one nobody made."
        )


# ---------------------------------------------------------------------------
# The split's own invariants (BL-E008-010 phase 4).
#
# The split is only worth what keeps it apart. Three properties hold it: every module
# says what it is for, machinery is shared through `support` rather than sideways
# between subjects, and a module that stopped being collected fails loudly instead of
# quietly examining nothing.
#
# Scope is `_contract_modules()`, the same directory read the meta-guard uses, so a
# tenth subject is covered the moment its file exists.
# ---------------------------------------------------------------------------


def test_every_contract_module_states_the_subject_it_covers() -> None:
    """A module with no docstring is a module with no boundary.

    The split's value is that a reader can find the guard that owns a rule, and that the
    next author knows where a new one goes. That only survives if each file says what it
    holds -- `test_workflow_contracts.py` most of all, being the remainder by
    construction rather than a subject.
    """
    modules = _contract_modules()
    assert modules, "no contract modules on disk; this guard examined nothing"
    for module in modules:
        if module.name == "__init__.py":
            continue
        docstring = ast.get_docstring(ast.parse(module.read_text(encoding="utf-8")))
        assert docstring, f"{module.name} states no subject"
        assert len(docstring.splitlines()[0]) > 20, (
            f"{module.name} opens with {docstring.splitlines()[0]!r}, which names no "
            f"subject a reader could use to decide whether a new guard belongs here"
        )


def _sideways_imports(source: str) -> set[str]:
    """Contract modules this source imports from, other than `support` and `conftest`.

    All three spellings, because the first draft of this helper read absolute
    `from tests.ci.x import y` only -- and `from .x import y`, which is the same
    dependency and the more natural one to write inside a package, walked straight past
    it. The plant that found that is kept below.
    """
    sideways: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        modules: list[str] = []
        if isinstance(node, ast.ImportFrom):
            # A relative import carries `level` and a module name with no package
            # prefix; `from . import x` carries no module name at all and names its
            # targets in `names` instead.
            if node.level:
                modules = [node.module] if node.module else [a.name for a in node.names]
            elif node.module and node.module.startswith("tests.ci."):
                modules = [node.module]
        elif isinstance(node, ast.Import):
            modules = [
                alias.name for alias in node.names if alias.name.startswith("tests.ci.")
            ]
        for module in modules:
            target = module.rsplit(".", 1)[-1]
            if target not in {"support", "conftest"}:
                sideways.add(target)
    return sideways


def test_no_subject_module_reaches_into_another() -> None:
    """Shared machinery goes to `support`, shared fixtures to `conftest`, and nowhere
    else.

    A subject that imports a helper from a sibling has re-tangled the thing the split
    undid: the sibling can no longer change without breaking a module that does not
    mention it, and the 7,441-line file grows back one import at a time. Adding the
    helper to `support` costs one line and keeps the dependency pointing one way.
    """
    modules = [m for m in _contract_modules() if m.stem.startswith("test_")]
    assert modules, "no subject modules on disk; this guard examined nothing"
    for module in modules:
        sideways = _sideways_imports(module.read_text(encoding="utf-8"))
        assert not sideways, (
            f"{module.name} imports from {sorted(sideways)}. Shared machinery belongs "
            f"in tests/ci/support.py and a shared fixture in tests/ci/conftest.py."
        )


def test_the_split_invariant_guard_catches_a_sideways_import() -> None:
    """The plant, kept as a test rather than recorded in a comment.

    `_sideways_imports` is the whole reach of the guard above, and a version that
    matched on `import tests.ci.` alone, or that forgot the relative form, would pass
    every real module today while catching nothing tomorrow.
    """
    for spelling in (
        "from tests.ci.test_topology import _surface_overlap",
        "from .test_topology import _surface_overlap",
        "from . import test_topology",
        "import tests.ci.test_topology",
    ):
        assert _sideways_imports(spelling) == {"test_topology"}, spelling
    for allowed in (
        "from tests.ci.support import _jobs",
        "from .support import _jobs",
        "from tests.ci.conftest import tagged_repository",
        "from tests.support import tracked_text_files",
        "import json",
    ):
        assert _sideways_imports(allowed) == set(), allowed


def test_every_subject_module_still_holds_guards() -> None:
    """A module that stopped being collected is the failure the split could cause.

    Nothing in a passing run distinguishes "this subject holds no violations" from
    "pytest stopped reading this file" -- a renamed function prefix, or a module left
    without a single test after an edit, and the suite goes green over less than it
    covered. Asserted per module, because the total is what the collection identity list
    checked once, at the split, and nothing checks afterwards.
    """
    modules = [m for m in _contract_modules() if m.stem.startswith("test_")]
    assert modules, "no subject modules on disk; this guard examined nothing"
    for module in modules:
        tests = [
            node.name
            for node in ast.parse(module.read_text(encoding="utf-8")).body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name.startswith("test_")
        ]
        assert tests, (
            f"{module.name} is named as a test module and defines no test. Either it "
            f"holds guards or it should not exist."
        )
