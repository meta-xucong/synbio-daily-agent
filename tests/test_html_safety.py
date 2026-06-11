import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import html_safety


def test_validate_html_safety_rejects_active_content():
    for html in [
        "<script>alert(1)</script>",
        '<a href="javascript:alert(1)">x</a>',
        '<img src="x" onerror="alert(1)">',
        "<iframe src='https://example.com'></iframe>",
        "<object></object>",
        "<embed>",
    ]:
        result = html_safety.validate_html_safety(html)
        assert not result["is_safe"], html


def test_validate_html_safety_requires_rel_for_blank_links():
    bad = '<a href="https://example.com" target="_blank">x</a>'
    good = '<a href="https://example.com" target="_blank" rel="noopener noreferrer">x</a>'

    assert not html_safety.validate_html_safety(bad)["is_safe"]
    assert html_safety.validate_html_safety(good)["is_safe"]
