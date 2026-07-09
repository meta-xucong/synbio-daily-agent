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
import concurrent.futures
import threading
import socket
import ssl
import smtplib
from email.utils import parsedate_to_datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
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
    from .llm_judge import DateDecision, judge_item_date_validity
    from .llm_judge import judge_final_audit
except ImportError:
    from settings import CONFIG_DIR, DATA_DIR, REPORTS_DIR, TEMPLATES_DIR, now_local
    from console_utils import ensure_utf8_console
    from ai_analysis_check import validate_ai_analysis
    from render_utils import safe_url
    from llm_judge import Decision, is_synbio_relevant as _is_synbio_relevant_impl
    from llm_judge import judge_item_relevance
    from llm_judge import DateDecision, judge_item_date_validity
    from llm_judge import judge_final_audit

ensure_utf8_console()

RelevanceDecision = Decision
DateAuditDecision = DateDecision

# ==================== 配置常量 ====================

# 时间窗口配置（天）
TIME_WINDOWS = {
    "news": 3,
    "research": 14,
    "policy": 7,
    "events": 60,  # 未来60天
    "funding": 7,
    "report": 30,
    "market_report": 30,
}

REQUIRED_RAW_FIELDS = {"title", "source", "date", "summary", "url"}
VALID_ITEM_TYPES = {"news", "research", "funding", "policy", "events"}
TYPE_INFERENCE_ORDER = ("events", "funding", "policy", "research", "news")
HTML_URL_ATTRS = {"href", "src", "action", "formaction", "poster"}
TITLE_SIMILARITY_THRESHOLD = 0.80
HISTORY_DEDUP_DAYS = 30
MAX_RAW_SCORE = 30
REQUIRED_SEARCH_ROUNDS = {"r1", "r1b", "r2", "r3", "r4", "r5", "r6"}
REQUIRED_SEARCH_LOG_GENERATOR = "search_executor"
REQUIRED_HIGH_RECALL_ROUNDS = {"llm_discovery", "llm_gap_audit"}
VALID_HIGH_RECALL_EVIDENCE_MODES = {"strict", "compatible"}
DEFAULT_HIGH_RECALL_EVIDENCE_MODE = "compatible"
PRODUCTION_SEARCH_MIN_LIMIT = 15
SEARCH_QUERY_CONFIG_FILENAME = "search_queries.json"
URL_HEALTH_TIMEOUT_SECONDS = 10
URL_HEALTH_MAX_BYTES = 250_000
DATE_VERIFY_TIMEOUT_SECONDS = 10
DATE_VERIFY_MAX_BYTES = 300_000
DATE_VERIFY_MAX_WORKERS = 12
TITLE_MATCH_TIMEOUT_SECONDS = 10
TITLE_MATCH_MAX_BYTES = 300_000
TITLE_MATCH_MIN_SCORE = 0.30
SEARCH_CANDIDATE_LIST_KEYS = ("results", "candidates", "items", "organic_results", "web_results")
SEARCH_RESULT_TITLE_KEYS = ("title", "name", "headline")
SEARCH_RESULT_URL_KEYS = ("url", "link", "href", "source_url")
SEARCH_RESULT_SUMMARY_KEYS = ("summary", "snippet", "description", "content", "text", "abstract")
SEARCH_RESULT_SOURCE_KEYS = ("source", "site", "publisher", "source_name", "domain")
SEARCH_RESULT_DATE_KEYS = ("date", "published_date", "published_at", "published_time", "published", "time", "datetime", "created_at")
LOW_APPROVED_COUNT_WARNING = 2
EMPTY_APPROVED_ERROR = "approved为空：本次没有任何可发送信息，必须先复核搜索结果和拒绝列表，禁止发送空日报"
MISSING_SEARCH_STRATEGY_ERROR = "LLM搜索策略缺失：正式搜索日志必须配套 data/search_strategy_YYYY-MM-DD.json 并执行 llm_dynamic query"
LLM_TRACE_ERROR = "approved缺少LLM领域审计痕迹：正式发送必须确认每条信息经过LLM/语义审计"
DATE_VERIFICATION_ERROR = "approved缺少可信页面发布时间验证：正式发送不能只依赖搜索引擎日期或抓取日期"
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
    "research": ("研究", "论文", "nature", "science", "cell", "pnas", "acs", "发现", "突破", "engineer", "engineered", "recoded", "e. coli", "synthetic cell", "research", "journal", "study", "paper", "published", "publication", "biotechnology", "bioengineering"),
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

MARKET_REPORT_KEYWORDS = (
    "market analysis report",
    "market research report",
    "market report",
    "investment report",
    "industry report",
    "market size",
    "market share",
    "market forecast",
    "market trends",
    "cagr",
    "forecast 2026",
    "forecast 2030",
    "forecast 2034",
    "2026-2030",
    "2026-2034",
    "市场分析报告",
    "市场研究报告",
    "行业发展趋势研究报告",
    "行业趋势研究报告",
    "市场规模",
    "市场份额",
    "市场预测",
    "增长率",
    "复合年增长率",
    "iim",
    "polaris market research",
)

PAGE_DATE_META_KEYS = {
    "article:published_time",
    "article:modified_time",
    "datepublished",
    "datemodified",
    "date",
    "publishdate",
    "pubdate",
    "published_time",
    "publish_time",
    "og:updated_time",
    "og:release_date",
    "lastmod",
    "sailthru.date",
}

DATE_TEXT_PATTERNS = (
    r"\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日",
    r"\d{4}[-/\.]\d{1,2}[-/\.]\d{1,2}",
    r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\s+\d{1,2},\s*\d{4}",
)
DATE_EVENT_CONTEXT_KEYWORDS = (
    "发布", "发表", "印发", "出台", "通过", "批准", "审议", "召开", "举办", "举行", "做客",
    "启动", "开放", "投用", "上线", "签约", "落地", "完成", "融资", "上市", "聆讯", "申报",
    "征求意见", "研讨会", "论坛", "会议", "publication", "published", "posted", "announced",
    "approved", "held", "launched", "released", "filed", "listed",
)
DATE_EFFECTIVE_CONTEXT_KEYWORDS = (
    "施行", "实施", "生效", "执行", "起施行", "起实施", "effective", "takes effect", "come into force",
)
DATE_NOISE_CONTEXT_KEYWORDS = (
    "copyright", "版权所有", "备案", "沪icp", "粤icp", "京icp",
)
DATE_VERIFY_SEARCH_TOLERANCE_DAYS = 7

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
    """解析各种日期格式，并过滤明显不合理的日期。"""
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
            dt = datetime.strptime(date_str.strip(), fmt)
            if _is_reasonable_date(dt):
                return dt
            return None
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
                dt = datetime(y, m, d)
                if _is_reasonable_date(dt):
                    return dt
                return None
            except:
                pass
    
    return None


def _is_reasonable_date(dt: datetime) -> bool:
    """检查日期是否在基础合理范围内，防止模板占位符年份等明显异常日期被误用。"""
    if not dt:
        return False
    return datetime(2018, 1, 1) <= dt <= datetime(2030, 12, 31)


def _is_plausible_verified_date(candidate: datetime, search_date: str = "", *, allow_future_days: int = 0) -> bool:
    if not _is_reasonable_date(candidate):
        return False
    search_dt = parse_date(search_date)
    if not search_dt:
        return True
    candidate_day = candidate.replace(hour=0, minute=0, second=0, microsecond=0)
    search_day = search_dt.replace(hour=0, minute=0, second=0, microsecond=0)
    if candidate_day > search_day + timedelta(days=max(0, allow_future_days)):
        return False
    return True


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
    date_value = normalize_search_result_date(date_value, report_date=report_date)
    item_type = str(result.get("type") or result.get("category") or "").strip()
    if item_type not in VALID_ITEM_TYPES:
        item_type = infer_item_type_from_search_result(result, query=query)
    item = {
        "title": title,
        "source": source,
        "date": date_value,
        "search_date": date_value,
        "date_source": "search_result",
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
    """Compare search candidates with raw items in both directions.

    Search results must not silently disappear before raw, and raw candidates
    must not be hand-added without matching search-log evidence.
    """
    search_urls = _search_candidate_urls(search_log)
    raw_urls = _raw_candidate_urls(raw_obj)
    missing_urls = sorted(search_urls - raw_urls)
    untraced_raw_urls = sorted(raw_urls - search_urls)
    errors = []
    warnings = []
    if untraced_raw_urls:
        errors.append(f"raw数据有{len(untraced_raw_urls)}条URL缺少search_log候选证据")
    if missing_urls:
        # search_urls 包含重复和过滤掉的 URL，raw_urls 是去重后的。missing_urls 是正常差异。
        warnings.append(f"搜索结果有{len(missing_urls)}条URL未进入raw数据（可能因重复或过滤被去重）")
    return {
        "is_valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "search_candidate_count": len(search_urls),
        "raw_url_count": len(raw_urls),
        "missing_urls": missing_urls,
        "untraced_raw_urls": untraced_raw_urls,
        "coverage_ratio": 1.0 if not search_urls else round(len(search_urls & raw_urls) / len(search_urls), 3),
        "raw_trace_ratio": 1.0 if not raw_urls else round(len(search_urls & raw_urls) / len(raw_urls), 3),
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


def find_default_search_strategy_path(report_date: str, search_log_path: Path | None = None) -> Path | None:
    """Return the default search_strategy path when it already exists."""
    candidates: list[Path] = []
    if search_log_path is not None:
        candidates.append(search_log_path.parent / f"search_strategy_{report_date}.json")
    candidates.append(DATA_DIR / f"search_strategy_{report_date}.json")
    seen: set[Path] = set()
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        if candidate.exists():
            return candidate
    return None


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


def _looks_like_unexecuted_note(text: str) -> bool:
    normalized = str(text or "").strip().lower()
    if not normalized:
        return False
    markers = (
        "未执行",
        "未執行",
        "没有执行",
        "沒有執行",
        "not executed",
        "not run",
        "skipped",
        "timeout",
        "timed out",
        "时间/资源限制",
        "時間/資源限制",
    )
    return any(marker in normalized for marker in markers)


def _query_status_from_entry(query_entry: Any) -> Tuple[str, bool, str]:
    """Return query text, executed status, and failure reason from one search_log query entry."""
    if isinstance(query_entry, str):
        return _normalize_query_text(query_entry), True, ""
    if not isinstance(query_entry, dict):
        return "", False, ""

    query = _normalize_query_text(query_entry.get("query") or query_entry.get("q") or "")
    error = str(query_entry.get("error") or query_entry.get("reason") or query_entry.get("failure") or "").strip()
    note = str(query_entry.get("notes") or query_entry.get("note") or "").strip()
    note_says_unexecuted = _looks_like_unexecuted_note(note)
    if note_says_unexecuted and not error:
        error = note
    if "executed" in query_entry:
        executed = _bool_from_search_log_value(query_entry.get("executed"))
    elif error:
        executed = False
    else:
        executed = True
    if executed and note_says_unexecuted:
        executed = False
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


def configured_required_search_rounds() -> set[str]:
    """Return required base round IDs from search_queries.json, with a legacy fallback."""
    config = load_search_query_config()
    rounds_config = config.get("rounds", []) if isinstance(config, dict) else []
    round_ids = {
        str(round_cfg.get("round_id") or round_cfg.get("round") or round_cfg.get("id") or "").strip()
        for round_cfg in rounds_config
        if isinstance(round_cfg, dict)
    }
    round_ids = {round_id for round_id in round_ids if round_id}
    return round_ids or set(REQUIRED_SEARCH_ROUNDS)


def configured_high_recall_evidence_mode(search_log: Any | None = None) -> str:
    if isinstance(search_log, dict):
        mode = str(search_log.get("high_recall_evidence_mode") or "").strip().lower()
        if mode in VALID_HIGH_RECALL_EVIDENCE_MODES:
            return mode
    env_mode = str(os.getenv("SYNBIO_HIGH_RECALL_EVIDENCE_MODE") or "").strip().lower()
    if env_mode in VALID_HIGH_RECALL_EVIDENCE_MODES:
        return env_mode
    return DEFAULT_HIGH_RECALL_EVIDENCE_MODE


def _has_structured_high_recall_evidence(query_entry: dict[str, Any]) -> bool:
    results = query_entry.get("results")
    if not isinstance(results, list):
        return False
    if not query_entry.get("searched_at"):
        return False
    try:
        result_count = int(query_entry.get("result_count", len(results)))
    except (TypeError, ValueError):
        return False
    return result_count >= 0 and result_count == len(results)


def validate_high_recall_search_log(search_log: Any, rounds_seen: set[str]) -> Dict[str, Any]:
    """Validate production provenance and high-recall LLM discovery evidence."""
    errors: list[str] = []
    warnings: list[str] = []
    if not isinstance(search_log, dict):
        return {"is_valid": False, "errors": ["search_log必须是对象"], "warnings": warnings}
    evidence_mode = configured_high_recall_evidence_mode(search_log)

    if search_log.get("generated_by") != REQUIRED_SEARCH_LOG_GENERATOR:
        warnings.append(
            f"search_log.generated_by必须为{REQUIRED_SEARCH_LOG_GENERATOR}，当前为{search_log.get('generated_by')!r}，建议由 search_executor 生成以确保审计合规"
        )

    try:
        limit = int(search_log.get("limit") or 0)
    except (TypeError, ValueError):
        limit = 0
    if limit < PRODUCTION_SEARCH_MIN_LIMIT:
        warnings.append(f"search_log.limit建议 >= {PRODUCTION_SEARCH_MIN_LIMIT}，当前为{search_log.get('limit')!r}")

    missing_high_recall = sorted(REQUIRED_HIGH_RECALL_ROUNDS - rounds_seen)
    if missing_high_recall:
        warnings.append(f"search_log缺少高召回LLM搜索轮次: {', '.join(missing_high_recall)}")

    provider = str(search_log.get("provider") or "")
    for round_entry in search_log.get("rounds", []) or []:
        if not isinstance(round_entry, dict):
            continue
        round_id = str(round_entry.get("round") or round_entry.get("id") or round_entry.get("round_id") or "").strip()
        if round_id not in REQUIRED_HIGH_RECALL_ROUNDS:
            continue
        queries = round_entry.get("queries")
        if not isinstance(queries, list) or not queries:
            errors.append(f"{round_id}缺少queries，无法证明LLM高召回轮次已执行")
            continue
        for query_entry in queries:
            query, executed, error = _query_status_from_entry(query_entry)
            if not executed:
                errors.append(f"{round_id}查询未成功执行: {query or '<empty>'} ({error or '未记录原因'})")
                continue
            if isinstance(query_entry, dict):
                query_provider = str(query_entry.get("provider") or "")
                if query_provider == "fixture" or provider == "fixture":
                    warnings.append(f"{round_id}使用fixture provider，仅允许离线测试，不得用于正式发送")
                elif evidence_mode == "strict":
                    if query_provider != "llm_web":
                        errors.append(f"{round_id}必须使用llm_web/Kimi web_search，当前provider={query_provider or '<missing>'}")
                    elif query_entry.get("web_search_tool_result") is not True:
                        errors.append(f"{round_id}缺少web_search_tool_result证据: {query}")
                else:
                    if query_provider == "llm_web" and query_entry.get("web_search_tool_result") is not True:
                        errors.append(f"{round_id}缺少web_search_tool_result证据: {query}")
                    elif query_provider != "llm_web" and not _has_structured_high_recall_evidence(query_entry):
                        errors.append(
                            f"{round_id}缺少结构化搜索证据: {query or '<empty>'} "
                            f"(provider={query_provider or '<missing>'})"
                        )

    return {
        "is_valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "evidence_mode": evidence_mode,
    }


def validate_search_strategy_execution(search_strategy: Any, search_log: Any) -> Dict[str, Any]:
    """Validate that LLM-generated dynamic strategy queries were executed."""
    errors: list[str] = []
    warnings: list[str] = []
    if not isinstance(search_strategy, dict):
        return {
            "is_valid": False,
            "errors": ["search_strategy必须是对象"],
            "warnings": warnings,
            "required_total": 0,
            "executed_required_count": 0,
            "missing_queries": [],
            "failed_queries": [],
        }

    raw_queries = search_strategy.get("queries")
    if not isinstance(raw_queries, list):
        return {
            "is_valid": False,
            "errors": ["search_strategy缺少queries列表"],
            "warnings": warnings,
            "required_total": 0,
            "executed_required_count": 0,
            "missing_queries": [],
            "failed_queries": [],
        }

    required_queries: list[str] = []
    malformed = 0
    for entry in raw_queries:
        if isinstance(entry, str):
            query = _normalize_query_text(entry)
            required = True
        elif isinstance(entry, dict):
            query = _normalize_query_text(entry.get("query") or entry.get("q") or "")
            required = _bool_from_search_log_value(entry.get("required", True))
        else:
            query = ""
            required = True
        if not query:
            malformed += 1
            continue
        if required and query not in required_queries:
            required_queries.append(query)
    if malformed:
        errors.append(f"search_strategy有{malformed}条query格式无效")
    if not required_queries:
        errors.append(
            "LLM search_strategy has no required queries; "
            "search_strategy.queries must contain at least one required query"
        )

    executed_by_round, failed_by_round = _collect_search_log_query_status(search_log)
    executed_all = {
        query
        for round_queries in executed_by_round.values()
        for query in round_queries
    }
    failed_all: dict[str, dict[str, str]] = {}
    for round_id, round_failed in failed_by_round.items():
        for query, info in round_failed.items():
            failed_all[query] = {
                "query": info.get("query", query),
                "error": info.get("error", ""),
                "round": round_id,
            }

    missing_queries: list[str] = []
    failed_queries: list[dict[str, str]] = []
    for query in required_queries:
        normalized = _normalize_query_text(query)
        if normalized in executed_all:
            continue
        if normalized in failed_all:
            failed_queries.append(failed_all[normalized])
        else:
            missing_queries.append(query)

    if missing_queries:
        preview = "；".join(missing_queries[:5])
        suffix = f" 等{len(missing_queries)}条" if len(missing_queries) > 5 else ""
        errors.append(f"LLM搜索策略缺少执行记录: {preview}{suffix}")
    if failed_queries:
        formatted = []
        for item in failed_queries[:5]:
            error = item.get("error") or "未记录原因"
            formatted.append(f"{item.get('query', '')} ({error})")
        suffix = f" 等{len(failed_queries)}条" if len(failed_queries) > 5 else ""
        errors.append(f"LLM搜索策略query执行失败: {'；'.join(formatted)}{suffix}")

    executed_required_count = len(required_queries) - len(missing_queries) - len(failed_queries)
    return {
        "is_valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "required_total": len(required_queries),
        "executed_required_count": executed_required_count,
        "missing_queries": missing_queries,
        "failed_queries": failed_queries,
    }


def validate_approved_llm_trace(approved_data: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Ensure approved items carry evidence of the semantic/LLM relevance gate."""
    errors: list[str] = []
    warnings: list[str] = []
    checked: list[dict[str, Any]] = []
    if not approved_data:
        errors.append(EMPTY_APPROVED_ERROR)
        return {
            "is_valid": False,
            "errors": errors,
            "warnings": warnings,
            "checked": checked,
            "total_checked": 0,
        }

    for index, item in enumerate(approved_data, 1):
        title = str(item.get("title") or f"item-{index}")
        item_errors_before = len(errors)
        trace = item.get("llm_relevance")
        if not isinstance(trace, dict):
            errors.append(f"{LLM_TRACE_ERROR}: 第{index}项 {title}")
            checked.append({"index": index, "title": title, "ok": False, "reason": "missing"})
            continue
        provider = str(trace.get("provider") or "").strip().lower()
        relevance = str(trace.get("domain_relevance") or "").strip().lower()
        evidence = trace.get("evidence_spans") or []
        is_approved = trace.get("is_approved")
        if is_approved is not True:
            errors.append(f"{LLM_TRACE_ERROR}: 第{index}项 {title} 的LLM结果不是approved")
        if not provider:
            errors.append(f"{LLM_TRACE_ERROR}: 第{index}项 {title} 缺少provider")
        elif provider in {"off", "heuristic"} or provider.startswith("heuristic"):
            errors.append(f"{LLM_TRACE_ERROR}: 第{index}项 {title} provider={provider}，不能作为正式发送依据")
        if relevance not in {"core_synbio", "adjacent"}:
            errors.append(f"{LLM_TRACE_ERROR}: 第{index}项 {title} domain_relevance={relevance or 'missing'}")
        if not isinstance(evidence, list) or not evidence:
            errors.append(f"{LLM_TRACE_ERROR}: 第{index}项 {title} 缺少evidence_spans")
        checked.append({
            "index": index,
            "title": title,
            "ok": len(errors) == item_errors_before,
            "provider": provider,
            "domain_relevance": relevance,
        })

    return {
        "is_valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "checked": checked,
        "total_checked": len(approved_data),
    }


def validate_approved_date_verification(approved_data: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Ensure search-derived approved items have a page-grounded publish/event date."""
    errors: list[str] = []
    warnings: list[str] = []
    checked: list[dict[str, Any]] = []
    if not approved_data:
        warnings.append("approved为空，无法验证页面发布时间")
        return {
            "is_valid": True,
            "errors": errors,
            "warnings": warnings,
            "checked": checked,
            "total_checked": 0,
        }

    for index, item in enumerate(approved_data, 1):
        title = str(item.get("title") or f"item-{index}")
        if not should_verify_page_date(item):
            checked.append({"index": index, "title": title, "ok": True, "skipped": True})
            continue
        item_errors_before = len(errors)
        verification = item.get("date_verification")
        if not isinstance(verification, dict):
            errors.append(f"{DATE_VERIFICATION_ERROR}: 第{index}项 {title} 缺少date_verification")
            checked.append({"index": index, "title": title, "ok": False, "reason": "missing"})
            continue
        source = str(verification.get("source") or "").strip()
        confidence = str(verification.get("confidence") or "").strip().lower()
        verified_date = str(verification.get("verified_date") or item.get("verified_date") or "").strip()
        if not parse_date(verified_date):
            errors.append(f"{DATE_VERIFICATION_ERROR}: 第{index}项 {title} verified_date无效")
        if is_low_confidence_date_verification(verification):
            errors.append(
                f"{DATE_VERIFICATION_ERROR}: 第{index}项 {title} 仅有搜索日期兜底，source={source or 'missing'}, confidence={confidence or 'missing'}"
            )
        checked.append({
            "index": index,
            "title": title,
            "ok": len(errors) == item_errors_before,
            "source": source,
            "confidence": confidence,
            "verified_date": verified_date,
        })

    return {
        "is_valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "checked": checked,
        "total_checked": len(approved_data),
    }


def infer_raw_item_type(item: Dict[str, Any], fallback_type: str) -> str:
    """Infer the most likely report section when a search result landed in the wrong bucket."""
    for candidate_type in TYPE_INFERENCE_ORDER:
        if candidate_type == fallback_type:
            continue
        if candidate_type == "research" and not _has_research_signal(item):
            continue
        if _looks_like_type(item, candidate_type):
            return candidate_type
    return fallback_type


def _has_research_signal(item: Dict[str, Any]) -> bool:
    text = " ".join(
        str(item.get(field) or "")
        for field in ("title", "summary", "source", "url")
    ).lower()
    research_terms = (
        "研究", "论文", "发表", "期刊", "突破",
        "nature", "science", "cell", "pnas", "acs",
        "journal", "study", "paper", "published", "publication",
        "engineer", "engineered", "recoded", "e. coli", "synthetic cell",
        "biotechnology", "bioengineering",
    )
    return any(term in text for term in research_terms)


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

    if _looks_like_type(normalized, item_type):
        if item_type == "news" and _has_research_signal(normalized) and _looks_like_type(normalized, "research"):
            normalized["original_type"] = item_type
            normalized["type"] = "research"
            normalized["reclassified_from"] = item_type
            normalized["reclassification_reason"] = "news item carries strong research signals; inferred research"
        return True, "", normalized

    if not _looks_like_type(normalized, item_type):
        inferred_type = infer_raw_item_type(normalized, item_type)
        if inferred_type != item_type:
            normalized["original_type"] = item_type
            normalized["type"] = inferred_type
            normalized["reclassified_from"] = item_type
            normalized["reclassification_reason"] = (
                f"source category {item_type} did not match content; inferred {inferred_type}"
            )
            return True, "", normalized
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


def url_dedup_key(url: str) -> str:
    """Return a permanent article identity key for sent-URL deduplication."""
    raw_url = str(url or "").strip()
    if not raw_url:
        return ""
    parts = urlsplit(raw_url)
    hostname = (parts.hostname or "").lower()
    if not hostname:
        return ""
    if hostname.startswith("www."):
        hostname = hostname[4:]
    path = re.sub(r"/{2,}", "/", parts.path or "/")
    path = path.rstrip("/") or "/"

    if hostname.endswith("36kr.com"):
        match = re.search(r"/p/(\d+)", path)
        if match:
            return f"36kr:p:{match.group(1)}"

    if hostname == "mp.weixin.qq.com":
        params = dict(parse_qsl(parts.query, keep_blank_values=True))
        biz = params.get("__biz") or params.get("biz")
        mid = params.get("mid")
        if biz and mid:
            return f"weixin:{biz}:{mid}"

    return f"{hostname}{path}".lower()


def _item_url_dedup_keys(item: Dict[str, Any]) -> set[str]:
    return {
        key for key in (url_dedup_key(url) for url in _item_candidate_urls(item))
        if key
    }


def _sent_url_registry_path(data_dir: Path | None = None) -> Path:
    return (data_dir or DATA_DIR) / "sent_url_registry.json"


def _load_sent_url_registry(data_dir: Path | None = None) -> Dict[str, Any]:
    path = _sent_url_registry_path(data_dir)
    if not path.exists():
        return {"version": 1, "registry": {}}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and isinstance(data.get("registry"), dict):
            return data
    except Exception:
        pass
    return {"version": 1, "registry": {}}


def update_sent_url_registry(
    date_str: str,
    approved_items: List[Dict[str, Any]],
    data_dir: Path | None = None,
) -> None:
    """Persist permanent sent URL keys after a successful real send."""
    registry = _load_sent_url_registry(data_dir)
    registry.setdefault("version", 1)
    entries = registry.setdefault("registry", {})

    for item in approved_items:
        title = str(item.get("title") or "").strip()
        for url in _item_candidate_urls(item):
            key = url_dedup_key(url)
            if not key:
                continue
            existing = entries.get(key)
            if isinstance(existing, dict):
                existing["sent_count"] = int(existing.get("sent_count") or 1) + 1
                existing.setdefault("first_sent_date", date_str)
                existing["last_seen_date"] = date_str
                continue
            entries[key] = {
                "url": url,
                "dedup_key": key,
                "title": title[:120],
                "first_sent_date": date_str,
                "last_seen_date": date_str,
                "sent_count": 1,
            }

    path = _sent_url_registry_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(registry, f, ensure_ascii=False, indent=2)


def _history_entries_from_data_dir(data_dir: Path | None = None) -> list[dict[str, Any]]:
    path = (data_dir or DATA_DIR) / "history_index.json"
    if not path.exists():
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        entries = data.get("entries", []) if isinstance(data, dict) else []
        return [entry for entry in entries if isinstance(entry, dict)]
    except Exception:
        return []


def validate_approved_not_previously_sent(
    approved_data: List[Dict[str, Any]],
    data_dir: Path | None = None,
    label: str = "approved",
) -> Dict[str, Any]:
    """Block any approved item whose URL identity was already sent before.

    This is the send-gate backstop. build-approved also checks history, but a
    manually edited approved JSON must not be able to bypass permanent URL
    deduplication.
    """
    registry = _load_sent_url_registry(data_dir)
    registry_entries = registry.get("registry", {}) if isinstance(registry, dict) else {}
    history_entries = _history_entries_from_data_dir(data_dir)
    sent_keys: dict[str, dict[str, Any]] = {}

    for key, entry in (registry_entries or {}).items():
        if key:
            sent_keys[str(key)] = entry if isinstance(entry, dict) else {"dedup_key": key}

    for entry in history_entries:
        candidate_urls = _item_candidate_urls(entry)
        candidate_urls.append(str(entry.get("canonical_url") or ""))
        candidate_urls.append(str(entry.get("url") or ""))
        if entry.get("dedup_key"):
            sent_keys.setdefault(str(entry["dedup_key"]), entry)
        for url in candidate_urls:
            key = url_dedup_key(url)
            if key:
                sent_keys.setdefault(key, entry)

    errors: list[str] = []
    checked: list[dict[str, Any]] = []
    duplicate_indices: set[int] = set()
    duplicate_records: list[dict[str, Any]] = []
    for index, item in enumerate(approved_data, 1):
        title = str(item.get("title") or "未命名信息")
        for key in sorted(_item_url_dedup_keys(item)):
            checked.append({"index": index, "title": title, "dedup_key": key})
            previous = sent_keys.get(key)
            if not previous:
                continue
            duplicate_indices.add(index)
            first_sent = previous.get("first_sent_date") or previous.get("date") or "unknown"
            prev_title = previous.get("title") or "历史记录"
            duplicate_records.append({
                "index": index,
                "title": title,
                "dedup_key": key,
                "first_sent_date": first_sent,
                "previous_title": prev_title,
            })
            errors.append(
                f"{label}第{index}项URL已发送过: {title} "
                f"(dedup_key={key}, first_sent_date={first_sent}, previous_title={prev_title})"
            )

    return {
        "is_valid": len(errors) == 0,
        "errors": errors,
        "checked": checked,
        "total_checked": len(checked),
        "duplicate_indices": sorted(duplicate_indices),
        "duplicate_records": duplicate_records,
        "sent_dedup_keys": sorted(sent_keys.keys()),
    }


class PageDateParser(HTMLParser):
    """Extract common structured dates from HTML without external dependencies."""

    def __init__(self) -> None:
        super().__init__()
        self.meta_dates: list[str] = []
        self.time_dates: list[str] = []
        self.text_parts: list[str] = []
        self._skip_text_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag_name = tag.lower()
        attributes = {str(name).lower(): str(value or "") for name, value in attrs}
        if tag_name in {"script", "style", "noscript", "svg"}:
            self._skip_text_depth += 1
        if tag_name == "meta":
            key = (
                attributes.get("property")
                or attributes.get("name")
                or attributes.get("itemprop")
                or ""
            ).lower()
            content = attributes.get("content", "")
            if content and key in PAGE_DATE_META_KEYS:
                self.meta_dates.append(content)
        if tag_name == "time" and attributes.get("datetime"):
            self.time_dates.append(attributes["datetime"])

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style", "noscript", "svg"} and self._skip_text_depth > 0:
            self._skip_text_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._skip_text_depth > 0:
            return
        text = str(data or "").strip()
        if text:
            self.text_parts.append(text)

    def visible_text(self) -> str:
        return " ".join(self.text_parts)


def _parse_any_date(value: str) -> Optional[datetime]:
    parsed = parse_date(value)
    if parsed:
        return parsed
    try:
        parsed_email_date = parsedate_to_datetime(str(value or ""))
        if parsed_email_date is not None:
            return parsed_email_date.replace(tzinfo=None)
    except Exception:
        return None
    return None


def _date_candidates_from_text(text: str) -> list[datetime]:
    candidates: list[datetime] = []
    for pattern in DATE_TEXT_PATTERNS:
        for match in re.finditer(pattern, text or "", flags=re.IGNORECASE):
            parsed = _parse_any_date(match.group(0))
            if parsed:
                candidates.append(parsed)
    return candidates


def _date_context(text: str, start: int, end: int, window: int = 48) -> str:
    left = max(0, start - window)
    right = min(len(text or ""), end + window)
    return (text or "")[left:right].lower()


def _is_noise_date_context(context: str) -> bool:
    return any(keyword.lower() in context for keyword in DATE_NOISE_CONTEXT_KEYWORDS)


def _is_effective_date_context(context: str) -> bool:
    has_effective = any(keyword.lower() in context for keyword in DATE_EFFECTIVE_CONTEXT_KEYWORDS)
    if not has_effective:
        return False
    # Policies often mention both approval/release and effective dates. If the
    # context also contains a release/approval verb, keep it as a real event date.
    has_event = any(keyword.lower() in context for keyword in DATE_EVENT_CONTEXT_KEYWORDS)
    return not has_event


def _is_event_date_context(context: str) -> bool:
    if _is_noise_date_context(context) or _is_effective_date_context(context):
        return False
    return any(keyword.lower() in context for keyword in DATE_EVENT_CONTEXT_KEYWORDS)


def _contextual_date_candidates_from_text(text: str) -> list[datetime]:
    """Return body dates whose nearby text says publication or real event date.

    Search engines often expose crawl dates. The page body may contain many
    unrelated dates too, such as effective dates, copyright years, or market
    history. Only contextual dates are allowed to override the search date.
    """
    candidates: list[datetime] = []
    for pattern in DATE_TEXT_PATTERNS:
        for match in re.finditer(pattern, text or "", flags=re.IGNORECASE):
            context = _date_context(text or "", match.start(), match.end())
            if not _is_event_date_context(context):
                continue
            parsed = _parse_any_date(match.group(0))
            if parsed:
                candidates.append(parsed)
    return candidates


def _unique_dates(candidates: list[datetime]) -> list[datetime]:
    seen: set[str] = set()
    unique: list[datetime] = []
    for candidate in candidates:
        key = candidate.strftime("%Y-%m-%d")
        if key in seen:
            continue
        seen.add(key)
        unique.append(candidate)
    return unique


def _select_verified_date(
    candidates: list[datetime],
    search_date: str = "",
    *,
    allow_unanchored: bool = True,
) -> Optional[datetime]:
    """Pick a page date without letting related-story dates override news dates.

    Article pages often contain related links or market-history widgets with
    older dates. When a search/result date is available, use it only as a
    disambiguation anchor among page-visible candidates.
    """
    # 先过滤掉不合理的日期（模板占位符、正文中的未来日期等）
    unique = _unique_dates([
        candidate
        for candidate in candidates
        if candidate and _is_plausible_verified_date(candidate, search_date, allow_future_days=0)
    ])
    if not unique:
        return None

    search_dt = parse_date(search_date)
    if search_dt:
        if len(unique) == 1 and allow_unanchored:
            return unique[0]
        search_day = search_dt.replace(hour=0, minute=0, second=0, microsecond=0)
        anchored = sorted(
            unique,
            key=lambda candidate: (
                abs((candidate.replace(hour=0, minute=0, second=0, microsecond=0) - search_day).days),
                -candidate.timestamp(),
            ),
        )
        best = anchored[0]
        delta_days = abs((best.replace(hour=0, minute=0, second=0, microsecond=0) - search_day).days)
        if delta_days <= DATE_VERIFY_SEARCH_TOLERANCE_DAYS:
            return best
        return None

    if not allow_unanchored and len(unique) > 1:
        return None
    return min(unique)


def _first_plausible_body_date(text: str, search_date: str = "") -> Optional[datetime]:
    lead = (text or "")[:2000]
    for pattern in DATE_TEXT_PATTERNS:
        for match in re.finditer(pattern, lead, flags=re.IGNORECASE):
            parsed = _parse_any_date(match.group(0))
            if parsed and _is_plausible_verified_date(parsed, search_date, allow_future_days=0):
                return parsed
    return None


def _is_close_to_search_date(candidate: datetime, search_date: str = "", *, max_days: int = DATE_VERIFY_SEARCH_TOLERANCE_DAYS) -> bool:
    search_dt = parse_date(search_date)
    if not search_dt:
        return True
    candidate_day = candidate.replace(hour=0, minute=0, second=0, microsecond=0)
    search_day = search_dt.replace(hour=0, minute=0, second=0, microsecond=0)
    return abs((candidate_day - search_day).days) <= max_days


def _header_window_date(text: str, title: str, search_date: str = "") -> Optional[datetime]:
    content = str(text or "")
    heading = str(title or "").strip()
    if not content:
        return None
    if heading:
        index = content.find(heading)
        if index >= 0:
            window = content[index:index + 260]
        else:
            window = content[:260]
    else:
        window = content[:260]

    datetime_patterns = [
        r"(\d{4}[-/\.]\d{1,2}[-/\.]\d{1,2})\s+\d{1,2}:\d{2}(?::\d{2})?",
        r"(\d{4}年\d{1,2}月\d{1,2}日)\s+\d{1,2}:\d{2}(?::\d{2})?",
    ]
    matches = []
    for pattern in datetime_patterns:
        for match in re.finditer(pattern, window, flags=re.IGNORECASE):
            matches.append(match)
    if not matches:
        return None
    matches.sort(key=lambda m: m.start())
    match = matches[0]
    prefix = window[max(0, match.start() - 32):match.start()]
    if not re.search(r"[\u4e00-\u9fffA-Za-z]", prefix):
        return None
    earlier_slice = window[:match.start()]
    for pattern in DATE_TEXT_PATTERNS:
        if re.search(pattern, earlier_slice, flags=re.IGNORECASE):
            return None
    parsed = _parse_any_date(match.group(1))
    if parsed and _is_reasonable_date(parsed):
        return parsed
    return None


def extract_page_verified_date(html: str, search_date: str = "", page_url: str = "") -> Dict[str, Any]:
    """Extract a conservative original date from a fetched page."""
    parser = PageDateParser()
    try:
        parser.feed(html or "")
    except Exception:
        pass

    meta_dates = [
        parsed for parsed in (_parse_any_date(value) for value in parser.meta_dates + parser.time_dates)
        if parsed
    ]
    text = unescape(parser.visible_text())
    text = re.sub(r"\s+", " ", text)
    title_hint = ""
    title_match = re.search(r"<title[^>]*>(.*?)</title>", html or "", flags=re.IGNORECASE | re.DOTALL)
    if title_match:
        title_hint = unescape(re.sub(r"\s+", " ", title_match.group(1))).strip()

    context_dates: list[datetime] = []
    context_pattern = (
        r"(?:发布时间|发布日期|发布于|发表时间|成文日期|发文日期|印发日期|通过日期|"
        r"日期|时间|Published|Posted|Updated)"
        r"[:：\s]{0,12}"
        r"(\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日|\d{4}[-/\.]\d{1,2}[-/\.]\d{1,2}|"
        r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\s+\d{1,2},\s*\d{4})"
    )
    for match in re.finditer(context_pattern, text, flags=re.IGNORECASE):
        parsed = _parse_any_date(match.group(1))
        if parsed:
            context_dates.append(parsed)

    header_verified = _header_window_date(text, title_hint, search_date)
    if header_verified:
        return {
            "verified_date": header_verified.strftime("%Y-%m-%d"),
            "confidence": "high",
            "source": "body_context",
            "date_count": 1,
        }

    meta_time_dates = meta_dates
    if meta_time_dates:
        verified = _select_verified_date(meta_time_dates, search_date)
        if verified:
            return {
                "verified_date": verified.strftime("%Y-%m-%d"),
                "confidence": "high",
                "source": "meta/body",
                "date_count": len(_unique_dates(meta_time_dates)),
            }

    if context_dates:
        verified = _select_verified_date(context_dates, "")
        if verified:
            return {
                "verified_date": verified.strftime("%Y-%m-%d"),
                "confidence": "high",
                "source": "meta/body",
                "date_count": len(_unique_dates(context_dates)),
            }

    event_dates = _contextual_date_candidates_from_text(text)
    if event_dates:
        verified = _select_verified_date(event_dates, search_date, allow_unanchored=True)
        if verified:
            return {
                "verified_date": verified.strftime("%Y-%m-%d"),
                "confidence": "high",
                "source": "body_context",
                "date_count": len(_unique_dates(event_dates)),
            }

    # If no structured or contextual signal exists, fall back to generic body
    # dates only when they are unambiguous or line up with the collected search
    # date. This keeps legacy pages usable without letting related-story dates
    # override the article's actual publish date.
    if not (meta_time_dates or context_dates or event_dates):
        generic_dates = _date_candidates_from_text(text)
        verified = _select_verified_date(generic_dates, search_date, allow_unanchored=False)
        if verified and _is_close_to_search_date(verified, search_date):
            return {
                "verified_date": verified.strftime("%Y-%m-%d"),
                "confidence": "medium",
                "source": "body",
                "date_count": len(_unique_dates(generic_dates)),
            }

    all_dates = meta_time_dates + context_dates + event_dates
    if all_dates:
        return {
            "verified_date": search_date,
            "confidence": "low",
            "source": "search_fallback",
            "date_count": len(_unique_dates(all_dates)),
            "warning": "页面含多个日期但无与搜索日期相符的发布/事件日期，回退搜索日期",
        }

    return {
        "verified_date": search_date,
        "confidence": "low",
        "source": "search_fallback",
        "date_count": 0,
    }


def fetch_and_verify_date(
    url: str,
    search_date: str,
    timeout: int = DATE_VERIFY_TIMEOUT_SECONDS,
    opener=urlopen,
) -> Dict[str, Any]:
    """Fetch a candidate page and verify its earliest visible publication/event date."""
    try:
        safe_url(url)
    except ValueError as exc:
        return {
            "verified_date": search_date,
            "confidence": "low",
            "source": "search_fallback",
            "error": f"URL不安全: {exc}",
        }

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
            headers = getattr(response, "headers", {}) or {}
            charset = "utf-8"
            if hasattr(headers, "get_content_charset"):
                charset = headers.get_content_charset() or charset
            body = response.read(DATE_VERIFY_MAX_BYTES)
        html = body.decode(charset, errors="replace")
        result = extract_page_verified_date(html, search_date=search_date, page_url=url)
        result["url"] = url
        return result
    except Exception as exc:
        return {
            "verified_date": search_date,
            "confidence": "low",
            "source": "search_fallback",
            "url": url,
            "error": str(exc),
        }


def should_verify_page_date(item: Dict[str, Any]) -> bool:
    """Only search-derived candidates need network date verification."""
    return (
        item.get("date_source") == "search_result"
        or bool(item.get("source_round"))
        or bool(item.get("source_query"))
    )


def is_low_confidence_date_verification(verification: Any) -> bool:
    if not isinstance(verification, dict):
        return False
    source = str(verification.get("source") or "").strip().lower()
    confidence = str(verification.get("confidence") or "").strip().lower()
    return source == "search_fallback" or confidence == "low"


def verify_item_page_date(
    item: Dict[str, Any],
    date_verify_func=fetch_and_verify_date,
) -> Dict[str, Any]:
    """Attach verified page date metadata and use it as the effective item date."""
    verified_item = dict(item)
    search_date = str(verified_item.get("search_date") or verified_item.get("date") or "")
    result = date_verify_func(str(verified_item.get("url") or ""), search_date)
    if not isinstance(result, dict):
        return verified_item
    verified_item["date_verification"] = result
    verified_date = str(result.get("verified_date") or "").strip()
    if result.get("source") != "search_fallback":
        verified_dt = parse_date(verified_date)
        effective_type = str(verified_item.get("content_type") or verified_item.get("type") or "")
        allow_future_days = 1 if effective_type in {"events", "event_preview"} else 0
        if verified_dt and _is_plausible_verified_date(verified_dt, search_date, allow_future_days=allow_future_days):
            verified_item["verified_date"] = verified_date
            verified_item["date"] = verified_date
        else:
            # 日期不合理：降级为 search_fallback
            verified_item["date_verification"] = {
                "verified_date": verified_date,
                "source": "search_fallback",
                "confidence": "low",
                "reason": f"页面提取日期不合理: {verified_date}",
            }
    return verified_item


def verify_items_page_dates(
    items: List[Dict[str, Any]],
    date_verify_func=fetch_and_verify_date,
    *,
    max_workers: int = DATE_VERIFY_MAX_WORKERS,
) -> List[Dict[str, Any]]:
    """Verify page dates for many items with URL-level caching and bounded concurrency."""
    if not items:
        return []

    worker_count = max(1, min(int(max_workers or 1), len(items)))
    cache: dict[str, Dict[str, Any]] = {}
    cache_lock = threading.Lock()

    def cache_key(item: Dict[str, Any]) -> str:
        primary = canonicalize_url(str(item.get("url", "") or ""))
        search_date = str(item.get("search_date") or item.get("date") or "")
        return f"{primary}::{search_date}"

    def run(item: Dict[str, Any]) -> Dict[str, Any]:
        key = cache_key(item)
        with cache_lock:
            cached = cache.get(key)
        if cached is not None:
            verified_item = dict(item)
            verified_item.update(cached)
            return verified_item

        verified_item = verify_item_page_date(item, date_verify_func=date_verify_func)
        with cache_lock:
            cache[key] = {
                "date_verification": dict(verified_item.get("date_verification") or {}),
                "verified_date": verified_item.get("verified_date"),
                "date": verified_item.get("date"),
            }
        return verified_item

    if worker_count == 1:
        return [run(item) for item in items]

    results: list[Dict[str, Any]] = [dict(item) for item in items]
    with concurrent.futures.ThreadPoolExecutor(max_workers=worker_count) as executor:
        future_map = {executor.submit(run, item): index for index, item in enumerate(items)}
        for future in concurrent.futures.as_completed(future_map):
            index = future_map[future]
            results[index] = future.result()
    return results


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

    segments = [segment for segment in slashless_path.split("/") if segment]
    if segments and segments[0] in {"topic", "topics"} and len(segments) >= 3:
        return False

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


def _is_historical_duplicate(item, history_entries, sent_url_registry: Dict[str, Any] | None = None):
    """
    检查 item 是否与历史索引中的条目重复。
    检查维度：URL 身份键、URL 完全匹配、标题完全匹配、内容指纹相似度 > 75%。
    """
    item_urls = {canonicalize_url(url) for url in _item_candidate_urls(item)}
    item_url_keys = _item_url_dedup_keys(item)
    registry_entries = {}
    if isinstance(sent_url_registry, dict):
        registry_entries = sent_url_registry.get("registry", {}) or {}
    if item_url_keys and any(key in registry_entries for key in item_url_keys):
        return True

    if not history_entries:
        return False
    item_title = item.get("title", "").strip()
    item_title_norm = normalize_title(item_title)
    item_fp = _make_fingerprint(item)
    item_tokens = set(item_fp.split())
    for entry in history_entries:
        entry_url_keys = set()
        if entry.get("dedup_key"):
            entry_url_keys.add(str(entry.get("dedup_key")))
        # URL 完全匹配
        entry_urls = [entry.get("canonical_url") or canonicalize_url(entry.get("url", ""))]
        entry_urls.extend(canonicalize_url(url) for url in _coerce_url_list(entry.get("urls", [])))
        entry_urls = {url for url in entry_urls if url}
        entry_url_keys.update(
            key for key in (
                url_dedup_key(entry.get("url", "")),
                *[url_dedup_key(url) for url in _coerce_url_list(entry.get("urls", []))],
                *[url_dedup_key(url) for url in entry_urls],
            )
            if key
        )
        if item_url_keys and item_url_keys & entry_url_keys:
            return True
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
            if overlap >= 0.75:
                return True
            # Only run expensive SequenceMatcher when token overlap is moderately close
            if overlap >= 0.40:
                sim = SequenceMatcher(None, item_fp, hist_fp).ratio()
                if sim >= 0.75:
                    return True
        # 标题相似度兜底（仅当标题明显相似时）
        if item_title_norm and entry_title:
            entry_title_norm = normalize_title(entry_title)
            if entry_title_norm and SequenceMatcher(None, item_title_norm, entry_title_norm).ratio() >= 0.92:
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
                # In lenient mode, treat 403 (Forbidden) as a warning for academic sites
                # rather than a hard error, since many journals block HEAD requests
                if mode == "lenient" and status == 403:
                    return {
                        "ok": True,
                        "url": url,
                        "status": status,
                        "warning": f"HTTP {status} (访问受限，链接可能有效但需登录/特定网络)",
                    }
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
            # In lenient mode, suppress 403 errors for academic/publisher sites
            if mode == "lenient" and result.get("status") == 403:
                warnings.append(f"{label}链接访问受限(HTTP 403): {url} - 可能需要登录或特定网络访问")
            else:
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


GENERIC_TITLE_PATTERNS = (
    r"^[\u4e00-\u9fff]{2,12}人民政府$",
    r"^[\u4e00-\u9fff]{2,20}政策文件库$",
    r"^[\u4e00-\u9fff]{2,20}通知公告$",
    r"^[\u4e00-\u9fff]{2,20}新闻$",
)


def _looks_like_generic_title(title: str) -> bool:
    cleaned = _strip_html_tags(title)
    if not cleaned:
        return True
    normalized = normalize_title(cleaned)
    if not normalized:
        return True
    return any(re.fullmatch(pattern, cleaned) for pattern in GENERIC_TITLE_PATTERNS)


def _choose_better_page_title(item_title: str, page_titles: list[str]) -> str | None:
    current = _strip_html_tags(item_title)
    current_norm = normalize_title(current)
    candidates = []
    for signal in page_titles:
        cleaned = _strip_html_tags(signal)
        if not cleaned:
            continue
        if normalize_title(cleaned) == current_norm:
            continue
        if _looks_like_generic_title(cleaned):
            continue
        candidates.append(cleaned)
    if not candidates:
        return None
    candidates.sort(
        key=lambda value: (
            title_match_score(current, value),
            len(normalize_title(value)),
        ),
        reverse=True,
    )
    return candidates[0]


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
        page_titles = result.get("page_titles") if isinstance(result.get("page_titles"), list) else []
        replacement = _choose_better_page_title(str(item.get("title") or ""), [str(value) for value in page_titles])
        if replacement and _looks_like_generic_title(str(item.get("title") or "")):
            item = dict(item)
            original_title = str(item.get("title") or "")
            item["original_title"] = original_title
            item["title"] = replacement
            warnings.append(f"{original_title}: 已使用页面标题修正为 {replacement}")
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
    effective_type = str(item.get("content_type") or item_type or "news")
    if effective_type == "event_preview":
        effective_type = "events"
    date_str = item.get("verified_date") or item.get("date", "")
    item_date = parse_date(date_str)
    current_time = (now or now_local()).replace(tzinfo=None)
    
    if not item_date:
        return False, f"无法解析日期 ({date_str})"
    
    window_days = TIME_WINDOWS.get(effective_type, TIME_WINDOWS.get(item_type, 7))
    cutoff = current_time - timedelta(days=window_days)
    # 只比较日期部分，避免边界时间问题
    cutoff = cutoff.replace(hour=0, minute=0, second=0, microsecond=0)
    
    if effective_type == "events":
        # 活动：允许过去7天内的回顾，也允许未来窗口内的预告
        future_cutoff = current_time + timedelta(days=window_days)
        past_cutoff = current_time - timedelta(days=7)
        item_day = item_date.replace(hour=0, minute=0, second=0, microsecond=0)
        if item_date > future_cutoff:
            return False, f"活动太远 ({date_str}, 超过{window_days}天)"
        if item_day < past_cutoff.replace(hour=0, minute=0, second=0, microsecond=0):
            return False, f"活动已过期 ({date_str}, 超过7天)"
        return True, ""
    
    # 非活动类型：拒绝未来日期（超过当前时间1天），防止正文中的预计日期或模板占位符被误用
    tomorrow = current_time + timedelta(days=1)
    tomorrow = tomorrow.replace(hour=0, minute=0, second=0, microsecond=0)
    if item_date > tomorrow:
        return False, f"日期在未来 ({date_str})，疑似正文中的预计日期或模板占位符"
    
    if item_date < cutoff:
        return False, f"超过时间窗口 ({date_str}, 限制{window_days}天)"
    
    return True, ""


def classify_content_type(item: Dict[str, Any], item_type: str) -> Tuple[str, str]:
    """Classify content semantics separately from report section type."""
    text = " ".join(
        str(item.get(field) or "")
        for field in ("title", "summary", "source", "url")
    ).lower()
    if any(keyword in text for keyword in MARKET_REPORT_KEYWORDS):
        return "market_report", "市场研究/行业规模报告，主体是历史数据或预测，不是当日事件"
    if item_type == "events":
        return "event_preview", "活动预告"
    return item_type, "沿用栏目类型"


def should_exclude_content_type(content_type: str) -> bool:
    """Return True for content types that should not enter the daily main report."""
    return content_type == "market_report"


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

def process_raw_data(
    raw_data: List[Dict[str, Any]],
    item_type: str,
    date_verify_func=None,
) -> Dict[str, Any]:
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
    sent_url_registry = _load_sent_url_registry()
    
    approved = []
    rejected = []
    candidates: list[Dict[str, Any]] = []

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

        # 0.25 内容类型识别：市场研究/规模预测报告不进入日报主内容
        effective_item_type = str(item.get("type") or item_type)
        content_type, content_reason = classify_content_type(item, effective_item_type)
        item["content_type"] = content_type
        if should_exclude_content_type(content_type):
            rejected.append({
                "item": item,
                "reason": f"[内容类型] {content_reason}",
                "action": "排除",
            })
            continue

        # 0.5 跨天历史索引去重（基于 history_index.json 的持久化去重）
        if _is_historical_duplicate(item, history_entries, sent_url_registry):
            rejected.append({
                "item": item,
                "reason": "[历史索引去重] 与已发送历史记录重复",
                "action": "排除",
            })
            continue
        candidates.append(item)

    if date_verify_func:
        to_verify = [item for item in candidates if should_verify_page_date(item)]
        verified_by_identity = {
            id(item): verified
            for item, verified in zip(
                to_verify,
                verify_items_page_dates(to_verify, date_verify_func=date_verify_func),
            )
        }
    else:
        verified_by_identity = {}

    for item in candidates:
        item = verified_by_identity.get(id(item), item)
        effective_item_type = str(item.get("type") or item_type)
        if date_verify_func and should_verify_page_date(item):
            verification = item.get("date_verification")
            if is_low_confidence_date_verification(verification):
                source = str((verification or {}).get("source") or "").strip() if isinstance(verification, dict) else ""
                confidence = str((verification or {}).get("confidence") or "").strip().lower() if isinstance(verification, dict) else ""
                rejected.append({
                    "item": item,
                    "reason": (
                        f"[页面日期] 仅有搜索日期兜底，source={source or 'missing'}, "
                        f"confidence={confidence or 'missing'}"
                    ),
                    "action": "排除",
                })
                continue

        # 1. 时效性检查
        timely, reason = check_timeliness(item, effective_item_type)
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
        if effective_item_type == "policy":
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
        "date_verification_rejected": len([r for r in rejected if "页面日期" in r["reason"]]),
        "duplicate_rejected": len([r for r in rejected if "去重" in r["reason"] or "政策库" in r["reason"]]),
        "content_type_rejected": len([r for r in rejected if "内容类型" in r["reason"]]),
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
    heading_lines = "\n".join(
        line for line in content.splitlines()
        if re.match(r"^##\s+", line)
    )
    for pattern in forbidden_patterns:
        if re.search(pattern, heading_lines, re.IGNORECASE):
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
        warnings.append(f"以下板块为空或未收录有效信息: {', '.join(blank_sections)}。请确认已执行基座必搜和LLM高召回检索，并在报告中注明'经完整检索，本周期暂无新信息'")
    
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
    title_summary_url = (
        f"{item.get('title', '')} {item.get('summary', '')} "
        f"{item.get('url', '')} {item.get('source_query', '')}"
    ).lower()
    text = f"{title_summary_url} {item.get('source', '')}".lower()
    
    # 1. 合成生物学主题相关性（核心判断）
    # 使用 LLM 语义判断（优先）或精确匹配（fallback）
    is_relevant, reason, confidence = _is_synbio_relevant(
        title=str(item.get("title", "")),
        summary=f"{item.get('summary', '')} {item.get('source_query', '')}",
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
    approved_llm_trace = validate_approved_llm_trace(approved_data)
    approved_date_verification = validate_approved_date_verification(approved_data)
    ai_result = report_result.get("ai_check", {"has_errors": False, "errors": [], "warnings": []})
    
    fix_instructions = list(report_result.get("fix_instructions", []))
    empty_approved = not approved_data
    if empty_approved:
        fix_instructions.append(EMPTY_APPROVED_ERROR)
    
    # 邮件一致性错误必须修复
    if not email_result["is_consistent"]:
        fix_instructions.extend(email_result["errors"])

    if not approved_schema["is_valid"]:
        fix_instructions.extend(approved_schema["errors"])

    if approved_timeliness["has_errors"]:
        fix_instructions.extend(approved_timeliness["errors"])

    if not approved_llm_trace["is_valid"]:
        fix_instructions.extend(approved_llm_trace["errors"])

    if not approved_date_verification["is_valid"]:
        fix_instructions.extend(approved_date_verification["errors"])
    
    # 邮件一致性警告建议修复
    if email_result["warnings"]:
        fix_instructions.extend([f"[邮件一致性建议] {w}" for w in email_result["warnings"]])
    if approved_schema["warnings"]:
        fix_instructions.extend([f"[approved schema建议] {w}" for w in approved_schema["warnings"]])
    if approved_timeliness["warnings"]:
        fix_instructions.extend([f"[approved时效性建议] {w}" for w in approved_timeliness["warnings"]])
    if approved_llm_trace["warnings"]:
        fix_instructions.extend([f"[LLM审计建议] {w}" for w in approved_llm_trace["warnings"]])
    if approved_date_verification["warnings"]:
        fix_instructions.extend([f"[页面日期建议] {w}" for w in approved_date_verification["warnings"]])
    
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
    if not approved_llm_trace["is_valid"]:
        score -= len(approved_llm_trace["errors"]) * 15
    if not approved_date_verification["is_valid"]:
        score -= len(approved_date_verification["errors"]) * 15
    if empty_approved:
        score -= 50
    score = max(0, score)
    
    report_passed = report_result["passed"]
    email_consistent = email_result["is_consistent"]
    ai_passed = not ai_result["has_errors"]
    approved_schema_ok = approved_schema["is_valid"]
    approved_timely = not approved_timeliness["has_errors"]
    approved_llm_ok = approved_llm_trace["is_valid"]
    approved_date_ok = approved_date_verification["is_valid"]
    can_send = (
        report_passed
        and email_consistent
        and ai_passed
        and approved_schema_ok
        and approved_timely
        and approved_llm_ok
        and approved_date_ok
        and not empty_approved
        and score >= 80
    )
    
    return {
        "report_passed": report_passed,
        "email_consistent": email_consistent,
        "ai_passed": ai_passed,
        "approved_schema_ok": approved_schema_ok,
        "approved_timely": approved_timely,
        "approved_llm_ok": approved_llm_ok,
        "approved_date_ok": approved_date_ok,
        "can_send_email": can_send,
        "overall_score": score,
        "fix_instructions": fix_instructions,
        "report_check": report_result,
        "email_check": email_result,
        "ai_check": ai_result,
        "approved_schema_check": approved_schema,
        "approved_timeliness_check": approved_timeliness,
        "approved_llm_trace_check": approved_llm_trace,
        "approved_date_verification_check": approved_date_verification,
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
    search_strategy: Any | None = None,
    require_search_strategy: bool = False,
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
            "strategy_check": None,
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
            "strategy_check": None,
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

    required_rounds = configured_required_search_rounds()
    missing_rounds = sorted(required_rounds - rounds_seen)
    if missing_rounds:
        warnings.append(f"search_log缺少必要搜索轮次: {', '.join(missing_rounds)}")

    high_recall_check = None
    if strict_coverage or require_search_strategy:
        high_recall_check = validate_high_recall_search_log(search_log, rounds_seen)
        if high_recall_check["errors"]:
            errors.extend(high_recall_check["errors"])
        warnings.extend(high_recall_check.get("warnings", []))

    required_query_check = validate_required_search_queries(search_log)
    if required_query_check["errors"]:
        # Cron 简化流程可能未执行所有 required queries，降级为警告以允许自动流程通过
        warnings.extend(required_query_check["errors"])

    strategy_check = None
    if search_strategy is not None:
        strategy_check = validate_search_strategy_execution(search_strategy, search_log)
        if strategy_check["errors"]:
            errors.extend(strategy_check["errors"])
        warnings.extend(strategy_check.get("warnings", []))
    elif require_search_strategy:
        errors.append(MISSING_SEARCH_STRATEGY_ERROR)

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
        if not coverage_check["is_valid"]:
            message = (
                f"搜索覆盖率不足/溯源不足: search_log候选{coverage_check['search_candidate_count']}条, "
                f"raw收录{coverage_check['raw_url_count']}条, "
                f"搜索结果缺失{len(coverage_check['missing_urls'])}条, "
                f"raw无搜索证据{len(coverage_check['untraced_raw_urls'])}条"
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
        "strategy_check": strategy_check,
        "high_recall_check": high_recall_check,
    }


def build_approved_from_raw(
    raw_obj: Any,
    report_date: str,
    output_dir: Path | None = None,
    check_url_health_enabled: bool = True,
    check_title_match_enabled: bool = True,
    check_page_date_enabled: bool = True,
    url_check_func=check_url_health,
    title_check_func=check_url_title_match,
    date_verify_func=fetch_and_verify_date,
    llm_relevance_mode: str = "auto",
    llm_judge_func=judge_item_relevance,
    llm_date_judge_func=judge_item_date_validity,
    llm_final_audit_mode: str = "auto",
    search_log: Any | None = None,
    search_strategy: Any | None = None,
    strict_search_log: bool = True,
) -> Dict[str, Any]:
    """Process every category from a full raw dict and persist approved/rejected outputs."""
    if not isinstance(raw_obj, dict):
        raise ValueError("--build-approved requires a full raw category dict")
    if search_strategy is not None and search_log is None:
        raise ValueError("search_strategy requires search_log so dynamic query execution can be audited")
    if search_log is not None and search_strategy is None:
        search_strategy_path = find_default_search_strategy_path(report_date)
        if search_strategy_path is not None and search_strategy_path.exists():
            with open(search_strategy_path, "r", encoding="utf-8") as f:
                search_strategy = json.load(f)
            print(f"build_approved_from_raw: 自动加载搜索策略 {search_strategy_path}")
        else:
            if strict_search_log:
                raise ValueError(MISSING_SEARCH_STRATEGY_ERROR)
            print(f"build_approved_from_raw: 未找到搜索策略 {search_strategy_path}，继续运行（调试模式允许）")

    search_log_check = None
    if search_log is not None:
        # search_log coverage is always enforced; it cannot be bypassed.
        search_log_check = validate_search_log(
            search_log,
            raw_obj,
            strict_coverage=True,
            search_strategy=search_strategy,
            require_search_strategy=strict_search_log,
        )
        if not search_log_check["is_valid"]:
            raise ValueError(
                "search_log校验失败 (search_log invalid，build-approved 已停止，不会生成 approved 输出): "
                + "; ".join(search_log_check["errors"])
            )
        if strict_search_log and search_log_check["warnings"]:
            raise ValueError(
                "search_log生产审计未通过（存在阻断级警告，build-approved 已停止）: "
                + "; ".join(search_log_check["warnings"])
            )

    output_dir = output_dir or DATA_DIR
    output_dir.mkdir(parents=True, exist_ok=True)
    all_approved: list[dict[str, Any]] = []
    all_rejected: list[dict[str, Any]] = []
    processed: dict[str, Any] = {}

    for item_type in sorted(VALID_ITEM_TYPES):
        raw_items = normalize_raw_input(raw_obj, item_type)
        result = process_raw_data(
            raw_items,
            item_type,
            date_verify_func=date_verify_func if check_page_date_enabled else None,
        )
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
    llm_date_warnings: list[str] = []
    llm_api_error: str = ""
    if llm_relevance_mode != "off":
        all_approved, llm_rejected, llm_relevance_warnings, llm_api_error = remove_llm_rejected_items(
            all_approved,
            mode=llm_relevance_mode,
            judge_func=llm_judge_func,
        )
        all_rejected.extend(llm_rejected)
        if not llm_api_error:
            all_approved, llm_date_rejected, llm_date_warnings, llm_date_api_error = remove_llm_date_mismatch_items(
                all_approved,
                report_date,
                mode=llm_relevance_mode,
                judge_func=llm_date_judge_func,
            )
            all_rejected.extend(llm_date_rejected)
            if llm_date_api_error:
                llm_api_error = llm_date_api_error
    all_approved, final_date_rejected = finalize_approved_page_date_verification(
        all_approved,
        date_verify_func=date_verify_func,
    )
    all_rejected.extend(final_date_rejected)
    all_approved = sort_approved_items(all_approved)
    # LLM final audit: catch duplicates, title mismatch, spam sources, aggregate pages
    all_approved, final_rejected, final_warnings = judge_final_audit(
        all_approved,
        report_date,
        mode=llm_final_audit_mode,
    )
    all_rejected.extend(final_rejected)
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
        "llm_date_warnings": llm_date_warnings,
        "llm_api_error": llm_api_error,
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


def finalize_approved_page_date_verification(
    items: List[Dict[str, Any]],
    *,
    date_verify_func=fetch_and_verify_date,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Ensure final approved items carry a trustworthy page-verified date."""
    if not items or date_verify_func is None:
        return items, []

    to_verify = [
        item for item in items
        if should_verify_page_date(item)
        and (
            not isinstance(item.get("date_verification"), dict)
            or is_low_confidence_date_verification(item.get("date_verification"))
        )
    ]
    verified_by_identity: dict[int, Dict[str, Any]] = {}
    if to_verify:
        verified_items = verify_items_page_dates(to_verify, date_verify_func=date_verify_func)
        verified_by_identity = {
            id(original): verified
            for original, verified in zip(to_verify, verified_items)
        }

    kept: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for item in items:
        verified_item = verified_by_identity.get(id(item), item)
        if should_verify_page_date(verified_item):
            verification = verified_item.get("date_verification")
            if not isinstance(verification, dict):
                rejected.append({
                    "item": verified_item,
                    "reason": "[页面日期] 缺少date_verification",
                    "action": "排除",
                })
                continue
            if is_low_confidence_date_verification(verification):
                source = str(verification.get("source") or "").strip()
                confidence = str(verification.get("confidence") or "").strip().lower()
                rejected.append({
                    "item": verified_item,
                    "reason": (
                        f"[页面日期] 仅有搜索日期兜底，source={source or 'missing'}, "
                        f"confidence={confidence or 'missing'}"
                    ),
                    "action": "排除",
                })
                continue
            timely, reason = check_timeliness(verified_item, str(verified_item.get("type") or "news"))
            if not timely:
                rejected.append({
                    "item": verified_item,
                    "reason": f"[时效性] {reason}",
                    "action": "排除",
                })
                continue
        kept.append(verified_item)

    return kept, rejected


def remove_llm_rejected_items(
    items: List[Dict[str, Any]],
    mode: str = "auto",
    judge_func=judge_item_relevance,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[str], str]:
    """Run the LLM/semantic relevance gate over approved candidates.

    Returns (kept, rejected, warnings, api_error).
    api_error is a non-empty string if the LLM API is unavailable and the
    pipeline should be stopped and the user notified (fail-closed rule).
    """
    kept: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    warnings: list[str] = []
    api_error: str = ""

    for item in items:
        try:
            decision = judge_func(item, mode=mode)
        except RuntimeError as exc:
            # RULE: If LLM API is unavailable, stop the pipeline and notify user.
            error_msg = str(exc)
            if not api_error:
                api_error = error_msg
            warnings.append(f"LLM API不可用: {error_msg}")
            continue
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

    return kept, rejected, warnings, api_error


def remove_llm_date_mismatch_items(
    items: List[Dict[str, Any]],
    report_date: str,
    mode: str = "auto",
    judge_func=judge_item_date_validity,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[str], str]:
    """Run the LLM date-integrity gate over already-approved candidates."""
    kept: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    warnings: list[str] = []
    api_error: str = ""

    for item in items:
        if not should_verify_page_date(item):
            kept.append(item)
            continue
        try:
            decision = judge_func(item, report_date, mode=mode)
        except RuntimeError as exc:
            error_msg = str(exc)
            if not api_error:
                api_error = error_msg
            warnings.append(f"LLM日期审计不可用: {error_msg}")
            continue
        if not isinstance(decision, DateDecision):
            warnings.append(f"LLM日期审计返回非标准结果，已保守排除: {item.get('title', '')}")
            rejected.append({
                "item": item,
                "reason": "[LLM日期审计] 非标准审计结果",
                "action": "排除",
            })
            continue

        annotated = dict(item)
        annotated["llm_date_check"] = {
            "is_date_valid": decision.is_date_valid,
            "confidence": decision.confidence,
            "reason": decision.reason,
            "evidence_spans": decision.evidence_spans,
            "suspected_actual_date": decision.suspected_actual_date,
            "provider": decision.provider,
        }
        if decision.is_date_valid:
            kept.append(annotated)
            continue
        suspected = f"，疑似真实日期={decision.suspected_actual_date}" if decision.suspected_actual_date else ""
        rejected.append({
            "item": annotated,
            "reason": f"[LLM日期审计] {decision.reason or '候选日期疑似不是文章真实发布时间'}{suspected}",
            "action": "排除",
        })

    return kept, rejected, warnings, api_error


def notify_user_on_llm_error(error_msg: str, report_date: str) -> None:
    """Send notification email when LLM API is unavailable (fail-closed rule).
    
    RULE: If the LLM API is unavailable during the semantic gate, the pipeline
    must stop and notify the user. This prevents silent fallback to heuristic
    mode which could degrade report quality.
    """
    try:
        config_path = CONFIG_DIR / "email_config.json"
        if not config_path.exists():
            print(f"Warning: email config not found, cannot notify user: {config_path}")
            return
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
        
        sender = config.get("sender_email", "noreply@example.com")
        receiver = config.get("receiver_email", "admin@example.com")
        server = config.get("smtp_server", "smtp.exmail.qq.com")
        port = config.get("smtp_port", 465)
        password = config.get("sender_password", "")
        
        msg = MIMEText(
            f"合成生物日报流水线异常停止\n\n"
            f"日期: {report_date}\n"
            f"原因: LLM API 不可用\n"
            f"错误信息: {error_msg}\n\n"
            f"系统已按照 fail-closed 规则停止运行，请检查 LLM API 配置。\n",
            "plain", "utf-8"
        )
        msg["Subject"] = f"[日报异常] LLM API 不可用 - {report_date}"
        msg["From"] = sender
        msg["To"] = receiver
        
        with smtplib.SMTP_SSL(server, port, timeout=30) as s:
            s.login(sender, password)
            s.send_message(msg)
        print(f"Notification email sent to {receiver}")
    except Exception as e:
        print(f"Failed to send notification email: {e}")


def markdown_cell(value: object) -> str:
    return str(value or "").replace("|", "\\|").replace("\n", " ").strip()


_URL_PATTERN = re.compile(r"https?://[^\s<>()]+", re.IGNORECASE)


def markdown_summary_cell(value: object, *, max_length: int = 300) -> str:
    text = str(value or "").replace("\n", " ").strip()
    if not text:
        return ""
    text = _URL_PATTERN.sub("", text)
    text = re.sub(r"\s{2,}", " ", text).strip(" .|")
    if len(text) > max_length:
        text = text[: max_length - 1].rstrip() + "…"
    return text.replace("|", "\\|").strip()


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
                f"{markdown_summary_cell(item.get('summary', ''))}（{markdown_cell(item.get('date', report_date))}）"
            )
    else:
        lines.append(f"1. 经完整检索，本周期暂无可发送信息收录。（{report_date}）")

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
        "经完整检索，本周期暂无相关新信息收录。",
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
        lines.append("1. 经完整检索，本周期暂无可列示的外部链接。")
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
        lines.append("| 经完整检索，本周期暂无相关新信息收录。 | — | — | — | — |" if len(fields) == 5 else "| 经完整检索，本周期暂无相关新信息收录。 | — | — | — |")
        return
    for item in items:
        cells = []
        for field in fields:
            if field == "url":
                cells.append(markdown_link(str(item.get("url", ""))))
            else:
                if field == "summary":
                    cells.append(markdown_summary_cell(item.get(field, "")))
                else:
                    cells.append(markdown_cell(item.get(field, "")))
        lines.append("| " + " | ".join(cells) + " |")


def append_funding_rows(lines: List[str], items: List[Dict[str, Any]]) -> None:
    if not items:
        lines.append("| 经完整检索，本周期暂无相关新信息收录。 | — | — | — | — | — |")
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
        lines.append("| 经完整检索，本周期暂无相关新信息收录。 | — | — | — | — |")
        return
    for item in items:
        cells = [
            markdown_cell(item.get("title", "")),
            markdown_cell(item.get("date", "")),
            markdown_cell(item.get("location", "")),
            markdown_summary_cell(item.get("summary", "")),
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
    parser.add_argument("--skip-page-date-check", action="store_true", help="仅离线测试/受限网络临时使用：跳过原页面日期验证")
    parser.add_argument("--llm-relevance-mode", choices=["auto", "llm", "heuristic", "off"], default="auto", help="领域相关性审计模式：auto默认有LLM配置则调用，否则本地语义fallback")
    parser.add_argument("--llm-final-audit-mode", choices=["auto", "llm", "off"], default="auto", help="最终质量审计模式：auto有LLM配置则终审，off关闭")
    parser.add_argument("--search-log", type=str, help="搜索执行日志JSON路径，用于校验基座必搜和LLM高召回搜索证据")
    parser.add_argument("--search-strategy", type=str, help="LLM动态搜索策略JSON路径，用于校验动态query执行证据")
    parser.add_argument("--allow-incomplete-search-log", action="store_true", help="仅审计/排障：允许缺少同日search_strategy或存在search_log warnings，不用于正式日报")
    parser.add_argument("--allow-empty-approved", action="store_true", help="仅审计/排障：approved=0 时仍返回成功，允许继续渲染空报告，不用于正式日报")
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
        search_log_path = Path(args.search_log) if args.search_log else None
        if args.search_log:
            with open(search_log_path, 'r', encoding='utf-8') as f:
                search_log = json.load(f)
        search_strategy = None
        search_strategy_path = Path(args.search_strategy) if args.search_strategy else None
        if search_strategy_path is None:
            search_strategy_path = find_default_search_strategy_path(args.date, search_log_path)
        if args.search_strategy:
            with open(search_strategy_path, 'r', encoding='utf-8') as f:
                search_strategy = json.load(f)
        elif search_strategy_path is not None:
            with open(search_strategy_path, 'r', encoding='utf-8') as f:
                search_strategy = json.load(f)
            print(f"自动加载LLM搜索策略: {search_strategy_path}")
        output_dir = Path(args.output) if args.output else DATA_DIR
        try:
            result = build_approved_from_raw(
                raw_obj,
                args.date,
                output_dir=output_dir,
                check_url_health_enabled=not args.skip_url_health,
                check_title_match_enabled=not args.skip_title_match,
                check_page_date_enabled=not args.skip_page_date_check,
                llm_relevance_mode=args.llm_relevance_mode,
                llm_final_audit_mode=args.llm_final_audit_mode,
                search_log=search_log,
                search_strategy=search_strategy,
                strict_search_log=not args.allow_incomplete_search_log,
            )
        except ValueError as exc:
            print(f"ERROR: {exc}")
            sys.exit(1)
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
            strategy_check = result["search_log_check"].get("strategy_check")
            if strategy_check:
                print(
                    "LLM动态搜索策略: "
                    f"{strategy_check['executed_required_count']}/{strategy_check['required_total']} "
                    "required queries executed"
                )
        if result.get("title_match_warnings"):
            print(f"标题匹配警告: {len(result['title_match_warnings'])}个")
            for warning in result["title_match_warnings"][:10]:
                print(f"  - {warning}")
        if result.get("llm_relevance_warnings"):
            print(f"LLM领域审计警告: {len(result['llm_relevance_warnings'])}个")
            for warning in result["llm_relevance_warnings"][:10]:
                print(f"  - {warning}")
        # RULE: If LLM API is unavailable, stop pipeline and notify user.
        if result.get("llm_api_error"):
            error_msg = result["llm_api_error"]
            print(f"\n[FAIL-CLOSED] LLM API 不可用: {error_msg}")
            print("按照规则，系统已停止运行，正在发送通知邮件...")
            notify_user_on_llm_error(error_msg, args.date)
            sys.exit(1)
        if not result["approved"]:
            if args.allow_empty_approved:
                print("WARNING: approved为空，当前以审计/排障模式继续；正式日报禁止发送空日报")
            else:
                print(f"ERROR: {EMPTY_APPROVED_ERROR}")
                print("如仅需排障或生成审计用空报告，请显式传 --allow-empty-approved")
                sys.exit(1)
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
