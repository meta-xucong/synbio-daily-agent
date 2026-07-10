#!/usr/bin/env python3
"""Stable article URL identities shared by search, review, and send gates."""

from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


TRACKING_QUERY_PREFIXES = ("utm_",)
TRACKING_QUERY_KEYS = {
    "fbclid", "gclid", "mc_cid", "mc_eid", "igshid", "spm", "from", "ref",
}


def canonicalize_url(url: str) -> str:
    """Normalize a URL without dropping parameters that identify an article."""
    raw_url = str(url or "").strip()
    if not raw_url:
        return ""
    try:
        parts = urlsplit(raw_url)
    except ValueError:
        return raw_url

    query_pairs = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key.lower() not in TRACKING_QUERY_KEYS
        and not key.lower().startswith(TRACKING_QUERY_PREFIXES)
    ]
    # Query order is not meaningful for the article URLs we compare, while a
    # stable order lets equivalent provider links share one identity.
    query_pairs.sort(key=lambda pair: (pair[0].lower(), pair[1]))
    path = re.sub(r"/{2,}", "/", parts.path or "/")
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, urlencode(query_pairs, doseq=True), ""))


def url_dedup_key(url: str) -> str:
    """Return a durable article identity while retaining semantic query IDs."""
    canonical = canonicalize_url(url)
    if not canonical:
        return ""
    try:
        parts = urlsplit(canonical)
    except ValueError:
        return ""

    hostname = (parts.hostname or "").lower()
    if hostname.startswith("www."):
        hostname = hostname[4:]
    if not hostname:
        return ""
    path = (parts.path or "/").rstrip("/") or "/"

    if hostname.endswith("36kr.com"):
        match = re.search(r"/p/(\d+)", path)
        if match:
            return f"36kr:p:{match.group(1)}"

    if hostname == "mp.weixin.qq.com":
        params = dict(parse_qsl(parts.query, keep_blank_values=True))
        biz = params.get("__biz") or params.get("biz")
        mid = params.get("mid")
        if biz and mid:
            return f"weixin:{biz}:{mid}"

    query = f"?{parts.query}" if parts.query else ""
    return f"{hostname}{path}{query}"
