# 脚本使用指南

## report_pipeline.py

### 功能概述

`report_pipeline.py` 是 AS hub 合成生物行业日报的核心处理脚本，负责：

1. **历史事件指纹提取与去重**
2. **时效性过滤**
3. **信息聚合与价值排序**
4. **报告格式验证**
5. **合规复检与迭代修正**
6. **邮件一致性验证**
7. **MIME类型验证**

### 使用方法

#### 1. 处理原始数据

```python
import sys
sys.path.insert(0, r"scripts")
from report_pipeline import process_raw_data

# 处理新闻类数据
result = process_raw_data(raw_news_items, "news")
print(f"通过: {result['stats']['approved']}条, 拒绝: {result['stats']['rejected']}条")

# approved 列表中的信息可用于生成报告
approved_items = result["approved"]
```

#### 2. 运行合规复检

```python
from report_pipeline import run_compliance_check

result = run_compliance_check("reports/2026-06-08.md")
print(f"通过: {result['passed']}, 可发送邮件: {result['can_send_email']}, 得分: {result['overall_score']}")

if result['fix_instructions']:
    print("需要修复:")
    for instr in result['fix_instructions']:
        print(f"  - {instr}")
```

#### 3. 验证邮件一致性

```python
from report_pipeline import validate_email_consistency

result = validate_email_consistency(email_body_html, approved_data)
print(f"一致: {result['is_consistent']}")

if result['errors']:
    print("错误:")
    for e in result['errors']:
        print(f"  - {e}")
```

#### 4. 验证MIME类型

```python
from report_pipeline import validate_email_mime_type

result = validate_email_mime_type(email_msg)
print(f"有效: {result['is_valid']}")

if result['errors']:
    print("MIME错误:")
    for e in result['errors']:
        print(f"  - {e}")
```

#### 5. 完整验证

```python
from report_pipeline import run_full_validation

result = run_full_validation(
    report_md_path="reports/2026-06-08.md",
    email_body=email_html,
    approved_data=approved_items,
    raw_stats={"total": 25, "approved": 8}
)

print(f"报告通过: {result['report_passed']}")
print(f"邮件一致: {result['email_consistent']}")
print(f"可发送: {result['can_send_email']}")
print(f"综合得分: {result['overall_score']}")
```

### 命令行使用

```bash
# 验证报告
python scripts/report_pipeline.py --validate reports/2026-06-08.md --output reports/validation.json

# 处理原始数据
python scripts/report_pipeline.py --process data/raw_2026-06-08.json --type news --output data/processed.json

# 查看统计
python scripts/report_pipeline.py
```

### 配置常量

| 常量 | 默认值 | 说明 |
|------|--------|------|
| `TIME_WINDOWS["news"]` | 7 | 新闻时效性窗口（天） |
| `TIME_WINDOWS["research"]` | 14 | 研究时效性窗口（天） |
| `TIME_WINDOWS["funding"]` | 7 | 融资时效性窗口（天） |
| `TIME_WINDOWS["policy"]` | 30 | 政策时效性窗口（天） |
| `TIME_WINDOWS["events"]` | 90 | 活动时效性窗口（天） |

### 权威来源分级

| 级别 | 来源 |
|------|------|
| Tier 1 | Nature, Science, Cell, Nature Biotechnology, Nature Communications, Science Advances, Cell Metabolism, PNAS |
| Tier 2 | GEN, FierceBiotech, SynBioBeta, 36氪, 投资界, 动脉网, 医药魔方, 科技日报, IT之家 |
| Tier 3 | 生物谷, 合成生物学网, 搜狐, 新浪, 微信 |
