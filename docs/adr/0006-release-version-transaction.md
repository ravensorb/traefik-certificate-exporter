# ADR-0006: Committed Poetry version and atomic release identity

- **Status:** Accepted
- **Date:** 2026-08-31
- **Deciders:** Maintainer (ravensorb)
- **Principle(s) in tension:** Simple local release preparation, complete remote identity, and recoverability under concurrent publication

## Context

The previous `scripts/git-increment-version.sh` derived a version independently of Poetry, created
a tag without a matching committed package-version change, and used `git push --tags origin main`.
That broad, non-atomic operation could publish unrelated tags or update only one half of the release
identity. A retry after a partial or uncertain failure had no narrow state contract.

The project already commits its package version in `pyproject.toml`, with dynamic versioning
disabled. The release mechanism therefore needs to preserve Poetry as the version authority while
making the version commit and exact tag one indivisible remote publication.

## Options considered

| Option | Benefits | Costs and risks |
|---|---|---|
| Keep a tag-only shell helper | Small and familiar | Duplicates version logic, can drift from package metadata, and cannot safely publish two refs |
| Let CI infer a version dynamically | Avoids a preparation commit | Conflicts with the committed-version packaging contract and makes local artifacts differ from release identity |
| Guard a Poetry version commit and publish its exact annotated tag atomically | One version authority, inspectable local state, and all-or-nothing remote refs | Requires Git servers that support atomic push and explicit recovery validation |

## Decision

Use `scripts/release_version.py` as the sole release transaction and retire the broad shell path.
The following are invariants:

1. Only `major`, `minor`, and `patch` are accepted. Poetry calculates and writes the version; no
   second version file or TOML version parser exists.
2. Preparation starts from a clean checkout of the remote's advertised default branch, with equal
   local/remote tips, complete equal exact-stable-tag histories, and a greatest tag matching the
   committed Poetry version. These checks query the remote without fetching so a failed
   precondition does not mutate local refs.
3. The changed working tree is validated by the authoritative `just check` command. Failure invokes
   Poetry to restore the original version and verifies a clean tree before stopping.
4. A successful gate creates one predictable version commit and one annotated exact
   `vMAJOR.MINOR.PATCH` tag that peels to that commit. Preparation without publication prints the
   exact push rather than executing it.
5. Publication refetches and revalidates the remote parent, tag absence, local commit, committed
   version, and tag immediately before one command:

   ```text
   git push --atomic origin HEAD:<default-branch> refs/tags/vMAJOR.MINOR.PATCH
   ```

   Broad refspecs, `--tags`, force, separate pushes, destructive rollback, and non-atomic fallback
   are prohibited.
6. A failed push preserves the local commit and tag. Resume accepts only one direct unpushed release
   commit, exactly one matching annotated tag, an equal Poetry version, the unchanged remote parent,
   and an absent remote exact tag. It repeats the existing atomic push without bumping, committing,
   or retagging.

The root `justfile` remains a thin, credential-free facade for dry-run, guarded publication, and
resume. It contains no version calculation.

## Consequences

- Positive: package metadata, commit identity, and stable tag cannot drift through the supported
  release path.
- Positive: a server-side rejection or race updates neither remote ref when atomic push is
  supported, while the exact local identity remains inspectable.
- Positive: recovery rejects ambiguous or already-published state instead of guessing or rolling
  back.
- Trade-off: remotes without atomic-push support cannot use this release transaction; maintainers
  must resolve server capability rather than accepting partial publication.
- Trade-off: preparation requires complete exact stable-tag history and a synchronized default
  branch, so shallow or stale clones must be reconciled before a release.
