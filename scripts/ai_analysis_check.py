#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI深度分析防幻觉验证脚本 v3
精确检测，低误报
"""

import re
import json
from pathlib import Path
from typing import Dict, List, Any, Set

try:
    from .console_utils import ensure_utf8_console
except ImportError:
    from console_utils import ensure_utf8_console

ensure_utf8_console()


NUMBER_TOKEN_PATTERN = re.compile(
    r'(?:\d{4}-\d{1,2}-\d{1,2}|\d+(?:\.\d+)?\s*(?:%|％|家|名|个|项|亿元|万元|万美元|亿美元|元|美元|欧元|天|年|月|日|轮)?)'
    r'|(?:数十|数百|数千|数万|上百|上千|近百|逾百|数百万|数千万|数亿元|数千万元|数百万元|数万元)'
)
COMPANY_SUFFIXES = ("公司", "集团", "科技", "生物", "医药", "医疗", "健康", "制药", "资本")
COMPANY_NAME_PATTERN = re.compile(r"[\u4e00-\u9fff]{2,6}?(?:公司|集团|科技|生物|医药|医疗|健康|制药|资本)")
FALSE_COMPANY_PREFIXES = {
    "后续", "重大", "传统", "人工智能", "向生物", "对生物",
    "在生物", "以生物", "将生物", "为生物", "从生物",
    "相关", "行业", "产业", "企业", "技术", "平台",
    "创新", "资本", "市场", "政策", "监管", "融资",
    "制造", "投产", "说明",
}
FALSE_COMPANY_TERMS = {
    "后续生物", "重大科技", "传统医药", "人工智能",
    "合成生物", "生物技术", "生物制造", "生物医药",
}
FALSE_COMPANY_INFIXES = {
    "后续", "重大", "传统", "人工智能", "合成生物",
    "生物制造", "生物技术", "生物医药", "平台",
    "显示", "说明", "正在", "仍获", "企业", "产业",
}
GENERIC_COMPANY_TERMS = {"科技", "生物", "医药", "医疗", "健康", "制药", "资本"}


def is_probable_chinese_company_name(text: str) -> bool:
    """Return whether a Chinese suffix phrase is likely a concrete company name."""
    if not text or text in CHINESE_WHITELIST or text in FALSE_COMPANY_TERMS:
        return False
    if text in GENERIC_COMPANY_TERMS:
        return False
    if any(text.startswith(prefix) for prefix in FALSE_COMPANY_PREFIXES):
        return False
    if any(term in text for term in FALSE_COMPANY_INFIXES):
        return False

    # 包含常见动词/介词（如"的"、"在"、"涉及"）的组合不太可能是公司名
    if any(p in text for p in {"的", "在", "涉及", "驱动", "应用"}):
        return False

    return bool(re.fullmatch(rf"[\u4e00-\u9fff]{{2,6}}(?:{'|'.join(COMPANY_SUFFIXES)})", text))


def extract_report_facts(report_path: str) -> Set[str]:
    """从报告中提取所有事实关键词（标题、公司名、活动名等）"""
    facts = set()
    
    with open(report_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 提取各板块表格中的第一列（标题/公司/活动名）
    sections = [
        (r'## 📰 行业热点新闻\n\n(.*?)(?=\n## )', "标题"),
        (r'## 🔬 最新研究成果\n\n(.*?)(?=\n## )', "标题"),
        (r'## 💰 融资与投资动态\n\n(.*?)(?=\n## )', "公司"),
        (r'## 🏛️ 政策与监管\n\n(.*?)(?=\n## )', "政策/法规"),
        (r'## 📅 行业活动预告\n\n(.*?)(?=\n## )', "活动名称"),
    ]
    
    for pattern, header_name in sections:
        section_match = re.search(pattern, content, re.DOTALL)
        if not section_match:
            continue
        
        section_text = section_match.group(1)
        for line in section_text.split('\n'):
            line = line.strip()
            if not line.startswith('|') or line.startswith('|---'):
                continue
            
            cells = [c.strip() for c in line.split('|')[1:-1]]
            if not cells:
                continue
            
            title = cells[0]
            if title in (header_name, '—', '', '本周期暂无相关新信息收录'):
                continue
            if '暂无' in title:
                continue
            
            # 添加完整标题
            facts.add(title.lower())
            # 添加标题中的关键词
            words = re.findall(r'[\u4e00-\u9fff]{2,}|[a-zA-Z]{3,}', title)
            for w in words:
                facts.add(w.lower())
            for company_match in COMPANY_NAME_PATTERN.finditer(title):
                company_name = company_match.group(0)
                if is_probable_chinese_company_name(company_name):
                    facts.add(company_name.lower())
    
    # 提取执行摘要中的关键词
    summary_match = re.search(r'## 📌 执行摘要\n\n(.*?)(?=\n## )', content, re.DOTALL)
    if summary_match:
        words = re.findall(r'[\u4e00-\u9fff]{2,}|[a-zA-Z]{3,}', summary_match.group(1))
        for w in words:
            facts.add(w.lower())
    
    return facts


def extract_number_tokens(text: str) -> Set[str]:
    """Extract concrete numeric facts that must be grounded in non-AI content."""
    tokens = set()
    for match in NUMBER_TOKEN_PATTERN.finditer(text):
        token = re.sub(r"\s+", "", match.group(0))
        if token in {"1", "2", "3", "4", "5", "6", "7", "8"}:
            continue
        tokens.add(token)
    return tokens


def non_ai_content(content: str) -> str:
    """Return report content with the AI analysis section removed."""
    return re.sub(r'## 🤖 AI 深度分析\n\n.*?(?=\n## |\Z)', '', content, flags=re.DOTALL)


def validate_ai_analysis(report_path: str) -> Dict[str, Any]:
    """验证AI分析是否只引用了正文已收录的信息"""
    errors = []
    warnings = []
    hallucinations = []
    verified = []
    
    with open(report_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 提取AI分析部分
    analysis_match = re.search(r'## 🤖 AI 深度分析\n\n(.*?)(?=\n## |\Z)', content, re.DOTALL)
    if not analysis_match:
        return {"has_errors": True, "errors": ["无法找到AI分析板块"], "warnings": [], "hallucinations": [], "verified": []}
    
    analysis_text = analysis_match.group(1)
    
    # 提取正文事实库
    facts = extract_report_facts(report_path)
    supported_numbers = extract_number_tokens(non_ai_content(content))
    
    # 检测策略：只检测明确的公司名和机构名
    # 策略1：检测加粗段落中的具体引用（排除结构标题）
    # 匹配 **非数字开头的内容**
    for match in re.finditer(r'\*\*([^*\d][^*]{2,80})\*\*', analysis_text):
        text = match.group(1).strip()
        
        # 跳过结构标题
        if text in STRUCTURE_TITLES or any(t in text for t in STRUCTURE_TITLES):
            continue
        
        # 检查是否能在正文中找到
        text_lower = text.lower()
        keywords = re.findall(r'[\u4e00-\u9fff]{2,}|[a-zA-Z]{3,}', text_lower)
        
        if not keywords:
            continue
        
        # 检查关键词是否都在事实库中
        found_count = sum(1 for kw in keywords if kw in facts)
        if found_count >= len(keywords):  # 100%关键词必须全部匹配
            verified.append(text)
        else:
            # 未找到匹配，可能是幻觉
            hallucinations.append(text)
            if len(keywords) >= 2 and found_count == 0:
                errors.append(f"AI分析引用未收录信息: '{text}'")
            else:
                warnings.append(f"AI分析可能引用未收录信息: '{text}'")
    
    # 策略2：检测独立出现的英文公司名（不在加粗中）
    # 只检测明显的大写多词组合（如 "Twist Bioscience"）
    for match in re.finditer(r'\b([A-Z][a-zA-Z]{2,}(?:\s+[A-Z][a-zA-Z]{2,}){1,2})\b', analysis_text):
        text = match.group(1)
        if text in ENGLISH_WHITELIST:
            continue
        if text.lower() in facts:
            verified.append(text)
        else:
            # 检查是否部分匹配
            parts = text.lower().split()
            if any(p in facts for p in parts if len(p) >= 3):
                verified.append(text)
            else:
                hallucinations.append(text)
                errors.append(f"AI分析引用未收录公司: '{text}'")
    
    # 策略3：检测中文公司名（含行业后缀）
    for match in COMPANY_NAME_PATTERN.finditer(analysis_text):
        text = match.group(0)
        if not is_probable_chinese_company_name(text):
            continue
        if text.lower() in facts:
            verified.append(text)
        else:
            hallucinations.append(text)
            errors.append(f"AI分析引用未收录公司: '{text}'")

    # 策略4：检测数字、金额、比例、日期是否来自正文非AI部分
    for token in sorted(extract_number_tokens(analysis_text)):
        if token in supported_numbers:
            verified.append(token)
        else:
            hallucinations.append(token)
            errors.append(f"AI分析引用未收录数字: '{token}'")
    
    # 去重
    hallucinations = list(set(h for h in hallucinations if h.strip()))
    verified = list(set(v for v in verified if v.strip()))
    
    return {
        "has_errors": len(errors) > 0,
        "errors": errors,
        "warnings": warnings,
        "hallucinations": hallucinations,
        "verified": verified,
    }


# 白名单
STRUCTURE_TITLES = {
    "趋势研判", "竞争格局变化", "风险提示",
    "第一梯队", "第二梯队", "第三梯队",
    "平台型巨头", "产业化先锋", "细分赛道新锐", "区域竞争格局",
    "外资头部企业加速布局中国合成生物制造产业集群",
    "虚拟公司模式或成为合成生物创业新范式",
    "合成细胞研究进入系统化整合阶段",
    "政府产业基金加速布局生物制造",
    "AI×合成生物学成为不可逆趋势",
    "区域产业集群效应加速显现",
    "亚洲合成生物学战略协同加速",
    "国资基金成为合成生物早期投资主力",
    "资本市场对合成生物龙头保持关注",
    "技术转化风险", "资本寒冬持续", "监管不确定性",
    "国际竞争加剧", "政策落地不及预期风险", "人才短缺",
    "技术转化周期长风险", "资本寒冬持续风险", "国际竞争加剧风险",
    "政策落地不及预期风险", "人才竞争加剧风险",
    "技术转化周期长", "资本寒冬持续", "国际竞争加剧",
    "政策落地不及预期", "人才竞争加剧",
}

ENGLISH_WHITELIST = {
    # 通用缩写和技术术语
    "AI", "DNA", "RNA", "FDA", "GRAS", "CAGR",
    # 期刊名（通用）
    "Nature", "Science", "Cell", "Biotechnology", "Biology",
    # 通用行业词
    "Synthetic", "Biology", "Engineering", "Evolution", "Design",
    # 地名
    "China", "Asia", "Europe", "US", "USA", "EU",
    "Beijing", "Shanghai", "Shenzhen", "Guangzhou", "Wuxi",
    "Nanjing", "Hangzhou", "Chengdu", "Hong Kong",
    # 通用金融/商业术语
    "IPO", "VC", "PE", "Q4", "Q3", "Q2", "Q1",
    "ML", "DBTL", "NGS", "C1",
    # 会议/组织通用词
    "SBE", "WIfoR", "SynBYSS", "EuropaBio", "LIT",
}

CHINESE_WHITELIST = {
    # 通用行业词
    "合成生物学", "合成生物", "生物制造", "生物技术", "人工智能",
    "技术转化", "产业化", "商业化", "市场规模", "研发投入",
    "企业", "公司", "行业", "产业", "市场", "资本", "投资", "融资",
    "技术", "产品", "平台", "管线", "产能", "成本", "收入", "利润",
    # 通用动词/形容词
    "预计", "预测", "有望", "或将", "可能", "趋势", "格局", "风险",
    "重要", "关键", "核心", "主要", "显著", "明显", "潜在", "长期", "短期",
    "链接健康", "时效性", "去重门禁", "分类一致性", "发送门禁",
    # 通用连接词
    "此外", "同时", "另一方面", "综上所述", "总体而言", "具体来看",
    "置信度", "高", "中", "低",
    # 地名
    "北京昌平", "上海", "深圳", "广州", "无锡",
}


def main():
    import argparse

    parser = argparse.ArgumentParser(description="AI分析防幻觉验证 v3")
    parser.add_argument("--report", type=str, required=True, help="报告文件路径")
    parser.add_argument("--output", type=str, help="输出JSON路径")
    args = parser.parse_args()
    
    result = validate_ai_analysis(args.report)
    
    if args.output:
        with open(args.output, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
    
    print(f"验证结果: {'通过' if not result['has_errors'] else '未通过'}")
    if result['hallucinations']:
        print(f"\n发现 {len(result['hallucinations'])} 个可能幻觉:")
        for h in result['hallucinations']:
            print(f"  - {h}")
    if result['verified']:
        print(f"\n已验证 {len(result['verified'])} 个实体")
    if not result['hallucinations']:
        print("\nAI分析无幻觉，所有引用均能在正文中找到对应。")
    raise SystemExit(1 if result["has_errors"] else 0)


if __name__ == "__main__":
    main()
