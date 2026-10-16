"""证据工具：把字段值回溯到原文的页码与坐标。

从 prototype/run_demo.py 的 locate() **原样迁移**，算法不变：
  · 在页面拼接文本中查找字段值（逐字匹配）
  · 出现多次时取离锚点最近的一处
  · 跨物理行时合并成多个矩形（bboxes）
  · 找不到返回 None —— 不猜

竞赛对应条款：
  「数据来源可核验」—— 每个字段值都要能指回原文的逐字引文与坐标。
"""
from __future__ import annotations

from core.models import BBox, Evidence

#: 金额必须紧邻这些标签，否则怀疑是预算/合计（与 run_demo 保持一致）
AMOUNT_LABELS = ("中标金额", "中标价")

#: 标签前视窗口（字符数）
AMOUNT_CONTEXT_WINDOW = 12


def locate(page: dict, raw, anchor: int = 0) -> Evidence | None:
    """在页面中定位 raw 的逐字位置，返回带坐标的 Evidence。

    page 需含：file / page / start / text / chars
    anchor 是用于消歧的参考偏移（通常是事件对齐位置在页内的偏移）。
    """
    if raw is None or not isinstance(raw, str) or not raw:
        return None
    text: str = page["text"]
    candidates, offset = [], 0
    while True:
        pos = text.find(raw, offset)
        if pos < 0:
            break
        candidates.append(pos)
        offset = pos + len(raw)
    if not candidates:
        return None
    pos = min(candidates, key=lambda p: abs(p - anchor))
    chars = page["chars"][pos:pos + len(raw)]

    # 同一物理行内的字符合并为一个矩形；换行则新开一个矩形
    rectangles: list[BBox] = []
    for ch in chars:
        b = BBox.from_any(ch["bbox"])
        if rectangles and abs(rectangles[-1].top - b.top) < 2 and b.x0 >= rectangles[-1].x0:
            rectangles[-1].x1 = max(rectangles[-1].x1, b.x1)
            rectangles[-1].bottom = max(rectangles[-1].bottom, b.bottom)
        else:
            rectangles.append(BBox(b.x0, b.top, b.x1, b.bottom))

    return Evidence(
        file=page["file"], page=page["page"], quote=raw,
        start=page["start"] + pos, end=page["start"] + pos + len(raw),
        bboxes=rectangles, verified=True,
    )


def amount_is_labelled(page: dict, evidence: Evidence) -> bool:
    """检查金额证据前方是否紧邻「中标金额 / 中标价」标签。

    用途：拦截"把项目预算当中标金额"的错误（预算串用）。
    返回 False 表示未紧邻标签，应触发人工复核。
    """
    local_start = evidence.start - page["start"]
    context = page["text"][max(0, local_start - AMOUNT_CONTEXT_WINDOW):local_start]
    return any(label in context for label in AMOUNT_LABELS)


def verify_evidence(pages: list[dict], evidence: Evidence) -> bool:
    """复核一条证据：引文必须能在对应页面的文本层中按偏移取回。"""
    page = next((p for p in pages
                 if p["file"] == evidence.file and p["page"] == evidence.page), None)
    if page is None:
        return False
    local = evidence.start - page["start"]
    return page["text"][local:local + len(evidence.quote)] == evidence.quote


class EvidenceTool:
    """工具包装（落 trace）。纯函数 locate/verify 也可直接调用。"""

    name = "evidence"

    def __init__(self, trace=None) -> None:
        self.trace = trace

    def locate(self, page: dict, raw, anchor: int = 0) -> Evidence | None:
        ev = locate(page, raw, anchor)
        if self.trace is not None:
            self.trace.tool_called(tool=self.name, action="locate",
                                   file=page.get("file"), page=page.get("page"),
                                   quote=(raw[:40] if isinstance(raw, str) else None),
                                   found=ev is not None)
        return ev

    def verify(self, pages: list[dict], evidence: Evidence) -> bool:
        ok = verify_evidence(pages, evidence)
        if self.trace is not None:
            self.trace.tool_called(tool=self.name, action="verify",
                                   file=evidence.file, page=evidence.page,
                                   quote=evidence.quote[:40], ok=ok)
        return ok
