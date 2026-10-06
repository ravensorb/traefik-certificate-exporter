# ADR-0027: Vendored-tree "not maintained by us" framing lives only in CODEOWNERS, not `docs/guidelines.md`

- **Status:** Proposed
- **Date:** 2026-10-06
- **Deciders:** Maintainer (ravensorb)
- **Epic:** E011
- **Departs from spec:** n/a
- **Principle(s) in tension:** Factual accuracy of story Context/Interface-Contract
  citations vs. a plausible-sounding but unverified source attribution.

## Context

E011-S01-002's Context section attributes the quote "this project neither authors nor
maintains" (describing the vendored `.agents/`/`.claude/` trees) to
`docs/guidelines.md`, and its Interface Contracts bullet instructs: "`docs/guidelines.md`
— update the 'vendored skills, not maintained by us' framing to either cite the new
check, or explicitly record that no 'installed release' source of truth exists yet."

Both files were read directly to verify. `docs/guidelines.md` (213 lines) contains
exactly one reference to either vendored path at all — a single relative Markdown link,
`[GitHub Actions overlay]` → `../.agents/skills/l3io-arch-review/references/standards-github-actions.md`
on line 63 — which is a citation link to a reference document, not prose describing or
characterizing the vendored trees in any way. No sentence resembling "neither authors nor
maintains," "vendored skills," "not maintained by us," or any paraphrase of that framing
exists anywhere in the file.

The actual matching language lives in `.github/CODEOWNERS`'s header comment, which states:

> Agent instructions. Tooling is told to "READ its entire contents and follow its
> directions exactly", these trees are excluded from the linting gates, and the agents
> that read them hold write access. That combination makes them executable surface in
> every sense that matters, so they are reviewed like it.

This is the file that actually frames `.agents/`/`.claude/`/`.github/agents/` as
externally-sourced, not-linted, high-trust-surface trees — the same substantive point
the story's Context section was reaching for, just misattributed to the wrong file.

## Options considered

| Option | Pros | Cons | Standards fit |
|--------|------|------|---------------|
| A. Treat this as a citation-only error; retarget the story's Interface Contracts bullet to `.github/CODEOWNERS`'s header comment, quoting it precisely, and leave `docs/guidelines.md` untouched since it has no independent framing to correct | Matches what was actually verified in both files; does not invent a passage in `docs/guidelines.md` that does not exist; does not touch a file that has nothing wrong in it | The story's Business-AC outcome bullet ("a reviewer... can check the standing claim in `docs/guidelines.md`...") also needs the same retarget, not just the Interface Contracts bullet, to stay internally consistent — noted for the implementer but out of this ADR's scope (only the Interface Contracts bullet was authorized for patching) | Correct per verification; keeps the story's remaining citation to real, quoted text |
| B. Add a new framing sentence into `docs/guidelines.md` so the quote becomes true after the fact | "Fixes" the citation by changing the target instead of the claim | Fabricates documentation to match a wrong citation rather than correcting the citation; duplicates governance prose that already lives in CODEOWNERS, inviting drift between two descriptions of the same trees | Rejected — the scope here is a factual correction, not a documentation-expansion task |

## Decision

**Option A.** `docs/guidelines.md` does not independently describe the vendored
`.agents/`/`.claude/` trees in any way — verified by reading the full file; its one
mention of `.agents/` is an unrelated relative link to a reference document, not
descriptive prose. The "not maintained by us" / "neither authors nor maintains" framing
exists solely in `.github/CODEOWNERS`'s header comment, specifically the paragraph
beginning "Agent instructions. Tooling is told to 'READ its entire contents and follow
its directions exactly'..." quoted in full above. E011-S01-002's Interface Contracts
bullet is retargeted to that file and that exact passage, rather than to
`docs/guidelines.md`.

## Consequences

- Positive: The story now cites text that actually exists, verified against current file
  content, closing AG-4 without inventing new prose in a file that never carried this
  framing.
- Negative / trade-offs accepted: The story's Business-AC Outcome bullet still reads
  "...the standing claim in `docs/guidelines.md`..." and was left as-is per this task's
  scope (only the Interface Contracts bullet was authorized for patching) — an
  implementer picking up E011-S01-002 should retarget that bullet too before closing the
  story, since it describes the same misattribution.
- Follow-ups / exit plan: none — this is a documentation-citation correction, not a
  deferred capability.
