# MCP 服务说明

> 竞赛对应条款：
> 「参赛作品须同步提交…包括智能体编排框架、Tool、Prompt、Skill、**MCP**…等核心模块」

## 它是什么

把本项目的**确定性工具**暴露为标准 MCP（Model Context Protocol）服务，
任何支持 MCP 的客户端（如 Claude Desktop、各类 Agent 框架）都能发现并调用。

**由本项目自实现**（`mcp/server.py`），JSON-RPC 2.0 over stdio，**不依赖任何第三方 MCP SDK**
—— 以保证在受控环境中无额外网络与依赖即可运行。

## 启动

```powershell
# stdio 服务（供 MCP 客户端接入）
.venv\Scripts\python.exe mcp/server.py

# 协议与工具自检（15 项，不启动服务）
.venv\Scripts\python.exe mcp/server.py --selftest
```

MCP 客户端配置示例（把 `<项目根目录>` 替换为实际路径）：

```json
{
  "mcpServers": {
    "bid-notice-extractor": {
      "command": "<项目根目录>\\.venv\\Scripts\\python.exe",
      "args": ["<项目根目录>\\mcp\\server.py"]
    }
  }
}
```

## 暴露的工具（7 个，全部确定性）

| 工具 | 作用 | 关键约束 |
|---|---|---|
| `calculate_unit_convert` | 金额单位换算（万元/亿元 → 元） | 返回 `calc_id`、算式、舍入方式；单位未知则拒绝换算 |
| `calculate_ratio` | 百分数占比 | **分母为 0 直接拒绝**；先算比率再乘 100（避免精度丢失） |
| `calculate_yoy` | 同比 | 返回**两步**记录（差额 + 比率），两步都留痕 |
| `normalize_amount` | 金额归一化 | **拦截预算/合计口径**；缺失返回 `null` 而非 `0` |
| `normalize_date` | 日期归一化 | 只接受完整年月日，**不补齐**缺失的月/日 |
| `verify_evidence` | 证据核验 | 逐字引文须能在页面文本层按偏移原样取回 |
| `registry_list` | 能力清单 | 返回技能/工具/提示词（含 SHA256）与环境约束 |

## 设计取向：为什么**不**把模型暴露为 MCP 工具

| 考虑 | 说明 |
|---|---|
| **可验证性优先** | 只暴露确定性工具，评审方**无需 GPU、无需 Ollama** 即可完整验证核心逻辑 |
| **受控环境** | 模型调用有硬上限（单次运行 1 次请求、55 秒超时），不适合作为可被客户端随意反复调用的工具 |
| **职责边界** | 模型是**编排层内部**的一个环节（`agent/orchestrator.py`），不是对外能力。对外只暴露"能给出确定答案"的能力 |
| **审计** | 确定性工具的输出可逐步复算；模型输出不可复算，不适合作为 MCP 契约的一部分 |

## 协议支持

| 方法 | 说明 |
|---|---|
| `initialize` | 握手，返回协议版本 `2024-11-05` 与 `tools` 能力 |
| `tools/list` | 列出工具及 JSON Schema |
| `tools/call` | 调用工具，返回 `content` + `structuredContent` |
| `notifications/initialized` | 客户端就绪通知（无响应） |
| `ping` | 存活检查 |

**帧格式**：同时支持 MCP 官方的 `Content-Length` 帧与换行分隔 JSON（NDJSON），便于用管道手工验证：

```powershell
'{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"calculate_ratio","arguments":{"numerator":"12805000","denominator":"15000000"}}}' |
  .venv\Scripts\python.exe mcp/server.py
```

输出（节选）：

```json
{"jsonrpc":"2.0","id":1,"result":{"isError":false,
 "structuredContent":{"ok":true,"calc":{"calc_id":"R0001","op":"ratio",
 "result":"85.37","result_unit":"%",
 "trace_note":"占比分子 12805000元 ÷ 占比分母 15000000元 × 100 = 85.37%",
 "status":"valid"}}}}
```

## 自检覆盖（15 项）

```
PASS  initialize 返回协议版本
PASS  initialize 声明 tools 能力
PASS  tools/list 返回 7 个工具
PASS  每个工具都有 JSON Schema
PASS  单位换算结果正确
PASS  返回算式留痕
PASS  返回舍入方式说明
PASS  占比结果正确（85.37）
PASS  除零被拒绝
PASS  预算口径被拦截
PASS  不完整日期拒绝归一化
PASS  registry_list 含技能/工具/提示词
PASS  未知工具返回 isError
PASS  未知方法返回 -32601
PASS  通知无响应
```

## 数据契约

- **金额一律用十进制字符串**（如 `"1280.50"`），**不使用二进制浮点**
- 计算结果统一经 `decimal_str()` 规范化（去尾随零），因此 `12805000.00` 的对外形式是 `"12805000"`
- 失败以 `{"ok": false, "error"/"reason": ...}` 表达，**不抛异常给客户端**
- 每次计算返回完整留痕：`calc_id` / `op` / `operands` / `result` / `result_unit` / `rounding` / `trace_note` / `status` / `reason` / `depends_on`
