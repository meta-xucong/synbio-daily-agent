import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import llm_search_strategy
import report_pipeline


def _strategy_config():
    return {
        "min_queries": 2,
        "max_queries": 4,
        "strategy_round_id": "llm_dynamic",
        "base_rounds": ["r1", "r5"],
        "coverage_dimensions": ["policy", "funding", "enterprise"],
        "tracked_entities": ["蓝晶微生物", "华恒生物"],
        "technology_topics": ["precision fermentation", "无细胞合成"],
        "source_hints": ["site:vbdata.cn 合成生物 融资"],
    }


def _search_log_with_dynamic_query(query="蓝晶微生物 最新 生物制造", executed=True):
    return {
        "date": "2026-06-25",
        "rounds": [
            {"round": "r1", "queries": ["合成生物 最新新闻 今日"], "candidates": []},
            {"round": "r2", "queries": ["q2"], "candidates": []},
            {"round": "r3", "queries": ["q3"], "candidates": []},
            {"round": "r4", "queries": ["q4"], "candidates": []},
            {"round": "r5", "queries": ["q5"], "candidates": []},
            {
                "round": "llm_dynamic",
                "queries": [{"query": query, "executed": executed, "error": "" if executed else "timeout"}],
                "candidates": [],
            },
        ],
    }


def test_heuristic_search_strategy_uses_seed_memory():
    strategy = llm_search_strategy.generate_search_strategy(
        "2026-06-25",
        config=_strategy_config(),
        mode="heuristic",
    )

    queries = [item["query"] for item in strategy["queries"]]
    assert strategy["provider"] == "heuristic"
    assert len(queries) >= 2
    assert any("蓝晶微生物" in query for query in queries)
    assert any("vbdata.cn" in query for query in queries)
    assert all(item["required"] for item in strategy["queries"])


def test_heuristic_search_strategy_keeps_all_tracked_entities_with_high_max_queries():
    config = _strategy_config()
    config["max_queries"] = 20
    config["coverage_queries"] = [
        {"query": "site:stic.sz.gov.cn 合成生物", "target_section": "policy"},
        {"query": "site:kw.beijing.gov.cn 生物制造", "target_section": "policy"},
        {"query": "site:sh.gov.cn 合成生物", "target_section": "policy"},
        {"query": "生物制造 政策 落地", "target_section": "news"},
        {"query": "合成生物 签约 落地", "target_section": "news"},
        {"query": "site:vbdata.cn 合成生物", "target_section": "news"},
        {"query": "site:36kr.com 合成生物", "target_section": "news"},
        {"query": "华恒生物 聆讯 上市", "target_section": "funding"},
    ]
    config["tracked_entities"] = [
        "蓝晶微生物", "华恒生物", "凯赛生物", "华熙生物",
        "引航生物", "川宁生物", "和晨生物", "微远生物",
        "虹摹生物", "微元合成",
    ]

    strategy = llm_search_strategy.generate_search_strategy(
        "2026-06-25",
        config=config,
        mode="heuristic",
    )

    queries = [item["query"] for item in strategy["queries"]]
    assert len(queries) == 20
    assert any("蓝晶微生物" in q for q in queries)
    assert any("凯赛生物" in q for q in queries)
    assert any("华熙生物" in q for q in queries)
    assert any("引航生物" in q for q in queries)
    assert any("川宁生物" in q for q in queries)
    assert any("和晨生物" in q for q in queries)
    assert any("微远生物" in q for q in queries)
    assert any("虹摹生物" in q for q in queries)
    assert any("微元合成" in q for q in queries)
    assert any("site:stic.sz.gov.cn" in q for q in queries)
    assert any("生物制造 政策 落地" in q for q in queries)


def test_heuristic_search_strategy_keeps_coverage_floor_queries():
    config = _strategy_config()
    config["max_queries"] = 6
    config["coverage_queries"] = [
        {"query": "site:stic.sz.gov.cn 合成生物", "target_section": "policy"},
        {"query": "生物制造 政策 落地", "target_section": "news"},
        {"query": "site:vbdata.cn 合成生物", "target_section": "news"},
        {"query": "华恒生物 聆讯 上市", "target_section": "funding"},
    ]

    strategy = llm_search_strategy.generate_search_strategy(
        "2026-06-25",
        config=config,
        mode="heuristic",
    )

    queries = [item["query"] for item in strategy["queries"]]
    assert "site:stic.sz.gov.cn 合成生物" in queries
    assert "生物制造 政策 落地" in queries
    assert "site:vbdata.cn 合成生物" in queries
    assert "华恒生物 聆讯 上市" in queries


def test_llm_search_strategy_normalizes_fake_client_response():
    class FakeClient:
        is_configured = True
        model = "fake-model"

        def complete(self, prompt):
            assert "合成生物日报的信息检索指挥官" in prompt
            return json.dumps({
                "blindspots": ["重点企业", "融资"],
                "queries": [
                    {
                        "query": "蓝晶微生物 最新 生物制造",
                        "reason": "重点企业补搜",
                        "priority": "high",
                        "target_section": "news",
                        "expected_source_type": "company_or_media",
                    },
                    {
                        "query": "site:vbdata.cn 合成生物 融资",
                        "reason": "中文融资补搜",
                        "priority": "high",
                        "target_section": "funding",
                    },
                ],
            }, ensure_ascii=False)

    strategy = llm_search_strategy.generate_search_strategy(
        "2026-06-25",
        config=_strategy_config(),
        mode="llm",
        client=FakeClient(),
    )

    assert strategy["provider"] == "llm"
    assert strategy["model"] == "fake-model"
    assert strategy["queries"][0]["priority"] == "high"
    assert strategy["queries"][1]["target_section"] == "funding"
    assert strategy["blindspots"] == ["重点企业", "融资"]


def test_messages_text_client_uses_search_strategy_token_budget(monkeypatch):
    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps({
                "content": [{"text": '{"queries": []}'}],
            }).encode("utf-8")

    def fake_opener(request, timeout=45):
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        return FakeResponse()

    monkeypatch.setenv("ANTHROPIC_SEARCH_STRATEGY_MAX_TOKENS", "4200")
    client = llm_search_strategy.MessagesTextClient(
        llm_search_strategy.LLMClient(
            base_url="https://example.invalid",
            auth_token="test-token",
            opener=fake_opener,
        )
    )

    client.complete("prompt")

    assert captured["payload"]["max_tokens"] == 4200


def test_llm_search_strategy_appends_missing_coverage_queries():
    config = _strategy_config()
    config["max_queries"] = 5
    config["coverage_queries"] = [
        {"query": "site:stic.sz.gov.cn 合成生物", "target_section": "policy"},
        {"query": "site:vbdata.cn 合成生物", "target_section": "news"},
    ]
    strategy = llm_search_strategy.normalize_strategy_response(
        {
            "queries": [
                {
                    "query": "蓝晶微生物 最新 合成生物",
                    "reason": "重点企业补搜",
                    "target_section": "news",
                }
            ],
        },
        report_date="2026-06-25",
        config=config,
        provider="llm",
        model="fake-model",
    ).to_dict()

    queries = [item["query"] for item in strategy["queries"]]
    assert "蓝晶微生物 最新 合成生物" in queries
    assert "site:stic.sz.gov.cn 合成生物" in queries
    assert "site:vbdata.cn 合成生物" in queries


def test_llm_search_strategy_coverage_floor_displaces_full_llm_response():
    config = _strategy_config()
    config["max_queries"] = 4
    config["coverage_queries"] = [
        {"query": "site:stic.sz.gov.cn 合成生物", "target_section": "policy"},
        {"query": "生物制造 政策 落地", "target_section": "news"},
        {"query": "site:vbdata.cn 合成生物", "target_section": "news"},
        {"query": "华恒生物 聆讯 上市", "target_section": "funding"},
    ]

    strategy = llm_search_strategy.normalize_strategy_response(
        {
            "queries": [
                {"query": f"LLM 临时查询 {index}", "reason": "模型补搜"}
                for index in range(1, 5)
            ],
        },
        report_date="2026-06-25",
        config=config,
        provider="llm",
        model="fake-model",
    ).to_dict()

    queries = [item["query"] for item in strategy["queries"]]
    assert len(queries) == 4
    assert queries == [
        "site:stic.sz.gov.cn 合成生物",
        "生物制造 政策 落地",
        "site:vbdata.cn 合成生物",
        "华恒生物 聆讯 上市",
    ]


def test_llm_search_strategy_splits_overpacked_company_query():
    config = _strategy_config()
    config["tracked_entities"] = ["蓝晶微生物", "华恒生物", "凯赛生物", "引航生物"]
    strategy = llm_search_strategy.normalize_strategy_response(
        {
            "queries": [{
                "query": "蓝晶微生物 华恒生物 凯赛生物 引航生物 2026年6月 融资 产品 合作 公告",
                "reason": "重点企业批量补搜",
                "priority": "high",
                "target_section": "funding",
            }, {
                "query": "site:vbdata.cn 合成生物 融资",
                "reason": "中文融资补搜",
            }],
        },
        report_date="2026-06-25",
        config=config,
        provider="llm",
        model="fake-model",
    ).to_dict()

    queries = [item["query"] for item in strategy["queries"]]
    assert "蓝晶微生物 华恒生物 合成生物 公告 最新" in queries
    assert "凯赛生物 引航生物 合成生物 公告 最新" in queries
    assert all(sum(entity in query for entity in config["tracked_entities"]) <= 2 for query in queries)


def test_validate_search_strategy_execution_blocks_missing_query():
    strategy = {
        "queries": [
            {"query": "蓝晶微生物 最新 生物制造", "required": True},
            {"query": "华恒生物 港交所 合成生物", "required": True},
        ]
    }
    result = report_pipeline.validate_search_strategy_execution(
        strategy,
        _search_log_with_dynamic_query("蓝晶微生物 最新 生物制造"),
    )

    assert not result["is_valid"]
    assert result["executed_required_count"] == 1
    assert "华恒生物 港交所 合成生物" in result["missing_queries"]
    assert "LLM搜索策略缺少执行记录" in ";".join(result["errors"])


def test_validate_search_strategy_execution_blocks_failed_query():
    strategy = {"queries": [{"query": "蓝晶微生物 最新 生物制造", "required": True}]}
    result = report_pipeline.validate_search_strategy_execution(
        strategy,
        _search_log_with_dynamic_query("蓝晶微生物 最新 生物制造", executed=False),
    )

    assert not result["is_valid"]
    assert result["failed_queries"][0]["error"] == "timeout"
    assert "执行失败" in ";".join(result["errors"])


def test_find_default_search_strategy_path_prefers_search_log_directory(tmp_path):
    search_log_path = tmp_path / "search_log_2026-06-25.json"
    strategy_path = tmp_path / "search_strategy_2026-06-25.json"
    search_log_path.write_text("{}", encoding="utf-8")
    strategy_path.write_text('{"queries":[]}', encoding="utf-8")

    found = report_pipeline.find_default_search_strategy_path("2026-06-25", search_log_path)

    assert found == strategy_path


def test_build_approved_rejects_strategy_without_search_log():
    raw = {"news": [], "research": [], "funding": [], "policy": [], "events": []}

    try:
        report_pipeline.build_approved_from_raw(
            raw,
            "2026-06-25",
            search_strategy={"queries": [{"query": "蓝晶微生物 最新"}]},
        )
    except ValueError as exc:
        assert "search_strategy requires search_log" in str(exc)
    else:
        raise AssertionError("search_strategy without search_log should fail closed")


def test_validate_search_log_enforces_llm_strategy(monkeypatch):
    monkeypatch.setattr(report_pipeline, "load_search_query_config", lambda: {
        "rounds": [{"round_id": "r1", "required_queries": ["合成生物 最新新闻 今日"]}]
    })
    raw = {"news": [], "research": [], "funding": [], "policy": [], "events": []}
    strategy = {"queries": [{"query": "蓝晶微生物 最新 生物制造", "required": True}]}

    result = report_pipeline.validate_search_log(
        _search_log_with_dynamic_query("别的查询"),
        raw,
        strict_coverage=True,
        search_strategy=strategy,
    )

    assert not result["is_valid"]
    assert result["strategy_check"]["required_total"] == 1
    assert "LLM搜索策略缺少执行记录" in ";".join(result["errors"])


def test_audit_search_log_auto_loads_sibling_strategy(tmp_path):
    search_log = _search_log_with_dynamic_query("别的查询")
    search_log_path = tmp_path / "search_log_2026-06-25.json"
    strategy_path = tmp_path / "search_strategy_2026-06-25.json"
    search_log_path.write_text(json.dumps(search_log, ensure_ascii=False), encoding="utf-8")
    strategy_path.write_text(json.dumps({
        "queries": [{"query": "蓝晶微生物 最新 生物制造", "required": True}]
    }, ensure_ascii=False), encoding="utf-8")

    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / "audit_search_log.py"),
            str(search_log_path),
            "--relaxed",
        ],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 1
    assert "auto-loaded search strategy" in completed.stdout
    assert "LLM搜索策略缺少执行记录" in completed.stdout


def test_llm_search_strategy_cli_heuristic(tmp_path):
    output = tmp_path / "strategy.json"
    config = tmp_path / "strategy_config.json"
    config.write_text(json.dumps(_strategy_config(), ensure_ascii=False), encoding="utf-8")

    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / "llm_search_strategy.py"),
            "--date",
            "2026-06-25",
            "--output",
            str(output),
            "--mode",
            "heuristic",
            "--config",
            str(config),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    data = json.loads(output.read_text(encoding="utf-8"))
    assert data["date"] == "2026-06-25"
    assert len(data["queries"]) >= 2
