#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""reorg-analyze.py -- measure the shape of a plan. Read-only; emits findings, never advice.

WHAT THIS IS FOR. `/l3io-plan reorg` proposes a better plan shape. The proposal itself needs
judgment -- which stories belong together, what is worth retiring -- and that is the agent's
half. This is the other half: every signal that can be MEASURED is measured here, so the
agent argues from evidence rather than from impression, and so the same tree produces the
same findings twice running. A proposal whose reasons cannot be re-derived is one nobody can
check.

WHAT IT DELIBERATELY DOES NOT DO. It does not decide, rank, or recommend. Each finding
carries an id, the nodes involved, a measured value, and what that value suggests -- and
stops. In particular an ORPHAN (a story nothing depends on) is reported as a QUESTION, never
as a retirement finding: leaf work is very often the actual deliverable, and a tool that
scored "nothing depends on this" as "delete this" would be confidently wrong about the most
valuable story in the plan.

WHY IT TAKES JSON ON STDIN RATHER THAN READING THE TREE. Check 26 forbids any file under
`skills/` from assembling a state path; `pm-status.py` is the only thing that resolves a key
to a location. So the shape of the plan arrives via `pm-status.py dump-plan`, and this script
never touches the state tree:

    uv run {pm_status} dump-plan --state-root S | uv run reorg-analyze.py

THE PRIMARY OBJECTIVE IS THE CRITICAL PATH. The spec's one objective is to reduce the cost of
discovering a problem late, measured as the longest dependency chain weighted by elapsed
hours: every hour on it is an hour nothing else can proceed through, and a late discovery
there invalidates the most downstream work. Everything else here is a guardrail.
"""
import json
import sys

# How a story's elapsed estimate is found, in order of preference. A story planned but not
# yet estimated contributes 0 rather than blocking the analysis -- a plan is usually
# reorganised BEFORE everything is estimated, which is exactly when the shape is still cheap
# to change.
_ELAPSED_KEYS = ("elapsed_hours", "elapsed_hours_high", "elapsed_hours_low")


def elapsed(node) -> float:
    est = node.get("estimate") or {}
    if not isinstance(est, dict):
        return 0.0
    for k in _ELAPSED_KEYS:
        v = est.get(k)
        if isinstance(v, (int, float)):
            return float(v)
    return 0.0


def index(plan: dict):
    """(stories, epics, story_epic) -- flat lookups over the PLANNED set only."""
    stories, epics, story_epic = {}, {}, {}
    for epic in plan.get("planned", []):
        epics[epic["key"]] = epic
        for sprint in epic.get("sprints", []):
            for st in sprint.get("stories", []):
                stories[st["key"]] = st
                story_epic[st["key"]] = (epic["key"], sprint["key"])
    return stories, epics, story_epic


def find_cycles(edges: dict) -> list:
    """Every dependency cycle, as a list of node lists. Iterative DFS with a colour map.

    Reported rather than raised. `step-05-dependency-graph.md` halts on a cycle, which is
    correct for planning and is also the end of the help it offers; here a cycle is a finding
    the proposal can be built to break.
    """
    WHITE, GREY, BLACK = 0, 1, 2
    colour = dict.fromkeys(edges, WHITE)
    cycles, stack = [], []

    def walk(start):
        frames = [(start, iter(edges.get(start, ())))]
        colour[start] = GREY
        stack.append(start)
        while frames:
            node, it = frames[-1]
            nxt = next(it, None)
            if nxt is None:
                colour[node] = BLACK
                stack.pop()
                frames.pop()
                continue
            if nxt not in colour:
                continue                      # a dangling reference; reported separately
            if colour[nxt] == GREY:
                cycles.append(stack[stack.index(nxt):] + [nxt])
            elif colour[nxt] == WHITE:
                colour[nxt] = GREY
                stack.append(nxt)
                frames.append((nxt, iter(edges.get(nxt, ()))))

    for n in list(edges):
        if colour.get(n) == WHITE:
            walk(n)
    return cycles


def longest_path(edges: dict, weight, min_len: int = 2) -> tuple:
    """(hours, path) of the heaviest dependency CHAIN of at least `min_len` nodes.

    MIN_LEN IS 2 ON PURPOSE, and it is the difference between measuring the right thing and
    the wrong one. A reorg can only change the SHAPE of a plan; it cannot make a story
    smaller. So a single heavy story is not a critical path -- there is no serialisation in
    it to remove, and reporting it as one would point the proposal at work it cannot help.
    What matters is the longest chain of work that must happen IN ORDER, because that is the
    part a regrouping can actually shorten.

    Memoised; safe on a cyclic graph.

    A cycle makes "longest" undefined, so a node already being evaluated contributes 0 and
    the cycle is reported by `find_cycles` instead. Returning a wrong number silently would
    be worse than returning a short one beside an explicit cycle finding.
    """
    best, visiting = {}, set()

    def walk(n):
        if n in best:
            return best[n]
        if n in visiting:
            return 0.0, []
        visiting.add(n)
        top_h, top_p = 0.0, []
        for d in edges.get(n, ()):
            if d in edges:
                h, p = walk(d)
                if h > top_h:
                    top_h, top_p = h, p
        visiting.discard(n)
        best[n] = (weight(n) + top_h, [n] + top_p)
        return best[n]

    out = (0.0, [])
    for n in edges:
        h, p = walk(n)
        if len(p) >= min_len and h > out[0]:
            out = (h, p)
    return out


def analyze(plan: dict) -> dict:
    stories, epics, story_epic = index(plan)
    active = {e["key"] for e in plan.get("active", [])}
    archived = {e["key"] for e in plan.get("archived", [])}
    findings = []

    def add(fid, severity, nodes, measured, suggests):
        findings.append({"id": fid, "severity": severity, "nodes": nodes,
                         "measured": measured, "suggests": suggests})

    story_edges = {k: [d for d in v.get("depends_on", [])] for k, v in stories.items()}
    epic_edges = {k: [d for d in v.get("depends_on", [])] for k, v in epics.items()}

    # --- hard problems -------------------------------------------------------------
    for cyc in find_cycles(epic_edges) + find_cycles(story_edges):
        add("cycle", "blocker", cyc, {"length": len(cyc) - 1},
            "break the cycle; nothing downstream of it can be ordered")

    for key, deps in list(story_edges.items()) + list(epic_edges.items()):
        for d in deps:
            if d not in stories and d not in epics and d not in active and d not in archived:
                add("dangling-dependency", "blocker", [key, d], {},
                    f"{key} depends on {d}, which does not exist in any bucket")

    # --- the primary objective -----------------------------------------------------
    hours, path = longest_path(story_edges, lambda k: elapsed(stories.get(k, {})))
    if path:
        add("critical-path", "info", path,
            {"elapsed_hours": round(hours, 2), "length": len(path)},
            "the primary objective: every hour on this chain is an hour nothing else "
            "proceeds through, and a late discovery here invalidates the most work")
    else:
        add("no-critical-path", "info", [], {},
            "no story depends on another, so there is no serialisation to shorten — a "
            "reorg here can improve grouping, but not ordering")

    # --- guardrails ----------------------------------------------------------------
    coupling = {}
    for key, deps in story_edges.items():
        src = story_epic.get(key, (None,))[0]
        for d in deps:
            dst = story_epic.get(d, (None,))[0]
            if src and dst and src != dst:
                coupling[(src, dst)] = coupling.get((src, dst), 0) + 1
    for (a, b), n in sorted(coupling.items(), key=lambda kv: -kv[1]):
        if n >= 2:
            add("cross-epic-coupling", "warn", [a, b], {"edges": n},
                f"{n} story dependencies cross {a} -> {b}; the boundary may be in the "
                f"wrong place")

    for epic in plan.get("planned", []):
        sizes = [(s["key"], sum(elapsed(st) for st in s.get("stories", [])))
                 for s in epic.get("sprints", [])]
        sized = [h for _k, h in sizes if h > 0]
        if len(sized) >= 2 and min(sized) > 0 and max(sized) / min(sized) >= 3:
            add("sprint-imbalance", "warn", [epic["key"]],
                {"sprints": dict(sizes), "ratio": round(max(sized) / min(sized), 2)},
                "one sprint is several times another; work may be unevenly grouped")

    for key, st in stories.items():
        for d in st.get("depends_on", []):
            if d in active or story_epic.get(d, (None,))[0] in active:
                add("blocked-by-active", "info", [key, d], {},
                    f"{key} cannot start before in-flight {d}; it constrains any ordering")

    # --- questions, never conclusions ----------------------------------------------
    depended_on = {d for deps in story_edges.values() for d in deps}
    for key in sorted(stories):
        if key not in depended_on and not stories[key].get("depends_on"):
            add("isolated-story", "question", [key], {},
                "nothing depends on this and it depends on nothing — ask whether it is a "
                "deliverable or a leftover. NOT a retirement recommendation: leaf work is "
                "very often the point of the plan")

    return {
        "summary": {
            "planned_epics": len(epics),
            "planned_stories": len(stories),
            "critical_path_hours": round(hours, 2),
            "cross_epic_edges": sum(coupling.values()),
            "blockers": sum(1 for f in findings if f["severity"] == "blocker"),
        },
        "findings": findings,
    }


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] in ("-h", "--help"):
        sys.stdout.write(__doc__ + "\nusage: pm-status.py dump-plan ... | reorg-analyze.py\n")
        return 0
    try:
        plan = json.load(sys.stdin)
    except json.JSONDecodeError as e:
        sys.stderr.write(f"reorg-analyze.py: stdin is not valid JSON ({e}). Pipe "
                         f"`pm-status.py dump-plan --state-root S` into this.\n")
        return 2
    if not isinstance(plan, dict) or "planned" not in plan:
        sys.stderr.write("reorg-analyze.py: expected dump-plan output (an object with a "
                         "`planned` key); refusing to analyse an unknown shape.\n")
        return 2
    sys.stdout.write(json.dumps(analyze(plan), indent=2) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
