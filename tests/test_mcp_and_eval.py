"""S8/S9 测试：MCP 服务 + 评测指标。

运行：
    .venv\\Scripts\\python.exe tests/test_mcp_and_eval.py
"""
from __future__ import annotations

import json
import shutil
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evaluation.metrics import (                       # noqa: E402
    REQUIRED_SECTIONS, evaluate_calculations, evaluate_evidence, evaluate_report,
)
from evaluation.stability import stability             # noqa: E402
from mcp.server import handle, PROTOCOL_VERSION        # noqa: E402
from mcp.tools import call_tool, list_tools            # noqa: E402

PASS = 0
FAIL = 0
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "tests" / "_out" / "mcpeval"


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
print("A. MCP 协议")
print("=" * 70)
r = handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
check("协议版本", r["result"]["protocolVersion"], PROTOCOL_VERSION)
check("serverInfo 有名称", r["result"]["serverInfo"]["name"], "bid-notice-extractor")
check("通知无响应", handle({"jsonrpc": "2.0", "method": "notifications/initialized"}), None)
check("ping 返回空结果", handle({"jsonrpc": "2.0", "id": 9, "method": "ping"})["result"], {})
check("未知方法 -32601", handle({"jsonrpc": "2.0", "id": 2, "method": "x/y"})["error"]["code"], -32601)

print()
print("=" * 70)
print("B. MCP 工具（7 个，全部确定性）")
print("=" * 70)
tools = list_tools()
check("工具数量", len(tools), 7)
check_true("全部带 inputSchema", all("inputSchema" in t for t in tools))
check_true("全部有 description", all(t.get("description") for t in tools))
print(f"    {[t['name'] for t in tools]}")

sc = call_tool("calculate_unit_convert",
               {"amount": "0.326", "unit": "亿元"})["structuredContent"]
check("亿元换算（去尾零）", str(sc["calc"]["result"]), "32600000")

sc = call_tool("calculate_ratio",
               {"numerator": "12805000", "denominator": "15000000"})["structuredContent"]
check("占比 85.37", str(sc["calc"]["result"]), "85.37")

sc = call_tool("calculate_ratio", {"numerator": "1", "denominator": "0"})["structuredContent"]
check("除零被拒绝", sc["ok"], False)
check("除零 status=rejected", sc["calc"]["status"], "rejected")

sc = call_tool("calculate_yoy", {"current": "120", "prior": "100"})["structuredContent"]
check("同比（去尾零后为 20）", str(sc["calc"]["result"]), "20")
check("同比返回两步记录", len(sc["steps"]), 2)

sc = call_tool("normalize_amount", {"raw": "人民币1,280.50万元"})["structuredContent"]
check("正常金额归一化", sc["value"], "12805000")
check("币种解析", sc["currency"], "CNY")

sc = call_tool("normalize_amount", {"raw": "合计人民币100万元"})["structuredContent"]
check("合计口径被拦截", sc["value"], None)
check_true("拦截原因说明", "预算" in sc["reason"] or "合计" in sc["reason"], sc["reason"])

sc = call_tool("normalize_amount", {"raw": "尚未确定"})["structuredContent"]
check("缺失不填零", sc["value"], None)
check("缺失 status（尚未确定应识别为 missing）", sc["status"], "missing")

sc = call_tool("normalize_date", {"raw": "2026年2月30日"})["structuredContent"]
check("不存在日期被拒", sc["value"], None)

sc = call_tool("registry_list", {})["structuredContent"]
check_true("registry 含四类信息",
           all(k in sc for k in ("skills", "tools", "prompts", "data_environment")))
check_true("prompts 带 sha256", all("sha256" in p for p in sc["prompts"]))

res = call_tool("不存在", {})
check("未知工具 isError", res["isError"], True)

print()
print("=" * 70)
print("C. 评测指标：计算自洽性")
print("=" * 70)
good = [
    {"calc_id": "C1", "op": "ratio", "status": "valid", "result": "85.37",
     "operands": [{"value": "12805000", "unit": "元"}, {"value": "15000000", "unit": "元"}]},
    {"calc_id": "C2", "op": "unit_convert", "status": "valid", "result": "12805000.00",
     "operands": [{"value": "1280.50", "unit": "万元"}]},
]
m = evaluate_calculations(good)
check("自洽率 1.0", m["self_consistent_rate"], 1.0)
check("无失败", m["failures"], 0)

bad = [{"calc_id": "C3", "op": "ratio", "status": "valid", "result": "99.99",
        "operands": [{"value": "100", "unit": "元"}, {"value": "200", "unit": "元"}]}]
m = evaluate_calculations(bad)
check("错误占比被抓出", m["failures"], 1)
check("失败明细含期望值", m["failure_detail"][0]["reason"], "ratio 不自洽")

zero = [{"calc_id": "C4", "op": "ratio", "status": "valid", "result": "1",
         "operands": [{"value": "1", "unit": "元"}, {"value": "0", "unit": "元"}]}]
m = evaluate_calculations(zero)
check("分母为零但仍标 valid 被抓出", m["failures"], 1)

print()
print("=" * 70)
print("D. 评测指标：证据可核验性")
print("=" * 70)
pages = [{"file": "a.pdf", "page": 1, "start": 0, "end": 10, "text": "0123456789"}]
ok_ev = [{"assertion_id": "A1", "kind": "fact",
          "evidence": [{"file": "a.pdf", "page": 1, "start": 0, "end": 3,
                        "quote": "012", "verified": True}]}]
m = evaluate_evidence(ok_ev, pages)
check("证据核验率 1.0", m["verified_rate"], 1.0)

bad_ev = [{"assertion_id": "A2", "kind": "fact",
           "evidence": [{"file": "a.pdf", "page": 1, "start": 0, "end": 3,
                         "quote": "999", "verified": True}]}]
m = evaluate_evidence(bad_ev, pages)
check("错误引文被抓出", m["evidence_failures"], 1)

naked = [{"assertion_id": "A3", "kind": "fact", "evidence": []}]
m = evaluate_evidence(naked, pages)
check("无证据事实被统计", m["facts_without_verified_evidence"], ["A3"])

print()
print("=" * 70)
print("E. 评测指标：报告完整性")
print("=" * 70)
md_full = "\n".join(REQUIRED_SECTIONS)
doc_full = {"counts": {"assertions_fact": 3, "assertions_inference": 1, "assertions_opinion": 1,
                       "assertions_rejected": 0, "evidence_verified": 5},
            "sections": {"assertion_split": [{"kind": "fact"}, {"kind": "inference"},
                                             {"kind": "opinion"}]}}
m = evaluate_report(md_full, doc_full)
check("七节齐全", m["sections_present"], 7)
check("无缺失节", m["sections_missing"], [])
check("三类断言齐全", m["has_all_three_kinds"], True)

m = evaluate_report("## 一、结论摘要\n", {"counts": {}, "sections": {"assertion_split": []}})
check("缺节被抓出", len(m["sections_missing"]), 6)
check("缺类被抓出", m["has_all_three_kinds"], False)

print()
print("=" * 70)
print("F. 稳定性（3 次回放）")
print("=" * 70)
rep = stability(runs=3)
check("产物一致", rep["all_files_identical"], True)
check("指标一致", rep["all_metrics_identical"], True)
check("确定性结论", rep["deterministic"], True)
check("模型调用为 0", rep["model_calls_per_run"], 0)
check_true("声明了适用边界", "回放确定性" in rep["scope"], rep["scope"])
check_true("明确不声称模型稳定性", "不能" in rep["scope"])
print(f"    逐产物：{ {k: ('一致' if v['identical'] else '不一致') for k, v in rep['file_consistency'].items()} }")

print()
print("=" * 70)
print("G. 假设文档与第三方声明（竞赛硬要求）")
print("=" * 70)
asm = (ROOT / "ASSUMPTIONS.md").read_text(encoding="utf-8")
for aid in ("AS0001", "AS0005", "AS0008"):
    check_true(f"ASSUMPTIONS.md 含 {aid}", aid in asm)
check_true("含「适用范围」表述", "适用范围" in asm)
check_true("含「风险因素」表述", "风险" in asm)
check_true("含「事实 / 推论 / 观点」区分说明", "事实 / 推论 / 观点" in asm or "区分" in asm)

tp = (ROOT / "THIRD_PARTY.md").read_text(encoding="utf-8")
check_true("THIRD_PARTY.md 含「调用方式」列", "调用方式" in tp)
check_true("说明分工（不冒充自研）", "未修改" in tp and "本项目" in tp)
check_true("MCP README 存在", (ROOT / "mcp" / "README.md").is_file())

print()
print("=" * 70)
print(f"结果：PASS={PASS}  FAIL={FAIL}")
print("=" * 70)

shutil.rmtree(OUT, ignore_errors=True)
sys.exit(1 if FAIL else 0)
