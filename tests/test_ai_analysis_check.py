import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import ai_analysis_check


def test_ai_analysis_allows_numbers_grounded_in_body():
    result = ai_analysis_check.validate_ai_analysis(str(ROOT / "tests" / "fixtures" / "valid_report.md"))
    assert not result["has_errors"]


def test_ai_analysis_blocks_ungrounded_entity_and_number():
    result = ai_analysis_check.validate_ai_analysis(str(ROOT / "tests" / "fixtures" / "invalid_ai_report.md"))
    assert result["has_errors"]
    assert any("未来科技" in error for error in result["errors"])
    assert any("143家" in error for error in result["errors"])


def test_ai_analysis_cli_exits_nonzero_on_errors():
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "ai_analysis_check.py"),
            "--report",
            str(ROOT / "tests" / "fixtures" / "invalid_ai_report.md"),
        ],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
    )
    assert result.returncode == 1
