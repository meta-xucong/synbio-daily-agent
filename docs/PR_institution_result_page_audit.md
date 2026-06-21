# 科研机构成果页与科学网查询覆盖修复设计

## 背景

运行反馈显示，部分科研机构或高校来源的合成生物信息容易在两个位置丢失：

- 搜索层：科学网政策类标题常用“征求意见”“申报指南”“通知”“国家重点研发计划”等词，仅搜索“征集”覆盖不足。
- URL 过滤层：科研机构/高校站点中，成果页、论文列表页和具体文章页可能包含明确发表日期和论文信息，不应与普通商业聚合页混为一谈。

## 设计判断

不采用“科研机构域名全部白名单”的方案。

原因：

- `edu.cn`、`ac.cn`、`cas.cn` 等后缀覆盖大量学院首页、机构首页、新闻列表页和栏目页。
- 如果域名级别直接放行，会绕过现有聚合页防线，使站点根页、分类页、搜索页重新进入 approved 前流程。
- 真实日报需要具体可核验 URL；如果搜索结果只给机构根页，应让其停留在 rejected/待人工补链，而不是拿主页当论文链接发送。

采用窄例外方案：

- 继续拦截根页、`/index.html`、`/news`、`/category/`、`/topic/`、`?q=` 等明显聚合/列表 URL。
- 只对科研成果/论文路径做明确例外，例如 `/zxcg.htm`、`/cg.htm`、`/publications.html`、`/papers.html`。
- 保持具体文章路径放行，例如深圳先进院 `isynbio.siat.ac.cn/.../article_*.html`。

## 修改范围

### 1. 科学网必搜查询扩展

在 `config/search_queries.json` 的 r5 轮次增加：

- `site:sciencenet.cn 合成生物 征求意见`
- `site:sciencenet.cn 合成生物 申报指南`
- `site:sciencenet.cn 合成生物 通知`
- `site:sciencenet.cn 合成生物 国家重点研发计划`

这些 query 仍为 required query，必须进入 `search_log_YYYY-MM-DD.json`。

### 2. URL 聚合页窄例外

在 `scripts/report_pipeline.py` 中新增成果/论文页路径例外：

- `/zxcg.htm`
- `/cg.htm`
- `/publications.html`
- `/publication.html`
- `/papers.html`
- `/paper.html`
- `/latest-results.html`
- `/latest-result.html`

例外只在聚合页路径判断前生效；域名黑名单仍优先生效。

### 3. 文档漂移修正

当前代码已经强制 search coverage，`--relaxed-search-coverage` 不再存在。同步删除 README、USAGE_GUIDE、DEVELOPMENT 中的残留说明。

## 验收标准

- `isynbio.siat.ac.cn` 的具体文章 URL 通过聚合页过滤。
- `isynbio.siat.ac.cn/` 和 `/index.html` 仍被聚合页过滤。
- `synbio.suat-sz.edu.cn/index/zxcg.htm` 通过聚合页过滤。
- `example.com/news`、`example.com/category/...`、`example.com/search?q=...` 仍被过滤。
- 新增科学网 query 全部在配置中，并由 required-query gate 统计。
- 单元测试与全量测试通过。
