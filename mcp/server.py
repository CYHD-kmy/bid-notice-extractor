"""MCP 服务：JSON-RPC 2.0 over stdio，把 tools.py 的工具暴露给 MCP 客户端。

支持两种帧格式（自动识别，便于用管道直接测试）：
  · **Content-Length 帧**：MCP 官方 stdio 传输格式
  · **换行分隔 JSON（NDJSON）**：方便 `echo '...' | python mcp/server.py` 手工验证

已实现的 MCP 方法：
  initialize           握手，声明协议版本与能力
  tools/list           列出工具（含 JSON Schema）
  tools/call           调用工具
  notifications/initialized   客户端就绪通知（无响应）
  ping                 存活检查

启动：
  .venv\\Scripts\\python.exe mcp/server.py            # stdio 服务
  .venv\\Scripts\\python.exe mcp/server.py --selftest # 自检并退出

竞赛对应条款：
  「须同步提交…包括智能体编排框架、Tool、Prompt、Skill、MCP…等核心模块」
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from mcp.tools import call_tool, list_tools            # noqa: E402

PROTOCOL_VERSION = "2024-11-05"
SERVER_INFO = {"name": "bid-notice-extractor", "version": "1.0.0"}

#: 服务端能力声明
CAPABILITIES = {"tools": {"listChanged": False}}


def _ok(req_id, result) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _err(req_id, code: int, message: str, data=None) -> dict:
    e = {"code": code, "message": message}
    if data is not None:
        e["data"] = data
    return {"jsonrpc": "2.0", "id": req_id, "error": e}


def handle(request: dict) -> dict | None:
    """处理一条 JSON-RPC 请求。返回 None 表示这是通知，无需响应。"""
    method = request.get("method")
    req_id = request.get("id")
    params = request.get("params") or {}

    # ---- 通知类：无 id，不回复 ----
    if method == "notifications/initialized":
        return None
    if method in ("notifications/cancelled",):
        return None

    if method == "initialize":
        return _ok(req_id, {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": CAPABILITIES,
            "serverInfo": SERVER_INFO,
            "instructions": (
                "中标公告结构化抽取原型的能力接口。所有工具均为确定性实现，"
                "不调用模型；金额一律使用十进制字符串，计算返回完整算式留痕。"
            ),
        })

    if method == "ping":
        return _ok(req_id, {})

    if method == "tools/list":
        return _ok(req_id, {"tools": list_tools()})

    if method == "tools/call":
        name = params.get("name")
        if not name:
            return _err(req_id, -32602, "缺少参数 name")
        return _ok(req_id, call_tool(name, params.get("arguments") or {}))

    if req_id is None:
        return None                       # 未知通知，忽略
    return _err(req_id, -32601, f"未实现的方法：{method}")


# ======================================================================
# stdio 传输
# ======================================================================

def _read_message(stream) -> dict | None:
    """读一条消息。自动识别 Content-Length 帧与 NDJSON。"""
    while True:
        line = stream.readline()
        if not line:
            return None
        text = line.decode("utf-8", "replace").strip()
        if not text:
            continue
        if text.lower().startswith("content-length:"):
            try:
                length = int(text.split(":", 1)[1].strip())
            except ValueError:
                continue
            # 跳过 Content-Length 与 body 之间的空行
            while True:
                sep = stream.readline()
                if not sep or sep.strip() == b"":
                    break
            body = stream.read(length)
            return json.loads(body.decode("utf-8", "replace"))
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            continue                      # 忽略无法解析的行


def _write_message(stream, message: dict, framed: bool = False) -> None:
    payload = json.dumps(message, ensure_ascii=False).encode("utf-8")
    if framed:
        stream.write(b"Content-Length: %d\r\n\r\n" % len(payload))
    stream.write(payload)
    stream.write(b"\n")
    stream.flush()


def serve(stdin=None, stdout=None) -> int:
    stdin = stdin or sys.stdin.buffer
    stdout = stdout or sys.stdout.buffer
    framed = False
    while True:
        request = _read_message(stdin)
        if request is None:
            return 0
        if request.get("method") == "initialize":
            # 若客户端用 Content-Length 帧，则回复也用同样格式
            framed = bool(request.get("_framed", False))
        response = handle(request)
        if response is not None:
            _write_message(stdout, response, framed=framed)


# ======================================================================
# 自检
# ======================================================================

def selftest() -> int:
    """不启动服务，直接验证协议处理与工具调用。"""
    ok = True

    def check(label, cond, detail=""):
        nonlocal ok
        print(f"  {'PASS' if cond else 'FAIL'}  {label}" + ("" if cond else f"  {detail}"))
        ok = ok and cond

    r = handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    check("initialize 返回协议版本",
          r["result"]["protocolVersion"] == PROTOCOL_VERSION)
    check("initialize 声明 tools 能力", "tools" in r["result"]["capabilities"])

    r = handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
    names = [t["name"] for t in r["result"]["tools"]]
    check("tools/list 返回 7 个工具", len(names) == 7, str(names))
    check("每个工具都有 JSON Schema",
          all("inputSchema" in t for t in r["result"]["tools"]))

    r = handle({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {
        "name": "calculate_unit_convert",
        "arguments": {"amount": "1280.50", "unit": "万元", "label": "中标金额"}}})
    sc = r["result"]["structuredContent"]
    # 注意：to_dict() 用 decimal_str() 规范化，会去掉尾随零，
    # 因此 12805000.00 的对外形式是 "12805000"（这是有意的统一契约）
    serialized = json.loads(json.dumps(sc, default=str))
    check("单位换算结果正确（去尾零后为 12805000）",
          serialized["calc"]["result"] == "12805000", serialized["calc"]["result"])
    check("返回算式留痕", "× 10000" in sc["calc"]["trace_note"])
    check("返回舍入方式说明", bool(sc["calc"]["rounding"]))

    r = handle({"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {
        "name": "calculate_ratio",
        "arguments": {"numerator": "12805000", "denominator": "15000000"}}})
    sc = r["result"]["structuredContent"]
    check("占比结果正确（85.37）", sc["calc"]["result"] == "85.37", str(sc["calc"]["result"]))

    r = handle({"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {
        "name": "calculate_ratio",
        "arguments": {"numerator": "100", "denominator": "0"}}})
    sc = r["result"]["structuredContent"]
    check("除零被拒绝", sc["ok"] is False and sc["calc"]["status"] == "rejected",
          str(sc["calc"]))

    r = handle({"jsonrpc": "2.0", "id": 6, "method": "tools/call", "params": {
        "name": "normalize_amount",
        "arguments": {"raw": "项目预算人民币2,000万元"}}})
    sc = r["result"]["structuredContent"]
    check("预算口径被拦截", sc["value"] is None and "预算" in sc["reason"], str(sc))

    r = handle({"jsonrpc": "2.0", "id": 7, "method": "tools/call", "params": {
        "name": "normalize_date", "arguments": {"raw": "2026年10月"}}})
    check("不完整日期拒绝归一化", r["result"]["structuredContent"]["value"] is None)

    r = handle({"jsonrpc": "2.0", "id": 8, "method": "tools/call", "params": {
        "name": "registry_list", "arguments": {}}})
    sc = r["result"]["structuredContent"]
    check("registry_list 含技能/工具/提示词",
          all(k in sc for k in ("skills", "tools", "prompts")))

    r = handle({"jsonrpc": "2.0", "id": 9, "method": "tools/call", "params": {
        "name": "不存在的工具", "arguments": {}}})
    check("未知工具返回 isError", r["result"]["isError"] is True)

    r = handle({"jsonrpc": "2.0", "id": 10, "method": "不存在的/方法", "params": {}})
    check("未知方法返回 -32601", r["error"]["code"] == -32601)

    check("通知无响应", handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None)

    print()
    print(f"  自检结果：{'全部通过' if ok else '存在失败'}")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="中标公告抽取原型的 MCP 服务（stdio）")
    ap.add_argument("--selftest", action="store_true", help="运行协议与工具自检后退出")
    args = ap.parse_args()
    if args.selftest:
        return selftest()
    return serve()


if __name__ == "__main__":
    sys.exit(main())
