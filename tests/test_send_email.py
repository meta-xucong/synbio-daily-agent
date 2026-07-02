import json
import smtplib
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import send_email
import generate_from_template
import report_pipeline


def _add_llm_trace(item: dict) -> dict:
    enriched = dict(item)
    enriched.setdefault("search_date", enriched.get("date", "2026-06-10"))
    enriched.setdefault("date_source", "page_verified")
    enriched.setdefault("date_verification", {
        "verified_date": enriched.get("date", "2026-06-10"),
        "confidence": "high",
        "source": "meta/body",
        "url": enriched.get("url", ""),
    })
    enriched.setdefault("verified_date", enriched.get("date", "2026-06-10"))
    enriched.setdefault("llm_relevance", {
        "is_approved": True,
        "domain_relevance": "core_synbio",
        "confidence": 0.9,
        "reason": "含合成生物/生物制造证据",
        "evidence_spans": ["合成生物", "生物制造"],
        "section": enriched.get("type", "news"),
        "provider": "llm-test",
    })
    enriched.setdefault("domain_relevance", enriched["llm_relevance"]["domain_relevance"])
    enriched.setdefault("confidence", enriched["llm_relevance"]["confidence"])
    return enriched


def _write_runtime_tree(
    tmp_path: Path,
    report_name: str = "valid_report.md",
    *,
    date_str: str = "2026-06-10",
    approved_items: list[dict] | None = None,
):
    (tmp_path / "config").mkdir(parents=True)
    (tmp_path / "data").mkdir(parents=True)
    (tmp_path / "reports").mkdir(parents=True)
    config = {
        "enabled": True,
        "smtp_server": "smtp.example.com",
        "smtp_port": 465,
        "sender_email": "sender@example.com",
        "sender_password": "not-real",
        "receiver_email": "receiver@example.com",
        "check_url_health": False,
    }
    (tmp_path / "config" / "email_config.json").write_text(json.dumps(config), encoding="utf-8")
    approved = approved_items or [
        {
            "title": "星河生物完成数千万元 pre-A 轮融资",
            "source": "SynBioBeta",
            "date": date_str,
            "summary": "星河生物完成数千万元 pre-A 轮融资，用于合成生物制造平台扩产。",
            "url": "https://example.com/news/xinghe",
            "type": "news",
            "source_round": "r1",
            "raw_score": 24,
            "value_score": 8,
        }
    ]
    approved = [_add_llm_trace(item) for item in approved]
    (tmp_path / "data" / f"approved_{date_str}.json").write_text(json.dumps(approved, ensure_ascii=False), encoding="utf-8")
    raw = {"news": approved, "research": [], "funding": [], "policy": [], "events": []}
    (tmp_path / "data" / f"raw_{date_str}.json").write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    approved_urls = [item["url"] for item in approved]
    search_log = {
        "version": 1,
        "date": date_str,
        "generated_by": "search_executor",
        "provider": "llm_web",
        "llm_discovery_provider": "llm_web",
        "high_recall_enabled": True,
        "required_high_recall_rounds": ["llm_discovery", "llm_gap_audit"],
        "limit": 15,
        "rounds": [
            {"round": "r1", "queries": [{"query": "synthetic biology funding 2026", "executed": True, "provider": "llm_web"}], "candidates": approved_urls},
            {"round": "r2", "queries": [{"query": "synthetic biology research 2026", "executed": True, "provider": "llm_web"}], "candidates": []},
            {"round": "r3", "queries": [{"query": "synthetic biology policy 2026", "executed": True, "provider": "llm_web"}], "candidates": []},
            {"round": "r4", "queries": [{"query": "synthetic biology events 2026", "executed": True, "provider": "llm_web"}], "candidates": []},
            {"round": "r5", "queries": [{"query": "synthetic biology China 2026", "executed": True, "provider": "llm_web"}], "candidates": []},
            {"round": "llm_dynamic", "queries": [{"query": "synthetic biology dynamic validation 2026", "executed": True, "provider": "llm_web"}], "candidates": []},
            {"round": "llm_discovery", "queries": [{"query": "recent synthetic biology discovery", "executed": True, "provider": "llm_web", "web_search_tool_result": True}], "candidates": []},
            {"round": "llm_gap_audit", "queries": [{"query": "synthetic biology gap audit", "executed": True, "provider": "llm_web", "web_search_tool_result": True}], "candidates": []},
        ],
    }
    (tmp_path / "data" / f"search_log_{date_str}.json").write_text(json.dumps(search_log, ensure_ascii=False), encoding="utf-8")
    search_strategy = {
        "queries": [{"query": "synthetic biology dynamic validation 2026", "required": True}]
    }
    (tmp_path / "data" / f"search_strategy_{date_str}.json").write_text(json.dumps(search_strategy, ensure_ascii=False), encoding="utf-8")
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
    md = tmp_path / "reports" / f"{date_str}.md"
    md.write_text((ROOT / "tests" / "fixtures" / report_name).read_text(encoding="utf-8"), encoding="utf-8")
    html = tmp_path / "reports" / f"{date_str}.html"
    email = tmp_path / "reports" / f"{date_str}_email.html"
    if report_name == "valid_report.md":
        generate_from_template.generate(
            report_date=date_str,
            approved_path=tmp_path / "data" / f"approved_{date_str}.json",
            markdown_path=md,
            html_output=html,
            email_output=email,
        )
    else:
        html.write_text((ROOT / "tests" / "fixtures" / "valid_report.html").read_text(encoding="utf-8"), encoding="utf-8")
    return md, html


def _set_allow_simple_fallback(tmp_path: Path, enabled: bool) -> None:
    config_path = tmp_path / "config" / "email_config.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["allow_simple_fallback"] = enabled
    config_path.write_text(json.dumps(config), encoding="utf-8")


def test_send_gate_failure_does_not_call_smtp(tmp_path, monkeypatch):
    md, html = _write_runtime_tree(tmp_path, report_name="invalid_ai_report.md")
    monkeypatch.setattr(send_email, "CONFIG_DIR", tmp_path / "config")
    monkeypatch.setattr(send_email, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(send_email, "smtplib", type("SMTPModule", (), {"SMTP_SSL": lambda *a, **k: (_ for _ in ()).throw(AssertionError("SMTP called"))}))

    assert send_email.send_daily_report("2026-06-10", md, html) is False


def test_send_dry_run_passes_without_smtp(tmp_path, monkeypatch):
    md, html = _write_runtime_tree(tmp_path)
    monkeypatch.setattr(send_email, "CONFIG_DIR", tmp_path / "config")
    monkeypatch.setattr(send_email, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(send_email, "smtplib", type("SMTPModule", (), {"SMTP_SSL": lambda *a, **k: (_ for _ in ()).throw(AssertionError("SMTP called"))}))

    assert send_email.send_daily_report("2026-06-10", md, html, dry_run=True) is True


def test_send_gate_restores_report_pipeline_runtime_paths(tmp_path, monkeypatch):
    md, html = _write_runtime_tree(tmp_path)
    original_paths = (report_pipeline.CONFIG_DIR, report_pipeline.DATA_DIR, report_pipeline.REPORTS_DIR)
    monkeypatch.setattr(send_email, "CONFIG_DIR", tmp_path / "config")
    monkeypatch.setattr(send_email, "DATA_DIR", tmp_path / "data")

    result = send_email.validate_send_gate("2026-06-10", md, html, check_url_health=False)

    assert result["passed"], result["errors"]
    assert (report_pipeline.CONFIG_DIR, report_pipeline.DATA_DIR, report_pipeline.REPORTS_DIR) == original_paths


def test_send_gate_auto_resolves_runtime_root_from_report_paths(tmp_path, monkeypatch):
    actual_root = tmp_path / "actual"
    wrong_root = tmp_path / "wrong"
    md, html = _write_runtime_tree(actual_root)
    (wrong_root / "config").mkdir(parents=True)
    (wrong_root / "data").mkdir(parents=True)
    (wrong_root / "config" / "email_config.json").write_text(json.dumps({
        "enabled": True,
        "smtp_server": "smtp.example.com",
        "smtp_port": 465,
        "sender_email": "wrong@example.com",
        "sender_password": "not-real",
        "receiver_email": "wrong@example.com",
        "check_url_health": False,
    }), encoding="utf-8")
    (wrong_root / "data" / "approved_2026-06-10.json").write_text("[]", encoding="utf-8")

    monkeypatch.setattr(send_email, "CONFIG_DIR", wrong_root / "config")
    monkeypatch.setattr(send_email, "DATA_DIR", wrong_root / "data")

    result = send_email.validate_send_gate("2026-06-10", md, html, check_url_health=False)

    assert result["passed"], result["errors"]
    assert result["details"]["runtime_context"]["data_dir"] == str(actual_root / "data")
    assert any("自动切换运行目录" in warning for warning in result["warnings"])
    assert any("多个活跃运行目录" in warning for warning in result["warnings"])


def test_send_dry_run_does_not_require_email_config(tmp_path, monkeypatch):
    md, html = _write_runtime_tree(tmp_path)
    (tmp_path / "config" / "email_config.json").unlink()
    monkeypatch.setattr(send_email, "CONFIG_DIR", tmp_path / "config")
    monkeypatch.setattr(send_email, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(send_email, "smtplib", type("SMTPModule", (), {"SMTP_SSL": lambda *a, **k: (_ for _ in ()).throw(AssertionError("SMTP called"))}))
    checked_urls = []

    def healthy(urls, label="URL"):
        checked_urls.extend(urls)
        return {"is_valid": True, "errors": [], "checked_urls": [], "total_checked": len(urls)}

    monkeypatch.setattr(send_email, "validate_url_health", healthy)

    assert send_email.send_daily_report("2026-06-10", md, html, dry_run=True) is True
    assert "https://example.com/news/xinghe" in checked_urls


def test_load_email_config_falls_back_to_default_config_dir(tmp_path, monkeypatch):
    runtime_config_dir = tmp_path / "runtime-config"
    fallback_config_dir = tmp_path / "fallback-config"
    runtime_config_dir.mkdir()
    fallback_config_dir.mkdir()
    fallback_config = {
        "enabled": True,
        "smtp_server": "smtp.example.com",
        "smtp_port": 465,
        "sender_email": "fallback@example.com",
        "sender_password": "secret",
        "receiver_email": "receiver@example.com",
    }
    (fallback_config_dir / "email_config.json").write_text(json.dumps(fallback_config), encoding="utf-8")
    monkeypatch.setattr(send_email, "CONFIG_DIR", fallback_config_dir)

    loaded = send_email.load_email_config(runtime_config_dir)

    assert loaded["sender_email"] == "fallback@example.com"


def test_send_gate_blocks_unsafe_html(tmp_path, monkeypatch):
    md, html = _write_runtime_tree(tmp_path)
    html.write_text('<script>alert(1)</script>', encoding="utf-8")
    monkeypatch.setattr(send_email, "CONFIG_DIR", tmp_path / "config")
    monkeypatch.setattr(send_email, "DATA_DIR", tmp_path / "data")

    result = send_email.validate_send_gate("2026-06-10", md, html, check_url_health=False)

    assert not result["passed"]
    assert any("HTML安全" in error for error in result["errors"])


def test_send_gate_blocks_minimal_fallback_html(tmp_path, monkeypatch):
    md, html = _write_runtime_tree(tmp_path)
    html.write_text((ROOT / "tests" / "fixtures" / "valid_report.html").read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setattr(send_email, "CONFIG_DIR", tmp_path / "config")
    monkeypatch.setattr(send_email, "DATA_DIR", tmp_path / "data")

    result = send_email.validate_send_gate("2026-06-10", md, html, check_url_health=False)

    assert not result["passed"]
    assert any("模板样式" in error for error in result["errors"])


def test_send_gate_blocks_unapproved_h5_attachment_url(tmp_path, monkeypatch):
    md, html = _write_runtime_tree(tmp_path)
    html.write_text(
        '<div class="card-title">星河生物完成数千万元 pre-A 轮融资</div>'
        '<a href="https://example.com/news/xinghe">已批准</a>'
        '<a href="https://unapproved.example.com/news">未批准</a>',
        encoding="utf-8",
    )
    monkeypatch.setattr(send_email, "CONFIG_DIR", tmp_path / "config")
    monkeypatch.setattr(send_email, "DATA_DIR", tmp_path / "data")

    result = send_email.validate_send_gate("2026-06-10", md, html, check_url_health=False)

    assert not result["passed"]
    assert any("H5附件" in error and "approved" in error for error in result["errors"])
    assert "https://unapproved.example.com/news" in result["details"]["h5_url_consistency"]["missing_urls"]


def test_send_gate_blocks_unapproved_h5_src_url(tmp_path, monkeypatch):
    md, html = _write_runtime_tree(tmp_path)
    html.write_text(
        '<div class="card-title">星河生物完成数千万元 pre-A 轮融资</div>'
        '<A HREF=https://example.com/news/xinghe>已批准</A>'
        '<img SRC="https://tracker.example.com/pixel.png">',
        encoding="utf-8",
    )
    monkeypatch.setattr(send_email, "CONFIG_DIR", tmp_path / "config")
    monkeypatch.setattr(send_email, "DATA_DIR", tmp_path / "data")

    result = send_email.validate_send_gate("2026-06-10", md, html, check_url_health=False)

    assert not result["passed"]
    assert "https://tracker.example.com/pixel.png" in result["details"]["h5_url_consistency"]["missing_urls"]


def test_send_gate_blocks_dead_approved_url(tmp_path, monkeypatch):
    md, html = _write_runtime_tree(tmp_path)
    monkeypatch.setattr(send_email, "CONFIG_DIR", tmp_path / "config")
    monkeypatch.setattr(send_email, "DATA_DIR", tmp_path / "data")

    def dead_link_check(urls, label="URL"):
        assert "https://example.com/news/xinghe" in urls
        return {
            "is_valid": False,
            "errors": ["approved链接不可用: https://example.com/news/xinghe - HTTP状态异常: 404"],
            "checked_urls": [{"ok": False, "url": "https://example.com/news/xinghe"}],
            "total_checked": 1,
        }

    monkeypatch.setattr(send_email, "validate_url_health", dead_link_check)

    result = send_email.validate_send_gate("2026-06-10", md, html, check_url_health=True)

    assert not result["passed"]
    assert any("链接不可用" in error for error in result["errors"])


def test_send_gate_blocks_missing_search_log(tmp_path, monkeypatch):
    md, html = _write_runtime_tree(tmp_path)
    (tmp_path / "data" / "search_log_2026-06-10.json").unlink()
    monkeypatch.setattr(send_email, "CONFIG_DIR", tmp_path / "config")
    monkeypatch.setattr(send_email, "DATA_DIR", tmp_path / "data")

    result = send_email.validate_send_gate("2026-06-10", md, html, check_url_health=False)

    assert not result["passed"]
    assert any("搜索日志不存在" in error for error in result["errors"])


def test_send_gate_blocks_missing_search_strategy(tmp_path, monkeypatch):
    md, html = _write_runtime_tree(tmp_path)
    (tmp_path / "data" / "search_strategy_2026-06-10.json").unlink()
    monkeypatch.setattr(send_email, "CONFIG_DIR", tmp_path / "config")
    monkeypatch.setattr(send_email, "DATA_DIR", tmp_path / "data")

    result = send_email.validate_send_gate("2026-06-10", md, html, check_url_health=False)

    assert not result["passed"]
    assert any("LLM搜索策略缺失" in error for error in result["errors"])


def test_send_gate_blocks_empty_approved(tmp_path, monkeypatch):
    md, html = _write_runtime_tree(tmp_path)
    (tmp_path / "data" / "approved_2026-06-10.json").write_text("[]", encoding="utf-8")
    monkeypatch.setattr(send_email, "CONFIG_DIR", tmp_path / "config")
    monkeypatch.setattr(send_email, "DATA_DIR", tmp_path / "data")

    result = send_email.validate_send_gate("2026-06-10", md, html, check_url_health=False)

    assert not result["passed"]
    assert any("approved为空" in error for error in result["errors"])


def test_send_gate_blocks_when_all_approved_urls_were_already_sent(tmp_path, monkeypatch):
    md, html = _write_runtime_tree(tmp_path)
    history = {
        "version": 1,
        "entries": [{
            "url": "https://example.com/news/xinghe",
            "canonical_url": "https://example.com/news/xinghe",
            "urls": ["https://example.com/news/xinghe"],
            "title": "Previously sent",
            "fingerprint": "old",
            "date": "2026-06-10",
            "first_sent_date": "2026-06-10",
        }],
    }
    (tmp_path / "data" / "history_index.json").write_text(json.dumps(history, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(send_email, "CONFIG_DIR", tmp_path / "config")
    monkeypatch.setattr(send_email, "DATA_DIR", tmp_path / "data")

    blocked = send_email.validate_send_gate("2026-06-10", md, html, check_url_health=False)

    assert not blocked["passed"]
    assert any("均已发送过" in error for error in blocked["errors"])
    assert blocked["details"]["send_payload"]["effective_approved_count"] == 0


def test_send_gate_filters_sent_items_and_stages_incremental_send(tmp_path, monkeypatch, capsys):
    approved = [
        {
            "title": "旧合成生物平台扩产消息",
            "source": "SynBioBeta",
            "date": "2026-06-10",
            "summary": "旧合成生物制造平台扩产消息摘要。",
            "url": "https://example.com/news/xinghe",
            "type": "news",
            "source_round": "r1",
            "raw_score": 24,
            "value_score": 8,
        },
        {
            "title": "新合成生物平台签约扩产消息",
            "source": "SynBioBeta",
            "date": "2026-06-10",
            "summary": "新合成生物平台签约扩产消息摘要。",
            "url": "https://example.com/news/new-item",
            "type": "news",
            "source_round": "r1",
            "raw_score": 25,
            "value_score": 8,
        },
    ]
    md, html = _write_runtime_tree(tmp_path, approved_items=approved)
    search_log_path = tmp_path / "data" / "search_log_2026-06-10.json"
    search_log = json.loads(search_log_path.read_text(encoding="utf-8"))
    search_log["rounds"][0]["candidates"] = [
        "https://example.com/news/xinghe",
        "https://example.com/news/new-item",
    ]
    search_log_path.write_text(json.dumps(search_log, ensure_ascii=False), encoding="utf-8")
    history = {
        "version": 1,
        "entries": [{
            "url": "https://example.com/news/xinghe",
            "canonical_url": "https://example.com/news/xinghe",
            "urls": ["https://example.com/news/xinghe"],
            "title": "Previously sent",
            "fingerprint": "old",
            "date": "2026-06-10",
            "first_sent_date": "2026-06-10",
        }],
    }
    send_log = {"version": 1, "sends": [{"date": "2026-06-10", "status": "success", "send_mode": "auto"}]}
    (tmp_path / "data" / "history_index.json").write_text(json.dumps(history, ensure_ascii=False), encoding="utf-8")
    (tmp_path / "data" / "send_log.json").write_text(json.dumps(send_log, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(send_email, "CONFIG_DIR", tmp_path / "config")
    monkeypatch.setattr(send_email, "DATA_DIR", tmp_path / "data")

    gate = send_email.validate_send_gate("2026-06-10", md, html, check_url_health=False)

    assert gate["passed"], gate["errors"]
    assert gate["details"]["send_payload"]["original_approved_count"] == 2
    assert gate["details"]["send_payload"]["effective_approved_count"] == 1
    assert gate["details"]["send_payload"]["filtered_duplicate_count"] == 1
    assert gate["details"]["send_payload"]["staged"] is True
    assert any("已过滤 1 条已发送信息" in warning for warning in gate["warnings"])
    assert any("已有成功发送记录" in warning for warning in gate["warnings"])

    assert send_email.send_daily_report("2026-06-10", md, html, dry_run=True) is True
    output = capsys.readouterr().out
    assert "邮件发送门禁警告" in output
    assert "已过滤 1 条已发送信息" in output


def test_send_gate_blocks_approved_url_already_in_sent_registry(tmp_path, monkeypatch):
    md, html = _write_runtime_tree(tmp_path)
    approved_path = tmp_path / "data" / "approved_2026-06-10.json"
    approved = json.loads(approved_path.read_text(encoding="utf-8"))
    approved[0]["title"] = "方昕博士解读生物制造产业落地：四城市政策对比"
    approved[0]["url"] = "https://www.36kr.com/p/3051114996943496?utm_source=newsletter"
    approved_path.write_text(json.dumps(approved, ensure_ascii=False), encoding="utf-8")
    registry = {
        "version": 1,
        "registry": {
            "36kr:p:3051114996943496": {
                "first_sent_date": "2026-06-24",
                "title": "从实验室到应用场！方昕博士解读生物制造产业落地与投资逻辑",
            }
        },
    }
    (tmp_path / "data" / "sent_url_registry.json").write_text(json.dumps(registry, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(send_email, "CONFIG_DIR", tmp_path / "config")
    monkeypatch.setattr(send_email, "DATA_DIR", tmp_path / "data")

    result = send_email.validate_send_gate("2026-06-10", md, html, check_url_health=False)

    assert not result["passed"]
    assert any("均已发送过" in error for error in result["errors"])
    assert result["details"]["sent_url_registry"]["duplicate_indices"] == [1]
    assert result["details"]["sent_url_registry"]["duplicate_records"][0]["dedup_key"] == "36kr:p:3051114996943496"


def test_force_send_records_manual_resend(tmp_path, monkeypatch):
    md, html = _write_runtime_tree(tmp_path)
    send_log = {"version": 1, "sends": [{"date": "2026-06-10", "status": "success", "send_mode": "auto"}]}
    (tmp_path / "data" / "send_log.json").write_text(json.dumps(send_log, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(send_email, "CONFIG_DIR", tmp_path / "config")
    monkeypatch.setattr(send_email, "DATA_DIR", tmp_path / "data")
    sent_messages = []

    def record_send(config, msg):
        sent_messages.append(msg)

    monkeypatch.setattr(send_email, "send_message_via_smtp", record_send)

    assert send_email.send_daily_report("2026-06-10", md, html, force_send=True, send_mode="manual") is True
    assert len(sent_messages) == 1
    log = json.loads((tmp_path / "data" / "send_log.json").read_text(encoding="utf-8"))
    assert log["sends"][-1]["date"] == "2026-06-10"
    assert log["sends"][-1]["status"] == "success"
    assert log["sends"][-1]["forced"] is True
    assert log["sends"][-1]["send_mode"] == "manual"


def test_send_gate_health_check_includes_markdown_plain_urls(tmp_path, monkeypatch):
    md, html = _write_runtime_tree(tmp_path)
    md.write_text(
        md.read_text(encoding="utf-8") + "\n\n附加链接: https://example.com/news/from-markdown\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(send_email, "CONFIG_DIR", tmp_path / "config")
    monkeypatch.setattr(send_email, "DATA_DIR", tmp_path / "data")
    seen_urls = []

    def healthy(urls, label="URL"):
        seen_urls.extend(urls)
        return {"is_valid": True, "errors": [], "checked_urls": [], "total_checked": len(urls)}

    monkeypatch.setattr(send_email, "validate_url_health", healthy)

    send_email.validate_send_gate("2026-06-10", md, html, check_url_health=True)

    assert "https://example.com/news/from-markdown" in seen_urls


def test_smtp_500_returns_false_without_default_fallback(tmp_path, monkeypatch, capsys):
    md, html = _write_runtime_tree(tmp_path)
    monkeypatch.setattr(send_email, "CONFIG_DIR", tmp_path / "config")
    monkeypatch.setattr(send_email, "DATA_DIR", tmp_path / "data")

    def fail_send(config, msg):
        raise smtplib.SMTPResponseException(500, b"bad syntax")

    monkeypatch.setattr(send_email, "send_message_via_smtp", fail_send)

    assert send_email.send_daily_report("2026-06-10", md, html) is False
    output = capsys.readouterr().out
    assert "SMTP发送失败: code=500" in output
    assert "诊断建议" in output
    assert "降级发送" not in output


def test_smtp_500_simple_fallback_requires_config_flag(tmp_path, monkeypatch, capsys):
    md, html = _write_runtime_tree(tmp_path)
    approved_path = tmp_path / "data" / "approved_2026-06-10.json"
    approved = json.loads(approved_path.read_text(encoding="utf-8"))
    approved[0]["urls"] = [
        "https://example.com/news/xinghe",
        "https://example.com/news/xinghe-secondary?utm_source=newsletter",
    ]
    approved_path.write_text(json.dumps(approved, ensure_ascii=False), encoding="utf-8")
    _set_allow_simple_fallback(tmp_path, True)
    monkeypatch.setattr(send_email, "CONFIG_DIR", tmp_path / "config")
    monkeypatch.setattr(send_email, "DATA_DIR", tmp_path / "data")
    sent_messages = []

    def fail_then_record(config, msg):
        if not sent_messages:
            sent_messages.append(msg)
            raise smtplib.SMTPResponseException(500, b"bad syntax")
        sent_messages.append(msg)

    monkeypatch.setattr(send_email, "send_message_via_smtp", fail_then_record)

    assert send_email.send_daily_report("2026-06-10", md, html) is True
    output = capsys.readouterr().out
    assert "邮件已降级发送：仅HTML正文，无附件" in output
    assert len(sent_messages) == 2
    assert sent_messages[1].get_content_type() == "text/html"
    history = json.loads((tmp_path / "data" / "history_index.json").read_text(encoding="utf-8"))
    assert history["entries"][0]["url"] == "https://example.com/news/xinghe"
    assert history["entries"][0]["canonical_url"] == "https://example.com/news/xinghe"
    assert {entry["canonical_url"] for entry in history["entries"]} == {
        "https://example.com/news/xinghe",
        "https://example.com/news/xinghe-secondary",
    }
    assert all("https://example.com/news/xinghe-secondary?utm_source=newsletter" in entry["urls"] for entry in history["entries"])
    registry = json.loads((tmp_path / "data" / "sent_url_registry.json").read_text(encoding="utf-8"))
    assert set(registry["registry"]) == {
        "example.com/news/xinghe",
        "example.com/news/xinghe-secondary",
    }


def test_history_index_update_deduplicates_existing_secondary_urls(tmp_path, monkeypatch):
    (tmp_path / "data").mkdir()
    history_path = tmp_path / "data" / "history_index.json"
    history_path.write_text(json.dumps({
        "version": 1,
        "entries": [{
            "url": "https://example.com/news/primary",
            "canonical_url": "https://example.com/news/primary",
            "urls": ["https://example.com/news/secondary?utm_source=old"],
            "title": "Previously sent",
            "fingerprint": "old",
            "date": "2026-06-09",
            "first_sent_date": "2026-06-09",
            "last_sent_date": "2026-06-09",
            "sent_count": 1,
        }],
    }, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(send_email, "DATA_DIR", tmp_path / "data")

    send_email._update_history_index("2026-06-10", [{
        "title": "Same story from secondary URL",
        "summary": "Same story",
        "date": "2026-06-10",
        "url": "https://example.com/news/secondary",
    }])

    history = json.loads(history_path.read_text(encoding="utf-8"))
    assert len(history["entries"]) == 1
    assert history["entries"][0]["last_sent_date"] == "2026-06-10"
    assert history["entries"][0]["sent_count"] == 2
    registry = json.loads((tmp_path / "data" / "sent_url_registry.json").read_text(encoding="utf-8"))
    assert "example.com/news/secondary" in registry["registry"]


def test_history_index_update_increments_sent_count_once_per_existing_story(tmp_path, monkeypatch):
    (tmp_path / "data").mkdir()
    history_path = tmp_path / "data" / "history_index.json"
    history_path.write_text(json.dumps({
        "version": 1,
        "entries": [{
            "url": "https://example.com/news/primary",
            "canonical_url": "https://example.com/news/primary",
            "dedup_key": "example.com/news/primary",
            "urls": [
                "https://example.com/news/primary",
                "https://example.com/news/secondary",
            ],
            "title": "Previously sent",
            "fingerprint": "old",
            "date": "2026-06-09",
            "first_sent_date": "2026-06-09",
            "last_sent_date": "2026-06-09",
            "sent_count": 1,
        }],
    }, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(send_email, "DATA_DIR", tmp_path / "data")

    send_email._update_history_index("2026-06-10", [{
        "title": "Same story",
        "summary": "Same story",
        "date": "2026-06-10",
        "url": "https://example.com/news/primary",
        "urls": [
            "https://example.com/news/primary",
            "https://example.com/news/secondary",
        ],
    }])

    history = json.loads(history_path.read_text(encoding="utf-8"))
    assert len(history["entries"]) == 1
    assert history["entries"][0]["sent_count"] == 2
