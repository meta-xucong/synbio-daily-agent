# AS hub NEWs agent - 防偏差机制
# 本文件为强制规则，任何情况下不得绕过

## 核心原则

> **无论自动任务还是手动操作，必须严格执行完整流水线。**
> 
> **严禁跳过任何步骤。严禁基于搜索结果直接手写报告。**
> 
> **慢无所谓，对最重要。**

---

## 一、完整流水线（9步，缺一不可）

```
Step 1: 读取配置（数据源 + 去重规则 + 脚本指南）
Step 2: 生成 LLM 动态搜索策略，并执行 config/search_queries.json 基座 required_queries + search_strategy 动态 required queries
Step 3: 保存结构化搜索日志并自动生成raw → data/search_strategy_YYYY-MM-DD.json + data/search_log_YYYY-MM-DD.json + data/raw_YYYY-MM-DD.json
Step 4: 调用 report_pipeline.py 处理（基座/动态query覆盖审计+搜索覆盖率审计+去重+过滤+排序）
Step 5: 基于 approved 列表和 raw 计数生成Markdown报告
Step 6: 调用 report_pipeline.py 验证报告格式
Step 7: 生成H5 HTML报告
Step 8: 生成邮件正文（与H5严格一致）
Step 9: 邮件推送（send gate通过后才发送）
```

**任何情况下，Step 3→Step 4→Step 5→Step 6 必须连续执行，不得跳过。**

---

## 二、防偏差检查清单（每次生成报告前必须逐项确认）

### 检查点A：原始数据已保存
- [ ] 已创建 `data/raw_YYYY-MM-DD.json`
- [ ] 已创建 `data/search_strategy_YYYY-MM-DD.json`，并执行策略中的全部 required 动态 query
- [ ] 已创建 `data/search_log_YYYY-MM-DD.json`，覆盖 `config/search_queries.json` 中 r1-r5 全部 required query 和 LLM 动态 required query，并保留结构化搜索结果（title/url/snippet/source/date）
- [ ] 每条 required query 都记录了 `executed` 和 `results_count`；无结果时为 `executed: true, results_count: 0`，不得省略
- [ ] 已用 `--build-raw-from-search` 自动生成 raw，JSON中包含所有搜索到的信息（news/research/funding/policy/events）
- [ ] 每条信息有title/source/date/summary/url/type/source_round字段
- [ ] url字段是具体文章链接，不是网站首页

**未保存原始数据或搜索日志 → 禁止生成报告**

### 检查点B：脚本已执行
- [ ] 已调用 `report_pipeline.py` 处理每个类别
- [ ] 已执行 `scripts\audit_search_log.py --search-strategy data\search_strategy_YYYY-MM-DD.json` 或 build-approved 默认严格门禁，确认基座 required query、LLM 动态 query 和 search_log 候选 URL 没有在 raw 阶段静默丢失
- [ ] 已查看处理结果（approved/rejected数量）
- [ ] 已确认 rejected 原因（去重/时效性/政策库）
- [ ] 已保存 `data/approved_YYYY-MM-DD.json`

**未执行脚本处理 → 禁止生成报告**

### 检查点C：只使用approved数据
- [ ] 报告中的每条信息都能在 `data/approved_YYYY-MM-DD.json` 中找到
- [ ] 报告中的信息标题与approved数据中的title一致
- [ ] 报告中的链接与approved数据中的url一致
- [ ] 没有使用任何rejected列表中的信息

**发现未approved信息混入报告 → 立即删除并重新检查**

### 检查点D：报告已验证
- [ ] 已调用 `report_pipeline.py` 验证报告格式
- [ ] `passed=True` 且 `can_send_email=True`
- [ ] 得分 >= 80
- [ ] 无必须修复的fix_instructions

**验证不通过 → 禁止发送邮件，必须修正后重新验证**

### 检查点E：邮件一致性
- [ ] 邮件正文中的每条信息都在H5报告中存在
- [ ] 邮件正文中的每个链接都与H5报告中的链接一致
- [ ] 邮件正文没有H5报告中没有的信息

**邮件与H5不一致 → 禁止发送邮件**

---

## 三、常见偏差模式与对策

| 偏差模式 | 后果 | 对策 |
|---------|------|------|
| 基于搜索结果直接手写报告 | 去重失效、信息重复、格式错误 | **强制先保存JSON，再调用脚本** |
| 缺少搜索日志或 source_round | 无法证明五轮检索，旧内容可能补录混入 | **发送前 pre_check 强制阻断** |
| 省略 site: 定向查询 | 政策、会议、垂直媒体信息系统性漏采 | **config/search_queries.json + audit_search_log.py + send gate 强制阻断** |
| 跳过report_pipeline.py | 去重失效、时效性不检查、价值不排序 | **脚本执行是门禁，不执行不生成** |
| 使用rejected信息 | 重复信息、过期信息混入报告 | **只使用approved列表** |
| 跳过验证直接发送 | 格式错误、日期排序错误 | **验证不通过禁止发送** |
| 邮件自由创作不基于H5 | 邮件与报告不一致 | **邮件必须从approved+H5提取** |
| 为了快而省略步骤 | 质量下降、错误频发 | **慢无所谓，对最重要** |

---

## 四、自动化防偏差脚本

### 4.1 预检查脚本

在生成报告前，自动检查前置条件：

```python
from scripts.pre_check import pre_check

result = pre_check("YYYY-MM-DD")
assert result["can_proceed"]
```

脚本路径来自 `scripts/settings.py`，默认仓库根目录，也可用 `SYNBIO_DAILY_HOME` 覆盖。

### 4.2 报告生成后检查

```python
# scripts/post_check.py
def post_check(report_path: str, approved_path: str) -> dict:
    """报告生成后的强制检查"""
    errors = []
    
    # 读取报告和approved数据
    with open(report_path, 'r', encoding='utf-8') as f:
        report = f.read()
    with open(approved_path, 'r', encoding='utf-8') as f:
        approved = json.load(f)
    
    # 检查1: 报告中的每个链接都在approved中
    import re
    report_links = set(re.findall(r'https?://[^\s\)]+', report))
    approved_links = set()
    for item in approved:
        approved_links.add(item.get("url", ""))
        approved_links.update(item.get("urls", []))
    
    extra_links = report_links - approved_links
    if extra_links:
        errors.append(f"报告包含未approved的链接: {extra_links}")
    
    # 检查2: 报告中的每个标题都在approved中
    for item in approved:
        if item["title"] not in report and item["title"][:30] not in report:
            errors.append(f"approved信息未在报告中体现: {item['title'][:50]}")
    
    return {
        "can_send": len(errors) == 0,
        "errors": errors,
    }
```

---

## 五、报告头部追踪标记

每份报告必须在头部包含流水线追踪信息：

```markdown
# 合成生物行业日报 — 2026-06-11

> 报告生成时间：2026-06-11 09:15:00 (UTC+8)  
> 信息来源：公开网络检索  
> 覆盖维度：新闻动态、研究成果、融资投资、政策监管、行业活动  
> **流水线追踪**：原始数据=10条 → 脚本处理 → approved=6条 → 验证通过(100分) → 已发送
```

**未包含追踪标记的报告视为未经过完整流水线。**

---

## 六、手动操作特别规则

当用户要求"今天发一下""重新生成"等紧急请求时：

1. **不得跳过任何步骤**
2. **必须明确告知用户正在执行完整流程**
3. **如果某步骤失败，必须修正后才能继续**
4. **不得为了快而降低质量**

**标准回复模板**：
> "正在执行完整流水线：五轮搜索 → 保存JSON → 脚本处理（去重+过滤） → 生成报告 → 验证 → 发送邮件。预计需要X分钟，请稍候。"

---

## 七、偏差事后处理

如果发现已发送的报告存在偏差（如重复、遗漏、格式错误）：

1. **立即记录偏差原因**到 `data/deviation_log.json`
2. **分析根本原因**：是步骤跳过？还是规则理解错误？
3. **更新防偏差机制**：将新发现的偏差模式加入本文件
4. **重新生成并补发**正确版本
5. **向用户说明情况**并道歉

---

## 八、AI深度分析防幻觉规则（强制）

### 8.1 核心原则

> **AI分析只能基于正文已收录的approved信息，严禁引入任何外部知识。**

### 8.2 生成前强制步骤

在生成AI深度分析前，必须执行以下步骤：

1. **提取正文收录的所有事件标题**
   - 从新闻板块表格提取所有标题
   - 从研究成果板块表格提取所有标题
   - 从融资板块表格提取所有公司名
   - 从政策板块表格提取所有政策名称
   - 从活动板块表格提取所有活动名称

2. **构建"允许引用清单"**
   - 清单中的每个条目必须有明确的正文来源
   - 清单格式：`[板块] 标题（日期）`

3. **生成AI分析时，必须在prompt中附加以下指令**：

```
【强制约束】
你只能基于以下正文已收录的信息进行分析。严禁引入任何未在正文中出现的信息、公司、数据或事件。

允许引用的正文信息清单：
{允许引用清单}

禁止行为：
- 禁止引用未在正文中出现的公司名称（如引航生物、瑞德林、微元合成等）
- 禁止引用未在正文中出现的数据（如"143家创新企业"等）
- 禁止引用未在正文中出现的事件（如"港交所A1申请"等）
- 禁止基于训练数据中的行业常识进行推断

允许行为：
- 对正文中已收录的信息进行深度解读和趋势推断
- 基于已收录信息之间的关联进行逻辑分析
- 使用通用的行业框架（如第一/二/三梯队分类）进行组织，但每个具体案例必须来自正文

验证要求：
生成完成后，逐条检查分析内容中的每个具体事实，确认其能在正文中找到对应来源。如有无法对应的内容，立即删除。
```

### 8.3 生成后强制检查清单

AI分析生成完成后，必须逐项核对以下清单，确认无幻觉后方可发送：

#### 检查项A：公司名核对
- [ ] 逐行检查AI分析中出现的每个公司/机构名
- [ ] 确认该公司名在正文表格中出现过（新闻/融资/研究/政策/活动任一板块）
- [ ] 如果公司名未在正文中出现，**必须删除或替换为模糊表述**

**常见幻觉公司（需特别注意）**：
- 引航生物、瑞德林、微元合成、森瑞斯、桦冠生物、百雀羚
- LanzaX、SDL、Kamau Therapeutics、Anthropic
- 如果正文中未出现，AI分析中不得引用

#### 检查项B：具体事件核对
- [ ] 逐行检查AI分析中提到的每个具体事件/数据
- [ ] 确认该事件在正文表格或摘要中出现过
- [ ] 如果事件未出现，**必须删除或模糊化**

**常见幻觉事件（需特别注意）**：
- "港交所A1申请"、"143家创新企业"、"50名领军人才"
- "LanzaTech正在孵化LanzaX"、"百雀羚双擎实验室"
- 如果正文中未出现，AI分析中不得引用

#### 检查项C：数据核对
- [ ] 检查AI分析中的所有数字/数据
- [ ] 确认数据来源是正文中的某条信息
- [ ] 禁止基于训练数据中的行业常识编造数据

#### 检查项D：趋势推断边界
- [ ] 趋势推断必须基于正文中已收录的信息
- [ ] 允许使用"预计"、"有望"等模糊表述，但推断的逻辑起点必须是正文信息
- [ ] 禁止基于训练数据中的行业趋势进行推断

### 8.4 修正流程

如果AI分析检查发现问题：

1. **记录问题**：将幻觉内容记录到 `data/ai_hallucination_log.json`
2. **删除幻觉**：从AI分析中删除所有无法对应正文的具体事实
3. **重新生成**：基于正文收录的信息重新生成分析
4. **再次核对**：运行8.3检查清单，确认无幻觉
5. **通过后才允许发送邮件**

### 8.5 已发现的幻觉案例（持续更新）

| 日期 | 幻觉内容 | 正文中是否出现 | 处理方式 |
|------|---------|--------------|---------|
| 6月8日 | "安徽农业大学生物制造学院揭牌" | ❌ 未出现 | 删除 |
| 6月8日 | "SDL、Kamau Therapeutics" | ❌ 未出现 | 删除 |
| 6月9日 | "Anthropic等AI巨头" | ❌ 未出现 | 删除 |
| 6月9日 | "瑞德林、微元合成" | ❌ 未出现 | 删除 |
| 6月9日 | "森瑞斯、桦冠生物" | ❌ 未出现 | 删除 |
| 6月10日 | "引航生物递交港交所A1申请" | ❌ 未出现 | 删除 |
| 6月10日 | "LanzaTech正在孵化LanzaX" | ❌ 未出现 | 删除 |
| 6月11日 | "引航生物递交港交所A1申请" | ❌ 未出现 | 删除 |
| 6月11日 | "百雀羚双擎实验室" | ❌ 未出现 | 删除 |
| 6月11日 | "昌平区已集聚143家创新企业" | ❌ 未出现 | 删除 |

---

*版本：v1.2*
*更新日期：2026-06-11*
*新增：AI深度分析防幻觉规则 + 执行摘要日期标注强制检查*
