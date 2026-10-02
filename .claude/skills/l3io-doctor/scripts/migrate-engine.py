#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["ruamel.yaml>=0.18"]
# ///
"""
migrate-engine.py -- the eight-step migration run.

    detect -> read -> resolve -> plan -> GATE -> write -> verify -> dispose

The gate sits BEFORE the write, and that position is the whole point. The previous prose
migration ran its completeness checks AFTER writing and before deleting the source, so a
parse that produced zero nodes passed every check vacuously and then `rm -f`'d a live
BMad tracking file while reporting success. A gate placed before the write cannot do
that, whatever the cause of the empty parse -- including causes nobody has met yet.

Steps 1-4 are read-only and safe to run at any time. Steps 5-8 run only under --apply.

Usage:
  migrate-engine.py --artifacts DIR --project-root DIR --plan [--format json|text]
  migrate-engine.py --artifacts DIR --project-root DIR --apply --state-root DIR \\
                    --pm-status PATH [--dispose]
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
detect_layout = _load("detect_layout", "detect-layout.py")
_l3io = _load("read_l3io_flat", "read-l3io-flat.py")
_bmad = _load("read_bmad_flat", "read-bmad-flat.py")
_per_epic = _load("read_per_epic", "read-per-epic.py")
_split = _load("read_split", "read-split.py")
_artifacts = _load("read_artifacts", "read-artifacts.py")

# Keyed by the fixture directory name. test-engine.py asserts this key set equals the
# directories on disk, so a deleted fixture fails the suite rather than shrinking the
# corpus silently.
READERS = {
    "l3io-flat": lambda art, root, state: _l3io.read(art / "sprint-status.yaml"),
    "bmad-flat": lambda art, root, state: _bmad.read(art / "sprint-status.yaml"),
    "per-epic": lambda art, root, state: _per_epic.read(root / "_bmad" / "state"),
    "split": lambda art, root, state: _split.read(art),
    "artifacts": lambda art, root, state: _artifacts.read(art, state),
}

_KIND_ORDER = ("epic", "sprint", "story")


def detect(artifacts_dir: Path, project_root: Path) -> str:
    """Name the source layout present, or 'none'.

    Order matters. The split layout is checked FIRST because a split project also carries
    sprint-status.yaml, so checking the flat file first would misread every split project.
    And the flat file's SCHEMA is what separates l3io-flat from bmad-flat -- never its
    path, which both share.
    """
    art, root = Path(artifacts_dir), Path(project_root)

    if (art / "sprint-status-backlog.yaml").is_file() or \
       (art / "sprint-status-archived.yaml").is_file():
        return "split"

    flat = art / "sprint-status.yaml"
    if flat.is_file():
        schema = detect_layout.classify_flat(flat)
        if schema == "bmad":
            return "bmad-flat"
        if schema == "l3io":
            return "l3io-flat"

    legacy = root / "_bmad" / "state"
    if legacy.is_dir() and any(legacy.glob("*.yaml")):
        return "per-epic"

    if art.is_dir() and any(art.glob("epic-*/sprint-*/stories/*.md")):
        return "artifacts"

    return "none"


def gather(layout: str, artifacts_dir: Path, project_root: Path,
           state_root: Path | None = None) -> list:
    """Run the reader for `layout`. An unknown layout yields zero records.

    `state_root` is consumed by the artifacts reader when given, so an additive
    bootstrap on a project with partial sharded state emits records only for the
    orphan stories. The legacy-source readers ignore it -- they always parse
    their own source in full."""
    reader = READERS.get(layout)
    if reader is None:
        return []
    return sr.dedupe(reader(Path(artifacts_dir), Path(project_root),
                            Path(state_root) if state_root else None))


def source_is_empty(layout: str, artifacts_dir: Path, project_root: Path) -> bool:
    """True when the source this layout names holds no bytes worth parsing.

    Distinguishes 'there was nothing to migrate' (fine) from 'there was something and we
    parsed none of it' (the gate's business).
    """
    art, root = Path(artifacts_dir), Path(project_root)
    if layout in ("l3io-flat", "bmad-flat"):
        candidates = [art / "sprint-status.yaml"]
    elif layout == "split":
        candidates = [art / n for n in _split.SPLIT_FILES]
    elif layout == "per-epic":
        candidates = sorted((root / "_bmad" / "state").glob("*.yaml"))
    elif layout == "artifacts":
        candidates = sorted(art.glob("epic-*/sprint-*/stories/*.md"))
    else:
        candidates = []
    for p in candidates:
        try:
            if p.is_file() and p.read_text(encoding="utf-8").strip():
                return False
        except OSError:
            continue
    return True


def build_plan(records: list) -> dict:
    """Order records parents-first and report counts plus validation problems.

    Parents first is a hard requirement, not a nicety: `import-node` exits 3 on a sprint
    whose epic directory does not exist yet.
    """
    ordered = sorted(
        records,
        key=lambda r: _KIND_ORDER.index(r["kind"])
        if r.get("kind") in _KIND_ORDER else len(_KIND_ORDER))
    counts = {k: 0 for k in _KIND_ORDER}
    problems = []
    for rec in ordered:
        for p in sr.validate(rec):
            problems.append(f"{rec.get('kind')} {rec.get('key')!r}: {p}")
        if rec.get("kind") in counts:
            counts[rec["kind"]] += 1
    return {"records": ordered, "counts": counts, "problems": problems}


def render_plan(layout: str, plan: dict) -> str:
    lines = [
        f"MIGRATION PLAN -- source layout: {layout}",
        "=" * 64,
        f"  epics   {plan['counts']['epic']:>4}",
        f"  sprints {plan['counts']['sprint']:>4}",
        f"  stories {plan['counts']['story']:>4}",
    ]
    inferred = [r for r in plan["records"] if r.get("origin") == "inferred"]
    if inferred:
        lines.append(f"  ({len(inferred)} node(s) inferred, marked origin: inferred)")
    if plan["problems"]:
        lines.append("")
        lines.append("PROBLEMS:")
        lines.extend(f"  - {p}" for p in plan["problems"])
    lines.append("=" * 64)
    return "\n".join(lines) + "\n"


def gate(layout: str, plan: dict, artifacts_dir: Path, project_root: Path):
    """The pre-write gate. Returns a refusal message, or None to proceed.

    Two refusals, both BEFORE anything is written:

      1. The source holds content and the plan is EMPTY. This is the general form of the
         live defect -- a BMad-schema sprint-status.yaml read as if it were ours yields
         zero records, and the old prose then deleted the source while reporting success.
         The gate does not care WHY the parse produced nothing, which is exactly what
         makes it worth more than fixing any single cause.
      2. Any record failed validation. A plan that cannot be written correctly must not
         be half-written.
    """
    total = sum(plan["counts"].values())
    if total == 0 and not source_is_empty(layout, artifacts_dir, project_root):
        return (
            "BLOCKED: the source holds content but the plan is empty -- nothing would "
            f"be migrated.\n  layout detected: {layout}\n"
            "  Nothing has been written and the source is untouched.\n"
            "  A flat sprint-status.yaml carrying BMad's `development_status:` mapping "
            "is the common cause;\n  run `detect-layout.py --classify` to confirm which "
            "schema is present."
        )
    if plan["problems"]:
        listed = "\n".join(f"    - {p}" for p in plan["problems"][:10])
        more = "" if len(plan["problems"]) <= 10 else \
            f"\n    ... and {len(plan['problems']) - 10} more"
        return (
            f"BLOCKED: {len(plan['problems'])} record(s) failed validation.\n"
            f"{listed}{more}\n  Nothing has been written and the source is untouched."
        )
    return None


def _node_argv(rec: dict) -> list:
    """The node-addressing flags for one record. Keys are E001 / E001-S01 / E001-S01-002."""
    kind, key = rec["kind"], rec["key"]
    if kind == "epic":
        return ["--epic", key]
    if kind == "sprint":
        epic_key, sprint_num = key.split("-S")
        return ["--epic", epic_key, "--sprint", f"S{sprint_num}"]
    return ["--story", key]


def write(plan: dict, state_root: Path, pm_status: str):
    """Write every planned record with `pm-status.py import-node`, then dispatch any
    record `extras` through typed set-* verbs.

    Every node goes through the one writer verb -- never a direct file write -- so each
    lands under the same epic write lock, event log and status validation as any other
    state write. Returns (written_count, errors); a SKIP is not counted as written, which
    is what makes a retried migration idempotent.

    After import-node lands the node, any fields the reader captured in the record's
    `extras` are dispatched:
      - scalar fields (goal, superseded_by) via `set-field`, so they land on disk.
      - structured fields (depends_on, estimate, actual) now have typed writers:
      -   depends_on -> set-depends-on, estimate -> set-estimate, actual -> set-actual
      -   (--runtime other --tokens-na --no-calibrate). An UNRECOGNISED extra still WARNs naming
        the record and the value -- pm-status.py does not yet expose the typed
        set-* verbs those need, so silent loss becomes visible loss until the
        follow-up lands. See docs/superpowers/plans/... for the write-side backfill.
    A failed set-field is reported alongside import-node errors; the caller decides.
    """
    import subprocess

    written, errors = 0, []
    for rec in plan["records"]:
        argv = ["uv", "run", pm_status, "import-node",
                "--state-root", str(state_root),
                "--status", rec["status"], "--title", rec.get("title", "")]
        argv += _node_argv(rec)
        if rec.get("classification") and rec["kind"] == "story":
            argv += ["--classification", rec["classification"]]
        if rec.get("origin"):
            argv += ["--origin", rec["origin"],
                     "--origin-note", rec.get("origin_note", "")]

        proc = subprocess.run(argv, capture_output=True, check=False, text=True)
        if proc.returncode != 0:
            errors.append(
                f"{rec['kind']} {rec['key']}: exit {proc.returncode} -- "
                f"{proc.stderr.strip()}")
            continue
        if not proc.stdout.startswith("SKIP"):
            written += 1

        extras_errors = _apply_extras(rec, state_root, pm_status)
        errors.extend(extras_errors)
    return written, errors


def _apply_extras(rec: dict, state_root: Path, pm_status: str) -> list:
    """Consume rec['extras'] with set-field for scalars and WARN for structured fields.

    Returns any errors from set-field calls; the WARN branch never errors -- it prints
    to stderr and moves on, because the goal is visibility, not gating."""
    import subprocess

    errors = []
    extras = rec.get("extras") or {}
    for field, value in extras.items():
        if field in sr.SCALAR_EXTRAS_TO_SET_FIELD:
            argv = ["uv", "run", pm_status, "set-field",
                    "--state-root", str(state_root),
                    "--field", field, "--value", str(value)]
            argv += _node_argv(rec)
            proc = subprocess.run(argv, capture_output=True, check=False, text=True)
            if proc.returncode != 0:
                errors.append(
                    f"{rec['kind']} {rec['key']}: set-field {field}= failed -- "
                    f"{proc.stderr.strip()}")
        elif field == "depends_on":
            # List-shaped, so it needs the list-shaped verb: routing it through set-field
            # would store "['E001']" as a scalar, which a later reader takes for one.
            items = value if isinstance(value, (list, tuple)) else [value]
            argv = ["uv", "run", pm_status, "set-depends-on",
                    "--state-root", str(state_root)]
            argv += _node_argv(rec)
            for item in items:
                argv += ["--add", str(item)]
            proc = subprocess.run(argv, capture_output=True, check=False, text=True)
            if proc.returncode != 0:
                errors.append(
                    f"{rec['kind']} {rec['key']}: set-depends-on failed -- "
                    f"{proc.stderr.strip()}")
        elif field == "estimate":
            # The mapping's keys ARE set-estimate's flag names with underscores: man_hours ->
            # --man-hours, tokens_k_min -> --tokens-k-min. Point values and ranges both have a
            # flag, so the translation is mechanical and needs no per-metric table.
            #
            # cost is the exception and is DROPPED, not passed: it is derived from tokens at
            # capture time and frozen, set-estimate rejects --cost* outright (exit 2), and a
            # legacy cost is a number nobody can re-derive. Skipping it is the hard rule, not
            # a shortcut.
            if not isinstance(value, dict):
                errors.append(f"{rec['kind']} {rec['key']}: estimate is "
                              f"{type(value).__name__}, expected a mapping")
                continue
            argv = ["uv", "run", pm_status, "set-estimate",
                    "--state-root", str(state_root)]
            argv += _node_argv(rec)
            dropped = []
            for k, v in value.items():
                if str(k).startswith("cost"):
                    dropped.append(str(k))
                    continue
                argv += [f"--{str(k).replace('_', '-')}", str(v)]
            if dropped:
                sys.stderr.write(
                    f"NOTE {rec['kind']} {rec['key']}: estimate {', '.join(dropped)} not "
                    f"carried -- cost is derived from tokens at capture time, never stored "
                    f"from a source.\n")
            proc = subprocess.run(argv, capture_output=True, check=False, text=True)
            if proc.returncode != 0:
                errors.append(
                    f"{rec['kind']} {rec['key']}: set-estimate failed -- "
                    f"{proc.stderr.strip()}")
        elif field == "actual":
            # import-actual, not set-actual with three flags. Both write the same thing --
            # runtime=other, tokens=N/A, no calibration sample -- but set-actual only does so
            # if the caller passes all three, and omitting --no-calibrate poisons the learned
            # ratios silently rather than failing. import-actual fixes them in its defaults
            # and does not expose --runtime, --tokens-* or --calibrate at all, so a wrong call
            # is a usage error instead of a quiet one.
            #
            #   runtime=other   a migrated actual has no Claude provenance to claim
            #   tokens=N/A      legacy data carries no four-class split, and the sentinel is
            #                   the honest value -- 0 would be consumed by calibration as a
            #                   real measurement and drive the learned ratio toward zero
            #   no calibration  a bulk import must not append hundreds of samples in one pass;
            #                   `pm-status.py calibration redrive` rebuilds from the nodes
            #                   afterwards if they are wanted
            if not isinstance(value, dict):
                errors.append(f"{rec['kind']} {rec['key']}: actual is "
                              f"{type(value).__name__}, expected a mapping")
                continue
            argv = ["uv", "run", pm_status, "import-actual",
                    "--state-root", str(state_root), "--node", rec["kind"]]
            argv += _node_argv(rec)
            dropped = []
            for k, v in value.items():
                key = str(k)
                if key.startswith(("cost", "tokens")):
                    dropped.append(key)
                    continue
                argv += [f"--{key.replace('_', '-')}", str(v)]
            if dropped:
                sys.stderr.write(
                    f"NOTE {rec['kind']} {rec['key']}: actual {', '.join(dropped)} not carried "
                    f"-- cost is derived, and a legacy token total cannot be split into the "
                    f"four classes set-actual requires, so tokens land as the N/A sentinel "
                    f"rather than a fabricated split.\n")
            proc = subprocess.run(argv, capture_output=True, check=False, text=True)
            if proc.returncode != 0:
                errors.append(
                    f"{rec['kind']} {rec['key']}: import-actual failed -- "
                    f"{proc.stderr.strip()}")
        elif field in sr.STRUCTURED_EXTRAS_TO_WARN:
            sys.stderr.write(
                f"WARN {rec['kind']} {rec['key']}: skipping {field}={value!r} -- "
                f"pm-status.py has no typed writer for this field yet; the value "
                f"was in the source and is not being carried into state.\n")
        else:
            sys.stderr.write(
                f"WARN {rec['kind']} {rec['key']}: unrecognised extra {field}={value!r} -- "
                f"the reader captured a field the engine does not know how to route.\n")
    return errors


def _node_relpath(rec: dict):
    """(epic_key, path-relative-to-the-epic-directory) for one record."""
    kind, key = rec["kind"], rec["key"]
    if kind == "epic":
        return key, "epic.yaml"
    if kind == "sprint":
        epic_key, sprint_num = key.split("-S")
        return epic_key, os.path.join(f"sprint-{int(sprint_num):02d}", "sprint.yaml")
    epic_key, sprint_part, _ = key.split("-", 2)
    return epic_key, os.path.join(f"sprint-{int(sprint_part[1:]):02d}", f"{key}.yaml")


def verify_against_plan(plan: dict, state_root: Path) -> list:
    """Read the tree back and compare it to THE PLAN, not to itself.

    Stage E of the old prose checked its result against the set it had just produced, so
    an empty set verified clean. This reads each planned record's node off disk and
    compares key and status, so a node that was never written, or was written wrong, is
    reported.
    """
    from ruamel.yaml import YAML

    problems = []
    root = Path(state_root)
    for rec in plan["records"]:
        epic_key, rel = _node_relpath(rec)
        epic_dirname = f"epic-{int(epic_key[1:]):03d}"

        found = None
        for folder in ("active", "planned", "archived"):
            cand = root / folder / epic_dirname / rel
            if cand.is_file():
                found = cand
                break
        if found is None:
            problems.append(f"{rec['kind']} {rec['key']}: planned but not found on disk")
            continue
        try:
            node = YAML(typ="safe").load(found.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001 -- one unreadable node is reported, the verify continues
            problems.append(f"{rec['kind']} {rec['key']}: unreadable on disk -- {exc}")
            continue
        if not isinstance(node, dict):
            problems.append(f"{rec['kind']} {rec['key']}: not a mapping on disk")
            continue
        if str(node.get("status")) != rec["status"]:
            problems.append(
                f"{rec['kind']} {rec['key']}: status on disk {node.get('status')!r} "
                f"!= planned {rec['status']!r}")
    return problems


def dispose(layout: str, artifacts_dir: Path, project_root: Path) -> list:
    """Rename the source aside. NEVER deletes.

    The old Stage F `rm -f`'d the source. A rename to `.legacy` is recoverable by a human
    with no backup to find, and detect-layout.py deliberately does not match the `.legacy`
    name, so a migrated project reads clean afterwards.

    The 'artifacts' layout has no source to retire: story .md files are artifacts, and
    artifacts are never moved.
    """
    art, root = Path(artifacts_dir), Path(project_root)
    if layout in ("l3io-flat", "bmad-flat"):
        candidates = [art / "sprint-status.yaml"]
    elif layout == "split":
        candidates = [art / n for n in _split.SPLIT_FILES]
    elif layout == "per-epic":
        candidates = sorted((root / "_bmad" / "state").glob("*.yaml"))
    else:
        candidates = []

    moved = []
    for p in candidates:
        if p.is_file():
            p.rename(p.with_suffix(p.suffix + ".legacy"))
            moved.append(str(p))
    return moved


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="the doctor's migration engine")
    parser.add_argument("--artifacts", required=True)
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--plan", action="store_true", help="read-only: show the plan")
    parser.add_argument("--format", choices=["json", "text"], default="text")
    parser.add_argument("--apply", action="store_true", help="write the plan")
    parser.add_argument("--state-root", help="required with --apply")
    parser.add_argument("--pm-status", help="path to pm-status.py; required with --apply")
    parser.add_argument("--dispose", action="store_true",
                        help="rename the source aside after a verified write")
    args = parser.parse_args(argv)

    if args.apply and not (args.state_root and args.pm_status):
        parser.error("--apply requires --state-root and --pm-status")

    art, root = Path(args.artifacts), Path(args.project_root)
    layout = detect(art, root)
    if layout == "none":
        sys.stdout.write("No migratable source layout found -- nothing to do.\n")
        return 0

    # For the artifacts reader, the state root -- when we know it -- lets us skip
    # already-tracked stories so the plan lists only genuinely new work. In --plan
    # mode without --state-root we degrade to "show everything", the pre-existing
    # behaviour; --apply always has --state-root by the check above.
    state_for_reader = args.state_root if args.state_root else None
    plan = build_plan(gather(layout, art, root, state_for_reader))

    if not args.apply:
        if args.format == "json":
            json.dump({"layout": layout, **plan}, sys.stdout, indent=2)
            sys.stdout.write("\n")
        else:
            sys.stdout.write(render_plan(layout, plan))
        return 0

    refusal = gate(layout, plan, art, root)
    if refusal:
        sys.stderr.write(refusal + "\n")
        return 1

    written, errors = write(plan, Path(args.state_root), args.pm_status)
    if errors:
        sys.stderr.write("FAILED during write -- source untouched:\n")
        for e in errors:
            sys.stderr.write(f"  {e}\n")
        return 1

    problems = verify_against_plan(plan, Path(args.state_root))
    if problems:
        sys.stderr.write("FAILED verification against the plan -- source untouched:\n")
        for p in problems:
            sys.stderr.write(f"  {p}\n")
        return 1

    sys.stdout.write(f"OK wrote {written} node(s); verified against the plan.\n")
    if args.dispose:
        for p in dispose(layout, art, root):
            sys.stdout.write(f"  retired {p} -> {p}.legacy\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
