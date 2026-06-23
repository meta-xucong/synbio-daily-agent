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
import socket
import ssl
from html import unescape
from html.parser import HTMLParser
from difflib import SequenceMatcher
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Any, Tuple, Optional
import glob
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

try:
    from .settings import CONFIG_DIR, DATA_DIR, REPORTS_DIR, TEMPLATES_DIR, now_local
    from .console_utils import ensure_utf8_console
    from .ai_analysis_check import validate_ai_analysis
    from .render_utils import safe_url
    from .llm_judge import Decision, is_synbio_relevant as _is_synbio_relevant_impl
    from .llm_judge import judge_item_relevance
except ImportError:
    from settings import CONFIG_DIR, DATA_DIR, REPORTS_DIR, TEMPLATES_DIR, now_local
    from console_utils import ensure_utf8_console
    from ai_analysis_check import validate_ai_analysis
    from render_utils import safe_url
    from llm_judge import Decision, is_synbio_relevant as _is_synbio_relevant_impl
    from llm_judge import judge_item_relevance

ensure_utf8_console()

RelevanceDecision = Decision

# ==================== 配置常量 ====================

# 时间窗口配置（天）
TIME_WINDOWS = {
    "news": 7,
    "research": 14,
    "policy": 30,
    "events": 90,  # 未来90天
    "funding": 7,
}

REQUIRED_RAW_FIELDS = {"title", "source", "date", "summary", "url"}
VALID_ITEM_TYPES = {"news", "research", "funding", "policy", "events"}
HTML_URL_ATTRS = {"href", "src", "action", "formaction", "poster"}
TITLE_SIMILARITY_THRESHOLD = 0.80
HISTORY_DEDUP_DAYS = 30
MAX_RAW_SCORE = 30
REQUIRED_SEARCH_ROUNDS = {"r1", "r2", "r3", "r4", "r5"}
SEARCH_QUERY_CONFIG_FILENAME = "search_queries.json"
URL_HEALTH_TIMEOUT_SECONDS = 10
URL_HEALTH_MAX_BYTES = 250_000
TITLE_MATCH_TIMEOUT_SECONDS = 10
TITLE_MATCH_MAX_BYTES = 300_000
TITLE_MATCH_MIN_SCORE = 0.30
SEARCH_CANDIDATE_LIST_KEYS = ("results", "candidates", "items", "organic_results", "web_results")
SEARCH_RESULT_TITLE_KEYS = ("title", "name", "headline")
SEARCH_RESULT_URL_KEYS = ("url", "link", "href", "source_url")
SEARCH_RESULT_SUMMARY_KEYS = ("summary", "snippet", "description", "content", "text", "abstract")
SEARCH_RESULT_SOURCE_KEYS = ("source", "site", "publisher", "source_name", "domain")
SEARCH_RESULT_DATE_KEYS = ("date", "published_at", "published_time", "published", "time", "datetime", "created_at")
LOW_APPROVED_COUNT_WARNING = 2
TRACKING_QUERY_PREFIXES = ("utm_",)
TRACKING_QUERY_KEYS = {
    "fbclid", "gclid", "mc_cid", "mc_eid", "igshid", "spm", "from", "ref",
}
DELETED_CONTENT_PATTERNS = [
    "文章已删除",
    "内容已删除",
    "该内容已被发布者删除",
    "该文章已被删除",
    "该文章不存在",
    "内容不存在",
    "页面不存在",
    "账号已删除",
    "帐号已删除",
    "账号已注销",
    "帐号已注销",
    "该账号已被封禁",
    "该帐号已被封禁",
    "此内容因违规无法查看",
    "已被删除或不可见",
    "404 not found",
    "page not found",
    "this article is no longer available",
    "this page is no longer available",
    "post not found",
]
APPROVED_REQUIRED_FIELDS = {
    "title", "source", "date", "summary", "url", "type", "raw_score", "value_score",
}
TYPE_TITLE_KEYWORDS = {
    "policy": ("政策", "法规", "监管", "规划", "计划", "报告", "项目", "措施", "指南", "征集", "通知", "公告", "课题", "专项", "申报", "标准", "开放共享", "grant", "call", "program", "programme", "proposal", "award", "regulation", "guidance"),
    "events": ("大会", "会议", "论坛", "研讨会", "峰会", "活动", "课程", "培训", "webinar", "conference", "symposium", "forum", "course", "summit", "workshop", "meeting", "webcast"),
    "funding": ("融资", "投资", "轮融资", "募资", "并购", "收购", "上市", "ipo", "series", "funding", "raised", "raises", "raise", "seed", "pre-a", "pre a", "round", "venture", "capital", "backs", "secures", "investment"),
    "research": ("研究", "论文", "nature", "science", "cell", "pnas", "acs", "发现", "突破", "engineer", "research", "journal", "study", "paper", "published", "publication", "biotechnology", "bioengineering"),
}
TYPE_NEGATIVE_KEYWORDS = {
    "policy": ("investment report", "forum", "conference", "course", "webinar", "融资", "投资报告"),
    "funding": ("forum", "conference", "course", "policy", "regulation", "guidance", "研究", "论文"),
    "events": ("investment report", "融资", "获投", "raised", "raises", "funding"),
}

def _is_synbio_relevant(title: str = "", summary: str = "", url: str = "") -> Tuple[bool, str, str]:
    """Backward-compatible wrapper for llm_judge.is_synbio_relevant."""
    return _is_synbio_relevant_impl(title, summary, url)


def _is_synbio_relevant_bool(title: str = "", summary: str = "", url: str = "") -> bool:
    """Boolean convenience wrapper for classifier-like callers."""
    is_relevant, _, _ = _is_synbio_relevant(title, summary, url)
    return is_relevant
POLICY_AUTHORITY_HINTS = (
    "gov", "政府", "科委", "科创局", "发改委", "工信", "科技部", "市监", "监管", "部门", "委员会", "协会",
    "ministry", "agency", "commission", "authority", "government", "programme", "program",
)

# 分类/聚合页面 URL 路径黑名单。
# 只拦真正的栏目/索引页；/news/article-slug 这类文章页必须允许。
URL_AGGREGATE_EXACT_PATHS = {
    "/", "/index", "/index.php", "/index.html",
    "/news", "/news/", "/newsfeed", "/newsfeed/", "/newsroom", "/newsroom/",
    "/read", "/read/",
    "/blogs", "/blogs/", "/blogs/news", "/blogs/news/",
    "/events", "/events/", "/event", "/event/",
    "/conference", "/conference/", "/conferences", "/conferences/",
    "/session", "/session/", "/sessions", "/sessions/",
    "/journal", "/journal/", "/journals", "/journals/",
    "/product", "/product/", "/products", "/products/",
    "/service", "/service/", "/services", "/services/",
    "/search", "/search/",
}
URL_AGGREGATE_PREFIXES = (
    "/category/", "/categories/",
    "/type/", "/types/",
    "/list/", "/lists/",
    "/tag/", "/tags/",
    "/topic/", "/topics/",
    "/topic-hub/",
    "/search/",
)
URL_AGGREGATE_SUFFIXES = (
    "/news-and-features",
)
URL_AGGREGATE_PATH_EXCEPTIONS = (
    r"/zxcg\.htm$",
    r"/cg\.htm$",
    r"/latest-results?\.html$",
    r"/publications?\.html$",
    r"/papers?\.html$",
)

# 需要排除的域名片段（内容聚合站）
DOMAIN_BLACKLIST = [
    "newmarketpitch.com",  # 聚合多篇文章的市场报告站
    "conferences.nature.com",  # Nature 会议列表首页
    "synbioconference.org",  # SEED 会议列表首页
]

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


def normalize_raw_input(raw_obj: Any, item_type: str) -> List[Dict[str, Any]]:
    """Normalize raw JSON into a list for one category."""
    if item_type not in VALID_ITEM_TYPES:
        raise ValueError(f"unknown item type: {item_type}")

    if isinstance(raw_obj, dict):
        items = raw_obj.get(item_type, [])
    elif isinstance(raw_obj, list):
        items = raw_obj
    else:
        raise ValueError("raw data must be a list or a category dict")

    if not isinstance(items, list):
        raise ValueError(f"raw data for {item_type} must be a list")

    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise ValueError(f"raw item at index {index} must be a dict")

    return items


def count_raw_items(raw_obj: Any) -> int:
    """Count raw candidates across a full category dict or a single-category list."""
    if isinstance(raw_obj, dict):
        return sum(
            len(raw_obj.get(item_type, []))
            for item_type in sorted(VALID_ITEM_TYPES)
            if isinstance(raw_obj.get(item_type, []), list)
        )
    if isinstance(raw_obj, list):
        return len(raw_obj)
    raise ValueError("raw data must be a list or a category dict")


def _first_nonempty(mapping: Dict[str, Any], keys: Tuple[str, ...]) -> Any:
    for key in keys:
        value = mapping.get(key)
        if value not in (None, ""):
            return value
    return ""


def _search_result_dicts(search_log: Any) -> List[Tuple[str, str, Dict[str, Any]]]:
    """Return structured search result dicts with their source round/query."""
    if not isinstance(search_log, dict):
        return []
    results: list[tuple[str, str, dict[str, Any]]] = []
    for round_entry in search_log.get("rounds", []) or []:
        if not isinstance(round_entry, dict):
            continue
        round_id = str(round_entry.get("round") or round_entry.get("id") or "").strip()
        queries = round_entry.get("queries", []) or []
        query_texts = [str(q) for q in queries if not isinstance(q, dict) and q]
        if not query_texts:
            query_texts = [str(q.get("query") or q.get("q") or "") for q in queries if isinstance(q, dict)]
        default_query = next((q for q in query_texts if q), "")
        for list_key in SEARCH_CANDIDATE_LIST_KEYS:
            candidates = round_entry.get(list_key)
            if not isinstance(candidates, list):
                continue
            for candidate in candidates:
                if isinstance(candidate, dict):
                    query = str(candidate.get("source_query") or candidate.get("query") or candidate.get("search_query") or default_query)
                    results.append((round_id, query, candidate))
        for query_entry in queries:
            if not isinstance(query_entry, dict):
                continue
            query = str(query_entry.get("query") or query_entry.get("q") or "")
            for list_key in SEARCH_CANDIDATE_LIST_KEYS:
                candidates = query_entry.get(list_key)
                if not isinstance(candidates, list):
                    continue
                for candidate in candidates:
                    if isinstance(candidate, dict):
                        results.append((round_id, query, candidate))
    return results


def _search_candidate_urls(search_log: Any) -> set[str]:
    """Collect candidate URLs from both legacy URL lists and structured search results."""
    urls: set[str] = set()
    if not isinstance(search_log, dict):
        return urls
    for round_entry in search_log.get("rounds", []) or []:
        if not isinstance(round_entry, dict):
            continue
        for list_key in SEARCH_CANDIDATE_LIST_KEYS:
            candidates = round_entry.get(list_key)
            if isinstance(candidates, list):
                for candidate in candidates:
                    if isinstance(candidate, str) and candidate:
                        urls.add(canonicalize_url(candidate))
                    elif isinstance(candidate, dict):
                        url = _first_nonempty(candidate, SEARCH_RESULT_URL_KEYS)
                        if url:
                            urls.add(canonicalize_url(str(url)))
        for query_entry in round_entry.get("queries", []) or []:
            if not isinstance(query_entry, dict):
                continue
            for list_key in SEARCH_CANDIDATE_LIST_KEYS:
                candidates = query_entry.get(list_key)
                if not isinstance(candidates, list):
                    continue
                for candidate in candidates:
                    if isinstance(candidate, str) and candidate:
                        urls.add(canonicalize_url(candidate))
                    elif isinstance(candidate, dict):
                        url = _first_nonempty(candidate, SEARCH_RESULT_URL_KEYS)
                        if url:
                            urls.add(canonicalize_url(str(url)))
    return urls


def _raw_candidate_urls(raw_obj: Any) -> set[str]:
    urls: set[str] = set()
    if isinstance(raw_obj, dict):
        item_lists = [
            raw_obj.get(item_type, [])
            for item_type in sorted(VALID_ITEM_TYPES)
            if isinstance(raw_obj.get(item_type, []), list)
        ]
    elif isinstance(raw_obj, list):
        item_lists = [raw_obj]
    else:
        return urls
    for items in item_lists:
        for item in items:
            if not isinstance(item, dict):
                continue
            url = item.get("url")
            if url:
                urls.add(canonicalize_url(str(url)))
    return urls


def infer_item_type_from_search_result(result: Dict[str, Any], query: str = "") -> str:
    """Infer the most likely raw category from search result text and query context."""
    url = str(_first_nonempty(result, SEARCH_RESULT_URL_KEYS) or "")
    title = str(_first_nonempty(result, SEARCH_RESULT_TITLE_KEYS) or "")
    summary = str(_first_nonempty(result, SEARCH_RESULT_SUMMARY_KEYS) or "")
    text = " ".join(str(part or "") for part in (
        title,
        summary,
        _first_nonempty(result, SEARCH_RESULT_SOURCE_KEYS),
        url,
        query,
    )).lower()
    if any(keyword.lower() in text for keyword in TYPE_TITLE_KEYWORDS["funding"]):
        return "funding"
    if any(keyword.lower() in text for keyword in TYPE_TITLE_KEYWORDS["events"]):
        return "events"
    if any(keyword in text for keyword in ("白皮书", "行业报告", "产业报告", "blue paper", "white paper")):
        return "news"
    has_policy_keyword = any(keyword.lower() in text for keyword in TYPE_TITLE_KEYWORDS["policy"])
    has_policy_authority = any(hint.lower() in text for hint in POLICY_AUTHORITY_HINTS)
    netloc = urlsplit(url).netloc.lower()
    is_gov_cn = netloc.endswith(".gov.cn") or ".gov.cn:" in netloc
    if has_policy_keyword and (has_policy_authority or is_gov_cn):
        return "policy"
    if any(keyword.lower() in text for keyword in TYPE_TITLE_KEYWORDS["research"]):
        return "research"
    # LLM 语义判断：即使无典型研究关键词，合成生物学相关技术内容也归为 research
    if _is_synbio_relevant_bool(title=title, summary=summary, url=url):
        return "research"
    return "news"


def normalize_search_result_date(date_text: str, report_date: str | None = None) -> str:
    """Normalize explicit or relative search-result dates without inventing missing dates."""
    raw = str(date_text or "").strip()
    if parse_date(raw):
        return raw

    base_date = parse_date(report_date or "") or now_local().replace(tzinfo=None)
    text = raw.lower()
    relative_patterns = [
        (r"(\d+)\s*天前", "days"),
        (r"(\d+)\s*日前", "days"),
        (r"(\d+)\s*days?\s+ago", "days"),
        (r"(\d+)\s*小时前", "hours"),
        (r"(\d+)\s*hours?\s+ago", "hours"),
    ]
    for pattern, unit in relative_patterns:
        match = re.search(pattern, text)
        if not match:
            continue
        amount = int(match.group(1))
        delta = timedelta(days=amount) if unit == "days" else timedelta(hours=amount)
        return (base_date - delta).strftime("%Y-%m-%d")
    if any(marker in text for marker in ("今天", "今日", "today", "刚刚")):
        return base_date.strftime("%Y-%m-%d")
    if any(marker in text for marker in ("昨天", "yesterday")):
        return (base_date - timedelta(days=1)).strftime("%Y-%m-%d")
    return "N/A"


def normalize_search_result_to_raw_item(
    result: Dict[str, Any],
    round_id: str,
    query: str = "",
    report_date: str | None = None,
) -> Dict[str, Any] | None:
    """Convert one structured search result into a raw candidate item."""
    title = str(_first_nonempty(result, SEARCH_RESULT_TITLE_KEYS) or "").strip()
    url = str(_first_nonempty(result, SEARCH_RESULT_URL_KEYS) or "").strip()
    if not title or not url:
        return None
    summary = str(_first_nonempty(result, SEARCH_RESULT_SUMMARY_KEYS) or title).strip()
    source = str(_first_nonempty(result, SEARCH_RESULT_SOURCE_KEYS) or urlsplit(url).netloc or "搜索结果").strip()
    date_value = str(_first_nonempty(result, SEARCH_RESULT_DATE_KEYS) or "").strip()
    date_value = normalize_search_result_date(date_value or summary or title, report_date=report_date)
    item_type = str(result.get("type") or result.get("category") or "").strip()
    if item_type not in VALID_ITEM_TYPES:
        item_type = infer_item_type_from_search_result(result, query=query)
    item = {
        "title": title,
        "source": source,
        "date": date_value,
        "summary": summary,
        "url": url,
        "type": item_type,
        "source_round": round_id,
    }
    if query:
        item["source_query"] = query
    return item


def build_raw_from_search_log(search_log: Any, report_date: str | None = None) -> Dict[str, Any]:
    """Build a full raw category dict from structured search_log results."""
    raw = {item_type: [] for item_type in sorted(VALID_ITEM_TYPES)}
    seen_urls: set[str] = set()
    skipped = 0
    for round_id, query, result in _search_result_dicts(search_log):
        item = normalize_search_result_to_raw_item(result, round_id, query=query, report_date=report_date)
        if not item:
            skipped += 1
            continue
        canonical_url = canonicalize_url(str(item.get("url", "")))
        if canonical_url in seen_urls:
            continue
        seen_urls.add(canonical_url)
        raw[item["type"]].append(item)
    raw["_meta"] = {
        "generated_by": "report_pipeline.build_raw_from_search_log",
        "report_date": report_date,
        "structured_results": len(_search_result_dicts(search_log)),
        "raw_items": count_raw_items(raw),
        "skipped_results": skipped,
    }
    return raw


def validate_search_coverage(search_log: Any, raw_obj: Any) -> Dict[str, Any]:
    """Compare search candidates with raw items so search results cannot silently disappear."""
    search_urls = _search_candidate_urls(search_log)
    raw_urls = _raw_candidate_urls(raw_obj)
    missing_urls = sorted(search_urls - raw_urls)
    return {
        "is_valid": len(missing_urls) == 0,
        "errors": [f"搜索结果有{len(missing_urls)}条URL未进入raw数据"] if missing_urls else [],
        "warnings": [],
        "search_candidate_count": len(search_urls),
        "raw_url_count": len(raw_urls),
        "missing_urls": missing_urls,
        "coverage_ratio": 1.0 if not search_urls else round(len(search_urls & raw_urls) / len(search_urls), 3),
    }


def load_search_query_config() -> Dict[str, Any]:
    """Load the required daily search query configuration."""
    config_path = CONFIG_DIR / SEARCH_QUERY_CONFIG_FILENAME
    if not config_path.exists():
        return {}
    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)
    if not isinstance(config, dict):
        raise ValueError("search_queries.json必须是对象")
    rounds = config.get("rounds", [])
    if rounds is not None and not isinstance(rounds, list):
        raise ValueError("search_queries.json中的rounds必须是列表")
    return config


def _normalize_query_text(query: Any) -> str:
    return re.sub(r"\s+", " ", str(query or "")).strip()


def _bool_from_search_log_value(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() not in {"0", "false", "no", "n", "否", "未执行"}
    return bool(value)


def _query_status_from_entry(query_entry: Any) -> Tuple[str, bool, str]:
    """Return query text, executed status, and failure reason from one search_log query entry."""
    if isinstance(query_entry, str):
        return _normalize_query_text(query_entry), True, ""
    if not isinstance(query_entry, dict):
        return "", False, ""

    query = _normalize_query_text(query_entry.get("query") or query_entry.get("q") or "")
    error = str(query_entry.get("error") or query_entry.get("reason") or query_entry.get("failure") or "").strip()
    if "executed" in query_entry:
        executed = _bool_from_search_log_value(query_entry.get("executed"))
    elif error:
        executed = False
    else:
        executed = True
    return query, executed, error


def _collect_search_log_query_status(
    search_log: Any,
) -> Tuple[Dict[str, Dict[str, str]], Dict[str, Dict[str, Dict[str, str]]]]:
    """Collect executed and failed queries by round from old and new search_log formats."""
    executed_by_round: dict[str, dict[str, str]] = {}
    failed_by_round: dict[str, dict[str, dict[str, str]]] = {}
    if not isinstance(search_log, dict):
        return executed_by_round, failed_by_round

    for round_entry in search_log.get("rounds", []) or []:
        if not isinstance(round_entry, dict):
            continue
        round_id = str(round_entry.get("round") or round_entry.get("id") or round_entry.get("round_id") or "").strip()
        if not round_id:
            continue
        executed_by_round.setdefault(round_id, {})
        failed_by_round.setdefault(round_id, {})

        queries = round_entry.get("queries", []) or []
        if isinstance(queries, list):
            for query_entry in queries:
                query, executed, error = _query_status_from_entry(query_entry)
                if not query:
                    continue
                normalized = _normalize_query_text(query)
                if executed:
                    executed_by_round[round_id][normalized] = query
                else:
                    failed_by_round[round_id][normalized] = {"query": query, "error": error}

                if isinstance(query_entry, dict):
                    for list_key in SEARCH_CANDIDATE_LIST_KEYS:
                        candidates = query_entry.get(list_key)
                        if not isinstance(candidates, list):
                            continue
                        for candidate in candidates:
                            if isinstance(candidate, dict):
                                source_query = _normalize_query_text(
                                    candidate.get("source_query") or candidate.get("query") or candidate.get("search_query")
                                )
                                if source_query:
                                    executed_by_round[round_id][source_query] = source_query

        for list_key in SEARCH_CANDIDATE_LIST_KEYS:
            candidates = round_entry.get(list_key)
            if not isinstance(candidates, list):
                continue
            for candidate in candidates:
                if isinstance(candidate, dict):
                    source_query = _normalize_query_text(
                        candidate.get("source_query") or candidate.get("query") or candidate.get("search_query")
                    )
                    if source_query:
                        executed_by_round[round_id][source_query] = source_query

    return executed_by_round, failed_by_round


def _round_source_queries(round_entry: Dict[str, Any]) -> set[str]:
    """Collect query evidence from legacy candidate-only search_log rounds."""
    source_queries: set[str] = set()
    for list_key in SEARCH_CANDIDATE_LIST_KEYS:
        candidates = round_entry.get(list_key)
        if not isinstance(candidates, list):
            continue
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            source_query = _normalize_query_text(
                candidate.get("source_query") or candidate.get("query") or candidate.get("search_query")
            )
            if source_query:
                source_queries.add(source_query)
    return source_queries


def validate_required_search_queries(search_log: Any) -> Dict[str, Any]:
    """Validate that configured required search queries were actually executed."""
    config = load_search_query_config()
    rounds_config = config.get("rounds", []) if isinstance(config, dict) else []
    if not rounds_config:
        return {
            "is_valid": False,
            "errors": [f"搜索查询配置缺失或未配置rounds: {CONFIG_DIR / SEARCH_QUERY_CONFIG_FILENAME}"],
            "warnings": [],
            "required_total": 0,
            "executed_required_count": 0,
            "missing_by_round": {},
            "failed_by_round": {},
        }
    executed_by_round, failed_by_round = _collect_search_log_query_status(search_log)
    missing_by_round: dict[str, list[str]] = {}
    failed_required_by_round: dict[str, list[dict[str, str]]] = {}
    required_total = 0

    for round_cfg in rounds_config:
        if not isinstance(round_cfg, dict):
            continue
        round_id = str(round_cfg.get("round_id") or round_cfg.get("round") or round_cfg.get("id") or "").strip()
        if not round_id:
            continue
        required_queries = [
            _normalize_query_text(query)
            for query in round_cfg.get("required_queries", []) or []
            if _normalize_query_text(query)
        ]
        required_total += len(required_queries)
        executed = executed_by_round.get(round_id, {})
        failed = failed_by_round.get(round_id, {})
        for query in required_queries:
            normalized = _normalize_query_text(query)
            if normalized in executed:
                continue
            if normalized in failed:
                failed_required_by_round.setdefault(round_id, []).append(failed[normalized])
            else:
                missing_by_round.setdefault(round_id, []).append(query)

    messages: list[str] = []
    for round_id, missing in sorted(missing_by_round.items()):
        preview = "；".join(missing[:5])
        suffix = f" 等{len(missing)}条" if len(missing) > 5 else ""
        messages.append(f"搜索轮次 {round_id} 缺少必需查询: {preview}{suffix}")
    for round_id, failed in sorted(failed_required_by_round.items()):
        formatted = []
        for item in failed[:5]:
            query = item.get("query", "")
            error = item.get("error") or "未记录原因"
            formatted.append(f"{query} ({error})")
        suffix = f" 等{len(failed)}条" if len(failed) > 5 else ""
        messages.append(f"搜索轮次 {round_id} 必需查询未成功执行: {'；'.join(formatted)}{suffix}")

    executed_required_count = required_total - sum(len(v) for v in missing_by_round.values()) - sum(
        len(v) for v in failed_required_by_round.values()
    )
    return {
        "is_valid": not messages,
        "errors": messages,
        "warnings": [],
        "required_total": required_total,
        "executed_required_count": executed_required_count,
        "missing_by_round": missing_by_round,
        "failed_by_round": failed_required_by_round,
    }


def validate_raw_item(item: Dict[str, Any], item_type: str) -> Tuple[bool, str, Dict[str, Any]]:
    """Validate and normalize one raw item before filtering."""
    normalized = dict(item)
    missing = sorted(
        field for field in REQUIRED_RAW_FIELDS
        if field not in normalized or normalized.get(field) in (None, "")
    )
    if missing:
        return False, f"[schema] missing required fields: {', '.join(missing)}", normalized

    normalized["type"] = normalized.get("type") or item_type
    if normalized["type"] not in VALID_ITEM_TYPES:
        return False, f"[schema] invalid type: {normalized['type']}", normalized
    if normalized["type"] != item_type:
        return False, f"[schema] type mismatch: item has {normalized['type']}, category is {item_type}", normalized

    try:
        safe_url(str(normalized.get("url", "")))
    except ValueError:
        url = str(normalized.get("url", ""))
        return False, f"[schema] invalid url: {url}", normalized

    if not _looks_like_type(normalized, item_type):
        return False, f"[schema] type content mismatch: item does not look like {item_type}", normalized

    return True, "", normalized


def canonicalize_url(url: str) -> str:
    """Return a stable URL for equality checks while preserving article identity."""
    parts = urlsplit(str(url or "").strip())
    scheme = parts.scheme.lower()
    netloc = parts.netloc.lower()
    path = parts.path or "/"
    query_pairs = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        key_lower = key.lower()
        if key_lower in TRACKING_QUERY_KEYS or key_lower.startswith(TRACKING_QUERY_PREFIXES):
            continue
        query_pairs.append((key, value))
    query = urlencode(query_pairs, doseq=True)
    return urlunsplit((scheme, netloc, path, query, ""))


def _hostname_matches(hostname: str, domain: str) -> bool:
    hostname = hostname.lower().strip(".")
    domain = domain.lower().strip(".")
    return hostname == domain or hostname.endswith(f".{domain}")


def _is_category_or_aggregate_url(url: str) -> bool:
    """判断 URL 是否为分类页、聚合页或列表页。"""
    if not url:
        return True

    try:
        parts = urlsplit(url)
    except ValueError:
        return True

    hostname = (parts.hostname or "").lower()
    if not hostname:
        return True

    for domain in DOMAIN_BLACKLIST:
        if _hostname_matches(hostname, domain):
            return True

    path = parts.path or "/"
    normalized_path = re.sub(r"/{2,}", "/", path).lower()
    if normalized_path != "/" and normalized_path.endswith("/"):
        slashless_path = normalized_path.rstrip("/")
    else:
        slashless_path = normalized_path

    if any(re.search(pattern, slashless_path) for pattern in URL_AGGREGATE_PATH_EXCEPTIONS):
        return False

    if normalized_path in URL_AGGREGATE_EXACT_PATHS or slashless_path in URL_AGGREGATE_EXACT_PATHS:
        return True

    if any(normalized_path.startswith(prefix) for prefix in URL_AGGREGATE_PREFIXES):
        return True

    if any(slashless_path.endswith(suffix) for suffix in URL_AGGREGATE_SUFFIXES):
        return True

    # 检查查询参数是否为搜索/分页类聚合参数
    query_params = parse_qsl(parts.query)
    query_keys = {k.lower() for k, _ in query_params}
    listing_paths = ("/search", "/list", "/lists", "/category", "/tag", "/tags", "/topic")
    if query_keys & {"searchkey", "search", "q", "keyword", "keywords", "query", "s"} and any(
        normalized_path.startswith(path) for path in listing_paths
    ):
        return True
    # 带有分页参数的文章页可能是列表页（如 /news?page=1）
    if "page" in query_keys and slashless_path in {"/news", "/blogs", "/article", "/read", "/list", "/lists"}:
        return True
    if "categoryid" in query_keys:
        return True

    if slashless_path == "/search":
        return True

    return False


def _load_history_index():
    """加载 history_index.json 用于跨天持久化去重"""
    data_dir = Path(DATA_DIR) if 'DATA_DIR' in globals() else Path(__file__).resolve().parents[1] / "data"
    history_path = data_dir / "history_index.json"
    if history_path.exists():
        try:
            with open(history_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("entries", [])
        except Exception:
            pass
    return []


def _normalize_history_text(text: str) -> str:
    text = str(text or "").lower()
    text = re.sub(r"[^\u4e00-\u9fff\w\s]", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _history_tokens(text: str) -> set[str]:
    normalized = _normalize_history_text(text)
    tokens = {token for token in re.findall(r"[a-z0-9]{4,}", normalized)}
    chinese_text = "".join(re.findall(r"[\u4e00-\u9fff]+", normalized))
    for size in (2, 3, 4):
        for index in range(0, max(len(chinese_text) - size + 1, 0)):
            tokens.add(chinese_text[index:index + size])
    return tokens


def _make_fingerprint(item):
    """生成基于中英文内容关键词的指纹，用于跨天去重。"""
    tokens = _history_tokens(f"{item.get('title', '')} {item.get('summary', '')}")
    return " ".join(sorted(tokens)[:80])


def _coerce_url_list(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(url or "") for url in value if url]
    return []


def _item_candidate_urls(item) -> list[str]:
    """Return all primary and secondary URLs for duplicate/link checks."""
    urls = [item.get("url", "")]
    urls.extend(_coerce_url_list(item.get("urls", [])))
    return [url for url in dict.fromkeys(str(url or "") for url in urls) if url]


def _is_historical_duplicate(item, history_entries):
    """
    检查 item 是否与历史索引中的条目重复。
    检查维度：URL 完全匹配、标题完全匹配、内容指纹相似度 > 75%。
    """
    if not history_entries:
        return False
    item_urls = {canonicalize_url(url) for url in _item_candidate_urls(item)}
    item_title = item.get("title", "").strip()
    item_title_norm = normalize_title(item_title)
    item_fp = _make_fingerprint(item)
    item_tokens = set(item_fp.split())
    for entry in history_entries:
        # URL 完全匹配
        entry_urls = [entry.get("canonical_url") or canonicalize_url(entry.get("url", ""))]
        entry_urls.extend(canonicalize_url(url) for url in _coerce_url_list(entry.get("urls", [])))
        entry_urls = {url for url in entry_urls if url}
        if item_urls and item_urls & entry_urls:
            return True
        # 标题完全匹配
        entry_title = entry.get("title", "")
        if item_title_norm and item_title_norm == normalize_title(entry_title):
            return True
        # 内容指纹相似度
        hist_fp = entry.get("fingerprint", "")
        if item_fp and hist_fp:
            hist_tokens = set(str(hist_fp).split())
            overlap = len(item_tokens & hist_tokens) / max(len(item_tokens | hist_tokens), 1)
            sim = max(overlap, SequenceMatcher(None, item_fp, hist_fp).ratio())
            if sim >= 0.75:
                return True
    return False


def _is_ssl_network_error(exc: BaseException) -> bool:
    """Return True for SSL/certificate failures that may be local network issues."""
    if isinstance(exc, ssl.SSLError):
        return True
    reason = getattr(exc, "reason", None)
    if isinstance(reason, ssl.SSLError):
        return True
    text = f"{exc} {reason}".lower()
    return any(marker in text for marker in ("ssl", "certificate", "cert_verify", "bad_ecpoint", "bad ecpoint"))


def check_url_health(
    url: str,
    timeout: int = URL_HEALTH_TIMEOUT_SECONDS,
    opener=urlopen,
    mode: str = "strict",
) -> Dict[str, Any]:
    """Check whether a URL opens and does not look like a deleted/invalid article."""
    try:
        safe_url(url)
    except ValueError as exc:
        return {"ok": False, "url": url, "reason": f"URL不安全: {exc}"}

    request = Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/126.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
    )
    try:
        with opener(request, timeout=timeout) as response:
            status = getattr(response, "status", getattr(response, "code", 200))
            final_url = getattr(response, "url", url)
            headers = getattr(response, "headers", {}) or {}
            content_type = ""
            if hasattr(headers, "get"):
                content_type = headers.get("Content-Type", "") or headers.get("content-type", "")

            if status >= 400:
                return {"ok": False, "url": url, "status": status, "reason": f"HTTP状态异常: {status}"}

            if any(kind in content_type.lower() for kind in ("text/", "html", "xml", "json", "")):
                body = response.read(URL_HEALTH_MAX_BYTES)
                charset = "utf-8"
                if hasattr(headers, "get_content_charset"):
                    charset = headers.get_content_charset() or charset
                text = body.decode(charset, errors="replace")
                text_lower = text.lower()
                for pattern in DELETED_CONTENT_PATTERNS:
                    if pattern.lower() in text_lower:
                        return {
                            "ok": False,
                            "url": url,
                            "status": status,
                            "reason": f"页面疑似失效/删除: {pattern}",
                        }

            return {"ok": True, "url": url, "status": status, "final_url": final_url}
    except HTTPError as exc:
        return {"ok": False, "url": url, "status": exc.code, "reason": f"HTTP状态异常: {exc.code}"}
    except (URLError, TimeoutError, socket.timeout, ssl.SSLError) as exc:
        if str(mode).lower() == "soft" and _is_ssl_network_error(exc):
            return {
                "ok": True,
                "url": url,
                "warning": f"SSL/证书网络检查失败，soft模式不阻断: {exc}",
                "ssl_warning": True,
            }
        return {"ok": False, "url": url, "reason": f"URL无法打开: {exc}"}
    except Exception as exc:
        return {"ok": False, "url": url, "reason": f"URL检查失败: {exc}"}


def validate_approved_url_health(
    approved_data: List[Dict[str, Any]],
    label: str = "approved",
    check_func=check_url_health,
) -> Dict[str, Any]:
    """Ensure every approved URL is reachable and not a known deleted-content page."""
    return validate_url_health(collect_approved_urls(approved_data), label=label, check_func=check_func)


def validate_url_health(
    urls: List[str],
    label: str = "URL",
    check_func=check_url_health,
    mode: str = "strict",
) -> Dict[str, Any]:
    """Ensure each outbound URL is reachable and not a known deleted-content page."""
    urls = list(dict.fromkeys(urls))
    errors = []
    warnings = []
    checked = []
    for url in urls:
        try:
            result = check_func(url, mode=mode)
        except TypeError:
            result = check_func(url)
        checked.append(result)
        if not result.get("ok"):
            errors.append(f"{label}链接不可用: {url} - {result.get('reason', '未知错误')}")
        if result.get("warning"):
            warnings.append(f"{label}链接警告: {url} - {result['warning']}")

    return {
        "is_valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "checked_urls": checked,
        "total_checked": len(checked),
    }


def _strip_html_tags(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    return re.sub(r"\s+", " ", unescape(text)).strip()


class HTMLTitleSignalExtractor(HTMLParser):
    """Extract page title signals while respecting normal HTML parsing rules."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.signals: list[str] = []
        self._capture_tag: str | None = None
        self._capture_chunks: list[str] = []
        self._captured_tags: set[str] = set()

    def _add_signal(self, value: str) -> None:
        signal = _strip_html_tags(value)
        if signal and signal not in self.signals:
            self.signals.append(signal)

    def handle_starttag(self, tag, attrs):
        tag_name = str(tag or "").lower()
        attr_map = {str(name or "").lower(): value for name, value in attrs}
        if tag_name == "meta":
            title_kind = str(attr_map.get("property") or attr_map.get("name") or "").lower()
            if title_kind in {"og:title", "twitter:title"} and attr_map.get("content"):
                self._add_signal(str(attr_map["content"]))
            return
        if tag_name in {"title", "h1"} and tag_name not in self._captured_tags:
            self._capture_tag = tag_name
            self._capture_chunks = []

    def handle_data(self, data):
        if self._capture_tag:
            self._capture_chunks.append(data)

    def handle_endtag(self, tag):
        tag_name = str(tag or "").lower()
        if self._capture_tag == tag_name:
            self._add_signal("".join(self._capture_chunks))
            self._captured_tags.add(tag_name)
            self._capture_tag = None
            self._capture_chunks = []


def extract_title_signals(html_text: str) -> List[str]:
    """Extract page title candidates from common HTML title signals."""
    parser = HTMLTitleSignalExtractor()
    parser.feed(html_text or "")
    parser.close()
    return parser.signals


def _title_tokens(text: str) -> set[str]:
    raw = str(text or "").lower()
    tokens = set(re.findall(r"[a-z0-9]{3,}", raw))
    for chunk in re.findall(r"[\u4e00-\u9fff]{2,}", raw):
        for size in (2, 3, 4):
            if len(chunk) >= size:
                tokens.update(chunk[index:index + size] for index in range(0, len(chunk) - size + 1))
    return {token for token in tokens if token}


def title_match_score(item_title: str, page_title: str) -> float:
    """Return a conservative 0-1 score for item title vs page title."""
    item_norm = normalize_title(item_title)
    page_norm = normalize_title(page_title)
    if not item_norm or not page_norm:
        return 0.0
    if item_norm in page_norm or page_norm in item_norm:
        return 1.0
    item_tokens = _title_tokens(item_title)
    page_tokens = _title_tokens(page_title)
    if not item_tokens or not page_tokens:
        return SequenceMatcher(None, item_norm, page_norm).ratio()
    overlap = len(item_tokens & page_tokens) / max(len(item_tokens), 1)
    if re.search(r"[\u4e00-\u9fff]", item_title + page_title):
        return overlap
    return max(overlap, SequenceMatcher(None, item_norm, page_norm).ratio())


def check_url_title_match(
    item: Dict[str, Any],
    timeout: int = TITLE_MATCH_TIMEOUT_SECONDS,
    opener=urlopen,
    min_score: float = TITLE_MATCH_MIN_SCORE,
) -> Dict[str, Any]:
    """Check whether a reachable page title matches the collected item title."""
    url = str(item.get("url") or "")
    item_title = str(item.get("title") or "")
    if not url or not item_title:
        return {"ok": True, "url": url, "warning": "缺少URL或标题，跳过标题匹配"}

    try:
        safe_url(url)
    except ValueError as exc:
        return {"ok": False, "url": url, "reason": f"URL不安全: {exc}"}

    request = Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/126.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
    )
    try:
        with opener(request, timeout=timeout) as response:
            status = getattr(response, "status", getattr(response, "code", 200))
            if status >= 400:
                return {"ok": True, "url": url, "warning": f"标题匹配跳过: HTTP {status}"}
            headers = getattr(response, "headers", {}) or {}
            charset = "utf-8"
            if hasattr(headers, "get_content_charset"):
                charset = headers.get_content_charset() or charset
            body = response.read(TITLE_MATCH_MAX_BYTES)
    except (HTTPError, URLError, TimeoutError, socket.timeout, ssl.SSLError) as exc:
        return {"ok": True, "url": url, "warning": f"标题匹配跳过: URL无法读取 ({exc})"}
    except Exception as exc:
        return {"ok": True, "url": url, "warning": f"标题匹配跳过: {exc}"}

    html_text = body.decode(charset, errors="replace")
    signals = extract_title_signals(html_text)
    if not signals:
        return {"ok": True, "url": url, "warning": "标题匹配跳过: 页面无可解析标题信号"}

    scored = [(signal, title_match_score(item_title, signal)) for signal in signals]
    best_title, best_score = max(scored, key=lambda pair: pair[1])
    if best_score < min_score:
        return {
            "ok": False,
            "url": url,
            "reason": f"标题与页面不匹配: item='{item_title}', page='{best_title}', score={best_score:.2f}",
            "page_titles": signals,
            "score": best_score,
        }
    return {"ok": True, "url": url, "page_titles": signals, "score": best_score}


def remove_title_mismatch_items(
    items: List[Dict[str, Any]],
    title_check_func=check_url_title_match,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[str]]:
    """Drop items whose reachable page title clearly does not match the item title."""
    kept: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    warnings: list[str] = []
    for item in items:
        result = title_check_func(item)
        if not result.get("ok"):
            rejected.append({
                "item": item,
                "reason": f"[标题匹配] {result.get('reason', '标题与URL页面不匹配')}",
                "action": "排除",
            })
            continue
        if result.get("warning"):
            warnings.append(f"{item.get('title', '未命名信息')}: {result['warning']}")
        kept.append(item)
    return kept, rejected, warnings


def normalize_title(title: str) -> str:
    """Normalize titles before similarity checks."""
    title = re.sub(r"\s+", "", str(title or "").lower())
    title = re.sub(r"[^\w\u4e00-\u9fff]+", "", title)
    return title


def title_similarity(a: str, b: str) -> float:
    """Return SequenceMatcher title similarity in the 0-1 range."""
    left = normalize_title(a)
    right = normalize_title(b)
    if not left or not right:
        return 0.0
    return SequenceMatcher(None, left, right).ratio()


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


def load_historical_events(days: int = HISTORY_DEDUP_DAYS) -> Dict[str, Dict[str, Any]]:
    """加载最近N天的历史事件指纹库"""
    fingerprint_db = {}
    
    now = now_local().replace(tzinfo=None)
    cutoff_date = now - timedelta(days=days)
    today_str = now.strftime("%Y-%m-%d")
    
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
                similarity = title_similarity(title, existing_title)
                if similarity >= TITLE_SIMILARITY_THRESHOLD:
                    return True, f"标题相似度{similarity:.0%}: {existing_title} ({existing_data['date']})"
    
    return False, ""


def check_timeliness(item: Dict[str, Any], item_type: str, now: Optional[datetime] = None) -> Tuple[bool, str]:
    """检查时效性"""
    date_str = item.get("date", "")
    item_date = parse_date(date_str)
    current_time = (now or now_local()).replace(tzinfo=None)
    
    if not item_date:
        return False, f"无法解析日期 ({date_str})"
    
    window_days = TIME_WINDOWS.get(item_type, 7)
    cutoff = current_time - timedelta(days=window_days)
    # 只比较日期部分，避免边界时间问题
    cutoff = cutoff.replace(hour=0, minute=0, second=0, microsecond=0)
    
    if item_type == "events":
        # 活动预告：检查是否在未来90天内
        future_cutoff = current_time + timedelta(days=window_days)
        today = current_time.replace(hour=0, minute=0, second=0, microsecond=0)
        item_day = item_date.replace(hour=0, minute=0, second=0, microsecond=0)
        if item_day < today:
            return False, f"活动已过期 ({date_str})"
        if item_date > future_cutoff:
            return False, f"活动太远 ({date_str}, 超过{window_days}天)"
        return True, ""
    
    if item_date < cutoff:
        return False, f"超过时间窗口 ({date_str}, 限制{window_days}天)"
    
    return True, ""


def calculate_raw_score(item: Dict[str, Any]) -> int:
    """计算信息价值原始分数"""
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
        days_ago = (now_local().replace(tzinfo=None) - item_date).days
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


def normalize_value_score(raw_score: int) -> float:
    """Normalize raw score into the documented 0-10 range."""
    return min(10.0, round(max(raw_score, 0) / MAX_RAW_SCORE * 10, 1))


def calculate_value_score(item: Dict[str, Any]) -> float:
    """计算0-10范围的信息价值分数"""
    return normalize_value_score(calculate_raw_score(item))


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
    fingerprint_db = load_historical_events(days=HISTORY_DEDUP_DAYS)
    policy_db = load_policy_database()
    history_entries = _load_history_index()
    
    approved = []
    rejected = []
    
    for item in raw_data:
        schema_ok, schema_reason, item = validate_raw_item(item, item_type)
        if not schema_ok:
            rejected.append({
                "item": item,
                "reason": schema_reason,
                "action": "排除",
            })
            continue
        
        # 0. URL 过滤：排除分类/聚合页面和黑名单域名
        url = item.get("url", "")
        if _is_category_or_aggregate_url(url):
            rejected.append({
                "item": item,
                "reason": f"[URL过滤] 聚合页/黑名单域名: {url}",
                "action": "排除",
            })
            continue
        
        # 0.5 跨天历史索引去重（基于 history_index.json 的持久化去重）
        if _is_historical_duplicate(item, history_entries):
            rejected.append({
                "item": item,
                "reason": "[历史索引去重] 与已发送历史记录重复",
                "action": "排除",
            })
            continue
        
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
        raw_score = calculate_raw_score(item)
        item["raw_score"] = raw_score
        item["value_score"] = normalize_value_score(raw_score)
        
        approved.append(item)
    
    # 5. 聚合多源报道
    approved = aggregate_duplicates(approved)
    batch_fingerprint_db = dict(fingerprint_db)
    batch_deduped = []
    for item in approved:
        is_dup, dup_reason = is_duplicate(item, batch_fingerprint_db)
        if is_dup:
            rejected.append({
                "item": item,
                "reason": f"[批次去重] {dup_reason}",
                "action": "排除",
            })
            continue
        batch_fingerprint_db[generate_fingerprint(item)] = {
            "title": item.get("title", ""),
            "date": item.get("date", ""),
            "company": item.get("company", ""),
            "type": item.get("type", ""),
        }
        batch_deduped.append(item)
    approved = batch_deduped
    
    # 6. 按价值分数排序
    approved.sort(key=lambda x: x.get("value_score", 0), reverse=True)
    
    stats = {
        "total_input": len(raw_data),
        "approved": len(approved),
        "rejected": len(rejected),
        "timeliness_rejected": len([r for r in rejected if "时效性" in r["reason"]]),
        "duplicate_rejected": len([r for r in rejected if "去重" in r["reason"] or "政策库" in r["reason"]]),
        "schema_rejected": len([r for r in rejected if "[schema]" in r["reason"]]),
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


def validate_timeliness_in_report(report_path: str, now: Optional[datetime] = None) -> Dict[str, Any]:
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
                date_str = match[-1].strip() if len(match) > 3 else match[2].strip()
                title = match[0].strip()
                if title and title != "标题" and not title.startswith("-"):
                    all_dates.append((title, date_str))
    
    # 检查每个日期
    now = (now or now_local()).replace(tzinfo=None)
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
    ai_result = validate_ai_analysis(report_path)
    
    fix_instructions = []
    
    # 结构错误必须修复
    if not structure["is_valid"]:
        fix_instructions.extend(structure["errors"])
    
    # 时效性错误必须修复
    if timeliness["has_errors"]:
        fix_instructions.extend(timeliness["errors"])

    # AI分析错误必须修复
    if ai_result["has_errors"]:
        fix_instructions.extend(ai_result["errors"])
    
    # 警告建议修复
    if structure["warnings"]:
        fix_instructions.extend([f"[建议] {w}" for w in structure["warnings"]])
    if timeliness["warnings"]:
        fix_instructions.extend([f"[建议] {w}" for w in timeliness["warnings"]])
    if ai_result["warnings"]:
        fix_instructions.extend([f"[AI分析建议] {w}" for w in ai_result["warnings"]])
    
    # 计算综合分数
    score = 100
    score -= len(structure["errors"]) * 20
    score -= len(timeliness["errors"]) * 15
    score -= len(ai_result["errors"]) * 15
    score -= len(structure["warnings"]) * 5
    score -= len(timeliness["warnings"]) * 3
    score -= len(ai_result["warnings"]) * 3
    score = max(0, score)
    
    passed = len(structure["errors"]) == 0 and len(timeliness["errors"]) == 0 and not ai_result["has_errors"]
    can_send = passed and score >= 80
    
    return {
        "passed": passed,
        "can_send_email": can_send,
        "structure_check": structure,
        "timeliness_check": timeliness,
        "ai_check": ai_result,
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
    email_urls = extract_http_urls(email_body)
    
    # 提取approved数据中的所有URL
    approved_urls = collect_approved_urls(approved_data)
    approved_titles = []
    for item in approved_data:
        title = item.get("title", "")
        if title:
            approved_titles.append(title)
    
    # 检查邮件URL是否都在approved中
    url_check = validate_urls_against_approved(email_urls, approved_data, label="邮件正文")
    errors.extend(url_check["errors"])
    missing_urls = url_check["missing_urls"]
    
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
    expected_summary_count = min(5, len(approved_data))
    summary_items = re.findall(r'<span class="num">(\d+)</span>', email_body)
    if len(summary_items) < expected_summary_count:
        warnings.append(f"邮件正文执行摘要可能不完整: 找到{len(summary_items)}条，期望{expected_summary_count}条")
    
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


class HTMLURLExtractor(HTMLParser):
    """Extract HTTP(S) URL attributes from HTML using browser-like parsing."""

    def __init__(self) -> None:
        super().__init__()
        self.urls: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        for name, value in attrs:
            if not value or name.lower() not in HTML_URL_ATTRS:
                continue
            decoded = unescape(value)
            if decoded.lower().startswith(("http://", "https://")):
                self.urls.append(decoded)


def extract_http_urls(html: str) -> List[str]:
    """Extract unique HTTP(S) URL attribute values from HTML."""
    parser = HTMLURLExtractor()
    parser.feed(html)
    return list(dict.fromkeys(parser.urls))


def extract_plain_http_urls(text: str) -> List[str]:
    """Extract unique plain HTTP(S) URLs from Markdown or text."""
    urls = []
    for match in re.finditer(r"https?://[^\s<>\]\)\"']+", text or ""):
        urls.append(match.group(0).rstrip(".,;，。；）)]"))
    return list(dict.fromkeys(urls))


def collect_approved_urls(approved_data: List[Dict[str, Any]]) -> List[str]:
    """Collect unique primary and aggregated approved URLs."""
    approved_urls: list[str] = []
    for item in approved_data:
        url = item.get("url", "")
        if url:
            approved_urls.append(url)
        approved_urls.extend([u for u in _coerce_url_list(item.get("urls", [])) if u])
    return list(dict.fromkeys(approved_urls))


def validate_urls_against_approved(urls: List[str], approved_data: List[Dict[str, Any]], label: str = "HTML") -> Dict[str, Any]:
    """Ensure every extracted URL is present in approved data."""
    approved_urls = collect_approved_urls(approved_data)
    approved_canonical_urls = {canonicalize_url(u) for u in approved_urls}
    missing_urls = [u for u in urls if canonicalize_url(u) not in approved_canonical_urls]
    errors = []
    if missing_urls:
        errors.append(f"{label}包含{len(missing_urls)}个approved数据中不存在的URL: {missing_urls[:3]}")
    return {
        "is_consistent": len(errors) == 0,
        "errors": errors,
        "urls": urls,
        "approved_urls": approved_urls,
        "missing_urls": missing_urls,
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


def _looks_like_type(item: Dict[str, Any], item_type: str) -> bool:
    """Check whether item content matches its claimed type and synbio relevance."""
    title_summary_url = f"{item.get('title', '')} {item.get('summary', '')} {item.get('url', '')}".lower()
    text = f"{title_summary_url} {item.get('source', '')}".lower()
    
    # 1. 合成生物学主题相关性（核心判断）
    # 使用 LLM 语义判断（优先）或精确匹配（fallback）
    is_relevant, reason, confidence = _is_synbio_relevant(
        title=str(item.get("title", "")),
        summary=str(item.get("summary", "")),
        url=str(item.get("url", "")),
    )
    if not is_relevant:
        return False
    
    # 2. 如果 LLM 高置信度判断为合成生物学，且类型是 research 或 news，直接通过
    # 避免老关键词列表的过度过滤（如"改造地衣芽孢杆菌高效合成血清素"不含"研究"）
    if confidence in ("high", "llm", "cached") and item_type in ("news", "research"):
        return True
    
    # 3. 类型专用负向检查（避免错配）
    if any(keyword in title_summary_url for keyword in TYPE_NEGATIVE_KEYWORDS.get(item_type, ())):
        return False
    
    # 4. 类型专用正向检查（低置信度或 policy/funding/events 仍需关键词验证）
    if item_type == "policy":
        has_policy_keyword = any(keyword.lower() in title_summary_url for keyword in TYPE_TITLE_KEYWORDS["policy"])
        has_authority = any(hint.lower() in text for hint in POLICY_AUTHORITY_HINTS)
        netloc = urlsplit(str(item.get("url", ""))).netloc.lower()
        is_gov_cn = netloc.endswith(".gov.cn") or ".gov.cn:" in netloc
        if is_gov_cn and has_policy_keyword:
            return True
        return has_policy_keyword and has_authority
    
    if item_type in ("news", "research"):
        # news/research 在 LLM 判断通过后已直接返回，走到这里是低置信度情况
        return True
    
    keywords = TYPE_TITLE_KEYWORDS.get(item_type, ())
    return any(keyword.lower() in text for keyword in keywords)


def validate_approved_schema(approved_data: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Validate approved JSON before report/email generation or sending."""
    errors = []
    warnings = []
    seen_urls: dict[str, str] = {}
    total_checked = 0

    for index, item in enumerate(approved_data, 1):
        total_checked += 1
        if not isinstance(item, dict):
            errors.append(f"approved第{index}项不是对象")
            continue

        title = str(item.get("title", "") or "").strip()
        missing = sorted(
            field for field in APPROVED_REQUIRED_FIELDS
            if field not in item or item.get(field) in (None, "")
        )
        if missing:
            errors.append(f"approved第{index}项缺少必填字段: {', '.join(missing)}")

        item_type = str(item.get("type") or "").lower()
        if item_type not in VALID_ITEM_TYPES:
            errors.append(f"approved第{index}项type无效: {item.get('type')}")
        elif not _looks_like_type(item, item_type):
            errors.append(f"approved第{index}项疑似类别错配: {title} ({item_type})")

        if not parse_date(str(item.get("date", "") or "")):
            errors.append(f"approved第{index}项日期无法解析: {item.get('date')}")

        for score_field in ("raw_score", "value_score"):
            try:
                score = float(item.get(score_field))
            except (TypeError, ValueError):
                errors.append(f"approved第{index}项{score_field}不是数字: {item.get(score_field)}")
                continue
            if score_field == "value_score" and not 0 <= score <= 10:
                errors.append(f"approved第{index}项value_score超出0-10: {score}")
            if score_field == "raw_score" and score < 0:
                errors.append(f"approved第{index}项raw_score不能为负: {score}")

        urls = _item_candidate_urls(item)
        for url in [u for u in dict.fromkeys(urls) if u]:
            try:
                safe_url(str(url))
            except ValueError as exc:
                errors.append(f"approved第{index}项URL不安全: {url} ({exc})")
                continue
            if _is_category_or_aggregate_url(str(url)):
                errors.append(f"approved第{index}项URL疑似聚合页/黑名单域名: {url}")
            canonical = canonicalize_url(str(url))
            if canonical in seen_urls and seen_urls[canonical] != title:
                errors.append(
                    f"approved URL重复但标题不同: {url} -> '{seen_urls[canonical]}' / '{title}'"
                )
            else:
                seen_urls[canonical] = title

    return {
        "is_valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "total_checked": total_checked,
    }


def validate_approved_timeliness(approved_data: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Validate approved items against their type-specific business windows."""
    errors = []
    warnings = []
    total_checked = 0

    for item in approved_data:
        item_type = item.get("type") or "news"
        ok, reason = check_timeliness(item, item_type)
        total_checked += 1
        if not ok:
            title = item.get("title", "未命名信息")
            errors.append(f"approved信息时效性不合规: {title} ({item_type}) - {reason}")

    return {
        "has_errors": len(errors) > 0,
        "errors": errors,
        "warnings": warnings,
        "total_checked": total_checked,
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
    approved_schema = validate_approved_schema(approved_data)
    approved_timeliness = validate_approved_timeliness(approved_data)
    ai_result = report_result.get("ai_check", {"has_errors": False, "errors": [], "warnings": []})
    
    fix_instructions = list(report_result.get("fix_instructions", []))
    
    # 邮件一致性错误必须修复
    if not email_result["is_consistent"]:
        fix_instructions.extend(email_result["errors"])

    if not approved_schema["is_valid"]:
        fix_instructions.extend(approved_schema["errors"])

    if approved_timeliness["has_errors"]:
        fix_instructions.extend(approved_timeliness["errors"])
    
    # 邮件一致性警告建议修复
    if email_result["warnings"]:
        fix_instructions.extend([f"[邮件一致性建议] {w}" for w in email_result["warnings"]])
    if approved_schema["warnings"]:
        fix_instructions.extend([f"[approved schema建议] {w}" for w in approved_schema["warnings"]])
    if approved_timeliness["warnings"]:
        fix_instructions.extend([f"[approved时效性建议] {w}" for w in approved_timeliness["warnings"]])
    
    # 计算综合分数
    score = report_result["overall_score"]
    if not email_result["is_consistent"]:
        score -= len(email_result["errors"]) * 15
    if email_result["warnings"]:
        score -= len(email_result["warnings"]) * 3
    if not approved_schema["is_valid"]:
        score -= len(approved_schema["errors"]) * 15
    if approved_schema["warnings"]:
        score -= len(approved_schema["warnings"]) * 3
    if approved_timeliness["has_errors"]:
        score -= len(approved_timeliness["errors"]) * 15
    if approved_timeliness["warnings"]:
        score -= len(approved_timeliness["warnings"]) * 3
    score = max(0, score)
    
    report_passed = report_result["passed"]
    email_consistent = email_result["is_consistent"]
    ai_passed = not ai_result["has_errors"]
    approved_schema_ok = approved_schema["is_valid"]
    approved_timely = not approved_timeliness["has_errors"]
    can_send = report_passed and email_consistent and ai_passed and approved_schema_ok and approved_timely and score >= 80
    
    return {
        "report_passed": report_passed,
        "email_consistent": email_consistent,
        "ai_passed": ai_passed,
        "approved_schema_ok": approved_schema_ok,
        "approved_timely": approved_timely,
        "can_send_email": can_send,
        "overall_score": score,
        "fix_instructions": fix_instructions,
        "report_check": report_result,
        "email_check": email_result,
        "ai_check": ai_result,
        "approved_schema_check": approved_schema,
        "approved_timeliness_check": approved_timeliness,
    }


def save_rejection_log(rejected: List[Dict[str, Any]], report_date: str):
    """保存被拒绝的信息日志"""
    log_file = DATA_DIR / f"rejected_{report_date}.json"
    
    with open(log_file, 'w', encoding='utf-8') as f:
        json.dump(rejected, f, ensure_ascii=False, indent=2)


def validate_search_log(
    search_log: Any,
    raw_obj: Any | None = None,
    strict_coverage: bool = False,
) -> Dict[str, Any]:
    """Validate evidence that all five search rounds were executed."""
    errors: list[str] = []
    warnings: list[str] = []

    if not isinstance(search_log, dict):
        return {
            "is_valid": False,
            "errors": ["search_log必须是对象"],
            "warnings": warnings,
            "rounds_seen": [],
            "total_queries": 0,
            "required_query_check": None,
        }

    rounds = search_log.get("rounds")
    if not isinstance(rounds, list):
        return {
            "is_valid": False,
            "errors": ["search_log缺少rounds列表"],
            "warnings": warnings,
            "rounds_seen": [],
            "total_queries": 0,
            "required_query_check": None,
        }

    rounds_seen: set[str] = set()
    total_queries = 0
    for index, round_entry in enumerate(rounds, 1):
        if not isinstance(round_entry, dict):
            errors.append(f"search_log第{index}轮不是对象")
            continue
        round_id = str(round_entry.get("round") or round_entry.get("id") or "").strip()
        if round_id:
            rounds_seen.add(round_id)
        queries = round_entry.get("queries", [])
        if isinstance(queries, list):
            query_count = len([q for q in queries if q])
            if not query_count:
                query_count = len(_round_source_queries(round_entry))
            total_queries += query_count
        else:
            errors.append(f"search_log第{index}轮queries不是列表")
        if not round_id:
            errors.append(f"search_log第{index}轮缺少round/id")
        if not queries and not _round_source_queries(round_entry):
            errors.append(f"search_log第{index}轮缺少queries")

    missing_rounds = sorted(REQUIRED_SEARCH_ROUNDS - rounds_seen)
    if missing_rounds:
        errors.append(f"search_log缺少必要搜索轮次: {', '.join(missing_rounds)}")

    required_query_check = validate_required_search_queries(search_log)
    if required_query_check["errors"]:
        if strict_coverage:
            errors.extend(required_query_check["errors"])
        else:
            warnings.extend(required_query_check["errors"])

    coverage_check = None
    if raw_obj is not None:
        raw_rounds = set()
        missing_source_round = 0
        if isinstance(raw_obj, dict):
            for item_type in sorted(VALID_ITEM_TYPES):
                items = raw_obj.get(item_type, [])
                if not isinstance(items, list):
                    continue
                for item in items:
                    if isinstance(item, dict) and item.get("source_round"):
                        raw_rounds.add(str(item.get("source_round")))
                    elif isinstance(item, dict):
                        missing_source_round += 1
        elif isinstance(raw_obj, list):
            for item in raw_obj:
                if isinstance(item, dict) and item.get("source_round"):
                    raw_rounds.add(str(item.get("source_round")))
                elif isinstance(item, dict):
                    missing_source_round += 1
        if missing_source_round:
            errors.append(f"raw数据有{missing_source_round}条缺少source_round，无法追溯搜索轮次")
        total_raw_items = count_raw_items(raw_obj)
        if not raw_rounds and total_raw_items > 0:
            errors.append("raw数据缺少source_round，无法追溯搜索轮次")
        elif not raw_rounds <= rounds_seen:
            errors.append(f"raw数据包含search_log未记录的source_round: {sorted(raw_rounds - rounds_seen)}")
        unused_rounds = sorted(rounds_seen - raw_rounds)
        if unused_rounds:
            warnings.append(f"以下搜索轮次执行过但未产生raw候选: {', '.join(unused_rounds)}")
        coverage_check = validate_search_coverage(search_log, raw_obj)
        if coverage_check["search_candidate_count"] and not coverage_check["is_valid"]:
            message = (
                f"搜索覆盖率不足: search_log候选{coverage_check['search_candidate_count']}条, "
                f"raw收录{coverage_check['raw_url_count']}条, "
                f"缺失{len(coverage_check['missing_urls'])}条"
            )
            if strict_coverage:
                errors.append(message)
            else:
                warnings.append(message)

    return {
        "is_valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "rounds_seen": sorted(rounds_seen),
        "total_queries": total_queries,
        "required_query_check": required_query_check,
        "coverage_check": coverage_check,
    }


def build_approved_from_raw(
    raw_obj: Any,
    report_date: str,
    output_dir: Path | None = None,
    check_url_health_enabled: bool = True,
    check_title_match_enabled: bool = True,
    url_check_func=check_url_health,
    title_check_func=check_url_title_match,
    llm_relevance_mode: str = "auto",
    llm_judge_func=judge_item_relevance,
    search_log: Any | None = None,
) -> Dict[str, Any]:
    """Process every category from a full raw dict and persist approved/rejected outputs."""
    if not isinstance(raw_obj, dict):
        raise ValueError("--build-approved requires a full raw category dict")

    search_log_check = None
    if search_log is not None:
        # search_log coverage is always enforced; it cannot be bypassed.
        search_log_check = validate_search_log(search_log, raw_obj, strict_coverage=True)
        if not search_log_check["is_valid"]:
            raise ValueError("search_log校验失败: " + "; ".join(search_log_check["errors"]))

    output_dir = output_dir or DATA_DIR
    output_dir.mkdir(parents=True, exist_ok=True)
    all_approved: list[dict[str, Any]] = []
    all_rejected: list[dict[str, Any]] = []
    processed: dict[str, Any] = {}

    for item_type in sorted(VALID_ITEM_TYPES):
        raw_items = normalize_raw_input(raw_obj, item_type)
        result = process_raw_data(raw_items, item_type)
        processed[item_type] = result
        all_approved.extend(result.get("approved", []))
        for rejected in result.get("rejected", []):
            rejected = dict(rejected)
            rejected["category"] = item_type
            all_rejected.append(rejected)
        with open(output_dir / f"processed_{item_type}_{report_date}.json", "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

    all_approved, conflict_rejected = remove_conflicting_url_items(all_approved)
    all_rejected.extend(conflict_rejected)
    if check_url_health_enabled:
        all_approved, health_rejected = remove_unhealthy_url_items(all_approved, url_check_func=url_check_func)
        all_rejected.extend(health_rejected)
    title_match_warnings: list[str] = []
    if check_title_match_enabled:
        all_approved, title_rejected, title_match_warnings = remove_title_mismatch_items(
            all_approved,
            title_check_func=title_check_func,
        )
        all_rejected.extend(title_rejected)
    llm_relevance_warnings: list[str] = []
    if llm_relevance_mode != "off":
        all_approved, llm_rejected, llm_relevance_warnings = remove_llm_rejected_items(
            all_approved,
            mode=llm_relevance_mode,
            judge_func=llm_judge_func,
        )
        all_rejected.extend(llm_rejected)
    all_approved = sort_approved_items(all_approved)
    approved_check = validate_approved_schema(all_approved)
    approved_path = output_dir / f"approved_{report_date}.json"
    rejected_path = output_dir / f"rejected_{report_date}.json"
    with open(approved_path, "w", encoding="utf-8") as f:
        json.dump(all_approved, f, ensure_ascii=False, indent=2)
    with open(rejected_path, "w", encoding="utf-8") as f:
        json.dump(all_rejected, f, ensure_ascii=False, indent=2)

    stats = {
        item_type: processed[item_type]["stats"]
        for item_type in sorted(processed)
    }
    return {
        "approved_path": str(approved_path),
        "rejected_path": str(rejected_path),
        "approved": all_approved,
        "rejected": all_rejected,
        "stats": stats,
        "approved_schema": approved_check,
        "search_log_check": search_log_check,
        "title_match_warnings": title_match_warnings,
        "llm_relevance_warnings": llm_relevance_warnings,
    }


def sort_approved_items(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Sort final approved items by date and value for stable report generation."""
    return sorted(
        items,
        key=lambda item: (
            parse_date(str(item.get("date", "") or "")) or datetime.min,
            float(item.get("value_score") or 0),
        ),
        reverse=True,
    )


def remove_conflicting_url_items(items: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Drop lower-ranked items when the same URL is attached to different titles."""
    kept: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    seen: dict[str, str] = {}

    for item in sort_approved_items(items):
        title = str(item.get("title", "") or "")
        urls = _item_candidate_urls(item)
        canonical_urls = [canonicalize_url(str(url)) for url in urls if url]
        conflicts = [
            url for url in canonical_urls
            if url in seen and normalize_title(seen[url]) != normalize_title(title)
        ]
        if conflicts:
            rejected.append({
                "item": item,
                "reason": f"[approved冲突] URL已用于不同标题: {conflicts[:3]}",
                "action": "排除",
            })
            continue
        for url in canonical_urls:
            seen[url] = title
        kept.append(item)

    return kept, rejected


def remove_unhealthy_url_items(
    items: List[Dict[str, Any]],
    url_check_func=check_url_health,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Drop items whose primary outbound URL cannot pass the link health gate."""
    kept: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []

    for item in items:
        primary_url = str(item.get("url") or "")
        result = url_check_func(primary_url)
        if not result.get("ok"):
            rejected.append({
                "item": item,
                "reason": f"[链接健康] 主链接不可用: {primary_url} - {result.get('reason', '未知错误')}",
                "action": "排除",
            })
            continue

        healthy_urls = []
        for url in _coerce_url_list(item.get("urls", [])):
            url = str(url or "")
            if not url:
                continue
            if canonicalize_url(url) == canonicalize_url(primary_url):
                healthy_urls.append(url)
                continue
            extra_result = url_check_func(url)
            if extra_result.get("ok"):
                healthy_urls.append(url)
            else:
                rejected.append({
                    "item": item,
                    "reason": f"[链接健康] 备用链接不可用并已移除: {url} - {extra_result.get('reason', '未知错误')}",
                    "action": "移除备用链接",
                })
        if healthy_urls:
            item["urls"] = list(dict.fromkeys(healthy_urls))
        kept.append(item)

    return kept, rejected


def remove_llm_rejected_items(
    items: List[Dict[str, Any]],
    mode: str = "auto",
    judge_func=judge_item_relevance,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[str]]:
    """Run the LLM/semantic relevance gate over approved candidates."""
    kept: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    warnings: list[str] = []

    for item in items:
        decision = judge_func(item, mode=mode)
        if not isinstance(decision, Decision):
            warnings.append(f"LLM领域审计返回非标准结果，已保守拒绝: {item.get('title', '')}")
            rejected.append({
                "item": item,
                "reason": "[LLM领域审计] 非标准审计结果",
                "action": "排除",
            })
            continue

        annotated = dict(item)
        annotated["llm_relevance"] = {
            "is_approved": decision.is_approved,
            "domain_relevance": decision.domain_relevance,
            "confidence": decision.confidence,
            "reason": decision.reason,
            "evidence_spans": decision.evidence_spans,
            "section": decision.section,
            "provider": decision.provider,
        }
        annotated["domain_relevance"] = decision.domain_relevance
        annotated["confidence"] = decision.confidence

        if decision.provider == "heuristic-fallback":
            warnings.append(f"LLM领域审计失败，已对候选使用本地fallback: {item.get('title', '')}")

        if decision.is_approved:
            kept.append(annotated)
            continue

        rejected.append({
            "item": annotated,
            "reason": f"[LLM领域审计] {decision.reject_message()}",
            "action": "排除",
        })

    return kept, rejected, warnings


def markdown_cell(value: object) -> str:
    return str(value or "").replace("|", "\\|").replace("\n", " ").strip()


def markdown_link(url: str) -> str:
    safe_url(str(url or ""))
    return str(url)


def group_approved_by_type(items: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    grouped = {item_type: [] for item_type in sorted(VALID_ITEM_TYPES)}
    for item in sort_approved_items(items):
        item_type = str(item.get("type") or "news").lower()
        grouped.setdefault(item_type, []).append(item)
    return grouped


def render_markdown_report(
    approved_data: List[Dict[str, Any]],
    report_date: str,
    raw_count: int | None = None,
) -> str:
    """Render a deterministic Markdown report using only approved data."""
    approved = sort_approved_items(approved_data)
    grouped = group_approved_by_type(approved)
    raw_total = len(approved) if raw_count is None else raw_count

    lines = [
        f"# 合成生物行业日报 — {report_date}",
        "",
        f"> 报告生成时间：{now_local().strftime('%Y-%m-%d %H:%M:%S')}  ",
        "> 信息来源：公开网络检索  ",
        "> 覆盖维度：新闻动态、研究成果、融资投资、政策监管、行业活动",
        f"> **流水线追踪**：原始数据={raw_total}条 → 脚本处理 → approved={len(approved)}条 → 验证=待发送门禁",
        "",
        "---",
        "",
        "## 📌 执行摘要",
        "",
    ]

    summary_items = approved[:5]
    if summary_items:
        for index, item in enumerate(summary_items, 1):
            lines.append(
                f"{index}. **{markdown_cell(item.get('title', '未命名信息'))}**："
                f"{markdown_cell(item.get('summary', ''))}（{markdown_cell(item.get('date', report_date))}）"
            )
    else:
        lines.append(f"1. 经五轮检索，本周期暂无可发送信息收录。（{report_date}）")

    lines.extend([
        "",
        "---",
        "",
        "## 📰 行业热点新闻",
        "",
        "| 标题 | 来源 | 时间 | 摘要 | 链接 |",
        "|------|------|------|------|------|",
    ])
    append_item_rows(lines, grouped.get("news", []), ["title", "source", "date", "summary", "url"])

    lines.extend([
        "",
        "---",
        "",
        "## 🔬 最新研究成果",
        "",
        "| 标题 | 期刊/机构 | 核心发现 | 链接 |",
        "|------|----------|----------|------|",
    ])
    append_item_rows(lines, grouped.get("research", []), ["title", "source", "summary", "url"])

    lines.extend([
        "",
        "---",
        "",
        "## 💰 融资与投资动态",
        "",
        "| 公司 | 轮次 | 金额 | 投资方 | 时间 | 链接 |",
        "|------|------|------|--------|------|------|",
    ])
    append_funding_rows(lines, grouped.get("funding", []))

    lines.extend([
        "",
        "---",
        "",
        "## 🏛️ 政策与监管",
        "",
        "### 国内政策",
        "",
        "| 政策/法规 | 发布机构 | 时间 | 核心内容 | 链接 |",
        "|-----------|----------|------|----------|------|",
    ])
    append_item_rows(lines, grouped.get("policy", []), ["title", "source", "date", "summary", "url"])
    lines.extend([
        "",
        "### 国际监管动态",
        "",
        "经五轮检索，本周期暂无相关新信息收录。",
        "",
        "---",
        "",
        "## 📅 行业活动预告",
        "",
        "| 活动名称 | 时间 | 地点 | 亮点 | 链接 |",
        "|----------|------|------|------|------|",
    ])
    append_event_rows(lines, grouped.get("events", []))

    lines.extend([
        "",
        "---",
        "",
        "## 🤖 AI 深度分析",
        "",
        "### 趋势研判",
        "",
    ])
    if approved:
        title_list = "；".join(
            f"{markdown_cell(item.get('title', ''))}（{markdown_cell(item.get('date', report_date))}）"
            for item in approved[:5]
        )
        lines.append(f"本周期可发送信息主要包括：{title_list}。这些信息已通过时效性、分类一致性和去重门禁。")
    else:
        lines.append("本周期没有可发送信息，建议继续监控公开来源。")
    lines.extend([
        "",
        "### 竞争格局变化",
        "",
        "本周期仅基于正文已收录信息进行归纳，不引入外部实体。",
        "",
        "### 风险提示",
        "",
        "1. 链接可访问性、信息时效性和来源一致性仍需在发送门禁中持续验证。",
        "",
        "---",
        "",
        "## 📎 附录：完整链接列表",
        "",
    ])
    if approved:
        for index, item in enumerate(approved, 1):
            lines.append(f"{index}. {markdown_link(str(item.get('url', '')))}")
    else:
        lines.append("1. 经五轮检索，本周期暂无可列示的外部链接。")
    lines.extend([
        "",
        "---",
        "",
        "> 免责声明：本报告信息来源于公开网络检索，仅供参考，不构成投资建议。",
        "",
    ])
    return "\n".join(lines)


def append_item_rows(lines: List[str], items: List[Dict[str, Any]], fields: List[str]) -> None:
    if not items:
        lines.append("| 经五轮检索，本周期暂无相关新信息收录。 | — | — | — | — |" if len(fields) == 5 else "| 经五轮检索，本周期暂无相关新信息收录。 | — | — | — |")
        return
    for item in items:
        cells = []
        for field in fields:
            if field == "url":
                cells.append(markdown_link(str(item.get("url", ""))))
            else:
                cells.append(markdown_cell(item.get(field, "")))
        lines.append("| " + " | ".join(cells) + " |")


def append_funding_rows(lines: List[str], items: List[Dict[str, Any]]) -> None:
    if not items:
        lines.append("| 经五轮检索，本周期暂无相关新信息收录。 | — | — | — | — | — |")
        return
    for item in items:
        cells = [
            markdown_cell(item.get("company") or item.get("title", "")),
            markdown_cell(item.get("round") or "—"),
            markdown_cell(item.get("amount") or "未披露"),
            markdown_cell(item.get("investor") or "—"),
            markdown_cell(item.get("date", "")),
            markdown_link(str(item.get("url", ""))),
        ]
        lines.append("| " + " | ".join(cells) + " |")


def append_event_rows(lines: List[str], items: List[Dict[str, Any]]) -> None:
    if not items:
        lines.append("| 经五轮检索，本周期暂无相关新信息收录。 | — | — | — | — |")
        return
    for item in items:
        cells = [
            markdown_cell(item.get("title", "")),
            markdown_cell(item.get("date", "")),
            markdown_cell(item.get("location", "")),
            markdown_cell(item.get("summary", "")),
            markdown_link(str(item.get("url", ""))),
        ]
        lines.append("| " + " | ".join(cells) + " |")


# ==================== CLI 入口 ====================

def main():
    """命令行入口，用于测试"""
    import argparse
    import sys
    
    parser = argparse.ArgumentParser(description="AS hub NEWs agent - Report Pipeline")
    parser.add_argument("--validate", type=str, help="验证报告文件路径")
    parser.add_argument("--full-validate", type=str, help="运行报告+邮件+AI完整验证的Markdown报告路径")
    parser.add_argument("--email", type=str, help="完整验证使用的邮件HTML路径")
    parser.add_argument("--approved", type=str, help="完整验证使用的approved JSON路径")
    parser.add_argument("--process", type=str, help="处理原始数据JSON文件")
    parser.add_argument("--build-raw-from-search", type=str, help="从结构化search_log自动生成raw JSON")
    parser.add_argument("--build-approved", type=str, help="从完整raw dict一次性生成processed/approved/rejected")
    parser.add_argument("--check-url-health", action="store_true", help="兼容旧命令；build-approved默认已开启链接健康检查")
    parser.add_argument("--skip-url-health", action="store_true", help="仅离线测试/受限网络临时使用：跳过build-approved链接健康检查")
    parser.add_argument("--check-title-match", action="store_true", help="兼容旧命令；build-approved默认已开启标题-URL匹配")
    parser.add_argument("--skip-title-match", action="store_true", help="仅离线测试/受限网络临时使用：跳过build-approved标题-URL匹配")
    parser.add_argument("--llm-relevance-mode", choices=["auto", "llm", "heuristic", "off"], default="auto", help="领域相关性审计模式：auto默认有LLM配置则调用，否则本地语义fallback")
    parser.add_argument("--search-log", type=str, help="搜索执行日志JSON路径，用于校验五轮搜索证据")
    parser.add_argument("--strict-search-coverage", action="store_true", help="兼容旧命令；build-approved默认已严格校验必搜query和候选URL覆盖")
    parser.add_argument("--render-md", type=str, help="从approved JSON生成确定性Markdown报告")
    parser.add_argument("--raw", type=str, help="render-md使用的raw JSON路径，用于准确显示原始数据总数")
    parser.add_argument("--date", type=str, help="--build-approved 输出使用的日期 YYYY-MM-DD")
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
                print(f"  {i}. {instr}")
        sys.exit(0 if result["passed"] else 1)

    elif args.full_validate:
        if not args.email or not args.approved:
            parser.error("--full-validate requires --email and --approved")
        with open(args.email, 'r', encoding='utf-8') as f:
            email_body = f.read()
        with open(args.approved, 'r', encoding='utf-8') as f:
            approved_data = json.load(f)
        result = run_full_validation(args.full_validate, email_body, approved_data)
        output_path = args.output or (args.full_validate.replace('.md', '_full_validation.json'))
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        can_send = "YES" if result["can_send_email"] else "NO"
        print(f"Full validation result saved to: {output_path}")
        print(f"Can send email: {can_send}, Score: {result['overall_score']}")
        if result["fix_instructions"]:
            print(f"Fix instructions ({len(result['fix_instructions'])} items):")
            for i, instr in enumerate(result["fix_instructions"][:10], 1):
                print(f"  {i}. {instr}")
        sys.exit(0 if result["can_send_email"] else 1)
    
    elif args.render_md:
        if not args.date:
            parser.error("--render-md requires --date")
        if not args.output:
            parser.error("--render-md requires --output")
        with open(args.render_md, 'r', encoding='utf-8') as f:
            approved_data = json.load(f)
        raw_count = None
        raw_path = Path(args.raw) if args.raw else DATA_DIR / f"raw_{args.date}.json"
        if args.raw and not raw_path.exists():
            parser.error(f"--raw file does not exist: {raw_path}")
        if raw_path.exists():
            with open(raw_path, 'r', encoding='utf-8') as f:
                raw_count = count_raw_items(json.load(f))
        markdown = render_markdown_report(approved_data, args.date, raw_count=raw_count)
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(markdown, encoding="utf-8")
        print(f"Markdown报告已生成: {output_path}")
        sys.exit(0)

    elif args.build_raw_from_search:
        if not args.date:
            parser.error("--build-raw-from-search requires --date")
        if not args.output:
            parser.error("--build-raw-from-search requires --output")
        with open(args.build_raw_from_search, 'r', encoding='utf-8') as f:
            search_log = json.load(f)
        raw_obj = build_raw_from_search_log(search_log, report_date=args.date)
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(raw_obj, ensure_ascii=False, indent=2), encoding="utf-8")
        meta = raw_obj.get("_meta", {})
        print(
            f"raw已生成: {output_path} "
            f"(结构化搜索结果{meta.get('structured_results', 0)}条, raw{meta.get('raw_items', 0)}条, 跳过{meta.get('skipped_results', 0)}条)"
        )
        sys.exit(0)

    elif args.build_approved:
        if not args.date:
            parser.error("--build-approved requires --date")
        with open(args.build_approved, 'r', encoding='utf-8') as f:
            raw_obj = json.load(f)
        search_log = None
        if args.search_log:
            with open(args.search_log, 'r', encoding='utf-8') as f:
                search_log = json.load(f)
        output_dir = Path(args.output) if args.output else DATA_DIR
        result = build_approved_from_raw(
            raw_obj,
            args.date,
            output_dir=output_dir,
            check_url_health_enabled=not args.skip_url_health,
            check_title_match_enabled=not args.skip_title_match,
            llm_relevance_mode=args.llm_relevance_mode,
            search_log=search_log,
        )
        print(f"approved已生成: {result['approved_path']} ({len(result['approved'])}条)")
        print(f"rejected已生成: {result['rejected_path']} ({len(result['rejected'])}条)")
        if result.get("search_log_check"):
            print(
                "search_log校验通过: "
                f"{len(result['search_log_check']['rounds_seen'])}轮, "
                f"{result['search_log_check']['total_queries']}个query"
            )
            coverage_check = result["search_log_check"].get("coverage_check")
            if coverage_check:
                print(
                    "搜索覆盖率: "
                    f"{coverage_check['raw_url_count']}/{coverage_check['search_candidate_count']} "
                    f"({coverage_check['coverage_ratio']:.0%})"
                )
        if result.get("title_match_warnings"):
            print(f"标题匹配警告: {len(result['title_match_warnings'])}个")
            for warning in result["title_match_warnings"][:10]:
                print(f"  - {warning}")
        if result.get("llm_relevance_warnings"):
            print(f"LLM领域审计警告: {len(result['llm_relevance_warnings'])}个")
            for warning in result["llm_relevance_warnings"][:10]:
                print(f"  - {warning}")
        if not result["approved_schema"]["is_valid"]:
            print(f"approved schema错误: {len(result['approved_schema']['errors'])}个")
            for error in result["approved_schema"]["errors"][:10]:
                print(f"  - {error}")
        sys.exit(0 if result["approved_schema"]["is_valid"] else 1)

    elif args.process:
        with open(args.process, 'r', encoding='utf-8') as f:
            raw_obj = json.load(f)
        
        raw_data = normalize_raw_input(raw_obj, args.type)
        result = process_raw_data(raw_data, args.type)
        
        if args.output:
            with open(args.output, 'w', encoding='utf-8') as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
        
        print(f"处理完成: 输入{result['stats']['total_input']}条, 通过{result['stats']['approved']}条, 拒绝{result['stats']['rejected']}条")
    
    else:
        # 默认：显示历史事件库统计
        fp_db = load_historical_events(days=HISTORY_DEDUP_DAYS)
        print(f"历史事件指纹库: {len(fp_db)}条记录")
        
        policy_db = load_policy_database()
        print(f"政策库: {len(policy_db)}条记录")


if __name__ == "__main__":
    main()
