"""生成带复杂表格的合成样本 PDF：samples_fixtures/03_table_heavy.pdf

用途：验证 tools/table_extract_tool.py 的表格解析能力（竞赛方向 1 的考察点）。

刻意设计的难点（用来暴露解析工具的边界，而不是让它"看起来成功"）：
  表 1：标准三线表（表头 + 数值）—— 应高置信度解析
  表 2：含合并单元格（横跨多列）—— 应被记为 parse_issues 而非强行对齐
  表 3：列数不齐（末行少一格）—— 应被如实记录

数据均为虚构，不构成投资建议。
"""
from __future__ import annotations

import sys
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "samples_fixtures" / "03_table_heavy.pdf"

FONT_CANDIDATES = [
    ("SimHei", r"C:\Windows\Fonts\simhei.ttf"),
    ("SimSun", r"C:\Windows\Fonts\simsun.ttc"),
    ("ArialUnicode", r"C:\Windows\Fonts\msyh.ttc"),
    ("ArialUnicode", "/System/Library/Fonts/Supplemental/Arial Unicode.ttf"),
]


def pick_font() -> str:
    for name, path in FONT_CANDIDATES:
        if Path(path).exists():
            try:
                pdfmetrics.registerFont(TTFont(name, path))
                return name
            except Exception:
                continue
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    return "STSong-Light"


def draw_table(c, font, x, y, col_widths, rows, title, line_color=(0.55, 0.6, 0.68)):
    """画一个带边框的表格，返回表格底部 y 坐标。"""
    row_h = 24
    c.setFont(font, 12)
    c.setFillColorRGB(0.08, 0.16, 0.25)
    c.drawString(x, y + 10, title)

    c.setStrokeColorRGB(*line_color)
    c.setLineWidth(0.7)
    top = y - row_h
    total_w = sum(col_widths)

    for i, row in enumerate(rows):
        ry = top - i * row_h
        # 横线
        c.line(x, ry, x + total_w, ry)
        # 竖线
        cx = x
        c.line(cx, ry, cx, ry - row_h)
        for w in col_widths:
            cx += w
            c.line(cx, ry, cx, ry - row_h)
        # 文本
        c.setFont(font, 11 if i else 12)
        c.setFillColorRGB(0.15, 0.2, 0.26)
        tx = x
        for j, cell in enumerate(row):
            if cell is None:
                tx += col_widths[j]
                continue
            span = 1
            # 支持 ("跨列文本", n) 形式：跨 n 列
            text = cell
            if isinstance(cell, tuple):
                text, span = cell
            c.drawString(tx + 6, ry - row_h + 8, str(text))
            tx += sum(col_widths[j:j + span])
    c.line(x, top - len(rows) * row_h, x + total_w, top - len(rows) * row_h)
    return top - len(rows) * row_h


def main() -> None:
    font = pick_font()
    width, height = A4
    c = canvas.Canvas(str(OUT), pagesize=A4, invariant=1)
    c.setTitle("模拟中标结果汇总表（虚构数据）")
    c.setAuthor("比赛原型 / 合成样例")

    def header():
        c.setFillColorRGB(0.08, 0.16, 0.25)
        c.setFont(font, 20)
        c.drawString(48, height - 62, "关于多个项目中标结果的模拟公告")
        c.setFillColorRGB(0.65, 0.2, 0.12)
        c.setFont(font, 10)
        c.drawString(48, height - 86, "模拟数据：公司、机构及项目均为虚构；不构成投资建议。")
        c.setFillColorRGB(0.12, 0.17, 0.24)
        c.setFont(font, 12)
        c.drawString(48, height - 118, "披露日期：2026年10月13日")

    # ---------------- 第 1 页：标准表 ----------------
    header()
    y = height - 165
    y = draw_table(
        c, font, 48, y, [150, 110, 110, 90],
        [
            ["项目名称", "中标金额", "中标日期", "工期(天)"],
            ["青岚智慧园区配套工程", "人民币1,280.50万元", "2026年10月10日", "180"],
            ["北辰综合管廊一期工程", "人民币0.326亿元", "2026年10月11日", "240"],
            ["河畔智慧园区配套工程", "尚未确定", "2026年10月12日", ""],
        ],
        "表 1  各项目中标金额明细",
    )

    y -= 40
    draw_table(
        c, font, 48, y, [180, 130, 150],
        [
            ["合计项目数", "3 个", "统计口径：本公告"],
            [("以上金额均为含税口径", 2), "—"],
        ],
        "表 2  汇总（含跨列标题，用于检验合并单元格处理）",
    )

    c.setFont(font, 9)
    c.setFillColorRGB(0.45, 0.5, 0.56)
    c.drawString(48, 40, "样例编号：03_table_heavy | 第 1 页 / 共 1 页 | 表格为合成数据")
    c.showPage()

    # ---------------- 第 2 页：列数不齐 ----------------
    header()
    y = height - 165
    draw_table(
        c, font, 48, y, [110, 100, 100, 100],
        [
            ["序号", "项目编号", "金额", "备注"],
            ["1", "XM-2026-001", "1,280.50万", "已公示"],
            ["2", "XM-2026-002", "3,260.00万"],
            ["3", "XM-2026-003", "待定", "复核中"],
        ],
        "表 3  项目清单（末行缺一格，用于检验行列不齐的记录）",
    )
    c.setFont(font, 9)
    c.setFillColorRGB(0.45, 0.5, 0.56)
    c.drawString(48, 40, "样例编号：03_table_heavy | 第 2 页 / 共 2 页")
    c.showPage()
    c.save()
    print(f"created {OUT}  (font={font})")


if __name__ == "__main__":
    sys.exit(main())
