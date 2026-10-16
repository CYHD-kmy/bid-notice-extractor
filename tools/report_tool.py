"""报告生成工具：把抽取结果 + 计算明细 + 断言集组装成可交付的分析报告。

竞赛对应条款：
  「最终成果应以结构化数据、表格或分析报告等形式呈现，不得仅提交自然语言对话记录」
  「应说明主要假设、适用范围和风险因素，并明确区分事实、推论与观点」

硬约束：
  · 若存在 kind=fact 但未通过校验的断言，**报告生成失败**（宁可不出报告，不出错报告）
  · 报告必须包含"事实/推论/观点分离表"
  · 报告必须包含"风险因素与不确定项"一节（含 needs_review / missing 字段）
  · 报告必须包含"可复现性说明"（文件哈希、模型调用次数、trace 路径）

输出：Markdown（人读）+ JSON（机读）
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from core.models import (
    Assertion, AssertionKind, Assumption, Calculation, Confidence, Evidence,
    ReviewStatus,
)

CURRENCY_CN = {"CNY": "元", "USD": "美元", "HKD": "港元", "EUR": "欧元"}


class ReportError(RuntimeError):
    """报告无法生成（存在无证据的事实断言等硬性违规）。"""


@dataclass
class ReportContext:
    """生成报告所需的全部输入（由编排层填充）。"""
    run_id: str = ""
    mode: str = "replay"
    model_name: str = ""
    model_calls: int = 0
    source_sha256: str = ""
    input_files: list[dict] = field(default_factory=list)   # [{"file":..., "sha256":...}]
    trace_path: str = ""
    trace_counts: dict = field(default_factory=dict)
    data_config: dict = field(default_factory=dict)
    calc_config: dict = field(default_factory=dict)
    evaluation: dict = field(default_factory=dict)
    scope_note: str = ""
    synthetic: bool = True


@dataclass
class RecordView:
    """报告里一条业务记录的可读视图。"""
    case_id: str
    project: str
    fields: dict
    normalized_amount: dict | None = None     # normalize_amount 的结果
    evidence: dict[str, Evidence] = field(default_factory=dict)
    calculations: list[str] = field(default_factory=list)
    issues: list[dict] = field(default_factory=list)
    status: str = "valid"


# ======================================================================
# 生成器
# ======================================================================

class ReportTool:
    name = "report"

    def __init__(self, trace=None, prefix: str = "R") -> None:
        self.trace = trace
        self.prefix = prefix

    # ------------------------------------------------------------------ 校验
    @staticmethod
    def _guard(assertions: list[Assertion], rejected: list[Assertion]) -> None:
        """报告前置校验：不允许"无证据的事实"混入。"""
        bad = [a for a in assertions
               if a.kind == AssertionKind.FACT and not any(e.verified for e in a.evidence)]
        if bad:
            ids = "、".join(a.assertion_id for a in bad)
            raise ReportError(
                f"存在 {len(bad)} 条无已核验证据的事实断言（{ids}），拒绝生成报告。"
                "事实类断言必须能回溯到原文逐字引文。"
            )
        # 被拒绝的断言不得出现在 accepted 列表里（双重保险）
        accepted_ids = {a.assertion_id for a in assertions}
        leaked = [a for a in rejected if a.assertion_id in accepted_ids]
        if leaked:
            raise ReportError("检测到被拒绝的断言混入报告：" +
                              "、".join(a.assertion_id for a in leaked))

    # ------------------------------------------------------------------ 组装
    def build(self, ctx: ReportContext, records: list[RecordView],
              calculations: list[Calculation], assertions: list[Assertion],
              assumptions: list[Assumption],
              rejected: list[Assertion] | None = None) -> dict:
        rejected = rejected or []
        self._guard(assertions, rejected)

        calc_index = {c.calc_id: c for c in calculations}
        calc_summary = _calc_summary(calculations)

        risks = _collect_risks(records, calculations, assertions, rejected)

        doc = {
            "run_id": ctx.run_id,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "mode": ctx.mode,
            "scope_note": ctx.scope_note,
            "synthetic_data": ctx.synthetic,
            "sections": {
                "summary": [a.to_dict() for a in assertions
                            if a.kind in (AssertionKind.FACT, AssertionKind.INFERENCE)],
                "records": [_record_dict(r) for r in records],
                "calculations": [c.to_dict() for c in calculations],
                "assumptions": [a.to_dict() for a in assumptions],
                "risks": risks,
                "assertion_split": [a.to_dict() for a in assertions],
                "reproducibility": _repro_dict(ctx),
            },
            "counts": {
                "records": len(records),
                "calculations_total": len(calculations),
                "calculations_valid": calc_summary["performed"],
                "calculations_blocked": calc_summary["blocked"],
                "assertions_fact": sum(1 for a in assertions if a.kind == AssertionKind.FACT),
                "assertions_inference": sum(1 for a in assertions if a.kind == AssertionKind.INFERENCE),
                "assertions_opinion": sum(1 for a in assertions if a.kind == AssertionKind.OPINION),
                "assertions_rejected": len(rejected),
                "evidence_verified": sum(
                    len([e for e in a.evidence if e.verified]) for a in assertions),
            },
            "calc_summary": calc_summary,
        }
        # 供 Markdown 渲染用的索引（不进 JSON）
        self._calc_index = calc_index
        return doc

    # ------------------------------------------------------------------ 渲染
    def to_markdown(self, doc: dict) -> str:
        s = doc["sections"]
        c = doc["counts"]
        L: list[str] = []
        add = L.append

        add("# 中标公告结构化抽取分析报告")
        add("")
        add(f"- 运行编号：`{doc['run_id']}`")
        add(f"- 生成时间（UTC）：{doc['generated_at']}")
        add(f"- 运行模式：**{doc['mode']}**"
            + ("（回放：0 次模型调用）" if doc["mode"] == "replay" else ""))
        add(f"- 数据性质：{'合成样例' if doc.get('synthetic_data') else '真实数据'}")
        add("")
        if doc.get("scope_note"):
            add(f"> **适用范围**：{doc['scope_note']}")
            add("")

        # ---------------- 一、结论摘要
        add("## 一、结论摘要")
        add("")
        add("> 本节只收录 **事实** 与 **推论** 两类断言；每条均标注证据与依据。")
        add("")
        facts = [a for a in s["summary"] if a["kind"] == "fact"]
        infers = [a for a in s["summary"] if a["kind"] == "inference"]
        add(f"**事实（{len(facts)} 条）**")
        add("")
        if facts:
            add("| # | 事实 | 证据位置 | 置信度 |")
            add("|---|---|---|---|")
            for i, a in enumerate(facts, 1):
                add(f"| {i} | {a['text']} | {_ev_ref(a['evidence'])} | {a['confidence']} |")
        else:
            add("（无）")
        add("")
        add(f"**推论（{len(infers)} 条）**")
        add("")
        if infers:
            add("| # | 推论 | 计算依据 | 假设 | 置信度 |")
            add("|---|---|---|---|---|")
            for i, a in enumerate(infers, 1):
                calcs = "、".join(a["calculations"]) or "—"
                asms = "、".join(a["assumptions"]) or "—"
                add(f"| {i} | {a['text']} | {calcs} | {asms} | {a['confidence']} |")
        else:
            add("（无）")
        add("")

        # ---------------- 二、数据表
        add("## 二、抽取数据表")
        add("")
        for r in s["records"]:
            add(f"### {r['case_id']} · {r['project']}")
            add("")
            add("| 字段 | 原文取值 | 归一化 | 证据 |")
            add("|---|---|---|---|")
            for f in ("company", "project", "bidder", "award_amount_raw",
                      "currency", "award_date", "disclosure_date"):
                raw = r["fields"].get(f)
                norm = ""
                if f == "award_amount_raw" and r.get("normalized_amount"):
                    na = r["normalized_amount"]
                    if na.get("value") is not None:
                        norm = f"{na['value']} {CURRENCY_CN.get(na.get('currency'), '')}".strip()
                    else:
                        norm = f"（{na.get('status')}）"
                add(f"| {f} | {_cell(raw)} | {_cell(norm)} | {r['evidence'].get(f, '—')} |")
            if r.get("issues"):
                add("")
                add("**待复核项**")
                add("")
                for it in r["issues"]:
                    add(f"- `{it.get('field')}`：{it.get('reason')}")
            add("")

        # ---------------- 三、计算明细
        add("## 三、计算明细（量化计算过程记录）")
        add("")
        add(f"本次共 {c['calculations_total']} 条计算记录，"
            f"其中有效 {c['calculations_valid']} 条、未计算/被拦截 {c['calculations_blocked']} 条。")
        add("")
        add("| 计算ID | 类型 | 算式 | 结果 | 舍入 | 状态 |")
        add("|---|---|---|---|---|---|")
        for calc in s["calculations"]:
            add(f"| {calc['calc_id']} | {calc['op']} | {_cell(calc['trace_note'])} "
                f"| {_cell(calc['result'])}{calc['result_unit']} | {_cell(calc['rounding'])} "
                f"| {calc['status']} |")
        add("")
        add("> 计算全程使用 `Decimal`，不使用二进制浮点；缺失值不参与计算，单位不一致不自动换算。")
        add("")

        # ---------------- 四、假设与适用范围
        add("## 四、假设与适用范围")
        add("")
        if s["assumptions"]:
            add("| 假设ID | 假设内容 | 依据 | 适用范围 | 若不成立的影响 |")
            add("|---|---|---|---|---|")
            for a in s["assumptions"]:
                add(f"| {a['assumption_id']} | {a['text']} | {_cell(a['basis'])} "
                    f"| {_cell(a['scope'])} | {_cell(a['risk_if_wrong'])} |")
        else:
            add("（本次运行未登记假设）")
        add("")

        # ---------------- 五、风险因素与不确定项
        add("## 五、风险因素与不确定项")
        add("")
        if s["risks"]:
            for group, items in s["risks"].items():
                if not items:
                    continue
                add(f"**{group}**（{len(items)} 项）")
                add("")
                for it in items:
                    add(f"- {it}")
                add("")
        else:
            add("（未发现）")
            add("")

        # ---------------- 六、事实/推论/观点分离表
        add("## 六、事实 / 推论 / 观点 分离表")
        add("")
        add("| 断言ID | 类型 | 内容 | 证据数 | 计算依据 | 适用边界 | 置信度 | 状态 |")
        add("|---|---|---|---|---|---|---|---|")
        for a in s["assertion_split"]:
            evn = len([e for e in a["evidence"] if e.get("verified")])
            add(f"| {a['assertion_id']} | **{_kind_cn(a['kind'])}** | {_cell(a['text'])} "
                f"| {evn} | {_cell('、'.join(a['calculations'])) or '—'} "
                f"| {_cell(a['limitations']) or '—'} | {a['confidence']} | {a['status']} |")
        add("")
        if c["assertions_rejected"]:
            add(f"> 另有 **{c['assertions_rejected']}** 条断言因不满足证据/依据要求被拦截，"
                f"未进入本报告（详见 `assertions.jsonl` 中被拒绝记录）。")
            add("")

        # ---------------- 七、可复现性说明
        add("## 七、可复现性说明")
        add("")
        rep = s["reproducibility"]
        add(f"- 输入文件与 SHA256：")
        for f in rep["input_files"]:
            add(f"  - `{f['file']}` → `{f['sha256']}`")
        add(f"- 正文 SHA256：`{rep['source_sha256']}`")
        add(f"- 模型：`{rep['model_name']}`，本次调用 **{rep['model_calls']}** 次"
            + ("（回放模式不调用模型）" if rep["model_calls"] == 0 else ""))
        add(f"- 追溯日志：`{rep['trace_path']}`")
        add("")
        if rep.get("trace_counts"):
            add("| 事件类型 | 条数 |")
            add("|---|---|")
            for k, v in sorted(rep["trace_counts"].items()):
                add(f"| `{k}` | {v} |")
            add("")
        if rep.get("data_config"):
            add("**数据环境约束**")
            add("")
            add("| 项 | 值 |")
            add("|---|---|")
            for k, v in rep["data_config"].items():
                add(f"| {k} | {v} |")
            add("")
        if rep.get("calc_config"):
            add("**计算规则**")
            add("")
            add("| 项 | 值 |")
            add("|---|---|")
            for k, v in rep["calc_config"].items():
                add(f"| {k} | {v} |")
            add("")
        if rep.get("evaluation"):
            add("**评测结果**")
            add("")
            add("| 指标 | 值 |")
            add("|---|---|")
            for k, v in rep["evaluation"].items():
                if isinstance(v, (str, int, float, type(None))):
                    add(f"| {k} | {v} |")
            add("")

        add("---")
        add("")
        add("*本报告由 `tools/report_tool.py` 自动生成；所有事实性内容均可通过上表中的"
            "文件、页码与逐字引文回溯至原始 PDF。*")
        return "\n".join(L) + "\n"

    # ------------------------------------------------------------------ 落盘
    def write(self, out_dir: Path, ctx: ReportContext, records, calculations,
              assertions, assumptions, rejected=None) -> dict:
        doc = self.build(ctx, records, calculations, assertions, assumptions, rejected)
        md = self.to_markdown(doc)
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "report.json").write_text(
            json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (out_dir / "report.md").write_text(md, encoding="utf-8")
        if self.trace is not None:
            self.trace.log("report_generated",
                           files=["report.md", "report.json"],
                           records=doc["counts"]["records"],
                           calculations=doc["counts"]["calculations_total"],
                           fact=doc["counts"]["assertions_fact"],
                           inference=doc["counts"]["assertions_inference"],
                           opinion=doc["counts"]["assertions_opinion"],
                           rejected=doc["counts"]["assertions_rejected"],
                           md_bytes=len(md.encode("utf-8")))
        return doc


# ======================================================================
# 辅助
# ======================================================================

def _kind_cn(kind: str) -> str:
    return {"fact": "事实", "inference": "推论", "opinion": "观点"}.get(kind, kind)


def _cell(v) -> str:
    if v is None or v == "":
        return "—"
    return str(v).replace("|", "\\|").replace("\n", " ")


def _ev_ref(evidence: list[dict]) -> str:
    parts = []
    for e in evidence:
        if not e.get("verified"):
            continue
        bbs = e.get("bboxes") or []
        loc = f"p{e['page']}"
        if bbs:
            loc += f"@({bbs[0][0]:.0f},{bbs[0][1]:.0f})"
        parts.append(f"{e['file']} {loc}「{_cell(e['quote'])}」")
    return "；".join(parts) if parts else "—"


def _calc_summary(calculations: list[Calculation]) -> dict:
    performed = [c for c in calculations if c.is_valid]
    blocked = [c for c in calculations if not c.is_valid]
    by_op: dict[str, int] = {}
    for c in performed:
        by_op[c.op.value] = by_op.get(c.op.value, 0) + 1
    return {
        "total": len(calculations),
        "performed": len(performed),
        "blocked": len(blocked),
        "by_op": by_op,
        "blocked_reasons": [{"calc_id": c.calc_id, "reason": c.reason} for c in blocked],
    }


def _record_dict(r: RecordView) -> dict:
    return {
        "case_id": r.case_id,
        "project": r.project,
        "status": r.status,
        "fields": {k: v for k, v in r.fields.items()},
        "normalized_amount": r.normalized_amount,
        "evidence": {k: _ev_ref([v.to_dict()]) for k, v in r.evidence.items()},
        "calculations": list(r.calculations),
        "issues": list(r.issues),
    }


def _collect_risks(records: list[RecordView], calculations: list[Calculation],
                   assertions: list[Assertion], rejected: list[Assertion]) -> dict:
    risks: dict[str, list[str]] = {
        "字段缺失": [],
        "待复核字段": [],
        "计算被拦截": [],
        "断言被拒绝": [],
        "证据不足": [],
    }
    for r in records:
        for it in (r.issues or []):
            reason = it.get("reason", "")
            field = it.get("field", "?")
            line = f"{r.case_id} · `{field}`：{reason}"
            if "缺失" in reason:
                risks["字段缺失"].append(line)
            else:
                risks["待复核字段"].append(line)
        for m, v in (r.fields or {}).items():
            if v in (None, ""):
                line = f"{r.case_id} · `{m}` 未披露"
                if line not in risks["字段缺失"]:
                    risks["字段缺失"].append(line)
    for c in calculations:
        if not c.is_valid:
            risks["计算被拦截"].append(f"{c.calc_id}（{c.op.value}）：{c.reason}")
    for a in rejected:
        risks["断言被拒绝"].append(
            f"{a.assertion_id}（{_kind_cn(a.kind.value)}）：{'；'.join(a.issues)}")
    for a in assertions:
        if a.kind == AssertionKind.FACT and not any(e.verified for e in a.evidence):
            risks["证据不足"].append(f"{a.assertion_id}：事实断言缺已核验证据")
    return {k: v for k, v in risks.items() if v} or risks


def _repro_dict(ctx: ReportContext) -> dict:
    return {
        "input_files": ctx.input_files,
        "source_sha256": ctx.source_sha256,
        "model_name": ctx.model_name,
        "model_calls": ctx.model_calls,
        "trace_path": ctx.trace_path,
        "trace_counts": ctx.trace_counts,
        "data_config": ctx.data_config,
        "calc_config": ctx.calc_config,
        "evaluation": ctx.evaluation,
    }


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()
