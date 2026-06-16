import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import ai_analysis_check


def test_ai_analysis_allows_numbers_grounded_in_body():
    result = ai_analysis_check.validate_ai_analysis(str(ROOT / "tests" / "fixtures" / "valid_report.md"))
    assert not result["has_errors"]


def test_ai_analysis_blocks_ungrounded_entity_and_number():
    result = ai_analysis_check.validate_ai_analysis(str(ROOT / "tests" / "fixtures" / "invalid_ai_report.md"))
    assert result["has_errors"]
    assert any("未来科技" in error for error in result["errors"])
    assert any("143家" in error for error in result["errors"])


def test_ai_analysis_cli_exits_nonzero_on_errors():
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "ai_analysis_check.py"),
            "--report",
            str(ROOT / "tests" / "fixtures" / "invalid_ai_report.md"),
        ],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
    )
    assert result.returncode == 1


def test_ai_analysis_does_not_flag_descriptive_chinese_phrases(tmp_path):
    report = tmp_path / "report.md"
    report.write_text(
        """
# 合成生物行业日报

## 📌 执行摘要

1. 沃森生物合成生物制造业务正式投产（2026-06-11）

## 📰 行业热点新闻

| 标题 | 来源 | 时间 | 摘要 | 链接 |
|---|---|---|---|---|
| 沃森生物合成生物制造业务正式投产 | 公司公告 | 2026-06-11 | 安宁基地完成产品交付。 | https://example.com/watson |

## 🔬 最新研究成果

经五轮检索，本周期暂无相关新信息收录。

## 💰 融资与投资动态

经五轮检索，本周期暂无相关新信息收录。

## 🏛️ 政策与监管

### 国内政策

经五轮检索，本周期暂无相关新信息收录。

### 国际监管动态

经五轮检索，本周期暂无相关新信息收录。

## 📅 行业活动预告

经五轮检索，本周期暂无相关新信息收录。

## 🤖 AI 深度分析

### 趋势研判

沃森生物的投产说明传统医药企业正在向生物制造延伸，后续生物制造产能释放值得关注，重大科技成果转化仍需验证，链接健康、分类一致性和去重门禁需要持续检查。

### 竞争格局变化

该企业在产业化端具备示范意义。

### 风险提示

商业化节奏仍需观察。

## 📎 附录

- https://example.com/watson
""".strip(),
        encoding="utf-8",
    )

    result = ai_analysis_check.validate_ai_analysis(str(report))

    assert not result["has_errors"], result["errors"]
    assert "沃森生物" in result["verified"]
