# LLM Search Orchestration

## Problem

The daily report cannot rely on an ever-growing static keyword list. Static queries are useful as guardrails, but they cannot decide which companies, technologies, policy sources, or international signals matter on a given day. The pipeline therefore uses a hybrid agent design:

- deterministic code enforces invariants;
- the LLM plans semantic search coverage and reviews candidates;
- every LLM decision is saved as structured JSON for replay and audit.

## Architecture

```text
base required search
  -> LLM search strategy
  -> external search executor
  -> structured search_log
  -> search strategy execution gate
  -> build_raw_from_search_log
  -> deterministic gates
  -> LLM relevance gate
  -> final report validation/send gate
```

The repository does not own the actual web-search provider. Kimiwork, Daimon, or another executor runs the queries. The repository owns the contract:

1. `scripts/llm_search_strategy.py` generates `data/search_strategy_YYYY-MM-DD.json`.
2. The executor must record every dynamic query in `data/search_log_YYYY-MM-DD.json`.
3. `scripts/audit_search_log.py --search-strategy ...` and `report_pipeline.py --build-approved --search-strategy ...` block if a required dynamic query was skipped or failed.

## Deterministic vs LLM Responsibilities

Deterministic code must continue to own:

- raw/search log schema;
- required base query execution;
- dynamic query execution coverage;
- URL health and deleted-page checks;
- title/URL match checks;
- date freshness;
- history deduplication;
- HTML/MIME safety;
- approved URL consistency;
- same-day send protection.

The LLM owns semantic judgment:

- what to search today beyond the base rounds;
- which blind spots remain after base search;
- whether a candidate is actually synthetic biology or biomanufacturing;
- whether it is important enough to include;
- which section it belongs to.

The LLM never bypasses deterministic gates.

## Strategy JSON Contract

`scripts/llm_search_strategy.py` writes this shape:

```json
{
  "version": 1,
  "date": "2026-06-25",
  "generated_by": "llm_search_strategy",
  "provider": "llm",
  "model": "kimi-for-coding",
  "strategy_round_id": "llm_dynamic",
  "base_rounds": ["r1", "r5"],
  "coverage_dimensions": ["policy", "funding", "enterprise"],
  "blindspots": ["重点企业动态", "精密发酵融资"],
  "queries": [
    {
      "query": "蓝晶微生物 最新 生物制造",
      "reason": "重点企业近期进展未被基座搜索覆盖",
      "priority": "high",
      "target_section": "news",
      "expected_source_type": "company_or_media",
      "iteration": 1,
      "required": true
    }
  ]
}
```

Rules:

- `queries[].query` must be non-empty and unique after whitespace normalization.
- `priority` is `high`, `medium`, or `low`.
- `target_section` is one of `news`, `research`, `funding`, `policy`, or `events`.
- `required` defaults to `true`; required queries must appear as executed in `search_log`.
- The LLM should generate 8-12 dynamic queries by default.
- `config/llm_search_strategy.json` `coverage_queries` are hard floors, not suggestions. If the LLM returns a full query list but omits a floor query such as a government source or broad vertical-media query, normalization replaces discretionary LLM queries so every coverage floor remains in the final strategy. `max_queries` limits discretionary queries and may be exceeded only when the configured floor itself is larger than the cap.

## Daily Workflow

```powershell
python scripts\llm_search_strategy.py --date YYYY-MM-DD --output data\search_strategy_YYYY-MM-DD.json --mode llm

# Kimiwork executes base queries and every strategy query, then saves:
# data\search_log_YYYY-MM-DD.json

python scripts\audit_search_log.py data\search_log_YYYY-MM-DD.json --search-strategy data\search_strategy_YYYY-MM-DD.json

python scripts\report_pipeline.py --build-raw-from-search data\search_log_YYYY-MM-DD.json --date YYYY-MM-DD --output data\raw_YYYY-MM-DD.json

python scripts\report_pipeline.py --build-approved data\raw_YYYY-MM-DD.json --date YYYY-MM-DD --output data --search-log data\search_log_YYYY-MM-DD.json --search-strategy data\search_strategy_YYYY-MM-DD.json --llm-relevance-mode llm
```

Use `--mode llm` in production strategy generation. `--mode auto` can fall back to heuristic planning only when no provider is configured; if a provider is configured and fails, it fails closed.

Strategy generation needs a larger output budget than single-item relevance review because it returns blind spots plus many structured queries. `scripts/llm_search_strategy.py` defaults to `ANTHROPIC_SEARCH_STRATEGY_MAX_TOKENS=3600` and accepts an environment override. If production sees truncated JSON or unterminated arrays, increase this value rather than falling back to manual query editing.

## Why This Is Not Another Keyword List

`config/llm_search_strategy.json` is seed memory, not a checklist. It gives the LLM tracked entities, technology areas, and known source hints. The daily strategy file is the actual task list, and it is generated from current date, recent report history, and optional base search evidence.

This keeps broad recall while preserving auditability: if an important story is missed, the investigation asks whether the LLM strategy omitted the dimension, whether the executor skipped the query, or whether deterministic gates rejected it.
