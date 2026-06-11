#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AS hub NEWs agent - 预检查脚本
生成报告前的强制检查，确保前置条件已满足
"""

import json
from pathlib import Path
from datetime import datetime

BASE_DIR = Path(r"D:\AI\合成生物行业报告")
DATA_DIR = BASE_DIR / "data"


def pre_check(date_str: str) -> dict:
    """生成报告前的强制检查"""
    errors = []
    warnings = []
    
    # 检查1: 原始数据存在
    raw_path = DATA_DIR / f"raw_{date_str}.json"
    if not raw_path.exists():
        errors.append(f"❌ 原始数据不存在: {raw_path}")
    else:
        try:
            with open(raw_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
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
    
    # 检查3: 各类别处理结果存在
    for cat in ["news", "research", "funding", "policy", "events"]:
        proc_path = DATA_DIR / f"processed_{cat}_{date_str}.json"
        if not proc_path.exists():
            errors.append(f"❌ 处理结果不存在: {proc_path} → 必须先调用report_pipeline.py")
    
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
        date_str = datetime.now().strftime("%Y-%m-%d")
    
    result = pre_check(date_str)
    sys.exit(0 if result["can_proceed"] else 1)
