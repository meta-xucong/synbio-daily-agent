import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import render_utils


def test_safe_text_escapes_html():
    assert render_utils.safe_text('<script>alert("x")</script>') == "&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt;"


def test_safe_url_allows_http_and_https():
    assert render_utils.safe_url("https://example.com/a") == "https://example.com/a"
    assert render_utils.safe_url("http://example.com/a") == "http://example.com/a"


def test_safe_url_rejects_unsafe_schemes():
    for url in ["javascript:alert(1)", "data:text/html,boom", "/relative/path", ""]:
        try:
            render_utils.safe_url(url)
        except ValueError:
            pass
        else:
            raise AssertionError(f"expected unsafe url rejection for {url!r}")
