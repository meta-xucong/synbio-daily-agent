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
        "date": "2026-06-10",
        "rounds": [
            {"round": "r1", "queries": ["synthetic biology funding"], "candidates": ["https://example.com/news/yeast-platform"]},
            {"round": "r2", "queries": ["synthetic biology research"], "candidates": []},
            {"round": "r3", "queries": ["synthetic biology policy"], "candidates": []},
            {"round": "r4", "queries": ["synthetic biology events"], "candidates": []},
            {"round": "r5", "queries": ["synthetic biology China"], "candidates": []},
        ],
    }


def test_validate_search_log_requires_five_rounds_and_raw_traceability():
    raw = {
        "news": [_item(type="news", source_round="r1")],
        "research": [],
        "funding": [],
        "policy": [],
        "events": [],
    }

    result = report_pipeline.validate_search_log(_search_log(), raw)

    assert result["is_valid"], result["errors"]
    assert result["rounds_seen"] == ["r1", "r2", "r3", "r4", "r5"]
    assert result["total_queries"] == 5
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
    raw = {"news": [], "research": [], "funding": [], "policy": [], "events": []}

    result = report_pipeline.validate_search_log(_search_log(), raw)

    assert result["is_valid"], result["errors"]
    assert set(result["rounds_seen"]) == {"r1", "r2", "r3", "r4", "r5"}
    assert "raw数据缺少source_round" not in ";".join(result["errors"])


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
    log["rounds"][1]["queries"] = [{"query": "site:synbiobeta.com synthetic biology 2026", "executed": True, "results_count": 0}]
    log["rounds"][4]["queries"] = [{"query": "site:kw.beijing.gov.cn 合成生物", "executed": True, "results_count": 0}]
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

    result = report_pipeline.validate_search_log(log, raw, strict_coverage=True)

    assert result["is_valid"], result["errors"]
    assert result["total_queries"] == 5
    assert raw["news"][0]["source_query"] == "合成生物 白皮书 报告 发布"


def test_validate_search_log_blocks_required_query_executed_false(monkeypatch):
    monkeypatch.setattr(report_pipeline, "load_search_query_config", lambda: {
        "rounds": [{"round_id": "r5", "required_queries": ["site:kw.beijing.gov.cn 合成生物"]}]
    })
    log = _search_log()
    log["rounds"][4]["queries"] = [{
        "query": "site:kw.beijing.gov.cn 合成生物",
        "executed": False,
        "error": "timeout",
    }]
    raw = {"news": [], "research": [], "funding": [], "policy": [], "events": []}

    result = report_pipeline.validate_search_log(log, raw, strict_coverage=True)

    assert not result["is_valid"]
    assert "必需查询未成功执行" in ";".join(result["errors"])
    assert "timeout" in ";".join(result["errors"])


def test_validate_search_log_warns_when_required_query_config_missing(monkeypatch):
    monkeypatch.setattr(report_pipeline, "load_search_query_config", lambda: {})
    raw = {"news": [], "research": [], "funding": [], "policy": [], "events": []}

    result = report_pipeline.validate_search_log(_search_log(), raw)
    strict_result = report_pipeline.validate_search_log(_search_log(), raw, strict_coverage=True)

    assert result["is_valid"]
    assert any("搜索查询配置缺失" in warning for warning in result["warnings"])
    assert not strict_result["is_valid"]
    assert any("搜索查询配置缺失" in error for error in strict_result["errors"])


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


def test_build_approved_blocks_strict_search_coverage_gap(tmp_path, monkeypatch):
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
            strict_search_coverage=True,
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
            check_url_health_enabled=False,
            check_title_match_enabled=False,
        )
    except ValueError as exc:
        assert "site:kw.beijing.gov.cn 合成生物" in str(exc)
    else:
        raise AssertionError("build-approved should enforce required query coverage by default")


def test_build_approved_can_relax_required_query_gate(tmp_path, monkeypatch):
    monkeypatch.setattr(report_pipeline, "load_historical_events", lambda days=30: {})
    monkeypatch.setattr(report_pipeline, "_load_history_index", lambda: [])
    monkeypatch.setattr(report_pipeline, "load_search_query_config", lambda: {
        "rounds": [{"round_id": "r5", "required_queries": ["site:kw.beijing.gov.cn 合成生物"]}]
    })
    raw = {"news": [], "research": [], "funding": [], "policy": [], "events": []}

    result = report_pipeline.build_approved_from_raw(
        raw,
        "2026-06-18",
        output_dir=tmp_path,
        search_log=_search_log(),
        strict_search_coverage=False,
        check_url_health_enabled=False,
        check_title_match_enabled=False,
    )

    assert result["approved"] == []
    assert any("site:kw.beijing.gov.cn 合成生物" in warning for warning in result["search_log_check"]["warnings"])


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
    raw = {
        "news": [_item(type="news", source_round="r6")],
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
            check_url_health_enabled=False,
            check_title_match_enabled=False,
        )
    except ValueError as exc:
        assert "search_log校验失败" in str(exc)
        assert "未记录的source_round" in str(exc)
    else:
        raise AssertionError("invalid search_log should fail build-approved")


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
    assert result["stats"]["schema_rejected"] == 1
    assert "type content mismatch" in result["rejected"][0]["reason"]


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
    assert report_pipeline._is_category_or_aggregate_url("https://example.com/news")
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
                title="Nature reports engineered legumes",
                summary="A Nature paper reports engineered legumes for nitrogen fixation.",
                url="https://example.com/news/shared",
                date="2026-06-10",
            ),
            _item(
                title="AlphaFold revolutionizes protein design",
                summary="A different story incorrectly reuses the same Nature URL.",
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


def test_run_compliance_check_includes_ai_grounding_errors():
    result = report_pipeline.run_compliance_check(str(ROOT / "tests" / "fixtures" / "invalid_ai_report.md"))

    assert not result["passed"]
    assert "ai_check" in result
    assert any("143家" in error for error in result["fix_instructions"])
