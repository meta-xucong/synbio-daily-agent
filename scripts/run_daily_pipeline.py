#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Run the full fail-closed daily report pipeline.

This is the single production entrypoint for Kimiwork/OpenClaw automation. It
does not implement business logic itself; it calls the audited scripts in the
required order and stops on the first failure.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

try:
    from .settings import DATA_DIR, REPORTS_DIR, date_str as current_date_str
    from .console_utils import ensure_utf8_console
except ImportError:
    from settings import DATA_DIR, REPORTS_DIR, date_str as current_date_str
    from console_utils import ensure_utf8_console


ensure_utf8_console()

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"


def run_step(label: str, args: list[str]) -> None:
    print(f"\n=== {label} ===")
    completed = subprocess.run(
        [sys.executable, *args],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        raise RuntimeError(f"{label} failed with exit code {completed.returncode}")


def approved_titles(path: Path) -> list[str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise RuntimeError(f"approved must be a list: {path}")
    if not data:
        raise RuntimeError("approved=0，停止发送；请先审计搜索结果和 rejected 列表")
    return [str(item.get("title") or "") for item in data if isinstance(item, dict)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the full synbio daily report pipeline")
    parser.add_argument("--date", default=current_date_str(), help="Report date YYYY-MM-DD")
    parser.add_argument("--provider", default="auto", help="Base search provider for search_executor")
    parser.add_argument("--limit", type=int, default=15, help="Search result limit per query")
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--max-workers", type=int, default=5, help="Bounded query concurrency for base search provider rounds")
    parser.add_argument("--rpm", type=int, help="Optional request-per-minute cap for the base search provider")
    parser.add_argument("--send", action="store_true", help="Actually send email after dry-run gate passes")
    parser.add_argument("--send-mode", default="auto")
    args = parser.parse_args(argv)

    date = args.date
    strategy_path = DATA_DIR / f"search_strategy_{date}.json"
    search_log_path = DATA_DIR / f"search_log_{date}.json"
    raw_path = DATA_DIR / f"raw_{date}.json"
    approved_path = DATA_DIR / f"approved_{date}.json"
    report_dir = REPORTS_DIR / date
    report_path = report_dir / "report.md"
    h5_path = report_dir / "h5.html"
    email_path = report_dir / "email.html"

    try:
        run_step("LLM health check", ["scripts/llm_health_check.py", "--date", date, "--json"])
        run_step("LLM search strategy", [
            "scripts/llm_search_strategy.py",
            "--date", date,
            "--output", str(strategy_path),
            "--mode", "llm",
        ])
        search_executor_args = [
            "scripts/search_executor.py",
            "--date", date,
            "--strategy", str(strategy_path),
            "--output", str(search_log_path),
            "--provider", args.provider,
            "--limit", str(args.limit),
            "--timeout", str(args.timeout),
            "--retries", str(args.retries),
            "--max-workers", str(args.max_workers),
        ]
        if args.rpm is not None:
            search_executor_args.extend(["--rpm", str(args.rpm)])
        run_step("High-recall search executor", search_executor_args)
        run_step("Build raw from search", [
            "scripts/report_pipeline.py",
            "--build-raw-from-search", str(search_log_path),
            "--date", date,
            "--output", str(raw_path),
        ])
        run_step("Audit search log", [
            "scripts/audit_search_log.py",
            str(search_log_path),
            "--raw", str(raw_path),
            "--search-strategy", str(strategy_path),
        ])
        run_step("Build approved", [
            "scripts/report_pipeline.py",
            "--build-approved", str(raw_path),
            "--date", date,
            "--output", str(DATA_DIR),
            "--search-log", str(search_log_path),
            "--search-strategy", str(strategy_path),
        ])
        titles = approved_titles(approved_path)
        run_step("Pre-check", ["scripts/pre_check.py", date])
        run_step("Render markdown", [
            "scripts/report_pipeline.py",
            "--render-md", str(approved_path),
            "--date", date,
            "--raw", str(raw_path),
            "--output", str(report_path),
        ])
        run_step("Generate H5/email", [
            "scripts/generate_from_template.py",
            "--date", date,
            "--approved", str(approved_path),
            "--markdown", str(report_path),
            "--html-output", str(h5_path),
            "--email-output", str(email_path),
        ])
        run_step("Full validation", [
            "scripts/report_pipeline.py",
            "--full-validate", str(report_path),
            "--email", str(email_path),
            "--approved", str(approved_path),
            "--output", str(DATA_DIR / f"full_validation_{date}.json"),
        ])
        run_step("Send dry-run gate", [
            "scripts/send_email.py",
            date,
            str(report_path),
            str(h5_path),
            str(email_path),
            "--dry-run",
            "--send-mode", args.send_mode,
        ])
        if args.send:
            run_step("Real send", [
                "scripts/send_email.py",
                date,
                str(report_path),
                str(h5_path),
                str(email_path),
                "--send-mode", args.send_mode,
            ])
        run_step("Post-send search audit", [
            "scripts/audit_search_log.py",
            str(search_log_path),
            "--raw", str(raw_path),
            "--search-strategy", str(strategy_path),
        ])
        run_step("Post-send pre-check", ["scripts/pre_check.py", date])
    except Exception as exc:
        print(f"\n[FAIL-CLOSED] {exc}", file=sys.stderr)
        return 1

    print("\nPipeline completed")
    print(f"approved={len(titles)}")
    for title in titles:
        print(f"- {title}")
    print(f"send={'real' if args.send else 'dry-run-only'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
