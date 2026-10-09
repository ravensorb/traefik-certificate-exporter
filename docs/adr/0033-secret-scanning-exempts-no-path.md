# ADR-0033: Secret scanning exempts no path, and the untracked-file gate has two severities

- **Status:** Accepted
- **Date:** 2026-10-08
- **Deciders:** Maintainer + E012-S01-002
- **Epic:** E012
- **Departs from spec:** n/a
- **Principle(s) in tension:** "vendored trees are not this project's to lint" (the
  reasoning behind the original allowlist), gate proportionality (BL-E011-020)

Two findings about the same thing: which files the gates actually read, and what they do
about it.

## Part 1 — the secret scanner exempts no path (RT-008 / BL-E011-015)

### Context

`.gitleaks.toml` allowlisted three paths outright:

```toml
[[allowlists]]
description = "Vendored tool trees this project neither authors nor maintains"
paths = ['''^\.agents/''', '''^\.claude/''', '''^_bmad/''']
```

That is 2,391 files — roughly half the repository — exempt from the only content gate
this project has. The same trees are read verbatim as instructions by agents holding
write access (ADR-0032), and any pull request can edit them.

The justification was that the trees are vendored. That is an argument about whose fault
a problem would be, not about whether a credential pasted into a skill file is live. A
single commit under those paths carried a secret past the gate, and the gate reported
green.

The exemption also had a second, quieter effect: because `gitleaks dir` takes no notice
of pre-commit's `exclude:`, these three patterns were a *second* hand-kept copy of the
vendored list, and a guard existed solely to assert the two copies stayed identical.
That guard made the allowlist look governed while governing only its agreement with a
regex.

### Decision

The path allowlists are removed. Scanning the trees produced exactly 57 findings, all
`generic-api-key` false positives in two classes, and both are now allowlisted by **what
was examined** — a whole line or a whole value — with no `paths` key at all:

| Class | Allowlist |
|---|---|
| 39 SHA-256 digests in `_bmad/_config/files-manifest.csv` | `regexTarget = "line"`, `regexes = ['''(?m)^"[a-z0-9-]+","[^"]+","[^"]+","[^"]+\.[A-Za-z0-9]+","[a-f0-9]{64}"\r?$''']` — the manifest's whole five-column row |
| 18 instances of `const expiredToken = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...';` in a vendored testing guide — the public header `{"alg":"HS256","typ":"JWT"}` plus an ellipsis, which gitleaks prints redacted as `******` | `regexTarget = "secret"`, `regexes = ['''^eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9\.\.\.$''']` — that exact value |

**No allowlist may carry `paths`, even narrowed by `condition = "AND"`.** The first draft of
this decision used exactly that form, on the reading "this file AND this value". In the
pinned gitleaks build (v8.30.1) it does not behave that way: a `paths` entry exempts the
file outright, in `dir` and `git` mode, whatever the regexes say. A live-format PAT
planted beside a regex that cannot match was reported as `no leaks found`.

Without `paths`, an allowlist applies to every file in the repository, so each must be
narrow enough that a real credential cannot satisfy it anywhere. The second draft failed
that too: an unanchored `expiredToken = '` match exempted any value assigned to that name
in any file, and a two-column `"name","<64 hex>"` regex exempted a hex API key in any
CSV. Both were reproduced against the real scanner before being replaced.

So the rule is enforced in two places.
`test_the_secret_scanner_exempts_no_path_from_content_scanning` refuses a `paths` key and
requires every allowlist to constrain content. And `verify-build.yaml`'s self-proving
probe plants, **for each allowlist**, a real-looking credential in the shape that
allowlist was built for and requires the hook to fail on it;
`test_the_secret_scanner_proves_itself_in_ci` fails if there are fewer near-miss plants
than allowlists. **Allowlist the value or the line, never the directory.** A path
allowlist exempts whatever a future commit puts there; a value allowlist exempts the
thing that was actually examined.

Two further guards keep the exemption from returning by another route.
`test_no_vendored_tree_is_excluded_from_the_scanner_by_the_linting_config` requires the
gitleaks hook to stay `always_run: true` with `pass_filenames: false`, so pre-commit's
`exclude:` — a decision about what ruff and mypy should read — cannot reach the scanner.
And `verify-build.yaml`'s self-proving probe now plants a credential **inside `_bmad/`
and requires the scan to fail**; it previously planted the same credential there and
required the scan to *pass*. The direction of that assertion is the entire finding,
which is why it is proven in CI rather than described here.

### Consequences

- A credential committed into a vendored tree fails the gate, locally and in CI.
- A future false positive in a vendored file must be allowlisted by its whole value or
  line, with a near-miss plant added to the CI probe. That is more work per occurrence and
  is the intended cost.
- The guard asserting that two copies of the vendored list agreed is gone; there is now
  one list (`vendored-trees.lock`, ADR-0032) and it governs linting, not scanning.

## Part 2 — the untracked-file gate has two severities (BL-E011-020)

### Context

`pre-commit run --all-files` enumerates `git ls-files`. A file that has never been
`git add`-ed is absent from that listing, so every file-scoped hook skips it while the
run reports green. This repository hit that three times: a whole epic shipped unlinted, a
new mypy gate passed a deliberately planted type error, and `tests/ci/test_gates.py`
itself shipped with an undefined name.

`test_no_file_escapes_every_gate_by_never_having_been_added` closed it — and blocked on
*any* untracked path. In practice that means a draft under `docs/`, an in-flight report
under `_bmad-output/`, or a scratch file at the repository root turns CI red. None of
those files is read by a file-scoped hook when it is tracked either, so the gate was
failing builds over work in progress while claiming to be about unlinted code.

A gate that is red for reasons the reader has learned to dismiss stops being read at
all — including on the run where it catches the unlinted `src/` module.

### Decision

The classifier returns two lists, split by `LINTED_ROOTS = ("src/", "tests/",
".github/")`:

- **Blocking** — untracked under those roots. There, "untracked" means ruff, mypy,
  actionlint or the contract suite reported green over code they never read. That is the
  defect the gate exists for, and all three recurrences were in `src/` or `tests/`.
- **Advisory** — everywhere else. Reported through `warnings.warn`, so pytest collects
  it into the warnings summary that every runner prints, and `verify-build.yaml`'s
  `untracked-coverage` job runs with `-W always` so the list appears in the job log. Not
  fatal.

The split lives in `_unlinted_untracked_paths` rather than at the call site, so
`test_the_coverage_guard_catches_a_file_planted_in_a_real_repository` — which plants
files in a throwaway git repository — exercises the real classifier. That test now
plants `docs/draft.md` alongside the untracked `tests/` module and asserts the first is
advisory and the second blocking, because a downgrade that is not asserted is
indistinguishable from deleting the finding.

### Consequences

- A work-in-progress tree no longer fails CI, and the blocking half keeps its meaning.
- An untracked file outside the linted roots is still reported every run; it is just not
  a build failure.
- If a new linted root appears (a second package, say), it must be added to
  `LINTED_ROOTS` or files under it are only warned about. That is a hand-kept list, and
  it is small and named in one place for that reason.

## Amendment (2026-10-09) — ADR-0035

The near-miss-probe and untracked-file-gate parts of this record are superseded by ADR-0035; both were retired with the governed pipeline. The rule that secret scanning exempts no path is carried forward (as restated by ADR-0037: the repository adds no path exemption). The `gitleaks` and `gitleaks-history` pre-commit hooks scan the tree and the history with whatever config they are given, and honour a `paths` allowlist silently. The no-`paths` rule is mechanically enforced again by the `gitleaks-no-paths-allowlist` pygrep hook in `.pre-commit-config.yaml` (E013 sprint-01 closure, SD-01-2). The narrowness of each allowlist is not mechanically enforced; it is held by CODEOWNERS review of `.gitleaks.toml`. Both mechanical guards named in "So the rule is enforced in two places" were retired with the governed pipeline: the test that refused a `paths` key (`test_the_secret_scanner_exempts_no_path_from_content_scanning`) and the `verify-build.yaml` near-miss probe.

## Amendment (2026-10-09): ADR-0037

The rule is restated as "the repository adds no path exemption". `.gitleaks.toml` sets `useDefault = true`, so gitleaks' maintained default global allowlist is inherited: it skips lock files, dependency site-packages and the VCS directory by path. That inherited set is accepted, not added by this repository, and it is recorded with the gitleaks version, plugin versions and venv interpreter that produced it in the `.gitleaks.toml` header and `docs/developer.md`. A gitleaks upgrade, plugin-lock bump or interpreter change that alters the set updates both records in the same change. The text above is kept as written.
