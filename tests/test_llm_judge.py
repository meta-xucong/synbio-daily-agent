import json
import pytest
import sys
from io import BytesIO
from pathlib import Path
from urllib.error import HTTPError


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


def test_date_prompt_prioritizes_article_header_evidence_and_expired_events():
    prompt = llm_judge._build_date_validation_prompt({
        "title": "Synthetic biology forum",
        "type": "events",
        "content_type": "event_preview",
        "date": "2026-07-10",
        "summary": "The forum was held on July 3.",
        "date_verification": {
            "evidence": "article header near title: Synthetic biology forum | 2026-07-03",
        },
    }, "2026-07-10", ascii_safe=True)

    assert "article heading" in prompt
    assert "event_preview" in prompt
    assert '"content_type": "event_preview"' in prompt
    assert "2026-07-03" in prompt


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


def test_aiself_client_sends_ascii_safe_prompt_for_chinese_candidate():
    response_payload = {
        "content": [{
            "type": "text",
            "text": json.dumps({
                "decision": "include",
                "domain_relevance": "core_synbio",
                "confidence": 0.92,
                "reason": "decoded Chinese candidate contains PHA cell-factory evidence",
                "evidence_spans": ["蓝晶微生物PHA产业化", "细胞工厂"],
                "section": "news",
                "reject_reason": None,
            }, ensure_ascii=False),
        }]
    }
    seen = {}

    def fake_opener(request, timeout=45):
        body = json.loads(request.data.decode("utf-8"))
        seen["content"] = body["messages"][0]["content"]
        seen["content_type"] = request.headers.get("Content-type") or request.headers.get("Content-Type")
        return _FakeResponse(json.dumps(response_payload).encode("utf-8"))

    client = llm_judge.AnthropicRelevanceClient(
        base_url="https://aiself.vip",
        auth_token="test-token",
        model="kimi-for-coding",
        opener=fake_opener,
    )
    decision = client.judge({
        "title": "蓝晶微生物PHA产业化",
        "summary": "工程菌株和发酵放大。",
        "type": "news",
    })

    assert client.use_ascii_prompts
    assert all(ord(ch) < 128 for ch in seen["content"])
    assert "\\u84dd\\u6676\\u5fae\\u751f\\u7269" in seen["content"]
    assert "application/json" in seen["content_type"]
    assert decision.is_approved


def test_ascii_prompt_can_be_disabled_for_aiself(monkeypatch):
    monkeypatch.setenv("SYNBIO_LLM_ASCII_PROMPTS", "0")
    client = llm_judge.AnthropicRelevanceClient(
        base_url="https://aiself.vip",
        auth_token="test-token",
    )

    assert not client.use_ascii_prompts


def test_ccswitch_local_proxy_defaults_to_kimi_and_utf8(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://127.0.0.1:15721")
    client = llm_judge.AnthropicRelevanceClient(
        base_url="http://127.0.0.1:15721",
        auth_token="PROXY_MANAGED",
        model=llm_judge._default_model(),
    )

    assert client.model == "kimi-for-coding"
    assert not client.use_ascii_prompts


def test_kimi_official_client_disables_thinking_for_json_judging():
    response_payload = {
        "content": [{
            "type": "text",
            "text": json.dumps({
                "decision": "include",
                "domain_relevance": "core_synbio",
                "confidence": 0.90,
                "reason": "含合成生物学直接证据",
                "evidence_spans": ["synthetic biology"],
                "section": "news",
                "reject_reason": None,
            }, ensure_ascii=False),
        }]
    }
    seen = {}

    def fake_opener(request, timeout=45):
        seen["body"] = json.loads(request.data.decode("utf-8"))
        return _FakeResponse(json.dumps(response_payload).encode("utf-8"))

    client = llm_judge.AnthropicRelevanceClient(
        base_url="https://api.kimi.com/coding",
        auth_token="test-token",
        model="kimi-for-coding",
        opener=fake_opener,
    )
    decision = client.judge({
        "title": "Synthetic biology update",
        "summary": "Synthetic biology and biomanufacturing progress.",
        "type": "news",
    })

    assert seen["body"]["thinking"] == {"type": "disabled"}
    assert decision.is_approved


def test_anthropic_client_parses_date_validation_response():
    response_payload = {
        "content": [{
            "type": "text",
            "text": json.dumps({
                "is_date_valid": False,
                "confidence": 0.96,
                "reason": "候选日期更像页脚最近内容日期，不像文章真实发布时间",
                "evidence_spans": ["该轮融资于2023年1月完成交割", "氪记2022"],
                "suspected_actual_date": "2023-01-12",
            }, ensure_ascii=False),
        }]
    }
    seen = {}

    def fake_opener(request, timeout=45):
        seen["body"] = json.loads(request.data.decode("utf-8"))
        return _FakeResponse(json.dumps(response_payload).encode("utf-8"))

    client = llm_judge.AnthropicRelevanceClient(
        base_url="https://api.kimi.com/coding",
        auth_token="test-token",
        model="kimi-for-coding",
        opener=fake_opener,
    )
    decision = client.judge_date({
        "title": "从躺着拿钱到融资内卷，合成生物回归商业理性 | 氪记2022-36氪",
        "summary": "该轮融资于2023年1月完成交割",
        "date": "2026-07-03",
        "search_date": "2026-07-03",
        "type": "research",
    }, "2026-07-03")

    assert seen["body"]["thinking"] == {"type": "disabled"}
    assert not decision.is_date_valid
    assert decision.suspected_actual_date == "2023-01-12"


def test_llm_client_falls_back_to_secondary_provider_on_http_403(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_FALLBACKS", json.dumps([
        {
            "base_url": "https://aiself.vip",
            "auth_token": "fallback-token",
            "model": "deepseek-chat",
        }
    ]))
    seen = {"urls": []}
    response_payload = {
        "content": [{
            "type": "text",
            "text": json.dumps({
                "decision": "include",
                "domain_relevance": "core_synbio",
                "confidence": 0.91,
                "reason": "含合成生物证据",
                "evidence_spans": ["合成生物", "生物制造"],
                "section": "news",
                "reject_reason": None,
            }, ensure_ascii=False),
        }]
    }

    def fake_opener(request, timeout=45):
        seen["urls"].append(request.full_url)
        if "api.kimi.com" in request.full_url:
            raise HTTPError(
                request.full_url,
                403,
                "Forbidden",
                hdrs=None,
                fp=BytesIO(b'{"error":{"message":"usage limit exceeded"}}'),
            )
        return _FakeResponse(json.dumps(response_payload).encode("utf-8"))

    client = llm_judge.AnthropicRelevanceClient(
        base_url="https://api.kimi.com/coding",
        auth_token="primary-token",
        model="kimi-for-coding",
        opener=fake_opener,
    )
    decision = client.judge({
        "title": "Synthetic biology update",
        "summary": "Synthetic biology and biomanufacturing progress.",
        "type": "news",
    })

    assert decision.is_approved
    assert any("api.kimi.com" in url for url in seen["urls"])
    assert any("aiself.vip" in url for url in seen["urls"])
    assert client.last_used_model == "deepseek-chat"


def test_llm_client_falls_back_on_malformed_date_json(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_FALLBACKS", json.dumps([
        {
            "base_url": "https://aiself.vip",
            "auth_token": "fallback-token",
            "model": "deepseek-chat",
        }
    ]))
    calls = []

    def fake_opener(request, timeout=45):
        calls.append(request.full_url)
        if "api.kimi.com" in request.full_url:
            return _FakeResponse(json.dumps({
                "content": [{"type": "text", "text": '{"is_date_valid": true "confidence": 0.8}'}]
            }).encode("utf-8"))
        return _FakeResponse(json.dumps({
            "content": [{
                "type": "text",
                "text": json.dumps({
                    "is_date_valid": True,
                    "confidence": 0.95,
                    "reason": "备用provider返回了合法JSON",
                    "evidence_spans": ["2026-07-08", "正式开园"],
                    "suspected_actual_date": None,
                }, ensure_ascii=False),
            }]
        }).encode("utf-8"))

    client = llm_judge.AnthropicRelevanceClient(
        base_url="https://api.kimi.com/coding",
        auth_token="primary-token",
        model="kimi-for-coding",
        opener=fake_opener,
    )
    decision = client.judge_date({
        "title": "诺赫合成生物产业园开园",
        "summary": "7月3日产业园正式开园。",
        "date": "2026-07-03",
        "search_date": "2026-07-03",
        "type": "events",
    }, "2026-07-09")

    assert decision.is_date_valid
    assert any("api.kimi.com" in url for url in calls)
    assert any("aiself.vip" in url for url in calls)


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


def test_material_biomanufacturing_company_event_overrides_llm_rejection():
    class RejectingClient:
        is_configured = True

        def judge(self, item):
            return llm_judge.Decision(
                is_approved=False,
                domain_relevance="out_of_scope",
                confidence=0.82,
                reason="ordinary corporate news",
                reject_reason="no technical synthetic biology content",
                section="news",
                provider="llm-test",
            )

    decision = llm_judge.judge_item_relevance({
        "title": "688639，实控人被刑拘！紧急辞职！",
        "summary": (
            "华恒生物公告称，公司实控人、董事长因涉嫌非法吸收公众存款罪被刑事拘留。"
            "公司主营业务为生物制造，不涉及上述事项。"
        ),
        "type": "news",
    }, mode="llm", client=RejectingClient())

    assert decision.is_approved
    assert decision.domain_relevance == "adjacent"
    assert decision.provider == "llm-test+material_event_rule"
    assert any("生物制造" in span for span in decision.evidence_spans)


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
