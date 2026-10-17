# 部署与复现

Python 3.12，在项目根目录创建虚拟环境并安装 requirements.lock.txt。Node.js用于安装现有PDF.js前端依赖。以下是Windows PowerShell示例：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock.txt
npm ci --prefix prototype/web
.\.venv\Scripts\python.exe prototype/run_demo.py --mode replay --output outputs/check-run
.\.venv\Scripts\python.exe -m http.server 8765 --bind 127.0.0.1
```

macOS/Linux使用 .venv/bin/python。回放无需Ollama和模型，但仍需要Python解析依赖。不要把回放速度当成推理速度。新回放结果位于 outputs/check-run/result.json；若已合并运行结果查看改进，可用 prototype/open_result.py 打印其查看链接。原界面默认读取历史 outputs/result.json。

真实推理前，按Ollama官方说明安装服务及明确选择的模型。复制 config.example.json 为 config.local.json 后调整地址、模型和预算；本程序不自动安装或下载模型。

```powershell
.\.venv\Scripts\python.exe prototype/run_demo.py --mode live --input samples/new.pdf --output outputs/new-run --config config.local.json
```

启动检查只查询模型列表和服务版本，实际推理最多一次。记录 runtime.json 的Python、系统、依赖版本、配置、模型digest和服务版本。使用远程地址前需明确数据访问范围；不要将密码或token写入配置。

qwen_text_prefill只允许原qwen3-vl:8b适配；其他模型须关闭并另行验证。不能用同一个标签证明权重相同，应比较digest。推理服务未连接、标签未安装、超时或响应截断时明确失败，检查 failure.json 和 trace.jsonl，不回退到历史结果。

自动测试：python -m unittest discover -s tests -v；前端逻辑测试：node --test tests/*.mjs。完整新模型效果和不同硬件耗时需另行验证。
