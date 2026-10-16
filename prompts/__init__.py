"""prompts 包：外置提示词加载器。

竞赛对应条款：
  「参赛作品须同步提交…包括智能体编排框架、Tool、Prompt、Skill…等核心模块」

设计要点：
  · 提示词以 Markdown 存放于 prompts/，便于单独审阅与版本管理
  · 运行时读取，不内嵌在 Python 字符串里
  · `_schema.md` 是字段定义的唯一来源，提示词与校验器共享
"""
from __future__ import annotations

import re
from pathlib import Path

PROMPTS_DIR = Path(__file__).resolve().parent

#: 可用提示词名称 -> 文件名
AVAILABLE: dict[str, str] = {
    "extract_bid_notice": "extract_bid_notice.md",
    "schema": "_schema.md",
    "extract_table": "extract_table.md",
}


class PromptNotFound(KeyError):
    """请求的提示词不存在。"""


def load(name: str) -> str:
    """读取提示词原文（含 Markdown 标题，便于人工审阅）。

    name 可以是逻辑名（"extract_bid_notice"）或文件名（"extract_bid_notice.md"）。
    """
    filename = AVAILABLE.get(name, name)
    path = PROMPTS_DIR / filename
    if not path.is_file():
        raise PromptNotFound(
            f"提示词不存在：{name}。可用：{', '.join(sorted(AVAILABLE))}"
        )
    return path.read_text(encoding="utf-8")


def load_body(name: str) -> str:
    """读取提示词正文，去掉 Markdown 标题与引用块，得到可直接发给模型的纯文本。

    用途：模型只应看到指令本身，不应看到"这是外置提示词"这类元信息。
    """
    text = load(name)
    lines: list[str] = []
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("#") or s.startswith(">") or s.startswith("---"):
            continue
        lines.append(line)
    body = "\n".join(lines).strip()
    return re.sub(r"\n{3,}", "\n\n", body)


def digest(name: str) -> str:
    """提示词的 SHA256 —— 写进运行记录，便于评审核对"用的是哪一版提示词"。"""
    import hashlib
    return hashlib.sha256(load(name).encode("utf-8")).hexdigest()


__all__ = ["load", "load_body", "digest", "AVAILABLE", "PromptNotFound", "PROMPTS_DIR"]
