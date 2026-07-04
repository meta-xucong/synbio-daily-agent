#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Safe rendering helpers for HTML and email output."""

from __future__ import annotations

import re
from html import escape
from urllib.parse import urlsplit, urlunsplit


ALLOWED_URL_SCHEMES = {"http", "https"}
FORBIDDEN_URL_CHARS = re.compile(r"[\s\"'<>`\\\x00-\x1f\x7f]")


def safe_text(value: object) -> str:
    """Escape external text before inserting it into HTML."""
    return escape(str(value or ""), quote=True)


def truncate_summary(value: object, max_length: int = 300) -> str:
    """Truncate long summaries for H5/email display without breaking HTML."""
    text = str(value or "").strip()
    if len(text) <= max_length:
        return text
    return text[: max_length - 1].rstrip() + "…"


def safe_url(url: str) -> str:
    """Validate a URL for HTML/email links."""
    value = str(url or "").strip()
    if FORBIDDEN_URL_CHARS.search(value):
        raise ValueError(f"unsafe url: {url!r}")

    parsed = urlsplit(value)
    if parsed.scheme.lower() not in ALLOWED_URL_SCHEMES or not parsed.netloc:
        raise ValueError(f"unsafe url: {url!r}")
    return escape(urlunsplit(parsed), quote=True)


def safe_link_attrs() -> str:
    """Return standard external-link attributes."""
    return 'target="_blank" rel="noopener noreferrer"'
