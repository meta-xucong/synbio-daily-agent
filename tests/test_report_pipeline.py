import json
import subprocess
import sys
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


def test_process_raw_data_rejects_url_attribute_injection(monkeypatch):
    monkeypatch.setattr(report_pipeline, "load_historical_events", lambda days=30: {})
    result = report_pipeline.process_raw_data([
        _item(url='https://example.com" onmouseover="alert(1)'),
    ], "news")

    assert result["stats"]["approved"] == 0
    assert result["stats"]["schema_rejected"] == 1


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
        "url": "https://example.com/news/xinghe",
        "type": "news",
        "date": approved_date,
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
        "url": "https://example.com/news/xinghe",
        "type": "news",
        "date": "2026-05-01",
    }]

    result = report_pipeline.run_full_validation(report, email, approved)

    assert not result["can_send_email"]
    assert result["approved_timeliness_check"]["has_errors"]


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


def test_run_compliance_check_includes_ai_grounding_errors():
    result = report_pipeline.run_compliance_check(str(ROOT / "tests" / "fixtures" / "invalid_ai_report.md"))

    assert not result["passed"]
    assert "ai_check" in result
    assert any("143家" in error for error in result["fix_instructions"])
