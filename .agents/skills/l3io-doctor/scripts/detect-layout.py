#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["ruamel.yaml>=0.18"]
# ///
"""
detect-layout.py -- detect a project holding both state layouts at once. Read-only.

Why this exists
----------------
`bmad-build` writes a flat `sprint-status.yaml` under the artifact root; this package's PM
skills read and write a sharded `state/` tree under the same root. Both default to the same
`{implementation_artifacts}` value, so a project can end up with both writers active at once,
each blind to the other's changes. `bmad-build` only writes the flat file when it already
exists (bmm's `step-03-implement.md:27`), so the collision is conditional -- once the flat
file is gone (migrated or deleted), the second writer stops on its own.

`migrate-state` resolves this by renaming the flat file to `sprint-status.yaml.legacy`, a name
this check does not match. Proving that a post-migration project reads clean -- not just that
a colliding one is flagged -- is the load-bearing case in this script's test suite: a detector
that still fires after the fix becomes permanent noise people learn to ignore.

A shell snippet inside a step file cannot be unit-tested, so the decision lives here and
`steps/health-check.md` only calls it and interprets the exit code.

Usage
-----
  detect-layout.py --artifacts DIR

Exit 0 -- no collision: only one layout present, neither present, or the flat file has
          already been migrated to its `.legacy` form.
Exit 1 -- both a flat sprint-status.yaml and a sharded state/ tree exist under DIR; prints a
          `layout-collision: ...` line naming both paths.
Exit 3 -- --classify only: the flat sprint-status.yaml carries BMad's `development_status:`
          mapping, not this package's `epics:` list. Deleting or migrating it as if it were
          ours would destroy the file bmad-sprint-planning, bmad-build and bmad-retrospective
          all read. argparse owns exit 2, which is why this is 3.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


def classify_flat(path: Path) -> str:
    """Classify a flat sprint-status.yaml by its top-level schema.

    BMad's own file (bmad-sprint-planning/sprint-status-template.yaml) is a
    `development_status:` MAPPING of node-id -> status. This package's legacy flat
    file is an `epics:` LIST. They share this filename and default directory, so the
    discriminator must be the schema, never the path.

    Returns 'bmad', 'l3io', 'empty', or 'unreadable'. Never raises.
    """
    from ruamel.yaml import YAML
    from ruamel.yaml.error import YAMLError

    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return "unreadable"
    if not text.strip():
        return "empty"
    try:
        data = YAML(typ="safe").load(text)
    except YAMLError:
        return "unreadable"
    if not isinstance(data, dict):
        return "unreadable"
    if isinstance(data.get("development_status"), dict):
        return "bmad"
    if isinstance(data.get("epics"), list):
        return "l3io"
    return "unreadable"


def detect(artifacts: Path) -> tuple[int, str]:
    """Return (exit_code, message). message is empty when there is no collision."""
    flat = artifacts / "sprint-status.yaml"
    sharded = artifacts / "state"
    if flat.is_file() and sharded.is_dir():
        return 1, f"layout-collision: both {flat} and {sharded}/ exist\n"
    return 0, ""


def reachability(artifacts: Path, project_root: Path) -> dict:
    """Is the configured state tree the one this project actually has, and is it tracked?

    Two failures that both look like "no state" to a caller that only checks the configured
    path, and that a confidently-empty report turns into a wrong answer rather than a refusal:

      orphaned  -- a state tree exists somewhere else, because `implementation_artifacts` was
                   repointed. The old tree still holds the history.
      untracked -- the state tree is on disk but git ignores it, so it is one `git clean` from
                   gone and invisible to every other clone.

    Read-only, and never raises: a missing git, a non-repo, or an unreadable tree all report
    what could be established rather than failing the caller.

    This lives here because two step files already carried the orphan probe as an inline shell
    pair, with a comment asking the next person to keep them in sync -- and a third copy was
    about to be added to the health check. One tested implementation, three callers.
    """
    art, root = Path(artifacts), Path(project_root)
    configured = art / "state"
    out = {"configured": str(configured), "configured_exists": configured.is_dir(),
           "orphaned": [], "untracked": False, "git_available": False}

    def _git(*a):
        try:
            r = subprocess.run(["git", "-C", str(root), *a], capture_output=True, check=False,
                               text=True, timeout=30)
            return r
        except (OSError, subprocess.SubprocessError):
            return None

    probe = _git("rev-parse", "--is-inside-work-tree")
    out["git_available"] = bool(probe and probe.returncode == 0
                                and probe.stdout.strip() == "true")

    # Tracked state trees anywhere in the repo, plus untracked ones on disk. Both matter: a
    # repointed artifacts dir leaves the old tree tracked, while a fresh one may not be.
    found = set()
    if out["git_available"]:
        ls = _git("ls-files", "--", "*/state/active/epic-*/epic.yaml",
                  "state/active/epic-*/epic.yaml")
        if ls and ls.returncode == 0:
            for line in ls.stdout.splitlines():
                p = (root / line).resolve()
                # .../state/active/epic-NNN/epic.yaml -> .../state
                found.add(p.parent.parent.parent)
    try:
        for d in root.glob("**/state/active"):
            if d.is_dir():
                found.add(d.parent.resolve())
    except OSError:
        pass

    try:
        conf_resolved = configured.resolve()
    except OSError:
        conf_resolved = configured
    out["orphaned"] = sorted(str(p) for p in found if p != conf_resolved)

    if out["configured_exists"] and out["git_available"]:
        ci = _git("check-ignore", "-q", str(configured))
        out["untracked"] = bool(ci and ci.returncode == 0)

    return out


def main(argv: list[str] | None = None) -> int:

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--artifacts", required=True,
        help="{implementation_artifacts} directory to check for the flat file and state/ tree",
    )
    parser.add_argument(
        "--classify", action="store_true",
        help="classify the flat sprint-status.yaml by schema instead of checking for a collision",
    )
    parser.add_argument(
        "--reachability", action="store_true",
        help="report state trees outside --artifacts, and whether the configured one is gitignored",
    )
    parser.add_argument("--project-root", help="required with --reachability")
    parser.add_argument("--format", choices=["text", "json"], default="text")
    args = parser.parse_args(argv)

    if args.reachability:
        if not args.project_root:
            parser.error("--reachability requires --project-root")
        r = reachability(Path(args.artifacts), Path(args.project_root))
        if args.format == "json":
            sys.stdout.write(json.dumps(r, indent=2) + "\n")
        else:
            for p in r["orphaned"]:
                sys.stdout.write(f"orphaned-state: {p}\n")
            if r["untracked"]:
                sys.stdout.write(f"untracked-state: {r['configured']} is gitignored\n")
            if not r["orphaned"] and not r["untracked"]:
                sys.stdout.write("state-reachability: ok\n")
        return 4 if (r["orphaned"] or r["untracked"]) else 0


    if args.classify:
        flat = Path(args.artifacts) / "sprint-status.yaml"
        if not flat.is_file():
            sys.stdout.write("flat-schema: absent\n")
            return 0
        schema = classify_flat(flat)
        sys.stdout.write(f"flat-schema: {schema}\n")
        return 3 if schema == "bmad" else 0

    code, message = detect(Path(args.artifacts))
    if message:
        sys.stdout.write(message)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
