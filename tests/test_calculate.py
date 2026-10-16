"""计算引擎与计算工具的单元测试。

运行：
    .venv\\Scripts\\python.exe -m pytest tests -q
或直接：
    .venv\\Scripts\\python.exe tests/test_calculate.py
"""
from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

# 允许直接运行本文件
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.models import (  # noqa: E402
    CalculationEngine, Evidence, Operand, ReviewStatus,
)
from core.trace import Trace  # noqa: E402
from tools.calculate_tool import CalculationTool, UNIT_FACTORS  # noqa: E402

PASS = 0
FAIL = 0


def check(label: str, got, want) -> None:
    global PASS, FAIL
    if got == want:
        PASS += 1
        print(f"  PASS  {label}")
    else:
        FAIL += 1
        print(f"  FAIL  {label}\n        期望 {want!r}\n        实际 {got!r}")


def ev(quote: str = "1,280.50万元") -> Evidence:
    return Evidence(file="samples/01_single.pdf", page=1, quote=quote,
                    start=0, end=len(quote), verified=True)


# ======================================================================
print("=" * 70)
print("1. 单位换算")
print("=" * 70)
tool = CalculationTool()
c1 = tool.to_base_unit("中标金额", Decimal("1280.50"), "万元", "field:award_amount_raw", [ev()])
check("万元 -> 元 结果", str(c1.result), "12805000.00")  # Decimal 保留标度
check("状态 valid", c1.status, ReviewStatus.VALID)
check("算式可读", c1.trace_note, "中标金额 1280.50 万元 × 10000 = 12805000 元")  # decimal_str 去尾零
check("证据可回溯", len(c1.evidence_of()), 1)
check("证据已核验", c1.evidence_of()[0].verified, True)

c2 = tool.to_base_unit("中标金额", Decimal("0.326"), "亿元", "field:award_amount_raw", [ev()])
check("亿元 -> 元 结果", str(c2.result), "32600000.000")  # 0.326 标度为 3

c3 = tool.to_base_unit("中标金额", Decimal("500"), "元", "field:award_amount_raw", [ev()])
check("元 不换算仍留痕", c3.status, ReviewStatus.VALID)
check("元 结果不变", str(c3.result), "500")

print()
print("=" * 70)
print("2. 缺失值：不填零、不计算")
print("=" * 70)
c4 = tool.to_base_unit("中标金额", None, "万元", "field:award_amount_raw", [])
check("缺失 -> 结果 None", c4.result, None)
check("缺失 -> status", c4.status, ReviewStatus.MISSING)
check("缺失 -> 有原因说明", bool(c4.reason), True)

print()
print("=" * 70)
print("3. 未知单位：不猜")
print("=" * 70)
c5 = tool.to_base_unit("中标金额", Decimal("100"), "万元港币", "field:award_amount_raw", [])
check("未知单位 -> 结果 None", c5.result, None)
check("未知单位 -> needs_review", c5.status, ReviewStatus.NEEDS_REVIEW)

print()
print("=" * 70)
print("4. 单位不一致：不自动换算")
print("=" * 70)
eng = CalculationEngine(prefix="U")
a = Operand(label="A", value=Decimal("100"), unit="元", source="field:x")
b = Operand(label="B", value=Decimal("5"), unit="万元", source="field:y")
r = eng.add(a, b)
check("单位不一致 -> 结果 None", r.result, None)
check("单位不一致 -> needs_review", r.status, ReviewStatus.NEEDS_REVIEW)

print()
print("=" * 70)
print("5. 除零：拒绝计算")
print("=" * 70)
eng2 = CalculationEngine(prefix="Z")
zero = Operand(label="预算", value=Decimal("0"), unit="元", source="field:budget")
part = Operand(label="中标金额", value=Decimal("100"), unit="元", source="field:award")
r2 = eng2.ratio(part, zero)
check("除零 -> 结果 None", r2.result, None)
check("除零 -> rejected", r2.status, ReviewStatus.REJECTED)

print()
print("=" * 70)
print("6. 占比（保留 2 位，ROUND_HALF_UP）")
print("=" * 70)
eng3 = CalculationEngine(prefix="S")
p = Operand(label="中标金额", value=Decimal("12805000"), unit="元", source="field:award", evidence=[ev()])
w = Operand(label="项目预算", value=Decimal("15000000"), unit="元", source="field:budget")
r3 = eng3.share(p, w)
check("占比结果", str(r3.result), "85.37")
check("占比单位", r3.result_unit, "%")
check("占比算式含 ×100", "× 100" in r3.trace_note, True)
check("占比证据继承自输入", len(r3.evidence_of()), 1)

print()
print("=" * 70)
print("7. 同比（分两步，两步都留痕）")
print("=" * 70)
eng4 = CalculationEngine(prefix="Y")
cur = Operand(label="本期收入", value=Decimal("120"), unit="万元", source="field:rev_2026")
pri = Operand(label="上期收入", value=Decimal("100"), unit="万元", source="field:rev_2025")
before = len(eng4.history)
yoy = eng4.yoy(cur, pri)
check("同比结果 %", str(yoy.result), "20.00")
check("同比单位", yoy.result_unit, "%")
check("产生 2 条计算记录", len(eng4.history) - before, 2)
check("依赖链已记录", len(yoy.depends_on) == 1 and yoy.depends_on[0] == eng4.history[before].calc_id, True)

print()
print("=" * 70)
print("8. 全流程不出现 float")
print("=" * 70)
bad = []
for c in eng4.history + eng3.history + tool.engine.history:
    for o in c.operands:
        if isinstance(o.value, float):
            bad.append((c.calc_id, o.label))
    if isinstance(c.result, float):
        bad.append((c.calc_id, "result"))
check("无 float 参与运算", bad, [])

print()
print("=" * 70)
print("9. trace 事件与导出")
print("=" * 70)
trace = Trace(Path(__file__).resolve().parents[1] / "tests" / "_out" / "trace", truncate=True)
t2 = CalculationTool(trace=trace)
t2.to_base_unit("中标金额", Decimal("1280.50"), "万元", "field:award_amount_raw", [ev()])
t2.share("金额占预算比",
         Operand(label="中标金额", value=Decimal("12805000"), unit="元", source="field:a"),
         Operand(label="项目预算", value=Decimal("15000000"), unit="元", source="field:b"))
counts = trace.counts()
check("有 tool_called 事件", counts.get("tool_called", 0), 2)
check("有 calculation_performed 事件", counts.get("calculation_performed", 0), 2)

out = Path(__file__).resolve().parents[1] / "tests" / "_out" / "calculations.jsonl"
n = t2.export_jsonl(out)
check("导出 JSONL 行数", n, 2)
check("JSONL 文件存在", out.exists(), True)
import json
rows = [json.loads(l) for l in out.read_text(encoding="utf-8").splitlines() if l.strip()]
check("每行有 trace_note", all(r.get("trace_note") for r in rows), True)
check("每行有 calc_id", all(r.get("calc_id") for r in rows), True)

print()
print("=" * 70)
print(f"结果：PASS={PASS}  FAIL={FAIL}")
print("=" * 70)
sys.exit(1 if FAIL else 0)
