#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Render approved data into a safe minimal HTML report.

This is a validation-friendly fallback renderer. The production H5 layout still
uses `templates/daily_report_template_v2.html`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

try:
    from .render_utils import safe_link_attrs, safe_text, safe_url
except ImportError:
    from render_utils import safe_link_attrs, safe_text, safe_url


EMPTY_SECTION_TEXT = "经五轮检索，本周期暂无相关新信息收录。"


SECTION_TITLES = {
    "news": "行业热点新闻",
    "research": "最新研究成果",
    "funding": "融资与投资动态",
    "policy": "政策与监管",
    "events": "行业活动预告",
}


def _items_for_type(items: Iterable[dict[str, Any]], item_type: str) -> list[dict[str, Any]]:
    return [item for item in items if item.get("type") == item_type]


def render_item_card(item: dict[str, Any]) -> str:
    """Render one approved item card with escaped text and validated URL."""
    title = safe_text(item.get("title", ""))
    source = safe_text(item.get("source", ""))
    date = safe_text(item.get("date", ""))
    summary = safe_text(item.get("summary", ""))
    url = safe_url(str(item.get("url", "")))
    attrs = safe_link_attrs()
    return (
        '<div class="card">'
        '<div class="card-header">'
        f'<div class="card-title">{title}</div>'
        f'<span class="card-tag">{safe_text(item.get("type", ""))}</span>'
        '</div>'
        f'<div class="card-meta"><span>{source}</span><span>{date}</span></div>'
        f'<div class="card-summary">{summary}</div>'
        f'<a href="{url}" {attrs} class="card-link">查看详情</a>'
        '</div>'
    )


def render_section(items: list[dict[str, Any]], item_type: str) -> str:
    """Render a typed section, preserving an explicit empty-state marker."""
    section_title = safe_text(SECTION_TITLES[item_type])
    typed_items = _items_for_type(items, item_type)
    if not typed_items:
        body = f'<p class="empty-section">{safe_text(EMPTY_SECTION_TEXT)}</p>'
    else:
        body = "\n".join(render_item_card(item) for item in typed_items)
    return f'<section class="content-section" data-section="{item_type}"><h2>{section_title}</h2>{body}</section>'


def render_report_html(items: list[dict[str, Any]], date_str: str) -> str:
    """Render a minimal safe HTML report from approved items."""
    sections = "\n".join(render_section(items, item_type) for item_type in SECTION_TITLES)
    return (
        "<!doctype html>\n"
        '<html lang="zh-CN"><head><meta charset="utf-8">'
        f"<title>合成生物行业日报 - {safe_text(date_str)}</title></head><body>"
        f"<h1>合成生物行业日报 - {safe_text(date_str)}</h1>"
        f"<p><strong>流水线追踪</strong>：approved={len(items)}</p>"
        f"{sections}</body></html>"
    )


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Render safe minimal HTML report from approved JSON")
    parser.add_argument("--approved", required=True)
    parser.add_argument("--date", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    with open(args.approved, "r", encoding="utf-8") as f:
        items = json.load(f)
    html = render_report_html(items, args.date)
    Path(args.output).write_text(html, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
