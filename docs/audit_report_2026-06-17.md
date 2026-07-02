# 历史审计报告

## 审计范围
- 6月12日、13日、14日、16日、17日 已发送报告
- 共 35 条已发送信息
- 抽样验证 14 条 URL 实际内容

## 问题分级

### P0 级（严重错误）：已发送内容完全错误

| 日期 | 标题 | URL | 问题 |
|------|------|-----|------|
| 6-17 | 江苏合成生物与生物制造高质量发展大会举办 | `zgjssw.gov.cn/...` | **标题与内容完全不符**：实际是"全市服务业大会召开"，与合成生物无关 |
| 6-12 | 荷兰精密发酵工厂启动... | `vegconomist.com/category/fermentation/` | **聚合页URL冒充具体文章**：该URL是分类页面，不是具体文章 |
| 6-12 | 中国科研团队合成降解工程菌株 | `ithome.com/tags/合成生物学` | **标签页URL**：聚合页被当作具体文章 |
| 6-12 | 梅奥诊所与Syntax Bio合作 | `bydrug.pharmcube.com/news?searchKey=合成生物&page=1` | **搜索页URL**：搜索结果被当作文章 |
| 6-13 | Ginkgo Bioworks推出合成生物平台 | `ginkgobioworks.com/news/2026-06-12` | **404编造URL**：Ginkgo没有此URL |
| 6-13 | Twist Bioscience发布DNA合成技术 | `twistbioscience.com/news/2026-06-11` | **404编造URL**：Twist没有此URL |
| 6-13 | 合成生物+ESG产业投资新风口 | `sina.com.cn/roll/2026-06-11/doc-123456.shtml` | **404编造URL**：doc-123456是占位符 |
| 6-13 | SynBioBeta 2026亮点 | `synbiobeta.com/read/2026-06-10` | **404编造URL**：SynBioBeta没有此URL |
| 6-13 | 中科院深圳先进院SYMPLEX上线 | `siat.ac.cn/news/2026-06-07` | **404编造URL**：该网站无此路径 |
| 6-13 | 中国生物工程学会白皮书 | `csb.org.cn/news/2026-06-06` | **404编造URL**：学会网站无此路径 |
| 6-13 | 合成生物学中的人工智能 | `nature.com/articles/s41586-026-02177-4` | **重复URL错误使用**：此URL也被用于"豆类自然共生移植到谷物" |

### P1 级（内容可疑）：无法验证或部分失实

| 日期 | 标题 | 问题 |
|------|------|------|
| 6-12 | 欧盟Biotech Act II征求意见 | 与第一条共用同一个聚合页URL，无法对应 |
| 6-16 | 无锡合成生物产业化园区招标 | 页面内容为空，无法验证 |
| 6-14 | 工信部首批生物制造标志性产品名单 | 来源日期5-8，与6-14报告不匹配，且URL为聚合页面 |
| 6-14 | 多个微信公众号链接 | 在黑名单中，不应被收录 |

### P2 级（格式问题）

- 6月14日 approved 数据格式与其他日期完全不同
- 6月13日多个条目标记 source 为"政府公告/政策文件"但类型是 news
- 6月16日 funding 条目缺少核心字段（金额、轮次、投资方）

---

## 根本原因分析

1. **早期日期（6月12-14日）使用非标准流程**：这些日期的数据是**手工构造或模拟数据**，不是通过真实搜索-验证流程生成
2. **URL 从未被验证**：构建 raw 数据时，搜索结果的 URL 被直接复制，没有检查是否真实存在
3. **聚合页被当作文章**：搜索引擎返回的列表页、分类页、标签页被错误当作具体文章URL使用
4. **标题和URL分离**：从搜索结果中提取的标题和URL分别来自不同结果，被错误配对

---

## 防止方案

### 1. 强制 URL 真实性验证（发送前必须执行）

在 `build_approved_from_raw` 中增加 URL 验证步骤：

- 对每个 approved item 的 URL 发送 HEAD 请求
- 404/403/500 的 URL 直接 reject
- 聚合页 URL（匹配 URL_CATEGORY_BLACKLIST）直接 reject
- 验证失败写入 rejected 日志，明确标注原因

### 2. 标题-内容一致性抽样检查

对高价值条目（score > 10 的 news/research），用 fetch 获取实际内容：
- 检查页面标题是否包含核心关键词
- 检查页面内容是否包含条目标题中的关键词
- 匹配度低于阈值（如30%）则 reject

### 3. 禁止已知聚合域名作为信息源

扩展 DOMAIN_BLACKLIST：
- `vegconomist.com/category/*`
- `technologynetworks.com/topic-hub/*`
- `ithome.com/tags/*`
- `*.mp.weixin.qq.com/s`（文章页面可以，但需验证）
- 任何包含 `?searchKey=` 的 URL

### 4. 科学期刊 URL 格式验证

Nature/Science 文章 URL 必须符合 DOI 格式：
- `nature.com/articles/s41586-YYYY-NNNNN-N` 或类似
- 同一 URL 不能被用于两个不同标题

### 5. 数据溯源标记

每个 approved item 必须记录：
- `source_round`: 哪一轮搜索发现的
- `search_query`: 具体使用的搜索关键词
- `url_verified`: URL 验证通过时间戳
- `title_match_score`: 标题与内容匹配度得分

### 6. 发送前人工抽检机制

当 approved 数量 > 5 时，自动抽取 2-3 条最高分和最低分条目：
- 输出验证报告
- 包含 URL 可访问性、标题匹配度、内容摘要对比
- 如果验证报告中有 P0 级问题，阻断发送
