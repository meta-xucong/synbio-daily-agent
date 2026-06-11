#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AS hub NEWs agent - 报告后检查脚本
报告生成后的强制检查，确保报告只包含approved信息
"""

import json
import re
from pathlib import Path

BASE_DIR = Path(r"D:\AI\合成生物行业报告")
DATA_DIR = BASE_DIR / "data"
REPORTS_DIR = BASE_DIR / "reports"


def post_check(date_str: str) -> dict:
    """报告生成后的强制检查"""
    errors = []
    warnings = []
    
    report_path = REPORTS_DIR / f"{date_str}.md"
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
    
    # 检查1: 报告中的每个链接都在approved中
    report_links = set(re.findall(r'https?://[^\s\)]+', report))
    approved_links = set()
    for item in approved:
        approved_links.add(item.get("url", ""))
        approved_links.update(item.get("urls", []))
    
    extra_links = report_links - approved_links
    # 排除占位链接和常见非信息链接
    excluded_patterns = ["example", "placeholder", "template", "demo", "test"]
    extra_links = {l for l in extra_links if not any(p in l.lower() for p in excluded_patterns)}
    if extra_links:
        errors.append(f"❌ 报告包含未approved的链接: {extra_links}")
    
    # 检查2: approved中的每个信息都在报告中体现
    for item in approved:
        title = item.get("title", "")
        # 检查标题或标题前30字是否在报告中
        if title not in report and title[:30] not in report:
            warnings.append(f"⚠️ approved信息可能未在报告中体现: {title[:50]}")
    
    # 检查3: 报告头部是否有流水线追踪标记
    if "流水线追踪" not in report and "approved=" not in report:
        warnings.append("⚠️ 报告缺少流水线追踪标记")
    
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
    from datetime import datetime
    
    if len(sys.argv) > 1:
        date_str = sys.argv[1]
    else:
        date_str = datetime.now().strftime("%Y-%m-%d")
    
    result = post_check(date_str)
    sys.exit(0 if result["can_send"] else 1)
