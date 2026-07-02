# 合成生物日报流水线 - 全面代码审计报告

**审计对象**: `scripts/report_pipeline.py` (1067行)  
**审计日期**: 2026-06-11  
**审计结论**: 发现 **3个严重缺陷**、**5个中等风险**、**4个轻微问题**。其中2个严重缺陷可能导致去重/时效性机制失效，建议立即修复。

---

## 一、严重缺陷（立即修复）

### 🔴 缺陷1: `is_duplicate()` 公司匹配逻辑存在空值穿透漏洞

**位置**: line 256-259  
**代码**:
```python
if company and existing_company and company == existing_company:
    if event_type == existing_type or not event_type or not existing_type:
        return True, f"公司重复: ..."
```

**问题**: 当 `event_type` 为空字符串（新数据未标注类型）时，`not event_type` 为 `True`，条件直接成立。这意味着：
- 如果历史库中有一条 `existing_type="funding"` 的绿色康成记录
- 新数据是 `type="news"` 的绿色康成（或type为空）
- 会被**错误判定为重复**，导致合法新闻被过滤

**修复建议**:
```python
if company and existing_company and company == existing_company:
    # 只有当双方type都明确且相同时，才判定为公司重复
    if event_type and existing_type and event_type == existing_type:
        return True, f"公司重复: ..."
    # 如果type不明确，降级为标题相似度检查，不直接判定重复
```

**影响**: 高。可能导致不同板块的公司信息被错误去重。

---

### 🔴 缺陷2: `calculate_value_score()` 金额正则表达式逻辑错误

**位置**: line 321  
**代码**:
```python
if re.search(r'\d+\.?\d*\s*[亿万元美元]', summary):
    score += VALUE_WEIGHTS["completeness"] * 2
```

**问题**: `[亿万元美元]` 是**字符类**，不是字符串匹配。它匹配"亿"、"万"、"元"、"美"、"元"中的**单个字符**。
- "1亿美元" → 匹配到 "1美"（"美"在字符类中），但"元"未被匹配
- "10亿元" → 匹配到 "10亿"，正确
- "500万元" → 匹配到 "500万"，正确
- "1000美元" → 匹配到 "1000美"，"元"丢失

**后果**: 含"美元"的金额信息无法获得完整性加分，可能导致美元融资事件价值评分偏低，排序靠后甚至被截断。

**修复建议**:
```python
if re.search(r'\d+\.?\d*\s*(?:亿|万)?(?:元|美元|欧元|英镑)', summary):
    score += VALUE_WEIGHTS["completeness"] * 2
```

---

### 🔴 缺陷3: `validate_report_structure()` 空白板块检测失效（中文字符误判）

**位置**: line 643-644  
**代码**:
```python
if re.search(r'暂无|本周期暂无|color:#888|—\s*—\s*—', section_text) and not re.search(r'\w{10,}', section_text):
    blank_sections.append(section_name)
```

**问题**: `\w{10,}` 只匹配 `[a-zA-Z0-9_]`，**不匹配中文字符**。如果板块内容是纯中文（如"本周期暂无相关新信息收录"），`\w{10,}` 匹配结果为0，条件成立，被误判为空白板块。

**后果**: 产生大量虚假警告，干扰判断。

**修复建议**:
```python
# 匹配至少10个字符（包括中文）
has_content = len(re.findall(r'[\u4e00-\u9fff]|[a-zA-Z0-9]', section_text)) >= 10
if re.search(r'暂无|本周期暂无|color:#888|—\s*—\s*—', section_text) and not has_content:
    blank_sections.append(section_name)
```

---

## 二、中等风险（建议修复）

### 🟡 风险4: `validate_timeliness_in_report()` 表格日期提取正则覆盖不全

**位置**: line 669-682  
**代码**:
```python
date_patterns = [
    r'\|([^|]+)\|([^|]+)\|(\d{4}-\d{2}-\d{2})\|',
    r'\|([^|]+)\|([^|]+)\|([^|]+)\|(\d{4}-\d{2}-\d{2})\|',
]
```

**问题**: 
- 新闻表格是5列（标题|来源|时间|摘要|链接），第一个模式只能匹配3列+日期，会漏掉
- 研究成果表格是4列（标题|期刊|发现|链接），没有独立的日期列，会被错误匹配
- 融资表格是5列（公司|轮次|金额|投资方|链接），日期在"轮次"或"金额"列？实际上融资表格通常没有日期列

**后果**: 时效性验证可能漏检大量过期信息，或产生误报。

**修复建议**: 按板块类型分别定义表格结构，精确提取日期列。

---

### 🟡 风险5: `generate_fingerprint()` 截断碰撞风险

**位置**: line 120  
**代码**:
```python
fingerprint_text = f"{company}|{event_type}|{title[:50]}"
```

**问题**: 两个不同事件如果前50字符相同（如长标题的前缀相同），会产生相同指纹。

**案例**:
- "绿色康成完成亿元Pre-A轮融资用于技术研发"
- "绿色康成完成亿元Pre-A轮融资用于市场拓展"
前50字符完全相同，指纹相同，会被误判为同一事件。

**修复建议**:
```python
# 使用完整标题，或增加更多区分字段
fingerprint_text = f"{company}|{event_type}|{title}|{item.get('source', '')}"
# 如果担心哈希长度，可以缩短哈希输出，但输入信息要完整
return hashlib.md5(fingerprint_text.encode('utf-8')).hexdigest()[:16]
```

---

### 🟡 风险6: `load_historical_events()` 非报告文件混入

**位置**: line 193-197  
**代码**:
```python
report_files = sorted(
    glob.glob(str(REPORTS_DIR / "*.md")),
    key=os.path.getmtime,
    reverse=True
)
```

**问题**: 如果 `reports/` 目录下存在模板文件（如 `template.md`）、备份文件（如 `2026-06-11_backup.md`），也会被加载到历史库中。

**后果**: 模板中的示例数据（如"示例公司"）可能污染指纹库，导致真实数据被误判为重复。

**修复建议**:
```python
report_files = sorted(
    [f for f in glob.glob(str(REPORTS_DIR / "*.md")) 
     if re.search(r'\d{4}-\d{2}-\d{2}', os.path.basename(f))],
    key=os.path.getmtime,
    reverse=True
)
```

---

### 🟡 风险7: `check_timeliness()` 活动过期判断过于严格

**位置**: line 290-291  
**代码**:
```python
if item_date < datetime.now():
    return False, f"活动已过期 ({date_str})"
```

**问题**: 如果活动是今天（2026-06-11）但当前时间是上午9点，而活动开始时间是下午2点，`item_date`（如果只含日期，默认00:00:00）< `datetime.now()`（09:00:00），会被判定为"已过期"。

**后果**: 当天活动被错误过滤。

**修复建议**:
```python
# 活动只比较日期，不比较时间
today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
item_day = item_date.replace(hour=0, minute=0, second=0, microsecond=0)
if item_day < today:
    return False, f"活动已过期 ({date_str})"
```

---

### 🟡 风险8: `validate_report_structure()` 日期标注检查只支持全角括号

**位置**: line 534  
**代码**:
```python
date_annotations = re.findall(r'\（\d{4}-\d{2}-\d{2}\）', summary_text)
```

**问题**: 只匹配全角括号 `（）`，如果报告使用半角括号 `()`，检测不到。

**修复建议**:
```python
date_annotations = re.findall(r'[\(\（]\d{4}-\d{2}-\d{2}[\)\）]', summary_text)
```

---

## 三、轻微问题（可选优化）

### 🟢 问题9: 多个函数使用裸 `except`

**位置**: line 106, 236, 544, 573, 600, 977  
**代码示例**:
```python
try:
    ...
except:
    pass
```

**问题**: 裸except会捕获所有异常（包括KeyboardInterrupt、SystemExit），可能隐藏真正的bug。

**修复建议**: 使用具体异常类型，如 `except (ValueError, TypeError):` 或 `except Exception as e:` 并记录日志。

---

### 🟢 问题10: `calculate_value_score()` 影响力关键词前导空格

**位置**: line 340-341  
**代码**:
```python
impact_keywords = ["融资", "并购", "上市", "获批", "突破", " Nature", " Science", 
                   "政策", "法规", "规划", "亿元", "亿美元", "FDA", "GRAS"]
```

**问题**: `" Nature"` 和 `" Science"` 带有前导空格。如果标题是"Nature Biotechnology"（N前面没有空格），不会匹配。

**修复建议**: 去掉前导空格，在匹配时统一转小写并做单词边界检查。

---

### 🟢 问题11: `run_full_validation()` 未纳入MIME类型检查

**位置**: line 920-968  
**问题**: `validate_email_mime_type()` 函数已定义但从未被 `run_full_validation()` 调用，MIME类型检查游离在完整验证流程之外。

**修复建议**: 在 `run_full_validation()` 中增加MIME类型验证步骤。

---

### 🟢 问题12: `extract_events_from_report()` 表格分隔符"—"未被过滤

**位置**: line 162  
**代码**:
```python
if title and title != "标题" and not title.startswith("-") and title != "公司":
```

**问题**: `title.startswith("-")` 过滤的是半角连字符 `-`，但Markdown表格分隔行通常使用全角破折号 `—`（em dash）或重复符号 `------`。如果表格使用 `| — | — | — |` 作为分隔行，`—` 不以 `-` 开头，会被提取为有效事件。

**后果**: 指纹库中混入无效条目 `"—"`，可能干扰去重。

**修复建议**:
```python
if (title and title not in ("标题", "公司", "—", "---") 
    and not title.startswith("-") 
    and not title.startswith("—")):
```

---

## 四、审计结论与修复优先级

| 优先级 | 缺陷 | 影响 | 修复工作量 |
|--------|------|------|-----------|
| **P0** | 缺陷1: `is_duplicate()` 空type穿透 | 去重误判，可能过滤合法信息 | 2行 |
| **P0** | 缺陷2: 金额正则表达式错误 | 美元融资评分偏低 | 1行 |
| **P0** | 缺陷3: 空白板块检测失效 | 虚假警告干扰判断 | 2行 |
| **P1** | 风险4: 时效性验证正则覆盖不全 | 漏检过期信息 | 10行 |
| **P1** | 风险5: 指纹截断碰撞 | 不同事件误判重复 | 1行 |
| **P1** | 风险6: 非报告文件混入 | 模板数据污染指纹库 | 2行 |
| **P1** | 风险7: 活动当天被过滤 | 当天活动丢失 | 2行 |
| **P1** | 风险8: 日期标注括号类型 | 格式验证误报 | 1行 |
| **P2** | 问题9-12 | 代码健壮性 | 5行 |

**总体评估**: 当前规则框架设计合理，但存在 **3个可导致功能失效的代码级bug**。修复后，去重、时效性、验证三大核心机制可达到生产环境可靠性要求。

**建议**: 立即修复P0缺陷（共5行代码），重新运行6月11日报验证，确认去重和评分机制完全正确。
