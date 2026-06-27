import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import pre_check
import report_pipeline


def test_pre_check_auto_loads_search_strategy(tmp_path, monkeypatch):
    monkeypatch.setattr(pre_check, "DATA_DIR", tmp_path)
    monkeypatch.setattr(report_pipeline, "load_search_query_config", lambda: {
        "rounds": [{"round_id": "r1", "required_queries": ["合成生物 最新新闻 今日"]}]
    })
    raw = {
        "news": [{
            "title": "合成生物项目落地",
            "source": "测试源",
            "date": "2026-06-10",
            "summary": "合成生物项目落地。",
            "url": "https://example.com/news/synbio-project",
            "type": "news",
            "source_round": "r1",
        }],
        "research": [],
        "funding": [],
        "policy": [],
        "events": [],
    }
    search_log = {
        "date": "2026-06-10",
        "rounds": [
            {
                "round": "r1",
                "queries": [{
                    "query": "合成生物 最新新闻 今日",
                    "executed": True,
                    "results": [{
                        "title": "合成生物项目落地",
                        "url": "https://example.com/news/synbio-project",
                    }],
                }],
            },
            {"round": "r2", "queries": ["q2"], "candidates": []},
            {"round": "r3", "queries": ["q3"], "candidates": []},
            {"round": "r4", "queries": ["q4"], "candidates": []},
            {"round": "r5", "queries": ["q5"], "candidates": []},
        ],
    }
    strategy = {"queries": [{"query": "蓝晶微生物 最新 生物制造", "required": True}]}

    (tmp_path / "raw_2026-06-10.json").write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    (tmp_path / "approved_2026-06-10.json").write_text("[]", encoding="utf-8")
    (tmp_path / "search_log_2026-06-10.json").write_text(json.dumps(search_log, ensure_ascii=False), encoding="utf-8")
    (tmp_path / "search_strategy_2026-06-10.json").write_text(json.dumps(strategy, ensure_ascii=False), encoding="utf-8")

    result = pre_check.pre_check("2026-06-10")

    assert not result["can_proceed"]
    assert any("LLM搜索策略缺少执行记录" in error for error in result["errors"])
