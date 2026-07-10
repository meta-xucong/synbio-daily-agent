import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import report_pipeline
import search_executor
import search_history
from url_identity import url_dedup_key


def _result(url: str, *, title: str = "Synthetic biology update") -> dict:
    return {
        "title": title,
        "url": url,
        "snippet": "A relevant synthetic biology item.",
        "source": "Example",
        "date": "2026-07-09",
    }


def test_url_dedup_key_keeps_semantic_query_ids_and_drops_tracking():
    first = url_dedup_key("https://www.jfdaily.com/news/detail?id=100&utm_source=feed")
    same = url_dedup_key("https://jfdaily.com/news/detail?utm_medium=email&id=100")
    second = url_dedup_key("https://www.jfdaily.com/news/detail?id=101")

    assert first == "jfdaily.com/news/detail?id=100"
    assert same == first
    assert second == "jfdaily.com/news/detail?id=101"
    assert second != first


def test_history_bootstrap_marks_terminal_rejections_for_downstream_skip(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    url = "https://example.com/news/old-item?id=100"
    search_log = {
        "rounds": [{"queries": [{"results": [_result(url)]}]}],
    }
    (data_dir / "search_log_2026-07-09.json").write_text(
        json.dumps(search_log), encoding="utf-8"
    )
    rejected = [{
        "item": dict(_result(url), type="news"),
        "reason": "[timeliness] outside report window",
    }]
    (data_dir / "rejected_2026-07-09.json").write_text(
        json.dumps(rejected), encoding="utf-8"
    )

    registry = search_history.load_registry(search_history.default_registry_path(data_dir))
    stats = search_history.refresh_registry_from_artifacts(
        registry, data_dir, before_date="2026-07-10"
    )
    annotation = search_history.classify_and_record_result(
        registry, _result(url), "2026-07-10"
    )

    assert stats == {"search_logs": 1, "rejections": 1, "sent": 0, "expired": 0}
    assert annotation["prior_seen"] is True
    assert annotation["skip_downstream"] is True
    assert annotation["reason"] == "previous_terminal_decision"


def test_retryable_page_date_rejection_is_rechecked_on_its_due_date(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    url = "https://example.com/research/unverified"
    rejected = [{
        "item": dict(_result(url), type="research"),
        "reason": "[\u9875\u9762\u65e5\u671f] search fallback only",
    }]
    (data_dir / "rejected_2026-07-09.json").write_text(
        json.dumps(rejected, ensure_ascii=False), encoding="utf-8"
    )

    registry = search_history.load_registry(search_history.default_registry_path(data_dir))
    search_history.refresh_registry_from_artifacts(registry, data_dir, before_date="2026-07-10")
    annotation = search_history.classify_and_record_result(
        registry, _result(url), "2026-07-10"
    )

    assert annotation["previous_status"] == "retryable"
    assert annotation["skip_downstream"] is False


def test_history_bootstrap_is_idempotent_for_legacy_sent_keys(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "sent_url_registry.json").write_text(json.dumps({
        "version": 1,
        "registry": {
            "legacy-key": {
                "url": "https://example.com/article?id=100",
                "title": "Sent item",
                "first_sent_date": "2026-07-01",
                "last_seen_date": "2026-07-01",
            }
        },
    }), encoding="utf-8")

    registry = search_history.load_registry(search_history.default_registry_path(data_dir))
    search_history.refresh_registry_from_artifacts(registry, data_dir, before_date="2026-07-10")
    search_history.refresh_registry_from_artifacts(registry, data_dir, before_date="2026-07-10")

    entry = registry["entries"][url_dedup_key("https://example.com/article?id=100")]
    assert entry["status"] == "sent"
    assert entry["legacy_dedup_keys"] == ["legacy-key"]


def test_execute_search_plan_keeps_history_evidence_and_raw_skips_terminal_result():
    class Provider:
        name = "fixture"

        def search(self, query, *, limit):
            return [_result("https://example.com/news/sent")]

    key = url_dedup_key("https://example.com/news/sent")
    registry = {
        "version": 1,
        "entries": {
            key: {
                "dedup_key": key,
                "url": "https://example.com/news/sent",
                "title": "Previously sent",
                "type": "news",
                "first_seen_date": "2026-07-01",
                "last_seen_date": "2026-07-09",
                "seen_count": 1,
                "status": "sent",
            }
        },
    }

    search_log, ok = search_executor.execute_search_plan(
        [{"round": "r1", "queries": ["synthetic biology"]}],
        Provider(),
        date="2026-07-10",
        search_history_registry=registry,
    )
    raw = report_pipeline.build_raw_from_search_log(search_log, report_date="2026-07-10")

    result = search_log["rounds"][0]["queries"][0]["results"][0]
    assert ok
    assert result["search_history"]["skip_downstream"] is True
    assert result["search_history"]["reason"] == "previously_sent"
    assert report_pipeline.count_raw_items(raw) == 0
    assert raw["_meta"]["history_skipped_results"] == 1
