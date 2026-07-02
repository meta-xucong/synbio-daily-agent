import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import report_pipeline
import search_executor


def _write_plan_files(tmp_path):
    config = {
        "rounds": [
            {
                "round_id": "r1",
                "theme": "base",
                "required_queries": ["合成生物 最新新闻 今日"],
            }
        ]
    }
    strategy = {
        "strategy_round_id": "llm_dynamic",
        "queries": [{"query": "蓝晶微生物 PHA 项目 进展", "required": True}],
    }
    search_config = tmp_path / "search_queries.json"
    strategy_path = tmp_path / "search_strategy_2026-06-30.json"
    search_config.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
    strategy_path.write_text(json.dumps(strategy, ensure_ascii=False), encoding="utf-8")
    return search_config, strategy_path


def test_load_search_plan_includes_base_and_llm_dynamic(tmp_path):
    search_config, strategy_path = _write_plan_files(tmp_path)

    rounds = search_executor.load_search_plan(search_config, strategy_path)

    assert [round_entry["round"] for round_entry in rounds] == [
        "r1",
        "llm_dynamic",
        "llm_discovery",
        "llm_gap_audit",
    ]
    assert rounds[0]["queries"] == ["合成生物 最新新闻 今日"]
    assert rounds[1]["queries"] == ["蓝晶微生物 PHA 项目 进展"]
    assert rounds[2]["requires_llm_web"] is True
    assert rounds[3]["requires_llm_web"] is True


def test_load_search_plan_accepts_utf8_bom_files(tmp_path):
    search_config, strategy_path = _write_plan_files(tmp_path)
    search_config.write_bytes(b"\xef\xbb\xbf" + search_config.read_bytes())

    rounds = search_executor.load_search_plan(search_config, strategy_path)

    assert rounds[0]["queries"] == ["合成生物 最新新闻 今日"]


def test_load_search_plan_dedupes_dynamic_queries_already_in_base(tmp_path):
    config = {
        "rounds": [{
            "round_id": "r1",
            "theme": "base",
            "required_queries": ["合成生物 最新新闻 今日", "site:dg.gov.cn 合成生物 生物制造 产业园"],
        }]
    }
    strategy = {
        "strategy_round_id": "llm_dynamic",
        "queries": [
            {"query": "site:dg.gov.cn 合成生物 生物制造 产业园", "required": True},
            {"query": "未来健康产业大会 合成生物学创新产业峰会", "required": True},
        ],
    }
    search_config = tmp_path / "search_queries.json"
    strategy_path = tmp_path / "search_strategy_2026-07-02.json"
    search_config.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
    strategy_path.write_text(json.dumps(strategy, ensure_ascii=False), encoding="utf-8")

    rounds = search_executor.load_search_plan(search_config, strategy_path)

    dynamic = next(round_entry for round_entry in rounds if round_entry["round"] == "llm_dynamic")
    assert dynamic["queries"] == ["未来健康产业大会 合成生物学创新产业峰会"]


def test_search_executor_fixture_output_builds_raw(tmp_path):
    search_config, strategy_path = _write_plan_files(tmp_path)
    fixture = tmp_path / "fixture.json"
    fixture.write_text(json.dumps({
        "queries": {
            "合成生物 最新新闻 今日": [
                {
                    "title": "合成生物中试平台落地",
                    "url": "https://example.com/news/platform",
                    "snippet": "生物制造中试平台发布。",
                    "source": "Example",
                    "date": "2026-06-30",
                }
            ],
            "蓝晶微生物 PHA 项目 进展": [],
        }
    }, ensure_ascii=False), encoding="utf-8")
    output = tmp_path / "search_log_2026-06-30.json"

    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / "search_executor.py"),
            "--date",
            "2026-06-30",
            "--search-config",
            str(search_config),
            "--strategy",
            str(strategy_path),
            "--provider",
            "fixture",
            "--llm-discovery-provider",
            "fixture",
            "--fixture",
            str(fixture),
            "--output",
            str(output),
        ],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    search_log = json.loads(output.read_text(encoding="utf-8"))
    assert search_log["generated_by"] == "search_executor"
    assert search_log["provider"] == "fixture"
    assert search_log["llm_discovery_provider"] == "fixture"
    assert search_log["high_recall_enabled"] is True
    assert search_log["rounds"][0]["queries"][0]["executed"] is True
    assert search_log["rounds"][0]["queries"][0]["result_count"] == 1

    raw = report_pipeline.build_raw_from_search_log(search_log, report_date="2026-06-30")
    items = [
        item
        for bucket in ("news", "research", "funding", "policy", "events")
        for item in raw[bucket]
    ]
    assert items[0]["title"] == "合成生物中试平台落地"
    assert items[0]["source_round"] == "r1"
    assert items[0]["source_query"] == "合成生物 最新新闻 今日"


def test_search_executor_fails_closed_without_provider(tmp_path, monkeypatch):
    search_config, strategy_path = _write_plan_files(tmp_path)
    output = tmp_path / "search_log_2026-06-30.json"
    for key in search_executor.PROVIDER_ENV_KEYS.values():
        monkeypatch.delenv(key, raising=False)
    monkeypatch.delenv("SYNBIO_SEARCH_FIXTURE", raising=False)

    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / "search_executor.py"),
            "--date",
            "2026-06-30",
            "--search-config",
            str(search_config),
            "--strategy",
            str(strategy_path),
            "--output",
            str(output),
        ],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 2
    assert "no configured fast search provider" in completed.stderr
    assert not output.exists()


def test_auto_provider_requires_fast_search_even_when_kimi_is_configured(monkeypatch):
    for key in search_executor.PROVIDER_ENV_KEYS.values():
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://example.invalid")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "test-token")

    try:
        search_executor.make_provider("auto")
    except search_executor.NoSearchProviderConfigured as exc:
        message = str(exc)
        assert "fast search provider" in message
        assert "SERPER_API_KEY" in message
        assert "llm_web is reserved" in message
    else:
        raise AssertionError("provider=auto must not silently use llm_web for base queries")


def test_auto_provider_can_opt_in_to_llm_web_for_diagnostics(monkeypatch):
    for key in search_executor.PROVIDER_ENV_KEYS.values():
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://example.invalid")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "test-token")

    provider = search_executor.make_provider("auto", allow_llm_web_auto=True)

    assert provider.name == "llm_web"


def test_explicit_llm_web_provider_requires_diagnostic_opt_in(monkeypatch):
    for key in search_executor.PROVIDER_ENV_KEYS.values():
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://example.invalid")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "test-token")

    try:
        search_executor.make_provider("llm_web")
    except search_executor.NoSearchProviderConfigured as exc:
        message = str(exc)
        assert "diagnostics only" in message
        assert "fast search provider" in message
    else:
        raise AssertionError("explicit llm_web base provider must be diagnostic-only")

    provider = search_executor.make_provider("llm_web", allow_llm_web_auto=True)
    assert provider.name == "llm_web"


def test_execute_search_plan_records_failed_query_without_marking_executed():
    class BrokenProvider:
        name = "broken"

        def search(self, query, *, limit):
            raise search_executor.SearchProviderError("timeout")

    search_log, ok = search_executor.execute_search_plan(
        [{"round": "r1", "queries": ["合成生物 最新新闻 今日"]}],
        BrokenProvider(),
        date="2026-06-30",
    )

    query_entry = search_log["rounds"][0]["queries"][0]
    assert not ok
    assert query_entry["executed"] is False
    assert query_entry["error"] == "timeout"


def test_execute_search_plan_uses_llm_provider_for_high_recall_rounds():
    class MainProvider:
        name = "serper"

        def search(self, query, *, limit):
            return [{"title": "Base result", "url": "https://example.com/base"}]

    class LLMProvider:
        name = "llm_web"

        def search(self, query, *, limit):
            return [{"title": "LLM result", "url": "https://example.com/llm"}]

    search_log, ok = search_executor.execute_search_plan(
        [
            {"round": "r1", "queries": ["base query"]},
            {"round": "llm_discovery", "queries": ["broad discovery"], "requires_llm_web": True},
            {"round": "llm_gap_audit", "queries": ["gap audit"], "requires_llm_web": True},
        ],
        MainProvider(),
        llm_provider=LLMProvider(),
        date="2026-07-01",
    )

    assert ok
    assert search_log["rounds"][0]["queries"][0]["provider"] == "serper"
    assert search_log["rounds"][1]["queries"][0]["provider"] == "llm_web"
    assert search_log["rounds"][1]["queries"][0]["web_search_tool_result"] is True
    assert search_log["rounds"][2]["queries"][0]["provider"] == "llm_web"


def test_llm_web_search_provider_extracts_server_tool_results():
    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps({
                "content": [
                    {
                        "type": "server_tool_use",
                        "name": "web_search",
                        "input": {"query": "synthetic biology news"},
                    },
                    {
                        "type": "web_search_tool_result",
                        "tool_use_id": "tool-1",
                        "content": [
                            {
                                "type": "web_search_result",
                                "title": "Synthetic biology news item",
                                "url": "https://example.com/synbio",
                            }
                        ],
                    },
                ]
            }).encode("utf-8")

    def fake_opener(request, timeout=90):
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        captured["timeout"] = timeout
        return FakeResponse()

    client = search_executor.LLMClient(
        base_url="https://example.invalid",
        auth_token="test-token",
        model="kimi-for-coding",
        opener=fake_opener,
        timeout=90,
    )
    provider = search_executor.LLMWebSearchProvider(client, timeout=90)

    results = provider.search("synthetic biology news", limit=5)

    assert captured["payload"]["tools"][0]["type"] == "web_search_20250305"
    assert captured["timeout"] == 90
    assert results == [{
        "title": "Synthetic biology news item",
        "url": "https://example.com/synbio",
        "snippet": "Synthetic biology news item",
        "source": "example.com",
        "date": "",
        "source_query": "synthetic biology news",
        "search_provider": "llm_web",
        "rank": 1,
    }]


def test_llm_web_search_provider_requires_tool_result():
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps({"content": [{"type": "text", "text": "invented answer"}]}).encode("utf-8")

    def fake_opener(request, timeout=90):
        return FakeResponse()

    client = search_executor.LLMClient(
        base_url="https://example.invalid",
        auth_token="test-token",
        opener=fake_opener,
        timeout=90,
    )
    provider = search_executor.LLMWebSearchProvider(client, timeout=90)

    try:
        provider.search("synthetic biology news", limit=5)
    except search_executor.SearchProviderError as exc:
        assert "web_search_tool_result" in str(exc)
    else:
        raise AssertionError("llm_web provider must fail when the model did not run web_search")


def test_llm_web_search_provider_retries_when_tool_not_called():
    calls = []

    class FakeResponse:
        def __init__(self, payload):
            self.payload = payload

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps(self.payload).encode("utf-8")

    def fake_opener(request, timeout=90):
        calls.append(json.loads(request.data.decode("utf-8")))
        if len(calls) == 1:
            return FakeResponse({"content": [{"type": "text", "text": "not searched"}]})
        return FakeResponse({
            "content": [
                {"type": "server_tool_use", "name": "web_search", "input": {"query": "synthetic biology news"}},
                {
                    "type": "web_search_tool_result",
                    "content": [{
                        "type": "web_search_result",
                        "title": "Retried search result",
                        "url": "https://example.com/retried",
                    }],
                },
            ]
        })

    client = search_executor.LLMClient(
        base_url="https://example.invalid",
        auth_token="test-token",
        opener=fake_opener,
        timeout=90,
    )
    provider = search_executor.LLMWebSearchProvider(client, timeout=90, retries=2)

    results = provider.search("synthetic biology news", limit=5)

    assert len(calls) == 2
    assert "MANDATORY" in calls[1]["messages"][0]["content"]
    assert results[0]["title"] == "Retried search result"
