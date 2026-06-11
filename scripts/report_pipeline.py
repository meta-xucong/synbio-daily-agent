#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AS hub NEWs agent - Report Pipeline
合成生物行业日报 - 自动化流水线脚本

功能：
1. 历史事件指纹提取与去重
2. 时效性过滤
3. 信息聚合与价值排序
4. 报告格式验证
5. 合规复检与迭代修正

作者：Kimi Work Auto-Generated
版本：v1.0
"""

import json
import os
import re
import hashlib
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Any, Tuple, Optional
import glob

# ==================== 配置常量 ====================

BASE_DIR = Path(r"D:\AI\合成生物行业报告")
REPORTS_DIR = BASE_DIR / "reports"
CONFIG_DIR = BASE_DIR / "config"
DATA_DIR = BASE_DIR / "data"
TEMPLATES_DIR = BASE_DIR / "templates"

# 时间窗口配置（天）
TIME_WINDOWS = {
    "news": 7,
    "research": 14,
    "policy": 30,
    "events": 90,  # 未来90天
    "funding": 7,
}

# 板块名称映射
SECTION_MAP = {
    "执行摘要": "summary",
    "行业热点新闻": "news",
    "最新研究成果": "research",
    "融资与投资动态": "funding",
    "政策与监管": "policy",
    "行业活动预告": "events",
    "AI 深度分析": "analysis",
    "附录": "appendix",
}

# 价值权重配置
VALUE_WEIGHTS = {
    "multi_platform": 3,      # 多平台曝光
    "authority": 3,           # 来源权威性
    "completeness": 2,        # 信息完整性
    "timeliness": 2,          # 时效性
    "impact": 2,              # 行业影响力
}

# 权威来源分级
AUTHORITY_TIERS = {
    "tier1": ["nature", "science", "cell", "nature biotechnology", "nature communications",
              "science advances", "cell metabolism", "pnas"],
    "tier2": ["genengnews", "fiercebiotech", "synbiobeta", "36kr", "pedaily", 
              "vbdata", "bydrug.pharmcube", "stdaily", "ithome"],
    "tier3": ["bioon", "synbio-he", "sohu", "sina", "weixin"],
}

# ==================== 工具函数 ====================

def parse_date(date_str: str) -> Optional[datetime]:
    """解析各种日期格式"""
    if not date_str or date_str == "N/A":
        return None
    
    formats = [
        "%Y-%m-%d",
        "%Y-%m",
        "%Y/%m/%d",
        "%Y年%m月%d日",
        "%Y.%m.%d",
    ]
    
    for fmt in formats:
        try:
            return datetime.strptime(date_str.strip(), fmt)
        except ValueError:
            continue
    
    # 尝试从文本中提取日期
    patterns = [
        r'(\d{4})[-/](\d{1,2})[-/](\d{1,2})',
        r'(\d{4})年(\d{1,2})月(\d{1,2})日',
    ]
    for pattern in patterns:
        match = re.search(pattern, date_str)
        if match:
            try:
                y, m, d = int(match.group(1)), int(match.group(2)), int(match.group(3))
                return datetime(y, m, d)
            except:
                pass
    
    return None


def generate_fingerprint(item: Dict[str, Any]) -> str:
    """生成事件指纹，用于去重"""
    # 组合关键字段生成指纹
    company = item.get("company", "")
    title = item.get("title", "")
    event_type = item.get("type", "")
    
    # 提取核心实体（公司名、产品名、技术名）
    fingerprint_text = f"{company}|{event_type}|{title}"
    return hashlib.md5(fingerprint_text.encode('utf-8')).hexdigest()[:16]


def extract_events_from_report(report_path: str) -> List[Dict[str, Any]]:
    """从历史报告中提取已报道的事件"""
    events = []
    
    if not os.path.exists(report_path):
        return events
    
    with open(report_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 按板块分割内容，以便推断类型
    sections = re.split(r'(##\s+📰|##\s+🔬|##\s+💰|##\s+🏛️|##\s+📅)', content)
    
    current_type = "news"
    for i, section in enumerate(sections):
        # 推断当前板块类型
        if '行业热点新闻' in section:
            current_type = "news"
        elif '最新研究成果' in section:
            current_type = "research"
        elif '融资与投资动态' in section:
            current_type = "funding"
        elif '政策与监管' in section:
            current_type = "policy"
        elif '行业活动预告' in section:
            current_type = "events"
        
        # 提取表格中的事件（支持4列和5列表格）
        # 5列表格: | 标题 | 来源 | 时间 | 摘要 | 链接 |
        table_pattern_5col = r'\|([^|]+)\|([^|]+)\|([^|]+)\|([^|]+)\|([^|]+)\|'
        # 4列表格: | 标题 | 期刊/机构 | 核心发现 | 链接 |
        table_pattern_4col = r'\|([^|]+)\|([^|]+)\|([^|]+)\|([^|]+)\|'
        
        matches_5col = re.findall(table_pattern_5col, section)
        matches_4col = re.findall(table_pattern_4col, section)
        
        # 处理5列表格
        for match in matches_5col:
            if len(match) >= 5:
                title = match[0].strip()
                source = match[1].strip()
                date_str = match[2].strip()
                summary = match[3].strip()
                
                if (title and title != "标题" and not title.startswith("-") and title != "公司"
                    and not title.startswith("本周期暂无") and not title.startswith("暂无")
                    and title != "—"):
                    company = ""
                    if current_type == "funding":
                        company = title
                    
                    event = {
                        "title": title,
                        "source": source,
                        "date": date_str,
                        "summary": summary,
                        "type": current_type,
                        "company": company,
                    }
                    event["fingerprint"] = generate_fingerprint(event)
                    events.append(event)
        
        # 处理4列表格（研究成果等）
        for match in matches_4col:
            if len(match) >= 4:
                title = match[0].strip()
                source = match[1].strip()
                summary = match[2].strip()
                
                if (title and title != "标题" and not title.startswith("-")
                    and not title.startswith("本周期暂无") and not title.startswith("暂无")
                    and title != "—"):
                    event = {
                        "title": title,
                        "source": source,
                        "date": "",  # 4列表格通常没有独立日期列
                        "summary": summary,
                        "type": current_type,
                        "company": "",
                    }
                    event["fingerprint"] = generate_fingerprint(event)
                    events.append(event)
    
    return events


def load_historical_events(days: int = 7) -> Dict[str, Dict[str, Any]]:
    """加载最近N天的历史事件指纹库"""
    fingerprint_db = {}
    
    cutoff_date = datetime.now() - timedelta(days=days)
    today_str = datetime.now().strftime("%Y-%m-%d")
    
    # 查找最近N天的报告文件，排除当天报告和变体文件
    all_files = glob.glob(str(REPORTS_DIR / "*.md"))
    
    # 按日期分组，每个日期只保留标准命名文件（如 2026-06-10.md）
    date_to_file = {}
    for f in all_files:
        filename = os.path.basename(f)
        date_match = re.search(r'(\d{4}-\d{2}-\d{2})', filename)
        if not date_match:
            continue
        file_date_str = date_match.group(1)
        # 排除当天报告（防止自我去重）
        if file_date_str == today_str:
            continue
        file_date = datetime.strptime(file_date_str, "%Y-%m-%d")
        if file_date < cutoff_date:
            continue
        # 优先选择标准命名文件（不含 _revised, _full 等后缀）
        if file_date_str not in date_to_file:
            date_to_file[file_date_str] = f
        elif "_" not in filename and "_" in os.path.basename(date_to_file[file_date_str]):
            # 当前文件是标准命名，替换变体
            date_to_file[file_date_str] = f
    
    report_files = sorted(date_to_file.values(), key=os.path.getmtime, reverse=True)
    
    for report_file in report_files:
        filename = os.path.basename(report_file)
        events = extract_events_from_report(report_file)
        for event in events:
            fp = event.get("fingerprint", "")
            if fp and fp not in fingerprint_db:
                fingerprint_db[fp] = {
                    "title": event["title"],
                    "date": event.get("date", "unknown"),
                    "source_file": filename,
                    "company": event.get("company", ""),
                    "type": event.get("type", ""),
                }
    
    return fingerprint_db


def load_policy_database() -> List[Dict[str, Any]]:
    """加载已收录的政策库"""
    policy_file = CONFIG_DIR / "policy_database.json"
    
    if not policy_file.exists():
        return []
    
    try:
        with open(policy_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return data.get("policies", [])
    except:
        return []


def is_duplicate(item: Dict[str, Any], fingerprint_db: Dict[str, Any]) -> Tuple[bool, str]:
    """检查是否重复"""
    fp = generate_fingerprint(item)
    
    if fp in fingerprint_db:
        return True, f"指纹匹配: {fingerprint_db[fp]['title']} ({fingerprint_db[fp]['date']})"
    
    # 获取当前item的company和title
    company = item.get("company", "")
    title = item.get("title", "")
    event_type = item.get("type", "")
    
    for existing_fp, existing_data in fingerprint_db.items():
        existing_title = existing_data.get("title", "")
        existing_company = existing_data.get("company", "")
        existing_type = existing_data.get("type", "")
        
        # 1. company匹配：同一公司+同一类型视为重复（主要用于融资事件）
        if company and existing_company and company == existing_company:
            # 只有当双方type都明确且相同时，才判定为公司重复
            if event_type and existing_type and event_type == existing_type:
                return True, f"公司重复: {existing_title} ({existing_data['date']})"
        
        # 2. 标题相似度
        if title and existing_title:
            title_words = set(re.findall(r'[\u4e00-\u9fff]{2,}|[a-zA-Z]{3,}', title.lower()))
            existing_words = set(re.findall(r'[\u4e00-\u9fff]{2,}|[a-zA-Z]{3,}', existing_title.lower()))
            
            if len(title_words) > 0 and len(existing_words) > 0:
                overlap = len(title_words & existing_words) / max(len(title_words), len(existing_words))
                if overlap > 0.6:  # 60%关键词重叠视为重复
                    return True, f"标题相似: {existing_title} ({existing_data['date']})"
    
    return False, ""


def check_timeliness(item: Dict[str, Any], item_type: str) -> Tuple[bool, str]:
    """检查时效性"""
    date_str = item.get("date", "")
    item_date = parse_date(date_str)
    
    if not item_date:
        return True, "无法解析日期，保留待人工审核"
    
    window_days = TIME_WINDOWS.get(item_type, 7)
    cutoff = datetime.now() - timedelta(days=window_days)
    # 只比较日期部分，避免边界时间问题
    cutoff = cutoff.replace(hour=0, minute=0, second=0, microsecond=0)
    
    if item_type == "events":
        # 活动预告：检查是否在未来90天内
        future_cutoff = datetime.now() + timedelta(days=window_days)
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        item_day = item_date.replace(hour=0, minute=0, second=0, microsecond=0)
        if item_day < today:
            return False, f"活动已过期 ({date_str})"
        if item_date > future_cutoff:
            return False, f"活动太远 ({date_str}, 超过{window_days}天)"
        return True, ""
    
    if item_date < cutoff:
        return False, f"超过时间窗口 ({date_str}, 限制{window_days}天)"
    
    return True, ""


def calculate_value_score(item: Dict[str, Any]) -> int:
    """计算信息价值分数"""
    score = 0
    
    # 1. 来源权威性
    source = item.get("source", "").lower()
    for tier, sources in AUTHORITY_TIERS.items():
        for auth_source in sources:
            if auth_source in source:
                if tier == "tier1":
                    score += VALUE_WEIGHTS["authority"] * 3
                elif tier == "tier2":
                    score += VALUE_WEIGHTS["authority"] * 2
                else:
                    score += VALUE_WEIGHTS["authority"]
                break
    
    # 2. 信息完整性（有具体数据）
    summary = item.get("summary", "")
    if re.search(r'\d+\.?\d*\s*(?:亿|万)?(?:元|美元|欧元|英镑)', summary):
        score += VALUE_WEIGHTS["completeness"] * 2
    if re.search(r'\d{4}-\d{2}-\d{2}', summary):
        score += VALUE_WEIGHTS["completeness"]
    
    # 3. 时效性（越新分越高）
    date_str = item.get("date", "")
    item_date = parse_date(date_str)
    if item_date:
        days_ago = (datetime.now() - item_date).days
        if days_ago <= 1:
            score += VALUE_WEIGHTS["timeliness"] * 3
        elif days_ago <= 3:
            score += VALUE_WEIGHTS["timeliness"] * 2
        elif days_ago <= 7:
            score += VALUE_WEIGHTS["timeliness"]
    
    # 4. 行业影响力（关键词匹配）
    title = item.get("title", "").lower()
    impact_keywords = ["融资", "并购", "上市", "获批", "突破", "nature", "science", 
                       "政策", "法规", "规划", "亿元", "亿美元", "fda", "gras"]
    for kw in impact_keywords:
        if kw in title:
            score += VALUE_WEIGHTS["impact"]
    
    return score


def aggregate_duplicates(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """聚合同一事件的多源报道"""
    groups = {}
    
    for item in items:
        fp = generate_fingerprint(item)
        
        if fp not in groups:
            groups[fp] = {
                "primary": item,
                "sources": [item.get("source", "")],
                "urls": [item.get("url", "")],
            }
        else:
            groups[fp]["sources"].append(item.get("source", ""))
            groups[fp]["urls"].append(item.get("url", ""))
    
    aggregated = []
    for fp, group in groups.items():
        primary = group["primary"]
        sources = list(set([s for s in group["sources"] if s]))
        urls = list(set([u for u in group["urls"] if u]))
        
        # 合并来源信息
        if len(sources) > 1:
            primary["source"] = f"多家媒体 ({', '.join(sources[:3])})"
            if len(sources) > 3:
                primary["source"] += f" 等{len(sources)}家"
        
        primary["urls"] = urls
        primary["source_count"] = len(sources)
        aggregated.append(primary)
    
    return aggregated


# ==================== 核心处理函数 ====================

def process_raw_data(raw_data: List[Dict[str, Any]], item_type: str) -> Dict[str, Any]:
    """
    处理原始数据：过滤 → 去重 → 聚合 → 排序
    
    返回: {
        "approved": [...],      # 通过审核的信息
        "rejected": [...],      # 被拒绝的信息及原因
        "stats": {...},         # 统计信息
    }
    """
    fingerprint_db = load_historical_events(days=7)
    policy_db = load_policy_database()
    
    approved = []
    rejected = []
    
    for item in raw_data:
        item_id = item.get("id", "")
        title = item.get("title", "")
        
        # 1. 时效性检查
        timely, reason = check_timeliness(item, item_type)
        if not timely:
            rejected.append({
                "item": item,
                "reason": f"[时效性] {reason}",
                "action": "排除",
            })
            continue
        
        # 2. 去重检查
        is_dup, dup_reason = is_duplicate(item, fingerprint_db)
        if is_dup:
            rejected.append({
                "item": item,
                "reason": f"[去重] {dup_reason}",
                "action": "排除",
            })
            continue
        
        # 3. 政策库去重（仅政策类）
        if item_type == "policy":
            policy_name = item.get("title", "")
            issuer = item.get("source", "")
            is_policy_dup = False
            for policy in policy_db:
                if policy.get("policy_name") == policy_name and policy.get("issuer") == issuer:
                    is_policy_dup = True
                    break
            if is_policy_dup:
                rejected.append({
                    "item": item,
                    "reason": "[政策库] 已收录政策",
                    "action": "排除",
                })
                continue
        
        # 4. 计算价值分数
        score = calculate_value_score(item)
        item["value_score"] = score
        
        approved.append(item)
    
    # 5. 聚合多源报道
    approved = aggregate_duplicates(approved)
    
    # 6. 按价值分数排序
    approved.sort(key=lambda x: x.get("value_score", 0), reverse=True)
    
    stats = {
        "total_input": len(raw_data),
        "approved": len(approved),
        "rejected": len(rejected),
        "timeliness_rejected": len([r for r in rejected if "时效性" in r["reason"]]),
        "duplicate_rejected": len([r for r in rejected if "去重" in r["reason"] or "政策库" in r["reason"]]),
        "avg_score": sum(a.get("value_score", 0) for a in approved) / max(len(approved), 1),
    }
    
    return {
        "approved": approved,
        "rejected": rejected,
        "stats": stats,
    }


# ==================== 报告验证函数 ====================

def validate_report_structure(report_path: str) -> Dict[str, Any]:
    """
    验证报告结构是否符合模板要求
    
    返回: {
        "is_valid": bool,
        "errors": [str],
        "warnings": [str],
        "sections_found": [str],
    }
    """
    errors = []
    warnings = []
    sections_found = []
    
    if not os.path.exists(report_path):
        errors.append(f"报告文件不存在: {report_path}")
        return {"is_valid": False, "errors": errors, "warnings": warnings, "sections_found": []}
    
    with open(report_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 1. 检查必需板块
    required_sections = [
        "## 📌 执行摘要",
        "## 📰 行业热点新闻",
        "## 🔬 最新研究成果",
        "## 💰 融资与投资动态",
        "## 🏛️ 政策与监管",
        "## 📅 行业活动预告",
        "## 🤖 AI 深度分析",
        "## 📎 附录",
    ]
    
    for section in required_sections:
        if section in content:
            sections_found.append(section.replace("## ", ""))
        else:
            errors.append(f"缺少必需板块: {section}")
    
    # 2. 检查禁止的额外板块
    forbidden_patterns = [
        r"## [^#]*公司[^#]*进展",
        r"## [^#]*产品[^#]*动态",
    ]
    for pattern in forbidden_patterns:
        if re.search(pattern, content, re.IGNORECASE):
            errors.append(f"发现禁止的额外板块，匹配模式: {pattern}")
    
    # 3. 检查执行摘要格式（日期标注 + 降序排列）
    summary_section = re.search(r'## 📌 执行摘要\n\n(.*?)(?=\n## )', content, re.DOTALL)
    if summary_section:
        summary_text = summary_section.group(1)
        summary_items = re.findall(r'^\d+\.', summary_text, re.MULTILINE)
        if len(summary_items) < 1:
            errors.append(f"执行摘要条目过少: {len(summary_items)}条 (要求至少1条)")
        elif len(summary_items) > 8:
            warnings.append(f"执行摘要条目过多: {len(summary_items)}条 (建议5-8条)")
        
        # 检查每条是否有日期标注
        date_annotations = re.findall(r'\（\d{4}-\d{2}-\d{2}\）', summary_text)
        if len(date_annotations) < len(summary_items):
            errors.append(f"执行摘要日期标注不完整: {len(date_annotations)}/{len(summary_items)}条有日期标注，每条必须末尾标注（YYYY-MM-DD）")
        
        # 检查日期是否按降序排列
        dates = re.findall(r'\（(\d{4}-\d{2}-\d{2})\）', summary_text)
        if len(dates) >= 2:
            parsed_dates = []
            for d in dates:
                try:
                    parsed_dates.append(datetime.strptime(d, "%Y-%m-%d"))
                except:
                    pass
            for i in range(1, len(parsed_dates)):
                if parsed_dates[i] > parsed_dates[i-1]:
                    errors.append(f"执行摘要日期未按降序排列: 第{i}条日期({dates[i]})晚于第{i+1}条({dates[i-1]})")
                    break
    else:
        errors.append("无法解析执行摘要板块")
    
    # 4. 检查表格格式及日期排序
    table_sections = {
        "## 📰 行业热点新闻": "news",
        "## 🔬 最新研究成果": "research", 
        "## 💰 融资与投资动态": "funding",
        "## 📅 行业活动预告": "events"
    }
    for section_name, section_key in table_sections.items():
        section_content = re.search(re.escape(section_name) + r'\n\n(.*?)(?=\n## )', content, re.DOTALL)
        if section_content:
            section_text = section_content.group(1)
            # 如果板块明确标注"暂无"，允许不使用表格
            is_empty_section = bool(re.search(r'本周期暂无相关新信息收录|本周期暂无|暂无新信息|color:#888', section_text))
            if not is_empty_section and "| 标题 |" not in section_text and "| 公司 |" not in section_text and "| 活动名称 |" not in section_text:
                errors.append(f"{section_name} 未使用表格格式")
            
            # 检查表格日期列是否按降序排列
            date_rows = re.findall(r'\|\s*(\d{4}-\d{2}-\d{2})\s*\|', section_text)
            if len(date_rows) >= 2:
                parsed_dates = []
                for d in date_rows:
                    try:
                        parsed_dates.append(datetime.strptime(d.strip(), "%Y-%m-%d"))
                    except:
                        pass
                for i in range(1, len(parsed_dates)):
                    if parsed_dates[i] > parsed_dates[i-1]:
                        errors.append(f"{section_name} 表格日期未按降序排列: 第{i}行日期({date_rows[i]})晚于第{i+1}行({date_rows[i-1]})")
                        break
    
    # 5. 检查政策板块格式及日期排序
    policy_section = re.search(r'## 🏛️ 政策与监管\n\n(.*?)(?=\n## )', content, re.DOTALL)
    if policy_section:
        policy_text = policy_section.group(1)
        if "### 国内政策" not in policy_text:
            warnings.append("政策与监管板块缺少 '### 国内政策' 子标题")
        if "### 国际监管动态" not in policy_text:
            warnings.append("政策与监管板块缺少 '### 国际监管动态' 子标题")
        
        # 检查国内政策表格日期是否按降序排列
        domestic_match = re.search(r'### 国内政策\n\n(.*?)(?=### 国际监管动态)', policy_text, re.DOTALL)
        if domestic_match:
            domestic_text = domestic_match.group(1)
            date_rows = re.findall(r'\|\s*(\d{4}-\d{2}-\d{2})\s*\|', domestic_text)
            if len(date_rows) >= 2:
                parsed_dates = []
                for d in date_rows:
                    try:
                        parsed_dates.append(datetime.strptime(d.strip(), "%Y-%m-%d"))
                    except:
                        pass
                for i in range(1, len(parsed_dates)):
                    if parsed_dates[i] > parsed_dates[i-1]:
                        errors.append(f"政策与监管-国内政策表格日期未按降序排列: 第{i}行日期({date_rows[i]})晚于第{i+1}行({date_rows[i-1]})")
                        break
    
    # 6. 检查AI分析深度
    analysis_section = re.search(r'## 🤖 AI 深度分析\n\n(.*?)(?=\n## )', content, re.DOTALL)
    if analysis_section:
        analysis_text = analysis_section.group(1)
        if "### 趋势研判" not in analysis_text:
            errors.append("AI深度分析缺少 '### 趋势研判'")
        if "### 竞争格局变化" not in analysis_text:
            errors.append("AI深度分析缺少 '### 竞争格局变化'")
        if "### 风险提示" not in analysis_text:
            errors.append("AI深度分析缺少 '### 风险提示'")
        
        # 检查是否有具体事件引用（避免空泛）
        if not re.search(r'\d{4}-\d{2}-\d{2}|Nature|Science|亿元|融资|政策', analysis_text):
            warnings.append("AI深度分析可能过于空泛，缺少具体事件引用")
    
    # 7. 检查附录链接
    appendix_section = re.search(r'## 📎 附录(.*?)$', content, re.DOTALL)
    if appendix_section:
        appendix_text = appendix_section.group(1)
        links = re.findall(r'https?://[^\s\)]+', appendix_text)
        if len(links) < 1:
            warnings.append(f"附录链接过少: {len(links)}条 (要求至少1条)")
    
    # 8. 检查空白板块（新增）
    blank_sections = []
    for section_name, section_marker in [
        ("行业热点新闻", "## 📰 行业热点新闻"),
        ("最新研究成果", "## 🔬 最新研究成果"),
        ("融资与投资动态", "## 💰 融资与投资动态"),
        ("政策与监管", "## 🏛️ 政策与监管"),
        ("行业活动预告", "## 📅 行业活动预告"),
    ]:
        section_content = re.search(re.escape(section_marker) + r'\n\n(.*?)(?=\n## )', content, re.DOTALL)
        if section_content:
            section_text = section_content.group(1)
            # 检查是否只有"暂无"或空白
            has_content = len(re.findall(r'[\u4e00-\u9fff]|[a-zA-Z0-9]', section_text)) >= 10
            if re.search(r'暂无|本周期暂无|color:#888|—\s*—\s*—', section_text) and not has_content:
                blank_sections.append(section_name)
    
    if blank_sections:
        warnings.append(f"以下板块为空或未收录有效信息: {', '.join(blank_sections)}。请确认已执行第五轮定向补搜，并在报告中注明'经全面检索，本周期暂无新信息'")
    
    is_valid = len(errors) == 0
    
    return {
        "is_valid": is_valid,
        "errors": errors,
        "warnings": warnings,
        "sections_found": sections_found,
    }


def validate_timeliness_in_report(report_path: str) -> Dict[str, Any]:
    """验证报告中所有信息的时效性"""
    errors = []
    warnings = []
    
    with open(report_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 提取所有日期
    date_patterns = [
        r'\|([^|]+)\|([^|]+)\|(\d{4}-\d{2}-\d{2})\|',
        r'\|([^|]+)\|([^|]+)\|([^|]+)\|(\d{4}-\d{2}-\d{2})\|',
    ]
    
    all_dates = []
    for pattern in date_patterns:
        matches = re.findall(pattern, content)
        for match in matches:
            if len(match) >= 3:
                date_str = match[-3].strip() if len(match) > 3 else match[2].strip()
                title = match[0].strip()
                if title and title != "标题" and not title.startswith("-"):
                    all_dates.append((title, date_str))
    
    # 检查每个日期
    now = datetime.now()
    for title, date_str in all_dates:
        item_date = parse_date(date_str)
        if item_date:
            days_ago = (now - item_date).days
            if days_ago > 30:
                errors.append(f"信息过时: '{title[:30]}...' 发布于 {date_str} ({days_ago}天前, 超过30天)")
            elif days_ago > 14:
                warnings.append(f"信息较旧: '{title[:30]}...' 发布于 {date_str} ({days_ago}天前)")
    
    return {
        "has_errors": len(errors) > 0,
        "errors": errors,
        "warnings": warnings,
        "total_checked": len(all_dates),
    }


# ==================== 主流程函数 ====================

def run_compliance_check(report_path: str, raw_stats: Dict[str, Any] = None) -> Dict[str, Any]:
    """
    运行完整的合规复检
    
    返回: {
        "passed": bool,
        "can_send_email": bool,
        "structure_check": {...},
        "timeliness_check": {...},
        "overall_score": int,
        "fix_instructions": [str],
    }
    """
    structure = validate_report_structure(report_path)
    timeliness = validate_timeliness_in_report(report_path)
    
    fix_instructions = []
    
    # 结构错误必须修复
    if not structure["is_valid"]:
        fix_instructions.extend(structure["errors"])
    
    # 时效性错误必须修复
    if timeliness["has_errors"]:
        fix_instructions.extend(timeliness["errors"])
    
    # 警告建议修复
    if structure["warnings"]:
        fix_instructions.extend([f"[建议] {w}" for w in structure["warnings"]])
    if timeliness["warnings"]:
        fix_instructions.extend([f"[建议] {w}" for w in timeliness["warnings"]])
    
    # 计算综合分数
    score = 100
    score -= len(structure["errors"]) * 20
    score -= len(timeliness["errors"]) * 15
    score -= len(structure["warnings"]) * 5
    score -= len(timeliness["warnings"]) * 3
    score = max(0, score)
    
    passed = len(structure["errors"]) == 0 and len(timeliness["errors"]) == 0
    can_send = passed and score >= 80
    
    return {
        "passed": passed,
        "can_send_email": can_send,
        "structure_check": structure,
        "timeliness_check": timeliness,
        "overall_score": score,
        "fix_instructions": fix_instructions,
        "raw_stats": raw_stats or {},
    }


def validate_email_consistency(email_body: str, approved_data: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    验证邮件正文与H5/approved数据的一致性
    
    规则：
    1. 邮件正文中的所有URL必须在approved数据中存在
    2. 邮件正文中的信息标题必须在approved数据中存在（模糊匹配）
    3. 邮件正文不能包含approved数据中没有的信息
    
    返回: {
        "is_consistent": bool,
        "errors": [str],
        "warnings": [str],
        "email_urls": [str],
        "approved_urls": [str],
        "missing_urls": [str],
        "email_titles": [str],
        "missing_titles": [str],
    }
    """
    errors = []
    warnings = []
    
    # 提取邮件正文中的所有URL
    email_urls = re.findall(r'href=["\'](https?://[^"\']+)["\']', email_body)
    email_urls = list(set(email_urls))
    
    # 提取approved数据中的所有URL
    approved_urls = []
    approved_titles = []
    for item in approved_data:
        url = item.get("url", "")
        if url:
            approved_urls.append(url)
        title = item.get("title", "")
        if title:
            approved_titles.append(title)
    
    # 检查邮件URL是否都在approved中
    missing_urls = [u for u in email_urls if u not in approved_urls]
    if missing_urls:
        errors.append(f"邮件正文包含{len(missing_urls)}个H5/approved数据中不存在的URL: {missing_urls[:3]}")
    
    # 提取邮件正文中的信息标题（通过粗体或卡片标题）
    email_titles = []
    # 匹配 <div class="card-title">标题</div>
    card_titles = re.findall(r'<div class="card-title">(.*?)</div>', email_body)
    email_titles.extend(card_titles)
    # 匹配 <strong>数字. 标题</strong>
    strong_titles = re.findall(r'<strong>(\d+)\.\s*(.*?)</strong>', email_body)
    email_titles.extend([t[1] for t in strong_titles])
    # 匹配 <strong>标题</strong> 不在数字列表中的
    other_strong = re.findall(r'<strong>([^<]{10,80})</strong>', email_body)
    for t in other_strong:
        if not re.match(r'^\d+\.', t):
            email_titles.append(t)
    
    email_titles = [t.strip() for t in email_titles if t.strip()]
    
    # 检查邮件标题是否都在approved中（模糊匹配：共享关键词）
    missing_titles = []
    for email_title in email_titles:
        found = False
        for approved_title in approved_titles:
            # 提取关键词（中文字符或英文单词）
            email_words = set(re.findall(r'[\u4e00-\u9fff]{2,}|[a-zA-Z]{3,}', email_title.lower()))
            approved_words = set(re.findall(r'[\u4e00-\u9fff]{2,}|[a-zA-Z]{3,}', approved_title.lower()))
            if len(email_words) > 0 and len(approved_words) > 0:
                overlap = len(email_words & approved_words) / max(len(email_words), len(approved_words))
                if overlap > 0.5:  # 50%关键词重叠视为匹配
                    found = True
                    break
        if not found:
            missing_titles.append(email_title)
    
    if missing_titles:
        errors.append(f"邮件正文包含{len(missing_titles)}条H5/approved数据中不存在的信息: {missing_titles[:3]}")
    
    # 检查邮件是否遗漏了执行摘要的关键信息
    # 执行摘要应该有5条，检查是否有5个数字标记
    summary_items = re.findall(r'<span class="num">(\d+)</span>', email_body)
    if len(summary_items) < 5:
        warnings.append(f"邮件正文执行摘要可能不完整: 找到{len(summary_items)}条，期望5条")
    
    is_consistent = len(errors) == 0
    
    return {
        "is_consistent": is_consistent,
        "errors": errors,
        "warnings": warnings,
        "email_urls": email_urls,
        "approved_urls": approved_urls,
        "missing_urls": missing_urls,
        "email_titles": email_titles,
        "missing_titles": missing_titles,
    }


def validate_email_mime_type(email_msg) -> Dict[str, Any]:
    """
    验证邮件附件的MIME类型是否正确
    
    规则：
    1. HTML附件必须使用 text/html MIME类型
    2. Markdown附件必须使用 text/plain MIME类型
    3. 严禁使用 application/octet-stream（会导致附件变成.bin文件）
    
    返回: {
        "is_valid": bool,
        "errors": [str],
        "warnings": [str],
        "attachments_checked": [str],
    }
    """
    errors = []
    warnings = []
    attachments_checked = []
    
    # 遍历邮件所有部分
    for part in email_msg.walk():
        content_type = part.get_content_type()
        content_disposition = part.get("Content-Disposition", "")
        
        # 只检查附件
        if "attachment" in content_disposition:
            filename = part.get_filename() or "未知文件"
            attachments_checked.append(f"{filename} ({content_type})")
            
            # 检查HTML附件
            if filename.endswith(".html"):
                if content_type != "text/html":
                    errors.append(
                        f"HTML附件 '{filename}' MIME类型错误: 当前为 '{content_type}', "
                        f"必须使用 'text/html'。使用 MIMEText(content, 'html', 'utf-8') 创建。"
                    )
            
            # 检查MD附件
            elif filename.endswith(".md"):
                if content_type != "text/plain":
                    errors.append(
                        f"Markdown附件 '{filename}' MIME类型错误: 当前为 '{content_type}', "
                        f"必须使用 'text/plain'。使用 MIMEText(content, 'plain', 'utf-8') 创建。"
                    )
            
            # 检查是否使用了错误的 octet-stream
            if content_type == "application/octet-stream":
                errors.append(
                    f"附件 '{filename}' 使用了错误的MIME类型 'application/octet-stream'，"
                    f"这会导致QQ邮箱等客户端显示为.bin文件。"
                )
    
    is_valid = len(errors) == 0
    
    return {
        "is_valid": is_valid,
        "errors": errors,
        "warnings": warnings,
        "attachments_checked": attachments_checked,
    }


def run_full_validation(report_md_path: str, email_body: str, approved_data: List[Dict[str, Any]], raw_stats: Dict[str, Any] = None) -> Dict[str, Any]:
    """
    运行完整的报告+邮件一致性验证
    
    返回: {
        "report_passed": bool,
        "email_consistent": bool,
        "can_send_email": bool,
        "overall_score": int,
        "fix_instructions": [str],
    }
    """
    # 1. 验证Markdown报告
    report_result = run_compliance_check(report_md_path, raw_stats)
    
    # 2. 验证邮件一致性
    email_result = validate_email_consistency(email_body, approved_data)
    
    fix_instructions = list(report_result.get("fix_instructions", []))
    
    # 邮件一致性错误必须修复
    if not email_result["is_consistent"]:
        fix_instructions.extend(email_result["errors"])
    
    # 邮件一致性警告建议修复
    if email_result["warnings"]:
        fix_instructions.extend([f"[邮件一致性建议] {w}" for w in email_result["warnings"]])
    
    # 计算综合分数
    score = report_result["overall_score"]
    if not email_result["is_consistent"]:
        score -= len(email_result["errors"]) * 15
    if email_result["warnings"]:
        score -= len(email_result["warnings"]) * 3
    score = max(0, score)
    
    report_passed = report_result["passed"]
    email_consistent = email_result["is_consistent"]
    can_send = report_passed and email_consistent and score >= 80
    
    return {
        "report_passed": report_passed,
        "email_consistent": email_consistent,
        "can_send_email": can_send,
        "overall_score": score,
        "fix_instructions": fix_instructions,
        "report_check": report_result,
        "email_check": email_result,
    }


def save_rejection_log(rejected: List[Dict[str, Any]], report_date: str):
    """保存被拒绝的信息日志"""
    log_file = DATA_DIR / f"rejected_{report_date}.json"
    
    with open(log_file, 'w', encoding='utf-8') as f:
        json.dump(rejected, f, ensure_ascii=False, indent=2)


# ==================== CLI 入口 ====================

def main():
    """命令行入口，用于测试"""
    import argparse
    import io
    import sys
    
    # Fix Windows console encoding
    if sys.platform == 'win32':
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')
    
    parser = argparse.ArgumentParser(description="AS hub NEWs agent - Report Pipeline")
    parser.add_argument("--validate", type=str, help="验证报告文件路径")
    parser.add_argument("--process", type=str, help="处理原始数据JSON文件")
    parser.add_argument("--type", type=str, default="news", help="数据类型")
    parser.add_argument("--output", type=str, help="输出文件路径")
    
    args = parser.parse_args()
    
    if args.validate:
        result = run_compliance_check(args.validate)
        output_path = args.output or (args.validate.replace('.md', '_validation.json'))
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        
        # Safe output without emoji
        passed = "YES" if result['passed'] else "NO"
        can_send = "YES" if result['can_send_email'] else "NO"
        print(f"Validation result saved to: {output_path}")
        print(f"Passed: {passed}, Can send email: {can_send}, Score: {result['overall_score']}")
        if result['fix_instructions']:
            print(f"Fix instructions ({len(result['fix_instructions'])} items):")
            for i, instr in enumerate(result['fix_instructions'][:10], 1):
                # Remove emoji for safe console output
                safe_instr = instr.encode('ascii', 'ignore').decode('ascii')
                print(f"  {i}. {safe_instr}")
    
    elif args.process:
        with open(args.process, 'r', encoding='utf-8') as f:
            raw_data = json.load(f)
        
        result = process_raw_data(raw_data, args.type)
        
        if args.output:
            with open(args.output, 'w', encoding='utf-8') as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
        
        print(f"处理完成: 输入{result['stats']['total_input']}条, 通过{result['stats']['approved']}条, 拒绝{result['stats']['rejected']}条")
    
    else:
        # 默认：显示历史事件库统计
        fp_db = load_historical_events(days=7)
        print(f"历史事件指纹库: {len(fp_db)}条记录")
        
        policy_db = load_policy_database()
        print(f"政策库: {len(policy_db)}条记录")


if __name__ == "__main__":
    main()
