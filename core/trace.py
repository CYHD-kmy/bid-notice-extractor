"""结构化追溯日志。

竞赛要求「完整记录文件访问、工具调用、计算过程和结果生成情况」。
本模块把每类操作落成一行 JSON（JSONL），事件类型集中在 TraceEvent 枚举中，
便于评审按类别核对完整性。

设计要点：
  · 每条事件带 UTC 时间戳与序号，可重建执行顺序
  · 事件类型显式枚举，避免出现"自由格式日志"
  · 不写业务数据到日志之外的地方（日志本身即可独立审阅）
"""
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any


class TraceEvent(str, Enum):
    """全部可追溯事件类型（评审可按此清单逐项核对）。"""

    # —— 文件与数据访问 ——
    FILE_READ = "file_read"
    PDF_PAGE_PARSED = "pdf_page_parsed"
    TABLE_PARSED = "table_parsed"
    RECORDED_EXTRACTIONS_READ = "recorded_extractions_read"

    # —— 检索 ——
    RETRIEVE_QUERY = "retrieve_query"

    # —— 模型调用 ——
    MODEL_CALL_STARTED = "model_call_started"
    MODEL_CALL_FINISHED = "model_call_finished"

    # —— 工具调用 ——
    TOOL_CALLED = "tool_called"
    TOOL_FAILED = "tool_failed"

    # —— 计算过程 ——
    CALCULATION_PERFORMED = "calculation_performed"
    CALCULATION_BLOCKED = "calculation_blocked"

    # —— 断言与核验 ——
    ASSERTION_CREATED = "assertion_created"
    ASSERTION_REJECTED = "assertion_rejected"
    RECORD_VALIDATED = "record_validated"

    # —— 结果生成 ——
    REPORT_GENERATED = "report_generated"
    OUTPUTS_WRITTEN = "outputs_written"

    # —— 评测与运行状态 ——
    EVALUATION = "evaluation"
    RUN_STARTED = "run_started"
    RUN_FAILED = "run_failed"
    RUN_FINISHED = "run_finished"


class Trace:
    """JSONL 追溯日志写入器（线程安全）。

    与原 prototype/run_demo.py 里的 Trace 保持相同的文件格式与路径约定
    （<out>/trace.jsonl），因此旧输出可继续被工具消费。
    """

    def __init__(self, out_dir: Path, filename: str = "trace.jsonl",
                 truncate: bool = True) -> None:
        self.path = Path(out_dir) / filename
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if truncate:
            self.path.write_text("", encoding="utf-8")
        self._seq = 0
        self._lock = threading.Lock()

    def log(self, operation: TraceEvent | str, **details: Any) -> dict:
        """写一条事件。返回写入的字典，便于调用方复用。"""
        with self._lock:
            self._seq += 1
            row = {
                "seq": self._seq,
                "time": datetime.now(timezone.utc).isoformat(),
                "operation": operation.value if isinstance(operation, TraceEvent) else str(operation),
            }
            row.update(_jsonable(details))
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
            return row

    # ---------------------------------------------------------------- 便捷方法
    def tool_called(self, tool: str, **kw) -> dict:
        return self.log(TraceEvent.TOOL_CALLED, tool=tool, **kw)

    def tool_failed(self, tool: str, error: str, **kw) -> dict:
        return self.log(TraceEvent.TOOL_FAILED, tool=tool, error=error, **kw)

    def calculation(self, calc) -> dict:
        """记录的是一条 Calculation（core.models）。"""
        ev = TraceEvent.CALCULATION_PERFORMED if calc.is_valid else TraceEvent.CALCULATION_BLOCKED
        return self.log(
            ev,
            calc_id=calc.calc_id,
            op=calc.op.value,
            operands=[{"label": o.label,
                       "value": None if o.value is None else str(o.value),
                       "unit": o.unit, "source": o.source} for o in calc.operands],
            result=None if calc.result is None else str(calc.result),
            result_unit=calc.result_unit,
            rounding=calc.rounding,
            trace_note=calc.trace_note,
            status=calc.status.value,
            reason=calc.reason,
        )

    def assertion_created(self, a) -> dict:
        return self.log(TraceEvent.ASSERTION_CREATED, assertion_id=a.assertion_id,
                        kind=a.kind.value, text=a.text,
                        evidence_count=len(a.evidence),
                        calculations=list(a.calculations),
                        confidence=a.confidence.value)

    def assertion_rejected(self, a) -> dict:
        return self.log(TraceEvent.ASSERTION_REJECTED, assertion_id=a.assertion_id,
                        kind=a.kind.value, issues=list(a.issues))

    def counts(self) -> dict[str, int]:
        """统计各类事件条数（用于报告里的可追溯性说明）。"""
        out: dict[str, int] = {}
        if not self.path.exists():
            return out
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                op = json.loads(line).get("operation", "?")
            except json.JSONDecodeError:
                continue
            out[op] = out.get(op, 0) + 1
        return out


def _jsonable(value: Any) -> Any:
    """把不可 JSON 序列化的值转成可序列化形式。"""
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Path):
        return value.as_posix()
    if hasattr(value, "to_dict"):
        return _jsonable(value.to_dict())
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)
