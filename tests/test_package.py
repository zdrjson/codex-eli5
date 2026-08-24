from __future__ import annotations

import json
import struct
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
        self.assertEqual("AVAILABLE", entry["policy"]["installation"])
        self.assertEqual("ON_INSTALL", entry["policy"]["authentication"])

    def test_manifest_and_skill_are_discoverable(self) -> None:
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        self.assertEqual(PLUGIN_ROOT.name, manifest["name"])
        self.assertRegex(manifest["version"], r"^\d+\.\d+\.\d+$")
        prompts = manifest["interface"]["defaultPrompt"]
        self.assertIsInstance(prompts, list)
        self.assertLessEqual(len(prompts), 3)
        self.assertTrue(
            all(isinstance(prompt, str) and len(prompt) <= 128 for prompt in prompts)
        )
        skills_root = PLUGIN_ROOT / manifest["skills"]
        skill_files = list(skills_root.glob("*/SKILL.md"))
        self.assertTrue(skill_files)
        for skill_file in skill_files:
            source = skill_file.read_text(encoding="utf-8")
            self.assertRegex(
                source, r"(?s)^---\n.*\bname:\s*\S+.*\bdescription:\s*.+?\n---"
            )

    def test_listing_assets_and_website_are_shippable(self) -> None:
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        interface = manifest["interface"]
        self.assertEqual(
            "https://github.com/zdrjson/codex-eli5", interface["websiteURL"]
        )
        for field in ("composerIcon", "logo", "logoDark"):
            relative = interface[field]
            self.assertTrue(relative.startswith("./assets/"))
            asset = PLUGIN_ROOT / relative
            self.assertTrue(asset.is_file(), f"missing {field}: {asset}")
            data = asset.read_bytes()
            self.assertEqual(b"\x89PNG\r\n\x1a\n", data[:8])
            width, height = struct.unpack(">II", data[16:24])
            self.assertEqual(width, height)
            self.assertGreaterEqual(width, 128)

    def test_skill_ui_metadata_mentions_the_skill(self) -> None:
        metadata = (
            PLUGIN_ROOT / "skills" / "eli5" / "agents" / "openai.yaml"
        ).read_text(encoding="utf-8")
        self.assertIn('default_prompt: "Use $codex-eli5:eli5 ', metadata)
        self.assertIn("allow_implicit_invocation: true", metadata)

    def test_installed_plugin_carries_license_and_notice(self) -> None:
        for name in ("LICENSE", "NOTICE"):
            repository_copy = (ROOT / name).read_text(encoding="utf-8")
            plugin_copy = (PLUGIN_ROOT / name).read_text(encoding="utf-8")
            self.assertEqual(repository_copy, plugin_copy)

    def test_repository_has_no_unresolved_scaffold_or_merge_markers(self) -> None:
        blocked = ("[" + "TODO:", "<" * 7, "=" * 7, ">" * 7)
        for path in ROOT.rglob("*"):
            if not path.is_file() or ".git" in path.parts:
                continue
            if path.suffix.lower() not in {".md", ".py", ".json", ".yaml", ".yml"}:
                continue
            source = path.read_text(encoding="utf-8")
            for marker in blocked:
                self.assertNotIn(marker, source, f"{marker} found in {path}")


if __name__ == "__main__":
    unittest.main()
