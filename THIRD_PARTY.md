# 第三方来源与使用范围

2026-10-13 下载。第三方代码保留在 `references/`，核心库文件未修改。自编代码为 `prototype/` 内的样例生成、编排、校验、评测、持久化和演示界面。不要将第三方源码申报为自研。

本仓库按上表固定 commit 将 `references/` 的**工作区文件**一并收录（便于换机后直接 `pip install -r requirements.lock.txt` 开箱复现），但**未收录各项目自身的 `.git` 目录**，因此它们不是 submodule，只是普通文件。需要跟随上游更新时，请按上表 commit 重新克隆；各目录内的 `LICENSE`／`LICENSE.txt` 随源码一并保留。

| 项目 | 固定 commit / 运行版本 | 许可证 | 本原型使用范围 |
|---|---|---|---|
| [google/langextract](https://github.com/google/langextract) | `f6dc772b738a44cd6f77d0858d6ce3afa16acd15`；1.7.1 | Apache-2.0，仓库 `LICENSE` | 示例提示构建、Ollama provider、结构化解析、中文字符对齐、结果序列化 |
| [jsvine/pdfplumber](https://github.com/jsvine/pdfplumber) | `4c64b92d5caccd71c645e98e0fabb0c4dba7ff45`；0.11.10 | MIT，仓库 `LICENSE.txt` | 电子 PDF 文本、字符坐标提取；不提供 OCR |
| [mozilla/pdf.js](https://github.com/mozilla/pdf.js) | `e1412d3a540bec075b58c01853e1d85f45f7e841` | Apache-2.0，仓库 `LICENSE` | 稀疏检出 examples/web/docs 作阅读参考 |
| [pdfjs-dist](https://www.npmjs.com/package/pdfjs-dist) | **6.4.299**，见 `prototype/web/package-lock.json` | Apache-2.0 | 实际浏览器 PDF 渲染；使用官方预构建发行包，并非由上述源码 commit 本机编译 |
| [PaddlePaddle/PaddleNLP](https://github.com/PaddlePaddle/PaddleNLP) | `3f87dac9b719f75399f92f8bf634ae2ef0611832` | Apache-2.0，仓库 `LICENSE` | 只阅读 `slm/examples/information_extraction/DuEE` 的事件/角色设计，不安装、不训练、不执行其模型 |
| [ReportLab](https://pypi.org/project/reportlab/) | 4.4.9 | BSD | 制作两份合成 PDF 测试材料 |
| [Ollama](https://github.com/ollama/ollama) | 0.35.1 | MIT | 本机 HTTP 推理服务，仅访问 `127.0.0.1:11434` |
| [Qwen3-VL](https://huggingface.co/Qwen/Qwen3-VL-8B-Thinking) | 本机已有 `qwen3-vl:8b`，Q4_K_M；digest `901cae73216286ea8c5aba8b46d307ff7188f737285ec500c795a12f05225d28` | 本机模型许可证声明 Apache-2.0 | 仅文本抽取，没有使用图像能力；未下载或提交模型权重 |

Python 3.12.14。主要运行依赖版本及本次环境记录见 `requirements.lock.txt` 和 `outputs/runtime.json`；前端依赖使用 npm lockfile。

DuEE-Fin 的官方金融数据及 `duee_fin_event_schema.json` 未随此代码仓提供，本项目没有下载、导入或宣称拥有官方数据集。两份测试 PDF 与标签均由本项目合成，不能代表真实公告评测集。

PDF 中文字体取自本机 Arial Unicode，仅嵌入样例文档，没有复制或再分发字体安装文件。换机生成样例时脚本会回退到 ReportLab 的 STSong-Light CID 字体，建议核验渲染效果。

本机 `qwen3-vl:8b` 是 Thinking 版本。原生 `think=false` 的首次试跑未返回答案；[Ollama 项目维护者说明](https://github.com/ollama/ollama/issues/16945)建议使用 Instruct 版本关闭思考。为避免额外下载，第二次只做文本模板预填充适配，成功录制一次结果。这是本机受限试跑方案，正式参赛需选定并验证适用的模型与调用方式。
