# AS hub NEWs agent - 脚本使用指南

本指南供本地运行、Cron 子 Agent 和 CI 验证使用。当前验证状态以 `python -m pytest -q` 和脚本实际返回码为准。

## 路径与环境

默认项目根目录为仓库根目录，也可以用环境变量覆盖：

```powershell
$env:SYNBIO_DAILY_HOME = "D:\path\to\synbio-daily-agent"
$env:SYNBIO_DAILY_TZ = "Asia/Shanghai"
```

脚本均使用相对路径或 `SYNBIO_DAILY_HOME`，不依赖固定本机目录。

## 处理原始数据

生产运行应先从结构化搜索日志自动生成 raw，避免人工挑选遗漏搜索结果；然后从完整 raw dict 生成 processed/approved/rejected，并在写出 approved 前剔除打不开或疑似删除的链接：

```powershell
python scripts\report_pipeline.py --build-raw-from-search data\search_log_2026-06-11.json --date 2026-06-11 --output data\raw_2026-06-11.json
python scripts\report_pipeline.py --build-approved data\raw_2026-06-11.json --date 2026-06-11 --output data --strict-search-coverage --search-log data\search_log_2026-06-11.json
```

该命令会写出：

- `data/processed_news_YYYY-MM-DD.json`
- `data/processed_research_YYYY-MM-DD.json`
- `data/processed_funding_YYYY-MM-DD.json`
- `data/processed_policy_YYYY-MM-DD.json`
- `data/processed_events_YYYY-MM-DD.json`
- `data/approved_YYYY-MM-DD.json`
- `data/rejected_YYYY-MM-DD.json`

生产数据还必须包含 `data/search_log_YYYY-MM-DD.json`，记录 `r1` 到 `r5` 五轮检索的 query 和候选证据。建议 search_log 中保留结构化搜索结果（`title/url/snippet/source/date`），并用 `--build-raw-from-search` 自动写入 raw。raw 中每条候选必须带 `source_round`，否则 `--search-log` 和发送前 `pre_check` 都会阻断。

`--process` 仍支持完整 raw dict 或单类别 list，但主要用于调试单个类别：

```powershell
python scripts\report_pipeline.py --process data\raw_2026-06-11.json --type news --output data\processed_news_2026-06-11.json
```

完整 raw dict 结构：

```json
{
  "news": [{"title": "...", "source": "...", "date": "2026-06-11", "summary": "...", "url": "https://example.com/a"}],
  "research": [],
  "funding": [],
  "policy": [],
  "events": []
}
```

推荐 raw item 至少包含：

```json
{"title": "...", "source": "...", "date": "2026-06-11", "summary": "...", "url": "https://example.com/a", "type": "news", "source_round": "r1"}
```

处理规则：

- 必填字段：`title/source/date/summary/url`
- 缺少 `type` 时自动补为 `--type`
- 如果 item 自带 `type` 且与 `--type` 不一致，将作为 schema 错误拒绝
- 不合规 URL、缺字段、过期信息、重复信息、历史索引命中、同URL不同标题冲突、死链写入 `rejected`
- `data/history_index.json` 会在真实发送成功后更新；后续处理会用主链接和 `urls` 备用链接一起做跨天持久化去重
- `value_score` 为 0-10，`raw_score` 保留原始分
- approved schema 必须包含 `title/source/date/summary/url/type/raw_score/value_score`，日期、类别、URL和分数范围都会在发送前再次校验
- 链接健康和标题-URL匹配在 `--build-approved` 默认开启；仅离线测试或临时排障可用 `--skip-url-health` / `--skip-title-match` 显式关闭
- `--strict-search-coverage` 会要求 search_log 中的候选 URL 全部进入 raw；如果需要人工丢弃某条结果，应先让它进入 raw，再由 rejected 记录拒绝原因

## 生成 Markdown 报告

推荐从 approved 确定性生成 Markdown，避免旧报告或人工链接混入：

```powershell
python scripts\report_pipeline.py --render-md data\approved_2026-06-11.json --date 2026-06-11 --raw data\raw_2026-06-11.json --output reports\2026-06-11.md
```

## 验证报告

```powershell
python scripts\report_pipeline.py --validate reports\2026-06-11.md --output data\validation_2026-06-11.json
```

`--validate` 会执行结构、基础时效性和 AI 防幻觉检查；AI 未收录实体/数字会导致验证失败。

如需同时验证邮件正文与 approved 数据：

```powershell
python scripts\report_pipeline.py --full-validate reports\2026-06-11.md --email reports\email_2026-06-11.html --approved data\approved_2026-06-11.json --output data\full_validation_2026-06-11.json
```

必须满足：

- 8 个固定板块全部保留
- 无信息板块写明：`经五轮检索，本周期暂无相关新信息收录。`
- AI 分析只引用正文已收录实体和数字
- 附录链接来自 approved 数据

## 邮件 Gate 与 Dry Run

## 生产 H5 与邮件正文

正式日报必须使用定稿模板渲染入口：

```powershell
python scripts\generate_from_template.py --date 2026-06-11 --approved data\approved_2026-06-11.json --markdown reports\2026-06-11.md --html-output reports\synbio_daily_2026-06-11.html --email-output reports\email_2026-06-11.html
```

`generate_from_template.py` 会读取 `templates/daily_report_template_v2.html`，保留定稿 CSS/类名，并在输出前执行 HTML safety 与 approved URL 一致性检查。

`render_html.py` / `render_email.py` 仅用于 emergency fallback 或测试夹具，不得作为正式日报输出。

推荐发送前先 dry-run：

```powershell
python scripts\send_email.py 2026-06-11 reports\2026-06-11.md reports\synbio_daily_2026-06-11.html reports\email_2026-06-11.html --dry-run
```

`send_email.py` 会强制执行：

1. `pre_check(date)`
2. 读取 `data/approved_YYYY-MM-DD.json`
3. `run_full_validation(report_md, email_body, approved_data)`
4. `validate_ai_analysis(report_md)`
5. `post_check(date)`
6. 构造 MIME 后执行 `validate_email_mime_type(msg)`

任一 gate 失败，脚本返回非 0，且不会连接 SMTP。

`pre_check(date)` 会要求 `raw_YYYY-MM-DD.json`、`approved_YYYY-MM-DD.json` 和 `search_log_YYYY-MM-DD.json` 同时存在，并校验搜索日志覆盖 `r1` 到 `r5`、每条 raw 候选都能通过 `source_round` 追溯到对应搜索轮次。

`--dry-run` 不要求存在真实 `config/email_config.json`；真实发送仍必须配置邮箱。

`allow_simple_fallback=false` 为默认推荐。只有在 SMTP 服务商持续拒绝 multipart 附件邮件，并且可接受“仅 HTML 正文、无附件”的降级发送时，才应在 `config/email_config.json` 中显式设为 `true`。
`check_url_health=true` 为默认推荐。发送 gate 会在连接 SMTP 前检查 H5、邮件正文和 Markdown 附件里的实际外链是否可打开，并拦截 4xx/5xx、超时以及“文章已删除/账号已注销/页面不存在”等软失效页面。缺少真实邮箱配置时的 `--dry-run` 也默认执行链接健康检查；测试中需要跳过网络时应显式 mock 或在配置中临时设为 `false`。
`url_health_mode=strict` 为默认推荐。受限网络或代理环境反复出现 SSL/证书握手误报时，可临时设为 `soft`；soft 模式只把 SSL/证书类网络错误降级为 warning，HTTP 404 和页面删除仍会阻断。

真实发送同一日期日报默认只能成功一次。人工补发必须显式使用：

```powershell
python scripts\send_email.py 2026-06-11 reports\2026-06-11.md reports\synbio_daily_2026-06-11.html reports\email_2026-06-11.html --force-send --send-mode manual
```

`--force-send` 只绕过“同日期已发送”检查，不跳过 pre_check、AI grounding、approved URL、链接健康、MIME 等门禁；发送尝试会写入 `data/send_log.json`。

## 本地测试

```powershell
python -m pytest -q
python -m compileall scripts
rg -n -F 'D:\AI\合成生物行业报告' .
```

最后一条不应出现运行逻辑中的硬编码路径。

## 文件命名规范

- 原始数据：`data/raw_YYYY-MM-DD.json`
- 搜索日志：`data/search_log_YYYY-MM-DD.json`
- 处理结果：`data/processed_{category}_YYYY-MM-DD.json`
- approved：`data/approved_YYYY-MM-DD.json`
- rejected：`data/rejected_YYYY-MM-DD.json`
- Markdown：`reports/YYYY-MM-DD.md`
- H5：`reports/synbio_daily_YYYY-MM-DD.html`
- 邮件 HTML：`reports/email_YYYY-MM-DD.html`
