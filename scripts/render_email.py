#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Render safe email HTML from approved data."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

try:
    from .render_utils import safe_link_attrs, safe_text, safe_url
except ImportError:
    from render_utils import safe_link_attrs, safe_text, safe_url


def render_email_html(items: list[dict[str, Any]], date_str: str, limit: int = 5) -> str:
    """Render a concise email body from approved items."""
    rows = []
    attrs = safe_link_attrs()
    for index, item in enumerate(items[:limit], 1):
        title = safe_text(item.get("title", ""))
        summary = safe_text(item.get("summary", ""))
        url = safe_url(str(item.get("url", "")))
        rows.append(
            f'<li><span class="num">{index}</span> '
            f'<a href="{url}" {attrs}><strong>{title}</strong></a>'
            f'<p>{summary}</p></li>'
        )
    if not rows:
        rows.append('<li>经五轮检索，本周期暂无相关新信息收录。</li>')
    return (
        '<!doctype html><html lang="zh-CN"><body>'
        f"<h1>合成生物行业日报 - {safe_text(date_str)}</h1>"
        '<ul class="summary-list">'
        + "\n".join(rows)
        + "</ul></body></html>"
    )


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Render safe email body from approved JSON")
    parser.add_argument("--approved", required=True)
    parser.add_argument("--date", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    with open(args.approved, "r", encoding="utf-8") as f:
        items = json.load(f)
    html = render_email_html(items, args.date)
    Path(args.output).write_text(html, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
