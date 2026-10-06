#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["ruamel.yaml>=0.18"]
# ///
# pm-status-version: 3.2.6   (machine-readable marker; `self-install` compares this across copies — keep at top)
"""
pm-status.py — deterministic, atomic, round-trip-safe writer for the l3io-pm
sharded state tree, and the reader behind its progress report.

Why this exists
---------------
Status transitions used to be free-form YAML edits the model performed between
phases. Under load or parallel execution those edits were skipped, malformed, or
they reordered/stripped the file. This script makes every transition a single
deterministic operation:

  * node addressing follows references/status-files.md (epic -> sprints -> stories),
  * writes are atomic (temp file + os.replace) so a crash never leaves a partial file,
  * ruamel round-trip load/dump preserves key order and comments so diffs stay clean,
  * `verify` is a hard read-back gate the orchestrator can branch on (exit code).

BMad standardizes on `uv run`; the PEP-723 header above lets `uv` provision
ruamel.yaml automatically. Always invoke via `uv run pm-status.py ...` — running
under `python3` directly bypasses the provisioning and fails with
ModuleNotFoundError anywhere ruamel.yaml is not already installed globally.

Subcommands
-----------
  set-status    --state-root S  (--story KEY | --epic ID [--sprint ID])  --status S
                [--title T] [--reason "R"] [--resolution "R"]
                [--flock] [--no-events] [--session-id ID]
                (story transitions gated per-pair via VALID_STORY_TRANSITIONS; sprint and
                epic keep enum-only validation. --status blocked REQUIRES --reason and is
                permitted only from in-progress or review; the reason lands on the node
                as blocked_reason and a paired block_open event is appended. A subsequent
                transition off blocked clears blocked_reason and appends block_close with
                the derived duration_hours. blocked -> done additionally REQUIRES
                --resolution. A story set to done resolves every key in its resolves:
                as fixed, ref the story, printing `resolved BL-...` per NEW resolution
                and `ok BL-... already resolved (...)` per key resolved before; a failure
                there warns, naming /l3io-doctor triage, and still exits 0 -- ADR-0003)
  sync-story-doc --artifacts-root R  (NOT the state root)  --story KEY  --status S
                [--quiet]
                (writes status: into the story markdown's frontmatter; the state
                YAML stays the source of truth. Never fails its caller -- a
                missing file, missing/unterminated frontmatter, or a parse
                error prints WARN to stderr and exits 0)
  story-doc-init --state-root S  --artifacts-root R  --story KEY
                (creates the story document skeleton from the state node when absent;
                an existing document is left untouched, exit 0 "exists")
  import-node   --state-root S  (--story KEY | --epic ID [--sprint ID])  --status S
                [--title T] [--classification C] [--origin {inferred}] [--origin-note N]
                [--reason R]   (REQUIRED when --story ... --status blocked; stored as
                                blocked_reason and in the paired block_open event; rejected
                                on any other kind or status)
                [--no-events] [--session-id ID]
                (creates a missing state node from a migration record; idempotent by
                SKIP -- an existing node is left untouched and no event is appended;
                exit 3 when a sprint or story's parent epic is absent)
  set-actual    --state-root S   --node {story,sprint,epic}  (--story KEY | --epic ID [--sprint ID])
                [--elapsed-hours H] [--man-hours H] [--hitl-hours H]
                [--tokens-input K] [--tokens-output K] [--tokens-cache-write K] [--tokens-cache-read K]
                (any --tokens-* requires --model M; under --runtime claude ALL FOUR are
                required once any is given — an explicit 0 counts; [--token-rates JSON]
                overrides its rate card;
                cost is DERIVED from tokens x rates — --cost is declared but always rejected)
                [--tokens-na]   (in place of --tokens-*; runtime=other only, forbidden under runtime=claude)
                [--runtime {claude,codex,copilot,other}] [--flock] [--no-events] [--session-id ID]
                [--no-calibrate]
                (derives the node's calibration sample inline — write
                completion_evidence.fix_iterations BEFORE this call, or the scope/fix
                split cannot see it; the sample is emitted at most once per node,
                guarded by a `calibration_sampled_at` marker)
  set-estimate  --state-root S  (--story KEY | --epic ID [--sprint ID])
                [--man-hours-low H] [--man-hours-high H] [--hitl-hours-low H] [--hitl-hours-high H]
                [--elapsed-hours-low H] [--elapsed-hours-high H]
                [--tokens-k-min K] [--tokens-k-max K]
                (sprint/epic ranges; kind is inferred from --story vs --epic[/--sprint] —
                a story node instead takes the single-value aliases --man-hours H,
                --hitl-hours H, --elapsed-hours H, --tokens-k K;
                --time-hours* accepted as a deprecated alias for --elapsed-hours*;
                cost is DERIVED from tokens x rates — --cost/--cost-low/--cost-high are
                declared but always rejected; use estimate-story/estimate-rollup instead)
                [--confidence {low,medium,high}] [--flock]
  set-depends-on --state-root S  (--story KEY | --epic ID)  --add KEY [--add KEY ...]
                (appends to depends_on, the one LIST-shaped field: epic keys on an epic
                node, story keys on a story node -- status-files.md §11. set-field would
                store a list as the string "['E001']", which a reader takes for a scalar.
                Idempotent, order preserved, all-or-nothing: every key is validated
                before anything is written. A sprint node has no depends_on: exit 2)
  import-actual --state-root S  --node story|sprint|epic  (--story KEY | --epic ID [--sprint ID])
                [--elapsed-hours H] [--man-hours H] [--hitl-hours H]
                (an actual OBSERVED ELSEWHERE, for a migration. runtime=other, tokens=N/A and
                no calibration sample are FIXED, not flags: --runtime, --tokens-*, --model and
                --calibrate are absent from its surface, so a call that would claim Claude
                provenance or poison the learned ratios is a usage error rather than a silent
                one. Delegates to set-actual, which is unchanged)
  set-field     --state-root S  (--story KEY | --epic ID [--sprint ID])  --field NAME --value V
                (refuses any field in DERIVED_NODE_FIELDS, any sub-path of one
                (<name>.x), or any parent path of one (completion_evidence, which would
                replace test_runs) -- completion_evidence.tests_passing (use
                add-test-run), status (use set-status), resolves (use promote-issue))
  add-test-run  --state-root S  --story KEY  --command CMD  --exit-code N
                (appends {command, exit_code} to completion_evidence.test_runs and
                derives completion_evidence.tests_passing as all(exit_code == 0) over
                the LAST run of each distinct command -- record failures too, a
                re-run of the same command supersedes them for the boolean only)
  usage         [TRANSCRIPT ...]  [--claude-session ID] [--state-root S]
                [--agent NAME] [--epic ID] [--sprint ID] [--story KEY]
                [--since ISO] [--until ISO] [--allow-unidentified]
                [--model M] [--token-rates JSON] [--format {text,json}]
                (sums a session transcript's token usage by class, for feeding
                set-actual; verifies the transcript's sessionId before summing
                and refuses an unconfirmed file unless --allow-unidentified;
                omit TRANSCRIPT to resolve this session's own transcript from
                $CLAUDE_CODE_SESSION_ID or --claude-session; --state-root plus
                node keys derive a --since/--until window from that node's
                dispatch bracket instead of passing one explicitly)
  verify        --state-root S  --scope {story,sprint,epic}  (--story KEY | --epic ID [--sprint ID])
                [--require-tokens] [--runtime {claude,other}]
                (--scope epic checks structural/back-reference integrity across the
                epic's whole subtree; --scope story/sprint check completion of one node)
  list-epics    --state-root S  [--format keys|json]
                (read-only; empty/absent state -> empty output, exit 0; keys default
                prints one E{nnn} per line, sorted; json prints [{key, bucket, status}, ...]
                with bucket in active/planned/archived order)
  list-stories  --state-root S  --epic E  [--sprint S]  [--format keys|json]
                (read-only; absent epic exits 3; absent sprint -> empty output, exit 0;
                filters out sprint.yaml/epic.yaml and any non-story .yaml files)
  show          --state-root S  --epic ID  [--sprint ID]
  report        --state-root S  [--plan P] [--format tree|json|md] [--out F]
                [--all] [--watch SECS]
  dispatch      --state-root S  --event {open,close}  --agent NAME
                [--epic ID] [--sprint ID] [--story KEY] [--session-id ID]
                (appends a dispatch_open/dispatch_close event to events.jsonl;
                feeds report's stall detection and marks the child/orchestration
                spend boundary -- records timestamps only, never a token count)
  set-lock      --state-root S  --epic ID  --session-id SESS  [--ttl-minutes N]
  clear-lock    --state-root S  --epic ID
  check-lock    --state-root S  --epic ID  --session-id SESS
  append-issue  (--state-root S | --file F)  [--key BL-E{nnn}-{nnn}]  --epic E  [--sprint S]  --title T
                --source S  --severity {Low,Medium,High,Critical}  [--description D]
                [--allow-duplicate]
                [--session-id ID]   (keys: max(next[epic], highest suffix in either
                issue file + 1); an explicit --key is canonicalized and must match --epic)
                (--key omitted allocates the next number for --epic under a lock --
                the caller never invents {nnn}; an explicit --key that already exists
                exits 2, as does allocating past {nnn} = 999. A content duplicate (same
                normalized title/epic/sprint/source)
                of an open item, or of a resolved wontfix/duplicate/obsolete item whose
                severity is at least the new finding's, is skipped (exit 0, nothing written); a
                match against a resolved fixed item is appended as a recurrence, and
                one above a wontfix/duplicate/obsolete severity as re-raised. The
                newest resolved match decides. --allow-duplicate bypasses all of it)
  list-issues   --state-root S  [--epic E] [--sprint S]
                [--severity {Low,Medium,High,Critical}] [--format {text,json}]
                [--status {backlog,scheduled}] [--resolved [--resolution R]] [--all]
                (open items by default; --resolved lists issues-resolved.yaml;
                --all: JSON {open, resolved} under one lock; every JSON item carries
                origin_archived)
                (filters combine with AND; a repeated --severity ORs the given severities;
                a missing issues.yaml, or a filter matching nothing, is success — exit 0
                with an empty result, not an error)
  resolve-issue --state-root S  --key K  --resolution {fixed,wontfix,duplicate,obsolete}
                [--ref R] [--note N] [--session-id ID] [--cause {cli,triage,plan-intake}]
                (moves an open item to issues-resolved.yaml -- resolved file first, open
                file second; fixed needs --ref story key or SHA, duplicate needs --ref an
                open or non-duplicate BL key, wontfix/obsolete need --note; an already
                resolved key exits 0 after clearing any stale open copy)
  update-issue  --state-root S  --key K  --severity {Low,Medium,High,Critical}
                [--note N] [--session-id ID] [--cause {cli,triage,plan-intake}]
                (re-severities an OPEN item; a resolved key exits 2, one in neither
                issue file 3; the severity it already has exits 0 as "unchanged",
                writing no file and no event)
  promote-issue --state-root S  --artifacts-root R  --key K [--key K2 ...]  --epic E
                --sprint S  --classification {simple,standard,complex}  [--title T]
                [--model M] [--token-rates JSON] [--session-id ID] [--cause C]
                (creates an estimated story whose `resolves:` lists the items, writes its
                document, rolls up sprint and epic, then marks the items scheduled; every
                refusal is checked before the first write; a retry after an interrupted
                run resumes the existing story -- only with the same --epic/--sprint (a
                claimant elsewhere exits 2 naming them), and a dead claim (a story under
                archived/ that is not done) is ignored; a foreign epic lock exits 5 when
                check-lock would report it LOCKED, and whenever promote cannot evaluate
                it (not a mapping, no session_id, a missing, unparseable or timezone-less
                claimed_at, a non-integer ttl_minutes); the holder must equal
                --session-id exactly to count as this session's own, as in set-lock and
                check-lock, and a whitespace-only one is no session_id -- clear-lock removes an
                abandoned one; a story node that does not parse, is not valid UTF-8 or
                is not a mapping, or a claimant whose key: is malformed, exits 2 naming
                the file, before any write)
  schedule-issue --state-root S  --key K [--key K2 ...]  --story E{nnn}-S{nn}-{nnn}
                [--session-id ID] [--cause C]
                (attaches open items to a story that ALREADY EXISTS -- the counterpart to
                promote-issue, which only ever creates one; appends each key to the
                story's `resolves:` and marks the items scheduled, story node first so an
                interrupted run leaves finding 1d, which repair-issue --action link
                repairs, rather than 1e, which has no single-key repair; idempotent by
                skip for a key already scheduled to THIS story, exit 2 for one scheduled
                to a different story; exit 3 for an absent story, exit 2 for a story that
                is `done` or whose epic is under archived/, exit 4 on a back-reference
                mismatch; does NOT re-estimate the story or roll up its parents; locks in
                promote-issue's order -- epic_node_lock then one issues_lock spanning the
                decisive check through the save; every refusal is checked before the first
                write)
  audit-issues  --state-root S  [--format {text,json}]
                (read-only integrity checks 1a-1k over both issue files and the story
                nodes' resolves:, read under issues_lock when either issue file exists;
                otherwise the story walk still runs, unlocked, over an empty store;
                a key with a resolved entry is not evaluated for 1b, 1c, 1d, 1f
                or 1g -- its stale open copy shows as 1a, and 1h and 1j still
                apply; a key duplicated within one file (1i) is not evaluated
                for 1b, 1c, 1d, 1f or 1g either; 1d/1h ignore a dead claim -- a
                story under archived/ that is not done; 1j fires only when the
                ref story's resolves: lists the key; 1e also reports every
                non-canonical alias key in next (1 or '1' for '001') whatever its
                value, and any next above 1000; exit 4 when anything is
                found, and on a malformed issue file or a story node that does
                not parse, is not valid UTF-8 or is not a mapping, where
                --format json prints {"findings": [], "error": MSG})
  repair-issue  --state-root S  --key K  --action {unschedule,link,reseed,reopen}
                [--story KEY] [--session-id ID] [--cause C]
                (each action refuses unless its audit finding holds: unschedule 1b/1g,
                link 1d (--story must be the story that lists K), reseed 1e, reopen 1j;
                unschedule and link also refuse a key with a resolved entry -- rerun
                resolve-issue to clear the stale open copy (1a); reseed merges
                non-canonical aliases of the epic's next key by max, drops them, and
                never lowers it, but refuses (nothing written) any of those values
                above 1000;
                unschedule writes an issue_unscheduled event; a story node that does
                not parse, is not valid UTF-8 or is not a mapping exits 2 naming the
                file, before any write)
  move-epic     --state-root S  --epic ID  --to {planned,active,archived}
  archive-epic  --state-root S  --epic ID   (alias for move-epic --to archived)
  calibration   show  --state-root S  [--format {text,json}]
                (inspects pm-calibration.yaml; a missing file is a normal
                cold-start state, not an error)
  estimate-story --state-root S  --story KEY  --classification C
                [--confidence {low,medium,high}] [--model M] [--token-rates JSON]
                (writes estimate = band_mid x scope_ratio x fix_factor, per
                metric, using whichever calibrated scope ratio is active per
                metric; cost is priced from the banded tokens_k total rather
                than banded/calibrated on its own; --model falls back to
                DEFAULT_ESTIMATE_MODEL)
  estimate-rollup --state-root S  --epic ID  [--sprint ID]
                [--model M] [--token-rates JSON]
                (rolls a sprint's story estimates, or an epic's sprint
                estimates, up to the parent as sum(children) + a calibrated
                closure band + a calibrated orchestration band, always in
                range form; omit --sprint for epic-level)
  rates         [--model M] [--token-rates JSON]
                (prints the effective per-class token rate table -- shipped
                defaults merged with any --token-rates/modules.l3io-pm
                override -- so what actually prices tokens is inspectable
                without reading source or guessing; read-only)
  self-install  --dest PATH  [--force]
  adr-reserve   --state-root S  --epic ID  --slug SLUG  [--count N]
                (reserves N sequential ADR numbers under a lock, before dispatch;
                prints one zero-padded number per line; see adr_register_path)
  notice        --state-root S  --key KEY
                (records a one-time-ever advisory notice in {state-root}/.notices.yaml
                under flock, keyed on KEY alone -- there is no session concept that
                outlives one skill invocation, so this is scoped to the project, not a
                session; exit 0 = not yet emitted for KEY (and now recorded), exit 1 =
                already emitted, exit 2 = usage error OR an unexpected recording failure
                (never conflated with exit 1); advisory only -- a damaged notices file
                never blocks the caller, but a failed write is reported, not silently
                treated as success)

Exit codes: 0 = success/verified, 1 = notice already emitted for this key
(notice only), 2 = usage error or, for notice only, an unexpected recording failure,
3 = node not found, 4 = verification failure (missing/invalid field), 5 = epic locked.
Errors go to stderr; machine output (verify summaries) goes to stdout.
"""
from __future__ import annotations

import argparse
import contextlib
import glob
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import UTC, datetime

try:
    from ruamel.yaml import YAML
except ModuleNotFoundError:  # pragma: no cover - environment guard
    sys.stderr.write(
        "pm-status.py: ruamel.yaml is required. Run via `uv run` (auto-provisions it) "
        "or `pip install ruamel.yaml`.\n"
    )
    sys.exit(2)

PM_STATUS_VERSION = "3.2.6"  # keep in sync with the top-of-file `# pm-status-version:` marker

VALID_STORY_STATUS = {"backlog", "ready-for-dev", "in-progress", "review", "done", "blocked"}
VALID_SPRINT_STATUS = {"backlog", "in-progress", "review", "done"}
VALID_EPIC_STATUS = {"backlog", "in-progress", "done"}

# Story transitions. Enforced per-story only; sprints and epics keep their existing
# looser enum-only check because they compose from their children and their transitions
# are driven by roll-ups, not by explicit set-status calls in the middle of a story lifecycle.
# See docs/superpowers/specs/2026-09-25-story-lifecycle-blocked-design.md §3.
#
# The table gates two invariants: the blocked lifecycle (only entered from active work,
# only exited back to work or done-with-resolution) and the terminality of done. Free
# movement between non-blocked, non-done statuses stays allowed -- existing consumers
# have long moved a story backwards after a fix, and forwards past review when the work
# was small enough not to need one, and gating either would be scope creep against a
# design whose stated goal was blocked's cleanliness.
#
# `blocked` can enter only from `in-progress` or `review` -- a story never picked up is
# not blocked, it is just not ready, and its impediment belongs in state/issues.yaml.
# `done` is terminal.
VALID_STORY_TRANSITIONS = {
    "backlog":       {"ready-for-dev", "in-progress", "review", "done"},
    "ready-for-dev": {"backlog", "in-progress", "review", "done"},
    "in-progress":   {"backlog", "ready-for-dev", "review", "done", "blocked"},
    "review":        {"backlog", "ready-for-dev", "in-progress", "done", "blocked"},
    "blocked":       {"in-progress", "done"},   # done requires --resolution
    # done is "operationally reopenable" -- reopen paths, idempotent second-done, and
    # the import-node-then-set-status ordering all move a done story to another non-
    # blocked status. The one thing we still forbid is done -> blocked, so a story
    # reopened for more work goes through in-progress before it can block, which keeps
    # `blocked` entered only from active work rather than from history.
    "done":          {"backlog", "ready-for-dev", "in-progress", "review", "done"},
}
METRIC_FIELDS = ("elapsed_hours", "man_hours", "hitl_hours", "tokens_k", "cost")

# The subset of METRIC_FIELDS whose SCOPE ratio is learned. `cost` is derived
# from tokens x rates (Tasks 6/7) rather than entered or actualed on its own,
# so letting it also accumulate a scope-ratio sample would give a derived
# value an independently-learned correction — exactly the drift this rework
# removes. `cost` deliberately stays IN METRIC_FIELDS: it is still stored,
# verified, and reported, just never scope-calibrated. Derived (not restated)
# from METRIC_FIELDS so the two can't drift apart the way separately-typed
# copies did before.
CALIBRATED_METRIC_FIELDS = tuple(m for m in METRIC_FIELDS if m != "cost")


def _yaml() -> YAML:
    y = YAML()  # round-trip mode: preserves comments + key order
    y.preserve_quotes = True
    y.width = 4096  # never line-wrap scalars
    y.indent(mapping=2, sequence=2, offset=0)  # match the flush-dash status-file style
    return y


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load(path: str):
    y = _yaml()
    if not os.path.exists(path):
        return y, None
    with open(path, "r", encoding="utf-8") as f:
        return y, y.load(f)


def _atomic_dump(y: YAML, data, path: str) -> None:
    """Write to a temp file in the same directory, then os.replace (atomic on POSIX).

    Every node write reaches the disk through here, so this is where the rule "an epic.yaml
    write holds its epic_node_lock" is checked (`_require_epic_lock`)."""
    _require_epic_lock(path)
    d = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".pm-status.", suffix=".tmp", dir=d)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            y.dump(data, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _atomic_create(path: str, text: str) -> bool:
    """Create `path` with `text` only if it does not already exist -- atomically and without
    ever clobbering: write a temp file in the same directory, fsync it, then os.link it into
    place (link fails with FileExistsError when the path exists, where os.replace would
    overwrite). Returns False when the path already existed. The temp file is removed on
    every path, success or failure."""
    d = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".pm-status.", suffix=".tmp", dir=d)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        try:
            os.link(tmp, path)
        except FileExistsError:
            return False
        return True
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


# State roots whose .gitignore this process has already checked (_ensure_lock_ignore).
_LOCK_IGNORE_CHECKED = set()
_LOCK_IGNORE_LINE = "*.lock"
NOTICES_FILENAME = ".notices.yaml"  # the one-time-ever advisory ledger, keyed on --key
                                     # alone (cmd_notice below) -- no pruning: a project's
                                     # set of distinct notice keys stays small by construction
# Every filename pm-status.py writes at a state root that must never reach git: the
# per-family lock sidecars (one glob covers all of them) and the notices ledger.
_GITIGNORE_PATTERNS = (_LOCK_IGNORE_LINE, NOTICES_FILENAME)


def _lock_rule_present(text: str, pattern: str = _LOCK_IGNORE_LINE) -> bool:
    """True when git reads `text` (a .gitignore) as ignoring every `pattern`: some line is
    exactly `pattern` and no LATER line is exactly `!pattern`. Parsed as git parses it: split
    on "\\n" only -- never str.splitlines(), which also breaks on U+0085 and other characters
    git keeps inside a line -- and strip exactly one trailing "\\r", then trailing spaces,
    since leading spaces are part of the pattern. The caller decodes with utf-8-sig, so a
    leading UTF-8 BOM is skipped, as git skips it. A narrower negation such as `!keep.lock`
    is a deliberate user choice and is left as written."""
    present = False
    for raw in text.split("\n"):
        line = raw.removesuffix("\r")
        line = line.rstrip(" ")
        if line == pattern:
            present = True
        elif line == "!" + pattern:
            present = False
    return present


def _missing_ignore_patterns(text: str):
    """Which of `_GITIGNORE_PATTERNS` git does NOT currently read `text` as ignoring."""
    return [p for p in _GITIGNORE_PATTERNS if not _lock_rule_present(text, p)]


def _ensure_lock_ignore(state_root: str) -> None:
    """Make `{state_root}/.gitignore` carry every pattern in `_GITIGNORE_PATTERNS` --
    `*.lock` and `.notices.yaml` -- so neither a lock file nor the notices ledger is ever
    committed.

    Every lock file this script creates is an empty flock target -- the several families in
    the state root and the per-node `.yaml.lock` sidecars below it -- and the sprint-closure
    checkpoint stages the whole state tree; `.notices.yaml` is the one non-lock file this
    script writes at the state root that is equally advisory and equally not for git. Neither
    pattern matches the state-root directory itself, so step-00-activate's `git check-ignore`
    gate still passes.

    Called on EVERY lock acquisition inside a state root, not only when a pattern's file is
    first written: a project whose lock files already exist, or that adopts a newer
    pm-status.py that adds a pattern, gets the missing rule(s) on its next lock. A bare
    `append-issue --file` outside a state root (no status folders, no --state-root) is
    skipped, so it never writes a .gitignore into a repo root (_file_lock). Memoized per
    process, so each state root is checked at most once. Absent file -> created (no-clobber
    _atomic_create) with one comment line and every pattern. Present -> READ first, and only
    when at least one pattern is missing (as git reads it, _lock_rule_present) is it opened
    for append and flocked, then re-checked under the flock so two processes cannot both
    append it -- only the still-missing patterns are written, so an already-satisfied pattern
    is never duplicated; a read-only .gitignore that already has every pattern is never opened
    for writing. Missing lines are appended after a newline when the file lacks a trailing
    one; existing content is never rewritten or reordered. Best-effort: this runs inside the
    lock path, so an OSError or an undecodable file warns once on stderr and returns -- it
    never raises and never fails the verb."""
    root = os.path.realpath(state_root or ".")
    if root in _LOCK_IGNORE_CHECKED:
        return
    _LOCK_IGNORE_CHECKED.add(root)
    path = os.path.join(root, ".gitignore")
    try:
        if not os.path.lexists(path) and _atomic_create(
                path, "# pm-status.py state files -- never commit\n" +
                      "".join(f"{p}\n" for p in _GITIGNORE_PATTERNS)):
            return
        with open(path, "rb") as fh:                # read first: needs no write access
            if not _missing_ignore_patterns(fh.read().decode("utf-8-sig")):
                return
        try:
            import fcntl
        except ImportError:  # pragma: no cover - non-POSIX
            fcntl = None
        with open(path, "a+b") as fh:
            if fcntl is not None:
                fcntl.flock(fh, fcntl.LOCK_EX)
            try:
                fh.seek(0)
                text = fh.read().decode("utf-8-sig")   # re-check under the flock; BOM skipped
                missing = _missing_ignore_patterns(text)
                if not missing:
                    return
                sep = "" if not text or text.endswith("\n") else "\n"
                fh.write((sep + "".join(f"{p}\n" for p in missing)).encode("utf-8"))
                fh.flush()
            finally:
                if fcntl is not None:
                    fcntl.flock(fh, fcntl.LOCK_UN)
    except (OSError, UnicodeDecodeError) as e:
        sys.stderr.write(f"pm-status.py: warning -- could not add "
                         f"{', '.join(_GITIGNORE_PATTERNS)} to {path}: {e}\n")


def _state_root_of_node(path: str):
    """The state root above a node file: the parent of the nearest ancestor named for a
    status folder (active/planned/archived). None when there is no such ancestor."""
    d = os.path.dirname(os.path.abspath(path))
    while True:
        parent = os.path.dirname(d)
        if os.path.basename(d) in STATUS_DIRS:
            return parent
        if parent == d:
            return None
        d = parent


def _flock_write_or_plain(use_flock: bool, y: YAML, data, path: str) -> None:
    """Acquire an exclusive flock on `path` (or a sidecar .lock file) then atomic-dump."""
    if not use_flock:
        _atomic_dump(y, data, path)
        return
    try:
        import fcntl
    except ImportError:
        # Windows or environments without fcntl — fall back to plain write with a warning
        sys.stderr.write("pm-status.py: fcntl unavailable — writing without flock (non-POSIX)\n")
        _atomic_dump(y, data, path)
        return
    lock_path = path + ".lock"
    d = os.path.dirname(os.path.abspath(lock_path)) or "."
    os.makedirs(d, exist_ok=True)
    state_root = _state_root_of_node(path)
    if state_root is not None:                  # never a .gitignore inside a node directory
        _ensure_lock_ignore(state_root)
    with open(lock_path, "w") as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        try:
            _atomic_dump(y, data, path)
        finally:
            fcntl.flock(lf, fcntl.LOCK_UN)


# --------------------------------------------------------------------------- #
# Sharded layout resolution — the ONLY place that knows where nodes live on disk
# --------------------------------------------------------------------------- #
STATUS_DIRS = ("active", "planned", "archived")  # active first: hottest path

# Layout knowledge belongs in the resolver section with everything else that knows
# where a node lives. DIR_FOR_STATUS is DERIVED, never written out a second time --
# two hand-kept halves of one mapping is how they drift apart.
STATUS_FOR_DIR = {"planned": "backlog", "active": "in-progress", "archived": "done"}
DIR_FOR_STATUS = {status: folder for folder, status in STATUS_FOR_DIR.items()}


def epic_dirname(epic_key: str) -> str:
    """'E001' -> 'epic-001'. Accepts unpadded input ('E42' -> 'epic-042')."""
    n = str(epic_key).strip().lstrip("Ee")
    if not n.isdigit():
        raise ValueError(f"bad epic key: {epic_key!r}")
    return f"epic-{int(n):03d}"


def sprint_dirname(sprint_key: str) -> str:
    """'S01' -> 'sprint-01'. Accepts unpadded input ('S7' -> 'sprint-07')."""
    n = str(sprint_key).strip().lstrip("Ss")
    if not n.isdigit():
        raise ValueError(f"bad sprint key: {sprint_key!r}")
    return f"sprint-{int(n):02d}"


def parse_story_key(key: str) -> tuple:
    """'E001-S01-003' -> ('E001', 'S01', '003')."""
    parts = str(key).strip().split("-")
    if len(parts) != 3 or not parts[0].startswith("E") or not parts[1].startswith("S"):
        raise ValueError(f"bad story key: {key!r} (expected E{{nnn}}-S{{nn}}-{{nnn}})")
    return parts[0], parts[1], parts[2]


def find_epic_dir(state_root: str, epic_key: str):
    """Absolute path to the epic's directory, whichever status folder holds it."""
    name = epic_dirname(epic_key)
    for status in STATUS_DIRS:
        p = os.path.join(state_root, status, name)
        if os.path.isdir(p):
            return p
    return None


def iter_epic_dirs(state_root: str):
    """Yield (bucket, epic_key, epic_dir_path) for every epic directory in the state tree.

    Missing state root yields nothing. Order: bucket in STATUS_DIRS order (active,
    planned, archived), key sorted within each bucket. Non-conforming entries
    (a directory that does not match epic-{nnn}, a regular file with that name) are
    skipped silently -- they are not this enumerator's concern.

    The one enumerator behind list-epics; also the enumerator a future caller uses to
    answer "does this epic exist and in which bucket?" without probing filesystem paths.
    """
    if not os.path.isdir(state_root):
        return
    for bucket in STATUS_DIRS:
        bucket_dir = os.path.join(state_root, bucket)
        if not os.path.isdir(bucket_dir):
            continue
        for name in sorted(os.listdir(bucket_dir)):
            if not name.startswith("epic-"):
                continue
            p = os.path.join(bucket_dir, name)
            if not os.path.isdir(p):
                continue
            suffix = name[len("epic-"):]
            if not (suffix.isdigit() and len(suffix) == 3):
                continue
            yield bucket, f"E{suffix}", p


def iter_story_files(state_root: str, epic_key: str, sprint_key=None):
    """Yield (story_key, story_file_path) for every story node file under an epic,
    optionally scoped to one sprint.

    A missing epic yields nothing (callers check find_epic_dir separately when they
    want to distinguish absent from empty). Files that are not stories -- sprint.yaml,
    epic.yaml, a .yaml.lock sidecar, anything whose name does not parse as
    E{nnn}-S{nn}-{nnn} -- are filtered out here so callers do not have to.
    """
    d = find_epic_dir(state_root, epic_key)
    if d is None:
        return
    target_sprint_dir = sprint_dirname(sprint_key) if sprint_key is not None else None
    for sd_path in list_sprint_dirs(state_root, epic_key):
        sd_name = os.path.basename(sd_path)
        if target_sprint_dir is not None and sd_name != target_sprint_dir:
            continue
        for name in sorted(os.listdir(sd_path)):
            if not name.endswith(".yaml"):
                continue
            story_key = name[:-len(".yaml")]
            try:
                parse_story_key(story_key)
            except ValueError:
                continue
            yield story_key, os.path.join(sd_path, name)


def epic_file(state_root: str, epic_key: str):
    d = find_epic_dir(state_root, epic_key)
    if d is None:
        return None
    p = os.path.join(d, "epic.yaml")
    return p if os.path.exists(p) else None


def sprint_file(state_root: str, epic_key: str, sprint_key: str):
    d = find_epic_dir(state_root, epic_key)
    if d is None:
        return None
    p = os.path.join(d, sprint_dirname(sprint_key), "sprint.yaml")
    return p if os.path.exists(p) else None


def story_file(state_root: str, story_key: str):
    epic_key, sprint_key, _ = parse_story_key(story_key)
    d = find_epic_dir(state_root, epic_key)
    if d is None:
        return None
    p = os.path.join(d, sprint_dirname(sprint_key), f"{story_key}.yaml")
    return p if os.path.exists(p) else None


def load_node(path: str):
    """Load a bare node file (no `epics:` wrapper). Returns (yaml, node|None)."""
    return _load(path)


def save_node(y, node, path: str, use_flock: bool = False) -> None:
    _flock_write_or_plain(use_flock, y, node, path)


def check_backrefs(node, epic_key: str, sprint_key: str | None = None) -> list:
    """Compare a node's parent back-references against its resolved location.

    An ABSENT back-reference is a failure, not a pass. Sprint and story files are
    required to carry `epic:` (and stories `sprint:`) — see status-files.md §4 — and
    migrate-state adds them as a brand-new step, so "field missing entirely" is exactly
    the case this check has to catch. Epic nodes have no parent and are never passed
    here (callers skip them).
    """
    problems = []
    if node is None:
        return ["node is empty"]
    got_epic = str(node.get("epic", "")).strip()
    if not got_epic:
        problems.append(f"epic back-reference absent (expected {str(epic_key).strip()!r})")
    elif got_epic != str(epic_key).strip():
        problems.append(f"epic back-reference {got_epic!r} != path epic {epic_key!r}")
    if sprint_key is not None:
        got_sprint = str(node.get("sprint", "")).strip()
        if not got_sprint:
            problems.append(f"sprint back-reference absent (expected {str(sprint_key).strip()!r})")
        elif got_sprint != str(sprint_key).strip():
            problems.append(f"sprint back-reference {got_sprint!r} != path sprint {sprint_key!r}")
    return problems


def resolve_node_path(state_root: str, args, kind: str):
    """Resolve a node kind + keys to (path, label). Exits 3 when the node is absent."""
    if kind == "story":
        if not args.story:
            _die_usage("--story is required for a story node")
        p = story_file(state_root, args.story)
        label = f"story {args.story}"
    elif kind == "sprint":
        if not (args.epic and args.sprint):
            _die_usage("--epic and --sprint are required for a sprint node")
        p = sprint_file(state_root, args.epic, args.sprint)
        label = f"epic {args.epic} sprint {args.sprint}"
    elif kind == "epic":
        if not args.epic:
            _die_usage("--epic is required for an epic node")
        p = epic_file(state_root, args.epic)
        label = f"epic {args.epic}"
    else:
        _die_usage(f"unknown node kind: {kind}")
    if p is None:
        _die_notfound(label)
    return p, label


def ensure_node_path(state_root: str, args, kind: str, status: str):
    """Resolve a node kind + keys to (path, label), CREATING the directory when absent.

    The counterpart to resolve_node_path() for the one case that function cannot serve:
    a node that does not exist yet. It is the ONLY function that creates a state
    directory, and it lives here -- in the section that is the only place a key becomes
    a location -- on purpose. A mkdir in a subcommand body is exactly how that invariant
    breaks; check 26 in check-docs.mjs fails the build if one appears.

    A NEW epic is placed by its status, per the placement rule. An epic that already has
    a directory is left where it is: relocating on a status change is move-epic's job,
    which uses `git mv` so history survives. Sprints and stories require their epic's
    directory to exist and exit 3 when it does not.
    """
    if kind == "epic" and status not in DIR_FOR_STATUS:
        _die_usage(
            f"cannot place a new epic with status {status!r} -- "
            f"expected one of {sorted(DIR_FOR_STATUS)}"
        )
    if kind == "epic":
        if not args.epic:
            _die_usage("--epic is required for an epic node")
        d = find_epic_dir(state_root, args.epic)
        if d is None:
            d = os.path.join(state_root, DIR_FOR_STATUS[status], epic_dirname(args.epic))
        os.makedirs(d, exist_ok=True)
        return os.path.join(d, "epic.yaml"), f"epic {args.epic}"

    if kind == "sprint":
        if not (args.epic and args.sprint):
            _die_usage("--epic and --sprint are required for a sprint node")
        d = find_epic_dir(state_root, args.epic)
        if d is None:
            _die_notfound(f"epic {args.epic} (create it before its sprints)")
        sd = os.path.join(d, sprint_dirname(args.sprint))
        os.makedirs(sd, exist_ok=True)
        return os.path.join(sd, "sprint.yaml"), f"epic {args.epic} sprint {args.sprint}"

    if kind == "story":
        if not args.story:
            _die_usage("--story is required for a story node")
        epic_key, sprint_key, _ = parse_story_key(args.story)
        d = find_epic_dir(state_root, epic_key)
        if d is None:
            _die_notfound(f"epic {epic_key} (create it before its stories)")
        sd = os.path.join(d, sprint_dirname(sprint_key))
        os.makedirs(sd, exist_ok=True)
        return os.path.join(sd, f"{args.story}.yaml"), f"story {args.story}"

    _die_usage(f"unknown node kind: {kind}")


def _load_checked(state_root: str, args, kind: str):
    """Resolve, load, and validate back-references. Exits 3 (missing) or 4 (misplaced)."""
    path, label = resolve_node_path(state_root, args, kind)
    y, node = load_node(path)
    if node is None:
        _die_notfound(f"{label} — file {path} is empty")
    if kind == "story":
        ek, sk, _ = parse_story_key(args.story)
        problems = check_backrefs(node, ek, sk)
    elif kind == "sprint":
        problems = check_backrefs(node, args.epic)
    else:
        problems = []
    if problems:
        sys.stderr.write(f"pm-status.py: back-reference mismatch for {label}: {'; '.join(problems)}\n")
        sys.exit(4)
    return y, node, path, label


def _infer_kind(args) -> str:
    if args.story:
        return "story"
    if args.epic and args.sprint:
        return "sprint"
    if args.epic:
        return "epic"
    _die_usage("specify --story, or --epic [--sprint]")


def _epic_write_lock(args, kind, require_exists: bool = True):
    """epic_node_lock around a node verb's read-modify-write when the node is an epic; no
    lock for a sprint or story, whose files are not epic.yaml. Resolves the epic first, so
    an absent one exits 3 exactly as before with no lock file created; the verb resolves
    again inside the hold, since a move-epic may land while it waits.

    require_exists=False is for import-node, whose whole purpose is the node that does not
    exist yet. It still takes the lock -- a concurrent import of the same epic must
    serialise -- it just does not demand the node be there first. Every other caller keeps
    the default, so their behaviour is unchanged.
    """
    if kind != "epic":
        return contextlib.nullcontext()
    if require_exists:
        resolve_node_path(args.state_root, args, "epic")
    return epic_node_lock(args.state_root, args.epic)


def _die_usage(msg: str):
    sys.stderr.write(f"pm-status.py: {msg}\n")
    sys.exit(2)


def _die_notfound(what: str):
    sys.stderr.write(f"pm-status.py: node not found — {what}\n")
    sys.exit(3)


class PMError(Exception):
    """A refusal or failure raised by a non-exiting core function.

    Core functions never call sys.exit: in-process callers -- the set-status done
    hook, promote-issue's estimate -- must be able to catch a failure. Only a cmd_
    wrapper turns one into an exit code, through _run_core."""

    def __init__(self, code: int, msg: str):
        super().__init__(msg)
        self.code = code
        self.msg = msg


def _run_core(fn) -> int:
    """Run a cmd_ body, mapping PMError onto the exit-code contract."""
    try:
        return fn()
    except PMError as e:
        sys.stderr.write(f"pm-status.py: {e.msg}\n")
        return e.code


EVENTS_FILENAME = "events.jsonl"


def events_path(state_root: str) -> str:
    """The one project-level event log. A single log (not one per sprint) keeps the
    progress report a single read and makes cross-epic velocity computable."""
    return os.path.join(state_root, EVENTS_FILENAME)


def append_event(state_root: str, payload: dict) -> None:
    """Append one JSON line under flock. NEVER raises: telemetry must not be able to
    fail a status write, matching the calibration contract in set-actual."""
    try:
        p = events_path(state_root)
        os.makedirs(os.path.dirname(os.path.abspath(p)) or ".", exist_ok=True)
        line = json.dumps(payload, sort_keys=True) + "\n"
        try:
            import fcntl
        except ImportError:  # pragma: no cover - non-POSIX
            fcntl = None
        with open(p, "a", encoding="utf-8") as fh:
            if fcntl is not None:
                fcntl.flock(fh, fcntl.LOCK_EX)
            try:
                fh.write(line)
                fh.flush()
            finally:
                if fcntl is not None:
                    fcntl.flock(fh, fcntl.LOCK_UN)
    except Exception as e:  # noqa: BLE001 - deliberate: never fail the caller
        sys.stderr.write(f"pm-status.py: warning — could not append event: {e}\n")


def _event_keys(kind: str, args) -> dict:
    """Node-identifying fields for an event payload, by node kind."""
    if kind == "story":
        epic_key, sprint_key, _ = parse_story_key(args.story)
        return {"node": "story", "key": args.story, "epic": epic_key, "sprint": sprint_key}
    # Canonical, not raw. `_dispatch_identity` is (agent, epic, sprint, story), so a close
    # spelled differently from its open never cancels it and the dispatch reports as
    # permanently stalled in `report --stall-minutes`. Measured: open --epic 003 then close
    # --epic E003 leaves 1 dispatch open. The story branch above already yields key form via
    # parse_story_key; these two now match it instead of echoing the caller.
    if kind == "sprint":
        sk = canonical_sprint_key(args.sprint)
        return {"node": "sprint", "key": sk, "epic": canonical_epic_key(args.epic), "sprint": sk}
    ek = canonical_epic_key(args.epic)
    return {"node": "epic", "key": ek, "epic": ek, "sprint": None}


# Fixed thresholds, in hours. Deliberately not configurable in this iteration: the
# calibration data needed to tune them is what this report will generate.
STUCK_THRESHOLDS = {
    ("story", "in-progress"): 4.0,
    ("story", "review"): 4.0,
    ("sprint", "in-progress"): 24.0,
    ("epic", "in-progress"): 72.0,
}


def _parse_iso(ts):
    """Parse a pm-status timestamp into an aware datetime, or None if unusable."""
    if not ts:
        return None
    try:
        return datetime.fromisoformat(str(ts).strip())
    except (TypeError, ValueError):
        return None


def _lock_age_minutes(claimed, now=None) -> float:
    """Minutes elapsed since `claimed` (an aware datetime, e.g. from `_parse_iso`).

    Shared by cmd_check_lock and cmd_set_lock so their TTL arithmetic cannot diverge
    into two independently-wrong implementations.
    """
    return ((now or datetime.now(UTC)) - claimed).total_seconds() / 60.0


def build_events_index(state_root: str) -> dict:
    """key -> the most recent *status* event for that key.

    Returns {} when the log is absent, which is the normal case for every project
    predating it — callers then fall back to `updated_at`.
    """
    idx: dict = {}
    p = events_path(state_root)
    if not os.path.isfile(p):
        return idx
    try:
        with open(p, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except ValueError:
                    continue  # a torn or hand-mangled line must not kill the report
                if not isinstance(ev, dict):
                    continue
                if ev.get("event") != "status" or not ev.get("key"):
                    continue
                k = _indexable_key(ev["key"])      # a non-empty list is truthy AND unhashable
                if k is None:
                    continue
                prev = idx.get(k)
                if prev is None or str(ev.get("ts", "")) >= str(prev.get("ts", "")):
                    idx[k] = ev
    except OSError as e:
        sys.stderr.write(f"pm-status.py: warning — could not read event log: {e}\n")
    return idx


DEFAULT_STALL_MINUTES = 15


def cmd_dispatch(args) -> int:
    """Record a subagent dispatch opening or closing.

    Two consumers, one event pair rather than two parallel logs that can
    disagree: `open_dispatches` (stall detection) reads it here, and the closing
    agent reads it to place the boundary between a child's spend and the
    orchestrator's (metrics-contract.md §6, "Where the boundary between 'child'
    and 'orchestration' is").

    NOT a derivation of orchestration spend. This script has no access to a
    session transcript and cannot see a token count; it records two timestamps.
    The counts are read from the transcript's `usage` fields by the agent, as for
    every other metric — these events remove the judgement about where one
    bucket ends and the next begins, not the reading.
    """
    payload = {"ts": _now_iso(),
               "event": "dispatch_open" if args.event == "open" else "dispatch_close",
               "agent": args.agent,
               "session": getattr(args, "session_id", None)}
    # Canonical, not raw. This is the fifth write site of the same class and the one that
    # matters: _dispatch_identity is (agent, epic, sprint, story), so an open and a close
    # spelled differently are different dispatches and the close never cancels the open --
    # the dispatch then reports as permanently stalled. --story is strict (a non-canonical
    # key is rejected outright), so it passes through unchanged.
    _canon = {"epic": canonical_epic_key, "sprint": canonical_sprint_key}
    for k in ("epic", "sprint", "story"):
        v = getattr(args, k, None)
        if v:
            payload[k] = _canon[k](v) if k in _canon else v
    # Resolve the match BEFORE appending: this close is itself a close record, so
    # a scan taken afterwards has already cancelled the open it is reporting on.
    matched = None
    if args.event == "close":
        matched = _pending_dispatches(args.state_root).get(_dispatch_identity(payload))
    append_event(args.state_root, payload)
    if args.event != "close":
        sys.stdout.write(f"OK dispatch {args.event} {args.agent}\n")
    elif matched is not None:
        # An orphan close stays exit 0 -- legitimate on a log that may begin
        # mid-run -- but the verb could not previously tell the two cases apart,
        # so a close that cancelled nothing read exactly like one that worked.
        sys.stdout.write(f"OK dispatch close {args.agent} "
                         f"(cancelled open from {matched.get('ts')})\n")
    else:
        sys.stdout.write(f"OK dispatch close {args.agent} (no matching open found)\n")
    return 0


def _hashable_field(v):
    """A hashable stand-in for a field read out of `events.jsonl`.

    Used by every reader over that log that keys a dict on a record field. The log is
    append-only, written by concurrent flock'd writers and documented as possibly torn,
    so a field can hold any JSON type -- and a list or a dict is unhashable, which turns
    `idx[rec["key"]]` into `TypeError: unhashable type` and takes down the reader.

    The readers all guarded the RECORD (`isinstance(rec, dict)`) and none guarded a
    field inside it, so the same defect existed four times over: in
    `_dispatch_identity`, where it crashed `report --watch`; in `build_events_index`,
    where `ev.get("key")` was only truthy-checked and a non-empty list is truthy; and in
    `actual_event_times`, where `k not in idx` raises exactly as a subscript does -- a
    membership test is not the safe alternative to indexing.

    `str()` is a floor that keeps the scan alive and the record distinguishable, not a
    conversion any caller should rely on: a malformed field has no correct value, and
    inventing one would be worse than carrying it through as its own repr.

    Carrying through is right HERE and wrong for an index -- see `_indexable_key`.
    """
    return v if isinstance(v, (str, int, float, bool)) else str(v)


def _indexable_key(v):
    """A node key usable as an index key, or None when the field cannot be one.

    The counterpart to `_hashable_field`, and the difference is the reader's job, not a
    preference. `_dispatch_identity` only needs INTERNAL consistency -- an open and its
    close hashing alike -- so a malformed field carried through under its repr still
    matches its own close, and dropping it would make that dispatch permanently
    uncloseable. An index keyed by node key is looked up BY a real node key, so a value
    that no node could ever have is not a key: carrying it adds a phantom entry
    corresponding to nothing, and dropping it loses nothing real.

    Returns None for a list, a dict, or an empty/whitespace-only string. The caller
    skips the record, which is what "a torn line must not kill the read" has always
    meant one level up.
    """
    if not isinstance(v, (str, int, float)) or isinstance(v, bool):
        return None
    k = str(v).strip()
    return k or None


def _dispatch_identity(rec: dict) -> tuple:
    """What makes two dispatch records the same dispatch. Agent plus node keys —
    a story-level retry of the same agent reuses the identity deliberately, so a
    close always cancels the most recent matching open.

    Node keys are canonicalised HERE, on read, rather than trusted as stored. The
    write sites canonicalise too, but a write site can only govern records written
    after it: `events.jsonl` is append-only, so an open written before the
    write-side fix holds the caller's spelling ('01') while every close now holds
    'S01'. Comparing the two raw left those dispatches permanently uncloseable,
    with no CLI route to clear them, because the canonical write path cannot emit
    a close that matches a non-canonical open. Canonicalising on read makes every
    historical spelling comparable with no rewrite of the log, which is sound
    because both key functions are idempotent ('S01' -> 'S01') and total
    (`_norm_num` falls back to the stripped string rather than raising).

    Every element is forced hashable. This tuple is a dict key on the stall
    dashboard's read path, and a record whose field held a list used to raise
    `TypeError: unhashable type` out of `pending[...]` — crashing the exact
    surface `_pending_dispatches` documents itself as reading defensively for.
    Guarding the whole record (`isinstance(rec, dict)`) never covered a single
    field inside it.
    """
    agent, epic = rec.get("agent"), rec.get("epic")
    sprint, story = rec.get("sprint"), rec.get("story")
    return (None if agent is None else _hashable_field(agent),
            None if epic is None else canonical_epic_key(epic),
            None if sprint is None else canonical_sprint_key(sprint),
            None if story is None else _hashable_field(story))


def _pending_dispatches(state_root: str) -> dict:
    """`_dispatch_identity` -> the open record still outstanding for it.

    The one scan behind both `open_dispatches` (which then applies an age
    threshold) and the `dispatch --event close` report, so the question "is there
    an open matching this close?" is answered by the same matching rule that
    decides whether a dispatch shows as stalled. Answering it twice, two ways, is
    how the two could disagree.

    Reads defensively, exactly as `build_events_index` does over the same file:
    the log is appended to by concurrent flock'd writers and is documented as
    possibly torn, so a valid-JSON line that is not an object (a bare `42` from a
    torn write or a hand-edit) must be skipped, not dereferenced, and an OSError
    must warn rather than abort. This is the read behind `report --watch`, the
    stall dashboard — a crash here takes down precisely the surface the stall
    feature exists to provide. `_dispatch_identity` carries the same obligation
    down to the individual field.
    """
    path = events_path(state_root)
    if not os.path.exists(path):
        return {}
    pending: dict = {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(rec, dict):
                    continue
                ev = rec.get("event")
                if ev == "dispatch_open":
                    pending[_dispatch_identity(rec)] = rec
                elif ev == "dispatch_close":
                    pending.pop(_dispatch_identity(rec), None)
    except OSError as e:
        sys.stderr.write(f"pm-status.py: warning — could not read event log: {e}\n")
    return pending


def open_dispatches(state_root: str, threshold_minutes: float, now=None) -> list:
    """Dispatches opened and never closed, older than the threshold, oldest first.

    Cannot interrupt a hang — makes it visible. A close with no matching open is
    ignored rather than treated as an error: events.jsonl is append-only and may
    begin mid-run on a pre-existing project. The close verb reports which case it
    was (see `_dispatch_close_report`), so "ignored" never means "unreported".
    """
    pending = _pending_dispatches(state_root)
    if now is None:
        now = datetime.now(UTC)
    out = []
    for rec in pending.values():
        opened = _parse_iso(rec.get("ts"))
        if opened is None:
            continue
        age = (now - opened).total_seconds() / 60.0
        if age < threshold_minutes:
            continue
        out.append({"agent": rec.get("agent"), "epic": rec.get("epic"),
                    "sprint": rec.get("sprint"), "story": rec.get("story"),
                    "opened_at": rec.get("ts"), "age_minutes": round(age, 1)})
    return sorted(out, key=lambda r: r["opened_at"])


def dwell_hours(node, events_index: dict, now=None):
    """Hours the node has been in its CURRENT status.

    Returns (hours, exact). `exact` is True only when the event log recorded the
    transition into this very status. The `updated_at` fallback is approximate
    because any field write refreshes it, not only a status change.
    """
    if node is None:
        return None, False
    now = now or datetime.now(UTC)
    status = str(node.get("status", ""))
    key = str(node.get("key", ""))
    ev = (events_index or {}).get(key)
    if ev is not None and str(ev.get("to", "")) == status:
        started = _parse_iso(ev.get("ts"))
        if started is not None:
            return max(0.0, (now - started).total_seconds() / 3600.0), True
    started = _parse_iso(node.get("updated_at"))
    if started is None:
        return None, False
    return max(0.0, (now - started).total_seconds() / 3600.0), False


def compute_flags(level: str, key: str, status: str, dwell, exact: bool) -> list:
    """Stuck flags for one node. Terminal and waiting statuses are never flagged."""
    if dwell is None:
        return []
    threshold = STUCK_THRESHOLDS.get((level, str(status)))
    if threshold is None or dwell < threshold:
        return []
    return [{"kind": "stuck", "level": level, "key": key, "status": str(status),
             "dwell_hours": round(dwell, 2), "threshold": threshold, "exact": exact}]


def _epic_path_or_die(args) -> str:
    """Resolve epic path from args.state_root and args.epic; exit 3 if not found."""
    p = epic_file(args.state_root, args.epic)
    if p is None:
        _die_notfound(f"epic {args.epic}")
    return p


# --------------------------------------------------------------------------- #
# computed roll-ups — sprint/epic aggregates over per-story child files
# --------------------------------------------------------------------------- #
def list_sprint_dirs(state_root: str, epic_key: str) -> list:
    """Sorted sprint directories for an epic. Lexical sort is correct order (zero-padded)."""
    d = find_epic_dir(state_root, epic_key)
    if d is None:
        return []
    return sorted(os.path.join(d, n) for n in os.listdir(d)
                  if n.startswith("sprint-") and os.path.isdir(os.path.join(d, n)))


def _sprint_key_from_dir(sprint_dir_path: str) -> str:
    """'.../epic-001/sprint-01' -> 'S01'. Inverse of sprint_dirname for a path from
    list_sprint_dirs."""
    return "S" + os.path.basename(sprint_dir_path).split("-")[1]


# --------------------------------------------------------------------------- #
# Calibration — the learning loop. See references/metrics-contract.md §8.
# The file is a SHARED append target: every set-actual across parallel
# subagents may append to it, so the WHOLE read-modify-write cycle runs under
# one exclusive lock (`calibration_lock`) — not just the write. Locking only
# the write let two concurrent samplers each read the same pre-append state and
# the second one silently clobber the first's sample. Unlike node files, which
# are sharded per story precisely to avoid contention.
# --------------------------------------------------------------------------- #
CALIBRATION_SCHEMA_VERSION = 2
MIN_SAMPLES = 3          # a component below this is recorded but not applied
DECAY = 0.8              # exponential decay, applied oldest-first
COLD_START_SCOPE_RATIO = 1.0
COLD_START_FIX_FACTOR = 1.25
CLASSIFICATIONS = ("simple", "standard", "complex")
CLOSURE_LEVELS = ("sprint", "epic")


def calibration_path(state_root: str) -> str:
    return os.path.join(state_root, "pm-calibration.yaml")


def new_calibration(granularity: str = "story"):
    from ruamel.yaml.comments import CommentedMap
    cal = CommentedMap()
    cal["version"] = CALIBRATION_SCHEMA_VERSION
    cal["granularity"] = granularity
    cal["scope"] = CommentedMap((c, CommentedMap()) for c in CLASSIFICATIONS)
    cal["closure"] = CommentedMap((lv, CommentedMap()) for lv in CLOSURE_LEVELS)
    cal["fix"] = CommentedMap((c, CommentedMap()) for c in CLASSIFICATIONS)
    # Unlike closure, orchestration has no estimated band to measure a ratio
    # against (it ships null by design — see record_orchestration_sample), so
    # it is seeded empty here and filled by set-actual --block orchestration.
    cal["orchestration"] = CommentedMap((lv, CommentedMap()) for lv in CLOSURE_LEVELS)
    return cal


def load_calibration(state_root: str):
    """Load the calibration file, or a fresh skeleton if absent. Never raises."""
    p = calibration_path(state_root)
    y, data = _load(p)
    if data is None:
        return _yaml(), new_calibration()
    for key, default in (("scope", CLASSIFICATIONS), ("fix", CLASSIFICATIONS),
                         ("closure", CLOSURE_LEVELS), ("orchestration", CLOSURE_LEVELS)):
        if key not in data or data[key] is None:
            from ruamel.yaml.comments import CommentedMap
            data[key] = CommentedMap((k, CommentedMap()) for k in default)
    if "granularity" not in data:
        data["granularity"] = "story"
    return y, data


# Re-entrant within a process: flock is held per open file description, so a
# second open()+LOCK_EX from the same process would deadlock against itself.
# The depth counter lets save_calibration nest inside calibration_lock (which
# is exactly what the record_* paths do) without reacquiring.
_CAL_LOCK = {"depth": 0, "fh": None}


@contextlib.contextmanager
def _file_lock(lock_path: str, depth_state: dict, state_root: str | None = None):
    """Exclusive flock over a read-modify-write cycle, reentrant per process.

    Extracted from calibration_lock so the ADR register can hold a lock without a
    second implementation. The reentrancy counter is the part that must not be
    re-derived by hand: a nested acquire that re-opens the file drops the outer
    hold on close, and the failure only appears under real parallelism.

    `depth_state` is a dict private to one lock family (e.g. `_CAL_LOCK` or
    `_ADR_LOCK`) with at least a `"depth"` key; each family gets its own dict so
    a calibration hold and an ADR-register hold never share depth counting.

    `state_root` is the root whose .gitignore gets `*.lock` (_ensure_lock_ignore). The
    calibration, ADR and epic families pass theirs, and issues_lock passes the issues file's
    directory whenever that path came from a state root. Without one -- only a bare
    `append-issue --file X` -- the lock's own directory is used only if it holds a status
    folder: X's directory might be the repo root, where `*.lock` would silently ignore
    uv.lock, yarn.lock and Cargo.lock repo-wide.
    """
    if depth_state["depth"] > 0:               # already held by this process
        depth_state["depth"] += 1
        try:
            yield
        finally:
            depth_state["depth"] -= 1
        return
    try:
        import fcntl
    except ImportError:  # pragma: no cover - non-POSIX
        sys.stderr.write(f"pm-status.py: fcntl unavailable — {lock_path} is not "
                         f"lock-protected (non-POSIX)\n")
        yield
        return
    lock_dir = os.path.dirname(os.path.abspath(lock_path)) or "."
    os.makedirs(lock_dir, exist_ok=True)
    if state_root is not None:
        _ensure_lock_ignore(state_root)
    elif any(os.path.isdir(os.path.join(lock_dir, s)) for s in STATUS_DIRS):
        _ensure_lock_ignore(lock_dir)           # a bare --file that does sit in a state root
    fh = open(lock_path, "w")  # noqa: SIM115 -- the fd outlives this statement; flock holds it until the finally
    fcntl.flock(fh, fcntl.LOCK_EX)
    depth_state["depth"], depth_state["fh"] = 1, fh
    try:
        yield
    finally:
        depth_state["depth"], depth_state["fh"] = 0, None
        try:
            fcntl.flock(fh, fcntl.LOCK_UN)
        finally:
            fh.close()


@contextlib.contextmanager
def calibration_lock(state_root: str):
    """Hold an exclusive lock over a whole calibration read-modify-write cycle.

    `save_calibration` alone is not enough: load -> mutate -> save is not atomic,
    so two parallel `set-actual` calls could both load the same file and the
    second save would drop the first's sample. Callers that mutate must wrap the
    load AND the save in this.
    """
    with _file_lock(calibration_path(state_root) + ".lock", _CAL_LOCK, state_root):
        yield


_ADR_LOCK = {"depth": 0, "fh": None}


@contextlib.contextmanager
def adr_register_lock(state_root: str):
    """Hold an exclusive lock over a whole ADR-register read-modify-write cycle.

    Same reasoning as calibration_lock: load -> mutate -> save is not atomic, and
    this is exactly the register two parallel adr-reserve calls must not race on.
    """
    with _file_lock(adr_register_path(state_root) + ".lock", _ADR_LOCK, state_root):
        yield


def notices_path(state_root: str) -> str:
    return os.path.join(state_root, NOTICES_FILENAME)


_NOTICES_LOCK = {"depth": 0, "fh": None}


@contextlib.contextmanager
def notices_lock(state_root: str):
    """Hold an exclusive lock over a whole notices read-modify-write cycle.

    Same reasoning as calibration_lock and adr_register_lock: load -> mutate -> save is
    not atomic, and two concurrent callers -- e.g. `l3io-execute` and `l3io-plan`
    invoked around the same time in one project -- must not both decide the same key has
    not been shown yet and each write their own "now recorded" copy, silently dropping one.
    """
    with _file_lock(notices_path(state_root) + ".lock", _NOTICES_LOCK, state_root):
        yield


_ISSUES_LOCK = {"depth": 0, "fh": None}


@contextlib.contextmanager
def issues_lock(file_path: str, bare_file: bool = False):
    """Hold an exclusive lock over a whole issues.yaml read-modify-write cycle.

    Same reasoning as calibration_lock/adr_register_lock: load -> allocate a key
    -> dedupe-check -> mutate -> save is not atomic, and `issues.yaml` is a shared
    append target across every epic and every parallel subagent -- exactly what
    ADR numbers needed a register for after two parallel agents both read the
    same near-empty directory and chose the same number. The lock file is keyed off
    the OPEN issues file's path: `issues_paths(state_root)[0]` for every issue verb,
    which all address the files through `--state-root` (status-files.md §7), or
    `append-issue`'s compatibility `--file`, which must equal that path when
    `--state-root` is also given -- so both addressing forms contend on one lock. The
    resolved file lives beside it and is covered by the same hold (IssueStore loads
    both issue files under it).

    `bare_file` is True only for `append-issue --file` given without --state-root. Every
    other path is `issues_paths(state_root)[0]`, so its directory IS the state root and is
    passed on as one; a bare --file's directory is not trusted to be one (_file_lock).
    """
    with _file_lock(file_path + ".lock", _ISSUES_LOCK,
                    None if bare_file else os.path.dirname(os.path.abspath(file_path))):
        yield


_EPIC_NODE_LOCK = {"depth": 0, "fh": None, "path": None}


def epic_lock_path(state_root: str, epic_key: str) -> str:
    """One epic's lock file: `{state_root}/epic-{nnn}.lock`.

    OUTSIDE the epic's directory, deliberately. move-epic / archive-epic `git mv` that whole
    directory between status folders. A lock file inside it would travel with it: a waiter
    that had resolved the old path would then lock a file that is no longer there (and
    recreate the old directory to hold it) while later callers lock the moved file -- two
    holders of one lock. A name built from the state root and the epic key alone is the same
    before, during and after a move, and for every spelling of the key ('E001', '001', '1')
    and of the root (relative or absolute -- realpath)."""
    return os.path.join(os.path.realpath(state_root), epic_dirname(epic_key) + ".lock")


@contextlib.contextmanager
def epic_node_lock(state_root: str, epic_key: str):
    """Hold an exclusive lock over one epic's epic.yaml read-modify-write cycle.

    Same reasoning as calibration_lock/adr_register_lock/issues_lock: load -> decide -> save
    is not atomic. set-lock needs the lock for mutual exclusion (two sessions both reading
    "no live foreign lock" and both claiming), and every other epic.yaml writer needs it so a
    concurrent holder cannot overwrite its change with a stale copy -- promote's roll-up once
    restored a `_lock` that clear-lock, which took no lock, had just removed. `_atomic_dump`
    refuses an epic.yaml write made without it (`_require_epic_lock`). Each epic is its own
    contention domain, so the lock is per epic (epic_lock_path), not per state root.

    Callers resolve the epic, take this lock, then RESOLVE AGAIN inside it: move-epic holds
    it too, so a move that landed while a caller waited has moved the directory its first
    answer named. They resolve first as well, so an absent epic exits 3 with no lock file
    created.

    ONE EPIC AT A TIME. The re-entrancy counter is per lock family, not per epic, so a nested
    acquire of a SECOND epic's lock would skip its flock silently; it raises instead.
    Re-entry on the same epic (promote -> rollup_parent_estimate) nests on the one flock.

    LOCK ORDER, enforced: the epic lock is taken first, never under issues_lock or
    calibration_lock. promote holds epic -> issues and set-actual holds epic -> calibration;
    a FRESH epic lock taken inside either would invert that order and can deadlock against
    them, so it raises. A same-epic re-entry is not fresh -- promote's roll-up re-enters its
    epic under issues_lock -- and is allowed."""
    lock_path = epic_lock_path(state_root, epic_key)
    held = _EPIC_NODE_LOCK["path"]
    if held is not None and held != lock_path:
        raise RuntimeError(f"epic_node_lock: {lock_path} requested while {held} is held -- "
                           f"one epic lock at a time")
    if held is None and (_ISSUES_LOCK["depth"] or _CAL_LOCK["depth"]):
        under = "issues_lock" if _ISSUES_LOCK["depth"] else "calibration_lock"
        raise RuntimeError(f"epic_node_lock: lock order -- {lock_path} requested under {under}; "
                           f"the epic lock is taken first, never under issues_lock or "
                           f"calibration_lock")
    with _file_lock(lock_path, _EPIC_NODE_LOCK, state_root):
        _EPIC_NODE_LOCK["path"] = lock_path
        try:
            yield
        finally:
            if held is None:
                _EPIC_NODE_LOCK["path"] = None


def _require_epic_lock(path: str) -> None:
    """Refuse an epic.yaml write unless this process holds THAT epic's epic_node_lock.

    Called from `_atomic_dump`, which every node write reaches, so the rule is checked on
    every write pm-status.py makes rather than trusted to a list of verbs -- the list once
    left clear-lock, move-epic and the node verbs all writing epic.yaml unlocked. Files made
    outside this script (doctor's bootstrap-state heredoc, agent-written migrate-state
    output) are not covered; they only create epic files, so there is nothing to race. A
    RuntimeError, not a PMError: no input causes this, only a code path that skipped the
    lock."""
    if os.path.basename(path) != "epic.yaml":
        return
    epic_dir = os.path.dirname(os.path.abspath(path))
    state_root = os.path.dirname(os.path.dirname(epic_dir))
    want = os.path.join(os.path.realpath(state_root), os.path.basename(epic_dir) + ".lock")
    if _EPIC_NODE_LOCK["path"] != want:
        raise RuntimeError(f"{path} written without its epic_node_lock ({want}) -- "
                           f"every epic.yaml write must hold it")


def save_calibration(y, cal, state_root: str) -> None:
    """Always locked — this file is written from every set-actual."""
    with calibration_lock(state_root):
        _atomic_dump(y, cal, calibration_path(state_root))


def migrate_calibration(y, cal, state_root: str):
    """version 1 -> 2. Original preserved as .v1 and never read again."""
    if cal.get("version") == CALIBRATION_SCHEMA_VERSION:
        return cal
    p = calibration_path(state_root)
    backup = p + ".v1"
    if os.path.exists(p) and not os.path.exists(backup):
        import shutil
        shutil.copy2(p, backup)
    blended = cal.get("ratio")
    fresh = new_calibration(cal.get("granularity", "story"))
    # The old blended figure maps onto scope only. closure and fix start at
    # zero samples: the v1 file cannot separate them, and seeding from a
    # blended number would import exactly the bias the split removes.
    if isinstance(blended, (int, float)):
        from ruamel.yaml.comments import CommentedMap
        for c in CLASSIFICATIONS:
            entry = CommentedMap()
            entry["samples"] = [float(blended)]
            fresh["scope"][c] = CommentedMap((("man_hours", entry),))
    save_calibration(y, fresh, state_root)
    return fresh


def weighted_ratio(samples: list) -> float:
    """Exponential-decay weighted mean, oldest first (most recent weighs most)."""
    vals = [float(s) for s in samples if _is_number(s)]
    if not vals:
        return None
    n = len(vals)
    num = den = 0.0
    for i, v in enumerate(vals):
        w = DECAY ** (n - 1 - i)
        num += v * w
        den += w
    return num / den if den else None


# A calibration sample outside this range is not wrong by construction — it
# is a ratio (actual/estimate-ish, see derive_story_sample), and most real
# ratios sit near 1.0 — but one this far off is exactly the shape a story
# sample would have if orchestration-shaped overhead (a defect this rework
# separately isolates into its own `orchestration` component) leaked into
# it under the old rules. FLAG surfaces that suspicion for human review; it
# never drops or corrects the sample itself.
TOKENS_SANITY_RANGE = (0.5, 2.0)

# Stamped once, at the top level of the calibration file itself, the first
# time migrate_calibration_metrics finishes a real pass over it — including
# a pass that finds nothing to migrate. This is NOT a version bump: `version`
# stays CALIBRATION_SCHEMA_VERSION == 2. A timestamp recording that a reshape
# happened is data about the file, exactly like `orchestration`, `token_mix`,
# and `legacy` below — not a schema generation.
#
# This replaces an earlier, REJECTED design that inferred "already migrated"
# from the presence/absence of the old `cost`/`time_hours` keys. That
# inference has a silent blind spot: a non-Claude-runtime project never
# accumulates `cost` samples (cost is N/A there and skipped by calibration),
# so a file that also happens to have no `time_hours` samples — for any
# reason — would read as "already migrated" under that design and never have
# its old-definition `man_hours`/`fix` samples quarantined. No error, no log
# line, just silently wrong ratios applied to every future estimate — the
# exact failure this migration exists to prevent. A positive marker has no
# such blind spot: its absence always means "run it," regardless of which
# sample types the file happens to contain.
CALIBRATION_METRICS_MARKER = "metrics_migrated_at"
TOKEN_BASIS_MARKER = "token_basis_migrated_at"


def migrate_calibration_metrics(y, cal, state_root: str) -> list:
    """Reshape a pre-metrics-rework calibration file in place. Returns a
    change log (empty when there was nothing to migrate).

    Gated on CALIBRATION_METRICS_MARKER, a positive marker stamped at the end
    of every real pass through this function — even a no-op one. A brand-new
    project has nothing to migrate on its first write, but still gets
    stamped right there, before that same write appends its first (entirely
    legitimate) sample: this is what stops a LATER real man_hours or fix
    sample from ever being revisited and wrongly quarantined (see
    test_man_hours_written_after_the_one_time_cutover_is_never_revisited).

    Once past the gate, `man_hours` and `fix` quarantine UNCONDITIONALLY —
    no corroborating cost/time_hours marker is required in the same bucket
    or file (see test_man_hours_quarantined_even_without_cost_or_time_hours_markers,
    the case that falsified an earlier key-presence-based design). `version`
    stays 2 throughout: compatibility is by shape-tolerant reads, never a
    version gate.
    """
    if cal.get(CALIBRATION_METRICS_MARKER):
        return []

    log = []
    p = calibration_path(state_root)
    backup = p + ".pre-metrics"
    if os.path.exists(p) and not os.path.exists(backup):
        import shutil
        shutil.copy2(p, backup)
        log.append(f"backup {os.path.basename(backup)}")

    def _reshape(component: str):
        buckets = cal.get(component) or {}
        for bucket, metrics in list(buckets.items()):
            if not hasattr(metrics, "items"):
                continue
            if "cost" in metrics:
                del metrics["cost"]
                log.append(f"DROP {component}.{bucket}.cost (derived from tokens x rates "
                           f"since Task 10 — never independently calibrated again)")
            if "time_hours" in metrics:
                metrics["elapsed_hours"] = metrics.pop("time_hours")
                log.append(f"RENAME {component}.{bucket}.time_hours -> elapsed_hours")
            if "man_hours" in metrics:
                from ruamel.yaml.comments import CommentedMap
                dest = (cal.setdefault("legacy", CommentedMap())
                           .setdefault(component, CommentedMap())
                           .setdefault(bucket, CommentedMap()))
                dest["man_hours"] = metrics.pop("man_hours")
                log.append(f"QUARANTINE {component}.{bucket}.man_hours (definition changed: "
                           f"human attention -> counterfactual developer effort — old "
                           f"samples are incomparable, preserved under legacy.{component}.{bucket})")
            samples = list((metrics.get("tokens_k") or {}).get("samples") or [])
            if samples:
                r = weighted_ratio(samples)
                if r is not None and not (TOKENS_SANITY_RANGE[0] <= r <= TOKENS_SANITY_RANGE[1]):
                    log.append(
                        f"FLAG {component}.{bucket}.tokens_k ratio={r:.2f} outside "
                        f"{TOKENS_SANITY_RANGE} — carried forward as-is, but review "
                        f"before trusting (possible orchestration overhead swept "
                        f"into story samples under the old rules)")

    for component in ("scope", "closure"):
        _reshape(component)

    fix = cal.get("fix") or {}
    fix_had_content = any(bool(v) for v in fix.values())
    if fix_had_content:
        from ruamel.yaml.comments import CommentedMap
        cal.setdefault("legacy", CommentedMap())["fix"] = fix
        cal["fix"] = CommentedMap((c, CommentedMap()) for c in CLASSIFICATIONS)
        log.append("QUARANTINE fix (wholesale — every cohort is measured in "
                   "mean_man_hours, the same definition change as scope/closure "
                   "man_hours; fix has no per-metric split to act on selectively, "
                   "preserved under legacy.fix)")

    # token_mix seeding stays tied to "did this pass actually find and move
    # legacy content" (log non-empty), NOT to the marker gate above: seeding
    # it unconditionally on every first-ever pass (including a no-op one on
    # a brand-new project) would recreate the exact conflict Task 9 hit and
    # routed around for new_calibration — see
    # test_record_skips_token_mix_when_actual_lacks_a_total, which asserts
    # token_mix stays ABSENT on a fresh project's first write when there is
    # nothing to observe yet.
    if log and "token_mix" not in cal:
        from ruamel.yaml.comments import CommentedMap
        cal["token_mix"] = CommentedMap((("samples", []),))
        log.append("SEED token_mix (empty — new component, nothing to migrate from)")

    cal[CALIBRATION_METRICS_MARKER] = _now_iso()
    return log


def migrate_calibration_token_basis(y, cal, state_root: str) -> list:
    """Drop scope tokens_k samples measured on the pre-fresh basis. Once, in place.

    Those samples are `cache_inclusive_actual / fresh_scale_band`, so they carry a
    basis error of roughly three orders of magnitude (see FRESH_TOKEN_CLASSES).
    They cannot be repaired here: a stored sample is a bare rounded ratio, with no
    raw counts to recompute from. Purging is the only honest option, and it is
    enough -- the nodes still hold their per-class actuals, so the buckets refill
    correctly on the next closes, now on the right basis.

    What deliberately SURVIVES:

    - `token_mix` samples. They are per-class FRACTIONS of a total, so they never
      depended on which classes the scope basis counted. They are also what now
      projects cache_read at estimate time, and they are the only measured record
      of how extreme the real split is -- discarding them would throw away the
      evidence that motivated this change.
    - every non-tokens_k component. man_hours, hitl_hours and elapsed_hours were
      never measured in tokens and are untouched by the basis error.

    `version` stays 2. Compatibility here is by shape-tolerant reads and a
    positive marker, never a version gate.
    """
    if cal.get(TOKEN_BASIS_MARKER):
        return []

    log = []
    p = calibration_path(state_root)
    backup = p + ".pre-token-basis"
    if os.path.exists(p) and not os.path.exists(backup):
        import shutil
        shutil.copy2(p, backup)
        log.append(f"backup {os.path.basename(backup)}")

    for bucket, metrics in list((cal.get("scope") or {}).items()):
        if not hasattr(metrics, "items"):
            continue
        entry = metrics.get("tokens_k")
        if not hasattr(entry, "get"):
            continue
        n = len(entry.get("samples") or [])
        if n:
            entry["samples"] = []
            log.append(f"PURGE scope.{bucket}.tokens_k ({n} sample(s) measured against a "
                       f"cache-inclusive actual over a fresh-token band — unrecoverable, "
                       f"the stored form is a bare ratio; the bucket refills on the next closes)")

    cal[TOKEN_BASIS_MARKER] = _now_iso()
    return log


def _component_samples(cal, component: str, bucket: str, metric: str) -> list:
    node = ((cal.get(component) or {}).get(bucket) or {}).get(metric) or {}
    return list(node.get("samples") or [])


def active_scope_ratio(cal, classification: str, metric: str):
    if metric == "tokens_k" and not (cal or {}).get(TOKEN_BASIS_MARKER):
        # Pre-basis file: any tokens_k scope samples here were measured as a
        # cache-inclusive actual over a fresh-token band and are wrong by orders
        # of magnitude (see FRESH_TOKEN_CLASSES). The purge runs on the next
        # WRITE, but read-only callers -- estimate-story, estimate-rollup,
        # calibration show -- must not migrate, and must not apply them either.
        # Cold start is the correct answer until a write cleans the file.
        return None
    s = _component_samples(cal, "scope", classification, metric)
    return weighted_ratio(s) if len(s) >= MIN_SAMPLES else None


def active_closure_ratio(cal, level: str, metric: str):
    """Learned closure overhead, with zero samples excluded.

    A zero residual is a skip, not a sample of 0.0 -- `derive_closure_sample`
    refuses to create one and says why at length. That guard is write-side
    only, so it cannot help a file that already contains a zero: written by a
    version predating the guard, or by any path not yet identified (the
    2026-08-25 production report observed one whose origin no code path in
    2.4.7 explains). Filtering here repairs every such file on the next read,
    with no migration to run and no schema change.

    Excluded from the average AND from the count: three zeros plus one real
    sample is one sample, not four, and must stay inactive.
    """
    s = [v for v in _component_samples(cal, "closure", level, metric)
         if _is_number(v) and abs(float(v)) > 1e-9]
    return weighted_ratio(s) if len(s) >= MIN_SAMPLES else None


def active_orchestration_fraction(cal, level: str, metric: str):
    """Learned orchestration overhead as a FRACTION of the children's total.

    Every other component here (scope, closure) learns a RATIO: actual over
    an estimate, correcting a number that already exists. Orchestration has
    no such number to correct — the band ships `null` (spec §6.4) because
    every measurement available at design time was contaminated by an
    operational defect (repeated cache-eviction on blocking waits), and
    sizing a prior on contaminated data would commit that bug to every future
    estimate. So there is nothing to measure a ratio against, and a
    ratio-based component could never bootstrap from its first sample.

    Instead the sample IS the band: orchestration_actual / sum(children
    actual), directly observable from the first closed sprint or epic. A
    future maintainer tempted to "fix" this into a ratio for consistency with
    closure would remove the one thing that lets it start learning at all.

    None until MIN_SAMPLES, same decay as every other component.
    """
    samples = _component_samples(cal, "orchestration", level, metric)
    return weighted_ratio(samples) if len(samples) >= MIN_SAMPLES else None


def active_fix_factor(cal, classification: str):
    """Needs BOTH cohorts at threshold — one cohort alone cannot form a ratio."""
    entry = (cal.get("fix") or {}).get(classification) or {}
    clean, rework = entry.get("clean") or {}, entry.get("reworked") or {}
    if int(clean.get("samples", 0)) < MIN_SAMPLES or int(rework.get("samples", 0)) < MIN_SAMPLES:
        return None
    cm, rm = clean.get("mean_man_hours"), rework.get("mean_man_hours")
    if not _is_number(cm) or not _is_number(rm) or float(cm) == 0:
        return None
    return float(rm) / float(cm)


def _num_or_none(v):
    """Parse a metric value, tolerating a leading '$' on cost. None if not numeric.

    Normalizing before the numeric guard (rather than after) matters: a
    check-then-lstrip order lets a '$'-prefixed cost fail _is_number and get
    skipped before the lstrip ever runs, silently starving the cost
    component of samples. This is the single normalization both the guard
    and the parse share, so they can't disagree.
    """
    if v is None or _is_na(v):
        return None
    s = str(v).strip().lstrip("$")
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def _applied_scope_ratio(est, metric):
    """The scope ratio that was applied to `metric` when this estimate was written.

    `estimate-story` records one ratio PER METRIC (`scope_ratios`), because the
    five metrics calibrate independently. A single scalar `scope_ratio` is the
    older/manual form (`set-estimate --scope-ratio`) and is accepted as a
    fallback for every metric. Missing entirely -> 1.0.
    """
    m = est.get("scope_ratios")
    if hasattr(m, "get"):
        v = _num_or_none(m.get(metric))
        if v is not None and v > 0:
            return v
    v = _num_or_none(est.get("scope_ratio"))
    return v if v is not None and v > 0 else 1.0


def _actual_metric(actual: dict, metric: str):
    """A metric's numeric actual. tokens_k is a mapping now — the total is what
    is banded and calibrated; the class split prices cost and nothing else.
    """
    v = (actual or {}).get(metric)
    if metric == "tokens_k" and hasattr(v, "get"):
        v = v.get("total")
    return _num_or_none(v)


def _estimate_metric(est: dict, metric: str):
    """A metric's numeric value from an ESTIMATE block. The single-value
    (story) form of `tokens_k` is a MAPPING (`tokens_block`'s `total` + the
    four per-class counts, since Tasks 6/7) — the same shape `_actual_metric`
    unwraps above, mirrored here for the estimate side.

    EVERY reader of an estimate's tokens_k must go through this, never
    `_num_or_none(est.get(metric))` directly. That direct form is exactly what
    silently zeroed two independent things before Task 10 found and fixed the
    first: `_child_estimate_value` (a sprint/epic roll-up would see zero
    children with a tokens_k estimate, `estimate-rollup` would just never emit
    `tokens_k_min`/`tokens_k_max`) and `derive_story_sample` (a story's
    tokens_k scope ratio never accumulated a sample — cold-start forever,
    silently, for the metric the whole cost derivation now hangs off). Both
    call sites now route through here so a fourth instance can't reintroduce
    the same blind spot by hand-duplicating the unwrap.
    """
    v = (est or {}).get(metric)
    if metric == "tokens_k" and hasattr(v, "get"):
        v = v.get("total")
    return _num_or_none(v)


# Node fields that are numeric or boolean regardless of how they arrive. `set-field`
# takes --value as text, so without this a numeric field lands on disk as a quoted
# string and every later reader has to guess. That is not hypothetical: writing
# fix_iterations through set-field stored '0', and the calibration path then depended
# on that string being int()-parseable. '0' happened to work; '0.0' raised ValueError
# and lost the sample entirely, and an unsubstituted '{fix_iterations}' placeholder --
# or any other non-numeric text -- silently became provenance=backout on a story that
# needed no rework at all.
NUMERIC_NODE_FIELDS = {
    "completion_evidence.fix_iterations",
    "completion_evidence.files_changed",
}
BOOL_NODE_FIELDS = {"completion_evidence.tests_passing"}

# Fields set-field must refuse outright: each is derived from other recorded data
# rather than asserted by an agent. completion_evidence.tests_passing used to be a
# free-form boolean an agent wrote about its own work -- not falsifiable, and not
# even checked against anything it ran. A story once shipped ten green gates and
# tests_passing: true having broken a suite it never ran; the break surfaced two
# stories later by accident. add-test-run records the command and exit code instead,
# and derives the boolean from that recorded set.
DERIVED_NODE_FIELDS = {
    "completion_evidence.tests_passing":
        "derived from completion_evidence.test_runs — record what you ran with "
        "`add-test-run --command CMD --exit-code N` instead of asserting the result",
    "resolves":
        "written by `promote-issue`, which also schedules the items it names -- a hand "
        "write would link a story the backlog does not know about",
    "status":
        "status changes go through `set-status`, which records the transition event and "
        "runs the done hook that resolves a story's backlog items",
}


def _iter_count(v):
    """fix_iterations as a non-negative int, or None if it is not one.

    Tolerant on the way in because historical nodes hold strings, and total: an
    unparseable value returns None rather than raising. `int(v)` alone raised
    ValueError on '0.0' -- inside `derive_story_sample` that aborted the whole
    sample, so a story with zero rework contributed nothing instead of the exact
    scope reading it should have.
    """
    if isinstance(v, bool) or v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f != int(f) or f < 0:
        return None
    return int(f)


def _exit_code_or_fail(v) -> int:
    """An exit code that will not parse is a failure, never a pass.

    test_runs is hand-editable YAML, and `_iter_count` already exists here
    because historical nodes hold strings. Same tolerance — but the fallback is
    asymmetric on purpose: an unreadable exit code must never derive
    `tests_passing: true`.
    """
    try:
        return int(v)
    except (TypeError, ValueError):
        return 1


def derive_story_sample(node, blocked_hours: float = 0.0):
    """Compute a story's scope samples and its fix cohort. None when not derivable.

    When `blocked_hours > 0`, `elapsed_hours` is deliberately absent from the
    returned sample's `scope_ratios`: wall-clock during blocked time includes
    human wait, and folding that into calibration would poison the scope ratio
    for future stories. Other metrics are unaffected -- `man_hours`,
    `hitl_hours` and `tokens_k` are assessed or counted, not measured against
    a wall-clock, so blocked time does not poison them. Design:
    docs/superpowers/specs/2026-09-25-story-lifecycle-blocked-design.md §5.

    THE SAMPLE MUST BE MEASURED AGAINST THE BASE BAND, NOT AGAINST THE LAST
    ESTIMATE. The estimate is `band_mid x scope_ratio_applied x fix_factor`, so a
    raw `actual / estimate` (or `actual x fix / estimate`) measures error against
    an estimate that already contains the previous ratio. Feeding that back as
    the next ratio makes the loop converge to sqrt(truth / band_mid) — a
    permanent underestimate no volume of data closes — and means a perfect
    estimate never produces a neutral sample. Dividing the applied ratio back
    out fixes both:

      exact   (fix_iterations == 0, the actual is pure scope):
          sample = actual x scope_ratio_applied x fix_factor / estimate
                 = actual / band_mid
      backout (rework present or unknown — the actual mixes scope and rework):
          scope portion is actual / fix_factor, so the fix factor cancels:
          sample = actual x scope_ratio_applied / estimate
                 = actual / (band_mid x fix_factor)
      legacy  (estimate predates the recorded factors): both default to 1.0,
          sample = actual / estimate, labelled `legacy` so an audit can tell
          the imprecision apart.
    """
    if not node:
        return None
    est, act = node.get("estimate") or {}, node.get("actual") or {}
    if not est or not act:
        return None

    iters = _iter_count((node.get("completion_evidence") or {}).get("fix_iterations"))
    has_factors = _is_number(est.get("fix_factor"))
    fix_factor = float(est["fix_factor"]) if has_factors else 1.0

    if not has_factors:
        provenance = "legacy"
    elif iters == 0:
        provenance = "exact"
    else:
        provenance = "backout"

    ratios = {}
    for metric in CALIBRATED_METRIC_FIELDS:
        if metric == "elapsed_hours" and blocked_hours and blocked_hours > 0:
            continue     # excluded per §5: wall-clock includes human wait time
        e_num, a_num = _estimate_metric(est, metric), _actual_metric(act, metric)
        if metric == "tokens_k":
            # Measure SCOPE against the fresh classes only -- on BOTH sides.
            #
            # The actual side is the defect being fixed: a cache-inclusive actual
            # over a fresh-scale band, ~1000x apart (see FRESH_TOKEN_CLASSES).
            # The estimate side matters just as much and is easy to miss: the
            # cancellation that reduces this expression to `actual / band_mid`
            # only holds while the denominator IS `band_mid x applied x fix`.
            # Since estimate-story now adds a projected cache_read on top of the
            # banded fresh total, `tokens_k.total` is no longer that quantity, and
            # dividing by it would reintroduce a basis error in the other
            # direction. The estimate's fresh sum is the banded quantity.
            a_tk, e_tk = (act or {}).get("tokens_k"), (est or {}).get("tokens_k")
            a_num = fresh_tokens(a_tk) if hasattr(a_tk, "get") else None
            if hasattr(e_tk, "get"):
                e_fresh = fresh_tokens(e_tk)
                e_num = e_fresh if e_fresh > 0 else e_num
            if a_num is not None and a_num <= 0:
                a_num = None      # no fresh tokens recorded -> no scope signal
        if e_num is None or a_num is None:
            continue          # missing, N/A, or non-numeric — never coerced to zero
        if e_num == 0:
            continue
        applied = _applied_scope_ratio(est, metric) if has_factors else 1.0
        if provenance == "backout":
            # actual/fix_factor is the scope portion; the fix_factor cancels.
            ratios[metric] = a_num * applied / e_num
        else:
            ratios[metric] = a_num * applied * fix_factor / e_num

    if not ratios:
        return None
    return {
        "classification": str(node.get("classification", "standard")),
        "provenance": provenance,
        "fix_iterations": iters,
        "scope_ratios": ratios,
        "actual_man_hours": float(act["man_hours"]) if _is_number(act.get("man_hours")) else None,
    }


def _bump_cohort(entry, cohort: str, man_hours):
    """Running mean over a cohort, so a full sample history is not needed."""
    from ruamel.yaml.comments import CommentedMap
    c = entry.get(cohort)
    if c is None:
        c = CommentedMap()
        c["mean_man_hours"] = 0.0
        c["samples"] = 0
        entry[cohort] = c
    if man_hours is None:
        return
    n = int(c.get("samples", 0))
    mean = float(c.get("mean_man_hours", 0.0))
    c["mean_man_hours"] = round((mean * n + man_hours) / (n + 1), 4)
    c["samples"] = n + 1


CALIBRATION_MARKER = "calibration_sampled_at"
# The orchestration sample is a SEPARATE fact from the actual/closure sample,
# and a sprint or epic node can carry both — one marker cannot gate both
# without one silently suppressing the other (a closed sprint's closure
# sample would forever block its later orchestration sample, or vice versa).
# So orchestration gets its own marker, using the exact same guard mechanism
# below (a `marker` parameter), rather than a second copy of the mechanism.
ORCHESTRATION_MARKER = "orchestration_sampled_at"


def _already_sampled(node, marker=CALIBRATION_MARKER):
    """The replay guard: a node that already emitted its sample carries a marker."""
    v = (node or {}).get(marker)
    return str(v) if v else None


def _mark_sampled(node, node_path, y=None, marker=CALIBRATION_MARKER) -> None:
    """Stamp the node so a second set-actual on it cannot double-count.

    Idempotency lives on the node, not in the caller: `--no-calibrate` only
    helps someone who remembers to pass it, and a duplicated sample is
    invisible afterwards.
    """
    if node is None or not node_path:
        return
    node[marker] = _now_iso()
    _atomic_dump(y or _yaml(), node, node_path)


def record_story_sample(state_root: str, node, node_path: str | None = None, y=None) -> str:
    """Derive a story's calibration sample and append it to the shared file.

    A write path, unlike load_calibration: migrates a stale schema version
    before appending, so a v1 file is never mistaken for v2 and corrupted by
    samples landing in a structure that doesn't exist there yet. The whole
    load->mutate->save runs under one exclusive lock so parallel samplers
    cannot clobber each other's appends.
    """
    prior = _already_sampled(node)
    if prior:
        return f"sample already recorded at {prior} — skipped (replay)"
    story_key = str(node.get("key", "") or "").strip()
    blocked_hours = _total_blocked_hours(state_root, story_key)
    sample = derive_story_sample(node, blocked_hours=blocked_hours)
    if sample is None:
        return "no sample (missing estimate or actual)"
    if blocked_hours > 0:
        # Inline duration lets an operator eyeball whether the exclusion was
        # warranted -- a 5-minute block resolves quickly; a 6-day block obviously
        # doesn't -- without cross-referencing the event log. Per §5 of the design.
        sys.stderr.write(
            f"pm-status.py: WARN blocked story {story_key} — elapsed_hours "
            f"sample deferred (event log shows {blocked_hours:.1f}h in blocked); "
            f"man_hours, hitl_hours, tokens_k still recorded\n")
    from ruamel.yaml.comments import CommentedMap
    with calibration_lock(state_root):
        y_cal, cal = load_calibration(state_root)
        if cal.get("version") != CALIBRATION_SCHEMA_VERSION:
            cal = migrate_calibration(y_cal, cal, state_root)
        for line in migrate_calibration_metrics(y_cal, cal, state_root):
            sys.stderr.write(f"pm-status.py: calibration migration: {line}\n")
        for line in migrate_calibration_token_basis(y_cal, cal, state_root):
            sys.stderr.write(f"pm-status.py: calibration migration: {line}\n")
        cls = sample["classification"]
        act_model = (node.get("actual") or {}).get("model")

        bucket = cal["scope"].setdefault(cls, CommentedMap())
        for metric, ratio in sample["scope_ratios"].items():
            entry = bucket.setdefault(metric, CommentedMap())
            entry.setdefault("samples", [])
            entry["samples"].append(round(ratio, 4))
            if act_model:
                seen = entry.setdefault("models_seen", [])
                if act_model not in seen:
                    seen.append(act_model)

        # The observed per-class split, as a fraction of the actual's total —
        # feeds observed_mix() once 3 samples accrue, superseding
        # COLD_START_TOKEN_MIX. Independent of the scope-ratio samples above:
        # this is about how a token total divides across classes, not about
        # how big the total itself is.
        tk = (node.get("actual") or {}).get("tokens_k")
        if hasattr(tk, "get"):
            total = _num_or_none(tk.get("total"))
            if total and total > 0:
                mix_bucket = cal.setdefault("token_mix", CommentedMap())
                mix_bucket.setdefault("samples", [])
                mix_entry = {c: round((_num_or_none(tk.get(c)) or 0.0) / total, 4)
                             for c in TOKEN_CLASSES}
                if act_model:
                    mix_entry["model"] = act_model
                mix_bucket["samples"].append(mix_entry)

        fix_entry = cal["fix"].setdefault(cls, CommentedMap())
        iters = sample["fix_iterations"]
        if iters is not None:
            _bump_cohort(fix_entry, "clean" if iters == 0 else "reworked",
                         sample["actual_man_hours"])

        save_calibration(y_cal, cal, state_root)
    _mark_sampled(node, node_path, y)
    return (f"scope+{len(sample['scope_ratios'])} metrics, "
            f"provenance={sample['provenance']}, class={cls}")


def _mid(est, low_key: str, high_key: str):
    """Midpoint of a range-form estimate. None if either bound is missing/non-numeric."""
    lo, hi = _num_or_none(est.get(low_key)), _num_or_none(est.get(high_key))
    if lo is None or hi is None:
        return None
    return (lo + hi) / 2.0


CLOSURE_RANGE_KEYS = {
    "man_hours":     ("man_hours_low", "man_hours_high"),
    "hitl_hours":    ("hitl_hours_low", "hitl_hours_high"),
    "elapsed_hours": ("elapsed_hours_low", "elapsed_hours_high"),
    "tokens_k":      ("tokens_k_min", "tokens_k_max"),
}
# No "cost" row: cost is derived from the rolled-up tokens_k range (see
# cmd_estimate_rollup) rather than banded and calibrated on its own — the
# story-level equivalent of this was already true (BASE_BANDS has no cost
# row either). Keeping a separate closure-cost band was the last place the
# old defect survived: a cost figure with no arithmetic tie to the token
# figure it should track, drifting apart as the two calibrated independently.


# Wall-clock metrics legitimately go NEGATIVE as a closure residual: if a closure
# node's children ever overlap in wall-clock time, the parent's wall-clock can be
# below the sum of its children's by design (today's step files run children
# strictly in order, so this does not arise in practice; the check stays
# defensive). That is topology, not a miscount, and must not be reported as one.
# Man-hours, tokens and cost are additive regardless of concurrency, so a
# negative residual there really is a miscount.
WALL_CLOCK_METRICS = ("elapsed_hours",)


def _closure_nodes(state_root: str, level: str, epic_key: str, sprint_key=None):
    """(parent path, child paths) for a closure sample at `level`."""
    if level == "sprint":
        return (sprint_file(state_root, epic_key, sprint_key),
                list_story_files(state_root, epic_key, sprint_key))
    return (epic_file(state_root, epic_key),
            [sprint_file(state_root, epic_key, _sprint_key_from_dir(d))
             for d in list_sprint_dirs(state_root, epic_key)])


def _skip_summary(skipped: dict) -> str:
    return "; ".join(f"{m}: {r}" for m, r in skipped.items()) or "no metrics available"


def derive_closure_sample(state_root: str, level: str, epic_key: str, sprint_key=None):
    """Closure overhead = parent actual - sum(children actuals). Returns (sample, reason).

    THE RATIO'S DENOMINATOR MUST BE THE QUANTITY THE RATIO IS APPLIED TO.
    `estimate-rollup` applies the learned ratio to the CLOSURE BAND alone
    (`total x (1 + ratio x closure_band + fraction x ORCH_SPREAD)`), so the
    residual has to be divided by the ESTIMATED CLOSURE OVERHEAD ALONE, never
    by the whole parent estimate and never by closure-plus-orchestration.
    Dividing by the whole parent made learn and apply different quantities,
    and a perfectly consistent history moved the estimate AWAY from its own
    observed truth.

    THE ORCHESTRATION BAND IS NOT PART OF THIS DENOMINATOR. Since the
    orchestration term joined the roll-up, `pmid - sum(child estimates)` is
    the closure band PLUS the orchestration band, while the residual it
    divides (`parent actual - sum(children actual)`) is closure-only —
    orchestration lives in its own `orchestration` block, outside `actual`.
    Leaving the orchestration band in the denominator understated every
    closure sample by exactly the factor the two bands differ by (with an
    active fraction of 0.5 and children summing to 20, a true overhead of 5
    recorded as 0.3704 instead of 1.4286 — 3.9x low, and worse as the
    fraction grows). So the applied fraction (`estimate.orchestration_ratios`,
    the same divide-it-back-out record `closure_ratios` and `scope_ratios`
    are) is subtracted back off at its band MIDPOINT (`ORCH_MID`), leaving
    exactly `est_total x closure_ratio_applied x mid(COLD_START_CLOSURE_BAND)`
    — the quantity the closure ratio is applied to and nothing else.

    And, as with the story scope ratio, the estimated overhead already contains
    the ratio that was applied when the parent estimate was written, so that
    ratio is divided back out (`closure_ratios` on the estimate block, 1.0 when
    absent). Without it the loop settles on a geometric mean instead of the
    truth. Concretely: children estimated 40, closure overhead truly 8 every
    time. Estimated overhead cold-start = 47 - 40 = 7, sample 8/7 = 1.143, and
    `40 x (1 + 1.143 x 0.175) = 48.0` — the observed total, and stable on every
    later generation because the applied ratio cancels.

    Guards, each skipping just THAT METRIC with a reason rather than aborting
    the whole sample: any child missing that metric's actual (a partial sum
    understates overhead and biases the ratio low, permanently); a negative
    residual (a miscount — except for wall-clock, where parallel execution makes
    it expected); a ZERO residual (see below); an estimated overhead <= 0
    (nothing to measure against); and N/A tokens, which skips just that metric
    while man-hours still record under non-Claude runtimes where tokens are
    legitimately absent.

    A ZERO RESIDUAL IS A SKIP, NOT A SAMPLE OF 0.0 — and "zero" means within a
    relative tolerance, on both signs, not exactly 0.0 in binary. A parent actual
    equal to the sum of its children means the closure phases' own spend
    (adversarial analysis, retrospective, QA generation — real, measurable
    work) was attributed to nothing. Recording that as a legitimate 0.0
    sample is worse than recording nothing: 0.0 is not None, so after three
    such sprints `active_closure_ratio` returns 0.0, `cmd_estimate_rollup`
    accepts it, and the closure band contributes nothing to any future
    estimate — permanently, with no marker saying why. The step files now
    instruct the parent actual as "sum of children PLUS this level's own
    closure-phase spend" precisely so this does not arise; when it does, it
    is a capture defect and must be reported as one, not learned from. Both
    signs route to that one reason because a bare sum over decimal inputs lands
    on either side of zero depending on the values (0.3 + 0.6 vs 0.9 leaves
    +1.11e-16; 1.1 + 2.2 vs 3.3 leaves -4.44e-16), and calling the second a
    "miscount" would tell the reader something false.

    Iterates CALIBRATED_METRIC_FIELDS, not CLOSURE_RANGE_KEYS or the full
    METRIC_FIELDS: `cost` never produces a closure sample (Task 10) — it is
    derived from the rolled-up tokens_k range at estimate-rollup time, so a
    residual measured against its own band would have nothing left to divide
    against and nothing calibrating it downstream would ever read the sample.
    """
    ppath, child_paths = _closure_nodes(state_root, level, epic_key, sprint_key)
    if ppath is None:
        return None, f"{level} node not found"
    _, pnode = load_node(ppath)
    pact = (pnode or {}).get("actual") or {}
    pest = (pnode or {}).get("estimate") or {}
    if not pact:
        return None, f"{level} has no actual yet"

    children = []
    for cp in child_paths:
        if cp is None:
            children.append(None)
            continue
        _, cn = load_node(cp)
        children.append(cn)

    applied_ratios = pest.get("closure_ratios")
    applied_orch = pest.get("orchestration_ratios")
    closure, ratios, skipped = {}, {}, {}
    for metric in CALIBRATED_METRIC_FIELDS:
        total = 0.0
        complete = True
        for cn in children:
            cv = _actual_metric((cn or {}).get("actual"), metric) if cn is not None else None
            if cv is None:
                complete = False   # missing, N/A, or non-numeric child actual
                break
            total += cv
        if not complete:
            skipped[metric] = "a child is missing this metric's actual"
            continue
        pv = _actual_metric(pact, metric)
        if pv is None:
            skipped[metric] = f"{level} actual is missing or N/A for this metric"
            continue
        residual = pv - total
        # Near-zero is checked FIRST, and on BOTH signs. `residual` is unrounded
        # float arithmetic over decimal inputs, so `== 0` only catches a residual
        # that happens to land exactly on zero in binary. Children of 0.3 and 0.6
        # against a parent written as the bare sum 0.9 leave +1.11e-16, which
        # sails past `== 0` and records three 0.0 samples — C2 reopened, on
        # ordinary tenths-of-an-hour input. The mirror (1.1 + 2.2 vs 3.3) leaves
        # -4.44e-16 and would otherwise be reported as a miscount that did not
        # happen. One relative tolerance, both signs, one reason. The tolerance is
        # relative to the parent so it stays meaningful at any magnitude, and
        # floored at 1.0 so it never collapses to nothing for small values; at
        # 1e-9 it is many orders below the smallest real closure overhead and many
        # above double-precision summation noise.
        if abs(residual) <= 1e-9 * max(1.0, abs(pv)):
            skipped[metric] = (
                f"zero residual (parent {pv} equals children sum {total} to within float "
                f"tolerance) — this {level}'s own closure-phase spend was attributed to "
                f"nothing; a 0.0 sample would train the closure component to zero "
                f"permanently. Re-capture the {level} actual as children + this level's "
                f"closure-phase spend (metrics-contract.md §6)")
            continue
        if residual < 0:
            if metric in WALL_CLOCK_METRICS:
                skipped[metric] = (f"negative wall-clock residual (parent {pv} below children "
                                   f"sum {total}) — expected under parallel execution, not a miscount")
            else:
                skipped[metric] = (f"negative residual (parent {pv} below children sum "
                                   f"{total}) — miscounted")
            continue
        closure[metric] = residual

        lo, hi = CLOSURE_RANGE_KEYS[metric]
        pmid = _mid(pest, lo, hi)
        if pmid is None:
            skipped[metric] = f"{level} has no estimate range for this metric"
            continue
        est_total, all_est = 0.0, True
        for cn in children:
            v = _child_estimate_value(cn, metric) if cn is not None else None
            if v is None:
                all_est = False
                break
            est_total += v
        if not all_est:
            skipped[metric] = "a child is missing this metric's estimate"
            continue
        # Back out the orchestration band before dividing: `pmid - est_total` is
        # closure band PLUS orchestration band, and `residual` is closure-only.
        orch_f = 0.0
        if hasattr(applied_orch, "get"):
            f = _num_or_none(applied_orch.get(metric))
            if f is not None and f > 0:
                orch_f = f
        expected = pmid - est_total - est_total * orch_f * ORCH_MID
        if expected <= 0:
            skipped[metric] = (f"estimated closure overhead is {round(expected, 4)} (<= 0) — "
                               f"nothing to measure the residual against")
            continue
        applied = 1.0
        if hasattr(applied_ratios, "get"):
            a = _num_or_none(applied_ratios.get(metric))
            if a is not None and a > 0:
                applied = a
        ratios[metric] = residual * applied / expected

    if not closure:
        return None, "no metric produced a closure residual — " + _skip_summary(skipped)
    return {"level": level, "closure_actual": closure, "ratios": ratios,
            "skipped": skipped}, "ok"


def record_closure_sample(state_root: str, level: str, epic_key: str, sprint_key=None) -> str:
    """Derive a sprint/epic's closure sample and append it to the shared file.

    A write path, unlike load_calibration: migrates a stale schema version
    before appending, so a v1 file is never mistaken for v2 and corrupted by
    samples landing in a structure that doesn't exist there yet.
    """
    ppath, _ = _closure_nodes(state_root, level, epic_key, sprint_key)
    y_node, pnode = load_node(ppath) if ppath else (None, None)
    prior = _already_sampled(pnode)
    if prior:
        return f"sample already recorded at {prior} — skipped (replay)"

    sample, reason = derive_closure_sample(state_root, level, epic_key, sprint_key)
    if sample is None:
        return f"no closure sample: {reason}"
    if not sample["ratios"]:
        return "no closure sample: " + _skip_summary(sample["skipped"])

    from ruamel.yaml.comments import CommentedMap
    with calibration_lock(state_root):
        y, cal = load_calibration(state_root)
        if cal.get("version") != CALIBRATION_SCHEMA_VERSION:
            cal = migrate_calibration(y, cal, state_root)
        for line in migrate_calibration_metrics(y, cal, state_root):
            sys.stderr.write(f"pm-status.py: calibration migration: {line}\n")
        for line in migrate_calibration_token_basis(y, cal, state_root):
            sys.stderr.write(f"pm-status.py: calibration migration: {line}\n")
        bucket = cal["closure"].setdefault(level, CommentedMap())
        for metric, ratio in sample["ratios"].items():
            entry = bucket.setdefault(metric, CommentedMap())
            entry.setdefault("samples", [])
            entry["samples"].append(round(ratio, 4))
        save_calibration(y, cal, state_root)
    _mark_sampled(pnode, ppath, y_node)
    note = f"closure {level} +{len(sample['ratios'])} metrics"
    if sample["skipped"]:
        note += f" (skipped — {_skip_summary(sample['skipped'])})"
    return note


def record_orchestration_sample(state_root: str, level: str, epic_key: str,
                                 sprint_key=None) -> str:
    """Append one closed sprint/epic's orchestration-vs-children fraction.

    THE FRACTION, NOT A RATIO. Every other component here (scope, closure)
    learns a ratio — actual over an ESTIMATE, correcting a number that
    already exists. Orchestration has nothing to correct: the band ships
    `null` by design, because every number available when this was built was
    contaminated by an operational defect (roughly thirty blocking waits each
    outlived the prompt cache and re-created a ~93k-token prefix), and sizing
    a prior on that would commit the bug to every future estimate. So there
    is no estimate to divide by, and a ratio-based component could never
    bootstrap — it would need the very thing it doesn't have. Instead the
    sample IS the band: orchestration_actual / sum(children actual), directly
    observable from the first closed sprint or epic. Do not "fix" this into a
    ratio for consistency with closure — that would remove the one thing
    that lets it start learning at all.

    THE DENOMINATOR MUST BE COMPLETE, per metric, the same guard
    derive_closure_sample applies to its residual: if any child that exists
    is missing that metric's actual, the sum silently understates the true
    total and the fraction is inflated — a wrong number that looks right, and
    permanently so once it feeds calibration. So a metric is sampled only
    when EVERY child carries a numeric actual for it; a partial sum is
    treated as no sample, not as a smaller one.

    `cost` is deliberately absent from CALIBRATED_METRIC_FIELDS: it is
    derived from tokens x rates, so its fraction is already implied by the
    tokens_k fraction and a second, independently-drifting copy would add
    nothing but disagreement.

    REPLAY-GUARDED, like every other record_*_sample here: a second
    `set-actual --block orchestration` on the same node (a retry, a
    corrected number, a replayed closure step) must not append a second
    sample and skew the learned fraction with nothing on disk to explain it.
    Gated on its own ORCHESTRATION_MARKER rather than the closure/story
    CALIBRATION_MARKER, because a sprint or epic node carries both an
    actual/closure sample and an orchestration sample — one marker would let
    whichever writes first silently suppress the other. `_closure_nodes`
    resolves the same parent path for both sprint and epic level, so this
    one guard covers both without a level-specific branch.
    """
    ppath, cpaths = _closure_nodes(state_root, level, epic_key, sprint_key)
    if ppath is None:
        return ""
    y_node, pnode = load_node(ppath)
    prior = _already_sampled(pnode, marker=ORCHESTRATION_MARKER)
    if prior:
        return f"sample already recorded at {prior} — skipped (replay)"
    orch = (pnode or {}).get("orchestration") or {}
    if not orch:
        return ""

    children = []
    for cp in cpaths:
        if cp is None:
            children.append(None)
            continue
        _, cn = load_node(cp)
        children.append(cn)

    from ruamel.yaml.comments import CommentedMap
    recorded, skipped = {}, {}
    for metric in CALIBRATED_METRIC_FIELDS:
        over = _actual_metric(orch, metric)
        if over is None:
            continue  # orchestration itself has no actual for this metric
        total, complete = 0.0, True
        for cn in children:
            cv = _actual_metric((cn or {}).get("actual"), metric) if cn is not None else None
            if cv is None:
                complete = False
                break
            total += cv
        if not complete:
            skipped[metric] = "a child is missing this metric's actual"
            continue
        if total <= 0:
            skipped[metric] = "children's total is zero or negative — nothing to divide by"
            continue
        recorded[metric] = round(over / total, 4)

    if not recorded:
        return "" if not skipped else "no orchestration sample: " + _skip_summary(skipped)

    with calibration_lock(state_root):
        y, cal = load_calibration(state_root)
        if cal.get("version") != CALIBRATION_SCHEMA_VERSION:
            cal = migrate_calibration(y, cal, state_root)
        for line in migrate_calibration_metrics(y, cal, state_root):
            sys.stderr.write(f"pm-status.py: calibration migration: {line}\n")
        for line in migrate_calibration_token_basis(y, cal, state_root):
            sys.stderr.write(f"pm-status.py: calibration migration: {line}\n")
        bucket = cal.setdefault("orchestration", CommentedMap()).setdefault(level, CommentedMap())
        for metric, frac in recorded.items():
            entry = bucket.setdefault(metric, CommentedMap())
            entry.setdefault("samples", [])
            entry["samples"].append(frac)
        save_calibration(y, cal, state_root)
    _mark_sampled(pnode, ppath, y_node, marker=ORCHESTRATION_MARKER)

    note = f"orchestration {level} +{len(recorded)} metrics"
    if skipped:
        note += f" (skipped — {_skip_summary(skipped)})"
    return note


def actual_event_times(state_root: str) -> dict:
    """{story key: ts of its latest `actual` event}, from state/events.jsonl.

    The one honest source for "when did this story close". `updated_at` is not:
    any field write overwrites it, so it dates the last edit rather than the
    closure. Used by `redrive_story_samples` to rebuild calibration samples in
    the chronological order the original appends had -- see the refusal there
    for why an incomplete answer is not usable.
    """
    idx: dict = {}
    p = events_path(state_root)
    if not os.path.isfile(p):
        return idx
    try:
        with open(p, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except ValueError:
                    continue  # a torn or hand-mangled line must not kill the rebuild
                if not isinstance(ev, dict):
                    continue
                if ev.get("event") != "actual" or ev.get("node") != "story":
                    continue
                k = ev.get("key")
                if not k:
                    continue
                k = _indexable_key(k)              # `k not in idx` raises on an unhashable k
                if k is None:
                    continue
                ts = str(ev.get("ts", ""))
                if k not in idx or ts >= idx[k]:
                    idx[k] = ts
    except OSError as e:
        raise PMError(2, f"could not read the event log at {p}: {e}") from e
    return idx


def redrive_story_samples(state_root: str) -> dict:
    """Rebuild `scope` and `fix` from the nodes on disk. Returns a report.

    Unlike the token-basis purge, this recovers rather than discards: a stored sample is
    a bare ratio with nothing behind it, but the NODES still hold every input
    `derive_story_sample` needs -- estimate, actual, and completion_evidence. So a batch
    of samples derived under a bug can simply be derived again, correctly, instead of
    being thrown away and waited for.

    Which is what this is for. `set-field` stored `fix_iterations` as text, and the
    provenance test depended on that text parsing as an int: a story that needed no rework
    was read as `backout`, its scope ratio divided by the 1.25 fix factor it never
    incurred, and the `clean` cohort never filled -- so the `fix` component could not
    activate at all. Every story closed under that behaviour is wrong in the same
    direction, and every one of them is repairable from disk.

    Only `scope` and `fix` are rebuilt. `closure`, `orchestration` and `token_mix` derive
    from different inputs and were never affected, so they are left exactly as they are.

    Samples are re-appended in CLOSURE order, taken from each story's `actual` event in
    state/events.jsonl -- not in the order the tree walk visits them. `weighted_ratio`
    weights the last entry most, so order is load-bearing, and directory order is not a
    neutral substitute for it. Raises PMError(2) without writing anything when that order
    cannot be established for every sampled story.
    """
    from ruamel.yaml.comments import CommentedMap
    report = {"stories": 0, "sampled": 0, "provenance": {}, "skipped": 0}
    with calibration_lock(state_root):
        # Pass 1 -- gather, mutating nothing. The refusal below has to be able to
        # leave the file and the backup untouched, so no write happens until the
        # ordering is known to be establishable.
        gathered = []
        for status in STATUS_DIRS:
            base = os.path.join(state_root, status)
            if not os.path.isdir(base):
                continue
            for ed in sorted(os.listdir(base)):
                if not ed.startswith("epic-"):
                    continue
                ekey = "E" + ed.split("-", 1)[1]
                for sd in sorted(list_sprint_dirs(state_root, ekey) or []):
                    skey = _sprint_key_from_dir(sd)
                    for sf in sorted(list_story_files(state_root, ekey, skey) or []):
                        report["stories"] += 1
                        try:
                            _, node = load_node(sf)
                        except Exception:                     # noqa: BLE001
                            report["skipped"] += 1
                            continue
                        sample = derive_story_sample(node)
                        if sample is None:
                            report["skipped"] += 1
                            continue
                        key = str(node.get("key") or
                                  os.path.splitext(os.path.basename(sf))[0])
                        gathered.append((key, sample))

        # Pass 2 -- restore chronological order, or refuse.
        #
        # `weighted_ratio` is an exponential-decay mean over samples oldest-first,
        # so the LAST entry in a list weighs most. The original samples were
        # appended one per `set-actual`, in closure order, which made that
        # weighting mean what it says. Rebuilding by walking the tree replaced it
        # with lexicographic key order -- and because STATUS_DIRS is
        # ("active", "planned", "archived"), archived epics land LAST and collect
        # the HIGHEST recency weight. Archived work is the oldest work, so on any
        # project with an archived epic the weighting was not merely scrambled, it
        # was cleanly inverted: a repair that changed no data re-priced every
        # unstarted story, silently, in a command that advertises itself as a
        # repair. Observed on a real project as a ~16% rise on `complex`.
        #
        # Refusing on an incomplete answer rather than falling back to directory
        # order is deliberate, and follows `adr-reserve`/`AdrHomeUnresolved`: a
        # confidently wrong result with a success code is worse than no result.
        # Directory order is not a neutral default -- it is anti-chronological by
        # construction here -- and `--no-events` means a log can exist and still
        # not cover every story, which looks orderable and is not.
        if gathered:
            times = actual_event_times(state_root)
            missing = sorted({k for k, _ in gathered if not times.get(k)})
            if missing:
                shown = ", ".join(missing[:5]) + ("..." if len(missing) > 5 else "")
                raise PMError(2,
                    f"redrive: cannot establish closure order for {len(missing)} of "
                    f"{len(gathered)} sampled stories -- no `actual` event in "
                    f"{events_path(state_root)} for: {shown}. Calibration ratios are "
                    f"recency-weighted, so rebuilding in directory order would invert "
                    f"the weighting rather than repair it (archived epics sort last "
                    f"and would weigh most). Nothing written; the calibration file is "
                    f"unchanged. This is expected on a project predating the event log, "
                    f"or one whose actuals were written with --no-events.")
            gathered.sort(key=lambda g: (times[g[0]], g[0]))

        # Pass 3 -- write.
        y, cal = load_calibration(state_root)
        backup = calibration_path(state_root) + ".pre-redrive"
        if os.path.exists(calibration_path(state_root)) and not os.path.exists(backup):
            import shutil
            shutil.copy2(calibration_path(state_root), backup)
            report["backup"] = os.path.basename(backup)

        cal["scope"] = CommentedMap()
        cal["fix"] = CommentedMap()

        for _key, sample in gathered:
            cls = sample["classification"]
            bucket = cal["scope"].setdefault(cls, CommentedMap())
            for metric, ratio in sample["scope_ratios"].items():
                entry = bucket.setdefault(metric, CommentedMap())
                entry.setdefault("samples", [])
                entry["samples"].append(round(ratio, 4))
            iters = sample["fix_iterations"]
            if iters is not None:
                _bump_cohort(cal["fix"].setdefault(cls, CommentedMap()),
                             "clean" if iters == 0 else "reworked",
                             sample["actual_man_hours"])
            report["sampled"] += 1
            pv = sample["provenance"]
            report["provenance"][pv] = report["provenance"].get(pv, 0) + 1
        save_calibration(y, cal, state_root)
    return report


def cmd_calibration(args) -> int:
    if getattr(args, "action", "show") == "redrive":
        # Through _run_core: redrive refuses with PMError(2) when it cannot establish
        # closure order, and main() has no PMError handler of its own -- without this
        # the refusal would surface as a traceback and exit 1 instead of the documented
        # exit 2 with its message.
        def _redrive() -> int:
            rep = redrive_story_samples(args.state_root)
            if rep.get("backup"):
                sys.stdout.write(f"backup {rep['backup']}\n")
            prov = " ".join(f"{k}={v}" for k, v in sorted(rep["provenance"].items()))
            sys.stdout.write(
                f"OK calibration redrive — stories seen {rep['stories']}, "
                f"samples rebuilt {rep['sampled']}, skipped {rep['skipped']}"
                + (f" [{prov}]" if prov else "") + "\n")
            sys.stdout.write("scope and fix rebuilt from the nodes in closure order (from "
                             "events.jsonl); closure, orchestration and token_mix untouched.\n")
            sys.stdout.write("Ratios are recency-weighted, so estimates for unstarted stories "
                             "may move even where no sample changed — re-run estimate-story to "
                             "see current numbers.\n")
            return 0
        return _run_core(_redrive)
    if getattr(args, "action", "show") == "migrate-metrics":
        with calibration_lock(args.state_root):
            y, cal = load_calibration(args.state_root)
            if cal.get("version") != CALIBRATION_SCHEMA_VERSION:
                cal = migrate_calibration(y, cal, args.state_root)
            log = migrate_calibration_metrics(y, cal, args.state_root)
            # Same explicit entry point, because an operator reaching for a migration
            # wants the file correct, not correct-except-for-one-component. Both are
            # separately marker-gated, so running this on an already-migrated file is
            # a no-op rather than a second purge.
            log = log + migrate_calibration_token_basis(y, cal, args.state_root)
            save_calibration(y, cal, args.state_root)
        for line in log:
            sys.stdout.write(line + "\n")
        sys.stdout.write(f"OK calibration migrate-metrics ({len(log)} changes)\n")
        return 0

    _, cal = load_calibration(args.state_root)
    exists = os.path.exists(calibration_path(args.state_root))

    mixed_buckets = []
    for c in CLASSIFICATIONS:
        for m in CALIBRATED_METRIC_FIELDS:
            entry = ((cal.get("scope") or {}).get(c) or {}).get(m) or {}
            seen = entry.get("models_seen") or []
            if len(seen) > 1:
                mixed_buckets.append(f"{c}/{m} ({', '.join(seen)})")
    if mixed_buckets:
        sys.stdout.write(
            "WARN: scope calibration contains mixed-model samples — ratios may be unreliable.\n"
            "Consider `calibration redrive` after settling on one model:\n"
        )
        for b in mixed_buckets:
            sys.stdout.write(f"  {b}\n")

    rows = []
    for c in CLASSIFICATIONS:
        for m in CALIBRATED_METRIC_FIELDS:  # cost never scope-calibrates (derived, see above)
            n = len(_component_samples(cal, "scope", c, m))
            r = active_scope_ratio(cal, c, m)
            rows.append(("scope", f"{c}/{m}", n, r))
    for lv in CLOSURE_LEVELS:
        # Closure no longer calibrates `cost` on its own (Task 10): the rolled-up
        # cost is now derived from the rolled-up tokens_k range, so this loop
        # moves onto CALIBRATED_METRIC_FIELDS like the scope loop above, rather
        # than the full METRIC_FIELDS it used while closure cost was still real.
        for m in CALIBRATED_METRIC_FIELDS:
            n = len(_component_samples(cal, "closure", lv, m))
            r = active_closure_ratio(cal, lv, m)
            rows.append(("closure", f"{lv}/{m}", n, r))
    for lv in CLOSURE_LEVELS:
        # Orchestration never calibrates `cost` (derived from tokens x
        # rates — see record_orchestration_sample), so this loop uses
        # CALIBRATED_METRIC_FIELDS, exactly like the scope and closure loops
        # above. All three agree; none of them iterates the full METRIC_FIELDS
        # any more.
        for m in CALIBRATED_METRIC_FIELDS:
            n = len(_component_samples(cal, "orchestration", lv, m))
            r = active_orchestration_fraction(cal, lv, m)
            rows.append(("orchestration", f"{lv}/{m}", n, r))
    for c in CLASSIFICATIONS:
        entry = (cal.get("fix") or {}).get(c) or {}
        n = min(int((entry.get("clean") or {}).get("samples", 0)),
                int((entry.get("reworked") or {}).get("samples", 0)))
        rows.append(("fix", c, n, active_fix_factor(cal, c)))

    if getattr(args, "format", "text") == "json":
        import json
        sys.stdout.write(json.dumps({
            "exists": exists,
            "granularity": cal.get("granularity", "story"),
            "components": [{"component": a, "bucket": b, "samples": n,
                            "active_ratio": r} for a, b, n, r in rows],
        }, indent=2) + "\n")
        return 0

    if not exists:
        sys.stdout.write("No calibration file yet — all components cold-start.\n")
    sys.stdout.write(f"granularity: {cal.get('granularity', 'story')}\n")
    sys.stdout.write(f"{'COMPONENT':<14} {'BUCKET':<22} {'SAMPLES':>7}  RATIO\n")
    for a, b, n, r in rows:
        shown = f"{r:.3f}" if r is not None else f"(cold-start, needs {MIN_SAMPLES})"
        sys.stdout.write(f"{a:<14} {b:<22} {n:>7}  {shown}\n")
    return 0


TOKEN_CLASSES = ("input", "output", "cache_write", "cache_read")

# USD per 1M tokens, Anthropic first-party API rates as of 2026-06-24.
# cache_write is 1.25x input; cache_read is 0.1x input.
# Partner-operated platforms (Bedrock, Vertex) price separately and need a
# config override at modules.l3io-pm.token_rates.
TOKEN_RATES = {
    "claude-opus-5":      {"input": 5.00,  "output": 25.00, "cache_write": 6.25,  "cache_read": 0.50},
    "claude-opus-5-fast": {"input": 10.00, "output": 50.00, "cache_write": 12.50, "cache_read": 1.00},
    "claude-fable-5":     {"input": 10.00, "output": 50.00, "cache_write": 12.50, "cache_read": 1.00},
    "claude-sonnet-5":    {"input": 3.00,  "output": 15.00, "cache_write": 3.75,  "cache_read": 0.30},
    "claude-sonnet-4-6":  {"input": 3.00,  "output": 15.00, "cache_write": 3.75,  "cache_read": 0.30},
    "claude-haiku-4-5":   {"input": 1.00,  "output": 5.00,  "cache_write": 1.25,  "cache_read": 0.10},
    # OpenAI — verify at https://openai.com/api/pricing before use.
    # Retired models retained for historical actuals verification:
    "codex-1":            {"input": 5.00,  "output": 30.00, "cache_write": 6.25,  "cache_read": 2.50},  # retired; original o3-based Codex Cloud
    "gpt-5":              {"input": 5.00,  "output": 30.00, "cache_write": 6.25,  "cache_read": 2.50},  # ambiguous; verify before use
    "gpt-5.4":            {"input": 2.50,  "output": 10.00, "cache_write": 3.13,  "cache_read": 1.25},  # retired 2026-08-31; succeeded by gpt-5.6-terra/luna in Codex
    # GPT-5.6 family (GA 2026-07-09): Sol/Terra/Luna.
    # Sol input/output/cache_read are promotional through 2026-11-21; cache_write is 1.25×
    # the original $5.00 standard input rate and did not move with the promotion.
    "gpt-5.6-sol":        {"input": 4.00,  "output": 20.00, "cache_write": 6.25,  "cache_read": 0.40},
    "gpt-5.6-terra":      {"input": 2.00,  "output": 12.00, "cache_write": 2.50,  "cache_read": 0.20},
    "gpt-5.6-luna":       {"input": 0.20,  "output":  1.20, "cache_write": 0.25,  "cache_read": 0.02},
}


def resolve_rates(model: str, overrides=None) -> dict:
    """The rate card for `model`, config overrides winning per model.

    An unknown model is a KeyError, never a default. A silently-wrong rate is
    exactly the failure this whole change exists to remove: the same token count
    prices 2x apart between a $5/M and a $10/M tier.
    """
    table = dict(TOKEN_RATES)
    if overrides:
        for k, v in overrides.items():
            table[k] = {**table.get(k, {}), **v}
    if model not in table:
        raise KeyError(f"unknown model {model!r} — add it to modules.l3io-pm.token_rates "
                       f"or use one of {sorted(table)}")
    return table[model]


def cost_from_tokens(tokens: dict, model: str, overrides=None) -> float:
    """USD for a per-class token count. `tokens` values are in THOUSANDS, rates
    are per million, hence the /1000."""
    rates = resolve_rates(model, overrides)
    total = 0.0
    for cls in TOKEN_CLASSES:
        v = _num_or_none((tokens or {}).get(cls))
        if v is None:
            continue
        # An override-only model can define a subset of the four classes. A bare
        # rates[cls] would surface as KeyError('cache_read') — which callers
        # print verbatim as e.args[0], giving the user the single word
        # "cache_read". Same hard-error policy as an unknown model, but with a
        # message that says what to do.
        if cls not in rates:
            raise KeyError(f"model {model!r} has no {cls!r} rate — modules.l3io-pm.token_rates "
                           f"must define all of {list(TOKEN_CLASSES)} for a model it adds")
        total += v * rates[cls]
    return round(total / 1000.0, 2)


FRESH_TOKEN_CLASSES = ("input", "output", "cache_write")
"""The classes a story's SIZE predicts.

`cache_read` is deliberately absent. It is a function of corpus size times agent
count -- how much context each dispatched agent re-reads -- not of how much work
the story asks for. A story that touches one file in a large repo reads the same
corpus as one that touches ten. Folding it into the scope basis made the ratio
measure the repo, not the story.

This is not theoretical. BASE_BANDS' tokens_k numbers (20-200k) were authored as
fresh-token bands, but actuals are captured cache-inclusive: one observed story
measured 182,121k with 97.4% of it cache reads. Dividing a cache-inclusive actual
by a fresh-scale band gave a scope ratio absorbing a ~1000x basis gap in silence,
and the per-class evidence is unambiguous about it being a basis error rather
than a real signal -- the complex bucket read 285.291 across five samples that
straddled the accounting change, while standard read 7.386 across three that did
not. Only the poisoned bucket moved.

cache_read is still captured, still priced, and still rolled up. It is simply not
what `scope` learns from; it belongs to the orchestration term, which is measured
as a fraction of children rather than predicted from a band.
"""


def fresh_tokens(block) -> float:
    """Sum of the fresh classes in a tokens_k mapping. 0.0 for a non-mapping."""
    if not hasattr(block, "get"):
        return 0.0
    return sum(_num_or_none(block.get(c)) or 0.0 for c in FRESH_TOKEN_CLASSES)


def fresh_share(mix: dict) -> float:
    """The fraction of a token mix that is fresh. Guarded against a degenerate mix."""
    f = sum(float(mix.get(c, 0.0)) for c in FRESH_TOKEN_CLASSES)
    return f if f > 0 else sum(COLD_START_TOKEN_MIX[c] for c in FRESH_TOKEN_CLASSES)


def tokens_block(counts: dict):
    """A tokens_k mapping: the four classes plus their validated total.

    `total` is stored rather than recomputed on read so that a node remains
    self-describing when read by anything that does not know the class list.
    It is always the sum — never an independently-entered number.
    """
    from ruamel.yaml.comments import CommentedMap

    tk = CommentedMap()
    total = 0.0
    for cls in TOKEN_CLASSES:
        v = _num_or_none(counts.get(cls)) or 0.0
        tk[cls] = int(v) if float(v).is_integer() else v
        total += v
    out = CommentedMap()
    out["total"] = int(total) if float(total).is_integer() else round(total, 2)
    for cls in TOKEN_CLASSES:
        out[cls] = tk[cls]
    return out


def rate_overrides(args):
    """Parse --token-rates into the overrides dict resolve_rates expects."""
    raw = getattr(args, "token_rates", "") or ""
    if not raw.strip():
        return None
    try:
        return json.loads(raw)
    except ValueError as e:
        _die_usage(f"--token-rates is not valid JSON: {e}")


def cmd_rates(args) -> int:
    """Print the effective rate table. Read-only; exists so the value actually in
    force — including any --token-rates override — is inspectable without
    reading source or guessing."""
    overrides = rate_overrides(args)
    # The EFFECTIVE table, per design §5 — so an override-only model (one that
    # exists solely in modules.l3io-pm.token_rates, e.g. a Bedrock or Vertex
    # rate card) is listed rather than silently omitted. Listing sorted(TOKEN_RATES)
    # alone made `rates` report the shipped defaults while pricing used something
    # else, which is the one thing this read-only subcommand exists to prevent.
    models = [args.model] if args.model else sorted(set(TOKEN_RATES) | set(overrides or {}))
    for m in models:
        try:
            r = resolve_rates(m, overrides)
        except KeyError as e:
            # e.args[0], not str(e) — KeyError.__str__ repr-quotes its argument,
            # which would double-wrap a message that already reads as prose.
            sys.stderr.write(f"pm-status.py: {e.args[0]}\n")
            return 2
        # `r.get`, not `r[...]`: an override-only model (one this table has no
        # shipped defaults to merge over) can legitimately define a subset of
        # the four classes, and listing it must report the gap rather than
        # raise KeyError on the model the user added by hand.
        cells = "  ".join(f"{c}=" + (f"{r[c]:.2f}" if _is_number(r.get(c)) else "n/a")
                          for c in TOKEN_CLASSES)
        sys.stdout.write(f"{m:<22} {cells}\n")
    return 0


def adr_register_path(state_root: str) -> str:
    return os.path.join(state_root, "adr-register.yaml")


def load_adr_register(state_root: str):
    """Load the ADR register, or a fresh skeleton if absent, empty, or malformed.

    Never raises: an absent file, an empty file, and a `next` that fails to
    parse as an int are all legal states that resolve to "start at 1" — a
    project with no adr-register.yaml yet must still work.
    """
    p = adr_register_path(state_root)
    y, data = _load(p)
    if data is None:
        from ruamel.yaml.comments import CommentedMap
        reg = CommentedMap()
        reg["next"] = 1
        reg["reserved"] = []
        return y, reg
    if data.get("reserved") is None:
        data["reserved"] = []
    return y, data


# The `ADR-` prefix is optional on the one home and case-insensitive on both. The
# scan's whole reason for existing (see `highest_adr_on_disk`) is the ADR nobody
# allocated through the register -- a hand-written one -- and hand-written ADRs are
# commonly named `ADR-NNNN-slug.md`, which matched neither pattern. A real directory
# holding ADR-0004..ADR-0025 scanned as "highest is 0", exactly as confidently as an
# empty one, and `adr-reserve` then issued numbers that were already on disk.
# Widening can only raise the floor the allocator starts from, never lower it.
_ADR_DOC_NAME = re.compile(r"^(?:[Aa][Dd][Rr]-)?(\d{4})-.+\.md$")
_ADR_OLD_HOME_NAME = re.compile(r"^[Aa][Dd][Rr]-(\d{4})-.+\.md$")


def _git_toplevel(path: str):
    """The git work tree containing `path`, or None (not a repo, or no git on PATH)."""
    try:
        r = subprocess.run(["git", "-C", path, "rev-parse", "--show-toplevel"],
                           capture_output=True, check=False, text=True)
    except OSError:
        return None
    top = r.stdout.strip()
    return top if r.returncode == 0 and top else None


class AdrHomeUnresolved(Exception):
    """The one ADR home (ADR-0005) could not be located, so the disk scan is impossible.

    Raised rather than warned-and-continued. `adr-reserve` is the only thing standing
    between two agents and one ADR number, so a number allocated from a scan that never
    happened is worse than no number at all: the caller reads exit 0 and a four-digit
    string off stdout and has no way to tell it apart from a real allocation. The old
    behaviour printed `0001` next to a stderr warning nobody captured.
    """


def highest_adr_on_disk(state_root: str, adr_dir: str = "") -> int:
    """Highest ADR number already written, in the one home and in the old one (ADR-0005).

    The register still records who is in flight; this scan only stops a new reservation
    from colliding with a file that already exists: a hand-written ADR, a Mode C ADR, or
    an ADR in a project that has not run `migrate-adrs`. The one home is `adr_dir` when
    given (step files pass {project-root}/docs/adr, since a BMad project need not be the
    repository root), else <git top-level of the state root>/docs/adr.

    Raises AdrHomeUnresolved when neither is available. The default is deliberately NOT
    widened to some guess (the state root's parent, the cwd): scanning the wrong tree
    reports "highest is 0" just as confidently as scanning an empty right one.
    """
    impl = os.path.dirname(os.path.abspath(state_root))
    hi = 0
    for arch in glob.glob(os.path.join(impl, "epic-*", "arch")):
        for name in os.listdir(arch):
            m = _ADR_OLD_HOME_NAME.match(name)
            if m:
                hi = max(hi, int(m.group(1)))
    if not adr_dir:
        top = _git_toplevel(state_root if os.path.isdir(state_root) else impl)
        if top is None:
            raise AdrHomeUnresolved(
                f"{state_root} is not inside a git work tree, so the one ADR home "
                f"(<git top-level>/docs/adr) cannot be located, and the old home "
                f"(epic-*/arch/) alone does not say what numbers docs/adr already "
                f"holds. Pass --adr-dir DIR naming the project's ADR directory "
                f"(normally {{project-root}}/docs/adr) and retry.")
        adr_dir = os.path.join(top, "docs", "adr")
    if adr_dir and os.path.isdir(adr_dir):
        for name in os.listdir(adr_dir):
            m = _ADR_DOC_NAME.match(name)
            if m:
                hi = max(hi, int(m.group(1)))
    return hi


def cmd_adr_reserve(args) -> int:
    """Allocate ADR numbers before dispatch, under a lock.

    A directory listing shows who has FINISHED writing. Only a register knows
    who is in flight. Three parallel ADR agents read the same near-empty
    directory and two of them chose 0013 while two chose 0014; the surviving
    ADR-0014 was cited by four stories meaning two different documents, and
    repairing that cost more than the gate it came from.
    """
    if args.count < 1:
        sys.stderr.write("ERROR --count must be >= 1\n")
        return 2
    from ruamel.yaml.comments import CommentedMap
    with adr_register_lock(args.state_root):
        yaml, reg = load_adr_register(args.state_root)
        # Unlike a malformed `next` (recoverable -- reset to 1 and keep going),
        # a malformed `reserved` is refused outright rather than repaired: this
        # list is the record of who is in flight, which is the entire reason
        # the register exists. Silently replacing it with [] would let a new
        # reservation collide with an in-flight one it can no longer see.
        reserved = reg.get("reserved")
        if not isinstance(reserved, list):
            sys.stderr.write(
                f"pm-status.py: adr-register.yaml has a malformed 'reserved' field "
                f"(expected a list, got {type(reserved).__name__}: {reserved!r}); "
                f"refusing to reserve -- a register that cannot say who is already "
                f"in flight cannot be trusted to hand out a new number. Fix or "
                f"restore adr-register.yaml by hand, then retry.\n")
            return 2
        try:
            start = int(reg.get("next", 1))
        except (TypeError, ValueError):
            sys.stderr.write(f"pm-status.py: adr-register.yaml has a malformed "
                             f"'next' ({reg.get('next')!r}); resetting to 1\n")
            start = 1
        start = max(start, 1)
        # Refuse rather than guess. Every other failure in this function returns 2
        # before a number is printed, and so does this one: a caller capturing stdout
        # cannot tell a guessed 0001 from a scanned one.
        try:
            on_disk = highest_adr_on_disk(args.state_root, args.adr_dir)
        except AdrHomeUnresolved as exc:
            sys.stderr.write(f"pm-status.py: adr-reserve: refusing to allocate -- {exc}\n")
            return 2
        start = max(start, on_disk + 1)
        numbers = list(range(start, start + args.count))
        for n in numbers:
            entry = CommentedMap()
            entry["number"] = n
            entry["slug"] = args.slug
            entry["epic"] = canonical_epic_key(args.epic)
            entry["reserved_at"] = _now_iso()
            reg.setdefault("reserved", []).append(entry)
        reg["next"] = start + args.count
        _atomic_dump(yaml, reg, adr_register_path(args.state_root))
    sys.stdout.write("\n".join(f"{n:04d}" for n in numbers) + "\n")
    return 0


def cmd_notice(args) -> int:
    """Record a one-time-ever advisory notice for this project. Exit 0 = emit it now (and
    record it), exit 1 = already emitted for this key, exit 2 = usage error OR an unexpected
    failure while recording (lock/I/O). 2 is deliberately overloaded with "usage error"
    rather than given a new number of its own: a caller that treats any nonzero exit as "do
    not print the pointer" already handles it correctly either way, and the one distinction
    that matters -- 1 means "already said, all is well" -- stays unambiguous. A crash must
    never surface as 1: a caller told "already emitted" says nothing further and moves on,
    so a masked crash would silently and permanently suppress the pointer with nothing to
    show for it.

    Scope is the KEY ALONE, not a session: there is no notion of "session" that outlives one
    skill invocation (`{session_id}` in `step-00-activate.md` is bound fresh per invocation
    and no caller of `notice` is ever a dispatched subagent that could inherit one), so a
    per-session key would never repeat and this would fire every single invocation -- exactly
    the nagging it exists to prevent. A key is recorded at most once, ever, per project: once
    a key has fired, it never fires again for that `--state-root`, which is correct for an
    advisory whose content is static ("this exists, configure it if you want") and whose
    trigger condition (`modules.l3io-pm` being absent) is itself a valid permanent state, not
    a transient one to keep re-flagging.

    An absent or unparseable notices file means nothing has been emitted yet -- a notice is
    advisory only, so a damaged file must never block the caller's real work; it is simply
    treated as empty and rewritten clean on this call. That tolerance covers a bad READ only:
    a failure while actually recording (the lock, or the write itself) is a real failure and
    is reported as one, not folded into "already emitted" or silently swallowed as success.
    """
    key = (args.key or "").strip()
    if not key:
        sys.stderr.write("notice: --key must be non-empty\n")
        return 2
    path = notices_path(args.state_root)
    try:
        os.makedirs(args.state_root, exist_ok=True)
        with notices_lock(args.state_root):
            # _load returns (yaml_instance, data) -- data is None when the file is absent
            # or fails to parse the way _load's caller expects. Reuse the returned YAML
            # instance for the dump so round-trip settings (width, indent, quote style)
            # match.
            try:
                y, data = _load(path)
            except Exception:  # noqa: BLE001 -- a notice ledger that cannot be read is rebuilt, never fatal
                y, data = _yaml(), None
            keys = data.get("keys") if isinstance(data, dict) else None
            if not isinstance(keys, list):
                keys = []
            if key in keys:
                return 1
            keys.append(key)
            _atomic_dump(y, {"keys": keys}, path)
    except Exception as e:  # noqa: BLE001 -- recording a notice must never fail the command it advises
        sys.stderr.write(f"notice: could not record the notice at {path}: {e}\n")
        return 2
    return 0


# The estimate-time model. Skills pass modules.l3io-pm.default_model through
# --model; this is the fallback for a direct CLI call, and it is a REAL model
# id so an unknown-model error can never be produced by the default itself.
DEFAULT_ESTIMATE_MODEL = "claude-opus-5"

# Cold-start assumption about a healthy, cache-warm run. NOT a calibrated
# ratio and not a component of its own: it is replaced by the observed mean
# once three story samples carry class data (see observed_mix below). It
# affects only how a banded TOTAL is SPLIT across classes — the banded total
# itself is untouched by it.
COLD_START_TOKEN_MIX = {"input": 0.15, "output": 0.05,
                        "cache_write": 0.30, "cache_read": 0.50}


def observed_mix(cal) -> dict:
    """Mean observed token mix, or the cold-start assumption below MIN_SAMPLES."""
    samples = ((cal or {}).get("token_mix") or {}).get("samples") or []
    # hasattr(s, "get") first: a stray non-mapping entry (hand-edit, bad
    # merge, partial corruption of the committed, shared calibration file)
    # must fall back to cold-start like every other malformed shape here —
    # not crash `estimate-story` for the whole project. Same guard as the
    # tokens_k mapping check in record_story_sample above.
    usable = [s for s in samples if hasattr(s, "get") and
              all(_num_or_none(s.get(c)) is not None for c in TOKEN_CLASSES)]
    if len(usable) < MIN_SAMPLES:
        return dict(COLD_START_TOKEN_MIX)
    mix = {c: sum(float(s[c]) for s in usable) / len(usable) for c in TOKEN_CLASSES}
    total = sum(mix.values())
    if total <= 0:
        return dict(COLD_START_TOKEN_MIX)
    return {c: v / total for c, v in mix.items()}   # renormalize; means need not sum to 1


def split_tokens(total: float, mix: dict) -> dict:
    """Split a banded total across classes, preserving the total exactly.

    Rounding drift goes to the largest class rather than being dropped, so
    `sum(classes) == total` is an invariant a test can assert and a reader can
    trust.
    """
    out = {c: round(total * float(mix.get(c, 0.0))) for c in TOKEN_CLASSES}
    drift = round(total) - sum(out.values())
    if drift:
        biggest = max(TOKEN_CLASSES, key=lambda c: out[c])
        out[biggest] += drift
    return out


# Cold-start base bands (low, high) per classification. These were previously a
# markdown table in steps/shared/step-estimate.md; this is now the single source.
# No `cost` row: cost is derived from the tokens_k total (split across classes,
# then priced per model) rather than banded and calibrated on its own — see
# cmd_estimate_story. Keeping a separate cost band was the original defect: a
# cost estimate with no arithmetic relationship to the token estimate it should
# follow, drifting apart from it as the two calibrated independently.
# `tokens_k` here is a FRESH-token band (input + output + cache_write) -- it always
# was, but nothing said so, and the actual it was divided by is cache-inclusive.
# That mismatch is the defect FRESH_TOKEN_CLASSES documents. Do not "correct" these
# numbers upward to meet a cache-inclusive actual: cache_read is projected from the
# observed mix at estimate time and belongs to orchestration, not scope.
BASE_BANDS = {
    "simple":   {"man_hours": (2, 4),  "hitl_hours": (0.1, 0.3), "elapsed_hours": (0.5, 1.5),
                 "tokens_k": (20, 50)},
    "standard": {"man_hours": (4, 8),  "hitl_hours": (0.2, 0.5), "elapsed_hours": (1, 3),
                 "tokens_k": (40, 100)},
    "complex":  {"man_hours": (8, 16), "hitl_hours": (0.3, 1.0), "elapsed_hours": (2, 6),
                 "tokens_k": (80, 200)},
}


def compute_story_estimate(state_root, node, cls, model, overrides, confidence=None):
    """Compute and write a story's estimate block: band midpoint x scope ratio x fix
    factor, per metric. Classification is the model's judgment; everything after it
    is arithmetic, done here so it's error-checked and reproducible.

    Each metric queries its own calibrated scope ratio — man_hours and tokens_k may
    be calibrated independently once each has >=3 samples, so ratios are looked up
    per metric, never hoisted out and reused across all four in BASE_BANDS.

    All four applied ratios are recorded as `estimate.scope_ratios`, per metric.
    This is load-bearing, not provenance: `derive_story_sample` divides the applied
    ratio back out to measure the next sample against the base band, and one
    scalar cannot reconstruct four metrics' corrections.

    `cost` is not one of the banded/calibrated metrics: it is priced from the
    banded tokens_k TOTAL, split across classes by `observed_mix` (or the
    cold-start assumption below three samples), then run through
    `cost_from_tokens` for `--model` (falling back to DEFAULT_ESTIMATE_MODEL).
    This keeps cost arithmetically bound to the token estimate it prices —
    the two can no longer drift apart the way a separately-banded,
    separately-calibrated cost could.

    Never saves and never exits: cmd_estimate_story saves after it; promote-issue
    writes the new node and its estimate in one save.
    """
    _, cal = load_calibration(state_root)
    fix = active_fix_factor(cal, cls)
    fix = COLD_START_FIX_FACTOR if fix is None else fix

    from ruamel.yaml.comments import CommentedMap

    # Every value below is computed into locals first, including the token
    # split and the priced cost -- node/est is not touched until all of that
    # (in particular cost_from_tokens, the one call that can raise) has
    # succeeded. An in-process caller must be able to catch PMError and keep
    # going without finding a half-written estimate block behind it.
    applied = CommentedMap()
    raw = {}
    for metric, (lo, hi) in BASE_BANDS[cls].items():
        mid = (lo + hi) / 2.0
        ratio = active_scope_ratio(cal, cls, metric)
        if ratio is None:
            ratio = COLD_START_SCOPE_RATIO
        applied[metric] = round(ratio, 4)
        value = mid * ratio * fix
        raw[metric] = round(value) if metric == "tokens_k" else round(value, 2)

    # The band produces FRESH tokens, matching what the scope ratio now measures.
    # cache_read is then projected from the observed mix rather than banded: it
    # tracks corpus x agent count, so a story-size band cannot predict it, but the
    # ratio it bears to fresh tokens is exactly what token_mix samples record.
    fresh_total = raw["tokens_k"]
    mix = observed_mix(cal)
    fshare = fresh_share(mix)
    counts = split_tokens(fresh_total, {c: mix.get(c, 0.0) / fshare for c in FRESH_TOKEN_CLASSES})
    counts["cache_read"] = round(fresh_total * (mix.get("cache_read", 0.0) / fshare))
    tokens_est = tokens_block(counts)
    try:
        cost = cost_from_tokens(counts, model, overrides)
    except KeyError as e:
        # e.args[0], not str(e) — KeyError.__str__ repr-quotes its argument,
        # which would double-wrap a message that already reads as prose.
        raise PMError(2, e.args[0])

    # Everything above is a local computation; only now, with cost already
    # priced successfully, do we touch node. Get the existing estimate block
    # or create one -- in place, so any other keys and ruamel comments on an
    # existing block survive -- then write the computed values into it in the
    # same key order cmd_estimate_story has always produced.
    est = node.get("estimate")
    if est is None:
        est = CommentedMap()
        node["estimate"] = est
    for metric, value in raw.items():
        est[metric] = value
    est.pop("tokens_k")
    est["tokens_k"] = tokens_est
    est["cost"] = cost
    est["model"] = model

    est["fix_factor"] = round(fix, 4)
    est["scope_ratios"] = applied
    est.pop("scope_ratio", None)   # the superseded single-value form
    if confidence:
        est["confidence"] = confidence
    node["classification"] = cls
    node["updated_at"] = _now_iso()
    return applied


def cmd_estimate_story(args) -> int:
    """CLI wrapper over compute_story_estimate: resolve, compute, save, report."""
    path = story_file(args.state_root, args.story)
    if path is None:
        _die_notfound(f"story {args.story}")
    y, node = load_node(path)
    if node is None:
        _die_notfound(f"story {args.story} — file is empty")
    try:
        applied = compute_story_estimate(args.state_root, node, args.classification,
                                         args.model or DEFAULT_ESTIMATE_MODEL,
                                         rate_overrides(args), args.confidence)
    except PMError as e:
        _die_usage(e.msg)
    save_node(y, node, path)
    shown = " ".join(f"{m}={v}" for m, v in applied.items())
    sys.stdout.write(f"OK estimate-story {args.story} class={args.classification} "
                     f"scope_ratios[{shown}] fix_factor={node['estimate']['fix_factor']}\n")
    return 0


# Closure overhead as a fraction of children, used when no calibrated ratio is
# active yet. Deliberately a band, not a point: closure cost is variable.
COLD_START_CLOSURE_BAND = (0.10, 0.25)

# The orchestration fraction (active_orchestration_fraction) is a point
# estimate; these widen it into a range the same way COLD_START_CLOSURE_BAND
# widens the closure ratio. There is NO cold-start pair here, unlike closure
# — and that asymmetry is deliberate, not an oversight to "fix" by adding one.
# While the component is inactive (< MIN_SAMPLES) the fraction is 0 and the
# band contributes nothing to the roll-up at all; a cold-start orchestration
# band would put a number on a quantity this rework explicitly refuses to
# guess (see active_orchestration_fraction's docstring — every pre-existing
# measurement was contaminated by a cache-eviction defect). The stderr
# warning `cmd_estimate_rollup` emits while unseeded is what stands in for
# that number instead.
ORCH_SPREAD = (0.8, 1.2)

# The orchestration band's contribution to the roll-up MIDPOINT, per unit of
# applied fraction. `derive_closure_sample` subtracts `est_total x fraction x
# ORCH_MID` off the parent estimate midpoint so what remains is the closure
# band alone — the quantity the closure ratio is actually applied to. Derived
# from ORCH_SPREAD rather than restated as `1.0`, so widening the spread
# asymmetrically can never silently desynchronise the two.
ORCH_MID = (ORCH_SPREAD[0] + ORCH_SPREAD[1]) / 2.0


def _child_estimate_value(node, metric):
    """A child's value for `metric`: single-value form first (a story), else
    the midpoint of its range form (a sprint). None if neither is present.

    Reuses CLOSURE_RANGE_KEYS (metric -> parent low/high key names) rather
    than a second near-duplicate mapping, and `_estimate_metric` (not a local
    unwrap) for the single-value read — see that function's docstring for why
    duplicating the tokens_k unwrap here is exactly the mistake to avoid.
    """
    est = (node or {}).get("estimate") or {}
    v = _estimate_metric(est, metric)
    if v is not None:
        return v
    lo, hi = CLOSURE_RANGE_KEYS[metric]
    return _mid(est, lo, hi)


def rollup_parent_estimate(state_root, epic, sprint, model, overrides):
    """Roll a sprint's story estimates, or an epic's sprint estimates, up to
    the parent as a range: sum(children) + a closure band + an orchestration
    band. Output is always range form, even when every child estimate is
    single-value (the story form).

    The closure band scales by the calibrated closure ratio for level/metric
    once active (>=3 samples), else the cold-start band applies (equivalently,
    ratio 1.0). The orchestration band scales by the calibrated orchestration
    FRACTION for level/metric once active, else it contributes nothing — there
    is no cold-start prior for orchestration (see ORCH_SPREAD, and
    active_orchestration_fraction's docstring for why). Both bands widen by a
    fixed spread (COLD_START_CLOSURE_BAND, ORCH_SPREAD respectively) rather
    than landing on a single point.

    The applied ratios/fractions are recorded as `estimate.closure_ratios` and
    `estimate.orchestration_ratios`, per metric, so `derive_closure_sample` and
    a future orchestration-sample reader can divide them back out — the same
    reason `estimate.scope_ratios` exists on a story.

    `cost` is not one of the banded metrics (see CLOSURE_RANGE_KEYS): it is
    derived from the rolled-up tokens_k range, split across classes by
    `observed_mix`, then priced for `--model` (falling back to
    DEFAULT_ESTIMATE_MODEL) — the sprint/epic-level mirror of what
    `cmd_estimate_story` already does for a story. This keeps the rolled-up
    cost arithmetically bound to the rolled-up token estimate it prices,
    instead of banding and calibrating a second, independently-drifting cost.

    Never exits: raises PMError(3) for a missing parent, PMError(2) for
    nothing to roll up or an unpriceable model.

    The epic-level roll-up rewrites epic.yaml, so it runs under that epic's
    epic_node_lock -- re-entrantly when promote-issue, which already holds it,
    is the caller. An epic the pre-check cannot find raises PMError(3) right
    there, with no lock file created for it. It is never handed to the body
    unlocked: find_epic_dir scans active -> planned -> archived, so a move-epic
    the other way can land mid-scan and hide an epic that exists, and the body's
    own re-resolve would then find it and reach save_node without the lock.
    """
    if sprint:
        return _rollup_parent_estimate(state_root, epic, sprint, model, overrides)
    if epic_file(state_root, epic) is None:
        raise PMError(3, f"epic {epic}")
    with epic_node_lock(state_root, epic):
        return _rollup_parent_estimate(state_root, epic, sprint, model, overrides)


def _rollup_parent_estimate(state_root, epic, sprint, model, overrides):
    """rollup_parent_estimate's body; the caller holds the epic lock for an epic roll-up."""
    level = "sprint" if sprint else "epic"
    if level == "sprint":
        ppath = sprint_file(state_root, epic, sprint)
        child_paths = list_story_files(state_root, epic, sprint)
    else:
        ppath = epic_file(state_root, epic)
        child_paths = [sprint_file(state_root, epic, _sprint_key_from_dir(d))
                       for d in list_sprint_dirs(state_root, epic)]
    if ppath is None:
        raise PMError(3, f"{level} {sprint or epic}")
    y, pnode = load_node(ppath)
    if pnode is None:
        raise PMError(3, f"{level} file is empty")

    _, cal = load_calibration(state_root)
    from ruamel.yaml.comments import CommentedMap
    est = CommentedMap()
    applied = CommentedMap()
    orch_applied = CommentedMap()
    counted = 0
    for metric, (lo_key, hi_key) in CLOSURE_RANGE_KEYS.items():
        total = 0.0
        seen = 0
        for cp in child_paths:
            if cp is None:
                continue
            _, cn = load_node(cp)
            v = _child_estimate_value(cn, metric)
            if v is not None:
                total += v
                seen += 1
        if seen == 0:
            continue
        counted = max(counted, seen)
        ratio = active_closure_ratio(cal, level, metric)
        if ratio is None:
            ratio = 1.0            # cold start: the closure band applies unscaled
        applied[metric] = round(ratio, 4)

        frac = active_orchestration_fraction(cal, level, metric)
        orch_applied[metric] = round(frac, 4) if frac is not None else 0
        of = frac or 0.0
        lo = total * (1 + ratio * COLD_START_CLOSURE_BAND[0] + of * ORCH_SPREAD[0])
        hi = total * (1 + ratio * COLD_START_CLOSURE_BAND[1] + of * ORCH_SPREAD[1])
        if metric == "tokens_k":
            est[lo_key], est[hi_key] = round(lo), round(hi)
        else:
            est[lo_key], est[hi_key] = round(lo, 2), round(hi, 2)

    if counted == 0:
        raise PMError(2, f"{level} {sprint or epic} has no child estimates to roll up")

    est["closure_ratios"] = applied
    est["orchestration_ratios"] = orch_applied
    # ANY inactive metric warns, not just "every metric inactive" (`not any(...)`
    # would under-fire: orchestration calibrates per metric, and a metric is
    # sampled only when every child carries a numeric actual for it, so under a
    # mixed runtime man_hours can activate while tokens_k never does — `any()`
    # would then be true and stay silent on exactly the metric the warning
    # exists to flag). Named, not blanket: listing which metrics are still
    # unestimated makes the warning actionable instead of a caveat that is
    # "always true anyway" once any single metric has activated.
    inactive = [m for m, v in orch_applied.items() if not v]
    if inactive:
        sys.stderr.write(
            "pm-status.py: warning — orchestration is unestimated for "
            f"{', '.join(inactive)} (component has <{MIN_SAMPLES} samples at "
            f"{level} level); this estimate is known-low on those metrics.\n")

    mix = observed_mix(cal)
    try:
        for bound, key in (("tokens_k_min", "cost_low"), ("tokens_k_max", "cost_high")):
            tv = _num_or_none(est.get(bound))
            if tv is not None:
                est[key] = cost_from_tokens(split_tokens(tv, mix), model, overrides)
    except KeyError as e:
        # e.args[0], not str(e) — KeyError.__str__ repr-quotes its argument,
        # which would double-wrap a message that already reads as prose.
        raise PMError(2, e.args[0])
    est["model"] = model

    est["confidence"] = "medium"
    pnode["estimate"] = est
    pnode["updated_at"] = _now_iso()
    save_node(y, pnode, ppath)
    return level, counted


def cmd_estimate_rollup(args) -> int:
    """CLI wrapper over rollup_parent_estimate."""
    try:
        level, counted = rollup_parent_estimate(args.state_root, args.epic, args.sprint,
                                                args.model or DEFAULT_ESTIMATE_MODEL,
                                                rate_overrides(args))
    except PMError as e:
        if e.code == 3:
            _die_notfound(e.msg)
        _die_usage(e.msg)
    sys.stdout.write(f"OK estimate-rollup {level} {args.sprint or args.epic} "
                     f"from {counted} children\n")
    return 0


def list_story_files(state_root: str, epic_key: str, sprint_key: str) -> list:
    """Sorted story files in a sprint, excluding sprint.yaml."""
    d = find_epic_dir(state_root, epic_key)
    if d is None:
        return []
    sd = os.path.join(d, sprint_dirname(sprint_key))
    if not os.path.isdir(sd):
        return []
    return sorted(os.path.join(sd, n) for n in os.listdir(sd)
                  if n.endswith(".yaml") and n != "sprint.yaml")


def _accumulate_actuals(totals: dict, node) -> None:
    actual = (node or {}).get("actual") or {}
    for m in METRIC_FIELDS:
        v = _actual_metric(actual, m)
        if v is None:
            continue
        totals[m] = totals.get(m, 0.0) + v


# --------------------------------------------------------------------------- #
# spend attribution — the three buckets metrics-contract.md §6 defines
#
# The estimate has three terms (children + closure band + orchestration band), so
# a report of what was actually spent has to have the same three, or the largest
# term stays invisible: on the run that motivated this model, orchestration was
# 72% of total spend and stories were 24%. Recording it on disk and omitting it
# from every rendered report leaves the number nobody can act on. Design §9's CLI
# table specifies this breakout for `report`; `show` carries it too, since it is
# the per-node view of the same three buckets.
# --------------------------------------------------------------------------- #
SPEND_BUCKETS = ("stories", "closure", "orchestration")


def _block_totals(node, block: str = "actual") -> dict:
    """One metric block's numeric values. Absent and `N/A` entries are omitted
    rather than coerced to zero — a missing measurement is not a measured zero."""
    b = (node or {}).get(block) or {}
    out = {}
    for m in METRIC_FIELDS:
        v = _actual_metric(b, m)
        if v is not None:
            out[m] = v
    return out


def _add_totals(dst: dict, src: dict) -> None:
    for k, v in (src or {}).items():
        dst[k] = dst.get(k, 0.0) + v


def _closure_totals(parent_actual: dict, children_total: dict) -> dict:
    """A node's own closure-phase spend: its `actual` minus its children's sum.

    The same residual `derive_closure_sample` measures its component from, so the
    report and the calibration loop can never disagree about what "closure" means.
    Only metrics BOTH sides carry are reported — a parent metric with no comparable
    children sum has no residual, not a residual equal to the whole parent. Clamped
    at zero for display: a negative residual is a wall-clock overlap or a miscount
    (`derive_closure_sample` names which), not negative spend.
    """
    out = {}
    for m, pv in (parent_actual or {}).items():
        cv = (children_total or {}).get(m)
        if cv is None:
            continue
        out[m] = max(0.0, pv - cv)
    return out


def _new_spend() -> dict:
    return {b: {} for b in SPEND_BUCKETS}


def _merge_spend(dst: dict, src: dict) -> None:
    for b in SPEND_BUCKETS:
        _add_totals(dst[b], (src or {}).get(b) or {})


def _spend_total(spend: dict) -> dict:
    """The three buckets summed — what the level actually cost, end to end."""
    out = {}
    for b in SPEND_BUCKETS:
        _add_totals(out, (spend or {}).get(b) or {})
    return out


def _sprint_spend(story_totals: dict, snode) -> dict:
    return {"stories": dict(story_totals),
            "closure": _closure_totals(_block_totals(snode, "actual"), story_totals),
            "orchestration": _block_totals(snode, "orchestration")}


def _has_spend(spend: dict) -> bool:
    return any((spend or {}).get(b) for b in SPEND_BUCKETS)


def rollup_sprint(state_root: str, epic_key: str, sprint_key: str) -> dict:
    by_status, totals, stories = {}, {}, []
    blocked_details, cumulative_blocks = [], 0
    for p in list_story_files(state_root, epic_key, sprint_key):
        _, node = load_node(p)
        if node is None:
            continue
        st = str(node.get("status", "unknown"))
        by_status[st] = by_status.get(st, 0) + 1
        _accumulate_actuals(totals, node)
        row = {"key": node.get("key", os.path.basename(p)), "status": st}
        if st == "blocked":
            row["blocked_reason"] = str(node.get("blocked_reason", "") or "")
            blocked_details.append(
                {"key": row["key"], "reason": row["blocked_reason"]})
        # completion_evidence.blocks_seen counts events over the story's whole life,
        # not current state; a story currently unblocked can still contribute here.
        ce = node.get("completion_evidence") or {}
        cumulative_blocks += int(ce.get("blocks_seen", 0) or 0)
        stories.append(row)
    sp = sprint_file(state_root, epic_key, sprint_key)
    _, snode = load_node(sp) if sp else (None, None)
    return {
        "key": sprint_key,
        "status": str((snode or {}).get("status", "unknown")),
        "story_count": len(stories),
        "by_status": by_status,
        "blocked_stories": len(blocked_details),
        "blocked_details": blocked_details,
        "blocks_seen_cumulative": cumulative_blocks,
        "actual_totals": totals,
        "node_actual": _block_totals(snode, "actual"),
        "spend": _sprint_spend(totals, snode),
        "stories": stories,
    }


def rollup_epic(state_root: str, epic_key: str) -> dict:
    by_status, totals, sprints, story_count = {}, {}, [], 0
    spend, sprint_actual_sum = _new_spend(), {}
    blocked_stories_total, cumulative_blocks_total = 0, 0
    blocked_details_all = []
    for sd in list_sprint_dirs(state_root, epic_key):
        skey = _sprint_key_from_dir(sd)
        r = rollup_sprint(state_root, epic_key, skey)
        sprints.append(r)
        story_count += r["story_count"]
        for k, v in r["by_status"].items():
            by_status[k] = by_status.get(k, 0) + v
        for k, v in r["actual_totals"].items():
            totals[k] = totals.get(k, 0.0) + v
        _merge_spend(spend, r["spend"])
        _add_totals(sprint_actual_sum, r["node_actual"])
        blocked_stories_total += r.get("blocked_stories", 0)
        cumulative_blocks_total += r.get("blocks_seen_cumulative", 0)
        for detail in r.get("blocked_details", []):
            blocked_details_all.append({**detail, "sprint": r["key"]})
    ep = epic_file(state_root, epic_key)
    _, enode = load_node(ep) if ep else (None, None)
    # The epic's OWN closure residual sits on top of its sprints' — one bucket,
    # two levels, because both are "the closing level's own closure phases".
    _add_totals(spend["closure"],
                _closure_totals(_block_totals(enode, "actual"), sprint_actual_sum))
    _add_totals(spend["orchestration"], _block_totals(enode, "orchestration"))
    return {
        "key": epic_key,
        "status": str((enode or {}).get("status", "unknown")),
        "sprint_count": len(sprints),
        "story_count": story_count,
        "by_status": by_status,
        "blocked_stories": blocked_stories_total,
        "blocked_details": blocked_details_all,
        "blocks_seen_cumulative": cumulative_blocks_total,
        "actual_totals": totals,
        "node_actual": _block_totals(enode, "actual"),
        "spend": spend,
        "sprints": sprints,
    }


def _fmt_actuals(totals: dict) -> str:
    """Render an actuals dict in stable METRIC_FIELDS order."""
    return "  ".join(f"{m}={_norm_spend(totals.get(m))}" for m in METRIC_FIELDS)


def _norm_spend(v):
    """Display form for a summed metric: 0 when absent, trimmed of float noise.

    Summing floats produces 3.9000000000000004; a report that prints that is
    reporting its own arithmetic rather than the number. Rounded to 4 places
    (well past any metric's real precision) and shown as an int when integral.
    """
    if v is None:
        return 0
    try:
        f = round(float(v), 4)
    except (TypeError, ValueError):
        return v
    return int(f) if f.is_integer() else f


# --------------------------------------------------------------------------- #
# progress model — one builder, consumed by every renderer and every surface
# --------------------------------------------------------------------------- #
def list_all_epics(state_root: str) -> list:
    """(epic_key, dir_status) for every epic in every status folder, sorted by key.

    The directory name is authoritative for the key: 'epic-001' -> 'E001'. Reading the
    key from the file instead would let a mis-keyed file hide an epic entirely.
    """
    found = []
    for status in STATUS_DIRS:
        base = os.path.join(state_root, status)
        if not os.path.isdir(base):
            continue
        for name in sorted(os.listdir(base)):
            if not name.startswith("epic-"):
                continue
            if not os.path.isdir(os.path.join(base, name)):
                continue
            suffix = name[len("epic-"):]
            if not suffix.isdigit():
                continue
            found.append((f"E{int(suffix):03d}", status))
    return sorted(found, key=lambda t: t[0])


def _build_sprint_detail(state_root: str, epic_key: str, sprint_key: str,
                         events_index: dict, now=None) -> dict:
    """One sprint and its stories.

    `detail["flags"]` holds only the sprint's OWN flags (its stuck state, and any story
    file too broken to become a node of its own). Story flags live on their story. The
    flat aggregate is assembled later by `_collect_flags` — an earlier version pushed
    descendants' flags up into the parent, which made every ancestor row report "stuck"
    whenever one story was.
    """
    flags: list = []
    sp = sprint_file(state_root, epic_key, sprint_key)
    snode = {}
    if sp is not None:
        try:
            _, loaded = load_node(sp)
            snode = loaded or {}
        except Exception as e:  # noqa: BLE001 - a bad file must not kill the report
            flags.append({"kind": "unreadable", "level": "sprint",
                          "key": f"{epic_key}/{sprint_key}", "detail": str(e)})

    s_status = str(snode.get("status", "unknown"))
    s_dwell, s_exact = dwell_hours({"key": sprint_key, "status": s_status,
                                    "updated_at": snode.get("updated_at")},
                                   events_index, now)
    flags += compute_flags("sprint", f"{epic_key}/{sprint_key}", s_status, s_dwell, s_exact)

    stories, by_status, totals = [], {}, {}
    for p in list_story_files(state_root, epic_key, sprint_key):
        try:
            _, node = load_node(p)
        except Exception as e:  # noqa: BLE001
            # No story node exists to hang this on, so it belongs to the sprint.
            flags.append({"kind": "unreadable", "level": "story",
                          "key": os.path.basename(p), "detail": str(e)})
            continue
        if node is None:
            continue
        st = str(node.get("status", "unknown"))
        key = str(node.get("key", os.path.basename(p)))
        by_status[st] = by_status.get(st, 0) + 1
        _accumulate_actuals(totals, node)
        d, ex = dwell_hours(node, events_index, now)
        story_row = {"key": key, "status": st,
                     "estimate": dict(node.get("estimate") or {}),
                     "actual": dict(node.get("actual") or {}),
                     "updated_at": node.get("updated_at"),
                     "dwell_hours": None if d is None else round(d, 2),
                     "dwell_exact": ex,
                     "flags": compute_flags("story", key, st, d, ex)}
        if st == "blocked":
            story_row["blocked_reason"] = str(node.get("blocked_reason", "") or "")
        stories.append(story_row)

    return {"key": sprint_key, "status": s_status, "story_count": len(stories),
            "by_status": by_status, "actual_totals": totals,
            "node_actual": _block_totals(snode, "actual"),
            "spend": _sprint_spend(totals, snode),
            "estimate": dict(snode.get("estimate") or {}),
            "updated_at": snode.get("updated_at"),
            "dwell_hours": None if s_dwell is None else round(s_dwell, 2),
            "dwell_exact": s_exact, "flags": flags, "stories": stories}


def _collect_flags(epic_detail: dict) -> list:
    """Flatten one epic subtree's flags for the model-level aggregate."""
    out = list(epic_detail.get("flags") or [])
    for sp in epic_detail.get("sprints") or []:
        out += list(sp.get("flags") or [])
        for st in sp.get("stories") or []:
            out += list(st.get("flags") or [])
    return out


def build_epic_detail(state_root: str, epic_key: str, dir_status: str,
                      events_index: dict, now=None) -> dict:
    """One epic subtree, enriched with dwell times, flags, and placement checks."""
    flags: list = []
    ep = epic_file(state_root, epic_key)
    y_node = None
    if ep is not None:
        try:
            _, y_node = load_node(ep)
        except Exception as e:  # noqa: BLE001
            flags.append({"kind": "unreadable", "level": "epic", "key": epic_key,
                          "detail": str(e)})
    enode = y_node or {}

    status = str(enode.get("status", "unknown"))
    expected = STATUS_FOR_DIR.get(dir_status)
    if expected and status != "unknown" and status != expected:
        flags.append({"kind": "placement", "level": "epic", "key": epic_key,
                      "detail": f"status {status!r} but sits in {dir_status}/ "
                                f"(expected {expected!r})"})

    lock = None
    raw_lock = enode.get("_lock")
    if isinstance(raw_lock, dict):
        claimed = _parse_iso(raw_lock.get("claimed_at"))
        ttl = raw_lock.get("ttl_minutes")
        stale = False
        if claimed is not None and ttl:
            try:
                age_min = ((now or datetime.now(UTC))
                           - claimed).total_seconds() / 60.0
                stale = age_min > float(ttl)
            except (TypeError, ValueError):
                stale = False
        lock = {"session_id": raw_lock.get("session_id"),
                "claimed_at": raw_lock.get("claimed_at"),
                "ttl_minutes": ttl, "stale": stale}
        if stale:
            flags.append({"kind": "stale-lock", "level": "epic", "key": epic_key,
                          "detail": f"lock claimed {raw_lock.get('claimed_at')} "
                                    f"exceeds ttl {ttl}m"})

    dwell, exact = dwell_hours({"key": epic_key, "status": status,
                                "updated_at": enode.get("updated_at")},
                               events_index, now)
    flags += compute_flags("epic", epic_key, status, dwell, exact)

    sprints, totals, by_status, story_count = [], {}, {}, 0
    spend, sprint_actual_sum = _new_spend(), {}
    for sd in list_sprint_dirs(state_root, epic_key):
        skey = _sprint_key_from_dir(sd)
        s_detail = _build_sprint_detail(state_root, epic_key, skey, events_index, now)
        sprints.append(s_detail)
        story_count += s_detail["story_count"]
        for k, v in s_detail["by_status"].items():
            by_status[k] = by_status.get(k, 0) + v
        for k, v in s_detail["actual_totals"].items():
            totals[k] = totals.get(k, 0.0) + v
        _merge_spend(spend, s_detail["spend"])
        _add_totals(sprint_actual_sum, s_detail["node_actual"])
    _add_totals(spend["closure"],
                _closure_totals(_block_totals(enode, "actual"), sprint_actual_sum))
    _add_totals(spend["orchestration"], _block_totals(enode, "orchestration"))

    return {
        "key": epic_key, "title": enode.get("title"), "status": status,
        "dir_status": dir_status, "sprint_count": len(sprints),
        "story_count": story_count, "by_status": by_status,
        "estimate": dict(enode.get("estimate") or {}),
        "actual_totals": totals, "node_actual": _block_totals(enode, "actual"),
        "spend": spend, "updated_at": enode.get("updated_at"),
        "dwell_hours": None if dwell is None else round(dwell, 2),
        "dwell_exact": exact, "lock": lock, "flags": flags, "sprints": sprints,
    }


def load_plan(plan_pointer: str):
    """Load plan phases via the stable pointer.

    `plan-output-meta.yaml` is a pointer plus summary scalars and deliberately holds no
    phases list (step-06-plan-output.md §4), so the phases come from the snapshot it
    names, resolved in the pointer's own directory. A dangling pointer yields the meta
    with empty phases rather than an error: the state hierarchy is still worth showing.
    """
    if not plan_pointer or not os.path.isfile(plan_pointer):
        return None
    try:
        _, meta = _load(plan_pointer)
    except Exception as e:  # noqa: BLE001
        sys.stderr.write(f"pm-status.py: warning — could not read plan pointer: {e}\n")
        return None
    if not meta:
        return None
    meta = dict(meta)
    phases = []
    snap_name = meta.get("current_plan")
    if snap_name:
        snap = os.path.join(os.path.dirname(os.path.abspath(plan_pointer)), str(snap_name))
        if os.path.isfile(snap):
            try:
                _, snode = _load(snap)
                phases = [dict(p) for p in ((snode or {}).get("phases") or [])]
            except Exception as e:  # noqa: BLE001
                sys.stderr.write(f"pm-status.py: warning — could not read plan "
                                 f"snapshot: {e}\n")
        else:
            sys.stderr.write(f"pm-status.py: warning — plan pointer names a missing "
                             f"snapshot: {snap_name}\n")
    return {"meta": meta, "phases": phases}


DEFAULT_REPORT_STATUSES = ("planned", "active")


def build_progress_model(state_root: str, plan=None, statuses=None,
                         include_archived: bool = False, now=None) -> dict:
    """The one model every renderer and every surface consumes.

    `statuses` selects which state folders appear in the DISPLAY lists — pass a subset of
    STATUS_DIRS, e.g. {"active"} for only what is moving. Defaults to planned + active, so
    finished work stays out of the way until asked for.

    Every epic is built regardless of the filter. Phase progress needs a true denominator:
    a bar reading "2/3 epics done" must mean the same thing whatever you chose to look at,
    so counting always sees the whole tree and only the listing narrows.

    `include_archived` is the older boolean form, kept so existing callers keep working;
    it is equivalent to adding "archived" to the default set.
    """
    if statuses is None:
        statuses = set(DEFAULT_REPORT_STATUSES)
        if include_archived:
            statuses.add("archived")
    statuses = set(statuses)
    unknown = statuses - set(STATUS_DIRS)
    if unknown:
        raise ValueError(f"unknown status folder(s): {sorted(unknown)} "
                         f"— expected a subset of {list(STATUS_DIRS)}")
    events_index = build_events_index(state_root)
    details, flags = {}, []
    totals = {"epics": {}, "sprints": {}, "stories": {}}
    spend = _new_spend()

    for epic_key, dir_status in list_all_epics(state_root):
        d = build_epic_detail(state_root, epic_key, dir_status, events_index, now)
        details[epic_key] = d
        flags += _collect_flags(d)
        # Spend, like the status counts below, is summed over EVERY epic, not only
        # the visible ones: "what has this project cost" must not change because
        # the caller narrowed the listing to `active`.
        _merge_spend(spend, d["spend"])
        totals["epics"][d["status"]] = totals["epics"].get(d["status"], 0) + 1
        for sp in d["sprints"]:
            totals["sprints"][sp["status"]] = totals["sprints"].get(sp["status"], 0) + 1
        for k, v in d["by_status"].items():
            totals["stories"][k] = totals["stories"].get(k, 0) + v

    def visible(d):
        return d["dir_status"] in statuses

    phases, claimed = [], set()
    for ph in (plan or {}).get("phases") or []:
        members = [str(k) for k in (ph.get("epics") or [])]
        claimed.update(members)
        present = [details[k] for k in members if k in details]
        phases.append({
            "phase": ph.get("phase"), "parallel": bool(ph.get("parallel")),
            "epics": members, "dependencies": list(ph.get("dependencies") or []),
            "epic_total": len(members),
            "epic_done": sum(1 for d in present if d["status"] == "done"),
            "epics_detail": [d for d in present if visible(d)],
        })

    return {
        "generated": _now_iso(),
        "state_root": os.path.abspath(state_root),
        "statuses": sorted(statuses),
        "plan": (plan or {}).get("meta"),
        "phases": phases,
        "unplanned_epics": [d for k, d in sorted(details.items())
                            if k not in claimed and visible(d)],
        "totals": totals,
        "spend": spend,
        "spend_total": _spend_total(spend),
        "flags": flags,
    }


# --------------------------------------------------------------------------- #
# renderers — thin: they consume the model and nothing else
# --------------------------------------------------------------------------- #
def _bar(done: int, total: int, width: int = 10) -> str:
    if total <= 0:
        return "░" * width
    filled = round(width * max(0, min(done, total)) / total)
    return "█" * filled + "░" * (width - filled)


def _dwell_str(node: dict) -> str:
    h = node.get("dwell_hours")
    if h is None:
        return ""
    approx = "" if node.get("dwell_exact") else "~"
    return f"{approx}{h:.1f}h"


def _stuck_suffix(node: dict) -> str:
    return "  ⚠ stuck" if any(f["kind"] == "stuck" for f in node.get("flags") or []) else ""


def _render_epic_tree(d: dict, out: list, indent: str = "  ") -> None:
    done = d["by_status"].get("done", 0)
    out.append(f"{indent}{d['key']} {(d.get('title') or ''):<24} {d['status']:<12} "
               f"{done}/{d['story_count']} stories  {_dwell_str(d)}{_stuck_suffix(d)}")
    if d.get("lock") and d["lock"].get("stale"):
        out.append(f"{indent}  ⚠ STALE LOCK — claimed {d['lock'].get('claimed_at')} "
                   f"(ttl {d['lock'].get('ttl_minutes')}m)")
    for sp in d["sprints"]:
        s_done = sp["by_status"].get("done", 0)
        # Cosmetic wart from the design (§13): a sprint whose stories are ALL
        # blocked reads as "actively being worked" when its status is still
        # in-progress. Surface it in the header, not as a status transition.
        s_blocked = sp["by_status"].get("blocked", 0)
        header_status = sp["status"]
        if s_blocked and s_blocked == sp["story_count"] and sp["story_count"] > 0:
            header_status = f"{sp['status']} (all {s_blocked} stories blocked)"
        out.append(f"{indent}  {sp['key']:<6} {header_status:<20} "
                   f"{s_done}/{sp['story_count']}  {_dwell_str(sp)}{_stuck_suffix(sp)}")
        for st in sp["stories"]:
            if st["status"] == "done":
                continue  # counts above carry finished work; the tree shows what is live
            suffix = ""
            if st["status"] == "blocked":
                reason = st.get("blocked_reason", "")
                suffix = f"  [blocked: {reason}]" if reason else "  [blocked]"
            out.append(f"{indent}    {st['key']:<20} {st['status']:<14} "
                       f"{_dwell_str(st)}{_stuck_suffix(st)}{suffix}")


def _blocked_stories_from_model(model: dict) -> list:
    """Every currently-blocked story in the model, with its reason and location.

    Walks the model's phases + unplanned_epics rather than re-reading the tree
    from disk. Used by both render_tree and render_md so their "Blocked stories"
    sections agree on shape and content. The JSON emitter returns the whole
    model already; callers reading JSON pick the same field paths directly.
    """
    out = []
    for phase in model.get("phases") or []:
        for d in phase.get("epics_detail") or []:
            for sp in d.get("sprints") or []:
                for st in sp.get("stories") or []:
                    if st.get("status") == "blocked":
                        out.append({
                            "epic": d["key"], "sprint": sp["key"],
                            "story": st["key"],
                            "reason": st.get("blocked_reason", "")})
    for d in model.get("unplanned_epics") or []:
        for sp in d.get("sprints") or []:
            for st in sp.get("stories") or []:
                if st.get("status") == "blocked":
                    out.append({
                        "epic": d["key"], "sprint": sp["key"],
                        "story": st["key"],
                        "reason": st.get("blocked_reason", "")})
    return out


def render_tree(model: dict) -> str:
    out: list = []
    plan = model.get("plan")
    if plan:
        out.append(f"PLAN {plan.get('current_plan')}   readiness={plan.get('readiness')}"
                   f"   generated={plan.get('generated')}")
    else:
        out.append("PLAN (none — showing state only)")
    out.append(f"STATE {model['state_root']}")
    # Name the filter whenever it is not the default, so a short list is never mistaken for
    # an empty project. "only" would be a lie when every folder is shown, so word that case
    # differently.
    shown = model.get("statuses") or list(DEFAULT_REPORT_STATUSES)
    if sorted(shown) == sorted(STATUS_DIRS):
        out.append("SHOWING every status, including archived")
    elif sorted(shown) != sorted(DEFAULT_REPORT_STATUSES):
        out.append(f"SHOWING {', '.join(shown)} only "
                   f"(totals and phase counts still cover every epic)")
    out.append("")

    total_phases = len(model["phases"])
    for ph in model["phases"]:
        kind = "parallel" if ph["parallel"] else "sequential"
        out.append(f"Phase {ph['phase']}/{total_phases} ({kind})  "
                   f"{_bar(ph['epic_done'], ph['epic_total'])}  "
                   f"{ph['epic_done']}/{ph['epic_total']} epics done")
        if ph["dependencies"]:
            out.append(f"  depends on: {', '.join(str(x) for x in ph['dependencies'])}")
        if not ph["epics_detail"]:
            out.append("  (all epics in this phase are archived — pass --all to show)")
        for d in ph["epics_detail"]:
            _render_epic_tree(d, out)
        out.append("")

    if model["unplanned_epics"]:
        out.append("Not in any plan phase:" if model["phases"] else "Epics:")
        for d in model["unplanned_epics"]:
            _render_epic_tree(d, out)
        out.append("")

    if not model["phases"] and not model["unplanned_epics"]:
        out.append("No epics found — nothing to report.")
        out.append("")

    out.append("Totals")
    for level in ("epics", "sprints", "stories"):
        counts = model["totals"].get(level) or {}
        body = "  ".join(f"{k}={v}" for k, v in sorted(counts.items())) or "none"
        out.append(f"  {level:<9} {body}")

    spend = model.get("spend") or {}
    if _has_spend(spend):
        out.append("")
        out.append("Spend (actual, by attribution — covers every epic, not just those listed)")
        for bucket in SPEND_BUCKETS:
            out.append(f"  {bucket:<14} {_fmt_actuals(spend.get(bucket) or {})}")
        out.append(f"  {'TOTAL':<14} {_fmt_actuals(model.get('spend_total') or {})}")

    blocked = _blocked_stories_from_model(model)
    if blocked:
        out.append("")
        out.append(f"Blocked stories ({len(blocked)}):")
        for b in blocked:
            where = f"{b['epic']}/{b['sprint']}/"
            reason = b["reason"] or "(no reason recorded)"
            out.append(f"  {where}{b['story']:<20}  {reason}")

    other = [f for f in model["flags"] if f["kind"] != "stuck"]
    if other:
        out.append("")
        out.append("Anomalies")
        for f in other:
            out.append(f"  [{f['kind']}] {f.get('key')} — {f.get('detail', '')}")

    if any(f["kind"] == "stuck" and not f.get("exact") for f in model["flags"]):
        out.append("")
        out.append("~ dwell times are approximate (no event log yet — derived from "
                   "updated_at, which any field write refreshes)")
    # Column padding leaves ragged trailing spaces on rows with no dwell/flag suffix.
    return "\n".join(line.rstrip() for line in out) + "\n"


def render_md(model: dict) -> str:
    plan = model.get("plan")
    out = ["# Progress Report", "",
           (f"Generated by `pm-status.py report` at {model['generated']}. This file is a "
           "view, not a source of truth — do not hand-edit; regenerate it."), ""]
    if plan:
        out.append(f"**Plan:** `{plan.get('current_plan')}` — readiness "
                   f"`{plan.get('readiness')}`, generated {plan.get('generated')}")
    else:
        out.append("**Plan:** none found — state only.")
    out.append("")

    if model["phases"]:
        out += ["## Phases", "", "| Phase | Mode | Epics done | Members |",
                "|---|---|---|---|"]
        for ph in model["phases"]:
            mode = "parallel" if ph["parallel"] else "sequential"
            out.append(f"| {ph['phase']} | {mode} | {ph['epic_done']}/{ph['epic_total']} "
                       f"| {', '.join(ph['epics'])} |")
        out.append("")

    rows = [d for ph in model["phases"] for d in ph["epics_detail"]] + model["unplanned_epics"]
    out += ["## Epics", "", "| Epic | Title | Status | Sprints | Stories done | Dwell |",
            "|---|---|---|---|---|---|"]
    if not rows:
        out.append("| _none_ | | | | | |")
    for d in rows:
        out.append(f"| {d['key']} | {d.get('title') or ''} | {d['status']} "
                   f"| {d['sprint_count']} | {d['by_status'].get('done', 0)}/"
                   f"{d['story_count']} | {_dwell_str(d) or '—'} |")
    out.append("")

    live = [(d, sp, st) for d in rows for sp in d["sprints"] for st in sp["stories"]
            if st["status"] not in ("done", "backlog")]
    if live:
        out += ["## Stories in flight", "",
                "| Story | Epic | Sprint | Status | Dwell | Stuck |",
                "|---|---|---|---|---|---|"]
        for d, sp, st in live:
            stuck = "yes" if any(f["kind"] == "stuck" for f in st["flags"]) else ""
            out.append(f"| {st['key']} | {d['key']} | {sp['key']} | {st['status']} "
                       f"| {_dwell_str(st) or '—'} | {stuck} |")
        out.append("")

    out += ["## Totals", "", "| Level | Counts |", "|---|---|"]
    for level in ("epics", "sprints", "stories"):
        counts = model["totals"].get(level) or {}
        body = ", ".join(f"{k}={v}" for k, v in sorted(counts.items())) or "none"
        out.append(f"| {level} | {body} |")
    out.append("")

    blocked = _blocked_stories_from_model(model)
    if blocked:
        out += [f"## Blocked stories ({len(blocked)})", "",
                "| Story | Epic | Sprint | Reason |", "|---|---|---|---|"]
        for b in blocked:
            reason = b["reason"] or "(no reason recorded)"
            out.append(f"| {b['story']} | {b['epic']} | {b['sprint']} | {reason} |")
        out.append("")

    spend = model.get("spend") or {}
    if _has_spend(spend):
        out += ["## Spend", "",
                ("Actual spend by attribution, over every epic in the tree (not only the "
                "epics listed above). `stories` is the sum of the leaf actuals, `closure` "
                "each level's own closure-phase residual, `orchestration` the separate "
                "orchestration block."), "",
                "| Attribution | " + " | ".join(METRIC_FIELDS) + " |",
                "|---|" + "---|" * len(METRIC_FIELDS)]
        rows = [(b, spend.get(b) or {}) for b in SPEND_BUCKETS]
        rows.append(("**total**", model.get("spend_total") or {}))
        for label, vals in rows:
            cells = " | ".join(str(_norm_spend(vals.get(m))) for m in METRIC_FIELDS)
            out.append(f"| {label} | {cells} |")
        out.append("")
    return "\n".join(out) + "\n"


# --------------------------------------------------------------------------- #
# subcommands
# --------------------------------------------------------------------------- #
def _resolve_story_items(state_root, node, story_key, session) -> None:
    """After a story reaches `done`, resolve every key in its `resolves:` as fixed.

    ADR-0003: this never fails set-status. The status save already happened and is
    durable; reporting it as failed would invite a retry or a rollback of finished
    work. Every exception except KeyboardInterrupt -- SystemExit included -- becomes
    a warning, and audit-issues finding 1c catches what was missed. `resolves:` itself
    is hand-editable YAML, so normalising it (a bare scalar counts as one key; anything
    else is a malformed-field warning) happens INSIDE the catch-all too -- a bad shape
    there must warn, never raise out of set-status."""
    raw = node.get("resolves")
    if not raw:
        return
    try:
        if isinstance(raw, str):
            keys = [raw]
        elif isinstance(raw, (list, tuple)):
            keys = [str(k) for k in raw]
        else:
            sys.stderr.write(f"pm-status.py: warning -- {story_key} has a malformed resolves: "
                             f"({raw!r}); nothing resolved. Run /l3io-doctor triage.\n")
            return
        open_path = issues_paths(state_root)[0]
        with issues_lock(open_path):
            store = IssueStore(open_path)
            for k in keys:
                try:
                    kc = canonical_bl_key(k)
                    was_resolved = bool(kc and store.resolved_items(kc))
                    msg = resolve_issue_core(store, k, "fixed", story_key, None,
                                             session, "set-status")
                    # `resolved BL-...` is the spec §2.6 output contract for a NEW
                    # resolution only; a key resolved before (a repeat done) gets `ok`.
                    sys.stdout.write(f"{'ok' if was_resolved else 'resolved'} {msg}\n")
                except PMError as e:
                    sys.stderr.write(f"pm-status.py: warning -- could not resolve {k} "
                                     f"for {story_key}: {e.msg} -- run /l3io-doctor "
                                     f"triage\n")
    except KeyboardInterrupt:
        raise
    except BaseException as e:  # noqa: BLE001 -- deliberate, ADR-0003
        sys.stderr.write(f"pm-status.py: warning -- done hook failed for {story_key}: "
                         f"{e!r}; the status write stands. Run /l3io-doctor triage "
                         f"(audit-issues finding 1c) to finish it.\n")


def cmd_set_status(args) -> int:
    kind = _infer_kind(args)
    valid = {"story": VALID_STORY_STATUS, "sprint": VALID_SPRINT_STATUS, "epic": VALID_EPIC_STATUS}[kind]
    if args.status not in valid:
        _die_usage(f"invalid {kind} status '{args.status}' — expected one of {sorted(valid)}")

    # blocked-lifecycle argument guards (story only -- sprint/epic keep no --reason/--resolution).
    reason = str(getattr(args, "reason", "") or "").strip()
    resolution = str(getattr(args, "resolution", "") or "").strip()
    if kind == "story" and args.status == "blocked" and not reason:
        _die_usage("--status blocked requires --reason \"<why>\" -- a blocked story with no reason "
                   "on record is what this flag exists to prevent")
    if kind != "story" and (reason or resolution):
        _die_usage("--reason and --resolution are story-only flags; sprints and epics compose "
                   "from their children")
    if kind == "story" and args.status != "blocked" and reason:
        _die_usage("--reason is only valid with --status blocked; other transitions have no "
                   "reason field to record")

    # An epic node is written under its epic_node_lock. The event append inside is a leaf
    # lock, and the done hook below (issues_lock) runs only for a story, outside any hold.
    with _epic_write_lock(args, kind):
        y, node, path, label = _load_checked(args.state_root, args, kind)
        prior = str(node.get("status", "")) or None

        # Story transitions are per-pair, not per-target. See VALID_STORY_TRANSITIONS.
        if kind == "story" and prior is not None:
            allowed = VALID_STORY_TRANSITIONS.get(prior, set())
            if args.status not in allowed:
                _die_usage(
                    f"invalid story transition {prior!r} -> {args.status!r}; from {prior!r} "
                    f"allowed: {sorted(allowed) or ['(terminal)']}")
            # blocked -> done is the one transition that requires --resolution: the story
            # resolved by the same event that unblocked it (e.g. spec change removed the need).
            if prior == "blocked" and args.status == "done" and not resolution:
                _die_usage("blocked -> done requires --resolution \"<why the story is done "
                           "rather than resumed>\"; use --status in-progress to resume")

        node["status"] = args.status
        node["updated_at"] = _now_iso()
        if args.title:
            node["title"] = args.title
        if kind == "story":
            leaving_blocked = prior == "blocked" and args.status != "blocked"
            entering_blocked = args.status == "blocked" and prior != "blocked"
            if args.status == "blocked":
                node["blocked_reason"] = reason
            elif leaving_blocked and "blocked_reason" in node:
                # Current node reflects only current state; block history lives in the log.
                del node["blocked_reason"]
            if entering_blocked:
                # completion_evidence.blocks_seen: O(1) counter for closure-side
                # observability. Not used for cohort routing -- see §5 of the design.
                # Not decremented on exit (this counts events, not current state).
                from ruamel.yaml.comments import CommentedMap
                ce = node.get("completion_evidence")
                if not isinstance(ce, dict):
                    ce = CommentedMap()
                    node["completion_evidence"] = ce
                ce["blocks_seen"] = int(ce.get("blocks_seen", 0) or 0) + 1
        else:
            leaving_blocked = entering_blocked = False
        save_node(y, node, path, getattr(args, "flock", False))

        if not getattr(args, "no_events", False):
            payload = {"ts": _now_iso(), "event": "status",
                       "from": prior, "to": args.status,
                       "session": getattr(args, "session_id", None)}
            payload.update(_event_keys(kind, args))
            append_event(args.state_root, payload)
            if entering_blocked:
                bp = {"ts": _now_iso(), "event": "block_open",
                      "story": args.story, "reason": reason,
                      "session": getattr(args, "session_id", None)}
                append_event(args.state_root, bp)
            if leaving_blocked:
                dur = _block_duration_since_last_open(args.state_root, args.story)
                bc = {"ts": _now_iso(), "event": "block_close",
                      "story": args.story, "duration_hours": dur,
                      "session": getattr(args, "session_id", None)}
                if args.status == "done":
                    bc["resolution"] = resolution
                append_event(args.state_root, bc)

    sys.stdout.write(f"OK set-status {label} -> {args.status}\n")
    if kind == "story" and args.status == "done":
        _resolve_story_items(args.state_root, node, args.story,
                             getattr(args, "session_id", None))
    return 0


def _total_blocked_hours(state_root: str, story_key: str) -> float:
    """Sum `duration_hours` across every closed block for this story SINCE its
    most recent `dispatch_open`.

    A story with any nonzero blocked time in the current dispatch cycle cannot
    produce an `elapsed_hours` calibration sample -- wall-clock during blocked
    time includes human wait, which would poison the scope ratio for future
    stories. The exclusion is per-metric, not per-sample: other metrics stay
    recorded.

    Scoping to the most recent dispatch cycle avoids the multi-session
    over-exclusion the design's §5 amendment named: a story blocked in Session 1
    and completed cleanly in Session 2 must not get Session 2's `elapsed_hours`
    excluded because of Session 1's blocks. Index-based (not timestamp-based)
    boundary because events.jsonl is append-only and its order reflects
    chronology reliably even under clock skew.

    Fallback: when the story has no `dispatch_open` on record -- either because
    the log was truncated, or because the story predates dispatch bracketing --
    the scan reverts to counting all `block_close` events. That preserves the
    safety-first bias for stories where the dispatch bracket isn't available.

    Returns 0.0 on a missing log, an empty story key, or an unreadable line
    within the log -- lenient enough that a torn write does not silently fail
    the calibration write path this feeds.
    """
    if not story_key:
        return 0.0
    p = events_path(state_root)
    if not os.path.exists(p):
        return 0.0
    try:
        with open(p, encoding="utf-8") as fh:
            lines = fh.readlines()
    except OSError:
        return 0.0
    parsed = []      # (line_index, event, story, duration_hours-or-None)
    for i, line in enumerate(lines):
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        story = rec.get("story")
        if story != story_key:
            continue
        ev = rec.get("event")
        if ev not in ("dispatch_open", "block_close"):
            continue
        parsed.append((i, ev, rec.get("duration_hours")))
    if not parsed:
        return 0.0
    # Find the LATEST dispatch_open index for this story; sum block_close
    # durations after it. If there is no dispatch_open at all, sum everything
    # (safety-first fallback for stories that predate dispatch bracketing).
    last_open_idx = -1
    for i, ev, _ in parsed:
        if ev == "dispatch_open":
            last_open_idx = i
    total = 0.0
    for i, ev, d in parsed:
        if ev != "block_close":
            continue
        if last_open_idx >= 0 and i < last_open_idx:
            continue
        if isinstance(d, (int, float)):
            total += float(d)
    return round(total, 3)


def _block_duration_since_last_open(state_root: str, story_key: str):
    """Hours since the most recent block_open event for `story_key`.

    Returns None when no block_open is found on the story (a caller-side bug the WARN
    downstream can surface without crashing). Reads the events log from the end.
    """
    p = events_path(state_root)
    if not os.path.exists(p):
        return None
    try:
        with open(p, encoding="utf-8") as fh:
            lines = fh.readlines()
    except OSError:
        return None
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if rec.get("event") == "block_open" and rec.get("story") == story_key:
            opened = _parse_iso(rec.get("ts"))
            if opened is None:
                return None
            now = _parse_iso(_now_iso())
            if now is None:
                return None
            delta = (now - opened).total_seconds() / 3600.0
            return round(delta, 3)
    return None


EPIC_KEY_RE = re.compile(r"^E\d{3}$")
STORY_KEY_RE = re.compile(r"^E\d{3}-S\d{2}-\d{3}$")
# status-files.md §11: `depends_on` lives on BOTH an epic node (epic keys) and a story node
# (story keys). Reading only that section's first sentence gives the epic case and silently
# loses the story case, which is the shape the migration fixtures actually carry.
DEPENDS_ON_KEY_RE = {"epic": EPIC_KEY_RE, "story": STORY_KEY_RE}


def cmd_set_depends_on(args) -> int:
    """Append epic keys to an epic's `depends_on` list.

    `depends_on` is epic-only and list-shaped (status-files.md §11). `set-field --value` takes a
    single string, so routing a list through it would store "['E001']" as a scalar -- worse than
    not writing it at all, because a later reader takes it for one. That is exactly why the
    migration engine WARNed and skipped this field rather than flattening it.

    All-or-nothing: every key is validated before anything is written, because a half-applied
    dependency list is a worse artefact than an absent one -- l3io-plan topologically sorts
    on it, so a missing edge silently reorders a phase.
    """
    from ruamel.yaml.comments import CommentedSeq
    from ruamel.yaml.scalarstring import SingleQuotedScalarString as SQ

    kind = _infer_kind(args)
    if kind not in DEPENDS_ON_KEY_RE:
        _die_usage(f"depends_on lives on an epic or a story node, not a {kind} "
                   f"(status-files.md §11)")
    key_re = DEPENDS_ON_KEY_RE[kind]
    self_key = args.epic if kind == "epic" else args.story

    keys = list(args.add or [])
    if not keys:
        _die_usage("set-depends-on needs at least one --add KEY")
    for k in keys:
        if not key_re.match(k):
            _die_usage(f"--add {k!r} is not a {kind} key (expected {key_re.pattern}); "
                       f"nothing written")
        if k == self_key:
            _die_usage(f"--add {k!r} is the node itself -- it cannot depend on itself; "
                       f"nothing written")

    with _epic_write_lock(args, kind):
        y, node, path, label = _load_checked(args.state_root, args, kind)
        existing = node.get("depends_on")
        if not isinstance(existing, list):
            existing = CommentedSeq()
            node["depends_on"] = existing
        added = []
        for k in keys:
            if str(k) not in [str(e) for e in existing]:
                existing.append(SQ(k))
                added.append(k)
        node["updated_at"] = _now_iso()
        save_node(y, node, path, getattr(args, "flock", False))

    sys.stdout.write(f"OK set-depends-on {label} += {added or '(nothing new)'}\n")
    return 0


def cmd_import_node(args) -> int:

    """Create a state node from a migration record. The counterpart to set-status for a
    node that does not exist yet.

    This is cmd_set_status with ONE step swapped -- ensure_node_path() where set-status
    calls _load_checked() -- because _load_checked exits 3 on a missing node, which is
    correct for set-status and fatal for this verb. set-status itself is untouched: it
    must never create anything.

    Idempotent by SKIP, not by overwrite. A migration retried after a partial run must
    not clobber a node a later step already edited, so an existing file is left exactly
    as it is and reported.
    """
    from ruamel.yaml.scalarstring import SingleQuotedScalarString as SQ

    kind = _infer_kind(args)
    valid = {
        "story": VALID_STORY_STATUS,
        "sprint": VALID_SPRINT_STATUS,
        "epic": VALID_EPIC_STATUS,
    }[kind]
    if args.status not in valid:
        _die_usage(
            f"invalid {kind} status '{args.status}' -- expected one of {sorted(valid)}")

    # blocked_reason gate: a story imported at `status: blocked` must carry a --reason
    # the same way set-status does. Migration sources that carry blocked state (bmad-loop
    # is the shape) preserve the reason on the record; a source that reports blocked but
    # cannot preserve the reason is a broken source, not an acceptable import shape.
    # Sprints and epics don't have `blocked` in their status enum, so the guard is
    # story-only by construction.
    reason = str(getattr(args, "reason", "") or "").strip()
    if kind == "story" and args.status == "blocked" and not reason:
        _die_usage("--status blocked requires --reason \"<why>\" -- a blocked story with no "
                   "reason on record is what this flag exists to prevent")
    if kind != "story" and reason:
        _die_usage("--reason is a story-only flag; sprint/epic status sets have no blocked")
    if kind == "story" and args.status != "blocked" and reason:
        _die_usage("--reason is only valid with --status blocked")

    with _epic_write_lock(args, kind, require_exists=False):
        path, label = ensure_node_path(args.state_root, args, kind, args.status)
        if os.path.exists(path):
            sys.stdout.write(f"SKIP import-node {label} -- already exists\n")
            return 0

        node = {}
        if kind == "epic":
            node["key"] = SQ(args.epic)
            node["title"] = args.title or ""
            node["goal"] = ""
        elif kind == "sprint":
            node["key"] = SQ(args.sprint)
            node["epic"] = SQ(args.epic)
            node["title"] = args.title or ""
        else:
            epic_key, sprint_key, _ = parse_story_key(args.story)
            node["key"] = SQ(args.story)
            node["epic"] = SQ(epic_key)
            node["sprint"] = SQ(sprint_key)
            node["title"] = args.title or ""
            node["classification"] = args.classification or "unknown"

        node["status"] = args.status
        node["updated_at"] = _now_iso()
        if args.origin:
            node["origin"] = args.origin
            node["origin_note"] = args.origin_note or ""
        if kind == "story" and args.status == "blocked":
            node["blocked_reason"] = reason
            # completion_evidence.blocks_seen is a counter of OUR events, not the
            # source's history -- import-node predates our history for a migrated node,
            # so the counter starts at 0. A subsequent set-status --status blocked would
            # bump it. Not adding it here.

        save_node(_yaml(), node, path, getattr(args, "flock", False))

        if not getattr(args, "no_events", False):
            payload = {
                "ts": _now_iso(), "event": "import", "from": None, "to": args.status,
                "session": getattr(args, "session_id", None),
            }
            payload.update(_event_keys(kind, args))
            append_event(args.state_root, payload)
            # For a story imported at blocked, emit a paired block_open so a future
            # set-status transitioning off blocked can derive duration the same way
            # a set-status-created block does. Without this, _block_duration_since_
            # last_open would return None and block_close would land without duration.
            if kind == "story" and args.status == "blocked":
                bp = {"ts": _now_iso(), "event": "block_open",
                      "story": args.story, "reason": reason,
                      "session": getattr(args, "session_id", None)}
                append_event(args.state_root, bp)

    sys.stdout.write(f"OK import-node {label} -> {args.status}\n")
    return 0


def story_doc_path(artifacts_root: str, story_key: str) -> str:
    """E{nnn}-S{nn}-{nnn} -> {artifacts}/epic-{nnn}/sprint-{nn}/stories/{key}.md

    The artifact tree mirrors the state tree with an identical path suffix but is
    NOT the state tree: artifacts are human-authored and never moved between
    status directories. This is the only place that resolves a story key to a
    document path, for the same reason story_file() is the only place that
    resolves one to a state path.
    """
    m = re.match(r"^E(\d{3})-S(\d{2})-\d{3}$", story_key)
    if not m:
        raise ValueError(f"not a story key: {story_key!r}")
    return os.path.join(artifacts_root, f"epic-{m.group(1)}",
                        f"sprint-{m.group(2)}", "stories", f"{story_key}.md")


def cmd_sync_story_doc(args) -> int:
    """Write `status:` into the story markdown's frontmatter.

    The state YAML is the machine's truth; this file is the human's. They have
    never agreed -- a production audit found 73 of 73 stories divergent, every
    one of them in the same direction, which is an unimplemented write rather
    than drift.

    This NEVER fails its caller. It runs after a set-status that has already
    succeeded, and a documentation write must not be able to strand a state
    transition that is already durable.
    """
    if args.status not in VALID_STORY_STATUS:
        sys.stderr.write(f"ERROR unknown story status {args.status!r}; "
                         f"expected one of {', '.join(sorted(VALID_STORY_STATUS))}\n")
        return 2
    try:
        path = story_doc_path(args.artifacts_root, args.story)
    except ValueError as exc:
        sys.stderr.write(f"ERROR {exc}\n")
        return 2
    if not os.path.exists(path):
        sys.stderr.write(f"WARN no story file at {path} — state was written, "
                         f"document not updated\n")
        return 0

    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    if not text.startswith("---\n"):
        sys.stderr.write(f"WARN {path} has no YAML frontmatter — nothing to update\n")
        return 0
    end = text.find("\n---", 3)
    if end == -1:
        sys.stderr.write(f"WARN {path} has an unterminated frontmatter block\n")
        return 0
    head, body = text[4:end + 1], text[end + 4:]

    # ruamel round-trip: preserves key order and comments. Never split on '---'
    # by hand -- a body line of dashes is legal markdown and would corrupt it.
    from ruamel.yaml.comments import CommentedMap
    yaml = _yaml()
    try:
        meta = yaml.load(head)
    except Exception:                                    # noqa: BLE001
        # Deliberately broad. This runs after a set-status that already
        # succeeded, and no parse failure is worth stranding a durable state
        # transition over. The warning is the signal; the exit code is not.
        sys.stderr.write(f"WARN {path} frontmatter does not parse as YAML — "
                         f"state was written, document not updated\n")
        return 0
    if meta is None:
        meta = CommentedMap()
    if not hasattr(meta, "get"):
        sys.stderr.write(f"WARN {path} frontmatter is not a mapping — "
                         f"state was written, document not updated\n")
        return 0
    if meta.get("status") == args.status:
        if not args.quiet:
            sys.stdout.write(f"OK {args.story} document already {args.status}\n")
        return 0
    meta["status"] = args.status
    buf = io.StringIO()
    yaml.dump(meta, buf)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("---\n" + buf.getvalue() + "---" + body)
    if not args.quiet:
        sys.stdout.write(f"OK {args.story} document -> {args.status}\n")
    return 0


def init_story_doc(state_root, artifacts_root, story_key, context_md="", ac_lines=None,
                   must_not_exist=False) -> str:
    """Create a story document's skeleton from its state node -- the only writer of
    that skeleton (story prep and promote-issue both call it). Returns 'created' or
    'exists'. Raises PMError: 2 for a bad key or, under must_not_exist, an existing
    document; 3 for a missing state node."""
    from ruamel.yaml.comments import CommentedMap
    from ruamel.yaml.scalarstring import SingleQuotedScalarString as SQ
    try:
        doc = story_doc_path(artifacts_root, story_key)
    except ValueError as e:
        raise PMError(2, str(e))
    path = story_file(state_root, story_key)
    if path is None:
        raise PMError(3, f"story {story_key}")
    _, node = load_node(path)
    if node is None:
        raise PMError(3, f"story {story_key} — file is empty")
    title = str(node.get("title") or story_key)
    meta = CommentedMap()
    meta["key"] = SQ(story_key)
    meta["title"] = SQ(title)
    meta["status"] = str(node.get("status") or "backlog")
    meta["classification"] = str(node.get("classification") or "standard")
    buf = io.StringIO()
    _yaml().dump(meta, buf)
    parts = ["---\n", buf.getvalue(), "---\n\n", f"# {title}\n\n"]
    if context_md:
        parts.append(context_md.rstrip("\n") + "\n\n")
    parts.append("## Acceptance Criteria\n\n")
    if ac_lines:
        parts.extend(f"- {line}\n" for line in ac_lines)
    else:
        parts.append("<!-- Technical ACs to be added below -->\n")
    if not _atomic_create(doc, "".join(parts)):
        if must_not_exist:
            raise PMError(2, f"story document {doc} already exists -- refusing to adopt it")
        return "exists"
    return "created"


def cmd_story_doc_init(args) -> int:
    def run():
        result = init_story_doc(args.state_root, args.artifacts_root, args.story)
        sys.stdout.write(f"OK story-doc-init {args.story} {result} -> "
                         f"{story_doc_path(args.artifacts_root, args.story)}\n")
        return 0
    return _run_core(run)


def cmd_import_actual(args) -> int:
    """set-actual with the migration contract baked into defaults that cannot be overridden.

    A migrated actual needs three things, each easy to forget and dangerous to forget:

      runtime = other   it has no Claude provenance to claim
      tokens  = N/A     legacy data carries no four-class split, and 0 would be consumed by
                        calibration as a real measurement, dragging the learned ratio to zero
      no calibration    a bulk import must not append hundreds of samples in one pass;
                        `calibration redrive` rebuilds from the nodes afterwards if wanted

    set-actual can express all three -- that is why this verb delegates rather than
    reimplements, and why set-actual is left exactly as it is. What it cannot do is stop a
    caller omitting one: forget --tokens-na under runtime=claude and you get a refusal, but
    forget --no-calibrate and the ratios are quietly poisoned with unmeasured data. This verb
    removes that choice. --runtime, --tokens-*, --model and --calibrate are not in its surface
    at all, so a wrong call is a usage error rather than a silent one.
    """
    args.runtime = "other"
    args.tokens_na = True
    args.no_calibrate = True
    args.block = "actual"
    args.model = ""
    args.token_rates = ""
    args.cost = None
    for f in ("tokens_input", "tokens_output", "tokens_cache_write", "tokens_cache_read"):
        setattr(args, f, None)
    return cmd_set_actual(args)


def cmd_set_actual(args) -> int:

    kind = args.node
    block = getattr(args, "block", "actual")
    if block == "orchestration" and kind == "story":
        _die_usage("--block orchestration is only valid on a sprint or epic — a story's "
                   "orchestration belongs to its parent sprint")
    if args.cost is not None:   # a usage error on any node: refused before the epic lock
        _die_usage("--cost is not accepted: cost is derived from tokens x rates. "
                   "Fix the token counts or modules.l3io-pm.token_rates instead.")
    # Both the node save and, for a sprint or epic, the calibration sample's replay marker
    # (_mark_sampled) write the node, so an epic's whole cycle runs under its lock. Lock
    # order: epic_node_lock, then calibration_lock inside the record_* helpers.
    with _epic_write_lock(args, kind):
        return _set_actual(args, kind, block)


def _set_actual(args, kind, block) -> int:
    """cmd_set_actual's body; the caller holds the epic lock for an epic node."""
    y, node, path, label = _load_checked(args.state_root, args, kind)

    provided = {
        "elapsed_hours": args.elapsed_hours,
        "man_hours": args.man_hours,
        "hitl_hours": args.hitl_hours,
    }

    classes = {c: getattr(args, "tokens_" + c) for c in TOKEN_CLASSES}
    given = {c: v for c, v in classes.items() if v is not None}
    if args.tokens_na and given:
        _die_usage("--tokens-na cannot be combined with explicit token counts")
    if args.tokens_na:
        if args.runtime == "claude":
            _die_usage("runtime=claude forbids tokens=N/A — capture the exact per-class "
                       "counts from the session transcript (see metrics-contract.md §3)")
        elif args.runtime == "codex":
            _die_usage("runtime=codex forbids tokens=N/A — capture input_tokens, "
                       "output_tokens+reasoning_output_tokens, and cached_input_tokens "
                       "from rollout-*.jsonl token_count events "
                       "(see metrics-contract.md §3)")
        elif args.runtime == "copilot":
            _die_usage("runtime=copilot forbids tokens=N/A — pass --tokens-input "
                       "(prompt_tokens) and --tokens-output (completion_tokens) summed "
                       "across the node's dispatch window (see metrics-contract.md §3)")
        provided["tokens_k"] = "N/A"
        provided["cost"] = "N/A"
    elif args.runtime == "copilot":
        # Copilot exposes prompt_tokens (input) and completion_tokens (output) only.
        # No cache class split is accessible to the agent, so cost cannot be accurately
        # priced — store the total as a scalar and cost as N/A.
        inp = _num_or_none(args.tokens_input)
        out_t = _num_or_none(args.tokens_output)
        if inp is None or out_t is None:
            _die_usage(
                "runtime=copilot requires --tokens-input (prompt_tokens) and "
                "--tokens-output (completion_tokens) — read these from each API "
                "response's usage object and sum across the node's dispatch window "
                "(see metrics-contract.md §3). --tokens-na is forbidden.")
        total = inp + out_t
        provided["tokens_k"] = int(total) if float(total).is_integer() else round(total, 2)
        provided["cost"] = "N/A"  # no class split → cannot price accurately
    elif given:
        # Under runtime=claude an incomplete class set is a usage error, not a
        # zero-fill. `tokens_block` defaults an omitted class to 0, `total` sums
        # to the classes that were passed, `cost` derives from those, and
        # `verify` then confirms all three agree with each other — internally
        # consistent and therefore unfalsifiable. One forgotten flag understates
        # a node by an order of magnitude: cache classes dominate real runs
        # (99.8% cache_creation on the motivating run), so an omitted
        # --tokens-cache-write is not a rounding error. An explicit 0 stays
        # valid — the requirement is that the capturer looked at all four, not
        # that all four are nonzero. runtime=other stays permissive: a runtime
        # that exposes only some classes is exactly what --runtime other is for.
        if args.runtime == "claude" and len(given) < len(TOKEN_CLASSES):
            missing = [c for c in TOKEN_CLASSES if c not in given]
            _die_usage(
                "runtime=claude requires all four token classes when any is given — "
                f"missing: {', '.join('--tokens-' + m.replace('_', '-') for m in missing)}. "
                "Read input_tokens, output_tokens, cache_creation_input_tokens and "
                "cache_read_input_tokens from the session transcript's usage fields "
                "(metrics-contract.md §3); pass an explicit 0 for a class that really "
                "is zero.")
        if args.runtime == "codex":
            required_cx = ("input", "output", "cache_read")
            missing_cx = [c for c in required_cx if c not in given]
            if missing_cx:
                _die_usage(
                    "runtime=codex requires --tokens-input, --tokens-output, and "
                    "--tokens-cache-read (read from rollout-*.jsonl token_count events — "
                    "see metrics-contract.md §3). Missing: "
                    + ", ".join("--tokens-" + m.replace("_", "-") for m in missing_cx)
                    + ". Note: --tokens-cache-write defaults to 0 (Codex CLI drops "
                    "cache_write_tokens; see github.com/openai/codex/issues/32479).")
            if "cache_write" not in given:
                given["cache_write"] = "0"
        if not args.model:
            _die_usage("--model is required whenever token counts are given — the same "
                       "token count prices 2x apart between a $5/M and a $10/M tier")
        try:
            cost = cost_from_tokens(given, args.model, rate_overrides(args))
        except KeyError as e:
            # e.args[0], not str(e) — KeyError.__str__ repr-quotes its argument,
            # which would double-wrap a message that already reads as prose.
            _die_usage(e.args[0])
        provided["tokens_k"] = tokens_block(given)
        provided["cost"] = cost
        provided["model"] = args.model

    provided = {k: v for k, v in provided.items() if v is not None}
    if not provided:
        _die_usage("set-actual needs at least one of --elapsed-hours/--man-hours/"
                   "--hitl-hours/--tokens-* /--tokens-na")

    block_data = node.get(block)
    if block_data is None:
        from ruamel.yaml.comments import CommentedMap

        block_data = CommentedMap()
        node[block] = block_data
    for k, v in provided.items():
        block_data[k] = v if not isinstance(v, str) else _coerce(k, v)

    save_node(y, node, path, getattr(args, "flock", False))

    calib_note = ""
    if not getattr(args, "no_calibrate", False):
        # Calibration is DERIVED data. A failure here must never fail the
        # actuals write, which is the primary record — but it must be visible,
        # not silent.
        try:
            if block == "orchestration":
                # kind is "sprint" or "epic" here — a story was already rejected above.
                calib_note = record_orchestration_sample(
                    args.state_root, kind, args.epic, args.sprint if kind == "sprint" else None)
            elif kind == "story":
                # path + y so the sample can stamp its replay marker on the node
                calib_note = record_story_sample(args.state_root, node, path, y)
            elif kind == "sprint":
                calib_note = record_closure_sample(args.state_root, "sprint",
                                                   args.epic, args.sprint)
            elif kind == "epic":
                calib_note = record_closure_sample(args.state_root, "epic", args.epic)
        except Exception as e:                      # noqa: BLE001 - deliberate isolation
            sys.stderr.write(f"pm-status.py: warning — actual written, but calibration "
                             f"sample failed: {e}\n")
            calib_note = "calibration skipped (see stderr)"

    if not getattr(args, "no_events", False):
        payload = {"ts": _now_iso(), "event": "actual",
                   "from": None, "to": None,
                   "session": getattr(args, "session_id", None)}
        payload.update(_event_keys(kind, args))
        append_event(args.state_root, payload)

    suffix = f" [{calib_note}]" if calib_note else ""
    est_model = (node.get("estimate") or {}).get("model")
    act_model = provided.get("model")
    if est_model and act_model and est_model != act_model:
        suffix += (f" [model mismatch: estimated at {est_model!r},"
                   f" executed at {act_model!r} — costs not comparable]")
    sys.stdout.write(f"OK set-actual {label} {sorted(provided)}{suffix}\n")
    return 0


def _parse_version_line(path: str):
    """Read the `# pm-status-version: X.Y.Z` marker from a copy on disk; None if absent."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            for _ in range(80):  # marker is at the top (just under the PEP-723 header)
                line = f.readline()
                if not line:
                    break
                if "pm-status-version:" in line:
                    token = line.split("pm-status-version:")[1].strip().split()[0]  # first token only
                    return tuple(int(x) for x in token.split("."))
    except (OSError, ValueError):
        return None
    return None


def _file_sha(path: str):
    """SHA-256 of a file's bytes; None if it cannot be read."""
    try:
        with open(path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    except OSError:
        return None


CLAUDE_SESSION_ENV = "CLAUDE_CODE_SESSION_ID"


def resolve_session_transcript(session_id: str = "") -> tuple:
    """(paths, session_id) for a Claude session's own transcript. ([], id) if not found.

    A session transcript is named `<session-id>.jsonl` under
    `~/.claude/projects/<slugified-cwd>/`, and every record inside carries the same
    `sessionId`. The id itself is in the environment as CLAUDE_CODE_SESSION_ID. So a
    session can identify its own transcript exactly, and does not have to be told.

    Searched across every project directory rather than only the slug for the current
    cwd: a subagent may run with a different working directory than the session that
    spawned it, and guessing the slug would reintroduce exactly the ambiguity this
    function exists to remove.
    """
    session_id = session_id or os.environ.get(CLAUDE_SESSION_ENV, "")
    if not session_id:
        return [], ""
    root = os.path.expanduser("~/.claude/projects")
    if not os.path.isdir(root):
        return [], session_id
    hits = []
    for d in sorted(os.listdir(root)):
        fp = os.path.join(root, d, f"{session_id}.jsonl")
        if os.path.exists(fp):
            hits.append(fp)
        # Subagent turns are NOT in the parent file -- no record anywhere carries
        # isSidechain in the main transcript. They live in a sibling directory named
        # for the session, and they carry the SAME sessionId, so identity still
        # verifies. Resolving only the .jsonl reported sidechain=0 and silently
        # omitted every dispatched agent's spend.
        sub = os.path.join(root, d, session_id, "subagents")
        if os.path.isdir(sub):
            hits.extend(os.path.join(sub, n) for n in sorted(os.listdir(sub))
                        if n.endswith(".jsonl"))
    return hits, session_id


def transcript_sessions(path: str) -> set:
    """The distinct `sessionId` values in a .jsonl file. Empty set if it carries none."""
    out = set()
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                if isinstance(rec, dict) and rec.get("sessionId"):
                    out.add(str(rec["sessionId"]))
    except OSError:
        return set()
    return out


def read_transcript_usage(paths, since=None, until=None) -> dict:
    """Sum a session transcript's real token usage, by class. THE executable form of
    "read the usage fields".

    That instruction was not executable, and an agent asked to follow it by hand hit
    every trap below at once. Two of them inflate and one deflates, so the wrong answer
    came out plausible rather than obviously broken: the errors partly cancel.
    Each is handled here, and each is a property of the real file format, verified
    against a 2,482-record transcript rather than assumed:

    1. INFLATES -- **the same API call appears many times.** Assistant records are
       written repeatedly as a message streams and is revised, carrying an identical
       `message.id` and identical `usage` each time. The sample held 2,482 assistant
       records for 953 distinct ids: summing records rather than ids overstates by
       roughly 2.6x. Deduplicated here by `message.id`, keeping the first occurrence.

    2. INFLATES -- **cache creation is reported twice, two ways.** `usage` carries both
       the flat `cache_creation_input_tokens` and a nested `cache_creation` mapping of
       `ephemeral_5m/1h` counts. They are the same tokens: the nested values summed
       equalled the flat field in 2,482 of 2,482 records. Adding both double-counts the
       most expensive class. Only the flat field is read.

    3. DEFLATES -- **subagent turns are easy to miss.** Work dispatched to a subagent is
       recorded with `isSidechain: true`, and often in a different file entirely. Reading
       one file, or filtering sidechains out, silently drops whole phases -- which is the
       deflating half that made the net error look small. Sidechain records are counted,
       and `paths` accepts directories so a run split across files is summed whole.

    Returns the four class totals plus counts that let a caller sanity-check the read.
    """
    files = []
    for entry in (paths if isinstance(paths, (list, tuple)) else [paths]):
        if os.path.isdir(entry):
            for root, _dirs, names in os.walk(entry):
                files.extend(os.path.join(root, n) for n in sorted(names)
                             if n.endswith(".jsonl"))
        elif os.path.exists(entry):
            files.append(entry)

    totals = {c: 0 for c in TOKEN_CLASSES}
    seen, records, sidechain, outside, undated = set(), 0, 0, 0, 0
    for fp in files:
        try:
            fh = open(fp, "r", encoding="utf-8")  # noqa: SIM115 -- catch OSError on open, then `with fh:` below
        except OSError as e:
            sys.stderr.write(f"pm-status.py: warning — cannot read {fp}: {e}\n")
            continue
        with fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue          # torn or partial line; the log is appended to live
                if not isinstance(rec, dict) or rec.get("type") != "assistant":
                    continue
                msg = rec.get("message")
                if not isinstance(msg, dict):
                    continue
                usage = msg.get("usage")
                if not isinstance(usage, dict):
                    continue
                # Trap 1: one id, one contribution. Fall back to identity when a record
                # carries no id, so an unidentifiable turn is counted rather than dropped
                # -- erring toward the inflating side is safe here, silently losing a
                # turn is not.
                key = msg.get("id") or f"{fp}:{records}"
                records += 1
                if key in seen:
                    continue
                seen.add(key)
                # A session transcript spans everything that session ever did. One
                # observed file covered a whole epic lineage: its bare total was 330.5M
                # tokens, ~66x the sprint actually being closed, and recording that as a
                # node's actual would have poisoned calibration for the rest of the epic.
                # A window is how a node's own span is cut out of it.
                if since is not None or until is not None:
                    when = _parse_iso(rec.get("timestamp"))
                    if when is None:
                        undated += 1
                        continue
                    if (since is not None and when < since) or \
                       (until is not None and when > until):
                        outside += 1
                        continue
                if rec.get("isSidechain"):
                    sidechain += 1
                totals["input"] += _num_or_none(usage.get("input_tokens")) or 0
                totals["output"] += _num_or_none(usage.get("output_tokens")) or 0
                # Trap 2: the flat field only, never the nested mapping as well.
                totals["cache_write"] += _num_or_none(usage.get("cache_creation_input_tokens")) or 0
                totals["cache_read"] += _num_or_none(usage.get("cache_read_input_tokens")) or 0

    return {"tokens": totals, "files": len(files), "records": records,
            "unique_messages": len(seen), "sidechain_messages": sidechain,
            "outside_window": outside, "undated_skipped": undated,
            "windowed": since is not None or until is not None}


def dispatch_window(state_root: str, agent: str = "", epic: str = "",
                    sprint: str = "", story: str = ""):
    """(open_ts, close_ts) for a node's dispatch bracket. (None, None) if unbracketed.

    This is what makes a node's actual measurable at all. A session transcript records
    everything that session ever did -- one observed file spanned a whole epic lineage --
    so "the transcript" is not the same question as "this story's spend". The
    dispatch_open/dispatch_close pair already marks exactly that boundary for every spawn
    (metrics-contract.md §6); this reads it back so the token count can be cut to it.

    Matches on the keys given and ignores those left empty, so a sprint-level query does
    not have to know its stories. Uses the FIRST open and the LAST close, because a story
    is re-dispatched on every fix iteration and all of it is that story's spend.
    """
    path = events_path(state_root)
    if not os.path.exists(path):
        return None, None
    want = {"agent": agent, "epic": epic, "sprint": sprint, "story": story}
    want = {k: v for k, v in want.items() if v}
    first_open = last_close = None
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(rec, dict):
                    continue
                if rec.get("event") not in ("dispatch_open", "dispatch_close"):
                    continue
                if any(str(rec.get(k, "")) != v for k, v in want.items()):
                    continue
                when = _parse_iso(rec.get("ts"))
                if when is None:
                    continue
                if rec["event"] == "dispatch_open":
                    if first_open is None or when < first_open:
                        first_open = when
                else:
                    if last_close is None or when > last_close:
                        last_close = when
    except OSError as e:
        sys.stderr.write(f"pm-status.py: warning — could not read event log: {e}\n")
    return first_open, last_close


def cmd_usage(args) -> int:
    """Print a transcript's token usage, and the set-actual flags to record it.

    IDENTITY IS CHECKED BEFORE ARITHMETIC. Summing the wrong file is the failure this
    command exists to prevent, and it is the one that produced the original bad number:
    pointed at a task `.output` artifact instead of a session transcript, a hand-count
    reported an output figure several times below what the agent that ran the story had
    itself reported. The cache figures matched closely, so nothing looked wrong -- it was
    file choice, not arithmetic. A reader that can be aimed at the wrong file has not fixed that; it has
    moved it one step earlier.

    So: with no path, resolve this session's own transcript from the environment. With a
    path, verify the file actually is a session transcript and belongs to the expected
    session. Refuse rather than guess. `--allow-unidentified` is the deliberate override,
    and it has to be typed.
    """
    want = args.claude_session or os.environ.get(CLAUDE_SESSION_ENV, "")
    paths = list(args.transcript)
    resolved = False

    if not paths:
        paths, want = resolve_session_transcript(args.claude_session)
        resolved = True
        if not paths:
            sys.stderr.write(
                "pm-status.py: cannot resolve this session's transcript — "
                + (f"no ~/.claude/projects/*/{want}.jsonl found\n" if want else
                   f"{CLAUDE_SESSION_ENV} is not set\n")
                + "  Pass the transcript path explicitly, or --claude-session ID. Refusing to\n"
                  "  guess: summing the wrong file is the error this command exists to prevent.\n")
            return 2

    if not args.allow_unidentified:
        problems = []
        for fp in paths:
            targets = [fp]
            if os.path.isdir(fp):
                targets = [os.path.join(r, n) for r, _d, ns in os.walk(fp)
                           for n in sorted(ns) if n.endswith(".jsonl")]
            for t in targets:
                found = transcript_sessions(t)
                if not found:
                    problems.append(f"{t}: carries no sessionId — this is not a session "
                                    f"transcript (a task .output artifact looks like this)")
                elif len(found) > 1:
                    # Checked BEFORE membership: a file holding two sessions is malformed
                    # whatever we were expecting, and "mixes N sessions" is the actionable
                    # diagnosis. Testing membership first reported it as a plain mismatch
                    # and hid the fact that the file itself is wrong.
                    problems.append(f"{t}: mixes {len(found)} sessions {sorted(found)}")
                elif want and want not in found:
                    problems.append(f"{t}: belongs to session(s) {sorted(found)}, not {want}")
        if problems:
            sys.stderr.write("pm-status.py: refusing to sum — cannot confirm whose transcript "
                             "this is:\n")
            for pr in problems:
                sys.stderr.write(f"  {pr}\n")
            sys.stderr.write("  Pass the right file, set --claude-session, or --allow-unidentified\n"
                             "  to override deliberately.\n")
            return 2

    since = _parse_iso(args.since) if args.since else None
    until = _parse_iso(args.until) if args.until else None
    scope_src = "explicit --since/--until" if (since or until) else ""
    node_keys = {k: getattr(args, k, "") or "" for k in ("agent", "epic", "sprint", "story")}
    if not (since or until) and any(node_keys.values()):
        if not args.state_root:
            _die_usage("--state-root is required to derive a window from a node's dispatch "
                       "bracket (or pass --since/--until yourself)")
        since, until = dispatch_window(args.state_root, **node_keys)
        named = " ".join(f"{k}={v}" for k, v in node_keys.items() if v)
        if since is None and until is None:
            sys.stderr.write(
                f"pm-status.py: no dispatch bracket found for {named} in events.jsonl —\n"
                "  refusing to report an unscoped total for a node. A session transcript spans\n"
                "  everything that session did; without the bracket there is nothing to cut it\n"
                "  to. Bracket the spawn (metrics-contract.md §6) or pass --since/--until.\n")
            return 2
        scope_src = f"dispatch bracket for {named}"

    res = read_transcript_usage(paths, since=since, until=until)
    res["scope"] = scope_src
    res["since"], res["until"] = since, until
    if not res["files"]:
        sys.stderr.write("pm-status.py: no .jsonl transcript found at the given path(s)\n")
        return 3
    # Only claim a session when identity was actually CHECKED. Printing the id from the
    # environment beside numbers read out of an unverified file is the same lie in a new
    # place -- a header that asserts provenance it does not have.
    verified = not args.allow_unidentified
    res["session"] = (want or "(unverified)") if verified else "(UNVERIFIED — --allow-unidentified)"
    res["source"] = ("resolved from environment" if resolved
                     else "given on the command line, identity checked" if verified
                     else "given on the command line, identity NOT checked")
    res["paths"] = paths
    t = res["tokens"]
    total = sum(t.values())
    if args.format == "json":
        sys.stdout.write(json.dumps({**res, "total": total}, indent=2, sort_keys=True) + "\n")
        return 0

    k = {c: t[c] / 1000.0 for c in TOKEN_CLASSES}
    sys.stdout.write(f"session {res['session']} ({res['source']})\n")
    if res.get("scope"):
        sys.stdout.write(f"scope   {res['scope']}\n")
        sys.stdout.write(f"        {res['since']} .. {res['until']}\n")
    for fp in res["paths"]:
        sys.stdout.write(f"  {fp}\n")
    sys.stdout.write(
        f"files={res['files']} records={res['records']} "
        f"unique={res['unique_messages']} sidechain={res['sidechain_messages']}\n")
    if res["records"] > res["unique_messages"]:
        dropped = res["records"] - res["unique_messages"]
        sys.stdout.write(f"  deduplicated {dropped} repeated record(s) of the same message\n")
    if res["sidechain_messages"] == 0 and res["files"] == 1:
        sys.stdout.write("  note: no subagent (sidechain) turns seen in this file — if this "
                         "run dispatched subagents, pass their transcripts too\n")
    if res.get("windowed"):
        sys.stdout.write(f"  excluded {res['outside_window']} message(s) outside the window"
                         + (f", {res['undated_skipped']} undated\n" if res["undated_skipped"]
                            else "\n"))
    else:
        sys.stdout.write(
            "  ** UNSCOPED — this is the WHOLE SESSION, not one node. A session transcript\n"
            "     spans every story it ever ran; one observed file totalled ~66x the sprint\n"
            "     being closed. Do NOT pass this to set-actual. Scope it with --story/--sprint\n"
            "     /--epic (+ --state-root) or --since/--until. **\n")
    for c in TOKEN_CLASSES:
        sys.stdout.write(f"  {c:<12} {t[c]:>12,}  ({k[c]:.1f}k)\n")
    sys.stdout.write(f"  {'TOTAL':<12} {total:>12,}  ({total / 1000.0:.1f}k)\n\n")
    if args.model:
        try:
            sys.stdout.write(f"cost {cost_from_tokens(k, args.model, rate_overrides(args)):.2f} "
                             f"USD at {args.model} rates\n\n")
        except KeyError as e:
            _die_usage(e.args[0])
    if not res.get("windowed"):
        sys.stdout.write("set-actual flags withheld: an unscoped session total is not a "
                         "node's actual.\n")
        return 0
    sys.stdout.write("set-actual flags:\n  " + " ".join(
        f"--tokens-{c.replace('_', '-')} {k[c]:.3f}" for c in TOKEN_CLASSES) + "\n")
    return 0


def cmd_self_install(args) -> int:
    """Copy this script to --dest unless the destination is already this exact script.

    This is how the module shares one runtime copy: each PM skill's setup (and its activation
    self-heal) calls `self-install --dest {project-root}/_bmad/scripts/pm-status.py`, so both
    skills reference a single installed copy — the `resolve_customization.py` pattern.

    THE GUARD IS CONTENT, NOT VERSION. It used to skip whenever the destination's version
    marker was >= this one, which made an equal version mean "identical" — an assumption the
    marker cannot carry, because it is hand-maintained and therefore drifts. It did: ten
    commits changed this script under 2.3.0, and after the bump to 2.4.0 another changed it
    again under 2.4.0. A project that installed at either moment kept a stale copy forever,
    with self-install cheerfully reporting a skip every time, and the staleness was invisible
    because both copies agreed on the number they printed. One such copy sat 920 lines behind
    and was missing a Critical fix.

    A strictly newer destination is still protected — that is a genuine downgrade and the
    version is the only thing that can express it. What no longer happens is treating "same
    number" as "same file".
    """
    src = os.path.abspath(__file__)
    dest = os.path.abspath(args.dest)
    mine = tuple(int(x) for x in PM_STATUS_VERSION.split("."))
    theirs = _parse_version_line(dest) if os.path.exists(dest) else None

    if os.path.exists(dest) and not args.force:
        same = _file_sha(src) is not None and _file_sha(src) == _file_sha(dest)
        if same:
            sys.stdout.write(f"OK self-install skipped — {dest} is already this exact script "
                             f"({PM_STATUS_VERSION})\n")
            return 0
        if theirs is not None and theirs > mine:
            sys.stdout.write(f"OK self-install skipped — {dest} is "
                             f"{'.'.join(map(str, theirs))} > {PM_STATUS_VERSION} "
                             f"(refusing to downgrade)\n")
            return 0
        if theirs is not None and theirs == mine:
            # Same number, different bytes. Installing is right; saying nothing is not --
            # this means a release shipped a changed script without moving the marker, and
            # the only place that can be noticed is here.
            sys.stderr.write(f"pm-status.py: warning — {dest} reports {PM_STATUS_VERSION} but "
                             f"its content differs from this copy; reinstalling. A changed "
                             f"script shipped under an unchanged version marker.\n")
    d = os.path.dirname(dest) or "."
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".pm-status.", suffix=".tmp", dir=d)
    try:
        with open(src, "r", encoding="utf-8") as rf, os.fdopen(fd, "w", encoding="utf-8") as wf:
            wf.write(rf.read())
            wf.flush()
            os.fsync(wf.fileno())
        os.chmod(tmp, 0o755)
        os.replace(tmp, dest)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    was = ".".join(map(str, theirs)) if theirs else "absent"
    sys.stdout.write(f"OK self-install {dest} ({was} -> {PM_STATUS_VERSION})\n")
    return 0


def cmd_set_lock(args) -> int:
    """Claim the epic ownership lock. Exit 0 on success (claim / re-claim / takeover);
    exit 5 (matching cmd_check_lock's "locked" code) when a foreign lock is live or
    unreadable, in which case the file is left untouched.

    The whole read-existing-lock -> decide -> write-claim cycle runs under
    `epic_node_lock` -- see its docstring for why a bare read-then-write here would be
    the same check-then-act race this function exists to close.
    """
    from ruamel.yaml.comments import CommentedMap
    _epic_path_or_die(args)                     # exit 3 before any lock file is created
    with epic_node_lock(args.state_root, args.epic):
        path = _epic_path_or_die(args)          # again: a move may have landed meanwhile
        y, data = load_node(path)
        if data is None:
            _die_notfound(f"epic {args.epic} file is empty")

        takeover_note = ""
        existing = data.get("_lock")
        if existing is not None:
            if not isinstance(existing, dict):
                sys.stdout.write(
                    f"LOCKED epic {args.epic}: existing _lock is malformed (not a "
                    f"mapping) — a lock that cannot be read is not a lock that may "
                    f"be stolen; refusing to claim\n")
                return 5
            holder = str(existing.get("session_id", ""))
            if holder != args.session_id:
                if "claimed_at" not in existing:
                    sys.stdout.write(
                        f"LOCKED epic {args.epic}: existing _lock held by {holder!r} "
                        f"has no claimed_at — refusing to claim\n")
                    return 5
                claimed = _parse_iso(existing.get("claimed_at"))
                if claimed is None:
                    sys.stdout.write(
                        f"LOCKED epic {args.epic}: existing _lock held by {holder!r} "
                        f"has an unparseable claimed_at "
                        f"({existing.get('claimed_at')!r}) — refusing to claim\n")
                    return 5
                ttl = int(existing.get("ttl_minutes", 30))
                age_minutes = _lock_age_minutes(claimed)
                if age_minutes <= ttl:
                    remaining = ttl - age_minutes
                    sys.stdout.write(
                        f"LOCKED epic {args.epic} held by {holder} "
                        f"({remaining:.1f}m remaining of {ttl}m ttl)\n")
                    return 5
                takeover_note = (f" (took over stale lock from {holder}, "
                                  f"age={age_minutes:.1f}m > ttl={ttl}m)")
            # else: same session — re-claim below, refreshing claimed_at. A retry
            # by the owner must not deadlock or refuse against its own lock.

        lock = CommentedMap()
        lock["session_id"] = args.session_id
        lock["claimed_at"] = _now_iso()
        lock["ttl_minutes"] = args.ttl_minutes
        data["_lock"] = lock
        # _lock must appear first — rebuild with _lock at top
        ordered = CommentedMap()
        ordered["_lock"] = lock
        for k, v in data.items():
            if k != "_lock":
                ordered[k] = v
        _atomic_dump(y, ordered, path)
        sys.stdout.write(
            f"OK set-lock epic {args.epic} session={args.session_id} "
            f"ttl={args.ttl_minutes}m{takeover_note}\n")
    return 0


def cmd_clear_lock(args) -> int:
    """Remove the epic's `_lock`. The read-delete-write runs under epic_node_lock, like every
    epic.yaml write: without it, a concurrent promote-issue roll-up (which saves the whole
    epic node under that lock) could land after this write and restore the lock it removed."""
    absent = f"OK clear-lock epic {args.epic} (epic/file absent — no-op)\n"
    if epic_file(args.state_root, args.epic) is None:
        sys.stdout.write(absent)                # no lock file for an absent epic
        return 0
    with epic_node_lock(args.state_root, args.epic):
        path = epic_file(args.state_root, args.epic)     # again: a move may have landed
        if path is None:
            sys.stdout.write(absent)
            return 0
        y, data = load_node(path)
        if data is None:
            sys.stdout.write(f"OK clear-lock epic {args.epic} (file empty — no-op)\n")
            return 0
        if "_lock" not in data:
            sys.stdout.write(f"OK clear-lock epic {args.epic} (no _lock present — no-op)\n")
            return 0
        del data["_lock"]
        _atomic_dump(y, data, path)
    sys.stdout.write(f"OK clear-lock epic {args.epic}\n")
    return 0


def _check_lock_verdict(lock, session_id) -> tuple:
    """check-lock's verdict on a PRESENT `_lock` value, as (exit, line): 0 when the epic
    is free to claim, 5 when another session holds it within its TTL.

    Extracted verbatim from cmd_check_lock -- same lines, same order of evaluation, and
    the same ValueError on a non-integer ttl_minutes. promote-issue (`_foreign_lock_error`)
    takes this verdict only for a lock it can evaluate (`_unevaluable_lock_reason`), so the
    two agree on every well-formed lock: e.g. `ttl_minutes: 0` is always stale to both,
    where promote used to read it as 30. A lock this verdict calls unreadable is FREE to
    check-lock, a read, but refused by both write verbs, set-lock and promote (Ruling 24).
    cmd_set_lock is deliberately NOT routed through here: it parses the TTL only after the
    timestamp, so sharing would change one of the two verbs."""
    if not isinstance(lock, dict):
        return 0, "FREE (unreadable lock — not a mapping — treating as stale)"
    holder = str(lock.get("session_id", ""))
    if holder == session_id:
        return 0, "FREE (own session)"
    claimed_str = str(lock.get("claimed_at", ""))
    ttl = int(lock.get("ttl_minutes", 30))
    claimed = _parse_iso(claimed_str)
    if claimed is None:
        return 0, "FREE (unreadable lock timestamp — treating as stale)"
    age_minutes = _lock_age_minutes(claimed)
    if age_minutes > ttl:
        return 0, f"FREE (stale lock from {holder}, age={age_minutes:.1f}m > ttl={ttl}m)"
    return 5, f"LOCKED by {holder} (claimed {claimed_str}, ttl={ttl}m)"


def cmd_check_lock(args) -> int:
    """Exit 0 if epic is free to claim; exit 5 if held by another session within TTL.

    Timestamp parsing and age arithmetic go through `_parse_iso`/`_lock_age_minutes`
    -- the same helpers `cmd_set_lock` uses -- so the two TTL comparisons cannot drift
    apart into two independently-wrong implementations. The verdict itself lives in
    `_check_lock_verdict`, which promote-issue shares.
    """
    path = epic_file(args.state_root, args.epic)
    if path is None:
        sys.stdout.write("FREE\n")
        return 0
    _y, data = load_node(path)
    if data is None or "_lock" not in data:
        sys.stdout.write("FREE\n")
        return 0
    code, line = _check_lock_verdict(data["_lock"], args.session_id)
    sys.stdout.write(line + "\n")
    return code


def _maybe_set(d, key: str, val, coerce):
    if val is not None:
        try:
            d[key] = coerce(val)
        except (ValueError, TypeError):
            d[key] = val


def cmd_set_estimate(args) -> int:
    # Rejected before anything else is touched: cost is derived from tokens x
    # rates (cmd_estimate_story / cmd_estimate_rollup), never accepted as
    # direct input. --cost, --cost-low, and --cost-high stay declared (with
    # help=argparse.SUPPRESS) purely so this is a clear usage error instead of
    # an argparse "unrecognized arguments" one.
    if getattr(args, "cost", None) is not None or getattr(args, "cost_low", None) is not None \
            or getattr(args, "cost_high", None) is not None:
        _die_usage("cost is derived from tokens x rates and cannot be set directly — "
                   "fix the token counts or modules.l3io-pm.token_rates instead")

    kind = _infer_kind(args)
    with _epic_write_lock(args, kind):
        return _set_estimate(args, kind)


def _set_estimate(args, kind) -> int:
    """cmd_set_estimate's body; the caller holds the epic lock for an epic node."""
    y, node, path, label = _load_checked(args.state_root, args, kind)

    from ruamel.yaml.comments import CommentedMap
    est = node.get("estimate")
    if est is None:
        est = CommentedMap()
        node["estimate"] = est

    if kind == "story":
        # Stories: single values (not ranges)
        _maybe_set(est, "man_hours", args.man_hours, float)
        _maybe_set(est, "hitl_hours", args.hitl_hours, float)
        _maybe_set(est, "elapsed_hours", args.elapsed_hours, float)
        _maybe_set(est, "tokens_k", args.tokens_k_min, int)
    else:
        # Sprints and epics: low/high ranges
        _maybe_set(est, "man_hours_low", args.man_hours_low, float)
        _maybe_set(est, "man_hours_high", args.man_hours_high, float)
        _maybe_set(est, "hitl_hours_low", args.hitl_hours_low, float)
        _maybe_set(est, "hitl_hours_high", args.hitl_hours_high, float)
        _maybe_set(est, "elapsed_hours_low", args.elapsed_hours_low, float)
        _maybe_set(est, "elapsed_hours_high", args.elapsed_hours_high, float)
        _maybe_set(est, "tokens_k_min", args.tokens_k_min, int)
        _maybe_set(est, "tokens_k_max", args.tokens_k_max, int)

    # Calibration factors: applied to get from base values to the estimate
    _maybe_set(est, "fix_factor", getattr(args, "fix_factor", None), float)
    _maybe_set(est, "scope_ratio", getattr(args, "scope_ratio", None), float)

    # Confidence: explicit arg wins; else derive from completeness
    if args.confidence:
        est["confidence"] = args.confidence
    elif "confidence" not in est:
        # No cost/cost_low/cost_high in EITHER list: set-estimate never writes
        # any of them (cost is derived, not settable — see the rejection above),
        # so requiring one would make the estimate permanently "low" confidence.
        # The story list used to name `cost`, which set-estimate rejects at the
        # top of this function and can therefore never satisfy — so every
        # hand-written story estimate came out `low` no matter how complete it
        # was, and the derivation could only ever report one of its two values.
        range_keys = ["man_hours_low", "man_hours_high", "hitl_hours_low", "hitl_hours_high",
                      "elapsed_hours_low", "elapsed_hours_high",
                      "tokens_k_min", "tokens_k_max"]
        story_keys = ["man_hours", "hitl_hours", "elapsed_hours", "tokens_k"]
        check = story_keys if kind == "story" else range_keys
        est["confidence"] = "medium" if all(k in est for k in check) else "low"

    save_node(y, node, path, getattr(args, "flock", False))
    sys.stdout.write(f"OK set-estimate {label}\n")
    return 0


def cmd_set_field(args) -> int:
    """Set an arbitrary nested field at a dot-path within a node.
    --story KEY | --epic ID [--sprint ID] selects the node.
    --field: dot-path within the node, e.g. 'retrospective.summary', 'closed.date'
    --value: string value to set
    """
    # The field itself OR any sub-path of it: an exact-match lookup let `resolves.x` walk
    # into the node and save a mapping under resolves:, and `status.x` crash mid-walk.
    derived = next((d for d in DERIVED_NODE_FIELDS
                    if args.field == d or args.field.startswith(d + ".")), None)
    if derived is not None:
        inside = "" if derived == args.field else f" (it is inside {derived})"
        _die_usage(f"--field {args.field} is not directly writable{inside}: "
                   f"{DERIVED_NODE_FIELDS[derived]}")
    # ...or a PARENT of one: `completion_evidence` would replace the whole mapping and
    # discard the test_runs that tests_passing is derived from.
    contained = next((d for d in sorted(DERIVED_NODE_FIELDS)
                      if d.startswith(args.field + ".")), None)
    if contained is not None:
        _die_usage(f"--field {args.field} is not directly writable (it contains {contained}): "
                   f"{DERIVED_NODE_FIELDS[contained]}")

    kind = _infer_kind(args)
    with _epic_write_lock(args, kind):
        return _set_field(args, kind)


def _set_field(args, kind) -> int:
    """cmd_set_field's body; the caller holds the epic lock for an epic node."""
    y, node, path, label = _load_checked(args.state_root, args, kind)

    field_parts = args.field.split(".")
    target = node
    for part in field_parts[:-1]:
        if target.get(part) is None:
            from ruamel.yaml.comments import CommentedMap
            target[part] = CommentedMap()
        target = target[part]
    value = args.value
    if args.field in NUMERIC_NODE_FIELDS:
        n = _iter_count(value) if args.field.endswith("fix_iterations") else None
        if args.field.endswith("fix_iterations"):
            if n is None:
                _die_usage(
                    f"--field {args.field} needs a non-negative whole number, got {value!r}. "
                    "Stored as text this silently becomes provenance=backout on a story that "
                    "needed no rework, and the clean fix cohort never fills. If the value came "
                    "from a template placeholder, it was not substituted.")
            value = n
        elif _is_number(value):
            value = _coerce(field_parts[-1], value)
    elif args.field in BOOL_NODE_FIELDS:
        low = str(value).strip().lower()
        if low in ("true", "yes", "1"):
            value = True
        elif low in ("false", "no", "0"):
            value = False
    target[field_parts[-1]] = value

    save_node(y, node, path, getattr(args, "flock", False))
    sys.stdout.write(f"OK set-field {label} {args.field}={args.value!r}\n")
    return 0


def cmd_add_test_run(args) -> int:
    """Append one executed test command and derive tests_passing from the set.

    The boolean it replaces recorded that the agent was satisfied, not that
    anything passed: a story shipped `tests_passing: true` having broken a
    suite it never ran, and the break surfaced two stories later. A command
    and an exit code are falsifiable by anyone who re-runs them.

    DERIVATION RULE: `tests_passing` is `all(exit_code == 0)` over the **last
    run of each distinct command**, not over every run ever appended. Agents
    are told to record every command they ran, failures included, so the normal
    fix-then-rerun cycle -- `pytest` -> 1, fix, `pytest` -> 0 -- appends both.
    Folding history into the boolean would leave that story permanently
    `tests_passing: false` and punish exactly the behavior the record wants.
    The full history stays in `test_runs`: that is the evidence, and dropping
    the failed run to make the boolean come out right would destroy it. A
    command whose last run is non-zero still derives False, however many green
    runs preceded it.
    """
    if args.exit_code < 0:
        sys.stderr.write("ERROR --exit-code must be >= 0\n")
        return 2
    path = story_file(args.state_root, args.story)
    if path is None:
        _die_notfound(f"story {args.story}")
    y, node = load_node(path)
    if node is None:
        _die_notfound(f"story {args.story} — file {path} is empty")
    from ruamel.yaml.comments import CommentedMap
    ce = node.setdefault("completion_evidence", CommentedMap())
    runs = ce.setdefault("test_runs", [])
    entry = CommentedMap()
    entry["command"] = args.command
    entry["exit_code"] = int(args.exit_code)
    runs.append(entry)
    # Last run wins per distinct command (see the docstring's DERIVATION RULE).
    # dict keeps insertion order and a re-run overwrites in place, so this is the
    # latest verdict for each command, in the order the commands first appeared.
    latest = {}
    for r in runs:
        if not isinstance(r, dict):
            # A hand-edited list can hold a scalar; an unreadable entry must never
            # derive a pass, and it has no command to key on -- give it its own slot.
            latest[("__malformed__", id(r))] = r
            continue
        latest[r.get("command")] = r
    ce["tests_passing"] = all(
        _exit_code_or_fail(r.get("exit_code") if isinstance(r, dict) else None) == 0
        for r in latest.values()
    )
    save_node(y, node, path, use_flock=True)
    sys.stdout.write(f"OK {args.story} test run recorded "
                     f"({args.command} -> {args.exit_code}); "
                     f"tests_passing={ce['tests_passing']}\n")
    return 0


_BL_KEY_RE = re.compile(r"^BL-E(\d+)-(\d+)$")


# --------------------------------------------------------------------------- #
# Issue store -- issues.yaml (open items) + issues-resolved.yaml (resolved).
# Spec: docs/superpowers/specs/2026-09-10-issue-lifecycle-design.md; ADR-0002.
# --------------------------------------------------------------------------- #
ISSUES_FILENAME = "issues.yaml"
RESOLVED_FILENAME = "issues-resolved.yaml"
OPEN_ISSUE_STATUSES = ("backlog", "scheduled")
# Statuses the PRE-3.0 schema used for an open item, mapped to their current equivalent.
# `deferred` was that schema's resting state for a deliberate deferral -- open, unscheduled --
# which is exactly `backlog` now. A project upgrading with a legacy backlog otherwise gets one
# undifferentiated 1f per item (453 on a real one) whose repair text is "report only", so
# triage reports everything and can act on nothing. Mapping to a RESOLVED state instead would
# be a judgement, not a migration, so it is deliberately not done here.
LEGACY_OPEN_STATUSES = {"deferred": "backlog"}


RESOLUTIONS = ("fixed", "wontfix", "duplicate", "obsolete", "deferred")
# A backlog item's kind. `defect` is the default and is never written, so every file written
# before kinds existed still reads as all defects. The spec kinds come from spec-align.py's
# spec sync (docs/adr/0004-agents-edit-architecture-specs.md): they are confirmed or
# rejected in doctor triage, never promoted to a story.
ISSUE_KINDS = ("defect", "spec-change", "spec-proposal")
SPEC_ISSUE_KINDS = ISSUE_KINDS[1:]
SEVERITY_RANK = {"Low": 0, "Medium": 1, "High": 2, "Critical": 3}


def _int_or_none(v):
    if isinstance(v, bool):
        return None
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return None


def canonical_bl_key(key):
    """'BL-E1-2' -> 'BL-E001-002'. None when the key cannot be written canonically."""
    m = _BL_KEY_RE.match(str(key).strip())
    if not m:
        return None
    epic, n = int(m.group(1)), int(m.group(2))
    if epic > 999 or n > 999 or n < 1:
        return None
    return f"BL-E{epic:03d}-{n:03d}"


def issues_paths(state_root: str) -> tuple:
    return (os.path.join(state_root, ISSUES_FILENAME),
            os.path.join(state_root, RESOLVED_FILENAME))


def _remove_identity(lst, obj) -> None:
    """Remove `obj` itself -- not an equal mapping -- from a list."""
    for i, x in enumerate(lst):
        if x is obj:
            del lst[i]
            return


class IssueStore:
    """Both issue files, loaded together. The caller holds issues_lock(open_path)
    across the whole load -> mutate -> save cycle; the resolved file lives beside
    the open one, so one lock covers both."""

    def __init__(self, open_path: str):
        from ruamel.yaml.comments import CommentedMap, CommentedSeq
        self.open_path = open_path
        self.state_root = os.path.dirname(os.path.abspath(open_path))
        self.resolved_path = os.path.join(self.state_root, RESOLVED_FILENAME)
        self.y, self.open = _load(open_path)
        self.yr, self.res = _load(self.resolved_path)
        if self.open is None:
            self.open = CommentedMap()
        if self.open.get("backlog") is None:
            self.open["backlog"] = CommentedSeq()
        if self.res is None:
            self.res = CommentedMap()
        if self.res.get("resolved") is None:
            self.res["resolved"] = CommentedSeq()
        for name, lst, path in (("backlog", self.open["backlog"], open_path),
                                ("resolved", self.res["resolved"], self.resolved_path)):
            if not isinstance(lst, list):
                raise PMError(2, f"{path} has a malformed '{name}' field (expected a list, "
                                 f"got {type(lst).__name__}: {lst!r}); refusing to write -- "
                                 f"a list that cannot say what is recorded cannot be trusted "
                                 f"to receive more. Fix or restore it by hand, then retry.")

    @property
    def backlog(self):
        return self.open["backlog"]

    @property
    def resolved(self):
        return self.res["resolved"]

    @staticmethod
    def _matching(lst, key):
        return [i for i in lst if isinstance(i, dict) and str(i.get("key", "")) == key]

    def open_items(self, key):
        return self._matching(self.backlog, key)

    def resolved_items(self, key):
        return self._matching(self.resolved, key)

    def single_open(self, key):
        """The one open item with this key, or None. PMError(2) when the key appears
        more than once -- no verb may act on an ambiguous key (audit-issues 1i)."""
        opens = self.open_items(key)
        if len(opens) > 1:
            raise PMError(2, f"{key} appears {len(opens)} times in {self.open_path} -- "
                             f"resolve it by hand (audit-issues finding 1i)")
        return opens[0] if opens else None

    def highest_suffix(self, epic_norm: str) -> int:
        highest = 0
        for item in list(self.backlog) + list(self.resolved):
            if not isinstance(item, dict):
                continue
            m = _BL_KEY_RE.match(str(item.get("key", "")))
            if m and _norm_num(m.group(1), 3) == epic_norm:
                highest = max(highest, int(m.group(2)))
        return highest

    def stored_next(self, epic_norm: str):
        nxt = self.open.get("next")
        if not isinstance(nxt, dict) or epic_norm not in nxt:
            return None
        n = _int_or_none(nxt.get(epic_norm))
        if n is None:
            sys.stderr.write(f"pm-status.py: warning -- next[{epic_norm!r}] = "
                             f"{nxt.get(epic_norm)!r} is not an integer; ignoring it\n")
        return n

    def _next_map(self):
        from ruamel.yaml.comments import CommentedMap
        nxt = self.open.get("next")
        if nxt is not None and not isinstance(nxt, dict):
            sys.stderr.write(f"pm-status.py: warning -- {self.open_path} has a malformed "
                             f"'next' ({nxt!r}); rebuilding it from the highest keys\n")
            nxt = None
        if nxt is None:
            nxt = CommentedMap()
            if "next" in self.open:
                self.open["next"] = nxt
            else:
                self.open.insert(0, "next", nxt)
        return nxt

    def raise_next(self, epic_norm: str, at_least: int) -> None:
        """`next` never decreases: store max(what is stored, at_least)."""
        stored = self.stored_next(epic_norm)
        self._next_map()[epic_norm] = max(stored or 0, at_least)

    def allocate(self, epic_norm: str) -> str:
        n = max(self.stored_next(epic_norm) or 1, self.highest_suffix(epic_norm) + 1)
        if n > 999:
            raise PMError(2, f"epic {epic_norm} has used every backlog key: BL-E{epic_norm}-999 "
                             f"is the last a three-digit suffix can name, and keys are never "
                             f"reused -- nothing written")
        self.raise_next(epic_norm, n + 1)
        return f"BL-E{epic_norm}-{n:03d}"

    def save_open(self) -> None:
        _atomic_dump(self.y, self.open, self.open_path)

    def save_resolved(self) -> None:
        _atomic_dump(self.yr, self.res, self.resolved_path)


def _issue_event(state_root, event, item, session=None, cause="cli", **fields) -> None:
    payload = {"ts": _now_iso(), "event": event, "key": str(item.get("key", "")),
               "epic": str(item.get("epic", "")), "session": session, "cause": cause}
    payload.update(fields)
    append_event(state_root, payload)


def _norm_issue_title(title) -> str:
    """Strip, collapse internal whitespace, and casefold -- for duplicate MATCHING
    only. The stored title is never rewritten to this normalized form."""
    return " ".join(str(title).split()).casefold()


SOURCE_PHASE_RE = re.compile(r"^[A-Za-z][\w-]*$")


def resolve_source(args):
    """Return (source_string, phase, ref) for an append-issue call.

    `--source` is free text stored verbatim and validated nowhere, and it is the only link an
    issue has back to the artifact that raised it. A real backlog grew 100+ distinct shapes,
    and audit-backlog.py accumulated five regexes trying to read them -- every one of which
    has been wrong about some shape. This package's own step-03-dev-loop.md even emits a
    source its own primary reader rejects, surviving only because an earlier regex uses
    .search rather than .match.

    So the structured form DERIVES the string rather than sitting beside it: a caller cannot
    produce a phase/ref pair that disagrees with the text, because it does not write the text.
    Validation here guarantees the result parses as `{phase} ({ref})`, which is the invariant
    the readers depend on.

    `--source` stays accepted and stored byte-for-byte: _content_matches compares it exactly
    as one of four duplicate-detection keys, deliberately, because over-matching loses a real
    finding.
    """
    raw = getattr(args, "source", None)
    phase = getattr(args, "source_phase", None)
    ref = getattr(args, "source_ref", None)
    note = getattr(args, "source_note", "") or ""

    if raw and phase:
        _die_usage("--source and --source-phase are alternatives -- pass one, not both")
    if not raw and not phase:
        _die_usage("append-issue needs --source, or --source-phase with --source-ref")
    if note and not phase:
        _die_usage("--source-note applies only to --source-phase")
    if raw:
        return raw, None, None

    if not ref:
        _die_usage("--source-phase requires --source-ref")
    if not SOURCE_PHASE_RE.match(phase):
        _die_usage(f"--source-phase {phase!r} must match {SOURCE_PHASE_RE.pattern} -- the "
                   f"derived source has to parse as '{{phase}} ({{ref}})', which a space or a "
                   f"punctuation character breaks")
    if "(" in ref or ")" in ref:
        _die_usage(f"--source-ref {ref!r} must not contain parentheses -- they delimit the ref "
                   f"in the derived source string")

    derived = f"{phase} ({ref})" + (f" — {note}" if note else "")
    return derived, phase, ref


def _content_matches(item, epic_norm: str, sprint_norm: str, source: str, norm_title: str) -> bool:

    return (isinstance(item, dict)
            and _norm_num(item.get("epic", ""), 3) == epic_norm
            and _norm_num(item.get("sprint", "") or "", 2) == sprint_norm
            and str(item.get("source", "")) == source
            and _norm_issue_title(item.get("title", "")) == norm_title)


def _find_issue_by_content(backlog, epic_norm: str, sprint_norm: str, source: str, norm_title: str):
    """Match on all four of normalized title + epic + sprint + source, deliberately.
    Over-matching (e.g. title alone) loses a real finding; under-matching leaves
    noise. Losing data is the worse failure, so this only catches near-certain
    repeats -- a re-run of the same story re-deferring the same finding."""
    for item in backlog:
        if _content_matches(item, epic_norm, sprint_norm, source, norm_title):
            return item
    return None


def _last_resolved_match(resolved, epic_norm, sprint_norm, source, norm_title):
    """The NEWEST resolved item with the same content. issues-resolved.yaml is appended
    in resolution order, so the last match is the newest."""
    hits = [r for r in resolved if _content_matches(r, epic_norm, sprint_norm, source, norm_title)]
    return hits[-1] if hits else None


def cmd_append_issue(args) -> int:
    """Append a BL item to the backlog list in state/issues.yaml.

    The whole load -> allocate-key -> dedupe-check -> mutate -> save cycle runs
    under one exclusive lock (`issues_lock`): `issues.yaml` is a shared append
    target across every epic and every parallel subagent, and locking only the
    write (as this used to) lets two concurrent callers read the same pre-write
    backlog, allocate the same next number, and have the second save silently
    drop the first's item -- the same collision class production ADR numbers
    hit (three parallel agents, one directory listing, two agents each picking
    0013 and 0014).

    `--key` is optional. Omitted, the next number for `--epic` is allocated
    here (never by the caller -- nothing bound `{nnn}` anywhere, which is
    exactly how two callers used to invent the same one). Given, and it
    already names an existing item, that is refused (exit 2) rather than
    silently renumbered: a caller naming a key means it. Either way, a content
    duplicate (same normalized title + epic + sprint + source) is skipped --
    the caller's desired end state, "this finding is recorded", already holds
    -- unless `--allow-duplicate` forces a second entry.

    Keys come from `IssueStore.allocate`: `max(next[epic], highest suffix in
    either issue file + 1)`, so a deleted or resolved item's key is never
    handed out again.
    """
    return _run_core(lambda: _append_issue(args))


def _issues_open_path(args) -> str:
    """The open issues file from --state-root, or from --file (compatibility)."""
    sr = getattr(args, "state_root", "") or ""
    f = getattr(args, "file", "") or ""
    if sr:
        p = issues_paths(sr)[0]
        if f and os.path.abspath(f) != os.path.abspath(p):
            raise PMError(2, f"append-issue: --file {f} is not {p} -- pass --state-root "
                             f"alone (--file is kept only for compatibility)")
        return p
    if f:
        return f
    raise PMError(2, "append-issue: pass --state-root (or, for compatibility, --file)")


def _append_issue(args) -> int:
    from ruamel.yaml.comments import CommentedMap
    # Resolved before the lock: a usage error should not hold issues.yaml while it exits.
    source_str, source_phase, source_ref = resolve_source(args)
    open_path = _issues_open_path(args)
    epic_norm = _norm_num(args.epic, 3)
    sprint_norm = _norm_num(args.sprint, 2) if args.sprint else ""
    norm_title = _norm_issue_title(args.title)
    kind = getattr(args, "kind", None) or "defect"
    ref = (getattr(args, "ref", None) or "").strip()
    if kind in SPEC_ISSUE_KINDS and not ref:
        raise PMError(2, f"append-issue: --kind {kind} needs --ref (the docs(spec) commit SHA, "
                         f"or the proposal file's path)")
    if kind == "spec-change" and not _SHA_RE.match(ref):
        raise PMError(2, f"append-issue: --kind spec-change needs --ref to be a commit SHA, "
                         f"not {ref!r}")
    explicit = None
    if args.key:
        explicit = canonical_bl_key(args.key)
        if explicit is None:
            raise PMError(2, f"append-issue: --key {args.key!r} is not a backlog key "
                             f"(expected BL-E{{nnn}}-{{nnn}})")
        if explicit[4:7] != epic_norm:
            raise PMError(2, f"append-issue: --key {explicit} belongs to epic "
                             f"{explicit[4:7]}, not --epic {epic_norm}")
    with issues_lock(open_path, bare_file=not (getattr(args, "state_root", "") or "")):
        store = IssueStore(open_path)
        if explicit is not None:
            clash = store.open_items(explicit) + store.resolved_items(explicit)
            if clash:
                raise PMError(2, f"append-issue: --key {explicit!r} already exists "
                                 f"(title: {clash[0].get('title', '')!r}) -- refusing to "
                                 f"silently assign a different key; pick a key that is not "
                                 f"already taken, or omit --key to auto-allocate the next "
                                 f"one for this epic")
        note = ""
        if not args.allow_duplicate:
            dup = _find_issue_by_content(store.backlog, epic_norm, sprint_norm,
                                         source_str, norm_title)
            if dup is not None:
                sys.stdout.write(
                    f"OK append-issue skipped -- matches existing {dup.get('key', '')} "
                    f"(same title/epic/sprint/source); nothing written. Pass "
                    f"--allow-duplicate to force a second entry.\n")
                return 0
            prior = _last_resolved_match(store.resolved, epic_norm, sprint_norm,
                                         source_str, norm_title)
            if prior is not None:
                res, psev = str(prior.get("resolution", "")), str(prior.get("severity", ""))
                if res == "fixed":
                    note = f" (recurrence of {prior.get('key')})"
                elif SEVERITY_RANK.get(args.severity, 0) > SEVERITY_RANK.get(psev, 0):
                    note = f" (re-raised above {prior.get('key')} {res} at {psev})"
                else:
                    sys.stdout.write(
                        f"OK append-issue skipped -- matches {prior.get('key')} resolved as "
                        f"{res} (severity {psev}); nothing written. Pass --allow-duplicate "
                        f"to force a second entry.\n")
                    return 0
        if explicit is not None:
            key = explicit
            store.raise_next(epic_norm, int(explicit[-3:]) + 1)
        else:
            key = store.allocate(epic_norm)
        item = CommentedMap()
        item["key"] = key
        # epic_norm/sprint_norm, not args.*: both are computed at the top of this function
        # and already trusted for the key, the --key cross-check, dedupe matching and
        # store.allocate(). Storing the caller's spelling instead let one epic appear as
        # '3', '03', '003', 'E3', 'E003' and 'e003' in one file -- all six accepted, all
        # six producing the same correct key.
        item["epic"] = epic_norm
        item["sprint"] = sprint_norm
        item["title"] = args.title
        item["source"] = source_str
        if source_phase:
            item["source_phase"] = source_phase
            item["source_ref"] = source_ref
        item["severity"] = args.severity
        item["status"] = "backlog"
        if kind != "defect":
            item["kind"] = kind
        if ref:
            item["ref"] = ref
        if args.description:
            item["description"] = args.description
        store.backlog.append(item)
        store.save_open()
    _issue_event(store.state_root, "issue_opened", item,
                 getattr(args, "session_id", None), "cli", severity=args.severity)
    sys.stdout.write(f"OK append-issue {key} -> {open_path}{note}\n")
    return 0


_STORY_KEY_RE = re.compile(r"^E\d{3}-S\d{2}-\d{3}$")
_SHA_RE = re.compile(r"^[0-9a-f]{7,40}$")


def _validate_resolution_flags(resolution, ref, note) -> None:
    if resolution not in RESOLUTIONS:
        raise PMError(2, f"--resolution must be one of {', '.join(RESOLUTIONS)}")
    if resolution == "fixed":
        if not ref:
            raise PMError(2, "--resolution fixed needs --ref (a story key or a commit SHA)")
        if not (_STORY_KEY_RE.match(ref) or _SHA_RE.match(ref)):
            raise PMError(2, f"--ref {ref!r} is neither a story key (E{{nnn}}-S{{nn}}-{{nnn}}) "
                             f"nor a commit SHA")
    elif resolution == "duplicate":
        if not ref:
            raise PMError(2, "--resolution duplicate needs --ref naming the surviving BL key")
    elif not (note or "").strip():
        raise PMError(2, f"--resolution {resolution} needs --note saying why")


def resolve_issue_core(store, key, resolution, ref=None, note=None,
                       session=None, cause="cli") -> str:
    """Resolve one open item. The caller holds issues_lock(store.open_path).

    Order is the contract (spec §2.2): a key already in the resolved file has any
    stale open copy removed BEFORE the idempotent return, so a crash between the
    two writes below is always cleared by a rerun; otherwise the item is appended
    to the resolved file first and removed from the open file second, so a crash
    can duplicate it but never lose it."""
    from ruamel.yaml.comments import CommentedMap
    _validate_resolution_flags(resolution, ref, note)
    k = canonical_bl_key(key)
    if k is None:
        raise PMError(2, f"{key!r} is not a backlog key")
    item, done = store.single_open(k), store.resolved_items(k)
    if done:
        prior = done[-1].get("resolution")
        if item is not None:
            _remove_identity(store.backlog, item)
            store.save_open()
            return f"{k} already resolved ({prior}); removed the stale open copy"
        return f"{k} already resolved ({prior})"
    if item is None:
        raise PMError(3, f"{k} is in neither {store.open_path} nor {store.resolved_path}")
    if resolution == "duplicate":
        r = canonical_bl_key(ref)
        if r is None or r == k:
            raise PMError(2, f"--ref {ref!r} must name a different BL key")
        t_open, t_res = store.open_items(r), store.resolved_items(r)
        if not t_open and not t_res:
            raise PMError(2, f"--ref {r} does not exist")
        if not t_open and all(str(t.get("resolution")) == "duplicate" for t in t_res):
            raise PMError(2, f"--ref {r} is itself resolved as a duplicate -- point at the "
                             f"item it duplicates")
        ref = r
    entry = CommentedMap()
    for kk, vv in item.items():
        entry[kk] = vv
    entry["status"] = "resolved"
    entry["resolution"] = resolution
    entry["resolved_at"] = _now_iso()
    if ref:
        entry["ref"] = ref
    if note:
        entry["note"] = note
    store.resolved.append(entry)
    store.save_resolved()
    _remove_identity(store.backlog, item)
    store.save_open()
    _issue_event(store.state_root, "issue_resolved", entry, session, cause,
                 resolution=resolution, ref=ref)
    tail = ""
    if str(item.get("status")) == "scheduled" and cause != "set-status":
        tail = f"; story {item.get('story')} still lists it in resolves"
    return f"{k} ({resolution}{', ref ' + ref if ref else ''}){tail}"


def cmd_resolve_issue(args) -> int:
    def run():
        open_path = issues_paths(args.state_root)[0]
        with issues_lock(open_path):
            msg = resolve_issue_core(IssueStore(open_path), args.key, args.resolution,
                                     args.ref, args.note, args.session_id, args.cause)
        sys.stdout.write(f"OK resolve-issue {msg}\n")
        return 0
    return _run_core(run)


def update_issue_core(store, key, severity, note=None, session=None, cause="cli") -> str:
    """Change an open item's severity. The caller holds issues_lock(store.open_path)."""
    k = canonical_bl_key(key)
    if k is None:
        raise PMError(2, f"{key!r} is not a backlog key")
    done = store.resolved_items(k)
    if done:
        raise PMError(2, f"{k} is resolved ({done[-1].get('resolution')}) -- only open "
                         f"items can be re-severitied")
    item = store.single_open(k)
    if item is None:
        raise PMError(3, f"{k} is in neither {store.open_path} nor {store.resolved_path}")
    before = str(item.get("severity", ""))
    if before == severity:
        # No change is not an update: no save, and no issue_updated event with from == to.
        # A --note lives only in that event, so say it was dropped rather than drop it silently.
        return (f"{k} severity {severity} unchanged"
                f"{' (note not recorded)' if note is not None else ''}")
    item["severity"] = severity
    store.save_open()
    _issue_event(store.state_root, "issue_updated", item, session, cause,
                 **{"from": before, "to": severity, "note": note})
    return f"{k} severity {before} -> {severity}"


def cmd_update_issue(args) -> int:
    def run():
        open_path = issues_paths(args.state_root)[0]
        with issues_lock(open_path):
            msg = update_issue_core(IssueStore(open_path), args.key, args.severity,
                                    args.note, args.session_id, args.cause)
        sys.stdout.write(f"OK update-issue {msg}\n")
        return 0
    return _run_core(run)


_STORY_FILE_RE = re.compile(r"^E\d{3}-S\d{2}-(\d{3})\.(yaml|md)$")


def _unevaluable_lock_reason(lock, session_id):
    """Why promote cannot evaluate a present `_lock`, or None when it can (Ruling 24).

    promote is a write verb, like set-lock, so it fails safe: a foreign lock whose shape it
    cannot read refuses, even where check-lock (a read) reports such a lock FREE. A lock
    naming this session is this session's own and is not refused -- set-lock re-claims its
    own lock the same way, whatever else the block holds. Everything this returns None for
    is exactly what `_check_lock_verdict` can judge without raising.

    The holder is compared to the caller EXACTLY (Ruling F2), as `_check_lock_verdict` and
    cmd_set_lock compare it: a hand-edited 'me ' is foreign to `me` in all three paths, so a
    padded id fails safe. Only the presence check strips, reading a whitespace-only
    session_id as missing."""
    if not isinstance(lock, dict):
        return "not a mapping"
    holder = str(lock.get("session_id", "") or "")
    if not holder.strip():
        return "no session_id"
    if session_id and holder == session_id:
        return None
    claimed = _parse_iso(str(lock.get("claimed_at", "")))
    if claimed is None:
        return "claimed_at is missing or unparseable"
    if claimed.tzinfo is None:
        return "claimed_at has no timezone"
    try:
        int(lock.get("ttl_minutes", 30))
    except (TypeError, ValueError):
        return f"ttl_minutes {lock.get('ttl_minutes')!r} is not a whole number"
    return None


def _foreign_lock_error(epath: str, session_id, epic_key: str):
    """PMError(5) when the epic's `_lock` blocks this session, else None.

    A lock promote cannot evaluate (`_unevaluable_lock_reason`) refuses, naming the epic
    and clear-lock for an abandoned one (Ruling 24). A well-formed lock gets check-lock's
    own verdict (`_check_lock_verdict`, carryover 16), so promote shares its TTL semantics:
    a stale lock -- including any `ttl_minutes: 0` -- does not block. An absent or null
    `_lock` is no lock, as set-lock reads it."""
    _, data = load_node(epath)
    lock = (data or {}).get("_lock")
    if lock is None:
        return None
    why = _unevaluable_lock_reason(lock, session_id)
    if why:
        return PMError(5, f"epic {epic_key} holds a _lock that cannot be evaluated ({why}) "
                          f"-- refusing to write; if the lock is abandoned, remove it with "
                          f"clear-lock --epic {epic_key}")
    code, line = _check_lock_verdict(lock, session_id)
    if code == 0:
        return None
    return PMError(5, f"epic {epic_key} is {line} -- pass that --session-id, or wait for the "
                      f"lock to expire")


def _next_story_key(state_root, artifacts_root, epic_key, sprint_key) -> str:
    """Highest story number in the sprint across the state directory AND the artifact
    stories/ directory, plus one: a document without a state node still owns its key."""
    prefix = f"{epic_key}-{sprint_key}-"
    dirs = [os.path.join(find_epic_dir(state_root, epic_key), sprint_dirname(sprint_key)),
            os.path.join(artifacts_root, epic_dirname(epic_key), sprint_dirname(sprint_key),
                         "stories")]
    highest = 0
    for d in dirs:
        if not os.path.isdir(d):
            continue
        for name in os.listdir(d):
            m = _STORY_FILE_RE.match(name)
            if m and name.startswith(prefix):
                highest = max(highest, int(m.group(1)))
    return f"{prefix}{highest + 1:03d}"


def _yaml_error_reason(e) -> str:
    """One line from a ruamel parse error: its problem and where, not the multi-line dump."""
    problem = getattr(e, "problem", None) or (str(e).splitlines() or [type(e).__name__])[0]
    mark = getattr(e, "problem_mark", None)
    if mark is None:
        return problem
    return f"{problem} (line {mark.line + 1}, column {mark.column + 1})"


def _walk_story_nodes(state_root):
    """Yield (story_key, status_dir, node, path) for every story node in every status folder.

    A node that does not parse, is not valid UTF-8, or is not a mapping (Ruling F4) is
    PMError(2) naming the file (Ruling F1): every caller is a
    verb that must refuse before its first write rather than exit 1 with a traceback.
    audit-issues maps it onto its existing error channel (exit 4), not a new finding id."""
    from ruamel.yaml.error import YAMLError
    for sdir in STATUS_DIRS:
        base = os.path.join(state_root, sdir)
        if not os.path.isdir(base):
            continue
        for ename in sorted(os.listdir(base)):
            edir = os.path.join(base, ename)
            if not (ename.startswith("epic-") and os.path.isdir(edir)):
                continue
            for sname in sorted(os.listdir(edir)):
                spd = os.path.join(edir, sname)
                if not (sname.startswith("sprint-") and os.path.isdir(spd)):
                    continue
                for fname in sorted(os.listdir(spd)):
                    if not fname.endswith(".yaml") or fname == "sprint.yaml":
                        continue
                    path = os.path.join(spd, fname)
                    try:
                        node = load_node(path)[1]
                    except YAMLError as e:
                        raise PMError(2, f"{path} does not parse: {_yaml_error_reason(e)} -- "
                                         f"fix the file by hand")
                    except UnicodeDecodeError as e:
                        raise PMError(2, f"{path} is not valid UTF-8 ({e.reason} at byte "
                                         f"{e.start}) -- fix the file by hand")
                    if node is None:
                        continue
                    if not isinstance(node, dict):
                        held = "a list" if isinstance(node, list) else "a scalar"
                        raise PMError(2, f"{path} is not a mapping (it holds {held}) -- fix "
                                         f"the file by hand")
                    yield str(node.get("key") or fname[:-5]), sdir, node, path


def _dead_claim(status_dir, node) -> bool:
    """A story under archived/ that is not `done` is ignored as a claimant, because its
    epic is closed: promote's resume and audit 1d/1h skip it. If that story is later marked
    `done` (cmd_set_status has no archived guard, and pm-sync pull runs `set-status done`),
    the claim revives, and audit 1h reports the double listing; audit 1g still reports an
    item SCHEDULED to it (1g is keyed on the item's `story:`)."""
    return status_dir == "archived" and str(node.get("status", "")) != "done"


def _partial_promotion(state_root, keys):
    """The story (if any) that already claims these `keys` via its `resolves`, across EVERY
    epic -- keys spread across stories, or a story listing a superset/subset of what was
    asked for, are both claims that must refuse rather than silently mint a second story
    (audit-issues 1d/1h). Resumes only the exact match: exactly one claimant, whose
    `resolves` set equals `keys` exactly, and whose status is not `done`. Anything else --
    no exact claimant, more than one claimant, or a lone claimant whose resolves is a
    superset/subset or who is already done -- refuses (PMError 2) rather than guess.
    A dead claim (`_dead_claim`) is not a claimant at all: after the 1g repair the item is
    backlog again and a re-promotion must mint a new story, not resume the archived one.
    The caller refuses a returned claimant outside its own --epic/--sprint, which parses the
    claimant's key -- so a malformed one is refused here, naming the node, before any write."""
    keyset = set(keys)
    claimants = {}
    for story_key, sdir, node, path in _walk_story_nodes(state_root):
        if _dead_claim(sdir, node):
            continue
        resolves = {str(k) for k in (node.get("resolves") or [])}
        if resolves & keyset:
            claimants[story_key] = (node, path)
    if not claimants:
        return None
    if len(claimants) == 1:
        (story_key, (node, path)), = claimants.items()
        resolves = {str(k) for k in (node.get("resolves") or [])}
        if resolves == keyset and str(node.get("status", "")) != "done":
            try:
                parse_story_key(story_key)
            except ValueError:
                raise PMError(2, f"story node {path} has a malformed key {story_key!r} -- fix "
                                 f"it by hand, then rerun")
            return story_key
    raise PMError(2, f"{', '.join(keys)} already claimed by {sorted(claimants)} -- run "
                     f"/l3io-doctor triage (audit-issues 1d/1h)")


def _promotable_items(store, keys):
    """Resolved is checked FIRST, then the single-open guard (Ruling 8 + Ruling 5): a
    key present in issues-resolved.yaml is resolved even if a stale open copy remains
    (resolve's crash window), and IssueStore.single_open raises PMError(2) itself for
    an ambiguous key (audit-issues finding 1i)."""
    items = []
    for k in keys:
        done = store.resolved_items(k)
        if done:
            raise PMError(2, f"{k} is already resolved ({done[-1].get('resolution')})")
        item = store.single_open(k)
        if item is None:
            raise PMError(2, f"{k} is not an open backlog item")
        if str(item.get("status", "backlog")) == "scheduled":
            raise PMError(2, f"{k} is already scheduled to story {item.get('story')}")
        kind = str(item.get("kind") or "defect")
        if kind != "defect":
            raise PMError(2, f"{k} is a {kind} item -- spec items are confirmed or rejected in "
                             f"/l3io-doctor triage, never promoted to a story")
        items.append(item)
    return items


def _promotion_context(items) -> str:
    lines = ["## Context", "", "Promoted from deferred finding(s):"]
    for it in items:
        desc = str(it.get("description", "") or "").strip()
        lines.append(f"- {it.get('key')} ({it.get('severity')}, {it.get('source')})"
                     + (f" — {desc}" if desc else ""))
    return "\n".join(lines)


def _promote_target(sr, epic_key, sprint_key):
    """(epic path, sprint path) for promote-issue, refusing an absent (3) or archived (2)
    epic and an absent (3) or already-started (2) sprint. Run once before the epic lock, to
    refuse fast, and again under it, where the answer is decisive."""
    epath = epic_file(sr, epic_key)
    if epath is None:
        raise PMError(3, f"epic {epic_key} not found under {sr}")
    if os.path.basename(os.path.dirname(os.path.dirname(epath))) == "archived":
        raise PMError(2, f"epic {epic_key} is archived -- promote into a planned or active epic")
    spath = sprint_file(sr, epic_key, sprint_key)
    if spath is None:
        raise PMError(3, f"sprint {epic_key}-{sprint_key} not found")
    sstatus = str((load_node(spath)[1] or {}).get("status", ""))
    if sstatus != "backlog":
        raise PMError(2, f"sprint {epic_key}-{sprint_key} is {sstatus!r}, not backlog -- "
                         f"promote into a sprint that has not started")
    return epath, spath


def cmd_promote_issue(args) -> int:
    """Turn open BL items into a new story (spec §2.4). Every refusal is checked before
    the first write. An early advisory `issues_lock` check refuses fast, before the epic
    lock is even taken. Then, under `epic_node_lock`, a decisive foreign-lock re-check is
    followed by ONE `issues_lock` hold spanning the decisive item check through the
    schedule save: the item check, partial-promotion detection, the story-document
    pre-check, the story node + estimate save, the story document, both roll-ups, and
    finally marking the items scheduled and saving -- all under that single nested
    `issues_lock`, so a concurrent `resolve-issue` on the same key can never land between
    the check and the write (Ruling 12a). Story first among the writes, so a failure after
    it (e.g. the scheduling save itself failing) leaves a story whose `resolves` still
    names the items, and a retry resumes it via `_partial_promotion`."""
    return _run_core(lambda: _promote_issue(args))


def _promote_issue(args) -> int:
    from ruamel.yaml.comments import CommentedMap, CommentedSeq
    from ruamel.yaml.scalarstring import SingleQuotedScalarString as SQ
    sr, ar = args.state_root, args.artifacts_root
    keys = []
    for raw in args.key:
        k = canonical_bl_key(raw)
        if k is None:
            raise PMError(2, f"--key {raw!r} is not a backlog key")
        if k not in keys:
            keys.append(k)
    if len(keys) > 1 and not args.title:
        raise PMError(2, "promoting several items into one story needs --title")
    model = args.model or DEFAULT_ESTIMATE_MODEL
    overrides = rate_overrides(args)                      # bad JSON exits 2 here, pre-write
    try:
        rates = resolve_rates(model, overrides)
    except KeyError as e:
        raise PMError(2, e.args[0])
    missing = [c for c in TOKEN_CLASSES if c not in rates]
    if missing:
        raise PMError(2, f"model {model!r} has no rate for {missing}")
    epic_key = "E" + _norm_num(args.epic, 3)
    sprint_key = "S" + _norm_num(args.sprint, 2)
    epath, spath = _promote_target(sr, epic_key, sprint_key)
    open_path = issues_paths(sr)[0]
    with issues_lock(open_path):
        _promotable_items(IssueStore(open_path), keys)     # advisory: refuse fast, no epic lock yet
    err = _foreign_lock_error(epath, args.session_id, epic_key)          # advisory
    if err:
        raise err
    with epic_node_lock(sr, epic_key):
        # Resolve again under the lock: move-epic holds it too, so a move that landed while
        # this call waited has moved the directory the paths above name, and writing
        # through them would recreate the old directory as a ghost.
        epath, spath = _promote_target(sr, epic_key, sprint_key)
        err = _foreign_lock_error(epath, args.session_id, epic_key)      # decisive
        if err:
            raise err
        # One issues_lock hold spans the decisive item check through the schedule save
        # (Ruling 12a): nothing in between (compute_story_estimate, init_story_doc,
        # rollup_parent_estimate/save_node) takes issues_lock itself, so a concurrent
        # resolve-issue on the same key blocks here rather than landing between this
        # check and the write that would otherwise orphan an estimated story.
        with issues_lock(open_path):
            store = IssueStore(open_path)
            items = _promotable_items(store, keys)             # decisive
            story_key = _partial_promotion(sr, keys)
            resumed = story_key is not None
            if resumed:
                # Resume only the interrupted call itself (spec §2.4, "a story in the target
                # epic"): a claimant elsewhere was never locked or foreign-lock-checked here,
                # and the roll-ups below would target --epic, not the claimant's epic.
                c_epic, c_sprint, _ = parse_story_key(story_key)
                if (c_epic, c_sprint) != (epic_key, sprint_key):
                    raise PMError(2, f"{', '.join(keys)} were partly promoted into {story_key} "
                                     f"-- retry with --epic {c_epic[1:]} --sprint {c_sprint[1:]}")
            else:
                story_key = _next_story_key(sr, ar, epic_key, sprint_key)
                if os.path.exists(story_doc_path(ar, story_key)):
                    raise PMError(2, f"story document for {story_key} already exists -- "
                                     f"refusing to adopt it")
                node = CommentedMap()
                node["key"] = SQ(story_key)
                node["epic"] = SQ(epic_key)
                node["sprint"] = SQ(sprint_key)
                node["title"] = args.title or str(items[0].get("title", ""))
                node["status"] = "backlog"
                node["classification"] = args.classification
                seq = CommentedSeq(keys)
                seq.fa.set_flow_style()
                node["resolves"] = seq
                compute_story_estimate(sr, node, args.classification, model, overrides)
                _atomic_dump(_yaml(), node,
                            os.path.join(os.path.dirname(spath), f"{story_key}.yaml"))
            init_story_doc(sr, ar, story_key, context_md=_promotion_context(items),
                           ac_lines=[f"The deferred finding {i.get('key')} is resolved: "
                                     f"{i.get('title')}" for i in items],
                           must_not_exist=not resumed)
            _, story_sprint, _ = parse_story_key(story_key)
            rollup_parent_estimate(sr, epic_key, story_sprint, model, overrides)
            rollup_parent_estimate(sr, epic_key, None, model, overrides)
            for it in items:
                it["status"] = "scheduled"
                it["story"] = story_key
                it["scheduled_at"] = _now_iso()
            store.save_open()
    for it in items:
        _issue_event(sr, "issue_scheduled", it, args.session_id, args.cause, story=story_key)
    sys.stdout.write(f"OK promote-issue {', '.join(keys)} -> {story_key}"
                     f"{' (resumed)' if resumed else ''}\n")
    return 0


def _schedulable_items(store, keys, story_key):
    """Split `keys` into (to_schedule, already_here) for a named existing story.

    Gate order mirrors `_promotable_items`: resolved FIRST (Ruling 8), because a key in
    issues-resolved.yaml is resolved even if a stale open copy survives resolve's crash
    window, then the single-open guard (Ruling 5, finding 1i). It differs in exactly one
    place. An item already scheduled to THIS story is a skip rather than a refusal,
    because the mapping that drives this verb is executed as a batch and re-running the
    whole batch has to be safe -- the alternative is asking the operator to track which
    of 28 rows applied. An item scheduled to a DIFFERENT story is still a refusal:
    moving it silently would rewrite a scheduling decision somebody made and leave the
    old story's `resolves` naming an item it no longer owns, which is audit finding 1e.
    """
    to_schedule, already_here = [], []
    for k in keys:
        done = store.resolved_items(k)
        if done:
            raise PMError(2, f"{k} is already resolved ({done[-1].get('resolution')})")
        item = store.single_open(k)
        if item is None:
            raise PMError(2, f"{k} is not an open backlog item")
        kind = str(item.get("kind") or "defect")
        if kind != "defect":
            raise PMError(2, f"{k} is a {kind} item -- spec items are confirmed or rejected "
                             f"in /l3io-doctor triage, never scheduled to a story")
        if str(item.get("status", "backlog")) == "scheduled":
            at = str(item.get("story") or "")
            if at == story_key:
                already_here.append(item)
                continue
            raise PMError(2, f"{k} is already scheduled to story {at} -- unschedule it first "
                             f"(repair-issue --action unschedule --key {k}) rather than "
                             f"moving it silently")
        to_schedule.append(item)
    return to_schedule, already_here


def _schedule_target(sr, epic_key, story_key):
    """(epic path, story path, story node) for schedule-issue, refusing a home the work
    will never reach. Run once before the epic lock to refuse fast, and again under it,
    where the answer is decisive.

    Deliberately NOT `_promote_target`: that one also requires the sprint to be
    `backlog`, which is right for allocating a new story and wrong here -- attaching a
    finding to an existing story in a sprint already under way is the ordinary case.

    The two refusals are the failure this verb exists to avoid: an item silently
    acquiring a home nobody will work. `done` and `archived` are checked separately
    because neither implies the other -- a story under `archived/` can still read
    `status: backlog`, which is how 34 open items on one consumer tree came to be keyed
    to an epic that had been archived out from under them.
    """
    epath = epic_file(sr, epic_key)
    if epath is None:
        raise PMError(3, f"epic {epic_key} not found under {sr}")
    if os.path.basename(os.path.dirname(os.path.dirname(epath))) == "archived":
        raise PMError(2, f"epic {epic_key} is archived -- schedule into a planned or active "
                         f"epic, or move the epic back first (move-epic)")
    spath = story_file(sr, story_key)
    if spath is None:
        raise PMError(3, f"story {story_key} not found under {sr} -- schedule-issue attaches "
                         f"to a story that exists; use promote-issue to create one")
    node = load_node(spath)[1]
    if node is None:
        raise PMError(3, f"story {story_key} -- file {spath} is empty")
    ek, sk, _ = parse_story_key(story_key)
    problems = check_backrefs(node, ek, sk)
    if problems:
        raise PMError(4, f"back-reference mismatch for story {story_key}: "
                         f"{'; '.join(problems)}")
    status = str(node.get("status", ""))
    if status == "done":
        raise PMError(2, f"story {story_key} is done -- its acceptance criteria are already "
                         f"closed, so an unfixed finding attached here is lost. Schedule it "
                         f"to an open story, or promote-issue a new one")
    return epath, spath, node


def cmd_schedule_issue(args) -> int:
    """Attach open BL items to a story that ALREADY EXISTS (the counterpart to
    promote-issue, which only ever creates one).

    Locking mirrors promote-issue exactly, including the nesting order, so the two
    cannot deadlock against each other: an advisory `issues_lock` check to refuse fast,
    an advisory foreign-lock check, then `epic_node_lock`, a re-resolve under it because
    move-epic holds the same lock and may have moved the directory while this call
    waited, a decisive foreign-lock re-check, and ONE `issues_lock` hold spanning the
    decisive item check through the schedule save (Ruling 12a) so a concurrent
    resolve-issue on the same key cannot land between the check and the write.

    Story node first among the writes, matching promote: a failure after it leaves a
    story whose `resolves` names the items while they still read `backlog`, which is
    audit finding 1d -- the state `repair-issue --action link` exists to repair. The
    reverse order would leave items pointing at a story that never claimed them, which
    is finding 1e and has no single-key repair.

    It does NOT re-estimate the story or re-roll-up its parents. The story's estimate was
    set when it was written, by whoever sized it; attaching a finding whose fix its
    acceptance criteria already imply is not a resize, and overwriting a human's estimate
    as a side effect of a bookkeeping verb would be worse than leaving it stale.
    """
    return _run_core(lambda: _schedule_issue(args))


def _schedule_issue(args) -> int:
    from ruamel.yaml.comments import CommentedSeq
    sr = args.state_root
    keys = []
    for raw in args.key:
        k = canonical_bl_key(raw)
        if k is None:
            raise PMError(2, f"--key {raw!r} is not a backlog key")
        if k not in keys:
            keys.append(k)
    try:
        epic_key, _sprint_key, _ = parse_story_key(args.story)
    except ValueError as e:
        raise PMError(2, str(e)) from None

    open_path = issues_paths(sr)[0]
    _schedule_target(sr, epic_key, args.story)                    # advisory: refuse fast
    with issues_lock(open_path):
        _schedulable_items(IssueStore(open_path), keys, args.story)   # advisory
    err = _foreign_lock_error(epic_file(sr, epic_key), args.session_id, epic_key)
    if err:
        raise err
    with epic_node_lock(sr, epic_key):
        # Re-resolve under the lock: move-epic holds it too, so a move that landed while
        # this call waited has moved the directory the paths above name.
        epath, spath, node = _schedule_target(sr, epic_key, args.story)
        err = _foreign_lock_error(epath, args.session_id, epic_key)    # decisive
        if err:
            raise err
        with issues_lock(open_path):
            store = IssueStore(open_path)
            items, already = _schedulable_items(store, keys, args.story)   # decisive
            if items:
                existing = [str(x) for x in (node.get("resolves") or [])]
                seq = node.get("resolves")
                if not isinstance(seq, CommentedSeq):
                    seq = CommentedSeq(existing)
                    seq.fa.set_flow_style()
                    node["resolves"] = seq
                for it in items:
                    k = str(it.get("key"))
                    if k not in existing:        # a story may already claim it (finding 1d)
                        seq.append(k)
                save_node(_yaml(), node, spath)
                stamp = _now_iso()
                for it in items:
                    it["status"] = "scheduled"
                    it["story"] = args.story
                    it["scheduled_at"] = stamp
                store.save_open()
    for it in items:
        # via: a third route to `scheduled`. promote-issue writes no via, repair-link
        # writes "repair-link"; without a distinct value the log cannot say how an item
        # got its story, which is the only record of whether a human chose it.
        _issue_event(sr, "issue_scheduled", it, args.session_id, args.cause,
                     story=args.story, via="schedule")
    done_keys = [str(i.get("key")) for i in items]
    skipped = [str(i.get("key")) for i in already]
    parts = []
    if done_keys:
        parts.append(f"{', '.join(done_keys)} -> {args.story}")
    if skipped:
        parts.append(f"{', '.join(skipped)} already scheduled to {args.story} (skipped)")
    sys.stdout.write(f"OK schedule-issue {'; '.join(parts)}\n")
    return 0


# BL keys run 001-999, so next[epic] -- the NEXT key to hand out -- is at most 1000.
_BL_NEXT_MAX = 1000


def _audit_findings(state_root, store) -> list:
    """Structural integrity findings 1a-1k (spec §3.1). The caller holds issues_lock."""
    findings = []

    def add(fid, key, detail, repair, story=None, epic=None):
        findings.append({"id": fid, "key": key, "story": story, "epic": epic,
                         "detail": detail, "repair": repair})

    # claims: every story listing a key (1b and 1j read it). live: the same minus dead claims
    # (_dead_claim) -- 1d and 1h read only live claims, so the 1g repair leaves a clean audit.
    stories, claims, live = {}, {}, {}
    for skey, sdir, node, _ in _walk_story_nodes(state_root):
        stories[skey] = (sdir, str(node.get("status", "")))
        dead = _dead_claim(sdir, node)
        for k in node.get("resolves") or []:
            claims.setdefault(str(k), []).append(skey)
            if not dead:
                live.setdefault(str(k), []).append(skey)
    open_by, res_by = {}, {}
    for lst, by in ((store.backlog, open_by), (store.resolved, res_by)):
        for it in lst:
            if isinstance(it, dict):
                by.setdefault(str(it.get("key", "")), []).append(it)

    for by, fname in ((open_by, ISSUES_FILENAME), (res_by, RESOLVED_FILENAME)):
        for k, its in by.items():
            if len(its) > 1:
                add("1i", k, f"appears {len(its)} times in {fname}",
                    "report only -- rekey or merge by hand")
            elif canonical_bl_key(k) != k:
                add("1i", k, f"non-canonical key in {fname}", "report only -- rekey by hand")
    for k in open_by:
        if k in res_by:
            add("1a", k, "present in both issue files",
                "resolve-issue rerun -- it clears the open copy")
    for k in open_by:
        if k in res_by:
            continue            # Ruling 8, resolved first: the stale open copy is 1a only
        try:
            it = store.single_open(k)
        except PMError:
            continue            # 1i (reported above): an ambiguous key is never evaluated
        st = str(it.get("status", ""))
        if st in LEGACY_OPEN_STATUSES:
            add("1f", k, f"open item has legacy status {st!r} (pre-3.0 resting state)",
                f"run: pm-status.py repair-issue --state-root S --key {k} "
                f"--action normalize-status  # -> {LEGACY_OPEN_STATUSES[st]}")
        elif st not in OPEN_ISSUE_STATUSES:
            add("1f", k, f"open item has status {st!r}", "report only")
        kind = it.get("kind")
        if kind is not None and str(kind) not in ISSUE_KINDS:
            add("1k", k, f"unknown kind {kind!r}", "report only -- fix the kind by hand")
        elif str(kind) in SPEC_ISSUE_KINDS and not str(it.get("ref") or "").strip():
            add("1k", k, f"{kind} item has no ref",
                "report only -- add the commit SHA or the proposal path by hand")
        if st == "scheduled":
            sk = str(it.get("story", "") or "")
            if sk not in stories or sk not in claims.get(k, []):
                add("1b", k, f"scheduled to {sk or '(none)'}, which is missing or does not "
                             f"list it", "repair-issue --action unschedule", story=sk or None)
            elif stories[sk][0] == "archived" and stories[sk][1] != "done":
                add("1g", k, f"scheduled to {sk}, which is archived and not done",
                    "repair-issue --action unschedule", story=sk)
    for k, sks in claims.items():
        lsks = live.get(k, [])
        if len(lsks) > 1:
            add("1h", k, f"listed in resolves of {', '.join(lsks)}",
                "report only -- decide which story owns it")
        if k not in open_by and k not in res_by:
            add("1b", k, f"named in resolves of {', '.join(sks)} but in neither issue file",
                "report only -- remove it from resolves by hand", story=sks[0])
            continue
        if k not in open_by or k in res_by:     # Ruling 8: resolved first
            continue
        try:
            it = store.single_open(k)
        except PMError:
            continue                            # 1i: an ambiguous key is never evaluated
        for sk in lsks:
            if sk not in stories:
                continue
            if stories[sk][1] == "done":
                add("1c", k, f"story {sk} is done but {k} is still open",
                    f"resolve-issue --key {k} --resolution fixed --ref {sk}", story=sk)
            elif str(it.get("status", "")) == "backlog":
                add("1d", k, f"story {sk} lists {k}, which is still backlog",
                    f"repair-issue --action link --story {sk}", story=sk)
    nxt = store.open.get("next")
    by_hand = f"fix it by hand; reseed refuses a value above {_BL_NEXT_MAX}"
    hand_fix = f"report only -- {by_hand}"
    if nxt is not None and not isinstance(nxt, dict):
        add("1e", "next", f"next is malformed ({nxt!r})", "repair-issue --action reseed")
    elif nxt:
        # Sort on the normalised epic: a hand-edited unquoted key (`1: 5`) is an int, and
        # sorting it against the string keys raised TypeError.
        for e in sorted(nxt, key=lambda e: (_norm_num(str(e), 3), str(e))):
            en = _norm_num(str(e), 3)
            stored, highest = _int_or_none(nxt.get(e)), store.highest_suffix(en)
            beyond = stored is not None and stored > _BL_NEXT_MAX
            if e != en:
                # User decision: allocate reads only the canonical key, so an alias (`1` or
                # '1' for '001') is 1e whatever its value; reseed folds it in by max -- except
                # past the key space, which reseed refuses (exit 2), so that alias gets the
                # same hand-fix repair as its key-space finding below, not a reseed it can't run.
                advice = by_hand if beyond else "run repair-issue --action reseed"
                # Name the raw bytes, not just the parsed key. The parsed key can differ
                # from what is in the file in two ways at once -- an unquoted `019` loads
                # as `19`, losing both the quoting AND the leading zero -- so an operator
                # shown only `19` goes looking for a writer that emits integers and finds
                # none. The usual cause is an external YAML round-trip rather than any
                # pm-status verb: PyYAML's safe_dump quotes `001`-`007` and `012`, whose
                # digits resolve as octal, but emits `008`, `009`, `018`, `019` bare
                # because 8 and 9 are not octal digits -- so a project can round-trip this
                # file for weeks and only corrupt the epics with an 8 or 9 behind the
                # leading zero. Cost a consumer project a wrongly-filed defect against
                # append-issue, which normalises correctly in every spelling.
                add("1e", f"BL-E{en}", f"next has a non-canonical key {e!r} for epic {en} "
                                      f"(= {nxt.get(e)!r}); allocate reads only the quoted "
                                      f"{en!r}. Check the raw bytes -- a bare (unquoted) "
                                      f"{en} in the file parses as {e!r}, and an external "
                                      f"YAML round-trip is a likelier cause than any "
                                      f"pm-status write -- {advice}",
                    hand_fix if beyond else "repair-issue --action reseed", epic=en)
            elif stored is None or stored <= highest:
                add("1e", f"BL-E{en}", f"next[{e}] = {nxt.get(e)!r} but the highest key is "
                                      f"{highest:03d}", "repair-issue --action reseed", epic=en)
            if beyond:
                add("1e", f"BL-E{en}", f"next[{e!r}] = {stored} exceeds the BL key space (keys "
                                      f"stop at 999, so next is at most {_BL_NEXT_MAX})",
                    hand_fix, epic=en)
    for k, its in res_by.items():
        it = its[-1]
        ref = str(it.get("ref", "") or "")
        # Only a ref story whose resolves: lists the key: a legitimate `--ref <story in
        # progress>` never claimed it, and reopening it would manufacture a 1b.
        if (str(it.get("resolution")) == "fixed" and ref in stories
                and stories[ref][1] != "done" and ref in claims.get(k, [])):
            add("1j", k, f"resolved fixed by {ref}, which is now {stories[ref][1]!r}",
                "repair-issue --action reopen", story=ref)
    return findings


def cmd_audit_issues(args) -> int:
    """Structural integrity of the backlog (spec §3.1). Read-only. Both issue files are
    read under issues_lock whenever either one exists, so a concurrent resolve cannot
    fake a finding. When neither exists, no lock is taken -- a read-only command must
    not create issues.yaml.lock -- and the story walk still runs, unlocked, over an
    empty store, so finding 1b can still report a resolves: key that names neither
    file. Exit 4 when anything is found. A malformed issue file, or a story node that
    does not parse, is not valid UTF-8 or is not a mapping (Rulings F1/F4: the existing
    channel, not a new finding id), also exits 4; under
    --format json it still prints a parseable document, {"findings": [], "error": MSG},
    because triage and the health check parse it. Heuristic checks live in
    l3io-doctor/scripts/audit-backlog.py."""
    findings = []
    open_path, res_path = issues_paths(args.state_root)
    try:
        if os.path.exists(open_path) or os.path.exists(res_path):
            with issues_lock(open_path):
                findings = _audit_findings(args.state_root, IssueStore(open_path))
        elif os.path.isdir(args.state_root):
            findings = _audit_findings(args.state_root, IssueStore(open_path))
    except PMError as e:
        sys.stderr.write(f"pm-status.py: {e.msg}\n")
        if args.format == "json":   # triage T2 and health-check Check 13 parse this document
            sys.stdout.write(json.dumps({"findings": [], "error": e.msg}, indent=2) + "\n")
        return 4
    if args.format == "json":
        sys.stdout.write(json.dumps({"findings": findings}, indent=2) + "\n")
    elif not findings:
        sys.stdout.write("audit-issues: no integrity findings\n")
    else:
        for f in findings:
            sys.stdout.write(f"{f['id']}  {f['key']}  {f['detail']}\n"
                             f"      repair: {f['repair']}\n")
    return 4 if findings else 0


def cmd_repair_issue(args) -> int:
    """Narrow structural repairs (spec §3.4). Each action refuses (exit 2) unless its
    audit finding holds for --key, so it can only move the backlog toward a state
    audit-issues accepts -- never invent one it would flag. `unschedule` and `link` act on
    an open item, so they also refuse a key with a resolved entry (Ruling 8, resolved
    first): a stale open copy is finding 1a, cleared by a resolve-issue rerun."""
    return _run_core(lambda: _repair_issue(args))


def _epic_is_archived(state_root, item) -> bool | None:
    """True/False for an item's epic, or None when its status cannot be established.

    None matters: an item whose epic has no state node cannot be classified, and guessing
    either way is the error this whole path exists to avoid.
    """
    epic = str(item.get("epic", "")).strip()
    if not epic:
        return None
    d = find_epic_dir(state_root, f"E{_norm_num(epic, 3)}")
    if d is None:
        return None
    return os.path.basename(os.path.dirname(d)) == "archived"


def _normalize_one_legacy(store, state_root, item, session, cause):
    """Apply the epic-aware rule to one legacy-status item. Returns a verb string for the
    report: 'resolved', 'normalized', or 'skipped'.

    The rule, and why it is not a flat mapping: `deferred` was a DISPOSITION -- "we looked at
    this and decided not now". `backlog` means open and undecided, and neither open status
    carries a decision, so mapping every `deferred` to `backlog` erases one.

      behind an OPEN epic      -> backlog. The loss is harmless: the item is open either way.
      behind an ARCHIVED epic  -> resolved `deferred`. It will not be picked up in that epic,
                                  and issues-resolved.yaml is where a resolution can actually
                                  hold the decision.
      epic status unknown      -> skipped, reported, untouched.

    Measured on the project that found this: 518 of 520 open items sat behind archived epics,
    and mapping them to `backlog` made 444 undecided findings behind closed epics, reddening
    that project's guard against exactly that.
    """
    was = str(item.get("status", ""))
    archived = _epic_is_archived(state_root, item)
    key = str(item.get("key", ""))
    if archived is None:
        return "skipped"
    if archived:
        resolve_issue_core(store, key, "deferred",
                           note=f"migrated from the pre-3.0 open status {was!r}; the epic was "
                                f"already closed, so the deferral is recorded as a resolution "
                                f"rather than reopened as undecided",
                           session=session, cause=cause)
        return "resolved"
    item["status"] = LEGACY_OPEN_STATUSES[was]
    _issue_event(store.state_root, "issue_status_normalized", item, session, cause,
                 note=f"{was} -> {item['status']}")
    return "normalized"


def _normalize_all_legacy(args) -> int:
    """Normalize every legacy open status in one pass, under one lock.

    Measured on a real upgrade: 452 items. One-at-a-time that is 452 subprocesses, each
    taking the issues lock, inside a triage step that confirms per item -- reported back as
    impractical, and it is. Batching adds no judgement: the mapping is mechanical, and the
    same LEGACY_OPEN_STATUSES membership test gates each item exactly as the single-key path
    does, so anything unrecognised is left alone rather than swept along.
    """
    open_path = issues_paths(args.state_root)[0]
    with issues_lock(open_path):
        store = IssueStore(open_path)
        # Snapshot first: resolve_issue_core mutates the open list, so iterating it live
        # would skip items.
        legacy = [it for it in list(store.open.get("backlog") or [])
                  if isinstance(it, dict) and str(it.get("status", "")) in LEGACY_OPEN_STATUSES]
        if not legacy:
            sys.stdout.write("OK normalize-status --all-legacy: no legacy status found\n")
            return 0
        tally = {"resolved": 0, "normalized": 0, "skipped": 0}
        skipped_keys = []
        for it in legacy:
            verb = _normalize_one_legacy(store, args.state_root, it,
                                         args.session_id, args.cause)
            tally[verb] += 1
            if verb == "skipped":
                skipped_keys.append(str(it.get("key", "")))
        store.save_open()
    sys.stdout.write(
        f"OK normalize-status --all-legacy: {tally['normalized']} normalized to backlog "
        f"(open epic), {tally['resolved']} resolved as deferred (closed epic), "
        f"{tally['skipped']} skipped\n")
    if skipped_keys:
        sys.stdout.write(
            f"  skipped -- epic status could not be established, left untouched: "
            f"{', '.join(skipped_keys)}\n")
    return 0


def _normalize_keys(args) -> int:
    """Rewrite every stored epic/sprint to its canonical form, wherever one is stored.

    Fixes records written before the write sites normalised: --epic accepted '3', '03',
    '003', 'E3', 'E003' and 'e003', all six produced the same correct key, and all six were
    stored verbatim. One consuming project measured 116 bare-digit against 7 E-prefixed in
    one file. No verb could repair them -- update-issue changes severity only and the other
    repair actions do not touch these fields -- and hand-editing is forbidden by the state
    contract, so they were simply stuck.

    Whole-file by default with no --key, because unlike normalize-status there is no
    per-item judgement: the canonical form of a key is not a decision. Two files, each kept
    in the form it already uses (see canonical_epic_key): issues.yaml stores bare digits,
    adr-register.yaml stores key form.
    """
    changed = {"issues": 0, "register": 0}
    open_path = issues_paths(args.state_root)[0]
    with issues_lock(open_path):
        store = IssueStore(open_path)
        for lst in (store.backlog, store.resolved):
            for it in lst:
                if not isinstance(it, dict):
                    continue
                for field, width in (("epic", 3), ("sprint", 2)):
                    cur = it.get(field)
                    if cur in (None, ""):
                        continue
                    want = _norm_num(cur, width)
                    if str(cur) != want:
                        it[field] = want
                        changed["issues"] += 1
        if changed["issues"]:
            store.save_open()
            store.save_resolved()

    with adr_register_lock(args.state_root):
        y, reg = load_adr_register(args.state_root)
        for entry in reg.get("reserved") or []:
            if not isinstance(entry, dict) or not entry.get("epic"):
                continue
            want = canonical_epic_key(entry["epic"])
            if str(entry["epic"]) != want:
                entry["epic"] = want
                changed["register"] += 1
        if changed["register"]:
            _atomic_dump(y, reg, adr_register_path(args.state_root))

    total = changed["issues"] + changed["register"]
    if total == 0:
        sys.stdout.write("OK normalize-keys: every stored epic/sprint is already canonical\n")
        return 0
    sys.stdout.write(
        f"OK normalize-keys: {changed['issues']} field(s) in issues.yaml, "
        f"{changed['register']} in adr-register.yaml\n")
    return 0


def _repair_issue(args) -> int:
    from ruamel.yaml.comments import CommentedMap
    if getattr(args, "all_legacy", False):
        if args.action != "normalize-status":
            raise PMError(2, "--all-legacy applies only to --action normalize-status")
        return _normalize_all_legacy(args)
    # normalize-keys is whole-file by construction: the canonical form of a key is not a
    # judgement call, so there is nothing for a --key to scope and nothing to confirm.
    if args.action == "normalize-keys":
        return _normalize_keys(args)
    if not args.key:
        raise PMError(2, "--key is required, or --all-legacy with --action normalize-status, "
                         "or --action normalize-keys")
    k = canonical_bl_key(args.key)
    if k is None:
        raise PMError(2, f"--key {args.key!r} is not a backlog key")
    epic = k[4:7]
    act = args.action
    open_path = issues_paths(args.state_root)[0]
    with issues_lock(open_path):
        store = IssueStore(open_path)
        findings = _audit_findings(args.state_root, store)

        def holds(ids, story=None):
            return any(f["id"] in ids and f["key"] == k and (story is None or f["story"] == story)
                       for f in findings)

        if act == "link" and not args.story:
            raise PMError(2, "--action link needs --story")
        if act in ("unschedule", "link"):
            done = store.resolved_items(k)      # Ruling 8: resolved first
            if done:
                raise PMError(2, f"{act}: {k} is already resolved "
                                 f"({done[-1].get('resolution')}) -- audit finding 1a: rerun "
                                 f"resolve-issue --key {k} (any valid --resolution; the "
                                 f"recorded one is kept) to clear a stale open copy")
        if act == "unschedule":
            opens = store.open_items(k)
            if not (holds({"1b", "1g"}) and len(opens) == 1
                    and str(opens[0].get("status")) == "scheduled"):
                raise PMError(2, f"unschedule: audit finding 1b/1g does not hold for {k}")
            it = opens[0]
            story = it.get("story")
            it["status"] = "backlog"
            it.pop("story", None)
            it.pop("scheduled_at", None)
            store.save_open()
            # scheduled -> backlog is a status transition; the events are its history
            _issue_event(store.state_root, "issue_unscheduled", it, args.session_id,
                         args.cause, story=str(story) if story is not None else None)
            msg = f"{k} unscheduled -> backlog"
        elif act == "link":
            if not holds({"1d"}, story=args.story):
                raise PMError(2, f"link: audit finding 1d does not hold for {k} and {args.story}")
            it = store.single_open(k)           # 1i refusal, never an arbitrary copy
            it["status"] = "scheduled"
            it["story"] = args.story
            it["scheduled_at"] = _now_iso()
            store.save_open()
            # via: tells a repaired scheduling apart from promote's, which has no via field
            _issue_event(store.state_root, "issue_scheduled", it, args.session_id, args.cause,
                         story=args.story, via="repair-link")
            msg = f"{k} scheduled to {args.story}"
        elif act == "normalize-status":
            # Gated like every other action: only a status this schema once used, and only
            # to its documented equivalent. An unrecognised status has no safe mapping, so
            # it stays 1f/report-only rather than being guessed into backlog.
            opens = store.open_items(k)
            if len(opens) != 1:
                raise PMError(2, f"normalize-status: {k} does not resolve to one open item")
            it = opens[0]
            was = str(it.get("status", ""))
            if was not in LEGACY_OPEN_STATUSES:
                raise PMError(2, f"normalize-status: {k} has status {was!r}, which is not a "
                                 f"known legacy status ({', '.join(sorted(LEGACY_OPEN_STATUSES))})"
                                 f" -- audit finding 1f does not hold in its legacy form")
            verb = _normalize_one_legacy(store, args.state_root, it,
                                         args.session_id, args.cause)
            store.save_open()
            if verb == "skipped":
                msg = (f"{k} left at {was!r} -- its epic has no state node, so whether the "
                       f"epic is closed cannot be established and the mapping would be a guess")
            elif verb == "resolved":
                msg = f"{k} {was} -> resolved as deferred (its epic is closed)"
            else:
                msg = f"{k} {was} -> {it['status']} (legacy status normalized)"
        elif act == "reseed":
            if not any(f["id"] == "1e" and (f["epic"] == epic or f["key"] == "next")
                       for f in findings):
                raise PMError(2, f"reseed: audit finding 1e does not hold for epic {epic}")
            nxt = store.open.get("next")
            if not isinstance(nxt, dict):
                nxt = CommentedMap()
                store.open["next"] = nxt
                epics = sorted({canonical_bl_key(str(i.get("key", "")))[4:7]
                                for i in list(store.backlog) + list(store.resolved)
                                if isinstance(i, dict) and canonical_bl_key(str(i.get("key", "")))})
                for e in epics:
                    nxt[e] = store.highest_suffix(e) + 1
            else:
                # Drop non-canonical aliases of the epic (a hand-edited `1:`), which audit
                # would otherwise keep reporting as 1e -- folding their values into the max,
                # so `next` never decreases.
                aliases = [a for a in nxt if _norm_num(str(a), 3) == epic]
                # ...but never fold a value past the key space into the canonical key: that
                # is a hand edit gone wrong, and the max would make it permanent.
                for a in aliases:
                    v = _int_or_none(nxt.get(a))
                    if v is not None and v > _BL_NEXT_MAX:
                        raise PMError(2, f"reseed: next[{a!r}] = {v} exceeds the BL key space "
                                         f"(keys stop at 999, so next is at most "
                                         f"{_BL_NEXT_MAX}) -- fix it by hand; nothing written")
                known = [v for v in (_int_or_none(nxt.get(a)) for a in aliases) if v is not None]
                for a in aliases:
                    if a != epic:
                        del nxt[a]
                nxt[epic] = max([store.highest_suffix(epic) + 1] + known)
            store.save_open()
            msg = f"next reseeded ({', '.join(f'{e}={v}' for e, v in nxt.items())})"
        else:  # reopen
            if not holds({"1j"}):
                raise PMError(2, f"reopen: audit finding 1j does not hold for {k}")
            entry = store.resolved_items(k)[-1]
            ref = str(entry.get("ref"))
            if not store.open_items(k):        # absent unless a previous reopen was interrupted
                item = CommentedMap()
                for kk, vv in entry.items():
                    if kk not in ("resolution", "resolved_at", "ref", "note"):
                        item[kk] = vv
                item["status"] = "scheduled"
                item["story"] = ref
                item["scheduled_at"] = _now_iso()
                store.backlog.append(item)
                store.save_open()               # add first: an item is never lost
            _remove_identity(store.resolved, entry)
            store.save_resolved()
            _issue_event(store.state_root, "issue_reopened", entry, args.session_id,
                         args.cause, story=ref)
            msg = f"{k} reopened, scheduled to {ref}"
    sys.stdout.write(f"OK repair-issue {msg}\n")
    return 0


def _norm_num(v, width: int) -> str:
    """Normalize a possibly key-prefixed or unpadded numeric id to a zero-padded digit
    string: 'E1'/'001' -> '001' (width=3); 'S1'/'01' -> '01' (width=2). Falls back to the
    stripped original string when it is not purely numeric, so a malformed stored value
    still compares by equality instead of raising."""
    s = str(v).strip()
    core = s.lstrip("EeSs")
    if core.isdigit():
        return f"{int(core):0{width}d}"
    return s


def canonical_epic_key(v) -> str:
    """'3'/'03'/'003'/'E3'/'e003' -> 'E003'. The KEY form, for files that store keys.

    Two canonical forms exist on purpose and the difference is per-file, not arbitrary:
    `issues.yaml` stores bare digits ('003') because `canonical_bl_key` slices them straight
    out of `BL-E003-007`, and `events.jsonl` stores key form ('E003') because its story
    records already derive `epic` from `parse_story_key`, which yields 'E001'. Forcing one
    form everywhere would either churn every existing backlog record or make a dispatch
    event disagree with the story event beside it. So: normalise to the form the file
    already uses, and never store the caller's spelling.
    """
    return "E" + _norm_num(v, 3)


def canonical_sprint_key(v) -> str:
    """'1'/'01'/'S1'/'s01' -> 'S01'. See canonical_epic_key for why two forms exist."""
    return "S" + _norm_num(v, 2)


def _origin_archived(state_root, epic) -> bool:
    try:
        d = find_epic_dir(state_root, "E" + _norm_num(epic, 3))
    except ValueError:
        return False
    return d is not None and os.path.basename(os.path.dirname(d)) == "archived"


def cmd_list_issues(args) -> int:
    """List (with optional filters) the open items in issues.yaml; with --resolved, the
    resolved items in issues-resolved.yaml; with --all (JSON only), both.

    A missing issues.yaml and a filter set that matches nothing are both success
    (exit 0) — an empty backlog is a normal project state, not a failure. Filters
    combine with AND; a repeated --severity ORs the given severities together.

    --all reads both files under one issues_lock so a concurrent resolve cannot
    tear the snapshot.
    """
    return _run_core(lambda: _list_issues(args))


def _list_issues(args) -> int:
    if args.resolution and not args.resolved:
        raise PMError(2, "--resolution filters resolved items; add --resolved")
    if args.status and (args.resolved or args.all):
        raise PMError(2, "--status filters open items; drop --resolved/--all")
    if args.all and args.format != "json":
        raise PMError(2, "--all is JSON only; add --format json")
    open_path, res_path = issues_paths(args.state_root)
    if args.all:
        if not (os.path.exists(open_path) or os.path.exists(res_path)):
            opened, resolved = [], []
        else:
            with issues_lock(open_path):
                od, rd = _load(open_path)[1] or {}, _load(res_path)[1] or {}
            for name, data, path in (("backlog", od, open_path), ("resolved", rd, res_path)):
                if data.get(name) is not None and not isinstance(data.get(name), list):
                    raise PMError(2, f"{path} has a malformed '{name}' field")
            opened = list(od.get("backlog") or [])
            resolved = list(rd.get("resolved") or [])
    else:
        src = res_path if args.resolved else open_path
        items = list((_load(src)[1] or {}).get("resolved" if args.resolved else "backlog") or [])

    epic_filter = _norm_num(args.epic, 3) if args.epic else None
    sprint_filter = _norm_num(args.sprint, 2) if args.sprint else None
    severity_filter = set(args.severity) if args.severity else None

    def matches(item) -> bool:
        if not isinstance(item, dict):
            return False
        if epic_filter is not None and _norm_num(item.get("epic", ""), 3) != epic_filter:
            return False
        if sprint_filter is not None:
            item_sprint = str(item.get("sprint", "") or "").strip()
            # empty sprint = epic-level item; it never satisfies a --sprint filter
            if not item_sprint or _norm_num(item_sprint, 2) != sprint_filter:
                return False
        if severity_filter is not None and item.get("severity") not in severity_filter:
            return False
        if args.status and str(item.get("status", "")) != args.status:
            return False
        if args.resolution and str(item.get("resolution", "")) != args.resolution:
            return False
        return not (getattr(args, "kind", None) and str(item.get("kind") or "defect") != args.kind)

    def as_json(item):
        d = dict(item)
        d["origin_archived"] = _origin_archived(args.state_root, item.get("epic", ""))
        return d

    if args.all:
        sys.stdout.write(json.dumps({"open": [as_json(i) for i in opened if matches(i)],
                                     "resolved": [as_json(i) for i in resolved if matches(i)]},
                                    indent=2) + "\n")
        return 0
    filtered = [i for i in items if matches(i)]
    if args.format == "json":
        sys.stdout.write(json.dumps([as_json(i) for i in filtered], indent=2) + "\n")
        return 0
    if not filtered:
        sys.stdout.write("(no matching issues)\n")
        return 0
    state_col = "RESOLUTION" if args.resolved else "STATUS"
    headers = ["KEY", "EPIC", "SPRINT", "SEVERITY", state_col, "ORIGIN", "TITLE"]
    rows = [[str(i.get("key", "")), str(i.get("epic", "")), str(i.get("sprint", "")) or "-",
             str(i.get("severity", "")),
             str(i.get("resolution" if args.resolved else "status", "")),
             "archived" if _origin_archived(args.state_root, i.get("epic", "")) else "-",
             str(i.get("title", ""))] for i in filtered]
    widths = [max(len(headers[c]), *(len(r[c]) for r in rows)) for c in range(len(headers))]

    def _fmt_row(cells):
        last = len(cells) - 1
        return "  ".join(c if idx == last else c.ljust(widths[idx]) for idx, c in enumerate(cells))

    sys.stdout.write(_fmt_row(headers) + "\n")
    for r in rows:
        sys.stdout.write(_fmt_row(r) + "\n")
    return 0


def move_epic(state_root: str, epic_key: str, to_status: str) -> str:
    """Move an epic directory between status folders, preferring `git mv`.

    The directory name never changes — only its parent folder — so git records a
    rename and `git log --follow` keeps working on every file in the tree.

    Every path handed to `git mv` is absolutized first, and so is its `cwd`. A relative
    `state_root` would otherwise be resolved twice — once by the caller's process cwd when
    the operands were built, and again by `cwd=state_root` inside the subprocess — so git
    would be told to move a path that does not exist, fail, and drop silently through to
    the `shutil.move` fallback with exit 0 and no rename recorded. Preserving history via
    `git mv` is the entire reason this function moves directories instead of collapsing
    them, so that degradation must not be silent: the fallback now warns on stderr.

    The move and the epic.yaml status write run under the epic's epic_node_lock. Its lock
    file lives outside the directory being moved (epic_lock_path), so the move cannot carry
    it away from a waiter; every waiter resolves the epic again once it holds the lock, and
    so finds the moved directory. Two movers serialize the same way.
    """
    if to_status not in STATUS_DIRS:
        raise ValueError(f"bad status folder {to_status!r} — expected one of {list(STATUS_DIRS)}")
    state_root = os.path.abspath(state_root)
    if find_epic_dir(state_root, epic_key) is None:          # before any lock file exists
        raise FileNotFoundError(f"epic {epic_key} not found under {state_root}")
    with epic_node_lock(state_root, epic_key):
        return _move_epic_locked(state_root, epic_key, to_status)


def _move_epic_locked(state_root: str, epic_key: str, to_status: str) -> str:
    """move_epic's body; the caller holds the epic's lock and passes an absolute root."""
    src = find_epic_dir(state_root, epic_key)
    if src is None:
        raise FileNotFoundError(f"epic {epic_key} not found under {state_root}")
    src = os.path.abspath(src)
    dest_parent = os.path.join(state_root, to_status)
    dest = os.path.abspath(os.path.join(dest_parent, epic_dirname(epic_key)))
    if src == dest:
        return dest
    if os.path.exists(dest):
        raise FileExistsError(f"destination already exists: {dest}")
    os.makedirs(dest_parent, exist_ok=True)

    moved = False
    reason = "git mv was not attempted"
    try:
        import subprocess
        r = subprocess.run(["git", "mv", src, dest], cwd=state_root,
                           capture_output=True, check=False, text=True)
        moved = r.returncode == 0
        if not moved:
            reason = (r.stderr.strip() or r.stdout.strip()
                      or f"git mv exited {r.returncode}").replace("\n", " ")
    except (OSError, ImportError) as e:
        moved = False
        reason = f"could not run git: {e}"
    if not moved:
        import shutil
        sys.stderr.write(
            f"pm-status.py: WARNING — `git mv` failed ({reason}); falling back to a plain "
            f"filesystem move of {src} -> {dest}. Git will see this as delete+add, not a "
            f"rename, so `git log --follow` will not cross it for these files.\n"
        )
        shutil.move(src, dest)

    p = os.path.join(dest, "epic.yaml")
    if os.path.exists(p):
        y, node = load_node(p)
        if node is not None:
            node["status"] = STATUS_FOR_DIR[to_status]
            node["updated_at"] = _now_iso()
            save_node(y, node, p)
    return dest


def cmd_move_epic(args) -> int:
    to = getattr(args, "to", None) or "archived"
    try:
        dest = move_epic(args.state_root, args.epic, to)
    except FileNotFoundError as e:
        _die_notfound(str(e))
    except (ValueError, FileExistsError) as e:
        _die_usage(str(e))
    sys.stdout.write(f"OK move-epic {args.epic} -> {to} ({dest})\n")
    return 0


def cmd_list_epics(args) -> int:
    """Enumerate every epic in the state tree with its status bucket.

    Read-only. A missing state root prints nothing and exits 0 -- the shape of a
    project with no state yet, which is the same silent shape the old
    `ls -d ... 2>/dev/null` probe gave callers.

    --format keys (default): one E{nnn} per line, sorted, buckets flattened. Cheap.
    --format json: a list of {key, bucket, status}, sorted by (bucket, key) with
    STATUS_DIRS order preserved so active/planned/archived is a stable read.
    """
    rows = list(iter_epic_dirs(args.state_root))
    if args.format == "json":
        out = [{"key": k, "bucket": b, "status": STATUS_FOR_DIR[b]} for b, k, _ in rows]
        sys.stdout.write(json.dumps(out) + "\n")
    else:
        for _b, k, _p in rows:
            sys.stdout.write(f"{k}\n")
    return 0


def cmd_list_stories(args) -> int:
    """Enumerate story keys for an epic, optionally scoped to one sprint.

    Read-only. A missing epic exits 3 -- absent-vs-empty matters for the caller,
    and the resolver already distinguishes them. A sprint that does not exist
    yields nothing and exits 0: a project can ask about a sprint it has not
    created yet, and the answer is not an error, it is an empty list.

    Filters out sprint.yaml/epic.yaml and anything whose name does not parse as
    a story key -- callers get story keys, no post-processing required.
    """
    if find_epic_dir(args.state_root, args.epic) is None:
        _die_notfound(f"epic {args.epic}")
    sprint = args.sprint if args.sprint else None
    rows = list(iter_story_files(args.state_root, args.epic, sprint))
    if args.format == "json":
        out = []
        for k, _p in rows:
            _e, sk, _ = parse_story_key(k)
            out.append({"key": k, "sprint": sk})
        sys.stdout.write(json.dumps(out) + "\n")
    else:
        for k, _p in rows:
            sys.stdout.write(f"{k}\n")
    return 0


def cmd_show(args) -> int:
    """Render a computed sprint or epic roll-up. Exits 3 if the epic (or,
    when --sprint is given, that sprint within it) does not resolve — an
    empty roll-up must never be printed for a node that doesn't exist."""
    d = find_epic_dir(args.state_root, args.epic)
    if d is None:
        _die_notfound(f"epic {args.epic}")

    if args.sprint:
        sd = os.path.join(d, sprint_dirname(args.sprint))
        if not os.path.isdir(sd):
            _die_notfound(f"epic {args.epic} sprint {args.sprint}")
        r = rollup_sprint(args.state_root, args.epic, args.sprint)
        # Cosmetic wart named in the design (§13): a sprint whose stories are
        # ALL blocked reads as "actively being worked" when its status is
        # still in-progress. Surface it in the header rather than promote it to
        # a status transition (that would need its own transition table).
        header_status = r["status"]
        n_blocked = r.get("blocked_stories", 0)
        if n_blocked and n_blocked == r["story_count"] and r["story_count"] > 0:
            header_status = f"{r['status']} (all {n_blocked} stories blocked)"
        sys.stdout.write(f"{args.epic}/{r['key']}  status={header_status}  "
                         f"stories={r['story_count']}\n")
        for s in r["stories"]:
            suffix = ""
            if s["status"] == "blocked":
                reason = s.get("blocked_reason", "")
                suffix = f"  [blocked: {reason}]" if reason else "  [blocked]"
            sys.stdout.write(f"  {s['key']:<20} {s['status']}{suffix}\n")
        sys.stdout.write(f"  actuals: {_fmt_actuals(r['actual_totals'])}\n")
        _write_spend(r["spend"])
        return 0

    r = rollup_epic(args.state_root, args.epic)
    sys.stdout.write(f"{r['key']}  status={r['status']}  sprints={r['sprint_count']}  "
                     f"stories={r['story_count']}\n")
    for sp in r["sprints"]:
        sys.stdout.write(f"  {sp['key']:<8} status={sp['status']:<12} stories={sp['story_count']}\n")
    sys.stdout.write(f"  actuals: {_fmt_actuals(r['actual_totals'])}\n")
    n_blocked = r.get("blocked_stories", 0)
    if n_blocked > 0:
        cumul = r.get("blocks_seen_cumulative", 0)
        cumul_note = f", {cumul} cumulative block events" if cumul else ""
        sys.stdout.write(f"  blocked_stories: {n_blocked}{cumul_note}\n")
    _write_spend(r["spend"])
    return 0


def _write_spend(spend: dict) -> None:
    """The three-bucket breakout under a `show` roll-up.

    The `actuals:` line above is the CHILDREN's sum only — that is what it has
    always been, and callers parse it. Closure and orchestration are printed
    beside it rather than folded into it, because the whole point of the model is
    that the three are separately attributable (metrics-contract.md §6).
    """
    if not _has_spend(spend):
        return
    for bucket in SPEND_BUCKETS:
        vals = (spend or {}).get(bucket) or {}
        if vals:
            sys.stdout.write(f"  spend/{bucket:<14} {_fmt_actuals(vals)}\n")
    sys.stdout.write(f"  spend/{'TOTAL':<14} {_fmt_actuals(_spend_total(spend))}\n")


def cmd_report(args) -> int:
    """Plan-aware progress report. Read-only unless --out is given, which is what lets
    read-only callers (l3io-doctor stats) share this exact code path."""
    if not os.path.isdir(args.state_root):
        _die_notfound(f"state root {args.state_root}")

    if args.all and args.status:
        _die_usage("pass --all or --status, not both")
    if args.status:
        statuses = {x.strip() for x in args.status.split(",") if x.strip()}
        unknown = statuses - set(STATUS_DIRS)
        if unknown:
            _die_usage(f"unknown --status value(s) {sorted(unknown)} "
                       f"— expected a subset of {list(STATUS_DIRS)}")
    elif args.all:
        statuses = set(STATUS_DIRS)
    else:
        statuses = set(DEFAULT_REPORT_STATUSES)

    def once() -> str:
        plan = load_plan(args.plan) if args.plan else None
        model = build_progress_model(args.state_root, plan=plan, statuses=statuses)
        stalled = open_dispatches(args.state_root,
                                  getattr(args, "stall_minutes", DEFAULT_STALL_MINUTES))
        if args.format == "json":
            model["stalled_dispatches"] = stalled
            return json.dumps(model, indent=2, sort_keys=True) + "\n"
        text = render_md(model) if args.format == "md" else render_tree(model)
        if stalled:
            lines = ["", "STALLED DISPATCH (open past threshold):"]
            for s in stalled:
                where = " ".join(x for x in (s["epic"], s["sprint"], s["story"]) if x)
                lines.append(f"  {s['agent']:<20} {where:<28} "
                             f"{s['age_minutes']}m  since {s['opened_at']}")
            text = text + "\n".join(lines) + "\n"
        return text

    if args.watch:
        import time
        try:
            while True:
                sys.stdout.write("\x1b[2J\x1b[H")   # clear + home
                sys.stdout.write(once())
                sys.stdout.write(f"\n[refreshing every {args.watch}s — Ctrl-C to stop]\n")
                sys.stdout.flush()
                time.sleep(args.watch)
        except KeyboardInterrupt:
            return 0

    text = once()
    if args.out:
        d = os.path.dirname(os.path.abspath(args.out)) or "."
        os.makedirs(d, exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text)
        sys.stdout.write(f"OK report {args.out} ({args.format})\n")
        return 0
    sys.stdout.write(text)
    return 0


def cmd_verify(args) -> int:
    kind = args.scope  # story | sprint | epic
    if kind == "epic":
        _y, node, _path, label = _load_checked(args.state_root, args, kind)
        failures: list[str] = []
        for sd in list_sprint_dirs(args.state_root, args.epic):
            skey = _sprint_key_from_dir(sd)
            sp = sprint_file(args.state_root, args.epic, skey)
            if sp is None:
                failures.append(f"{skey}: sprint.yaml missing")
            else:
                _, snode = load_node(sp)
                failures += [f"{skey}: {p}" for p in check_backrefs(snode, args.epic)]
            for stf in list_story_files(args.state_root, args.epic, skey):
                _, stnode = load_node(stf)
                if stnode is None:
                    failures.append(f"{os.path.basename(stf)}: empty")
                    continue
                failures += [f"{stnode.get('key', '?')}: {p}"
                             for p in check_backrefs(stnode, args.epic, skey)]
        if failures:
            for f in failures:
                sys.stderr.write(f"FAIL {f}\n")
            return 4
        sys.stdout.write(f"PASS epic {args.epic}\n")
        return 0

    _y, node, _path, label = _load_checked(args.state_root, args, kind)

    problems: list[str] = []
    if node.get("status") != "done":
        problems.append(f"status={node.get('status')!r} (expected done)")

    actual = node.get("actual") or {}
    required = list(METRIC_FIELDS)
    for m in required:
        if m not in actual:
            problems.append(f"actual.{m} absent")
            continue
        val = actual[m]
        # Numeric fields must be numeric; token/cost may be N/A only under non-claude runtime.
        if m in ("elapsed_hours", "man_hours", "hitl_hours"):
            if _is_na(val) or not _is_number(val):
                problems.append(f"actual.{m}={val!r} (must be numeric)")
        else:  # tokens_k, cost
            if _is_na(val):
                copilot_cost_na = (args.runtime == "copilot" and m == "cost")
                if not copilot_cost_na and (
                    args.require_tokens or args.runtime in ("claude", "codex", "copilot")
                ):
                    problems.append(
                        f"actual.{m}=N/A (forbidden under runtime={args.runtime} "
                        f"/ --require-tokens)")

    # tokens_k, once structured, is self-verifying: its total must equal the sum
    # of its four classes, and its cost must equal what those tokens price out to
    # under its own recorded model. A hand-edited cost is exactly the failure
    # this closes — without it, a bogus number survives in committed state
    # indefinitely because nothing ever recomputes it.
    tk = actual.get("tokens_k")
    if hasattr(tk, "get"):
        parts = sum(_num_or_none(tk.get(c)) or 0.0 for c in TOKEN_CLASSES)
        total = _num_or_none(tk.get("total"))
        # Unlike cost (below), total and parts are NOT on the same rounding grid:
        # `total` was rounded to 2dp once at write time (tokens_block), but
        # `parts` here is an unrounded re-sum of the class values. That write-time
        # rounding alone can separate a legitimate total from its exact sum by up
        # to half the last decimal place (0.005) with no error involved at all —
        # so tightening this to cost's 0.005 would risk failing correctly-rounded
        # data. 0.01 keeps a safe margin above that rounding noise while still
        # catching any genuine (typically integer-scale, since counts are whole
        # thousands of tokens) divergence.
        if total is None or abs(total - parts) > 0.01:
            problems.append(f"actual.tokens_k.total={total!r} != sum of classes ({parts})")
        model = actual.get("model")
        if not model:
            problems.append("actual.model absent (cost cannot be verified)")
        else:
            try:
                expect = cost_from_tokens(tk, str(model), rate_overrides(args))
            except KeyError as e:
                # e.args[0], not str(e) — KeyError.__str__ repr-quotes its argument,
                # which would double-wrap a message that already reads as prose.
                problems.append(e.args[0])
            else:
                got = _num_or_none(actual.get("cost"))
                # Both got and expect are already rounded to cents (the smallest
                # unit either can carry), so the smallest genuine divergence is
                # exactly one cent (0.01). A tolerance of 0.01 would not fire on
                # it — the tolerance would be exactly the size of the error it
                # exists to catch. Half the discrete unit still absorbs true
                # float-summation noise (~1e-9 to 1e-14) with enormous margin
                # while catching any one-cent divergence.
                if got is None or abs(got - expect) > 0.005:
                    problems.append(f"actual.cost={got!r} != derived {expect} "
                                    f"for model {model}")
    elif "tokens_k" in actual and not _is_na(tk):
        # A bare scalar tokens_k has no class split, so the cost invariant above
        # cannot run at all — `tokens_k: 500` next to `cost: 9999.99` used to
        # return PASS. Design §4.3 says a hand-edited cost cannot survive verify;
        # keeping the pre-rework scalar shape was a one-line way around it. The
        # scalar form stays legitimate under runtime=other (set-estimate writes
        # it, and a runtime with no per-class visibility has nothing better), so
        # this fires only where exact per-class capture is required.
        if args.require_tokens or args.runtime in ("claude", "codex"):
            problems.append(
                f"actual.tokens_k={tk!r} is not the per-class mapping — cost cannot be "
                f"verified against it. Re-capture with set-actual "
                f"--tokens-input/--tokens-output/--tokens-cache-write/--tokens-cache-read "
                f"and --model (metrics-contract.md §3)")

    if kind == "story" and "completion_evidence" not in node:
        problems.append("completion_evidence absent")

    est_model = (node.get("estimate") or {}).get("model")
    act_model = actual.get("model")
    if est_model and act_model and est_model != act_model:
        sys.stdout.write(
            f"WARN {label}: estimate.model={est_model!r} ≠ actual.model={act_model!r}"
            f" — estimate cost denominated in {est_model} rates\n"
        )
    if problems:
        sys.stdout.write(f"FAIL {label}: " + "; ".join(problems) + "\n")
        return 4
    sys.stdout.write(f"PASS {label}\n")
    return 0


# --------------------------------------------------------------------------- #
# value helpers
# --------------------------------------------------------------------------- #
def _is_na(v) -> bool:
    return isinstance(v, str) and v.strip().upper() in {"N/A", "NA", "NONE", ""}


def _is_number(v) -> bool:
    if isinstance(v, bool):
        return False
    if isinstance(v, (int, float)):
        return True
    if isinstance(v, str):
        try:
            float(v)
            return True
        except ValueError:
            return False
    return False


def _coerce(field: str, v: str):
    """Numeric metrics become int/float unless N/A. `cost` is derived, not entered;
    the only string it can be here is N/A."""
    if _is_na(v):
        return v
    try:
        f = float(v)
        return int(f) if f.is_integer() and field != "cost" else f
    except ValueError:
        return v


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="pm-status.py", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    def node_args(sp):
        sp.add_argument("--story", help="story key (addresses a story node)")
        sp.add_argument("--epic", help="zero-paddable epic id")
        sp.add_argument("--sprint", help="zero-paddable sprint id")

    s = sub.add_parser("set-status", help="set a node's status atomically")
    s.add_argument("--state-root", required=True, help="path to {implementation_artifacts}/state")
    node_args(s)
    s.add_argument("--status", required=True)
    s.add_argument("--title")
    s.add_argument("--reason", default="",
                   help="required when --status blocked; free-text why the story halted. "
                        "Rejected on any other status (a --reason for review would only "
                        "confuse the record).")
    s.add_argument("--resolution", default="",
                   help="required when a story transitions blocked -> done; free-text "
                        "why the story shipped as-is rather than resumed (e.g. \"spec "
                        "change removed the need for this story\").")
    s.add_argument("--flock", action="store_true", help="acquire exclusive flock before write")
    s.add_argument("--no-events", dest="no_events", action="store_true",
                   help="skip the events.jsonl append for this call")
    s.add_argument("--session-id", dest="session_id", default=None,
                   help="recorded in the event payload; null when omitted")
    s.set_defaults(func=cmd_set_status)

    sd = sub.add_parser("sync-story-doc",
                        help="write status into the story markdown's frontmatter")
    sd.add_argument("--artifacts-root", required=True,
                    help="implementation_artifacts root (NOT the state root)")
    sd.add_argument("--story", required=True)
    sd.add_argument("--status", required=True)
    sd.add_argument("--quiet", action="store_true")
    sd.set_defaults(func=cmd_sync_story_doc)

    di = sub.add_parser("story-doc-init",
                        help="create a story document skeleton from its state node")
    di.add_argument("--state-root", required=True)
    di.add_argument("--artifacts-root", required=True,
                    help="implementation_artifacts root (NOT the state root)")
    di.add_argument("--story", required=True)
    di.set_defaults(func=cmd_story_doc_init)

    sdo = sub.add_parser("set-depends-on",
                         help="append dependency keys to an epic or story node's depends_on list")
    sdo.add_argument("--state-root", required=True)
    sdo.add_argument("--epic")
    sdo.add_argument("--story", help="a story node's depends_on takes story keys")
    sdo.add_argument("--sprint")
    sdo.add_argument("--add", action="append", required=True, metavar="KEY",
                     help="repeatable; idempotent, order preserved. Epic keys for an epic "
                          "node, story keys for a story node")
    sdo.set_defaults(func=cmd_set_depends_on)

    imp = sub.add_parser("import-node",
                         help="create a state node from a migration record")
    imp.add_argument("--state-root", required=True)
    imp.add_argument("--epic")
    imp.add_argument("--sprint")
    imp.add_argument("--story")
    imp.add_argument("--status", required=True)
    imp.add_argument("--title", default="")
    imp.add_argument("--classification", default="unknown")
    imp.add_argument("--origin", choices=["inferred"],
                     help="mark the node as reconstructed rather than read")
    imp.add_argument("--origin-note", default="",
                     help="why the node was inferred; recorded beside --origin")
    imp.add_argument("--reason", default="",
                     help="required when importing a story at --status blocked; "
                          "recorded on the node as blocked_reason and in the paired "
                          "block_open event so a future exit-from-blocked can derive "
                          "duration. Rejected on any other kind or status.")
    imp.add_argument("--no-events", action="store_true")
    imp.add_argument("--session-id")
    imp.set_defaults(func=cmd_import_node)

    a = sub.add_parser("set-actual", help="write a validated actual block")
    a.add_argument("--state-root", required=True, help="path to {implementation_artifacts}/state")
    a.add_argument("--node", required=True, choices=["story", "sprint", "epic"])
    node_args(a)
    a.add_argument("--block", choices=["actual", "orchestration"], default="actual",
                   help="which metric block to write (orchestration: sprint/epic only)")
    a.add_argument("--elapsed-hours", dest="elapsed_hours")
    a.add_argument("--man-hours", dest="man_hours")
    a.add_argument("--hitl-hours", dest="hitl_hours",
                   help="human attention actually spent supervising (hours)")
    a.add_argument("--tokens-input", dest="tokens_input")
    a.add_argument("--tokens-output", dest="tokens_output")
    a.add_argument("--tokens-cache-write", dest="tokens_cache_write")
    a.add_argument("--tokens-cache-read", dest="tokens_cache_read")
    a.add_argument("--tokens-na", dest="tokens_na", action="store_true",
                   help="record tokens/cost as N/A (runtime=other only)")
    a.add_argument("--model", default="", help="model id that priced these tokens")
    a.add_argument("--token-rates", dest="token_rates", default="",
                   help="JSON object of per-model rate overrides")
    a.add_argument("--cost", default=None, help=argparse.SUPPRESS)
    a.add_argument("--runtime", choices=["claude", "codex", "copilot", "other"], default="other")
    a.add_argument("--flock", action="store_true", help="acquire exclusive flock before write")
    a.add_argument("--no-calibrate", dest="no_calibrate", action="store_true",
                   help="skip calibration sampling (backfills, replays)")
    a.add_argument("--no-events", dest="no_events", action="store_true",
                   help="skip the events.jsonl append for this call")
    a.add_argument("--session-id", dest="session_id", default=None,
                   help="recorded in the event payload; null when omitted")
    a.set_defaults(func=cmd_set_actual)

    ia = sub.add_parser("import-actual",
                        help="record an actual observed elsewhere (migration); runtime=other, "
                             "tokens=N/A and no calibration sample are FIXED, not optional")
    ia.add_argument("--state-root", required=True)
    ia.add_argument("--node", required=True, choices=["story", "sprint", "epic"])
    ia.add_argument("--story")
    ia.add_argument("--epic")
    ia.add_argument("--sprint")
    ia.add_argument("--elapsed-hours", dest="elapsed_hours")
    ia.add_argument("--man-hours", dest="man_hours")
    ia.add_argument("--hitl-hours", dest="hitl_hours")
    ia.add_argument("--flock", action="store_true")
    ia.add_argument("--no-events", dest="no_events", action="store_true")
    ia.add_argument("--session-id", dest="session_id", default=None)
    ia.set_defaults(func=cmd_import_actual)

    v = sub.add_parser("verify", help="read-back gate; nonzero exit on any gap")
    v.add_argument("--state-root", required=True, help="path to {implementation_artifacts}/state")
    v.add_argument("--scope", required=True, choices=["story", "sprint", "epic"])
    node_args(v)
    v.add_argument("--require-tokens", action="store_true")
    v.add_argument("--runtime", choices=["claude", "codex", "copilot", "other"], default="other")
    v.add_argument("--token-rates", dest="token_rates", default="",
                   help="JSON object of per-model rate overrides")
    v.set_defaults(func=cmd_verify)

    le = sub.add_parser("list-epics",
                        help="list every epic key in the state tree with its status bucket")
    le.add_argument("--state-root", required=True)
    le.add_argument("--format", choices=["keys", "json"], default="keys")
    le.set_defaults(func=cmd_list_epics)

    ls_ = sub.add_parser("list-stories",
                         help="list story keys for an epic, optionally scoped to one sprint")
    ls_.add_argument("--state-root", required=True)
    ls_.add_argument("--epic", required=True)
    ls_.add_argument("--sprint", default="")
    ls_.add_argument("--format", choices=["keys", "json"], default="keys")
    ls_.set_defaults(func=cmd_list_stories)

    sh = sub.add_parser("show", help="render a computed sprint or epic roll-up")
    sh.add_argument("--state-root", required=True)
    sh.add_argument("--epic", required=True)
    sh.add_argument("--sprint", default="")
    sh.set_defaults(func=cmd_show)

    rp = sub.add_parser("report", help="plan-aware progress report (read-only unless --out)")
    rp.add_argument("--state-root", required=True)
    rp.add_argument("--plan", default="", help="path to plan-output-meta.yaml")
    rp.add_argument("--format", choices=["tree", "json", "md"], default="tree")
    rp.add_argument("--out", default="", help="write to this file instead of stdout")
    rp.add_argument("--all", action="store_true",
                    help="show every status folder (sugar for --status planned,active,archived)")
    rp.add_argument("--status", default="",
                    help="comma list of state folders to display: planned, active, archived "
                         "(default: planned,active). Counting is unaffected — phase "
                         "denominators always see the whole tree")
    rp.add_argument("--watch", type=int, default=0, metavar="SECS",
                    help="re-render on an interval (tree only in practice)")
    rp.add_argument("--stall-minutes", dest="stall_minutes", type=float,
                    default=DEFAULT_STALL_MINUTES,
                    help="flag dispatches open longer than this (default 15)")
    rp.set_defaults(func=cmd_report)

    dp = sub.add_parser("dispatch", help="record a subagent dispatch open/close")
    dp.add_argument("--state-root", required=True)
    dp.add_argument("--event", required=True, choices=["open", "close"])
    dp.add_argument("--agent", required=True)
    dp.add_argument("--epic", default="")
    dp.add_argument("--sprint", default="")
    dp.add_argument("--story", default="")
    dp.add_argument("--session-id", dest="session_id", default=None)
    dp.set_defaults(func=cmd_dispatch)

    si = sub.add_parser("self-install", help="copy this script to --dest, version-guarded")
    si.add_argument("--dest", required=True, help="target path, e.g. {project-root}/_bmad/scripts/pm-status.py")
    si.add_argument("--force", action="store_true", help="overwrite even if dest is same/newer")
    si.set_defaults(func=cmd_self_install)

    sl = sub.add_parser("set-lock", help="write _lock block to a per-epic active file")
    sl.add_argument("--state-root", required=True)
    sl.add_argument("--epic", required=True, help="epic key, e.g. E001")
    sl.add_argument("--session-id", dest="session_id", required=True)
    sl.add_argument("--ttl-minutes", dest="ttl_minutes", type=int, default=30)
    sl.set_defaults(func=cmd_set_lock)

    cl = sub.add_parser("clear-lock", help="remove _lock block from a per-epic active file")
    cl.add_argument("--state-root", required=True)
    cl.add_argument("--epic", required=True, help="epic key, e.g. E001")
    cl.set_defaults(func=cmd_clear_lock)

    ck = sub.add_parser("check-lock", help="check if a per-epic file is free to claim; exit 5 if held")
    ck.add_argument("--state-root", required=True)
    ck.add_argument("--epic", required=True, help="epic key, e.g. E001")
    ck.add_argument("--session-id", dest="session_id", required=True, help="caller's session id")
    ck.set_defaults(func=cmd_check_lock)

    se = sub.add_parser("set-estimate", help="write estimate block to a story, sprint, or epic node")
    se.add_argument("--state-root", required=True, help="path to {implementation_artifacts}/state")
    node_args(se)
    # Range fields (sprint/epic)
    se.add_argument("--man-hours-low", dest="man_hours_low")
    se.add_argument("--man-hours-high", dest="man_hours_high")
    se.add_argument("--hitl-hours-low", dest="hitl_hours_low")
    se.add_argument("--hitl-hours-high", dest="hitl_hours_high")
    se.add_argument("--elapsed-hours-low", "--time-hours-low", dest="elapsed_hours_low")
    se.add_argument("--elapsed-hours-high", "--time-hours-high", dest="elapsed_hours_high")
    se.add_argument("--tokens-k-min", dest="tokens_k_min")
    se.add_argument("--tokens-k-max", dest="tokens_k_max")
    # --cost / --cost-low / --cost-high are declared but SUPPRESSed from --help
    # and rejected in cmd_set_estimate: cost is derived from tokens x rates,
    # never accepted as direct input (see the rejection at the top of
    # cmd_set_estimate). Declaring them here — rather than leaving them
    # unrecognized — turns that rejection into a clear usage error instead of
    # argparse's generic "unrecognized arguments".
    se.add_argument("--cost-low", dest="cost_low", help=argparse.SUPPRESS)
    se.add_argument("--cost-high", dest="cost_high", help=argparse.SUPPRESS)
    # Single-value fields (story)
    se.add_argument("--man-hours", dest="man_hours")
    se.add_argument("--hitl-hours", dest="hitl_hours",
                    help="human attention actually spent supervising (hours)")
    se.add_argument("--elapsed-hours", "--time-hours", dest="elapsed_hours",
                    help="--time-hours is a deprecated alias")
    se.add_argument("--tokens-k", dest="tokens_k_min")  # alias to tokens_k_min for story use
    se.add_argument("--cost", dest="cost", help=argparse.SUPPRESS)
    se.add_argument("--confidence", choices=["low", "medium", "high"])
    se.add_argument("--fix-factor", dest="fix_factor",
                    help="fix multiplier applied; required for the scope/fix split")
    se.add_argument("--scope-ratio", dest="scope_ratio",
                    help="calibrated scope ratio applied (1.0 when cold-start)")
    se.add_argument("--flock", action="store_true", help="acquire exclusive flock before write")
    se.set_defaults(func=cmd_set_estimate)

    sf = sub.add_parser("set-field", help="set a nested field at a dot-path within a node")
    sf.add_argument("--state-root", required=True, help="path to {implementation_artifacts}/state")
    node_args(sf)
    sf.add_argument("--field", required=True, help="dot-path within the node, e.g. 'retrospective.summary'")
    sf.add_argument("--value", required=True, help="string value to set")
    sf.set_defaults(func=cmd_set_field)

    a = sub.add_parser("add-test-run", help="record one executed test command and its exit code")
    a.add_argument("--state-root", required=True, help="path to {implementation_artifacts}/state")
    a.add_argument("--story", required=True)
    a.add_argument("--command", required=True, help="the test command actually executed")
    a.add_argument("--exit-code", dest="exit_code", type=int, required=True)
    a.set_defaults(func=cmd_add_test_run)

    ai = sub.add_parser("append-issue", help="append a BL item to state/issues.yaml")
    ai.add_argument("--state-root", dest="state_root", default="",
                    help="path to {implementation_artifacts}/state (preferred)")
    ai.add_argument("--file", default="",
                    help="compatibility alias for <state-root>/issues.yaml")
    ai.add_argument("--session-id", dest="session_id", default=None)
    ai.add_argument("--key", default="",
                    help="BL-E{nnn}-{nnn}; omit to auto-allocate the next number for "
                         "--epic under a lock. An explicit key that already exists "
                         "exits 2 rather than being silently reassigned.")
    ai.add_argument("--epic", required=True, help="zero-padded epic number, e.g. '001'")
    ai.add_argument("--sprint", default="", help="zero-padded sprint number; empty for epic-level")
    ai.add_argument("--title", required=True)
    ai.add_argument("--source", default=None,
                    help="free-text source, stored verbatim (legacy form; prefer --source-phase)")
    ai.add_argument("--source-phase", dest="source_phase", default=None,
                    help="structured source: the phase, e.g. code-review. With --source-ref it "
                         "DERIVES --source as '{phase} ({ref})', so the two cannot disagree")
    ai.add_argument("--source-ref", dest="source_ref", default=None,
                    help="structured source: the finding or story it points at; no parentheses")
    ai.add_argument("--source-note", dest="source_note", default="",
                    help="structured source: free text appended after the parens")
    ai.add_argument("--severity", required=True, choices=["Low", "Medium", "High", "Critical"])
    ai.add_argument("--description", default="")
    ai.add_argument("--kind", default="defect", choices=list(ISSUE_KINDS),
                    help="defect (default, not written) | spec-change | spec-proposal")
    ai.add_argument("--ref", default="",
                    help="spec kinds only: the docs(spec) commit SHA, or the proposal path")
    ai.add_argument("--allow-duplicate", dest="allow_duplicate", action="store_true",
                    help="append even if an existing item matches this title+epic+"
                         "sprint+source (default: skip and exit 0)")
    ai.set_defaults(func=cmd_append_issue)

    ri = sub.add_parser("resolve-issue",
                        help="resolve an open BL item into issues-resolved.yaml")
    ri.add_argument("--state-root", required=True)
    ri.add_argument("--key", required=True)
    ri.add_argument("--resolution", required=True, choices=list(RESOLUTIONS))
    ri.add_argument("--ref", default=None)
    ri.add_argument("--note", default=None)
    ri.add_argument("--session-id", dest="session_id", default=None)
    ri.add_argument("--cause", default="cli", choices=["cli", "triage", "plan-intake"])
    ri.set_defaults(func=cmd_resolve_issue)

    ui = sub.add_parser("update-issue", help="change an open BL item's severity")
    ui.add_argument("--state-root", required=True)
    ui.add_argument("--key", required=True)
    ui.add_argument("--severity", required=True, choices=["Low", "Medium", "High", "Critical"])
    ui.add_argument("--note", default=None)
    ui.add_argument("--session-id", dest="session_id", default=None)
    ui.add_argument("--cause", default="cli", choices=["cli", "triage", "plan-intake"])
    ui.set_defaults(func=cmd_update_issue)

    pi = sub.add_parser("promote-issue", help="turn open BL items into a new estimated story")
    pi.add_argument("--state-root", required=True)
    pi.add_argument("--artifacts-root", required=True,
                    help="implementation_artifacts root (NOT the state root)")
    pi.add_argument("--key", required=True, action="append", help="repeatable")
    pi.add_argument("--epic", required=True)
    pi.add_argument("--sprint", required=True)
    pi.add_argument("--classification", required=True, choices=list(CLASSIFICATIONS))
    pi.add_argument("--title", default="")
    pi.add_argument("--model", default="")
    pi.add_argument("--token-rates", dest="token_rates", default="")
    pi.add_argument("--session-id", dest="session_id", default=None)
    pi.add_argument("--cause", default="cli", choices=["cli", "triage", "plan-intake"])
    pi.set_defaults(func=cmd_promote_issue)

    si = sub.add_parser("schedule-issue",
                        help="attach open BL items to a story that already exists")
    si.add_argument("--state-root", required=True)
    si.add_argument("--key", required=True, action="append", help="repeatable")
    si.add_argument("--story", required=True, help="an existing story key E{nnn}-S{nn}-{nnn}")
    si.add_argument("--session-id", dest="session_id", default=None)
    si.add_argument("--cause", default="cli", choices=["cli", "triage", "plan-intake"])
    si.set_defaults(func=cmd_schedule_issue)

    au = sub.add_parser("audit-issues", help="structural integrity checks over the backlog")
    au.add_argument("--state-root", required=True)
    au.add_argument("--format", choices=["text", "json"], default="text")
    au.set_defaults(func=cmd_audit_issues)

    rp = sub.add_parser("repair-issue", help="structural repair gated on an audit-issues finding")
    rp.add_argument("--state-root", required=True)
    rp.add_argument("--key", default=None,
                    help="the item; for reseed, any key of the epic; omit with --all-legacy")
    rp.add_argument("--action", required=True,
                    choices=["unschedule", "link", "reseed", "reopen", "normalize-status",
                             "normalize-keys"])
    rp.add_argument("--story", default=None, help="with --action link")
    rp.add_argument("--all-legacy", dest="all_legacy", action="store_true",
                    help="with --action normalize-status: every legacy status in one pass")
    rp.add_argument("--session-id", dest="session_id", default=None)
    rp.add_argument("--cause", default="cli", choices=["cli", "triage", "plan-intake"])
    rp.set_defaults(func=cmd_repair_issue)

    li = sub.add_parser("list-issues", help="list (with filters) open BL items, resolved ones "
                                            "(--resolved), or both (--all, JSON)")
    li.add_argument("--state-root", required=True, help="path to {implementation_artifacts}/state")
    li.add_argument("--epic", help="epic id — accepts 'E001' or '001'")
    li.add_argument("--sprint", help="sprint id — accepts 'S01' or '01'; never matches an epic-level (empty-sprint) item")
    li.add_argument("--severity", action="append", choices=["Low", "Medium", "High", "Critical"],
                    help="filter by severity; repeat to OR multiple severities")
    li.add_argument("--format", choices=["text", "json"], default="text")
    li.add_argument("--status", choices=["backlog", "scheduled"],
                    help="open items with this status")
    li.add_argument("--resolved", action="store_true", help="list issues-resolved.yaml instead")
    li.add_argument("--resolution", choices=list(RESOLUTIONS), help="with --resolved only")
    li.add_argument("--kind", choices=list(ISSUE_KINDS),
                    help="items of this kind; an item without `kind` is a defect")
    li.add_argument("--all", action="store_true",
                    help='JSON {"open": [...], "resolved": [...]} read under one lock')
    li.set_defaults(func=cmd_list_issues)

    mv = sub.add_parser("move-epic", help="move an epic directory between status folders")
    mv.add_argument("--state-root", required=True)
    mv.add_argument("--epic", required=True)
    mv.add_argument("--to", required=True, choices=list(STATUS_DIRS))
    mv.set_defaults(func=cmd_move_epic)

    ae = sub.add_parser("archive-epic", help="alias for move-epic --to archived")
    ae.add_argument("--state-root", required=True)
    ae.add_argument("--epic", required=True)
    ae.set_defaults(func=cmd_move_epic, to="archived")

    up = sub.add_parser("usage", help="sum a session transcript's token usage, by class")
    up.add_argument("transcript", nargs="*",
                    help="transcript .jsonl file(s) or directory(ies); omit to resolve this "
                         "session's own transcript from $" + CLAUDE_SESSION_ENV)
    up.add_argument("--claude-session", dest="claude_session", default="",
                    help="the Claude session id the transcript must belong to (NOT the l3io "
                         "run --session-id); defaults to $" + CLAUDE_SESSION_ENV)
    up.add_argument("--state-root", default="", help="state root, to read events.jsonl")
    up.add_argument("--agent", default="", help="scope to this agent's dispatch bracket")
    up.add_argument("--epic", default="", help="scope to this epic")
    up.add_argument("--sprint", default="", help="scope to this sprint")
    up.add_argument("--story", default="", help="scope to this story")
    up.add_argument("--since", default="", help="ISO timestamp lower bound")
    up.add_argument("--until", default="", help="ISO timestamp upper bound")
    up.add_argument("--allow-unidentified", action="store_true",
                    help="sum a file that cannot be confirmed as this session's transcript")
    up.add_argument("--model", default="", help="also price the total at this model's rates")
    up.add_argument("--token-rates", dest="token_rates", default="",
                    help="JSON overrides for the rate table")
    up.add_argument("--format", choices=["text", "json"], default="text")
    up.set_defaults(func=cmd_usage)

    cal = sub.add_parser("calibration", help="inspect the calibration file")
    cal.add_argument("action", choices=["show", "migrate-metrics", "redrive"])
    cal.add_argument("--state-root", required=True)
    cal.add_argument("--format", choices=["text", "json"], default="text")
    cal.set_defaults(func=cmd_calibration)

    es = sub.add_parser("estimate-story", help="compute and write a story estimate")
    es.add_argument("--state-root", required=True)
    es.add_argument("--story", required=True)
    es.add_argument("--classification", required=True, choices=list(CLASSIFICATIONS))
    es.add_argument("--confidence", choices=["low", "medium", "high"])
    es.add_argument("--model", default="",
                    help="model id to price the derived cost; falls back to DEFAULT_ESTIMATE_MODEL")
    es.add_argument("--token-rates", dest="token_rates", default="",
                    help="JSON object of per-model rate overrides")
    es.set_defaults(func=cmd_estimate_story)

    er = sub.add_parser("estimate-rollup", help="roll child estimates up to a sprint or epic")
    er.add_argument("--state-root", required=True)
    er.add_argument("--epic", required=True)
    er.add_argument("--sprint", default="")
    er.add_argument("--model", default="",
                    help="model id to price the derived cost; falls back to DEFAULT_ESTIMATE_MODEL")
    er.add_argument("--token-rates", dest="token_rates", default="",
                    help="JSON object of per-model rate overrides")
    er.set_defaults(func=cmd_estimate_rollup)

    rt = sub.add_parser("rates", help="print the effective token rate table (read-only)")
    rt.add_argument("--model", default="")
    rt.add_argument("--token-rates", dest="token_rates", default="",
                    help="JSON object of per-model rate overrides")
    rt.set_defaults(func=cmd_rates)

    ar = sub.add_parser("adr-reserve",
                        help="reserve N sequential ADR numbers under a lock, before dispatch")
    ar.add_argument("--state-root", required=True)
    ar.add_argument("--epic", required=True)
    ar.add_argument("--slug", required=True)
    ar.add_argument("--count", type=int, default=1)
    ar.add_argument("--adr-dir", dest="adr_dir", default="",
                    help="the one ADR home to scan (default: <git top-level>/docs/adr)")
    ar.set_defaults(func=cmd_adr_reserve)

    nt = sub.add_parser("notice",
                        help="record a one-time-ever advisory notice; exit 1 if already shown")
    nt.add_argument("--state-root", required=True)
    nt.add_argument("--key", required=True)
    nt.set_defaults(func=cmd_notice)

    p.add_argument("--version", action="version", version=f"pm-status.py {PM_STATUS_VERSION}")
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
