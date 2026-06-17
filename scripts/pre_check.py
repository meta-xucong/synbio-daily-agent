#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AS hub NEWs agent - 预检查脚本
生成报告前的强制检查，确保前置条件已满足
"""

import json
try:
    from .settings import DATA_DIR, date_str as current_date_str
    from .console_utils import ensure_utf8_console
    from .report_pipeline import validate_search_log
except ImportError:
    from settings import DATA_DIR, date_str as current_date_str
    from console_utils import ensure_utf8_console
    from report_pipeline import validate_search_log

ensure_utf8_console()


def pre_check(date_str: str) -> dict:
    """生成报告前的强制检查"""
    errors = []
    warnings = []
    
    # 检查1: 原始数据存在
    raw_path = DATA_DIR / f"raw_{date_str}.json"
    raw_data = None
    if not raw_path.exists():
        errors.append(f"❌ 原始数据不存在: {raw_path}")
    else:
        try:
            with open(raw_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            raw_data = data
            total_items = 0
            for cat in ["news", "research", "funding", "policy", "events"]:
                if cat not in data:
                    warnings.append(f"⚠️ 原始数据缺少 {cat} 类别")
                else:
                    total_items += len(data.get(cat, []))
            if total_items == 0:
                errors.append(f"❌ 原始数据为空: {raw_path}")
            else:
                print(f"✅ 原始数据已保存: {total_items} 条信息")
        except Exception as e:
            errors.append(f"❌ 原始数据JSON格式错误: {raw_path} ({e})")

    # 检查1.5: 搜索日志存在且覆盖五轮搜索
    search_log_path = DATA_DIR / f"search_log_{date_str}.json"
    if not search_log_path.exists():
        errors.append(f"❌ 搜索日志不存在: {search_log_path} → 必须记录五轮搜索query和采集证据")
    else:
        try:
            with open(search_log_path, 'r', encoding='utf-8') as f:
                search_log = json.load(f)
            search_log_result = validate_search_log(search_log, raw_data)
            if not search_log_result["is_valid"]:
                errors.extend([f"❌ 搜索日志不合规: {e}" for e in search_log_result["errors"]])
            else:
                print(
                    "✅ 搜索日志已保存: "
                    f"{len(search_log_result['rounds_seen'])} 轮, "
                    f"{search_log_result['total_queries']} 个query"
                )
            warnings.extend([f"⚠️ 搜索日志提示: {w}" for w in search_log_result["warnings"]])
        except Exception as e:
            errors.append(f"❌ 搜索日志JSON格式错误: {search_log_path} ({e})")
    
    # 检查2: 脚本处理结果存在
    approved_path = DATA_DIR / f"approved_{date_str}.json"
    if not approved_path.exists():
        errors.append(f"❌ approved数据不存在: {approved_path} → 必须先调用report_pipeline.py")
    else:
        try:
            with open(approved_path, 'r', encoding='utf-8') as f:
                approved = json.load(f)
            print(f"✅ approved数据已保存: {len(approved)} 条信息")
        except Exception as e:
            errors.append(f"❌ approved数据格式错误: {approved_path} ({e})")
    
    # 检查3: 各类别处理结果存在（可选，因为 process_raw_data 需要 --output 才保存）
    missing_proc = []
    for cat in ["news", "research", "funding", "policy", "events"]:
        proc_path = DATA_DIR / f"processed_{cat}_{date_str}.json"
        if not proc_path.exists():
            missing_proc.append(cat)
    
    if missing_proc:
        warnings.append(f"⚠️ 部分类别未保存处理结果: {', '.join(missing_proc)}。如已调用 report_pipeline.py 但无输出，可忽略此警告")
    
    can_proceed = len(errors) == 0
    
    print(f"\n{'='*50}")
    if can_proceed:
        print("✅ 预检查通过，可以生成报告")
    else:
        print(f"❌ 预检查未通过，发现 {len(errors)} 个错误:")
        for e in errors:
            print(f"  {e}")
    
    if warnings:
        print(f"\n⚠️ 警告 ({len(warnings)}条):")
        for w in warnings:
            print(f"  {w}")
    
    return {
        "can_proceed": can_proceed,
        "errors": errors,
        "warnings": warnings,
    }


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        date_str = sys.argv[1]
    else:
        date_str = current_date_str()
    
    result = pre_check(date_str)
    sys.exit(0 if result["can_proceed"] else 1)
