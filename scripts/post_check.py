#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AS hub NEWs agent - 报告后检查脚本
报告生成后的强制检查，确保报告只包含approved信息
"""

import json
import re
from pathlib import Path

try:
    from .settings import DATA_DIR, REPORTS_DIR, date_str as current_date_str
    from .console_utils import ensure_utf8_console
except ImportError:
    from settings import DATA_DIR, REPORTS_DIR, date_str as current_date_str
    from console_utils import ensure_utf8_console

ensure_utf8_console()


def _coerce_url_list(value):
    if not value:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(url or "") for url in value if url]
    return []


def _extract_report_links(report: str) -> set[str]:
    links = []
    for match in re.finditer(r"https?://[^\s<>\]\)\"']+", report or ""):
        links.append(match.group(0).rstrip(".,;，。；）)]"))
    return set(links)


def post_check(date_str: str, report_path: str = None) -> dict:
    """报告生成后的强制检查
    
    Args:
        date_str: 日期字符串
        report_path: 报告文件路径（可选，默认使用 REPORTS_DIR/{date_str}.md）
    """
    errors = []
    warnings = []
    
    if report_path is None:
        report_dir_report = REPORTS_DIR / date_str / "report.md"
        legacy_report = REPORTS_DIR / f"{date_str}.md"
        report_path = report_dir_report if report_dir_report.exists() else legacy_report
    else:
        report_path = Path(report_path)
    
    approved_path = DATA_DIR / f"approved_{date_str}.json"
    
    if not report_path.exists():
        errors.append(f"❌ 报告不存在: {report_path}")
        return {"can_send": False, "errors": errors, "warnings": warnings}
    
    if not approved_path.exists():
        errors.append(f"❌ approved数据不存在: {approved_path}")
        return {"can_send": False, "errors": errors, "warnings": warnings}
    
    # 读取报告和approved数据
    with open(report_path, 'r', encoding='utf-8') as f:
        report = f.read()
    with open(approved_path, 'r', encoding='utf-8') as f:
        approved = json.load(f)
    if not isinstance(approved, list):
        errors.append("❌ approved数据格式错误：必须是列表")
        approved = []
    if not approved:
        errors.append("❌ approved为空：本次没有任何可发送信息，禁止发送空日报")
    
    # 检查1: 报告中的每个链接都在approved中
    report_links = _extract_report_links(report)
    approved_links = set()
    for item in approved:
        approved_links.add(item.get("url", ""))
        approved_links.update(_coerce_url_list(item.get("urls", [])))
    
    extra_links = report_links - approved_links
    # 排除占位链接和常见非信息链接
    excluded_patterns = ["example", "placeholder", "template", "demo", "test"]
    extra_links = {l for l in extra_links if not any(p in l.lower() for p in excluded_patterns)}
    if extra_links and approved:
        errors.append(f"❌ 报告包含未approved的链接: {extra_links}")
    
    # 检查2: approved中的每个信息都在报告中体现
    for item in approved:
        title = item.get("title", "")
        escaped_title = title.replace("|", r"\|")
        # 检查标题或标题前30字是否在报告中
        if (
            title not in report
            and title[:30] not in report
            and escaped_title not in report
            and escaped_title[:30] not in report
        ):
            errors.append(f"❌ approved信息未在报告中体现: {title[:50]}")
    
    # 检查3: 报告头部是否有流水线追踪标记
    if "流水线追踪" not in report and "approved=" not in report:
        errors.append("❌ 报告缺少流水线追踪标记")
    
    can_send = len(errors) == 0
    
    print(f"\n{'='*50}")
    print(f"报告后检查结果:")
    print(f"  报告路径: {report_path}")
    print(f"  approved信息: {len(approved)} 条")
    print(f"  报告中的链接: {len(report_links)} 个")
    print(f"  approved中的链接: {len(approved_links)} 个")
    
    if can_send:
        print("✅ 报告后检查通过，可以发送邮件")
    else:
        print(f"❌ 报告后检查未通过，发现 {len(errors)} 个错误:")
        for e in errors:
            print(f"  {e}")
    
    if warnings:
        print(f"\n⚠️ 警告 ({len(warnings)}条):")
        for w in warnings:
            print(f"  {w}")
    
    return {
        "can_send": can_send,
        "errors": errors,
        "warnings": warnings,
    }


if __name__ == "__main__":
    import sys
    
    report_path = None
    if len(sys.argv) > 1:
        date_str = sys.argv[1]
        if len(sys.argv) > 2:
            report_path = sys.argv[2]
    else:
        date_str = current_date_str()
    
    result = post_check(date_str, report_path)
    sys.exit(0 if result["can_send"] else 1)
