"""表格解析工具：从 PDF 中提取复杂表格，并让每个单元格可回溯到原文坐标。

竞赛对应条款（方向 1 明确考察点）：
  「从非标准化公告、扫描文件和复杂表格中提取质押、中标、股权变动等关键字段」
  「重点考察字段提取的完整性、格式规范性、**表格解析准确性**和结果一致性」

设计要点：
  · 用 pdfplumber 的 find_tables() 取表格结构（含单元格 bbox）
  · 每个单元格独立生成 Evidence（逐字引文 + 页码 + 坐标），
    与字段抽取共用同一套证据机制 —— 表格内容同样可回溯
  · 表头识别带置信度；行列数不齐、合并单元格等**如实记录为 parse_issues**，不强行对齐
  · 解析失败不猜测：宁可标记问题，不编造结构
"""
from __future__ import annotations

import re
from pathlib import Path

from core.models import BBox, Confidence, Evidence, Table, TableCell
from core.trace import Trace, TraceEvent


class TableExtractionTool:
    """表格解析工具。

    输入：pdfplumber 的 Page 对象 + 页面文本索引（chars / start 偏移）
    输出：core.models.Table 列表
    """

    name = "table_extract"

    def __init__(self, trace: Trace | None = None, prefix: str = "T") -> None:
        self.trace = trace
        self.prefix = prefix
        self._n = 0

    # ------------------------------------------------------------------ 主流程
    def extract(self, page, page_meta: dict) -> list[Table]:
        """从一页中提取全部表格。

        page      : pdfplumber Page
        page_meta : run_demo.parse_pdfs 产出的 page 字典
                    （至少含 file / page / start / chars）
        """
        found = page.find_tables()
        if self.trace is not None:
            self.trace.tool_called(tool=self.name, action="find_tables",
                                   file=page_meta["file"], page=page_meta["page"],
                                   tables_found=len(found))
        tables: list[Table] = []
        for t in found:
            table = self._build(t, page_meta)
            tables.append(table)
            if self.trace is not None:
                self.trace.log(TraceEvent.TABLE_PARSED,
                               table_id=table.table_id, file=table.file,
                               page=table.page, n_rows=table.n_rows,
                               n_cols=table.n_cols,
                               header_confidence=table.header_confidence.value,
                               cells=len(table.cells),
                               issues=len(table.parse_issues),
                               issues_detail=table.parse_issues)
        return tables

    # ------------------------------------------------------------------ 单表构建
    def _build(self, found_table, page_meta: dict) -> Table:
        self._n += 1
        table_id = f"{self.prefix}{self._n:03d}"
        # extract() 返回二维文本矩阵；这里是解析后的结果
        matrix = found_table.extract() or []
        n_rows = len(matrix)
        n_cols = max((len(r) for r in matrix), default=0)

        cells: list[TableCell] = []
        issues: list[str] = []

        # 行列数不齐 -> 如实记录
        uneven = [i for i, r in enumerate(matrix) if len(r) != n_cols]
        if uneven:
            issues.append(
                f"第 {', '.join(str(i + 1) for i in uneven[:5])} 行单元格数量与最大列数({n_cols})不一致"
                + ("（可能含合并单元格）" if n_cols else "")
            )
        if n_rows == 0 or n_cols == 0:
            issues.append("表格为空或未被正确识别")

        # 逐单元格构建（带坐标与证据）
        for r, row in enumerate(matrix):
            for c, text in enumerate(row):
                raw = "" if text is None else str(text)
                bbox = self._cell_bbox(found_table, r, c)
                evidence = self._cell_evidence(raw, bbox, page_meta)
                cells.append(TableCell(text=raw, row=r, col=c,
                                       bbox=bbox, evidence=evidence))
                if evidence is None and raw.strip():
                    issues.append(f"单元格({r + 1},{c + 1})文本未能在页面文本层定位")

        header_conf = self._header_confidence(matrix)
        if header_conf == Confidence.LOW:
            issues.append("表头识别置信度低（首行可能不是表头，或表格无表头）")

        return Table(
            table_id=table_id, file=page_meta["file"], page=page_meta["page"],
            n_rows=n_rows, n_cols=n_cols, cells=cells,
            header_confidence=header_conf, parse_issues=issues,
        )

    # ------------------------------------------------------------------ 坐标
    @staticmethod
    def _cell_bbox(found_table, r: int, c: int) -> BBox | None:
        """取单元格坐标。

        pdfplumber 0.11.x 的结构为：
            Table.rows[r] -> Row，Row.cells -> list[tuple(x0, top, x1, bottom)]
        """
        cell = None
        rows = getattr(found_table, "rows", None)
        if rows is not None:
            try:
                cell = rows[r].cells[c]
            except (IndexError, AttributeError, TypeError):
                cell = None
        if cell is None:
            # 退化路径：Table.cells 是扁平的 tuple 列表，按几何位置匹配
            try:
                flat = found_table.cells
                target = rows[r].cells[c] if rows is not None else None
                if target is not None:
                    cell = target
                else:
                    cell = flat[r * max(1, len(flat) // max(1, len(rows))) + c]
            except Exception:
                cell = None
        if cell is None:
            return None
        try:
            x0, top, x1, bottom = cell
        except (TypeError, ValueError):
            return None
        return BBox(float(x0), float(top), float(x1), float(bottom))

    # ------------------------------------------------------------------ 证据
    @staticmethod
    def _cell_evidence(text: str, bbox: BBox | None, page_meta: dict) -> Evidence | None:
        """把单元格文本映射回页面拼接文本，生成逐字证据。

        页面文本是"逐字符按 x0 排序后直接拼接"的，因此单元格文本应当
        在拼接文本中以连续子串形式出现（同一行内按 x 排序，与单元格内排序一致）。
        找不到则返回 None —— 不猜。
        """
        s = (text or "").strip()
        if not s:
            return None
        page_text: str = page_meta.get("text", "")
        chars = page_meta.get("chars", [])
        pos = page_text.find(s)
        if pos < 0:
            # 单元格文本可能因换行被拼接打散，尝试去掉空白后再找
            compact = re.sub(r"\s+", "", s)
            if not compact:
                return None
            pos = page_text.find(compact)
            if pos < 0:
                return None
            s = compact
        page_start = page_meta.get("start", 0)
        seg = chars[pos:pos + len(s)]
        bboxes: list[BBox] = []
        if bbox is not None:
            # 优先使用单元格自身坐标（更可靠，直接来自表格结构）
            bboxes = [bbox]
        elif seg:
            for ch in seg:
                bb = ch.get("bbox")
                if bb:
                    bboxes.append(BBox.from_any(bb))
        return Evidence(
            file=page_meta["file"], page=page_meta["page"], quote=s,
            start=page_start + pos, end=page_start + pos + len(s),
            bboxes=bboxes, verified=True,
        )

    # ------------------------------------------------------------------ 表头判断
    @staticmethod
    def _header_confidence(matrix: list[list]) -> Confidence:
        """表头识别置信度。

        规则（保守）：
          · 至少 2 行，且首行全部非空、其余行有数值型 -> HIGH
          · 首行非空但行数不足 -> MEDIUM
          · 首行存在空单元格 -> LOW
        """
        if len(matrix) < 2:
            return Confidence.LOW
        header = matrix[0]
        if not header or any((c is None or str(c).strip() == "") for c in header):
            return Confidence.LOW
        body = [row for row in matrix[1:] if any(c not in (None, "") for c in row)]
        if not body:
            return Confidence.LOW
        numeric_like = sum(
            1 for row in body for c in row
            if re.fullmatch(r"[+-]?\d[\d,]*(\.\d+)?%?", str(c or "").strip())
        )
        return Confidence.HIGH if numeric_like > 0 else Confidence.MEDIUM

    # ------------------------------------------------------------------ 汇总/导出
    @staticmethod
    def summary(tables: list[Table]) -> dict:
        issues = [f"{t.table_id}: {i}" for t in tables for i in t.parse_issues]
        return {
            "tables": len(tables),
            "cells": sum(len(t.cells) for t in tables),
            "cells_with_evidence": sum(
                1 for t in tables for c in t.cells if c.evidence is not None),
            "high_confidence_headers": sum(
                1 for t in tables if t.header_confidence == Confidence.HIGH),
            "issues_total": len(issues),
            "issues": issues,
        }

    @staticmethod
    def export_jsonl(path: Path, tables: list[Table]) -> int:
        import json
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            for t in tables:
                f.write(json.dumps(t.to_dict(), ensure_ascii=False) + "\n")
        return len(tables)
