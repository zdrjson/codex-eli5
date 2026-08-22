#!/usr/bin/env python3
"""Check that an ELI5 page is self-contained, visual, and accessible.

The checker has no third-party dependencies and supports Python 3.9+.
It validates two contracts:

* self-contained: one UTF-8 HTML file with no hidden file or network dependencies
* picture-first: a configurable visible-word budget and named inline SVGs
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Dict, List, Optional, Tuple

DEFAULT_MAX_WORDS = 120
VOID_ELEMENTS = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "frame",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "param",
    "source",
    "track",
    "wbr",
}
SKIP_TEXT_TAGS = {"noscript", "script", "style", "template"}
SRC_RESOURCE_TAGS = {
    "audio",
    "embed",
    "frame",
    "iframe",
    "img",
    "input",
    "script",
    "source",
    "track",
    "video",
}
BACKGROUND_RESOURCE_TAGS = {"body", "table", "td", "th"}
LINK_RESOURCE_RELS = {
    "apple-touch-icon",
    "dns-prefetch",
    "icon",
    "manifest",
    "mask-icon",
    "modulepreload",
    "preconnect",
    "prefetch",
    "preload",
    "prerender",
    "stylesheet",
}
P_CLOSING_START_TAGS = {
    "address",
    "article",
    "aside",
    "blockquote",
    "details",
    "dialog",
    "div",
    "dl",
    "fieldset",
    "figcaption",
    "figure",
    "footer",
    "form",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "header",
    "hgroup",
    "hr",
    "main",
    "menu",
    "nav",
    "ol",
    "p",
    "pre",
    "search",
    "section",
    "table",
    "ul",
}
CJK_CHARACTER_RE = re.compile(
    "[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af\uf900-\ufaff]"
)
WORD_RE = re.compile(r"[^\W_]+(?:['’\-][^\W_]+)*", flags=re.UNICODE)
REQUIRED_CSP_DIRECTIVES = {
    "default-src": ["'none'"],
    "base-uri": ["'none'"],
    "form-action": ["'none'"],
    "img-src": ["data:"],
    "font-src": ["data:"],
    "media-src": ["data:"],
    "style-src": ["'unsafe-inline'"],
    "script-src": ["'unsafe-inline'"],
}


@dataclass
class CheckResult:
    """Structured result for the CLI and future integrations."""

    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    visible_words: int = 0

    @property
    def content_ok(self) -> bool:
        return not self.errors

    @property
    def ok(self) -> bool:
        """Backward-compatible alias for callers that only inspect errors."""

        return self.content_ok


def _first_values(attrs: List[Tuple[str, Optional[str]]]) -> Dict[str, str]:
    values: Dict[str, str] = {}
    for raw_key, raw_value in attrs:
        key = raw_key.lower()
        if key not in values:
            values[key] = raw_value or ""
    return values


def _is_inline_reference(value: str) -> bool:
    value = value.strip().strip("'\"")
    lowered = value.lower()
    return (
        not value
        or value.startswith("#")
        or lowered.startswith("data:")
        or lowered == "about:blank"
    )


def _has_html_doctype(source: str) -> bool:
    remainder = source.lstrip("\ufeff \t\n\f\r")
    while remainder.startswith("<!--"):
        comment_end = remainder.find("-->")
        if comment_end < 0:
            return False
        remainder = remainder[comment_end + 3 :].lstrip(" \t\n\f\r")
    return bool(
        re.match(
            r"<!doctype[\t\n\f\r ]+html[\t\n\f\r ]*>",
            remainder,
            flags=re.IGNORECASE,
        )
    )


def _byte_offset(source: str, line: int, column: int, tag_text: str) -> int:
    line_starts = [0]
    line_starts.extend(match.end() for match in re.finditer("\n", source))
    if line < 1 or line > len(line_starts):
        return len(source.encode("utf-8")) + 1
    character_end = line_starts[line - 1] + column + len(tag_text)
    return len(source[:character_end].encode("utf-8"))


def _display_reference(value: str) -> str:
    escaped: List[str] = []
    for character in value:
        codepoint = ord(character)
        if character == "\n":
            escaped.append(r"\n")
        elif character == "\r":
            escaped.append(r"\r")
        elif character == "\t":
            escaped.append(r"\t")
        elif codepoint < 32 or codepoint == 127:
            escaped.append(f"\\x{codepoint:02x}")
        elif codepoint in {0x2028, 0x2029}:
            escaped.append(f"\\u{codepoint:04x}")
        else:
            escaped.append(character)
    return "".join(escaped)


def _strip_css_comments(source: str) -> str:
    output: List[str] = []
    position = 0
    quote = ""
    while position < len(source):
        character = source[position]
        if quote:
            output.append(character)
            if character == "\\" and position + 1 < len(source):
                position += 1
                output.append(source[position])
            elif character == quote:
                quote = ""
        elif character in {"'", '"'}:
            quote = character
            output.append(character)
        elif source.startswith("/*", position):
            end = source.find("*/", position + 2)
            if end < 0:
                break
            output.append(" ")
            position = end + 1
        else:
            output.append(character)
        position += 1
    return "".join(output)


def _style_hides_element(style: str) -> bool:
    css = _strip_css_comments(style)
    code_mask = _code_mask(css, line_comments=False)
    pattern = re.compile(
        r"(?:^|;)\s*(display|visibility|content-visibility|all)\s*:\s*([^;]*)",
        flags=re.IGNORECASE,
    )
    winners: Dict[str, Tuple[bool, int, str]] = {}
    tracked_properties = ("display", "visibility", "content-visibility")
    for order, match in enumerate(pattern.finditer(css)):
        if not code_mask[match.start(1)]:
            continue
        property_name = match.group(1).lower()
        value = match.group(2).strip()
        important_match = re.search(r"!\s*important\s*$", value, flags=re.IGNORECASE)
        important = important_match is not None
        if important_match:
            value = value[: important_match.start()].strip()

        properties = (property_name,)
        if property_name == "all":
            properties = tracked_properties
            value = "visible-default"

        for target in properties:
            current = winners.get(target)
            if current is None or important or not current[0]:
                winners[target] = (important, order, value.lower())

    return (
        winners.get("display", (False, -1, ""))[2] == "none"
        or winners.get("visibility", (False, -1, ""))[2] in {"hidden", "collapse"}
        or winners.get("content-visibility", (False, -1, ""))[2] == "hidden"
    )


def _parse_csp(content: str) -> Tuple[Dict[str, List[str]], List[str]]:
    directives: Dict[str, List[str]] = {}
    duplicates: List[str] = []
    for raw_directive in content.split(";"):
        parts = raw_directive.split()
        if not parts:
            continue
        name = parts[0].lower()
        if name in directives:
            duplicates.append(name)
            continue
        directives[name] = [value.lower() for value in parts[1:]]
    return directives, duplicates


def _csp_errors(policies: List[Tuple[str, bool]]) -> List[str]:
    if not policies:
        return ["missing restrictive Content-Security-Policy meta tag"]
    if len(policies) != 1:
        return ["expected exactly one Content-Security-Policy meta tag"]

    content, before_active_content = policies[0]
    errors: List[str] = []
    if not before_active_content:
        errors.append("Content-Security-Policy must appear before active content")

    directives, duplicates = _parse_csp(content)
    if duplicates:
        errors.append(
            "duplicate Content-Security-Policy directives: " + ", ".join(duplicates)
        )
    for name, required_values in REQUIRED_CSP_DIRECTIVES.items():
        if directives.get(name) != required_values:
            errors.append(
                f"Content-Security-Policy must set {name} " + " ".join(required_values)
            )
    unexpected = sorted(set(directives).difference(REQUIRED_CSP_DIRECTIVES))
    if unexpected:
        errors.append(
            "unsupported Content-Security-Policy directives: " + ", ".join(unexpected)
        )
    return errors


def _srcset_candidates(value: str) -> List[str]:
    """Return srcset URLs, preserving commas inside data-URI candidates.

    A normal candidate URL ends at whitespace or a comma. A data URI consumes
    commas until its first whitespace; the optional descriptor then ends at the
    candidate-separating comma. This also handles compact ``1x,next.png`` forms.
    """

    candidates: List[str] = []
    position = 0
    length = len(value)
    while position < length:
        while position < length and (
            value[position].isspace() or value[position] == ","
        ):
            position += 1
        if position >= length:
            break

        start = position
        is_data_uri = value[position : position + 5].lower() == "data:"
        if is_data_uri:
            while position < length and not value[position].isspace():
                position += 1
        else:
            while (
                position < length
                and not value[position].isspace()
                and value[position] != ","
            ):
                position += 1

        candidate = value[start:position].strip()
        data_candidate_ended_with_separator = is_data_uri and candidate.endswith(",")
        if data_candidate_ended_with_separator:
            candidate = candidate.rstrip(",")
        if candidate:
            candidates.append(candidate)

        if data_candidate_ended_with_separator:
            continue

        while position < length and value[position] != ",":
            position += 1
        if position < length:
            position += 1
    return candidates


def _code_mask(source: str, line_comments: bool) -> List[bool]:
    """Mark source positions that are outside comments and quoted strings."""

    mask = [True] * len(source)
    position = 0
    while position < len(source):
        character = source[position]
        if character in {"'", '"', "`"}:
            quote = character
            mask[position] = False
            position += 1
            while position < len(source):
                mask[position] = False
                if source[position] == "\\":
                    position += 1
                    if position < len(source):
                        mask[position] = False
                elif source[position] == quote:
                    position += 1
                    break
                position += 1
            continue
        if source.startswith("/*", position):
            end = source.find("*/", position + 2)
            stop = len(source) if end < 0 else end + 2
            for index in range(position, stop):
                mask[index] = False
            position = stop
            continue
        if line_comments and source.startswith("//", position):
            end = source.find("\n", position + 2)
            stop = len(source) if end < 0 else end
            for index in range(position, stop):
                mask[index] = False
            position = stop
            continue
        position += 1
    return mask


def _css_function_body(css: str, open_parenthesis: int) -> Tuple[str, int]:
    depth = 1
    position = open_parenthesis + 1
    start = position
    quote = ""
    while position < len(css):
        character = css[position]
        if quote:
            if character == "\\":
                position += 2
                continue
            if character == quote:
                quote = ""
        elif character in {"'", '"'}:
            quote = character
        elif css.startswith("/*", position):
            end = css.find("*/", position + 2)
            position = len(css) if end < 0 else end + 2
            continue
        elif character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
            if depth == 0:
                return css[start:position], position + 1
        position += 1
    return css[start:], len(css)


def _split_css_candidates(source: str) -> List[str]:
    candidates: List[str] = []
    start = 0
    depth = 0
    quote = ""
    position = 0
    while position < len(source):
        character = source[position]
        if quote:
            if character == "\\":
                position += 2
                continue
            if character == quote:
                quote = ""
        elif character in {"'", '"'}:
            quote = character
        elif character == "(":
            depth += 1
        elif character == ")" and depth:
            depth -= 1
        elif character == "," and depth == 0:
            candidates.append(source[start:position].strip())
            start = position + 1
        position += 1
    candidates.append(source[start:].strip())
    return candidates


def _css_image_set_references(css: str, code_mask: List[bool]) -> List[str]:
    references: List[str] = []
    pattern = re.compile(r"(?:-webkit-)?image-set\s*\(", flags=re.IGNORECASE)
    position = 0
    while True:
        match = pattern.search(css, position)
        if not match:
            break
        position = match.end()
        if not code_mask[match.start()]:
            continue
        body, position = _css_function_body(css, match.end() - 1)
        for candidate in _split_css_candidates(body):
            if not candidate or candidate[0] not in {"'", '"'}:
                continue
            quote = candidate[0]
            end = 1
            while end < len(candidate):
                if candidate[end] == "\\":
                    end += 2
                    continue
                if candidate[end] == quote:
                    value = candidate[1:end].strip()
                    if value and value not in references:
                        references.append(value)
                    break
                end += 1
    return references


def _css_external_references(css: str) -> List[str]:
    code_mask = _code_mask(css, line_comments=False)
    references: List[str] = []
    for match in re.finditer(
        r"url\(\s*(['\"]?)(.*?)\1\s*\)", css, re.IGNORECASE | re.DOTALL
    ):
        if not code_mask[match.start()]:
            continue
        value = match.group(2).strip()
        if not _is_inline_reference(value) and value not in references:
            references.append(value)
    for match in re.finditer(
        r"@import\s+(['\"])(.*?)\1", css, re.IGNORECASE | re.DOTALL
    ):
        if not code_mask[match.start()]:
            continue
        value = match.group(2).strip()
        if not _is_inline_reference(value) and value not in references:
            references.append(value)
    for value in _css_image_set_references(css, code_mask):
        if not _is_inline_reference(value) and value not in references:
            references.append(value)
    return references


def _script_external_references(script: str) -> List[str]:
    code_mask = _code_mask(script, line_comments=True)
    patterns = (
        r"\b(?:import|export)\s*(?:\(\s*)?(?:[^'\"`\n]*?\sfrom\s*)?['\"`]([^'\"`]+)['\"`]",
        r"\b(?:fetch|WebSocket|EventSource)\s*\(\s*['\"`]([^'\"`]+)['\"`]",
        r"\b(?:Worker|SharedWorker)\s*\(\s*['\"`]([^'\"`]+)['\"`]",
        r"\bserviceWorker\.register\s*\(\s*['\"`]([^'\"`]+)['\"`]",
        r"\bsendBeacon\s*\(\s*['\"`]([^'\"`]+)['\"`]",
        r"\.open\s*\(\s*['\"`][A-Z]+['\"`]\s*,\s*['\"`]([^'\"`]+)['\"`]",
    )
    references: List[str] = []
    for pattern in patterns:
        for match in re.finditer(pattern, script, flags=re.IGNORECASE):
            if not code_mask[match.start()]:
                continue
            value = match.group(1)
            if "${" in value:
                continue
            value = value.strip()
            if not _is_inline_reference(value) and value not in references:
                references.append(value)
    return references


class ArtifactParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.has_html = False
        self.has_head = False
        self.has_body = False
        self.body_count = 0
        self.has_main = False
        self.has_heading = False
        self.lang = ""
        self.charset = ""
        self.charset_declarations: List[Tuple[str, int, int, str, bool]] = []
        self.viewport = ""
        self.title_parts: List[str] = []
        self.in_document_title = False
        self.has_style = False
        self.external_resources: List[str] = []
        self.images_without_alt = 0
        self.svgs_without_name = 0
        self.invalid_ids: List[str] = []
        self.duplicate_ids: List[str] = []
        self.csp_policies: List[Tuple[str, bool]] = []

        self._in_body = False
        self._in_head = False
        self._active_content_seen = False
        self._element_stack: List[Tuple[str, bool, bool, str]] = []
        self._hidden_depth = 0
        self._skip_text_depth = 0
        self._style_depth = 0
        self._script_depth = 0
        self._css_parts: List[str] = []
        self._script_parts: List[str] = []
        self._visible_text: List[str] = []
        self._id_text_parts: Dict[str, List[str]] = {}
        self._active_id_elements: List[Tuple[str, str]] = []

        self._svg_depth = 0
        self._svg_hidden = False
        self._svg_named = False
        self._svg_label_references: List[str] = []
        self._svg_title_flags: List[bool] = []
        self._svg_title_parts: List[str] = []
        self._svg_records: List[Tuple[bool, bool, bool, List[str]]] = []

    def _add_external(self, context: str, value: str) -> None:
        item = f"{context}={_display_reference(value)}"
        if item not in self.external_resources:
            self.external_resources.append(item)

    def _record_resource(
        self,
        tag: str,
        attribute: str,
        value: str,
        is_srcset: bool = False,
        allow_data: bool = True,
    ) -> None:
        candidates = _srcset_candidates(value) if is_srcset else [value]
        for candidate in candidates:
            candidate = candidate.strip()
            is_data = candidate.lower().startswith("data:")
            if (is_data and not allow_data) or not _is_inline_reference(candidate):
                self._add_external(f"{tag}[{attribute}]", candidate)

    def _scan_srcdoc(self, source: str) -> None:
        nested = ArtifactParser()
        try:
            nested.feed(source)
            nested.close()
            nested.finish()
        except Exception:
            return
        for item in nested.all_external_resources():
            self._add_external("iframe[srcdoc]", item)

    def _close_stack_from(self, match_index: int) -> None:
        closed = self._element_stack[match_index:]
        del self._element_stack[match_index:]
        for _, hidden_started, skip_started, closed_id in closed:
            if hidden_started and self._hidden_depth:
                self._hidden_depth -= 1
            if skip_started and self._skip_text_depth:
                self._skip_text_depth -= 1
            if closed_id:
                for index in range(len(self._active_id_elements) - 1, -1, -1):
                    if self._active_id_elements[index][1] == closed_id:
                        del self._active_id_elements[index]
                        break

    def _apply_implicit_closures(self, incoming_tag: str) -> None:
        candidates = set()
        if incoming_tag in P_CLOSING_START_TAGS:
            candidates.add("p")
        if incoming_tag == "li":
            candidates.add("li")
        elif incoming_tag in {"dt", "dd"}:
            candidates.update({"dt", "dd"})
        elif incoming_tag in {"rt", "rp"}:
            candidates.update({"rt", "rp"})
        elif incoming_tag == "option":
            candidates.add("option")
        elif incoming_tag == "optgroup":
            candidates.update({"option", "optgroup"})
        elif incoming_tag in {"thead", "tbody", "tfoot"}:
            candidates.update({"thead", "tbody", "tfoot"})
        elif incoming_tag == "tr":
            candidates.add("tr")
        elif incoming_tag in {"td", "th"}:
            candidates.update({"td", "th"})
        elif incoming_tag == "colgroup":
            candidates.add("colgroup")
        elif incoming_tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            candidates.update({"h1", "h2", "h3", "h4", "h5", "h6"})
        elif incoming_tag == "button":
            candidates.add("button")

        for index in range(len(self._element_stack) - 1, -1, -1):
            if self._element_stack[index][0] in candidates:
                self._close_stack_from(index)
                break

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        tag = tag.lower()
        self._apply_implicit_closures(tag)
        values = _first_values(attrs)
        attr_names = {key.lower() for key, _ in attrs}
        raw_element_id = values.get("id", "")
        element_id = ""
        if raw_element_id and re.search(r"[\t\n\f\r ]", raw_element_id):
            displayed_id = _display_reference(raw_element_id)
            if displayed_id not in self.invalid_ids:
                self.invalid_ids.append(displayed_id)
        elif raw_element_id in self._id_text_parts:
            if raw_element_id not in self.duplicate_ids:
                self.duplicate_ids.append(raw_element_id)
        elif raw_element_id:
            element_id = raw_element_id
            parts = self._id_text_parts.setdefault(element_id, [])
            aria_label = values.get("aria-label", "").strip()
            if aria_label:
                parts.append(aria_label)

        http_equiv = values.get("http-equiv", "").lower()
        is_csp_meta = tag == "meta" and http_equiv == "content-security-policy"
        if is_csp_meta:
            self.csp_policies.append(
                (values.get("content", "").strip(), not self._active_content_seen)
            )
        elif tag not in {"html", "head", "meta", "title"} or (
            tag == "meta" and http_equiv == "refresh"
        ):
            self._active_content_seen = True

        if tag == "html":
            self.has_html = True
            self.lang = values.get("lang", "").strip()
        elif tag == "head":
            self.has_head = True
            self._in_head = True
        elif tag == "body":
            self.has_body = True
            self.body_count += 1
            self._in_body = True
            self._in_head = False
        elif tag == "main":
            self.has_main = True
        elif tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self.has_heading = True
        elif tag == "title":
            if self._svg_depth:
                names_outer_svg = (
                    self._svg_depth == 1
                    and bool(self._element_stack)
                    and self._element_stack[-1][0] == "svg"
                )
                self._svg_title_flags.append(names_outer_svg)
            else:
                self.in_document_title = True
        elif tag == "meta":
            declared_charset = ""
            if "charset" in values:
                declared_charset = values["charset"].strip()
            elif http_equiv == "content-type":
                match = re.search(
                    r"charset\s*=\s*([^;\s]+)",
                    values.get("content", ""),
                    flags=re.IGNORECASE,
                )
                if match:
                    declared_charset = match.group(1).strip("'\"")
            if "charset" in values or declared_charset:
                line, column = self.getpos()
                self.charset_declarations.append(
                    (
                        declared_charset,
                        line,
                        column,
                        self.get_starttag_text() or "",
                        self._in_head,
                    )
                )
                if len(self.charset_declarations) == 1:
                    self.charset = declared_charset
            if values.get("name", "").lower() == "viewport":
                self.viewport = values.get("content", "").strip()
            if http_equiv == "refresh":
                match = re.search(
                    r"\burl\s*=\s*([^;]+)",
                    values.get("content", ""),
                    flags=re.IGNORECASE,
                )
                if match:
                    self._record_resource(
                        "meta",
                        "refresh",
                        match.group(1).strip("'\" "),
                        allow_data=False,
                    )

        if tag == "style":
            self.has_style = True
            self._style_depth += 1
        elif tag == "script":
            self._script_depth += 1

        if tag == "img" and "alt" not in attr_names:
            self.images_without_alt += 1

        if tag == "svg":
            if self._svg_depth == 0:
                role = values.get("role", "").lower()
                self._svg_hidden = values.get(
                    "aria-hidden", ""
                ).lower() == "true" or role in {"none", "presentation"}
                self._svg_named = bool(values.get("aria-label", "").strip())
                self._svg_label_references = values.get("aria-labelledby", "").split()
                self._svg_title_parts = []
            self._svg_depth += 1

        for raw_key, raw_value in attrs:
            key = raw_key.lower()
            value = (raw_value or "").strip()
            if key == "style" and value:
                self._css_parts.append(value)
            if key == "src" and tag in SRC_RESOURCE_TAGS and value:
                self._record_resource(
                    tag,
                    key,
                    value,
                    allow_data=tag not in {"embed", "frame", "iframe", "script"},
                )
            elif key == "poster" and tag == "video" and value:
                self._record_resource(tag, key, value)
            elif key == "background" and tag in BACKGROUND_RESOURCE_TAGS and value:
                self._record_resource(tag, key, value)
            elif key == "srcset" and tag in {"img", "source"} and value:
                self._record_resource(tag, key, value, is_srcset=True)
            elif (
                key in {"href", "xlink:href"}
                and tag
                in {
                    "base",
                    "feimage",
                    "image",
                    "use",
                }
                and value
            ):
                self._record_resource(
                    tag,
                    key,
                    value,
                    allow_data=tag in {"feimage", "image"},
                )
            elif key == "href" and tag == "link" and value:
                rels = set(values.get("rel", "").lower().split())
                if rels.intersection(LINK_RESOURCE_RELS):
                    passive_data_rels = {"apple-touch-icon", "icon", "mask-icon"}
                    self._record_resource(
                        tag,
                        key,
                        value,
                        allow_data=bool(rels) and rels.issubset(passive_data_rels),
                    )
            elif key == "data" and tag == "object" and value:
                self._record_resource(tag, key, value, allow_data=False)
            elif key == "action" and tag == "form" and value:
                self._record_resource(tag, key, value, allow_data=False)
            elif key == "formaction" and tag in {"button", "input"} and value:
                self._record_resource(tag, key, value, allow_data=False)
            elif key == "manifest" and tag == "html" and value:
                self._record_resource(tag, key, value, allow_data=False)
            elif key == "href" and tag == "a" and "download" in attr_names and value:
                self._record_resource(tag, key, value)
            elif key == "srcdoc" and tag == "iframe" and value:
                self._scan_srcdoc(value)

        skip_started = tag in SKIP_TEXT_TAGS
        style_value = values.get("style", "")
        hidden_started = "hidden" in attr_names or _style_hides_element(style_value)
        if tag not in VOID_ELEMENTS:
            if skip_started:
                self._skip_text_depth += 1
            if hidden_started:
                self._hidden_depth += 1
            self._element_stack.append((tag, hidden_started, skip_started, element_id))
            if element_id:
                self._active_id_elements.append((tag, element_id))

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "title":
            if self._svg_title_flags:
                self._svg_title_flags.pop()
            else:
                self.in_document_title = False
        elif tag == "svg" and self._svg_depth:
            self._svg_depth -= 1
            if self._svg_depth == 0:
                has_title = bool("".join(self._svg_title_parts).strip())
                self._svg_records.append(
                    (
                        self._svg_hidden,
                        self._svg_named,
                        has_title,
                        self._svg_label_references,
                    )
                )
        elif tag == "head":
            self._in_head = False

        if tag == "style" and self._style_depth:
            self._style_depth -= 1
        elif tag == "script" and self._script_depth:
            self._script_depth -= 1

        match_index = -1
        for index in range(len(self._element_stack) - 1, -1, -1):
            if self._element_stack[index][0] == tag:
                match_index = index
                break
        if match_index >= 0:
            self._close_stack_from(match_index)

    def handle_data(self, data: str) -> None:
        if self.in_document_title:
            self.title_parts.append(data)
        if self._svg_title_flags and self._svg_title_flags[-1]:
            self._svg_title_parts.append(data)
        if self._style_depth:
            self._css_parts.append(data)
        if self._script_depth:
            self._script_parts.append(data)
        for _, element_id in self._active_id_elements:
            self._id_text_parts[element_id].append(data)
        if (
            self._in_body
            and not self._skip_text_depth
            and not self._hidden_depth
            and not self._svg_title_flags
        ):
            self._visible_text.append(data)

    def finish(self) -> None:
        if self._svg_depth:
            has_title = bool("".join(self._svg_title_parts).strip())
            self._svg_records.append(
                (
                    self._svg_hidden,
                    self._svg_named,
                    has_title,
                    self._svg_label_references,
                )
            )
            self._svg_depth = 0
        for hidden, named, has_title, references in self._svg_records:
            has_referenced_name = any(
                "".join(self._id_text_parts.get(reference, [])).strip()
                for reference in references
            )
            if not (hidden or named or has_title or has_referenced_name):
                self.svgs_without_name += 1
        self._svg_records = []

    def visible_word_count(self) -> int:
        text = " ".join(self._visible_text)
        cjk_characters = CJK_CHARACTER_RE.findall(text)
        non_cjk_text = CJK_CHARACTER_RE.sub(" ", text)
        return len(cjk_characters) + len(WORD_RE.findall(non_cjk_text))

    def all_external_resources(self) -> List[str]:
        resources = list(self.external_resources)
        css = "\n".join(self._css_parts)
        script = "\n".join(self._script_parts)
        for value in _css_external_references(css):
            item = f"css[url]={value}"
            if item not in resources:
                resources.append(item)
        for value in _script_external_references(script):
            item = f"script[import]={value}"
            if item not in resources:
                resources.append(item)
        return resources

    def has_motion_without_reduction(self) -> bool:
        css = _strip_css_comments("\n".join(self._css_parts))
        code_mask = _code_mask(css, line_comments=False)
        has_motion = bool(
            any(
                code_mask[match.start()]
                for match in re.finditer(
                    r"\b(?:animation|transition)(?:-[\w-]+)?\s*:",
                    css,
                    flags=re.IGNORECASE,
                )
            )
        )
        has_reduce_query = any(
            code_mask[match.start()]
            for match in re.finditer(
                r"\(\s*prefers-reduced-motion\s*:\s*reduce\s*\)",
                css,
                flags=re.IGNORECASE,
            )
        )
        return has_motion and not has_reduce_query


def audit(
    path: Path,
    max_words: int = DEFAULT_MAX_WORDS,
    allow_external: bool = False,
) -> CheckResult:
    if max_words < 0:
        raise ValueError("max_words must be zero or greater")

    result = CheckResult()
    if path.suffix.lower() not in {".html", ".htm"}:
        result.errors.append("file extension must be .html or .htm")
    try:
        source = path.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        result.errors.append(f"cannot read UTF-8 HTML: {exc}")
        return result

    parser = ArtifactParser()
    try:
        parser.feed(source)
        parser.close()
        parser.finish()
    except Exception as exc:  # HTMLParser can surface malformed entities.
        result.errors.append(f"HTML parsing failed: {exc}")

    if not _has_html_doctype(source):
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
    if len(parser.charset_declarations) > 1:
        result.errors.append("multiple charset declarations")
    if parser.charset_declarations:
        _, line, column, tag_text, in_head = parser.charset_declarations[0]
        if not in_head:
            result.errors.append("charset meta tag must be inside head")
        if _byte_offset(source, line, column, tag_text) > 1024:
            result.errors.append(
                "charset meta tag must end within the first 1024 bytes"
            )
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
    elif parser.body_count > 1:
        result.errors.append("multiple body elements")
    if parser.images_without_alt:
        result.errors.append(
            f"{parser.images_without_alt} image(s) missing an alt attribute"
        )
    if parser.svgs_without_name:
        result.errors.append(
            f"{parser.svgs_without_name} inline SVG(s) missing a non-empty name "
            "or decorative marker"
        )
    if parser.invalid_ids:
        result.errors.append(
            "id attributes must not contain whitespace: "
            + ", ".join(parser.invalid_ids)
        )
    if parser.duplicate_ids:
        result.errors.append(
            "duplicate id attributes: " + ", ".join(parser.duplicate_ids)
        )
    if not allow_external:
        result.errors.extend(_csp_errors(parser.csp_policies))

    result.visible_words = parser.visible_word_count()
    if max_words and result.visible_words > max_words:
        result.errors.append(
            f"{result.visible_words} visible word units, budget is {max_words}"
        )

    external_resources = parser.all_external_resources()
    if external_resources:
        message = "disallowed resource references found: " + ", ".join(
            external_resources
        )
        if allow_external:
            result.warnings.append(message)
        else:
            result.errors.append(message)

    if not parser.has_main:
        result.warnings.append("missing main landmark")
    if not parser.has_heading:
        result.warnings.append("missing heading element")
    if parser.has_motion_without_reduction():
        result.warnings.append("motion styles found without prefers-reduced-motion")
    return result


def check(
    path: Path,
    max_words: int = DEFAULT_MAX_WORDS,
    allow_external: bool = False,
) -> List[str]:
    """Return only blocking errors for simple callers."""

    return audit(
        path,
        max_words=max_words,
        allow_external=allow_external,
    ).errors


def _non_negative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be zero or greater")
    return parsed


def _configure_output_streams() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(errors="backslashreplace")


def main() -> int:
    _configure_output_streams()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("html_file", type=Path)
    parser.add_argument(
        "--max-words",
        type=_non_negative_int,
        default=DEFAULT_MAX_WORDS,
        help=f"visible word-unit budget (default {DEFAULT_MAX_WORDS}; 0 disables)",
    )
    parser.add_argument(
        "--allow-external",
        "--allow-network",
        action="store_true",
        dest="allow_external",
        help="Allow external resource references but report them as warnings.",
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
    result = audit(
        args.html_file,
        max_words=args.max_words,
        allow_external=args.allow_external,
    )
    passed = result.content_ok and not (args.strict and result.warnings)

    if args.json_output:
        print(
            json.dumps(
                {
                    "file": str(args.html_file),
                    "ok": passed,
                    "contentOk": result.content_ok,
                    "strict": args.strict,
                    "errors": result.errors,
                    "warnings": result.warnings,
                    "visibleWords": result.visible_words,
                    "maxWords": args.max_words,
                },
                ensure_ascii=True,
                indent=2,
            )
        )
    else:
        for warning in result.warnings:
            print(f"WARNING: {warning}", file=sys.stderr)
        for error in result.errors:
            print(f"ERROR: {error}", file=sys.stderr)
        if passed:
            print(
                f"OK: {args.html_file} is a valid ELI5 HTML artifact "
                f"({result.visible_words} visible word units)"
            )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
