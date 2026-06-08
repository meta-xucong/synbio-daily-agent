# AS hub | 合成生物行业日报 Agent

> **AS hub = AI Synbio hub** — 用AI服务合成生物，专注于资讯、助手、营销  
> **Slogan**: AS Now as Future  
> **核心原则**: 我们不是新闻的搬运工。信息按价值排序，综合分析政策/科研/行业，提供趋势预测。

---

## 项目简介

这是一个基于 Kimi Work (Daimon) 的自动化日报生成 Agent，每天自动搜索合成生物行业最新资讯，经过脚本过滤、去重、价值排序后，生成 Markdown + H5 HTML 双版本报告，并推送到指定邮箱。

## 工作流概览

```
Step 1: 读取配置（数据源 + 去重规则 + 脚本指南）
Step 2: 多维度搜索（四轮搜索法：通用→定向→英文补充→生成前复查）
Step 3: 脚本强制过滤与去重（严禁跳过）
Step 4: 生成 Markdown 报告
Step 5: 生成 H5 HTML 报告（使用定稿模板）
Step 6: 合规复检（迭代修正，最多3次）
Step 7: 生成邮件正文（与H5严格一致）
Step 8: 邮件推送（三重验证通过后才发送）
Step 9: 更新政策库
```

---

## 目录结构

```
synbio-daily-agent/
├── README.md                          # 本文件
├── SKILL.md                           # Kimi Work 技能定义（完整工作流）
├── templates/
│   ├── daily_report_template.md       # Markdown 报告模板
│   └── daily_report_template_v2.html  # H5 HTML 定稿模板（CSS严禁修改）
├── scripts/
│   ├── report_pipeline.py             # 核心过滤/去重/验证脚本
│   └── USAGE_GUIDE.md                 # 脚本使用指南
├── config/
│   ├── data_sources.json              # 重点网站数据源配置
│   ├── dedup_rules.md                 # 时效性与去重规则
│   ├── email_config.example.json      # 邮件配置模板（需填写真实信息）
│   └── feishu_config.example.json     # 飞书配置模板（可选）
├── data/                              # 运行时数据（搜索原始数据、处理结果）
└── reports/                           # 生成的报告输出
```

---

## 快速开始

### 1. 克隆仓库

```bash
git clone https://github.com/meta-xucong/synbio-daily-agent.git
cd synbio-daily-agent
```

### 2. 配置邮件

复制模板并填写真实信息：

```bash
cp config/email_config.example.json config/email_config.json
```

编辑 `config/email_config.json`：

```json
{
  "smtp_server": "smtp.exmail.qq.com",
  "smtp_port": 465,
  "sender_email": "your-email@example.com",
  "sender_password": "your-password",
  "receiver_email": "recipient@example.com",
  "enabled": true
}
```

### 3. 配置飞书（可选）

```bash
cp config/feishu_config.example.json config/feishu_config.json
```

### 4. 在 Kimi Work 中导入

将 `SKILL.md` 内容复制到 Kimi Work 的技能系统中，或作为 cron 任务的 prompt 使用。

---

## 核心规则

### 信息搜索（四轮搜索法）

| 轮次 | 目的 | 示例 Query |
|------|------|-----------|
| 第一轮 | 通用搜索 | `合成生物 最新新闻 今日` |
| 第二轮 | 定向搜索（site:重点网站） | `site:36kr.com 合成生物 融资` |
| 第三轮 | 英文补充 | `synthetic biology breakthrough 2026` |
| 第四轮 | 生成前复查 | `合成生物 今日 最新` |

### 脚本过滤（严禁跳过）

所有搜索到的信息必须通过 `report_pipeline.py` 处理：
- **时效性过滤**：新闻7天、研究14天、融资7天、政策30天、活动90天
- **去重检查**：标题相似度≥80%视为重复
- **价值评分**：每条信息必须有 0-10 的价值评分
- **来源验证**：必须有明确的来源网站

### 报告格式（定稿模板，严禁修改）

**H5 报告**使用 `templates/daily_report_template_v2.html`，CSS 类名严禁修改：
- `.card`、`.card-link`、`.data-table`
- `.analysis-block`、`.risk-box`
- `.summary-list`、`.num`

**邮件正文** = H5 的结构化摘要版，链接、内容、顺序必须与 H5 完全一致。

### 三重验证才能发送邮件

1. Markdown 报告合规检查通过（得分≥80）
2. 邮件正文与 H5 一致性验证通过
3. 所有链接为原始文章链接（严禁分类页面URL）

### MIME 类型规则

| 附件类型 | MIME 类型 | 严禁使用 |
|---------|----------|---------|
| HTML 报告 | `text/html` | `application/octet-stream` |
| Markdown 报告 | `text/plain` | `application/octet-stream` |

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

---

## 定时任务配置

在 Kimi Work 中创建 cron 任务：

```
名称: 合成生物行业日报
触发: 每天 08:15 (Asia/Shanghai)
执行: local_conversation
Prompt: 读取 SKILL.md，执行 synbio-daily-report 工作流
```

---

## 输出示例

### 执行摘要（TOP 5）
1. **绿色康成完成pre-A轮融资**（2026-06-08）：清华系AI+合成生物企业...
2. **亚洲首个合成细胞技术路线图发布**（2026-06-08）：中科院深圳先进院...

### 板块结构
- 📰 行业热点新闻
- 🔬 最新研究成果
- 💰 融资与投资动态
- 🏛️ 政策与监管
- 📅 行业活动预告
- 🤖 AI 深度分析（趋势研判 + 竞争格局 + 风险提示）
- 📎 附录：完整链接列表

---

## 维护与更新

### 更新数据源
编辑 `config/data_sources.json` 添加/删除重点网站。

### 调整去重规则
编辑 `config/dedup_rules.md` 修改时效性窗口或相似度阈值。

### 修改报告模板
**H5 模板** (`templates/daily_report_template_v2.html`) 为定稿版本，CSS 样式、类名、布局结构**严禁修改**。仅可修改占位符替换逻辑。

---

## 许可证

MIT License — 自由使用、修改、分发。

---

> **AS hub | AI Synbio hub**  
> "AS Now as Future"
