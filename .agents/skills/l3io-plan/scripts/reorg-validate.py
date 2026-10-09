#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["ruamel.yaml>=0.18"]
# ///
"""reorg-validate.py -- judge a reorg TARGET. Refuses the whole thing, or accepts it.

WHAT A TARGET IS. The agent proposing a reorg does not emit operations; it emits a target
PLACEMENT, and the tooling derives the operations by diffing. This script stands between the
two: nothing an agent wrote reaches the state tree without passing here.

    uv run {pm_status} dump-plan --state-root S | uv run reorg-validate.py --target T.yaml

WHY THE FORMAT IS DELIBERATELY IMPOVERISHED. A row says only WHERE a node belongs:

    target:
      - key: E007-S02-004      # the node's CURRENT key -- never a new one
        epic: E003
        sprint: S01
        order: 5
    retire:
      - key: E041
        reason: "..."

No titles, no estimates, no `depends_on`, no destination keys. That is the whole safety
argument for handing a target tree to an agent: drift is not mitigated, it is
UNREPRESENTABLE. An agent that wanted to quietly reword a story has nowhere to put the words,
and one that wanted to pick a key it should not have has no field for it. Any unexpected field
is a refusal, not a warning -- a validator that shrugged at a field it did not understand
would be exactly the hole the format exists to close.

WHY THE TARGET MUST BE TOTAL. Every planned story appears exactly once, across `target` and
`retire`. An omission is an ERROR, never an implied "leave it alone", because an agent that
forgot a node and an agent that meant to leave it are indistinguishable from the outside --
and the second is far more common. Silence is the one thing a target state must never mean.

WHY IT REFUSES WHOLE RATHER THAN PER-ROW. A partially-applied target is neither the old plan
nor the new one, and the rationale the user accepted described the whole. Refusing names every
offending row so one pass fixes them all.
"""
import argparse
import json
import sys

TARGET_FIELDS = {"key", "epic", "sprint", "order"}
RETIRE_FIELDS = {"key", "reason"}
TOP_FIELDS = {"target", "retire"}


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


def index_plan(plan: dict):
    """(stories, sprints, epics, story_deps, epic_deps) over the PLANNED set."""
    stories, sprints, epics, story_deps, epic_deps = {}, set(), {}, {}, {}
    for epic in plan.get("planned", []):
        epics[epic["key"]] = epic
        epic_deps[epic["key"]] = list(epic.get("depends_on", []))
        for sp in epic.get("sprints", []):
            sprints.add((epic["key"], sp["key"]))
            for st in sp.get("stories", []):
                stories[st["key"]] = (epic["key"], sp["key"])
                story_deps[st["key"]] = list(st.get("depends_on", []))
    return stories, sprints, epics, story_deps, epic_deps


def has_cycle(edges: dict) -> list:
    WHITE, GREY, BLACK = 0, 1, 2
    colour = dict.fromkeys(edges, WHITE)
    found = []

    def walk(start):
        stack = [start]
        frames = [(start, iter(edges.get(start, ())))]
        colour[start] = GREY
        while frames:
            node, it = frames[-1]
            nxt = next(it, None)
            if nxt is None:
                colour[node] = BLACK
                stack.pop()
                frames.pop()
                continue
            if nxt not in colour:
                continue
            if colour[nxt] == GREY:
                found.append(stack[stack.index(nxt):] + [nxt])
            elif colour[nxt] == WHITE:
                colour[nxt] = GREY
                stack.append(nxt)
                frames.append((nxt, iter(edges.get(nxt, ()))))

    for n in list(edges):
        if colour.get(n) == WHITE:
            walk(n)
    return found


def validate(plan: dict, target) -> list:
    """Every reason to refuse. Empty means accept."""
    errs = []

    def bad(where, why):
        errs.append({"where": where, "why": why})

    if not isinstance(target, dict):
        return [{"where": "<file>", "why": "the target must be a mapping with `target` and "
                                           "optionally `retire`"}]
    extra = set(target) - TOP_FIELDS
    if extra:
        bad("<top level>", f"unexpected key(s) {sorted(extra)}; a target expresses placement "
                           f"and retirement only")
    rows = target.get("target")
    if rows is None:
        rows = []
    if not isinstance(rows, list):
        return errs + [{"where": "target", "why": "`target` must be a list of placement rows"}]
    retires = target.get("retire") or []
    if not isinstance(retires, list):
        return errs + [{"where": "retire", "why": "`retire` must be a list"}]

    stories, sprints, epics, story_deps, _epic_deps = index_plan(plan)

    # --- shape: the format cannot express drift ------------------------------------
    placed, retired = {}, {}
    for i, row in enumerate(rows):
        where = f"target[{i}]"
        if not isinstance(row, dict):
            bad(where, "each row must be a mapping")
            continue
        unexpected = set(row) - TARGET_FIELDS
        if unexpected:
            bad(where, f"unexpected field(s) {sorted(unexpected)} — a row says only WHERE a "
                       f"node belongs. Titles, estimates, dependencies and destination keys "
                       f"are not expressible here, on purpose")
        missing = TARGET_FIELDS - set(row) - {"order"}
        if missing:
            bad(where, f"missing required field(s) {sorted(missing)}")
            continue
        key = str(row.get("key"))
        if key in placed:
            bad(where, f"{key} appears more than once in `target`")
        placed[key] = row

    for i, row in enumerate(retires):
        where = f"retire[{i}]"
        if not isinstance(row, dict):
            bad(where, "each row must be a mapping")
            continue
        unexpected = set(row) - RETIRE_FIELDS
        if unexpected:
            bad(where, f"unexpected field(s) {sorted(unexpected)}")
        if "key" not in row:
            bad(where, "missing required field `key`")
            continue
        if not str(row.get("reason") or "").strip():
            bad(where, f"{row['key']} is retired with no reason — nobody could judge later "
                       f"whether it should come back")
        retired[str(row["key"])] = row

    # --- every key must resolve, and must be planned --------------------------------
    for key, row in placed.items():
        if key not in stories:
            bad(f"target[{key}]", "not a planned story — a target addresses nodes by their "
                                  "CURRENT key, and only planned work is writable")
    for key in retired:
        if key not in epics:
            bad(f"retire[{key}]", "not a planned epic — retirement is epic-level, because "
                                  "planned/active/archived are folders of epic directories")

    # --- totality -------------------------------------------------------------------
    retired_stories = {s for s, (e, _sp) in stories.items() if e in retired}
    for key in sorted(stories):
        if key not in placed and key not in retired_stories:
            bad(f"<missing>{key}", "every planned story must appear exactly once in `target` "
                                   "or be inside a retired epic. An omission is an error, "
                                   "never an implied 'leave it alone'")
        if key in placed and key in retired_stories:
            bad(f"target[{key}]", "placed and also inside a retired epic")

    # --- destinations ----------------------------------------------------------------
    created = {(str(r["epic"]), str(r["sprint"])) for r in placed.values()
               if "epic" in r and "sprint" in r}
    for key, row in placed.items():
        dest = (str(row.get("epic")), str(row.get("sprint")))
        if dest[0] in retired:
            bad(f"target[{key}]", f"placed into {dest[0]}, which is being retired")
        if dest[0] not in epics:
            bad(f"target[{key}]", f"destination epic {dest[0]} does not exist in planned/")
        elif dest not in sprints and dest not in created:
            bad(f"target[{key}]", f"destination sprint {dest[0]}-{dest[1]} does not exist "
                                  f"and is not created by this target")

    # --- the resulting graph ----------------------------------------------------------
    gone = retired_stories
    live_deps = {k: [d for d in v if d not in gone]
                 for k, v in story_deps.items() if k not in gone}
    for cyc in has_cycle(live_deps):
        bad("<graph>", f"the resulting plan has a dependency cycle: {' -> '.join(cyc)}")

    for key, deps in story_deps.items():
        if key in gone:
            continue
        for d in deps:
            if d in gone:
                bad(f"<graph>{key}", f"depends on {d}, which is inside a retired epic — "
                                     f"retire the dependent too, or keep {d}")

    # --- ordering ---------------------------------------------------------------------
    def place_of(k):
        if k in placed:
            r = placed[k]
            return str(r.get("epic")), str(r.get("sprint")), r.get("order")
        return (*stories.get(k, (None, None)), None)

    for key, deps in live_deps.items():
        ke, ks, ko = place_of(key)
        for d in deps:
            if d not in stories:
                continue                        # active/archived: ordering is not ours
            de, ds, do = place_of(d)
            if (ke, ks) == (de, ds) and isinstance(ko, int) and isinstance(do, int) \
                    and ko <= do:
                bad(f"target[{key}]", f"ordered at {ko} but depends on {d} at {do} in the "
                                      f"same sprint — a dependency cannot come later")
    return errs


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="reorg-validate.py", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--target", required=True, help="the proposed target placement (YAML)")
    ap.add_argument("--format", choices=("text", "json"), default="text")
    a = ap.parse_args(argv)

    try:
        plan = json.load(sys.stdin)
    except json.JSONDecodeError as e:
        sys.stderr.write(f"reorg-validate.py: stdin is not valid JSON ({e}). Pipe "
                         f"`pm-status.py dump-plan --state-root S` into this.\n")
        return 2
    if not isinstance(plan, dict) or "planned" not in plan:
        sys.stderr.write("reorg-validate.py: expected dump-plan output (an object with a "
                         "`planned` key); refusing to judge an unknown shape.\n")
        return 2

    target, err = load_target(a.target)
    if err:
        sys.stderr.write(f"reorg-validate.py: {err}\n")
        return 2

    errs = validate(plan, target)
    if a.format == "json":
        sys.stdout.write(json.dumps({"ok": not errs, "errors": errs}, indent=2) + "\n")
    elif errs:
        sys.stderr.write(f"reorg-validate.py: refusing this target — {len(errs)} problem(s). "
                         f"The whole target is refused, not the offending rows: a partly "
                         f"applied target is neither the old plan nor the new one.\n")
        for e in errs:
            sys.stderr.write(f"  {e['where']}: {e['why']}\n")
    else:
        sys.stdout.write("OK target is valid\n")
    return 2 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
