# LLM 中枢审计门禁设计

## 背景

扩大搜索关键词后，候选池会更完整，但也更容易混入普通生物医药、基础生物学、化学合成、材料、临床等不属于合成生物领域的信息。继续靠关键词、白名单、黑名单和路径例外叠规则，会导致规则越来越厚，但仍无法覆盖真实语义边界。

本设计将“是否属于合成生物领域”的判断从关键词规则升级为可选 LLM 中枢审计门禁。LLM 用作审稿人，不用作唯一事实来源。

## 架构原则

1. 搜索层可以更宽，宁可多抓候选，不在 query 层过早丢失。
2. 确定性门禁继续保留：URL 安全、聚合页、时效性、去重、标题-URL 匹配、链接健康、approved schema、send gate。
3. LLM 只负责语义审稿：判断候选是否属于合成生物/生物制造核心领域，给出证据和置信度。
4. LLM 输出必须是 JSON；无法解析、无证据、低置信度或判断为 `out_of_scope` 时不得进入 approved。
5. 没有 LLM 配置时，系统必须继续可运行，使用本地语义启发式 fallback。
6. API key 只能从环境变量读取，不写入仓库、测试、文档或日志。

## Provider 配置

支持 Anthropic-compatible Messages API，读取环境变量：

- `ANTHROPIC_BASE_URL`
- `ANTHROPIC_AUTH_TOKEN`
- `ANTHROPIC_MODEL`，默认 `claude-3-5-sonnet-20241022`

生产配置示例只写变量名，不记录真实 token。

## LLM 输出 Schema

```json
{
  "decision": "include|reject|escalate",
  "domain_relevance": "core_synbio|adjacent|out_of_scope|uncertain",
  "confidence": 0.0,
  "reason": "短理由",
  "evidence_spans": ["来自标题/摘要/正文的证据片段"],
  "section": "news|research|funding|policy|events",
  "reject_reason": null
}
```

## 收录规则

- `include` 且 `domain_relevance` 为 `core_synbio` 或 `adjacent`，且 `confidence >= 0.70`，且 `evidence_spans` 非空：通过。
- `reject` 或 `domain_relevance=out_of_scope`：拒绝。
- `escalate`、`uncertain`、`confidence < 0.70`、缺少证据：拒绝并写入 rejected，原因标记为 `[LLM领域审计]`。
- LLM API 错误时默认使用本地 fallback；不会因为 provider 临时不可用中断日报。

## 集成位置

`build_approved_from_raw` 流程中，先运行现有 category 内处理、批次冲突去重、链接健康、标题匹配，再运行 LLM 领域审计。

原因：

- 前置确定性门禁先剔除明显坏数据，减少 LLM 调用量。
- LLM 看到的是已经具备基本安全性和时效性的候选，更适合做语义判断。
- LLM rejection 会进入 `rejected_YYYY-MM-DD.json`，便于审计。

## 安全边界

- 不把 token 写进 `config`、`.env`、测试 fixture 或文档。
- 测试使用 fake client，不访问外部网络。
- 日志只输出审计数量和 rejected reason，不输出 token。
- LLM 判断不覆盖 URL、日期、去重和 approved URL 一致性门禁。

## 后续增强

- 页面正文抓取：当前第一阶段只使用 title/source/summary/url/type 和已有 page_text 字段。
- 双模型 critic：第二阶段可增加“反向审稿人”专门找普通医药/基础研究误收。
- 人工复核队列：低置信度 `escalate` 可写入单独 `review_YYYY-MM-DD.json`。
