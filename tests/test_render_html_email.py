import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import render_email
import render_html


def _approved(**overrides):
    item = {
        "title": '<script>alert("x")</script>',
        "source": "SynBioBeta",
        "date": "2026-06-10",
        "summary": "Safe summary with <b>literal markup</b>.",
        "url": "https://example.com/news/safe",
        "type": "news",
    }
    item.update(overrides)
    return item


def test_render_report_html_escapes_text_and_uses_safe_link_attrs():
    html = render_html.render_report_html([_approved()], "2026-06-10")

    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert "rel=\"noopener noreferrer\"" in html
    assert "流水线追踪" in html


def test_render_email_html_escapes_text_and_uses_safe_link_attrs():
    html = render_email.render_email_html([_approved()], "2026-06-10")

    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert "rel=\"noopener noreferrer\"" in html


def test_renderers_reject_unsafe_urls():
    unsafe = _approved(url="javascript:alert(1)")
    for render in (render_html.render_report_html, render_email.render_email_html):
        try:
            render([unsafe], "2026-06-10")
        except ValueError:
            pass
        else:
            raise AssertionError("unsafe URL was not rejected")
