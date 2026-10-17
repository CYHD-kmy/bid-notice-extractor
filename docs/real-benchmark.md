# 真实公告初始评测材料

benchmarks/real-seed.json包含两份公开真实PDF的来源、SHA256及三个事件的初始标注。已对照原文检查，尚未经过独立第二人复核，也没有进行模型效果测试；不能称为20至30份基准或独立保留测试集。PDF只下载到本地work，不将公告全文随贡献再分发。

```sh
python prototype/benchmark.py prepare --download
python prototype/run_demo.py --mode live --input work/benchmark-inputs/opte-20260114.pdf --output outputs/benchmark-opte --expected work/benchmark-labels/opte-20260114/expected.json --evaluation-manifest work/benchmark-labels/opte-20260114/expected.manifest.json
python prototype/benchmark.py assess --case opte-20260114 --result outputs/benchmark-opte/result.json
```

prepare只准备下载和指纹匹配的标签，不调用模型；assess只评估明确指定的已完成运行。每个真实样例应独立推理，以避免合并输入造成的预算截断。运行结果目录应同时保留origin.json以核验输入。初始标注已经参与本次设计检查，不能再宣称为未见测试集。

日期按公告落款日期标注。金智公告来源URL为8月8日，落款为8月7日；不要把下载路径日期替换为文内日期。币种仅标原文中的“元”，不补写没有出现的“人民币”；现有换算规则将元映射为CNY，这一标注口径需团队复核。其交易对手方不直接等同招标方，因此bidder不参与该样例评分。

两份资料覆盖角色区分、注册资本干扰、同页双项目、表格、预算与三年续签口径、跨页日期。后续需要团队独立复核标注，增加不同来源版式，另设完全未参与调试的测试集，重复推理后再报告稳定性。

来源：
- https://static.cninfo.com.cn/finalpage/2026-01-14/1224931547.PDF
- https://disc.static.szse.cn/download/disc/disk03/finalpage/2026-08-08/e9c27fa7-43ac-4ad4-8075-3b08c47098b2.PDF
