"""Local, one-inference announcement demo; replay is the default mode."""
from __future__ import annotations
from event_grounding import check_event_associations
import argparse
import csv
import hashlib
import json
from pathlib import Path
import sqlite3
from runtime_config import load_config, preflight, environment
import time
from datetime import datetime, timezone
import pdfplumber
import langextract as lx
from langextract.providers.ollama import OllamaLanguageModel
from langextract.core.tokenizer import UnicodeTokenizer
from validation import validate_records
from evaluate import evaluate_records, load_records, FIELDS
from evaluation_scope import evaluate_inputs

ROOT = Path(__file__).resolve().parents[1]
MODEL = "qwen3-vl:8b"
PROMPT = """从模拟中标公告提取每个独立的中标事件，按原文顺序输出，不能漏掉金额未确定的项目。
extraction_class 只能为 中标事件；extraction_text 只能是原文中逐字一致的完整项目名称。
attributes 包括 company(中标公司)、project(项目名称)、bidder(招标方，非中标方)、
award_amount_raw(中标金额原文，保留币种、逗号与单位)、currency(原文币种)、
award_date(中标日期原文)、disclosure_date(披露日期原文)。所有值必须逐字引用原文，不改写日期。
如有明确金额标签，另输出 award_amount_type（逐字金额标签，例如中标金额或成交金额）；不要自行猜测口径。
预算、总投资、合计、最高限价不属于单项目中标金额。金额尚未确定或未披露时，
award_amount_raw 和 currency 输出空字符串；不填零，不用项目预算代替。
每页披露日期适用于本页项目。不要输出示例事件、页码、文件名或说明文字。"""

EXAMPLE_TEXT = ("披露日期：2026年9月9日。星桥建设有限公司于2026年9月8日收到中标通知，"
                "中标项目为星桥道路工程，招标方为星桥建设中心。中标金额为人民币250万元。"
                "项目预算为人民币300万元。星桥建设有限公司于2026年9月7日收到中标通知，"
                "中标项目为星桥绿化工程，招标方为星桥园林中心。中标金额尚未确定。项目预算为人民币100万元。")

def examples():
    return [lx.data.ExampleData(text=EXAMPLE_TEXT, extractions=[
        lx.data.Extraction(extraction_class="中标事件", extraction_text="星桥道路工程", attributes={
            "company": "星桥建设有限公司", "project": "星桥道路工程", "bidder": "星桥建设中心",
            "award_amount_raw": "人民币250万元", "currency": "人民币", "award_date": "2026年9月8日",
            "disclosure_date": "2026年9月9日"}),
        lx.data.Extraction(extraction_class="中标事件", extraction_text="星桥绿化工程", attributes={
            "company": "星桥建设有限公司", "project": "星桥绿化工程", "bidder": "星桥园林中心",
            "award_amount_raw": "", "currency": "", "award_date": "2026年9月7日",
            "disclosure_date": "2026年9月9日"})])]

def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

class Trace:
    def __init__(self, out):
        self.path = out / "trace.jsonl"
        self.path.write_text("", encoding="utf-8")

    def log(self, operation, **details):
        row = {"time": datetime.now(timezone.utc).isoformat(), "operation": operation, **details}
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

def parse_pdfs(paths, trace):
    source, pages = "", []
    for path in paths:
        trace.log("file_read", file=path.relative_to(ROOT).as_posix(), sha256=digest(path), parser="pdfplumber")
        with pdfplumber.open(path) as pdf:
            for number, page in enumerate(pdf.pages, 1):
                source += f"\n[文件：{path.name}；页码：{number}]\n"
                start = len(source)
                chars = []
                for line in page.extract_text_lines():
                    # Physical line wraps are removed; every source character
                    # keeps its original PDF coordinates, including wraps.
                    for ch in sorted(line["chars"], key=lambda c: c["x0"]):
                        for letter in ch["text"]:
                            chars.append({"text": letter, "bbox": [round(ch[k], 3) for k in ("x0", "top", "x1", "bottom")]})
                text = "".join(ch["text"] for ch in chars)
                if not text.strip():
                    raise ValueError(f"{path.name} 第 {number} 页没有文本层；本原型未接入 OCR")
                source += text
                pages.append({"file": path.relative_to(ROOT).as_posix(), "case_id": path.stem, "page": number,
                              "width": page.width, "height": page.height, "start": start, "end": len(source),
                              "text": text, "chars": chars})
                trace.log("pdf_page_parsed", file=path.name, page=number, characters=len(text))
    if len(source) > 5000:
        raise ValueError("轻量试跑只接收不超过5000字符；长文档需另做分块及调用预算设计")
    return source, pages

class BudgetedOllama(OllamaLanguageModel):
    def __init__(self, out, trace, config=None):
        self.config = config or load_config()
        super().__init__(model_id=self.config.model, model_url=self.config.model_url, timeout=self.config.timeout_seconds,
                         think=False, temperature=0, seed=42, num_ctx=self.config.num_ctx,
                         max_output_tokens=self.config.max_output_tokens, keep_alive=0)
        self.out, self.trace, self.calls = out, trace, 0

    def _post_ollama_json(self, api_url, payload, request_timeout, num_threads, model):
        if self.calls >= 1:
            raise RuntimeError("达到1次模型调用硬上限；不自动重试")
        self.calls += 1
        # This installed qwen3-vl tag is the Thinking variant. Its native
        # renderer ignores think=False. Use a text-only Qwen chat template
        # with the empty reasoning block already completed. Freeze the full
        # transmitted prompt so this model-specific adapter can be audited.
        payload = dict(payload)
        if self.config.qwen_text_prefill:
            payload["raw"] = True
            payload["prompt"] = ("<|im_start|>system\n直接输出所要求的JSON对象。"
                             "所有字段必须引用给定原文，不要推理说明。<|im_end|>\n"
                             "<|im_start|>user\n" + payload["prompt"] + "<|im_end|>\n"
                             "<|im_start|>assistant\n<think>\n\n</think>\n\n")
        write_json(self.out / "model_request.json", dict(payload))
        self.trace.log("model_call_started", model=model, endpoint=api_url, call=self.calls,
                       timeout_seconds=request_timeout, max_output_tokens=self.config.max_output_tokens, keep_alive=0,
                       transport="qwen-text-prefill" if self.config.qwen_text_prefill else "native")
        start = time.monotonic()
        response = super()._post_ollama_json(api_url, payload, request_timeout, num_threads, model)
        write_json(self.out / "model_response.json", dict(response))
        self.trace.log("model_call_finished", seconds=round(time.monotonic() - start, 3),
                       prompt_tokens=response.get("prompt_eval_count"), output_tokens=response.get("eval_count"),
                       done_reason=response.get("done_reason"))
        if response.get("done_reason") == "length":
            raise RuntimeError("输出达到token上限，结果可能截断；已保存原始响应，不自动重试")
        return response

def locate(page, raw, anchor=0):
    if raw is None or not isinstance(raw, str) or not raw:
        return None
    text = page["text"]
    candidates, offset = [], 0
    while True:
        pos = text.find(raw, offset)
        if pos < 0:
            break
        candidates.append(pos)
        offset = pos + len(raw)
    if not candidates:
        return None
    pos = min(candidates, key=lambda p: abs(p - anchor))
    chars = page["chars"][pos:pos + len(raw)]
    # Keep multiple rectangles when a value crosses a physical PDF line.
    rectangles = []
    for ch in chars:
        b = ch["bbox"]
        if rectangles and abs(rectangles[-1][1] - b[1]) < 2 and b[0] >= rectangles[-1][0]:
            rectangles[-1][2] = max(rectangles[-1][2], b[2])
            rectangles[-1][3] = max(rectangles[-1][3], b[3])
        else:
            rectangles.append(b.copy())
    return {"file": page["file"], "page": page["page"], "quote": raw,
            "start": page["start"] + pos, "end": page["start"] + pos + len(raw),
            "bboxes": rectangles, "verified": True}

def build_records(doc, source, pages, trace):
    records = []
    for index, item in enumerate(doc.extractions or []):
        if item.extraction_class != "中标事件":
            continue
        interval = item.char_interval
        exact = bool(interval and interval.start_pos is not None and interval.end_pos is not None
                     and source[interval.start_pos:interval.end_pos] == item.extraction_text)
        page = next((p for p in pages if exact and p["start"] <= interval.start_pos < p["end"]), None)
        attrs = item.attributes or {}
        record = {key: (attrs.get(key) if isinstance(attrs.get(key), str) and attrs[key].strip() else None) for key in FIELDS}
        record["award_amount_type"] = attrs.get("award_amount_type") if isinstance(attrs.get("award_amount_type"), str) else None
        # Project identity comes from the exact, aligned extraction quote.
        record["project"] = item.extraction_text
        record.update(case_id=page["case_id"] if page else "unaligned", event_id=f"event-{index + 1}",
                      source_file=page["file"] if page else None, evidence={}, evidence_issues=[])
        if not page:
            record["evidence_issues"].append({"field": "project", "reason": "事件未精确对齐到原文"})
        else:
            anchor = interval.start_pos - page["start"]
            for field in FIELDS:
                if record[field] is None:
                    continue
                proof = locate(page, record[field], anchor)
                if proof:
                    record["evidence"][field] = proof
                else:
                    record["evidence_issues"].append({"field": field, "reason": "字段值未在事件所在页找到逐字证据"})
            if record["award_amount_raw"] is not None and "award_amount_raw" in record["evidence"]:
                proof = record["evidence"]["award_amount_raw"]
                local_start = proof["start"] - page["start"]
                context = page["text"][max(0, local_start - 12):local_start]
                if not any(label in context for label in ("中标金额", "中标价")):
                    record["evidence_issues"].append({"field": "award_amount_raw", "reason": "金额未紧邻中标金额标签，需核对是否预算"})
        records.append(record)
    records = validate_records(check_event_associations(records, pages))
    for r in records:
        if r["evidence_issues"]:
            r["validation_status"] = "needs_review"
            r["validation_issues"].extend(r["evidence_issues"])
        trace.log("record_validated", case_id=r["case_id"], project=r["project"],
                  amount_raw=r["award_amount_raw"], calculation=r["normalized"]["award_amount"],
                  status=r["validation_status"], evidence_fields=len(r["evidence"]))
    return records

def persist(out, result, trace):
    write_json(out / "result.json", result)
    with (out / "results.csv").open("w", encoding="utf-8-sig", newline="") as f:
        fields = ["case_id", *FIELDS, "amount_in_base_currency", "validation_status"]
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for r in result["records"]:
            writer.writerow({**{k: r.get(k) for k in fields}, "amount_in_base_currency": r["normalized"]["award_amount"]["value"]})
    with sqlite3.connect(out / "events.sqlite") as con:
        con.execute("CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, metadata TEXT NOT NULL)")
        con.execute("CREATE TABLE IF NOT EXISTS events (run_id TEXT, event_id TEXT, case_id TEXT, project TEXT, amount TEXT, record_json TEXT, PRIMARY KEY(run_id,event_id))")
        con.execute("INSERT OR REPLACE INTO runs VALUES (?,?)", (result["run_id"], json.dumps(result["meta"], ensure_ascii=False)))
        for r in result["records"]:
            con.execute("INSERT OR REPLACE INTO events VALUES (?,?,?,?,?,?)", (result["run_id"], r["event_id"], r["case_id"], r["project"],
                        r["normalized"]["award_amount"]["value"], json.dumps(r, ensure_ascii=False)))
    trace.log("outputs_written", files=["result.json", "results.csv", "events.sqlite", "metrics.json"])

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, help="模型配置JSON；回放不会连接模型")
    parser.add_argument("--mode", choices=["live", "replay"], default="replay")
    parser.add_argument("--input", nargs="*", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--replay-from", type=Path, default=ROOT / "outputs")
    parser.add_argument("--expected", type=Path, help="本次输入的人工标签；默认仅评测指纹匹配的内置样例")
    parser.add_argument("--evaluation-manifest", type=Path, help="输入与标签SHA256清单")
    args = parser.parse_args()
    try:
        config = load_config(args.config)
    except (ValueError, TypeError, OSError) as error:
        parser.error(str(error))
    paths = args.input or sorted((ROOT / "samples").glob("*.pdf"))
    if not 1 <= len(paths) <= 2:
        parser.error("本机轻量试跑限制为1至2份PDF")
    paths = [p.resolve() for p in paths]
    for p in paths:
        if not p.is_relative_to(ROOT):
            parser.error("输入须位于当前项目目录内，以保持数据访问范围可核验")
    out = (args.output or (ROOT / "outputs" if args.mode == "live" else ROOT / "outputs" / "replay")).resolve()
    if not out.is_relative_to(ROOT):
        parser.error("输出须位于当前项目目录内")
    if args.mode == "replay" and out == args.replay_from.resolve():
        parser.error("回放输出不能覆盖录制目录，请另指定 --output")
    if args.mode == "live" and (out / "trace.jsonl").exists():
        parser.error("已有执行日志，拒绝覆盖；请另指定 --output")
    out.mkdir(parents=True, exist_ok=True)
    trace = Trace(out)
    start = time.monotonic()
    model = None
    try:
        source, pages = parse_pdfs(paths, trace)
        write_json(out / "source.json", {"text": source, "pages": pages})
        source_hash = hashlib.sha256(source.encode()).hexdigest()
        runtime = environment(config)
        write_json(out / "runtime.json", runtime)
        if args.mode == "live":
            trace.log("model_preflight_started", model=config.model, endpoint=config.model_url)
            runtime["model"] = preflight(config)
            write_json(out / "runtime.json", runtime)
            trace.log("model_preflight_finished", **runtime["model"])
            model = BudgetedOllama(out, trace, config)
            doc = lx.extract(text_or_documents=source, model=model, prompt_description=PROMPT,
                             examples=examples(), fence_output=False, use_schema_constraints=False,
                             tokenizer=UnicodeTokenizer(),
                             max_char_buffer=10000, max_workers=1, batch_length=1, extraction_passes=1,
                             resolver_params={"suppress_parse_errors": False, "enable_fuzzy_alignment": False,
                                              "accept_match_lesser": False})
            lx.io.save_annotated_documents([doc], output_name="extractions.jsonl", output_dir=str(out))
            origin = {"model": config.model, "model_digest": runtime["model"]["digest"], "model_calls": model.calls, "source_sha256": source_hash,
                      "extractions_sha256": digest(out / "extractions.jsonl"),
                      "input_files": [{"file": p.relative_to(ROOT).as_posix(), "sha256": digest(p)} for p in paths]}
            write_json(out / "origin.json", origin)
        else:
            origin = json.loads((args.replay_from / "origin.json").read_text(encoding="utf-8"))
            if origin["source_sha256"] != source_hash:
                raise ValueError("输入与录制时不同，拒绝将历史模型输出当作本次提取结果")
            if [{**item, "file": item["file"].replace("\\", "/")} for item in origin["input_files"]] != [{"file": p.relative_to(ROOT).as_posix(), "sha256": digest(p)} for p in paths]:
                raise ValueError("PDF文件列表或二进制哈希与录制时不同")
            if origin["extractions_sha256"] != digest(args.replay_from / "extractions.jsonl"):
                raise ValueError("录制提取文件哈希不一致")
            trace.log("recorded_extractions_read", file=str(args.replay_from / "extractions.jsonl"),
                      sha256=digest(args.replay_from / "extractions.jsonl"))
            doc = next(iter(lx.io.load_annotated_documents_jsonl(str(args.replay_from / "extractions.jsonl"))))
        records = build_records(doc, source, pages, trace)
        # Gold labels are read only after inference and validation.
        metrics = evaluate_inputs(records, paths, ROOT, args.expected, args.evaluation_manifest)
        nonempty = [(r, k) for r in records for k in FIELDS if r.get(k) is not None]
        grounded = sum(k in r["evidence"] for r, k in nonempty)
        metrics["evidence"] = {"grounded_fields": grounded, "nonempty_fields": len(nonempty),
                               "coverage": grounded / len(nonempty) if nonempty else None,
                               "scope": "逐字引文与PDF坐标核验；不代表事件语义关联已被证明"}
        trace.log("evaluation", evaluated=metrics["evaluated"], gold_sha256=metrics.get("labels_sha256"),
                  field_accuracy=metrics["field_accuracy"], scope=metrics["evaluation_scope"])
        write_json(out / "metrics.json", metrics)
        result = {"run_id": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f"),
                  "meta": {"mode": args.mode, "model": origin["model"], "model_calls_this_run": model.calls if model else 0,
                           "original_live_calls": origin["model_calls"], "elapsed_seconds": round(time.monotonic() - start, 3),
                           "source_sha256": source_hash,
                           "synthetic_data": {"synthetic": True, "real": False}.get(metrics["data_kind"])},
                  "metrics": metrics, "records": records}
        persist(out, result, trace)
        print(json.dumps({"mode": args.mode, "model_calls": result["meta"]["model_calls_this_run"],
                          "events": len(records), "field_accuracy": metrics["field_accuracy"],
                          "needs_review": sum(r["validation_status"] == "needs_review" for r in records),
                          "seconds": result["meta"]["elapsed_seconds"], "output": str(out)}, ensure_ascii=False))
    except Exception as error:
        trace.log("run_failed", error=str(error), model_calls=model.calls if model else 0)
        write_json(out / "failure.json", {"error": str(error), "model_calls": model.calls if model else 0})
        raise

if __name__ == "__main__":
    main()
