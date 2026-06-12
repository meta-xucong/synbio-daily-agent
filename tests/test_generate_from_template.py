import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import generate_from_template
import send_email
from report_pipeline import extract_http_urls, validate_urls_against_approved


def _approved(**overrides):
    item = {
        "title": "星河生物完成数千万元 pre-A 轮融资",
        "source": "SynBioBeta",
        "date": "2026-06-10",
        "summary": "星河生物完成数千万元 pre-A 轮融资，用于合成生物制造平台扩产。",
        "url": "https://example.com/news/xinghe",
        "type": "news",
        "company": "星河生物",
        "round": "pre-A",
        "amount": "数千万元",
        "investor": "经纬创投",
        "location": "上海",
        "raw_score": 18,
        "value_score": 6,
    }
    item.update(overrides)
    return item


def _write_inputs(tmp_path, items=None):
    (tmp_path / "data").mkdir()
    (tmp_path / "reports").mkdir()
    approved = items or [
        _approved(type="news"),
        _approved(type="research", title="工程菌株提高生物基材料产率", url="https://example.com/research/strain"),
        _approved(type="funding", title="星河生物完成数千万元 pre-A 轮融资", url="https://example.com/funding/xinghe"),
        _approved(type="policy", title="北京发布生物制造支持政策", url="https://example.com/policy/beijing"),
        _approved(type="events", title="合成生物产业论坛即将举行", url="https://example.com/events/forum"),
    ]
    approved_path = tmp_path / "data" / "approved_2026-06-10.json"
    approved_path.write_text(json.dumps(approved, ensure_ascii=False), encoding="utf-8")
    md_path = tmp_path / "reports" / "2026-06-10.md"
    md_path.write_text((ROOT / "tests" / "fixtures" / "valid_report.md").read_text(encoding="utf-8"), encoding="utf-8")
    return approved, approved_path, md_path


def test_generate_from_template_outputs_production_classes(tmp_path):
    approved, approved_path, md_path = _write_inputs(tmp_path)
    html_path = tmp_path / "reports" / "synbio_daily_2026-06-10.html"
    email_path = tmp_path / "reports" / "email_2026-06-10.html"

    generate_from_template.generate("2026-06-10", approved_path, md_path, html_path, email_path)

    html = html_path.read_text(encoding="utf-8")
    email_html = email_path.read_text(encoding="utf-8")
    for marker in [
        "class=\"header\"",
        "summary-section",
        "content-section",
        "class=\"card\"",
        "data-table",
        "analysis-block",
        "risk-box",
    ]:
        assert marker in html
    for marker in ["<style>", "summary-section", "section-title"]:
        assert marker in email_html
    assert "class=\"card\"" in email_html or "data-table" in email_html

    for rendered, label in [(html, "H5"), (email_html, "邮件HTML")]:
        result = validate_urls_against_approved(extract_http_urls(rendered), approved, label=label)
        assert result["is_consistent"], result["errors"]


def test_generate_from_template_escapes_text_and_rejects_unsafe_url(tmp_path):
    approved, approved_path, md_path = _write_inputs(tmp_path, [_approved(title="<script>alert(1)</script>")])
    html_path = tmp_path / "reports" / "synbio_daily_2026-06-10.html"
    email_path = tmp_path / "reports" / "email_2026-06-10.html"

    generate_from_template.generate("2026-06-10", approved_path, md_path, html_path, email_path)
    html = html_path.read_text(encoding="utf-8")
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html

    bad_path = tmp_path / "data" / "approved_bad.json"
    bad_path.write_text(json.dumps([_approved(url="javascript:alert(1)")], ensure_ascii=False), encoding="utf-8")
    try:
        generate_from_template.generate("2026-06-10", bad_path, md_path, html_path, email_path)
    except ValueError as exc:
        assert "unsafe url" in str(exc)
    else:
        raise AssertionError("unsafe URL should fail generation")


def test_send_email_dry_run_passes_generated_template_output(tmp_path, monkeypatch):
    approved, approved_path, md_path = _write_inputs(tmp_path, [_approved(type="news")])
    raw_path = tmp_path / "data" / "raw_2026-06-10.json"
    raw_path.write_text(json.dumps({"news": approved, "research": [], "funding": [], "policy": [], "events": []}, ensure_ascii=False), encoding="utf-8")
    html_path = tmp_path / "reports" / "synbio_daily_2026-06-10.html"
    email_path = tmp_path / "reports" / "email_2026-06-10.html"
    generate_from_template.generate("2026-06-10", approved_path, md_path, html_path, email_path)

    monkeypatch.setattr(send_email, "CONFIG_DIR", tmp_path / "config")
    monkeypatch.setattr(send_email, "DATA_DIR", tmp_path / "data")
    (tmp_path / "config").mkdir()

    assert send_email.send_daily_report("2026-06-10", md_path, html_path, email_path, dry_run=True)
