#!/usr/bin/env python3
"""Run dependency-free checks on an ELI5 HTML artifact."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse


@dataclass
class CheckResult:
    """Structured result for CLI users and future integrations."""

    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def _is_network_url(value: str) -> bool:
    value = value.strip()
    parsed = urlparse(value)
    return parsed.scheme.lower() in {"http", "https"} or value.startswith("//")


def _resource_urls(value: str, is_srcset: bool = False) -> List[str]:
    if not is_srcset:
        return [value]
    urls: List[str] = []
    for candidate in value.split(","):
        candidate = candidate.strip()
        if candidate:
            urls.append(candidate.split()[0])
    return urls


class ArtifactParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.has_html = False
        self.has_body = False
        self.has_main = False
        self.has_heading = False
        self.lang = ""
        self.charset = ""
        self.title_parts: List[str] = []
        self.in_document_title = False
        self.viewport = ""
        self.has_style = False
        self.external_resources: List[str] = []
        self.images_without_alt = 0
        self.svgs_without_name = 0
        self.svg_stack: List[Dict[str, bool]] = []

    def _record_resource(self, value: str, is_srcset: bool = False) -> None:
        for candidate in _resource_urls(value, is_srcset=is_srcset):
            if _is_network_url(candidate) and candidate not in self.external_resources:
                self.external_resources.append(candidate)

    def handle_starttag(
        self, tag: str, attrs: List[Tuple[str, Optional[str]]]
    ) -> None:
        tag = tag.lower()
        values = {key.lower(): value for key, value in attrs}
        if tag == "html":
            self.has_html = True
            self.lang = (values.get("lang") or "").strip()
        elif tag == "body":
            self.has_body = True
        elif tag == "main":
            self.has_main = True
        elif tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self.has_heading = True
        elif tag == "title":
            if self.svg_stack:
                self.svg_stack[-1]["has_title"] = True
            else:
                self.in_document_title = True
        elif tag == "meta":
            if "charset" in values:
                self.charset = (values.get("charset") or "").strip()
            elif (values.get("http-equiv") or "").lower() == "content-type":
                match = re.search(
                    r"charset\s*=\s*([^;\s]+)",
                    values.get("content") or "",
                    flags=re.IGNORECASE,
                )
                if match:
                    self.charset = match.group(1).strip("'\"")
            if (values.get("name") or "").lower() == "viewport":
                self.viewport = (values.get("content") or "").strip()
            if (values.get("http-equiv") or "").lower() == "refresh":
                match = re.search(
                    r"\burl\s*=\s*([^;]+)",
                    values.get("content") or "",
                    flags=re.IGNORECASE,
                )
                if match:
                    self._record_resource(match.group(1).strip("'\" "))
        elif tag == "style":
            self.has_style = True
        elif tag == "img" and "alt" not in values:
            self.images_without_alt += 1

        if tag == "svg":
            role = (values.get("role") or "").lower()
            hidden = (values.get("aria-hidden") or "").lower() == "true"
            hidden = hidden or role in {"none", "presentation"}
            named = bool(
                (values.get("aria-label") or "").strip()
                or (values.get("aria-labelledby") or "").strip()
            )
            self.svg_stack.append(
                {"hidden": hidden, "named": named, "has_title": False}
            )

        for attribute in ("src", "poster"):
            value = (values.get(attribute) or "").strip()
            if value:
                self._record_resource(value)
        srcset = (values.get("srcset") or "").strip()
        if srcset:
            self._record_resource(srcset, is_srcset=True)
        if tag in {"link", "use", "image"}:
            href = (values.get("href") or values.get("xlink:href") or "").strip()
            if href:
                self._record_resource(href)
        if tag == "object":
            data = (values.get("data") or "").strip()
            if data:
                self._record_resource(data)
        if tag == "form":
            action = (values.get("action") or "").strip()
            if action:
                self._record_resource(action)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "title" and self.in_document_title:
            self.in_document_title = False
        elif tag == "svg" and self.svg_stack:
            svg = self.svg_stack.pop()
            if not (svg["hidden"] or svg["named"] or svg["has_title"]):
                self.svgs_without_name += 1

    def handle_data(self, data: str) -> None:
        if self.in_document_title:
            self.title_parts.append(data)

    def finish(self) -> None:
        while self.svg_stack:
            svg = self.svg_stack.pop()
            if not (svg["hidden"] or svg["named"] or svg["has_title"]):
                self.svgs_without_name += 1


def audit(path: Path, allow_network: bool = False) -> CheckResult:
    result = CheckResult()
    if path.suffix.lower() not in {".html", ".htm"}:
        result.errors.append("file extension must be .html or .htm")
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        result.errors.append(f"cannot read UTF-8 HTML: {exc}")
        return result

    parser = ArtifactParser()
    try:
        parser.feed(source)
        parser.close()
        parser.finish()
    except Exception as exc:  # HTMLParser can surface malformed entities.
        result.errors.append(f"HTML parsing failed: {exc}")

    if not re.match(r"\s*<!doctype\s+html", source, flags=re.IGNORECASE):
        result.errors.append("missing <!doctype html>")
    if not parser.has_html:
        result.errors.append("missing html element")
    if not parser.lang:
        result.errors.append("missing html lang attribute")
    normalized_charset = parser.charset.lower().replace("_", "-")
    if not normalized_charset:
        result.errors.append("missing charset meta tag")
    elif normalized_charset not in {"utf-8", "utf8"}:
        result.errors.append("charset meta tag must declare UTF-8")
    if not "".join(parser.title_parts).strip():
        result.errors.append("missing non-empty title")
    if not parser.viewport:
        result.errors.append("missing viewport meta tag")
    elif "width=device-width" not in parser.viewport.lower().replace(" ", ""):
        result.errors.append("viewport must include width=device-width")
    if not parser.has_style:
        result.errors.append("missing inline style block")
    if not parser.has_body:
        result.errors.append("missing body element")
    if parser.images_without_alt:
        result.errors.append(
            f"{parser.images_without_alt} image(s) missing an alt attribute"
        )
    if parser.svgs_without_name:
        result.errors.append(
            f"{parser.svgs_without_name} SVG(s) missing a name or decorative marker"
        )

    css_network_patterns = (
        r"@import\s+(?:url\()?\s*['\"]?(?:https?:)?//",
        r"url\(\s*['\"]?(?:https?:)?//",
    )
    if any(re.search(pattern, source, flags=re.IGNORECASE) for pattern in css_network_patterns):
        if "CSS network reference" not in parser.external_resources:
            parser.external_resources.append("CSS network reference")

    if parser.external_resources:
        message = "network resources found: " + ", ".join(parser.external_resources)
        if allow_network:
            result.warnings.append(message)
        else:
            result.errors.append(message)

    if not parser.has_main:
        result.warnings.append("missing main landmark")
    if not parser.has_heading:
        result.warnings.append("missing heading element")
    has_motion = bool(
        re.search(r"\b(?:animation|transition)(?:-[\w-]+)?\s*:", source, re.IGNORECASE)
    )
    if has_motion and "prefers-reduced-motion" not in source.lower():
        result.warnings.append("motion styles found without prefers-reduced-motion")
    return result


def check(path: Path, allow_network: bool = False) -> List[str]:
    """Return only blocking errors for compatibility with the original API."""

    return audit(path, allow_network=allow_network).errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("html_file", type=Path)
    parser.add_argument(
        "--allow-network",
        action="store_true",
        help="Allow external resources but report them as warnings.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Emit a machine-readable result.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Return a non-zero status when warnings are present.",
    )
    args = parser.parse_args()
    result = audit(args.html_file, allow_network=args.allow_network)
    passed = result.ok and not (args.strict and result.warnings)

    if args.json_output:
        print(
            json.dumps(
                {
                    "file": str(args.html_file),
                    "ok": result.ok,
                    "strictOk": passed,
                    "errors": result.errors,
                    "warnings": result.warnings,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        for warning in result.warnings:
            print(f"WARNING: {warning}", file=sys.stderr)
        for error in result.errors:
            print(f"ERROR: {error}", file=sys.stderr)
        if passed:
            print(f"OK: {args.html_file} is a valid ELI5 HTML artifact")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
