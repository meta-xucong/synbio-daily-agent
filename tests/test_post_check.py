import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import post_check


def test_post_check_blocks_missing_pipeline_trace(tmp_path, monkeypatch):
    reports = tmp_path / "reports"
    data = tmp_path / "data"
    reports.mkdir()
    data.mkdir()
    (reports / "2026-06-10.md").write_text("# 合成生物行业日报\n\nhttps://example.com/news/xinghe", encoding="utf-8")
    approved = [{"title": "星河生物", "url": "https://example.com/news/xinghe"}]
    (data / "approved_2026-06-10.json").write_text(json.dumps(approved, ensure_ascii=False), encoding="utf-8")

    monkeypatch.setattr(post_check, "REPORTS_DIR", reports)
    monkeypatch.setattr(post_check, "DATA_DIR", data)

    result = post_check.post_check("2026-06-10")

    assert not result["can_send"]
    assert any("流水线追踪" in error for error in result["errors"])


def test_post_check_accepts_string_urls_field(tmp_path, monkeypatch):
    reports = tmp_path / "reports"
    data = tmp_path / "data"
    reports.mkdir()
    data.mkdir()
    (reports / "2026-06-10.md").write_text(
        "# 合成生物行业日报\n\n流水线追踪：approved=1\n\n"
        "| 标题 | 来源 | 时间 | 摘要 | 链接 |\n"
        "|---|---|---|---|---|\n"
        "| 星河生物 | SynBioBeta | 2026-06-10 | 扩产。 | https://example.com/news/secondary |\n",
        encoding="utf-8",
    )
    approved = [{
        "title": "星河生物",
        "url": "https://example.com/news/primary",
        "urls": "https://example.com/news/secondary",
    }]
    (data / "approved_2026-06-10.json").write_text(json.dumps(approved, ensure_ascii=False), encoding="utf-8")

    monkeypatch.setattr(post_check, "REPORTS_DIR", reports)
    monkeypatch.setattr(post_check, "DATA_DIR", data)

    result = post_check.post_check("2026-06-10")

    assert result["can_send"], result["errors"]
