#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml"]
# ///
"""
Detect the remote platform (GitHub) from the git remote URL
and output connection settings as JSON.

Usage: uv run detect-platform.py <project-root>

Output (stdout): JSON with detected fields
Errors (stderr): human-readable messages with non-zero exit code
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path


def run(cmd: list[str], cwd: Path) -> tuple[int, str, str]:
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def detect_from_url(remote_url: str) -> dict:
    """Parse a git remote URL and extract platform and connection details."""
    url = remote_url.strip()

    # Normalize SSH to HTTPS form for parsing
    # git@github.com:org/repo.git → https://github.com/org/repo
    ssh_match = re.match(r"git@([^:]+):(.+?)(?:\.git)?$", url)
    if ssh_match:
        host = ssh_match.group(1)
        path = ssh_match.group(2)
        url = f"https://{host}/{path}"

    # Remove .git suffix
    url = re.sub(r"\.git$", "", url)

    # GitHub: https://github.com/owner/repo
    gh_match = re.match(r"https?://github\.com/([^/]+)/([^/]+)$", url)
    if gh_match:
        return {
            "platform": "github",
            "owner": gh_match.group(1),
            "repo": gh_match.group(2),
            "remote_url": url,
        }

    return {
        "platform": "unknown",
        "remote_url": url,
        "note": "Could not detect platform from remote URL. Set platform manually in sync-config.yaml.",
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="detect-platform.py",
        description=(
            "Detect the remote platform (GitHub) from the git remote URL. "
            "Outputs JSON with platform name and connection details."
        ),
    )
    parser.add_argument(
        "project_root",
        help="Path to the project root (must be a git repository with a remote set)",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    project_root = Path(args.project_root).resolve()
    if not project_root.is_dir():
        print(f"ERROR: project-root not found: {project_root}", file=sys.stderr)
        return 1

    # Try the origin remote first, then any remote
    for remote_name in ("origin", "upstream"):
        code, url, err = run(
            ["git", "remote", "get-url", remote_name], cwd=project_root
        )
        if code == 0 and url:
            result = detect_from_url(url)
            result["remote_name"] = remote_name
            print(json.dumps(result, indent=2))
            return 0

    # Fall back: list all remotes and take the first
    code, remotes_out, _ = run(["git", "remote", "-v"], cwd=project_root)
    if code == 0 and remotes_out:
        first_line = remotes_out.splitlines()[0]
        parts = first_line.split()
        if len(parts) >= 2:
            remote_name = parts[0]
            url = parts[1]
            result = detect_from_url(url)
            result["remote_name"] = remote_name
            print(json.dumps(result, indent=2))
            return 0

    print(
        "ERROR: No git remote found. Set a remote with: git remote add origin <url>",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
