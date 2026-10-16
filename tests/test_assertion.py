"""断言工具测试：验证事实/推论/观点三类断言的强制不变量。

运行：
    .venv\\Scripts\\python.exe tests/test_assertion.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.models import Confidence, Evidence, ReviewStatus  # noqa: E402
from core.trace import Trace  # noqa: E402
from tools.assertion_tool import (  # noqa: E402
    AssertionTool, amount_fact, facts_from_record,
)

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


def ev(quote="华澄智能工程股份有限公司"):
    return Evidence(file="samples/01_single.pdf", page=1, quote=quote,
                    start=0, end=len(quote), verified=True)


def ev_unverified():
    return Evidence(file="samples/01_single.pdf", page=1, quote="凭推测",
                    start=0, end=3, verified=False)


print("=" * 70)
print("1. 事实断言：有证据 -> 通过")
print("=" * 70)
tool = AssertionTool()
a1 = tool.fact("中标公司为「华澄智能工程股份有限公司」", evidence=[ev()])
check("状态 valid", a1.status, ReviewStatus.VALID)
check("无 issues", a1.issues, [])
check("进入 accepted", len(tool.assertions), 1)

print()
print("=" * 70)
print("2. 事实断言：无证据 -> 拒绝（竞赛硬要求）")
print("=" * 70)
t2 = AssertionTool()
a2 = t2.fact("中标金额约为一千万元", evidence=[])
check("被拒绝", a2.status, ReviewStatus.REJECTED)
check("有原因", any("证据" in i for i in a2.issues), True)
check("未进入 accepted", len(t2.assertions), 0)
check("进入 rejected", len(t2.rejected), 1)

print()
print("=" * 70)
print("3. 事实断言：证据未核验（verified=False）-> 同样拒绝")
print("=" * 70)
t3 = AssertionTool()
a3 = t3.fact("某某公司中标", evidence=[ev_unverified()])
check("未核验证据被拒", a3.status, ReviewStatus.REJECTED)

print()
print("=" * 70)
print("4. 推论断言：必须引用有效 calc_id")
print("=" * 70)
known = {"C0001", "C0002"}
t4 = AssertionTool()
a4 = t4.inference("中标金额占项目预算 85.37%", calculations=["C0002"],
                  known_calcs=known)
check("引用有效计算 -> 通过", a4.status, ReviewStatus.VALID)

a5 = t4.inference("金额占比偏高", calculations=["C9999"], known_calcs=known)
check("引用不存在计算 -> 拒绝", a5.status, ReviewStatus.REJECTED)
check("原因含 calc_id", any("C9999" in i for i in a5.issues), True)

a6 = t4.inference("两家公司金额接近", calculations=[], known_calcs=known)
check("无计算引用 -> 拒绝", a6.status, ReviewStatus.REJECTED)

print()
print("=" * 70)
print("5. 观点断言：必须写明适用边界")
print("=" * 70)
t5 = AssertionTool()
a7 = t5.opinion("该中标价格水平偏高", limitations="仅适用于同类园区配套工程，样本量 3")
check("有边界 -> 通过", a7.status, ReviewStatus.VALID)

a8 = t5.opinion("该中标价格水平偏高", limitations="")
check("无边界 -> 拒绝", a8.status, ReviewStatus.REJECTED)
check("原因含适用边界", any("适用边界" in i for i in a8.issues), True)

print()
print("=" * 70)
print("6. 假设引用校验")
print("=" * 70)
t6 = AssertionTool()
a9 = t6.inference("预计毛利率提升", calculations=["C0001"],
                  assumptions=["AS0001"], known_calcs={"C0001"},
                  known_assumptions={"AS0002"})
check("引用不存在假设 -> 拒绝", a9.status, ReviewStatus.REJECTED)
check("原因含假设ID", any("AS0001" in i for i in a9.issues), True)

print()
print("=" * 70)
print("7. 从记录自动生成事实断言（只对有证据的字段）")
print("=" * 70)
t7 = AssertionTool()
record = {
    "company": "华澄智能工程股份有限公司",
    "project": "青岚智慧园区配套工程",
    "bidder": "青岚市公共建设中心",
    "award_amount_raw": "人民币1,280.50万元",
    "currency": "人民币",
    "award_date": "2026年10月10日",
    "disclosure_date": None,          # 缺失
}
evidence = {
    "company": ev("华澄智能工程股份有限公司"),
    "project": ev("青岚智慧园区配套工程"),
    "bidder": ev("青岚市公共建设中心"),
    "award_amount_raw": ev("人民币1,280.50万元"),
    "award_date": ev("2026年10月10日"),
    # disclosure_date / currency 无证据
}
facts = facts_from_record(t7, record, evidence)
check("生成 4 条事实断言", len(facts), 4)
check("全部 valid", all(f.status == ReviewStatus.VALID for f in facts), True)
check("project 生成的是中文标签", any("项目名称" in f.text for f in facts), True)

af = amount_fact(t7, record, evidence, calc_ids=["C0001"], known_calcs={"C0001"})
check("金额事实断言生成", af is not None, True)
check("金额事实含原文", "1,280.50万元" in af.text, True)

print()
print("=" * 70)
print("8. 汇总与导出")
print("=" * 70)
t8 = AssertionTool()
t8.fact("事实一", evidence=[ev()])
t8.inference("推论一", calculations=["C0001"], known_calcs={"C0001"})
t8.opinion("观点一", limitations="限本样本")
t8.fact("无证据的事实", evidence=[])     # 应被拒
s = t8.summary()
check("accepted = 3", s["accepted"], 3)
check("rejected = 1", s["rejected"], 1)
check("fact = 1", s["fact"], 1)
check("inference = 1", s["inference"], 1)
check("opinion = 1", s["opinion"], 1)
check("拒绝明细非空", len(s["rejected_detail"]), 1)

out = Path(__file__).resolve().parents[1] / "tests" / "_out" / "assertions.jsonl"
n = t8.export_jsonl(out)
check("导出含被拒记录", n, 4)
check("文件存在", out.exists(), True)

import json
rows = [json.loads(l) for l in out.read_text(encoding="utf-8").splitlines() if l.strip()]
kinds = sorted({r["kind"] for r in rows})
check("三类断言齐全", kinds, ["fact", "inference", "opinion"])

print()
print("=" * 70)
print("9. trace 事件")
print("=" * 70)
trace = Trace(Path(__file__).resolve().parents[1] / "tests" / "_out" / "assert_trace", truncate=True)
t9 = AssertionTool(trace=trace)
t9.fact("有证据", evidence=[ev()])
t9.fact("无证据", evidence=[])
c = trace.counts()
check("assertion_created", c.get("assertion_created", 0), 1)
check("assertion_rejected", c.get("assertion_rejected", 0), 1)

print()
print("=" * 70)
print(f"结果：PASS={PASS}  FAIL={FAIL}")
print("=" * 70)
sys.exit(1 if FAIL else 0)
