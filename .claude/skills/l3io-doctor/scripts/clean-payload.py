#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.11"
# ///
"""
clean-payload.py -- remove THIS extension's installed payload, and nothing else.

Dry run by default. Nothing is deleted without `--apply`.

Why a hash and not a path list
------------------------------
`bmad uninstall` removes the entire BMAD installation -- it has no `--modules` flag -- so
removing one extension is not something BMad can do, and a hand-written list of our paths
would drift from what we actually ship the first time a file moved.

Each skill carries a generated `payload-manifest.json`: a SHA-256 per payload file, keyed
relative to that skill's own root. That file already IS the answer to "which files are ours",
it is regenerated whenever payload changes, and `check:manifest` fails the build when it
drifts. So the delete set is derived from it, and the hash decides each file's fate:

  hash matches    -> ours, unmodified. Safe to remove.
  hash differs    -> REPORTED, never removed. Somebody edited it; that edit is theirs, and
                     this script is not entitled to an opinion about it.
  not in manifest -> not ours. Not touched, not mentioned.

Erring this way is deliberate. Leaving a modified file behind is an inconvenience the
operator can see and fix. Deleting one is unrecoverable, and this estate has already paid
for an over-broad delete once.

What it never touches
---------------------
Project state and artifacts. `{implementation_artifacts}/state/**` is the project's own data
-- epics, sprints, stories, the issue backlog, the calibration file -- written by the project
over months and merely READ by our skills. It appears in no payload manifest, so the derived
scope already excludes it; the exclusion is restated here because it is the one mistake that
would matter, and a reader should not have to infer it.

`_bmad/scripts/pm-status.py` IS removed when it matches a manifest hash: it is our payload,
self-installed, and reinstalled automatically at the next skill activation.
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

# Where an installer puts skills. Derived per-root rather than assumed: a project may carry
# one, both, or neither, and a missing one is not an error.
_SKILL_ROOTS = (".claude/skills", ".agents/skills")
_GENERATED_FROM = "skills/_shared/"
_SELF_INSTALLED = ("_bmad/scripts/pm-status.py",)


def sha256(p: Path) -> str | None:
    try:
        h = hashlib.sha256()
        with open(p, "rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def discover(project: Path) -> list[tuple[Path, dict]]:
    """(skill directory, manifest) for every installed skill of ours, under every skill root.

    Identity is a `payload-manifest.json` carrying this package's `generated_from`, so a BMad
    core skill in the same directory is never considered ours, and renaming our skills needs
    no change here.
    """
    found = []
    for root_rel in _SKILL_ROOTS:
        root = project / root_rel
        if not root.is_dir():
            continue
        for entry in sorted(root.iterdir(), key=lambda p: p.name):
            manifest = entry / "payload-manifest.json"
            if not (entry.is_dir() and manifest.is_file()):
                continue
            try:
                data = json.loads(manifest.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if data.get("generated_from") != _GENERATED_FROM:
                continue
            if isinstance(data.get("files"), dict):
                found.append((entry, data))
    return found


def plan(project: Path):
    """(removable, modified, missing, manifests) -- decided, nothing done."""
    removable, modified, missing, manifests = [], [], [], []
    for skill_dir, data in discover(project):
        manifests.append(skill_dir / "payload-manifest.json")
        for rel, want in data["files"].items():
            p = skill_dir / rel
            if not p.is_file():
                missing.append(p)
                continue
            got = sha256(p)
            (removable if got == want else modified).append(p)

    # The self-installed copy is payload too, and it is the one file of ours that lives
    # outside a skill directory. It is matched against any manifest that ships it, because
    # self-install writes whichever module home's copy ran -- there is no single owner.
    wanted = set()
    for _, data in discover(project):
        for rel, want in data["files"].items():
            if rel.endswith("scripts/pm-status.py"):
                wanted.add(want)
    for rel in _SELF_INSTALLED:
        p = project / rel
        if not p.is_file():
            continue
        got = sha256(p)
        if got in wanted:
            removable.append(p)
        else:
            modified.append(p)
    return removable, modified, missing, manifests


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="clean-payload.py", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project-root", required=True)
    ap.add_argument("--apply", action="store_true",
                    help="actually delete; without it nothing is changed")
    ap.add_argument("--format", choices=("text", "json"), default="text")
    a = ap.parse_args(argv)

    project = Path(a.project_root).resolve()
    if not project.is_dir():
        sys.stderr.write(f"clean-payload.py: --project-root {project} is not a directory\n")
        return 2

    removable, modified, missing, manifests = plan(project)
    if not (removable or modified or manifests):
        if a.format == "json":
            json.dump({"status": "none-found", "removable": [], "modified": []}, sys.stdout)
            sys.stdout.write("\n")
        else:
            sys.stdout.write(f"clean-payload: no l3io payload found under {project}\n")
        return 4

    def rel(p):
        return str(p.relative_to(project))

    if a.format == "json":
        json.dump({"status": "applied" if a.apply else "dry-run",
                   "removable": sorted(rel(p) for p in removable),
                   "modified": sorted(rel(p) for p in modified),
                   "missing": sorted(rel(p) for p in missing)},
                  sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        verb = "Removing" if a.apply else "Would remove"
        sys.stdout.write(f"{verb} {len(removable)} payload file(s) under {project}\n")
        for p in sorted(removable):
            sys.stdout.write(f"  - {rel(p)}\n")
        if modified:
            sys.stdout.write(
                f"\nKEEPING {len(modified)} modified file(s) -- the hash does not match what "
                f"we shipped,\nso somebody edited them. Delete by hand if you meant to:\n")
            for p in sorted(modified):
                sys.stdout.write(f"  ! {rel(p)}\n")
        if missing:
            sys.stdout.write(f"\n{len(missing)} manifest entr(ies) already absent.\n")
        sys.stdout.write("\nProject state and artifacts are not touched: they appear in no "
                         "payload manifest.\n")

    if not a.apply:
        return 0

    failed = []
    for p in removable + manifests:
        try:
            p.unlink()
        except OSError as e:
            failed.append(f"{rel(p)}: {e}")
    # Prune directories that our own files emptied, deepest first. Never recursive: a
    # non-empty directory is left alone, which is what keeps a stray file from taking its
    # whole tree with it.
    for d in sorted({p.parent for p in removable + manifests}, key=lambda p: -len(p.parts)):
        cur = d
        while cur != project and cur.is_dir():
            try:
                cur.rmdir()          # fails on a non-empty directory, which is the guard
            except OSError:
                break
            cur = cur.parent
    if failed:
        sys.stderr.write("clean-payload.py: could not remove:\n")
        for f in failed:
            sys.stderr.write(f"  {f}\n")
        return 2
    sys.stdout.write(f"Removed {len(removable)} payload file(s) and "
                     f"{len(manifests)} manifest(s).\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
