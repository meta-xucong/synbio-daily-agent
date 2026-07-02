# synbio-daily-agent - Kimiwork 执行指令

**指令版本**：2026-07-01  
**适用对象**：Kimiwork 自动化执行日报流水线  
**工作目录**：`D:\AI\合成生物行业报告\github-repo\synbio-daily-agent`

---

## 硬性规则

你现在只负责执行 synbio-daily-agent 的既定日报流水线，**不要自行判断、不要手写 search_log/raw/approved/report，不要跳过任何 gate**。

1. **只能通过仓库 scripts 生成** search_strategy、search_log、raw、approved、report、html、email。
2. **严禁手工创建或修改** `data/search_log_YYYY-MM-DD.json`。
3. **严禁把未执行 query 标成** `executed=true`。
4. **严禁使用以下绕过参数**：
   - `--allow-missing-strategy`
   - `--allow-query-failures`
   - `--skip-url-health`
   - `--skip-title-match`
   - `--skip-page-date-check`
   - `--llm-relevance-mode off`
   - `--allow-llm-web-base`
   - `--force-send`
5. **任何一步返回非 0，立即停止并报告错误，不要继续**。
6. **approved=0 时立即停止，不要发送邮件**。
7. **audit_search_log、pre_check、full_validate、send_email --dry-run 全部通过后，才允许真实发送**。
8. **不要调用你自己的总结能力来补新闻**；所有新闻必须来自 search_executor 生成的 search_log，再由 report_pipeline 处理。
9. **发送后必须再运行审计**，确认 send_log 写入且无遗漏/错误。
10. **必须配置一个 fast search provider**：`SERPER_API_KEY`、`BRAVE_SEARCH_API_KEY`、`BING_SEARCH_API_KEY` 或 `TAVILY_API_KEY` 至少一个。Kimi/`llm_web` 只负责 LLM 策略、相关性判断、`llm_discovery` 和 `llm_gap_audit`，不能代替 r1-r6 基础搜索。

---

## PowerShell 执行脚本（唯一入口）

正式自动发送只允许调用统一入口，不要拆开执行单步命令：

```powershell
Set-Location "D:\AI\合成生物行业报告\github-repo\synbio-daily-agent"
$DATE = (Get-Date -Format "yyyy-MM-dd")

python scripts\run_daily_pipeline.py --date $DATE --provider auto --send --send-mode auto
if ($LASTEXITCODE -ne 0) { throw "Daily pipeline failed" }
```

只做 dry-run 验证时去掉 `--send`：

```powershell
python scripts\run_daily_pipeline.py --date $DATE --provider auto --send-mode auto
if ($LASTEXITCODE -ne 0) { throw "Daily pipeline dry-run failed" }
```

下面的分步命令仅供人工排障时对照，**正式日报不要逐条手工执行**。

```powershell
Set-Location "D:\AI\合成生物行业报告\github-repo\synbio-daily-agent"
$DATE = (Get-Date -Format "yyyy-MM-dd")

# 1. LLM 健康检查
python scripts\llm_health_check.py --date $DATE --json
if ($LASTEXITCODE -ne 0) { throw "LLM health check failed" }

# 1a. 搜索 provider 预检查：正式日报必须有 fast provider
if (-not ($env:SERPER_API_KEY -or $env:BRAVE_SEARCH_API_KEY -or $env:BING_SEARCH_API_KEY -or $env:TAVILY_API_KEY)) {
  throw "Missing fast search provider: set SERPER_API_KEY, BRAVE_SEARCH_API_KEY, BING_SEARCH_API_KEY, or TAVILY_API_KEY"
}

# 2. LLM 生成搜索策略
python scripts\llm_search_strategy.py --date $DATE --output "data\search_strategy_$DATE.json" --mode llm
if ($LASTEXITCODE -ne 0) { throw "LLM search strategy failed" }

# 3. 执行搜索（正式路径必须保留高召回轮次，不得使用 --disable-high-recall）
python scripts\search_executor.py --date $DATE --strategy "data\search_strategy_$DATE.json" --output "data\search_log_$DATE.json" --provider auto --limit 15 --timeout 30 --retries 2 --max-workers 5
if ($LASTEXITCODE -ne 0) { throw "Search executor failed" }

# 4. 从搜索日志构建 raw
python scripts\report_pipeline.py --build-raw-from-search "data\search_log_$DATE.json" --date $DATE --output "data\raw_$DATE.json"
if ($LASTEXITCODE -ne 0) { throw "Build raw failed" }

# 5. 审计搜索日志
python scripts\audit_search_log.py "data\search_log_$DATE.json" --raw "data\raw_$DATE.json" --search-strategy "data\search_strategy_$DATE.json"
if ($LASTEXITCODE -ne 0) { throw "Search audit failed" }

# 6. 构建 approved（含 LLM relevance gate）
python scripts\report_pipeline.py --build-approved "data\raw_$DATE.json" --date $DATE --output data --search-log "data\search_log_$DATE.json" --search-strategy "data\search_strategy_$DATE.json"
if ($LASTEXITCODE -ne 0) { throw "Build approved failed" }

# 6a. 检查 approved 数量
$approved = Get-Content "data\approved_$DATE.json" | ConvertFrom-Json
if ($approved.Count -eq 0) { throw "approved=0, 停止发送" }

# 7. Pre-check
python scripts\pre_check.py $DATE
if ($LASTEXITCODE -ne 0) { throw "Pre-check failed" }

# 8. 渲染 Markdown 报告
python scripts\report_pipeline.py --render-md "data\approved_$DATE.json" --date $DATE --raw "data\raw_$DATE.json" --output "reports\$DATE\report.md"
if ($LASTEXITCODE -ne 0) { throw "Render markdown failed" }

# 9. 生成 HTML 邮件
python scripts\generate_from_template.py --date $DATE --approved "data\approved_$DATE.json" --markdown "reports\$DATE\report.md" --html-output "reports\$DATE\h5.html" --email-output "reports\$DATE\email.html"
if ($LASTEXITCODE -ne 0) { throw "Generate HTML/email failed" }

# 10. 完整验证
python scripts\report_pipeline.py --full-validate "reports\$DATE\report.md" --email "reports\$DATE\email.html" --approved "data\approved_$DATE.json" --output "data\full_validation_$DATE.json"
if ($LASTEXITCODE -ne 0) { throw "Full validation failed" }

# 11. Dry-run 发送门禁
python scripts\send_email.py $DATE "reports\$DATE\report.md" "reports\$DATE\h5.html" "reports\$DATE\email.html" --dry-run --send-mode auto
if ($LASTEXITCODE -ne 0) { throw "Send dry-run failed" }

# 12. 真实发送
python scripts\send_email.py $DATE "reports\$DATE\report.md" "reports\$DATE\h5.html" "reports\$DATE\email.html" --send-mode auto
if ($LASTEXITCODE -ne 0) { throw "Real send failed" }

# 13. 发送后审计
python scripts\audit_search_log.py "data\search_log_$DATE.json" --raw "data\raw_$DATE.json" --search-strategy "data\search_strategy_$DATE.json"
python scripts\pre_check.py $DATE
```

---

## 最后报告格式

执行完成后，必须报告以下信息：

| 检查项 | 状态 |
|--------|------|
| LLM health | ok / failed |
| search_strategy | provider, model, query_count |
| search_executor | provider, 执行 query 数 |
| audit_search_log | valid / invalid |
| approved 数量 | N 条，标题列表 |
| send_log | 是否写入今天日期 |
| 真实发送 | 成功 / 失败 |

---

## 关键说明

- **LLM 使用点**：`llm_health_check` → `llm_search_strategy --mode llm` → `build-approved` 的 LLM relevance gate
- **搜索 provider 分层**：`--provider auto` 只会为 r1-r6 基础搜索选择 Serper/Brave/Bing/Tavily 这类 fast provider；没有 fast provider 会 fail-closed。当前默认高召回证据模式为 `compatible`，`llm_discovery` / `llm_gap_audit` 默认复用基础 provider（`same`）并保留结构化结果证据；只有 `strict` 模式才要求 Kimi `llm_web`。`--allow-llm-web-base` 只允许人工诊断使用，正式日报严禁使用。
- **只要严格按脚本链路跑，LLM 会被强制使用，搜索日志会被审计，空日报/假搜索/漏 LLM 都会被挡住**

## 常见失败处理

- 如果 `search_executor` 报 `no configured fast search provider` 或 `llm_web cannot be used for base required queries in production`，**停止并报告缺少 fast search provider**，不要改成 `--provider llm_web`，不要加 `--allow-llm-web-base`，不要手工补 `search_log`。
- 如果 `llm_health_check` 失败，**停止并报告 LLM 不可用**，不要改用 heuristic/off，也不要绕过 search_strategy。
