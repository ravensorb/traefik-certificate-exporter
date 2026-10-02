#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.11"
# ///
"""
merge-help-csv.py -- register a module's capabilities in BMad's help index.

Targets {project-root}/_bmad/_config/bmad-help.csv, which is the file the help system
actually reads. bmb's scaffolder targets _bmad/module-help.csv, which does not exist in
a core 6.12 install. See ADR-0007.

Anti-zombie: every row belonging to --module-code is dropped before the module's current
rows are appended, so a capability removed from the module cannot survive as a stale row.
Other modules' rows keep their original order.

Do not call this from module-setup.md. skills/_shared/module-setup.md records that the
installer, not setup, assembles _bmad/_config/bmad-help.csv from each module's own
module-help.csv at install time. This script exists only to satisfy
validate-module.py's presence check and to let a user re-register a module's help rows by
hand after an interrupted install -- wiring it into setup would put two writers on one
file, the exact defect class this package's config-layer split was written to avoid.
"""
import argparse
import csv
import sys
from pathlib import Path

HELP_REL = ("_bmad", "_config", "bmad-help.csv")
MODULE_COLUMN = 1


def reject_unresolved(label: str, value: str) -> str:
    if "{project-root}" in value:
        sys.stderr.write(
            f"error: {label} contains an unresolved {{project-root}} token: {value}\n"
            "Resolve it to a real path before invoking this script.\n")
        raise SystemExit(2)
    return value


def merge(target: Path, module_code: str, rows: list[list[str]]) -> None:
    header, kept = None, []
    if target.exists():
        with target.open(encoding="utf-8", newline="") as fh:
            all_rows = list(csv.reader(fh))
        if all_rows:
            header, body = all_rows[0], all_rows[1:]
            kept = [r for r in body
                    if len(r) <= MODULE_COLUMN or r[MODULE_COLUMN].strip() != module_code]
    if header is None:
        header = ["skill", "module", "description"]
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(header)
        writer.writerows(kept)
        writer.writerows(rows)


def main() -> int:
    p = argparse.ArgumentParser(description="Merge a module's help rows into bmad-help.csv.")
    p.add_argument("--project-root", required=True)
    p.add_argument("--module-help-csv", required=True,
                   help="the module's own assets/module-help.csv")
    p.add_argument("--module-code", required=True)
    args = p.parse_args()

    root = Path(reject_unresolved("--project-root", args.project_root))
    source = Path(reject_unresolved("--module-help-csv", args.module_help_csv))

    with source.open(encoding="utf-8", newline="") as fh:
        rows = [r for r in csv.reader(fh) if r]
    if rows and rows[0] and rows[0][0].strip() == "skill":
        rows = rows[1:]

    merge(root.joinpath(*HELP_REL), args.module_code, rows)
    print(f"merged {len(rows)} help row(s) for {args.module_code}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
