#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml"]
# ///
"""
Compute local drift for l3io-pm-sync — what has changed in BMad state
since the last sync, without making any remote API calls.

Usage: uv run drift-report.py <project-root>

Output (stdout): JSON drift manifest
Errors (stderr): human-readable messages with non-zero exit code

The manifest contains:
  unmapped_local  — BMad entities not yet in sync-state (never pushed)
  changed_local   — entities whose current content hash differs from last_synced_hash
  missing_local   — sync-state entries with no corresponding BMad file (deleted locally)

State layout
------------
l3io-pm state lives under `{implementation_artifacts}/state/{planned,active,archived}/`
(the sharded layout — see skills/_shared/status-files.md, the canonical contract).
Each epic is a directory (`epic-{nnn}`, 3-digit zero-padded) containing a bare
`epic.yaml` node and one `sprint-{nn}` (2-digit zero-padded) subdirectory per sprint,
each holding a bare `sprint.yaml` node plus one `{story-key}.yaml` file per story.
Nodes are stored bare (no `epics:`/`sprints:`/`stories:` list wrapper) — the
directory tree itself is the list. Deferred backlog items live in a single flat
`state/issues.yaml` file, independent of the per-epic status folders.
"""

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

import yaml


# BMad central config is resolved by core's resolver over four TOML layers — see
# references/config-resolution.md. There is no _bmad/config.yaml; reading one silently
# yielded {} and pinned every path to the default.
CORE_RESOLVER = "_bmad/scripts/resolve_config.py"
SYNC_CONFIG_FILE = "_bmad/sync-config.yaml"
SYNC_STATE_FILE = "_bmad/sync-state.yaml"

# Status folders under {implementation_artifacts}/state/, walked in this order for
# determinism. Mirrors skills/_shared/pm-status.py's STATUS_DIRS ("active" first —
# hottest path there because it resolves a single epic; here we walk all three, so
# order only affects the sequence entities appear in the manifest).
STATUS_DIRS = ("active", "planned", "archived")


def load_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    with path.open() as f:
        return yaml.safe_load(f) or {}


def resolve_config(project_root: Path) -> dict:
    """Resolve implementation_artifacts through BMad core's config resolver.

    The resolver merges the four TOML layers and prints JSON. It is installed by BMad
    core; if it is missing, BMad is not installed and we fall back to the documented
    default rather than inventing a path.
    """
    resolver = project_root / CORE_RESOLVER
    cfg: dict = {}
    if resolver.exists():
        try:
            proc = subprocess.run(
                [sys.executable, str(resolver), "--project-root", str(project_root)],
                capture_output=True,
                text=True,
                check=True,
            )
            cfg = json.loads(proc.stdout or "{}")
            # The resolver exits 0 but warns on stderr when a layer is malformed, and
            # silently drops that whole layer. Swallowing it would turn a typo in a
            # custom config into paths that quietly revert to defaults.
            if proc.stderr:
                sys.stderr.write(proc.stderr)
        except (subprocess.CalledProcessError, json.JSONDecodeError) as error:
            sys.stderr.write(f"warning: config resolution failed ({error}); using defaults\n")

    core = cfg.get("core") or {}
    pm = (cfg.get("modules") or {}).get("l3io-pm") or {}

    output_folder = core.get("output_folder") or str(project_root / "_bmad-output")
    impl = pm.get("implementation_artifacts") or f"{output_folder}/implementation-artifacts"
    return {"implementation_artifacts": impl}


def load_sync_state(project_root: Path) -> list[dict]:
    state = load_yaml(project_root / SYNC_STATE_FILE)
    return state.get("mappings", [])


def compute_hash(fields: dict) -> str:
    canonical = json.dumps(fields, sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(canonical.encode()).hexdigest()[:8]


def extract_story_fields(story_path: Path, status: str, story_node: dict) -> dict:
    """Extract the fields that participate in drift detection from a story's authored
    markdown (`story_path`, under the top-level `{implementation_artifacts}/epic-{nnn}/
    sprint-{nn}/stories/` tree — human/agent-authored, never moves) and its sharded state
    node (`story_node`, the bare mapping loaded from `state/{status}/epic-{nnn}/
    sprint-{nn}/{story-key}.yaml`)."""
    title = ""
    description = ""
    ac = ""
    assignee = story_node.get("assignee", "")
    tags = sorted(story_node.get("tags", []) or [])

    if story_path.exists():
        content = story_path.read_text(encoding="utf-8")
        # Extract title from first H1
        title_match = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
        if title_match:
            title = title_match.group(1).strip()

        # Extract description: between H1 and ## Acceptance Criteria
        ac_match = re.search(r"^##\s+Acceptance Criteria", content, re.MULTILINE | re.IGNORECASE)
        h1_match = re.search(r"^#\s+.+$", content, re.MULTILINE)
        if h1_match and ac_match:
            start = h1_match.end()
            end = ac_match.start()
            description = content[start:end].strip()
        elif h1_match:
            description = content[h1_match.end():].strip()

        # Extract AC section
        if ac_match:
            ac_content = content[ac_match.end():]
            # Stop at next H2
            next_h2 = re.search(r"^##\s+", ac_content, re.MULTILINE)
            if next_h2:
                ac = ac_content[:next_h2.start()].strip()
            else:
                ac = ac_content.strip()

    # Story-level estimate is a single value per metric — not the low/high range used at
    # sprint/epic level. See status-files.md §4. The metric set is METRIC_FIELDS:
    # elapsed_hours (formerly time_hours — the old name reads as 0 forever), man_hours,
    # hitl_hours, tokens_k (a MAPPING since the metrics rework; `total` is the figure that
    # is banded and compared), and the derived cost.
    estimate = story_node.get("estimate", {}) or {}
    tokens = estimate.get("tokens_k", 0)
    if hasattr(tokens, "get"):
        tokens = tokens.get("total", 0)
    return {
        "title": title.lower(),
        "description": description,
        "acceptance_criteria": ac,
        "status": status,
        "assignee": str(assignee).strip().lower(),
        "tags": tags,
        "estimates": {
            "man_hours": estimate.get("man_hours", 0),
            "hitl_hours": estimate.get("hitl_hours", 0),
            "elapsed_hours": estimate.get("elapsed_hours", 0),
            "tokens_k": tokens,
            "cost": estimate.get("cost", 0),
        },
    }


def _relative_or_absolute(path: Path, project_root: Path) -> str:
    """Best-effort project-relative path string; falls back to the absolute path if
    `path` is not actually under `project_root` (e.g. implementation_artifacts configured
    outside the project tree)."""
    try:
        return str(path.relative_to(project_root))
    except ValueError:
        return str(path)


def collect_bmad_entities(project_root: Path, impl_artifacts: str) -> tuple[list[dict], bool]:
    """Walk the sharded state tree and collect every epic, sprint, story, and backlog
    entity. See skills/_shared/status-files.md for the layout this mirrors.

    Returns (entities, state_root_found). `state_root_found` is False only when
    `{implementation_artifacts}/state/` itself does not exist on disk — distinct from a
    state root that exists but is (as yet) empty, so callers can tell "nothing to
    analyse yet" apart from "analysed and found zero drift".
    """
    impl_path = Path(impl_artifacts)
    state_root = impl_path / "state"
    entities: list[dict] = []

    if not state_root.is_dir():
        return entities, False

    for status_dir in STATUS_DIRS:
        status_path = state_root / status_dir
        if not status_path.is_dir():
            continue
        for epic_dir in sorted(p for p in status_path.iterdir() if p.is_dir()):
            if not epic_dir.name.startswith("epic-"):
                continue
            epic_node = load_yaml(epic_dir / "epic.yaml")
            # Bare node — no `epics:` wrapper. `epic-{nnn}` (3-digit) is both the
            # directory name and the source of the bmad_key's numeric suffix.
            epic_num = epic_dir.name.split("-", 1)[1]
            epic_key = f"E{epic_num}"

            entities.append({
                "bmad_key": epic_key,
                "bmad_type": "epic",
                "bmad_path": None,
                "fields": {
                    "title": (epic_node.get("title") or "").strip().lower(),
                    "status": epic_node.get("status", ""),
                    "goal": (epic_node.get("goal") or "").strip(),
                },
            })

            for sprint_dir in sorted(p for p in epic_dir.iterdir() if p.is_dir()):
                if not sprint_dir.name.startswith("sprint-"):
                    continue
                sprint_node = load_yaml(sprint_dir / "sprint.yaml")
                sprint_num = sprint_dir.name.split("-", 1)[1]
                sprint_key = f"S{sprint_num}"

                entities.append({
                    "bmad_key": f"{epic_key}-{sprint_key}",
                    "bmad_type": "sprint",
                    "bmad_path": None,
                    "fields": {
                        "title": (sprint_node.get("title") or "").strip().lower(),
                        "status": sprint_node.get("status", ""),
                    },
                })

                # Every *.yaml file in the sprint directory except sprint.yaml is a
                # story node — the directory listing IS the `stories:` list.
                story_files = sorted(
                    p for p in sprint_dir.iterdir()
                    if p.is_file() and p.suffix == ".yaml" and p.name != "sprint.yaml"
                )
                for story_path in story_files:
                    story_node = load_yaml(story_path)
                    # The filename is the authoritative key (it's what pm-status.py
                    # resolves by) — fall back to it if the node itself is empty/corrupt
                    # so a single bad file doesn't drop the entity from the walk.
                    story_key = str(story_node.get("key") or story_path.stem)

                    story_md_path = (
                        impl_path
                        / epic_dir.name
                        / sprint_dir.name
                        / "stories"
                        / f"{story_key}.md"
                    )
                    fields = extract_story_fields(
                        story_md_path, story_node.get("status", ""), story_node
                    )
                    entities.append({
                        "bmad_key": story_key,
                        "bmad_type": "story",
                        "bmad_path": _relative_or_absolute(story_md_path, project_root),
                        "fields": fields,
                        "file_exists": story_md_path.exists(),
                    })

    # Deferred backlog items — a single flat file, independent of the per-epic status
    # folders (state/issues.yaml; see status-files.md's "one exception: append-issue").
    issues_data = load_yaml(state_root / "issues.yaml")
    for item in issues_data.get("backlog", []):
        key = item.get("key", "")
        if key:
            entities.append({
                "bmad_key": key,
                "bmad_type": "backlog",
                "bmad_path": None,
                "fields": {
                    "title": (item.get("title") or "").strip().lower(),
                    "status": "backlog",
                },
            })

    return entities, True


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="drift-report.py",
        description=(
            "Compute local drift for l3io-pm-sync. "
            "Reports BMad entities that are unmapped, changed, or missing since the last sync. "
            "Does not make remote API calls. Output: JSON drift manifest."
        ),
    )
    parser.add_argument(
        "project_root",
        help="Path to the project root containing _bmad/ (config and sync state)",
    )
    args = parser.parse_args()
    project_root = Path(args.project_root).resolve()
    if not project_root.is_dir():
        print(f"ERROR: project-root not found: {project_root}", file=sys.stderr)
        return 1

    cfg = resolve_config(project_root)
    impl_artifacts = cfg["implementation_artifacts"]

    mappings = load_sync_state(project_root)
    mapped_keys = {m["bmad_key"]: m for m in mappings}

    entities, state_root_found = collect_bmad_entities(project_root, impl_artifacts)
    entity_keys = {e["bmad_key"] for e in entities}

    if not state_root_found:
        # Distinct from "analysed and found zero drift" — there is nothing to analyse
        # yet. This is a normal first-run state (see status-files.md §10, case 4), not
        # an error, so we still exit 0 and emit a valid manifest — but the manifest
        # itself is marked so callers can tell the two situations apart, and any
        # pre-existing sync-state mappings still surface honestly as missing_local
        # below rather than being silently swallowed.
        print(
            f"NOTE: no state directory found at {impl_artifacts}/state — nothing to "
            "analyse. This is expected before the first l3io-pm-plan/l3io-pm-execute "
            "run; if a legacy layout is present instead, run "
            "`/l3io-util-doctor migrate-state` to upgrade it.",
            file=sys.stderr,
        )

    unmapped_local = []
    changed_local = []
    missing_local = []

    # Check each BMad entity against sync-state
    for entity in entities:
        key = entity["bmad_key"]
        current_hash = compute_hash(entity["fields"])

        if key not in mapped_keys:
            unmapped_local.append({
                "bmad_key": key,
                "bmad_type": entity["bmad_type"],
                "bmad_path": entity.get("bmad_path"),
                "current_hash": current_hash,
            })
        else:
            mapping = mapped_keys[key]
            last_hash = mapping.get("last_synced_hash", "")
            if current_hash != last_hash:
                changed_local.append({
                    "bmad_key": key,
                    "bmad_type": entity["bmad_type"],
                    "bmad_path": entity.get("bmad_path"),
                    "remote_id": mapping.get("remote_id"),
                    "remote_url": mapping.get("remote_url"),
                    "current_hash": current_hash,
                    "last_synced_hash": last_hash,
                    "last_synced_at": mapping.get("last_synced_at"),
                })

    # Check for sync-state entries with no corresponding BMad entity
    for mapping in mappings:
        key = mapping["bmad_key"]
        if key not in entity_keys:
            missing_local.append({
                "bmad_key": key,
                "bmad_type": mapping.get("bmad_type"),
                "bmad_path": mapping.get("bmad_path"),
                "remote_id": mapping.get("remote_id"),
                "remote_url": mapping.get("remote_url"),
                "last_synced_at": mapping.get("last_synced_at"),
            })

    report = {
        "implementation_artifacts": impl_artifacts,
        "state_root_found": state_root_found,
        "total_entities": len(entities),
        "total_mapped": len(mappings),
        "unmapped_local": unmapped_local,
        "changed_local": changed_local,
        "missing_local": missing_local,
        "summary": {
            "unmapped": len(unmapped_local),
            "changed": len(changed_local),
            "missing": len(missing_local),
        },
    }

    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
