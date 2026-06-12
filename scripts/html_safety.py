#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""HTML safety checks for generated reports and email bodies."""

from __future__ import annotations

import re
from html import unescape
from html.parser import HTMLParser
from typing import Any

try:
    from .render_utils import safe_url
except ImportError:
    from render_utils import safe_url


FORBIDDEN_HTML_PATTERNS = [
    (r"<\s*script\b", "script tag"),
    (r"javascript\s*:", "javascript URL"),
    (r"data\s*:", "data URL"),
    (r"\son[a-z]+\s*=", "inline event handler"),
    (r"<\s*iframe\b", "iframe tag"),
    (r"<\s*object\b", "object tag"),
    (r"<\s*embed\b", "embed tag"),
]
URL_ATTRS = {"href", "src", "action", "formaction", "poster"}


class LinkSafetyParser(HTMLParser):
    """Collect unsafe parsed link and URL attribute behavior."""

    def __init__(self) -> None:
        super().__init__()
        self.errors: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = {name.lower(): (value or "") for name, value in attrs}
        for name, value in attr_map.items():
            if name in URL_ATTRS and value:
                decoded = unescape(value)
                try:
                    safe_url(decoded)
                except ValueError:
                    self.errors.append(f"unsafe URL attribute {name}={value!r}")
        if attr_map.get("target", "").lower() == "_blank":
            rel_values = set(attr_map.get("rel", "").lower().split())
            if not {"noopener", "noreferrer"}.issubset(rel_values):
                self.errors.append("target=_blank link missing rel=\"noopener noreferrer\"")


def validate_html_safety(html: str) -> dict[str, Any]:
    """Reject active HTML content and unsafe new-window links."""
    errors: list[str] = []
    for pattern, label in FORBIDDEN_HTML_PATTERNS:
        if re.search(pattern, html, re.IGNORECASE):
            errors.append(f"HTML contains unsafe pattern: {label}")

    parser = LinkSafetyParser()
    parser.feed(html)
    errors.extend(parser.errors)

    return {
        "is_safe": len(errors) == 0,
        "errors": errors,
    }
