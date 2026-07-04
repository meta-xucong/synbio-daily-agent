#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Synthetic Biology Relevance Judge.

This module provides a semantic audit layer for daily-report candidates:
- optional Anthropic-compatible LLM judging through environment variables
- dependency-free heuristic fallback for offline/CI execution
- backward-compatible tuple API for older report_pipeline callers
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional, Protocol, Tuple
from urllib.request import Request, urlopen


def _load_env() -> None:
    """Load .env file from project root (standard-library only, no dotenv dep)."""
    if os.getenv("SYNBIO_SKIP_DOTENV") in {"1", "true", "TRUE", "yes", "YES"}:
        return
    # resolve project root relative to this script: scripts/ -> repo root
    script_dir = Path(__file__).resolve().parent
    project_root = script_dir.parent

    secrets_path = project_root / "config" / "runtime_secrets.local.json"
    if secrets_path.is_file():
        try:
            payload = json.loads(secrets_path.read_text(encoding="utf-8"))
        except Exception:
            payload = None
        if isinstance(payload, dict):
            for key, value in payload.items():
                key = str(key).strip()
                if not key or os.getenv(key) is not None:
                    continue
                if isinstance(value, list):
                    os.environ[key] = json.dumps(value, ensure_ascii=False)
                elif value is not None:
                    os.environ[key] = str(value)

    env_path = project_root / ".env"
    if not env_path.is_file():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        # only set if not already present in the environment
        if key and os.getenv(key) is None:
            os.environ[key] = value


_load_env()


def _default_model() -> str:
    """Return default model based on the configured base URL."""
    base = os.getenv("ANTHROPIC_BASE_URL", "").lower()
    if (
        "api.kimi.com" in base
        or "aiself.vip" in base
        or "127.0.0.1:15721" in base
        or "localhost:15721" in base
    ):
        return "kimi-for-coding"
    return "claude-3-5-sonnet-20241022"


DEFAULT_MODEL = _default_model()
MIN_APPROVAL_CONFIDENCE = 0.70
ALLOWED_RELEVANCE = {"core_synbio", "adjacent", "out_of_scope", "uncertain"}
ALLOWED_SECTIONS = {"news", "research", "funding", "policy", "events"}
_TRUE_VALUES = {"1", "true", "TRUE", "yes", "YES", "on", "ON"}
_FALSE_VALUES = {"0", "false", "FALSE", "no", "NO", "off", "OFF"}
_MATERIAL_COMPANY_EVENT_TERMS = frozenset([
    "实控人", "实际控制人", "董事长", "总经理", "高管", "刑事拘留", "被刑拘", "被拘留",
    "立案", "证监会", "监管", "处罚", "问询函", "停牌", "重大事项", "公告", "辞职",
])
_COMPANY_BIOMFG_TERMS = frozenset([
    "主营业务为生物制造", "主营业务是生物制造", "合成生物", "生物制造",
    "biomanufacturing", "synthetic biology", "precision fermentation",
])


def provider_uses_ascii_prompts(base_url: str | None) -> bool:
    """Return whether prompts should stay ASCII on the provider wire.

    Some Anthropic-compatible gateways accept UTF-8 JSON but forward the message
    text to the upstream model through a non-UTF-8 path, turning Chinese into
    question marks.  Keeping the prompt ASCII and embedding Chinese as literal
    JSON unicode escapes preserves the information for those gateways.
    """
    setting = (os.getenv("SYNBIO_LLM_ASCII_PROMPTS") or "auto").strip()
    if setting in _TRUE_VALUES:
        return True
    if setting in _FALSE_VALUES:
        return False
    return "aiself.vip" in (base_url or "").lower()


def provider_supports_thinking_disable(base_url: str | None, model: str | None = None) -> bool:
    """Return whether the provider expects explicit thinking disable for stable JSON output."""
    base = (base_url or "").lower()
    model_name = (model or "").lower()
    return (
        "api.kimi.com" in base
        or "aiself.vip" in base
        or "127.0.0.1:15721" in base
        or "localhost:15721" in base
        or "kimi" in model_name
    )


def _material_company_event_override(item: dict[str, Any], decision: Decision) -> Decision:
    """Keep material events for explicitly synbio/biomanufacturing companies.

    The daily report is an industry-intelligence product.  A criminal detention,
    regulatory action, or other material event at a company whose candidate text
    explicitly identifies its synthetic-biology/biomanufacturing business can be
    important even when the article itself is not a technical R&D story.
    """
    if decision.is_approved:
        return decision
    text = " ".join(
        str(item.get(key, "") or "")
        for key in ("title", "summary", "page_title", "page_text", "source_query")
    ).lower()
    if not any(term.lower() in text for term in _COMPANY_BIOMFG_TERMS):
        return decision
    if not any(term.lower() in text for term in _MATERIAL_COMPANY_EVENT_TERMS):
        return decision
    evidence = [
        str(item.get("title") or item.get("summary") or item.get("url") or "material event")[:180]
    ]
    for term in _COMPANY_BIOMFG_TERMS:
        if term.lower() in text:
            evidence.append(term)
            break
    for term in _MATERIAL_COMPANY_EVENT_TERMS:
        if term.lower() in text:
            evidence.append(term)
            break
    return Decision(
        is_approved=True,
        domain_relevance="adjacent",
        confidence=max(decision.confidence, 0.78),
        reason="Material event at a company explicitly tied to synthetic biology or biomanufacturing.",
        evidence_spans=evidence,
        section="news",
        provider=f"{decision.provider}+material_event_rule",
        raw_response=decision.raw_response,
        decision="include",
    )


@dataclass
class Decision:
    """Structured relevance judgment for one candidate item."""

    is_approved: bool | None = None
    domain_relevance: str = "uncertain"
    confidence: float = 0.0
    reason: str = ""
    evidence_spans: list[str] = field(default_factory=list)
    section: Optional[str] = None
    reject_reason: Optional[str] = None
    provider: str = "heuristic"
    raw_response: Optional[str] = None
    decision: Optional[str] = None

    def __post_init__(self) -> None:
        status = str(self.decision or "").lower()
        if status not in {"include", "reject", "escalate"}:
            status = "include" if self.is_approved else "reject"
        self.decision = status
        if self.is_approved is None:
            self.is_approved = status == "include"
        if self.domain_relevance not in ALLOWED_RELEVANCE:
            self.domain_relevance = "uncertain"
        try:
            self.confidence = float(self.confidence)
        except (TypeError, ValueError):
            self.confidence = 0.0
        self.confidence = max(0.0, min(1.0, self.confidence))
        if self.section not in ALLOWED_SECTIONS:
            self.section = None
        self.evidence_spans = [
            str(span).strip()[:300]
            for span in (self.evidence_spans or [])
            if str(span).strip()
        ][:5]
        if self.is_approved:
            self.is_approved = (
                self.decision == "include"
                and
                self.domain_relevance in {"core_synbio", "adjacent"}
                and self.confidence >= MIN_APPROVAL_CONFIDENCE
                and bool(self.evidence_spans)
            )

    def reject_message(self) -> str:
        return self.reject_reason or self.reason or "领域相关性不足"


# Backward-compatible name used by existing Codex tests and report_pipeline.
RelevanceDecision = Decision


class JudgeClient(Protocol):
    @property
    def is_configured(self) -> bool:
        ...

    def judge(self, item: dict[str, Any]) -> Decision:
        ...


@dataclass
class DateDecision:
    """Structured judgment for whether a candidate date looks like the real publish/event date."""

    is_date_valid: bool = True
    confidence: float = 0.0
    reason: str = ""
    evidence_spans: list[str] = field(default_factory=list)
    suspected_actual_date: Optional[str] = None
    provider: str = "heuristic"
    raw_response: Optional[str] = None

    def __post_init__(self) -> None:
        try:
            self.confidence = float(self.confidence)
        except (TypeError, ValueError):
            self.confidence = 0.0
        self.confidence = max(0.0, min(1.0, self.confidence))
        self.evidence_spans = [
            str(span).strip()[:300]
            for span in (self.evidence_spans or [])
            if str(span).strip()
        ][:5]
        if self.suspected_actual_date:
            self.suspected_actual_date = str(self.suspected_actual_date).strip()[:40]


DateValidationDecision = DateDecision


# Strong positive signals: engineered biological systems and biomanufacturing.
_STRONG_POSITIVE = frozenset([
    "代谢工程", "基因编辑", "crispr", "基因线路", "基因回路", "基因电路",
    "细胞工厂", "底盘细胞", "底盘菌", "合成生物", "合成生物学", "synthetic biology",
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
    "cell-free", "biosynthesis", "biosynthetic", "synthetic genomics",
    "metabolic engineering", "cell factory", "engineered microbe",
    "engineered microbes", "engineered yeast", "precision fermentation",
    "pathway engineering", "genome editing", "protein engineering",
    "gene circuit", "dna synthesis", "fermentation",
])

# Minimum bio signals: if a candidate lacks ANY of these, it is almost certainly not biology-related.
_MINIMUM_BIO_SIGNALS = frozenset([
    "cell", "cells", "gene", "genes", "protein", "proteins", "enzyme", "enzymes",
    "bacteria", "bacterial", "microbe", "microbes", "microbial", "virus", "viral",
    "organism", "organisms", "biological", "biotech", "biotechnology", "biomanufacturing",
    "genome", "genomic", "genomics", "dna", "rna", "metabolism", "metabolic",
    "fermentation", "ferment", "biosynthesis", "biosynthetic", "synthetic", "engineering",
    "pathway", "pathways", "strain", "strains", "plasmid", "vector", "vectors", "host",
    "expression", "recombinant", "sequencing", "crispr", "editing", "molecular",
    "biochemistry", "biochemical", "biofuel", "biomaterial", "bioprocess",
    "organism", "organisms", "microorganism", "microorganisms", "bioreactor",
    "酵母", "细菌", "基因", "蛋白", "细胞", "代谢", "发酵", "合成", "工程",
    "编辑", "序列", "测序", "酶", "菌株", "质粒", "载体", "表达", "重组",
    "生物", "分子", "生化", "微生物", "有机体", "生物反应器", "生物技术",
    "途径", "通路", "改造", "构建", "设计", "优化", "调控",
])

_STRONG_NEGATIVE = frozenset([
    "固相合成", "spps", "化学合成", "有机合成", "全合成",
    "天然产物提取", "分离纯化", "结构鉴定", "晶体结构", "x射线",
    "免疫组化", "western blot", "pcr检测", "测序分析", "基因组测序",
    "临床试验", "病例报告", "流行病学", "回顾性分析", "meta分析",
    "纯化学", "化工合成", "石油化工", "煤化工", "费托合成",
    "药物化学", "高分子化学", "材料科学", "纳米材料",
    "传统发酵", "自然发酵", "野生菌株", "未改造",
    "clinical trial", "case report", "epidemiology", "retrospective",
    "chemical synthesis", "organic synthesis", "total synthesis",
])

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
    "neuronal", "neuron", "neurons", "neural circuit", "neural circuits", "synaptic",
    "receptor signaling", "receptor", "receptors", "endogenous receptor", "endogenous", "social behavior",
    "signal transduction", "signaling pathway", "signaling", "pathway", "pathways",
    "immune response", "immune", "inflammatory response", "inflammation", "inflammatory",
    "cytokine", "cytokines", "il-1", "interleukin", "interferon", "chemokine",
    "apoptosis", "autophagy", "necrosis", "pyroptosis", "cell death",
    "natural process", "natural product", "innate", "innate immunity", "adaptive immunity",
    "neurotransmitter", "neurotransmission", "synapse", "synapses", "connectivity",
    "behavior", "behaviour", "cognitive", "cognition", "memory", "learning",
    "physiology", "physiological", "pathology", "pathological", "disease mechanism",
])

_RE_ENGINEERING = re.compile(
    r"(工程|改造|构建|设计|重构|编辑|优化|组装|装配|从头).{0,15}(生物|细胞|微生物|菌|酵母|大肠杆菌|芽孢杆菌|棒杆菌|酶|基因|代谢|途径)"
)
_RE_BIO_MANUFACTURING = re.compile(
    r"(生物|细胞|微生物|酶).{0,15}(生产|制造|合成|工厂|发酵|催化|转化|降解)"
)
_RE_PLATFORM_TECH = re.compile(
    r"(平台|技术|工具|方法).{0,10}(合成|编辑|改造|工程|设计)"
)


def _count_hits(text_lower: str, terms: frozenset[str]) -> int:
    return sum(1 for term in terms if term in text_lower)


def _cache_path() -> Path | None:
    path_text = os.getenv("SYNBIO_LLM_JUDGE_CACHE")
    if path_text:
        return Path(path_text)
    home = os.getenv("SYNBIO_DAILY_HOME")
    if home:
        return Path(home) / "data" / "llm_judge_cache.json"
    return None


def _cache_key(item: dict[str, Any]) -> str:
    compact = {
        "title": str(item.get("title", "")),
        "summary": str(item.get("summary", "")),
        "url": str(item.get("url", "")),
        "type": str(item.get("type", "") or item.get("section", "")),
    }
    payload = json.dumps(compact, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _decision_from_dict(data: dict[str, Any]) -> Decision:
    return Decision(
        is_approved=bool(data.get("is_approved", False)),
        domain_relevance=str(data.get("domain_relevance", "uncertain")),
        confidence=float(data.get("confidence", 0.0) or 0.0),
        reason=str(data.get("reason", "") or ""),
        evidence_spans=list(data.get("evidence_spans") or []),
        section=data.get("section"),
        reject_reason=data.get("reject_reason"),
        provider=str(data.get("provider", "cache") or "cache"),
        raw_response=data.get("raw_response"),
    )


def _load_cached_decision(item: dict[str, Any]) -> Decision | None:
    path = _cache_path()
    if not path or not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        entry = data.get(_cache_key(item))
        if isinstance(entry, dict):
            decision = _decision_from_dict(entry)
            decision.provider = "cached"
            return decision
    except Exception:
        return None
    return None


def _store_cached_decision(item: dict[str, Any], decision: Decision) -> None:
    path = _cache_path()
    if not path:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {}
        if path.exists():
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                data = loaded
        payload = asdict(decision)
        payload.pop("raw_response", None)
        data[_cache_key(item)] = payload
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        return


def heuristic_relevance_decision(item: dict[str, Any]) -> Decision:
    """Local dependency-free fallback relevance decision."""
    title = str(item.get("title", ""))
    summary = str(item.get("summary", ""))
    url = str(item.get("url", ""))
    section = str(item.get("type") or item.get("section") or "") or None
    text = f"{title} {summary}".lower()

    pos_score = _count_hits(text, _STRONG_POSITIVE)
    neg_score = _count_hits(text, _STRONG_NEGATIVE)
    natural_score = _count_hits(text, _NATURAL_PROCESS)
    has_engineering = bool(_RE_ENGINEERING.search(text))
    has_bio_mfg = bool(_RE_BIO_MANUFACTURING.search(text))
    has_platform = bool(_RE_PLATFORM_TECH.search(text))

    evidence = [
        term for term in sorted(_STRONG_POSITIVE, key=len, reverse=True)
        if term in text
    ][:3]
    if not evidence and (has_engineering or has_bio_mfg or has_platform):
        evidence = [title or summary[:80] or url]

    if natural_score >= 1 and pos_score == 0 and not has_engineering and not has_bio_mfg:
        return Decision(
            is_approved=False,
            domain_relevance="out_of_scope",
            confidence=0.92,
            reason="基础生物学自然过程，无工程化改造特征",
            reject_reason="基础生物学自然过程，无合成生物工程化证据",
            section=section,
        )

    if neg_score >= 2 and pos_score == 0:
        return Decision(
            is_approved=False,
            domain_relevance="out_of_scope",
            confidence=0.90,
            reason="传统化学/基础医学，无合成生物工程化特征",
            reject_reason="传统化学/基础医学，无合成生物工程化证据",
            section=section,
        )

    if pos_score >= 2 or (pos_score >= 1 and (has_engineering or has_bio_mfg)):
        return Decision(
            is_approved=True,
            domain_relevance="core_synbio",
            confidence=0.90,
            reason="合成生物学工程化改造生物系统",
            evidence_spans=evidence,
            section=section,
        )

    if pos_score >= 1 and has_platform:
        return Decision(
            is_approved=True,
            domain_relevance="core_synbio",
            confidence=0.86,
            reason="合成生物学平台技术或工具",
            evidence_spans=evidence,
            section=section,
        )

    if pos_score >= 1:
        return Decision(
            is_approved=True,
            domain_relevance="adjacent",
            confidence=0.74,
            reason="含合成生物学相关术语",
            evidence_spans=evidence,
            section=section,
        )

    if natural_score >= 1 and not has_engineering and not has_bio_mfg:
        return Decision(
            is_approved=False,
            domain_relevance="out_of_scope",
            confidence=0.80,
            reason="偏向基础生物学自然过程，无工程化特征",
            reject_reason="偏向基础生物学自然过程",
            section=section,
        )

    if neg_score >= 1 and not has_engineering and not has_bio_mfg:
        return Decision(
            is_approved=False,
            domain_relevance="out_of_scope",
            confidence=0.78,
            reason="偏向传统方法或基础研究，无工程化特征",
            reject_reason="偏向传统方法或基础研究",
            section=section,
        )

    # Minimum bio-signal gate: if the text contains absolutely no biology-related
    # terminology, it cannot be synthetic biology (or even biology adjacent).
    bio_signal = _count_hits(text, _MINIMUM_BIO_SIGNALS)
    if bio_signal == 0:
        return Decision(
            is_approved=False,
            domain_relevance="out_of_scope",
            confidence=0.95,
            reason="内容不含任何生物学术语，明显不属于合成生物学或生物学领域",
            reject_reason="非生物学内容，完全超出合成生物学范围",
            section=section,
        )

    return Decision(
        is_approved=False,
        domain_relevance="uncertain",
        confidence=0.55,
        reason="本地语义fallback未找到明确的合成生物工程化证据，保守拒绝",
        reject_reason="未找到明确的合成生物工程化证据",
        evidence_spans=[title or summary[:80] or url],
        section=section,
    )


def _build_prompt(item: dict[str, Any], *, ascii_safe: bool = False) -> str:
    compact = {
        "title": str(item.get("title", ""))[:300],
        "source": str(item.get("source", ""))[:120],
        "date": str(item.get("date", ""))[:80],
        "summary": str(item.get("summary", ""))[:1200],
        "url": str(item.get("url", ""))[:300],
        "type": str(item.get("type", ""))[:40],
        "page_title": str(item.get("page_title", ""))[:300],
        "page_text": str(item.get("page_text", ""))[:2500],
    }
    if ascii_safe:
        return (
            "You are the semantic review gate for a synthetic-biology daily report.\n"
            "Judge whether the candidate should be included. Use only the fields in "
            "candidate_json; do not add outside facts.\n"
            "Important: candidate_json contains JSON unicode escape sequences such as "
            "\\u5408\\u6210\\u751f\\u7269. Decode them semantically before judging.\n"
            "Core scope includes engineered biological systems, cell factories, "
            "metabolic engineering, genetic circuits or editing, chassis cells, "
            "precision fermentation, biomanufacturing, enzyme/protein engineering, "
            "and artificial metabolic pathways.\n"
            "Also include material company events as adjacent industry news when "
            "the candidate explicitly says the company is in synthetic biology or "
            "biomanufacturing and the event is material, such as a controller or "
            "chairperson detention, regulatory investigation, major penalty, IPO, "
            "or major announcement.\n"
            "Reject ordinary clinical news, basic natural biology, pure chemical "
            "synthesis, generic materials, and traditional pharma news when there is "
            "no engineered-biology or biomanufacturing evidence.\n"
            "Return strict JSON only, no Markdown and no code fences. Schema:\n"
            "{"
            '"is_approved":true,'
            '"domain_relevance":"core_synbio|adjacent|out_of_scope|uncertain",'
            '"confidence":0.0,'
            '"reason":"short reason",'
            '"evidence_spans":["evidence copied or decoded from candidate_json"],'
            '"section":"news|research|funding|policy|events",'
            '"reject_reason":null'
            "}\n"
            "candidate_json:\n"
            f"{json.dumps(compact, ensure_ascii=True)}"
        )
    return (
        "你是合成生物行业日报的审稿人。判断候选信息是否应收录。\n"
        "只根据给定标题、摘要、页面标题/正文判断，不要引入外部知识。\n"
        "合成生物核心包括：工程化改造生物系统、细胞工厂、代谢工程、基因线路/编辑、"
        "底盘细胞、精准发酵、生物制造、酶/蛋白工程、人工代谢途径等。\n"
        "若候选明确说明公司属于合成生物/生物制造业务，且事件是实控人/董事长刑拘、"
        "监管立案、重大处罚、IPO、重大公告等公司重大事项，可作为 adjacent 行业新闻收录。\n"
        "普通临床、基础生物学自然机制、纯化学合成、材料、传统医药新闻应拒绝。\n"
        "必须输出纯 JSON，不要 Markdown。schema:\n"
        "{"
        '"is_approved":true,'
        '"domain_relevance":"core_synbio|adjacent|out_of_scope|uncertain",'
        '"confidence":0.0,'
        '"reason":"短理由",'
        '"evidence_spans":["原文证据片段"],'
        '"section":"news|research|funding|policy|events",'
        '"reject_reason":null'
        "}\n"
        "候选信息:\n"
        f"{json.dumps(compact, ensure_ascii=False)}"
    )


def _build_date_validation_prompt(
    item: dict[str, Any],
    report_date: str,
    *,
    ascii_safe: bool = False,
) -> str:
    compact = {
        "title": str(item.get("title", ""))[:300],
        "source": str(item.get("source", ""))[:120],
        "type": str(item.get("type", ""))[:40],
        "candidate_date": str(item.get("date", ""))[:40],
        "search_date": str(item.get("search_date", ""))[:40],
        "summary": str(item.get("summary", ""))[:2000],
        "url": str(item.get("url", ""))[:300],
        "date_verification": item.get("date_verification") if isinstance(item.get("date_verification"), dict) else {},
        "report_date": str(report_date or "")[:40],
    }
    if ascii_safe:
        return (
            "You are the date-integrity gate for a synthetic-biology daily report.\n"
            "Decide whether candidate_json.candidate_date is likely the actual article publish date or actual event date.\n"
            "Reject dates that look like cached page time, footer/recent-content date, copyright date, project start/plan date, or another historical date mentioned inside the article.\n"
            "Accept only when the candidate_date likely matches the article's real publish date or the real event date being reported.\n"
            "Return strict JSON only, no Markdown. Schema:\n"
            "{"
            '"is_date_valid":true,'
            '"confidence":0.0,'
            '"reason":"short reason",'
            '"evidence_spans":["evidence from candidate_json"],'
            '"suspected_actual_date":null'
            "}\n"
            "candidate_json:\n"
            f"{json.dumps(compact, ensure_ascii=True)}"
        )
    return (
        "你是合成生物行业日报的日期审稿人。\n"
        "判断 candidate_date 是否像文章真正的发布日期或真正的事件日期。\n"
        "如果它更像页脚最近内容日期、缓存时间、版权年份、项目计划日期、历史回顾日期，就判定为无效并建议排除。\n"
        "只有当 candidate_date 很像这篇文章自己的真实发布时间或活动真实日期时，才判定有效。\n"
        "必须输出纯 JSON，不要 Markdown。schema:\n"
        "{"
        '"is_date_valid":true,'
        '"confidence":0.0,'
        '"reason":"短理由",'
        '"evidence_spans":["原文证据片段"],'
        '"suspected_actual_date":null'
        "}\n"
        "候选信息:\n"
        f"{json.dumps(compact, ensure_ascii=False)}"
    )


def _extract_json_object(text: str) -> dict[str, Any]:
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError("LLM response did not contain a JSON object")
    parsed = json.loads(match.group(0))
    if not isinstance(parsed, dict):
        raise ValueError("LLM JSON response must be an object")
    return parsed


def normalize_llm_decision(data: dict[str, Any], raw_response: str | None = None) -> Decision:
    raw_decision = str(data.get("decision", "") or "").lower()
    if "is_approved" in data:
        is_approved = bool(data.get("is_approved"))
    else:
        is_approved = raw_decision == "include"
    relevance = str(data.get("domain_relevance", "uncertain") or "uncertain").lower()
    if relevance not in ALLOWED_RELEVANCE:
        relevance = "uncertain"
    try:
        confidence = float(data.get("confidence", 0.0) or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    evidence = data.get("evidence_spans") or []
    if not isinstance(evidence, list):
        evidence = [str(evidence)]
    section = str(data.get("section") or "").lower() or None
    reject_reason = data.get("reject_reason")
    return Decision(
        is_approved=is_approved,
        domain_relevance=relevance,
        confidence=confidence,
        reason=str(data.get("reason") or "").strip()[:500],
        evidence_spans=[str(item) for item in evidence],
        section=section,
        reject_reason=str(reject_reason).strip()[:500] if reject_reason else None,
        provider="llm",
        raw_response=raw_response,
        decision=raw_decision or None,
    )


def normalize_date_decision(data: dict[str, Any], raw_response: str | None = None) -> DateDecision:
    is_date_valid = bool(data.get("is_date_valid", False))
    try:
        confidence = float(data.get("confidence", 0.0) or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    evidence = data.get("evidence_spans") or []
    if not isinstance(evidence, list):
        evidence = [str(evidence)]
    return DateDecision(
        is_date_valid=is_date_valid,
        confidence=confidence,
        reason=str(data.get("reason") or "").strip()[:500],
        evidence_spans=[str(item) for item in evidence],
        suspected_actual_date=str(data.get("suspected_actual_date") or "").strip()[:40] or None,
        provider="llm",
        raw_response=raw_response,
    )


class LLMClient:
    """Minimal Anthropic-compatible Messages API client."""

    def __init__(
        self,
        base_url: str | None = None,
        auth_token: str | None = None,
        model: str | None = None,
        timeout: int = 45,
        opener: Callable[..., Any] = urlopen,
    ):
        self.base_url = (base_url or os.getenv("ANTHROPIC_BASE_URL") or "").rstrip("/")
        self.auth_token = auth_token if auth_token is not None else os.getenv("ANTHROPIC_AUTH_TOKEN")
        self.model = model or os.getenv("ANTHROPIC_MODEL") or DEFAULT_MODEL
        self.timeout = timeout
        self.opener = opener

    @property
    def is_configured(self) -> bool:
        return bool(self.base_url and self.auth_token)

    @property
    def use_ascii_prompts(self) -> bool:
        return provider_uses_ascii_prompts(self.base_url)

    @property
    def messages_url(self) -> str:
        if self.base_url.endswith("/v1"):
            return f"{self.base_url}/messages"
        return f"{self.base_url}/v1/messages"

    def complete_text(self, prompt: str, *, max_tokens: int = 600, temperature: float = 0) -> str:
        if not self.is_configured:
            raise RuntimeError("LLM provider is not configured")
        payload = {
            "model": self.model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": [{"role": "user", "content": prompt}],
        }
        if provider_supports_thinking_disable(self.base_url, self.model):
            payload["thinking"] = {"type": "disabled"}
        request = Request(
            self.messages_url,
            data=json.dumps(payload, ensure_ascii=self.use_ascii_prompts).encode("utf-8"),
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "x-api-key": self.auth_token or "",
                "Authorization": f"Bearer {self.auth_token or ''}",
                "anthropic-version": "2023-06-01",
            },
            method="POST",
        )
        with self.opener(request, timeout=self.timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
        parsed = json.loads(body)
        content = parsed.get("content")
        if isinstance(content, list):
            text = "\n".join(
                str(part.get("text", ""))
                for part in content
                if isinstance(part, dict)
            )
        elif isinstance(content, str):
            text = content
        else:
            text = str(parsed.get("text") or body)
        return text

    def judge(self, item: dict[str, Any]) -> Decision:
        text = self.complete_text(_build_prompt(item, ascii_safe=self.use_ascii_prompts), max_tokens=600, temperature=0)
        return normalize_llm_decision(_extract_json_object(text), raw_response=text)

    def final_audit(self, items: list[dict[str, Any]], report_date: str) -> list[dict[str, Any]]:
        text = self.complete_text(
            _build_final_audit_prompt(items, report_date, ascii_safe=self.use_ascii_prompts),
            max_tokens=1200,
            temperature=0,
        )
        return _extract_json_array(text)

    def judge_date(self, item: dict[str, Any], report_date: str) -> DateDecision:
        text = self.complete_text(
            _build_date_validation_prompt(item, report_date, ascii_safe=self.use_ascii_prompts),
            max_tokens=400,
            temperature=0,
        )
        return normalize_date_decision(_extract_json_object(text), raw_response=text)


AnthropicRelevanceClient = LLMClient


def llm_relevance_decision(item: dict[str, Any], client: JudgeClient | None = None) -> Decision:
    """Return a provider-backed relevance decision, raising on missing/failed provider."""
    cached = _load_cached_decision(item)
    if cached is not None:
        return cached
    llm_client = client or LLMClient()
    decision = llm_client.judge(item)
    _store_cached_decision(item, decision)
    return decision


def relevance_decision(
    item: dict[str, Any],
    *,
    use_llm: bool = True,
    client: JudgeClient | None = None,
) -> Decision:
    """Judge relevance with LLM first, then fallback to local heuristic."""
    if use_llm:
        try:
            decision = llm_relevance_decision(item, client=client)
            return _material_company_event_override(item, decision)
        except Exception:
            pass
    return heuristic_relevance_decision(item)


def judge_item_relevance(
    item: dict[str, Any],
    mode: str = "auto",
    client: JudgeClient | None = None,
) -> Decision:
    """Mode-aware wrapper used by report_pipeline."""
    selected_mode = (mode or "auto").lower()
    if selected_mode == "off":
        return Decision(
            is_approved=True,
            domain_relevance="adjacent",
            confidence=0.70,
            reason="LLM领域审计已关闭",
            evidence_spans=[str(item.get("title") or item.get("summary") or item.get("url") or "manual-off")],
            section=str(item.get("type") or "") or None,
            provider="off",
        )
    if selected_mode == "heuristic":
        return heuristic_relevance_decision(item)
    client_instance = client or LLMClient()
    if selected_mode == "llm" or (selected_mode == "auto" and client_instance.is_configured):
        try:
            decision = llm_relevance_decision(item, client=client_instance)
            return _material_company_event_override(item, decision)
        except Exception as exc:
            if selected_mode == "llm":
                # Fail closed: when LLM is explicitly required, any API failure
                # should stop the pipeline rather than silently falling back.
                raise RuntimeError(f"LLM领域审计失败: {exc}") from exc
            # auto mode: client is configured but API call failed -> also fail closed
            raise RuntimeError(f"LLM API已配置但调用失败: {exc}") from exc
    # auto mode: client not configured -> fallback to heuristic
    return heuristic_relevance_decision(item)


def judge_item_date_validity(
    item: dict[str, Any],
    report_date: str,
    mode: str = "auto",
    client: JudgeClient | None = None,
) -> DateDecision:
    selected_mode = (mode or "auto").lower()
    if selected_mode == "off":
        return DateDecision(
            is_date_valid=True,
            confidence=0.7,
            reason="LLM日期审计已关闭",
            evidence_spans=[str(item.get("date") or item.get("search_date") or "manual-off")],
            provider="off",
        )
    client_instance = client or LLMClient()
    if hasattr(client_instance, "judge_date") and (selected_mode == "llm" or (selected_mode == "auto" and client_instance.is_configured)):  # type: ignore[attr-defined]
        try:
            return client_instance.judge_date(item, report_date)  # type: ignore[attr-defined]
        except Exception as exc:
            if selected_mode == "llm":
                raise RuntimeError(f"LLM日期审计失败: {exc}") from exc
            raise RuntimeError(f"LLM API已配置但日期审计调用失败: {exc}") from exc
    return DateDecision(
        is_date_valid=True,
        confidence=0.51,
        reason="未配置LLM日期审计，跳过",
        evidence_spans=[str(item.get("date") or item.get("search_date") or "skipped")],
        provider="heuristic-skip",
    )


def _build_final_audit_prompt(items: list[dict[str, Any]], report_date: str, *, ascii_safe: bool = False) -> str:
    """Build a prompt for final quality audit of approved items."""
    truncated_items = []
    for i, item in enumerate(items):
        dv = item.get("date_verification") or {}
        truncated_items.append({
            "index": i,
            "title": str(item.get("title", ""))[:200],
            "type": str(item.get("type", "")),
            "date": str(item.get("date", "")),
            "source": str(item.get("source", ""))[:100],
            "url": str(item.get("url", ""))[:150],
            "summary": str(item.get("summary", ""))[:350],
            "domain_relevance": str(item.get("domain_relevance", "")),
            "date_verification_confidence": str(dv.get("confidence", "")),
        })
    schema = (
        "[\n"
        '  {"index":0,"keep":true,"reason":"保留原因","duplicate_of":null},\n'
        '  {"index":1,"keep":false,"reason":"重复-同一事件已保留#0","duplicate_of":0}\n'
        "]"
    )
    instructions = (
        "你是合成生物行业日报的最终质量审计员。以下候选条目已通过初步筛选，"
        "请你做最终把关，从严审查以下问题：\n"
        "\n"
        "审查标准（必须满足才能保留）：\n"
        "1. 重复检测：如果多条是同一事件/同一论坛/同一会议的不同媒体报道，只保留1条最佳（来源最权威、内容最完整），其余标记为重复\n"
        "2. 标题摘要匹配：标题是否与摘要内容一致？如果标题和正文完全无关（如标题是'超低轨科技'但摘要是'合成生物学峰会'），标记为不匹配\n"
        "3. 来源质量：来源网站是否可信？是否有垃圾广告、加密货币、赌博等低质量内容混入？\n"
        "4. 内容相关性：是否真正与合成生物学、生物制造相关？非合成生物的通用科技新闻应排除\n"
        "5. 聚合页面：如果是一个机构/网站的动态列表页（包含多篇不同日期文章），不应作为单条新闻收录\n"
        "\n"
        f"输出要求：必须返回纯JSON数组，不要Markdown。Schema示例：\n{schema}\n"
        f"报告日期: {report_date}\n"
        "候选条目:\n"
    )
    if ascii_safe:
        return instructions + json.dumps(truncated_items, ensure_ascii=True)
    return instructions + json.dumps(truncated_items, ensure_ascii=False)


def _extract_json_array(text: str) -> list[dict[str, Any]]:
    """Extract a JSON array from LLM response, tolerating trailing content."""
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return parsed
    except json.JSONDecodeError:
        pass
    # Try to find array pattern [...]
    match = re.search(r"\[.*\]", text, re.DOTALL)
    if not match:
        raise ValueError("LLM response did not contain a JSON array")
    parsed = json.loads(match.group(0))
    if not isinstance(parsed, list):
        raise ValueError("LLM JSON response must be an array")
    return parsed


def normalize_final_audit_decisions(
    raw_decisions: list[dict[str, Any]],
    items_count: int,
) -> list[dict[str, Any]]:
    """Normalize and validate final audit decisions, defaulting to keep for missing items."""
    decisions = []
    seen_indices = set()
    for entry in raw_decisions:
        if not isinstance(entry, dict):
            continue
        idx = entry.get("index")
        try:
            idx = int(idx)
        except (TypeError, ValueError):
            continue
        if idx < 0 or idx >= items_count:
            continue
        seen_indices.add(idx)
        keep = bool(entry.get("keep", True))
        reason = str(entry.get("reason") or ("保留" if keep else "排除")).strip()[:100]
        dup = entry.get("duplicate_of")
        try:
            dup = int(dup) if dup is not None else None
        except (TypeError, ValueError):
            dup = None
        if dup is not None and (dup < 0 or dup >= items_count or dup == idx):
            dup = None
        decisions.append({
            "index": idx,
            "keep": keep,
            "reason": reason,
            "duplicate_of": dup,
        })
    # Default missing indices to keep
    for i in range(items_count):
        if i not in seen_indices:
            decisions.append({"index": i, "keep": True, "reason": "LLM未明确判断，默认保留", "duplicate_of": None})
    return sorted(decisions, key=lambda x: x["index"])


def judge_final_audit(
    items: list[dict[str, Any]],
    report_date: str,
    mode: str = "auto",
    client: JudgeClient | None = None,
) -> Tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    """Run LLM final audit on approved items. Returns (kept, rejected, warnings).

    The audit checks:
    - duplicates (same event from different media)
    - title/summary mismatch
    - source quality (spam, crypto ads, etc.)
    - content relevance
    - aggregate pages
    """
    if not items:
        return [], [], []
    selected_mode = (mode or "auto").lower()
    warnings = []
    if selected_mode == "off":
        return list(items), [], ["LLM终审已关闭"]
    client_instance = client or LLMClient()
    if selected_mode == "llm" or (selected_mode == "auto" and client_instance.is_configured):
        try:
            if hasattr(client_instance, "final_audit"):
                raw_decisions = client_instance.final_audit(items, report_date)
            else:
                raise RuntimeError("LLM client does not support final_audit")
            decisions = normalize_final_audit_decisions(raw_decisions, len(items))
            kept = []
            rejected = []
            for dec in decisions:
                idx = dec["index"]
                item = dict(items[idx])
                if dec["keep"]:
                    item["final_audit"] = {
                        "keep": True,
                        "reason": dec["reason"],
                        "duplicate_of": dec["duplicate_of"],
                    }
                    kept.append(item)
                else:
                    item["final_audit"] = {
                        "keep": False,
                        "reason": dec["reason"],
                        "duplicate_of": dec["duplicate_of"],
                    }
                    item["rejection_reason"] = f"LLM终审排除: {dec['reason']}"
                    rejected.append(item)
            warnings.append(f"LLM终审: {len(kept)}/{len(items)} 保留, {len(rejected)}/{len(items)} 排除")
            return kept, rejected, warnings
        except Exception as exc:
            if selected_mode == "llm":
                raise RuntimeError(f"LLM终审失败: {exc}") from exc
            warnings.append(f"LLM终审调用失败，默认全部保留: {exc}")
            return list(items), [], warnings
    warnings.append("LLM未配置，跳过终审")
    return list(items), [], warnings

def is_synbio_relevant(title: str = "", summary: str = "", url: str = "") -> Tuple[bool, str, str]:
    """Backward-compatible tuple API used by older type checks."""
    decision = heuristic_relevance_decision({"title": title, "summary": summary, "url": url})
    if decision.is_approved:
        confidence = "high" if decision.confidence >= 0.85 else "medium"
        return True, decision.reason, confidence
    confidence = "high" if decision.confidence >= 0.85 else "medium"
    return False, decision.reject_message(), confidence


def batch_judge(items: list[dict]) -> list[Tuple[bool, str, str]]:
    """Judge a batch using the backward-compatible tuple API."""
    return [
        is_synbio_relevant(
            str(item.get("title", "")),
            str(item.get("summary", "")),
            str(item.get("url", "")),
        )
        for item in items
    ]


if __name__ == "__main__":
    test_cases = [
        ("湖北大学改造地衣芽孢杆菌高效合成血清素", "通过多维代谢工程策略构建细胞工厂", True),
        ("Cell：IL-1β信号通过中缝背核神经元调控社交行为", "受体激活神经连接，主动抑制社交行为", False),
        ("固相合成法制备抗菌肽", "采用固相合成策略（SPPS）制备抗菌肽", False),
        ("国家重点研发计划合成生物学重点专项申报指南征求意见", "合成生物学重点专项向社会征求意见", True),
    ]
    passed = 0
    for title, summary, expected in test_cases:
        result, reason, confidence = is_synbio_relevant(title, summary)
        status = "PASS" if result == expected else "FAIL"
        if result == expected:
            passed += 1
        print(f"{status}: {title[:40]}... ({confidence}) - {reason}")
    print(f"\n{passed}/{len(test_cases)} passed")
    if passed != len(test_cases):
        raise SystemExit(1)
