#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["networkx>=3.6"]
# ///
"""plan-graph.py -- every question about a plan that is a GRAPH question. Read-only.

Two modes, one graph:

    uv run {pm_status} dump-plan --state-root S | plan-graph.py analyze   -> findings JSON
    uv run {pm_status} dump-plan --state-root S | plan-graph.py phases    -> phases JSON

Both read `dump-plan` output on stdin and assemble no paths of their own, which is why they
can live here rather than inside pm-status.py.

WHY networkx AND NOT pm-status.py. The graph algorithms here were hand-written -- cycle
detection twice, longest path once, about 112 lines -- and networkx does all of it, plus
things that were simply absent: `transitive_reduction` for a redundant depends_on, and
`weakly_connected_components` for cohesion. It is NOT faster: measured on a 2000-story graph
it is slower than the hand-rolled version, and its import alone costs ~616 ms. That is
irrelevant at once-per-plan and would be ruinous in pm-status.py, which runs from 92 call
sites at ~0.21 s startup. So the dependency lives here and pm-status.py takes no graph
library at all. Do not "consolidate" them.

-- analyze ------------------------------------------------------------------------------

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

    uv run {pm_status} dump-plan --state-root S | uv run plan-graph.py analyze

THE PRIMARY OBJECTIVE IS THE CRITICAL PATH. The spec's one objective is to reduce the cost of
discovering a problem late, measured as the longest dependency chain weighted by elapsed
hours: every hour on it is an hour nothing else can proceed through, and a late discovery
there invalidates the most downstream work. Everything else here is a guardrail.
"""
import argparse
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


def _digraph(edges: dict):
    """{node: [things it depends on]} -> DiGraph with dependency -> dependent edges.

    Edge direction is EXECUTION order, so a path reads in the order work happens and
    `dag_longest_path` returns it that way round. Dependencies on nodes outside the set
    (active, archived, dangling) are dropped here -- they are reported separately and are not
    this graph's to order.
    """
    import networkx as nx
    g = nx.DiGraph()
    g.add_nodes_from(edges)
    g.add_edges_from((d, n) for n, deps in edges.items() for d in deps if d in edges)
    return g


def find_cycles(edges: dict) -> list:
    """Every simple cycle, each closed (first node repeated at the end).

    ALL of them, not the first. The analyzer reports every cycle it finds, and a plan with
    two broken clusters that surfaced one at a time would be half-fixed, re-run, and fail
    again. `graphlib.CycleError` carries exactly one cycle, which is why it is not used here.
    """
    import networkx as nx
    return [list(c) + [c[0]] for c in nx.simple_cycles(_digraph(edges))]


def longest_path(edges: dict, weight, min_len: int = 2) -> tuple:
    """(total weight, path) for the longest chain. Empty when nothing chains.

    `min_len=2` excludes a lone node: a story that depends on nothing and is depended on by
    nothing has no serialisation in it, however heavy, and naming it a chain points the
    reader at work the chain has nothing to do with.

    TOTAL ON A CYCLIC GRAPH, deliberately. `nx.dag_longest_path` raises NetworkXUnfeasible
    on one, but the analyzer reports a cycle AND still reports a chain -- a run that returned
    nothing but the cycle would hide every other fact about the plan. Cyclic input is reduced
    to its condensation, which is a DAG by construction, and the heaviest node of each
    collapsed group represents it.
    """
    import networkx as nx
    g = _digraph(edges)
    if not nx.is_directed_acyclic_graph(g):
        cond = nx.condensation(g)
        rep = {}
        for n, members in cond.nodes(data="members"):
            rep[n] = max(members, key=lambda m: (weight(m), m))
        g = nx.relabel_nodes(cond, rep, copy=True)
    for u, v in g.edges:
        g.edges[u, v]["w"] = weight(v)
    path = nx.dag_longest_path(g, weight="w", default_weight=0)
    if len(path) < min_len:
        return 0.0, []
    return sum(weight(n) for n in path), path


def phases(plan: dict) -> dict:
    """Epics grouped into the order they may run in. The plan snapshot's `phases` list.

    This replaces a hand-executed Kahn's algorithm: step-05 used to describe the algorithm in
    prose for an agent to run in its head, over the whole epic set, every plan run. It is the
    computation that decides what runs CONCURRENTLY, which makes it the worst candidate in the
    system for being done from memory.

    `nx.topological_generations` IS that grouping: generation N is exactly the set whose
    dependencies all sit in generations before it.

    `parallel` IS `len(epics) > 1`, and nothing else. The old prose said "more than one epic,
    or a single-epic phase with no ordering constraint", and its own worked example then
    marked a one-epic phase parallel and another one-epic phase sequential -- the rule and
    the example disagreed. It never mattered, because `l3io-execute`'s epic loop guards on
    `parallel_flag=true AND len(epics) > 1` independently, so the flag alone has never caused
    a concurrent dispatch of one epic. Making it mean the one thing it can act on removes the
    contradiction without changing behaviour.

    Epics are ordered within a generation, and generations among themselves, so the same plan
    yields the same phases twice running.
    """
    import networkx as nx
    epics = {e["key"]: e for e in plan.get("planned", [])}
    edges = {k: [d for d in (v.get("depends_on") or []) if d in epics]
             for k, v in epics.items()}
    g = _digraph(edges)

    out = []
    if not nx.is_directed_acyclic_graph(g):
        # A cycle has no topological order at all. Say so and emit nothing rather than a
        # plausible-looking ordering over a graph that does not have one; `analyze` reports
        # the cycles themselves.
        return {"phases": [], "error": "the epic dependency graph has a cycle, so it has no "
                                       "execution order — run `analyze` for the cycles"}
    for i, gen in enumerate(nx.topological_generations(g), start=1):
        keys = sorted(gen)
        deps = sorted({d for k in keys for d in edges[k]})
        out.append({"phase": i, "parallel": len(keys) > 1, "epics": keys,
                    "dependencies": deps})
    return {"phases": out, "phase_count": len(out),
            "epic_count": sum(len(p["epics"]) for p in out)}


def partition(plan: dict, lane_count: int) -> dict:
    """Propose which lane owns which epic. Emits a proposal; assigns nothing.

    WHEN THIS IS ASKED FOR. `lane_count > 1` — a CONFIGURED answer from setup, never inferred
    from the tree. A project set up for three lanes that has not assigned any yet looks
    exactly like a single-developer project if you only scan epics, and they must not get the
    same answer.

    TWO OBJECTIVES, REPORTED SEPARATELY, because they are not the same thing. Minimising
    cross-lane edges keeps lanes independent; keeping every lane busy is about phase coverage.
    A partition that is perfect by connectivity can hand one lane only late-phase epics and
    leave it idle until another finishes, so both numbers are reported and neither is silently
    traded for the other.

    OVER-PARTITIONING HAS A PRICE, AND SAYING SO IS THE POINT. Asking for more lanes than the
    work supports forces splits through real dependencies. On an eight-epic fixture with two
    natural clusters, k=2 costs zero cross-lane edges and k=3 costs two. A lead deciding
    whether to put a third person on this needs that before assigning, not after.
    """
    import networkx as nx
    from networkx.algorithms import community as nxc

    epics = {e["key"]: e for e in plan.get("planned", [])}
    if not epics:
        return {"lanes": [], "note": "no planned epics to partition"}
    k = max(1, min(int(lane_count), len(epics)))

    edges = {k2: [d for d in (v.get("depends_on") or []) if d in epics]
             for k2, v in epics.items()}
    g = _digraph(edges)
    # UNDIRECTED for the split: an edge that crosses a lane boundary costs the same whichever
    # way it points -- one lane waits on the other either way.
    groups = ([set(epics)] if k == 1
              else [set(c) for c in nxc.greedy_modularity_communities(
                  g.to_undirected(), best_n=k, cutoff=k)])

    lane_of = {e: i + 1 for i, grp in enumerate(groups) for e in grp}
    crossing = [(u, v) for u, v in g.edges if lane_of[u] != lane_of[v]]

    gens = ([] if not nx.is_directed_acyclic_graph(g)
            else [set(x) for x in nx.topological_generations(g)])
    lanes = []
    for i, grp in enumerate(sorted(groups, key=lambda s: sorted(s)), start=1):
        idx = lane_of[next(iter(grp))]
        phases = [n for n, gen in enumerate(gens, 1) if gen & grp]
        lanes.append({
            "lane": idx,
            "epics": sorted(grp),
            "phases": phases,
            "idle_phases": [n for n in range(1, len(gens) + 1) if n not in phases],
        })
    out = {
        "lanes": sorted(lanes, key=lambda x: x["lane"]),
        "lane_count": k,
        "cross_lane_edges": len(crossing),
        "crossings": [{"from": u, "to": v} for u, v in sorted(crossing)],
    }
    if k < int(lane_count):
        out["note"] = (f"only {len(epics)} planned epic(s), so {lane_count} lanes cannot each "
                       f"own one; proposing {k}")
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

    # --- how serialised the work inherently is -------------------------------------
    #
    # MEASURED IN HOPS, NOT HOURS, and reported as a fact rather than a target.
    #
    # It used to be the weighted critical path and the stated primary objective, which was
    # wrong twice. Hours are a band times a calibration ratio — two inferences deep — where
    # `depends_on` is declared about the work; and the hours are usually absent exactly when
    # a plan is cheapest to reshape, so the objective degraded to nothing on the plans that
    # most needed it. Hops need no estimates and serve the goal the spec actually states —
    # "reduce the cost of discovering a problem late" — more directly: each hop is a handoff
    # where a wrong assumption propagates.
    #
    # INFO, because a reorg CANNOT SHORTEN IT. Reorg moves stories between sprints and epics;
    # it never edits `depends_on`, so no move removes an edge from this chain. It is reported
    # so a reader knows how much serialisation the work carries, not so the proposal aims at
    # it. What a reorg can actually act on is which epic a dependency crosses — see
    # cross-epic-coupling below.
    hops, path = longest_path(story_edges, lambda _k: 1.0)
    if path:
        add("dependency-chain", "info", path, {"hops": len(path) - 1, "length": len(path)},
            "the longest chain of story dependencies. A reorg cannot shorten it — it never "
            "edits depends_on — so this is context for the proposal, not its target")
    else:
        add("no-dependency-chain", "info", [], {},
            "no story depends on another, so there is no serialisation at all — a reorg "
            "here can improve grouping, but there is no ordering to improve")

    # --- what a reorg can actually change ------------------------------------------
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

    # --- a crossing edge the PHASE GRAPH cannot see --------------------------------
    #
    # NO THRESHOLD HERE, unlike coupling above, and that difference is the point. Coupling
    # asks "is this boundary in the wrong place?", where one crossing edge is ordinary and
    # reporting it would be noise. This asks a different question: does the epic graph KNOW
    # about the edge? Phases are built from epic-level `depends_on`, so a story dependency
    # crossing E001 -> E003 with no `E001 depends_on E003` behind it leaves both epics in the
    # same parallel phase, running concurrently, while one needs the other finished. One such
    # edge is already a scheduling error, so one is already worth reporting.
    #
    # Reported, not refused (plan decision D1): existing projects likely carry one, and a
    # hand-written story dependency produces it with no reorg involved. Erroring on upgrade
    # would block runs on a defect the user did not cause. The finding names the epic-level
    # declaration that would back it, so the fix is a line of YAML rather than an
    # investigation.
    for (a, b) in sorted(coupling):
        if b not in epic_edges.get(a, ()):
            edges = sorted(k for k, deps in story_edges.items()
                           if story_epic.get(k, (None,))[0] == a
                           and any(story_epic.get(d, (None,))[0] == b for d in deps))
            add("unbacked-cross-epic-dependency", "warn", [a, b],
                {"edges": len(edges), "stories": edges},
                f"stories in {a} depend on {b}, but {a} does not declare "
                f"`depends_on: [{b}]`. Phases come from epic-level dependencies, so the two "
                f"can be scheduled into the same parallel phase and run concurrently. Add "
                f"{b} to {a}'s depends_on.")

    # --- dependencies that cross a LANE boundary -----------------------------------
    #
    # THE WHOLE LANE FEATURE RIDES ON ONE RELABEL. `coupling` above is already keyed by epic
    # pair, and `1 epic = 1 lane` makes the lane graph the epic graph with relabelled nodes
    # -- a colouring, not a second graph -- so this needs no traversal of its own. Had a
    # story been lane-assignable independently of its epic, the two graphs would differ and
    # every question here would need its own walk.
    #
    # SILENT WHEN LANES ARE OFF, which is the majority of projects. An epic with no `lane`
    # contributes nothing, so a tree that never declared one produces no findings at all.
    #
    # WARN, unlike unneeded-epic-dependency: a reorg CAN act on this, by moving the story to
    # an epic the other lane owns. That is the one remedy, and it is a reorg rather than a
    # field change, because moving between lanes means moving between epics.
    lane_of = {e["key"]: e.get("lane") for e in plan.get("planned", [])}
    lane_cross = {}
    for (a, b), n in coupling.items():
        la, lb = lane_of.get(a), lane_of.get(b)
        if la and lb and str(la) != str(lb):
            lane_cross[(str(la), str(lb))] = lane_cross.get((str(la), str(lb)), 0) + n
    for (la, lb), n in sorted(lane_cross.items(), key=lambda kv: (-kv[1], kv[0])):
        add("cross-lane-dependency", "warn", [f"lane {la}", f"lane {lb}"], {"edges": n},
            f"{n} story dependency(ies) cross from lane {la} into lane {lb}. Lane {la} waits "
            f"on lane {lb} for those, so the two developers are not working independently. "
            f"Move the story to an epic lane {lb} owns (/l3io-plan reorg), or accept the "
            f"coupling deliberately.")

    # --- an epic dependency nothing justifies any more ----------------------------
    #
    # THE INVERSE of unbacked-cross-epic-dependency above, and the signal a reorg produces.
    # A reorg's objective is to remove dependencies crossing an epic boundary -- but it
    # cannot edit epic-level `depends_on`, so the declaration survives the edges that earned
    # it. Phases come from that declaration, so the two epics keep serialising and the
    # parallelism the reorg was for never arrives.
    #
    # INFO, NOT WARN, and the reason is routing rather than importance: the plan-run advisory
    # maps `warn` to "run /l3io-plan reorg", and reorg is precisely the tool that CANNOT fix
    # this. Surfacing it there would point at a refusal. It is reported where it is
    # actionable -- in reorg's own post-apply report, which knows the edges were there a
    # moment ago.
    #
    # Never auto-dropped. An epic dependency can encode sequencing no story edge expresses
    # ("ship the API before the client"), and nothing here can tell that from a leftover.
    for epic in plan.get("planned", []):
        declared = [str(d) for d in (epic.get("depends_on") or [])]
        for target in sorted(set(declared)):
            if target not in epics:
                continue                       # dangling-dependency already covers it
            if coupling.get((epic["key"], target), 0) == 0:
                add("unneeded-epic-dependency", "info", [epic["key"], target],
                    {"edges": 0},
                    f"{epic['key']} declares depends_on: [{target}] but no story in "
                    f"{epic['key']} depends on one in {target}. Dropping it would let them "
                    f"share a parallel phase — unless the dependency is a sequencing "
                    f"decision no story edge expresses, which this cannot tell.")

    for epic in plan.get("planned", []):
        sizes = [(s["key"], sum(elapsed(st) for st in s.get("stories", [])))
                 for s in epic.get("sprints", [])]
        sized = [h for _k, h in sizes if h > 0]
        if len(sized) >= 2 and min(sized) > 0 and max(sized) / min(sized) >= 3:
            # INFO, not warn: effort is an impact a reorg reports, never an objective it
            # pursues (plan decision D4). Reorg cannot make work smaller, so treating load as
            # a driver would make retirement — deleting scope — the highest-scoring move
            # available, which is precisely the wrong incentive. This is the balancing pass's
            # input, not the structural pass's finding.
            add("sprint-imbalance", "info", [epic["key"]],
                {"sprints": dict(sizes), "ratio": round(max(sized) / min(sized), 2)},
                "one sprint is several times another; work may be unevenly grouped. An "
                "impact to report, not a reason to re-place work on its own")

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
            # Hops, not hours. The weighted critical path is gone: it needed estimates that
            # are usually absent when a plan is cheapest to reshape, and a reorg cannot
            # shorten a dependency chain in any case.
            "dependency_chain_hops": int(hops) - 1 if path else 0,
            "cross_epic_edges": sum(coupling.values()),
            "unbacked_cross_epic_edges": sum(
                1 for f in findings if f["id"] == "unbacked-cross-epic-dependency"),
            "blockers": sum(1 for f in findings if f["severity"] == "blocker"),
        },
        "findings": findings,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="plan-graph.py", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mode", choices=("analyze", "phases", "partition"),
                    help="analyze: measured findings. phases: the execution order. "
                         "partition: propose which lane owns which epic.")
    ap.add_argument("--lanes", type=int, default=0,
                    help="partition mode: how many lanes (from modules.l3io-pm.lane_count)")
    ap.add_argument("--pretty", action="store_true",
                    help="indent the JSON for reading by hand")
    a = ap.parse_args(sys.argv[1:] if argv is None else argv)

    try:
        plan = json.load(sys.stdin)
    except json.JSONDecodeError as e:
        sys.stderr.write(f"plan-graph.py: stdin is not valid JSON ({e}). Pipe "
                         f"`pm-status.py dump-plan --state-root S` into this.\n")
        return 2
    if not isinstance(plan, dict) or "planned" not in plan:
        sys.stderr.write("plan-graph.py: expected dump-plan output (an object with a "
                         "`planned` key); refusing to read an unknown shape.\n")
        return 2

    if a.mode == "partition":
        if a.lanes < 2:
            sys.stderr.write("plan-graph.py: partition needs --lanes 2 or more; "
                             "lane_count of 1 or absent means lanes are off.\n")
            return 2
        result = partition(plan, a.lanes)
    else:
        result = analyze(plan) if a.mode == "analyze" else phases(plan)
    sep = None if a.pretty else (",", ":")
    sys.stdout.write(json.dumps(result, indent=2 if a.pretty else None,
                                separators=sep) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
