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


DEFAULT_MODEL = "claude-3-5-sonnet-20241022"
MIN_APPROVAL_CONFIDENCE = 0.70
ALLOWED_RELEVANCE = {"core_synbio", "adjacent", "out_of_scope", "uncertain"}
ALLOWED_SECTIONS = {"news", "research", "funding", "policy", "events"}


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


# Strong positive signals: engineered biological systems and biomanufacturing.
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
    "metabolic engineering", "cell factory", "engineered microbe",
    "engineered microbes", "engineered yeast", "precision fermentation",
    "pathway engineering", "genome editing", "protein engineering",
    "gene circuit", "dna synthesis", "fermentation",
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
    "neuronal", "neuron", "neural circuit", "neural circuits", "synaptic",
    "receptor signaling", "endogenous receptor", "endogenous", "social behavior",
    "signal transduction", "immune response", "inflammatory response",
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

    return Decision(
        is_approved=True,
        domain_relevance="adjacent",
        confidence=0.70,
        reason="本地语义fallback未发现明确跑题证据，保留给后续门禁/人工复核",
        evidence_spans=[title or summary[:80] or url],
        section=section,
    )


def _build_prompt(item: dict[str, Any]) -> str:
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
    return (
        "你是合成生物行业日报的审稿人。判断候选信息是否应收录。\n"
        "只根据给定标题、摘要、页面标题/正文判断，不要引入外部知识。\n"
        "合成生物核心包括：工程化改造生物系统、细胞工厂、代谢工程、基因线路/编辑、"
        "底盘细胞、精准发酵、生物制造、酶/蛋白工程、人工代谢途径等。\n"
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
    def messages_url(self) -> str:
        if self.base_url.endswith("/v1"):
            return f"{self.base_url}/messages"
        return f"{self.base_url}/v1/messages"

    def judge(self, item: dict[str, Any]) -> Decision:
        if not self.is_configured:
            raise RuntimeError("LLM provider is not configured")
        payload = {
            "model": self.model,
            "max_tokens": 600,
            "temperature": 0,
            "messages": [{"role": "user", "content": _build_prompt(item)}],
        }
        request = Request(
            self.messages_url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
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
        return normalize_llm_decision(_extract_json_object(text), raw_response=text)


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
            return llm_relevance_decision(item, client=client)
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
    try:
        if selected_mode == "llm" or (client or LLMClient()).is_configured:
            return llm_relevance_decision(item, client=client)
    except Exception as exc:
        if selected_mode == "llm":
            return Decision(
                is_approved=False,
                domain_relevance="uncertain",
                confidence=0.0,
                reason=f"LLM领域审计失败: {exc}",
                reject_reason="LLM领域审计失败，未进入日报",
                provider="llm",
                decision="escalate",
            )
        fallback = heuristic_relevance_decision(item)
        fallback.provider = "heuristic-fallback"
        fallback.reason = f"LLM领域审计失败，使用本地fallback: {fallback.reason}"
        if fallback.reject_reason:
            fallback.reject_reason = f"LLM领域审计失败，使用本地fallback: {fallback.reject_reason}"
        return fallback
    return heuristic_relevance_decision(item)


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
