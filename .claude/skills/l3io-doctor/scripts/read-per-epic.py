#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["ruamel.yaml>=0.18"]
# ///
"""
read-per-epic.py -- read the legacy per-epic layout at {project-root}/_bmad/state/.

One YAML file per epic, each a bare epic node with `sprints:` nested inside it and
`stories:` inside those. Files are read in sorted order so the result is deterministic.

An unparseable file is SKIPPED, not fatal: one corrupt epic must not hide the other nine
from the migration plan the user is about to confirm.

Reader contract: pure. No writes, no refusal on an empty result.

Usage:  read-per-epic.py --dir PATH [--format json]
Exit 0 -- parsed (zero records is success)
Exit 1 -- the directory does not exist
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from pathlib import Path

_HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location(
    "state_record", os.path.join(_HERE, "state-record.py"))
sr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sr)


def _read_one(path: Path) -> list:
    from ruamel.yaml import YAML
    from ruamel.yaml.error import YAMLError

    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    if not text.strip():
        return []
    try:
        epic = YAML(typ="safe").load(text)
    except YAMLError:
        return []
    if not isinstance(epic, dict):
        return []
    ekey = str(epic.get("key", "")).strip()
    if not ekey:
        return []

    name = path.name
    out = [sr.make_record(
        "epic", ekey, str(epic.get("status", "backlog")),
        str(epic.get("title", "")), f"{name}:{ekey}",
        extras=sr.collect_extras(epic))]

    for sprint in epic.get("sprints") or []:
        if not isinstance(sprint, dict):
            continue
        skey = str(sprint.get("key", "")).strip()
        if not skey:
            continue
        out.append(sr.make_record(
            "sprint", f"{ekey}-{skey}", str(sprint.get("status", "backlog")),
            str(sprint.get("title", "")), f"{name}:{ekey}.sprints[{skey}]",
            extras=sr.collect_extras(sprint)))
        for story in sprint.get("stories") or []:
            if not isinstance(story, dict):
                continue
            stkey = str(story.get("key", "")).strip()
            if not stkey:
                continue
            out.append(sr.make_record(
                "story", stkey, str(story.get("status", "backlog")),
                str(story.get("title", "")),
                f"{name}:{ekey}.sprints[{skey}].stories[{stkey}]",
                classification=str(story.get("classification", "")).strip() or None,
                extras=sr.collect_extras(story)))
    return out


def read(state_dir: Path) -> list:
    """Parse every epic file under state_dir into normalised records."""
    d = Path(state_dir)
    if not d.is_dir():
        return []
    out = []
    for path in sorted(d.glob("*.yaml")):
        out.extend(_read_one(path))
    return sr.dedupe(out)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="read the legacy per-epic state layout")
    parser.add_argument("--dir", required=True, help="the _bmad/state directory")
    parser.add_argument("--format", choices=["json"], default="json")
    args = parser.parse_args(argv)

    d = Path(args.dir)
    if not d.is_dir():
        sys.stderr.write(f"read-per-epic.py: no such directory: {d}\n")
        return 1
    json.dump(read(d), sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
