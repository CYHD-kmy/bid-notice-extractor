"""报告生成测试：含"无证据的事实断言必须导致生成失败"这一硬约束。

运行：
    .venv\\Scripts\\python.exe tests/test_report.py
"""
from __future__ import annotations

import json
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.models import (  # noqa: E402
    Assertion, AssertionKind, Assumption, Calculation, Confidence, Evidence,
    ReviewStatus,
)
from core.trace import Trace  # noqa: E402
from tools.assertion_tool import AssertionTool  # noqa: E402
from tools.calculate_tool import CalculationTool  # noqa: E402
from tools.report_tool import (  # noqa: E402
    RecordView, ReportContext, ReportError, ReportTool,
)

PASS = 0
FAIL = 0
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "tests" / "_out" / "report"


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


def ev(quote: str, page: int = 1):
    return Evidence(file="samples/01_single.pdf", page=page, quote=quote,
                    start=0, end=len(quote), verified=True,
                    bboxes=[])


print("=" * 70)
print("1. 准备一条完整数据（计算 + 断言 + 假设）")
print("=" * 70)
trace = Trace(OUT, truncate=True)
calc_tool = CalculationTool(trace=trace)
conv = calc_tool.to_base_unit("中标金额", Decimal("1280.50"), "万元",
                              "field:award_amount_raw",
                              [ev("人民币1,280.50万元")])
check("单位换算有效", conv.is_valid, True)
check("换算结果", str(conv.result), "12805000.00")

share = calc_tool.share(
    "中标金额占预算比",
    __import__("core.models", fromlist=["Operand"]).Operand(
        label="中标金额", value=Decimal("12805000"), unit="元",
        source="field:award_amount_raw", evidence=[ev("人民币1,280.50万元")]),
    __import__("core.models", fromlist=["Operand"]).Operand(
        label="项目预算", value=Decimal("15000000"), unit="元", source="field:budget"),
)
check("占比有效", share.is_valid, True)
check("占比结果", str(share.result), "85.37")

assumption = Assumption(
    assumption_id="AS0001",
    text="假设项目预算 1,500 万元为含税口径",
    basis="公告原文未标注税率",
    scope="仅本项目",
    risk_if_wrong="若为不含税口径，则占比将被高估",
)

at = AssertionTool(trace=trace)
known_calcs = {c.calc_id for c in calc_tool.engine.history}
known_asm = {assumption.assumption_id}
facts = [
    at.fact("中标公司为「华澄智能工程股份有限公司」",
            evidence=[ev("华澄智能工程股份有限公司")], known_calcs=known_calcs),
    at.fact("项目名称为「青岚智慧园区配套工程」",
            evidence=[ev("青岚智慧园区配套工程")], known_calcs=known_calcs),
    at.fact("中标金额原文为「人民币1,280.50万元」",
            evidence=[ev("人民币1,280.50万元")], calculations=[conv.calc_id],
            known_calcs=known_calcs),
]
inf = at.inference(
    f"折算中标金额为 12,805,000 元，占项目预算 85.37%",
    calculations=[conv.calc_id, share.calc_id],
    assumptions=[assumption.assumption_id],
    known_calcs=known_calcs, known_assumptions=known_asm,
    limitations="占比基于公告披露的预算口径",
)
opi = at.opinion("该中标价格水平相对预算偏紧",
                 limitations="仅适用本样本；未与同类项目横向比较",
                 known_calcs=known_calcs)
check("事实 3 条全部有效", all(f.status == ReviewStatus.VALID for f in facts), True)
check("推论有效", inf.status, ReviewStatus.VALID)
check("观点有效", opi.status, ReviewStatus.VALID)

record = RecordView(
    case_id="01_single",
    project="青岚智慧园区配套工程",
    fields={"company": "华澄智能工程股份有限公司", "project": "青岚智慧园区配套工程",
            "bidder": "青岚市公共建设中心", "award_amount_raw": "人民币1,280.50万元",
            "currency": "人民币", "award_date": "2026年10月10日",
            "disclosure_date": "2026年10月13日"},
    normalized_amount={"value": "12805000", "currency": "CNY", "status": "valid"},
    evidence={"company": ev("华澄智能工程股份有限公司"),
              "project": ev("青岚智慧园区配套工程"),
              "award_amount_raw": ev("人民币1,280.50万元")},
    calculations=[conv.calc_id, share.calc_id],
    issues=[{"field": "bidder", "reason": "招标方字段未在事件所在页找到逐字证据"}],
    status="needs_review",
)

ctx = ReportContext(
    run_id="TEST-RUN-0001", mode="replay", model_name="qwen3-vl:8b", model_calls=0,
    source_sha256="a" * 64,
    input_files=[{"file": "samples/01_single.pdf", "sha256": "b" * 64}],
    trace_path=str(trace.path),
    trace_counts={},
    data_config={"allow_external_network": False, "restrict_to_project_dir": True},
    calc_config={"rounding": "ROUND_HALF_UP", "forbid_float": True},
    evaluation={"field_accuracy": 1.0},
    scope_note="2 份合成 PDF / 3 个事件，不能推断真实公告准确率",
    synthetic=True,
)

print()
print("=" * 70)
print("2. 生成报告（应成功）")
print("=" * 70)
rt = ReportTool(trace=trace)
try:
    doc = rt.write(OUT, ctx, [record], calc_tool.engine.history,
                   at.assertions, [assumption], at.rejected)
    check_true("报告生成成功", True)
except ReportError as e:
    check_true("报告生成成功", False, str(e))
    sys.exit(1)

md_path = OUT / "report.md"
js_path = OUT / "report.json"
check("report.md 存在", md_path.exists(), True)
check("report.json 存在", js_path.exists(), True)

md = md_path.read_text(encoding="utf-8")
print(f"  report.md 大小：{len(md.encode('utf-8'))} 字节")

print()
print("=" * 70)
print("3. 报告必须包含的 7 节")
print("=" * 70)
for sec in ["## 一、结论摘要", "## 二、抽取数据表", "## 三、计算明细",
            "## 四、假设与适用范围", "## 五、风险因素与不确定项",
            "## 六、事实 / 推论 / 观点 分离表", "## 七、可复现性说明"]:
    check_true(f"含「{sec}」", sec in md)

print()
print("=" * 70)
print("4. 内容正确性")
print("=" * 70)
check_true("计算算式出现在报告里", "× 10000" in md or "10000" in md)
check_true("占比 85.37 出现", "85.37" in md)
check_true("假设的风险说明出现", "若为不含税口径" in md)
check_true("风险一节含待复核项", "招标方字段未在事件所在页找到逐字证据" in md)
check_true("分离表含三类", all(k in md for k in ["**事实**", "**推论**", "**观点**"]))
check_true("可复现性含文件哈希", "b" * 64 in md)
check_true("适用边界出现", "仅适用本样本" in md)

d = json.loads(js_path.read_text(encoding="utf-8"))
check("JSON counts.records", d["counts"]["records"], 1)
check("JSON counts.assertions_fact", d["counts"]["assertions_fact"], 3)
check("JSON counts.assertions_inference", d["counts"]["assertions_inference"], 1)
check("JSON counts.assertions_opinion", d["counts"]["assertions_opinion"], 1)
check("JSON 计算总数", d["counts"]["calculations_total"], 2)
check("JSON 计算有效数", d["counts"]["calculations_valid"], 2)

print()
print("=" * 70)
print("5. 硬约束：无证据的事实断言 -> 报告必须生成失败")
print("=" * 70)
bad_fact = Assertion(
    assertion_id="A9999", kind=AssertionKind.FACT,
    text="中标金额约为一千万元",           # 凭空的事实
    evidence=[], status=ReviewStatus.VALID,
)
try:
    rt.build(ctx, [record], calc_tool.engine.history, [bad_fact], [assumption])
    check_true("无证据事实被拦截", False, "竟然生成了报告！")
except ReportError as e:
    check_true("无证据事实被拦截", True)
    check_true("报错信息指明问题", "无已核验证据" in str(e), str(e))

print()
print("=" * 70)
print("6. trace 事件")
print("=" * 70)
c = trace.counts()
check("有 report_generated", c.get("report_generated", 0), 1)
check("有 calculation_performed", c.get("calculation_performed", 0), 2)
check("有 assertion_created", c.get("assertion_created", 0), 5)

print()
print("=" * 70)
print(f"结果：PASS={PASS}  FAIL={FAIL}")
print("=" * 70)
print()
print("报告前 30 行预览：")
print("-" * 70)
for line in md.splitlines()[:30]:
    print("  " + line)
sys.exit(1 if FAIL else 0)
