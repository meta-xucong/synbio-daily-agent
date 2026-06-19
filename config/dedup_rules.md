# 时效性与去重规则

## 时效性规则

| 信息类型 | 最大时间窗口 | 说明 |
|---------|-----------|------|
| 行业热点新闻 | 7天 | 超过7天的新闻视为过期 |
| 最新研究成果 | 14天 | 超过14天的研究视为过期 |
| 融资与投资动态 | 7天 | 超过7天的融资视为过期 |
| 政策与监管 | 30天 | 超过30天的政策视为过期 |
| 行业活动预告 | 90天 | 超过90天的活动视为过期 |

## 去重规则

### 标题相似度阈值
- 标题相似度 ≥ 80% 视为重复
- 使用 difflib.SequenceMatcher 计算相似度

### 去重检查范围
- 检查过去 30 天内已收录的信息
- 检查当前批次内部重复
- 真实发送成功后写入 `data/history_index.json`
- 后续处理会用 `history_index.json` 中的标题、内容指纹、主链接和 `urls` 备用链接做跨天持久化去重
- URL 去重会忽略常见追踪参数，如 `utm_*`、`fbclid`、`gclid`、`ref`

### 特殊处理
- 同一事件的不同报道（如融资新闻的不同来源）保留价值评分最高的一条
- 同一研究的预印本和正式发表视为重复，保留正式发表版本
- 同一 canonical URL 如果对应不同标题，默认视为数据冲突，只保留排序更高的一条，其余进入 `rejected`

## 链接健康规则

正式生成 approved 时建议使用：

```powershell
python scripts\report_pipeline.py --build-raw-from-search data\search_log_YYYY-MM-DD.json --date YYYY-MM-DD --output data\raw_YYYY-MM-DD.json
python scripts\audit_search_log.py data\search_log_YYYY-MM-DD.json --raw data\raw_YYYY-MM-DD.json
python scripts\report_pipeline.py --build-approved data\raw_YYYY-MM-DD.json --date YYYY-MM-DD --output data --search-log data\search_log_YYYY-MM-DD.json
```

`search_log_YYYY-MM-DD.json` 必须覆盖 `config/search_queries.json` 中 `r1` 到 `r5` 的全部 required query，并保留结构化候选结果；raw 中每条候选必须带 `source_round`，用于审计候选来源并防止遗漏轮次、补录旧信息或人工挑选阶段漏收。build-approved 和发送 gate 默认严格校验必搜 query；仅排障可用 `--relaxed-search-coverage` 降级为警告。

发送 gate 默认也会检查 H5、邮件正文和 Markdown 附件中的实际外链。以下情况会阻断发送或进入 rejected：

- HTTP 4xx/5xx
- 超时、DNS、TLS/证书等无法打开
- 页面文本包含“文章已删除”“账号已注销”“页面不存在”等软失效提示
- 站点首页、分类页、搜索页、聚合页或黑名单域名
- URL 可访问但页面标题信号与候选标题明显不符（默认开启标题匹配，网络读取失败只记录 warning）

## 价值评分标准

代码当前保留两个分数字段：

- `raw_score`: 原始累加分，用于审计评分来源。
- `value_score`: 归一化后的 0-10 分，用于排序和展示。

`raw_score` 由以下维度累加：

| 评分维度 | 实现说明 |
|---------|----------|
| 来源权威性 | Nature/Science/Cell 等 tier1 来源加权最高，行业媒体次之 |
| 信息完整性 | 摘要中包含金额、日期等具体信息时加分 |
| 时效性 | 1天内、3天内、7天内分别加权 |
| 行业影响力 | 标题命中融资、并购、获批、突破、政策、FDA、GRAS 等关键词时加分 |

`value_score = min(10.0, round(raw_score / 30 * 10, 1))`。

## 输出格式

所有 approved 信息必须包含以下字段：
- `title`: 标题
- `source`: 来源
- `date`: 日期 (YYYY-MM-DD)
- `summary`: 摘要
- `url`: 原始链接
- `type`: 类型 (news/research/funding/policy/events)
- `raw_score`: 原始价值评分
- `value_score`: 价值评分 (0-10)
