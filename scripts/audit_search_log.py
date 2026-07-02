#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Audit a search_log against the configured required daily queries."""

import argparse
import json
import sys
from pathlib import Path

try:
    from .report_pipeline import find_default_search_strategy_path, validate_search_log
except ImportError:
    from report_pipeline import find_default_search_strategy_path, validate_search_log


def load_json(path: Path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit search_log required query coverage")
    parser.add_argument("search_log", type=Path, help="Path to data/search_log_YYYY-MM-DD.json")
    parser.add_argument("--raw", type=Path, help="Optional raw JSON path for candidate URL coverage audit")
    parser.add_argument("--search-strategy", type=Path, help="Optional LLM search strategy JSON path")
    parser.add_argument(
        "--allow-missing-strategy",
        action="store_true",
        help="Diagnostic-only: do not fail when the same-day LLM search strategy is absent",
    )
    parser.add_argument(
        "--relaxed",
        action="store_true",
        help="Downgrade missing required queries and candidate coverage gaps to warnings",
    )
    args = parser.parse_args()

    search_log = load_json(args.search_log)
    raw_obj = load_json(args.raw) if args.raw else None
    strategy_path = args.search_strategy
    if strategy_path is None and isinstance(search_log, dict) and search_log.get("date"):
        strategy_path = find_default_search_strategy_path(str(search_log.get("date")), args.search_log)
    search_strategy = load_json(strategy_path) if strategy_path else None
    if strategy_path and not args.search_strategy:
        print(f"auto-loaded search strategy: {strategy_path}")
    result = validate_search_log(
        search_log,
        raw_obj,
        strict_coverage=not args.relaxed,
        search_strategy=search_strategy,
        require_search_strategy=not args.allow_missing_strategy,
    )

    print(
        f"search_log rounds={len(result.get('rounds_seen', []))} "
        f"queries={result.get('total_queries', 0)} valid={result['is_valid']}"
    )
    required_query_check = result.get("required_query_check") or {}
    if required_query_check:
        print(
            "required queries: "
            f"{required_query_check.get('executed_required_count', 0)}/"
            f"{required_query_check.get('required_total', 0)} executed"
        )
    strategy_check = result.get("strategy_check") or {}
    if strategy_check:
        print(
            "LLM strategy queries: "
            f"{strategy_check.get('executed_required_count', 0)}/"
            f"{strategy_check.get('required_total', 0)} executed"
        )
    for warning in result.get("warnings", []):
        print(f"WARNING: {warning}")
    for error in result.get("errors", []):
        print(f"ERROR: {error}")
    return 0 if result["is_valid"] else 1


if __name__ == "__main__":
    sys.exit(main())
