# ADR-0006: Committed Poetry version and atomic release identity

- **Status:** Accepted
- **Date:** 2026-08-31
- **Deciders:** Maintainer (ravensorb)
- **Principle(s) in tension:** Simple local release preparation, complete remote identity, and recoverability under concurrent publication
- **Amended:** 2026-09-01 — made the *sole* version authority; `release.yaml` retired, and the
  identity/artifacts boundary drawn (see the two amendments below)

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
   are prohibited **in this transaction**. That scope is deliberate and is not a blanket ban on
   forced writes anywhere in the project — see "Alias tags move, and moving one is a forced write"
   below.
6. A failed push preserves the local commit and tag. Resume accepts only one direct unpushed release
   commit, exactly one matching annotated tag, an equal Poetry version, the unchanged remote parent,
   and an absent remote exact tag. It repeats the existing atomic push without bumping, committing,
   or retagging.

The root `justfile` remains a thin, credential-free facade for dry-run, guarded publication, and
resume. It contains no version calculation.

## Sole authority (amendment, 2026-09-01)

This transaction is the **only** mechanism permitted to move version identity.

`.github/workflows/release.yaml` ran `googleapis/release-please-action@v5` on every push to
`main` with `contents: write` and `release-type: python`, claiming the same identity this ADR
governs. Nothing arbitrated between them, and the collision had already occurred in this
repository's history: `f23f561` ("Change version to", a malformed bot commit) followed by
`ce61e05` ("fix: revert bot-corrupted version"). `build.yaml` carried its own comment recording
that the publication path "previously corrupted `pyproject.toml`'s version".

The competing mechanism was also not working. The CI/CD architecture review of 2026-08-31
records release-please failing on **every** run with `Fetching pyproject.toml … ✖ invalid
file`: its `python` strategy cannot parse this project's Poetry-legacy `pyproject.toml`, which
declares no PEP 621 `[project]` table, and it looks for `version.py` where this repository has
`_version.py`. The same review notes it is GitHub-API-only and cannot run against Gitea,
contradicting the project's one-pipeline/three-runners goal. The choice was not between two
working release paths; it was between a working one and a broken one that could still corrupt
state.

**Decision:** `release.yaml` is deleted. Releases are prepared and published only by
`scripts/release_version.py` via `just release`, run by a maintainer holding their own
credentials.

## Identity versus artifacts of an identity (amendment, 2026-09-01)

"Sole authority" was initially read as "no workflow may ever hold `contents: write`", which
would make a forge Release impossible to create. That reading is too broad.

**GitHub has no `releases:` permission scope.** Its documentation places release creation
inside `contents`: "`contents: read` permits an action to list the commits, and
`contents: write` allows the action to create a release." So any release automation needs it.

What this ADR owns is who **chooses** the version, not who attaches objects to a version
already chosen:

| Concern | Owner | Rationale |
|---|---|---|
| The committed Poetry version, and the exact `vX.Y.Z` annotated tag | **Local guarded transaction only** | This *is* the identity. Two writers cannot be reconciled — that is what corrupted `pyproject.toml` before. |
| The forge Release object, its assets, and the moving `vMAJOR`/`vMAJOR.MINOR` aliases | **A single registered CI finalizer job** | These attach to, or point at, an identity the transaction already decided and published. An alias is a pointer, not a choice. |

Package and image publication need none of this: PyPI/TestPyPI use registry credentials or
`id-token: write`, and GHCR/Docker Hub use `packages: write` plus a registry login. Only the
Release and the Git aliases touch `contents`.

**Enforcement is two guards, because one cannot cover it.**

- `test_no_workflow_holds_github_token_write_access_to_contents` — no workflow or job may
  declare `contents: write` unless its job name is registered in `RELEASE_FINALIZER_JOBS`.
- `test_no_workflow_writes_refs_or_releases_outside_a_finalizer` — no unregistered job may run
  `git push`, `gh release create/upload/edit/delete`, `gh api …/releases`, or a
  release-creating action.

The second exists because the first is structurally blind to the case that matters most. The
`permissions:` key configures **only** the automatic `GITHUB_TOKEN` — GitHub's wording is
"modify permissions for the `GITHUB_TOKEN`" — so a job pushing with a PAT, GitHub App token or
deploy key from `secrets` never trips it. Verified by planting a `git push origin
HEAD:refs/tags/v9.9.9` step with the permissions block untouched: the permissions check passed,
the behavioural check failed.

`RELEASE_FINALIZER_JOBS` is deliberately a hand-kept list rather than a derived scope: it is a
registry of granted exceptions, and adding a name to it *is* the grant. It is empty until
Epic 8 registers the stable-release finalizer, which must also depend on the governed verifier
so that nothing is released that was not first verified.

## The transaction as a state machine

Two phases. Everything up to the atomic push is local and fully reversible; the push is the
single irreversible step, and everything after it is confirmation rather than mutation.

```mermaid
stateDiagram-v2
    [*] --> Preconditions

    Preconditions: Preconditions<br/>clean tree, synced default branch,<br/>exact stable tag history
    Preconditions --> Bump: satisfied
    Preconditions --> [*]: refuse (no mutation yet)

    Bump: Poetry bump<br/>version-only change
    Bump --> Gate: proposed == written
    Bump --> Restore: unexpected change

    Gate: just check<br/>authoritative gate (non-mutating)
    Gate --> Identity: pass, tree unchanged
    Gate --> Restore: fail, or tree moved

    Identity: Local identity<br/>release commit + annotated exact tag
    Identity --> Push: built locally

    Push: Atomic two-ref push<br/>branch + tag, one operation
    Push --> Published: accepted
    Push --> Unconfirmed: rejected, raced, or unknown

    Restore: Restore<br/>original version returned
    Restore --> [*]: reported, nothing published

    Unconfirmed --> Resume: just release-resume
    Resume --> Published: remote state proves success
    Resume --> Unconfirmed: ambiguous -- refuses to guess

    Published --> [*]

    note right of Push
        The only irreversible step.
        Either both refs move or neither does.
    end note

    note right of Resume
        Never rolls back a published
        identity and never re-pushes
        one it cannot prove absent.
    end note
```

The `Restore` path is why the preconditions are strict: every failure before the push returns
the working tree to the version it started from, so a failed release leaves no partial identity
behind. The `Unconfirmed` state is deliberately terminal until a human runs the resume — an
automatic retry could double-publish, and an automatic rollback could delete a tag other
machines have already fetched.


## Alias tags move, and moving one is a forced write (amendment, 2026-09-02)

**Requirement, not a trade-off: once a valid release exists, the major alias floats.** `vMAJOR`
and `vMAJOR.MINOR` must advance to the newest compatible stable release. That is the point of
publishing them.

Moving a tag is a **non-fast-forward ref update**. There is no non-forced spelling of it —
`git push --force`, delete-and-recreate, and `PATCH .../git/refs` with `force: true` are the same
operation with different syntax. So §5's prohibition and this requirement cannot both be read
broadly, and it is §5 that is narrow: it governs **the release transaction's own atomic push**,
where force would let a botched run overwrite a published identity. It was never a statement
about alias refs, which did not exist when it was written.

The identity-versus-artifacts split already drawn above decides this cleanly:

| Ref | Mutability | Who writes it | Force |
|---|---|---|---|
| `refs/tags/vX.Y.Z` | **immutable** — this *is* the identity | local guarded transaction only | **never**, under any spelling |
| `refs/tags/vMAJOR`, `refs/tags/vMAJOR.MINOR` | **mutable by design** — pointers to an identity already chosen | the registered CI finalizer only | **required**, with `--force-with-lease` |

An alias does not choose a version; it points at one. Forcing it therefore cannot corrupt an
identity, which is the harm §5 exists to prevent.

**The mechanism is `LiquidLogicLabs/git-action-tag-floating-version@v1`, not a hand-rolled
push.** The action extracts the major and optional minor from an exact tag, points the aliases at
it, performs the non-fast-forward update, and skips prereleases by default
(`ignore-prerelease: true`). It needs `contents: write`, which is exactly the grant this ADR
governs, so its use is restricted to a registered finalizer.

Unlike ADR-0010's Release action it needs no forge backend: **a tag is a git concept, a Release
is a forge concept.** The alias action pushes refs with plain git — `using: node24`, no server
URL, no API base, no platform selector — so it is portable to Gitea for free. That is why one of
these two actions needs per-API handling and the other does not.

**Hand-rolling the push is forbidden outright**, not merely constrained. The constraints are the
hard part — `--force-with-lease` rather than a bare `--force` so a concurrent alias move fails
instead of being silently clobbered, never `--tags`, never a broad refspec, never against
`refs/tags/vX.Y.Z` — and a `run:` block re-deriving them would be a second implementation of the
alias rule, and the one most likely to get the lease wrong.

Two guards, verified by planted violation in both directions:

- `test_alias_moves_go_through_the_approved_action` — no `run:` step may perform a forced ref
  write under any spelling. Rejected even when the hand-rolled command was *correct*, using
  `--force-with-lease` against a valid alias ref.
- `test_the_alias_action_runs_only_from_a_registered_finalizer` — the action may run only from a
  `(workflow, job)` pair in `RELEASE_FINALIZER_JOBS`. The permitted path was confirmed to pass,
  not only the rejections.

Carry into E009's pinned tuple: this action is `using: node24`, the same runtime requirement
ADR-0010 records for the Release action.

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
