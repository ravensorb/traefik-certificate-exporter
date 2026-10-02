#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["ruamel.yaml>=0.18"]
# ///
"""
read-bmad-flat.py -- read BASE BMAD's sprint-status.yaml into records.

This is the file `bmad-sprint-planning`, `bmad-build` and `bmad-retrospective` all read.
Its schema (bmad-sprint-planning/sprint-status-template.yaml:53-66) is a flat
`development_status:` MAPPING of node id to status, with two id shapes:

    development_status:
      epic-1: backlog                  # an epic
      1-1-user-authentication: done    # epic 1, story 1

There is NO sprint concept in this schema. Every story emitted here is keyed into sprint
S01, and no sprint records are produced -- the engine creates the sprint node from the
story's own path. Reconstructing real sprint boundaries needs story artifacts, which is
read-artifacts.py's job, and those nodes are marked `origin: inferred`.

Statuses are MAPPED from a table, never guessed: an id whose status is not one this
package recognises is DROPPED, because calibration would consume a wrong status as a real
sample. An epic has no `review`/`ready-for-dev` state, so those fold to the nearest epic
status rather than being discarded.

Reader contract: pure. No writes, no refusal on an empty result.

Usage:  read-bmad-flat.py --file PATH [--format json]
Exit 0 -- parsed (zero records is success)
Exit 1 -- the file does not exist
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import sys
from pathlib import Path

_HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location(
    "state_record", os.path.join(_HERE, "state-record.py"))
sr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sr)

_EPIC_ID = re.compile(r"^epic-(\d+)$")
_STORY_ID = re.compile(r"^(\d+)-(\d+)-(.+)$")

_STORY_STATUS_MAP = {
    "backlog": "backlog",
    "ready-for-dev": "ready-for-dev",
    "in-progress": "in-progress",
    "review": "review",
    "done": "done",
}
_EPIC_STATUS_MAP = {
    "backlog": "backlog",
    "ready-for-dev": "backlog",
    "in-progress": "in-progress",
    "review": "in-progress",
    "done": "done",
}


def parse_id(node_id: str):
    """Classify a BMad development_status key. Returns (kind, our_key) or None."""
    node_id = (node_id or "").strip()
    m = _EPIC_ID.match(node_id)
    if m:
        return "epic", f"E{int(m.group(1)):03d}"
    m = _STORY_ID.match(node_id)
    if m:
        epic_n, story_n = int(m.group(1)), int(m.group(2))
        return "story", f"E{epic_n:03d}-S01-{story_n:03d}"
    return None


def _title_from_slug(node_id: str) -> str:
    m = _STORY_ID.match((node_id or "").strip())
    if not m:
        return ""
    return m.group(3).replace("-", " ").replace("_", " ").strip().capitalize()


def read(path: Path) -> list:
    from ruamel.yaml import YAML
    from ruamel.yaml.error import YAMLError

    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        return []
    if not text.strip():
        return []
    try:
        data = YAML(typ="safe").load(text)
    except YAMLError:
        return []
    if not isinstance(data, dict):
        return []
    status_map = data.get("development_status")
    if not isinstance(status_map, dict):
        return []

    name = Path(path).name
    out = []
    for node_id, raw_status in status_map.items():
        parsed = parse_id(str(node_id))
        if parsed is None:
            continue
        kind, key = parsed
        raw = str(raw_status).strip()
        table = _EPIC_STATUS_MAP if kind == "epic" else _STORY_STATUS_MAP
        if raw not in table:
            continue
        out.append(sr.make_record(
            kind, key, table[raw],
            _title_from_slug(str(node_id)) if kind == "story" else "",
            f"{name}:development_status[{node_id}]"))

    return sr.dedupe(out)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="read base BMad's sprint-status.yaml")
    parser.add_argument("--file", required=True)
    parser.add_argument("--format", choices=["json"], default="json")
    args = parser.parse_args(argv)

    p = Path(args.file)
    if not p.is_file():
        sys.stderr.write(f"read-bmad-flat.py: no such file: {p}\n")
        return 1
    json.dump(read(p), sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
