"""技能：报告组装。

把「记录 + 计算 + 断言 + 假设」组装成 ReportTool 需要的视图，并调用报告生成。
本技能是流水线的最后一环，也是**唯一**会因"无证据的事实"而失败的环节。

竞赛对应条款：
  「最终成果应以结构化数据、表格或分析报告等形式呈现，不得仅提交自然语言对话记录」
  「明确区分事实、推论与观点」
  「说明主要假设、适用范围和风险因素」
"""
from __future__ import annotations

from pathlib import Path

from core.models import (
    Assertion, Assumption, Calculation, Record, ReviewStatus,
)
from skills.base import Skill, SkillResult
from tools.report_tool import (
    RecordView, ReportContext, ReportError, ReportTool,
)


class ReportAssemblySkill(Skill):
    name = "report_assembly"
    description = "把记录、计算、断言、假设组装成七节分析报告（Markdown + JSON）"
    uses_tools = ("report", "assertion", "calculate")
    uses_prompts = ("schema",)

    def __init__(self, trace=None) -> None:
        super().__init__(trace)
        self.tool = ReportTool(trace=trace)

    # ------------------------------------------------------------------
    def run(self, records: list[Record], calculations: list[Calculation],
            assertions: list[Assertion], rejected: list[Assertion],
            assumptions: list[Assumption], ctx: ReportContext,
            out_dir: Path) -> SkillResult:
        self._log_start(records=len(records), calculations=len(calculations),
                        assertions=len(assertions), rejected=len(rejected))

        views = [self._to_view(r) for r in records]
        try:
            doc = self.tool.write(out_dir, ctx, views, calculations,
                                  assertions, assumptions, rejected)
        except ReportError as exc:
            # 报告生成失败是**设计行为**：宁可不出报告，不出错报告
            if self.trace is not None:
                self.trace.log("report_generated", ok=False, error=str(exc))
            return self._log_end(SkillResult(
                skill=self.name, status=ReviewStatus.REJECTED,
                payload=None, issues=[f"报告生成被拒绝：{exc}"],
                metrics={"rejected": True},
            ))

        counts = doc["counts"]
        result = SkillResult(
            skill=self.name,
            status=ReviewStatus.VALID,
            payload={"doc": doc, "md": (Path(out_dir) / "report.md").read_text(encoding="utf-8")},
            issues=[],
            metrics={
                "report_md": str(Path(out_dir) / "report.md"),
                "report_json": str(Path(out_dir) / "report.json"),
                "fact": counts["assertions_fact"],
                "inference": counts["assertions_inference"],
                "opinion": counts["assertions_opinion"],
                "rejected_assertions": counts["assertions_rejected"],
                "calculations": counts["calculations_total"],
            },
        )
        return self._log_end(result)

    # ------------------------------------------------------------------
    @staticmethod
    def _to_view(r: Record) -> RecordView:
        """Record（新模型）-> RecordView（报告渲染视图）。"""
        norm = (r.normalized or {}).get("award_amount") or {}
        return RecordView(
            case_id=r.case_id,
            project=r.record.get("project") or "",
            fields={k: r.record.get(k) for k in r.record},
            normalized_amount=norm or None,
            evidence=r.evidence,
            calculations=list(r.calculations),
            issues=list(r.validation_issues),
            status=r.validation_status.value,
        )
