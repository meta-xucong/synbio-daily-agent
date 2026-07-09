from datetime import datetime
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import report_pipeline


def test_timeliness_windows_by_type():
    now = datetime(2026, 6, 11, 12, 0, 0)

    assert report_pipeline.check_timeliness({"date": "2026-06-09"}, "news", now=now)[0]
    assert not report_pipeline.check_timeliness({"date": "2026-06-07"}, "news", now=now)[0]
    assert not report_pipeline.check_timeliness({"date": "2026-06-03"}, "news", now=now)[0]
    assert report_pipeline.check_timeliness({"date": "2026-05-29"}, "research", now=now)[0]
    assert not report_pipeline.check_timeliness({"date": "2026-05-27"}, "research", now=now)[0]
    assert report_pipeline.check_timeliness({"date": "2026-06-05"}, "policy", now=now)[0]
    assert not report_pipeline.check_timeliness({"date": "2026-06-03"}, "policy", now=now)[0]
    assert not report_pipeline.check_timeliness({"date": "2026-05-13"}, "policy", now=now)[0]
    assert report_pipeline.check_timeliness({"date": "2026-06-11"}, "events", now=now)[0]
    assert report_pipeline.check_timeliness({"date": "2026-06-10"}, "events", now=now)[0]  # 过去7天内允许回顾
    assert not report_pipeline.check_timeliness({"date": "2026-06-03"}, "events", now=now)[0]  # 超过7天拒绝
    assert not report_pipeline.check_timeliness({"date": "2026-09-11"}, "events", now=now)[0]
    assert not report_pipeline.check_timeliness({"date": "recently"}, "news", now=now)[0]
    assert not report_pipeline.check_timeliness(
        {"date": "2026-06-10", "verified_date": "2026-06-01"},
        "news",
        now=now,
    )[0]


def test_timeliness_uses_inferred_news_bucket_for_late_industry_story():
    now = datetime(2026, 7, 9, 12, 0, 0)
    item = {
        "date": "2026-07-03",
        "title": "合成生物学跨越“死亡之谷”,一家老牌药企的70年长跑_ZAKER新闻",
        "summary": "专访海正药业，讨论生物制造产业化落地。",
        "source_query": "生物制造 死亡谷 落地",
    }
    item["timeliness_type"] = report_pipeline.infer_timeliness_type(item, "events", "news")

    ok, reason = report_pipeline.check_timeliness(item, "events", now=now)

    assert not ok
    assert "超过时间窗口" in reason


def test_timeliness_keeps_true_event_preview_in_event_bucket():
    now = datetime(2026, 7, 9, 12, 0, 0)
    item = {
        "date": "2026-07-11",
        "title": "2026中欧生命科学国际论坛将于7月11日至12日举办",
        "summary": "报名通道开启，活动议程公布。",
        "source_query": "合成生物 研讨会 会议 活动",
    }
    item["timeliness_type"] = report_pipeline.infer_timeliness_type(item, "events", "event_preview")

    ok, _ = report_pipeline.check_timeliness(item, "events", now=now)

    assert ok
