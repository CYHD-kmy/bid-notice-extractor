"""表格解析测试：验证单元格可回溯、合并单元格与行列不齐被如实记录。

运行：
    .venv\\Scripts\\python.exe tests/test_table.py
（需先运行 tools/make_table_sample.py 生成样本）
"""
from __future__ import annotations

import sys
from pathlib import Path

import pdfplumber

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.models import Confidence  # noqa: E402
from core.trace import Trace  # noqa: E402
from tools.table_extract_tool import TableExtractionTool  # noqa: E402

PASS = 0
FAIL = 0
ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "samples_fixtures" / "03_table_heavy.pdf"
OUT = ROOT / "tests" / "_out" / "table"


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


if not SAMPLE.exists():
    print(f"  [!] 样本不存在：{SAMPLE}")
    print("      请先运行： .venv\\Scripts\\python.exe tools/make_table_sample.py")
    sys.exit(1)

print("=" * 70)
print("0. 准备：按 prototype/run_demo.py 的方式解析页面（逐字符 + 坐标）")
print("=" * 70)

trace = Trace(OUT, truncate=True)
tool = TableExtractionTool(trace=trace)
all_tables = []
page_metas = []

with pdfplumber.open(SAMPLE) as pdf:
    for number, page in enumerate(pdf.pages, 1):
        chars = []
        for line in page.extract_text_lines():
            for ch in sorted(line["chars"], key=lambda c: c["x0"]):
                for letter in ch["text"]:
                    chars.append({"text": letter,
                                  "bbox": [round(ch[k], 3) for k in ("x0", "top", "x1", "bottom")]})
        text = "".join(ch["text"] for ch in chars)
        meta = {"file": "samples_fixtures/03_table_heavy.pdf", "case_id": SAMPLE.stem,
                "page": number, "width": page.width, "height": page.height,
                "start": 0, "end": len(text), "text": text, "chars": chars}
        page_metas.append(meta)
        tables = tool.extract(page, meta)
        all_tables.extend(tables)
        print(f"  第 {number} 页：文本 {len(text)} 字符，识别到 {len(tables)} 个表格")

print()
print("=" * 70)
print("1. 表格识别数量")
print("=" * 70)
check_true("至少识别到 3 个表格", len(all_tables) >= 3, f"实际 {len(all_tables)}")
for t in all_tables:
    print(f"    {t.table_id}  p{t.page}  {t.n_rows}行 x {t.n_cols}列  "
          f"表头置信度={t.header_confidence.value}  单元格={len(t.cells)}  "
          f"问题={len(t.parse_issues)}")

print()
print("=" * 70)
print("2. 单元格可回溯（每个有内容的单元格都应带坐标证据）")
print("=" * 70)
total = sum(len(t.cells) for t in all_tables)
with_ev = sum(1 for t in all_tables for c in t.cells if c.evidence is not None)
check_true(f"带证据的单元格数 > 0", with_ev > 0, f"{with_ev}/{total}")

first = all_tables[0]
sample_cell = next((c for c in first.cells if c.text.strip()), None)
check_true("首个非空单元格有证据", sample_cell is not None and sample_cell.evidence is not None)
if sample_cell and sample_cell.evidence:
    e = sample_cell.evidence
    print(f"    示例：单元格({sample_cell.row},{sample_cell.col}) = 「{sample_cell.text}」")
    print(f"          证据：{e.file} p{e.page}  引文「{e.quote}」  verified={e.verified}")
    print(f"          坐标：{e.bboxes[0].as_list() if e.bboxes else '无'}")
    check("证据已核验", e.verified, True)
    check_true("证据带坐标", len(e.bboxes) > 0)

print()
print("=" * 70)
print("3. 逐字引文可在页面文本中定位（证据有效性）")
print("=" * 70)
ok = 0
bad = 0
for t in all_tables:
    meta = next(m for m in page_metas if m["page"] == t.page)
    for c in t.cells:
        if c.evidence is None:
            continue
        if meta["text"][c.evidence.start - meta["start"]:c.evidence.end - meta["start"]] == c.evidence.quote:
            ok += 1
        else:
            bad += 1
check("定位校验：全部命中", bad, 0)
check_true("命中数量 > 0", ok > 0, f"命中 {ok}")

print()
print("=" * 70)
print("4. 结构可审性 + 合并单元格的如实处理")
print("=" * 70)
print("  说明：pdfplumber 0.11.10 会把每行补齐到相同列数，合并单元格表现为")
print("        「文本在第一格、其余格为空串」，因此不会出现行列不齐。")
print("        '行列不齐' 检查保留为防御性逻辑，但不假设它在本样本触发。")
issues_all = [i for t in all_tables for i in t.parse_issues]
check_true("parse_issues 字段始终存在（结构可审）",
           all(hasattr(t, "parse_issues") for t in all_tables))
print(f"    本样本实际记录的问题数：{len(issues_all)}")
for i in issues_all[:8]:
    print(f"    · {i}")

# 4b. 真实准确性指标：非空单元格的文本应能在页面文本层定位
meta_by_page = {m["page"]: m for m in page_metas}
nonempty = nonempty_with_ev = 0
for tb in all_tables:
    for c in tb.cells:
        if not (c.text or "").strip():
            continue
        nonempty += 1
        if c.evidence is not None:
            nonempty_with_ev += 1
check("非空单元格全部可定位", nonempty - nonempty_with_ev, 0)
check_true("非空单元格数量 > 0", nonempty > 0, f"{nonempty}")

# 4c. 合并单元格如实处理：跨列文本只出现一次
merged_text = "以上金额均为含税口径"
t2 = next((x for x in all_tables if x.page == 1 and x.n_rows == 2), None)
check_true("找到含跨列文本的表 2", t2 is not None)
if t2:
    hits = [c for c in t2.cells if merged_text in (c.text or "")]
    check("跨列文本只出现 1 次（未重复）", len(hits), 1)
    empty_pad = [c for c in t2.cells if (c.text or "") == ""]
    check_true("空补位单元格被保留（不强行对齐语义）", len(empty_pad) >= 1,
               f"空补位 {len(empty_pad)} 个")

print()
print("=" * 70)
print("5. 表头置信度")
print("=" * 70)
confs = [t.header_confidence for t in all_tables]
check_true("标准表（表1）为 HIGH", all_tables[0].header_confidence == Confidence.HIGH,
           f"实际 {all_tables[0].header_confidence.value}")
print(f"    各表置信度：{[c.value for c in confs]}")

print()
print("=" * 70)
print("6. 汇总与导出")
print("=" * 70)
s = TableExtractionTool.summary(all_tables)
print(f"    {s}")
check_true("summary.tables 与识别数一致", s["tables"] == len(all_tables))
check_true("summary 含证据计数", s["cells_with_evidence"] > 0)

n = TableExtractionTool.export_jsonl(OUT / "tables.jsonl", all_tables)
check("导出 JSONL 行数", n, len(all_tables))

import json
rows = [json.loads(l) for l in (OUT / "tables.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
check("每行有 table_id", all(r.get("table_id") for r in rows), True)
check("每行有 parse_issues 字段", all("parse_issues" in r for r in rows), True)
cell0 = next(c for r in rows for c in r["cells"] if c["evidence"])
check_true("单元格证据进 JSON", cell0["evidence"]["quote"] != "", True)

print()
print("=" * 70)
print("7. trace 事件")
print("=" * 70)
c = trace.counts()
check_true("有 table_parsed 事件", c.get("table_parsed", 0) >= 3, f"{c.get('table_parsed')}")
check_true("有 tool_called 事件", c.get("tool_called", 0) >= 1)

print()
print("=" * 70)
print(f"结果：PASS={PASS}  FAIL={FAIL}")
print("=" * 70)
sys.exit(1 if FAIL else 0)
