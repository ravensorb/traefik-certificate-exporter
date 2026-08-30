#!/usr/bin/env python3
"""
Tests for drift-report.py — run with: python3 test-drift-report.py  (or `uv run`).

Exercises the sharded-state-tree walk (skills/_shared/status-files.md layout):
planned/active/archived status folders, bare epic.yaml/sprint.yaml nodes, per-file
story nodes, the sprint.yaml-is-not-a-story exclusion, backlog items from the flat
state/issues.yaml, and the unmapped/changed/missing drift classification against
_bmad/sync-state.yaml. Also covers the missing-state-root clean-exit path.
"""
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(os.path.dirname(HERE), "drift-report.py")

import importlib.util

spec = importlib.util.spec_from_file_location("drift_report", SCRIPT)
dr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dr)


def _write(path: str, content: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


class Base(unittest.TestCase):
    """Scratch project with `{project_root}/artifacts` as implementation_artifacts and
    an in-process CLI runner (patches sys.argv, calls dr.main() directly)."""

    # Minimal but faithful stand-in for BMad core's resolve_config.py: merges the four
    # TOML layers and prints JSON, exactly as core does. Written into each scratch project
    # so these tests exercise the real resolution path (subprocess + JSON + layer
    # precedence) without depending on a BMad install being present in CI.
    RESOLVER_STUB = '''\
import json, sys, tomllib
from pathlib import Path
root = Path(sys.argv[sys.argv.index("--project-root") + 1]) / "_bmad"
merged = {}
for rel in ("config.toml", "config.user.toml", "custom/config.toml", "custom/config.user.toml"):
    p = root / rel
    if not p.exists():
        continue
    try:
        layer = tomllib.loads(p.read_text())
    except tomllib.TOMLDecodeError as e:
        sys.stderr.write(f"warning: failed to parse {p}: {e}\\n")
        continue
    for k, v in layer.items():
        if isinstance(v, dict):
            merged.setdefault(k, {})
            for k2, v2 in v.items():
                if isinstance(v2, dict):
                    merged[k].setdefault(k2, {}).update(v2)
                else:
                    merged[k][k2] = v2
        else:
            merged[k] = v
json.dump(merged, sys.stdout)
'''

    def setUp(self):
        self.project_root = tempfile.mkdtemp()
        self.impl_artifacts = os.path.join(self.project_root, "artifacts")
        self.state_root = os.path.join(self.impl_artifacts, "state")
        _write(
            os.path.join(self.project_root, "_bmad", "scripts", "resolve_config.py"),
            self.RESOLVER_STUB,
        )
        _write(
            os.path.join(self.project_root, "_bmad", "custom", "config.toml"),
            f'[modules.l3io-pm]\nimplementation_artifacts = "{self.impl_artifacts}"\n',
        )

    def write_sync_state(self, mappings: list) -> None:
        import yaml

        _write(
            os.path.join(self.project_root, "_bmad", "sync-state.yaml"),
            yaml.dump({"version": 1, "last_sync": None, "mappings": mappings},
                      default_flow_style=False, sort_keys=False),
        )

    def make_epic(self, status: str, num: str, key=None, title="Test Epic",
                  epic_status="in-progress", goal="Ship it"):
        key = key or f"E{num}"
        path = os.path.join(self.state_root, status, f"epic-{num}", "epic.yaml")
        _write(path, f"key: '{key}'\ntitle: '{title}'\nstatus: {epic_status}\ngoal: '{goal}'\n")
        return os.path.dirname(path)

    def make_sprint(self, epic_dir: str, num: str, epic_key: str, key=None,
                     title="Test Sprint", sprint_status="in-progress"):
        key = key or f"S{num}"
        path = os.path.join(epic_dir, f"sprint-{num}", "sprint.yaml")
        _write(path, f"key: '{key}'\nepic: '{epic_key}'\ntitle: '{title}'\nstatus: {sprint_status}\n")
        return os.path.dirname(path)

    def make_story(self, sprint_dir: str, story_key: str, epic_key: str, sprint_key: str,
                    title="Test Story", story_status="in-progress"):
        path = os.path.join(sprint_dir, f"{story_key}.yaml")
        _write(
            path,
            f"key: '{story_key}'\nepic: '{epic_key}'\nsprint: '{sprint_key}'\n"
            f"title: '{title}'\nstatus: {story_status}\n",
        )
        return path

    def run_main(self, extra_argv=None):
        """Invoke dr.main() in-process with sys.argv patched; return (code, stdout_json, stderr)."""
        argv = ["drift-report.py", self.project_root] + (extra_argv or [])
        out, err = io.StringIO(), io.StringIO()
        code = 0
        try:
            with mock.patch.object(sys, "argv", argv):
                with redirect_stdout(out), redirect_stderr(err):
                    code = dr.main()
        except SystemExit as e:
            code = e.code if isinstance(e.code, int) else 1
        stdout_text = out.getvalue()
        parsed = json.loads(stdout_text) if stdout_text.strip() else None
        return code, parsed, err.getvalue()


class TestShardedTreeCollection(Base):
    """A tree spanning all three status folders is fully collected."""

    def setUp(self):
        super().setUp()
        # active/epic-001: 1 sprint, 2 stories
        e1 = self.make_epic("active", "001", epic_status="in-progress")
        s1 = self.make_sprint(e1, "01", "E001")
        self.make_story(s1, "E001-S01-001", "E001", "S01", title="First")
        self.make_story(s1, "E001-S01-002", "E001", "S01", title="Second")
        # planned/epic-005: 1 sprint, 1 story
        e5 = self.make_epic("planned", "005", epic_status="backlog")
        s5 = self.make_sprint(e5, "01", "E005", sprint_status="backlog")
        self.make_story(s5, "E005-S01-001", "E005", "S01", story_status="backlog")
        # archived/epic-002: 1 sprint, 1 story
        e2 = self.make_epic("archived", "002", epic_status="done")
        s2 = self.make_sprint(e2, "01", "E002", sprint_status="done")
        self.make_story(s2, "E002-S01-001", "E002", "S01", story_status="done")
        # backlog item in the flat issues.yaml
        _write(
            os.path.join(self.state_root, "issues.yaml"),
            "backlog:\n- key: BL-E001-001\n  epic: '001'\n  sprint: ''\n"
            "  title: Deferred item\n  source: review\n  severity: Low\n  status: backlog\n",
        )
        self.write_sync_state([])

    def test_all_entities_collected_across_status_folders(self):
        code, report, err = self.run_main()
        self.assertEqual(code, 0, err)
        self.assertTrue(report["state_root_found"])
        # 3 epics + 3 sprints + 4 stories + 1 backlog item = 11
        self.assertEqual(report["total_entities"], 11)

        keys_by_type = {}
        for bucket_entry in report["unmapped_local"]:
            keys_by_type.setdefault(bucket_entry["bmad_type"], set()).add(bucket_entry["bmad_key"])

        self.assertEqual(keys_by_type["epic"], {"E001", "E005", "E002"})
        self.assertEqual(keys_by_type["sprint"], {"E001-S01", "E005-S01", "E002-S01"})
        self.assertEqual(
            keys_by_type["story"],
            {"E001-S01-001", "E001-S01-002", "E005-S01-001", "E002-S01-001"},
        )
        self.assertEqual(keys_by_type["backlog"], {"BL-E001-001"})

    def test_story_bmad_path_uses_three_digit_epic_and_two_digit_sprint(self):
        code, report, err = self.run_main()
        self.assertEqual(code, 0, err)
        story_entries = [e for e in report["unmapped_local"] if e["bmad_type"] == "story"
                          and e["bmad_key"] == "E001-S01-001"]
        self.assertEqual(len(story_entries), 1)
        path = story_entries[0]["bmad_path"]
        self.assertIn(os.path.join("epic-001", "sprint-01", "stories", "E001-S01-001.md"), path)


class TestSprintYamlExcluded(Base):
    """sprint.yaml itself must never be collected as a story entity."""

    def setUp(self):
        super().setUp()
        e1 = self.make_epic("active", "001")
        self.make_sprint(e1, "01", "E001")
        self.write_sync_state([])

    def test_sprint_with_no_stories_yields_no_story_entities(self):
        code, report, err = self.run_main()
        self.assertEqual(code, 0, err)
        story_keys = {e["bmad_key"] for e in report["unmapped_local"] if e["bmad_type"] == "story"}
        self.assertEqual(story_keys, set())
        # Only the epic + sprint entities should be present.
        self.assertEqual(report["total_entities"], 2)


class TestDriftClassification(Base):
    """unmapped_local / changed_local / missing_local classification."""

    def setUp(self):
        super().setUp()
        e1 = self.make_epic("active", "001")
        s1 = self.make_sprint(e1, "01", "E001")
        self.make_story(s1, "E001-S01-001", "E001", "S01", title="Unmapped story")
        self.make_story(s1, "E001-S01-002", "E001", "S01", title="Changed story")

    def test_entity_not_in_sync_state_is_unmapped(self):
        self.write_sync_state([])
        code, report, err = self.run_main()
        self.assertEqual(code, 0, err)
        unmapped_keys = {e["bmad_key"] for e in report["unmapped_local"]}
        self.assertIn("E001-S01-001", unmapped_keys)
        self.assertEqual(report["changed_local"], [])
        self.assertEqual(report["missing_local"], [])

    def test_entity_with_stale_hash_is_changed(self):
        self.write_sync_state([{
            "bmad_key": "E001-S01-002",
            "bmad_type": "story",
            "bmad_path": "artifacts/epic-001/sprint-01/stories/E001-S01-002.md",
            "remote_id": 42,
            "remote_url": "https://example.invalid/issues/42",
            "last_synced_hash": "00000000",
            "last_synced_at": "2026-01-01T00:00:00Z",
        }])
        code, report, err = self.run_main()
        self.assertEqual(code, 0, err)
        changed = {e["bmad_key"]: e for e in report["changed_local"]}
        self.assertIn("E001-S01-002", changed)
        entry = changed["E001-S01-002"]
        self.assertEqual(entry["last_synced_hash"], "00000000")
        self.assertNotEqual(entry["current_hash"], "00000000")
        self.assertEqual(entry["remote_id"], 42)
        # The correctly-mapped-and-unchanged story must not also show as unmapped.
        unmapped_keys = {e["bmad_key"] for e in report["unmapped_local"]}
        self.assertNotIn("E001-S01-002", unmapped_keys)

    def test_sync_state_entry_with_no_local_file_is_missing(self):
        self.write_sync_state([{
            "bmad_key": "E999-S01-001",
            "bmad_type": "story",
            "bmad_path": "artifacts/epic-999/sprint-01/stories/E999-S01-001.md",
            "remote_id": 7,
            "remote_url": "https://example.invalid/issues/7",
            "last_synced_hash": "abcdef01",
            "last_synced_at": "2026-01-01T00:00:00Z",
        }])
        code, report, err = self.run_main()
        self.assertEqual(code, 0, err)
        missing_keys = {e["bmad_key"] for e in report["missing_local"]}
        self.assertEqual(missing_keys, {"E999-S01-001"})
        self.assertEqual(report["missing_local"][0]["remote_url"], "https://example.invalid/issues/7")


class TestMissingStateRoot(Base):
    """No {implementation_artifacts}/state/ directory at all — clean exit, not a crash."""

    def test_missing_state_root_exits_cleanly_and_is_distinguishable(self):
        # Note: setUp() never creates self.state_root.
        self.write_sync_state([])
        code, report, err = self.run_main()
        self.assertEqual(code, 0, err)
        self.assertIsNotNone(report)
        self.assertFalse(report["state_root_found"])
        self.assertEqual(report["total_entities"], 0)
        self.assertEqual(report["unmapped_local"], [])
        self.assertEqual(report["changed_local"], [])
        self.assertEqual(report["missing_local"], [])
        # This must read differently from a real zero-drift success, at least on stderr.
        self.assertIn("no state directory found", err)

    def test_missing_state_root_still_reports_stale_mappings_as_missing(self):
        # A prior sync-state mapping with nothing on disk anywhere must still surface
        # honestly as missing_local, even though the state root itself is absent.
        self.write_sync_state([{
            "bmad_key": "E001-S01-001",
            "bmad_type": "story",
            "bmad_path": "artifacts/epic-001/sprint-01/stories/E001-S01-001.md",
            "remote_id": 1,
            "remote_url": "https://example.invalid/issues/1",
            "last_synced_hash": "deadbeef",
            "last_synced_at": "2026-01-01T00:00:00Z",
        }])
        code, report, err = self.run_main()
        self.assertEqual(code, 0, err)
        self.assertFalse(report["state_root_found"])
        missing_keys = {e["bmad_key"] for e in report["missing_local"]}
        self.assertEqual(missing_keys, {"E001-S01-001"})


class TestConfigResolution(Base):
    """Config comes from BMad core's four-layer TOML resolver, never from a YAML file.

    Reading a `_bmad/config.yaml` that BMad has not created since the TOML migration
    silently yielded {} and pinned implementation_artifacts to the default, which is what
    made every skill open with 'No <module> section in config'.
    """

    def test_resolves_implementation_artifacts_from_pm_module_section(self):
        cfg = dr.resolve_config(Path(self.project_root))
        self.assertEqual(cfg["implementation_artifacts"], self.impl_artifacts)

    def test_user_layer_overrides_team_layer(self):
        _write(
            os.path.join(self.project_root, "_bmad", "custom", "config.user.toml"),
            '[modules.l3io-pm]\nimplementation_artifacts = "/personal/impl"\n',
        )
        cfg = dr.resolve_config(Path(self.project_root))
        self.assertEqual(cfg["implementation_artifacts"], "/personal/impl")

    def test_a_config_yaml_is_ignored_entirely(self):
        # The obsolete file must have no effect even when present — a repo upgrading from
        # 2.0.1 may still carry one written by the old module setup.
        _write(
            os.path.join(self.project_root, "_bmad", "config.yaml"),
            "implementation_artifacts: /obsolete/path\n",
        )
        cfg = dr.resolve_config(Path(self.project_root))
        self.assertEqual(cfg["implementation_artifacts"], self.impl_artifacts)

    def test_falls_back_to_default_when_bmad_is_not_installed(self):
        bare = tempfile.mkdtemp()
        cfg = dr.resolve_config(Path(bare))
        self.assertEqual(
            cfg["implementation_artifacts"],
            os.path.join(bare, "_bmad-output") + "/implementation-artifacts",
        )

    def test_malformed_layer_warning_reaches_stderr(self):
        # The resolver exits 0 and drops the bad layer. If we swallow its warning, a typo
        # in a custom config silently reverts every path to the default.
        _write(
            os.path.join(self.project_root, "_bmad", "custom", "config.user.toml"),
            "[modules.l3io-pm]\nthis is not = = valid toml\n",
        )
        err = io.StringIO()
        with redirect_stderr(err):
            cfg = dr.resolve_config(Path(self.project_root))
        self.assertEqual(cfg["implementation_artifacts"], self.impl_artifacts)
        self.assertIn("warning", err.getvalue().lower())


if __name__ == "__main__":
    unittest.main()
