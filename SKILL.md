---
name: synbio-daily-report
description: |
  合成生物行业日报生成工作流 - AS hub 项目专用。
  涵盖信息搜索、脚本过滤去重、报告生成（Markdown+H5+邮件）、合规复检、邮件推送的完整流程。
  触发条件：用户要求生成合成生物行业日报、或cron定时任务触发。
  核心原则：我们不是新闻的搬运工。信息按价值排序，综合分析政策/科研/行业，提供趋势预测。
---

# 合成生物行业日报生成工作流

## 项目背景

- **项目名称**：AS hub = AI Synbio hub
- **发起方**：甬江盛合
- **定位**：用AI服务合成生物，专注于资讯、助手、营销
- **Slogan**：AS Now as Future
- **核心原则**：我们不是新闻的搬运工。不做单纯的信息搬运和拼接，而是将信息按价值排序，综合分析政策、科研、行业，提供趋势预测。

## 工作流总览

```
Step 1: 读取配置（数据源 + 去重规则 + 脚本指南）
Step 2: 多维度搜索（重点网站优先，五轮搜索法）
Step 3: 脚本强制过滤与去重（严禁跳过）
Step 4: 生成Markdown报告
Step 5: 生成H5 HTML报告（必须使用 generate_from_template.py 和定稿模板）
Step 6: 合规复检（迭代修正，最多3次）
Step 7: 生成邮件正文（必须使用 generate_from_template.py，与H5严格一致）
Step 8: 邮件推送（send gate通过后才发送）
Step 9: 更新政策库
```

---

## Step 1: 读取配置

### 1.1 数据源配置
读取 `config/data_sources.json`

**重点网站（必须优先搜索）**：

**国外媒体（英文）**：
- SynBioBeta (synbiobeta.com)
- GEN / Genetic Engineering & Biotechnology News (genengnews.com)
- Labiotech (labiotech.eu)
- CRISPR Medicine News (crisprmedicinenews.com)
- FierceBiotech (fiercebiotech.com)
- iGEM (competition.igem.org)

**国内媒体（中文）**：
- 深波synbio（微信公众号）
- 合成生物学网 (synbio-he.com)
- 动脉网 (vbdata.cn)
- 医药魔方 (bydrug.pharmcube.com)
- 生物谷 (bioon.com)
- 投资界 (pedaily.cn)
- 36氪 (36kr.com)

### 1.2 去重规则
读取 `config/dedup_rules.md`

### 1.3 脚本使用指南
读取 `scripts/USAGE_GUIDE.md`

---

## Step 2: 多维度搜索（五轮搜索法，配置强制）

`config/search_queries.json` 是每日必搜 query 的唯一权威清单。不要从记忆或文档正文里自行删减 query；每次运行必须先读取该配置，逐轮执行 `rounds[].required_queries` 中的每一条查询。

**执行要求**：
- 每个 query 的 limit 设为 15-20。
- 每条 required query 都必须写入 `data/search_log_YYYY-MM-DD.json` 的 `queries`。
- 查询成功但无结果时，记录 `executed: true, results_count: 0`，这不视为漏搜。
- 查询因网络、超时或工具错误失败时，记录 `executed: false, error: "..."`，不得跳过不记；严格门禁会阻断，必须重试或人工确认后再继续。
- 必须保留结构化搜索结果（title/url/snippet/source/date），不得只保留人工挑选后的少数 URL。
- 政府网站、会议网站、英文专业媒体和中文垂直媒体的 `site:` 查询严禁省略。

推荐的 `search_log` 查询记录格式：

```json
{
  "round": "r5",
  "queries": [
    {
      "query": "site:kw.beijing.gov.cn 合成生物",
      "executed": true,
      "results_count": 0,
      "results": []
    }
  ],
  "candidates": []
}
```

保存 `search_log` 后可先独立审计：

```powershell
python scripts\audit_search_log.py data\search_log_YYYY-MM-DD.json
```

---

## Step 3: 脚本强制过滤与去重（严禁跳过）

### 3.1 保存原始数据
将搜索到的所有结构化结果先保存到 `search_log_YYYY-MM-DD.json`，再用脚本自动生成 raw，严禁人工挑选后只写入少数结果：

```powershell
python scripts\report_pipeline.py --build-raw-from-search data\search_log_YYYY-MM-DD.json --date YYYY-MM-DD --output data\raw_YYYY-MM-DD.json
```

raw 文件结构如下：

```python
import json
from settings import date_str

date_str = date_str()
raw_data = {
    "news": [{"title": "...", "source": "...", "date": "2026-06-08", "summary": "...", "url": "https://具体文章链接", "type": "news", "source_round": "r1"}],
    "research": [{"title": "...", "source": "...", "date": "2026-06-08", "summary": "...", "url": "https://具体文章链接", "type": "research", "source_round": "r3"}],
    "funding": [{"title": "...", "source": "...", "date": "2026-06-08", "summary": "...", "url": "https://具体文章链接", "type": "funding", "source_round": "r2", "company": "...", "round": "...", "amount": "...", "investor": "..."}],
    "policy": [{"title": "...", "source": "...", "date": "2026-06-08", "summary": "...", "url": "https://具体文章链接", "type": "policy", "source_round": "r5"}],
    "events": [{"title": "...", "source": "...", "date": "2026-06-08", "summary": "...", "url": "https://具体文章链接", "type": "events", "source_round": "r4", "location": "..."}],
}

raw_path = rf"data/raw_{date_str}.json"
with open(raw_path, 'w', encoding='utf-8') as f:
    json.dump(raw_data, f, ensure_ascii=False, indent=2)

search_log = {
    "date": date_str,
    "rounds": [
        {"round": "r1", "queries": ["合成生物 最新新闻 今日"], "candidates": []},
        {"round": "r2", "queries": ["site:36kr.com 合成生物 融资"], "candidates": []},
        {"round": "r3", "queries": ["synthetic biology breakthrough 2026"], "candidates": []},
        {"round": "r4", "queries": ["合成生物 今日 最新"], "candidates": []},
        {"round": "r5", "queries": ["site:gov.cn 合成生物 政策"], "candidates": []},
    ],
}
with open(rf"data/search_log_{date_str}.json", 'w', encoding='utf-8') as f:
    json.dump(search_log, f, ensure_ascii=False, indent=2)
```

**重要**：url字段必须是**具体文章的原始链接**，不能是网站首页或分类页面；每条 raw 候选必须带 `source_round`，并且 `data/search_log_YYYY-MM-DD.json` 必须覆盖 r1-r5 五轮检索。

### 3.2 调用脚本处理（强制步骤）

生产运行必须使用一次性 CLI 入口处理完整 raw dict，不得手工拼接 approved：

```powershell
python scripts\report_pipeline.py --build-approved data\raw_YYYY-MM-DD.json --date YYYY-MM-DD --output data --search-log data\search_log_YYYY-MM-DD.json
```

该命令会同时生成：

- `data/processed_news_YYYY-MM-DD.json`
- `data/processed_research_YYYY-MM-DD.json`
- `data/processed_funding_YYYY-MM-DD.json`
- `data/processed_policy_YYYY-MM-DD.json`
- `data/processed_events_YYYY-MM-DD.json`
- `data/approved_YYYY-MM-DD.json`
- `data/rejected_YYYY-MM-DD.json`

`--build-approved` 会统一执行 schema、必搜 query 覆盖审计、候选 URL 覆盖审计、URL聚合页过滤、跨天历史去重、当前批次去重、同URL不同标题冲突剔除、时效性、链接健康、标题-URL匹配、LLM领域审计、价值评分和 approved schema 校验。搜索覆盖不可绕过，会阻断“必搜 query 未执行”或“搜索结果存在但未进入 raw”的静默漏收。链接健康和标题-URL匹配默认开启，会在 approved 写出前剔除打不开、HTTP 4xx/5xx、超时、证书失败、疑似删除页或标题明显张冠李戴的信息；LLM领域审计默认 `--llm-relevance-mode auto`，配置 `ANTHROPIC_BASE_URL` 与 `ANTHROPIC_AUTH_TOKEN` 后调用 Anthropic-compatible provider 判断是否属于合成生物/生物制造领域，未配置时使用本地 fallback 仅拦截明显跑题项。仅离线测试或临时排障可用 `--skip-url-health` / `--skip-title-match` / `--llm-relevance-mode heuristic|off` 显式降级。

**重要**：
- **必须使用脚本处理后的 `approved` 列表中的信息**
- **严禁使用 `rejected` 列表中的信息**
- **必须保留 `data/history_index.json`，真实发送成功后会写入，后续跨天去重会检查主链接和 `urls` 备用链接**
- **必须保留 `data/search_log_YYYY-MM-DD.json`，发送前会检查五轮 query 和 raw 的 `source_round`**
- **严禁把 LLM provider token 写入仓库、配置文件、测试 fixture、报告或日志；只能由运行环境变量提供**
- 如果所有信息都被拒绝，生成"本周期暂无相关新信息"的报告

---

## Step 4: 生成Markdown报告

### 4.1 读取模板
读取 `templates/daily_report_template.md`

### 4.2 报告结构（固定板块，空板块保留占位）

**板块规则**：
- 如果某板块有approved信息，**必须体现**该板块
- 如果某板块无approved信息，**必须保留板块标题**，并标注"经五轮检索，本周期暂无相关新信息收录。"
- 执行摘要和AI深度分析**必须保留**（执行摘要按AI评分从高到低取前5条，再按日期降序排列）

**日期排序规则（强制要求）**：
- **执行摘要**：按AI评分从高到低取前5条，再按日期降序排列（最新→最旧），每条末尾标注 `（YYYY-MM-DD）`
- **行业热点新闻**：表格行按日期降序排列（最新→最旧）
- **最新研究成果**：表格行按日期降序排列（最新→最旧）
- **融资与投资动态**：表格行按日期降序排列（最新→最旧）
- **政策与监管**：国内政策表格按日期降序排列；国际动态列表按日期降序排列
- **行业活动预告**：表格行按日期降序排列（最新→最旧，未来日期在前）
- **附录链接列表**：按对应信息的日期降序排列

**执行摘要格式（强制要求）**：
```
1. **标题**：摘要内容...（YYYY-MM-DD） — *按AI评分从高到低取前5条*
2. **标题**：摘要内容...（YYYY-MM-DD）
```
- 每条末尾必须标注日期 `（YYYY-MM-DD）`
- 按日期降序排列，最新的信息排在第1条
- 精选5-8条最有价值的信息（优先选日期最近、价值分数最高的）

标准板块：
1. 📌 执行摘要（以AI评分从高到低取前5条，必须保留，按日期降序排列，每条带日期标注）
2. 📰 行业热点新闻（有信息时必须体现，按日期降序排列）
3. 🔬 最新研究成果（有信息时必须体现，按日期降序排列）
4. 💰 融资与投资动态（有信息时必须体现，按日期降序排列）
5. 🏛️ 政策与监管（有信息时必须体现，按日期降序排列）
6. 📅 行业活动预告（有信息时必须体现，按日期降序排列）
7. 🤖 AI 深度分析（必须保留）
8. 📎 附录：完整链接列表（必须保留，按日期降序排列）

### 4.3 保存报告

推荐使用确定性 Markdown 生成入口，避免人工链接或旧内容混入：

```powershell
python scripts\report_pipeline.py --render-md data\approved_YYYY-MM-DD.json --date YYYY-MM-DD --raw data\raw_YYYY-MM-DD.json --output reports\YYYY-MM-DD.md
```

保存到 `reports/YYYY-MM-DD.md` 后继续执行验证。

---

## Step 5: 生成H5 HTML报告（定稿模板）

**正式日报必须调用生产渲染器，严禁用 `render_html.py` / `render_email.py` 作为正式输出：**

```powershell
python scripts\generate_from_template.py --date YYYY-MM-DD --approved data\approved_YYYY-MM-DD.json --markdown reports\YYYY-MM-DD.md --html-output reports\synbio_daily_YYYY-MM-DD.html --email-output reports\email_YYYY-MM-DD.html
```

`generate_from_template.py` 会读取定稿模板、填充所有占位符，并在写出前执行 HTML safety 与 approved URL 一致性检查。

### 5.1 读取定稿模板
**必须读取** `templates/daily_report_template_v2.html`

该模板是定稿版本，CSS样式、类名、布局结构**严禁修改**。

### 5.2 替换占位符
模板中的占位符：
- `{{DATE}}` → 日期
- `{{DATE_FULL}}` → 完整日期
- `{{DATE_FILE}}` → 文件名日期
- `{{WEEKDAY}}` → 星期几
- `{{GEN_TIME}}` → 生成时间
- `{{GEN_TIME_FULL}}` → 完整生成时间
- `{{SUMMARY_ITEMS}}` → 执行摘要（按AI评分从高到低取前5条）
- `{{NEWS_SECTION}}` → 行业热点新闻板块
- `{{RESEARCH_SECTION}}` → 最新研究成果板块
- `{{FUNDING_SECTION}}` → 融资与投资动态板块
- `{{POLICY_SECTION}}` → 政策与监管板块
- `{{EVENTS_SECTION}}` → 行业活动预告板块
- `{{ANALYSIS_SECTION}}` → AI深度分析板块
- `{{APPENDIX_SECTION}}` → 附录板块

### 5.3 定稿格式要求（严禁修改）

**执行摘要格式**：
```html
<div class="summary-section">
    <div class="section-title">📌 执行摘要（以AI评分，从高到低，列出前五项）</div>
    <ul class="summary-list">
        <li><span class="num">1</span><span class="text"><strong>标题：</strong>摘要内容...（YYYY-MM-DD）</span></li>
    </ul>
</div>
```
- 每条执行摘要末尾必须标注日期 `（YYYY-MM-DD）`
- 执行摘要按日期降序排列（最新→最旧）

**新闻/研究/政策卡片格式**：
```html
<div class="card">
    <div class="card-header">
        <div class="card-title">文章标题</div>
        <span class="card-tag">标签</span>
    </div>
    <div class="card-meta">
        <span>📰 来源名称</span>
        <span>📅 2026-06-08</span>
    </div>
    <div class="card-summary">摘要内容...</div>
    <a href="https://原始文章链接" target="_blank" rel="noopener noreferrer" class="card-link">查看详情</a>
</div>
```
- 同一板块内的多个卡片必须按日期降序排列（最新→最旧）

**融资表格格式**：
```html
<table class="data-table">
    <tr><th>公司</th><th>轮次</th><th>金额</th><th>投资方</th><th>时间</th><th>详情</th></tr>
    <tr><td><strong>公司名</strong></td><td>轮次</td><td>金额</td><td>投资方</td><td>2026-06-08</td><td><a href="https://原始链接">查看</a></td></tr>
</table>
```
- 表格行必须按"时间"列降序排列（最新→最旧）

**活动表格格式**：
```html
<table class="data-table">
    <tr><th>活动名称</th><th>时间</th><th>地点</th><th>核心看点</th><th>详情</th></tr>
    <tr><td><strong>活动名</strong></td><td>2026-06-15</td><td>地点</td><td>看点</td><td><a href="https://原始链接">查看</a></td></tr>
</table>
```
- 表格行必须按"时间"列降序排列（最新→最旧，未来日期在前）

**AI分析格式**：
```html
<div class="analysis-block">
    <h4>📈 趋势研判</h4>
    <p><strong>1. 趋势标题</strong></p>
    <p>分析内容...</p>
</div>
<div class="analysis-block">
    <h4>🏢 竞争格局变化</h4>
    <p>...</p>
    <ul>...</ul>
</div>
<div class="risk-box">
    <h4>⚠️ 风险提示</h4>
    <ul>...</ul>
</div>
```

**附录格式**：
```html
<div class="content-section">
    <div class="section-title">📎 附录：完整链接列表</div>
    <table class="data-table">
        <tr><th>序号</th><th>信息标题</th><th>来源链接</th></tr>
        <tr><td>1</td><td>标题</td><td><a href="https://原始链接">点击查看</a></td></tr>
    </table>
</div>
```

### 5.4 链接要求（必须遵守）

1. 每个新闻卡片必须有 `<a href="原始链接" class="card-link">查看详情</a>`
2. 每个研究卡片必须有 `<a href="原始链接" class="card-link">查看详情</a>`
3. 每个政策卡片必须有 `<a href="原始链接" class="card-link">查看详情</a>`
4. 融资表格的"详情"列必须有 `<a href="原始链接">查看</a>`
5. 活动表格的"详情"列必须有 `<a href="原始链接">查看</a>`
6. 附录表格的"来源链接"列必须有 `<a href="原始链接">点击查看</a>`
7. **严禁使用分类页面URL作为链接**
8. 如果无法获取具体文章URL，使用搜索结果的URL，并在链接文字标注"[来源页面]"

### 5.5 板块缺失处理

如果某板块无approved信息：
- 保留板块标题，内部标注 `<p style="color:#888;font-size:14px;">经五轮检索，本周期暂无相关新信息收录。</p>`

### 5.6 保存H5报告
保存到 `reports/synbio_daily_YYYY-MM-DD.html`

---

## Step 6: 合规复检（迭代修正，最多3次）

### 6.1 调用脚本验证

```python
import sys
sys.path.insert(0, r"scripts")
from report_pipeline import run_compliance_check
import json
from settings import date_str

date_str = date_str()
report_path = rf"reports/{date_str}.md"

result = run_compliance_check(report_path)

print(f"验证结果: passed={result['passed']}, can_send={result['can_send_email']}, score={result['overall_score']}")

if result['fix_instructions']:
    print(f"需要修复的问题 ({len(result['fix_instructions'])}条):")
    for i, instr in enumerate(result['fix_instructions'], 1):
        print(f"  {i}. {instr}")
```

### 6.2 额外检查H5格式

验证H5报告是否符合定稿模板：
- 检查是否使用了定稿的CSS类名（`.card`、`.card-link`、`.data-table`、`.analysis-block`、`.risk-box`、`.summary-list`、`.num`）
- 检查每个卡片是否有原始链接
- 检查是否有禁止的CSS类名（`.news-card`、`.news-link`、`.summary-box` 等旧版类名）

**推荐：使用 PythonRun 执行自动化格式检查**：

```python
def main(ctx):
    import re
    date_str = "YYYY-MM-DD"  # 替换为实际日期
    html_path = rf"reports/{date_str}.html"
    
    with open(html_path, 'r', encoding='utf-8') as f:
        html = f.read()
    
    checks = {
        "定稿CSS类名 .card": ".card" in html,
        "定稿CSS类名 .card-link": ".card-link" in html,
        "定稿CSS类名 .data-table": ".data-table" in html,
        "定稿CSS类名 .analysis-block": ".analysis-block" in html,
        "定稿CSS类名 .risk-box": ".risk-box" in html,
        "定稿CSS类名 .summary-list": ".summary-list" in html,
        "定稿CSS类名 .num": ".num" in html,
        "禁止旧版类名 .news-card": ".news-card" not in html,
        "禁止旧版类名 .news-link": ".news-link" not in html,
        "禁止旧版类名 .summary-box": ".summary-box" not in html,
        "每个卡片有原始链接": html.count('class="card-link"') >= 4,
        "融资表格有链接": "<a href=" in html and ".data-table" in html,
        "附录表格有链接": "附录" in html and "<a href=" in html,
    }
    
    all_passed = all(checks.values())
    for check, passed in checks.items():
        status = "✅ 通过" if passed else "❌ 未通过"
        print(f"  {status}: {check}")
    print(f"\n总体结果: {'通过' if all_passed else '未通过'}")
    
    return {"h5_check_passed": all_passed, "checks": checks}
```

如果检查未通过，根据失败项修正H5报告后重新保存。

### 6.3 迭代修正规则

```
IF result["passed"] == False OR result["can_send_email"] == False:
    → 根据 fix_instructions 逐项修正报告
    → 修正后重新保存报告
    → 再次调用 run_compliance_check() 验证
    → 最多迭代3次
    
IF 3次迭代后仍不通过:
    → 记录错误到 data/validation_{date_str}.json
    → 跳过邮件发送
    → 在报告中注明"邮件发送因合规检查未通过而暂停"
```

---

## Step 7: 生成邮件正文（与H5严格一致）

### 7.1 核心原则

**邮件正文 = H5 报告的结构化摘要版**

- 邮件正文的**每一条信息**，必须直接从 H5 报告或 approved 数据中提取
- 邮件正文的**每一个链接**，必须与 H5 报告中对应信息的链接**完全一致**
- 邮件正文对同一事件的描述，必须与 H5 一致，**只允许精简（缩短摘要），不允许改写或添加新观点**
- **严禁在邮件正文中出现 H5 报告里没有的信息**
- **严禁在邮件正文中遗漏 H5 报告里的关键信息**

### 7.2 邮件正文板块结构（与 H5 一一对应）

```
📌 执行摘要（以AI评分，从高到低，列出前五项）
    → 与 H5 完全一致，顺序不变
    → 每条标题可点击链接到原始文章

📰 各板块精选（只放 H5 中 approved 的信息）
    → 行业热点：H5 中有则放 1-2 条最重要的，带原始链接
    → 研究成果：H5 中有则放 1-2 条最重要的，带原始链接
    → 融资动态：H5 中有则放 1-2 条最重要的，带原始链接
    → 政策监管：H5 中有则放 1-2 条最重要的，带原始链接
    → 活动预告：H5 中有则放 1-2 条最重要的，带原始链接
    → 如某板块无 approved 信息，保留板块并标注"经五轮检索，本周期暂无相关新信息收录。"

🧠 AI 深度分析要点（3个核心结论）
    → 趋势研判：1-2 句话（必须来自 H5 的 AI 分析板块）
    → 竞争格局：1-2 句话（必须来自 H5 的 AI 分析板块）
    → 风险提示：1-2 句话（必须来自 H5 的 AI 分析板块）

📎 提示：详细报告请查看附件 HTML
```

### 7.3 邮件正文生成方法（强制步骤）

**必须使用以下方法生成邮件正文，严禁自由创作：**

1. 读取 `data/approved_YYYY-MM-DD.json` 获取所有 approved 信息
2. 读取 `reports/synbio_daily_YYYY-MM-DD.html` 获取 H5 报告内容
3. 从 approved 数据中按板块分类，每个板块取价值分数最高的 1-2 条
4. 从 H5 的 AI 分析板块提取 3 个核心结论
5. 使用定稿 CSS 样式组装邮件正文 HTML
6. **确保邮件中的每个链接都与 approved 数据中的 url 字段完全一致**

### 7.4 邮件正文验证（强制步骤）

生成邮件正文后，必须使用 PythonRun 执行以下验证代码：

```python
import sys
sys.path.insert(0, r"scripts")
from report_pipeline import validate_email_consistency
import json
from settings import date_str

date_str = date_str()

approved_path = rf"data/approved_{date_str}.json"
with open(approved_path, 'r', encoding='utf-8') as f:
    approved_data = json.load(f)

email_path = rf"reports/email_{date_str}.html"
with open(email_path, 'r', encoding='utf-8') as f:
    email_body = f.read()

result = validate_email_consistency(email_body, approved_data)

print(f"邮件一致性验证: is_consistent={result['is_consistent']}")
if result['errors']:
    print(f"错误 ({len(result['errors'])}条):")
    for e in result['errors']:
        print(f"  ❌ {e}")
if result['warnings']:
    print(f"警告 ({len(result['warnings'])}条):")
    for w in result['warnings']:
        print(f"  ⚠️ {w}")

# 如果不一致，必须修正
if not result['is_consistent']:
    print("邮件正文与H5不一致，必须修正后才能发送")
```

**验证失败的处理**：
- 如果邮件正文包含 H5/approved 中没有的 URL → **删除该链接对应的内容**
- 如果邮件正文包含 H5/approved 中没有的信息标题 → **删除该信息**
- 如果邮件正文遗漏了执行摘要的关键信息 → **从 H5 补充**
- 如果邮件正文链接与 H5 不一致 → **修正为 H5 中的链接**

---

## Step 8: 邮件推送（send gate通过后才发送）

### 8.1 检查验证结果
必须通过 `scripts/send_email.py` 的发送门禁。门禁会执行 pre-check、报告验证、AI防幻觉、approved 链接健康检查、post-check 和 MIME 检查；任一失败不得连接 SMTP。

### 8.2 邮件配置
读取 `config/email_config.json`
`check_url_health` 默认保持 `true`，除离线测试外不得关闭；`allow_simple_fallback` 默认保持 `false`。

### 8.3 发送邮件

```powershell
python scripts\send_email.py YYYY-MM-DD reports\YYYY-MM-DD.md reports\synbio_daily_YYYY-MM-DD.html reports\email_YYYY-MM-DD.html --dry-run
python scripts\send_email.py YYYY-MM-DD reports\YYYY-MM-DD.md reports\synbio_daily_YYYY-MM-DD.html reports\email_YYYY-MM-DD.html
```

**MIME类型规则（严禁违反）**：
- HTML附件：`MIMEText(content, 'html', 'utf-8')`
- Markdown附件：`MIMEText(content, 'plain', 'utf-8')`
- **严禁使用 `MIMEBase('application', 'octet-stream')` 或 `application/octet-stream`**

---

## Step 9: 更新政策库

如有新收录的政策，更新 `config/policy_database.json`。

**重要：编辑前必须先读取并验证现有JSON格式**。该文件由历次报告运行自动维护，可能因并发编辑或格式问题存在语法错误（如数组元素间缺少逗号）。

**更新流程**：
1. 读取现有 `policy_database.json`
2. 用 `json.load()` 验证格式；如失败，先修复语法错误再添加新政策
3. 将新政策追加到 `policies` 数组
4. 更新 `last_updated` 字段
5. 保存后用 `json.load()` 再次验证
6. 如验证失败，回退到备份并记录错误

---

## 输出要求

1. **必须使用脚本处理信息** — 严禁跳过过滤/去重/排序步骤
2. **必须通过合规复检** — Markdown验证不通过不得发送邮件
3. **邮件必须与H5一致** — 邮件验证不通过不得发送邮件
4. **H5必须使用定稿模板** — CSS类名、样式、布局严禁修改
5. **所有链接必须是原始文章链接** — 严禁使用分类页面URL
6. **邮件正文必须使用定稿样式** — 确保链接在邮件中正确显示
7. **板块灵活处理** — 有信息必须体现，无信息可临时去掉
8. **最多迭代3次** — 3次仍不通过则记录错误并跳过发送
9. **完成后返回**：
   - 报告文件路径
   - 邮件发送状态（成功/失败/跳过及原因）
   - 收录信息数量、通过数量、拒绝数量
   - Markdown验证得分
   - 邮件一致性验证结果
   - 各板块信息数量
   - 主要趋势判断

---

## 防偏差机制（强制规则）

### 核心原则

> **无论自动任务还是手动操作，必须严格执行完整流水线。**
> 
> **严禁跳过任何步骤。严禁基于搜索结果直接手写报告。**
> 
> **慢无所谓，对最重要。**

### 完整流水线（9步，缺一不可）

```
Step 1: 读取配置（数据源 + 去重规则 + 脚本指南）
Step 2: 多维度搜索（五轮搜索法）
Step 3: 保存原始数据和搜索日志 → data/raw_YYYY-MM-DD.json + data/search_log_YYYY-MM-DD.json
Step 4: 调用 report_pipeline.py 处理（去重+过滤+排序+搜索日志审计）
Step 5: 基于 approved 列表和 raw 计数生成Markdown报告
Step 6: 调用 report_pipeline.py 验证报告格式
Step 7: 生成H5 HTML报告
Step 8: 生成邮件正文（与H5严格一致）
Step 9: 邮件推送（send gate通过后才发送）
```

**任何情况下，Step 3→Step 4→Step 5→Step 6 必须连续执行，不得跳过。**

### 防偏差检查清单

#### 检查点A：原始数据已保存
- [ ] 已创建 `data/raw_YYYY-MM-DD.json`
- [ ] 已创建 `data/search_log_YYYY-MM-DD.json`，覆盖 r1-r5 五轮搜索 query
- [ ] JSON中包含所有搜索到的信息（news/research/funding/policy/events）
- [ ] 每条信息有title/source/date/summary/url/type/source_round字段
- [ ] url字段是具体文章链接，不是网站首页

**未保存原始数据或搜索日志 → 禁止生成报告**

#### 检查点B：脚本已执行
- [ ] 已调用 `report_pipeline.py` 处理每个类别
- [ ] 已查看处理结果（approved/rejected数量）
- [ ] 已确认 rejected 原因（去重/时效性/政策库）
- [ ] 已保存 `data/approved_YYYY-MM-DD.json`

**未执行脚本处理 → 禁止生成报告**

#### 检查点C：只使用approved数据
- [ ] 报告中的每条信息都能在 `data/approved_YYYY-MM-DD.json` 中找到
- [ ] 报告中的信息标题与approved数据中的title一致
- [ ] 报告中的链接与approved数据中的url一致
- [ ] 没有使用任何rejected列表中的信息

**发现未approved信息混入报告 → 立即删除并重新检查**

#### 检查点D：报告已验证
- [ ] 已调用 `report_pipeline.py` 验证报告格式
- [ ] `passed=True` 且 `can_send_email=True`
- [ ] 得分 >= 80
- [ ] 无必须修复的fix_instructions

**验证不通过 → 禁止发送邮件，必须修正后重新验证**

#### 检查点E：邮件一致性
- [ ] 邮件正文中的每条信息都在H5报告中存在
- [ ] 邮件正文中的每个链接都与H5报告中的链接一致
- [ ] 邮件正文没有H5报告中没有的信息

**邮件与H5不一致 → 禁止发送邮件**

### 常见偏差模式与对策

| 偏差模式 | 后果 | 对策 |
|---------|------|------|
| 基于搜索结果直接手写报告 | 去重失效、信息重复、格式错误 | **强制先保存JSON，再调用脚本** |
| 缺少搜索日志或 source_round | 无法证明五轮检索，旧内容可能补录混入 | **发送前 pre_check 强制阻断** |
| 跳过report_pipeline.py | 去重失效、时效性不检查、价值不排序 | **脚本执行是门禁，不执行不生成** |
| 使用rejected信息 | 重复信息、过期信息混入报告 | **只使用approved列表** |
| 跳过验证直接发送 | 格式错误、日期排序错误 | **验证不通过禁止发送** |
| 邮件自由创作不基于H5 | 邮件与报告不一致 | **邮件必须从approved+H5提取** |
| 为了快而省略步骤 | 质量下降、错误频发 | **慢无所谓，对最重要** |

### 手动操作特别规则

当用户要求"今天发一下""重新生成"等紧急请求时：

1. **不得跳过任何步骤**
2. **必须明确告知用户正在执行完整流程**
3. **如果某步骤失败，必须修正后才能继续**
4. **不得为了快而降低质量**

**标准回复模板**：
> "正在执行完整流水线：五轮搜索 → 保存JSON → 脚本处理（去重+过滤） → 生成报告 → 验证 → 发送邮件。预计需要X分钟，请稍候。"

### 偏差事后处理

如果发现已发送的报告存在偏差（如重复、遗漏、格式错误）：

1. **立即记录偏差原因**到 `data/deviation_log.json`
2. **分析根本原因**：是步骤跳过？还是规则理解错误？
3. **更新防偏差机制**：将新发现的偏差模式加入本文件
4. **重新生成并补发**正确版本
5. **向用户说明情况**并道歉

---

*详细防偏差规则参见 `config/anti_deviation_rules.md`
