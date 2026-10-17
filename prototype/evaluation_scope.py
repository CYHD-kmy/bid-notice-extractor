"""Evaluate only labels explicitly bound to the exact input bytes."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from evaluate import evaluate_records, load_records


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def input_fingerprints(paths, root):
    return [{"file": Path(p).resolve().relative_to(root.resolve()).as_posix(),
             "sha256": sha256(p)} for p in paths]


def evaluate_inputs(records, paths, root, expected=None, manifest=None):
    explicit = expected is not None
    if manifest is not None and not explicit:
        raise ValueError("--evaluation-manifest requires --expected")
    expected = Path(expected) if explicit else root / "samples/expected.json"
    manifest = Path(manifest) if manifest else (
        expected.with_suffix(".manifest.json") if explicit else root / "samples/evaluation_manifest.json")
    skipped = {"evaluated": False, "field_accuracy": None, "data_kind": "unknown",
               "evaluation_scope": "未提供与输入匹配的标注，未评测"}
    if not manifest.is_file() or not expected.is_file():
        if explicit:
            raise ValueError("评测需要标签及其输入指纹清单；参见 docs/evaluation.md")
        return skipped
    provenance = json.loads(manifest.read_text(encoding="utf-8"))
    inputs = input_fingerprints(paths, root)
    matches = (sorted(provenance.get("input_files", []), key=lambda p: p["file"])
               == sorted(inputs, key=lambda p: p["file"])
               and provenance.get("labels_sha256") == sha256(expected))
    if not matches:
        if explicit:
            raise ValueError("标签清单与输入文件或标签SHA256不匹配，拒绝评测")
        return skipped
    metrics = evaluate_records(load_records(expected), records)
    kind = provenance.get("data_kind", "unknown")
    if kind not in {"synthetic", "real", "unknown"}:
        raise ValueError("data_kind must be synthetic, real, or unknown")
    metrics.update(evaluated=True, data_kind=kind, labels_sha256=sha256(expected),
                   evaluation_scope=f"{len(inputs)}份输入的配套标注；数据类别：{kind}；不能外推总体准确率")
    return metrics
