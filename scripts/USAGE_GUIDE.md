# AS hub NEWs agent - 脚本使用指南
# 本指南供Cron子Agent参考，确保正确使用report_pipeline.py

## 脚本位置
`D:\AI\合成生物行业报告\scripts\report_pipeline.py`

## 核心功能

### 1. 处理原始数据（过滤 + 去重 + 排序）

**输入**：原始信息JSON文件
**输出**：处理后的合规信息JSON文件

```python
import subprocess
import sys
import json

# 1. 将搜索到的原始信息保存为JSON
raw_data = {
    "news": [
        {"title": "...", "source": "...", "date": "2026-06-08", "summary": "...", "url": "...", "type": "news"},
        # ...
    ],
    "research": [...],
    "funding": [...],
    "policy": [...],
    "events": [...],
}

raw_path = r"D:\AI\合成生物行业报告\data\raw_2026-06-08.json"
with open(raw_path, 'w', encoding='utf-8') as f:
    json.dump(raw_data, f, ensure_ascii=False, indent=2)

# 2. 调用脚本处理每个类别
for category in ["news", "research", "funding", "policy", "events"]:
    output_path = r"D:\AI\合成生物行业报告\data\processed_{category}_2026-06-08.json"
    result = subprocess.run(
        [sys.executable, r"D:\AI\合成生物行业报告\scripts\report_pipeline.py",
         "--process", raw_path,
         "--type", category,
         "--output", output_path],
        capture_output=True, text=True
    )
    
    # 读取处理结果
    with open(output_path, 'r', encoding='utf-8') as f:
        processed = json.load(f)
    
    approved_items = processed["approved"]  # 通过审核的信息
    rejected_items = processed["rejected"]   # 被拒绝的信息及原因
    stats = processed["stats"]               # 统计信息
```

### 2. 验证报告（结构 + 时效性）

**输入**：生成的报告Markdown文件
**输出**：验证结果JSON文件

```python
import subprocess
import sys
import json

report_path = r"D:\AI\合成生物行业报告\reports\2026-06-08.md"
validation_path = r"D:\AI\合成生物行业报告\data\validation_result.json"

result = subprocess.run(
    [sys.executable, r"D:\AI\合成生物行业报告\scripts\report_pipeline.py",
     "--validate", report_path,
     "--output", validation_path],
    capture_output=True, text=True
)

with open(validation_path, 'r', encoding='utf-8') as f:
    validation = json.load(f)

# 检查结果
if validation["passed"] and validation["can_send_email"]:
    print("报告通过验证，可以发送邮件")
else:
    print(f"报告未通过验证，得分: {validation['overall_score']}")
    print("需要修复的问题:")
    for instr in validation["fix_instructions"]:
        print(f"  - {instr}")
```

## 迭代修正流程

```
生成报告 → 调用脚本验证 → 检查fix_instructions
    ↑                                    ↓
    └──── 根据fix_instructions修正 ─────┘
         （最多迭代3次）
```

**迭代规则**：
1. 第一次生成报告后，立即调用脚本验证
2. 如果 `passed = false` 或 `can_send_email = false`，根据 `fix_instructions` 修正报告
3. 修正后再次验证
4. 最多迭代3次，如果仍不通过，记录错误并跳过邮件发送

## 关键检查点

### 检查点0：信息源全面搜索（四轮搜索法，严禁遗漏）

**第一轮：通用关键词搜索**
- 使用中文关键词：合成生物、合成生物学、生物制造
- 使用英文关键词：synthetic biology, biomanufacturing

**第二轮：site:限定符定向搜索（必须逐个执行）**
- 国内源（7个）：`site:36kr.com 合成生物`、`site:pedaily.cn 合成生物 融资`、`site:vbdata.cn 合成生物`、`site:bydrug.pharmcube.com 合成生物`、`site:bioon.com 合成生物`、`site:synbio-he.com 合成生物`、`site:stdaily.com 合成生物`
- 国际源（6个）：`site:synbiobeta.com synthetic biology`、`site:genengnews.com synthetic biology`、`site:fiercebiotech.com synthetic biology`、`site:labiotech.eu synthetic biology`、`site:crisprmedicinenews.com CRISPR`

**第三轮：英文关键词补充搜索**
- `synthetic biology news today`
- `biomanufacturing funding 2026`
- `precision fermentation breakthrough`
- `cell factory engineering`

**第四轮：报告生成前复查**
- 重点检查投资界、36氪、动脉网、科技日报等高频更新源
- 确认今日/本周无新信息发布
- 如发现有遗漏，立即补充收录

**第五轮：空白板块强制补搜（新增，防止遗漏）**

如果某板块在四轮搜索后仍为空，必须执行定向补搜：

| 空白板块 | 强制补搜关键词 | 必查来源 |
|---------|-------------|---------|
| **政策板块为空** | `site:kw.beijing.gov.cn 合成生物`、`site:stic.sz.gov.cn 合成生物`、`site:sh.gov.cn 合成生物`、`site:sciencenet.cn 征集 合成生物`、`site:sohu.com 合成生物 政策 征集` | 北京市科委、深圳市科创委、上海市经信委、科学网政策频道 |
| **活动板块为空** | `SEED 2026 synthetic biology`、`site:synbioconference.org`、`site:scientificwisdom.org 合成生物`、`site:europabio.org event`、`site:academicx.org 合成生物` | AIChE/SBE、EuropaBio、学术会议网 |
| **研究板块为空** | `site:nature.com synthetic biology`、`site:science.org synthetic biology`、`site:cell.com synthetic biology`、`site:biorxiv.org synthetic biology` | Nature、Science、Cell、bioRxiv |
| **融资板块为空** | `site:pedaily.cn 合成生物 融资 2026`、`site:36kr.com 合成生物 融资`、`site:vbdata.cn 合成生物 融资` | 投资界、36氪、动脉网 |

**⚠️ 信息源遗漏陷阱**：
- 只搜通用关键词 → 遗漏垂直媒体独家信息
- 只搜一次不复查 → 错过下午发布的新信息
- 只搜中文不搜英文 → 错过国际重要动态
- **政策只搜"政策"二字 → 遗漏"征集""申报""储备课题"等行政术语**
- **会议只搜"会议"二字 → 遗漏英文会议名如SEED、SynBioBeta等**

### 检查点1：信息处理阶段
- [ ] 原始信息已保存为JSON
- [ ] 每个类别已调用脚本处理
- [ ] 已查看被拒绝的信息及原因
- [ ] 只使用 `approved` 列表中的信息生成报告

### 检查点2：报告生成阶段
- [ ] 严格使用模板 `templates/daily_report_template.md`
- [ ] 只包含脚本输出的合规信息
- [ ] 执行摘要精选5条最有价值的信息
- [ ] **空白板块检查**：如政策/研究/活动/融资板块为空，必须确认已执行第五轮定向补搜，并在报告中注明"经全面检索，本周期暂无新信息"，而非直接留空

### 检查点3：验证阶段
- [ ] 报告生成后立即调用脚本验证
- [ ] 检查 `validation["passed"]` 是否为 true
- [ ] 检查 `validation["can_send_email"]` 是否为 true
- [ ] 检查 `validation["overall_score"]` 是否 >= 80

### 检查点4：迭代修正
- [ ] 如有fix_instructions，逐项修正
- [ ] 修正后重新验证
- [ ] 最多迭代3次

### 检查点5：邮件发送
- [ ] 验证通过后，才生成HTML并发送邮件
- [ ] **邮件附件MIME类型必须正确**：
  - HTML附件：`MIMEText(html_content, 'html', 'utf-8')` → MIME类型 `text/html`
  - Markdown附件：`MIMEText(md_content, 'plain', 'utf-8')` → MIME类型 `text/plain`
  - **严禁使用 `MIMEBase('application', 'octet-stream')`**（会导致附件变成.bin文件）
- [ ] 邮件必须附带HTML附件
- [ ] 发送失败重试一次

**⚠️ 邮件附件MIME类型陷阱**：
- 使用 `MIMEBase('application', 'octet-stream')` → QQ邮箱显示为 `.bin` 文件
- 正确做法：HTML用 `MIMEText(content, 'html', 'utf-8')`，MD用 `MIMEText(content, 'plain', 'utf-8')`

## 注意事项

1. **不要跳过脚本验证直接发送邮件** — 这是强制步骤
2. **不要忽略fix_instructions** — 每个指令都必须处理
3. **不要使用被拒绝的信息** — 只使用approved列表
4. **保留处理日志** — 被拒绝的信息和验证结果保存到data目录，便于审计
5. **信息源搜索必须执行四轮** — 通用搜索 → site:定向搜索 → 英文补充搜索 → 生成前复查
6. **邮件附件MIME类型必须正确** — HTML用text/html，MD用text/plain，严禁用octet-stream

## 文件命名规范

- 原始数据：`data/raw_YYYY-MM-DD.json`
- 处理后数据：`data/processed_{category}_YYYY-MM-DD.json`
- 验证结果：`data/validation_result.json` 或 `data/validation_YYYY-MM-DD.json`
- 拒绝日志：`data/rejected_YYYY-MM-DD.json`

---

*指南版本：v1.1*
*更新日期：2026-06-08*
*更新内容：新增信息源四轮搜索法 + 邮件附件MIME类型检查*
