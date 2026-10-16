"""技能：中标公告 → 结构化字段 + 计算 + 事实断言。

这是方向 1 的主技能，编排流程：

    录制/模型抽取结果
        ↓
    ① 字段回溯证据（evidence_tool.locate）
        ↓
    ② 金额归一化（prototype.validation.normalize_amount，原逻辑不改）
        ↓
    ③ 单位换算留痕（calculate_tool.to_base_unit → Calculation）
        ↓
    ④ 生成事实断言（assertion_tool.fact，必须有已核验证据）
        ↓
    SkillResult{records, calculations, assertions}

竞赛对应条款：
  「数据结构化提取」+「数据来源可核验」+「量化计算」+「区分事实」
"""
from __future__ import annotations

from pathlib import Path

from core.models import (
    Assertion, Calculation, Confidence, Evidence, FIELDS, Operand,
    Record, ReviewStatus,
)
from skills.base import Skill, SkillResult
from tools.assertion_tool import AssertionTool, FIELD_LABELS, SKIP_FACT_FIELDS
from tools.calculate_tool import CalculationTool
from tools.evidence_tool import EvidenceTool, amount_is_labelled

# 复用原有归一化逻辑（不重写，保证与 prototype 行为一致）
import sys
_PROTOTYPE = Path(__file__).resolve().parents[1] / "prototype"
if str(_PROTOTYPE) not in sys.path:
    sys.path.insert(0, str(_PROTOTYPE))
from validation import normalize_amount                      # noqa: E402

#: 从金额原文中提取「单位 + 数值」用于换算
_UNIT_PATTERNS = (
    ("亿元", "亿元"),
    ("万元", "万元"),
    ("千元", "千元"),
    ("元", "元"),
)


def parse_amount_unit(raw: str) -> tuple[str | None, str]:
    """从金额原文拆出数值字符串与单位。

    只做**轻量拆分**，不做归一化（归一化交给 validation.normalize_amount）。
    返回 (数值字符串或 None, 单位)。
    """
    import re
    if not isinstance(raw, str) or not raw.strip():
        return None, ""
    text = raw.replace(",", "").replace("，", "")
    unit = ""
    for token, name in _UNIT_PATTERNS:
        if token in text:
            unit = name
            break
    m = re.search(r"(\d+(?:\.\d+)?)", text)
    return (m.group(1) if m else None), unit


class BidNoticeExtractionSkill(Skill):
    name = "bid_notice_extraction"
    description = "从中标公告抽取结构化字段，回溯证据，换算金额，生成事实断言"
    uses_tools = ("evidence", "calculate", "assertion")
    uses_prompts = ("extract_bid_notice", "schema")

    def __init__(self, trace=None, calc_prefix: str = "C") -> None:
        super().__init__(trace)
        self.evidence = EvidenceTool(trace)
        self.calc = CalculationTool(trace=trace)
        self.assertion = AssertionTool(trace)

    # ------------------------------------------------------------------
    def run(self, extracted: list[dict], pages: list[dict],
            expected_index: int = 0) -> SkillResult:
        """extracted: [{case_id, project, company, bidder, award_amount_raw,
                        currency, award_date, disclosure_date, source_start?}]
           pages:     parse_pdfs 产出的页面列表
        """
        self._log_start(records=len(extracted), pages=len(pages))
        records: list[Record] = []
        issues: list[str] = []

        for i, item in enumerate(extracted):
            case_id = str(item.get("case_id") or "unknown")
            mine: list[str] = []          # 本记录自己的问题（不含 case_id 前缀）
            project = str(item.get("project") or "")
            page = self._page_for(pages, case_id, item.get("source_start"), project)
            anchor = int(item.get("source_start") or 0) - (page["start"] if page else 0)

            evidence: dict[str, Evidence] = {}
            if page is None:
                mine.append("事件未对齐到任何页面，无法回溯证据")
            else:
                for field in FIELDS:
                    value = item.get(field)
                    if value is None or (isinstance(value, str) and not value.strip()):
                        continue
                    ev = self.evidence.locate(page, value, anchor)
                    if ev is None:
                        mine.append(f"`{field}` 值未在原文找到逐字证据")
                    else:
                        evidence[field] = ev

            # ---- ② 金额归一化（复用原逻辑）----
            raw_amount = item.get("award_amount_raw")
            norm = normalize_amount(raw_amount, item.get("currency"))

            # ---- ③ 单位换算留痕 ----
            calc_ids: list[str] = []
            num_str, unit = parse_amount_unit(raw_amount or "")
            if num_str is not None and norm.get("value") is not None:
                from decimal import Decimal
                conv = self.calc.to_base_unit(
                    label=FIELD_LABELS["award_amount_raw"].replace("原文", ""),
                    amount=Decimal(num_str), unit=unit,
                    source="field:award_amount_raw",
                    evidence=[evidence["award_amount_raw"]] if "award_amount_raw" in evidence else [],
                )
                calc_ids.append(conv.calc_id)
                if conv.is_valid and str(conv.result) != str(norm["value"]):
                    mine.append(
                        f"金额换算与归一化结果不一致："
                        f"计算引擎 {conv.result} vs validation {norm['value']}"
                    )
            elif raw_amount:
                # 金额存在但无法换算 —— 留一条被拦截的记录，不静默
                from decimal import Decimal
                blocked = self.calc.to_base_unit(
                    label="中标金额", amount=None, unit=unit or "未知",
                    source="field:award_amount_raw", evidence=[])
                calc_ids.append(blocked.calc_id)

            # ---- ④ 事实断言 ----
            known_calcs = {c.calc_id for c in self.calc.engine.history}
            for field in FIELDS:
                if field in SKIP_FACT_FIELDS:
                    continue
                value = item.get(field)
                ev = evidence.get(field)
                if value is None or ev is None:
                    continue
                self.assertion.fact(
                    f"{FIELD_LABELS.get(field, field)}为「{value}」",
                    evidence=[ev], known_calcs=known_calcs,
                )
            if raw_amount and "award_amount_raw" in evidence:
                self.assertion.fact(
                    f"中标金额原文为「{raw_amount}」",
                    evidence=[evidence["award_amount_raw"]],
                    calculations=calc_ids, known_calcs=known_calcs,
                )
                if page is not None and not amount_is_labelled(page, evidence["award_amount_raw"]):
                    mine.append("金额未紧邻「中标金额/中标价」标签，需核对是否误用预算")

            # 汇总本记录的问题（带 case_id 前缀供全局报告）
            issues.extend(f"{case_id} · {m}" for m in mine)
            rec_issues = [{"field": "record", "reason": m} for m in mine]
            records.append(Record(
                case_id=case_id, event_id=f"event-{i + 1}",
                record={k: item.get(k) for k in FIELDS},
                normalized={"award_amount": norm},
                evidence=evidence,
                calculations=calc_ids,
                validation_status=(ReviewStatus.NEEDS_REVIEW if rec_issues
                                   else ReviewStatus.VALID),
                validation_issues=rec_issues,
            ))

        result = SkillResult(
            skill=self.name,
            status=ReviewStatus.NEEDS_REVIEW if issues else ReviewStatus.VALID,
            payload={"records": records,
                     "calculations": self.calc.engine.history,
                     "assertions": self.assertion.assertions,
                     "rejected_assertions": self.assertion.rejected},
            issues=issues,
            metrics={"records": len(records),
                     "calculations": len(self.calc.engine.history),
                     "assertions": len(self.assertion.assertions),
                     "rejected_assertions": len(self.assertion.rejected),
                     "evidence_verified": sum(len(r.evidence) for r in records)},
        )
        return self._log_end(result)

    # ------------------------------------------------------------------
    @staticmethod
    def _page_for(pages: list[dict], case_id: str, source_start, project: str) -> dict | None:
        """定位事件所在页：优先用 source_start，其次按 case_id，最后在所有页里找项目名。"""
        if source_start is not None:
            for p in pages:
                if p["start"] <= int(source_start) < p["end"]:
                    return p
        for p in pages:
            if p.get("case_id") == case_id:
                return p
        if project:
            for p in pages:
                if project in p.get("text", ""):
                    return p
        return pages[0] if pages else None
