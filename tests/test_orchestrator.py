"""编排层端到端测试。

重点锁住两个曾真实出现的 bug：
  BUG-A  占比推论把不同项目的同类金额（两个项目的预算）当成同一个值，
         导致算出 217.33% 的错误占比 —— 缓存匹配必须包含金额值
  BUG-B  同一次运行里对同一个值重复换算，产生两个 calc_id 描述同一次计算

运行：
    .venv\\Scripts\\python.exe tests/test_orchestrator.py
"""
from __future__ import annotations

import json
import shutil
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.orchestrator import _find_cached_convert, run  # noqa: E402
from core.config import DEFAULT                          # noqa: E402
from core.models import CalcOp, Calculation, Operand, ReviewStatus  # noqa: E402

PASS = 0
FAIL = 0
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "tests" / "_out" / "orchestrator"


def check(label: str, got, want) -> None:
    global PASS, FAIL
    if got == want:
        PASS += 1
        print(f"  PASS  {label}")
    else:
        FAIL += 1
        print(f"  FAIL  {label}\n        期望 {want!r}\n        实际 {got!r}")


def check_true(label: str, cond, detail="") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS  {label}")
    else:
        FAIL += 1
        print(f"  FAIL  {label}  {detail}")


# ======================================================================
print("=" * 70)
print("1. 单元：缓存匹配必须区分金额值（BUG-A 的根因）")
print("=" * 70)


class _S:
    def __init__(self, calcs):
        self.calculations = calcs


def conv(calc_id, amount, unit, source):
    return Calculation(
        calc_id=calc_id, op=CalcOp.UNIT_CONVERT,
        operands=[Operand(label="x", value=Decimal(amount), unit=unit, source=source)],
        result=Decimal(amount) * (Decimal(10000) if unit == "万元" else Decimal(1)),
        result_unit="元", status=ReviewStatus.VALID, trace_note="t",
    )


state = _S([conv("C0003", "1500", "万元", "field:budget")])

check_true("同金额命中缓存",
           _find_cached_convert(state, "field:budget", "万元", Decimal("1500")) is not None)
check_true("不同金额不命中（关键！）",
           _find_cached_convert(state, "field:budget", "万元", Decimal("4000")) is None,
           "把 4000 万预算匹配到了 1500 万的记录 —— 这正是 217.33% 的成因")
check_true("不同单位不命中",
           _find_cached_convert(state, "field:budget", "亿元", Decimal("1500")) is None)
check_true("不同来源不命中",
           _find_cached_convert(state, "field:award_amount_raw", "万元", Decimal("1500")) is None)

# ======================================================================
print()
print("=" * 70)
print("2. 端到端：跑完整流水线")
print("=" * 70)
if OUT.exists():
    shutil.rmtree(OUT, ignore_errors=True)

result = run(mode="replay", out_dir=OUT)
counts = result["counts"]
print(f"    {json.dumps(counts, ensure_ascii=False)}")

check("记录数（3 个合成事件）", counts["records"], 3)
check_true("有计算记录", counts["calculations"] > 0, str(counts["calculations"]))
check("被拒绝的断言为 0", counts["assertions_rejected"], 0)
check_true("报告生成成功", result["meta"]["report_ok"] is True)

print()
print("=" * 70)
print("3. 占比计算正确性（BUG-A 的回归锁）")
print("=" * 70)
calcs = [json.loads(l) for l in (OUT / "calculations.jsonl")
         .read_text(encoding="utf-8").splitlines() if l.strip()]
ratios = [c for c in calcs if c["op"] == "ratio"]
check_true("有占比计算", len(ratios) > 0, str(len(ratios)))

for r in ratios:
    print(f"    {r['calc_id']}: {r['trace_note']}")
    pct = float(r["result"])
    check_true(f"{r['calc_id']} 占比在合理区间 (0, 150)", 0 < pct < 150,
               f"得到 {pct}% —— 超过 150% 说明用错了预算基准")

# 逐项核对：中标金额 / 预算 应等于记录里的占比
by_id = {c["calc_id"]: c for c in calcs}


def source_traces_to(source: str, field: str, seen=None) -> bool:
    """沿 calc: 链回溯，判断某个操作数最终是否源自指定字段。

    占比的除数是「预算换算记录 calc:C0003」，而 C0003 的输入才是
    field:budget —— 因此必须逐级回溯，不能只看一层。
    """
    if seen is None:
        seen = set()
    if source == field:
        return True
    if not source.startswith("calc:"):
        return False
    cid = source.split(":", 1)[1]
    if cid in seen or cid not in by_id:
        return False
    seen.add(cid)
    return any(source_traces_to(o["source"], field, seen)
               for o in by_id[cid]["operands"])


for r in ratios:
    ops = r["operands"]
    a, b = Decimal(ops[0]["value"]), Decimal(ops[1]["value"])
    expect = (a / b * 100).quantize(Decimal("0.01"))
    check(f"{r['calc_id']} 占比算式自洽", Decimal(r["result"]).quantize(Decimal("0.01")), expect)
    check_true(f"{r['calc_id']} 除数可回溯到 field:budget",
               source_traces_to(ops[1]["source"], "field:budget"),
               f"source={ops[1]['source']}")
    check_true(f"{r['calc_id']} 被除数可回溯到 field:award_amount_raw",
               source_traces_to(ops[0]["source"], "field:award_amount_raw"),
               f"source={ops[0]['source']}")

budgets = {r["operands"][1]["value"] for r in ratios}
check_true("两个项目用了各自的预算（不是同一个）", len(budgets) >= 2, str(budgets))

print()
print("=" * 70)
print("4. 无重复换算（BUG-B 的回归锁）")
print("=" * 70)
convs = [c for c in calcs if c["op"] == "unit_convert"]
keys = [(c["operands"][0]["source"], c["operands"][0]["value"], c["operands"][0]["unit"])
        for c in convs]
dup = [k for k in set(keys) if keys.count(k) > 1]
check("同 (来源,金额,单位) 的换算只出现一次", dup, [])
print(f"    换算记录 {len(convs)} 条：")
for c in convs:
    o = c["operands"][0]
    print(f"      {c['calc_id']}  {o['source']:<28} {o['value']} {o['unit']}")

print()
print("=" * 70)
print("5. 产物齐全性")
print("=" * 70)
for name in ("registry.json", "calculations.jsonl", "assertions.jsonl",
             "result.json", "results.csv", "report.md", "report.json",
             "trace.jsonl", "source.json"):
    check_true(f"产出 {name}", (OUT / name).exists())

print()
print("=" * 70)
print("6. 能力清单（竞赛要求的编排/Tool/Prompt/Skill 可核验）")
print("=" * 70)
reg = json.loads((OUT / "registry.json").read_text(encoding="utf-8"))
check_true("registry 含 skills", len(reg.get("skills", [])) >= 4)
check_true("registry 含 tools", len(reg.get("tools", [])) >= 5)
check_true("registry 含 prompts（含 sha256）",
           all("sha256" in p for p in reg.get("prompts", [])))
check_true("registry 声明数据环境约束", "data_environment" in reg)
check_true("registry 声明模型预算", "model" in reg)
print(f"    技能：{[s['name'] for s in reg['skills']]}")
print(f"    工具：{[t['name'] for t in reg['tools']]}")
print(f"    提示词：{[p['name'] for p in reg['prompts']]}")

print()
print("=" * 70)
print("7. 报告结构")
print("=" * 70)
md = (OUT / "report.md").read_text(encoding="utf-8")
for sec in ("## 一、结论摘要", "## 二、抽取数据表", "## 三、计算明细",
            "## 四、假设与适用范围", "## 五、风险因素与不确定项",
            "## 六、事实 / 推论 / 观点 分离表", "## 七、可复现性说明"):
    check_true(f"含「{sec}」", sec in md)
check_true("报告含假设 AS0005（预算口径）", "AS0005" in md)
check_true("报告未出现 217.33（错误值已消除）", "217.33" not in md)

print()
print("=" * 70)
print("8. 追溯事件覆盖（竞赛要求记录四类情况）")
print("=" * 70)
ops = [json.loads(l)["operation"] for l in (OUT / "trace.jsonl")
       .read_text(encoding="utf-8").splitlines() if l.strip()]
need = {
    "file_read": "文件访问",
    "tool_called": "工具调用",
    "calculation_performed": "计算过程",
    "outputs_written": "结果生成",
    "report_generated": "报告生成",
}
for op, cn in need.items():
    check_true(f"记录了「{cn}」({op})", op in ops, f"trace 操作类型：{sorted(set(ops))[:12]}")

print()
print("=" * 70)
print(f"结果：PASS={PASS}  FAIL={FAIL}")
print("=" * 70)
sys.exit(1 if FAIL else 0)
