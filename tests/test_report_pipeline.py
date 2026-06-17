import json
import subprocess
import sys
from urllib.error import HTTPError
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
        report_pipeline.build_approved_from_raw(raw, "2026-06-10", output_dir=tmp_path, search_log=_search_log())
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
    assert report_pipeline._is_category_or_aggregate_url("https://example.com/news")
    assert report_pipeline._is_category_or_aggregate_url("https://example.com/category/synthetic-biology")
    assert report_pipeline._is_category_or_aggregate_url("https://example.com/topic-hub/synthetic-biology/news-and-features")
    assert report_pipeline._is_category_or_aggregate_url("https://conferences.nature.com/synthetic-biology")


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

    result = report_pipeline.build_approved_from_raw(raw, "2026-06-10", output_dir=tmp_path)

    assert len(result["approved"]) == 1
    assert any("[approved冲突]" in item["reason"] for item in result["rejected"])
    assert result["approved_schema"]["is_valid"]


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


def test_run_compliance_check_includes_ai_grounding_errors():
    result = report_pipeline.run_compliance_check(str(ROOT / "tests" / "fixtures" / "invalid_ai_report.md"))

    assert not result["passed"]
    assert "ai_check" in result
    assert any("143家" in error for error in result["fix_instructions"])
