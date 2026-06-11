import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import send_email


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
            "value_score": 8,
        }
    ]
    (tmp_path / "data" / "approved_2026-06-10.json").write_text(json.dumps(approved, ensure_ascii=False), encoding="utf-8")
    raw = {"news": approved, "research": [], "funding": [], "policy": [], "events": []}
    (tmp_path / "data" / "raw_2026-06-10.json").write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    md = tmp_path / "reports" / "2026-06-10.md"
    md.write_text((ROOT / "tests" / "fixtures" / report_name).read_text(encoding="utf-8"), encoding="utf-8")
    html = tmp_path / "reports" / "2026-06-10.html"
    html.write_text((ROOT / "tests" / "fixtures" / "valid_report.html").read_text(encoding="utf-8"), encoding="utf-8")
    return md, html


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
