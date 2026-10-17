# 与输入绑定的评测

默认仅在输入路径、PDF SHA256及标签SHA256均匹配 samples/evaluation_manifest.json 时评测内置样例。其他输入仍可抽取，但准确率为 null，界面显示“未评测”，数据类别为未知。

使用自己的人工标签：

```sh
python prototype/run_demo.py --mode live --input samples/custom.pdf --output outputs/custom-run --expected samples/custom-labels.json --evaluation-manifest samples/custom-labels.manifest.json
```

清单格式（替换为实际指纹，不要保留占位值）：

```json
{
  "data_kind": "real",
  "input_files": [{"file": "samples/custom.pdf", "sha256": "PDF的SHA256"}],
  "labels_sha256": "custom-labels.json的SHA256"
}
```

路径相对项目根目录，统一使用 /。省略 --evaluation-manifest 时寻找标签同名的 .manifest.json。明确指定的标签不匹配时拒绝评测。标签在推理和校验完成后才读取，不输入模型。data_kind 是标注者声明，不是系统自动鉴定。

同时阅读事件精确率、召回率、完整事件正确率及多余事件数量。字段正确率不能独立代表整体效果；回放也不能代表模型再次推理的稳定性。
