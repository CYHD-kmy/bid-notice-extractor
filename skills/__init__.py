"""skills 包：技能层 = Prompt + Tool 的组合编排。

与 tools/ 的区别：
  · tools/   单个原子操作（算一次数、定位一次证据、解析一张表）
  · skills/  一个完整业务任务（把"中标公告 → 结构化字段 + 计算 + 断言"串起来）

竞赛对应条款：
  「参赛作品须同步提交…包括智能体编排框架、Tool、Prompt、Skill…等核心模块」
"""
from .base import Skill, SkillResult
from .bid_notice_extraction import BidNoticeExtractionSkill
from .consistency_check import ConsistencyCheckSkill
from .report_assembly import ReportAssemblySkill
from .table_structuring import TableStructuringSkill

__all__ = [
    "Skill", "SkillResult",
    "BidNoticeExtractionSkill", "ConsistencyCheckSkill",
    "TableStructuringSkill", "ReportAssemblySkill",
]
