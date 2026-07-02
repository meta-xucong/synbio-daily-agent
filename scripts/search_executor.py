#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Execute configured search queries and write an auditable search_log.

The executor is deliberately fail-closed: if no configured provider is
available, or if any query fails, it exits nonzero and does not pretend the
query was executed. Downstream gates can then trust `executed: true`.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import re
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

try:
    import winreg
except ImportError:  # pragma: no cover - non-Windows
    winreg = None

try:
    from .console_utils import ensure_utf8_console
    from .settings import CONFIG_DIR, DATA_DIR
    from .llm_judge import LLMClient
    from .llm_search_strategy import _llm_client_supports_thinking_disable
except ImportError:
    from console_utils import ensure_utf8_console
    from settings import CONFIG_DIR, DATA_DIR
    from llm_judge import LLMClient
    from llm_search_strategy import _llm_client_supports_thinking_disable


ensure_utf8_console()

DEFAULT_SEARCH_CONFIG = CONFIG_DIR / "search_queries.json"
DEFAULT_STRATEGY_CONFIG = CONFIG_DIR / "llm_search_strategy.json"
DEFAULT_LIMIT = 15
DEFAULT_TIMEOUT_SECONDS = 30
DEFAULT_RETRIES = 2
DEFAULT_MAX_WORKERS = 5
DEFAULT_TAVILY_DEVELOPMENT_RPM = 90
HIGH_RECALL_ROUND_IDS = ("llm_discovery", "llm_gap_audit")
VALID_HIGH_RECALL_EVIDENCE_MODES = {"strict", "compatible"}
DEFAULT_HIGH_RECALL_EVIDENCE_MODE = "compatible"
DEFAULT_LLM_DISCOVERY_QUERIES = [
    "近48小时 合成生物 生物制造 政府 高校 科协 地方媒体 发布",
    "近48小时 合成生物 生物制造 垂直媒体 融资 政策 活动 科研",
    "recent synthetic biology biomanufacturing news funding policy research events",
]
DEFAULT_LLM_GAP_AUDIT_QUERIES = [
    "未来健康产业大会 合成生物学创新产业峰会 2026",
    "中国创新创业大赛 合成生物 生物制造 专业赛 2026",
    "核酸合成生物学 中欧生命科学 国际论坛 2026",
    "生物制造中试平台 璧山 华东理工",
]
PROVIDER_ENV_KEYS = {
    "serper": "SERPER_API_KEY",
    "brave": "BRAVE_SEARCH_API_KEY",
    "bing": "BING_SEARCH_API_KEY",
    "tavily": "TAVILY_API_KEY",
    "llm_web": "ANTHROPIC_AUTH_TOKEN",
}
FAST_SEARCH_PROVIDERS = ("serper", "brave", "bing", "tavily")
AUTO_SEARCH_PROVIDERS = FAST_SEARCH_PROVIDERS


class SearchProviderError(RuntimeError):
    """Raised when a provider cannot complete a query."""


class NoSearchProviderConfigured(RuntimeError):
    """Raised when production search would otherwise be silently skipped."""


class QueryRateLimiter:
    """Simple start-rate limiter for provider requests."""

    def __init__(self, rpm: int | None = None):
        self.rpm = _positive_int(rpm, 0) if rpm is not None else 0
        self._interval = 60.0 / self.rpm if self.rpm > 0 else 0.0
        self._lock = threading.Lock()
        self._next_allowed_at = 0.0

    def acquire(self) -> None:
        if self._interval <= 0:
            return
        while True:
            with self._lock:
                now = time.monotonic()
                if now >= self._next_allowed_at:
                    self._next_allowed_at = now + self._interval
                    return
                sleep_for = self._next_allowed_at - now
            time.sleep(sleep_for)


def _read_json(path: Path) -> Any:
    with open(path, "r", encoding="utf-8-sig") as f:
        return json.load(f)


def _read_json_if_exists(path: Path | None) -> Any:
    if path is None or not path.exists():
        return {}
    return _read_json(path)


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _normalize_query(query: Any) -> str:
    return " ".join(str(query or "").split()).strip()


def _unique_queries(values: list[Any]) -> list[str]:
    queries: list[str] = []
    seen: set[str] = set()
    for value in values:
        if isinstance(value, dict):
            query = _normalize_query(value.get("query") or value.get("q"))
        else:
            query = _normalize_query(value)
        if not query or query in seen:
            continue
        seen.add(query)
        queries.append(query)
    return queries


def _positive_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _http_json(
    request: Request,
    *,
    opener: Callable[..., Any] = urlopen,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
    retries: int = DEFAULT_RETRIES,
) -> dict[str, Any]:
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            with opener(request, timeout=timeout) as response:
                body = response.read().decode("utf-8", errors="replace")
            parsed = json.loads(body)
            if not isinstance(parsed, dict):
                raise SearchProviderError("provider returned non-object JSON")
            return parsed
        except Exception as exc:
            last_error = exc
            retry_after = None
            if getattr(exc, "code", None) == 429:
                headers = getattr(exc, "headers", None)
                if headers is not None:
                    retry_after = headers.get("retry-after") or headers.get("Retry-After")
            if attempt >= retries:
                break
            if retry_after is not None:
                try:
                    time.sleep(max(0.0, float(retry_after)))
                    continue
                except (TypeError, ValueError):
                    pass
            time.sleep(min(2, attempt))
    raise SearchProviderError(str(last_error or "provider request failed"))


def _parse_api_keys(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value or "").strip()
    if not text:
        return []
    if text.startswith("["):
        try:
            parsed = json.loads(text)
        except Exception:
            parsed = None
        if isinstance(parsed, list):
            return [str(item).strip() for item in parsed if str(item).strip()]
    return [part.strip() for part in re.split(r"[\r\n,;]+", text) if part.strip()]


def _configured_api_keys(provider: str) -> list[str]:
    normalized = str(provider or "").strip().lower()
    if normalized == "tavily":
        merged: list[str] = []
        for value in (
            os.getenv("TAVILY_API_KEY"),
            _read_windows_env_var("TAVILY_API_KEY"),
            os.getenv("TAVILY_API_KEYS"),
        ):
            for key in _parse_api_keys(value):
                if key not in merged:
                    merged.append(key)
        if merged:
            return merged
    env_key = PROVIDER_ENV_KEYS.get(normalized)
    if not env_key:
        return []
    return _parse_api_keys(os.getenv(env_key))


def _read_windows_env_var(name: str) -> str | None:
    if os.getenv("SYNBIO_SKIP_DOTENV") in {"1", "true", "TRUE", "yes", "YES"}:
        return None
    if winreg is None or os.name != "nt":
        return None
    locations = [
        (winreg.HKEY_CURRENT_USER, r"Environment"),
        (winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"),
    ]
    for hive, subkey in locations:
        try:
            with winreg.OpenKey(hive, subkey) as key:
                value, _ = winreg.QueryValueEx(key, name)
        except OSError:
            continue
        text = str(value or "").strip()
        if text:
            return text
    return None


def _should_failover_key(error: str) -> bool:
    message = str(error or "").lower()
    if not message:
        return False
    if any(
        token in message
        for token in (
            "http error 401",
            "http error 403",
            "http error 429",
            "http error 500",
            "http error 502",
            "http error 503",
            "http error 504",
        )
    ):
        return True
    return any(
        token in message
        for token in (
            "rate limit",
            "too many requests",
            "quota",
            "credit",
            "credits",
            "exhaust",
            "unauthorized",
            "forbidden",
        )
    )


def configured_high_recall_evidence_mode() -> str:
    mode = str(os.getenv("SYNBIO_HIGH_RECALL_EVIDENCE_MODE") or "").strip().lower()
    if mode in VALID_HIGH_RECALL_EVIDENCE_MODES:
        return mode
    return DEFAULT_HIGH_RECALL_EVIDENCE_MODE


def default_llm_discovery_provider() -> str:
    configured = str(os.getenv("SYNBIO_LLM_DISCOVERY_PROVIDER") or "").strip().lower()
    if configured in {"llm_web", "fixture", "same"}:
        return configured
    return "same" if configured_high_recall_evidence_mode() == "compatible" else "llm_web"


def _domain(url: str) -> str:
    return urlsplit(url or "").netloc


def _coerce_result(
    item: dict[str, Any],
    *,
    query: str,
    provider: str,
    rank: int,
) -> dict[str, Any] | None:
    title = str(item.get("title") or item.get("name") or item.get("headline") or "").strip()
    url = str(item.get("url") or item.get("link") or item.get("href") or "").strip()
    if not title or not url:
        return None
    summary = str(
        item.get("summary")
        or item.get("snippet")
        or item.get("description")
        or item.get("content")
        or item.get("text")
        or title
    ).strip()
    source = str(
        item.get("source")
        or item.get("site")
        or item.get("publisher")
        or item.get("source_name")
        or _domain(url)
        or provider
    ).strip()
    date = str(
        item.get("date")
        or item.get("published_at")
        or item.get("published")
        or item.get("published_time")
        or item.get("age")
        or item.get("dateLastCrawled")
        or ""
    ).strip()
    return {
        "title": title,
        "url": url,
        "snippet": summary,
        "source": source,
        "date": date,
        "source_query": query,
        "search_provider": provider,
        "rank": rank,
    }


class FixtureSearchProvider:
    name = "fixture"

    def __init__(self, fixture_path: Path):
        data = _read_json(fixture_path)
        if isinstance(data, dict) and isinstance(data.get("queries"), dict):
            self.by_query = data["queries"]
        elif isinstance(data, dict):
            self.by_query = data
        elif isinstance(data, list):
            self.by_query = {
                str(entry.get("query") or ""): entry.get("results") or []
                for entry in data
                if isinstance(entry, dict)
            }
        else:
            raise ValueError("fixture must be a dict or list")

    def search(self, query: str, *, limit: int) -> list[dict[str, Any]]:
        results = self.by_query.get(query, [])
        if not isinstance(results, list):
            raise SearchProviderError(f"fixture results for query are not a list: {query}")
        normalized: list[dict[str, Any]] = []
        for rank, item in enumerate(results[:limit], 1):
            if not isinstance(item, dict):
                continue
            result = _coerce_result(item, query=query, provider=self.name, rank=rank)
            if result:
                normalized.append(result)
        return normalized


class SerperSearchProvider:
    name = "serper"

    def __init__(self, api_key: str, *, opener: Callable[..., Any] = urlopen, timeout: int = DEFAULT_TIMEOUT_SECONDS, retries: int = DEFAULT_RETRIES):
        self.api_key = api_key
        self.opener = opener
        self.timeout = timeout
        self.retries = retries

    def search(self, query: str, *, limit: int) -> list[dict[str, Any]]:
        payload = {"q": query, "num": limit, "gl": os.getenv("SERPER_GL", "cn"), "hl": os.getenv("SERPER_HL", "zh-cn")}
        request = Request(
            "https://google.serper.dev/search",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json", "X-API-KEY": self.api_key},
            method="POST",
        )
        data = _http_json(request, opener=self.opener, timeout=self.timeout, retries=self.retries)
        items = []
        for key in ("organic", "news"):
            values = data.get(key) or []
            if isinstance(values, list):
                items.extend(values)
        return _normalize_provider_results(items, query=query, provider=self.name, limit=limit)


class BraveSearchProvider:
    name = "brave"

    def __init__(self, api_key: str, *, opener: Callable[..., Any] = urlopen, timeout: int = DEFAULT_TIMEOUT_SECONDS, retries: int = DEFAULT_RETRIES):
        self.api_key = api_key
        self.opener = opener
        self.timeout = timeout
        self.retries = retries

    def search(self, query: str, *, limit: int) -> list[dict[str, Any]]:
        params = urlencode({"q": query, "count": min(limit, 20), "country": os.getenv("BRAVE_SEARCH_COUNTRY", "CN")})
        request = Request(
            f"https://api.search.brave.com/res/v1/web/search?{params}",
            headers={"Accept": "application/json", "X-Subscription-Token": self.api_key},
            method="GET",
        )
        data = _http_json(request, opener=self.opener, timeout=self.timeout, retries=self.retries)
        web = data.get("web") if isinstance(data.get("web"), dict) else {}
        items = web.get("results") if isinstance(web, dict) else []
        return _normalize_provider_results(items or [], query=query, provider=self.name, limit=limit)


class BingSearchProvider:
    name = "bing"

    def __init__(self, api_key: str, *, opener: Callable[..., Any] = urlopen, timeout: int = DEFAULT_TIMEOUT_SECONDS, retries: int = DEFAULT_RETRIES):
        self.api_key = api_key
        self.opener = opener
        self.timeout = timeout
        self.retries = retries

    def search(self, query: str, *, limit: int) -> list[dict[str, Any]]:
        params = urlencode({"q": query, "count": min(limit, 50), "mkt": os.getenv("BING_SEARCH_MKT", "zh-CN")})
        request = Request(
            f"https://api.bing.microsoft.com/v7.0/search?{params}",
            headers={"Accept": "application/json", "Ocp-Apim-Subscription-Key": self.api_key},
            method="GET",
        )
        data = _http_json(request, opener=self.opener, timeout=self.timeout, retries=self.retries)
        items = []
        web_pages = data.get("webPages") if isinstance(data.get("webPages"), dict) else {}
        if isinstance(web_pages.get("value"), list):
            items.extend(web_pages["value"])
        news = data.get("news") if isinstance(data.get("news"), dict) else {}
        if isinstance(news.get("value"), list):
            items.extend(news["value"])
        return _normalize_provider_results(items, query=query, provider=self.name, limit=limit)


class TavilySearchProvider:
    name = "tavily"

    def __init__(self, api_key: str | list[str], *, opener: Callable[..., Any] = urlopen, timeout: int = DEFAULT_TIMEOUT_SECONDS, retries: int = DEFAULT_RETRIES):
        self.api_keys = _parse_api_keys(api_key)
        if not self.api_keys:
            raise NoSearchProviderConfigured("tavily provider requires at least one API key")
        self.opener = opener
        self.timeout = timeout
        self.retries = retries
        self._lock = threading.Lock()
        self._active_index = 0

    def _ordered_keys(self) -> list[str]:
        with self._lock:
            start = self._active_index
        return self.api_keys[start:] + self.api_keys[:start]

    def _promote_key(self, api_key: str) -> None:
        with self._lock:
            try:
                self._active_index = self.api_keys.index(api_key)
            except ValueError:
                return

    def _search_with_key(self, api_key: str, query: str, *, limit: int) -> list[dict[str, Any]]:
        key_suffix = api_key[-6:] if len(api_key) >= 6 else api_key
        payload = {
            "api_key": api_key,
            "query": query,
            "max_results": limit,
            "search_depth": os.getenv("TAVILY_SEARCH_DEPTH", "basic"),
            "include_answer": False,
        }
        request = Request(
            "https://api.tavily.com/search",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            data = _http_json(request, opener=self.opener, timeout=self.timeout, retries=self.retries)
        except SearchProviderError as exc:
            raise SearchProviderError(f"{exc} [tavily_key_suffix={key_suffix}]") from exc
        items = data.get("results") or []
        return _normalize_provider_results(items, query=query, provider=self.name, limit=limit)

    def search(self, query: str, *, limit: int) -> list[dict[str, Any]]:
        last_error: Exception | None = None
        ordered_keys = self._ordered_keys()
        for index, api_key in enumerate(ordered_keys):
            try:
                results = self._search_with_key(api_key, query, limit=limit)
                if index > 0:
                    self._promote_key(api_key)
                return results
            except SearchProviderError as exc:
                last_error = exc
                if index >= len(ordered_keys) - 1 or not _should_failover_key(str(exc)):
                    break
        raise last_error or SearchProviderError("tavily provider request failed")


class LLMWebSearchProvider:
    """Use Anthropic-compatible server-side web_search as a search provider."""

    name = "llm_web"

    def __init__(self, client: LLMClient | None = None, *, opener: Callable[..., Any] = urlopen, timeout: int = 90, retries: int = DEFAULT_RETRIES):
        self.client = client or LLMClient(timeout=timeout, opener=opener)
        self.timeout = timeout
        self.retries = retries
        if not self.client.is_configured:
            raise NoSearchProviderConfigured("llm_web provider requires ANTHROPIC_BASE_URL and ANTHROPIC_AUTH_TOKEN")

    def search(self, query: str, *, limit: int) -> list[dict[str, Any]]:
        last_error: Exception | None = None
        for attempt in range(1, self.retries + 1):
            try:
                return self._search_once(query, limit=limit, force_tool=attempt > 1)
            except SearchProviderError as exc:
                last_error = exc
                if attempt >= self.retries:
                    break
                time.sleep(min(2, attempt))
        raise last_error or SearchProviderError("llm_web search failed")

    def _search_once(self, query: str, *, limit: int, force_tool: bool = False) -> list[dict[str, Any]]:
        instruction = (
            "MANDATORY: call the web_search tool now. Do not answer from memory. "
            "Use the exact search query between <query> tags."
            if force_tool else
            "Use the web_search tool exactly once for the following search query. "
            "Do not invent URLs. After the tool result, summarize only the returned titles and URLs."
        )
        payload = {
            "model": self.client.model,
            "max_tokens": _positive_int(os.getenv("ANTHROPIC_WEB_SEARCH_MAX_TOKENS"), 2048),
            "temperature": 0,
            "messages": [{
                "role": "user",
                "content": (
                    f"{instruction}\n"
                    f"<query>{query}</query>"
                ),
            }],
            "tools": [{
                "type": "web_search_20250305",
                "name": "web_search",
                "max_uses": 1,
            }],
            "tool_choice": {
                "type": "tool",
                "name": "web_search",
            },
        }
        if _llm_client_supports_thinking_disable(self.client):
            payload["thinking"] = {"type": "disabled"}
        request = Request(
            self.client.messages_url,
            data=json.dumps(payload, ensure_ascii=True).encode("utf-8"),
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "x-api-key": self.client.auth_token or "",
                "Authorization": f"Bearer {self.client.auth_token or ''}",
                "anthropic-version": "2023-06-01",
            },
            method="POST",
        )
        data = _http_json(request, opener=self.client.opener, timeout=self.timeout, retries=1)
        content = data.get("content") or []
        if not isinstance(content, list):
            raise SearchProviderError("llm_web response content is not a list")

        tool_query = ""
        raw_results: list[dict[str, Any]] = []
        saw_tool_result = False
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "server_tool_use" and block.get("name") == "web_search":
                tool_input = block.get("input") if isinstance(block.get("input"), dict) else {}
                tool_query = str(tool_input.get("query") or "")
            if block.get("type") == "web_search_tool_result":
                saw_tool_result = True
                result_content = block.get("content") or []
                if not isinstance(result_content, list):
                    continue
                for item in result_content:
                    if not isinstance(item, dict) or item.get("type") != "web_search_result":
                        continue
                    raw_results.append({
                        "title": item.get("title") or item.get("url"),
                        "url": item.get("url"),
                        "snippet": item.get("page_age") or "",
                        "source": _domain(str(item.get("url") or "")) or "web_search",
                        "date": item.get("page_age") or "",
                        "tool_query": tool_query,
                    })
        if not saw_tool_result:
            raise SearchProviderError("llm_web response did not include web_search_tool_result")
        return _normalize_provider_results(raw_results, query=query, provider=self.name, limit=limit)


def _normalize_provider_results(items: Any, *, query: str, provider: str, limit: int) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    if not isinstance(items, list):
        return normalized
    for rank, item in enumerate(items, 1):
        if not isinstance(item, dict):
            continue
        result = _coerce_result(item, query=query, provider=provider, rank=rank)
        if result:
            normalized.append(result)
        if len(normalized) >= limit:
            break
    return normalized


def _configured_high_recall_queries(config: dict[str, Any], key: str, defaults: list[str]) -> list[str]:
    values = config.get(key) if isinstance(config, dict) else None
    if isinstance(values, list):
        queries = _unique_queries(values)
        if queries:
            return queries
    return list(defaults)


def make_provider(
    name: str = "auto",
    *,
    fixture: Path | None = None,
    opener: Callable[..., Any] = urlopen,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
    retries: int = DEFAULT_RETRIES,
    allow_llm_web_auto: bool = False,
) -> Any:
    selected = (name or "auto").strip().lower()
    if fixture is not None or selected == "fixture":
        if fixture is None:
            fixture_env = os.getenv("SYNBIO_SEARCH_FIXTURE")
            if fixture_env:
                fixture = Path(fixture_env)
        if fixture is None:
            raise NoSearchProviderConfigured("fixture provider requires --fixture or SYNBIO_SEARCH_FIXTURE")
        return FixtureSearchProvider(fixture)

    if selected == "llm_web" and not allow_llm_web_auto:
        raise NoSearchProviderConfigured(
            "llm_web cannot be used for base required queries in production; "
            "configure a fast search provider or pass --allow-llm-web-base for diagnostics only"
        )

    candidates = (
        [*AUTO_SEARCH_PROVIDERS, "llm_web"]
        if selected == "auto" and allow_llm_web_auto
        else list(AUTO_SEARCH_PROVIDERS)
        if selected == "auto"
        else [selected]
    )
    for candidate in candidates:
        env_key = PROVIDER_ENV_KEYS.get(candidate)
        if not env_key:
            raise NoSearchProviderConfigured(f"unknown search provider: {candidate}")
        if candidate == "llm_web":
            llm_client = LLMClient(timeout=timeout, opener=opener)
            if not llm_client.is_configured:
                continue
            return LLMWebSearchProvider(llm_client, opener=opener, timeout=timeout, retries=retries)
        api_keys = _configured_api_keys(candidate)
        if not api_keys:
            continue
        if candidate == "serper":
            return SerperSearchProvider(api_keys[0], opener=opener, timeout=timeout, retries=retries)
        if candidate == "brave":
            return BraveSearchProvider(api_keys[0], opener=opener, timeout=timeout, retries=retries)
        if candidate == "bing":
            return BingSearchProvider(api_keys[0], opener=opener, timeout=timeout, retries=retries)
        if candidate == "tavily":
            return TavilySearchProvider(api_keys, opener=opener, timeout=timeout, retries=retries)

    if selected == "auto" and not allow_llm_web_auto:
        expected = ", ".join(
            f"{provider}:{PROVIDER_ENV_KEYS[provider]}" for provider in AUTO_SEARCH_PROVIDERS
        )
        raise NoSearchProviderConfigured(
            "no configured fast search provider for base required queries; "
            f"set one API key ({expected}). "
            "Kimi/llm_web is reserved for llm_discovery and llm_gap_audit unless "
            "--allow-llm-web-base is used for diagnostics."
        )
    expected = ", ".join(f"{provider}:{env}" for provider, env in PROVIDER_ENV_KEYS.items())
    raise NoSearchProviderConfigured(f"no configured search provider; set one API key ({expected})")


def load_search_plan(search_config: Path, strategy_path: Path | None = None) -> list[dict[str, Any]]:
    return load_high_recall_search_plan(search_config, strategy_path)


def load_high_recall_search_plan(
    search_config: Path,
    strategy_path: Path | None = None,
    *,
    strategy_config_path: Path | None = DEFAULT_STRATEGY_CONFIG,
    include_high_recall: bool = True,
) -> list[dict[str, Any]]:
    config = _read_json(search_config)
    rounds: list[dict[str, Any]] = []
    base_queries_seen: set[str] = set()
    for round_cfg in config.get("rounds", []) if isinstance(config, dict) else []:
        if not isinstance(round_cfg, dict):
            continue
        round_id = str(round_cfg.get("round_id") or round_cfg.get("round") or round_cfg.get("id") or "").strip()
        queries = _unique_queries(round_cfg.get("required_queries", []) or [])
        if round_id and queries:
            rounds.append({"round": round_id, "theme": round_cfg.get("theme", ""), "queries": queries})
            base_queries_seen.update(queries)

    if strategy_path is not None:
        strategy = _read_json(strategy_path)
        if not isinstance(strategy, dict):
            raise ValueError("search strategy must be an object")
        round_id = str(strategy.get("strategy_round_id") or "llm_dynamic").strip() or "llm_dynamic"
        queries = [
            query
            for query in _unique_queries(strategy.get("queries", []) or [])
            if query not in base_queries_seen
        ]
        if queries:
            rounds.append({"round": round_id, "theme": "LLM dynamic search", "queries": queries})

    if include_high_recall:
        strategy_config = _read_json_if_exists(strategy_config_path)
        discovery_queries = _configured_high_recall_queries(
            strategy_config,
            "llm_discovery_queries",
            DEFAULT_LLM_DISCOVERY_QUERIES,
        )
        gap_audit_queries = _configured_high_recall_queries(
            strategy_config,
            "llm_gap_audit_queries",
            DEFAULT_LLM_GAP_AUDIT_QUERIES,
        )
        rounds.append({
            "round": "llm_discovery",
            "theme": "LLM broad discovery across recent synbio sources",
            "queries": discovery_queries,
            "requires_llm_web": True,
        })
        rounds.append({
            "round": "llm_gap_audit",
            "theme": "LLM gap audit for source and topic blindspots",
            "queries": gap_audit_queries,
            "requires_llm_web": True,
        })
    return rounds


def execute_search_plan(
    rounds: list[dict[str, Any]],
    provider: Any,
    *,
    date: str,
    limit: int = DEFAULT_LIMIT,
    allow_query_failures: bool = False,
    llm_provider: Any | None = None,
    max_workers: int = DEFAULT_MAX_WORKERS,
    rpm: int | None = None,
) -> tuple[dict[str, Any], bool]:
    worker_count = _positive_int(max_workers, DEFAULT_MAX_WORKERS)
    base_rate_limiter = QueryRateLimiter(rpm)
    failed = False
    log_rounds: list[dict[str, Any]] = []
    for round_cfg in rounds:
        round_id = str(round_cfg.get("round") or "").strip()
        round_provider = llm_provider if round_cfg.get("requires_llm_web") and llm_provider is not None else provider
        round_queries = [
            _normalize_query(query)
            for query in round_cfg.get("queries", []) or []
        ]
        round_queries = [query_text for query_text in round_queries if query_text]
        query_entries: list[dict[str, Any]] = [{} for _ in round_queries]
        round_rate_limiter = base_rate_limiter if round_provider is provider else QueryRateLimiter(None)

        def run_query(query_text: str) -> dict[str, Any]:
            round_rate_limiter.acquire()
            entry = {
                "query": query_text,
                "executed": False,
                "provider": round_provider.name,
                "searched_at": _now_iso(),
                "results": [],
                "result_count": 0,
            }
            try:
                results = round_provider.search(query_text, limit=limit)
                entry["executed"] = True
                entry["results"] = results
                entry["result_count"] = len(results)
                if round_provider.name == "llm_web":
                    entry["web_search_tool_result"] = True
            except Exception as exc:
                entry["error"] = str(exc)[:500]
            return entry

        if round_provider is provider and worker_count > 1 and len(round_queries) > 1:
            with concurrent.futures.ThreadPoolExecutor(max_workers=min(worker_count, len(round_queries))) as executor:
                future_map = {
                    executor.submit(run_query, query_text): index
                    for index, query_text in enumerate(round_queries)
                }
                for future in concurrent.futures.as_completed(future_map):
                    index = future_map[future]
                    entry = future.result()
                    if entry.get("executed") is not True:
                        failed = True
                    query_entries[index] = entry
        else:
            for index, query_text in enumerate(round_queries):
                entry = run_query(query_text)
                if entry.get("executed") is not True:
                    failed = True
                query_entries[index] = entry

        log_rounds.append({
            "round": round_id,
            "theme": round_cfg.get("theme", ""),
            "queries": query_entries,
        })
    search_log = {
        "version": 1,
        "date": date,
        "generated_at": _now_iso(),
        "generated_by": "search_executor",
        "provider": provider.name,
        "llm_discovery_provider": llm_provider.name if llm_provider is not None else None,
        "high_recall_enabled": any(round_entry.get("round") in HIGH_RECALL_ROUND_IDS for round_entry in rounds),
        "required_high_recall_rounds": list(HIGH_RECALL_ROUND_IDS),
        "high_recall_evidence_mode": configured_high_recall_evidence_mode(),
        "limit": limit,
        "rounds": log_rounds,
    }
    diagnostics: list[str] = []
    if llm_provider is not None and llm_provider.name == "llm_web":
        high_recall_errors = [
            str(query_entry.get("error") or "")
            for round_entry in log_rounds
            if round_entry.get("round") in HIGH_RECALL_ROUND_IDS
            for query_entry in round_entry.get("queries", [])
            if isinstance(query_entry, dict) and query_entry.get("executed") is not True
        ]
        if high_recall_errors and all("400" in error or "web_search_tool_result" in error for error in high_recall_errors):
            diagnostics.append(
                "llm_web high-recall rounds failed consistently; the configured Anthropic-compatible gateway may not support "
                "server-side web_search_tool_result for this request shape. Verify gateway compatibility before production sends."
            )
    if diagnostics:
        search_log["diagnostics"] = diagnostics
    return search_log, (not failed or allow_query_failures)


def default_strategy_path(date: str) -> Path:
    return DATA_DIR / f"search_strategy_{date}.json"


def default_rpm_for_provider(provider_name: str) -> int | None:
    normalized = str(provider_name or "").strip().lower()
    if normalized == "tavily":
        return DEFAULT_TAVILY_DEVELOPMENT_RPM
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Execute base + LLM dynamic search queries into search_log JSON")
    parser.add_argument("--date", required=True, help="Report date YYYY-MM-DD")
    parser.add_argument("--output", required=True, type=Path, help="Output search_log JSON path")
    parser.add_argument("--search-config", type=Path, default=DEFAULT_SEARCH_CONFIG)
    parser.add_argument("--strategy-config", type=Path, default=DEFAULT_STRATEGY_CONFIG, help="LLM strategy seed config with high-recall discovery/gap queries")
    parser.add_argument("--strategy", type=Path, help="Same-day search_strategy JSON path")
    parser.add_argument("--allow-missing-strategy", action="store_true", help="Only for diagnostics; production should not use this")
    parser.add_argument("--provider", default=os.getenv("SYNBIO_SEARCH_PROVIDER", "auto"), choices=["auto", "fixture", "serper", "brave", "bing", "tavily", "llm_web"])
    parser.add_argument("--llm-discovery-provider", default=default_llm_discovery_provider(), choices=["llm_web", "fixture", "same"], help="Provider for llm_discovery and llm_gap_audit rounds; compatible mode defaults to same/base provider")
    parser.add_argument("--fixture", type=Path, help="Offline fixture mapping queries to results")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--retries", type=int, default=DEFAULT_RETRIES)
    parser.add_argument("--max-workers", type=int, default=DEFAULT_MAX_WORKERS, help="Bounded query concurrency for base provider rounds")
    parser.add_argument("--rpm", type=int, help="Optional request-per-minute cap for the base provider; Tavily defaults to a conservative free-plan-safe value")
    parser.add_argument("--allow-query-failures", action="store_true", help="Write failed queries but exit 0; not for production sends")
    parser.add_argument("--disable-high-recall", action="store_true", help="Diagnostics only: do not append llm_discovery/llm_gap_audit rounds")
    parser.add_argument(
        "--allow-llm-web-base",
        action="store_true",
        help="Diagnostics only: allow provider=auto to use slow llm_web for base required queries",
    )
    args = parser.parse_args(argv)

    strategy_path = args.strategy or default_strategy_path(args.date)
    if not strategy_path.exists():
        if args.allow_missing_strategy:
            strategy_path = None
        else:
            print(f"ERROR: missing same-day search strategy: {strategy_path}", file=sys.stderr)
            return 2

    try:
        provider = make_provider(
            args.provider,
            fixture=args.fixture,
            timeout=_positive_int(args.timeout, DEFAULT_TIMEOUT_SECONDS),
            retries=_positive_int(args.retries, DEFAULT_RETRIES),
            allow_llm_web_auto=args.allow_llm_web_base,
        )
        if args.disable_high_recall:
            llm_provider = None
        elif args.llm_discovery_provider == "same":
            llm_provider = provider
        else:
            llm_provider = make_provider(
                args.llm_discovery_provider,
                fixture=args.fixture,
                timeout=max(_positive_int(args.timeout, DEFAULT_TIMEOUT_SECONDS), 90),
                retries=_positive_int(args.retries, DEFAULT_RETRIES),
                allow_llm_web_auto=True,
            )
        rounds = load_high_recall_search_plan(
            args.search_config,
            strategy_path,
            strategy_config_path=args.strategy_config,
            include_high_recall=not args.disable_high_recall,
        )
        if not rounds:
            print("ERROR: no search queries loaded from config/strategy", file=sys.stderr)
            return 2
        search_log, ok = execute_search_plan(
            rounds,
            provider,
            date=args.date,
            limit=_positive_int(args.limit, DEFAULT_LIMIT),
            allow_query_failures=args.allow_query_failures,
            llm_provider=llm_provider,
            max_workers=_positive_int(args.max_workers, DEFAULT_MAX_WORKERS),
            rpm=args.rpm if args.rpm is not None else default_rpm_for_provider(provider.name),
        )
        _write_json(args.output, search_log)
    except NoSearchProviderConfigured as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"ERROR: search execution failed: {exc}", file=sys.stderr)
        return 1

    executed = sum(
        1
        for round_entry in search_log["rounds"]
        for query_entry in round_entry.get("queries", [])
        if query_entry.get("executed") is True
    )
    total = sum(len(round_entry.get("queries", [])) for round_entry in search_log["rounds"])
    print(f"search_log saved: {args.output} ({executed}/{total} queries executed, provider={provider.name})")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
