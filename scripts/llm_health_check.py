#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Live health check for the daily report LLM integration.

This script intentionally tests the same two LLM paths used in production:
semantic relevance judging and dynamic search-strategy generation.  It does
not print secrets.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    from .llm_judge import LLMClient
    from .llm_search_strategy import generate_search_strategy, load_strategy_config
except ImportError:
    from llm_judge import LLMClient
    from llm_search_strategy import generate_search_strategy, load_strategy_config


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = ROOT / "config" / "llm_search_strategy.json"


def _run_check(name: str, func) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        payload = func()
        return {
            "name": name,
            "ok": True,
            "elapsed_seconds": round(time.perf_counter() - started, 2),
            **payload,
        }
    except Exception as exc:
        return {
            "name": name,
            "ok": False,
            "elapsed_seconds": round(time.perf_counter() - started, 2),
            "error_type": type(exc).__name__,
            "error": str(exc),
        }


def _check_relevance(client: LLMClient) -> dict[str, Any]:
    sample = {
        "title": "蓝晶微生物推进PHA生物基材料细胞工厂产业化",
        "summary": "公司围绕工程菌株、代谢工程、发酵放大和生物制造产线推进PHA材料商业化。",
        "source": "health-check",
        "date": datetime.now().strftime("%Y-%m-%d"),
        "url": "https://example.com/synbio-health-check",
        "type": "news",
    }
    decision = client.judge(sample)
    if not decision.is_approved:
        raise RuntimeError(
            "LLM relevance check rejected a clear synbio sample: "
            f"{decision.reject_message()}"
        )
    if decision.domain_relevance not in {"core_synbio", "adjacent"}:
        raise RuntimeError(f"Unexpected domain_relevance={decision.domain_relevance}")
    if not decision.evidence_spans:
        raise RuntimeError("LLM relevance check returned no evidence_spans")
    raw_response = decision.raw_response or ""
    if raw_response.count("?") >= 6 or "乱码" in raw_response:
        raise RuntimeError("LLM relevance response suggests the Chinese input was corrupted")
    return {
        "provider": decision.provider,
        "domain_relevance": decision.domain_relevance,
        "confidence": decision.confidence,
        "section": decision.section,
        "evidence_count": len(decision.evidence_spans),
    }


def _check_strategy(client: LLMClient, report_date: str, config_path: Path) -> dict[str, Any]:
    config = load_strategy_config(config_path)
    strategy = generate_search_strategy(
        report_date,
        config=config,
        mode="llm",
        client=client,
    )
    queries = strategy.get("queries") or []
    min_queries = int(config.get("min_queries") or 1)
    if strategy.get("provider") != "llm":
        raise RuntimeError(f"Strategy provider is not llm: {strategy.get('provider')}")
    if len(queries) < min_queries:
        raise RuntimeError(f"Strategy returned {len(queries)} queries, below min_queries={min_queries}")
    malformed = [item for item in queries if not isinstance(item, dict) or not str(item.get("query", "")).strip()]
    if malformed:
        raise RuntimeError(f"Strategy returned malformed query entries: {len(malformed)}")
    return {
        "provider": strategy.get("provider"),
        "model": strategy.get("model"),
        "query_count": len(queries),
        "first_queries": [str(item.get("query", "")) for item in queries[:3]],
        "blindspot_count": len(strategy.get("blindspots") or []),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run live LLM health checks for the synbio daily agent")
    parser.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"), help="Report date for strategy smoke")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--timeout", type=int, default=90)
    parser.add_argument("--skip-strategy", action="store_true", help="Only test the relevance gate")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON only")
    args = parser.parse_args(argv)

    client = LLMClient(timeout=args.timeout)
    result: dict[str, Any] = {
        "configured": client.is_configured,
        "base_url": client.base_url,
        "model": client.model,
        "ascii_prompts": client.use_ascii_prompts,
        "checks": [],
    }
    if not client.is_configured:
        result["ok"] = False
        result["error"] = "ANTHROPIC_BASE_URL and ANTHROPIC_AUTH_TOKEN are required"
    else:
        result["checks"].append(_run_check("relevance", lambda: _check_relevance(client)))
        if not args.skip_strategy:
            result["checks"].append(_run_check("search_strategy", lambda: _check_strategy(client, args.date, args.config)))
        result["ok"] = all(check.get("ok") for check in result["checks"])

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"configured={result['configured']} base_url={result['base_url']} model={result['model']} ascii_prompts={result['ascii_prompts']}")
        for check in result.get("checks", []):
            status = "OK" if check.get("ok") else "FAIL"
            print(f"{status} {check['name']} {check['elapsed_seconds']}s")
            if check.get("ok"):
                details = {k: v for k, v in check.items() if k not in {"name", "ok", "elapsed_seconds"}}
                print(json.dumps(details, ensure_ascii=False))
            else:
                print(f"{check.get('error_type')}: {check.get('error')}")
        if not result["ok"] and result.get("error"):
            print(result["error"])
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
