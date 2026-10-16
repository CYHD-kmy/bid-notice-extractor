"""agent 包：智能体编排层。

  registry.py      技能/工具/提示词能力清单（评审可核验"有哪些能力"）
  orchestrator.py  流水线编排：输入 → 抽取 → 计算 → 核验 → 报告 → 落盘

注意：本文件**不做 eager import**，否则 `python -m agent.orchestrator`
会触发 "found in sys.modules after import of package" 警告并以非 0 退出。
需要便捷入口时用下面的 __getattr__ 惰性加载。
"""
from __future__ import annotations

__all__ = ["build_registry", "run", "RunState", "load_recorded_extractions"]


def __getattr__(name: str):
    """惰性导出（PEP 562）。"""
    if name == "build_registry":
        from .registry import build_registry
        return build_registry
    if name in ("run", "RunState", "load_recorded_extractions"):
        from . import orchestrator
        return getattr(orchestrator, name)
    raise AttributeError(f"module 'agent' has no attribute {name!r}")
