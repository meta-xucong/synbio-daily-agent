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
        "source_round": "r1",
        "round": "pre-A",
        "amount": "数千万元",
        "investor": "经纬创投",
        "location": "上海",
        "raw_score": 18,
        "value_score": 6,
        "search_date": "2026-06-10",
        "date_source": "page_verified",
        "verified_date": "2026-06-10",
        "date_verification": {
            "verified_date": "2026-06-10",
            "confidence": "high",
            "source": "meta/body",
            "url": "https://example.com/news/xinghe",
        },
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
    }
    item.update(overrides)
    return item


def _write_inputs(tmp_path, items=None):
    (tmp_path / "config").mkdir(exist_ok=True)
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
    query_config = {
        "rounds": [
            {"round_id": "r1", "required_queries": ["synthetic biology funding 2026"]},
            {"round_id": "r2", "required_queries": ["synthetic biology research 2026"]},
            {"round_id": "r3", "required_queries": ["synthetic biology policy 2026"]},
            {"round_id": "r4", "required_queries": ["synthetic biology events 2026"]},
            {"round_id": "r5", "required_queries": ["synthetic biology China 2026"]},
        ]
    }
    (tmp_path / "config" / "search_queries.json").write_text(json.dumps(query_config, ensure_ascii=False), encoding="utf-8")
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


def test_generate_from_template_renders_ai_bold_markdown(tmp_path):
    approved, approved_path, md_path = _write_inputs(tmp_path, [_approved(type="news")])
    md_path.write_text(
        """
# 合成生物行业日报

流水线追踪：approved=1

## 📌 执行摘要

1. 星河生物完成数千万元 pre-A 轮融资（2026-06-10）

## 📰 行业热点新闻

| 标题 | 来源 | 时间 | 摘要 | 链接 |
|---|---|---|---|---|
| 星河生物完成数千万元 pre-A 轮融资 | SynBioBeta | 2026-06-10 | 平台扩产。 | https://example.com/news/xinghe |

## 🤖 AI 深度分析

### 趋势研判

**1. 产业化信号增强**

星河生物融资显示平台扩产继续推进。

### 风险提示

- **技术放大风险** 仍需观察。

## 📎 附录

- https://example.com/news/xinghe
""".strip(),
        encoding="utf-8",
    )
    html_path = tmp_path / "reports" / "synbio_daily_2026-06-10.html"
    email_path = tmp_path / "reports" / "email_2026-06-10.html"

    generate_from_template.generate("2026-06-10", approved_path, md_path, html_path, email_path)

    html = html_path.read_text(encoding="utf-8")
    assert "<strong>1. 产业化信号增强</strong>" in html
    assert "<strong>技术放大风险</strong>" in html
    assert "**1. 产业化信号增强**" not in html


def test_send_email_dry_run_passes_generated_template_output(tmp_path, monkeypatch):
    approved, approved_path, md_path = _write_inputs(tmp_path, [_approved(type="news")])
    raw_path = tmp_path / "data" / "raw_2026-06-10.json"
    raw_path.write_text(json.dumps({"news": approved, "research": [], "funding": [], "policy": [], "events": []}, ensure_ascii=False), encoding="utf-8")
    search_log = {
        "version": 1,
        "date": "2026-06-10",
        "generated_by": "search_executor",
        "provider": "llm_web",
        "llm_discovery_provider": "llm_web",
        "high_recall_enabled": True,
        "required_high_recall_rounds": ["llm_discovery", "llm_gap_audit"],
        "limit": 15,
        "rounds": [
            {"round": "r1", "queries": [{"query": "synthetic biology funding 2026", "executed": True, "provider": "llm_web"}], "candidates": ["https://example.com/news/xinghe"]},
            {"round": "r2", "queries": [{"query": "synthetic biology research 2026", "executed": True, "provider": "llm_web"}], "candidates": []},
            {"round": "r3", "queries": [{"query": "synthetic biology policy 2026", "executed": True, "provider": "llm_web"}], "candidates": []},
            {"round": "r4", "queries": [{"query": "synthetic biology events 2026", "executed": True, "provider": "llm_web"}], "candidates": []},
            {"round": "r5", "queries": [{"query": "synthetic biology China 2026", "executed": True, "provider": "llm_web"}], "candidates": []},
            {"round": "llm_dynamic", "queries": [{"query": "synthetic biology dynamic validation 2026", "executed": True, "provider": "llm_web"}], "candidates": []},
            {"round": "llm_discovery", "queries": [{"query": "recent synthetic biology discovery", "executed": True, "provider": "llm_web", "web_search_tool_result": True}], "candidates": []},
            {"round": "llm_gap_audit", "queries": [{"query": "synthetic biology gap audit", "executed": True, "provider": "llm_web", "web_search_tool_result": True}], "candidates": []},
        ],
    }
    (tmp_path / "data" / "search_log_2026-06-10.json").write_text(json.dumps(search_log, ensure_ascii=False), encoding="utf-8")
    (tmp_path / "data" / "search_strategy_2026-06-10.json").write_text(
        json.dumps({"queries": [{"query": "synthetic biology dynamic validation 2026", "required": True}]}, ensure_ascii=False),
        encoding="utf-8",
    )
    html_path = tmp_path / "reports" / "synbio_daily_2026-06-10.html"
    email_path = tmp_path / "reports" / "email_2026-06-10.html"
    generate_from_template.generate("2026-06-10", approved_path, md_path, html_path, email_path)

    monkeypatch.setattr(send_email, "CONFIG_DIR", tmp_path / "config")
    monkeypatch.setattr(send_email, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(
        send_email,
        "validate_url_health",
        lambda urls, label="URL": {
            "is_valid": True,
            "errors": [],
            "checked_urls": [],
            "total_checked": len(urls),
        },
    )
    assert send_email.send_daily_report("2026-06-10", md_path, html_path, email_path, dry_run=True)
