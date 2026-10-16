"""智能体编排框架：把技能串成可追溯的流水线。

竞赛对应条款：
  「设计并实现能够在受控数据环境中完成信息检索、数据处理、逻辑核验、
    量化计算和报告生成等任务的智能体系统」
  「须同步提交…智能体编排框架…」
  「完整记录文件访问、工具调用、计算过程和结果生成情况」

流水线（每一步都落 trace）：

    ① 输入准备    PDF 解析（逐字符 + 坐标）
    ② 抽取        回放录制结果（默认）或调用模型（--mode live）
    ③ 数据处理    字段 → 结构化 + 证据回溯
    ④ 量化计算    金额单位换算、中标金额占预算比（calculate_tool，每步留痕）
    ⑤ 逻辑核验    跨字段一致性（consistency_check）
    ⑥ 报告生成    七节报告（report_assembly）
    ⑦ 产物落盘    registry / calculations / assertions / tables / result / csv

默认 replay 模式：**不调用模型**，评审方无需安装 Ollama 即可跑通全流程。
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
import time
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core.config import DEFAULT, Config                                    # noqa: E402
from core.models import (                                                  # noqa: E402
    Assertion, Assumption, Confidence, Operand,
)
from core.trace import Trace, TraceEvent                                   # noqa: E402
from skills import (                                                       # noqa: E402
    BidNoticeExtractionSkill, ConsistencyCheckSkill,
    ReportAssemblySkill, TableStructuringSkill,
)
from skills.bid_notice_extraction import FIELD_LABELS                      # noqa: E402
from tools.calculate_tool import UNIT_FACTORS                              # noqa: E402
from tools.report_tool import ReportContext, sha256_file                   # noqa: E402
from agent.registry import build_registry                                  # noqa: E402

# 复用原有 PDF 解析（含逐字符坐标），确保与 prototype 行为一致
_PROTO = _ROOT / "prototype"
if str(_PROTO) not in sys.path:
    sys.path.insert(0, str(_PROTO))
from run_demo import parse_pdfs as _parse_pdfs_legacy                      # noqa: E402


# ======================================================================
# 运行状态
# ======================================================================

class RunState:
    """一次运行的全部中间产物。"""

    def __init__(self, out_dir: Path, mode: str) -> None:
        self.out_dir = out_dir
        self.mode = mode
        self.source = ""
        self.pages: list[dict] = []
        self.extracted: list[dict] = []
        self.records = []
        self.calculations = []
        self.assertions: list[Assertion] = []
        self.rejected: list[Assertion] = []
        self.assumptions: list[Assumption] = []
        self.tables = []
        self.origin: dict = {}
        self.issues: list[str] = []


# ======================================================================
# 假设登记（竞赛要求「说明主要假设…和风险因素」）
# ======================================================================

def default_assumptions() -> list[Assumption]:
    """本原型的标准假设集，随运行写入报告第四节。"""
    return [
        Assumption(
            assumption_id="AS0001",
            text="中标金额原文标注的单位（万元/亿元）即公告披露口径，不做二次换算假设",
            basis="公告原文直接标注单位",
            scope="所有含单位的中标金额",
            risk_if_wrong="若公告单位标注错误，归一化金额会整体偏差 10 的幂次",
        ),
        Assumption(
            assumption_id="AS0002",
            text="每页披露日期适用于该页全部项目",
            basis="合成样例的排版约定；真实公告需逐份核验",
            scope="同页含多个中标事件的情形",
            risk_if_wrong="跨页公告的披露日期会被错误归属，影响日期顺序判断",
        ),
        Assumption(
            assumption_id="AS0003",
            text="字段值能在页面文本层中定位即为有效证据",
            basis="电子版 PDF 具备文本层；扫描件不适用",
            scope="仅电子版 PDF（本原型未接入 OCR）",
            risk_if_wrong="扫描件或图片型 PDF 无法抽取，流程直接报错而非给出错误结果",
        ),
        Assumption(
            assumption_id="AS0004",
            text="金额未披露时保持为空，不参与任何计算",
            basis="竞赛要求不得填零或替代",
            scope="所有 award_amount_raw 缺失的情形",
            risk_if_wrong="若实际披露了金额但未被抽取，属漏记而非错记（偏保守）",
        ),
        Assumption(
            assumption_id="AS0005",
            text="文中出现的「项目预算」仅作对比基准，不作为中标金额",
            basis="预算与中标金额口径不同",
            scope="同页同时出现中标金额与预算的情形",
            risk_if_wrong="若公告把预算写成中标金额，会被规则拦截并标为待复核",
        ),
    ]


# ======================================================================
# 抽取结果加载
# ======================================================================

def load_recorded_extractions(path: Path, source: str) -> list[dict]:
    """从录制的 extractions.jsonl 读取事件。"""
    import langextract as lx
    doc = next(iter(lx.io.load_annotated_documents_jsonl(str(path))))
    out: list[dict] = []
    for item in (doc.extractions or []):
        if item.extraction_class != "中标事件":
            continue
        interval = item.char_interval
        exact = bool(interval and interval.start_pos is not None
                     and interval.end_pos is not None
                     and source[interval.start_pos:interval.end_pos] == item.extraction_text)
        attrs = item.attributes or {}
        rec = {k: (attrs.get(k) if isinstance(attrs.get(k), str) and attrs[k].strip() else None)
               for k in FIELD_LABELS}
        rec["project"] = item.extraction_text
        rec["source_start"] = interval.start_pos if exact else None
        out.append(rec)
    return out


def case_id_for(pages: list[dict], source_start) -> str:
    if source_start is None:
        return "unaligned"
    for p in pages:
        if p["start"] <= source_start < p["end"]:
            return p.get("case_id") or "unknown"
    return "unaligned"


# ======================================================================
# 推论：中标金额占预算比（演示"推论必须挂计算记录"）
# ======================================================================

_AMOUNT_RE = re.compile(r"(\d[\d,]*(?:\.\d+)?)")
_BUDGET_RE = re.compile(r"项目预算为\s*(人民币[\d,\.]+\s*[万亿千]?元)")


def _decimal_of(raw) -> Decimal | None:
    if not raw:
        return None
    m = _AMOUNT_RE.search(str(raw).replace("，", ","))
    if not m:
        return None
    try:
        return Decimal(m.group(1).replace(",", ""))
    except InvalidOperation:
        return None


def _unit_of(raw) -> str:
    """取金额原文的单位（优先更长的单位，避免「万元」被「元」抢先匹配）。"""
    text = str(raw or "")
    for u in ("亿元", "万元", "千元"):
        if u in text:
            return u
    return "元"


def _find_cached_convert(state: RunState, source: str, unit: str, amount: Decimal):
    """复用已有的单位换算记录，避免同一次运行里重复计算同一个值。

    审计友好：计算明细里不应出现两个 calc_id 描述同一次换算。

    注意：**必须同时匹配金额值**。只按 source + unit 匹配会把不同项目的
    同类金额（如两个项目的预算）误当成同一个值 —— 曾因此算出 217.33% 的错误占比。
    """
    want = amount.quantize(Decimal("0.0001"))
    for c in state.calculations:
        if not c.is_valid or c.op.value != "unit_convert":
            continue
        if len(c.operands) != 1:
            continue
        op = c.operands[0]
        if op.source != source or op.unit != unit or op.value is None:
            continue
        if op.value.quantize(Decimal("0.0001")) == want:
            return c
    return None


def build_amount_share_assertion(state: RunState, calc_tool, assertion_tool) -> list[Assertion]:
    """为「同页给出项目预算」的记录生成一条占比推论。

    所有算术都走 CalculationEngine，因此每一步都有 calc 记录；
    找不到预算时不生成推论（而不是编一个数字）。
    """
    out: list[Assertion] = []
    for rec in state.records:
        raw_amount = rec.record.get("award_amount_raw")
        if not raw_amount:
            continue
        page = next((p for p in state.pages if p.get("case_id") == rec.case_id), None)
        if page is None:
            continue
        m = _BUDGET_RE.search(page["text"])
        if not m:
            continue
        a_val, b_val = _decimal_of(raw_amount), _decimal_of(m.group(1))
        if a_val is None or b_val is None:
            continue

        # 中标金额的换算若已做过就复用（不重复计算）
        a_unit = _unit_of(raw_amount)
        a_base = _find_cached_convert(state, "field:award_amount_raw", a_unit, a_val)
        if a_base is None:
            a_base = calc_tool.to_base_unit(
                "中标金额", a_val, a_unit, "field:award_amount_raw",
                [rec.evidence["award_amount_raw"]]
                if "award_amount_raw" in rec.evidence else [])
            state.calculations.append(a_base)
        # 预算金额的换算同样复用
        b_unit = _unit_of(m.group(1))
        b_base = _find_cached_convert(state, "field:budget", b_unit, b_val)
        if b_base is None:
            b_base = calc_tool.to_base_unit("项目预算", b_val, b_unit,
                                            "field:budget", [])
            state.calculations.append(b_base)
        if not (a_base.is_valid and b_base.is_valid):
            continue

        share = calc_tool.share(
            "中标金额占预算比",
            Operand(label="中标金额", value=a_base.result, unit="元",
                    source=f"calc:{a_base.calc_id}", evidence=a_base.evidence_of()),
            Operand(label="项目预算", value=b_base.result, unit="元",
                    source=f"calc:{b_base.calc_id}", evidence=b_base.evidence_of()),
        )
        state.calculations.append(share)
        if not share.is_valid:
            continue

        known_calcs = {c.calc_id for c in state.calculations}
        known_asm = {a.assumption_id for a in state.assumptions}
        a = assertion_tool.inference(
            f"中标金额（折算 {a_base.result.quantize(Decimal('1'))} 元）"
            f"占公告披露项目预算的 {share.result}%",
            calculations=list(rec.calculations) + [share.calc_id],
            evidence=[rec.evidence["award_amount_raw"]]
            if "award_amount_raw" in rec.evidence else [],
            assumptions=["AS0001", "AS0005"],
            known_calcs=known_calcs, known_assumptions=known_asm,
            confidence=Confidence.MEDIUM,
            limitations="占比基于公告披露的预算口径；预算与中标金额可能存在口径差异，"
                        "不等同于报价下浮率",
        )
        state.assertions.append(a)
        out.append(a)
    return out


def build_amount_share_opinion(state: RunState, assertion_tool,
                               share_assertions: list[Assertion]) -> list[Assertion]:
    """基于占比给出**观点**（而非推论）。

    竞赛要求「明确区分事实、推论与观点」。占比**数值**本身是推论（有算式可回溯）；
    而"这个比例意味着什么"的判断属于**观点**，因此必须：
      · 写明判别规则（阈值从哪来）
      · 写明适用边界与样本量
      · 显式声明这只是观点，不是事实

    阈值是**本原型自定义的经验分档**，没有监管或行业依据 ——
    这一点必须写进 limitations，否则等于把主观判断伪装成客观标准。
    """
    by_id = {c.calc_id: c for c in state.calculations}
    out: list[Assertion] = []

    for a in share_assertions:
        pct = None
        for cid in a.calculations:
            c = by_id.get(cid)
            if c is not None and c.op.value == "ratio" and c.is_valid:
                pct = c.result
                break
        if pct is None:
            continue

        if pct >= Decimal("95"):
            verdict = "接近预算上限，价格空间极小"
        elif pct >= Decimal("80"):
            verdict = "处于预算的较高区间"
        elif pct >= Decimal("50"):
            verdict = "处于预算的中等区间"
        else:
            verdict = "明显低于预算"

        known_calcs = {c.calc_id for c in state.calculations}
        known_asm = {x.assumption_id for x in state.assumptions}
        op = assertion_tool.opinion(
            f"该项目中标金额占公告披露预算 {pct}%，判断为「{verdict}」",
            limitations=(
                "① 判别阈值（50%/80%/95%）是本原型自定义的经验分档，无监管或行业依据；"
                "② 仅基于 1 个项目的单一比例，样本量为 1，不构成横向比较；"
                "③ 预算口径可能与最高投标限价不同，该比率不等同于报价下浮率；"
                "④ 本条为观点而非事实，不可作为投资依据"
            ),
            evidence=[e for cid in a.calculations
                      for e in (by_id[cid].evidence_of() if cid in by_id else [])][:1],
            assumptions=["AS0005", "AS0006"],
            known_calcs=known_calcs, known_assumptions=known_asm,
            confidence=Confidence.LOW,
        )
        state.assertions.append(op)
        out.append(op)
    return out


# ======================================================================
# 产物落盘
# ======================================================================

def _write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n",
                    encoding="utf-8")


def persist(state: RunState, trace: Trace, registry: dict,
            report_result=None) -> dict:
    out = state.out_dir
    out.mkdir(parents=True, exist_ok=True)

    _write_json(out / "registry.json", registry)

    with (out / "calculations.jsonl").open("w", encoding="utf-8") as f:
        for c in state.calculations:
            f.write(json.dumps(c.to_dict(), ensure_ascii=False) + "\n")

    with (out / "assertions.jsonl").open("w", encoding="utf-8") as f:
        for a in list(state.assertions) + list(state.rejected):
            f.write(json.dumps(a.to_dict(), ensure_ascii=False) + "\n")

    if state.tables:
        with (out / "tables.jsonl").open("w", encoding="utf-8") as f:
            for t in state.tables:
                f.write(json.dumps(t.to_dict(), ensure_ascii=False) + "\n")

    result = {
        "run_id": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f"),
        "meta": {
            "mode": state.mode,
            "synthetic_data": True,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "input_files": state.origin.get("input_files", []),
            "source_sha256": hashlib.sha256(state.source.encode()).hexdigest(),
        },
        "counts": {
            "records": len(state.records),
            "calculations": len(state.calculations),
            "calculations_valid": sum(1 for c in state.calculations if c.is_valid),
            "calculations_blocked": sum(1 for c in state.calculations if not c.is_valid),
            "assertions": len(state.assertions),
            "assertions_rejected": len(state.rejected),
            "tables": len(state.tables),
            "issues": len(state.issues),
        },
        "records": [r.to_dict() for r in state.records],
    }
    _write_json(out / "result.json", result)

    with (out / "results.csv").open("w", encoding="utf-8-sig", newline="") as f:
        fields = ["case_id", *FIELD_LABELS.keys(),
                  "amount_in_base_currency", "validation_status"]
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in state.records:
            norm = (r.normalized or {}).get("award_amount") or {}
            w.writerow({**{k: r.record.get(k) for k in FIELD_LABELS},
                        "case_id": r.case_id,
                        "amount_in_base_currency": norm.get("value"),
                        "validation_status": r.validation_status.value})

    if report_result is not None and report_result.ok:
        _write_json(out / "report_summary.json", report_result.metrics)

    trace.log(TraceEvent.OUTPUTS_WRITTEN,
              files=["registry.json", "calculations.jsonl", "assertions.jsonl",
                     "result.json", "results.csv", "report.md", "report.json",
                     "trace.jsonl"],
              counts=result["counts"])
    return result


# ======================================================================
# 主流程
# ======================================================================

def run(mode: str = "replay", inputs: list[Path] | None = None,
        out_dir: Path | None = None, replay_from: Path | None = None,
        with_tables: bool = True, config: Config = DEFAULT) -> dict:
    t0 = time.monotonic()
    paths = [Path(p) for p in (inputs or sorted(config.samples.glob("*.pdf")))]
    if not 1 <= len(paths) <= config.data.max_input_files:
        raise SystemExit(
            f"samples/ 下有 {len(paths)} 份 PDF，超出上限（{config.data.max_input_files} 份）。"
            "请用 --input 明确指定要处理的文件。"
        )
    for p in paths:
        config.ensure_inside(p, "输入文件")

    out = (Path(out_dir) if out_dir else
           (config.outputs / ("replay-agent" if mode == "replay" else "agent"))).resolve()
    config.ensure_inside(out, "输出目录")
    out.mkdir(parents=True, exist_ok=True)

    trace = Trace(out, truncate=True)
    state = RunState(out, mode)
    registry = build_registry(config)
    state.origin = {
        "model": config.model.name, "model_calls": 0,
        "input_files": [{"file": p.relative_to(config.root).as_posix(),
                         "sha256": sha256_file(p)} for p in paths],
    }
    trace.log(TraceEvent.RUN_STARTED, mode=mode,
              inputs=[p.name for p in paths], python=config.describe()["python"])

    try:
        # ---------- ① 输入准备（文件访问落 trace）----------
        state.source, state.pages = _parse_pdfs_legacy(paths, trace)
        _write_json(out / "source.json", {"text": state.source, "pages": state.pages})
        source_hash = hashlib.sha256(state.source.encode()).hexdigest()

        # ---------- ② 抽取 ----------
        if mode == "replay":
            src = Path(replay_from) if replay_from else config.outputs
            origin = json.loads((src / "origin.json").read_text(encoding="utf-8"))
            if origin["source_sha256"] != source_hash:
                raise ValueError("输入与录制时不同，拒绝将历史模型输出当作本次提取结果")
            if origin["input_files"] != state.origin["input_files"]:
                raise ValueError("PDF文件列表或二进制哈希与录制时不同")
            state.origin = origin
            trace.log(TraceEvent.RECORDED_EXTRACTIONS_READ,
                      file=str(src / "extractions.jsonl"))
            state.extracted = load_recorded_extractions(
                src / "extractions.jsonl", state.source)
        else:
            raise NotImplementedError(
                "live 模式请使用 prototype/run_demo.py --mode live（本编排层复用其录制结果）。"
                "默认 replay 是为了让评审在无 Ollama 环境下也能复现全流程。"
            )
        for e in state.extracted:
            e["case_id"] = case_id_for(state.pages, e.get("source_start"))

        # ---------- ③④ 数据处理 + 量化计算 + 事实断言 ----------
        extract_skill = BidNoticeExtractionSkill(trace=trace)
        r1 = extract_skill.run(state.extracted, state.pages)
        state.records = r1.payload["records"]
        state.calculations.extend(r1.payload["calculations"])
        state.assertions.extend(r1.payload["assertions"])
        state.rejected.extend(r1.payload["rejected_assertions"])
        state.issues.extend(r1.issues)

        # ---------- ④+ 占比推论（沿用抽取阶段的计算引擎，保证 calc_id 连续）----------
        state.assumptions = default_assumptions()
        shares = build_amount_share_assertion(state, extract_skill.calc,
                                              extract_skill.assertion)
        # 基于占比再给一条"观点"（带适用边界），使三类断言齐全
        build_amount_share_opinion(state, extract_skill.assertion, shares)

        # ---------- ⑤ 逻辑核验 ----------
        r2 = ConsistencyCheckSkill(trace=trace).run(state.records)
        state.issues.extend(r2.issues)

        # ---------- 表格 ----------
        if with_tables:
            # 注意：pdfplumber 的 Page 绑定在文件句柄上，
            # 必须在 with 块内完成解析，否则后续访问会报 "seek of closed file"
            import pdfplumber
            skill = TableStructuringSkill(trace=trace)
            collected = []
            with pdfplumber.open(paths[0]) as pdf:
                for meta in state.pages:
                    if meta["page"] - 1 < len(pdf.pages):
                        collected.extend(skill.tool.extract(pdf.pages[meta["page"] - 1], meta))
            state.tables = collected
            if collected:
                trace.log(TraceEvent.TOOL_CALLED, tool="skill:table_structuring",
                          phase="end", tables=len(collected))
            issues = [f"{t.table_id} · {i}" for t in collected for i in t.parse_issues]
            if issues:
                state.issues.extend(issues)

        # ---------- ⑥ 报告生成 ----------
        ctx = ReportContext(
            run_id=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f"),
            mode=mode, model_name=config.model.name, model_calls=0,
            source_sha256=source_hash, input_files=state.origin["input_files"],
            trace_path=trace.path.relative_to(config.root).as_posix(),
            trace_counts=trace.counts(),
            data_config=config.describe()["data"],
            calc_config=config.describe()["calc"],
            evaluation={},
            scope_note=("本报告基于合成样例，仅用于验证流水线可运行性与可追溯性，"
                        "不能推断真实公告的准确率"),
            synthetic=True,
        )
        report_result = ReportAssemblySkill(trace=trace).run(
            state.records, state.calculations, state.assertions,
            state.rejected, state.assumptions, ctx, out)

        # ---------- ⑦ 落盘 ----------
        result = persist(state, trace, registry, report_result)
        result["meta"]["elapsed_seconds"] = round(time.monotonic() - t0, 3)
        result["meta"]["report_ok"] = report_result.ok
        result["meta"]["output"] = out.relative_to(config.root).as_posix()
        _write_json(out / "result.json", result)

        trace.log(TraceEvent.RUN_FINISHED, ok=True,
                  elapsed_seconds=result["meta"]["elapsed_seconds"],
                  records=len(state.records), issues=len(state.issues))
        return result

    except Exception as exc:                       # noqa: BLE001
        trace.log(TraceEvent.RUN_FAILED, error=f"{type(exc).__name__}: {exc}")
        _write_json(out / "failure.json", {"error": f"{type(exc).__name__}: {exc}"})
        raise


# ======================================================================
# CLI
# ======================================================================

def main() -> int:
    ap = argparse.ArgumentParser(description="金融投研智能体编排（方向1：数据结构化提取）")
    ap.add_argument("--mode", choices=["replay", "live"], default="replay")
    ap.add_argument("--input", nargs="*", type=Path)
    ap.add_argument("--output", type=Path)
    ap.add_argument("--replay-from", type=Path, default=DEFAULT.outputs)
    ap.add_argument("--no-tables", action="store_true", help="跳过表格解析")
    ap.add_argument("--registry", action="store_true", help="只打印能力清单")
    args = ap.parse_args()

    if args.registry:
        print(json.dumps(build_registry(), ensure_ascii=False, indent=2))
        return 0

    result = run(mode=args.mode, inputs=args.input, out_dir=args.output,
                 replay_from=args.replay_from, with_tables=not args.no_tables)
    print(json.dumps({
        "mode": result["meta"]["mode"],
        "model_calls": 0,
        "records": result["counts"]["records"],
        "calculations": result["counts"]["calculations"],
        "assertions": result["counts"]["assertions"],
        "rejected": result["counts"]["assertions_rejected"],
        "tables": result["counts"]["tables"],
        "issues": result["counts"]["issues"],
        "report_ok": result["meta"]["report_ok"],
        "seconds": result["meta"]["elapsed_seconds"],
        "output": result["meta"]["output"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
