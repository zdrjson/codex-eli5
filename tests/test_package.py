from __future__ import annotations

import json
import struct
import unittest
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).parents[1]
MARKETPLACE = ROOT / ".agents" / "plugins" / "marketplace.json"
PLUGIN_ROOT = ROOT / "plugins" / "codex-eli5"
MANIFEST = PLUGIN_ROOT / ".codex-plugin" / "plugin.json"
SUBMISSION_ROOT = ROOT / "submission"
SUBMISSION_LISTING = SUBMISSION_ROOT / "listing.json"
SUBMISSION_TEST_CASES = SUBMISSION_ROOT / "test-cases.json"
REFERENCE_FIXTURE = SUBMISSION_ROOT / "fixtures" / "reference-explainer.png"


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

    def test_directory_listing_meets_final_limits(self) -> None:
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        interface = manifest["interface"]
        self.assertLessEqual(len(manifest["name"]), 64)
        self.assertRegex(manifest["version"], r"^\d+\.\d+\.\d+$")
        self.assertLessEqual(len(interface["displayName"]), 30)
        self.assertLessEqual(len(interface["shortDescription"]), 30)
        self.assertNotIn("\n", interface["shortDescription"])
        self.assertLessEqual(len(interface["longDescription"]), 4000)
        self.assertLessEqual(len(interface["developerName"]), 80)
        self.assertEqual(manifest["author"]["name"], interface["developerName"])
        self.assertLessEqual(len(interface["capabilities"]), 20)
        self.assertTrue(
            all(0 < len(capability) <= 120 for capability in interface["capabilities"])
        )

        prompts = interface["defaultPrompt"]
        self.assertLessEqual(len(prompts), 3)
        normalized = [" ".join(prompt.split()).casefold() for prompt in prompts]
        self.assertEqual(len(normalized), len(set(normalized)))
        self.assertTrue(all(0 < len(prompt) <= 128 for prompt in prompts))
        self.assertTrue(all("\n" not in prompt and "@" not in prompt for prompt in prompts))

        parsed = urlparse(interface["websiteURL"])
        self.assertEqual("https", parsed.scheme)
        self.assertTrue(parsed.netloc)
        self.assertLessEqual(len(interface["websiteURL"]), 1024)

        for field in ("privacyPolicyURL", "termsOfServiceURL"):
            parsed = urlparse(interface[field])
            self.assertEqual("https", parsed.scheme)
            self.assertTrue(parsed.netloc)
            self.assertLessEqual(len(interface[field]), 1024)

        listing = json.loads(SUBMISSION_LISTING.read_text(encoding="utf-8"))
        for field in (
            "websiteURL",
            "supportURL",
            "privacyPolicyURL",
            "termsOfServiceURL",
        ):
            parsed = urlparse(listing[field])
            self.assertEqual("https", parsed.scheme)
            self.assertTrue(parsed.netloc)
            self.assertLessEqual(len(listing[field]), 1024)

        self.assertEqual("skills_only", listing["submissionType"])
        self.assertEqual(manifest["version"], listing["version"])
        self.assertEqual(interface["displayName"], listing["displayName"])
        self.assertEqual(interface["shortDescription"], listing["shortDescription"])
        self.assertEqual(interface["longDescription"], listing["longDescription"])
        self.assertEqual(interface["developerName"], listing["developerName"])
        self.assertEqual(interface["category"], listing["category"])
        self.assertEqual(interface["capabilities"], listing["capabilities"])
        self.assertEqual(interface["defaultPrompt"], listing["starterPrompts"])
        self.assertEqual(interface["websiteURL"], listing["websiteURL"])
        self.assertEqual(interface["privacyPolicyURL"], listing["privacyPolicyURL"])
        self.assertEqual(interface["termsOfServiceURL"], listing["termsOfServiceURL"])

    def test_submission_test_cases_are_complete(self) -> None:
        cases = json.loads(SUBMISSION_TEST_CASES.read_text(encoding="utf-8"))
        self.assertEqual(5, len(cases["positive"]))
        self.assertEqual(3, len(cases["negative"]))
        positive_fields = {
            "id",
            "prompt",
            "expectedBehavior",
            "expectedResultShape",
            "fixtureData",
        }
        negative_fields = {"id", "scenario", "expectedBehavior", "whyNotComplete"}
        all_ids: list[str] = []
        for case in cases["positive"]:
            self.assertTrue(positive_fields.issubset(case))
            self.assertTrue(all(str(case[field]).strip() for field in positive_fields))
            all_ids.append(case["id"])
        for case in cases["negative"]:
            self.assertTrue(negative_fields.issubset(case))
            self.assertTrue(all(str(case[field]).strip() for field in negative_fields))
            all_ids.append(case["id"])
        self.assertEqual(len(all_ids), len(set(all_ids)))

    def test_skills_only_package_has_no_server_or_app_payload(self) -> None:
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        self.assertNotIn("mcpServers", manifest)
        self.assertNotIn("apps", manifest)
        self.assertNotIn("screenshots", manifest["interface"])
        self.assertFalse((PLUGIN_ROOT / ".mcp.json").exists())
        self.assertFalse((PLUGIN_ROOT / ".app.json").exists())

    def test_reference_fixture_is_fixed_and_reproducible(self) -> None:
        data = REFERENCE_FIXTURE.read_bytes()
        self.assertEqual(b"\x89PNG\r\n\x1a\n", data[:8])
        width, height = struct.unpack(">II", data[16:24])
        self.assertEqual((706, 560), (width, height))
        cases = json.loads(SUBMISSION_TEST_CASES.read_text(encoding="utf-8"))
        reference_case = next(
            case for case in cases["positive"] if case["id"] == "positive-reference-match"
        )
        self.assertIn("submission/fixtures/reference-explainer.png", reference_case["fixtureData"])
        self.assertIn("https://github.com/zdrjson/codex-eli5/", reference_case["fixtureData"])

    def test_public_policy_and_support_pages_exist(self) -> None:
        listing = json.loads(SUBMISSION_LISTING.read_text(encoding="utf-8"))
        for name in ("PRIVACY.md", "TERMS.md", "SUPPORT.md"):
            source = (ROOT / name).read_text(encoding="utf-8")
            self.assertGreater(len(source.strip()), 200)
            self.assertIn(listing["developerName"], source)

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
