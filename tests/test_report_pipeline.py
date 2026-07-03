import json
import ssl
import subprocess
import sys
from urllib.error import HTTPError, URLError
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import report_pipeline


def _item(**overrides):
    base = {
        "title": "Novel yeast platform improves fermentation",
        "source": "SynBioBeta",
        "date": "2026-06-10",
        "summary": "The platform improves fermentation yield by 20%.",
        "url": "https://example.com/news/yeast-platform",
    }
    base.update(overrides)
    return base


def test_normalize_raw_input_accepts_full_category_dict():
    raw = json.loads((ROOT / "tests" / "fixtures" / "raw_full.json").read_text(encoding="utf-8"))
    items = report_pipeline.normalize_raw_input(raw, "news")
    assert len(items) == 3
    assert items[0]["title"] == "Synthetic Bio Company Raises Series A"


def test_normalize_raw_input_accepts_single_category_list():
    items = [_item()]
    assert report_pipeline.normalize_raw_input(items, "news") == items


def test_count_raw_items_counts_full_category_dict():
    raw = {
        "news": [_item()],
        "research": [_item()],
        "funding": [],
        "policy": [],
        "events": [_item()],
        "ignored": [_item()],
    }

    assert report_pipeline.count_raw_items(raw) == 3


def _search_log():
    return {
        "version": 1,
        "date": "2026-06-10",
        "generated_by": "search_executor",
        "provider": "llm_web",
        "llm_discovery_provider": "llm_web",
        "high_recall_enabled": True,
        "required_high_recall_rounds": ["llm_discovery", "llm_gap_audit"],
        "limit": 15,
        "rounds": [
            {"round": "r1", "queries": [{"query": "synthetic biology funding", "executed": True, "provider": "llm_web"}], "candidates": ["https://example.com/news/yeast-platform"]},
            {"round": "r1b", "queries": [{"query": "synthetic biology peptide protein", "executed": True, "provider": "llm_web"}], "candidates": []},
            {"round": "r2", "queries": [{"query": "synthetic biology research", "executed": True, "provider": "llm_web"}], "candidates": []},
            {"round": "r3", "queries": [{"query": "synthetic biology policy", "executed": True, "provider": "llm_web"}], "candidates": []},
            {"round": "r4", "queries": [{"query": "synthetic biology events", "executed": True, "provider": "llm_web"}], "candidates": []},
            {"round": "r5", "queries": [{"query": "synthetic biology China", "executed": True, "provider": "llm_web"}], "candidates": []},
            {"round": "r6", "queries": [{"query": "biomanufacturing news", "executed": True, "provider": "llm_web"}], "candidates": []},
            {"round": "llm_discovery", "queries": [{"query": "recent synthetic biology discovery", "executed": True, "provider": "llm_web", "web_search_tool_result": True}], "candidates": []},
            {"round": "llm_gap_audit", "queries": [{"query": "synthetic biology gap audit", "executed": True, "provider": "llm_web", "web_search_tool_result": True}], "candidates": []},
        ],
    }


def _round(log, round_id):
    return next(item for item in log["rounds"] if item["round"] == round_id)


def test_validate_search_log_requires_configured_rounds_and_raw_traceability():
    raw = {
        "news": [_item(type="news", source_round="r1")],
        "research": [],
        "funding": [],
        "policy": [],
        "events": [],
    }

    result = report_pipeline.validate_search_log(_search_log(), raw)

    assert result["is_valid"], result["errors"]
    assert {"r1", "r1b", "r2", "r3", "r4", "r5", "r6"} <= set(result["rounds_seen"])
    assert result["total_queries"] == 9
    assert result["warnings"]


def test_validate_search_log_blocks_missing_round_and_untraced_raw_item():
    log = _search_log()
    log["rounds"] = log["rounds"][:4]
    raw = {
        "news": [
            _item(type="news", source_round="r1"),
            _item(type="news", url="https://example.com/news/untraced"),
        ],
        "research": [],
        "funding": [],
        "policy": [],
        "events": [],
    }

    result = report_pipeline.validate_search_log(log, raw)

    assert not result["is_valid"]
    assert any("缺少必要搜索轮次" in error for error in result["errors"])
    assert any("缺少source_round" in error for error in result["errors"])


def test_validate_search_log_allows_empty_raw_when_rounds_have_queries():
    raw = {
        "news": [
            _item(
                type="news",
                source_round="llm_discovery",
                source_query="broad discovery",
                url="https://example.com/discovery",
                title="Discovery",
            )
        ],
        "research": [],
        "funding": [],
        "policy": [],
        "events": [],
    }

    result = report_pipeline.validate_search_log(_search_log(), raw)

    assert result["is_valid"], result["errors"]
    assert {"r1", "r1b", "r2", "r3", "r4", "r5", "r6"} <= set(result["rounds_seen"])
    assert "raw数据缺少source_round" not in ";".join(result["errors"])


def test_configured_required_search_rounds_uses_legacy_fallback_when_config_missing(monkeypatch):
    monkeypatch.setattr(report_pipeline, "load_search_query_config", lambda: {})

    assert report_pipeline.configured_required_search_rounds() == {
        "r1", "r1b", "r2", "r3", "r4", "r5", "r6"
    }


def test_validate_search_log_blocks_missing_required_queries(monkeypatch):
    monkeypatch.setattr(report_pipeline, "load_search_query_config", lambda: {
        "rounds": [{"round_id": "r5", "required_queries": ["site:kw.beijing.gov.cn 合成生物"]}]
    })
    raw = {"news": [], "research": [], "funding": [], "policy": [], "events": []}

    result = report_pipeline.validate_search_log(_search_log(), raw, strict_coverage=True)

    assert not result["is_valid"]
    assert "site:kw.beijing.gov.cn 合成生物" in ";".join(result["errors"])
    assert result["required_query_check"]["required_total"] == 1


def test_validate_search_log_warns_when_required_queries_missing_not_strict(monkeypatch):
    monkeypatch.setattr(report_pipeline, "load_search_query_config", lambda: {
        "rounds": [{"round_id": "r5", "required_queries": ["site:kw.beijing.gov.cn 合成生物"]}]
    })
    raw = {"news": [], "research": [], "funding": [], "policy": [], "events": []}

    result = report_pipeline.validate_search_log(_search_log(), raw, strict_coverage=False)

    assert result["is_valid"], result["errors"]
    assert any("site:kw.beijing.gov.cn 合成生物" in warning for warning in result["warnings"])


def test_validate_search_log_passes_when_all_required_queries_present(monkeypatch):
    monkeypatch.setattr(report_pipeline, "load_search_query_config", lambda: {
        "rounds": [
            {"round_id": "r2", "required_queries": ["site:synbiobeta.com synthetic biology 2026"]},
            {"round_id": "r5", "required_queries": ["site:kw.beijing.gov.cn 合成生物"]},
        ]
    })
    log = _search_log()
    log["rounds"][2]["queries"] = [{"query": "site:synbiobeta.com synthetic biology 2026", "executed": True, "results_count": 0, "provider": "llm_web"}]
    log["rounds"][5]["queries"] = [{"query": "site:kw.beijing.gov.cn 合成生物", "executed": True, "results_count": 0, "provider": "llm_web"}]
    log["rounds"][0]["candidates"] = []
    raw = {"news": [], "research": [], "funding": [], "policy": [], "events": []}

    result = report_pipeline.validate_search_log(log, raw, strict_coverage=True)

    assert result["is_valid"], result["errors"]
    assert result["required_query_check"]["executed_required_count"] == 2


def test_validate_search_log_accepts_candidate_source_query_legacy_format(monkeypatch):
    monkeypatch.setattr(report_pipeline, "load_search_query_config", lambda: {
        "rounds": [{"round_id": "r1", "required_queries": ["合成生物 白皮书 报告 发布"]}]
    })
    log = {
        "date": "2026-06-18",
        "rounds": [
            {
                "round": "r1",
                "candidates": [{
                    "title": "2026中国合成生物制造白皮书发布",
                    "url": "https://bydrug.pharmcube.com/news/detail/whitepaper-2026",
                    "snippet": "白皮书系统介绍中国合成生物制造产业。",
                    "source": "ByDrug",
                    "date": "2026-06-17",
                    "source_query": "合成生物 白皮书 报告 发布",
                }],
            },
            {"round": "r2", "queries": ["q2"], "candidates": []},
            {"round": "r3", "queries": ["q3"], "candidates": []},
            {"round": "r4", "queries": ["q4"], "candidates": []},
            {"round": "r5", "queries": ["q5"], "candidates": []},
        ],
    }
    raw = report_pipeline.build_raw_from_search_log(log, report_date="2026-06-18")

    result = report_pipeline.validate_search_log(log, raw, strict_coverage=False)

    assert result["is_valid"], result["errors"]
    assert result["total_queries"] == 5
    assert raw["news"][0]["source_query"] == "合成生物 白皮书 报告 发布"


def test_validate_search_log_blocks_required_query_executed_false(monkeypatch):
    monkeypatch.setattr(report_pipeline, "load_search_query_config", lambda: {
        "rounds": [{"round_id": "r5", "required_queries": ["site:kw.beijing.gov.cn 合成生物"]}]
    })
    log = _search_log()
    _round(log, "r5")["queries"] = [{
        "query": "site:kw.beijing.gov.cn 合成生物",
        "executed": False,
        "error": "timeout",
    }]
    raw = {"news": [], "research": [], "funding": [], "policy": [], "events": []}

    result = report_pipeline.validate_search_log(log, raw, strict_coverage=True)

    assert not result["is_valid"]
    assert "必需查询未成功执行" in ";".join(result["errors"])
    assert "timeout" in ";".join(result["errors"])


def test_validate_search_log_blocks_required_query_marked_true_but_note_says_unexecuted(monkeypatch):
    monkeypatch.setattr(report_pipeline, "load_search_query_config", lambda: {
        "rounds": [{"round_id": "r5", "required_queries": ["site:kw.beijing.gov.cn 合成生物"]}]
    })
    log = _search_log()
    _round(log, "r5")["queries"] = [{
        "query": "site:kw.beijing.gov.cn 合成生物",
        "executed": True,
        "notes": "原始原因: 未执行（时间/资源限制）",
    }]
    raw = {
        "news": [
            _item(
                type="news",
                source_round="r1",
                source_query="synthetic biology funding",
            ),
            _item(
                type="news",
                title="Discovery",
                url="https://example.com/discovery",
                source_round="llm_discovery",
                source_query="broad discovery",
            )
        ],
        "research": [],
        "funding": [],
        "policy": [],
        "events": [],
    }

    result = report_pipeline.validate_search_log(log, raw, strict_coverage=True)

    assert not result["is_valid"]
    assert "未执行" in ";".join(result["errors"])


def test_validate_search_log_strict_blocks_manual_log_even_with_queries(monkeypatch):
    monkeypatch.setattr(report_pipeline, "load_search_query_config", lambda: {
        "rounds": [{"round_id": "r1", "required_queries": ["synthetic biology funding"]}]
    })
    log = _search_log()
    log.pop("generated_by")
    raw = {
        "news": [
            _item(
                type="news",
                title="Discovery",
                url="https://example.com/discovery",
                source_round="llm_discovery",
                source_query="broad discovery",
            )
        ],
        "research": [],
        "funding": [],
        "policy": [],
        "events": [],
    }

    result = report_pipeline.validate_search_log(
        log,
        raw,
        strict_coverage=True,
        search_strategy={"queries": [{"query": "recent synthetic biology discovery", "required": True}]},
    )

    assert not result["is_valid"]
    assert any("generated_by" in error for error in result["errors"])


def test_validate_search_log_strict_blocks_missing_high_recall_rounds(monkeypatch):
    monkeypatch.setattr(report_pipeline, "load_search_query_config", lambda: {
        "rounds": [{"round_id": "r1", "required_queries": ["synthetic biology funding"]}]
    })
    log = _search_log()
    log["rounds"] = [round_entry for round_entry in log["rounds"] if not round_entry["round"].startswith("llm_")]
    raw = {
        "news": [
            _item(
                type="news",
                title="Discovery",
                url="https://example.com/discovery",
                source_round="llm_discovery",
                source_query="broad discovery",
            )
        ],
        "research": [],
        "funding": [],
        "policy": [],
        "events": [],
    }

    result = report_pipeline.validate_search_log(
        log,
        raw,
        strict_coverage=True,
        search_strategy={"queries": [{"query": "synthetic biology funding", "required": True}]},
    )

    assert not result["is_valid"]
    assert any("高召回LLM搜索轮次" in error for error in result["errors"])


def test_validate_search_log_compatible_high_recall_accepts_tavily_structured_evidence(monkeypatch):
    monkeypatch.setattr(report_pipeline, "load_search_query_config", lambda: {
        "rounds": [{"round_id": "r1", "required_queries": ["synthetic biology funding"]}]
    })
    monkeypatch.setattr(report_pipeline, "validate_search_coverage", lambda *a, **k: {
        "is_valid": True,
        "errors": [],
        "warnings": [],
    })
    log = _search_log()
    log["high_recall_evidence_mode"] = "compatible"
    _round(log, "llm_discovery")["queries"] = [{
        "query": "broad discovery",
        "executed": True,
        "provider": "tavily",
        "searched_at": "2026-06-10T10:00:00+08:00",
        "results": [{"title": "Discovery", "url": "https://example.com/discovery"}],
        "result_count": 1,
    }]
    _round(log, "llm_gap_audit")["queries"] = [{
        "query": "gap audit",
        "executed": True,
        "provider": "tavily",
        "searched_at": "2026-06-10T10:00:05+08:00",
        "results": [],
        "result_count": 0,
    }]
    raw = {"news": [], "research": [], "funding": [], "policy": [], "events": []}

    result = report_pipeline.validate_search_log(
        log,
        raw,
        strict_coverage=True,
        search_strategy={"queries": [{"query": "synthetic biology funding", "required": True}]},
    )

    assert result["is_valid"], result["errors"]
    assert result["high_recall_check"]["evidence_mode"] == "compatible"


def test_validate_search_log_strict_high_recall_blocks_tavily_structured_evidence(monkeypatch):
    monkeypatch.setattr(report_pipeline, "load_search_query_config", lambda: {
        "rounds": [{"round_id": "r1", "required_queries": ["synthetic biology funding"]}]
    })
    log = _search_log()
    log["high_recall_evidence_mode"] = "strict"
    _round(log, "llm_discovery")["queries"] = [{
        "query": "broad discovery",
        "executed": True,
        "provider": "tavily",
        "searched_at": "2026-06-10T10:00:00+08:00",
        "results": [{"title": "Discovery", "url": "https://example.com/discovery"}],
        "result_count": 1,
    }]
    _round(log, "llm_gap_audit")["queries"] = [{
        "query": "gap audit",
        "executed": True,
        "provider": "tavily",
        "searched_at": "2026-06-10T10:00:05+08:00",
        "results": [],
        "result_count": 0,
    }]
    raw = {"news": [], "research": [], "funding": [], "policy": [], "events": []}

    result = report_pipeline.validate_search_log(
        log,
        raw,
        strict_coverage=True,
        search_strategy={"queries": [{"query": "synthetic biology funding", "required": True}]},
    )

    assert not result["is_valid"]
    assert any("必须使用llm_web" in error for error in result["errors"])


def test_validate_search_log_warns_when_required_query_config_missing(monkeypatch):
    monkeypatch.setattr(report_pipeline, "load_search_query_config", lambda: {})
    raw = {"news": [], "research": [], "funding": [], "policy": [], "events": []}

    result = report_pipeline.validate_search_log(_search_log(), raw)
    strict_result = report_pipeline.validate_search_log(_search_log(), raw, strict_coverage=True)

    assert result["is_valid"]
    assert any("搜索查询配置缺失" in warning for warning in result["warnings"])
    assert not strict_result["is_valid"]
    assert any("搜索查询配置缺失" in error for error in strict_result["errors"])


def test_search_query_config_covers_sciencenet_policy_terms():
    config = report_pipeline.load_search_query_config()
    queries = {
        query
        for round_cfg in config["rounds"]
        for query in round_cfg.get("required_queries", [])
    }

    assert "site:sciencenet.cn 合成生物 征求意见" in queries
    assert "site:sciencenet.cn 合成生物 申报指南" in queries
    assert "site:sciencenet.cn 合成生物 通知" in queries
    assert "site:sciencenet.cn 合成生物 国家重点研发计划" in queries


def test_search_query_config_covers_audited_company_and_vbdata_blindspots():
    config = report_pipeline.load_search_query_config()
    queries = {
        query
        for round_cfg in config["rounds"]
        for query in round_cfg.get("required_queries", [])
    }

    assert "site:vbdata.cn 生物制造" in queries
    assert "site:vbdata.cn 元英进" in queries
    assert "动脉网 生物制造 死亡谷" in queries
    assert "生物制造 死亡谷 落地" in queries
    assert "上市公司 生物制造 项目 公告" in queries
    assert "发酵 辅酶Q10 项目 公告" in queries


def test_extract_page_verified_date_uses_search_date_to_ignore_related_story_dates():
    html = """
    <html><body>
      <h1>元英进院士：跨越“死亡谷”，生物制造拼的不再是概念而是落地</h1>
      高康平 2026-06-26 21:53
      <p>在2026生物制造大赛启动仪式上发布产业化观察。</p>
      <aside>从规模优势到系统破局：中国生物制造为何需要一场大赛？ 2026-06-01</aside>
    </body></html>
    """

    result = report_pipeline.extract_page_verified_date(html, search_date="2026-06-26")

    assert result["verified_date"] == "2026-06-26"
    assert result["source"] == "body_context"


def test_extract_page_verified_date_falls_back_when_page_dates_do_not_match_search_date():
    html = """
    <html><body>
      <h1>金河生物5.5亿元新项目落地</h1>
      <aside>金河生物子公司获得新兽药注册证书 2026-01-13</aside>
      <aside>金河生物发布业绩预告 2026-01-31</aside>
    </body></html>
    """

    result = report_pipeline.extract_page_verified_date(html, search_date="2026-06-26")

    assert result["verified_date"] == "2026-06-26"
    assert result["source"] == "search_fallback"
    assert result["confidence"] == "low"
    assert "warning" in result


def test_extract_page_verified_date_rejects_far_future_placeholder_date():
    html = """
    <html><body>
      <h1>招商银行：生物制造系列报告①——把握合成生物发展趋势</h1>
      <p>版权所有 2099-10-10</p>
      <p>动脉智库 2025-02-06 17:30</p>
    </body></html>
    """

    result = report_pipeline.extract_page_verified_date(html, search_date="2026-07-03")

    assert result["verified_date"] == "2026-07-03"
    assert result["source"] == "search_fallback"


def test_validate_report_structure_forbidden_section_check_only_scans_headings(tmp_path):
    report = tmp_path / "report.md"
    report.write_text(
        """# 合成生物行业日报 — 2026-06-27

## 📌 执行摘要

1. **华恒生物动态**：公司尚未知悉调查的进展。（2026-06-25）

## 📰 行业热点新闻

| 标题 | 来源 | 时间 | 摘要 | 链接 |
|------|------|------|------|------|
| 华恒生物动态 | STCN | 2026-06-25 | 公司尚未知悉调查的进展。 | https://example.com/a |

## 🔬 最新研究成果

| 标题 | 期刊/机构 | 核心发现 | 链接 |
|------|----------|----------|------|
| 经五轮检索，本周期暂无相关新信息收录。 | — | — | — |

## 💰 融资与投资动态

| 公司 | 轮次 | 金额 | 投资方 | 时间 | 链接 |
|------|------|------|--------|------|------|
| 经五轮检索，本周期暂无相关新信息收录。 | — | — | — | — | — |

## 🏛️ 政策与监管

### 国内政策

| 政策/法规 | 发布机构 | 时间 | 核心内容 | 链接 |
|-----------|----------|------|----------|------|
| 经五轮检索，本周期暂无相关新信息收录。 | — | — | — | — |

### 国际监管动态

经五轮检索，本周期暂无相关新信息收录。

## 📅 行业活动预告

| 活动名称 | 时间 | 地点 | 亮点 | 链接 |
|----------|------|------|------|------|
| 经五轮检索，本周期暂无相关新信息收录。 | — | — | — | — |

## 🤖 AI 深度分析

### 趋势研判

仅基于正文已收录信息进行归纳。

### 竞争格局变化

仅基于正文已收录信息进行归纳。

### 风险提示

1. 链接可访问性仍需验证。

## 📎 附录

1. https://example.com/a
""",
        encoding="utf-8",
    )

    result = report_pipeline.validate_report_structure(str(report))

    assert not any("禁止的额外板块" in error for error in result["errors"])


def test_build_raw_from_search_log_keeps_whitepaper_result():
    log = _search_log()
    log["rounds"][0]["queries"] = [{
        "query": "合成生物 白皮书 报告 发布",
        "results": [{
            "title": "2026中国合成生物制造白皮书发布",
            "url": "https://bydrug.pharmcube.com/news/detail/whitepaper-2026",
            "snippet": "该白皮书系统介绍了中国合成生物制造产业的发展阶段、核心技术平台与产业化趋势。",
            "source": "ByDrug",
            "date": "2026-06-17",
        }],
    }]

    raw = report_pipeline.build_raw_from_search_log(log, report_date="2026-06-18")

    assert len(raw["news"]) == 1
    assert raw["news"][0]["title"] == "2026中国合成生物制造白皮书发布"
    assert raw["news"][0]["source_round"] == "r1"
    assert raw["news"][0]["source_query"] == "合成生物 白皮书 报告 发布"


def test_build_raw_from_search_log_classifies_authority_research_program_as_policy():
    log = _search_log()
    log["rounds"][0]["queries"] = [{
        "query": "合成生物 政策 申报 指南",
        "results": [
            {
                "title": "国家重点研发计划合成生物学重点专项申报指南征求意见",
                "url": "https://www.most.gov.cn/tztg/202606/t1.html",
                "snippet": "科技部发布项目申报指南，涉及合成生物学重点专项。",
                "source": "科技部",
                "date": "2026-06-17",
            },
            {
                "title": "深圳市合成生物研究设施开放共享若干措施发布",
                "url": "https://fgw.sz.gov.cn/zwgk/qt/tzgg/content/post_1.html",
                "snippet": "深圳市发改委发布合成生物研究设施开放共享政策措施。",
                "source": "深圳市发改委",
                "date": "2026-06-17",
            },
        ],
    }]

    raw = report_pipeline.build_raw_from_search_log(log, report_date="2026-06-18")

    assert [item["title"] for item in raw["policy"]] == [
        "国家重点研发计划合成生物学重点专项申报指南征求意见",
        "深圳市合成生物研究设施开放共享若干措施发布",
    ]
    assert not raw["research"]


def test_normalize_search_result_date_does_not_invent_missing_dates():
    assert report_pipeline.normalize_search_result_date("", report_date="2026-06-18") == "N/A"
    assert report_pipeline.normalize_search_result_date("3天前", report_date="2026-06-18") == "2026-06-15"
    assert report_pipeline.normalize_search_result_date("yesterday", report_date="2026-06-18") == "2026-06-17"


def test_validate_search_coverage_warns_when_search_result_missing_from_raw():
    log = _search_log()
    log["rounds"][0]["queries"] = [{
        "query": "合成生物 白皮书",
        "results": [{
            "title": "2026中国合成生物制造白皮书发布",
            "url": "https://bydrug.pharmcube.com/news/detail/whitepaper-2026",
            "snippet": "白皮书系统介绍中国合成生物制造产业。",
            "source": "ByDrug",
            "date": "2026-06-17",
        }],
    }]
    raw = {"news": [], "research": [], "funding": [], "policy": [], "events": []}

    result = report_pipeline.validate_search_log(log, raw)
    strict_result = report_pipeline.validate_search_log(log, raw, strict_coverage=True)

    assert result["is_valid"]
    assert any("搜索覆盖率不足" in warning for warning in result["warnings"])
    assert not strict_result["is_valid"]
    assert any("搜索覆盖率不足" in error for error in strict_result["errors"])


def test_validate_search_coverage_blocks_raw_without_search_evidence():
    log = _search_log()
    log["rounds"][0]["candidates"] = []
    raw = {
        "news": [
            _item(
                type="news",
                source_round="r1",
                url="https://example.com/news/manual-only",
            )
        ],
        "research": [],
        "funding": [],
        "policy": [],
        "events": [],
    }

    result = report_pipeline.validate_search_log(log, raw)
    strict_result = report_pipeline.validate_search_log(log, raw, strict_coverage=True)

    assert result["is_valid"]
    assert any("raw无搜索证据1条" in warning for warning in result["warnings"])
    assert not strict_result["is_valid"]
    assert any("raw无搜索证据1条" in error for error in strict_result["errors"])
    assert strict_result["coverage_check"]["untraced_raw_urls"] == [
        "https://example.com/news/manual-only"
    ]


def test_build_approved_blocks_search_coverage_gap(tmp_path, monkeypatch):
    monkeypatch.setattr(report_pipeline, "load_historical_events", lambda days=30: {})
    monkeypatch.setattr(report_pipeline, "_load_history_index", lambda: [])
    monkeypatch.setattr(report_pipeline, "load_search_query_config", lambda: {})
    log = _search_log()
    log["rounds"][0]["queries"] = [{
        "query": "合成生物 白皮书",
        "results": [{
            "title": "2026中国合成生物制造白皮书发布",
            "url": "https://bydrug.pharmcube.com/news/detail/whitepaper-2026",
            "snippet": "白皮书系统介绍中国合成生物制造产业。",
            "source": "ByDrug",
            "date": "2026-06-17",
        }],
    }]
    raw = {"news": [], "research": [], "funding": [], "policy": [], "events": []}

    try:
        report_pipeline.build_approved_from_raw(
            raw,
            "2026-06-18",
            output_dir=tmp_path,
            search_log=log,
            search_strategy={"queries": []},
            check_url_health_enabled=False,
            check_title_match_enabled=False,
        )
    except ValueError as exc:
        assert "搜索覆盖率不足" in str(exc)
    else:
        raise AssertionError("strict search coverage should block missing raw candidates")


def test_build_approved_defaults_to_strict_required_query_gate(tmp_path, monkeypatch):
    monkeypatch.setattr(report_pipeline, "load_historical_events", lambda days=30: {})
    monkeypatch.setattr(report_pipeline, "_load_history_index", lambda: [])
    monkeypatch.setattr(report_pipeline, "load_search_query_config", lambda: {
        "rounds": [{"round_id": "r5", "required_queries": ["site:kw.beijing.gov.cn 合成生物"]}]
    })
    raw = {"news": [], "research": [], "funding": [], "policy": [], "events": []}

    try:
        report_pipeline.build_approved_from_raw(
            raw,
            "2026-06-18",
            output_dir=tmp_path,
            search_log=_search_log(),
            search_strategy={"queries": []},
            check_url_health_enabled=False,
            check_title_match_enabled=False,
        )
    except ValueError as exc:
        assert "site:kw.beijing.gov.cn 合成生物" in str(exc)
    else:
        raise AssertionError("build-approved should enforce required query coverage by default")


def test_build_approved_enforces_required_query_gate_strictly(tmp_path, monkeypatch):
    monkeypatch.setattr(report_pipeline, "load_historical_events", lambda days=30: {})
    monkeypatch.setattr(report_pipeline, "_load_history_index", lambda: [])
    monkeypatch.setattr(report_pipeline, "load_search_query_config", lambda: {
        "rounds": [{"round_id": "r5", "required_queries": ["site:kw.beijing.gov.cn 合成生物"]}]
    })
    raw = {"news": [], "research": [], "funding": [], "policy": [], "events": []}

    try:
        report_pipeline.build_approved_from_raw(
            raw,
            "2026-06-18",
            output_dir=tmp_path,
            search_log=_search_log(),
            search_strategy={"queries": []},
            check_url_health_enabled=False,
            check_title_match_enabled=False,
        )
    except ValueError as exc:
        assert "site:kw.beijing.gov.cn 合成生物" in str(exc)
    else:
        raise AssertionError("build-approved must always enforce required query coverage; no relaxation allowed")


def test_report_pipeline_cli_build_raw_from_search(tmp_path):
    search_log = _search_log()
    search_log["rounds"][0]["queries"] = [{
        "query": "合成生物 白皮书 报告 发布",
        "results": [{
            "title": "2026中国合成生物制造白皮书发布",
            "url": "https://bydrug.pharmcube.com/news/detail/whitepaper-2026",
            "snippet": "该白皮书系统介绍了中国合成生物制造产业的发展阶段、核心技术平台与产业化趋势。",
            "source": "ByDrug",
            "date": "2026-06-17",
        }],
    }]
    search_path = tmp_path / "search_log.json"
    output = tmp_path / "raw.json"
    search_path.write_text(json.dumps(search_log, ensure_ascii=False), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "report_pipeline.py"),
            "--build-raw-from-search",
            str(search_path),
            "--date",
            "2026-06-18",
            "--output",
            str(output),
        ],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
    )

    assert result.returncode == 0, result.stderr
    raw = json.loads(output.read_text(encoding="utf-8"))
    assert raw["news"][0]["title"] == "2026中国合成生物制造白皮书发布"


def test_build_approved_blocks_invalid_search_log(tmp_path, monkeypatch):
    monkeypatch.setattr(report_pipeline, "load_historical_events", lambda days=30: {})
    monkeypatch.setattr(report_pipeline, "_load_history_index", lambda: [])
    monkeypatch.setattr(report_pipeline, "load_search_query_config", lambda: {
        "rounds": [{"round_id": "r1", "required_queries": ["synthetic biology funding"]}]
    })
    raw = {
        "news": [_item(type="news", source_round="r999")],
        "research": [],
        "funding": [],
        "policy": [],
        "events": [],
    }

    try:
        report_pipeline.build_approved_from_raw(
            raw,
            "2026-06-10",
            output_dir=tmp_path,
            search_log=_search_log(),
            search_strategy={"queries": [{"query": "recent synthetic biology discovery", "required": True}]},
            check_url_health_enabled=False,
            check_title_match_enabled=False,
        )
    except ValueError as exc:
        assert "search_log校验失败" in str(exc)
        assert "search_log invalid" in str(exc)
        assert "未记录的source_round" in str(exc)
    else:
        raise AssertionError("invalid search_log should fail build-approved")


def test_build_approved_requires_search_strategy_with_search_log(tmp_path, monkeypatch):
    monkeypatch.setattr(report_pipeline, "load_historical_events", lambda days=30: {})
    monkeypatch.setattr(report_pipeline, "_load_history_index", lambda: [])
    raw = {"news": [], "research": [], "funding": [], "policy": [], "events": []}

    try:
        report_pipeline.build_approved_from_raw(
            raw,
            "2026-06-10",
            output_dir=tmp_path,
            search_log=_search_log(),
            check_url_health_enabled=False,
            check_title_match_enabled=False,
        )
    except ValueError as exc:
        assert "LLM搜索策略缺失" in str(exc)
    else:
        raise AssertionError("search_log without same-day search_strategy should fail closed")


def test_process_raw_data_rejects_missing_required_fields_and_backfills_type(monkeypatch):
    monkeypatch.setattr(report_pipeline, "load_historical_events", lambda days=30: {})
    result = report_pipeline.process_raw_data([
        _item(type=""),
        _item(title="", url="https://example.com/news/missing-title"),
    ], "news")

    assert result["stats"]["approved"] == 1
    assert result["stats"]["schema_rejected"] == 1
    assert result["approved"][0]["type"] == "news"


def test_process_raw_data_rejects_type_category_mismatch(monkeypatch):
    monkeypatch.setattr(report_pipeline, "load_historical_events", lambda days=30: {})
    result = report_pipeline.process_raw_data([
        _item(type="policy"),
    ], "news")

    assert result["stats"]["approved"] == 0
    assert result["stats"]["schema_rejected"] == 1
    assert "type mismatch" in result["rejected"][0]["reason"]


def test_process_raw_data_reclassifies_event_before_rejecting(monkeypatch):
    monkeypatch.setenv("SYNBIO_DAILY_NOW", "2026-06-29T12:00:00+08:00")
    monkeypatch.setattr(report_pipeline, "load_historical_events", lambda days=30: {})
    monkeypatch.setattr(report_pipeline, "_load_history_index", lambda: [])
    monkeypatch.setattr(report_pipeline, "_load_sent_url_registry", lambda: {"version": 1, "registry": {}})
    result = report_pipeline.process_raw_data([
        _item(
            title="2026 Synthetic Biology: Engineering, Evolution, & Design (SEED)",
            source="synbioconference.org",
            date="2026-06-15",
            summary="Synthetic biology conference and meeting.",
            url="https://synbioconference.org/2026",
            type="funding",
        )
    ], "funding")

    assert result["stats"]["approved"] == 0
    assert result["stats"]["schema_rejected"] == 0
    assert result["rejected"][0]["item"]["type"] == "events"
    assert result["rejected"][0]["item"]["reclassified_from"] == "funding"


def test_process_raw_data_reclassifies_old_stock_concept_as_news(monkeypatch):
    monkeypatch.setenv("SYNBIO_DAILY_NOW", "2026-06-29T12:00:00+08:00")
    monkeypatch.setattr(report_pipeline, "load_historical_events", lambda days=30: {})
    monkeypatch.setattr(report_pipeline, "_load_history_index", lambda: [])
    monkeypatch.setattr(report_pipeline, "_load_sent_url_registry", lambda: {"version": 1, "registry": {}})
    result = report_pipeline.process_raw_data([
        _item(
            title="概念动态|华宝股份新增“合成生物”概念",
            source="同花顺iNews",
            date="2026-06-18",
            summary="公司已选定核心品类推进合成生物学战略落地。",
            url="https://m.10jqka.com.cn/20260618/c677569597.shtml",
            type="funding",
        )
    ], "funding")

    assert result["stats"]["approved"] == 0
    assert result["stats"]["schema_rejected"] == 0
    assert result["rejected"][0]["item"]["type"] == "news"
    assert "[时效性]" in result["rejected"][0]["reason"]


def test_process_raw_data_reclassifies_recoded_ecoli_as_research(monkeypatch):
    monkeypatch.setenv("SYNBIO_DAILY_NOW", "2026-06-29T12:00:00+08:00")
    monkeypatch.setattr(report_pipeline, "load_historical_events", lambda days=30: {})
    result = report_pipeline.process_raw_data([
        _item(
            title="Recoded E. coli Promises More Scalable Weight Loss Drug Production",
            source="GEN",
            date="2026-06-24",
            summary="...",
            url="https://example.com/research/recoded-ecoli-glp1",
            type="news",
            source_query="site:genengnews.com synthetic biology biomanufacturing",
        )
    ], "news")

    assert result["stats"]["approved"] == 1
    assert result["approved"][0]["type"] == "research"
    assert result["approved"][0]["reclassified_from"] == "news"


def test_process_raw_data_rejects_policy_bucket_non_policy_content(monkeypatch):
    monkeypatch.setattr(report_pipeline, "load_historical_events", lambda days=30: {})
    result = report_pipeline.process_raw_data([
        _item(
            title="SynBioBeta: 2025 Investment Report",
            summary="2024年全年合成生物学融资122亿美元，Q4融资43亿美元。",
            url="https://www.synbiobeta.com/reports/2024-investment-report",
            source="政府公告/政策文件",
            type="policy",
        ),
        _item(
            title="北京市科委：征集2026年度合成生物制造领域储备课题",
            summary="支持方向包括合成生物学元件智能设计，申报截止6月22日。",
            url="https://kw.beijing.gov.cn/zwgk/zcwj/202606/t20260601_4680315.html",
            source="北京市科委",
            type="policy",
        ),
    ], "policy")

    assert result["stats"]["approved"] == 1
    assert result["stats"]["schema_rejected"] == 0
    assert result["stats"]["content_type_rejected"] == 1
    assert "市场研究" in result["rejected"][0]["reason"]


def test_policy_classifier_allows_gov_cn_plan_report_and_association_repost(monkeypatch):
    monkeypatch.setattr(report_pipeline, "load_historical_events", lambda days=30: {})
    result = report_pipeline.process_raw_data([
        _item(
            title="深圳市计划报告：合成生物研究等重大科技设施投用并开放共享",
            summary="深圳市发展和改革委员会发布计划报告，披露合成生物研究重大科技设施投用并开放共享。",
            url="https://fgw.sz.gov.cn/zwgk/ghjh/202606/t20260615_123456.htm",
            source="深圳市发展和改革委员会",
            type="policy",
        ),
        _item(
            title="武汉市启动2026年度重点研发计划（合成生物领域）申报",
            summary="武汉市高新技术产业协会转载重点研发计划申报通知，面向合成生物领域项目征集。",
            url="https://www.whht.org.cn/news/2026-synbio-plan",
            source="武汉市高新技术产业协会",
            type="policy",
        ),
    ], "policy")

    assert result["stats"]["approved"] == 2
    assert not result["rejected"]


def test_policy_classifier_allows_gov_cn_measures(monkeypatch):
    monkeypatch.setattr(report_pipeline, "load_historical_events", lambda days=30: {})
    result = report_pipeline.process_raw_data([
        _item(
            title="深圳市推动合成生物创新引领生物制造产业高质量发展若干措施",
            summary="深圳市政府发布若干措施，支持合成生物创新引领生物制造产业高质量发展。",
            url="https://fgw.sz.gov.cn/zwgk/zcwj/202606/t20260617_123456.htm",
            source="深圳市发展和改革委员会",
            type="policy",
        )
    ], "policy")

    assert result["stats"]["approved"] == 1
    assert not result["rejected"]


def test_process_raw_data_rejects_url_attribute_injection(monkeypatch):
    monkeypatch.setattr(report_pipeline, "load_historical_events", lambda days=30: {})
    result = report_pipeline.process_raw_data([
        _item(url='https://example.com" onmouseover="alert(1)'),
    ], "news")

    assert result["stats"]["approved"] == 0
    assert result["stats"]["schema_rejected"] == 1


def test_category_filter_allows_article_paths_and_blocks_aggregate_pages():
    assert not report_pipeline._is_category_or_aggregate_url("https://example.com/news/yeast-platform")
    assert not report_pipeline._is_category_or_aggregate_url("https://example.com/news-and-features/yeast-platform")
    assert not report_pipeline._is_category_or_aggregate_url("https://example.com/events/synbio-forum-2026")
    assert not report_pipeline._is_category_or_aggregate_url("https://example.com/article/123?q=source")
    assert not report_pipeline._is_category_or_aggregate_url("https://mp.weixin.qq.com/s/example-article")
    assert not report_pipeline._is_category_or_aggregate_url(
        "https://www.genengnews.com/topics/bioprocessing/recoded-e-coli-promises-more-scalable-weight-loss-drug-production/"
    )
    assert not report_pipeline._is_category_or_aggregate_url("https://isynbio.siat.ac.cn/siat/2026-06/18/article_2026061810313229176.html")
    assert not report_pipeline._is_category_or_aggregate_url("https://synbio.suat-sz.edu.cn/index/zxcg.htm")
    assert not report_pipeline._is_category_or_aggregate_url("https://example.edu.cn/research/publications.html")
    assert not report_pipeline._is_category_or_aggregate_url("https://example.ac.cn/papers.html")
    assert report_pipeline._is_category_or_aggregate_url("https://example.com/news")
    assert report_pipeline._is_category_or_aggregate_url("https://www.genengnews.com/topics/bioprocessing/")
    assert report_pipeline._is_category_or_aggregate_url("https://isynbio.siat.ac.cn/")
    assert report_pipeline._is_category_or_aggregate_url("https://isynbio.siat.ac.cn/index.html")
    assert report_pipeline._is_category_or_aggregate_url("https://example.com/category/synthetic-biology")
    assert report_pipeline._is_category_or_aggregate_url("https://example.com/topic-hub/synthetic-biology/news-and-features")
    assert report_pipeline._is_category_or_aggregate_url("https://conferences.nature.com/synthetic-biology")
    assert report_pipeline._is_category_or_aggregate_url("https://example.com/search?q=synthetic-biology")


def test_process_raw_data_rejects_history_index_duplicates(monkeypatch):
    monkeypatch.setattr(report_pipeline, "load_historical_events", lambda days=30: {})
    monkeypatch.setattr(report_pipeline, "_load_history_index", lambda: [{
        "url": "https://example.com/news/yeast-platform",
        "title": "Novel yeast platform improves fermentation",
        "fingerprint": report_pipeline._make_fingerprint(_item()),
        "first_sent_date": "2026-06-09",
    }])

    result = report_pipeline.process_raw_data([
        _item(url="https://example.com/news/yeast-platform?utm_source=newsletter"),
    ], "news")

    assert result["stats"]["approved"] == 0
    assert result["stats"]["duplicate_rejected"] == 1
    assert "[历史索引去重]" in result["rejected"][0]["reason"]


def test_collect_approved_urls_accepts_string_urls_field():
    urls = report_pipeline.collect_approved_urls([{
        "url": "https://example.com/news/primary",
        "urls": "https://example.com/news/secondary",
    }])

    assert urls == [
        "https://example.com/news/primary",
        "https://example.com/news/secondary",
    ]


def test_history_index_duplicate_checks_secondary_urls(monkeypatch):
    monkeypatch.setattr(report_pipeline, "load_historical_events", lambda days=30: {})
    monkeypatch.setattr(report_pipeline, "_load_history_index", lambda: [{
        "url": "https://example.com/news/primary",
        "urls": ["https://example.com/news/secondary"],
        "title": "Different visible title",
        "fingerprint": "unrelated",
        "first_sent_date": "2026-06-09",
    }])

    result = report_pipeline.process_raw_data([
        _item(
            title="Fresh rewrite around the same sourced story",
            url="https://example.com/news/secondary?utm_source=newsletter",
        ),
    ], "news")

    assert result["stats"]["approved"] == 0
    assert result["stats"]["duplicate_rejected"] == 1
    assert "[历史索引去重]" in result["rejected"][0]["reason"]


def test_history_duplicate_uses_article_url_identity_for_36kr(monkeypatch):
    monkeypatch.setattr(report_pipeline, "load_historical_events", lambda days=30: {})
    monkeypatch.setattr(report_pipeline, "_load_sent_url_registry", lambda: {"version": 1, "registry": {}})
    monkeypatch.setattr(report_pipeline, "_load_history_index", lambda: [{
        "url": "https://36kr.com/p/3051114996943496",
        "title": "旧标题",
        "fingerprint": "unrelated",
        "first_sent_date": "2026-06-09",
    }])

    result = report_pipeline.process_raw_data([
        _item(
            title="方昕博士解读生物制造产业落地：四城市政策对比",
            summary="方昕博士讨论合成生物与生物制造产业落地。",
            url="https://www.36kr.com/p/3051114996943496?utm_source=newsletter",
        ),
    ], "news")

    assert result["stats"]["approved"] == 0
    assert result["stats"]["duplicate_rejected"] == 1
    assert "[历史索引去重]" in result["rejected"][0]["reason"]


def test_sent_url_registry_blocks_changed_title_duplicate(monkeypatch):
    monkeypatch.setattr(report_pipeline, "load_historical_events", lambda days=30: {})
    monkeypatch.setattr(report_pipeline, "_load_history_index", lambda: [])
    monkeypatch.setattr(report_pipeline, "_load_sent_url_registry", lambda: {
        "version": 1,
        "registry": {
            "36kr:p:3051114996943496": {
                "first_sent_date": "2026-06-09",
                "title": "从实验室到应用场！方昕博士解读生物制造产业落地与投资逻辑",
            }
        },
    })

    result = report_pipeline.process_raw_data([
        _item(
            title="方昕博士解读生物制造产业落地：四城市政策对比",
            summary="合成生物和生物制造产业落地相关内容。",
            url="https://www.36kr.com/p/3051114996943496",
        ),
    ], "news")

    assert result["stats"]["approved"] == 0
    assert result["stats"]["duplicate_rejected"] == 1


def test_process_raw_data_deduplicates_current_batch(monkeypatch):
    monkeypatch.setattr(report_pipeline, "load_historical_events", lambda days=30: {})
    result = report_pipeline.process_raw_data([
        _item(title="Synthetic Bio Company Raises Series A", url="https://example.com/a"),
        _item(title="Synthetic Bio Company Raises Series A!", url="https://example.com/b"),
    ], "news")

    assert result["stats"]["approved"] == 1
    assert result["stats"]["duplicate_rejected"] == 1


def test_value_score_is_normalized_to_0_10(monkeypatch):
    monkeypatch.setattr(report_pipeline, "load_historical_events", lambda days=30: {})
    result = report_pipeline.process_raw_data([_item()], "news")

    assert result["approved"]
    assert 0 <= result["approved"][0]["value_score"] <= 10
    assert "raw_score" in result["approved"][0]


def test_process_raw_data_rejects_market_report_from_main_news(monkeypatch):
    monkeypatch.setattr(report_pipeline, "load_historical_events", lambda days=30: {})
    monkeypatch.setattr(report_pipeline, "_load_history_index", lambda: [])
    monkeypatch.setattr(report_pipeline, "_load_sent_url_registry", lambda: {"version": 1, "registry": {}})

    result = report_pipeline.process_raw_data([
        _item(
            title="Synthetic Biology Market Analysis Report 2026-2034",
            summary="The market research report reviews 2024 market size, 2025 share and 2026-2034 CAGR forecast.",
            url="https://www.polarismarketresearch.com/synthetic-biology-market",
        ),
    ], "news")

    assert result["stats"]["approved"] == 0
    assert result["stats"]["content_type_rejected"] == 1
    assert "[内容类型]" in result["rejected"][0]["reason"]


def test_report_pipeline_cli_process_accepts_full_raw_dict(tmp_path, monkeypatch):
    output = tmp_path / "news_processed.json"
    env = dict(**__import__("os").environ, SYNBIO_DAILY_HOME=str(tmp_path))
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "report_pipeline.py"),
            "--process",
            str(ROOT / "tests" / "fixtures" / "raw_full.json"),
            "--type",
            "news",
            "--output",
            str(output),
        ],
        cwd=ROOT,
        env=env,
        text=True,
        encoding="utf-8",
        capture_output=True,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["stats"]["total_input"] == 3
    assert payload["stats"]["schema_rejected"] == 1


def test_report_pipeline_cli_validate_exits_nonzero_on_ai_errors(tmp_path):
    output = tmp_path / "validation.json"
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "report_pipeline.py"),
            "--validate",
            str(ROOT / "tests" / "fixtures" / "invalid_ai_report.md"),
            "--output",
            str(output),
        ],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
    )

    assert result.returncode == 1
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert not payload["passed"]
    assert "ai_check" in payload


def _write_full_validate_inputs(tmp_path, report_name="valid_report.md", email_name="full_valid_email.html", approved_date="2026-06-10"):
    approved = tmp_path / "approved.json"
    approved.write_text(json.dumps([{
        "title": "星河生物完成数千万元 pre-A 轮融资",
        "source": "SynBioBeta",
        "url": "https://example.com/news/xinghe",
        "summary": "星河生物完成数千万元 pre-A 轮融资，用于合成生物制造平台扩产。",
        "type": "news",
        "date": approved_date,
        "raw_score": 18,
        "value_score": 6.0,
        "llm_relevance": {
            "is_approved": True,
            "domain_relevance": "core_synbio",
            "confidence": 0.9,
            "reason": "含合成生物制造平台扩产证据",
            "evidence_spans": ["合成生物制造平台扩产"],
            "section": "news",
            "provider": "llm-test",
        },
        "domain_relevance": "core_synbio",
        "confidence": 0.9,
    }], ensure_ascii=False), encoding="utf-8")
    email = tmp_path / email_name
    email.write_text(
        '<span class="num">1</span><span class="num">2</span><span class="num">3</span><span class="num">4</span><span class="num">5</span>'
        '<div class="card-title">星河生物完成数千万元 pre-A 轮融资</div>'
        '<a href="https://example.com/news/xinghe">查看</a>',
        encoding="utf-8",
    )
    return approved, email, ROOT / "tests" / "fixtures" / report_name


def test_report_pipeline_cli_full_validate_valid_exits_zero(tmp_path):
    approved, email, report = _write_full_validate_inputs(tmp_path)
    output = tmp_path / "full_validation.json"
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "report_pipeline.py"),
            "--full-validate",
            str(report),
            "--email",
            str(email),
            "--approved",
            str(approved),
            "--output",
            str(output),
        ],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
    )

    assert output.exists()
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert "ai_check" in payload
    assert result.returncode == 0


def test_report_pipeline_cli_full_validate_invalid_exits_nonzero(tmp_path):
    approved, email, report = _write_full_validate_inputs(tmp_path, report_name="invalid_ai_report.md")
    output = tmp_path / "full_validation.json"
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "report_pipeline.py"),
            "--full-validate",
            str(report),
            "--email",
            str(email),
            "--approved",
            str(approved),
            "--output",
            str(output),
        ],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
    )

    assert output.exists()
    assert result.returncode == 1


def test_run_full_validation_blocks_approved_type_timeliness():
    report = str(ROOT / "tests" / "fixtures" / "valid_report.md")
    email = '<span class="num">1</span><span class="num">2</span><span class="num">3</span><span class="num">4</span><span class="num">5</span><div class="card-title">星河生物完成数千万元 pre-A 轮融资</div><a href="https://example.com/news/xinghe">查看</a>'
    approved = [{
        "title": "星河生物完成数千万元 pre-A 轮融资",
        "source": "SynBioBeta",
        "url": "https://example.com/news/xinghe",
        "summary": "星河生物完成数千万元 pre-A 轮融资，用于合成生物制造平台扩产。",
        "type": "news",
        "date": "2026-05-01",
        "raw_score": 18,
        "value_score": 6.0,
    }]

    result = report_pipeline.run_full_validation(report, email, approved)

    assert not result["can_send_email"]
    assert result["approved_timeliness_check"]["has_errors"]


def test_run_full_validation_blocks_empty_approved():
    report = str(ROOT / "tests" / "fixtures" / "valid_report.md")
    email = '<span class="num">0</span>'

    result = report_pipeline.run_full_validation(report, email, [])

    assert not result["can_send_email"]
    assert not result["approved_llm_trace_check"]["is_valid"]
    assert any("approved为空" in item for item in result["fix_instructions"])


def test_run_full_validation_blocks_missing_llm_trace():
    report = str(ROOT / "tests" / "fixtures" / "valid_report.md")
    email = '<span class="num">1</span><span class="num">2</span><span class="num">3</span><span class="num">4</span><span class="num">5</span><div class="card-title">星河生物完成数千万元 pre-A 轮融资</div><a href="https://example.com/news/xinghe">查看</a>'
    approved = [{
        "title": "星河生物完成数千万元 pre-A 轮融资",
        "source": "SynBioBeta",
        "url": "https://example.com/news/xinghe",
        "summary": "星河生物完成数千万元 pre-A 轮融资，用于合成生物制造平台扩产。",
        "type": "news",
        "date": "2026-06-10",
        "raw_score": 18,
        "value_score": 6.0,
    }]

    result = report_pipeline.run_full_validation(report, email, approved)

    assert not result["can_send_email"]
    assert any("缺少LLM领域审计痕迹" in item for item in result["fix_instructions"])


def test_validate_approved_date_verification_blocks_search_fallback():
    result = report_pipeline.validate_approved_date_verification([{
        "title": "合成生物产业园开园",
        "source": "测试源",
        "date": "2026-07-01",
        "summary": "合成生物产业园开园。",
        "url": "https://example.com/news/park",
        "type": "news",
        "source_round": "r1",
        "source_query": "合成生物 产业园",
        "date_verification": {
            "verified_date": "2026-07-01",
            "confidence": "low",
            "source": "search_fallback",
        },
    }])

    assert not result["is_valid"]
    assert "搜索日期兜底" in ";".join(result["errors"])


def test_validate_approved_schema_blocks_bad_urls_and_type_mismatch():
    approved = [
        {
            "title": "Technology Networks synthetic biology news hub",
            "source": "Technology Networks",
            "date": "2026-06-10",
            "summary": "Synthetic biology news listing page.",
            "url": "https://www.technologynetworks.com/tn/topic-hub/synthetic-biology/news-and-features",
            "type": "news",
            "raw_score": 10,
            "value_score": 3.3,
        },
        {
            "title": "EMBL Synthetic Biology Courses",
            "source": "EMBL",
            "date": "2026-06-10",
            "summary": "Synthetic biology course catalogue.",
            "url": "https://ecampus.embl.de/course/index.php?categoryid=43",
            "type": "policy",
            "raw_score": 10,
            "value_score": 3.3,
        },
        {
            "title": "Different title on same URL",
            "source": "Nature",
            "date": "2026-06-10",
            "summary": "Another story using the same URL.",
            "url": "https://www.technologynetworks.com/tn/topic-hub/synthetic-biology/news-and-features",
            "type": "news",
            "raw_score": 10,
            "value_score": 3.3,
        },
    ]

    result = report_pipeline.validate_approved_schema(approved)

    assert not result["is_valid"]
    assert any("聚合页" in error for error in result["errors"])
    assert any("类别错配" in error for error in result["errors"])
    assert any("URL重复" in error for error in result["errors"])


def test_report_pipeline_cli_build_approved_generates_outputs(tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "report_pipeline.py"),
            "--build-approved",
            str(ROOT / "tests" / "fixtures" / "raw_full.json"),
            "--date",
            "2026-06-10",
            "--output",
            str(tmp_path),
            "--skip-url-health",
            "--skip-title-match",
        ],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
    )

    assert result.returncode == 0, result.stderr + result.stdout
    approved = json.loads((tmp_path / "approved_2026-06-10.json").read_text(encoding="utf-8"))
    rejected = json.loads((tmp_path / "rejected_2026-06-10.json").read_text(encoding="utf-8"))
    assert approved
    assert rejected
    assert (tmp_path / "processed_news_2026-06-10.json").exists()


def test_build_approved_drops_conflicting_same_url_titles(tmp_path, monkeypatch):
    monkeypatch.setattr(report_pipeline, "load_historical_events", lambda days=30: {})
    monkeypatch.setattr(report_pipeline, "_load_history_index", lambda: [])
    raw = {
        "news": [
            _item(
                title="Engineered yeast platform for nitrogen fixation",
                summary="A study reports engineered yeast platform for nitrogen fixation.",
                url="https://example.com/news/shared",
                date="2026-06-10",
            ),
            _item(
                title="AlphaFold revolutionizes protein design",
                summary="A different story about synthetic biology but incorrectly reuses the same URL.",
                url="https://example.com/news/shared?utm_source=x",
                date="2026-06-10",
            ),
        ],
        "research": [],
        "funding": [],
        "policy": [],
        "events": [],
    }

    result = report_pipeline.build_approved_from_raw(
        raw,
        "2026-06-10",
        output_dir=tmp_path,
        check_url_health_enabled=False,
        check_title_match_enabled=False,
    )

    assert len(result["approved"]) == 1
    assert any("[approved冲突]" in item["reason"] for item in result["rejected"])
    assert result["approved_schema"]["is_valid"]


def test_build_approved_checks_url_health_by_default(tmp_path, monkeypatch):
    monkeypatch.setattr(report_pipeline, "load_historical_events", lambda days=30: {})
    monkeypatch.setattr(report_pipeline, "_load_history_index", lambda: [])
    raw = {
        "news": [
            _item(title="Healthy by default", url="https://example.com/news/default"),
            _item(title="Dead by default", url="https://example.com/news/dead"),
        ],
        "research": [],
        "funding": [],
        "policy": [],
        "events": [],
    }

    def fake_check(url):
        if "dead" in url:
            return {"ok": False, "reason": "HTTP状态异常: 404"}
        return {"ok": True, "status": 200}

    result = report_pipeline.build_approved_from_raw(
        raw,
        "2026-06-10",
        output_dir=tmp_path,
        url_check_func=fake_check,
        title_check_func=lambda item: {"ok": True},
    )

    assert [item["title"] for item in result["approved"]] == ["Healthy by default"]
    assert any("[链接健康]" in item["reason"] for item in result["rejected"])


def test_build_approved_can_skip_network_gates_explicitly(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNBIO_DAILY_NOW", "2026-06-11T12:00:00+08:00")
    monkeypatch.setattr(report_pipeline, "load_historical_events", lambda days=30: {})
    monkeypatch.setattr(report_pipeline, "_load_history_index", lambda: [])
    raw = {
        "news": [_item(title="Offline test item", url="https://example.com/news/offline")],
        "research": [],
        "funding": [],
        "policy": [],
        "events": [],
    }

    def fail_if_called(_):
        raise AssertionError("network gates should be explicitly skippable")

    result = report_pipeline.build_approved_from_raw(
        raw,
        "2026-06-10",
        output_dir=tmp_path,
        check_url_health_enabled=False,
        check_title_match_enabled=False,
        url_check_func=fail_if_called,
        title_check_func=fail_if_called,
    )

    assert [item["title"] for item in result["approved"]] == ["Offline test item"]


def test_build_approved_llm_gate_rejects_out_of_scope_item(tmp_path, monkeypatch):
    monkeypatch.setattr(report_pipeline, "load_historical_events", lambda days=30: {})
    monkeypatch.setattr(report_pipeline, "_load_history_index", lambda: [])
    raw = {
        "news": [
            _item(
                title="Engineered microbe cell factory improves fermentation yield",
                summary="Synthetic biology platform uses metabolic engineering and cell factory design.",
                url="https://example.com/news/cell-factory",
            ),
            _item(
                title="Synthetic biology forum mentions hospital expansion",
                summary="The healthcare forum mentioned synthetic biology while discussing hospital expansion.",
                url="https://example.com/news/hospital-expansion",
            ),
        ],
        "research": [],
        "funding": [],
        "policy": [],
        "events": [],
    }

    def fake_judge(item, mode="auto"):
        if "hospital" in item["title"].lower():
            return report_pipeline.RelevanceDecision(
                is_approved=False,
                domain_relevance="out_of_scope",
                confidence=0.93,
                reason="只是泛行业会议提及，不是合成生物事件",
                reject_reason="普通医疗行业扩张，缺少合成生物工程化证据",
                evidence_spans=["hospital expansion"],
                section="news",
                provider="llm-test",
            )
        return report_pipeline.RelevanceDecision(
            is_approved=True,
            domain_relevance="core_synbio",
            confidence=0.94,
            reason="含代谢工程和细胞工厂证据",
            evidence_spans=["metabolic engineering", "cell factory"],
            section="news",
            provider="llm-test",
        )

    result = report_pipeline.build_approved_from_raw(
        raw,
        "2026-06-10",
        output_dir=tmp_path,
        check_url_health_enabled=False,
        check_title_match_enabled=False,
        llm_relevance_mode="llm",
        llm_judge_func=fake_judge,
    )

    assert [item["title"] for item in result["approved"]] == [
        "Engineered microbe cell factory improves fermentation yield"
    ]
    assert result["approved"][0]["llm_relevance"]["provider"] == "llm-test"
    assert any("[LLM领域审计]" in item["reason"] for item in result["rejected"])


def test_build_approved_can_disable_llm_gate(tmp_path, monkeypatch):
    monkeypatch.setattr(report_pipeline, "load_historical_events", lambda days=30: {})
    monkeypatch.setattr(report_pipeline, "_load_history_index", lambda: [])
    raw = {
        "news": [_item(
            title="Synthetic biology platform expansion",
            summary="Synthetic biology platform expands fermentation manufacturing.",
            url="https://example.com/news/platform-expansion",
        )],
        "research": [],
        "funding": [],
        "policy": [],
        "events": [],
    }

    def fail_if_called(item, mode="auto"):
        raise AssertionError("LLM gate should be disabled")

    result = report_pipeline.build_approved_from_raw(
        raw,
        "2026-06-10",
        output_dir=tmp_path,
        check_url_health_enabled=False,
        check_title_match_enabled=False,
        llm_relevance_mode="off",
        llm_judge_func=fail_if_called,
    )

    assert [item["title"] for item in result["approved"]] == [
        "Synthetic biology platform expansion"
    ]
    assert "llm_relevance" not in result["approved"][0]


def test_looks_like_type_uses_tuple_relevance_wrapper_without_type_error():
    assert report_pipeline._looks_like_type(
        _item(
            title="Synthetic biology platform expansion",
            summary="Synthetic biology platform expands fermentation manufacturing.",
        ),
        "news",
    )


def test_build_approved_can_drop_unhealthy_primary_urls(tmp_path, monkeypatch):
    monkeypatch.setattr(report_pipeline, "load_historical_events", lambda days=30: {})
    monkeypatch.setattr(report_pipeline, "_load_history_index", lambda: [])
    raw = {
        "news": [
            _item(title="Healthy article", url="https://example.com/news/healthy"),
            _item(title="Missing article", url="https://example.com/news/missing"),
        ],
        "research": [],
        "funding": [],
        "policy": [],
        "events": [],
    }

    def fake_check(url):
        if "missing" in url:
            return {"ok": False, "reason": "HTTP状态异常: 404"}
        return {"ok": True, "status": 200}

    result = report_pipeline.build_approved_from_raw(
        raw,
        "2026-06-10",
        output_dir=tmp_path,
        check_url_health_enabled=True,
        check_title_match_enabled=False,
        url_check_func=fake_check,
    )

    assert [item["title"] for item in result["approved"]] == ["Healthy article"]
    assert any("[链接健康]" in item["reason"] for item in result["rejected"])


def test_report_pipeline_cli_render_md_generates_approved_only_report(tmp_path):
    approved_path = tmp_path / "approved.json"
    approved_path.write_text(json.dumps([{
        "title": "星河生物完成数千万元 pre-A 轮融资",
        "source": "SynBioBeta",
        "date": "2026-06-10",
        "summary": "星河生物完成数千万元 pre-A 轮融资，用于合成生物制造平台扩产。",
        "url": "https://example.com/news/xinghe",
        "type": "news",
        "raw_score": 18,
        "value_score": 6.0,
    }], ensure_ascii=False), encoding="utf-8")
    raw_path = tmp_path / "raw_2026-06-10.json"
    raw_path.write_text(json.dumps({
        "news": [
            {
                "title": "星河生物完成数千万元 pre-A 轮融资",
                "source": "SynBioBeta",
                "date": "2026-06-10",
                "summary": "星河生物完成数千万元 pre-A 轮融资，用于合成生物制造平台扩产。",
                "url": "https://example.com/news/xinghe",
                "type": "news",
                "source_round": "r1",
            },
            {
                "title": "旧闻应该被筛掉",
                "source": "Example",
                "date": "2026-05-01",
                "summary": "旧闻。",
                "url": "https://example.com/news/old",
                "type": "news",
                "source_round": "r2",
            },
        ],
        "research": [],
        "funding": [],
        "policy": [],
        "events": [],
    }, ensure_ascii=False), encoding="utf-8")
    output = tmp_path / "2026-06-10.md"

    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "report_pipeline.py"),
            "--render-md",
            str(approved_path),
            "--date",
            "2026-06-10",
            "--raw",
            str(raw_path),
            "--output",
            str(output),
        ],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
    )

    assert result.returncode == 0, result.stderr + result.stdout
    report = output.read_text(encoding="utf-8")
    assert "https://example.com/news/xinghe" in report
    assert "approved=1" in report
    assert "原始数据=2条" in report
    validation = report_pipeline.run_compliance_check(str(output))
    assert validation["passed"], validation["fix_instructions"]


def test_validate_email_consistency_accepts_aggregated_urls():
    approved = [{
        "title": "星河生物完成数千万元 pre-A 轮融资",
        "url": "https://example.com/news/primary",
        "urls": ["https://example.com/news/primary", "https://example.com/news/secondary"],
    }]
    email = '<div class="card-title">星河生物完成数千万元 pre-A 轮融资</div><a href="https://example.com/news/secondary">查看</a>'

    result = report_pipeline.validate_email_consistency(email, approved)

    assert result["is_consistent"]


def test_validate_email_consistency_unescapes_href_entities():
    approved = [{
        "title": "星河生物完成数千万元 pre-A 轮融资",
        "url": "https://example.com/article?id=1&utm_source=x",
    }]
    email = (
        '<div class="card-title">星河生物完成数千万元 pre-A 轮融资</div>'
        '<a href="https://example.com/article?id=1&amp;utm_source=x">查看</a>'
    )

    result = report_pipeline.validate_email_consistency(email, approved)

    assert result["is_consistent"]


def test_validate_urls_against_approved_checks_url_only():
    approved = [{
        "title": "已批准标题",
        "url": "https://example.com/article?id=1&utm_source=x",
    }]
    urls = report_pipeline.extract_http_urls(
        '<h2>不同的 H5 标题结构</h2>'
        '<a href="https://example.com/article?id=1&amp;utm_source=x">查看</a>'
    )

    result = report_pipeline.validate_urls_against_approved(urls, approved, label="H5附件")

    assert result["is_consistent"]


def test_extract_http_urls_handles_html_url_attributes():
    html = (
        '<A HREF=https://unapproved.example.com/upper>x</A>'
        '<a href="https://example.com/article?id=1&amp;utm_source=x">查看</a>'
        '<img SRC="https://tracker.example.com/pixel.png">'
        '<form action="https://forms.example.com/post"></form>'
        '<button formaction="https://forms.example.com/button">go</button>'
        '<video poster="https://cdn.example.com/poster.png"></video>'
        '<a href="/relative/path">relative</a>'
        '<a href="mailto:team@example.com">mail</a>'
    )

    assert report_pipeline.extract_http_urls(html) == [
        "https://unapproved.example.com/upper",
        "https://example.com/article?id=1&utm_source=x",
        "https://tracker.example.com/pixel.png",
        "https://forms.example.com/post",
        "https://forms.example.com/button",
        "https://cdn.example.com/poster.png",
    ]


class _FakeHeaders(dict):
    def get_content_charset(self):
        return "utf-8"


class _FakeResponse:
    status = 200
    code = 200
    url = "https://example.com/news/xinghe"
    headers = _FakeHeaders({"Content-Type": "text/html; charset=utf-8"})

    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self, size=-1):
        return self.body[:size]


def test_extract_title_signals_reads_og_title_title_and_h1():
    html = (
        '<html><head><meta property="og:title" content="OG 合成生物大会">'
        '<meta content="Twitter 合成生物大会" name="twitter:title">'
        "<title>页面标题</title></head><body><h1>正文标题</h1></body></html>"
    )

    assert report_pipeline.extract_title_signals(html) == [
        "OG 合成生物大会",
        "Twitter 合成生物大会",
        "页面标题",
        "正文标题",
    ]


def test_extract_page_verified_date_prefers_publish_meta_over_old_body_event_date():
    html = """
    <html>
      <head><meta property="article:published_time" content="2026-06-21T10:00:00+08:00"></head>
      <body>2024年11月22日，方昕博士做客科大硅谷大讲堂，解读生物制造。</body>
    </html>
    """

    result = report_pipeline.extract_page_verified_date(html, search_date="2026-06-21")

    assert result["verified_date"] == "2026-06-21"
    assert result["confidence"] == "high"


def test_extract_page_verified_date_ignores_effective_and_noise_dates_when_publish_meta_exists():
    html = """
    <html>
      <head><meta property="article:published_time" content="2026-06-24T09:00:00+08:00"></head>
      <body>
        深圳经济特区促进合成生物产业创新发展若干规定发布。
        本规定自2025年10月1日起施行。
        版权所有 2020 深圳市人民政府。
      </body>
    </html>
    """

    result = report_pipeline.extract_page_verified_date(html, search_date="2026-06-24")

    assert result["verified_date"] == "2026-06-24"
    assert result["confidence"] == "high"


def test_extract_page_verified_date_prefers_body_date_for_36kr_cache_meta():
    html = """
    <html>
      <head><meta property="article:published_time" content="2026-07-03T07:36:17+08:00"></head>
      <body>
        氪记2022
        2023-01-12 08:00
        这是一篇 36氪 旧文章，被移动端缓存页面重新注入了当天 meta 时间。
      </body>
    </html>
    """

    result = report_pipeline.extract_page_verified_date(
        html,
        search_date="2026-07-03",
        page_url="https://m.36kr.com/p/2084819844283143",
    )

    assert result["verified_date"] == "2023-01-12"
    assert result["source"] == "body"


def test_extract_page_verified_date_uses_body_event_date_without_label():
    html = """
    <html><body>
      2025年8月29日，经深圳市人民代表大会常务委员会审议通过合成生物产业创新发展规定。
    </body></html>
    """

    result = report_pipeline.extract_page_verified_date(html, search_date="2026-06-24")

    assert result["verified_date"] == "2025-08-29"
    assert result["confidence"] == "high"


def test_verify_item_page_date_demotes_future_non_event_date_to_search_fallback():
    item = _item(
        title="金河生物项目公告",
        summary="项目实施期间为2026年08月01日至2028年04月30日。",
        date="2026-06-26",
        search_date="2026-06-26",
        date_source="search_result",
        source_round="r1",
        type="funding",
        url="https://example.com/funding/jinhe",
    )

    def fake_verify(url, search_date):
        return {
            "verified_date": "2026-08-01",
            "confidence": "medium",
            "source": "body",
            "url": url,
        }

    verified = report_pipeline.verify_item_page_date(item, date_verify_func=fake_verify)

    assert verified["date"] == "2026-06-26"
    assert verified["date_verification"]["source"] == "search_fallback"
    assert verified["date_verification"]["confidence"] == "low"


def test_verify_item_page_date_keeps_near_future_event_date():
    item = _item(
        title="Synthetic Biology at the Intersection of Science, Ethics, and Policy",
        summary="Sep. 18, 2026 event page.",
        date="2026-07-03",
        search_date="2026-07-03",
        date_source="search_result",
        source_round="llm_discovery",
        type="events",
        url="https://example.com/events/synthetic-biology-policy",
    )
    item["content_type"] = "event_preview"

    def fake_verify(url, search_date):
        return {
            "verified_date": "2026-07-04",
            "confidence": "high",
            "source": "meta/body",
            "url": url,
        }

    verified = report_pipeline.verify_item_page_date(item, date_verify_func=fake_verify)

    assert verified["date"] == "2026-07-04"
    assert verified["verified_date"] == "2026-07-04"


def test_fetch_and_verify_date_extracts_body_date_without_network():
    def opener(request, timeout=10):
        return _FakeResponse("发布时间：2026年4月16日 深圳市合成生物研究设施开放共享若干措施".encode("utf-8"))

    result = report_pipeline.fetch_and_verify_date(
        "https://stic.sz.gov.cn/gkmlpt/content/12/12740/post_12740127.html",
        "2026-06-24",
        opener=opener,
    )

    assert result["verified_date"] == "2026-04-16"
    assert result["source"] == "meta/body"


def test_build_approved_rejects_old_item_after_page_date_verification(tmp_path, monkeypatch):
    monkeypatch.setattr(report_pipeline, "load_historical_events", lambda days=30: {})
    monkeypatch.setattr(report_pipeline, "_load_history_index", lambda: [])
    monkeypatch.setattr(report_pipeline, "_load_sent_url_registry", lambda: {"version": 1, "registry": {}})
    raw = {
        "news": [_item(
            title="方昕博士解读生物制造产业落地",
            summary="方昕博士讨论合成生物和生物制造产业落地。",
            date="2026-06-10",
            search_date="2026-06-10",
            date_source="search_result",
            source_round="r1",
            url="https://www.36kr.com/p/3051114996943496",
        )],
        "research": [],
        "funding": [],
        "policy": [],
        "events": [],
    }

    def fake_date_verify(url, search_date):
        return {
            "verified_date": "2024-11-22",
            "confidence": "high",
            "source": "body",
            "url": url,
        }

    result = report_pipeline.build_approved_from_raw(
        raw,
        "2026-06-10",
        output_dir=tmp_path,
        check_url_health_enabled=False,
        check_title_match_enabled=False,
        date_verify_func=fake_date_verify,
        llm_relevance_mode="off",
    )

    assert result["approved"] == []
    assert any("[时效性]" in item["reason"] for item in result["rejected"])
    rejected_item = next(item["item"] for item in result["rejected"] if "[时效性]" in item["reason"])
    assert rejected_item["verified_date"] == "2024-11-22"


def test_build_approved_rejects_search_fallback_date_verification(tmp_path, monkeypatch):
    monkeypatch.setattr(report_pipeline, "load_historical_events", lambda days=30: {})
    monkeypatch.setattr(report_pipeline, "_load_history_index", lambda: [])
    monkeypatch.setattr(report_pipeline, "_load_sent_url_registry", lambda: {"version": 1, "registry": {}})
    raw = {
        "news": [_item(
            title="未来实验室合成生物",
            summary="未来实验室报道合成生物产业观察。",
            date="2026-07-03",
            search_date="2026-07-03",
            date_source="search_result",
            source_round="r1",
            url="https://example.com/fallback-date",
        )],
        "research": [],
        "funding": [],
        "policy": [],
        "events": [],
    }

    def fake_date_verify(url, search_date):
        return {
            "verified_date": search_date,
            "confidence": "low",
            "source": "search_fallback",
            "url": url,
        }

    result = report_pipeline.build_approved_from_raw(
        raw,
        "2026-07-03",
        output_dir=tmp_path,
        check_url_health_enabled=False,
        check_title_match_enabled=False,
        date_verify_func=fake_date_verify,
        llm_relevance_mode="off",
    )

    assert result["approved"] == []
    assert any("[页面日期]" in item["reason"] for item in result["rejected"])
    assert result["stats"]["news"]["date_verification_rejected"] == 1


def test_build_approved_rejects_old_policy_file_after_page_date_verification(tmp_path, monkeypatch):
    monkeypatch.setattr(report_pipeline, "load_historical_events", lambda days=30: {})
    monkeypatch.setattr(report_pipeline, "_load_history_index", lambda: [])
    monkeypatch.setattr(report_pipeline, "_load_sent_url_registry", lambda: {"version": 1, "registry": {}})
    raw = {
        "news": [],
        "research": [],
        "funding": [],
        "policy": [_item(
            title="深圳市推动合成生物创新引领生物制造产业高质量发展若干措施",
            source="深圳市科技创新局",
            summary="深圳市发布合成生物和生物制造产业若干措施。",
            date="2026-06-24",
            search_date="2026-06-24",
            date_source="search_result",
            source_round="r5",
            type="policy",
            url="https://stic.sz.gov.cn/gkmlpt/content/12/12740/post_12740127.html",
        )],
        "events": [],
    }

    def fake_date_verify(url, search_date):
        return {
            "verified_date": "2026-04-16",
            "confidence": "high",
            "source": "meta/body",
            "url": url,
        }

    result = report_pipeline.build_approved_from_raw(
        raw,
        "2026-06-24",
        output_dir=tmp_path,
        check_url_health_enabled=False,
        check_title_match_enabled=False,
        date_verify_func=fake_date_verify,
        llm_relevance_mode="off",
    )

    assert result["approved"] == []
    assert any("[时效性]" in item["reason"] and "限制7天" in item["reason"] for item in result["rejected"])


def test_check_url_title_match_rejects_mismatched_reachable_page():
    def opener(request, timeout=10):
        return _FakeResponse("<title>全市服务业大会召开</title>".encode("utf-8"))

    result = report_pipeline.check_url_title_match(
        {
            "title": "江苏合成生物大会召开",
            "url": "https://www.zgjssw.gov.cn/news/example.html",
        },
        opener=opener,
    )

    assert not result["ok"]
    assert "标题与页面不匹配" in result["reason"]


def test_check_url_title_match_accepts_site_suffix_titles():
    def opener(request, timeout=10):
        return _FakeResponse("<title>江苏合成生物大会召开 - 江苏新闻网</title>".encode("utf-8"))

    result = report_pipeline.check_url_title_match(
        {
            "title": "江苏合成生物大会召开",
            "url": "https://www.zgjssw.gov.cn/news/example.html",
        },
        opener=opener,
    )

    assert result["ok"]
    assert result["score"] == 1.0


def test_check_url_title_match_keeps_network_errors_as_warning():
    def opener(request, timeout=10):
        raise URLError("temporary failure")

    result = report_pipeline.check_url_title_match(
        {
            "title": "江苏合成生物大会召开",
            "url": "https://www.zgjssw.gov.cn/news/example.html",
        },
        opener=opener,
    )

    assert result["ok"]
    assert "标题匹配跳过" in result["warning"]


def test_check_url_health_detects_deleted_content_without_network():
    def opener(request, timeout=10):
        return _FakeResponse("该文章已被删除".encode("utf-8"))

    result = report_pipeline.check_url_health("https://example.com/news/xinghe", opener=opener)

    assert not result["ok"]
    assert "页面疑似失效" in result["reason"]


def test_check_url_health_detects_http_error_without_network():
    def opener(request, timeout=10):
        raise HTTPError(request.full_url, 404, "not found", {}, None)

    result = report_pipeline.check_url_health("https://example.com/news/missing", opener=opener)

    assert not result["ok"]
    assert result["status"] == 404


def test_check_url_health_soft_mode_warns_on_ssl_errors_without_allowing_404():
    def ssl_opener(request, timeout=10):
        raise URLError(ssl.SSLError("SSL: BAD_ECPOINT bad ecpoint"))

    def http_opener(request, timeout=10):
        raise HTTPError(request.full_url, 404, "not found", {}, None)

    ssl_result = report_pipeline.check_url_health(
        "https://fgw.sz.gov.cn/zwgk/ghjh/example.html",
        opener=ssl_opener,
        mode="soft",
    )
    strict_result = report_pipeline.check_url_health(
        "https://fgw.sz.gov.cn/zwgk/ghjh/example.html",
        opener=ssl_opener,
        mode="strict",
    )
    http_result = report_pipeline.check_url_health(
        "https://example.com/news/missing",
        opener=http_opener,
        mode="soft",
    )

    assert ssl_result["ok"]
    assert ssl_result["ssl_warning"]
    assert not strict_result["ok"]
    assert not http_result["ok"]
    assert http_result["status"] == 404


def test_validate_url_health_soft_mode_returns_ssl_warnings():
    def ssl_check(url, mode="strict"):
        assert mode == "soft"
        return {"ok": True, "url": url, "warning": "SSL warning", "ssl_warning": True}

    result = report_pipeline.validate_url_health(["https://example.com/a"], check_func=ssl_check, mode="soft")

    assert result["is_valid"]
    assert result["warnings"]


def test_build_approved_title_match_can_be_explicitly_skipped(tmp_path, monkeypatch):
    monkeypatch.setattr(report_pipeline, "load_historical_events", lambda days=30: {})
    monkeypatch.setattr(report_pipeline, "_load_history_index", lambda: [])
    raw = {
        "news": [_item(title="江苏合成生物大会召开", url="https://example.com/news/service-conference")],
        "research": [],
        "funding": [],
        "policy": [],
        "events": [],
    }

    def reject_if_called(item):
        return {"ok": False, "reason": "should only run when enabled"}

    without_gate = report_pipeline.build_approved_from_raw(
        raw,
        "2026-06-10",
        output_dir=tmp_path / "without",
        check_url_health_enabled=False,
        check_title_match_enabled=False,
        title_check_func=reject_if_called,
    )
    with_gate = report_pipeline.build_approved_from_raw(
        raw,
        "2026-06-10",
        output_dir=tmp_path / "with",
        check_url_health_enabled=False,
        check_title_match_enabled=True,
        title_check_func=reject_if_called,
    )

    assert len(without_gate["approved"]) == 1
    assert len(with_gate["approved"]) == 0
    assert any("[标题匹配]" in item["reason"] for item in with_gate["rejected"])


def test_render_markdown_report_funding_defaults_missing_fields():
    report = report_pipeline.render_markdown_report([
        {
            "title": "天津大学天大系硬科技项目加速IPO，合成生物成优势方向",
            "source": "Example",
            "date": "2026-06-15",
            "summary": "天津大学相关硬科技项目推进IPO。",
            "url": "https://example.com/funding/tianda",
            "type": "funding",
            "raw_score": 10,
            "value_score": 3.3,
        }
    ], "2026-06-17", raw_count=1)

    assert "| 天津大学天大系硬科技项目加速IPO，合成生物成优势方向 | — | 未披露 | — | 2026-06-15 | https://example.com/funding/tianda |" in report


def test_render_markdown_report_strips_extra_urls_from_summary():
    report = report_pipeline.render_markdown_report([
        {
            "title": "生物制造大赛通知",
            "source": "Example",
            "date": "2026-07-03",
            "summary": "报名入口 https://www.chinasme.cn/bioCompetition/home 以及更多信息 https://mp.weixin.qq.com/s/abc",
            "url": "https://example.com/news/competition",
            "type": "news",
            "raw_score": 10,
            "value_score": 3.3,
        }
    ], "2026-07-03")

    assert "https://www.chinasme.cn/bioCompetition/home" not in report
    assert "https://mp.weixin.qq.com/s/abc" not in report
    assert "https://example.com/news/competition" in report


def test_run_compliance_check_includes_ai_grounding_errors():
    result = report_pipeline.run_compliance_check(str(ROOT / "tests" / "fixtures" / "invalid_ai_report.md"))

    assert not result["passed"]
    assert "ai_check" in result
    assert any("143家" in error for error in result["fix_instructions"])
