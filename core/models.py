"""可追溯数据模型：证据、计算、断言、假设、表格。

设计约束（全项目遵守）：
  ① 任何数值/结论都必须能回溯到原文（Evidence）
  ② 计算全程 Decimal，禁用二进制浮点
  ③ 事实/推论/观点必须显式区分，事实必须有证据
  ④ 缺失一律为 None，绝不用 0 或空串填充

本模块只定义数据结构与不变量，不做 IO。
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from enum import Enum
from typing import Any, Iterable


# ======================================================================
# 枚举
# ======================================================================

class AssertionKind(str, Enum):
    """断言类型 —— 竞赛要求「明确区分事实、推论与观点」。"""
    FACT = "fact"            # 直接来自原文，必须有逐字证据
    INFERENCE = "inference"  # 由事实+计算推导，必须能列出算式链
    OPINION = "opinion"      # 主观判断，必须给出依据与适用边界


class ReviewStatus(str, Enum):
    VALID = "valid"
    NEEDS_REVIEW = "needs_review"
    MISSING = "missing"
    REJECTED = "rejected"


class Confidence(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class CalcOp(str, Enum):
    UNIT_CONVERT = "unit_convert"   # 单位换算，如 万元 -> 元
    ADD = "add"
    SUB = "sub"
    MUL = "mul"
    DIV = "div"
    RATIO = "ratio"                 # 比率（除以基准，结果带 % 语义）
    YOY = "yoy"                     # 同比
    QOQ = "qoq"                     # 环比
    SHARE = "share"                 # 占比


# ======================================================================
# 证据
# ======================================================================

@dataclass
class BBox:
    """一个矩形区域（PDF 坐标，原点在左上）。"""
    x0: float
    top: float
    x1: float
    bottom: float

    def as_list(self) -> list[float]:
        return [self.x0, self.top, self.x1, self.bottom]

    @staticmethod
    def from_any(v: Any) -> "BBox":
        if isinstance(v, BBox):
            return v
        if isinstance(v, dict):
            return BBox(v["x0"], v["top"], v["x1"], v["bottom"])
        seq = list(v)
        return BBox(seq[0], seq[1], seq[2], seq[3])


@dataclass
class Evidence:
    """字段值的原文证据：逐字引文 + 位置 + 坐标。"""
    file: str                 # 相对路径，统一 posix 风格
    page: int                 # 1 起
    quote: str                # 逐字引文（必须与原文完全一致）
    start: int                # 拼接文本中的起始偏移
    end: int
    bboxes: list[BBox] = field(default_factory=list)
    verified: bool = False    # 是否已在原文成功定位

    def to_dict(self) -> dict:
        d = asdict(self)
        d["bboxes"] = [b.as_list() for b in self.bboxes]
        return d

    @staticmethod
    def from_dict(d: dict) -> "Evidence":
        return Evidence(
            file=d["file"], page=d["page"], quote=d["quote"],
            start=d["start"], end=d["end"],
            bboxes=[BBox.from_any(b) for b in d.get("bboxes", [])],
            verified=bool(d.get("verified", False)),
        )


# ======================================================================
# 计算
# ======================================================================

def decimal_str(value: Decimal) -> str:
    """Decimal -> 规范化字符串（去尾随零，不丢精度）。"""
    s = format(value, "f")
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s or "0"


@dataclass
class Operand:
    """计算的一个输入。来源必须是：某字段名、某计算ID、或字面常量。"""
    label: str                    # 人可读标签，如「中标金额」
    value: Decimal | None         # None 表示缺失（不得当成 0）
    unit: str = ""                # 元 / 万元 / %
    source: str = ""              # "field:award_amount_raw" | "calc:C0002" | "literal"
    evidence: list[Evidence] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "label": self.label,
            "value": None if self.value is None else decimal_str(self.value),
            "unit": self.unit,
            "source": self.source,
            "evidence": [e.to_dict() for e in self.evidence],
        }


@dataclass
class Calculation:
    """一次可审计的计算。

    trace_note 必须是人可读的完整算式，例如：
        「1,280.50 万元 × 10,000 = 12,805,000 元」
    """
    calc_id: str
    op: CalcOp
    operands: list[Operand]
    result: Decimal | None
    result_unit: str = ""
    rounding: str = ""            # 如 "ROUND_HALF_UP, 2 位小数"
    trace_note: str = ""
    status: ReviewStatus = ReviewStatus.VALID
    reason: str = ""              # status != VALID 时必填
    depends_on: list[str] = field(default_factory=list)  # 引用的其他 calc_id

    @property
    def is_valid(self) -> bool:
        return self.status == ReviewStatus.VALID and self.result is not None

    def evidence_of(self) -> list[Evidence]:
        """本计算的全部输入证据（结果因此也可回溯）。

        注意：命名为 evidence_of 而非 evidence，避免与 Operand.evidence
        （列表字段）在阅读时混淆。
        """
        out: list[Evidence] = []
        for op in self.operands:
            out.extend(op.evidence)
        return out

    def to_dict(self) -> dict:
        return {
            "calc_id": self.calc_id,
            "op": self.op.value,
            "operands": [o.to_dict() for o in self.operands],
            "result": None if self.result is None else decimal_str(self.result),
            "result_unit": self.result_unit,
            "rounding": self.rounding,
            "trace_note": self.trace_note,
            "status": self.status.value,
            "reason": self.reason,
            "depends_on": list(self.depends_on),
        }


class CalculationEngine:
    """计算引擎：所有算术的唯一入口，每步产生一条可审计记录。

    不变量：
      · 全程 Decimal
      · 任一操作数缺失 -> 不计算，产出 NEEDS_REVIEW 记录并说明原因
      · 单位不一致 -> 不计算，产出 NEEDS_REVIEW（不猜）
      · 除零 -> 不计算，产出 REJECTED
    """

    def __init__(self, prefix: str = "C") -> None:
        self._n = 0
        self._prefix = prefix
        self.history: list[Calculation] = []

    # -------------------------------------------------- 内部
    def _next_id(self) -> str:
        self._n += 1
        return f"{self._prefix}{self._n:04d}"

    def _record(self, calc: Calculation) -> Calculation:
        self.history.append(calc)
        return calc

    def _blocked(self, op: CalcOp, operands: list[Operand], status: ReviewStatus,
                 reason: str, rounding: str = "") -> Calculation:
        calc = Calculation(
            calc_id=self._next_id(), op=op, operands=operands, result=None,
            rounding=rounding, status=status, reason=reason,
            trace_note=f"[未计算] {reason}",
        )
        return self._record(calc)

    @staticmethod
    def _missing(operands: Iterable[Operand]) -> list[Operand]:
        return [o for o in operands if o.value is None]

    @staticmethod
    def _units(operands: Iterable[Operand]) -> set[str]:
        return {o.unit for o in operands if o.unit}

    # -------------------------------------------------- 单位换算
    def convert_unit(self, operand: Operand, factor: Decimal, to_unit: str,
                     rounding: str = "精确换算，不舍入") -> Calculation:
        """单位换算。如 万元 -> 元：factor=10000。"""
        if operand.value is None:
            return self._blocked(CalcOp.UNIT_CONVERT, [operand],
                                 ReviewStatus.MISSING, f"「{operand.label}」缺失，不换算")
        result = operand.value * factor
        note = (f"{operand.label} {operand.value} {operand.unit} × {decimal_str(factor)}"
                f" = {decimal_str(result)} {to_unit}")
        return self._record(Calculation(
            calc_id=self._next_id(), op=CalcOp.UNIT_CONVERT, operands=[operand],
            result=result, result_unit=to_unit, rounding=rounding,
            trace_note=note, status=ReviewStatus.VALID,
        ))

    # -------------------------------------------------- 二元运算
    def _binary(self, op: CalcOp, a: Operand, b: Operand, symbol: str,
                result_unit: str, places: int | None = None) -> Calculation:
        operands = [a, b]
        miss = self._missing(operands)
        if miss:
            names = "、".join(f"「{o.label}」" for o in miss)
            return self._blocked(op, operands, ReviewStatus.MISSING,
                                 f"{names}缺失，不计算（缺失不填零）")
        units = self._units(operands)
        if len(units) > 1:
            return self._blocked(op, operands, ReviewStatus.NEEDS_REVIEW,
                                 f"操作数单位不一致（{'、'.join(sorted(units))}），不自动换算")
        rounding = f"ROUND_HALF_UP, {places} 位小数" if places is not None else "不舍入"
        try:
            if op == CalcOp.ADD:
                raw = a.value + b.value
            elif op == CalcOp.SUB:
                raw = a.value - b.value
            elif op == CalcOp.MUL:
                raw = a.value * b.value
            elif op in (CalcOp.DIV, CalcOp.RATIO, CalcOp.SHARE):
                if b.value == 0:
                    return self._blocked(op, operands, ReviewStatus.REJECTED,
                                         f"除数为零（「{b.label}」），拒绝计算")
                raw = a.value / b.value
            else:
                return self._blocked(op, operands, ReviewStatus.REJECTED,
                                     f"不支持的运算 {op}")
        except (InvalidOperation, ArithmeticError) as exc:
            return self._blocked(op, operands, ReviewStatus.REJECTED, f"计算异常：{exc}")

        result = raw.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP) \
            if places is not None else raw
        note = (f"{a.label} {decimal_str(a.value)}{a.unit} {symbol} "
                f"{b.label} {decimal_str(b.value)}{b.unit} "
                f"= {decimal_str(result)}{result_unit}")
        return self._record(Calculation(
            calc_id=self._next_id(), op=op, operands=operands, result=result,
            result_unit=result_unit, rounding=rounding, trace_note=note,
            status=ReviewStatus.VALID,
        ))

    def add(self, a, b, unit="元") -> Calculation:
        return self._binary(CalcOp.ADD, a, b, "+", unit)

    def sub(self, a, b, unit="元") -> Calculation:
        return self._binary(CalcOp.SUB, a, b, "-", unit)

    def mul(self, a, b, unit="元") -> Calculation:
        return self._binary(CalcOp.MUL, a, b, "×", unit)

    def ratio(self, a, b, places=2) -> Calculation:
        """比率。百分数形态，保留 places 位小数。

        顺序很关键：先算比率（不舍入）→ 乘 100 → 最后才 quantize。
        若先 quantize 再乘 100，0.853667 会被截成 0.85，结果错成 85.00。
        """
        operands = [a, b]
        miss = self._missing(operands)
        if miss:
            names = "、".join(f"「{o.label}」" for o in miss)
            return self._blocked(CalcOp.RATIO, operands, ReviewStatus.MISSING,
                                 f"{names}缺失，不计算（缺失不填零）")
        units = self._units(operands)
        if len(units) > 1:
            return self._blocked(CalcOp.RATIO, operands, ReviewStatus.NEEDS_REVIEW,
                                 f"操作数单位不一致（{'、'.join(sorted(units))}），不自动换算")
        if b.value == 0:
            return self._blocked(CalcOp.RATIO, operands, ReviewStatus.REJECTED,
                                 f"除数为零（「{b.label}」），拒绝计算")
        rounding = f"ROUND_HALF_UP, {places} 位小数（先算比率，再乘 100）"
        pct = (a.value / b.value) * 100
        result = pct.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)
        note = (f"{a.label} {decimal_str(a.value)}{a.unit} ÷ "
                f"{b.label} {decimal_str(b.value)}{b.unit} × 100 "
                f"= {decimal_str(result)}%")
        return self._record(Calculation(
            calc_id=self._next_id(), op=CalcOp.RATIO, operands=operands,
            result=result, result_unit="%", rounding=rounding,
            trace_note=note, status=ReviewStatus.VALID,
        ))

    def share(self, part, whole, places=2) -> Calculation:
        return self.ratio(part, whole, places)

    def yoy(self, current: Operand, prior: Operand, places=2) -> Calculation:
        """同比 =（本期 - 上期）/ 上期 × 100%。分两步，两步都留痕。"""
        diff = self.sub(current, prior, unit=current.unit or prior.unit)
        if not diff.is_valid:
            return diff
        diff_op = Operand(label=f"{current.label}较{prior.label}变动", value=diff.result,
                          unit=current.unit, source=f"calc:{diff.calc_id}",
                          evidence=diff.evidence_of())
        base = Operand(label=prior.label, value=prior.value, unit=prior.unit,
                       source=prior.source, evidence=list(prior.evidence))
        r = self.ratio(diff_op, base, places)
        if r.is_valid:
            r.op = CalcOp.YOY
            r.depends_on = [diff.calc_id]
            r.trace_note = (f"({decimal_str(current.value)} - {decimal_str(prior.value)}) "
                            f"÷ {decimal_str(prior.value)} × 100 = {decimal_str(r.result)}%")
        return r

    def qoq(self, current: Operand, prior: Operand, places=2) -> Calculation:
        r = self.yoy(current, prior, places)
        if r.is_valid:
            r.op = CalcOp.QOQ
        return r


# ======================================================================
# 假设
# ======================================================================

@dataclass
class Assumption:
    """一条显式假设 —— 竞赛要求「说明主要假设…和风险因素」。"""
    assumption_id: str
    text: str
    basis: str = ""          # 依据：原文 / 行业惯例 / 用户输入
    scope: str = ""          # 适用范围
    risk_if_wrong: str = ""  # 若不成立的影响

    def to_dict(self) -> dict:
        return asdict(self)


# ======================================================================
# 断言
# ======================================================================

@dataclass
class Assertion:
    """一条可入报告的断言。

    不变量（由 validate() 强制）：
      · kind == FACT      -> 必须有 verified=True 的 Evidence
      · kind == INFERENCE -> 必须引用至少一条有效的 calc_id
      · kind == OPINION   -> 必须有 scope（适用边界）
    """
    assertion_id: str
    kind: AssertionKind
    text: str
    evidence: list[Evidence] = field(default_factory=list)
    calculations: list[str] = field(default_factory=list)   # calc_id
    assumptions: list[str] = field(default_factory=list)    # assumption_id
    confidence: Confidence = Confidence.MEDIUM
    limitations: str = ""
    status: ReviewStatus = ReviewStatus.VALID
    issues: list[str] = field(default_factory=list)

    def validate(self, known_calcs: set[str], known_assumptions: set[str]) -> list[str]:
        """返回问题列表；空列表表示通过。"""
        issues: list[str] = []
        if not self.text.strip():
            issues.append("断言内容为空")
        if self.kind == AssertionKind.FACT:
            if not any(e.verified for e in self.evidence):
                issues.append("事实类断言缺少已核验的逐字证据")
        elif self.kind == AssertionKind.INFERENCE:
            valid = [c for c in self.calculations if c in known_calcs]
            if not valid:
                issues.append("推论类断言未引用任何有效计算记录")
        elif self.kind == AssertionKind.OPINION:
            if not self.limitations.strip():
                issues.append("观点类断言未说明适用边界")
        for c in self.calculations:
            if c not in known_calcs:
                issues.append(f"引用了不存在的计算记录 {c}")
        for a in self.assumptions:
            if a not in known_assumptions:
                issues.append(f"引用了不存在的假设 {a}")
        self.issues = issues
        if issues:
            self.status = ReviewStatus.REJECTED
        return issues

    def to_dict(self) -> dict:
        return {
            "assertion_id": self.assertion_id,
            "kind": self.kind.value,
            "text": self.text,
            "evidence": [e.to_dict() for e in self.evidence],
            "calculations": list(self.calculations),
            "assumptions": list(self.assumptions),
            "confidence": self.confidence.value,
            "limitations": self.limitations,
            "status": self.status.value,
            "issues": list(self.issues),
        }


# ======================================================================
# 表格
# ======================================================================

@dataclass
class TableCell:
    text: str
    row: int
    col: int
    bbox: BBox | None = None
    evidence: Evidence | None = None

    def to_dict(self) -> dict:
        return {
            "text": self.text, "row": self.row, "col": self.col,
            "bbox": self.bbox.as_list() if self.bbox else None,
            "evidence": self.evidence.to_dict() if self.evidence else None,
        }


@dataclass
class Table:
    """解析出的表格。每个单元格带坐标，因此表格内容同样可回溯。"""
    table_id: str
    file: str
    page: int
    n_rows: int
    n_cols: int
    cells: list[TableCell] = field(default_factory=list)
    header_confidence: Confidence = Confidence.MEDIUM
    parse_issues: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "table_id": self.table_id, "file": self.file, "page": self.page,
            "n_rows": self.n_rows, "n_cols": self.n_cols,
            "cells": [c.to_dict() for c in self.cells],
            "header_confidence": self.header_confidence.value,
            "parse_issues": list(self.parse_issues),
        }


# ======================================================================
# 记录（抽取出的一个业务事件）
# ======================================================================

FIELDS = ("company", "project", "bidder", "award_amount_raw",
          "currency", "award_date", "disclosure_date")


@dataclass
class Record:
    case_id: str
    event_id: str
    record: dict[str, Any]                    # 原始字段（逐字引用）
    normalized: dict[str, Any] = field(default_factory=dict)
    evidence: dict[str, Evidence] = field(default_factory=dict)
    calculations: list[str] = field(default_factory=list)     # calc_id
    assertions: list[str] = field(default_factory=list)       # assertion_id
    validation_status: ReviewStatus = ReviewStatus.VALID
    validation_issues: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "case_id": self.case_id,
            "event_id": self.event_id,
            **{k: self.record.get(k) for k in FIELDS},
            "normalized": self.normalized,
            "evidence": {k: v.to_dict() for k, v in self.evidence.items()},
            "calculations": list(self.calculations),
            "assertions": list(self.assertions),
            "validation_status": self.validation_status.value,
            "validation_issues": list(self.validation_issues),
        }
