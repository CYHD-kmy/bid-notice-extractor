"""evaluation 包：确定性处理与可追溯性的评测。

  metrics.py    计算自洽性 / 证据可核验性 / 报告完整性
  stability.py  回放稳定性（N 次运行一致性）

**诚实边界**：本包评测的是**确定性处理链路**，不评测模型输出质量。
样本为合成数据，指标不能外推到真实公告。
"""
from .metrics import (
    REQUIRED_SECTIONS, evaluate_calculations, evaluate_evidence,
    evaluate_report, evaluate_run,
)

__all__ = [
    "evaluate_run", "evaluate_calculations", "evaluate_evidence",
    "evaluate_report", "REQUIRED_SECTIONS",
]
