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

`--process` 支持完整 raw dict，也支持单类别 list。

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

处理规则：

- 必填字段：`title/source/date/summary/url`
- 缺少 `type` 时自动补为 `--type`
- 不合规 URL、缺字段、过期信息、重复信息写入 `rejected`
- `value_score` 为 0-10，`raw_score` 保留原始分

## 验证报告

```powershell
python scripts\report_pipeline.py --validate reports\2026-06-11.md --output data\validation_2026-06-11.json
```

必须满足：

- 8 个固定板块全部保留
- 无信息板块写明：`经五轮检索，本周期暂无相关新信息收录。`
- AI 分析只引用正文已收录实体和数字
- 附录链接来自 approved 数据

## 邮件 Gate 与 Dry Run

推荐发送前先 dry-run：

```powershell
python scripts\send_email.py 2026-06-11 reports\2026-06-11.md reports\2026-06-11.html reports\2026-06-11_email.html --dry-run
```

`send_email.py` 会强制执行：

1. `pre_check(date)`
2. 读取 `data/approved_YYYY-MM-DD.json`
3. `run_full_validation(report_md, email_body, approved_data)`
4. `validate_ai_analysis(report_md)`
5. `post_check(date)`
6. 构造 MIME 后执行 `validate_email_mime_type(msg)`

任一 gate 失败，脚本返回非 0，且不会连接 SMTP。

## 本地测试

```powershell
python -m pytest -q
python -m compileall scripts
rg -n -F 'D:\AI\合成生物行业报告' .
```

最后一条不应出现运行逻辑中的硬编码路径。

## 文件命名规范

- 原始数据：`data/raw_YYYY-MM-DD.json`
- 处理结果：`data/processed_{category}_YYYY-MM-DD.json`
- approved：`data/approved_YYYY-MM-DD.json`
- rejected：`data/rejected_YYYY-MM-DD.json`
- Markdown：`reports/YYYY-MM-DD.md`
- H5：`reports/YYYY-MM-DD.html`
- 邮件 HTML：`reports/YYYY-MM-DD_email.html`
