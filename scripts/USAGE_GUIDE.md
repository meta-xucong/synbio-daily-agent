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
- 如果 item 自带 `type` 且与 `--type` 不一致，将作为 schema 错误拒绝
- 不合规 URL、缺字段、过期信息、重复信息写入 `rejected`
- `value_score` 为 0-10，`raw_score` 保留原始分

## 验证报告

```powershell
python scripts\report_pipeline.py --validate reports\2026-06-11.md --output data\validation_2026-06-11.json
```

`--validate` 会执行结构、基础时效性和 AI 防幻觉检查；AI 未收录实体/数字会导致验证失败。

如需同时验证邮件正文与 approved 数据：

```powershell
python scripts\report_pipeline.py --full-validate reports\2026-06-11.md --email reports\2026-06-11_email.html --approved data\approved_2026-06-11.json --output data\full_validation_2026-06-11.json
```

必须满足：

- 8 个固定板块全部保留
- 无信息板块写明：`经五轮检索，本周期暂无相关新信息收录。`
- AI 分析只引用正文已收录实体和数字
- 附录链接来自 approved 数据

## 邮件 Gate 与 Dry Run

## 安全渲染

从 approved JSON 生成 HTML/邮件正文时，可以使用安全渲染脚本做最小安全版本或测试夹具：

```powershell
python scripts\render_html.py --approved data\approved_2026-06-11.json --date 2026-06-11 --output reports\2026-06-11.html
python scripts\render_email.py --approved data\approved_2026-06-11.json --date 2026-06-11 --output reports\2026-06-11_email.html
```

渲染器会对外部文本执行 HTML escape，对 URL 执行 http/https allowlist，并给新窗口链接加 `rel="noopener noreferrer"`。`render_html.py` 是安全最小渲染器；正式 H5 视觉仍以 `templates/daily_report_template_v2.html` 为准。

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

`--dry-run` 不要求存在真实 `config/email_config.json`；真实发送仍必须配置邮箱。

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
