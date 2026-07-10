#!/usr/bin/env python3
"""Persistent search-result history for safe downstream deduplication."""

from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

try:
    from .url_identity import url_dedup_key
except ImportError:
    from url_identity import url_dedup_key


REGISTRY_VERSION = 1
REGISTRY_FILENAME = "search_url_registry.json"
RETRY_WINDOWS_DAYS = {
    "news": 3,
    "research": 14,
    "policy": 7,
    "funding": 7,
    "events": 60,
}
RETRY_DELAYS_DAYS = (1, 3, 7)
_DATE_FROM_NAME_RE = re.compile(r"_(\d{4}-\d{2}-\d{2})\.json$")


def default_registry_path(data_dir: Path) -> Path:
    return data_dir / REGISTRY_FILENAME


def _parse_day(value: Any) -> date | None:
    try:
        return datetime.strptime(str(value or "")[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _empty_registry() -> dict[str, Any]:
    return {"version": REGISTRY_VERSION, "entries": {}}


def load_registry(path: Path) -> dict[str, Any]:
    if not path.exists():
        return _empty_registry()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return _empty_registry()
    if not isinstance(payload, dict) or not isinstance(payload.get("entries"), dict):
        return _empty_registry()
    payload.setdefault("version", REGISTRY_VERSION)
    return payload


def save_registry(path: Path, registry: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    registry["version"] = REGISTRY_VERSION
    path.write_text(json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8")


def _ensure_entry(registry: dict[str, Any], item: dict[str, Any], seen_date: str) -> dict[str, Any] | None:
    url = str(item.get("url") or item.get("link") or "").strip()
    key = url_dedup_key(url)
    if not key:
        return None
    entries = registry.setdefault("entries", {})
    entry = entries.get(key)
    if not isinstance(entry, dict):
        entry = {
            "dedup_key": key,
            "url": url,
            "title": str(item.get("title") or "").strip()[:200],
            "type": str(item.get("type") or "news").strip().lower() or "news",
            "first_seen_date": seen_date,
            "last_seen_date": seen_date,
            "seen_count": 0,
            "status": "seen",
        }
        entries[key] = entry
    else:
        entry.setdefault("dedup_key", key)
        entry.setdefault("url", url)
        entry.setdefault("title", str(item.get("title") or "").strip()[:200])
        entry.setdefault("type", str(item.get("type") or "news").strip().lower() or "news")
        first_seen = _parse_day(entry.get("first_seen_date"))
        candidate_seen = _parse_day(seen_date)
        if first_seen is None or (candidate_seen is not None and candidate_seen < first_seen):
            entry["first_seen_date"] = seen_date
    return entry


def _set_seen_dates(entry: dict[str, Any], seen_date: str, *, increment: bool) -> None:
    previous = _parse_day(entry.get("last_seen_date"))
    current = _parse_day(seen_date)
    if previous is None or (current is not None and current >= previous):
        entry["last_seen_date"] = seen_date
    if increment:
        entry["seen_count"] = int(entry.get("seen_count") or 0) + 1


def _rejection_status(reason: Any) -> str:
    text = str(reason or "").lower()
    if not text:
        return "seen"
    if "页面日期" in text or "链接健康" in text:
        return "retryable"
    if "活动太远" in text:
        return "retryable"
    return "terminal"


def _retry_until(entry: dict[str, Any], item_type: str) -> date | None:
    first_seen = _parse_day(entry.get("first_seen_date"))
    if first_seen is None:
        return None
    return first_seen + timedelta(days=RETRY_WINDOWS_DAYS.get(item_type, 7))


def _record_rejection(entry: dict[str, Any], item: dict[str, Any], reason: Any, decision_date: str) -> None:
    prior_decision = _parse_day(entry.get("last_decision_date"))
    current_decision = _parse_day(decision_date)
    if current_decision is None or (prior_decision is not None and current_decision <= prior_decision):
        return

    item_type = str(item.get("type") or entry.get("type") or "news").strip().lower() or "news"
    entry["type"] = item_type
    entry["last_decision_date"] = decision_date
    entry["last_reason"] = str(reason or "")[:500]
    status = _rejection_status(reason)
    if status != "retryable":
        entry["status"] = "terminal"
        entry.pop("next_retry_date", None)
        entry.pop("retry_until", None)
        return

    attempts = int(entry.get("retry_attempts") or 0) + 1
    entry["retry_attempts"] = attempts
    until = _retry_until(entry, item_type)
    entry["retry_until"] = until.isoformat() if until else None
    if until is not None and current_decision > until:
        entry["status"] = "terminal"
        entry["last_reason"] = f"{entry['last_reason']} [unverified retry window expired]"[:500]
        entry.pop("next_retry_date", None)
        return
    delay = RETRY_DELAYS_DAYS[min(attempts - 1, len(RETRY_DELAYS_DAYS) - 1)]
    next_retry = current_decision + timedelta(days=delay)
    entry["status"] = "retryable"
    entry["next_retry_date"] = min(next_retry, until).isoformat() if until else next_retry.isoformat()


def _expire_retryable_entries(registry: dict[str, Any], as_of_date: str) -> int:
    as_of = _parse_day(as_of_date)
    if as_of is None:
        return 0
    expired = 0
    for entry in (registry.get("entries", {}) or {}).values():
        if not isinstance(entry, dict) or entry.get("status") != "retryable":
            continue
        retry_until = _parse_day(entry.get("retry_until"))
        if retry_until is None or as_of <= retry_until:
            continue
        entry["status"] = "terminal"
        entry["last_reason"] = f"{entry.get('last_reason', '')} [unverified retry window expired]"[:500]
        entry.pop("next_retry_date", None)
        expired += 1
    return expired


def _iter_search_results(payload: Any) -> Iterable[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    results: list[dict[str, Any]] = []
    for round_entry in payload.get("rounds", []) or []:
        if not isinstance(round_entry, dict):
            continue
        for query_entry in round_entry.get("queries", []) or []:
            if not isinstance(query_entry, dict):
                continue
            for item in query_entry.get("results", []) or []:
                if isinstance(item, dict):
                    results.append(item)
    return results


def _artifact_date(path: Path, prefix: str) -> str | None:
    if not path.name.startswith(prefix):
        return None
    match = _DATE_FROM_NAME_RE.search(path.name)
    return match.group(1) if match else None


def refresh_registry_from_artifacts(registry: dict[str, Any], data_dir: Path, *, before_date: str) -> dict[str, int]:
    """Backfill first-seen and terminal decisions from canonical daily artifacts."""
    cutoff = _parse_day(before_date)
    stats = {"search_logs": 0, "rejections": 0, "sent": 0, "expired": 0}
    if cutoff is None or not data_dir.exists():
        return stats

    for path in sorted(data_dir.glob("search_log_*.json")):
        artifact_date = _artifact_date(path, "search_log_")
        if artifact_date is None or _parse_day(artifact_date) is None or _parse_day(artifact_date) >= cutoff:
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        for item in _iter_search_results(payload):
            entry = _ensure_entry(registry, item, artifact_date)
            if entry is not None:
                _set_seen_dates(entry, artifact_date, increment=False)
                stats["search_logs"] += 1

    for path in sorted(data_dir.glob("rejected_*.json")):
        artifact_date = _artifact_date(path, "rejected_")
        if artifact_date is None or _parse_day(artifact_date) is None or _parse_day(artifact_date) >= cutoff:
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(payload, list):
            continue
        for record in payload:
            if not isinstance(record, dict) or not isinstance(record.get("item"), dict):
                continue
            entry = _ensure_entry(registry, record["item"], artifact_date)
            if entry is not None:
                _record_rejection(entry, record["item"], record.get("reason"), artifact_date)
                stats["rejections"] += 1

    sent_path = data_dir / "sent_url_registry.json"
    if sent_path.exists():
        try:
            sent_payload = json.loads(sent_path.read_text(encoding="utf-8"))
        except Exception:
            sent_payload = {}
        sent_entries = (sent_payload.get("registry", {}) or {}) if isinstance(sent_payload, dict) else {}
        for stored_key, record in sent_entries.items():
            if not isinstance(record, dict):
                continue
            item = {"url": record.get("url"), "title": record.get("title"), "type": "news"}
            entry = _ensure_entry(registry, item, str(record.get("first_sent_date") or before_date))
            if entry is None:
                continue
            entry["status"] = "sent"
            entry["last_reason"] = "previously sent"
            entry["last_decision_date"] = str(record.get("last_seen_date") or record.get("first_sent_date") or before_date)
            stats["sent"] += 1
            # Preserve the historical registry key only as a migration hint;
            # identity comparisons always use the current canonical key.
            raw_legacy_keys = entry.get("legacy_dedup_keys")
            legacy_keys = list(dict.fromkeys(str(key) for key in raw_legacy_keys)) if isinstance(raw_legacy_keys, list) else []
            entry["legacy_dedup_keys"] = legacy_keys
            if str(stored_key) not in legacy_keys:
                legacy_keys.append(str(stored_key))
    stats["expired"] = _expire_retryable_entries(registry, before_date)
    return stats


def classify_and_record_result(registry: dict[str, Any], result: dict[str, Any], report_date: str) -> dict[str, Any]:
    """Annotate one fresh search result with its downstream dedup disposition."""
    entry = _ensure_entry(registry, result, report_date)
    if entry is None:
        return {"skip_downstream": False, "reason": "missing_url_identity"}
    first_seen = _parse_day(entry.get("first_seen_date"))
    report_day = _parse_day(report_date)
    prior_seen = bool(entry.get("seen_count") or (first_seen is not None and report_day is not None and first_seen < report_day))
    _set_seen_dates(entry, report_date, increment=True)
    status = str(entry.get("status") or "seen")
    skip = False
    reason = "new_or_pending_review"
    today = report_day
    if status in {"sent", "terminal"}:
        skip = True
        reason = "previously_sent" if status == "sent" else "previous_terminal_decision"
    elif status == "retryable" and today is not None:
        until = _parse_day(entry.get("retry_until"))
        next_retry = _parse_day(entry.get("next_retry_date"))
        if until is not None and today > until:
            entry["status"] = "terminal"
            entry["last_reason"] = f"{entry.get('last_reason', '')} [unverified retry window expired]"[:500]
            skip = True
            reason = "retry_window_expired"
        elif next_retry is not None and today < next_retry:
            skip = True
            reason = "retry_backoff"
    return {
        "dedup_key": entry["dedup_key"],
        "prior_seen": prior_seen,
        "first_seen_date": entry.get("first_seen_date"),
        "previous_status": status,
        "skip_downstream": skip,
        "reason": reason,
    }
