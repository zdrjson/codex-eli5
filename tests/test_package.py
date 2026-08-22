from __future__ import annotations

import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
MARKETPLACE = ROOT / ".agents" / "plugins" / "marketplace.json"
PLUGIN_ROOT = ROOT / "plugins" / "codex-eli5"
MANIFEST = PLUGIN_ROOT / ".codex-plugin" / "plugin.json"


class PackageTests(unittest.TestCase):
    def test_marketplace_points_to_plugin(self) -> None:
        marketplace = json.loads(MARKETPLACE.read_text(encoding="utf-8"))
        self.assertEqual("codex-eli5", marketplace["name"])
        entry = marketplace["plugins"][0]
        self.assertEqual("codex-eli5", entry["name"])
        self.assertEqual("./plugins/codex-eli5", entry["source"]["path"])
        self.assertTrue(PLUGIN_ROOT.is_dir())

    def test_manifest_and_skill_are_discoverable(self) -> None:
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        self.assertEqual(PLUGIN_ROOT.name, manifest["name"])
        self.assertRegex(manifest["version"], r"^\d+\.\d+\.\d+$")
        skills_root = PLUGIN_ROOT / manifest["skills"]
        skill_files = list(skills_root.glob("*/SKILL.md"))
        self.assertTrue(skill_files)
        for skill_file in skill_files:
            source = skill_file.read_text(encoding="utf-8")
            self.assertRegex(source, r"(?s)^---\n.*\bname:\s*\S+.*\bdescription:\s*.+?\n---")


if __name__ == "__main__":
    unittest.main()
