"""技能与工具注册表：让评审能一眼看到"这个系统有哪些能力"。

竞赛对应条款：
  「参赛作品须同步提交…包括智能体编排框架、Tool、Prompt、Skill、MCP…等核心模块」
  注册表的输出（registry.json）即是这份能力清单的可核验形式。
"""
from __future__ import annotations

from core.config import DEFAULT, Config

from prompts import AVAILABLE as PROMPT_FILES
from prompts import digest as prompt_digest
from skills import (
    BidNoticeExtractionSkill, ConsistencyCheckSkill,
    ReportAssemblySkill, TableStructuringSkill,
)

#: 已实现的技能（类 -> 展示用）
SKILLS = (BidNoticeExtractionSkill, ConsistencyCheckSkill,
          TableStructuringSkill, ReportAssemblySkill)

#: 已实现的工具（名 -> 说明）。新工具在此登记，供 registry 输出。
TOOLS: dict[str, str] = {
    "evidence": "字段值回溯到原文页码与坐标（逐字引文 + bbox）",
    "calculate": "单位换算 / 比率 / 占比 / 同比 / 环比；全程 Decimal，每步留痕",
    "assertion": "构造与校验事实/推论/观点三类断言，强制证据与依据",
    "table_extract": "PDF 表格结构解析，单元格带坐标证据与表头置信度",
    "report": "七节分析报告生成（Markdown + JSON），拦截无证据的事实",
}

#: 不依赖模型的核心能力（便于评审理解"哪些是确定性逻辑"）
DETERMINISTIC_TOOLS = ("evidence", "calculate", "assertion", "table_extract")


def build_registry(config: Config = DEFAULT) -> dict:
    """产出能力清单：技能 / 工具 / 提示词 / 环境约束。"""
    return {
        "skills": [cls().describe() for cls in SKILLS],
        "tools": [{"name": k, "description": v,
                   "deterministic": k in DETERMINISTIC_TOOLS}
                  for k, v in sorted(TOOLS.items())],
        "prompts": [{"name": name, "file": fname, "sha256": prompt_digest(name)}
                    for name, fname in sorted(PROMPT_FILES.items())],
        "model": config.describe()["model"],
        "data_environment": config.describe()["data"],
        "calc_rules": config.describe()["calc"],
    }
