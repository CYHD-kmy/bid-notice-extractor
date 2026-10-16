"""tools 包：可审计的原子操作层。

每个工具都：
  · 只做一件事
  · 把调用落进 trace（tool_called）
  · 输入输出均为 core.models 里的数据结构（带证据）
"""
from .assertion_tool import (
    FIELD_LABELS, AssertionTool, amount_fact, facts_from_record,
)
from .calculate_tool import CalculationTool, UNIT_FACTORS, operand_from_amount
from .report_tool import (
    RecordView, ReportContext, ReportError, ReportTool, sha256_file,
)

__all__ = [
    "AssertionTool", "FIELD_LABELS", "facts_from_record", "amount_fact",
    "CalculationTool", "UNIT_FACTORS", "operand_from_amount",
    "ReportTool", "ReportContext", "RecordView", "ReportError", "sha256_file",
]