#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["ruamel.yaml>=0.18"]
# ///
"""
bmad-deps.py -- verify the installed BMad skills against the declared inventory. Read-only.

Why this exists
---------------
Three BMad releases renamed or removed skills this package dispatches, and nothing noticed
until someone installed 6.12.0 by hand: bmad-create-story and bmad-dev-story became shims,
bmad-review-adversarial-general merged into bmad-review, and
bmad-check-implementation-readiness was removed. Separately every presence probe read
.claude/commands/ while 6.12.0 installs to .claude/skills/, so an installed reviewer looked
absent and its gate silently self-skipped -- a skipped gate is indistinguishable from a
passed one.

check:docs check 16 asserts the step files agree with the inventory, but CI has no BMad
install (_bmad/ is gitignored). This script is the other half: it compares the same inventory
against a real install. Single consumer (l3io-doctor), so it ships in doctor's own
scripts/ per ADR-0001, like audit-backlog.py, with no sync group.

Usage
-----
  bmad-deps.py verify --project-root R [--inventory PATH] [--format {text,json}]

Exit 0 when every required skill resolves (optional ones only warn), 2 on a usage error or an
unparseable inventory -- bad JSON, a non-object top level, an absent, empty or non-list
`skills`, a non-object entry, or a `status`
outside STATUSES -- 3 when a required skill resolves nowhere, 4 when the inventory or the BMad
manifest cannot be read, 5 when `--strict` is passed and `status_contradictions` is non-empty.
Exit 4 covers a manifest that is missing or unreadable, but not one that is merely contentless:
a manifest parsing to no `installation` key is a successful read and the run proceeds, reporting
`BMad None`.

`--format json` emits nothing on the exit-2 and exit-4 paths; otherwise one object:
  bmad_version      installation.version, or null when the manifest omits it
  shims_installed   installation.installShims, false when the key is absent (pre-6.12)
  modules           the names in modules[], skipping any non-map entry
  resolved          [{name, status, resolved_as, path}] -- resolved_as is the preferred name,
                    or the fallback when the preferred one was absent
  missing_required  required entries resolving nowhere; non-empty is what makes the exit 3
  optional_absent   optional entries resolving nowhere -- a warning, the exit stays 0
  shims_in_use      [{name, path, replaced_by}] -- removed OR deprecated entries still present
                    on disk. A deprecated entry that resolves belongs here, not in `resolved`:
                    the field's own contract is "still present on disk", and a deprecated-but-
                    shipping skill fits that more precisely than a removed one does -- a removed
                    skill on disk is a leftover, a deprecated one is genuinely a shim in use.
  deprecated_absent [{name, replaced_by}] -- deprecated entries resolving nowhere. Reported
                    separately from `optional_absent` on purpose: a deprecated entry is not
                    optional, so "absent (optional -- its phase self-skips)" would be false for
                    it. This bucket is informational only and never affects the exit code.
  related_present   [{name, path, note}] -- related entries resolving somewhere. These are
                    third-party skills we do NOT dispatch (bmad-loop is the shape) but detect
                    for user-awareness: when present, l3io-help surfaces an overlap note so
                    users understand how the two flows fit together. Absent related skills are
                    silent by design (they are not our tooling; missing them is the default),
                    so there is no counterpart `related_absent` field.
  shipped_skills    sorted canonical ids from _bmad/_config/skill-manifest.csv column 1, or null
                    when that file is absent or unreadable -- the inventory is then unverifiable
                    against BMad's own declaration, which is reported as unknown, not agreement.
  status_contradictions
                    [{name, declared, manifest}] where `manifest` is "ships" (a `removed` entry
                    the manifest still ships) or "absent" (a `required`/`optional`/`deprecated`
                    entry -- i.e. one this inventory says should be in the manifest -- that the
                    manifest does not list). Always [] when shipped_skills is null. This is the
                    inventory-as-annotation check: the derived set is the manifest, and the
                    inventory's hand-kept statuses are claims about it that can be wrong.
  baseline_drift    [{field, expected, found}] -- `field` is "core_version" or "bmb_version";
                    non-empty when the installed manifest disagrees with
                    assets/bmad-baseline.json, the pinned pair every claim in this package's
                    docs was read against (ADR-0006). This is a WARNING, never a failure: BMad
                    moving on is normal; being unaware of it is the defect this field exists to
                    surface. It never changes the exit code, including under --strict. Empty
                    when the baseline file itself cannot be read (nothing to compare against,
                    not agreement).

Note: CI cannot run --strict. _bmad/ is gitignored, so the manifest is absent there and
load_shipped_skills() returns None. Contradiction detection is a runtime check, run
by /l3io-doctor check-deps against a real install -- the same division of labour
as the probe-path check.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import pathlib
import sys

from ruamel.yaml import YAML

DEFAULT_INVENTORY = pathlib.Path(__file__).resolve().parent.parent / "assets" / "bmad-dependencies.json"
DEFAULT_BASELINE = pathlib.Path(__file__).resolve().parent.parent / "assets" / "bmad-baseline.json"

# The only statuses this script knows how to act on. Anything else is a broken inventory, not
# a skill to be treated leniently -- see check_inventory().
#
# The five states carry distinct semantics:
#
#   required     -- we dispatch this; a missing one is a broken install, exit 3.
#   optional     -- we dispatch this in some phase; a missing one makes that phase self-skip.
#   related      -- we do NOT dispatch this. It is adjacent tooling users may have installed
#                   alongside us (bmad-loop is the shape); when present, we surface an
#                   informational note so users understand how the two flows fit together;
#                   when absent, that's the default, not a warning. Never counted as missing.
#   deprecated   -- BMad still ships this as a shim; if present here, we surface that its
#                   replacement is the newer name.
#   removed      -- BMad no longer ships this; if present anyway, we still surface it, since
#                   a stale install may carry it (the doctor's clean-legacy mode is the fix).
#   not-a-skill  -- token that looks like `bmad-*` but is not a skill (fixture directories,
#                   this script's own name, etc.); declared so check 16 doesn't trip on it.
STATUSES = ("required", "optional", "related", "deprecated", "removed", "not-a-skill")


def resolve(name: str, project_root: str) -> str | None:
    """Return the path `name` resolves to, or None. Both layouts, both roots.

    6.12.0 installs skills/<name>/SKILL.md; earlier releases install commands/<name>.md.
    Probing only one layout mis-detects an installed skill as absent on the other version,
    which is how a gate came to self-skip silently -- so both are always tried, under the
    project root first and then the user's home.
    """
    roots = [os.path.join(project_root, ".claude"),
             os.path.join(os.path.expanduser("~"), ".claude")]
    for root in roots:
        for rel in (os.path.join("skills", name, "SKILL.md"), os.path.join("commands", f"{name}.md")):
            p = os.path.join(root, rel)
            if os.path.exists(p):
                return p
    return None


def read_manifest(project_root: str):
    """(version, shims_installed, [module names], {module name: module version}) or None when
    unreadable.

    `installShims` exists only from 6.12.0 on, so it is read as absent-means-false: a
    KeyError here would crash on precisely the older install this script exists to protect.
    `modules` is a list of maps; a bare-string entry is skipped rather than fatal, and
    contributes no entry to the version map either.
    """
    mf = os.path.join(project_root, "_bmad", "_config", "manifest.yaml")
    if not os.path.exists(mf):
        return None
    try:
        with open(mf, encoding="utf-8") as fh:
            data = YAML(typ="safe").load(fh) or {}
    except Exception:  # noqa: BLE001 -- an unreadable manifest means 'unknown', not a crash
        return None
    inst = data.get("installation") or {}
    raw_modules = [m for m in (data.get("modules") or []) if isinstance(m, dict)]
    mods = [m.get("name") for m in raw_modules]
    module_versions = {m.get("name"): m.get("version") for m in raw_modules}
    return inst.get("version"), bool(inst.get("installShims", False)), mods, module_versions


def load_baseline(path) -> dict | None:
    """The pinned {core_version, bmb_version, ...} baseline, or None when it cannot be read.

    A missing or unparseable baseline means "nothing to compare against" -- reported as no
    drift, never as agreement, exactly like load_shipped_skills()'s None convention.
    """
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def compute_baseline_drift(core_version, bmb_version, baseline: dict | None) -> list[dict]:
    """[{field, expected, found}] for each of core_version/bmb_version that disagrees with the
    pinned baseline. A WARNING signal only -- callers must never fail on a non-empty result."""
    if baseline is None:
        return []
    drift = []
    for field, found in (("core_version", core_version), ("bmb_version", bmb_version)):
        expected = baseline.get(field)
        if expected is not None and found != expected:
            drift.append({"field": field, "expected": expected, "found": found})
    return drift


def load_shipped_skills(project_root: str) -> set[str] | None:
    """Canonical skill ids BMad declares it ships, from its own manifest.

    Returns None when the manifest is absent or unreadable -- the inventory is then
    unverifiable, which is reported as unknown rather than as agreement.
    """
    path = pathlib.Path(project_root) / "_bmad" / "_config" / "skill-manifest.csv"
    try:
        with path.open(encoding="utf-8", newline="") as fh:
            rows = csv.reader(fh)
            header = next(rows, None)
            if not header or header[0].strip() != "canonicalId":
                return None
            return {r[0].strip() for r in rows if r and r[0].strip()}
    except (OSError, csv.Error):
        return None


# Statuses that claim a skill belongs in BMad's manifest -- "removed" makes the opposite claim
# and is checked separately in find_contradictions(). "related" is deliberately absent: a
# related skill ships through its OWN package's installer (bmad-loop is the shape) and may
# or may not appear in BMad's skill-manifest.csv depending on whether BMad's own installer
# had a chance to see it. Either state is fine -- the manifest and the inventory are not
# claiming the same thing about a related skill, so there is no contradiction to find.
SHIPPED_STATUSES = {"required", "optional", "deprecated"}


def find_contradictions(entries, shipped: set[str] | None) -> list[dict]:
    """Inventory claims that BMad's own manifest disagrees with. Empty when shipped is None --
    an absent manifest makes the inventory unverifiable, not agreeable-with."""
    if shipped is None:
        return []
    out = []
    for e in entries:
        status = e.get("status")
        name = e.get("name")
        if status == "not-a-skill" or not name:
            continue
        in_manifest = name in shipped
        if status == "removed" and in_manifest:
            out.append({"name": name, "declared": status, "manifest": "ships"})
        elif status in SHIPPED_STATUSES and not in_manifest:
            out.append({"name": name, "declared": status, "manifest": "absent"})
    return out


def check_inventory(inv) -> str | None:
    """Return a complaint about the inventory's shape, or None when it is usable.

    This lives here, not only in check-docs.mjs: that check validates the *shipped* inventory,
    while --inventory accepts any path, so the script would otherwise trust a shape it never
    examined -- a guard proving its rule but not the rule's reach.

    An unknown `status` is fatal rather than lenient. Falling through to the optional bucket
    would report a typo'd "requried" skill as "optional -- its phase self-skips" and exit 0:
    a false green in exactly the class this script exists to prevent. A non-object top level
    or entry is fatal for the same reason read_manifest skips non-map modules -- an unchecked
    .get() would surface as exit 1, the one code this contract does not define.

    An absent or empty `skills` is fatal too, and the read is `.get("skills", [])` rather than
    `.get("skills") or []` for one reason: `or []` substituted the empty list *before* the
    isinstance guard below could see the bad value, so every falsy non-list -- {}, "", 0 -- and
    a missing key alike sailed through to exit 0, verifying nothing and printing only the
    version line. An inventory that declares no skills is not a usable inventory; a verifier
    that "passes" against one is the false green this whole script exists to prevent.
    """
    if not isinstance(inv, dict):
        return f"top level is {type(inv).__name__}, expected an object"
    if "skills" not in inv:
        return "no 'skills' key — an inventory declaring no skills verifies nothing"
    entries = inv["skills"]
    if not isinstance(entries, list):
        return f"'skills' is {type(entries).__name__}, expected a list"
    if not entries:
        return "'skills' is empty — an inventory declaring no skills verifies nothing"
    for i, e in enumerate(entries):
        if not isinstance(e, dict):
            return f"skills[{i}] is {type(e).__name__}, expected an object"
        if e.get("status") not in STATUSES:
            return (f"skills[{i}] ({e.get('name') or 'unnamed'}) has status "
                    f"{e.get('status')!r}, expected one of {', '.join(STATUSES)}")
    return None


def verify(args: argparse.Namespace) -> int:
    # Unreadable and unparseable are different failures with different exit codes: 4 says
    # "I could not look", 2 says "I looked and the inventory is broken".
    try:
        text = pathlib.Path(args.inventory).read_text(encoding="utf-8")
    except OSError as exc:
        print(f"cannot read inventory {args.inventory}: {exc}", file=sys.stderr)
        return 4
    try:
        inv = json.loads(text)
    except json.JSONDecodeError as exc:
        print(f"cannot parse inventory {args.inventory}: {exc}", file=sys.stderr)
        return 2
    complaint = check_inventory(inv)
    if complaint:
        print(f"cannot parse inventory {args.inventory}: {complaint}", file=sys.stderr)
        return 2
    man = read_manifest(args.project_root)
    if man is None:
        print(f"cannot read {args.project_root}/_bmad/_config/manifest.yaml — is BMad installed?",
              file=sys.stderr)
        return 4
    version, shims, modules, module_versions = man

    resolved, missing, shims_in_use, warnings, deprecated_absent, related_present = \
        [], [], [], [], [], []
    for e in inv["skills"]:  # a non-empty list of dicts; validated by check_inventory
        status = e.get("status")
        name = e.get("name")
        if status == "not-a-skill":
            continue
        if status in ("removed", "deprecated"):
            # Both statuses mean "still on disk, frozen, not to be treated as required or
            # optional" -- they differ only in whether BMad itself still ships the file. A
            # deprecated entry must not fall through to the required/optional branch below:
            # that would file a non-resolving deprecated skill as "optional -- self-skips",
            # which is false, and a resolving one as ordinary `resolved`, which buries the
            # exact signal `shims_in_use` exists to surface.
            hit = resolve(name, args.project_root)
            if hit:
                shims_in_use.append({"name": name, "path": hit,
                                     "replaced_by": e.get("replaced_by")})
            elif status == "deprecated":
                deprecated_absent.append({"name": name, "replaced_by": e.get("replaced_by")})
            continue
        if status == "related":
            # Adjacent tooling we do NOT dispatch. Present -> surface as informational so
            # callers can enable relationship-aware behaviour (e.g. l3io-help mentioning
            # bmad-loop's overlap). Absent -> silent: not our tooling, not a warning.
            hit = resolve(name, args.project_root)
            if hit:
                related_present.append({"name": name, "path": hit,
                                        "note": e.get("note", "")})
            continue
        hit, used = resolve(name, args.project_root), name
        if hit is None and e.get("fallback"):
            hit, used = resolve(e["fallback"], args.project_root), e["fallback"]
        if hit is None:
            (missing if status == "required" else warnings).append(name)
            continue
        resolved.append({"name": name, "status": status, "resolved_as": used, "path": hit})

    shipped = load_shipped_skills(args.project_root)
    contradictions = find_contradictions(inv["skills"], shipped)
    shipped_skills = sorted(shipped) if shipped is not None else None

    baseline = load_baseline(args.baseline)
    baseline_drift = compute_baseline_drift(version, module_versions.get("bmb"), baseline)

    if args.format == "json":
        print(json.dumps({"bmad_version": version, "shims_installed": shims,
                          "modules": modules, "resolved": resolved,
                          "missing_required": missing, "optional_absent": warnings,
                          "shims_in_use": shims_in_use,
                          "deprecated_absent": deprecated_absent,
                          "related_present": related_present,
                          "shipped_skills": shipped_skills,
                          "status_contradictions": contradictions,
                          "baseline_drift": baseline_drift}, indent=2))
    else:
        print(f"BMad {version} — modules: {', '.join(str(m) for m in modules)}")
        for r in resolved:
            note = "" if r["resolved_as"] == r["name"] else f"  (via {r['resolved_as']})"
            print(f"  ok       {r['name']}{note}")
        for n in warnings:
            print(f"  absent   {n} (optional — its phase self-skips)")
        for r in related_present:
            note = f" — {r['note']}" if r.get("note") else ""
            print(f"  related  {r['name']} is installed alongside this package{note}")
        for s in shims_in_use:
            print(f"  shim     {s['name']} is a deprecated shim; {s['replaced_by']} replaces it")
        for d in deprecated_absent:
            print(f"  gone     {d['name']} is deprecated and not installed here; "
                  f"{d['replaced_by']} is its replacement")
        for c in contradictions:
            if c["manifest"] == "ships":
                print(f"  CONTRADICTION  {c['name']} is declared {c['declared']} but BMad's "
                      f"manifest still ships it")
            else:
                print(f"  CONTRADICTION  {c['name']} is declared {c['declared']} but BMad's "
                      f"manifest does not list it")
        for d in baseline_drift:
            print(f"  BASELINE  {d['field']} drift: pinned {d['expected']!r}, "
                  f"installed {d['found']!r} (warning only — see assets/bmad-baseline.json)")
        for n in missing:
            print(f"  MISSING  {n} (required)")
        if missing:
            # Flush first: unflushed stdout would otherwise let this summary surface ahead of
            # the report it summarizes whenever the two streams are captured separately.
            sys.stdout.flush()
            print(f"\n{len(missing)} required skill(s) resolve nowhere. Install them, or run "
                  f"`npx bmad-method install --modules bmm` to refresh.", file=sys.stderr)

    if missing:
        return 3
    if args.strict and contradictions:
        return 5
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="bmad-deps.py", description=__doc__.split("\n")[1])
    sub = ap.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("verify", help="check the installed skills against the inventory")
    v.add_argument("--project-root", required=True)
    v.add_argument("--inventory", default=str(DEFAULT_INVENTORY))
    v.add_argument("--baseline", default=str(DEFAULT_BASELINE),
                   help="pinned {core_version, bmb_version, ...} to compare against "
                        "(warning-only, never affects the exit code)")
    v.add_argument("--format", choices=("text", "json"), default="text")
    v.add_argument("--strict", action="store_true",
                   help="exit 5 when status_contradictions is non-empty")
    v.set_defaults(fn=verify)
    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
