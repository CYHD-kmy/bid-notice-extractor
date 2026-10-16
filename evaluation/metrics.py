"""评测：计算准确性与报告完整性。

三类指标：
  ① 计算自洽性   —— 每条 ratio 的结果能否由它的操作数重算出来（真实准确性指标）
  ② 证据可核验性 —— 断言引用的证据能否在原文中按偏移取回
  ③ 报告完整性   —— 七节是否齐全、事实/推论/观点是否都被标注

**诚实边界**：本模块只评测**确定性处理**的结果，不评测模型输出质量。
样本为合成数据，指标不能外推到真实公告。
"""
from __future__ import annotations

import json
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path


# ======================================================================
# ① 计算自洽性
# ======================================================================

def evaluate_calculations(calculations: list[dict]) -> dict:
    """校验每条计算记录能否被独立重算出来。

    对 ratio 类：result 应等于 (分子/分母)*100 按 ROUND_HALF_UP 舍入到 2 位。
    对 unit_convert：result 应等于 操作数 × 换算因子。

    这是**真实准确性指标** —— 不依赖人工标签，纯靠算术自洽。
    """
    from tools.calculate_tool import UNIT_FACTORS

    checked = 0
    failures: list[dict] = []
    by_op: dict[str, int] = {}

    for c in calculations:
        op = c.get("op")
        by_op[op] = by_op.get(op, 0) + 1
        if c.get("status") != "valid" or c.get("result") is None:
            continue
        ops = c.get("operands") or []
        try:
            if op == "ratio":
                if len(ops) != 2:
                    failures.append({"calc_id": c["calc_id"], "reason": "ratio 操作数不为 2"})
                    continue
                a, b = Decimal(ops[0]["value"]), Decimal(ops[1]["value"])
                if b == 0:
                    failures.append({"calc_id": c["calc_id"], "reason": "分母为零但仍标为 valid"})
                    continue
                expect = ((a / b) * 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                checked += 1
                if Decimal(c["result"]) != expect:
                    failures.append({"calc_id": c["calc_id"], "reason": "ratio 不自洽",
                                     "recorded": c["result"], "expected": str(expect)})
            elif op == "unit_convert":
                if len(ops) != 1:
                    failures.append({"calc_id": c["calc_id"], "reason": "换算操作数不为 1"})
                    continue
                o = ops[0]
                factor = UNIT_FACTORS.get(o.get("unit") or "")
                if factor is None:
                    continue
                expect = Decimal(o["value"]) * factor
                checked += 1
                if Decimal(c["result"]) != expect:
                    failures.append({"calc_id": c["calc_id"], "reason": "换算不自洽",
                                     "recorded": c["result"], "expected": str(expect)})
            else:
                # add/sub/mul/yoy 等：只检查 result 可解析
                Decimal(c["result"])
        except Exception as exc:                                # noqa: BLE001
            failures.append({"calc_id": c.get("calc_id"), "reason": f"重算异常：{exc}"})

    total = len(calculations)
    return {
        "total": total,
        "checked": checked,
        "failures": len(failures),
        "self_consistent_rate": round((checked - len(failures)) / checked, 6) if checked else None,
        "by_op": by_op,
        "failure_detail": failures,
        "scope": "仅校验算术自洽性（能否由操作数重算），不校验业务口径是否正确",
    }


# ======================================================================
# ② 证据可核验性
# ======================================================================

def evaluate_evidence(assertions: list[dict], pages: list[dict]) -> dict:
    """校验事实类断言的证据能否在原文中按偏移原样取回。"""
    page_index = {(p["file"], p["page"]): p for p in pages}
    facts = [a for a in assertions if a.get("kind") == "fact"]
    checked = 0
    bad: list[dict] = []

    for a in facts:
        for e in a.get("evidence") or []:
            checked += 1
            page = page_index.get((e["file"], e["page"]))
            if page is None:
                bad.append({"assertion_id": a["assertion_id"], "reason": "找不到对应页面"})
                continue
            local = e["start"] - page["start"]
            got = page["text"][local:local + len(e["quote"])]
            if got != e["quote"]:
                bad.append({"assertion_id": a["assertion_id"], "reason": "引文与原文不符",
                            "expected": e["quote"], "actual": got})

    # 无证据的事实断言（应已被守卫拦下，此处做统计）
    naked = [a["assertion_id"] for a in facts
             if not any(e.get("verified") for e in (a.get("evidence") or []))]

    return {
        "fact_assertions": len(facts),
        "evidence_checked": checked,
        "evidence_failures": len(bad),
        "verified_rate": round((checked - len(bad)) / checked, 6) if checked else None,
        "facts_without_verified_evidence": naked,
        "failure_detail": bad,
        "scope": "校验逐字引文能否按偏移从页面文本层取回；不校验语义归属是否正确",
    }


# ======================================================================
# ③ 报告完整性
# ======================================================================

REQUIRED_SECTIONS = (
    "## 一、结论摘要",
    "## 二、抽取数据表",
    "## 三、计算明细",
    "## 四、假设与适用范围",
    "## 五、风险因素与不确定项",
    "## 六、事实 / 推论 / 观点 分离表",
    "## 七、可复现性说明",
)


def evaluate_report(report_md: str, report_doc: dict) -> dict:
    """校验报告结构完整性与断言分类覆盖。"""
    missing = [s for s in REQUIRED_SECTIONS if s not in report_md]
    counts = report_doc.get("counts", {})
    kinds = {a.get("kind") for a in report_doc.get("sections", {}).get("assertion_split", [])}
    return {
        "sections_required": len(REQUIRED_SECTIONS),
        "sections_present": len(REQUIRED_SECTIONS) - len(missing),
        "sections_missing": missing,
        "assertion_kinds_present": sorted(k for k in kinds if k),
        "has_all_three_kinds": {"fact", "inference", "opinion"}.issubset(kinds),
        "fact": counts.get("assertions_fact", 0),
        "inference": counts.get("assertions_inference", 0),
        "opinion": counts.get("assertions_opinion", 0),
        "rejected": counts.get("assertions_rejected", 0),
        "evidence_verified": counts.get("evidence_verified", 0),
        "md_chars": len(report_md),
        "scope": "校验七节齐全与三类断言均被标注；不评价文字质量",
    }


# ======================================================================
# 汇总
# ======================================================================

def evaluate_run(out_dir: Path) -> dict:
    """对一次运行的产物做完整评测。"""
    out_dir = Path(out_dir)
    calcs = _read_jsonl(out_dir / "calculations.jsonl")
    assertions = _read_jsonl(out_dir / "assertions.jsonl")
    source = json.loads((out_dir / "source.json").read_text(encoding="utf-8"))
    report_doc = json.loads((out_dir / "report.json").read_text(encoding="utf-8"))
    report_md = (out_dir / "report.md").read_text(encoding="utf-8")

    result = json.loads((out_dir / "result.json").read_text(encoding="utf-8"))
    return {
        "run_id": result.get("run_id"),
        "output": out_dir.name,
        "calculations": evaluate_calculations(calcs),
        "evidence": evaluate_evidence(assertions, source["pages"]),
        "report": evaluate_report(report_md, report_doc),
        "counts": result.get("counts", {}),
    }


def _read_jsonl(path: Path) -> list[dict]:
    if not Path(path).is_file():
        return []
    return [json.loads(l) for l in Path(path).read_text(encoding="utf-8").splitlines()
            if l.strip()]
