#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["ruamel.yaml>=0.18"]
# ///
"""reorg-derive.py -- turn a validated target into an ordered operation list. Emits, never acts.

    uv run {pm_status} dump-plan --state-root S | uv run reorg-derive.py --target T.yaml

THE OPERATION LIST IS DERIVED, NEVER TRUSTED. The agent writes a target placement; nothing it
writes is an operation. This diffs the current tree against that target and computes what
must happen, which removes a whole class of error outright: a malformed, incomplete or
self-contradictory operation list cannot exist if nobody writes one.

RUN THE VALIDATOR FIRST. This assumes a target that already passed `reorg-validate.py` and
does not re-check it. The two are deliberately separate: judging whether a target is legal and
computing what it implies are different questions, and a derivation that also validated would
be tempted to half-apply a target it found partly acceptable.

ORDER IS THE WHOLE POINT OF THIS FILE. The operations must be safe to apply in sequence:

  1. `create-sprint` for every destination that does not exist yet, BEFORE anything moves into
     it -- `reparent-story` refuses a missing destination, by design.
  2. `reparent-story`, grouped by destination and sorted by the target's `order`, so the
     allocator hands out keys in the sequence the proposal showed. Key order IS processing
     order (`status-files.md` §Key schema), so this is the only control the format has over it.
  3. `retire-epic` LAST. A story moving out of an epic that is being retired must leave before
     the epic is archived, or it goes to `archived/` with it.

WHAT "ORDER" CAN AND CANNOT DO. It sequences the stories THIS target moves. It cannot reorder
a story that stays put, because the only way to do that is to re-key it -- churning its key,
its document filename, its previous_keys and its remote-issue mapping for a local sequencing
change. The spec states that limit; this file honours it rather than pretending otherwise.

RE-DIFFING ANSWERS "WHAT IS LEFT?". Running this again after a partial apply yields exactly
the outstanding operations, because it compares states rather than replaying a script. That
property is why a half-finished reorg is detectable instead of silent.
"""
import argparse
import json
import sys


def load_target(path: str):
    from ruamel.yaml import YAML
    from ruamel.yaml.error import YAMLError
    try:
        with open(path, encoding="utf-8") as fh:
            return YAML(typ="safe").load(fh), None
    except FileNotFoundError:
        return None, f"target file not found: {path}"
    except UnicodeDecodeError:
        return None, f"target file is not valid utf-8: {path}"
    except YAMLError as e:
        return None, f"target file is not valid YAML: {e}"


def current_places(plan: dict) -> dict:
    """story key -> (epic, sprint), over the planned set."""
    out = {}
    for epic in plan.get("planned", []):
        for sp in epic.get("sprints", []):
            for st in sp.get("stories", []):
                out[st["key"]] = (epic["key"], sp["key"])
    return out


def existing_sprints(plan: dict) -> set:
    return {(e["key"], sp["key"]) for e in plan.get("planned", [])
            for sp in e.get("sprints", [])}


def derive(plan: dict, target) -> list:
    places = current_places(plan)
    have = existing_sprints(plan)
    rows = (target or {}).get("target") or []
    retires = (target or {}).get("retire") or []

    moves = []
    for row in rows:
        if not isinstance(row, dict) or "key" not in row:
            continue
        key = str(row["key"])
        dest = (str(row.get("epic")), str(row.get("sprint")))
        if places.get(key) == dest:
            continue                       # already there: a no-op, not an operation
        order = row.get("order")
        moves.append({"key": key, "dest": dest,
                      "order": order if isinstance(order, int) else 0})

    ops = []

    # 1. Destinations first. `reparent-story` refuses a missing destination sprint, so a
    #    create that came later would fail every move into it.
    for dest in sorted({m["dest"] for m in moves} - have):
        ops.append({"op": "create-sprint", "epic": dest[0], "sprint": dest[1],
                    "why": "destination does not exist yet"})

    # 2. Moves, grouped by destination and sequenced by `order` so the allocator hands out
    #    keys in the order the proposal showed.
    for m in sorted(moves, key=lambda m: (m["dest"], m["order"], m["key"])):
        ops.append({"op": "reparent-story", "story": m["key"],
                    "to_epic": m["dest"][0], "to_sprint": m["dest"][1],
                    "from": list(places.get(m["key"], ("?", "?")))})

    # 3. Retirements last, so anything leaving a retiring epic is already gone.
    for r in retires:
        if not isinstance(r, dict) or "key" not in r:
            continue
        ops.append({"op": "retire-epic", "epic": str(r["key"]),
                    "reason": str(r.get("reason") or "")})
    return ops


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="reorg-derive.py", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--target", required=True)
    a = ap.parse_args(argv)

    try:
        plan = json.load(sys.stdin)
    except json.JSONDecodeError as e:
        sys.stderr.write(f"reorg-derive.py: stdin is not valid JSON ({e}). Pipe "
                         f"`pm-status.py dump-plan --state-root S` into this.\n")
        return 2
    if not isinstance(plan, dict) or "planned" not in plan:
        sys.stderr.write("reorg-derive.py: expected dump-plan output (an object with a "
                         "`planned` key); refusing to derive from an unknown shape.\n")
        return 2

    target, err = load_target(a.target)
    if err:
        sys.stderr.write(f"reorg-derive.py: {err}\n")
        return 2

    ops = derive(plan, target)
    sys.stdout.write(json.dumps({"operations": ops, "count": len(ops)}, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
