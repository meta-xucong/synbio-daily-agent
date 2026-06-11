#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Safe rendering helpers for HTML and email output."""

from __future__ import annotations

from html import escape
from urllib.parse import urlparse


ALLOWED_URL_SCHEMES = {"http", "https"}


def safe_text(value: object) -> str:
    """Escape external text before inserting it into HTML."""
    return escape(str(value or ""), quote=True)


def safe_url(url: str) -> str:
    """Validate a URL for HTML/email links."""
    parsed = urlparse(url or "")
    if parsed.scheme not in ALLOWED_URL_SCHEMES or not parsed.netloc:
        raise ValueError(f"unsafe url: {url!r}")
    return url


def safe_link_attrs() -> str:
    """Return standard external-link attributes."""
    return 'target="_blank" rel="noopener noreferrer"'
