"""Create two tiny, explicitly fictional announcement PDFs and gold labels."""
from pathlib import Path
import json
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.lib.pagesizes import A4

ROOT = Path(__file__).resolve().parents[1]
CASES = [
    {
        "case_id": "01_single", "file": "01_single.pdf", "title": "关于单项目中标的模拟公告",
        "disclosure_date": "2026年10月13日", "events": [
            {"company": "华澄智能工程股份有限公司", "project": "青岚智慧园区配套工程",
             "bidder": "青岚市公共建设中心", "award_amount_raw": "人民币1,280.50万元",
             "currency": "人民币", "award_date": "2026年10月10日", "budget": "人民币1,500万元"}
        ]
    },
    {
        "case_id": "02_multi", "file": "02_multi.pdf", "title": "关于两个项目中标的模拟公告",
        "disclosure_date": "2026年10月13日", "events": [
            {"company": "华澄智能工程股份有限公司", "project": "北辰综合管廊一期工程",
             "bidder": "北辰市基础设施建设中心", "award_amount_raw": "人民币0.326亿元",
             "currency": "人民币", "award_date": "2026年10月11日", "budget": "人民币4,000万元"},
            {"company": "华澄智能工程股份有限公司", "project": "河畔智慧园区配套工程",
             "bidder": "河畔市园区运营中心", "award_amount_raw": None,
             "currency": None, "award_date": "2026年10月12日", "budget": "人民币2,000万元"}
        ]
    }
]

def wrap(text, font, size, width):
    line = ""
    for char in text:
        if pdfmetrics.stringWidth(line + char, font, size) > width and line:
            yield line
            line = ""
        line += char
    if line:
        yield line

def main():
    out = ROOT / "samples"
    out.mkdir(exist_ok=True)
    font_path = Path("/System/Library/Fonts/Supplemental/Arial Unicode.ttf")
    if font_path.exists():
        pdfmetrics.registerFont(TTFont("Chinese", str(font_path)))
    else:
        pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    font = "Chinese" if font_path.exists() else "STSong-Light"
    width, height = A4
    gold = []
    for case in CASES:
        c = canvas.Canvas(str(out / case["file"]), pagesize=A4, invariant=1)
        c.setTitle(case["title"] + "（模拟数据）")
        c.setAuthor("比赛原型 / 合成样例")
        for index, event in enumerate(case["events"]):
            c.setFillColorRGB(.08, .16, .25)
            c.setFont(font, 20)
            c.drawString(48, height - 65, case["title"])
            c.setFont(font, 10)
            c.setFillColorRGB(.65, .2, .12)
            c.drawString(48, height - 90, "模拟数据：公司、机构及项目均为虚构；不构成投资建议。")
            c.setFillColorRGB(.12, .17, .24)
            c.setFont(font, 12)
            c.drawString(48, height - 124, "披露日期：" + case["disclosure_date"])
            c.drawString(48, height - 154, f"项目 {index + 1}")
            amount = "中标金额为" + event["award_amount_raw"] if event["award_amount_raw"] else "中标金额尚未确定，以后续合同为准"
            paragraph = (f"{event['company']}于{event['award_date']}收到中标通知，"
                         f"中标项目为{event['project']}，招标方为{event['bidder']}。"
                         f"{amount}。项目预算为{event['budget']}，预算不代表中标金额。")
            y = height - 190
            for line in wrap(paragraph, font, 12, width - 96):
                c.drawString(48, y, line)
                y -= 25
            c.setFont(font, 11)
            c.drawString(48, y - 28, "本页描述一个项目；各项目应分别输出，金额缺失时保留空值。")
            c.setStrokeColorRGB(.82, .86, .9)
            c.line(48, 52, width - 48, 52)
            c.setFont(font, 9)
            c.drawString(48, 35, f"样例编号：{case['case_id']} | 第 {index + 1} 页 / 共 {len(case['events'])} 页")
            c.showPage()
            gold.append({"case_id": case["case_id"], **{k: v for k, v in event.items() if k != "budget"},
                         "disclosure_date": case["disclosure_date"]})
        c.save()
    (out / "expected.json").write_text(json.dumps({"records": gold}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Created {len(CASES)} fictional PDFs and {len(gold)} expected events in {out}")

if __name__ == "__main__":
    main()
