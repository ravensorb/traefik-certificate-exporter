#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["ruamel.yaml>=0.18"]
# ///
"""
read-l3io-flat.py -- read this package's LEGACY flat sprint-status.yaml into records.

The legacy layout is one `epics:` LIST with sprints nested inside each epic and stories
nested inside each sprint. Do not confuse it with BMad's own sprint-status.yaml, which is
a `development_status:` MAPPING at the same default path -- read-bmad-flat.py handles that
one, and detect-layout.py --classify decides which is present.

Reader contract: pure. No writes, no locking, no interaction, and NO refusal on an empty
result. A file this reader cannot make sense of yields zero records, which is a fact for
the engine's gate to act on -- not a judgement for the reader to make.

Usage:  read-l3io-flat.py --file PATH [--format json]
Exit 0 -- parsed (zero records is success)
Exit 1 -- the file does not exist
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


def read(path: Path) -> list:
    """Parse a legacy flat status file into normalised records."""
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
    if not isinstance(data, dict) or not isinstance(data.get("epics"), list):
        return []

    name = Path(path).name
    out = []
    for epic in data["epics"]:
        if not isinstance(epic, dict):
            continue
        ekey = str(epic.get("key", "")).strip()
        if not ekey:
            continue
        out.append(sr.make_record(
            "epic", ekey, str(epic.get("status", "backlog")),
            str(epic.get("title", "")), f"{name}:epics[{ekey}]",
            extras=sr.collect_extras(epic)))

        for sprint in epic.get("sprints") or []:
            if not isinstance(sprint, dict):
                continue
            skey = str(sprint.get("key", "")).strip()
            if not skey:
                continue
            out.append(sr.make_record(
                "sprint", f"{ekey}-{skey}", str(sprint.get("status", "backlog")),
                str(sprint.get("title", "")), f"{name}:epics[{ekey}].sprints[{skey}]",
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
                    f"{name}:epics[{ekey}].sprints[{skey}].stories[{stkey}]",
                    classification=str(story.get("classification", "")).strip() or None,
                    extras=sr.collect_extras(story)))

    return sr.dedupe(out)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="read a legacy flat sprint-status.yaml")
    parser.add_argument("--file", required=True, help="path to sprint-status.yaml")
    parser.add_argument("--format", choices=["json"], default="json")
    args = parser.parse_args(argv)

    p = Path(args.file)
    if not p.is_file():
        sys.stderr.write(f"read-l3io-flat.py: no such file: {p}\n")
        return 1
    json.dump(read(p), sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
