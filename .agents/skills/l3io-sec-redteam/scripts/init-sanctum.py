#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# ///
"""
First Breath — Deterministic sanctum scaffolding for l3io-sec-redteam.

Creates the sanctum folder structure, copies template files with config values
substituted, copies capability reference files into the sanctum, auto-generates
CAPABILITIES.md from capability prompt frontmatter, and creates the research-cache
directory.

After this script runs, the sanctum is fully self-contained — the agent does not
depend on the skill bundle location for normal operation.
"""

import argparse
import json
import re
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

# --- Agent-specific configuration ---

SKILL_NAME = "l3io-sec-redteam"
SANCTUM_DIR = SKILL_NAME

# Files that stay in the skill bundle (only used during First Breath, not copied to sanctum)
SKILL_ONLY_FILES = {"first-breath.md"}

TEMPLATE_FILES = [
    "INDEX-template.md",
    "PERSONA-template.md",
    "CREED-template.md",
    "BOND-template.md",
    "MEMORY-template.md",
    "CAPABILITIES-template.md",
]

EVOLVABLE = False

# --- End agent-specific configuration ---


# BMad core installs its config resolver here. It is never bundled with a skill -- run it from
# this path, exactly as references/config-resolution.md §2 specifies.
RESOLVER_REL = Path("_bmad") / "scripts" / "resolve_config.py"


def resolve_core_config(project_root: Path, warnings: list) -> dict:
    """The `core.*` config subtree, resolved the one documented way.

    There is no `_bmad/config.yaml`. BMad has kept central config in four TOML layers
    (`_bmad/config.toml`, `config.user.toml`, `custom/config.toml`, `custom/config.user.toml`)
    since the TOML migration, and merging them in the right order is BMad core's
    `resolve_config.py`'s job -- not this script's, and certainly not a hand-written reader's.
    This function used to open `_bmad/config.yaml` and `config.user.yaml` with a fifteen-line
    line-splitter; both paths have not existed for releases, so the read was a permanent no-op
    and every sanctum was personalised with the hardcoded defaults while reporting success.

    Returns {} and records a WARNING on any failure -- never a silent default. The caller still
    scaffolds the sanctum: personalisation is cosmetic and the agent can be told its owner's
    name in conversation, but the reason must reach the operator rather than being swallowed.
    """
    resolver = project_root / RESOLVER_REL
    if not resolver.exists():
        warnings.append(
            f"BMad core's config resolver is not installed at {resolver} — personalisation "
            f"fields fall back to defaults. Install BMad core, then edit BOND.md/PERSONA.md."
        )
        return {}

    argv = [str(resolver), "--project-root", str(project_root), "--key", "core"]
    # `uv run --python 3.11` is the documented invocation; the resolver needs tomllib (3.11+).
    # If uv is unavailable, config-resolution.md §2 says python3 works, so try that rather than
    # give up -- the same fallback step-00-activate.md documents for the other helpers.
    attempts = [["uv", "run", "--python", "3.11", *argv], ["python3", *argv]]
    last = ""
    for cmd in attempts:
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
        except (OSError, ValueError) as exc:  # uv not on PATH, or not executable
            last = f"{cmd[0]}: {exc}"
            continue
        if proc.returncode != 0:
            last = f"{cmd[0]} exited {proc.returncode}: {proc.stderr.strip().splitlines()[-1:] or ''}"
            continue
        try:
            resolved = json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            last = f"{cmd[0]} printed output that is not JSON: {exc}"
            continue
        if not isinstance(resolved, dict):
            last = f"{cmd[0]} printed {type(resolved).__name__}, not a JSON object"
            continue
        # `--key core` may print the core subtree directly or the whole document; accept both
        # rather than depending on which, since only two scalar fields are wanted either way.
        core = resolved.get("core") if isinstance(resolved.get("core"), dict) else resolved
        return core

    warnings.append(
        f"could not resolve config via {resolver} — personalisation fields fall back to "
        f"defaults ({last})"
    )
    return {}


def parse_frontmatter(file_path: Path) -> dict:
    """Extract YAML frontmatter from a markdown file."""
    meta = {}
    with open(file_path) as f:
        content = f.read()

    match = re.match(r"^---\s*\n(.*?)\n---", content, re.DOTALL)
    if not match:
        return meta

    for line in match.group(1).strip().split("\n"):
        if ":" in line:
            key, _, value = line.partition(":")
            meta[key.strip()] = value.strip().strip("'\"")
    return meta


def copy_references(source_dir: Path, dest_dir: Path) -> list[str]:
    """Copy all reference files (except skill-only files) into the sanctum."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    copied = []

    for source_file in sorted(source_dir.iterdir()):
        if source_file.name in SKILL_ONLY_FILES:
            continue
        if source_file.name.startswith("."):
            continue
        if source_file.is_file():
            shutil.copy2(source_file, dest_dir / source_file.name)
            copied.append(source_file.name)

    return copied


def discover_capabilities(references_dir: Path, sanctum_refs_path: str) -> list[dict]:
    """Scan references/ for capability prompt files with frontmatter."""
    capabilities = []

    for md_file in sorted(references_dir.glob("*.md")):
        if md_file.name in SKILL_ONLY_FILES:
            continue
        meta = parse_frontmatter(md_file)
        if meta.get("name") and meta.get("code"):
            capabilities.append({
                "name": meta["name"],
                "description": meta.get("description", ""),
                "code": meta["code"],
                "source": f"{sanctum_refs_path}/{md_file.name}",
            })
    return capabilities


def generate_capabilities_md(capabilities: list[dict]) -> str:
    """Generate CAPABILITIES.md content from discovered capabilities."""
    lines = [
        "# Capabilities",
        "",
        "## Built-in",
        "",
        "| Code | Name | Description | Source |",
        "|------|------|-------------|--------|",
    ]
    for cap in capabilities:
        lines.append(
            f"| {cap['code']} | {cap['name']} | {cap['description']} | `{cap['source']}` |"
        )

    lines.extend([
        "",
        "## Tools",
        "",
        "### Required",
        "- **WebSearch** — live research for cloud/platform best practices (must be enabled in Claude Code permissions)",
        "",
        "### User-Provided Tools",
        "",
        "_MCP servers, APIs, or services the owner has made available. Document them here._",
    ])

    return "\n".join(lines) + "\n"


def substitute_vars(content: str, variables: dict) -> str:
    """Replace {var_name} placeholders with values from the variables dict."""
    for key, value in variables.items():
        content = content.replace(f"{{{key}}}", value)
    return content


def main():
    parser = argparse.ArgumentParser(
        description="First Breath — create sanctum structure for l3io-sec-redteam.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="After this runs, start the agent to begin the First Breath conversation.",
    )
    parser.add_argument("project_root", help="Root of the project (where _bmad/ lives)")
    parser.add_argument("skill_path", help="Path to the skill directory (where SKILL.md lives)")
    parser.add_argument("--json", action="store_true", help="Emit structured JSON output")
    parser.add_argument("--user-name", default="",
                        help="core.user_name, when the caller has already resolved config")
    parser.add_argument("--communication-language", default="",
                        help="core.communication_language, when already resolved")
    args = parser.parse_args()

    project_root = Path(args.project_root).resolve()
    skill_path = Path(args.skill_path).resolve()
    use_json = args.json

    result: dict = {"skill": SKILL_NAME, "status": "unknown", "sanctum": "", "created": [], "warnings": []}

    # Paths
    bmad_dir = project_root / "_bmad"
    memory_dir = bmad_dir / "memory"
    sanctum_path = memory_dir / SANCTUM_DIR
    assets_dir = skill_path / "assets"
    references_dir = skill_path / "references"

    # Sanctum subdirectories
    sanctum_refs = sanctum_path / "references"

    result["sanctum"] = str(sanctum_path)

    # Check if sanctum already exists
    if sanctum_path.exists():
        msg = f"Sanctum already exists at {sanctum_path} — skipping First Breath scaffolding."
        result["status"] = "skipped"
        result["message"] = msg
        if use_json:
            print(json.dumps(result, indent=2))
        else:
            print(msg)
        sys.exit(0)

    # Load config. An explicit flag wins: a caller that already resolved config at activation
    # (SKILL.md does) can pass what it read instead of paying for a second resolver run.
    config = {} if (args.user_name and args.communication_language) else \
        resolve_core_config(project_root, result["warnings"])

    # Build variable substitution map
    today = datetime.now(UTC).date().isoformat()
    variables = {
        "user_name": args.user_name or config.get("user_name") or "friend",
        "communication_language":
            args.communication_language or config.get("communication_language") or "English",
        "birth_date": today,
        "project_root": str(project_root),
        "sanctum_path": str(sanctum_path),
    }

    # Create sanctum structure
    sanctum_path.mkdir(parents=True, exist_ok=True)
    (sanctum_path / "sessions").mkdir(exist_ok=True)
    (sanctum_path / "research-cache").mkdir(exist_ok=True)

    # Copy reference files into sanctum (capability prompts, guidance)
    copied_refs = copy_references(references_dir, sanctum_refs)
    result["created"].extend([f"references/{n}" for n in copied_refs])

    # Copy and substitute template files
    for template_name in TEMPLATE_FILES:
        template_path = assets_dir / template_name
        if not template_path.exists():
            result["warnings"].append(f"template {template_name} not found, skipped")
            continue

        output_name = template_name.replace("-template", "").upper()
        output_name = output_name[:-3] + ".md"

        content = template_path.read_text()
        content = substitute_vars(content, variables)

        (sanctum_path / output_name).write_text(content)
        result["created"].append(output_name)

    # CAPABILITIES.md is populated from assets/CAPABILITIES-template.md above.
    # We don't auto-generate from references/ frontmatter because bmad-method
    # validator rules WF-01/WF-02 forbid `name:` and `description:` in any
    # non-SKILL.md file. The hand-curated template is the source of truth.

    result["status"] = "created"

    if use_json:
        print(json.dumps(result, indent=2))
    else:
        print(f"Created sanctum at {sanctum_path}")
        for item in result["created"]:
            print(f"  + {item}")
        for w in result["warnings"]:
            print(f"  ! {w}")
        print()
        print("First Breath scaffolding complete. The conversational awakening can now begin.")


if __name__ == "__main__":
    main()
