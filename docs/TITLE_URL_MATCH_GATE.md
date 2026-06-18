# 标题-URL 匹配门禁

这个门禁用于拦截一种链接健康检查挡不住的问题：URL 可以打开，也不是删除页，但采集到的标题实际指向另一篇文章或另一个活动。

生产生成 approved 时建议显式开启：

```powershell
python scripts\report_pipeline.py --build-approved data\raw_YYYY-MM-DD.json --date YYYY-MM-DD --output data --check-url-health --check-title-match --strict-search-coverage --search-log data\search_log_YYYY-MM-DD.json
```

## 检查内容

- 使用 `GET` 读取页面，而不是只做 `HEAD`。
- 解析 `<meta property="og:title">`、`<meta name="twitter:title">`、`<title>` 和首个 `<h1>`。
- 用归一化标题和中文 n-gram token 重叠度比较 raw 标题与页面标题信号。
- 只拒绝明确的标题不匹配。
- 网络、SSL、解析失败只记录 warning，不作为标题匹配门禁的 blocking error。

## 不替代的门禁

- `--check-url-health` 仍负责拦截 404、超时、不安全 URL 和疑似删除页。
- send gate 仍会在 SMTP 前检查 H5、邮件正文和 Markdown 附件中的最终外链。
- approved URL 一致性仍负责确认报告和邮件中的链接都来自 approved 数据。

## 为什么不是默认强开

标题匹配需要实时读取网页，且不同站点的标题格式差异很大。如果无条件开启，会让本地测试、受限代理环境和临时网络故障变得不稳定。生产运行和手动补发前重建 approved 时应与 `--check-url-health` 一起开启；自动化测试应注入假的 `title_check_func`。

## 对 Kimi 审计建议的处理

- 采纳“标题-URL 匹配验证”作为关键防线。
- 不采纳全局 `mp.weixin.qq.com` 黑名单。微信公众号可以是具体文章页，不能因域名一刀切拒绝；聚合页和不可访问页仍由 URL 健康检查处理。
- 不把 URL 健康检查改成默认强制网络请求。生产 SOP 要求显式传 `--check-url-health --check-title-match`，测试和离线环境保持可控。
- 不把标题匹配网络错误当作 blocking error。404、删除页、超时等仍由 URL 健康检查负责阻断；标题匹配只在读到页面标题且明显不相关时拒绝。

## 推荐策略

- 生产和手动补发前重建 approved 必须使用 `--check-title-match`。
- 标题匹配网络错误只记录 warning。
- 只有页面返回标题信号，且所有标题信号都与候选标题明显无关时才拒绝。
- 遇到反复误判时优先做来源级规则或标题阈值调整，不做粗暴域名黑名单。
