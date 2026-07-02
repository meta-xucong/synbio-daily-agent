# AS hub | 合成生物行业日报 Agent

> **AS hub = AI Synbio hub** — 用AI服务合成生物，专注于资讯、助手、营销  
> **Slogan**: AS Now as Future  
> **核心原则**: 我们不是新闻的搬运工。信息按价值排序，综合分析政策/科研/行业，提供趋势预测。  
> **质量原则**: 慢无所谓，对最重要。严禁跳过任何步骤。

---

## 项目简介

这是一个基于 Kimi Work (Daimon) 的自动化日报生成 Agent，每天自动搜索合成生物行业最新资讯，经过**脚本强制过滤、去重、价值排序**后，生成 Markdown + H5 HTML 双版本报告，并推送到指定邮箱。

**关键特性**:
- **高召回混合搜索**: r1-r6 基座必搜 → LLM 动态 query → Kimi/LLM `llm_discovery` → `llm_gap_audit`
- **脚本强制去重**: 基于历史报告指纹库，严禁手动绕过
- **防偏差机制**: 9步完整流水线，任何情况下不得跳过
- **AI分析防幻觉**: AI深度分析只能引用正文已收录的信息
- **发送门禁**: pre-check + 报告验证 + AI防幻觉 + post-check + MIME检查，全部通过才发送

---

## 目录结构

```
synbio-daily-agent/
├── README.md                          # 本文件
├── SKILL.md                           # Kimi Work 技能定义（完整工作流）
├── config/
│   ├── anti_deviation_rules.md        # 防偏差机制（强制规则，任何情况不得绕过）
│   ├── data_sources.json              # 重点网站数据源配置
│   ├── dedup_rules.md                 # 时效性与去重规则
│   ├── email_config.json              # 邮件配置（本地文件，已gitignore）
│   ├── email_config.example.json      # 邮件配置模板
│   └── policy_database.json           # 已收录政策库
├── scripts/
│   ├── settings.py                    # 路径、时区和环境变量配置
│   ├── search_executor.py             # 执行基座+LLM动态搜索并生成search_log
│   ├── report_pipeline.py             # 核心过滤/去重/验证脚本
│   ├── generate_from_template.py       # 生产级H5/邮件模板渲染器
│   ├── send_email.py                  # 邮件发送脚本
│   ├── render_utils.py                # HTML安全转义和URL校验
│   ├── render_html.py                  # 安全最小fallback/测试夹具
│   ├── render_email.py                 # 安全最小fallback/测试夹具
│   ├── pre_check.py                   # 预检查脚本（生成报告前强制检查）
│   ├── post_check.py                  # 报告后检查脚本（确保只含approved信息）
│   └── ai_analysis_check.py          # AI分析防幻觉验证脚本
├── templates/
│   └── daily_report_template.md       # Markdown 报告模板（含日期标注示例）
├── data/                              # 运行时数据（搜索原始数据、处理结果、验证日志）
└── reports/                           # 生成的报告输出
```

---

## 完整流水线（9步，缺一不可）

```
Step 1: 读取配置（anti_deviation_rules.md + 数据源 + 去重规则）
Step 2: 生成 LLM 动态搜索策略，并执行基座必搜 + 动态 query
Step 3: 保存结构化搜索日志，并自动生成 raw → data/search_strategy_YYYY-MM-DD.json + data/search_log_YYYY-MM-DD.json + data/raw_YYYY-MM-DD.json
Step 4: 调用 report_pipeline.py --build-approved --search-log --search-strategy 处理（基座必搜门禁+LLM动态query门禁+覆盖率审计+去重+过滤+死链剔除+标题匹配+LLM领域审计+排序；链接健康、标题匹配、领域审计和搜索覆盖默认开启）
Step 5: 调用 report_pipeline.py --render-md --raw 基于 approved 生成Markdown报告
Step 6: 调用 report_pipeline.py 验证报告格式
Step 7: 调用 generate_from_template.py 生成定稿H5 HTML报告
Step 8: 调用 generate_from_template.py 生成定稿邮件正文
Step 9: 邮件推送（send gate通过后才发送）
```

**任何情况下，Step 2→Step 3→Step 4→Step 5→Step 6 必须连续执行，不得跳过。发送 gate 会阻断缺少搜索日志、缺少 `config/search_queries.json` 必搜查询记录，或 raw 候选缺少 `source_round` 的报告；build-approved 传入 `--search-strategy` 时还会阻断未执行的 LLM 动态 query。**

---

## 核心机制详解

### 1. 基座必搜 + LLM 动态搜索策略

| 轮次 | 目的 | 示例 Query |
|------|------|-----------|
| 第一轮 | 通用搜索 | `合成生物 最新新闻 今日` |
| 第二轮 | 定向搜索（site:重点网站） | `site:36kr.com 合成生物 融资` |
| 第三轮 | 英文补充 | `synthetic biology breakthrough 2026` |
| 第四轮 | 生成前复查 | `合成生物 今日 最新 白皮书 报告 发布 签约` |
| 第五轮 | 政府/会议强制搜索 | `site:gov.cn 合成生物 政策` |
| 第六轮 | 生物制造独立主题搜索 | `生物制造 产业化 项目` |
| LLM高召回 | 泛搜与缺口审计 | `llm_discovery` / `llm_gap_audit` |

`config/search_queries.json` 是每日基座必搜 query 的权威清单；`config/llm_search_strategy.json` 是 LLM 搜索中枢的种子记忆，不是固定 query 清单。每天先生成 `data/search_strategy_YYYY-MM-DD.json`，再执行基座 query 和策略里的动态 query。每个 query 建议 limit ≥ 15；即使无结果也必须记录 `executed: true, results_count: 0`。搜索日志应保留结构化结果（title/url/snippet/source/date），不要只保存人工挑选后的 URL。

### 2. 脚本处理（report_pipeline.py）

**输入**: `data/raw_YYYY-MM-DD.json` + `data/search_log_YYYY-MM-DD.json`
**输出**: `data/approved_YYYY-MM-DD.json` + `data/rejected_YYYY-MM-DD.json`

推荐生产命令使用统一入口，避免 Kimiwork/人工逐步执行时跳过搜索与审计门禁:

```powershell
python scripts\run_daily_pipeline.py --date YYYY-MM-DD --provider auto --timeout 30 --max-workers 5 --send --send-mode auto
```

只做 dry-run 验证时去掉 `--send`。以下分步命令仅供人工排障对照，正式日报不要手工拆开执行:

```powershell
python scripts\llm_search_strategy.py --date YYYY-MM-DD --output data\search_strategy_YYYY-MM-DD.json --mode llm
python scripts\search_executor.py --date YYYY-MM-DD --strategy data\search_strategy_YYYY-MM-DD.json --output data\search_log_YYYY-MM-DD.json --provider auto --limit 15 --timeout 30 --max-workers 5
python scripts\report_pipeline.py --build-raw-from-search data\search_log_YYYY-MM-DD.json --date YYYY-MM-DD --output data\raw_YYYY-MM-DD.json
python scripts\audit_search_log.py data\search_log_YYYY-MM-DD.json --raw data\raw_YYYY-MM-DD.json --search-strategy data\search_strategy_YYYY-MM-DD.json
python scripts\report_pipeline.py --build-approved data\raw_YYYY-MM-DD.json --date YYYY-MM-DD --output data --search-log data\search_log_YYYY-MM-DD.json --search-strategy data\search_strategy_YYYY-MM-DD.json
python scripts\report_pipeline.py --render-md data\approved_YYYY-MM-DD.json --date YYYY-MM-DD --raw data\raw_YYYY-MM-DD.json --output reports\YYYY-MM-DD.md
```

`search_executor.py` 是唯一推荐的生产搜索日志入口。它会读取 `config/search_queries.json` 的 r1-r6 基座必搜 query、同日 `search_strategy` 的 LLM 动态 query，并强制追加 `llm_discovery` 与 `llm_gap_audit` 两个高召回轮次。生产环境必须同时配置至少一个 fast search provider（Serper、Brave、Bing 或 Tavily）和 Kimi/Anthropic-compatible LLM：基础搜索由 fast provider 执行，Kimi 用于 LLM 策略和相关性判断。当前仓库默认启用兼容模式，高召回轮次默认复用基础 provider（`same`）并保留结构化搜索证据；如果未来切回 `strict` 模式，则高召回轮次必须由 `llm_web` 产出真实工具证据。

可配置的搜索 provider 环境变量：

```powershell
$env:SERPER_API_KEY = "<serper key>"              # google.serper.dev
$env:BRAVE_SEARCH_API_KEY = "<brave search key>" # api.search.brave.com
$env:BING_SEARCH_API_KEY = "<bing web search key>"
$env:TAVILY_API_KEY = "<tavily key>"
$env:ANTHROPIC_AUTH_TOKEN = "<kimi/anthropic-compatible key>" # required for LLM + llm_web high-recall rounds
```

默认 `--provider auto` 只按 Serper → Brave → Bing → Tavily 顺序选择基础搜索 provider，不会把 r1-r6 的几十上百条查询 fallback 到慢速 `llm_web`。当前默认高召回证据模式为 `compatible`，所以 `--llm-discovery-provider` 默认是 `same`；若显式切换 `SYNBIO_HIGH_RECALL_EVIDENCE_MODE=strict`，高召回轮次应改回 `llm_web` 并要求 `web_search_tool_result`。离线测试可用 `--provider fixture --fixture tests/fixtures/search_results.json`，人工诊断可显式加 `--allow-llm-web-base`，正式发送不得使用 fixture 或 `--allow-llm-web-base`。

如果基础 provider 是 Tavily 免费 key，建议保持 1 credit 的 Tavily 深度，并用 `--timeout 30 --max-workers 5 --rpm 90` 运行基础搜索轮次。项目默认使用 `search_depth=basic`，避免自动落到 2 credits 的 `advanced` 深度。这样可以把请求速率控制在 Tavily Development key 官方 100 RPM 之下，同时把 80+ 条必搜 query 从串行几十分钟压缩到几分钟级。

搜索日志必须记录 `config/search_queries.json` 中 r1-r6 的全部 `required_queries`，并包含 `generated_by=search_executor`、`limit>=15`、`llm_discovery`、`llm_gap_audit`。raw 中每条候选必须带 `source_round`，例如：

```json
{
  "date": "YYYY-MM-DD",
  "rounds": [
    {"round": "r1", "queries": ["合成生物 最新新闻 今日"], "candidates": ["https://example.com/article"]},
    {"round": "r2", "queries": ["site:36kr.com 合成生物 融资"], "candidates": []},
    {"round": "r3", "queries": ["synthetic biology breakthrough 2026"], "candidates": []},
    {"round": "r4", "queries": ["合成生物 今日 最新"], "candidates": []},
    {"round": "r5", "queries": ["site:gov.cn 合成生物 政策"], "candidates": []}
  ]
}
```

处理流程:
1. **URL过滤**: 拒绝站点首页、分类/聚合页、黑名单域名和不安全URL
2. **时效性过滤**: 新闻3天、研究14天、融资7天、政策7天、活动60天；日期无法解析直接拒绝
3. **基座必搜 query 门禁**: build-approved 和 send gate 默认要求 search_log 覆盖 `config/search_queries.json` 的所有 required query；缺少 `site:` 定向查询会阻断
4. **LLM动态 query 门禁**: 传入 `--search-strategy` 时，策略中的 required query 必须在 search_log 中成功执行；缺失或失败会阻断 build-approved
5. **搜索覆盖率审计**: 强制要求 search_log 中的候选 URL 都进入 raw，防止搜索结果被人工挑选阶段静默丢弃
6. **去重检查**:
   - 指纹匹配（MD5哈希，基于 company+type+完整title）
   - 公司重复（同一公司+同一类型视为重复）
   - 标题相似度（SequenceMatcher ≥80% 视为重复）
   - 最近30天历史报告 + `data/history_index.json` 持久化索引
   - 主链接和 `urls` 备用链接都会参与跨天去重
   - 当前批次内部重复与同URL不同标题冲突会被拒绝
7. **链接健康检查**: build-approved 默认会剔除 4xx/5xx、超时、证书失败以及“文章已删除/账号已注销/页面不存在”等软失效页面；仅离线测试可用 `--skip-url-health` 临时关闭
8. **标题匹配检查**: build-approved 默认会读取页面标题信号，剔除 URL 可访问但标题明显张冠李戴的信息；网络错误只记录 warning，仅离线测试可用 `--skip-title-match` 临时关闭
9. **LLM 领域审计**: `--llm-relevance-mode auto` 默认开启；配置 `ANTHROPIC_BASE_URL` 和 `ANTHROPIC_AUTH_TOKEN` 后调用 Anthropic-compatible provider 判断是否属于合成生物/生物制造领域，未配置时使用本地语义 fallback 拦截明显跑题项
10. **价值评分**: 保留 `raw_score`，`value_score` 归一化为0-10
11. **approved schema**: 发送前要求 `title/source/date/summary/url/type/raw_score/value_score`，并检查类别一致性、日期、URL和分数范围

### 3. 报告格式验证

验证项:
- 8个必需板块（执行摘要、新闻、研究、融资、政策、活动、AI分析、附录）
- 执行摘要: 至少1条，最多8条，**每条末尾必须标注（YYYY-MM-DD）**，按日期降序排列
- 表格格式: 新闻/融资/活动/研究必须使用表格，空板块标注"本周期暂无"可豁免
- 政策板块: 必须包含"国内政策"和"国际监管动态"子标题
- AI分析: 必须包含"趋势研判"、"竞争格局变化"、"风险提示"三个子板块
- 附录: 至少1个链接

### 4. AI深度分析防幻觉规则

**核心原则**: AI分析只能基于正文已收录的approved信息，严禁引入任何外部知识。

**强制检查清单**:
- [ ] 每个公司名必须在正文表格中出现过
- [ ] 每个具体事件/数据必须在正文中有来源
- [ ] 所有数字必须来自正文信息
- [ ] 趋势推断的逻辑起点必须是正文信息

**常见幻觉黑名单**（已发现的历史幻觉）:
- 引航生物、瑞德林、微元合成、森瑞斯、桦冠生物、百雀羚
- LanzaX、SDL、Kamau Therapeutics、Anthropic
- "港交所A1申请"、"143家创新企业"、"50名领军人才"

### 5. 邮件发送规则

- **主题**: `合成生物行业日报 - YYYY-MM-DD`
- **附件**: HTML报告（MIME: text/html）+ Markdown报告（MIME: text/plain）
- **严禁**: 使用 `application/octet-stream`（会导致附件变成.bin文件）

---

## 当前验证方式

项目状态以自动化测试和脚本返回码为准，不在文档中声明永久满分状态。

```powershell
python -m pytest -q
python scripts\report_pipeline.py --build-raw-from-search data\search_log_2026-06-11.json --date 2026-06-11 --output data\raw_2026-06-11.json
python scripts\report_pipeline.py --build-approved data\raw_2026-06-11.json --date 2026-06-11 --output data --search-log data\search_log_2026-06-11.json
python scripts\report_pipeline.py --render-md data\approved_2026-06-11.json --date 2026-06-11 --raw data\raw_2026-06-11.json --output reports\2026-06-11.md
python scripts\generate_from_template.py --date 2026-06-11 --approved data\approved_2026-06-11.json --markdown reports\2026-06-11.md --html-output reports\synbio_daily_2026-06-11.html --email-output reports\email_2026-06-11.html
python scripts\send_email.py 2026-06-11 reports\2026-06-11.md reports\synbio_daily_2026-06-11.html reports\email_2026-06-11.html --dry-run
```

邮件发送必须通过 `send_email.py` 的 gate；gate 失败时不会连接 SMTP。
正式 H5/邮件正文必须由 `generate_from_template.py` 生成；`render_html.py` / `render_email.py` 仅用于 emergency fallback 或测试夹具。

`config/email_config.json` 中的 `allow_simple_fallback` 默认应保持 `false`。只有在 SMTP 服务商持续拒绝带附件的 multipart 邮件，并且可接受“仅 HTML 正文、无附件”的降级发送时，才显式设为 `true`。
`check_url_health` 默认应保持 `true`；`url_health_mode` 默认应保持 `strict`。受限网络环境反复出现 SSL/证书握手误报时，可临时设为 `soft`，此时 404、页面已删除仍阻断，SSL/证书类网络错误只作为 warning。
真实发送同一日期日报默认只允许一次；确需人工补发时使用 `--force-send --send-mode manual`，该操作仍会执行所有内容门禁，并写入 `data/send_log.json` 留痕。

---

## 重点数据源

### 国外媒体（英文）
- [SynBioBeta](https://synbiobeta.com)
- [GEN / Genetic Engineering & Biotechnology News](https://genengnews.com)
- [Labiotech](https://labiotech.eu)
- [CRISPR Medicine News](https://crisprmedicinenews.com)
- [FierceBiotech](https://fiercebiotech.com)
- [iGEM](https://competition.igem.org)

### 国内媒体（中文）
- 深波synbio（微信公众号）
- [合成生物学网](https://synbio-he.com)
- [动脉网](https://vbdata.cn)
- [医药魔方](https://bydrug.pharmcube.com)
- [生物谷](https://bioon.com)
- [投资界](https://pedaily.cn)
- [36氪](https://36kr.com)
- [科技日报](https://stdaily.com)

---

## 定时任务配置

在 Kimi Work 中创建 cron 任务:

```
名称: 合成生物行业日报-每日生成
触发: 每天 08:15 (Asia/Shanghai)
执行: local_conversation
Prompt: 读取 config/anti_deviation_rules.md，执行完整9步流水线
```

---

## 输出示例

### 执行摘要（TOP 5，带日期标注）
```
1. **绿色康成完成pre-A轮融资**（2026-06-08）：清华系AI+合成生物企业...
   完成数千万元pre-A轮融资，由北京国管旗下基金投资。（2026-06-08）
2. **亚洲首个合成细胞技术路线图发布**（2026-06-06）：中科院深圳先进院...
   六国科学家联合在Nature Biotechnology发表。（2026-06-06）
```

### 板块结构
- 📰 行业热点新闻（表格，按日期降序）
- 🔬 最新研究成果（表格，按日期降序）
- 💰 融资与投资动态（表格，按日期降序）
- 🏛️ 政策与监管（国内政策表格 + 国际监管动态）
- 📅 行业活动预告（表格，按日期降序）
- 🤖 AI 深度分析（趋势研判 + 竞争格局 + 风险提示）
- 📎 附录：完整链接列表

---

## 维护与更新

### 更新数据源
编辑 `config/data_sources.json` 添加/删除重点网站。

### 调整去重规则
编辑 `config/dedup_rules.md` 修改时效性窗口或相似度阈值。

### 路径配置
设置 `SYNBIO_DAILY_HOME` 可覆盖项目根目录；默认使用仓库根目录。设置 `SYNBIO_DAILY_TZ` 可覆盖时区，默认 `Asia/Shanghai`。

### 修改防偏差机制
编辑 `config/anti_deviation_rules.md`，任何修改必须经过测试验证。

---

## 许可证

MIT License — 自由使用、修改、分发。

---

> **AS hub | AI Synbio hub**  
> "AS Now as Future"
