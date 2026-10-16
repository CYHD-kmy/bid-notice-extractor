"""技能基类：定义技能的统一接口与可审计性要求。

每个技能必须：
  · 声明 name 与 description（供 registry 展示，评审可查看"有哪些能力"）
  · 声明 uses_tools / uses_prompts（说明依赖，便于追溯）
  · run() 只做一件事，返回 SkillResult
  · 出错不吞：抛异常或返回 status=rejected，由编排层决定是否继续
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.models import ReviewStatus
from core.trace import Trace, TraceEvent


@dataclass
class SkillResult:
    """技能执行结果。"""
    skill: str
    status: ReviewStatus = ReviewStatus.VALID
    payload: Any = None
    issues: list[str] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status == ReviewStatus.VALID


class Skill:
    """技能基类。"""

    #: 技能名（英文短名，用于日志与 registry）
    name: str = "skill"
    #: 中文说明（供评审阅读）
    description: str = ""
    #: 依赖的工具名
    uses_tools: tuple[str, ...] = ()
    #: 依赖的提示词名（外置提示词）
    uses_prompts: tuple[str, ...] = ()

    def __init__(self, trace: Trace | None = None) -> None:
        self.trace = trace

    # ------------------------------------------------------------------ 供子类实现
    def run(self, *args, **kwargs) -> SkillResult:      # pragma: no cover - 抽象
        raise NotImplementedError

    # ------------------------------------------------------------------ 通用工具
    def _log_start(self, **details) -> None:
        if self.trace is not None:
            self.trace.log(TraceEvent.TOOL_CALLED, tool=f"skill:{self.name}",
                           phase="start", **details)

    def _log_end(self, result: SkillResult) -> SkillResult:
        if self.trace is not None:
            self.trace.log(TraceEvent.TOOL_CALLED, tool=f"skill:{self.name}",
                           phase="end", status=result.status.value,
                           issues=len(result.issues), **result.metrics)
        return result

    def describe(self) -> dict:
        """技能自述（写进 registry 输出，供评审核对能力清单）。"""
        return {
            "name": self.name,
            "description": self.description,
            "uses_tools": list(self.uses_tools),
            "uses_prompts": list(self.uses_prompts),
        }
