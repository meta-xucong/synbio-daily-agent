#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Synthetic Biology Relevance Judge — Semantic Heuristic
合成生物学领域相关性语义判断模块

核心原则：区分"工程化改造生物系统"（合成生物学）vs "纯化学合成" vs "基础生物学研究"

不使用外部 LLM API，纯本地语义启发式判断，零依赖，零配置。
"""

import re
from typing import Tuple


# 强正向信号：明确的合成生物学工程化改造特征
_STRONG_POSITIVE = frozenset([
    "代谢工程", "基因编辑", "crispr", "基因线路", "基因回路", "基因电路",
    "细胞工厂", "底盘细胞", "底盘菌", "合成生物学", "synthetic biology",
    "synbio", "生物制造", "biomanufacturing", "dna合成", "蛋白质工程",
    "途径重构", "代谢通路", "异源表达", "异源合成", "异源生产",
    "定向进化", "高通量筛选", "自动化平台", "生物反应器", "发酵优化",
    "基因组精简", "基因组编辑", "多基因表达调控", "动态调控",
    "模块化设计", "标准化元件", "生物元件", "生物传感器",
    "合成肽", "合成蛋白", "合成酶", "合成代谢物", "合成途径",
    "微生物合成", "细胞合成", "细菌合成", "酵母合成", "大肠杆菌合成",
    "芽孢杆菌合成", "枯草芽孢杆菌", "地衣芽孢杆菌", "谷氨酸棒杆菌",
    "一碳生物技术", "co₂固定", "人工固碳", "人工代谢途径",
    "工程菌", "工程菌株", "重组菌", "重组表达", "重组蛋白",
    "从头设计", "从头合成", "设计构建", "改造优化",
])

# 强负向信号：明确不是合成生物学
_STRONG_NEGATIVE = frozenset([
    "固相合成", "spps", "化学合成", "有机合成", "全合成",
    "天然产物提取", "分离纯化", "结构鉴定", "晶体结构", "x射线",
    "免疫组化", "western blot", "pcr检测", "测序分析", "基因组测序",
    "临床试验", "病例报告", "流行病学", "回顾性分析", "meta分析",
    "纯化学", "化工合成", "石油化工", "煤化工", "费托合成",
    "药物化学", "高分子化学", "材料科学", "纳米材料",
    "传统发酵", "自然发酵", "野生菌株", "未改造",
])

# 基础生物学自然过程信号——自然过程主导且无工程化，则排除
_NATURAL_PROCESS = frozenset([
    "神经元", "神经递质", "神经信号", "神经环路", "神经回路", "神经传导", "神经连接",
    "突触传递", "突触可塑性", "神经可塑性", "中缝背核",
    "信号通路", "信号转导", "信号传导", "信号级联", "信号传递",
    "受体结合", "受体激活", "配体结合", "配体识别", "受体介导",
    "免疫应答", "免疫反应", "炎症反应", "炎症因子", "细胞因子",
    "细胞凋亡", "细胞坏死", "细胞自噬", "细胞焦亡",
    "生理过程", "自然过程", "内源性", "天然产物", "内源合成",
    "疾病机制", "发病机制", "病理机制", "病理生理", "致病机制",
    "动物模型", "小鼠模型", "大鼠模型", "临床前",
    "行为学", "社交行为", "学习记忆", "认知功能", "情绪调节",
])

# 工程化改造 + 生物体 的上下文模式
_RE_ENGINEERING = re.compile(
    r"(工程|改造|构建|设计|重构|编辑|优化|组装|装配|从头).{0,15}(生物|细胞|微生物|菌|酵母|大肠杆菌|芽孢杆菌|棒杆菌|酶|基因|代谢|途径)")
_RE_BIO_MANUFACTURING = re.compile(
    r"(生物|细胞|微生物|酶).{0,15}(生产|制造|合成|工厂|发酵|催化|转化|降解)")
_RE_PLATFORM_TECH = re.compile(
    r"(平台|技术|工具|方法).{0,10}(合成|编辑|改造|工程|设计)")


def _count_hits(text_lower: str, terms: frozenset) -> int:
    return sum(1 for t in terms if t in text_lower)


def is_synbio_relevant(title: str = "", summary: str = "", url: str = "") -> Tuple[bool, str, str]:
    """
    Judge whether content belongs to synthetic biology.

    Returns: (is_relevant, reason, confidence)
    - confidence: "high" | "medium" | "low"
    """
    text = f"{title} {summary}".lower()

    pos_score = _count_hits(text, _STRONG_POSITIVE)
    neg_score = _count_hits(text, _STRONG_NEGATIVE)
    natural_score = _count_hits(text, _NATURAL_PROCESS)

    has_engineering = bool(_RE_ENGINEERING.search(text))
    has_bio_mfg = bool(_RE_BIO_MANUFACTURING.search(text))
    has_platform = bool(_RE_PLATFORM_TECH.search(text))

    # 1. 明确的基础生物学/神经科学/免疫学（自然过程 + 无工程化）
    if natural_score >= 1 and pos_score == 0 and not has_engineering and not has_bio_mfg:
        return False, "基础生物学研究（自然生理/神经/免疫过程），无工程化改造特征", "high"

    # 2. 明确的化学合成/基础医学
    if neg_score >= 2 and pos_score == 0:
        return False, "传统化学/基础生物学，无合成生物学工程化特征", "high"

    # 3. 明确的合成生物学（强正向信号 + 工程化上下文）
    if pos_score >= 2 or (pos_score >= 1 and (has_engineering or has_bio_mfg)):
        return True, "合成生物学工程化改造生物系统", "high"

    if pos_score >= 1 and has_platform:
        return True, "合成生物学平台技术或工具", "high"

    if pos_score >= 1:
        return True, "含合成生物学相关术语", "medium"

    # 4. 兜底
    if natural_score >= 1 and not has_engineering and not has_bio_mfg:
        return False, "偏向基础生物学自然过程，无工程化特征", "medium"

    if neg_score >= 1 and not has_engineering and not has_bio_mfg:
        return False, "偏向传统方法或基础研究，无工程化特征", "medium"

    return True, "语义模糊，默认保留待复核", "low"


def batch_judge(items: list[dict]) -> list[Tuple[bool, str, str]]:
    """Judge a batch of items."""
    return [
        is_synbio_relevant(
            str(item.get("title", "")),
            str(item.get("summary", "")),
            str(item.get("url", "")),
        )
        for item in items
    ]


if __name__ == "__main__":
    # Self-test
    test_cases = [
        ("Nature子刊：四川大学开发非经典WNT骨合成肽", "通过AlphaFold赋能的结构预测与虚拟筛选，鉴定出WNT7BRTID作为WNT衍生骨合成肽", True),
        ("Cell：IL-1β信号通过中缝背核神经元调控社交行为", "IL-1β通过结合大脑中缝背核神经元上的IL-1R1受体，激活神经连接，主动抑制社交行为", False),
        ("湖北大学改造地衣芽孢杆菌高效合成血清素", "通过多维代谢工程策略在地衣芽孢杆菌中构建高效合成血清素的细胞工厂", True),
        ("新型纳米材料用于药物递送", "开发了基于二氧化硅的纳米颗粒用于抗肿瘤药物递送", False),
        ("固相合成法制备抗菌肽", "采用固相合成策略（SPPS）制备了一系列抗菌肽，并测试其抗菌活性", False),
        ("西湖生物完成超亿元战略融资", "西湖生物医药科技有限公司宣布完成新一轮超亿元战略融资，加速红细胞药物平台临床开发", True),
        ("曾安平院士：一碳生物技术重塑未来生物制造产业", "德国科学院院士、西湖大学曾安平教授在绿碳科学发展研讨会上作引导报告，系统介绍一碳生物技术发展现状与最新进展", True),
        ("国家重点研发计划合成生物学重点专项申报指南征求意见", "国家重点研发计划合成生物学重点专项2026年度项目申报指南已通过国家科技管理信息系统向社会征求意见", True),
        ("深圳科学家领衔发布亚洲首个合成细胞技术路线图", "中国科学院深圳先进技术研究院刘陈立研究员领衔，发布亚洲首个合成细胞10年技术路线图", True),
    ]

    passed = 0
    for title, summary, expected in test_cases:
        result, reason, confidence = is_synbio_relevant(title, summary)
        status = "PASS" if result == expected else "FAIL"
        if result == expected:
            passed += 1
        print(f"{status}: {title[:40]}... ({confidence}) — {reason}")

    print(f"\n{passed}/{len(test_cases)} passed")
    if passed != len(test_cases):
        raise SystemExit(1)
