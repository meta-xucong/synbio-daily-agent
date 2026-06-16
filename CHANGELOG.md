# 更新日志 (Changelog)

## 2026-06-16

### 修复与优化

#### 1. 去重机制强化 — 跨天持久化历史索引 (`history_index.json`)
- **问题**：之前去重仅基于最近 30 天报告文件扫描，无法有效防止跨天重复发送（如 6 月 13 日已发送内容在 6 月 14 日再次混入）。
- **解决**：
  - 新增 `data/history_index.json` 作为跨天持久化去重数据库，存储所有已发送条目的 URL、标题、内容指纹及首次发送日期。
  - `report_pipeline.py` 新增 `_load_history_index()`、`_make_fingerprint()`、`_is_historical_duplicate()` 三个函数，在 `process_raw_data` 的时效性检查之前执行跨天历史去重。
  - 去重维度覆盖：URL 完全匹配、标题完全匹配、内容关键词指纹相似度 > 75%。
  - `send_email.py` 新增 `_update_history_index()`，在 SMTP 发送成功后自动将 `approved` 条目追加到历史索引，确保后续日期不会再重复收录。

#### 2. URL 来源稳定性过滤 — 拦截聚合页与黑名单域名
- **问题**：6 月 14 日报告出现微信公众号链接（`mp.weixin.qq.com`）显示"账号已注销"、会议列表页（如 `conferences.nature.com`、`synbioconference.org`）混入，导致用户点击后无法访问正文；`newmarketpitch.com` 聚合多篇文章，内容重复且质量不可控。
- **解决**：
  - 新增 `DOMAIN_BLACKLIST`：明确排除 `newmarketpitch.com`、`conferences.nature.com`、`synbioconference.org` 等聚合/目录域名。
  - 新增 `URL_CATEGORY_BLACKLIST`：覆盖 `/category/`、`/news/`、`/events/`、`/tag/`、`/topics/` 等 30+ 种聚合路径模式。
  - 新增 `_is_category_or_aggregate_url()` 函数，在 `validate_raw_item` 之后立即执行 URL 过滤，拦截分类页/列表页/聚合页，避免其进入报告。

#### 3. 内容结构平衡优化
- **问题**：6 月 14 日报告中研究类内容仅 1 条（20%），企业/融资类占 5 条（80%），内容结构失衡，研究深度不足。
- **解决**：优化 6 月 16 日日报选稿策略，研究类占比提升至 29%（2 条），覆盖 `Nature Chemical Biology` 与 `Nature Communications` 两项成果；同时保持企业动态、政策监管、融资 IPO 多板块覆盖。

#### 4. 链接来源质量提升
- **问题**：此前报告大量使用微信公众号（`mp.weixin.qq.com`）作为来源，链接不稳定，存在"账号已注销"风险。
- **解决**：6 月 16 日全部 7 条信息均来自高稳定性来源：
  - 政府官网（`fgw.sz.gov.cn`、`ggzyjy.wuxi.gov.cn`、`whht.org.cn`）
  - 权威媒体（`app.xinhuanet.com`、`stdaily.com`、`21jingji.com`）
  - 顶级学术期刊（`nature.com`）
  - 零微信公众号链接，零目录/聚合页面链接。

#### 5. 发送后自动归档
- `send_email.py` 在 `send_message_via_smtp` 成功后自动调用 `_update_history_index()`，实现发送与去重数据库的原子化同步，避免手动维护遗漏。

### 文件变更
- `scripts/report_pipeline.py`
  - 添加常量：`URL_CATEGORY_BLACKLIST`、`DOMAIN_BLACKLIST`
  - 添加函数：`_is_category_or_aggregate_url()`、`_load_history_index()`、`_make_fingerprint()`、`_is_historical_duplicate()`
  - 修改 `process_raw_data()`：插入 URL 过滤与跨天历史索引去重步骤
- `scripts/send_email.py`
  - 添加导入：`import re`
  - 添加函数：`_update_history_index()`
  - 修改 `send_daily_report()`：发送成功后自动更新历史索引
- 新增：`CHANGELOG.md`（本文档）

### 验证状态
- 6 月 16 日日报通过全部审计：无历史重复、无黑名单域名、无聚合页面、无失效微信链接、研究/产业内容比例平衡、当天仅发送一次。
