#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Generate production H5 and email HTML from the approved template."""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    from .console_utils import ensure_utf8_console
    from .html_safety import validate_html_safety
    from .render_utils import safe_link_attrs, safe_text, safe_url
    from .report_pipeline import extract_http_urls, validate_urls_against_approved
    from .settings import REPORTS_DIR, TEMPLATES_DIR, now_local
except ImportError:
    from console_utils import ensure_utf8_console
    from html_safety import validate_html_safety
    from render_utils import safe_link_attrs, safe_text, safe_url
    from report_pipeline import extract_http_urls, validate_urls_against_approved
    from settings import REPORTS_DIR, TEMPLATES_DIR, now_local


ensure_utf8_console()

TYPE_LABELS = {
    "news": "新闻",
    "research": "研究",
    "funding": "融资",
    "policy": "政策",
    "events": "活动",
}
WEEKDAYS = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
SECTION_ORDER = ["news", "research", "funding", "policy", "events"]
EMPTY_TEXT = "经五轮检索，本周期暂无相关新信息收录。"


def parse_date(value: object) -> datetime:
    """Parse item dates for sorting; unparsable dates sort last."""
    try:
        return datetime.fromisoformat(str(value or "").strip()[:10])
    except ValueError:
        return datetime.min


def sort_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Sort approved items by date desc and value score desc."""
    return sorted(
        items,
        key=lambda item: (parse_date(item.get("date")), float(item.get("value_score") or 0)),
        reverse=True,
    )


def load_approved(path: Path) -> list[dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError(f"approved JSON must be a list: {path}")
    return data


def group_items(items: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped = {item_type: [] for item_type in SECTION_ORDER}
    for item in items:
        item_type = str(item.get("type") or "news").lower()
        grouped.setdefault(item_type, []).append(item)
    return {key: sort_items(value) for key, value in grouped.items()}


def item_url(item: dict[str, Any]) -> str:
    """Validate and escape an approved item URL."""
    return safe_url(str(item.get("url") or ""))


def render_summary(items: list[dict[str, Any]], limit: int = 5) -> str:
    selected = sort_items(items)[:limit]
    if not selected:
        return f'<li><span class="num">1</span><span class="text">{safe_text(EMPTY_TEXT)}</span></li>'

    rows = []
    for index, item in enumerate(selected, 1):
        title = safe_text(item.get("title", "未命名信息"))
        summary = safe_text(item.get("summary", ""))
        date = safe_text(item.get("date", ""))
        url = item_url(item)
        rows.append(
            f'<li><span class="num">{index}</span><span class="text">'
            f'<a href="{url}" {safe_link_attrs()}><strong>{title}</strong></a>：{summary}（{date}）'
            f"</span></li>"
        )
    return "\n".join(rows)


def empty_section(title: str) -> str:
    return (
        '<div class="content-section">'
        f'<div class="section-title">{safe_text(title)}</div>'
        f'<p style="color:#888;font-size:14px;">{safe_text(EMPTY_TEXT)}</p>'
        "</div>"
    )


def render_card_section(title: str, items: list[dict[str, Any]], tag: str, limit: int | None = None) -> str:
    selected = items[:limit] if limit else items
    if not selected:
        return empty_section(title)

    cards = []
    for item in selected:
        url = item_url(item)
        cards.append(
            '<div class="card">'
            '<div class="card-header">'
            f'<div class="card-title">{safe_text(item.get("title", "未命名信息"))}</div>'
            f'<span class="card-tag">{safe_text(tag)}</span>'
            "</div>"
            '<div class="card-meta">'
            f'<span>📰 {safe_text(item.get("source", "未知来源"))}</span>'
            f'<span>📅 {safe_text(item.get("date", ""))}</span>'
            "</div>"
            f'<div class="card-summary">{safe_text(item.get("summary", ""))}</div>'
            f'<a href="{url}" {safe_link_attrs()} class="card-link">查看详情</a>'
            "</div>"
        )
    return (
        '<div class="content-section">'
        f'<div class="section-title">{safe_text(title)}</div>'
        + "\n".join(cards)
        + "</div>"
    )


def render_funding_section(items: list[dict[str, Any]], limit: int | None = None) -> str:
    selected = items[:limit] if limit else items
    if not selected:
        return empty_section("💰 融资与投资动态")

    rows = []
    for item in selected:
        url = item_url(item)
        company = item.get("company") or item.get("title") or "未命名公司"
        rows.append(
            "<tr>"
            f"<td><strong>{safe_text(company)}</strong></td>"
            f"<td>{safe_text(item.get('round', ''))}</td>"
            f"<td>{safe_text(item.get('amount', ''))}</td>"
            f"<td>{safe_text(item.get('investor', ''))}</td>"
            f"<td>{safe_text(item.get('date', ''))}</td>"
            f'<td><a href="{url}" {safe_link_attrs()}>查看</a></td>'
            "</tr>"
        )
    return (
        '<div class="content-section">'
        '<div class="section-title">💰 融资与投资动态</div>'
        '<table class="data-table">'
        "<tr><th>公司</th><th>轮次</th><th>金额</th><th>投资方</th><th>时间</th><th>详情</th></tr>"
        + "\n".join(rows)
        + "</table></div>"
    )


def render_events_section(items: list[dict[str, Any]], limit: int | None = None) -> str:
    selected = items[:limit] if limit else items
    if not selected:
        return empty_section("📅 行业活动预告")

    rows = []
    for item in selected:
        url = item_url(item)
        rows.append(
            "<tr>"
            f"<td><strong>{safe_text(item.get('title', '未命名活动'))}</strong></td>"
            f"<td>{safe_text(item.get('date', ''))}</td>"
            f"<td>{safe_text(item.get('location', ''))}</td>"
            f"<td>{safe_text(item.get('summary', ''))}</td>"
            f'<td><a href="{url}" {safe_link_attrs()}>查看</a></td>'
            "</tr>"
        )
    return (
        '<div class="content-section">'
        '<div class="section-title">📅 行业活动预告</div>'
        '<table class="data-table">'
        "<tr><th>活动名称</th><th>时间</th><th>地点</th><th>核心看点</th><th>详情</th></tr>"
        + "\n".join(rows)
        + "</table></div>"
    )


def extract_ai_analysis(markdown: str) -> str:
    match = re.search(r"## 🤖 AI 深度分析\n\n(.*?)(?=\n## |\Z)", markdown, re.DOTALL)
    return match.group(1).strip() if match else ""


def render_text_lines(text: str) -> str:
    parts = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith(("- ", "* ")):
            parts.append(f"<li>{safe_text(line[2:].strip())}</li>")
        else:
            parts.append(f"<p>{safe_text(line)}</p>")
    if any(part.startswith("<li>") for part in parts):
        list_items = "".join(part for part in parts if part.startswith("<li>"))
        paras = "".join(part for part in parts if not part.startswith("<li>"))
        return paras + f"<ul>{list_items}</ul>"
    return "".join(parts)


def render_analysis(markdown: str, email: bool = False) -> str:
    analysis = extract_ai_analysis(markdown)
    if not analysis:
        return empty_section("🤖 AI 深度分析")

    blocks = []
    sections = re.split(r"\n###\s+", "\n" + analysis)
    for section in sections:
        section = section.strip()
        if not section:
            continue
        lines = section.splitlines()
        heading = lines[0].strip("# ").strip()
        body = "\n".join(lines[1:]).strip()
        if not body:
            continue
        if email and len(blocks) >= 3:
            break
        content = render_text_lines(body)
        if "风险" in heading:
            blocks.append(f'<div class="risk-box"><h4>⚠️ {safe_text(heading)}</h4>{content}</div>')
        else:
            blocks.append(f'<div class="analysis-block"><h4>{safe_text(heading)}</h4>{content}</div>')

    return (
        '<div class="content-section">'
        '<div class="section-title">🤖 AI 深度分析</div>'
        + "\n".join(blocks or [f"<p>{safe_text(EMPTY_TEXT)}</p>"])
        + "</div>"
    )


def render_appendix(items: list[dict[str, Any]], limit: int | None = None) -> str:
    selected = sort_items(items)
    selected = selected[:limit] if limit else selected
    if not selected:
        return empty_section("📎 附录：完整链接列表")

    rows = []
    for index, item in enumerate(selected, 1):
        url = item_url(item)
        rows.append(
            "<tr>"
            f"<td>{index}</td>"
            f"<td>{safe_text(item.get('title', '未命名信息'))}</td>"
            f'<td><a href="{url}" {safe_link_attrs()}>点击查看</a></td>'
            "</tr>"
        )
    return (
        '<div class="content-section">'
        '<div class="section-title">📎 附录：完整链接列表</div>'
        '<table class="data-table">'
        "<tr><th>序号</th><th>信息标题</th><th>来源链接</th></tr>"
        + "\n".join(rows)
        + "</table></div>"
    )


def render_template(
    approved: list[dict[str, Any]],
    markdown: str,
    report_date: str,
    email: bool = False,
) -> str:
    template = (TEMPLATES_DIR / "daily_report_template_v2.html").read_text(encoding="utf-8")
    grouped = group_items(approved)
    display_dt = parse_date(report_date)
    now = now_local()
    section_limit = 2 if email else None
    appendix_limit = 5 if email else None

    replacements = {
        "{{DATE}}": safe_text(report_date),
        "{{DATE_FULL}}": safe_text(f"{display_dt.year}年{display_dt.month}月{display_dt.day}日"),
        "{{DATE_FILE}}": safe_text(report_date),
        "{{WEEKDAY}}": safe_text(WEEKDAYS[display_dt.weekday()] if display_dt != datetime.min else ""),
        "{{GEN_TIME}}": safe_text(now.strftime("%H:%M")),
        "{{GEN_TIME_FULL}}": safe_text(now.strftime("%Y-%m-%d %H:%M:%S")),
        "{{SUMMARY_ITEMS}}": render_summary(approved, limit=5),
        "{{NEWS_SECTION}}": render_card_section("📰 行业热点新闻", grouped.get("news", []), TYPE_LABELS["news"], section_limit),
        "{{RESEARCH_SECTION}}": render_card_section("🔬 最新研究成果", grouped.get("research", []), TYPE_LABELS["research"], section_limit),
        "{{FUNDING_SECTION}}": render_funding_section(grouped.get("funding", []), section_limit),
        "{{POLICY_SECTION}}": render_card_section("🏛️ 政策与监管", grouped.get("policy", []), TYPE_LABELS["policy"], section_limit),
        "{{EVENTS_SECTION}}": render_events_section(grouped.get("events", []), section_limit),
        "{{ANALYSIS_SECTION}}": render_analysis(markdown, email=email),
        "{{APPENDIX_SECTION}}": render_appendix(approved, appendix_limit),
    }

    html = template
    for placeholder, value in replacements.items():
        html = html.replace(placeholder, value)
    if "{{" in html or "}}" in html:
        raise ValueError("template placeholders remain after rendering")
    return html


def validate_generated_html(html: str, approved: list[dict[str, Any]], label: str) -> None:
    safety = validate_html_safety(html)
    if not safety["is_safe"]:
        raise ValueError(f"{label} HTML safety failed: {safety['errors']}")
    consistency = validate_urls_against_approved(extract_http_urls(html), approved, label=label)
    if not consistency["is_consistent"]:
        raise ValueError(f"{label} URL consistency failed: {consistency['errors']}")


def generate(
    report_date: str,
    approved_path: Path,
    markdown_path: Path,
    html_output: Path,
    email_output: Path,
) -> dict[str, Path]:
    approved = load_approved(approved_path)
    markdown = markdown_path.read_text(encoding="utf-8")
    html = render_template(approved, markdown, report_date, email=False)
    email_html = render_template(approved, markdown, report_date, email=True)

    validate_generated_html(html, approved, "H5")
    validate_generated_html(email_html, approved, "邮件HTML")

    html_output.parent.mkdir(parents=True, exist_ok=True)
    email_output.parent.mkdir(parents=True, exist_ok=True)
    html_output.write_text(html, encoding="utf-8")
    email_output.write_text(email_html, encoding="utf-8")
    return {"html": html_output, "email": email_output}


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate production H5 and email HTML from approved data")
    parser.add_argument("--date", required=True)
    parser.add_argument("--approved", required=True)
    parser.add_argument("--markdown", required=True)
    parser.add_argument("--html-output")
    parser.add_argument("--email-output")
    args = parser.parse_args()

    report_date = args.date
    html_output = Path(args.html_output) if args.html_output else REPORTS_DIR / f"synbio_daily_{report_date}.html"
    email_output = Path(args.email_output) if args.email_output else REPORTS_DIR / f"email_{report_date}.html"
    outputs = generate(
        report_date=report_date,
        approved_path=Path(args.approved),
        markdown_path=Path(args.markdown),
        html_output=html_output,
        email_output=email_output,
    )
    print(f"生产H5已生成: {outputs['html']}")
    print(f"邮件HTML已生成: {outputs['email']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
