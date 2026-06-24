import json
import pytest
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import llm_judge


class _FakeResponse:
    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return self.body


def test_heuristic_rejects_basic_biology_without_engineering():
    decision = llm_judge.heuristic_relevance_decision({
        "title": "Cell: IL-1beta signal regulates neuronal social behavior",
        "summary": "The paper describes endogenous receptor signaling and neural circuits.",
        "url": "https://example.com/basic-biology",
        "type": "research",
    })

    assert not decision.is_approved
    assert decision.domain_relevance == "out_of_scope"
    assert "自然过程" in decision.reject_message() or "基础生物学" in decision.reject_message()


def test_heuristic_includes_engineered_cell_factory():
    decision = llm_judge.heuristic_relevance_decision({
        "title": "工程菌细胞工厂提升萜类化合物生物制造效率",
        "summary": "团队通过代谢工程和动态调控构建底盘菌株，实现高效发酵生产。",
        "url": "https://example.com/synbio-cell-factory",
        "type": "research",
    })

    assert decision.is_approved
    assert decision.domain_relevance == "core_synbio"
    assert decision.evidence_spans


def test_normalize_llm_decision_requires_evidence_for_approval():
    decision = llm_judge.normalize_llm_decision({
        "decision": "include",
        "domain_relevance": "core_synbio",
        "confidence": 0.95,
        "reason": "looks relevant",
        "evidence_spans": [],
        "section": "news",
    })

    assert not decision.is_approved
    assert decision.decision == "include"


def test_anthropic_client_parses_messages_response_without_logging_secret():
    response_payload = {
        "content": [{
            "type": "text",
            "text": json.dumps({
                "decision": "include",
                "domain_relevance": "core_synbio",
                "confidence": 0.91,
                "reason": "含细胞工厂和代谢工程证据",
                "evidence_spans": ["细胞工厂", "代谢工程"],
                "section": "research",
                "reject_reason": None,
            }, ensure_ascii=False),
        }]
    }
    seen = {}

    def fake_opener(request, timeout=45):
        seen["url"] = request.full_url
        seen["token"] = request.headers.get("X-api-key") or request.headers.get("x-api-key")
        seen["body"] = json.loads(request.data.decode("utf-8"))
        return _FakeResponse(json.dumps(response_payload).encode("utf-8"))

    client = llm_judge.AnthropicRelevanceClient(
        base_url="https://example.invalid",
        auth_token="test-token",
        model="test-model",
        opener=fake_opener,
    )
    decision = client.judge({
        "title": "工程菌细胞工厂提升萜类化合物生物制造效率",
        "summary": "代谢工程构建细胞工厂。",
        "type": "research",
    })

    assert seen["url"] == "https://example.invalid/v1/messages"
    assert seen["token"] == "test-token"
    assert seen["body"]["model"] == "test-model"
    assert decision.is_approved
    assert decision.provider == "llm"


def test_anthropic_client_does_not_duplicate_v1_path():
    response_payload = {
        "content": json.dumps({
            "decision": "include",
            "domain_relevance": "core_synbio",
            "confidence": 0.90,
            "reason": "含生物制造证据",
            "evidence_spans": ["biomanufacturing"],
            "section": "news",
        })
    }
    seen = {}

    def fake_opener(request, timeout=45):
        seen["url"] = request.full_url
        seen["authorization"] = request.headers.get("Authorization")
        return _FakeResponse(json.dumps(response_payload).encode("utf-8"))

    client = llm_judge.AnthropicRelevanceClient(
        base_url="https://example.invalid/v1",
        auth_token="test-token",
        opener=fake_opener,
    )

    decision = client.judge({"title": "Synthetic biology biomanufacturing update"})

    assert seen["url"] == "https://example.invalid/v1/messages"
    assert seen["authorization"] == "Bearer test-token"
    assert decision.is_approved


def test_judge_item_relevance_auto_falls_back_when_unconfigured(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)

    decision = llm_judge.judge_item_relevance({
        "title": "工程菌细胞工厂提升萜类化合物生物制造效率",
        "summary": "代谢工程构建细胞工厂。",
        "type": "research",
    }, mode="auto")

    assert decision.is_approved
    assert decision.provider == "heuristic"


def test_judge_item_relevance_llm_failure_raises():
    class BrokenClient:
        is_configured = True

        def judge(self, item):
            raise RuntimeError("provider unavailable")

    with pytest.raises(RuntimeError) as exc_info:
        llm_judge.judge_item_relevance({}, mode="llm", client=BrokenClient())

    assert "LLM领域审计失败" in str(exc_info.value)


def test_judge_item_relevance_auto_configured_failure_raises():
    class BrokenClient:
        is_configured = True

        def judge(self, item):
            raise RuntimeError("provider unavailable")

    with pytest.raises(RuntimeError) as exc_info:
        llm_judge.judge_item_relevance({
            "title": "工程菌细胞工厂提升萜类化合物生物制造效率",
            "summary": "代谢工程构建细胞工厂。",
            "type": "research",
        }, mode="auto", client=BrokenClient())

    assert "LLM API已配置但调用失败" in str(exc_info.value)


def test_judge_item_relevance_auto_not_configured_fallbacks():
    class NotConfiguredClient:
        is_configured = False

        def judge(self, item):
            raise RuntimeError("should not be called")

    decision = llm_judge.judge_item_relevance({
        "title": "工程菌细胞工厂提升萜类化合物生物制造效率",
        "summary": "代谢工程构建细胞工厂。",
        "type": "research",
    }, mode="auto", client=NotConfiguredClient())

    assert decision.is_approved
    assert decision.provider == "heuristic"
