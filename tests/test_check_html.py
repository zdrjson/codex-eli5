from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = (
    Path(__file__).parents[1]
    / "plugins"
    / "codex-eli5"
    / "skills"
    / "eli5"
    / "scripts"
    / "check_html.py"
)
SPEC = importlib.util.spec_from_file_location("check_html", SCRIPT)
assert SPEC and SPEC.loader
CHECK_HTML = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = CHECK_HTML
SPEC.loader.exec_module(CHECK_HTML)


class CheckHtmlTests(unittest.TestCase):
    def write_html(self, source: str) -> Path:
        directory = Path(tempfile.mkdtemp())
        path = directory / "artifact.html"
        path.write_text(source, encoding="utf-8")
        self.addCleanup(directory.rmdir)
        self.addCleanup(path.unlink)
        return path

    def valid_html(self, body: str = "<main><h1>Topic</h1></main>") -> str:
        return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>Topic</title><style>body{{color:#111}}</style></head>
        <body>{body}</body></html>"""

    def test_accepts_self_contained_artifact(self) -> None:
        path = self.write_html(
            self.valid_html(
                '<main><h1>DNS</h1><svg role="img" aria-label="A map"></svg></main>'
            )
        )
        result = CHECK_HTML.audit(path)
        self.assertTrue(result.ok)
        self.assertEqual([], result.warnings)

    def test_rejects_external_resource_and_missing_metadata(self) -> None:
        path = self.write_html(
            '<html><head><title></title></head><body><img src="https://example.com/a.png"></body></html>'
        )
        errors = CHECK_HTML.check(path)
        self.assertIn("missing <!doctype html>", errors)
        self.assertIn("missing html lang attribute", errors)
        self.assertTrue(any(error.startswith("network resources found:") for error in errors))
        self.assertIn("1 image(s) missing an alt attribute", errors)

    def test_allows_outbound_citation_link_and_decorative_image(self) -> None:
        path = self.write_html(
            self.valid_html(
                '<main><h1>Topic</h1><img src="data:image/svg+xml,a" alt="">'
                '<a href="https://example.com/source">Source</a></main>'
            )
        )
        self.assertEqual([], CHECK_HTML.check(path))

    def test_detects_protocol_relative_srcset_and_unnamed_svg(self) -> None:
        path = self.write_html(
            self.valid_html(
                '<main><h1>Topic</h1><picture><source srcset="local.png 1x, //cdn.example/a.png 2x">'
                '</picture><svg></svg></main>'
            )
        )
        errors = CHECK_HTML.check(path)
        self.assertTrue(any("//cdn.example/a.png" in error for error in errors))
        self.assertIn("1 SVG(s) missing a name or decorative marker", errors)

    def test_allow_network_changes_error_to_warning(self) -> None:
        path = self.write_html(
            self.valid_html(
                '<main><h1>Topic</h1><script src="https://cdn.example/app.js"></script></main>'
            )
        )
        result = CHECK_HTML.audit(path, allow_network=True)
        self.assertTrue(result.ok)
        self.assertTrue(any("https://cdn.example/app.js" in item for item in result.warnings))

    def test_warns_when_motion_has_no_reduced_motion_fallback(self) -> None:
        source = self.valid_html().replace(
            "body{color:#111}", "body{color:#111;transition:color .2s}"
        )
        result = CHECK_HTML.audit(self.write_html(source))
        self.assertTrue(result.ok)
        self.assertIn(
            "motion styles found without prefers-reduced-motion", result.warnings
        )

    def test_json_cli_is_machine_readable(self) -> None:
        path = self.write_html(self.valid_html())
        completed = subprocess.run(
            [sys.executable, str(SCRIPT), "--json", str(path)],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(0, completed.returncode, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual([], payload["errors"])


if __name__ == "__main__":
    unittest.main()
