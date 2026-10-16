"""计算工具：把领域计算包装成可审计、可追溯的工具调用。

职责边界：
  · 本工具**只做算术**，不做字段抽取、不做判断
  · 每次调用落一条 trace 事件（tool_called），每步算术落一条 calculation_performed
  · 输入金额一律来自已带证据的字段，因此计算结果也能回溯到原文

竞赛对应条款：
  「量化计算」+「完整记录计算过程」
"""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Iterable

from core.models import (
    CalcOp, Calculation, CalculationEngine, Evidence, Operand, ReviewStatus,
    decimal_str,
)
from core.trace import Trace

# 中文单位 -> 元 的换算因子
UNIT_FACTORS: dict[str, Decimal] = {
    "元": Decimal(1),
    "千元": Decimal(1000),
    "万元": Decimal(10000),
    "亿元": Decimal(100000000),
}


class CalculationTool:
    """计算工具。持有一个 CalculationEngine，产出可审计的计算记录。"""

    name = "calculate"

    def __init__(self, trace: Trace | None = None, engine: CalculationEngine | None = None,
                 prefix: str = "C") -> None:
        self.trace = trace
        self.engine = engine or CalculationEngine(prefix=prefix)

    # ------------------------------------------------------------------ 内部
    def _after(self, calc: Calculation) -> Calculation:
        if self.trace is not None:
            self.trace.calculation(calc)
        return calc

    # ------------------------------------------------------------------ 单位换算
    def to_base_unit(self, label: str, amount: Decimal | None, unit: str,
                     source: str, evidence: Iterable[Evidence] = ()) -> Calculation:
        """把带单位的金额换算成「元」。

        这是金融场景最容易出错的一步（万元/亿元混用），因此单独留痕。
        单位未知时不猜，产出 needs_review。
        """
        ev = list(evidence)
        if self.trace is not None:
            self.trace.tool_called(tool=self.name, action="to_base_unit",
                                   label=label, amount=None if amount is None else str(amount),
                                   unit=unit, source=source)
        operand = Operand(label=label, value=amount, unit=unit, source=source, evidence=ev)
        factor = UNIT_FACTORS.get(unit)
        if factor is None:
            calc = Calculation(
                calc_id=self.engine._next_id(), op=CalcOp.UNIT_CONVERT,
                operands=[operand], result=None, result_unit="元",
                status=ReviewStatus.NEEDS_REVIEW,
                reason=f"单位「{unit or '未给出'}」不在支持范围（{'、'.join(UNIT_FACTORS)}），不换算",
                trace_note=f"[未换算] 单位「{unit or '未给出'}」无法确定，拒绝猜测",
            )
            self.engine.history.append(calc)
            return self._after(calc)
        if factor == 1:
            # 已是「元」，仍留一条记录，保证金额链路完整可审
            calc = Calculation(
                calc_id=self.engine._next_id(), op=CalcOp.UNIT_CONVERT,
                operands=[operand], result=amount, result_unit="元",
                rounding="无需换算", status=ReviewStatus.VALID,
                trace_note=f"{label} {decimal_str(amount)} 元（原单位即为元，未做换算）",
            )
            self.engine.history.append(calc)
            return self._after(calc)
        return self._after(self.engine.convert_unit(operand, factor, "元"))

    # ------------------------------------------------------------------ 比率 / 占比
    def share(self, label: str, part: Operand, whole: Operand, places: int = 2) -> Calculation:
        if self.trace is not None:
            self.trace.tool_called(tool=self.name, action="share", label=label,
                                   part=part.label, whole=whole.label)
        return self._after(self.engine.share(part, whole, places))

    def ratio(self, label: str, a: Operand, b: Operand, places: int = 2) -> Calculation:
        if self.trace is not None:
            self.trace.tool_called(tool=self.name, action="ratio", label=label,
                                   a=a.label, b=b.label)
        return self._after(self.engine.ratio(a, b, places))

    # ------------------------------------------------------------------ 同比 / 环比
    def yoy(self, label: str, current: Operand, prior: Operand, places: int = 2) -> list[Calculation]:
        """返回本次新增的全部计算记录（同比分两步：先差额再比率）。"""
        if self.trace is not None:
            self.trace.tool_called(tool=self.name, action="yoy", label=label,
                                   current=current.label, prior=prior.label)
        before = len(self.engine.history)
        result = self.engine.yoy(current, prior, places)
        new = self.engine.history[before:]
        if not new:
            # engine.yoy 在差额阶段就被拦下时不会新增记录
            new = [result]
        for c in new:
            if self.trace is not None:
                self.trace.calculation(c)
        return new

    def qoq(self, label: str, current: Operand, prior: Operand, places: int = 2) -> list[Calculation]:
        if self.trace is not None:
            self.trace.tool_called(tool=self.name, action="qoq", label=label)
        before = len(self.engine.history)
        result = self.engine.qoq(current, prior, places)
        new = self.engine.history[before:] or [result]
        for c in new:
            if self.trace is not None:
                self.trace.calculation(c)
        return new

    # ------------------------------------------------------------------ 差额
    def difference(self, label: str, a: Operand, b: Operand) -> Calculation:
        if self.trace is not None:
            self.trace.tool_called(tool=self.name, action="difference", label=label,
                                   a=a.label, b=b.label)
        return self._after(self.engine.sub(a, b, unit=a.unit or b.unit))

    # ------------------------------------------------------------------ 汇总
    def summary(self) -> dict:
        """计算过程统计 —— 供报告「计算明细」与评测使用。"""
        hist = self.engine.history
        performed = [c for c in hist if c.is_valid]
        blocked = [c for c in hist if not c.is_valid]
        return {
            "total": len(hist),
            "performed": len(performed),
            "blocked": len(blocked),
            "blocked_reasons": [{"calc_id": c.calc_id, "reason": c.reason} for c in blocked],
            "by_op": _count_by_op(performed),
        }

    def export_jsonl(self, path: Path) -> int:
        """把计算记录写成 JSONL（竞赛要求的「计算过程」产物）。"""
        import json
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            for c in self.engine.history:
                f.write(json.dumps(c.to_dict(), ensure_ascii=False) + "\n")
        return len(self.engine.history)


def _count_by_op(calcs: list[Calculation]) -> dict[str, int]:
    out: dict[str, int] = {}
    for c in calcs:
        out[c.op.value] = out.get(c.op.value, 0) + 1
    return out


# ----------------------------------------------------------------------
# 便捷构造：从字段原文金额生成 Operand
# ----------------------------------------------------------------------

def operand_from_amount(label: str, value: Decimal | None, unit: str,
                        source: str, evidence: Iterable[Evidence] = ()) -> Operand:
    """把「已归一化的金额 + 单位」构造成计算操作数。"""
    return Operand(label=label, value=value, unit=unit, source=source,
                   evidence=list(evidence))
