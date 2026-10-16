"""断言工具：把分析结论包装成「事实 / 推论 / 观点」三类可审计断言。

竞赛对应条款：
  「应说明主要假设、适用范围和风险因素，并明确区分事实、推论与观点」

强制不变量（由 core.models.Assertion.validate 执行）：
  · fact      -> 必须有 verified=True 的逐字证据，否则拒绝入报告
  · inference -> 必须引用至少一条有效 calc_id
  · opinion   -> 必须写明适用边界（limitations）

本工具只负责**构造与校验**，不生成自然语言（内容仍由模型/技能提供）。
"""
from __future__ import annotations

from typing import Iterable

from core.models import (
    Assertion, AssertionKind, Confidence, Evidence, ReviewStatus,
)
from core.trace import Trace


class AssertionTool:
    """断言工厂 + 校验器。"""

    name = "assertion"

    def __init__(self, trace: Trace | None = None, prefix: str = "A") -> None:
        self.trace = trace
        self._n = 0
        self._prefix = prefix
        self.assertions: list[Assertion] = []
        self.rejected: list[Assertion] = []

    # ------------------------------------------------------------------ 内部
    def _next_id(self) -> str:
        self._n += 1
        return f"{self._prefix}{self._n:04d}"

    def _register(self, a: Assertion, known_calcs: set[str],
                  known_assumptions: set[str]) -> Assertion:
        issues = a.validate(known_calcs, known_assumptions)
        if issues:
            self.rejected.append(a)
            if self.trace is not None:
                self.trace.assertion_rejected(a)
        else:
            self.assertions.append(a)
            if self.trace is not None:
                self.trace.assertion_created(a)
        return a

    # ------------------------------------------------------------------ 三类构造
    def fact(self, text: str, evidence: Iterable[Evidence],
             known_calcs: set[str] | None = None,
             known_assumptions: set[str] | None = None,
             confidence: Confidence = Confidence.HIGH,
             calculations: Iterable[str] = ()) -> Assertion:
        """事实类断言：必须带已核验的逐字证据。"""
        a = Assertion(
            assertion_id=self._next_id(), kind=AssertionKind.FACT, text=text,
            evidence=list(evidence), calculations=list(calculations),
            confidence=confidence,
        )
        return self._register(a, known_calcs or set(), known_assumptions or set())

    def inference(self, text: str, calculations: Iterable[str],
                  evidence: Iterable[Evidence] = (),
                  assumptions: Iterable[str] = (),
                  known_calcs: set[str] | None = None,
                  known_assumptions: set[str] | None = None,
                  confidence: Confidence = Confidence.MEDIUM,
                  limitations: str = "") -> Assertion:
        """推论类断言：必须引用有效计算记录。"""
        a = Assertion(
            assertion_id=self._next_id(), kind=AssertionKind.INFERENCE, text=text,
            evidence=list(evidence), calculations=list(calculations),
            assumptions=list(assumptions), confidence=confidence,
            limitations=limitations,
        )
        return self._register(a, known_calcs or set(), known_assumptions or set())

    def opinion(self, text: str, limitations: str,
                evidence: Iterable[Evidence] = (),
                assumptions: Iterable[str] = (),
                known_calcs: set[str] | None = None,
                known_assumptions: set[str] | None = None,
                confidence: Confidence = Confidence.LOW) -> Assertion:
        """观点类断言：必须写明适用边界。"""
        a = Assertion(
            assertion_id=self._next_id(), kind=AssertionKind.OPINION, text=text,
            evidence=list(evidence), assumptions=list(assumptions),
            confidence=confidence, limitations=limitations,
        )
        return self._register(a, known_calcs or set(), known_assumptions or set())

    # ------------------------------------------------------------------ 汇总
    def summary(self) -> dict:
        def cnt(kind: AssertionKind) -> int:
            return sum(1 for a in self.assertions if a.kind == kind)
        return {
            "accepted": len(self.assertions),
            "rejected": len(self.rejected),
            "fact": cnt(AssertionKind.FACT),
            "inference": cnt(AssertionKind.INFERENCE),
            "opinion": cnt(AssertionKind.OPINION),
            "rejected_detail": [
                {"assertion_id": a.assertion_id, "kind": a.kind.value, "issues": list(a.issues)}
                for a in self.rejected
            ],
        }

    def export_jsonl(self, path) -> int:
        """把断言集写成 JSONL（含被拒绝的，便于评审核查"拦下了什么"）。"""
        import json
        from pathlib import Path
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        rows = self.assertions + self.rejected
        with path.open("w", encoding="utf-8") as f:
            for a in rows:
                f.write(json.dumps(a.to_dict(), ensure_ascii=False) + "\n")
        return len(rows)


# ----------------------------------------------------------------------
# 从字段值自动构造「事实」断言（抽取场景的通用做法）
# ----------------------------------------------------------------------

FIELD_LABELS = {
    "company": "中标公司",
    "project": "项目名称",
    "bidder": "招标方",
    "award_amount_raw": "中标金额原文",
    "currency": "币种",
    "award_date": "中标日期",
    "disclosure_date": "披露日期",
}

# 不生成事实断言的字段（原始串由归一化结果表达，避免报告里重复啰嗦）
SKIP_FACT_FIELDS = {"award_amount_raw", "currency"}


def facts_from_record(tool: AssertionTool, record: dict,
                      evidence: dict[str, Evidence],
                      known_calcs: set[str] | None = None) -> list[Assertion]:
    """为一条抽取记录生成事实类断言。

    只对**有已核验证据**的字段生成；无证据的字段不生成断言（而不是生成后拒绝），
    这样可以区分「模型没抽到」与「抽到了但无法回溯」两种情况。
    """
    out: list[Assertion] = []
    for field in ("company", "project", "bidder", "award_date", "disclosure_date"):
        value = record.get(field)
        if value is None or field in SKIP_FACT_FIELDS:
            continue
        ev = evidence.get(field)
        if ev is None or not ev.verified:
            continue
        label = FIELD_LABELS.get(field, field)
        out.append(tool.fact(
            f"{label}为「{value}」",
            evidence=[ev],
            known_calcs=known_calcs,
        ))
    return out


def amount_fact(tool: AssertionTool, record: dict,
                evidence: dict[str, Evidence],
                calc_ids: Iterable[str],
                known_calcs: set[str] | None = None) -> Assertion | None:
    """金额事实：原文 + 归一化结果（引用了单位换算的计算记录）。"""
    raw = record.get("award_amount_raw")
    ev = evidence.get("award_amount_raw")
    if raw is None or ev is None or not ev.verified:
        return None
    return tool.fact(
        f"中标金额原文为「{raw}」",
        evidence=[ev],
        calculations=list(calc_ids),
        known_calcs=known_calcs,
    )
