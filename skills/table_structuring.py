"""技能：表格结构化。

编排：table_extract_tool（结构 + 坐标）→ 可选的表头语义理解（外置提示词）
本原型**默认不调用模型**：表头识别由 table_extract_tool 的规则完成，
提示词 `extract_table.md` 保留给"需要理解表头语义"的扩展场景，
以便评审看到 Skill 与 Prompt 的对应关系。

竞赛对应条款：
  「表格解析准确性」（方向 1 明确考察点）
"""
from __future__ import annotations

from core.models import Confidence, ReviewStatus, Table
from skills.base import Skill, SkillResult
from tools.table_extract_tool import TableExtractionTool


class TableStructuringSkill(Skill):
    name = "table_structuring"
    description = "从 PDF 解析表格结构与单元格坐标，输出可回溯的结构化表格"
    uses_tools = ("table_extract",)
    uses_prompts = ("extract_table",)

    def __init__(self, trace=None, prefix: str = "T") -> None:
        super().__init__(trace)
        self.tool = TableExtractionTool(trace=trace, prefix=prefix)

    def run(self, pages_pdf: list[tuple]) -> SkillResult:
        """pages_pdf: [(pdfplumber_page, page_meta), ...] —— 需保持页面顺序。"""
        self._log_start(pages=len(pages_pdf))
        tables: list[Table] = []
        for page, meta in pages_pdf:
            tables.extend(self.tool.extract(page, meta))

        issues: list[str] = []
        for t in tables:
            issues.extend(f"{t.table_id} · {i}" for i in t.parse_issues)
            if t.header_confidence == Confidence.LOW:
                issues.append(f"{t.table_id} · 表头置信度低，需人工确认表头行")

        s = TableExtractionTool.summary(tables)
        result = SkillResult(
            skill=self.name,
            status=ReviewStatus.NEEDS_REVIEW if issues else ReviewStatus.VALID,
            payload={"tables": tables},
            issues=issues,
            metrics={k: v for k, v in s.items() if k != "issues"},
        )
        return self._log_end(result)
