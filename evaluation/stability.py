"""稳定性评测：连续多次运行，检查产物是否逐项一致。

**重要边界（必须与结果一起呈现）**
------------------------------------------------
本模块测的是「**回放确定性**」，不是「**模型稳定性**」：

  · 回放模式为 0 次模型调用，处理链路无随机源（无温度、无采样）
  · 因此"N 次一致"验证的是**校验/计算/报告逻辑的确定性**
  · 本原型**只成功录制 1 次真实模型推理**（首次 71 秒达 token 上限而失败），
    所以**不能**据此宣称模型稳定

把这两者混为一谈会构成不实陈述。评测输出中同时写入 `scope` 字段说明边界。

用法：
    .venv\\Scripts\\python.exe -m evaluation.stability --runs 5
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core.config import DEFAULT                       # noqa: E402
from evaluation.metrics import evaluate_run           # noqa: E402

#: 参与一致性比对的产物（按内容比对，不用文件名）
COMPARED = ("calculations.jsonl", "assertions.jsonl", "results.csv", "registry.json")

#: 需要先剥离运行元数据再比对的产物（头部含 run_id 与生成时间，本身非确定性）
NORMALIZED_COMPARED = ("report.md", "report.json")

#: 含非确定性字段、不参与比对的产物
NON_DETERMINISTIC = ("result.json", "trace.jsonl", "source.json")

#: 在归一化时抹掉的、因运行而异的字段/行
#: （运行编号、生成时间、以及含运行输出目录名的追溯日志路径）
_STRIP_LINE_PREFIXES = ("- 运行编号：", "- 生成时间（UTC）：", "- 追溯日志：")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _normalized_sha256(path: Path, name: str) -> str:
    """剥离运行元数据后计算哈希，用于检验"内容"是否稳定。

    report.md / report.json 中本就该因运行而异的内容有三处：
      · run_id / generated_at（运行编号与时间）
      · trace_path（含运行输出目录名，如 run01/run02）
    逐字节比对没有意义；有意义的是"去掉这些运行标识后内容是否一致"。
    这也正是 `--output` 指向不同目录时仍能验证确定性的前提。
    """
    if name.endswith(".md"):
        lines = [l for l in path.read_text(encoding="utf-8").splitlines()
                 if not l.strip().startswith(_STRIP_LINE_PREFIXES)]
        payload = "\n".join(lines).encode("utf-8")
    else:
        doc = json.loads(path.read_text(encoding="utf-8"))
        doc.pop("run_id", None)
        doc.pop("generated_at", None)
        repro = doc.get("sections", {}).get("reproducibility")
        if isinstance(repro, dict):
            repro.pop("trace_path", None)
        payload = json.dumps(doc, ensure_ascii=False, sort_keys=True,
                             separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _normalized_metrics(out_dir: Path) -> dict:
    """去掉时间戳/运行编号后的指标快照，用于跨运行比对。"""
    m = evaluate_run(out_dir)
    m.pop("run_id", None)
    return m


def stability(runs: int = 5, keep: bool = False) -> dict:
    """连续跑 N 次流水线，比对产物一致性。"""
    from agent.orchestrator import run as run_pipeline

    base = DEFAULT.root / "tests" / "_out" / "stability"
    if base.exists():
        shutil.rmtree(base, ignore_errors=True)
    base.mkdir(parents=True, exist_ok=True)

    per_run: list[dict] = []
    for i in range(1, runs + 1):
        out = base / f"run{i:02d}"
        result = run_pipeline(mode="replay", out_dir=out, with_tables=True)
        per_run.append({
            "run": i,
            "dir": out.relative_to(DEFAULT.root).as_posix(),
            "hashes": {name: _sha256(out / name) for name in COMPARED if (out / name).is_file()},
            "normalized_hashes": {name: _normalized_sha256(out / name, name)
                                  for name in NORMALIZED_COMPARED if (out / name).is_file()},
            "metrics": _normalized_metrics(out),
            "counts": result["counts"],
        })

    # ---- 逐产物比对（原始哈希）----
    file_consistency: dict[str, dict] = {}
    for name in COMPARED:
        hashes = [r["hashes"].get(name) for r in per_run]
        present = [h for h in hashes if h]
        identical = len(set(present)) == 1 and len(present) == runs
        file_consistency[name] = {
            "runs_present": len(present),
            "identical": identical,
            "distinct_hashes": len(set(present)),
            "sha256": present[0] if present else None,
            "comparison": "逐字节",
        }

    # ---- 报告类产物：剥离运行元数据后比对 ----
    for name in NORMALIZED_COMPARED:
        hashes = [r["normalized_hashes"].get(name) for r in per_run]
        present = [h for h in hashes if h]
        identical = len(set(present)) == 1 and len(present) == runs
        file_consistency[name] = {
            "runs_present": len(present),
            "identical": identical,
            "distinct_hashes": len(set(present)),
            "sha256": present[0] if present else None,
            "comparison": "剥离 run_id 与生成时间后逐字节",
        }

    # ---- 指标比对（计算自洽率、证据核验率、报告完整性）----
    metric_consistency: dict[str, dict] = {}
    for path, getter in (
        ("calc.self_consistent_rate", lambda m: m["calculations"]["self_consistent_rate"]),
        ("calc.failures", lambda m: m["calculations"]["failures"]),
        ("evidence.verified_rate", lambda m: m["evidence"]["verified_rate"]),
        ("evidence.fact_assertions", lambda m: m["evidence"]["fact_assertions"]),
        ("report.sections_present", lambda m: m["report"]["sections_present"]),
        ("report.has_all_three_kinds", lambda m: m["report"]["has_all_three_kinds"]),
        ("report.fact", lambda m: m["report"]["fact"]),
        ("report.inference", lambda m: m["report"]["inference"]),
    ):
        try:
            values = [getter(r["metrics"]) for r in per_run]
        except KeyError:
            values = []
        metric_consistency[path] = {
            "values": values,
            "identical": len(set(map(json.dumps, values))) == 1 and bool(values),
        }

    all_files_identical = all(v["identical"] for v in file_consistency.values())
    all_metrics_identical = all(v["identical"] for v in metric_consistency.values())

    report = {
        "runs": runs,
        "mode": "replay",
        "model_calls_per_run": 0,
        "file_consistency": file_consistency,
        "metric_consistency": metric_consistency,
        "all_files_identical": all_files_identical,
        "all_metrics_identical": all_metrics_identical,
        "deterministic": all_files_identical and all_metrics_identical,
        "compared_artifacts": list(COMPARED),
        "normalized_compared_artifacts": list(NORMALIZED_COMPARED),
        "excluded_artifacts": list(NON_DETERMINISTIC),
        "exclusion_reason": "result.json 含 run_id 与时间戳、trace.jsonl 含时间戳、"
                            "source.json 体积大且不随运行变化 —— 均不参与比对；"
                            "report.md/report.json 剥离 run_id 与生成时间后再比对",
        "scope": "本指标为【回放确定性】：0 次模型调用、处理链路无随机源。"
                 "本原型仅成功录制 1 次真实推理，因此【不能】据此推断模型稳定性。",
        "per_run": [{k: v for k, v in r.items() if k != "metrics"} for r in per_run],
        "per_run_metrics": [r["metrics"] for r in per_run],
    }

    out = DEFAULT.root / "outputs" / "stability.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if not keep:
        shutil.rmtree(base, ignore_errors=True)
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description="回放稳定性评测")
    ap.add_argument("--runs", type=int, default=5, help="运行次数（默认 5）")
    ap.add_argument("--keep", action="store_true", help="保留中间运行目录")
    args = ap.parse_args()

    if args.runs < 2:
        print("runs 至少为 2")
        return 2

    report = stability(runs=args.runs, keep=args.keep)
    print(json.dumps({
        "runs": report["runs"],
        "model_calls_per_run": report["model_calls_per_run"],
        "all_files_identical": report["all_files_identical"],
        "all_metrics_identical": report["all_metrics_identical"],
        "deterministic": report["deterministic"],
        "files": {k: ("一致" if v["identical"] else f"不一致({v['distinct_hashes']}种)")
                  for k, v in report["file_consistency"].items()},
        "metrics_ok": {k: v["identical"] for k, v in report["metric_consistency"].items()},
        "scope": report["scope"],
    }, ensure_ascii=False, indent=2))
    return 0 if report["deterministic"] else 1


if __name__ == "__main__":
    sys.exit(main())
