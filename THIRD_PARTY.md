# 第三方来源与使用范围

2026-10-13 下载；2026-10-16 补充「调用方式」列。第三方代码保留在 `references/`，**核心库文件未修改**。

> **分工声明**（竞赛要求「不得将第三方成果冒充为自主开发成果」）
>
> | 目录 | 归属 | 说明 |
> |---|---|---|
> | `references/` | **第三方** | 按固定 commit 原样收录的参考源码，**未修改** |
> | `prototype/` | 本项目 | 样例生成、编排、校验、评测、持久化、演示界面 |
> | `core/`、`tools/`、`skills/`、`agent/`、`prompts/` | **本项目** | 可追溯数据模型、原子工具、技能、编排框架、外置提示词、注册表 |
> | `mcp/` | **本项目** | MCP 适配层（把 `tools/` 暴露为 MCP 服务）|
>
> 第三方源码**仅供比对与文献引用**；本项目的可追溯机制（证据回溯、计算留痕、
> 断言分类）均为自研，未调用第三方模型或服务来完成核心判断。

本仓库按上表固定 commit 将 `references/` 的**工作区文件**一并收录（便于换机后直接
`pip install -r requirements.lock.txt` 开箱复现），但**未收录各项目自身的 `.git` 目录**，
因此它们不是 submodule，只是普通文件。需要跟随上游更新时，请按上表 commit 重新克隆；
各目录内的 `LICENSE`／`LICENSE.txt` 随源码一并保留。

## 第三方清单（名称 / 版本 / 来源 / 许可证 / 调用方式 / 使用范围）

| 项目 | 固定 commit / 运行版本 | 许可证 | **调用方式** | 本原型使用范围 |
|---|---|---|---|---|
| [google/langextract](https://github.com/google/langextract) | `f6dc772b738a44cd6f77d0858d6ce3afa16acd15`；1.7.1 | Apache-2.0，仓库 `LICENSE` | **源码级** — `-e ./references/langextract`（editable 安装），`import langextract`；`lx.data` 构建示例、`lx.io` 读写 JSONL、`langextract.providers.ollama` 作推理通道 | 示例提示构建、Ollama provider、结构化解析、中文字符对齐、结果序列化 |
| [jsvine/pdfplumber](https://github.com/jsvine/pdfplumber) | `4c64b92d5caccd71c645e98e0fabb0c4dba7ff45`；0.11.10 | MIT，仓库 `LICENSE.txt` | **源码级** — `-e ./references/pdfplumber`（editable 安装），`import pdfplumber`；`extract_text_lines()` 取字符级坐标，`find_tables()` 取表格结构 | 电子 PDF 文本、字符坐标提取、表格结构提取；**不提供 OCR** |
| [mozilla/pdf.js](https://github.com/mozilla/pdf.js) | `e1412d3a540bec075b58c01853e1d85f45f7e841` | Apache-2.0，仓库 `LICENSE` | **仅源码参考** — 稀疏检出 `examples/web/docs`，**未编译、未在运行时调用** | 阅读参考（演示界面的 PDF 渲染思路） |
| [pdfjs-dist](https://www.npmjs.com/package/pdfjs-dist) | **6.4.299**，见 `prototype/web/package-lock.json` | Apache-2.0 | **包级** — `npm ci --prefix prototype/web` 安装官方预构建包；浏览器端 `import * as pdfjs from './node_modules/pdfjs-dist/build/pdf.mjs'` | 实际浏览器 PDF 渲染；**非**由上述源码 commit 本机编译 |
| [PaddlePaddle/PaddleNLP](https://github.com/PaddlePaddle/PaddleNLP) | `3f87dac9b719f75399f92f8bf634ae2ef0611832` | Apache-2.0，仓库 `LICENSE` | **仅人工阅读** — 只查阅 `slm/examples/information_extraction/DuEE` 的事件/角色组织设计；**不安装、不 import、不训练、不执行其任何模型** | 借鉴事件/角色 schema 的组织思路 |
| [ReportLab](https://pypi.org/project/reportlab/) | 4.4.9 | BSD | **包级** — `pip install reportlab==4.4.9`；`from reportlab.pdfgen import canvas` 生成合成样例 PDF | 制作合成 PDF 测试材料（`samples/`、`samples_fixtures/`） |
| [Ollama](https://github.com/ollama/ollama) | 0.35.1 | MIT | **本地 HTTP 服务** — 监听 `127.0.0.1:11434`；由 `langextract.providers.ollama.OllamaLanguageModel` 通过 HTTP 调用；**不访问任何外部网络** | 本机推理服务 |
| [Qwen3-VL](https://huggingface.co/Qwen/Qwen3-VL-8B-Thinking) | 本机已有 `qwen3-vl:8b`，Q4_K_M；digest `901cae73216286ea8c5aba8b46d307ff7188f737285ec500c795a12f05225d28` | 本机模型许可证声明 Apache-2.0 | **经 Ollama HTTP 调用**，单次运行硬上限 1 次请求（`core/config.py:ModelConfig.max_calls`），55 秒超时、1000 输出 token、`keep_alive=0` 结束即卸载；**未下载或提交模型权重** | 仅文本抽取；**未使用其图像能力** |

### 调用方式的分类说明

| 方式 | 含义 | 涉及项 |
|---|---|---|
| **源码级** | 源码随仓库收录并以 editable 方式安装，`import` 后直接进内存调用 | langextract、pdfplumber |
| **包级** | 从官方仓库安装的发行包（非本仓源码） | pdfjs-dist、ReportLab |
| **本地服务** | 通过本机 HTTP 端口调用，不出网 | Ollama、Qwen3-VL |
| **仅参考** | 只阅读源码或文档，**运行时不参与** | pdf.js、PaddleNLP |

## 环境与数据声明

- **Python** 3.12.14。主要运行依赖版本见 `requirements.lock.txt`，本次环境快照见 `outputs/runtime.json`；前端依赖使用 npm lockfile。
- **DuEE-Fin** 的官方金融数据及 `duee_fin_event_schema.json` **未随本仓提供**；本项目没有下载、导入或宣称拥有官方数据集。
- **测试材料**：`samples/` 与 `samples_fixtures/` 下的 PDF 与标签均由本项目合成，**不能代表真实公告评测集**。
- **字体**：PDF 中文字体取自本机（`simhei.ttf` / Arial Unicode），仅嵌入样例文档，**没有复制或再分发字体安装文件**。换机生成样例时脚本会回退到 ReportLab 的 `STSong-Light` CID 字体，建议核验渲染效果。
- **模型版本注意**：本机 `qwen3-vl:8b` 是 **Thinking 版本**。原生 `think=false` 的首次试跑未返回答案；[Ollama 项目维护者说明](https://github.com/ollama/ollama/issues/16945)建议使用 Instruct 版本关闭思考。为避免额外下载，第二次只做文本模板预填充适配，成功录制一次结果。**这是本机受限试跑方案，正式参赛需选定并验证适用的模型与调用方式。**
