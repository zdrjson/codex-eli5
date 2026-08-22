from __future__ import annotations

import importlib.util
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
SPEC.loader.exec_module(CHECK_HTML)


class CheckHtmlTests(unittest.TestCase):
    def write_html(self, source: str) -> Path:
        directory = Path(tempfile.mkdtemp())
        path = directory / "artifact.html"
        path.write_text(source, encoding="utf-8")
        return path

    def test_accepts_self_contained_artifact(self) -> None:
        path = self.write_html(
            """<!doctype html><html lang="en"><head><meta name="viewport"
            content="width=device-width"><title>DNS</title><style>body{color:#111}</style>
            </head><body><svg role="img" aria-label="A map"></svg></body></html>"""
        )
        self.assertEqual([], CHECK_HTML.check(path))

    def test_rejects_external_resource_and_missing_metadata(self) -> None:
        path = self.write_html('<html><head><title></title></head><body><img src="https://example.com/a.png"></body></html>')
        errors = CHECK_HTML.check(path)
        self.assertIn("missing <!doctype html>", errors)
        self.assertIn("missing html lang attribute", errors)
        self.assertTrue(any(error.startswith("external resources found:") for error in errors))
        self.assertIn("1 image(s) missing alt text", errors)

    def test_allows_outbound_citation_link(self) -> None:
        path = self.write_html(
            """<!doctype html><html lang="en"><head><meta name="viewport"
            content="width=device-width"><title>Topic</title><style>body{color:#111}</style>
            </head><body><a href="https://example.com/source">Source</a></body></html>"""
        )
        self.assertEqual([], CHECK_HTML.check(path))


if __name__ == "__main__":
    unittest.main()
