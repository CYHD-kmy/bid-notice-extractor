# 处理与查看新公告

将电子PDF放入项目 samples 或其他项目内目录。先启动并安装项目说明要求的本地模型，然后执行：

```sh
python prototype/run_demo.py --mode live --input samples/new.pdf --output outputs/new-run
python prototype/open_result.py outputs/new-run/result.json
python -m http.server 8765 --bind 127.0.0.1
```

打开第二条命令打印的链接。页面也可填写 outputs/new-run/result.json 切换运行结果，底部下载链接同步切换。该界面查看已完成任务，不在网页中启动模型、不上传文件。模型失败时查看对应目录 failure.json 和 trace.jsonl，不将旧结果当作新任务结果。

新文件没有匹配标签时不应显示准确率。历史样例与真实数据的类别来自运行元数据。当前仍限制为两份电子PDF、5000字符；扫描件和复杂表格尚未覆盖。不要用固定字段正确率代替事件精确率和召回率。
