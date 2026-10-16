"""mcp 包：把本项目的确定性工具暴露为 MCP 服务。

  tools.py    工具定义与实现（纯函数，输入输出均为 JSON）
  server.py   JSON-RPC 2.0 over stdio 的 MCP 服务端

设计取向：**只暴露确定性工具**，不把模型调用包装成 MCP 工具 ——
这样评审方无需 Ollama 也能通过 MCP 验证核心逻辑。
"""
