"""What this project's documents promise, checked against what it does.

The first subject moved out of `test_workflow_contracts.py` (BL-E008-010 phase 3). These
six guards share a subject rather than a mechanism: every one of them reads prose and
asks whether the repository still matches it. That is why they were the first to move --
they touch no workflow structure at all, so a mistake here could not hide behind one.

The rule they enforce between them is global rule 3: a claim in a document is a claim,
and this project has repeatedly found prose asserting mechanisms that no longer exist --
a guard cited by name after being deleted, a recipe prescribed that was never a recipe,
three links to a workflow removed two stories earlier.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.ci.support import (
    PROJECT_ROOT,
    RECOVERY_HEADING,
    WORKFLOWS,
    _contract_definitions,
    _defining_module,
    _load_workflow,
    _publishers,
    _runbook_findings,
    _statements,
    _trigger_surface,
)
from tests.support import tracked_text_files

OPERATIONAL_RUNBOOK = PROJECT_ROOT / "docs" / "operational.md"


def _recovery_section(text: str) -> str:
    """The section this story owns, located by heading and ended by the next one.

    Used only for the *positive* assertions, which are genuinely section-local. The
    prohibition scan runs over the whole page (review MEDIUM-2): `## Rollback` is another
    recovery procedure, and an operator following a prohibited instruction there is in
    the same trouble as one following it here.
    """
    assert RECOVERY_HEADING in text, f"{RECOVERY_HEADING} is missing from the runbook"
    body = text.split(RECOVERY_HEADING, 1)[1]
    return RECOVERY_HEADING + re.split(r"\n## ", body)[0]


def test_the_recovery_runbook_prescribes_failed_jobs_only_recovery() -> None:
    """CI-AR38. The runbook is the deliverable an operator acts on at 3am, so what it
    prescribes is as load-bearing as what the workflows enforce."""
    page = OPERATIONAL_RUNBOOK.read_text(encoding="utf-8")
    section = _recovery_section(page)

    assert re.search(r"re-?run\s+failed\s+jobs", section, re.IGNORECASE), (
        "the recovery section never names the failed-jobs-only rerun it exists to "
        "prescribe (CI-AR38)"
    )
    # Both forges, because the procedure differs and Epic 9 inherits this page.
    assert "GitHub" in section and "Gitea" in section

    # The three halt-and-escalate conditions, each named with its escalation.
    for condition in ("unsupported", "expired", "conflict"):
        assert re.search(condition, section, re.IGNORECASE), (
            f"the recovery section never names the {condition} halt condition"
        )
    assert re.search(r"escalat", section, re.IGNORECASE)

    # F17: the detector is the destination's own rejection, and the guard that forbids
    # the alternative is named where an operator can find it -- so the name has to
    # resolve. Derived from the page rather than hard-coded, so a second guard cited
    # later is checked too (review LOW-1).
    cited_guards = set(re.findall(r"\btest_[a-z0-9_]+", section))
    assert "test_no_publisher_queries_a_destination_before_uploading" in cited_guards
    for guard in sorted(cited_guards):
        assert guard in _contract_definitions(), (
            f"docs/operational.md cites {guard}, which no longer exists; the runbook "
            f"points an operator at nothing"
        )

    # F30: a digest carries no run identity, so the join key has to be spelled out.
    assert "org.opencontainers.image.revision" in section

    # The prohibition scan is the whole page, not this section.
    assert not _runbook_findings(page), _runbook_findings(page)
    assert len(_statements(page)) > len(_statements(section)), (
        "the prohibition scan is examining only the section it was widened past"
    )


JUSTFILE = PROJECT_ROOT / "justfile"


# A recipe declaration: a name at column 0, optional parameters, then `:` -- but not
# `:=`, which is an assignment.
JUST_RECIPE = re.compile(
    r"^([a-z][a-z0-9-]*)(?:\s+[A-Za-z_][A-Za-z0-9_]*)*\s*:(?!=)", re.MULTILINE
)


# A recipe being prescribed. Restricted to a code span because `just` is an ordinary
# English word: an unrestricted scan matched "just above", "just an" and "just because".
JUST_INVOCATION = re.compile(r"`just ([a-z][a-z0-9-]*)")


def _just_recipes() -> set[str]:
    """Recipe names, extracted from the justfile rather than from `just --summary`.

    CI installs no `just` -- the formatting hook says so and is local-only -- so the
    extraction is what runs there. `test_the_recipe_extraction_agrees_with_just_itself`
    keeps it honest wherever the binary exists.
    """
    return set(JUST_RECIPE.findall(JUSTFILE.read_text(encoding="utf-8")))


def test_the_recipe_extraction_agrees_with_just_itself() -> None:
    """The extraction above is a line shape, not a parser, so it is checked against the
    tool it stands in for whenever that tool is installed."""
    binary = shutil.which("just")
    if binary is None:
        pytest.skip("just is not installed; the extraction runs unverified here")
    summary = subprocess.run(
        [binary, "--summary"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    assert _just_recipes() == set(summary.stdout.split())


def test_every_recipe_a_document_prescribes_exists() -> None:
    """Global rule §3's recorded failure, in its original form: three committed
    documents prescribed a command-line flag that did not exist, and agents followed it
    for weeks because the instruction read as authoritative.

    `ARCHITECTURE-SPINE.md` CI-AR7 enumerated `setup`, `package` and `verify`, none of
    which are recipes, and `epics.md` wrote acceptance criteria against two of them. A
    reader running the documented command gets "Justfile does not contain recipe".

    Scope is documents that *prescribe*: `docs/`, the root pages, the planning
    artifacts, and the workflows. `_bmad-output/implementation-artifacts/` is excluded
    because it records what happened, including commands that have since been renamed.
    """
    recipes = _just_recipes()
    assert recipes, "no recipes in the justfile; this guard examined nothing"
    prescriptive = [
        (relative, text)
        for relative, text in tracked_text_files()
        if relative.startswith(
            ("docs/", "_bmad-output/planning-artifacts/", ".github/")
        )
        or "/" not in relative
    ]
    assert prescriptive, "no prescriptive documents; this guard examined nothing"
    for relative, text in prescriptive:
        for name in JUST_INVOCATION.findall(text):
            assert name in recipes, (
                f"{relative} prescribes `just {name}`, which is not a recipe. "
                f"Available: {', '.join(sorted(recipes))}"
            )


MARKDOWN_LINK = re.compile(r"\[[^\]]*\]\(([^)\s#]+)")


def _documented_files() -> list[tuple[str, str]]:
    """This project's own documentation: tracked markdown under `docs/`, plus the
    root-level pages.

    A positive derivation rather than a list of exclusions. The vendored tool trees are
    not this project's writing, and `_bmad-output/` is the agent execution record --
    point-in-time reports that describe deleted files *because* they were deleted, which
    is their function.
    """
    return [
        (relative, text)
        for relative, text in tracked_text_files()
        if relative.endswith(".md")
        and (relative.startswith("docs/") or "/" not in relative)
    ]


GUARD_CITATION = re.compile(r"\btest_[a-z0-9_]+")

# A citation that gives an ADDRESS as well as a name: `tests/ci/<module>.py::<guard>`,
# in prose or in a comment. The path half is the half a move invalidates.
ADDRESSED_CITATION = re.compile(r"tests/ci/(test_[a-z0-9_]+)\.py::(test_[a-z0-9_]+)")

# A citation into the test suite by LINE. Unmaintainable by construction: nothing
# rewrites it when code moves, and unlike a broken link it keeps resolving -- to
# whatever happens to occupy those lines now.
LINE_CITATION = re.compile(r"tests/[A-Za-z0-9_/]+\.py:\d+(?:-\d+)?")


def test_every_guard_a_document_cites_still_exists() -> None:
    """A citation is a promise the reader can follow it.

    This rule existed and was scoped to one section of one page -- the recovery runbook
    -- so a guard renamed anywhere else left its citations pointing at nothing. It is
    now every prescriptive document, and it earned that immediately: it caught
    `test_every_finalizer_states_the_scopes_it_relies_on_being_denied` **missing from
    the module entirely**, silently removed by a region replacement while ADR-0006 still
    cited it as the enforcement for the finalizer's denied scopes. The ADR read as
    enforced and nothing was enforcing it.

    Names matching a test module's own stem are excluded: `test_workflow_contracts` is
    a file, not a guard, and documents legitimately name the file.
    """
    modules = {path.stem for path in (PROJECT_ROOT / "tests").rglob("test_*.py")}
    known = _contract_definitions()
    documents = [
        (relative, text)
        for relative, text in tracked_text_files()
        if relative.startswith(
            ("docs/", "_bmad-output/planning-artifacts/", ".github/")
        )
        or "/" not in relative
    ]
    assert documents, "no prescriptive documents; this guard examined nothing"
    cited = 0
    for relative, text in documents:
        for name in sorted(set(GUARD_CITATION.findall(text))):
            if name in modules:
                continue
            cited += 1
            assert name in known, (
                f"{relative} cites {name}, which is not a guard in this module. Either "
                f"the guard was renamed and the citation was not, or it was removed and "
                f"the document still claims it enforces something."
            )
    assert cited, "no document cites a guard; this guard examined nothing"


def test_every_addressed_citation_names_the_module_that_holds_the_guard() -> None:
    """The name half of a citation survives a move. The path half does not.

    `test_every_guard_a_document_cites_still_exists` asks only whether the name exists
    somewhere in the suite, which is the right question for a bare citation and the wrong
    one for `tests/ci/x.py::guard`. The BL-E008-010 split moved 293 of 307 guards between
    modules and that guard stayed green over every one of them -- including
    .github/dependabot.yml, whose whole purpose is to point a reader at the test that
    justifies the artifact pin, and which spent the split pointing at the wrong file.

    Scope is the same document set as the guard above, and the answer comes from the
    directory rather than a table, so a tenth module is covered when it exists.
    """
    location = _defining_module()
    documents = [
        (relative, text)
        for relative, text in tracked_text_files()
        if relative.startswith(
            ("docs/", "_bmad-output/planning-artifacts/", ".github/")
        )
        or "/" not in relative
    ]
    assert documents, "no prescriptive documents; this guard examined nothing"
    checked = 0
    for relative, text in documents:
        for module, name in sorted(set(ADDRESSED_CITATION.findall(text))):
            checked += 1
            actual = location.get(name)
            assert actual, (
                f"{relative} cites {name}, which no module in the suite defines"
            )
            assert actual == f"{module}.py", (
                f"{relative} cites {name} at tests/ci/{module}.py, but it lives in "
                f"tests/ci/{actual}. A reader following the address finds nothing, and "
                f"the rule the citation justifies reads as unenforced."
            )
    assert checked, "no document gives a guard's address; this guard examined nothing"


def test_no_document_cites_the_test_suite_by_line_number() -> None:
    """A line number is a citation that rots silently and still resolves.

    ADR-0007 carried seven of them into `tests/ci/test_workflow_contracts.py`. The
    BL-E008-010 split moved every guard they described into other modules and left the
    file in place at a quarter of its length, so each citation went on resolving -- to
    unrelated code. A reader following `:43-89` for the pull-request adapter's isolation
    contract now lands in the middle of a different guard and has no way to know.

    That is worse than a dead link, which at least announces itself. ADR-0007's own
    status note excuses citations "to files that have been deleted"; these point at a
    file that survived, which is the case the note does not cover and the case that
    misleads.

    The fix is the `::guard` form, which `_defining_module` can check. Requiring it is
    the only way this stays true, because nothing else will notice.

    NOT COVERED: citations into workflow YAML by line (`verify-build.yaml:3-17` is one),
    and prose that describes a guard without naming it. Both rot the same way. This
    guard reads Python under `tests/` and claims nothing about the rest.
    """
    documents = [
        (relative, text)
        for relative, text in tracked_text_files()
        if relative.startswith(
            ("docs/", "_bmad-output/planning-artifacts/", ".github/")
        )
        or "/" not in relative
    ]
    assert documents, "no prescriptive documents; this guard examined nothing"
    offenders = {
        relative: sorted(set(found))
        for relative, text in documents
        if (found := LINE_CITATION.findall(text))
    }
    assert not offenders, (
        f"cite a guard as tests/ci/<module>.py::<guard>, never by line: {offenders}. "
        f"A line number survives the move that invalidates it and keeps resolving to "
        f"whatever took its place."
    )


def test_no_tracked_document_links_to_a_file_that_does_not_exist() -> None:
    """A link is a promise that its target exists; prose merely mentioning a filename is
    not, which is why only links are checked.

    `docs/guidelines.md` is cited by `dev.yaml` and `release.yaml` as the authority for
    choosing the metadata action, and it linked three times to
    `.github/workflows/build-container.yaml`, deleted in E007. A reader following the
    workflow's own citation to check why an action was chosen landed on a 404.

    Deliberately not restricted to `.github/`: a dead link to an ADR or a script is the
    same defect, and scoping to one directory is how the previous documentation guard
    ended up checking one page.
    """
    documents = _documented_files()
    assert documents, "no tracked documentation; this guard examined nothing"
    for relative, text in documents:
        for target in MARKDOWN_LINK.findall(text):
            if target.startswith(("http://", "https://", "mailto:")):
                continue
            # A regex inside a code span parses as a link -- `[^]](?:workflow|run)` and
            # its kind. No path in this repository holds a regex metacharacter, so the
            # implausible target is dropped rather than the whole code-span question
            # being reopened.
            if set(target) & set("|?*[]()"):
                continue
            resolved = (PROJECT_ROOT / relative).parent / target
            assert resolved.exists(), (
                f"{relative} links to {target}, which is not on disk. A document the "
                f"workflows cite as their authority must not point at a deleted file."
            )


def test_the_runbook_names_every_channel_and_no_workflow_that_is_not_on_disk() -> None:
    """The rename attack, and the docs half of "no dangling references".

    Scope is derived from disk both ways: every publishing channel must be documented by
    name, and every workflow filename the page cites must exist. Renaming `dev.yaml` and
    forgetting the page fails the first; renaming it and leaving the old reference
    behind fails the second. Citations are collected in both the forms the page actually
    uses -- the full `.github/workflows/x.yaml` path and the bare backticked filename --
    because review MEDIUM-6 found only two of the page's references were the former.

    The documented set is "owns an event AND holds a publisher": `ci.yaml` owns the pull
    request event and ships nothing, so an operations guide has nothing to say about it.
    """
    text = OPERATIONAL_RUNBOOK.read_text(encoding="utf-8")

    tracked_names = {Path(relative).name for relative, _ in tracked_text_files()}
    cited = set(re.findall(r"\.github/workflows/([\w.-]+\.ya?ml)", text)) | {
        name
        for name in re.findall(r"`([\w.-]+\.ya?ml)`", text)
        # A name that is not a workflow filename is somebody else's file -- the page
        # cites `config.yaml` and `docker-compose.yml` too -- and is resolved against
        # the tracked corpus rather than against this directory.
        if name not in tracked_names or (WORKFLOWS / name).exists()
    }
    assert len(cited) >= 4, f"the operations guide cites almost no workflow: {cited}"
    for name in sorted(cited):
        assert (WORKFLOWS / name).exists(), (
            f"docs/operational.md cites {name}, which is not in .github/workflows"
        )

    channels = sorted(
        path.name
        for path in WORKFLOWS.glob("*.yaml")
        if _trigger_surface(_load_workflow(path)) and _publishers(_load_workflow(path))
    )
    assert channels, "no publishing channel on disk; this guard examined nothing"
    for name in channels:
        assert name in text, (
            f"{name} owns an event and publishes, but the operations guide never names "
            f"it, so an operator has no runbook for the channel it drives"
        )
