# AS hub | 合成生物行业日报 Agent

> **AS hub = AI Synbio hub** — 用AI服务合成生物，专注于资讯、助手、营销  
> **Slogan**: AS Now as Future  
> **核心原则**: 我们不是新闻的搬运工。信息按价值排序，综合分析政策/科研/行业，提供趋势预测。  
> **质量原则**: 慢无所谓，对最重要。严禁跳过任何步骤。

---

## 项目简介

这是一个基于 Kimi Work (Daimon) 的自动化日报生成 Agent，每天自动搜索合成生物行业最新资讯，经过**脚本强制过滤、去重、价值排序**后，生成 Markdown + H5 HTML 双版本报告，并推送到指定邮箱。

**关键特性**:
- **五轮搜索法**: 通用 → 定向 → 英文补充 → 生成前复查 → 政府/会议强制搜索
- **脚本强制去重**: 基于历史报告指纹库，严禁手动绕过
- **防偏差机制**: 9步完整流水线，任何情况下不得跳过
- **AI分析防幻觉**: AI深度分析只能引用正文已收录的信息
- **三重验证**: 结构验证 + 时效性验证 + 邮件一致性验证，全部通过才发送

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
│   ├── email_config.json              # 邮件配置（真实配置，已脱敏）
│   ├── email_config.example.json      # 邮件配置模板
│   └── policy_database.json           # 已收录政策库
├── scripts/
│   ├── report_pipeline.py             # 核心过滤/去重/验证脚本（1085行）
│   ├── send_email.py                  # 邮件发送脚本
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
Step 2: 多维度搜索（五轮搜索法）
Step 3: 保存原始数据为JSON → data/raw_YYYY-MM-DD.json
Step 4: 调用 report_pipeline.py 处理（去重+过滤+排序）
Step 5: 基于 approved 列表生成Markdown报告
Step 6: 调用 report_pipeline.py 验证报告格式
Step 7: 生成H5 HTML报告
Step 8: 生成邮件正文（与H5严格一致）
Step 9: 邮件推送（三重验证通过后才发送）
```

**任何情况下，Step 3→Step 4→Step 5→Step 6 必须连续执行，不得跳过。**

---

## 核心机制详解

### 1. 五轮搜索法

| 轮次 | 目的 | 示例 Query |
|------|------|-----------|
| 第一轮 | 通用搜索 | `合成生物 最新新闻 今日` |
| 第二轮 | 定向搜索（site:重点网站） | `site:36kr.com 合成生物 融资` |
| 第三轮 | 英文补充 | `synthetic biology breakthrough 2026` |
| 第四轮 | 生成前复查 | `合成生物 今日 最新` |
| 第五轮 | 政府/会议强制搜索 | `site:gov.cn 合成生物 政策` |

### 2. 脚本处理（report_pipeline.py）

**输入**: `data/raw_YYYY-MM-DD.json`  
**输出**: `data/approved_YYYY-MM-DD.json` + `data/rejected_YYYY-MM-DD.json`

处理流程:
1. **时效性过滤**: 新闻7天、研究14天、融资7天、政策30天、活动90天
2. **去重检查**: 
   - 指纹匹配（MD5哈希，基于 company+type+完整title）
   - 公司重复（同一公司+同一类型视为重复）
   - 标题相似度（60%关键词重叠视为重复）
3. **价值评分**: 来源权威性 + 信息完整性 + 时效性 + 行业影响力
4. **聚合多源报道**: 同一事件的多源报道合并

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

## 已知漏洞修复记录

### 2026-06-11 修复批次

| 批次 | 修复内容 | 严重程度 |
|------|----------|----------|
| **批次1** | 去重bug: extract_events_from_report 未保存 company/type 字段，导致公司匹配失效 | P0 |
| **批次2** | 3个严重缺陷: 空type穿透、金额正则错误、空白检测失效 | P0 |
| **批次3** | 信息匮乏日验证规则优化: 执行摘要下限1条、附录链接下限1条、空板块豁免 | P1 |
| **批次4** | 历史库加载修复: 排除当天报告、排除变体文件、排除"暂无"伪事件 | P0 |
| **批次5** | 7个漏洞: 当天活动误判过期、研究成果不提取、双历史库、指纹截断、关键词空格、键名不一致、邮件主题硬编码 | 3P0+4P1 |
| **批次6** | 10个问题: 白名单含幻觉公司、50%阈值过松、pre_check检查不存在文件、模板缺失日期标注、占位链接排除不完整 | 2P0+3P1+5P2 |

**当前状态**: 所有已知P0/P1缺陷已修复，验证通过（score=100）。

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

### 修改防偏差机制
编辑 `config/anti_deviation_rules.md`，任何修改必须经过测试验证。

---

## 许可证

MIT License — 自由使用、修改、分发。

---

> **AS hub | AI Synbio hub**  
> "AS Now as Future"
