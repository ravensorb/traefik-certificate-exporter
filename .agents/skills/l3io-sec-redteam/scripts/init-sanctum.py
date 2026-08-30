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
import sys
from datetime import date
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


def parse_yaml_config(config_path: Path) -> dict:
    """Simple YAML key-value parser. Handles top-level scalar values only."""
    config = {}
    if not config_path.exists():
        return config
    with open(config_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if ":" in line:
                key, _, value = line.partition(":")
                value = value.strip().strip("'\"")
                if value:
                    config[key.strip()] = value
    return config


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
    sanctum_refs_path = "./references"

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

    # Load config
    config = {}
    for config_file in ["config.yaml", "config.user.yaml"]:
        config.update(parse_yaml_config(bmad_dir / config_file))

    # Build variable substitution map
    today = date.today().isoformat()
    variables = {
        "user_name": config.get("user_name", "friend"),
        "communication_language": config.get("communication_language", "English"),
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
