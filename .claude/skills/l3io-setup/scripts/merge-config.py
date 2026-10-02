#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["tomlkit>=0.13", "ruamel.yaml>=0.18"]
# ///
"""
merge-config.py -- the name BMad's module validator requires; the behaviour core needs.

bmad-module-builder's scaffolder emits a merge-config.py that writes _bmad/config.yaml
and _bmad/config.user.yaml, and deletes per-module config.yaml files. Core 6.12's
config_utils.load_central_config reads TOML ONLY:

    _bmad/config.toml -> config.user.toml -> custom/config.toml -> custom/config.user.toml

so the scaffolder's writer would make every l3io setting invisible and would delete
installer-generated files that exist. validate-module.py checks this file's PRESENCE
only (lines 137-165) and never reads it, so conforming to the name while keeping the
correct target satisfies the documented contract without breaking config resolution.

This is a thin wrapper: it delegates every argument, verbatim, to write-module-config.py
(this skill's own copy, next to this file), which already implements the correct
four-layer-aware write. There is no logic here to drift out of sync with that script.

See ADR-0007 and docs/superpowers/specs/2026-09-20-l3io-customization-layer-design.md §2.
"""
import runpy
import sys
from pathlib import Path

if __name__ == "__main__":
    target = Path(__file__).with_name("write-module-config.py")
    sys.argv[0] = str(target)
    runpy.run_path(str(target), run_name="__main__")
