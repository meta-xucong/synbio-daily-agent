#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LLM-based Synthetic Biology Relevance Judge
合成生物学领域相关性智能判断模块

设计原则：
- 用LLM的语义理解能力替代硬编码关键词穷举
- 明确区分"合成生物学"（工程化改造生物系统）vs"纯化学合成"vs"基础生物学"
- 缓存结果避免重复API调用
- LLM不可用时自动降级为语义启发式
"""

import json
import os
import re
import hashlib
from pathlib import Path
from typing import Dict, Any, Tuple, Optional

try:
    from .settings import DATA_DIR
except ImportError:
    DATA_DIR = Path(__file__).resolve().parents[1] / "data"

CACHE_FILE = DATA_DIR / "llm_judge_cache.json"

# 判断提示词——这是核心"通用思维"，定义了什么才叫合成生物学
_JUDGE_PROMPT_TEMPLATE = """你是一位合成生物学领域专家。请严格判断以下信息是否属于"合成生物学"（Synthetic Biology）领域。

【合成生物学的核心定义】
通过工程学方法（设计-构建-测试-学习循环）对生物系统进行改造、重构或从头构建，以实现可预测的功能或生产目标产物。关键特征：
1. 工程化思维：标准化、模块化、可预测性
2. 底盘细胞/微生物细胞工厂的构建与优化
3. 基因编辑、代谢工程、途径重构、基因线路设计
4. DNA合成、蛋白质工程、酶定向进化
5. 用改造后的生物体（细胞/微生物/酵母/酶）生产化学品、材料、药物、燃料、食品等
6. 自动化、高通量、AI辅助设计

【明确不属于合成生物学】
- 纯化学合成（固相合成多肽SPPS、有机合成、化工合成材料/燃料/香料）
- 纯基础生物学研究（自然免疫通路、神经信号机制、受体结合、细胞凋亡等，除非明确进行了工程化改造）
- 传统发酵工艺（仅描述"发酵生产"而无基因工程/代谢工程改造）
- 天然产物提取、分离纯化、结构鉴定
- 临床医学（病例报告、临床试验、流行病学）
- 传统生物信息学分析（仅测序、比对、注释）

【判断标准】
如果研究内容涉及"对生物体进行工程化改造以实现特定功能或产物"，则属于合成生物学。
如果研究仅是"观察自然生物现象"或"用化学方法合成物质"，则不属于。

请判断以下信息：
标题：{title}
摘要：{summary}
URL：{url}

请用严格JSON格式回答（不要markdown代码块，纯JSON）：
{{"is_synbio": true/false, "reason": "一句话解释", "confidence": "high/medium/low"}}"""


def _load_cache() -> Dict[str, Any]:
    if CACHE_FILE.exists():
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_cache(cache: Dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


def _make_key(title: str, summary: str) -> str:
    text = f"{title}|{summary}"
    return hashlib.md5(text.encode("utf-8")).hexdigest()[:16]


def _call_llm_api(prompt: str) -> Dict[str, Any]:
    """Call LLM API. Supports OpenAI-compatible endpoints."""
    api_key = os.getenv("OPENAI_API_KEY") or os.getenv("LLM_API_KEY")
    api_base = os.getenv("LLM_API_BASE", "https://api.openai.com/v1")
    model = os.getenv("LLM_MODEL", "gpt-4o-mini")

    if not api_key:
        raise RuntimeError("No LLM API key configured (OPENAI_API_KEY or LLM_API_KEY)")

    try:
        import requests
    except ImportError:
        raise RuntimeError("requests library not available")

    response = requests.post(
        f"{api_base}/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": "你是一个合成生物学领域专家，请严格按要求输出JSON。"},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.0,
            "max_tokens": 200,
        },
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()
    content = data["choices"][0]["message"]["content"]
    # Clean possible markdown code block
    content = content.strip()
    if content.startswith("```json"):
        content = content[7:]
    if content.startswith("```"):
        content = content[3:]
    if content.endswith("```"):
        content = content[:-3]
    content = content.strip()
    return json.loads(content)


def _semantic_heuristic_judge(title: str, summary: str, url: str) -> Tuple[bool, str, str]:
    """
    Semantic heuristic fallback when LLM API is unavailable.
    Smarter than naive keyword matching — uses context and signal weighting.
    Key principle: distinguish "engineering biology" (synbio) from "studying natural biology" (basic science).
    """
    text = f"{title} {summary}".lower()

    # 强正向信号：明确的工程化改造生物系统
    strong_positive = [
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
    ]

    # 强负向信号：明确不是合成生物学（化学合成、基础医学、基础研究）
    strong_negative = [
        "固相合成", "spps", "化学合成", "有机合成", "全合成",
        "天然产物提取", "分离纯化", "结构鉴定", "晶体结构", "x射线",
        "免疫组化", "western blot", "pcr检测", "测序分析", "基因组测序",
        "临床试验", "病例报告", "流行病学", "回顾性分析", "meta分析",
        "纯化学", "化工合成", "石油化工", "煤化工", "费托合成",
        "药物化学", "高分子化学", "材料科学", "纳米材料",
        "传统发酵", "自然发酵", "野生菌株", "未改造",
    ]

    # 基础生物学自然过程信号——如果主导是自然过程且无工程化，则排除
    natural_process_signals = [
        # 神经科学
        "神经元", "神经递质", "神经信号", "神经环路", "神经回路", "神经传导", "神经连接",
        "突触传递", "突触可塑性", "神经可塑性", "中缝背核",
        # 信号与受体
        "信号通路", "信号转导", "信号传导", "信号级联", "信号传递",
        "受体结合", "受体激活", "配体结合", "配体识别", "受体介导",
        # 免疫与炎症
        "免疫应答", "免疫反应", "炎症反应", "炎症因子", "细胞因子",
        "细胞凋亡", "细胞坏死", "细胞自噬", "细胞焦亡",
        # 生理与疾病
        "生理过程", "自然过程", "内源性", "天然产物", "内源合成",
        "疾病机制", "发病机制", "病理机制", "病理生理", "致病机制",
        "动物模型", "小鼠模型", "大鼠模型", "临床前",
        # 行为与认知
        "行为学", "社交行为", "学习记忆", "认知功能", "情绪调节",
    ]

    # 上下文模式：工程化改造 + 生物体
    has_engineering = bool(re.search(
        r"(工程|改造|构建|设计|重构|编辑|优化|组装|装配|从头).{0,15}(生物|细胞|微生物|菌|酵母|大肠杆菌|芽孢杆菌|棒杆菌|酶|基因|代谢|途径)",
        text,
    ))
    has_bio_manufacturing = bool(re.search(
        r"(生物|细胞|微生物|酶).{0,15}(生产|制造|合成|工厂|发酵|催化|转化|降解)",
        text,
    ))
    has_platform_tech = bool(re.search(
        r"(平台|技术|工具|方法).{0,10}(合成|编辑|改造|工程|设计)",
        text,
    ))

    pos_score = sum(1 for p in strong_positive if p in text)
    neg_score = sum(1 for n in strong_negative if n in text)
    natural_score = sum(1 for n in natural_process_signals if n in text)

    # 明确的基础生物学/神经科学/免疫学研究（自然过程主导 + 无工程化改造）
    # 宽松标准：只要出现1个自然过程信号且无正向工程化信号，就判定为基础生物学
    if natural_score >= 1 and pos_score == 0 and not has_engineering and not has_bio_manufacturing:
        return False, "属于基础生物学研究（自然生理过程/神经/免疫/疾病机制），无工程化改造特征", "high"

    # 明确的化学合成/基础医学
    if neg_score >= 2 and pos_score == 0:
        return False, "明确属于传统化学/基础生物学，无合成生物学工程化特征", "high"

    # 明确的合成生物学
    if pos_score >= 2 or (pos_score >= 1 and (has_engineering or has_bio_manufacturing)):
        return True, "具有合成生物学工程化改造生物系统的特征", "high"

    if pos_score >= 1 and has_platform_tech:
        return True, "合成生物学平台技术或工具开发", "high"

    if pos_score >= 1:
        return True, "含有合成生物学相关术语，上下文相关", "medium"

    # 有自然过程信号且无任何工程化信号（兜底）
    if natural_score >= 1 and not has_engineering and not has_bio_manufacturing:
        return False, "偏向基础生物学自然过程研究，无工程化特征", "medium"

    if neg_score >= 1 and not has_engineering and not has_bio_manufacturing:
        return False, "偏向传统方法或基础研究，无工程化特征", "medium"

    # 模糊项：宁可误收，不可漏报（低置信度通过）
    return True, "语义模糊，默认保留待人工复核", "low"


def is_synbio_relevant(
    title: str = "",
    summary: str = "",
    url: str = "",
    force_heuristic: bool = False,
) -> Tuple[bool, str, str]:
    """
    Smart judgment of whether content belongs to synthetic biology.

    Args:
        title: Article title
        summary: Article summary or abstract
        url: Source URL
        force_heuristic: If True, always use heuristic instead of LLM

    Returns:
        (is_relevant, reason, confidence)
        - is_relevant: bool
        - reason: str explanation
        - confidence: "high" | "medium" | "low" | "llm" | "cached"
    """
    cache = _load_cache()
    key = _make_key(title, summary)

    if key in cache:
        entry = cache[key]
        return entry["is_synbio"], entry["reason"], entry.get("confidence", "cached")

    if not force_heuristic:
        try:
            prompt = _JUDGE_PROMPT_TEMPLATE.format(title=title, summary=summary, url=url)
            result = _call_llm_api(prompt)
            is_synbio = bool(result.get("is_synbio", False))
            reason = str(result.get("reason", "LLM判断"))
            confidence = str(result.get("confidence", "llm"))
            cache[key] = {
                "is_synbio": is_synbio,
                "reason": reason,
                "confidence": confidence,
                "source": "llm",
                "title": title[:80],
            }
            _save_cache(cache)
            return is_synbio, reason, confidence
        except Exception as e:
            # LLM调用失败，降级到启发式
            pass

    # Fallback to semantic heuristic
    is_synbio, reason, confidence = _semantic_heuristic_judge(title, summary, url)
    cache[key] = {
        "is_synbio": is_synbio,
        "reason": reason,
        "confidence": confidence,
        "source": "heuristic",
        "title": title[:80],
    }
    _save_cache(cache)
    return is_synbio, reason, confidence


def batch_judge(items: list[Dict[str, Any]]) -> list[Tuple[bool, str, str]]:
    """Judge a batch of items. Returns list of (is_relevant, reason, confidence)."""
    results = []
    for item in items:
        title = str(item.get("title", ""))
        summary = str(item.get("summary", ""))
        url = str(item.get("url", ""))
        results.append(is_synbio_relevant(title, summary, url))
    return results


if __name__ == "__main__":
    # Self-test
    test_cases = [
        {
            "title": "Nature子刊：四川大学开发非经典WNT骨合成肽",
            "summary": "通过AlphaFold赋能的结构预测与虚拟筛选，鉴定出WNT7BRTID作为WNT衍生骨合成肽",
            "expected": True,
        },
        {
            "title": "Cell：IL-1β信号通过中缝背核神经元调控社交行为",
            "summary": "IL-1β通过结合大脑中缝背核神经元上的IL-1R1受体，激活神经连接，主动抑制社交行为",
            "expected": False,
        },
        {
            "title": "湖北大学改造地衣芽孢杆菌高效合成血清素",
            "summary": "通过多维代谢工程策略在地衣芽孢杆菌中构建高效合成血清素的细胞工厂",
            "expected": True,
        },
        {
            "title": "新型纳米材料用于药物递送",
            "summary": "开发了基于二氧化硅的纳米颗粒用于抗肿瘤药物递送",
            "expected": False,
        },
    ]

    for case in test_cases:
        result, reason, confidence = is_synbio_relevant(
            case["title"], case["summary"], force_heuristic=True
        )
        status = "✅" if result == case["expected"] else "❌"
        print(f"{status} {case['title'][:40]}... → {result} ({confidence}): {reason}")
