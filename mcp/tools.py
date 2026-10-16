"""MCP 工具定义：把本项目的原子工具暴露为 MCP 工具。

设计原则：
  · **只暴露确定性工具**（计算、归一化、证据核验、表格解析、能力清单）
    —— 这些不依赖模型，评审可在无 GPU／无 Ollama 环境下直接验证
  · 每个工具显式声明 JSON Schema，输入输出都是可 JSON 化的数据结构
  · 金额一律用 **Decimal 字符串**，绝不使用二进制浮点
  · 计算返回完整的"算式留痕"（calc_id / operands / rounding / trace_note）

竞赛对应条款：
  「参赛作品须同步提交…包括智能体编排框架、Tool、Prompt、Skill、**MCP**…等核心模块」
"""
from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core.models import CalculationEngine, Operand, ReviewStatus      # noqa: E402
from core.trace import Trace                                          # noqa: E402
from tools.calculate_tool import CalculationTool, UNIT_FACTORS        # noqa: E402
from tools.evidence_tool import verify_evidence                       # noqa: E402

_PROTO = _ROOT / "prototype"
if str(_PROTO) not in sys.path:
    sys.path.insert(0, str(_PROTO))
from validation import normalize_amount, normalize_date               # noqa: E402


# ======================================================================
# 工具实现（纯函数：输入 JSON -> 输出 JSON）
# ======================================================================

def tool_calculate_unit_convert(amount: str, unit: str,
                                label: str = "金额", source: str = "literal") -> dict:
    """把带单位的金额换算成「元」，并返回完整算式留痕。"""
    tool = CalculationTool(trace=None)
    try:
        value = Decimal(str(amount))
    except Exception as exc:                                    # noqa: BLE001
        return {"ok": False, "error": f"amount 无法解析为十进制：{exc}"}
    calc = tool.to_base_unit(label=label, amount=value, unit=unit, source=source)
    return {"ok": calc.is_valid, "calc": calc.to_dict(),
            "supported_units": sorted(UNIT_FACTORS)}


def tool_calculate_ratio(numerator: str, denominator: str, unit: str = "元",
                         label: str = "占比", places: int = 2) -> dict:
    """计算百分数占比，返回算式留痕。分母为 0 时**拒绝计算**。"""
    eng = CalculationEngine(prefix="R")
    try:
        a = Operand(label=label + "分子", value=Decimal(str(numerator)), unit=unit, source="literal")
        b = Operand(label=label + "分母", value=Decimal(str(denominator)), unit=unit, source="literal")
    except Exception as exc:                                    # noqa: BLE001
        return {"ok": False, "error": f"输入无法解析为十进制：{exc}"}
    calc = eng.ratio(a, b, places)
    return {"ok": calc.is_valid, "calc": calc.to_dict()}


def tool_calculate_yoy(current: str, prior: str, unit: str = "元",
                       places: int = 2) -> dict:
    """同比 =（本期 − 上期）/ 上期 × 100%。返回**两步**计算记录。"""
    eng = CalculationEngine(prefix="Y")
    try:
        cur = Operand(label="本期", value=Decimal(str(current)), unit=unit, source="literal")
        pri = Operand(label="上期", value=Decimal(str(prior)), unit=unit, source="literal")
    except Exception as exc:                                    # noqa: BLE001
        return {"ok": False, "error": f"输入无法解析为十进制：{exc}"}
    before = len(eng.history)
    result = eng.yoy(cur, pri, places)
    steps = eng.history[before:] or [result]
    return {"ok": result.is_valid, "calc": result.to_dict(),
            "steps": [c.to_dict() for c in steps]}


def tool_normalize_amount(raw: str, currency: str | None = None) -> dict:
    """金额归一化（复用 prototype/validation.py 的既有规则，未重写）。"""
    return normalize_amount(raw, currency)


def tool_normalize_date(raw: str) -> dict:
    """日期归一化：只接受完整年月日，**不补齐缺失的月/日**。"""
    return normalize_date(raw)


def tool_verify_evidence(file: str, page: int, start: int, end: int,
                         quote: str, pages: list[dict]) -> dict:
    """核验一条证据：引文必须能在对应页面的文本层中按偏移原样取回。"""
    from core.models import Evidence as _Evidence
    ev = _Evidence(file=file, page=page, start=int(start), end=int(end),
                   quote=quote, bboxes=[], verified=False)
    ev.verified = verify_evidence(pages, ev)
    return {"ok": True, "verified": ev.verified, "evidence": ev.to_dict()}


def tool_registry_list() -> dict:
    """返回能力清单（技能/工具/提示词/环境约束），供 MCP 客户端发现能力。"""
    from agent.registry import build_registry
    return build_registry()


# ======================================================================
# MCP 工具清单（名称 / 说明 / JSON Schema / 处理函数）
# ======================================================================

TOOLS: list[dict] = [
    {
        "name": "calculate_unit_convert",
        "description": "把带单位的金额换算成「元」，返回含 calc_id、算式、舍入方式的完整留痕",
        "inputSchema": {
            "type": "object",
            "properties": {
                "amount": {"type": "string", "description": "十进制金额字符串，如 '1280.50'"},
                "unit": {"type": "string", "enum": sorted(UNIT_FACTORS)},
                "label": {"type": "string", "default": "金额"},
                "source": {"type": "string", "default": "literal"},
            },
            "required": ["amount", "unit"],
        },
        "handler": tool_calculate_unit_convert,
    },
    {
        "name": "calculate_ratio",
        "description": "计算百分数占比（分母为 0 时拒绝计算并说明原因）",
        "inputSchema": {
            "type": "object",
            "properties": {
                "numerator": {"type": "string"},
                "denominator": {"type": "string"},
                "unit": {"type": "string", "default": "元"},
                "label": {"type": "string", "default": "占比"},
                "places": {"type": "integer", "default": 2},
            },
            "required": ["numerator", "denominator"],
        },
        "handler": tool_calculate_ratio,
    },
    {
        "name": "calculate_yoy",
        "description": "计算同比（分「差额」与「比率」两步，两步都留痕）",
        "inputSchema": {
            "type": "object",
            "properties": {
                "current": {"type": "string"},
                "prior": {"type": "string"},
                "unit": {"type": "string", "default": "元"},
                "places": {"type": "integer", "default": 2},
            },
            "required": ["current", "prior"],
        },
        "handler": tool_calculate_yoy,
    },
    {
        "name": "normalize_amount",
        "description": "金额归一化：拦截预算/合计口径，缺失返回 null 而非 0",
        "inputSchema": {
            "type": "object",
            "properties": {
                "raw": {"type": "string"},
                "currency": {"type": ["string", "null"]},
            },
            "required": ["raw"],
        },
        "handler": tool_normalize_amount,
    },
    {
        "name": "normalize_date",
        "description": "日期归一化为 ISO 格式；不完整日期拒绝归一化",
        "inputSchema": {
            "type": "object",
            "properties": {"raw": {"type": "string"}},
            "required": ["raw"],
        },
        "handler": tool_normalize_date,
    },
    {
        "name": "verify_evidence",
        "description": "核验逐字证据：引文能否在页面文本层按偏移原样取回",
        "inputSchema": {
            "type": "object",
            "properties": {
                "file": {"type": "string"},
                "page": {"type": "integer"},
                "start": {"type": "integer"},
                "end": {"type": "integer"},
                "quote": {"type": "string"},
                "pages": {"type": "array", "items": {"type": "object"}},
            },
            "required": ["file", "page", "start", "end", "quote", "pages"],
        },
        "handler": tool_verify_evidence,
    },
    {
        "name": "registry_list",
        "description": "列出本系统的技能、工具、提示词（含 SHA256）与数据环境约束",
        "inputSchema": {"type": "object", "properties": {}},
        "handler": tool_registry_list,
    },
]

TOOLS_BY_NAME: dict[str, dict] = {t["name"]: t for t in TOOLS}


def list_tools() -> list[dict]:
    """MCP tools/list 的返回体（去掉内部 handler）。"""
    return [{k: v for k, v in t.items() if k != "handler"} for t in TOOLS]


def call_tool(name: str, arguments: dict) -> dict:
    """MCP tools/call 的执行入口。"""
    entry = TOOLS_BY_NAME.get(name)
    if entry is None:
        return {"isError": True,
                "content": [{"type": "text",
                             "text": f"未知工具：{name}。可用：{', '.join(sorted(TOOLS_BY_NAME))}"}]}
    import json as _json
    try:
        result = entry["handler"](**(arguments or {}))
    except TypeError as exc:
        return {"isError": True,
                "content": [{"type": "text", "text": f"参数错误：{exc}"}]}
    except Exception as exc:                                    # noqa: BLE001
        return {"isError": True,
                "content": [{"type": "text", "text": f"{type(exc).__name__}: {exc}"}]}
    return {
        "isError": bool(isinstance(result, dict) and result.get("ok") is False),
        "content": [{"type": "text", "text": _json.dumps(result, ensure_ascii=False, indent=2)}],
        "structuredContent": result,
    }
