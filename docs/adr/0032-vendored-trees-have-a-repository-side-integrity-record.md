# ADR-0032: The vendored tool trees have a repository-side integrity record

- **Status:** Superseded by ADR-0035
- **Date:** 2026-10-08
- **Deciders:** Maintainer + E012-S01-002
- **Epic:** E012
- **Departs from spec:** n/a
- **Principle(s) in tension:** BL-E008-009's original deferral ("the installed release
  has no source of truth in this repository, and inventing one would be worse than the
  gap"), AD-09 (gates must not require a human to recompute what a script can write)

## Context

RT-006 (BL-E011-013) and AD-09 (BL-E011-021) are the two halves of one problem.

`.agents/`, `.claude/` and `_bmad/` hold 2,391 tracked files this project neither
authors nor maintains. They are excluded from every linting hook, they were allowlisted
out of the secret scanner (see ADR-0033), they are read verbatim as instructions by
agents holding write access to this repository, and any pull request can edit them.

What checked them was two things, and neither covered the claim:

- `test_the_vendored_trees_match_the_manifests_their_installer_shipped` verifies the
  files a `payload-manifest.json` names. That is 142 of 2,391 — the shared payload the
  installer copied into each skill, not the skill's contents. `SKILL.md`, the file
  CODEOWNERS itself calls executable surface, is named by no manifest.
- `test_the_vendored_trees_are_byte_identical_copies_of_each_other` compares `.agents/`
  with `.claude/`. A commit that edits both copies — which is the natural shape of an
  edit made by a tool, or by anyone who has read the guard — passes it. `_bmad/` has no
  mirror at all.

So 2,249 files were pinned by nothing, and `.github/CODEOWNERS` said so in prose whose
three integers a guard recomputed and asserted on every run.

That assertion is AD-09's complaint. A routine payload upgrade failed three gates at
once, and clearing the third required a human to recount files by hand and retype three
numbers into a comment. A gate that can only be satisfied by manual arithmetic is a gate
people learn to work around.

The same section also contained the reason the guards were fragile: `_vendored_trees()`
recovered the list of vendored trees by parsing `.pre-commit-config.yaml`'s `exclude:`
regex with `re.fullmatch(r"\^\((?P<alternatives>.+)\)/", ...)` and stripping
backslashes. An integrity check therefore depended on one regex keeping one exact shape;
a legitimate edit to the exclude pattern turned the check into a bare
`assert alternation` with no diagnostic, and a *narrowing* of the pattern would have
quietly narrowed what the integrity checks read.

## Decision

A tracked `vendored-trees.lock` at the repository root is the record.

1. **It names the vendored set.** `[trees]` is the answer to "is this tree vendored and
   accounted for?". `tests/ci/test_gates.py::test_the_pre_commit_exclude_matches_the_declared_vendored_set`
   validates the pre-commit `exclude:` *against* the lock, in both directions: a declared
   tree that is not excluded is vendored content being linted as project source, and an
   excluded directory that is not declared is skipped by the linters and hashed by
   nothing. The derivation is reversed, so no gate depends on a regex's shape.

2. **It records every tracked file.** `[files]` is `<mode> <git blob id>` per path, read
   from `git ls-files -s -z`, so an edit to vendored content fails
   `test_the_vendored_trees_match_the_repository_lock` whether or not a manifest names
   the file and whether or not both copies were edited together. A refresh changes
   exactly the lines of the files that moved, so the diff names them.

3. **`--check` regenerates the whole lock and compares it as text, every run.** Reading
   the blob ids is one `git` call and reads no file, so there is nothing to cache and no
   field is trusted to vouch for another: a hand-edited count, mode or blob fails exactly
   as a vendored edit does. The first version of this decision recorded a SHA-256 per
   file plus an `[index]` digest over the listing, and skipped the per-file comparison
   whenever that one digest matched — so a vendored edit passed behind a one-line change
   to `[index]`. Git's own object ids are no weaker a record: the lock is itself a git
   blob verified by the same hashing, and a SHA-256 column inside it adds nothing to
   that. The record is the index rather than the working tree, which is the state both
   callers check: pre-commit runs against what is staged and stashes unstaged edits while
   it does, and CI runs against a clean checkout.

4. **`scripts/vendored_trees.py --write` regenerates the lock *and* the CODEOWNERS
   coverage block,** which is now delimited by `# BEGIN GENERATED` / `# END GENERATED`
   markers. The counts are still asserted — an unchecked claim stated as a checked one
   is the defect BL-E008-009 exists for — but producing them is one command. This is
   AD-09's remedy: the claim keeps its teeth, the arithmetic stops being a person's job.

5. **The gates run through pytest, not through the script.** `verify-build.yaml`'s
   `supply-chain` job runs `pytest -q tests/ci/test_gates.py -k vendored` rather than
   `scripts/vendored_trees.py --check`, because ADR-0011 forbids a governed definition
   from reaching a decision through a Python module of this repository's own, and
   `test_no_publication_decision_lives_in_a_python_module` enforces it. The guard calls
   the generator; the job calls the guard.

## What this does not claim

The lock is a **repository-side** reference. It proves the trees have not changed since
this repository recorded them. It does not prove they match what the upstream project
published — only a `payload-manifest.json` does that, and it covers 142 files. The
generated CODEOWNERS block states that distinction in both directions and in files,
because a caveat that describes only the gap understates what is checked, and one that
describes only the lock overstates it.

Refreshing the lock is therefore a reviewed act. `/vendored-trees.lock` and
`/scripts/vendored_trees.py` are code-owned for exactly that reason: the lock's value is
that changing it is visible, and a diff of 2,391 digests that nobody is required to look
at is not visible.

## Consequences

- A payload upgrade is one command plus a review, instead of three failing gates and
  manual arithmetic.
- A credential or instruction injected into a vendored file is now caught by two
  independent gates: the digest here, and the secret scanner (ADR-0033).
- The lock is 2,425 lines and will churn on every payload refresh. That is the point —
  it is the diff that did not exist before — but it means a vendored upgrade should be
  its own commit, not folded into a feature change.
- Ignored paths (`__pycache__/`, `_bmad/memory/`) are deliberately outside the count.
  They are runtime artifacts, not vendored content, and `git ls-files` is what decides.

## Alternatives considered

- **Keep deferring, as BL-E008-009 did.** The deferral's reasoning was that a
  repository-authored record "asserts its own correctness". True, and it is why this ADR
  states what the lock does not claim — but "we cannot prove it matches upstream" is not
  a reason to leave 2,249 files provable against nothing at all.
- **Hash the trees into one aggregate digest.** Smaller diff, no useful failure message:
  "the vendored trees changed" names no file, and the whole value at review time is
  seeing which one.
- **Fetch upstream and compare.** `tests/ci` runs offline by design, and a gate that
  depends on a third party's availability fails for reasons unrelated to the change
  under test.
