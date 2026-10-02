#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["ruamel.yaml>=0.18"]
# ///
"""
audit-backlog.py -- heuristic audit of open l3io-pm backlog items. Read-only.

Why this exists
---------------
A backlog nothing ever pruned is full of findings that were fixed long ago. This
script proposes, with evidence, which open items look resolved: a bmad-defer: marker
that is gone, a file that no longer exists, a duplicate, and for everything else the
exact place the finding was recorded, so a reviewer checks one pointer instead of
searching. Every verdict is a proposal; doctor `triage` asks before acting. Spec items
(kind spec-change / spec-proposal) are skipped: triage's spec pass handles them.

Structural integrity lives in `pm-status.py audit-issues`. This script is the
single-consumer, heuristic half, so it ships in doctor's own scripts/ (ADR-0001), and
it reads items only through `pm-status.py list-issues --all` so issue-file layout
knowledge stays in one place.

Usage
-----
  audit-backlog.py --pm-status P --state-root S --artifacts-root A --project-root R
                   [--format {text,json}]
Exit 0 on success -- verdicts are proposals, not failures. Exit 2 when the items
cannot be listed.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys

CODE_MARKER_RE = re.compile(r"code-marker \(?([^():]+):(\d+)\)?")
REVIEW_RE = re.compile(r"code-review \((E(\d{3})-S(\d{2})-\d{3})\)")
PHASE_RE = re.compile(r"^([A-Za-z][\w-]*) \(([^()]+)\)$")
SEE_RE = re.compile(r"^See (\S+)")
# Two shapes the four regexes above never accepted, both produced by ordinary use.
# On a real 517-item backlog they were 70% of it, and every one came back
# `evidence: untraceable` -- reported upstream as "0 candidates", which reads like a
# clean bill rather than blindness. CLOSURE_REVIEW_RE takes a 2-part SPRINT key, where
# REVIEW_RE requires the literal `code-review` and a 3-part story key.
CLOSURE_REVIEW_RE = re.compile(r"closure review \((E(\d{3})-S(\d{2}))\)")
# A story key at the START, with any free text after it. Anchoring on `$` matched only a
# bare key, which measurement on a real backlog showed is the rare case: the dominant shape is
# `E004-S03-001 development`, `E004-S03-001 implementation`, `E004-S03-001 code review` and a
# long tail of similar, which the anchored form rejected on the trailing word alone. The
# one-hit-or-nothing lookup below is what keeps this safe to loosen.
BARE_STORY_RE = re.compile(r"^(E(\d{3})-S(\d{2})-\d{3})\b")
KEY_RE = re.compile(r"^BL-E\d{3}-(\d{3})$")
SEVERITY_RANK = {"Low": 0, "Medium": 1, "High": 2, "Critical": 3}

# The mass-missing guard exists to catch a project-root mismatch (the script pointed at
# the wrong checkout, so every code-marker path resolves to nothing) rather than the
# ordinary case of one or two markers whose files were legitimately deleted. With fewer
# than this many marker items there's no sample to judge "mismatched root" from, so a
# single missing file must fall through to its normal obsolete-candidate verdict instead
# of being suppressed as "suspect".
MIN_MARKERS_FOR_MASS_MISSING_GUARD = 3


def norm(text) -> str:
    return " ".join(str(text).split()).casefold()


def epic_of(item) -> str:
    e = str(item.get("epic", "")).strip().lstrip("Ee")
    return f"{int(e):03d}" if e.isdigit() else e


def suffix(key) -> int:
    m = KEY_RE.match(str(key))
    return int(m.group(1)) if m else 0


def rank(item) -> int:
    return SEVERITY_RANK.get(str(item.get("severity", "")), 0)


def load_items(pm_status, state_root):
    proc = subprocess.run([sys.executable, pm_status, "list-issues", "--state-root", state_root,
                           "--all", "--format", "json"], capture_output=True, check=False, text=True)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or f"list-issues exited {proc.returncode}")
    data = json.loads(proc.stdout)
    return data["open"], data["resolved"]


def verdict(item, kind, basis, evidence, pointer=None, ref=None) -> dict:
    return {"key": item.get("key"), "verdict": kind, "basis": basis, "evidence": evidence,
            "pointer": pointer, "ref": ref, "origin_archived": bool(item.get("origin_archived"))}


def marker_line(path, title):
    """Line number of a line carrying both `bmad-defer:` and the item's title text."""
    needle = norm(str(title).rstrip(" .;,"))
    with open(path, encoding="utf-8", errors="replace") as fh:
        for n, line in enumerate(fh, 1):
            low = norm(line)
            if "bmad-defer:" in low and needle and needle in low:
                return n
    return None


def duplicate_of(item, open_items, resolved):
    e, t = epic_of(item), norm(item.get("title", ""))
    for other in open_items:
        if other is item or epic_of(other) != e or norm(other.get("title", "")) != t:
            continue
        if suffix(other.get("key")) < suffix(item.get("key")) and rank(item) <= rank(other):
            return other.get("key"), (f"same title and epic as older open {other.get('key')} "
                                      f"({other.get('severity')})")
    for r in resolved:
        if str(r.get("resolution")) not in ("wontfix", "obsolete"):
            continue
        if epic_of(r) == e and norm(r.get("title", "")) == t and rank(item) <= rank(r):
            return r.get("key"), (f"same title and epic as {r.get('key')}, resolved "
                                  f"{r.get('resolution')} at {r.get('severity')}")
    return None


def _existing(path, *bases):
    if os.path.isabs(path):
        return path if os.path.isfile(path) else None
    for b in bases:
        p = os.path.join(b, path)
        if os.path.isfile(p):
            return p
    return None


def closure_dir(artifacts_root, item) -> str:
    e = epic_of(item)
    s = str(item.get("sprint", "") or "").strip().lstrip("Ss")
    if s.isdigit():
        return os.path.join(artifacts_root, f"epic-{e}", f"sprint-{int(s):02d}", "closure")
    return os.path.join(artifacts_root, f"epic-{e}", "epic-closure")


def _resolve_phase_ref(phase, ref, item, artifacts_root):
    """Resolve a STRUCTURED source. Same closure dir and same one-hit-or-nothing rule the
    parsed branches use -- the difference is only that phase and ref arrived as fields rather
    than being recovered from a string."""
    d = closure_dir(artifacts_root, item)
    if not os.path.isdir(d):
        return None
    ref_re = re.compile(rf"(?<![\w-]){re.escape(ref)}(?![\w-])")
    tokens = {phase.casefold(), phase.casefold().removeprefix("epic-")}
    hits = []
    for name in sorted(os.listdir(d)):
        if not name.endswith(".md"):
            continue
        p = os.path.join(d, name)
        if ref in name:
            hits.append(p)
            continue
        # Prefer a file whose name matches the phase, as the phase branch does; fall back to
        # any file in the closure dir, since a structured ref is unambiguous on its own.
        with open(p, encoding="utf-8", errors="replace") as fh:
            for n, line in enumerate(fh, 1):
                if ref_re.search(line):
                    hits.append(f"{p}:{n}")
                    break
    if len(hits) == 1:
        return hits[0]
    named = [h for h in hits if any(t in os.path.basename(h).casefold() for t in tokens)]
    return named[0] if len(named) == 1 else None


def pointer_for(item, project_root, artifacts_root):

    # An item written with `append-issue --source-phase` carries its phase and ref as fields,
    # so there is nothing to parse. The regex chain below stays for the items written before
    # that existed -- on one real backlog, 468 of 517 -- and is not going away: 76 of those
    # point at artifacts that were never written, so no reader will ever resolve them.
    phase, ref = (str(item.get("source_phase", "") or "").strip(),
                  str(item.get("source_ref", "") or "").strip())
    if phase and ref:
        return _resolve_phase_ref(phase, ref, item, artifacts_root)

    m = SEE_RE.match(str(item.get("description", "") or "").strip())
    if m:
        p = _existing(m.group(1), project_root, artifacts_root)
        if p:
            return p
    src = str(item.get("source", ""))
    m = REVIEW_RE.search(src)
    if m:
        p = os.path.join(artifacts_root, f"epic-{m.group(2)}", f"sprint-{m.group(3)}",
                         "closure", f"review-{m.group(1)}.md")
        return p if os.path.isfile(p) else None
    m = CLOSURE_REVIEW_RE.search(src)
    if m:
        p = os.path.join(artifacts_root, f"epic-{m.group(2)}", f"sprint-{m.group(3)}",
                         "closure", f"review-sprint-{m.group(1)}.md")
        return p if os.path.isfile(p) else None
    m = BARE_STORY_RE.match(src.strip())
    if m:
        # `append-issue --source <story-key>` is what normal use produces, and triage's
        # repair table already calls this field `{story}`.
        #
        # Look in the NAME and in the BODY, one unambiguous hit or nothing -- the same rule
        # the phase branch below uses. Name-only matching was the first attempt and it barely
        # reached anything: measured on a real tree, closure artifacts are named after the
        # KIND (retrospective.md, closure-report.md, redteam-report.md) and only 6 of 39
        # carried a story key in the name, so 31 findings sat in bodies the lookup never
        # opened. Two sibling branches resolving by different strategies is what hid that.
        #
        # Ambiguity is across FILES, not across lines: a key repeated inside one artifact is
        # still one hit, so the loop stops at the first line that matches in each file.
        key = m.group(1)
        d = os.path.join(artifacts_root, f"epic-{m.group(2)}", f"sprint-{m.group(3)}", "closure")
        if os.path.isdir(d):
            key_re = re.compile(rf"(?<![\w-]){re.escape(key)}(?![\w-])")
            hits = []
            for name in sorted(os.listdir(d)):
                if not name.endswith(".md"):
                    continue
                p = os.path.join(d, name)
                if key in name:
                    hits.append(p)
                    continue
                with open(p, encoding="utf-8", errors="replace") as fh:
                    for n, line in enumerate(fh, 1):
                        if key_re.search(line):
                            hits.append(f"{p}:{n}")
                            break
            if len(hits) == 1:
                return hits[0]
        return None
    m = PHASE_RE.match(src.strip())
    if not m:
        return None
    phase, fid = m.group(1).casefold(), m.group(2)
    tokens = {phase, phase.removeprefix("epic-")}
    d = closure_dir(artifacts_root, item)
    hits = []
    if os.path.isdir(d):
        id_re = re.compile(rf"(?<![\w-]){re.escape(fid)}(?![\w-])")
        for name in sorted(os.listdir(d)):
            if not name.endswith(".md") or not any(t in name.casefold() for t in tokens):
                continue
            with open(os.path.join(d, name), encoding="utf-8", errors="replace") as fh:
                for n, line in enumerate(fh, 1):
                    if id_re.search(line):
                        hits.append(f"{os.path.join(d, name)}:{n}")
    return hits[0] if len(hits) == 1 else None


def audit(open_items, resolved, project_root, artifacts_root):
    # Spec items (docs/adr/0004) are confirmed or rejected in triage's spec pass, never here.
    open_items = [it for it in open_items if str(it.get("kind") or "defect") == "defect"]
    verdicts, warnings = [], []
    markers = {}
    for it in open_items:
        m = CODE_MARKER_RE.search(str(it.get("source", "")))
        if m:
            markers[it.get("key")] = (m.group(1), os.path.join(project_root, m.group(1)))
    missing = [k for k, (_, p) in markers.items() if not os.path.isfile(p)]
    suspect = (len(markers) >= MIN_MARKERS_FOR_MASS_MISSING_GUARD
               and len(missing) * 2 > len(markers))
    if suspect:
        warnings.append(f"project-root suspect: {len(missing)} of {len(markers)} code-marker "
                        f"files are missing under {project_root}; no obsolete-candidate "
                        f"verdicts emitted")
    for it in open_items:
        key = it.get("key")
        if key in markers:
            rel, path = markers[key]
            if not os.path.isfile(path):
                if suspect:
                    verdicts.append(verdict(it, "needs-review", "mechanical",
                                            f"{rel} not found (project-root suspect)", rel))
                else:
                    verdicts.append(verdict(it, "obsolete-candidate", "mechanical",
                                            f"{rel} no longer exists", rel))
                continue
            line = marker_line(path, it.get("title", ""))
            if line is None:
                verdicts.append(verdict(it, "fixed-candidate", "mechanical",
                                        f"no bmad-defer: line containing the marker text in {rel}",
                                        rel))
            else:
                verdicts.append(verdict(it, "open", "mechanical",
                                        f"marker present at {rel}:{line}", f"{rel}:{line}"))
            continue
        dup = duplicate_of(it, open_items, resolved)
        if dup:
            verdicts.append(verdict(it, "duplicate-candidate", "mechanical", dup[1], ref=dup[0]))
            continue
        ptr = pointer_for(it, project_root, artifacts_root)
        verdicts.append(verdict(it, "needs-review", "pointer" if ptr else "none",
                                f"finding recorded at {ptr}" if ptr else "untraceable", ptr))
    return verdicts, warnings


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="audit-backlog.py", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pm-status", required=True, help="path to pm-status.py")
    ap.add_argument("--state-root", required=True)
    ap.add_argument("--artifacts-root", required=True)
    ap.add_argument("--project-root", required=True)
    ap.add_argument("--format", choices=["text", "json"], default="text")
    a = ap.parse_args(argv)
    try:
        open_items, resolved = load_items(a.pm_status, a.state_root)
    except (RuntimeError, ValueError, KeyError) as e:
        sys.stderr.write(f"audit-backlog.py: {e}\n")
        return 2
    verdicts, warnings = audit(open_items, resolved, a.project_root, a.artifacts_root)
    if a.format == "json":
        sys.stdout.write(json.dumps({"verdicts": verdicts, "warnings": warnings}, indent=2) + "\n")
        return 0
    for w in warnings:
        sys.stdout.write(f"WARN {w}\n")
    for v in verdicts:
        tag = " (origin archived)" if v["origin_archived"] else ""
        sys.stdout.write(f"{v['key']:<13} {v['verdict']:<20} {v['evidence']}{tag}\n")
    if not verdicts:
        sys.stdout.write("audit-backlog: no open items\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
