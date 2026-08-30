#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml"]
# ///
"""
Manage the sync-state.yaml ID mapping table for l3io-pm-sync.

Usage:
  uv run sync-state.py <project-root> list
  uv run sync-state.py <project-root> get <bmad-key>
  uv run sync-state.py <project-root> get-remote <remote-id>
  uv run sync-state.py <project-root> upsert -          # read JSON from stdin
  uv run sync-state.py <project-root> upsert @<file>    # read JSON from file
  uv run sync-state.py <project-root> update-hash <bmad-key> <hash> [<iso-timestamp>]
  uv run sync-state.py <project-root> remove <bmad-key>

All commands output JSON to stdout. Errors go to stderr with non-zero exit code.
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml


STATE_FILE = "_bmad/sync-state.yaml"


def load_state(project_root: Path) -> dict:
    state_path = project_root / STATE_FILE
    if not state_path.exists():
        return {"version": 1, "last_sync": None, "mappings": []}
    with state_path.open() as f:
        data = yaml.safe_load(f) or {}
    if "mappings" not in data:
        data["mappings"] = []
    return data


def save_state(project_root: Path, state: dict) -> None:
    state_path = project_root / STATE_FILE
    state_path.parent.mkdir(parents=True, exist_ok=True)
    with state_path.open("w") as f:
        yaml.dump(state, f, default_flow_style=False, allow_unicode=True, sort_keys=False)


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def cmd_list(project_root: Path, _args: list[str]) -> int:
    state = load_state(project_root)
    print(json.dumps(state["mappings"], indent=2))
    return 0


def cmd_get(project_root: Path, args: list[str]) -> int:
    if not args:
        print("ERROR: get requires <bmad-key>", file=sys.stderr)
        return 1
    bmad_key = args[0]
    state = load_state(project_root)
    for entry in state["mappings"]:
        if entry.get("bmad_key") == bmad_key:
            print(json.dumps(entry, indent=2))
            return 0
    print(f"ERROR: No mapping found for bmad_key={bmad_key}", file=sys.stderr)
    return 1


def cmd_get_remote(project_root: Path, args: list[str]) -> int:
    if not args:
        print("ERROR: get-remote requires <remote-id>", file=sys.stderr)
        return 1
    remote_id = str(args[0])
    state = load_state(project_root)
    for entry in state["mappings"]:
        if str(entry.get("remote_id", "")) == remote_id:
            print(json.dumps(entry, indent=2))
            return 0
    print(f"ERROR: No mapping found for remote_id={remote_id}", file=sys.stderr)
    return 1


def cmd_upsert(project_root: Path, args: list[str]) -> int:
    if not args:
        print("ERROR: upsert requires '-' (stdin), '@<file>' (file path), or a JSON string", file=sys.stderr)
        return 1
    source = args[0]
    try:
        if source == "-":
            raw = sys.stdin.read()
        elif source.startswith("@"):
            file_path = Path(source[1:])
            if not file_path.exists():
                print(f"ERROR: JSON file not found: {file_path}", file=sys.stderr)
                return 1
            raw = file_path.read_text(encoding="utf-8")
        else:
            raw = source
        entry = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"ERROR: Invalid JSON: {e}", file=sys.stderr)
        return 1

    if "bmad_key" not in entry:
        print("ERROR: JSON entry must have a 'bmad_key' field", file=sys.stderr)
        return 1

    state = load_state(project_root)
    bmad_key = entry["bmad_key"]

    for i, existing in enumerate(state["mappings"]):
        if existing.get("bmad_key") == bmad_key:
            state["mappings"][i] = entry
            save_state(project_root, state)
            print(json.dumps({"action": "updated", "bmad_key": bmad_key}))
            return 0

    state["mappings"].append(entry)
    save_state(project_root, state)
    print(json.dumps({"action": "inserted", "bmad_key": bmad_key}))
    return 0


def cmd_update_hash(project_root: Path, args: list[str]) -> int:
    if len(args) < 2:
        print(
            "ERROR: update-hash requires <bmad-key> <hash> [<iso-timestamp>]",
            file=sys.stderr,
        )
        return 1
    bmad_key, new_hash = args[0], args[1]
    timestamp = args[2] if len(args) > 2 else now_iso()

    state = load_state(project_root)
    for entry in state["mappings"]:
        if entry.get("bmad_key") == bmad_key:
            entry["last_synced_hash"] = new_hash
            entry["last_synced_at"] = timestamp
            save_state(project_root, state)
            print(json.dumps({"action": "hash_updated", "bmad_key": bmad_key}))
            return 0

    print(f"ERROR: No mapping found for bmad_key={bmad_key}", file=sys.stderr)
    return 1


def cmd_remove(project_root: Path, args: list[str]) -> int:
    if not args:
        print("ERROR: remove requires <bmad-key>", file=sys.stderr)
        return 1
    bmad_key = args[0]
    state = load_state(project_root)
    before = len(state["mappings"])
    state["mappings"] = [
        e for e in state["mappings"] if e.get("bmad_key") != bmad_key
    ]
    if len(state["mappings"]) == before:
        print(f"ERROR: No mapping found for bmad_key={bmad_key}", file=sys.stderr)
        return 1
    save_state(project_root, state)
    print(json.dumps({"action": "removed", "bmad_key": bmad_key}))
    return 0


COMMANDS = {
    "list": cmd_list,
    "get": cmd_get,
    "get-remote": cmd_get_remote,
    "upsert": cmd_upsert,
    "update-hash": cmd_update_hash,
    "remove": cmd_remove,
}


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="sync-state.py",
        description=(
            "Manage the sync-state.yaml ID mapping table for l3io-pm-sync. "
            f"Commands: {', '.join(COMMANDS)}"
        ),
    )
    parser.add_argument(
        "project_root",
        help="Path to the project root containing _bmad/sync-state.yaml",
    )
    parser.add_argument(
        "command",
        choices=list(COMMANDS),
        help="Operation to perform on the mapping table",
    )
    parser.add_argument(
        "extra",
        nargs=argparse.REMAINDER,
        help=(
            "Additional arguments for the command (e.g. bmad-key, hash). "
            "For upsert: use '-' to read JSON from stdin, '@<file>' to read from a file, "
            "or a literal JSON string (avoid shell quoting issues by preferring stdin/file)."
        ),
    )
    parsed = parser.parse_args()

    project_root = Path(parsed.project_root).resolve()
    command = parsed.command
    args = parsed.extra

    if not project_root.is_dir():
        print(f"ERROR: project-root not found: {project_root}", file=sys.stderr)
        return 1

    handler = COMMANDS.get(command)
    if not handler:
        print(
            f"ERROR: Unknown command '{command}'. Available: {', '.join(COMMANDS)}",
            file=sys.stderr,
        )
        return 1

    return handler(project_root, args)


if __name__ == "__main__":
    sys.exit(main())
