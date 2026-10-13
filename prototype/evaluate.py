"""Evaluate announcement events against human-checked annotations.

Usage: python evaluate.py --expected expected.json --actual results.json
Both inputs accept a record list or {"records": [...]}; case containers with
{"cases": [{"case_id": "...", "records": [...]}]} are also supported.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import json
from pathlib import Path
import re
import unicodedata

try:
    from .validation import normalize_amount, normalize_currency, normalize_date
except ImportError:
    from validation import normalize_amount, normalize_currency, normalize_date


FIELDS = ("company", "project", "bidder", "award_amount_raw", "currency", "award_date", "disclosure_date")


def _clean(value):
    if value is None:
        return None
    text = re.sub(r"\s+", "", unicodedata.normalize("NFKC", str(value)))
    return None if text.lower() in {"", "null", "none", "未披露", "不适用", "未知", "-", "—"} else text


def load_records(path) -> list[dict]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))

    def flatten(value, case_id=None):
        if isinstance(value, list):
            result = []
            for item in value:
                result.extend(flatten(item, case_id))
            return result
        if not isinstance(value, dict):
            raise ValueError("JSON must contain dictionaries or a list of dictionaries")
        current_case = value.get("case_id", case_id)
        for container_key in ("cases", "records", "results", "events"):
            if container_key in value and isinstance(value[container_key], list):
                return flatten(value[container_key], current_case)
        record = dict(value)
        if current_case is not None:
            record.setdefault("case_id", current_case)
        return [record]

    return flatten(data)


def field_matches(field: str, expected: dict, actual: dict) -> bool:
    left, right = expected.get(field), actual.get(field)
    if field == "award_amount_raw":
        if _clean(left) is None or _clean(right) is None:
            return _clean(left) is None and _clean(right) is None
        norm_left = normalize_amount(left, expected.get("currency"))
        norm_right = normalize_amount(right, actual.get("currency"))
        # Invalid strings cannot score correctly just because both normalize to
        # None. Approximate amounts retain a value but are reported for review.
        return (norm_left["value"] is not None and norm_right["value"] is not None
                and norm_left["value"] == norm_right["value"]
                and norm_left["currency"] == norm_right["currency"])
    if field == "currency":
        return normalize_currency(left) == normalize_currency(right)
    if field in {"award_date", "disclosure_date"}:
        if _clean(left) is None or _clean(right) is None:
            return _clean(left) is None and _clean(right) is None
        norm_left, norm_right = normalize_date(left), normalize_date(right)
        return norm_left["value"] is not None and norm_left["value"] == norm_right["value"]
    return _clean(left) == _clean(right)


def evaluate_records(expected: list[dict], actual: list[dict]) -> dict:
    """Match one-to-one on normalized (case_id, project), then score fields.

    Within duplicate project groups, pick the best remaining field match.
    Project identity errors deliberately count as a missed and an extra event;
    this is exact matching, not semantic/fuzzy matching.
    """
    actual_groups = defaultdict(list)
    for index, record in enumerate(actual):
        key = (_clean(record.get("case_id")), _clean(record.get("project")))
        actual_groups[key].append(index)
    used = set()
    field_stats = {field: {"correct": 0, "total": 0, "populated_correct": 0, "populated_total": 0} for field in FIELDS}
    matched_events, complete_events = 0, 0
    details = []
    for expected_index, target in enumerate(expected):
        key = (_clean(target.get("case_id")), _clean(target.get("project")))
        candidates = [index for index in actual_groups.get(key, []) if index not in used]
        annotated_fields = [field for field in FIELDS if field in target]
        if candidates:
            # If both sides have event_id, conflicting IDs must not match.
            candidates = [index for index in candidates if not (
                target.get("event_id") is not None and actual[index].get("event_id") is not None
                and str(target["event_id"]) != str(actual[index]["event_id"]))]
        actual_index = max(candidates, key=lambda index: sum(field_matches(field, target, actual[index])
                           for field in annotated_fields)) if candidates else None
        if actual_index is not None:
            used.add(actual_index)
            matched_events += 1
        mismatches = []
        for field in annotated_fields:
            correct = actual_index is not None and field_matches(field, target, actual[actual_index])
            field_stats[field]["total"] += 1
            field_stats[field]["correct"] += int(correct)
            if _clean(target.get(field)) is not None:
                field_stats[field]["populated_total"] += 1
                field_stats[field]["populated_correct"] += int(correct)
            if not correct:
                mismatches.append({"field": field, "expected": target.get(field),
                                   "actual": actual[actual_index].get(field) if actual_index is not None else None})
        complete = actual_index is not None and bool(annotated_fields) and not mismatches
        complete_events += int(complete)
        details.append({"case_id": target.get("case_id"), "project": target.get("project"),
                        "expected_index": expected_index, "actual_index": actual_index,
                        "matched": actual_index is not None, "complete": complete, "mismatches": mismatches})

    def ratio(numerator, denominator):
        return round(numerator / denominator, 6) if denominator else None

    for stats in field_stats.values():
        stats["accuracy"] = ratio(stats["correct"], stats["total"])
        stats["populated_accuracy"] = ratio(stats["populated_correct"], stats["populated_total"])
    total_fields = sum(stats["total"] for stats in field_stats.values())
    correct_fields = sum(stats["correct"] for stats in field_stats.values())
    populated_total = sum(stats["populated_total"] for stats in field_stats.values())
    populated_correct = sum(stats["populated_correct"] for stats in field_stats.values())
    missed = len(expected) - matched_events
    extra = len(actual) - len(used)
    return {
        "expected_events": len(expected), "predicted_events": len(actual), "matched_events": matched_events,
        "missed_events": missed, "extra_events": extra,
        "event_precision": ratio(matched_events, len(actual)), "event_recall": ratio(matched_events, len(expected)),
        "event_complete_count": complete_events, "event_complete_rate": ratio(complete_events, len(expected)),
        "field_accuracy": ratio(correct_fields, total_fields),
        "populated_field_accuracy": ratio(populated_correct, populated_total),
        "missing_rate": ratio(missed, len(expected)), "extra_rate": ratio(extra, len(actual)),
        "fields": field_stats, "details": details,
        "extra_records": [record for index, record in enumerate(actual) if index not in used],
        "method": "Exact one-to-one case_id/project matching; normalized Decimal money and complete dates. "
                  "Only annotated fields are scored; no LLM judge. Evidence checked separately.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected", required=True)
    parser.add_argument("--actual", required=True)
    parser.add_argument("--output")
    args = parser.parse_args()
    metrics = evaluate_records(load_records(args.expected), load_records(args.actual))
    serialized = json.dumps(metrics, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(serialized + "\n", encoding="utf-8")
    print(serialized)


if __name__ == "__main__":
    main()
