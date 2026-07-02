import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import llm_health_check
import llm_judge


class _Client:
    def __init__(self, decision):
        self._decision = decision

    def judge(self, item):
        return self._decision


def test_relevance_health_check_requires_decoded_chinese_evidence():
    decision = llm_judge.Decision(
        is_approved=True,
        domain_relevance="core_synbio",
        confidence=0.9,
        reason="Only saw PHA but not decoded Chinese evidence",
        evidence_spans=["?????PHA?????"],
        section="news",
        provider="llm-test",
        raw_response='{"evidence_spans":["?????PHA?????"]}',
    )

    with pytest.raises(RuntimeError) as exc_info:
        llm_health_check._check_relevance(_Client(decision))

    assert "Chinese input was corrupted" in str(exc_info.value)


def test_relevance_health_check_accepts_decoded_chinese_evidence():
    decision = llm_judge.Decision(
        is_approved=True,
        domain_relevance="core_synbio",
        confidence=0.9,
        reason="含蓝晶微生物、生物制造和细胞工厂证据",
        evidence_spans=["蓝晶微生物", "生物制造", "细胞工厂"],
        section="news",
        provider="llm-test",
        raw_response='{"evidence_spans":["蓝晶微生物","生物制造"]}',
    )

    result = llm_health_check._check_relevance(_Client(decision))

    assert result["decoded_marker_ok"] is True
