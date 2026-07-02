#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Generate an auditable LLM-driven daily search strategy.

This module plans what to search. It does not execute web search. The search
executor must record every generated query in search_log_YYYY-MM-DD.json, and
report_pipeline/audit_search_log can then enforce execution coverage.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Protocol
from urllib.request import Request

try:
    from .llm_judge import LLMClient, _extract_json_object
except ImportError:
    from llm_judge import LLMClient, _extract_json_object


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
CONFIG_DIR = ROOT / "config"
DEFAULT_CONFIG_PATH = CONFIG_DIR / "llm_search_strategy.json"
VALID_SECTIONS = {"news", "research", "funding", "policy", "events"}
VALID_PRIORITIES = {"high", "medium", "low"}
DEFAULT_STRATEGY_MAX_TOKENS = 6000
DEFAULT_STRATEGY_TIMEOUT_SECONDS = 90
DEFAULT_STRATEGY_RETRIES = 3


def _positive_int_env(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name) or default)
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


class StrategyClient(Protocol):
    @property
    def is_configured(self) -> bool:
        ...

    def complete(self, prompt: str) -> str:
        ...


@dataclass
class StrategyQuery:
    query: str
    reason: str
    priority: str = "medium"
    target_section: str = "news"
    expected_source_type: str = "mixed"
    iteration: int = 1
    required: bool = True


@dataclass
class SearchStrategy:
    version: int = 1
    date: str = ""
    generated_by: str = "llm_search_strategy"
    provider: str = "heuristic"
    model: str | None = None
    strategy_round_id: str = "llm_dynamic"
    base_rounds: list[str] = field(default_factory=list)
    coverage_dimensions: list[str] = field(default_factory=list)
    blindspots: list[str] = field(default_factory=list)
    queries: list[StrategyQuery] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["queries"] = [asdict(query) for query in self.queries]
        return data


class MessagesTextClient:
    """Small text-completion wrapper around the existing Anthropic client."""

    def __init__(self, llm_client: LLMClient | None = None):
        self.llm_client = llm_client or LLMClient()

    @property
    def is_configured(self) -> bool:
        return self.llm_client.is_configured

    def complete(self, prompt: str) -> str:
        if not self.llm_client.is_configured:
            raise RuntimeError("LLM provider is not configured")
        max_tokens = _positive_int_env("ANTHROPIC_SEARCH_STRATEGY_MAX_TOKENS", DEFAULT_STRATEGY_MAX_TOKENS)
        timeout = _positive_int_env(
            "ANTHROPIC_SEARCH_STRATEGY_TIMEOUT",
            max(DEFAULT_STRATEGY_TIMEOUT_SECONDS, int(self.llm_client.timeout or 0)),
        )
        retries = _positive_int_env("ANTHROPIC_SEARCH_STRATEGY_RETRIES", DEFAULT_STRATEGY_RETRIES)
        payload = {
            "model": self.llm_client.model,
            "max_tokens": max_tokens,
            "temperature": 0,
            "messages": [{"role": "user", "content": prompt}],
        }
        if _llm_client_supports_thinking_disable(self.llm_client):
            payload["thinking"] = {"type": "disabled"}
        last_error: Exception | None = None
        for attempt in range(1, retries + 1):
            request = Request(
                self.llm_client.messages_url,
                data=json.dumps(payload, ensure_ascii=self.llm_client.use_ascii_prompts).encode("utf-8"),
                headers={
                    "Content-Type": "application/json; charset=utf-8",
                    "x-api-key": self.llm_client.auth_token or "",
                    "Authorization": f"Bearer {self.llm_client.auth_token or ''}",
                    "anthropic-version": "2023-06-01",
                },
                method="POST",
            )
            try:
                with self.llm_client.opener(request, timeout=timeout) as response:
                    body = response.read().decode("utf-8", errors="replace")
                parsed = json.loads(body)
                content = parsed.get("content")
                if isinstance(content, list):
                    text = "\n".join(
                        str(part.get("text", ""))
                        for part in content
                        if isinstance(part, dict) and part.get("text") is not None
                    ).strip()
                    if text:
                        return text
                    block_types = [
                        str(part.get("type") or "<unknown>")
                        for part in content
                        if isinstance(part, dict)
                    ]
                    stop_reason = str(parsed.get("stop_reason") or "")
                    raise RuntimeError(
                        "LLM search strategy response contained no text blocks "
                        f"(stop_reason={stop_reason or 'unknown'}, content_types={block_types})"
                    )
                if isinstance(content, str):
                    return content
                text = str(parsed.get("text") or "").strip()
                if text:
                    return text
                raise RuntimeError("LLM search strategy response contained no text")
            except Exception as exc:
                last_error = exc
                if attempt >= retries:
                    break
                time.sleep(min(2, attempt))
        raise last_error or RuntimeError("LLM search strategy request failed")


def normalize_query_text(query: Any) -> str:
    return re.sub(r"\s+", " ", str(query or "")).strip()


def load_strategy_config(path: Path | None = None) -> dict[str, Any]:
    config_path = path or DEFAULT_CONFIG_PATH
    if not config_path.exists():
        return {}
    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)
    if not isinstance(config, dict):
        raise ValueError("llm_search_strategy.json must be an object")
    return config


def _read_json(path: Path) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_recent_approved_titles(
    data_dir: Path = DATA_DIR,
    report_date: str | None = None,
    days: int = 30,
    limit: int = 80,
) -> list[dict[str, str]]:
    """Load recent approved item titles so the LLM can avoid duplicates."""
    base_date = _parse_date(report_date) or datetime.now()
    lower_bound = base_date - timedelta(days=days)
    records: list[dict[str, str]] = []
    for path in sorted(data_dir.glob("approved_*.json"), reverse=True):
        date_text = path.stem.replace("approved_", "")
        item_date = _parse_date(date_text)
        if not item_date or item_date > base_date or item_date < lower_bound:
            continue
        try:
            items = _read_json(path)
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or "").strip()
            if not title:
                continue
            records.append({
                "date": date_text,
                "title": title[:160],
                "type": str(item.get("type") or "")[:30],
                "source": str(item.get("source") or "")[:80],
            })
            if len(records) >= limit:
                return records
    return records


def summarize_search_log(search_log: Any, max_results: int = 40) -> dict[str, Any]:
    """Compact a base search log for prompt context."""
    if not isinstance(search_log, dict):
        return {"rounds": [], "result_titles": []}
    rounds_summary: list[dict[str, Any]] = []
    result_titles: list[str] = []
    for round_entry in search_log.get("rounds", []) or []:
        if not isinstance(round_entry, dict):
            continue
        round_id = str(round_entry.get("round") or round_entry.get("id") or round_entry.get("round_id") or "")
        query_count = 0
        result_count = 0
        queries = round_entry.get("queries") or []
        if isinstance(queries, list):
            query_count = len(queries)
            for query_entry in queries:
                if isinstance(query_entry, dict):
                    for key in ("results", "candidates", "items"):
                        values = query_entry.get(key)
                        if isinstance(values, list):
                            result_count += len(values)
                            for value in values:
                                title = _candidate_title(value)
                                if title and len(result_titles) < max_results:
                                    result_titles.append(title)
                elif query_entry:
                    query_count += 0
        for key in ("results", "candidates", "items"):
            values = round_entry.get(key)
            if isinstance(values, list):
                result_count += len(values)
                for value in values:
                    title = _candidate_title(value)
                    if title and len(result_titles) < max_results:
                        result_titles.append(title)
        rounds_summary.append({
            "round": round_id,
            "query_count": query_count,
            "result_count": result_count,
        })
    return {
        "date": search_log.get("date"),
        "rounds": rounds_summary,
        "result_titles": result_titles,
    }


def _candidate_title(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("title") or value.get("name") or value.get("text") or "")[:160]
    return str(value or "")[:160]


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value[:10], "%Y-%m-%d")
    except ValueError:
        return None


def build_strategy_prompt(
    report_date: str,
    config: dict[str, Any],
    recent_titles: list[dict[str, str]] | None = None,
    base_search_summary: dict[str, Any] | None = None,
    ascii_safe: bool = False,
) -> str:
    min_queries = int(config.get("min_queries", 8) or 8)
    max_queries = int(config.get("max_queries", 12) or 12)
    compact = {
        "report_date": report_date,
        "config": {
            "min_queries": min_queries,
            "max_queries": max_queries,
            "base_rounds": config.get("base_rounds", []),
            "coverage_dimensions": config.get("coverage_dimensions", []),
            "tracked_entities": config.get("tracked_entities", []),
            "technology_topics": config.get("technology_topics", []),
            "coverage_queries": config.get("coverage_queries", []),
            "source_hints": config.get("source_hints", []),
            "negative_guidance": config.get("negative_guidance", []),
        },
        "recent_approved_titles": recent_titles or [],
        "base_search_summary": base_search_summary or {},
    }
    if ascii_safe:
        return (
            "You are the search commander for a synthetic-biology daily report. "
            "Your job is to generate high-recall, auditable web-search queries for today; "
            "you are not deciding final inclusion.\n"
            "Important: the context JSON below uses JSON unicode escape sequences such as "
            "\\u5408\\u6210\\u751f\\u7269. Decode them semantically before planning queries.\n"
            "Rules:\n"
            "1. Fill gaps left by the base search rounds.\n"
            "2. Cover policy, funding, key companies, research breakthroughs, events, "
            "international news, and technology/product directions.\n"
            "3. Avoid generic biology, pure chemical synthesis, and ordinary medical "
            "pathway news unless there is engineered-biology or biomanufacturing evidence.\n"
            "4. coverage_queries are mandatory recall floors; do not replace broad source "
            "queries with narrower funding/announcement-only queries.\n"
            "5. Every query needs a clear reason and should not be filler.\n"
            "6. Each query must express one search intent and include at most two key "
            "company names.\n"
            f"7. Return between {min_queries} and {max_queries} queries. Do not exceed {max_queries}.\n"
            "8. Use only target_section values: news, research, funding, policy, events. "
            "Company and product updates are news unless they are clearly funding or research.\n"
            "9. Keep blindspots to at most 5 short strings. Keep each reason under 90 characters.\n"
            "10. Return strict compact JSON only, no Markdown, no code fences, and fully closed JSON.\n\n"
            "Schema:\n"
            "{"
            '"blindspots":["blindspot"],'
            '"queries":[{'
            '"query":"search query",'
            '"reason":"why this should be searched today",'
            '"priority":"high|medium|low",'
            '"target_section":"news|research|funding|policy|events",'
            '"expected_source_type":"company|media|government|academic|investor|mixed",'
            '"iteration":1,'
            '"required":true'
            "}]}\n\n"
            "context_json:\n"
            f"{json.dumps(compact, ensure_ascii=True)}"
        )
    return (
        "你是合成生物日报的信息检索指挥官。你的任务不是判断最终收录，"
        "而是为今天生成高召回、可审计的动态搜索 query。\n"
        "必须遵守：\n"
        "1. 优先补足基座搜索没有覆盖的盲区；\n"
        "2. 覆盖政策、融资、重点企业、研究突破、活动、国际动态、技术产品方向；\n"
        "3. 避免普通生物学、普通化学合成、医学信号通路等跑题方向；\n"
        "4. coverage_queries 是召回底座，不要用更窄的融资/公告词替代宽口径来源 query；\n"
        "5. 每条 query 必须有明确理由，不能凑数；\n"
        "6. 每条 query 只表达一个检索意图，最多包含两个重点企业名；不要把很多企业或很多 OR 条件揉进一条；\n"
        f"7. 输出 {min_queries} 到 {max_queries} 条 query，绝对不要超过 {max_queries} 条；\n"
        "8. target_section 只能使用 news、research、funding、policy、events；企业/产品动态归 news，融资归 funding，论文归 research；\n"
        "9. blindspots 最多 5 条短句；每条 reason 控制在 90 字以内；\n"
        "10. 输出紧凑纯 JSON，不要 Markdown，不要 ```json 代码块；必须完整闭合 JSON 对象。\n\n"
        "schema:\n"
        "{"
        '"blindspots":["盲区"],'
        '"queries":[{'
        '"query":"搜索词",'
        '"reason":"为什么今天要搜",'
        '"priority":"high|medium|low",'
        '"target_section":"news|research|funding|policy|events",'
        '"expected_source_type":"company|media|government|academic|investor|mixed",'
        '"iteration":1,'
        '"required":true'
        "}]} \n\n"
        f"上下文:\n{json.dumps(compact, ensure_ascii=False)}"
    )


def build_compact_strategy_prompt(
    report_date: str,
    config: dict[str, Any],
    recent_titles: list[dict[str, str]] | None = None,
    base_search_summary: dict[str, Any] | None = None,
    ascii_safe: bool = False,
) -> str:
    """Build a short JSON-only retry prompt for providers with small output caps.

    Some Anthropic-compatible Kimi gateways spend the available output budget on
    internal ``thinking`` blocks when the full planning prompt is large.  This
    compact prompt keeps only the business constraints that must come from the
    LLM; deterministic coverage floors are appended later by
    ``normalize_strategy_response``.
    """
    # The final normalized strategy will still satisfy config["min_queries"]
    # because deterministic coverage floors are appended after parsing. Keep the
    # live LLM portion deliberately small so constrained gateways return final
    # text instead of spending their output budget on hidden/thinking blocks.
    min_queries = 6
    max_queries = 8
    tracked_entities = [str(item) for item in (config.get("tracked_entities") or [])[:10]]
    technology_topics = [str(item) for item in (config.get("technology_topics") or [])[:10]]
    source_hints = [str(item) for item in (config.get("source_hints") or [])[:12]]
    recent = [
        {
            "date": str(item.get("date") or ""),
            "title": str(item.get("title") or "")[:100],
        }
        for item in (recent_titles or [])[:12]
        if isinstance(item, dict)
    ]
    base_summary = {
        "rounds": (base_search_summary or {}).get("rounds", [])[:8]
        if isinstance(base_search_summary, dict)
        else [],
        "result_titles": (base_search_summary or {}).get("result_titles", [])[:12]
        if isinstance(base_search_summary, dict)
        else [],
    }
    compact = {
        "report_date": report_date,
        "required_dimensions": config.get("required_coverage_dimensions") or [
            "news",
            "research",
            "funding",
            "policy",
            "events",
            "company_announcement",
            "china_local_sources",
            "english_sources",
        ],
        "tracked_entities": tracked_entities,
        "technology_topics": technology_topics,
        "priority_source_hints": source_hints,
        "recent_approved_titles": recent,
        "base_search_summary": base_summary,
    }
    return (
        "Return ONLY compact JSON. First character must be { and last character must be }. "
        "No markdown. No explanation. Do not describe your plan. "
        "Generate high-recall web-search queries for a synthetic-biology / "
        f"biomanufacturing daily report dated {report_date}. "
        "Cover news, research, funding, policy, events, company announcements, "
        "China local/government/academic sources, and English sources. "
        f"Return {min_queries} to {max_queries} queries. Each query must have one intent. "
        "Keep each reason under 12 words. Keep blindspots to at most 3 strings. "
        "Use only target_section values news, research, funding, policy, events. "
        "Use only expected_source_type values company, media, government, academic, investor, mixed. "
        "You may use Chinese search terms from the escaped context when useful. "
        "Schema: {\"blindspots\":[\"...\"],\"queries\":[{\"query\":\"...\","
        "\"reason\":\"...\",\"priority\":\"high|medium|low\","
        "\"target_section\":\"news|research|funding|policy|events\","
        "\"expected_source_type\":\"company|media|government|academic|investor|mixed\","
        "\"iteration\":1,\"required\":true}]}. "
        "context_json: "
        f"{json.dumps(compact, ensure_ascii=True)}"
    )


def build_minimal_json_strategy_prompt(
    report_date: str,
    config: dict[str, Any],
    recent_titles: list[dict[str, str]] | None = None,
    base_search_summary: dict[str, Any] | None = None,
    ascii_safe: bool = False,
) -> str:
    """Build the smallest possible JSON-only fallback prompt.

    This prompt exists for Anthropic-compatible gateways that occasionally
    ignore a larger JSON instruction. The normalized strategy still receives
    deterministic coverage floors after parsing, so the model only needs to
    prove that the live LLM path can contribute a small number of fresh,
    structured discovery queries.
    """
    source_hints = [str(item) for item in (config.get("source_hints") or [])[:8]]
    coverage_queries = [
        str(item.get("query") if isinstance(item, dict) else item)
        for item in (config.get("coverage_queries") or [])[:8]
        if str(item.get("query") if isinstance(item, dict) else item).strip()
    ]
    compact = {
        "report_date": report_date,
        "source_hints": source_hints,
        "coverage_queries": coverage_queries,
        "recent_titles": [
            str(item.get("title") or "")[:80]
            for item in (recent_titles or [])[:8]
            if isinstance(item, dict)
        ],
        "base_rounds": (base_search_summary or {}).get("rounds", [])[:6]
        if isinstance(base_search_summary, dict)
        else [],
    }
    context = json.dumps(compact, ensure_ascii=True if ascii_safe else False)
    return (
        "Return valid JSON only. Output must start with { and end with }. "
        "No markdown, no comments, no explanation. "
        "Create 2 to 4 high-recall web search queries for today's synthetic "
        "biology / biomanufacturing daily report. Prefer source-specific or "
        "blindspot queries, not generic filler. "
        "Schema exactly: {\"blindspots\":[\"...\"],\"queries\":[{\"query\":\"...\","
        "\"reason\":\"...\",\"priority\":\"high|medium|low\","
        "\"target_section\":\"news|research|funding|policy|events\","
        "\"expected_source_type\":\"company|media|government|academic|investor|mixed\","
        "\"iteration\":1,\"required\":true}]}. "
        "context_json: "
        f"{context}"
    )


def extract_strategy_json_object(text: str) -> dict[str, Any]:
    """Extract a JSON object from noisy LLM strategy text.

    ``llm_judge._extract_json_object`` intentionally stays simple because it is
    also used by the relevance gate. Strategy generation is more tolerant: it
    may receive code fences or preambles from gateway models, so this scanner
    tries every balanced JSON object and returns the first one that looks like a
    strategy payload.
    """
    stripped = str(text or "").strip()
    try:
        parsed = json.loads(stripped)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    for candidate in _iter_balanced_json_objects(stripped):
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict) and (
            "queries" in parsed
            or "strategy" in parsed
            or "blindspots" in parsed
        ):
            return parsed

    # Fall back to the shared extractor so callers get the established error
    # message when no object can be recovered.
    return _extract_json_object(stripped)


def _iter_balanced_json_objects(text: str) -> list[str]:
    candidates: list[str] = []
    starts = [index for index, char in enumerate(text) if char == "{"]
    for start in starts:
        depth = 0
        in_string = False
        escape = False
        for index in range(start, len(text)):
            char = text[index]
            if in_string:
                if escape:
                    escape = False
                elif char == "\\":
                    escape = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    candidates.append(text[start:index + 1])
                    break
    return candidates


def generate_search_strategy(
    report_date: str,
    *,
    config: dict[str, Any] | None = None,
    recent_titles: list[dict[str, str]] | None = None,
    base_search_log: Any | None = None,
    mode: str = "auto",
    client: StrategyClient | LLMClient | None = None,
) -> dict[str, Any]:
    """Generate a normalized search strategy dict."""
    selected_mode = (mode or "auto").lower()
    if selected_mode not in {"auto", "llm", "heuristic"}:
        raise ValueError("mode must be one of: auto, llm, heuristic")
    cfg = config or load_strategy_config()
    base_summary = summarize_search_log(base_search_log) if base_search_log is not None else {}
    if selected_mode == "heuristic":
        return heuristic_search_strategy(report_date, cfg, recent_titles=recent_titles).to_dict()

    strategy_client = _ensure_strategy_client(client)
    if selected_mode == "llm" or strategy_client.is_configured:
        ascii_safe = _strategy_client_uses_ascii_prompts(strategy_client)
        prompts = [
            (
                "full",
                build_strategy_prompt(
                    report_date,
                    cfg,
                    recent_titles=recent_titles,
                    base_search_summary=base_summary,
                    ascii_safe=ascii_safe,
                ),
            ),
            (
                "compact",
                build_compact_strategy_prompt(
                    report_date,
                    cfg,
                    recent_titles=recent_titles,
                    base_search_summary=base_summary,
                    ascii_safe=ascii_safe,
                ),
            ),
            (
                "minimal_json",
                build_minimal_json_strategy_prompt(
                    report_date,
                    cfg,
                    recent_titles=recent_titles,
                    base_search_summary=base_summary,
                    ascii_safe=ascii_safe,
                ),
            ),
        ]
        if _strategy_client_prefers_compact_prompt(strategy_client):
            prompts = [prompts[1], prompts[2], prompts[0]]
        errors: list[str] = []
        for attempt_name, prompt in prompts:
            try:
                raw_text = strategy_client.complete(prompt)
                data = extract_strategy_json_object(raw_text)
                strategy = normalize_strategy_response(
                    data,
                    report_date=report_date,
                    config=cfg,
                    provider="llm",
                    model=_client_model(strategy_client),
                ).to_dict()
                strategy["prompt_attempt"] = attempt_name
                return strategy
            except Exception as exc:
                errors.append(f"{attempt_name}: {exc}")
        raise RuntimeError("LLM搜索策略生成失败: " + " | ".join(errors))

    return heuristic_search_strategy(report_date, cfg, recent_titles=recent_titles).to_dict()


def _ensure_strategy_client(client: StrategyClient | LLMClient | None) -> StrategyClient:
    if client is None:
        return MessagesTextClient()
    if hasattr(client, "complete"):
        return client  # type: ignore[return-value]
    return MessagesTextClient(client)  # type: ignore[arg-type]


def _client_model(client: StrategyClient) -> str | None:
    if isinstance(client, MessagesTextClient):
        return client.llm_client.model
    return str(getattr(client, "model", "") or "") or None


def _llm_client_supports_thinking_disable(llm_client: LLMClient) -> bool:
    base_url = (llm_client.base_url or "").lower()
    model = (llm_client.model or "").lower()
    return (
        "kimi" in model
        or "aiself.vip" in base_url
        or "127.0.0.1:15721" in base_url
        or "localhost:15721" in base_url
    )


def _strategy_client_uses_ascii_prompts(client: StrategyClient) -> bool:
    if isinstance(client, MessagesTextClient):
        return client.llm_client.use_ascii_prompts
    return bool(getattr(client, "use_ascii_prompts", False))


def _strategy_client_prefers_compact_prompt(client: StrategyClient) -> bool:
    if isinstance(client, MessagesTextClient):
        base_url = (client.llm_client.base_url or "").lower()
        model = (client.llm_client.model or "").lower()
    else:
        base_url = str(getattr(client, "base_url", "") or "").lower()
        model = str(getattr(client, "model", "") or "").lower()
    return (
        "kimi" in model
        or "aiself.vip" in base_url
        or "127.0.0.1:15721" in base_url
        or "localhost:15721" in base_url
    )


def heuristic_search_strategy(
    report_date: str,
    config: dict[str, Any],
    recent_titles: list[dict[str, str]] | None = None,
) -> SearchStrategy:
    """Offline fallback for CI and local dry runs."""
    max_queries = int(config.get("max_queries") or 12)
    base_rounds = [str(item) for item in config.get("base_rounds", []) if str(item).strip()]
    dimensions = [str(item) for item in config.get("coverage_dimensions", []) if str(item).strip()]
    queries: list[StrategyQuery] = []
    seen: set[str] = set()

    def add(query: str, reason: str, priority: str, section: str, source_type: str) -> None:
        normalized = normalize_query_text(query)
        if not normalized or normalized in seen or len(queries) >= max_queries:
            return
        seen.add(normalized)
        queries.append(StrategyQuery(
            query=normalized,
            reason=reason,
            priority=priority,
            target_section=section,
            expected_source_type=source_type,
        ))

    for coverage_query in iter_configured_coverage_queries(config):
        add(
            coverage_query.query,
            coverage_query.reason,
            coverage_query.priority,
            coverage_query.target_section,
            coverage_query.expected_source_type,
        )
    for entity in config.get("tracked_entities", []) or []:
        add(
            f"{entity} 最新 合成生物",
            "重点企业定向补搜，防止通用 query 漏掉企业进展",
            "high",
            "news",
            "company_or_media",
        )
        if len(queries) >= max_queries:
            break
    for hint in config.get("source_hints", []) or []:
        add(str(hint), "高价值来源定向补搜", "high", infer_section_from_query(str(hint)), "mixed")
    for topic in config.get("technology_topics", []) or []:
        add(
            f"{topic} 最新 融资 产业化",
            "技术/产品方向补搜，覆盖非公司名触发的信息",
            "medium",
            infer_section_from_query(str(topic)),
            "media_or_academic",
        )
    queries = append_missing_dimension_queries(queries, config, report_date=report_date)
    return SearchStrategy(
        date=report_date,
        provider="heuristic",
        model=None,
        strategy_round_id=str(config.get("strategy_round_id") or "llm_dynamic"),
        base_rounds=base_rounds,
        coverage_dimensions=dimensions,
        blindspots=["重点企业动态", "融资与产业化", "技术产品方向"],
        queries=queries,
    )


def infer_section_from_query(query: str) -> str:
    text = query.lower()
    if any(token in text for token in ("融资", "投资", "funding", "investment", "ipo", "港交所")):
        return "funding"
    if any(token in text for token in ("政策", "监管", "申报", "指南", "gov", "fda", "epa", "ec.europa")):
        return "policy"
    if any(token in text for token in ("论文", "研究", "biorxiv", "nature", "academic", "research")):
        return "research"
    if any(token in text for token in ("会议", "活动", "event", "conference", "webinar")):
        return "events"
    return "news"


def query_coverage_dimensions(entry: Any) -> set[str]:
    """Infer high-level coverage dimensions from one strategy query."""
    if isinstance(entry, str):
        query = normalize_query_text(entry)
        section = infer_section_from_query(query)
        source_type = ""
    elif isinstance(entry, dict):
        query = normalize_query_text(entry.get("query") or entry.get("q") or "")
        section = str(entry.get("target_section") or entry.get("section") or infer_section_from_query(query)).lower()
        source_type = str(entry.get("expected_source_type") or "").lower()
    else:
        return set()

    text = f"{query} {source_type}".lower()
    dims = {section} if section in VALID_SECTIONS else set()
    if any(token in text for token in ("公告", "cninfo", "上市公司", "company", "企业", "披露")):
        dims.add("company_announcement")
    if any(token in text for token in ("gov.cn", "政府", "科协", "高校", "大学", "sciencenet", "dg.gov.cn", "rednet", "hbkx", "ecust", "siat")):
        dims.add("china_local_sources")
    if any(token in text for token in ("synthetic", "biomanufacturing", "precision fermentation", "site:nature", "site:science", "site:genengnews", "site:synbiobeta", "site:labiotech", "site:fiercebiotech")):
        dims.add("english_sources")
    if any(token in text for token in ("论文", "研究", "nature", "science", "cell", "biorxiv", "科研", "团队")):
        dims.add("research")
    if any(token in text for token in ("会议", "大会", "峰会", "论坛", "赛事", "conference", "event")):
        dims.add("events")
    return dims


def normalize_strategy_response(
    data: dict[str, Any],
    *,
    report_date: str,
    config: dict[str, Any],
    provider: str,
    model: str | None,
) -> SearchStrategy:
    raw_queries = data.get("queries") or data.get("strategy") or []
    if not isinstance(raw_queries, list):
        raise ValueError("search strategy queries must be a list")

    min_queries = int(config.get("min_queries") or 1)
    max_queries = int(config.get("max_queries") or 12)
    normalized: list[StrategyQuery] = []
    seen: set[str] = set()
    for original_entry in raw_queries:
        for entry in expand_overpacked_query(original_entry, config):
            if len(normalized) >= max_queries:
                break
            if isinstance(entry, str):
                entry = {"query": entry}
            if not isinstance(entry, dict):
                continue
            query = normalize_query_text(entry.get("query") or entry.get("q") or "")
            if not query or query in seen:
                continue
            seen.add(query)
            priority = str(entry.get("priority") or "medium").lower()
            if priority not in VALID_PRIORITIES:
                priority = "medium"
            section = str(entry.get("target_section") or entry.get("section") or infer_section_from_query(query)).lower()
            if section not in VALID_SECTIONS:
                section = infer_section_from_query(query)
            normalized.append(StrategyQuery(
                query=query,
                reason=str(entry.get("reason") or "LLM动态搜索策略").strip()[:300],
                priority=priority,
                target_section=section,
                expected_source_type=str(entry.get("expected_source_type") or "mixed").strip()[:80] or "mixed",
                iteration=int(entry.get("iteration") or 1),
                required=bool(entry.get("required", True)),
            ))
        if len(normalized) >= max_queries:
            break
    normalized = append_missing_coverage_queries(normalized, config, max_queries=max_queries)
    normalized = append_missing_dimension_queries(normalized, config, report_date=report_date)
    if len(normalized) < min_queries:
        raise ValueError(f"LLM search strategy returned {len(normalized)} queries, below min_queries={min_queries}")

    blindspots = data.get("blindspots") or data.get("expected_blindspots") or []
    if not isinstance(blindspots, list):
        blindspots = [str(blindspots)]
    return SearchStrategy(
        date=report_date,
        provider=provider,
        model=model,
        strategy_round_id=str(config.get("strategy_round_id") or data.get("strategy_round_id") or "llm_dynamic"),
        base_rounds=[str(item) for item in config.get("base_rounds", []) if str(item).strip()],
        coverage_dimensions=[str(item) for item in config.get("coverage_dimensions", []) if str(item).strip()],
        blindspots=[str(item).strip()[:120] for item in blindspots if str(item).strip()][:10],
        queries=normalized,
    )


def iter_configured_coverage_queries(config: dict[str, Any]) -> list[StrategyQuery]:
    """Return configured coverage-floor queries in normalized StrategyQuery form."""
    queries: list[StrategyQuery] = []
    for entry in config.get("coverage_queries", []) or []:
        if isinstance(entry, str):
            query = normalize_query_text(entry)
            reason = "配置化覆盖底座查询"
            priority = "high"
            section = infer_section_from_query(query)
            source_type = "mixed"
        elif isinstance(entry, dict):
            query = normalize_query_text(entry.get("query") or entry.get("q") or "")
            reason = str(entry.get("reason") or "配置化覆盖底座查询").strip()[:300]
            priority = str(entry.get("priority") or "high").lower()
            if priority not in VALID_PRIORITIES:
                priority = "high"
            section = str(entry.get("target_section") or entry.get("section") or infer_section_from_query(query)).lower()
            if section not in VALID_SECTIONS:
                section = infer_section_from_query(query)
            source_type = str(entry.get("expected_source_type") or "mixed").strip()[:80] or "mixed"
        else:
            continue
        if query:
            queries.append(StrategyQuery(
                query=query,
                reason=reason,
                priority=priority,
                target_section=section,
                expected_source_type=source_type,
            ))
    return queries


def append_missing_coverage_queries(
    queries: list[StrategyQuery],
    config: dict[str, Any],
    *,
    max_queries: int,
) -> list[StrategyQuery]:
    """Ensure configured coverage-floor queries are present.

    ``max_queries`` limits the number of discretionary LLM queries parsed
    before this function runs; it is not a hard cap after coverage floors are
    appended.  This preserves proof that the LLM contributed live discovery
    queries while still making every configured source/theme floor mandatory.
    """
    coverage_queries = iter_configured_coverage_queries(config)
    seen = {normalize_query_text(query.query) for query in queries}
    result = list(queries)
    for coverage_query in coverage_queries:
        normalized = normalize_query_text(coverage_query.query)
        if normalized in seen:
            continue
        result.append(coverage_query)
        seen.add(normalized)
    return result


def _dimension_floor_queries(config: dict[str, Any], report_date: str) -> dict[str, StrategyQuery]:
    configured = config.get("dimension_floor_queries")
    floors: dict[str, StrategyQuery] = {}
    if isinstance(configured, dict):
        for dimension, entry in configured.items():
            if isinstance(entry, str):
                query = normalize_query_text(entry)
                section = infer_section_from_query(query)
                source_type = "mixed"
                reason = f"{dimension}维度覆盖兜底"
            elif isinstance(entry, dict):
                query = normalize_query_text(entry.get("query") or entry.get("q") or "")
                section = str(entry.get("target_section") or infer_section_from_query(query)).lower()
                source_type = str(entry.get("expected_source_type") or "mixed")
                reason = str(entry.get("reason") or f"{dimension}维度覆盖兜底")
            else:
                continue
            if query:
                floors[str(dimension)] = StrategyQuery(
                    query=query,
                    reason=reason[:300],
                    priority="high",
                    target_section=section if section in VALID_SECTIONS else infer_section_from_query(query),
                    expected_source_type=source_type[:80] or "mixed",
                )
    defaults = {
        "news": StrategyQuery("合成生物 生物制造 最新动态", "新闻维度覆盖兜底", "high", "news", "mixed"),
        "research": StrategyQuery("合成生物 论文 研究 Nature Cell Science", "科研维度覆盖兜底", "high", "research", "academic"),
        "funding": StrategyQuery("合成生物 融资 投资 IPO", "融资维度覆盖兜底", "high", "funding", "media"),
        "policy": StrategyQuery("合成生物 生物制造 政策 通知", "政策维度覆盖兜底", "high", "policy", "government"),
        "events": StrategyQuery("合成生物 大会 峰会 论坛 赛事", "活动维度覆盖兜底", "high", "events", "mixed"),
        "company_announcement": StrategyQuery("上市公司 生物制造 项目 公告", "公司公告维度覆盖兜底", "high", "news", "company"),
        "china_local_sources": StrategyQuery("合成生物 生物制造 政府 高校 科协 地方媒体", "中文地方源覆盖兜底", "high", "news", "government_academic_media"),
        "english_sources": StrategyQuery("synthetic biology biomanufacturing news funding research 2026", "英文源覆盖兜底", "high", "news", "media"),
    }
    for key, value in defaults.items():
        floors.setdefault(key, value)
    return floors


def append_missing_dimension_queries(
    queries: list[StrategyQuery],
    config: dict[str, Any],
    *,
    report_date: str,
) -> list[StrategyQuery]:
    required_dimensions = [
        str(item).strip()
        for item in config.get("required_coverage_dimensions", []) or []
        if str(item).strip()
    ]
    if not required_dimensions:
        return queries
    result = list(queries)
    covered: set[str] = set()
    for query in result:
        covered.update(query_coverage_dimensions(asdict(query)))
    floors = _dimension_floor_queries(config, report_date)
    seen = {normalize_query_text(query.query) for query in result}
    for dimension in required_dimensions:
        if dimension in covered:
            continue
        floor = floors.get(dimension)
        if not floor:
            continue
        normalized = normalize_query_text(floor.query)
        if normalized in seen:
            continue
        result.append(floor)
        seen.add(normalized)
        covered.update(query_coverage_dimensions(asdict(floor)))
    return result


def expand_overpacked_query(entry: Any, config: dict[str, Any]) -> list[Any]:
    """Split LLM queries that pack too many tracked entities into one search."""
    if not isinstance(entry, dict):
        return [entry]
    query = normalize_query_text(entry.get("query") or entry.get("q") or "")
    if not query:
        return [entry]
    tracked_entities = [
        str(entity)
        for entity in config.get("tracked_entities", []) or []
        if str(entity) and str(entity) in query
    ]
    if len(tracked_entities) <= 2:
        return [entry]

    site_match = re.search(r"\bsite:[^\s]+", query)
    site_prefix = f"{site_match.group(0)} " if site_match else ""
    suffix = _entity_query_suffix(query)
    expanded: list[dict[str, Any]] = []
    for index in range(0, len(tracked_entities), 2):
        group = tracked_entities[index:index + 2]
        cloned = dict(entry)
        cloned["query"] = normalize_query_text(f"{site_prefix}{' '.join(group)} {suffix}")
        cloned["reason"] = (
            str(entry.get("reason") or "重点企业补搜")[:240]
            + "（由多企业组合query自动拆分，保持一条query最多两个企业）"
        )
        expanded.append(cloned)
    return expanded


def _entity_query_suffix(query: str) -> str:
    text = query.lower()
    if any(token in text for token in ("公告", "cninfo", "披露")):
        return "合成生物 公告 最新"
    if any(token in text for token in ("融资", "投资", "funding", "ipo", "港交所")):
        return "合成生物 融资 最新"
    if any(token in text for token in ("产品", "合作", "产能", "投产")):
        return "合成生物 产品 合作 最新"
    return "最新 合成生物"


def validate_generated_strategy(strategy: dict[str, Any], config: dict[str, Any]) -> None:
    """Fail closed before writing a strategy that cannot drive dynamic search."""
    raw_queries = strategy.get("queries")
    if not isinstance(raw_queries, list):
        raise ValueError("search strategy queries must be a list")
    min_queries = max(1, int(config.get("min_queries") or 1))
    if len(raw_queries) < min_queries:
        raise ValueError(
            f"search strategy has {len(raw_queries)} queries, below min_queries={min_queries}"
        )
    required_count = 0
    for entry in raw_queries:
        if isinstance(entry, str):
            query = entry.strip()
            required = True
        elif isinstance(entry, dict):
            query = str(entry.get("query") or entry.get("q") or "").strip()
            required = bool(entry.get("required", True))
        else:
            query = ""
            required = True
        if query and required:
            required_count += 1
    if required_count < 1:
        raise ValueError("search strategy must contain at least one required query")
    required_dimensions = [
        str(item).strip()
        for item in config.get("required_coverage_dimensions", []) or []
        if str(item).strip()
    ]
    if required_dimensions:
        covered: set[str] = set()
        for entry in raw_queries:
            covered.update(query_coverage_dimensions(entry))
        missing = sorted(set(required_dimensions) - covered)
        if missing:
            raise ValueError(
                "search strategy coverage dimensions missing: "
                + ", ".join(missing)
            )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate LLM-driven search strategy JSON")
    parser.add_argument("--date", required=True, help="Report date YYYY-MM-DD")
    parser.add_argument("--output", required=True, type=Path, help="Output search_strategy JSON path")
    parser.add_argument("--mode", choices=["auto", "llm", "heuristic"], default="auto")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--base-search-log", type=Path, help="Optional base search_log JSON for blindspot planning")
    parser.add_argument("--recent-approved-dir", type=Path, default=DATA_DIR)
    parser.add_argument("--recent-days", type=int, default=30)
    args = parser.parse_args(argv)

    config = load_strategy_config(args.config)
    base_search_log = _read_json(args.base_search_log) if args.base_search_log else None
    recent_titles = load_recent_approved_titles(args.recent_approved_dir, args.date, days=args.recent_days)
    strategy = generate_search_strategy(
        args.date,
        config=config,
        recent_titles=recent_titles,
        base_search_log=base_search_log,
        mode=args.mode,
    )
    try:
        validate_generated_strategy(strategy, config)
    except Exception as exc:
        print(f"ERROR: invalid search strategy: {exc}", file=sys.stderr)
        return 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(strategy, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"search strategy saved: {args.output} "
        f"({len(strategy.get('queries', []))} queries, provider={strategy.get('provider')})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
