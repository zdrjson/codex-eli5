#!/usr/bin/env python3
"""Run lightweight, dependency-free checks on an ELI5 HTML artifact."""

from __future__ import annotations

import argparse
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse


class ArtifactParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.lang = ""
        self.title_parts: list[str] = []
        self.in_title = False
        self.has_viewport = False
        self.has_style = False
        self.external_resources: list[str] = []
        self.images_without_alt = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "html":
            self.lang = (values.get("lang") or "").strip()
        elif tag == "title":
            self.in_title = True
        elif tag == "meta" and (values.get("name") or "").lower() == "viewport":
            self.has_viewport = bool((values.get("content") or "").strip())
        elif tag == "style":
            self.has_style = True
        elif tag == "img" and not (values.get("alt") or "").strip():
            self.images_without_alt += 1

        resource_attributes = ["src", "poster", "srcset"]
        if tag == "link":
            resource_attributes.append("href")
        for key in resource_attributes:
            value = (values.get(key) or "").strip()
            if value and urlparse(value.split()[0]).scheme in {"http", "https"}:
                self.external_resources.append(value)

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self.in_title = False

    def handle_data(self, data: str) -> None:
        if self.in_title:
            self.title_parts.append(data)


def check(path: Path) -> list[str]:
    errors: list[str] = []
    if path.suffix.lower() not in {".html", ".htm"}:
        errors.append("file extension must be .html or .htm")
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        return [f"cannot read UTF-8 HTML: {exc}"]

    parser = ArtifactParser()
    try:
        parser.feed(source)
    except Exception as exc:  # HTMLParser can surface malformed entities.
        errors.append(f"HTML parsing failed: {exc}")

    if not re.match(r"\s*<!doctype\s+html", source, flags=re.IGNORECASE):
        errors.append("missing <!doctype html>")
    if not parser.lang:
        errors.append("missing html lang attribute")
    if not "".join(parser.title_parts).strip():
        errors.append("missing non-empty title")
    if not parser.has_viewport:
        errors.append("missing viewport meta tag")
    if not parser.has_style:
        errors.append("missing inline style block")
    if parser.external_resources:
        errors.append("external resources found: " + ", ".join(parser.external_resources))
    if re.search(r"@import\s+(?:url\()?['\"]?https?://", source, flags=re.IGNORECASE):
        errors.append("external CSS import found")
    if re.search(r"url\(\s*['\"]?https?://", source, flags=re.IGNORECASE):
        errors.append("external CSS asset found")
    if parser.images_without_alt:
        errors.append(f"{parser.images_without_alt} image(s) missing alt text")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("html_file", type=Path)
    args = parser.parse_args()
    errors = check(args.html_file)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(f"OK: {args.html_file} is a self-contained ELI5 HTML artifact")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
