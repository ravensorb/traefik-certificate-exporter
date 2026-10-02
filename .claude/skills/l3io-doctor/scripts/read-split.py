#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["ruamel.yaml>=0.18"]
# ///
"""
read-split.py -- read the split three-file status layout into records.

The split layout partitions the SAME `epics:` list schema as the legacy flat file across
three files by status:

    sprint-status.yaml            active
    sprint-status-backlog.yaml    backlog
    sprint-status-archived.yaml   done

So this reader does not parse anything itself -- it composes read-l3io-flat.py and owns
only two decisions: WHICH files, and joining them under one dedupe rule. A second parser
for the same schema is the copy that drifts.

Every file is optional; a project may carry any subset.

Reader contract: pure. No writes, no refusal on an empty result.

Usage:  read-split.py --dir PATH [--format json]
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


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, os.path.join(_HERE, filename))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sr = _load("state_record", "state-record.py")
flat = _load("read_l3io_flat", "read-l3io-flat.py")

SPLIT_FILES = (
    "sprint-status.yaml",
    "sprint-status-backlog.yaml",
    "sprint-status-archived.yaml",
)


def read(artifacts_dir: Path) -> list:
    """Parse every present split file into one deduped record list."""
    d = Path(artifacts_dir)
    if not d.is_dir():
        return []
    out = []
    for name in SPLIT_FILES:
        p = d / name
        if p.is_file():
            out.extend(flat.read(p))
    return sr.dedupe(out)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="read the split three-file status layout")
    parser.add_argument("--dir", required=True,
                        help="the implementation_artifacts directory")
    parser.add_argument("--format", choices=["json"], default="json")
    args = parser.parse_args(argv)

    d = Path(args.dir)
    if not d.is_dir():
        sys.stderr.write(f"read-split.py: no such directory: {d}\n")
        return 1
    json.dump(read(d), sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
