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

    # --- picture-first checks -------------------------------------------------

    HEAD = (
        '<!doctype html><html lang="en"><head><meta name="viewport" '
        'content="width=device-width"><title>T</title><style>body{color:#111}</style>'
        "</head><body>"
    )

    def test_flags_page_over_the_word_budget(self) -> None:
        path = self.write_html(self.HEAD + "<p>" + "word " * 130 + "</p></body></html>")
        errors = CHECK_HTML.check(path)
        self.assertTrue(any("budget is 120" in e for e in errors), errors)

    def test_word_budget_ignores_script_and_style_text(self) -> None:
        noise = "var x = '" + "filler " * 200 + "';"
        path = self.write_html(
            self.HEAD + f"<script>{noise}</script><style>{noise}</style>"
            "<p>Nine short words carry this whole explainer page.</p></body></html>"
        )
        self.assertEqual([], CHECK_HTML.check(path))

    def test_word_budget_is_configurable_and_can_be_disabled(self) -> None:
        path = self.write_html(self.HEAD + "<p>" + "word " * 130 + "</p></body></html>")
        self.assertEqual([], CHECK_HTML.check(path, max_words=0))
        self.assertEqual([], CHECK_HTML.check(path, max_words=500))

    def test_flags_inline_svg_without_an_accessible_name(self) -> None:
        path = self.write_html(self.HEAD + "<svg><rect/></svg></body></html>")
        errors = CHECK_HTML.check(path)
        self.assertTrue(any("no accessible name" in e for e in errors), errors)

    def test_accepts_svg_named_by_title_child_or_hidden(self) -> None:
        path = self.write_html(
            self.HEAD + "<svg><title>A pipe</title><rect/></svg>"
            '<svg aria-hidden="true"><rect/></svg>'
            '<svg aria-labelledby="cap"><rect/></svg></body></html>'
        )
        self.assertEqual([], CHECK_HTML.check(path))

    def test_nested_svg_counts_once(self) -> None:
        path = self.write_html(
            self.HEAD + '<svg aria-label="outer"><svg><rect/></svg></svg></body></html>'
        )
        self.assertEqual([], CHECK_HTML.check(path))

    def test_real_example_artifact_passes(self) -> None:
        example = Path(__file__).parents[1] / "example" / "eli5-how-does-dns-work.html"
        if not example.exists():
            self.skipTest("example artifact not present")
        self.assertEqual([], CHECK_HTML.check(example))


if __name__ == "__main__":
    unittest.main()
