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


def _write_runtime_tree(tmp_path: Path, report_name: str = "valid_report.md"):
    (tmp_path / "config").mkdir()
    (tmp_path / "data").mkdir()
    (tmp_path / "reports").mkdir()
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
    approved = [
        {
            "title": "星河生物完成数千万元 pre-A 轮融资",
            "source": "SynBioBeta",
            "date": "2026-06-10",
            "summary": "星河生物完成数千万元 pre-A 轮融资，用于合成生物制造平台扩产。",
            "url": "https://example.com/news/xinghe",
            "type": "news",
            "raw_score": 24,
            "value_score": 8,
        }
    ]
    (tmp_path / "data" / "approved_2026-06-10.json").write_text(json.dumps(approved, ensure_ascii=False), encoding="utf-8")
    raw = {"news": approved, "research": [], "funding": [], "policy": [], "events": []}
    (tmp_path / "data" / "raw_2026-06-10.json").write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    md = tmp_path / "reports" / "2026-06-10.md"
    md.write_text((ROOT / "tests" / "fixtures" / report_name).read_text(encoding="utf-8"), encoding="utf-8")
    html = tmp_path / "reports" / "2026-06-10.html"
    email = tmp_path / "reports" / "2026-06-10_email.html"
    if report_name == "valid_report.md":
        generate_from_template.generate(
            report_date="2026-06-10",
            approved_path=tmp_path / "data" / "approved_2026-06-10.json",
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
