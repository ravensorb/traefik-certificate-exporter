#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["ruamel.yaml>=0.18"]
# ///
"""
report-version.py -- which l3io-extensions version this project is running. Read-only.

Why this exists
---------------
Three consumers independently asked "which l3io am I on?" and had no way to answer it.
`_bmad/_config/manifest.yaml` records a custom-source module's `version` as the git ref
that was cloned, so a project tracking the default branch reads `version: main` -- which
is accurate and useless. Pinning a tag would make it read `3.2.4` and would also freeze
the module on that ref for every later upgrade, so it is not the answer either.

The version IS in the installed tree, in two places the installer writes:

  * `<skill>/payload-manifest.json` -> `version`, in every skill that ships payload
  * `<module home>/assets/module.yaml` -> `module_version`, in the four module homes

Both come from `package.json` at build time and are guarded in CI (`check:manifest`
reports STALE on drift; `check:version` asserts the module homes agree). This script
reads them back.

Why it does NOT lead with the installed pm-status.py
----------------------------------------------------
`check-pm-status` answers a different question -- is the *self-installed* copy at
`{project-root}/_bmad/scripts/pm-status.py` current -- and that copy is written by
self-install at skill activation, not by the installer. So immediately after a correct
upgrade it is still the previous version and `check-pm-status` correctly reports STALE,
which reads as a failed upgrade. That is a legitimate transient for exactly one
invocation. This script reports the shipped version as its headline (correct the instant
the installer finishes) and the self-installed copy only as a secondary, labelled line.

Scope is derived, never enumerated
----------------------------------
Skills are discovered by scanning `--skills-root` for a `payload-manifest.json` whose
`generated_from` is this package's shared source. A hand-kept skill list would drift from
the install -- and a reporter that silently covers fewer skills than are installed is
worse than none, because it would report agreement over a set that no longer contains the
disagreement. The four deprecated forwarders ship no payload and so carry no manifest;
their absence is correct and is not a finding.

Exit codes
----------
0 -- every discovered skill and module home reports the same version
3 -- they disagree (a partial or interrupted install); the disagreement is printed
4 -- no l3io skills discovered under --skills-root
2 -- usage error
"""
import argparse
import json
import re
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_GENERATED_FROM = "skills/_shared/"
_INSTALLED_PM_STATUS = Path("_bmad") / "scripts" / "pm-status.py"


def _load_yaml(path: Path):
    """Parse with a real YAML parser rather than a regex over `module_version:`.

    `check-pm-status.py` greps that one field on purpose -- it must run with no
    dependencies at all. This script already needs ruamel for nothing else, but the
    project rule is that a format gets its parser, and a regex here would also read a
    `module_version` that happened to appear inside the `module_greeting` block scalar
    two lines below it.
    """
    from ruamel.yaml import YAML
    with open(path, encoding="utf-8") as fh:
        return YAML(typ="safe").load(fh)


def discover(skills_root: Path) -> list[dict]:
    """One record per l3io skill found under `skills_root`, sorted by name.

    Identity is `payload-manifest.json` carrying our `generated_from`, so a BMad core
    skill sitting in the same `.claude/skills/` directory is not mistaken for ours and a
    future rename of our skills needs no change here.
    """
    found = []
    if not skills_root.is_dir():
        return found
    for entry in sorted(skills_root.iterdir(), key=lambda p: p.name):
        if not entry.is_dir():
            continue
        manifest = entry / "payload-manifest.json"
        if not manifest.is_file():
            continue
        rec = {"skill": entry.name, "payload_version": None, "module_code": None,
               "module_version": None, "errors": []}
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            rec["errors"].append(f"payload-manifest.json unreadable: {e}")
            found.append(rec)
            continue
        if data.get("generated_from") != _GENERATED_FROM:
            continue                      # not ours
        rec["payload_version"] = data.get("version")
        module_yaml = entry / "assets" / "module.yaml"
        if module_yaml.is_file():
            try:
                my = _load_yaml(module_yaml) or {}
                rec["module_code"] = my.get("code")
                rec["module_version"] = my.get("module_version")
            except Exception as e:        # noqa: BLE001 -- any parse failure is a finding, not a crash
                rec["errors"].append(f"module.yaml unreadable: {e}")
        found.append(rec)
    return found


def installed_pm_status(project_root: Path) -> str | None:
    """The version marker of the self-installed copy, or None if absent/unreadable.

    Read from the file's marker rather than by executing it: this is a reporting path
    and spawning the script under `uv` to ask its version costs a subprocess and can
    fail for reasons that have nothing to do with the version.
    """
    p = project_root / _INSTALLED_PM_STATUS
    try:
        with open(p, encoding="utf-8") as fh:
            head = fh.read(4096)
    except OSError:
        return None
    m = re.search(r"^#\s*pm-status-version:\s*(\S+)", head, re.MULTILINE)
    return m.group(1) if m else None


_BMAD_MANIFEST = Path("_bmad") / "_config" / "manifest.yaml"
_REGISTRY = "https://registry.npmjs.org/bmad-method/latest"


def installed_bmad(project_root: Path) -> str | None:
    """The BMad version from `_bmad/_config/manifest.yaml` -> `installation.version`.

    That is the key BMad's own installer writes (tools/installer/core/manifest.js), and it
    is the only place the core version is recorded: `modules.core.version` mirrors it, and a
    custom-source module records a git ref instead, which is why we do not read one here.
    """
    path = project_root / _BMAD_MANIFEST
    if not path.is_file():
        return None
    data = _load_yaml(path)
    if not isinstance(data, dict):
        return None
    inst = data.get("installation")
    v = inst.get("version") if isinstance(inst, dict) else None
    return str(v) if v else None


def latest_bmad(timeout: float = 5.0) -> tuple[str | None, str | None]:
    """(version, error). NEVER raises and never fails the command.

    This is the one network call in a read-only diagnostic, so it is opt-in (--check-latest)
    and degrades to a reported reason. A version check that turns `/l3io-doctor version`
    into a failure on a plane is worse than not having it: the offline user still needs the
    local half of the report, which is the half that answers "which l3io am I on?".
    """
    import json as _json
    import urllib.error
    import urllib.request
    try:
        # _REGISTRY is a fixed https literal, never user input.
        with urllib.request.urlopen(_REGISTRY, timeout=timeout) as r:
            return str(_json.loads(r.read()).get("version") or "") or None, None
    except urllib.error.URLError as e:
        return None, f"registry unreachable ({e.reason})"
    except Exception as e:  # noqa: BLE001 -- a diagnostic must not die on an unexpected shape
        return None, f"{type(e).__name__}: {e}"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="report-version.py", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--skills-root", default=str(_HERE.parent.parent),
                    help="directory holding the installed skills "
                         "(default: this skill's parent, i.e. its sibling skills)")
    ap.add_argument("--project-root", default=None,
                    help="also report the self-installed pm-status.py under this root")
    ap.add_argument("--format", choices=("text", "json"), default="text")
    ap.add_argument("--check-latest", action="store_true",
                    help="also ask the npm registry whether BMad is current (one network "
                         "call; reports the reason and still succeeds if it cannot reach it)")
    a = ap.parse_args(argv)

    skills = discover(Path(a.skills_root))
    versions = {r["payload_version"] for r in skills if r["payload_version"]}
    versions |= {r["module_version"] for r in skills if r["module_version"]}
    pm_installed = (installed_pm_status(Path(a.project_root))
                    if a.project_root else None)
    bmad_installed = installed_bmad(Path(a.project_root)) if a.project_root else None
    bmad_latest, bmad_err = latest_bmad() if a.check_latest else (None, None)

    if not skills:
        if a.format == "json":
            json.dump({"status": "none-found", "skills_root": a.skills_root,
                       "skills": []}, sys.stdout)
            sys.stdout.write("\n")
        else:
            sys.stdout.write(
                f"l3io-extensions: no l3io skills found under {a.skills_root}\n"
                f"Fix: pass --skills-root, or reinstall -- a standard install puts them "
                f"in .claude/skills/.\n")
        return 4

    status = "current" if len(versions) == 1 else "mixed"
    if a.format == "json":
        json.dump({"status": status,
                   "version": next(iter(versions)) if len(versions) == 1 else None,
                   "versions": sorted(versions),
                   "installed_pm_status": pm_installed,
                   "bmad": {"installed": bmad_installed, "latest": bmad_latest,
                            "current": (None if not (bmad_installed and bmad_latest)
                                        else bmad_installed == bmad_latest),
                            "error": bmad_err},
                   "skills": skills}, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0 if status == "current" else 3

    if status == "current":
        sys.stdout.write(f"l3io-extensions {next(iter(versions))} "
                         f"({len(skills)} skills installed)\n")
    else:
        sys.stdout.write(f"l3io-extensions: MIXED VERSIONS {', '.join(sorted(versions))}\n"
                         f"A partial or interrupted install. Re-run the upgrade.\n")
    for r in skills:
        mod = f"  module {r['module_code']} {r['module_version']}" if r["module_code"] else ""
        sys.stdout.write(f"  {r['skill']:<20} {r['payload_version'] or '?'}{mod}\n")
        for e in r["errors"]:
            sys.stdout.write(f"    ! {e}\n")
    if a.project_root:
        if pm_installed is None:
            sys.stdout.write(
                "\nself-installed pm-status.py: absent -- written by self-install at skill\n"
                "activation, not by the installer. Normal before the first l3io run.\n")
        else:
            note = "" if pm_installed in versions else \
                   "  (refreshed at the next skill activation, not by the installer)"
            sys.stdout.write(f"\nself-installed pm-status.py: {pm_installed}{note}\n")
        if bmad_installed:
            line = f"BMad: {bmad_installed}"
            if bmad_latest:
                line += (" (current)" if bmad_installed == bmad_latest
                         else f" -- latest is {bmad_latest}")
            elif bmad_err:
                line += f" (latest unknown: {bmad_err})"
            sys.stdout.write(line + "\n")
        else:
            sys.stdout.write(
                "BMad: version not recorded -- no _bmad/_config/manifest.yaml under "
                "the given --project-root\n")
    return 0 if status == "current" else 3


if __name__ == "__main__":
    sys.exit(main())
