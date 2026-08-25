from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
SCRIPT = (
    ROOT / "plugins" / "codex-eli5" / "skills" / "eli5" / "scripts" / "check_html.py"
)
SPEC = importlib.util.spec_from_file_location("check_html", SCRIPT)
assert SPEC and SPEC.loader
CHECK_HTML = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = CHECK_HTML
SPEC.loader.exec_module(CHECK_HTML)
CSP_META = (
    '<meta http-equiv="Content-Security-Policy" '
    "content=\"default-src 'none'; base-uri 'none'; form-action 'none'; "
    "img-src data:; font-src data:; media-src data:; style-src 'unsafe-inline'; "
    "script-src 'unsafe-inline'\">"
)


class CheckHtmlTests(unittest.TestCase):
    def write_html(self, source: str, suffix: str = ".html") -> Path:
        directory = Path(tempfile.mkdtemp())
        path = directory / f"artifact{suffix}"
        path.write_text(source, encoding="utf-8")
        self.addCleanup(directory.rmdir)
        self.addCleanup(path.unlink)
        return path

    def write_html_bytes(self, source: bytes) -> Path:
        directory = Path(tempfile.mkdtemp())
        path = directory / "artifact.html"
        path.write_bytes(source)
        self.addCleanup(directory.rmdir)
        self.addCleanup(path.unlink)
        return path

    def valid_html(
        self,
        body: str = "<main><h1>Topic</h1></main>",
        css: str = "body{color:#111}",
        script: str = "",
    ) -> str:
        script_tag = f"<script>{script}</script>" if script else ""
        return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>Topic</title>{CSP_META}<style>{css}</style></head>
        <body>{body}{script_tag}</body></html>"""

    def test_accepts_self_contained_artifact(self) -> None:
        path = self.write_html(
            self.valid_html(
                '<main><h1>DNS</h1><svg role="img" aria-label="A map"></svg></main>'
            )
        )
        result = CHECK_HTML.audit(path)
        self.assertTrue(result.content_ok)
        self.assertEqual([], result.warnings)

    def test_rejects_missing_metadata_external_image_and_missing_alt(self) -> None:
        path = self.write_html(
            '<html><head><title></title></head><body><img src="https://example.com/a.png"></body></html>'
        )
        errors = CHECK_HTML.check(path)
        self.assertIn("missing <!doctype html>", errors)
        self.assertIn("missing html lang attribute", errors)
        self.assertIn("missing charset meta tag", errors)
        self.assertTrue(
            any(
                error.startswith("disallowed resource references found:")
                for error in errors
            )
        )
        self.assertIn("1 image(s) missing an alt attribute", errors)

    def test_input_image_requires_alt(self) -> None:
        missing = self.write_html(
            self.valid_html(
                '<main><h1>Topic</h1><input type="IMAGE" '
                'src="data:image/png;base64,AAAA"></main>'
            )
        )
        self.assertIn(
            "1 image(s) missing an alt attribute", CHECK_HTML.check(missing)
        )

        named = self.write_html(
            self.valid_html(
                '<main><h1>Topic</h1><input type="image" '
                'src="data:image/png;base64,AAAA" alt="Diagram"></main>'
            )
        )
        self.assertEqual([], CHECK_HTML.check(named))

    def test_style_block_must_contain_css(self) -> None:
        empty = self.write_html(
            self.valid_html(
                '<main style="color:#111"><h1>Topic</h1></main>',
                css=" \n /* generated later */ ",
            )
        )
        self.assertIn("missing inline style block", CHECK_HTML.check(empty))

        nonempty = self.write_html(self.valid_html(css="body{color:#111}"))
        self.assertNotIn("missing inline style block", CHECK_HTML.check(nonempty))

    def test_allows_outbound_citation_and_decorative_data_image(self) -> None:
        path = self.write_html(
            self.valid_html(
                '<main><h1>Topic</h1><img src="data:image/svg+xml,a" alt="">'
                '<a href="https://example.com/source">Source</a></main>'
            )
        )
        self.assertEqual([], CHECK_HTML.check(path))

    def test_allows_passive_data_assets_but_rejects_active_data_documents(self) -> None:
        passive = self.write_html(
            self.valid_html(
                '<main><h1>Topic</h1><audio src="data:audio/wav;base64,AAAA"></audio>'
                '<img src="data:image/png;base64,AAAA" alt=""></main>',
                css=(
                    '@font-face{font-family:x;src:url("data:font/woff2;base64,AAAA")}'
                    "body{font-family:x,sans-serif}"
                ),
            )
        )
        self.assertEqual([], CHECK_HTML.check(passive))

        active = self.write_html(
            self.valid_html(
                "<main><h1>Topic</h1>"
                "<script src=\"data:text/javascript,fetch('https://example.com')\"></script>"
                '<iframe src="data:text/html,hello"></iframe>'
                '<object data="data:text/html,hello"></object></main>'
            )
        )
        joined = "\n".join(CHECK_HTML.check(active))
        self.assertIn("script[src]=data:text/javascript", joined)
        self.assertIn("iframe[src]=data:text/html", joined)
        self.assertIn("object[data]=data:text/html", joined)

    def test_flags_relative_and_absolute_file_dependencies(self) -> None:
        cases = {
            "relative script": '<script src="./app.js"></script>',
            "relative stylesheet": '<link rel="stylesheet" href="styles.css">',
            "base URL": '<base href="https://cdn.example/assets/">',
            "download": '<a download href="./guide.pdf">Guide</a>',
        }
        for label, fragment in cases.items():
            with self.subTest(label=label):
                path = self.write_html(
                    self.valid_html(f"<main><h1>Topic</h1>{fragment}</main>")
                )
                self.assertTrue(
                    any(
                        "disallowed resource references found:" in item
                        for item in CHECK_HTML.check(path)
                    )
                )

    def test_non_loading_href_and_src_like_attributes_are_not_dependencies(
        self,
    ) -> None:
        body = (
            '<main><h1>Topic</h1><link rel="canonical" href="https://example.com/topic">'
            '<div src="shown-as-data.txt">Diagram label</div></main>'
        )
        self.assertEqual([], CHECK_HTML.check(self.write_html(self.valid_html(body))))

    def test_flags_css_references_but_not_css_shown_as_code(self) -> None:
        path = self.write_html(
            self.valid_html(
                "<main><h1>Topic</h1><code>url(https://example.com/demo.png)</code></main>",
                css=(
                    'body{background:url("./bg.png");content:"url(fake.png)"}'
                    '.hero{background-image:image-set("./hero.webp" 1x, '
                    '"data:image/png;base64,AAAA" 2x)}'
                ),
            )
        )
        errors = CHECK_HTML.check(path)
        external = next(
            item for item in errors if item.startswith("disallowed resource references")
        )
        self.assertIn("./bg.png", external)
        self.assertIn("./hero.webp", external)
        self.assertNotIn("fake.png", external)
        self.assertNotIn("demo.png", external)

    def test_local_font_source_is_a_machine_dependency(self) -> None:
        path = self.write_html(
            self.valid_html(
                css=(
                    '@font-face{font-family:LocalOnly;src:local("Helvetica Neue")}'
                    "body{font-family:LocalOnly,sans-serif}"
                )
            )
        )
        external = next(
            item
            for item in CHECK_HTML.check(path)
            if item.startswith("disallowed resource references")
        )
        self.assertIn('local("Helvetica Neue")', external)

    def test_detects_protocol_relative_srcset_and_unnamed_svg(self) -> None:
        path = self.write_html(
            self.valid_html(
                '<main><h1>Topic</h1><picture><source srcset="local.png 1x, //cdn.example/a.png 2x">'
                "</picture><svg></svg></main>"
            )
        )
        errors = CHECK_HTML.check(path)
        self.assertTrue(any("//cdn.example/a.png" in error for error in errors))
        self.assertIn(
            "1 inline SVG(s) missing a non-empty name or decorative marker", errors
        )

    def test_compact_srcset_candidates_cannot_hide_file_dependencies(self) -> None:
        body = (
            "<main><h1>Topic</h1>"
            '<img srcset="data:image/png;base64,AAAA 1x,local.png 2x" alt="">'
            '<img srcset="data:image/png;base64,AAAA, local-two.png 2x" alt="">'
            '<img srcset="one.png 1x,two.png 2x" alt="">'
            "</main>"
        )
        joined = "\n".join(CHECK_HTML.check(self.write_html(self.valid_html(body))))
        self.assertIn("local.png", joined)
        self.assertIn("local-two.png", joined)
        self.assertIn("one.png", joined)
        self.assertIn("two.png", joined)

    def test_duplicate_resource_attributes_cannot_hide_remote_value(self) -> None:
        path = self.write_html(
            self.valid_html(
                '<main><h1>Topic</h1><img src="https://cdn.example/a.png" '
                'src="data:image/png,a" alt="A"></main>'
            )
        )
        self.assertTrue(any("cdn.example" in item for item in CHECK_HTML.check(path)))

    def test_resource_diagnostics_escape_control_characters(self) -> None:
        body = '<main><h1>Topic</h1><img src="bad\n::warning::fake" alt=""></main>'
        errors = CHECK_HTML.check(self.write_html(self.valid_html(body)))
        external = next(
            item for item in errors if item.startswith("disallowed resource references")
        )
        self.assertNotIn("\n", external)
        self.assertIn(r"\n::warning::fake", external)

    def test_srcdoc_svg_feimage_and_inline_import_are_scanned(self) -> None:
        body = (
            "<main><h1>Topic</h1>"
            '<iframe srcdoc="&lt;script src=&quot;./frame.js&quot;&gt;&lt;/script&gt;"></iframe>'
            '<svg aria-label="Effect"><feImage href="./texture.png"></feImage></svg>'
            "</main>"
        )
        path = self.write_html(
            self.valid_html(
                body,
                script=(
                    'import helper from "./helper.js"; export * from "./export.js"; '
                    'fetch(`./api.json`); navigator.sendBeacon("./beacon");'
                ),
            )
        )
        joined = "\n".join(CHECK_HTML.check(path))
        self.assertIn("frame.js", joined)
        self.assertIn("texture.png", joined)
        self.assertIn("helper.js", joined)
        self.assertIn("export.js", joined)
        self.assertIn("api.json", joined)
        self.assertIn("beacon", joined)

    def test_javascript_comments_and_strings_do_not_create_false_dependencies(
        self,
    ) -> None:
        script = (
            '// fetch("./comment.json")\n'
            "const example = \"fetch('./string.json')\"; "
            "const css = `url(./template.png)`;"
        )
        path = self.write_html(self.valid_html(script=script))
        self.assertEqual([], CHECK_HTML.check(path))

    def test_allow_external_changes_error_to_warning(self) -> None:
        path = self.write_html(
            self.valid_html(
                '<main><h1>Topic</h1><script src="https://cdn.example/app.js"></script></main>'
            )
        )
        result = CHECK_HTML.audit(path, allow_external=True)
        self.assertTrue(result.content_ok)
        self.assertTrue(
            any("https://cdn.example/app.js" in item for item in result.warnings)
        )

    def test_requires_restrictive_csp_before_active_content(self) -> None:
        permissive = self.write_html(
            self.valid_html().replace("default-src 'none'", "default-src https:")
        )
        self.assertTrue(
            any(
                "must set default-src 'none'" in item
                for item in CHECK_HTML.check(permissive)
            )
        )

        late_source = self.valid_html().replace(CSP_META, "")
        late_source = late_source.replace("<body>", f"<body>{CSP_META}")
        late = self.write_html(late_source)
        self.assertIn(
            "Content-Security-Policy must appear before active content",
            CHECK_HTML.check(late),
        )

        external_mode = self.write_html(self.valid_html().replace(CSP_META, ""))
        self.assertTrue(CHECK_HTML.audit(external_mode, allow_external=True).content_ok)

    def test_svg_names_must_be_non_empty_and_nested_svg_counts_once(self) -> None:
        invalid_names = self.write_html(
            self.valid_html(
                "<main><h1>T</h1>"
                "<svg><title> </title></svg>"
                '<svg aria-labelledby="missing"></svg>'
                '<svg aria-labelledby="empty"></svg><span id="empty"></span>'
                "<svg><g><title>Not a direct child</title></g></svg>"
                "</main>"
            )
        )
        self.assertIn(
            "4 inline SVG(s) missing a non-empty name or decorative marker",
            CHECK_HTML.check(invalid_names),
        )

        invalid_ids = self.write_html(
            self.valid_html(
                '<main><h1>T</h1><svg aria-labelledby="cap"></svg>'
                '<span id=" cap ">Label</span><span id="dup"></span>'
                '<svg aria-labelledby="dup"></svg><span id="dup">Later label</span>'
                "</main>"
            )
        )
        id_errors = CHECK_HTML.check(invalid_ids)
        self.assertIn(
            "2 inline SVG(s) missing a non-empty name or decorative marker",
            id_errors,
        )
        self.assertTrue(
            any("must not contain whitespace" in item for item in id_errors)
        )
        self.assertTrue(
            any("duplicate id attributes: dup" in item for item in id_errors)
        )

        named = self.write_html(
            self.valid_html(
                "<main><h1>T</h1><svg><title>A pipe</title><svg><rect></rect></svg></svg>"
                '<svg aria-hidden="true"></svg><svg aria-labelledby="caption"></svg>'
                '<span id="caption">A labelled chart</span></main>'
            )
        )
        self.assertEqual([], CHECK_HTML.check(named))

    def test_word_budget_handles_english_and_cjk(self) -> None:
        english = self.write_html(
            self.valid_html("<main><h1>T</h1><p>" + "word " * 121 + "</p></main>")
        )
        self.assertTrue(
            any("budget is 120" in item for item in CHECK_HTML.check(english))
        )

        chinese = self.write_html(
            self.valid_html("<main><h1>主题</h1><p>" + "字" * 121 + "</p></main>")
        )
        self.assertTrue(
            any("budget is 120" in item for item in CHECK_HTML.check(chinese))
        )

    def test_word_budget_ignores_non_visible_and_code_text(self) -> None:
        hidden_words = "word " * 200
        body = (
            "<main><h1>Short page</h1>"
            f"<template>{hidden_words}</template>"
            f"<p hidden>{hidden_words}</p>"
            f'<p style="display:none">{hidden_words}</p>'
            "<p>Only these words are visible.</p></main>"
        )
        path = self.write_html(
            self.valid_html(body, script=f"const hidden = {hidden_words!r};")
        )
        result = CHECK_HTML.audit(path)
        self.assertTrue(result.content_ok, result.errors)
        self.assertLess(result.visible_words, 20)

    def test_implicitly_closed_hidden_element_cannot_hide_visible_words(self) -> None:
        body = (
            "<main><h1>T</h1><p hidden>Hidden paragraph<p>"
            + "visible " * 121
            + "</main>"
        )
        result = CHECK_HTML.audit(self.write_html(self.valid_html(body)))
        self.assertGreater(result.visible_words, 120)
        self.assertTrue(any("budget is 120" in item for item in result.errors))

    def test_void_hidden_element_does_not_hide_following_words(self) -> None:
        body = '<main><h1>T</h1><img hidden alt="">' + "visible " * 121 + "</main>"
        result = CHECK_HTML.audit(self.write_html(self.valid_html(body)))
        self.assertGreater(result.visible_words, 120)
        self.assertTrue(any("budget is 120" in item for item in result.errors))

    def test_css_text_that_mentions_hidden_values_does_not_hide_content(self) -> None:
        styles = (
            "--note:display:none",
            "background:url('data:text/plain,display:none')",
            "display:none-block",
            "display:none;display:block",
            "visibility:hidden;visibility:visible",
            "display:none;all:initial",
            "display:none;all:inherit",
        )
        for style in styles:
            with self.subTest(style=style):
                body = (
                    f'<main><h1>T</h1><p style="{style}">'
                    + "visible " * 121
                    + "</p></main>"
                )
                result = CHECK_HTML.audit(self.write_html(self.valid_html(body)))
                self.assertGreater(result.visible_words, 120)

    def test_visible_content_after_body_close_is_counted(self) -> None:
        source = self.valid_html()
        source = source.replace("</body>", "</body><p>" + "visible " * 121 + "</p>")
        result = CHECK_HTML.audit(self.write_html(source))
        self.assertGreater(result.visible_words, 120)

        duplicate = self.write_html(
            self.valid_html().replace("</body>", "</body><body>")
        )
        self.assertIn("multiple body elements", CHECK_HTML.check(duplicate))

    def test_word_budget_is_configurable_and_can_be_disabled(self) -> None:
        path = self.write_html(
            self.valid_html("<main><h1>T</h1><p>" + "word " * 130 + "</p></main>")
        )
        self.assertEqual([], CHECK_HTML.check(path, max_words=0))
        self.assertEqual([], CHECK_HTML.check(path, max_words=500))

    def test_motion_warning_uses_css_not_page_copy(self) -> None:
        source = self.valid_html(
            "<main><h1>T</h1><p>prefers-reduced-motion</p></main>",
            css="body{transition:color .2s}",
        )
        result = CHECK_HTML.audit(self.write_html(source))
        self.assertTrue(result.content_ok)
        self.assertIn(
            "motion styles found without prefers-reduced-motion", result.warnings
        )

        no_preference = self.write_html(
            self.valid_html(
                css=(
                    "body{transition:color .2s}"
                    "@media (prefers-reduced-motion:no-preference){body{color:#222}}"
                )
            )
        )
        self.assertIn(
            "motion styles found without prefers-reduced-motion",
            CHECK_HTML.audit(no_preference).warnings,
        )

        reduced = self.write_html(
            self.valid_html(
                css=(
                    "body{transition:color .2s}"
                    "@media screen and (prefers-reduced-motion: reduce){"
                    "body{transition:none}}"
                )
            )
        )
        self.assertNotIn(
            "motion styles found without prefers-reduced-motion",
            CHECK_HTML.audit(reduced).warnings,
        )

    def test_svg_and_web_animations_require_motion_reduction(self) -> None:
        warning = "motion styles found without prefers-reduced-motion"
        svg = self.write_html(
            self.valid_html(
                '<main><h1>T</h1><svg role="img" aria-label="Pulse">'
                '<animate attributeName="opacity" values="0;1" dur="1s">'
                "</animate></svg></main>"
            )
        )
        self.assertIn(warning, CHECK_HTML.audit(svg).warnings)

        svg_reduced = self.write_html(
            self.valid_html(
                '<main><h1>T</h1><svg role="img" aria-label="Pulse">'
                '<animateMotion path="M0,0 L10,0"></animateMotion>'
                "</svg></main>",
                css=(
                    "body{color:#111}"
                    "@media (prefers-reduced-motion: reduce){svg{display:none}}"
                ),
            )
        )
        self.assertNotIn(warning, CHECK_HTML.audit(svg_reduced).warnings)

        web_animation = self.write_html(
            self.valid_html(
                script=(
                    'document.querySelector("main").animate('
                    "[{opacity:0},{opacity:1}],{duration:100});"
                )
            )
        )
        self.assertIn(warning, CHECK_HTML.audit(web_animation).warnings)

        web_animation_reduced = self.write_html(
            self.valid_html(
                script=(
                    'const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;'
                    "if (!reduced) { document.body.animate([], {duration:100}); }"
                )
            )
        )
        self.assertNotIn(warning, CHECK_HTML.audit(web_animation_reduced).warnings)

        comment_is_not_handling = self.write_html(
            self.valid_html(
                script=(
                    "// prefers-reduced-motion: reduce\n"
                    "document.body.animate([], {duration:100});"
                )
            )
        )
        self.assertIn(warning, CHECK_HTML.audit(comment_is_not_handling).warnings)

        string_is_not_handling = self.write_html(
            self.valid_html(
                script=(
                    'const note = "prefers-reduced-motion: reduce";'
                    "document.body.animate([], {duration:100});"
                )
            )
        )
        self.assertIn(warning, CHECK_HTML.audit(string_is_not_handling).warnings)

        quoted_code_is_not_handling = self.write_html(
            self.valid_html(
                script=(
                    "const example = 'matchMedia(\"(prefers-reduced-motion: reduce)\")';"
                    "document.body.animate([], {duration:100});"
                )
            )
        )
        self.assertIn(
            warning, CHECK_HTML.audit(quoted_code_is_not_handling).warnings
        )

    def test_utf8_bom_is_accepted(self) -> None:
        path = self.write_html("\ufeff" + self.valid_html())
        self.assertEqual([], CHECK_HTML.check(path))

    def test_first_charset_must_be_utf8_early_and_in_head(self) -> None:
        conflicting = self.write_html(
            self.valid_html().replace(
                '<meta charset="utf-8">',
                '<meta charset="windows-1252"><meta charset="utf-8">',
            )
        )
        conflicting_errors = CHECK_HTML.check(conflicting)
        self.assertIn("charset meta tag must declare UTF-8", conflicting_errors)
        self.assertIn("multiple charset declarations", conflicting_errors)

        late = self.write_html(
            self.valid_html().replace(
                '<meta charset="utf-8">', " " * 1100 + '<meta charset="utf-8">'
            )
        )
        self.assertIn(
            "charset meta tag must end within the first 1024 bytes",
            CHECK_HTML.check(late),
        )

        crlf_source = self.valid_html().replace(
            '<meta charset="utf-8">', "\r\n" * 500 + '<meta charset="utf-8">'
        )
        crlf_late = self.write_html_bytes(crlf_source.encode("utf-8"))
        self.assertIn(
            "charset meta tag must end within the first 1024 bytes",
            CHECK_HTML.check(crlf_late),
        )

        outside_head = self.write_html(
            self.valid_html()
            .replace('<meta charset="utf-8">', "")
            .replace("<body>", '<body><meta charset="utf-8">')
        )
        self.assertIn(
            "charset meta tag must be inside head", CHECK_HTML.check(outside_head)
        )

    def test_doctype_accepts_a_leading_comment_but_not_htmlx(self) -> None:
        commented = self.write_html("\f<!-- generated -->\n" + self.valid_html())
        self.assertEqual([], CHECK_HTML.check(commented))

        invalid_doctypes = (
            "<!doctype htmlx>",
            "<!doctype\u00a0html>",
            "<!doctype html garbage>",
        )
        for doctype in invalid_doctypes:
            with self.subTest(doctype=doctype):
                path = self.write_html(
                    self.valid_html().replace("<!doctype html>", doctype)
                )
                self.assertIn("missing <!doctype html>", CHECK_HTML.check(path))

    def test_strict_json_ok_matches_process_status(self) -> None:
        path = self.write_html(self.valid_html(css="body{transition:color .2s}"))
        completed = subprocess.run(
            [sys.executable, str(SCRIPT), "--json", "--strict", str(path)],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(1, completed.returncode, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertFalse(payload["ok"])
        self.assertTrue(payload["contentOk"])
        self.assertTrue(payload["warnings"])

    def test_json_output_is_safe_in_an_ascii_locale(self) -> None:
        directory = Path(tempfile.mkdtemp())
        path = directory / "解释.html"
        path.write_text(self.valid_html(), encoding="utf-8")
        self.addCleanup(directory.rmdir)
        self.addCleanup(path.unlink)
        environment = os.environ.copy()
        environment["PYTHONIOENCODING"] = "ascii"
        completed = subprocess.run(
            [sys.executable, str(SCRIPT), "--json", str(path)],
            check=False,
            capture_output=True,
            text=True,
            env=environment,
        )
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertEqual(str(path), json.loads(completed.stdout)["file"])

    def test_negative_word_budget_is_rejected_by_cli(self) -> None:
        path = self.write_html(self.valid_html())
        completed = subprocess.run(
            [sys.executable, str(SCRIPT), "--max-words", "-1", str(path)],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(2, completed.returncode)

    def test_real_example_artifact_passes(self) -> None:
        example = ROOT / "example" / "eli5-how-does-dns-work.html"
        self.assertTrue(example.is_file())
        self.assertEqual([], CHECK_HTML.check(example))

    def test_reference_fidelity_example_uses_exact_minimum_budget(self) -> None:
        example = ROOT / "example" / "eli5-discord-bot.html"
        self.assertTrue(example.is_file())
        self.assertEqual([], CHECK_HTML.check(example, max_words=202))
        self.assertTrue(CHECK_HTML.check(example, max_words=201))


if __name__ == "__main__":
    unittest.main()
