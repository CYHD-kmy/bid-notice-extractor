"""Verify recorded outputs without model calls; exercise tamper rejection."""
from pathlib import Path
import json
import shutil
import subprocess
import sys
from validation import normalize_amount, normalize_date

ROOT = Path(__file__).resolve().parents[1]

def main():
    live = json.loads((ROOT / "outputs/result.json").read_text(encoding="utf-8"))
    replay = json.loads((ROOT / "outputs/replay/result.json").read_text(encoding="utf-8"))
    assert live["records"] == replay["records"]
    assert replay["meta"]["model_calls_this_run"] == 0
    source = json.loads((ROOT / "outputs/source.json").read_text(encoding="utf-8"))
    pages = {(p["file"], p["page"]): p for p in source["pages"]}
    proofs = 0
    for record in live["records"]:
        for proof in record["evidence"].values():
            assert source["text"][proof["start"]:proof["end"]] == proof["quote"]
            page = pages[proof["file"], proof["page"]]
            for x0, y0, x1, y1 in proof["bboxes"]:
                assert 0 <= x0 <= x1 <= page["width"]
                assert 0 <= y0 <= y1 <= page["height"]
            proofs += 1
    assert normalize_amount("人民币1,280.50万元")["value"] == "12805000"
    assert normalize_amount("人民币0.326亿元")["value"] == "32600000"
    for text in (None, "项目预算人民币2,000万元", "人民币100至200万元", "合计人民币100万元"):
        assert normalize_amount(text)["value"] is None
    assert normalize_date("2026年2月30日")["value"] is None
    assert normalize_date("2026年10月")["value"] is None
    assert normalize_amount("USD 20万元", "人民币")["value"] is None

    work = ROOT / "work/verification"
    work.mkdir(parents=True, exist_ok=True)
    origin = json.loads((ROOT / "outputs/origin.json").read_text(encoding="utf-8"))
    tampered = work / "tampered-recording"
    tampered.mkdir(exist_ok=True)
    shutil.copyfile(ROOT / "outputs/extractions.jsonl", tampered / "extractions.jsonl")
    with (tampered / "extractions.jsonl").open("a") as f:
        f.write("\n")
    (tampered / "origin.json").write_text(json.dumps(origin), encoding="utf-8")
    commands = [(["--replay-from", str(tampered), "--output", str(work / "rejected-extractions")], "录制提取文件哈希不一致")]

    # Append harmless bytes after the PDF EOF: parsed text is unchanged, but
    # the file fingerprint must reject this different binary.
    copy_dir = work / "pdfs"
    copy_dir.mkdir(exist_ok=True)
    copied = []
    for item in origin["input_files"]:
        target = copy_dir / Path(item["file"]).name
        shutil.copyfile(ROOT / item["file"], target)
        copied.append(target)
        item["file"] = target.relative_to(ROOT).as_posix()
    with copied[0].open("ab") as f:
        f.write(b"\n% tampered layout provenance fixture\n")
    pdf_origin = work / "binary-recording"
    pdf_origin.mkdir(exist_ok=True)
    shutil.copyfile(ROOT / "outputs/extractions.jsonl", pdf_origin / "extractions.jsonl")
    (pdf_origin / "origin.json").write_text(json.dumps(origin), encoding="utf-8")
    commands.append((["--replay-from", str(pdf_origin), "--output", str(work / "rejected-binary"),
                      "--input", *(str(p) for p in copied)], "PDF文件列表或二进制哈希与录制时不同"))
    for options, reason in commands:
        result = subprocess.run([sys.executable, str(ROOT / "prototype/run_demo.py"), "--mode", "replay", *options],
                                text=True, capture_output=True, timeout=10,
                                encoding="utf-8", errors="replace")
        assert result.returncode != 0 and reason in result.stderr, result.stderr

    report = {"replay_identical": True, "verified_pdf_quotes": proofs, "tampered_extraction_rejected": True,
              "same_text_different_pdf_rejected": True, "missing_budget_range_checks": "passed",
              "model_calls_for_verification": 0}
    (ROOT / "outputs/verification.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))

if __name__ == "__main__":
    main()
