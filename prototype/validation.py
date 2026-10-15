"""Deterministic financial-field checks; standard library only.

Keep original fields unchanged. Normalized money uses decimal strings, never
binary floating point. A syntactically valid value does not verify its evidence.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import date
from decimal import Decimal, InvalidOperation
import re
import unicodedata


_MISSING = {"", "null", "none", "n/a", "na", "未披露", "不适用", "未知", "-", "—", "--"}
_UNDISCLOSED = {"未披露", "尚未确定", "暂未确定", "待定", "未知"}
_CURRENCY_ALIASES = {
    "人民币": "CNY", "rmb": "CNY", "cny": "CNY", "元": "CNY", "¥": "CNY",
    "￥": "CNY", "美元": "USD", "usd": "USD", "us$": "USD",
    "港元": "HKD", "港币": "HKD", "hkd": "HKD", "hk$": "HKD",
    "欧元": "EUR", "eur": "EUR", "€": "EUR",
}
_CURRENCY_NAMES = {"CNY": "元", "USD": "美元", "HKD": "港元", "EUR": "欧元"}
_MULTIPLIERS = {"": Decimal(1), "千": Decimal(1000), "万": Decimal(10000), "亿": Decimal(100000000)}


def _text(value) -> str:
    return unicodedata.normalize("NFKC", str(value)).strip() if value is not None else ""


def _decimal_string(value: Decimal) -> str:
    value_string = format(value, "f")
    return value_string.rstrip("0").rstrip(".") if "." in value_string else value_string


def normalize_currency(raw) -> str | None:
    text = _text(raw)
    if text.lower() in _MISSING:
        return None
    return _CURRENCY_ALIASES.get(text.lower(), text.upper())


def normalize_amount(raw, currency=None) -> dict:
    """Return raw/value/currency/normalized_unit/status/reason.

    A budget, aggregate, range, or multi-amount fragment is rejected rather than
    silently converted to an award. Missing input remains None, never zero.
    """
    currency_code = normalize_currency(currency)
    result = {
        "raw": raw, "value": None, "currency": currency_code,
        "normalized_unit": _CURRENCY_NAMES.get(currency_code),
        "status": "needs_review", "reason": "", "missing_reason": None, "tax_basis": None,
    }
    text = _text(raw)
    if text.lower() in _MISSING or text in _UNDISCLOSED:
        reason = 'not_applicable' if text == '不适用' else ('not_disclosed' if text in _UNDISCLOSED else 'not_extracted')
        result.update(status="missing", reason={"not_applicable": "金额不适用", "not_disclosed": "原文未披露或未确定金额",
                                                "not_extracted": "未取得金额，不能据此判断原文未披露"}[reason], missing_reason=reason)
        return result
    if isinstance(raw, bool):
        result["reason"] = "金额不能是布尔值"
        return result
    if re.search(r"预算|合计|汇总|总计|累计|总投资|最高限价|项目总额|合同金额|联合体总额", text):
        result["reason"] = "金额含预算或合计口径，不能自动作为单个项目中标金额"
        return result

    approximate = bool(re.search(r"约|大约|近|左右|预计|估计", text))
    text = re.sub(r"^(?:中标金额|中标价格|中标价|成交金额|成交价|金额)\s*[:：]?\s*", "", text)
    text = re.sub(r"^(?:大约|约|近|预计|估计)\s*", "", text)
    text = re.sub(r"\s*左右$", "", text)
    text = re.sub(r"\s+", "", text)
    # Only one numeric expression is allowed. Labelled fragments containing two
    # amounts, a ratio, or an interval do not match this full expression.
    match = re.fullmatch(
        r"(?P<prefix>人民币|RMB|CNY|美元|USD|US\$|港元|港币|HKD|HK\$|欧元|EUR|[¥€])?"
        r"(?P<number>[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)"
        r"(?P<scale>千|万|亿)?(?P<suffix>人民币|美元|港元|港币|欧元|元|RMB|CNY|USD|HKD|EUR)?"
        r"(?P<tax>\(含税\)|\(不含税\))?",
        text, flags=re.IGNORECASE,
    )
    if not match:
        result["reason"] = "金额格式不明确、包含多个金额或区间；请定位单个项目金额原文"
        return result
    prefix = normalize_currency(match["prefix"])
    suffix = normalize_currency(match["suffix"])
    currencies = {v for v in (currency_code, prefix, suffix) if v}
    if len(currencies) > 1:
        result["reason"] = "金额原文与币种字段冲突"
        return result
    resolved_currency = next(iter(currencies)) if currencies else None
    if resolved_currency not in _CURRENCY_NAMES:
        result["reason"] = "币种缺失或暂不支持；不得默认人民币"
        return result
    try:
        amount = Decimal(match["number"].replace(",", "")) * _MULTIPLIERS[match["scale"] or ""]
    except InvalidOperation:
        result["reason"] = "金额不能解析为十进制数"
        return result
    if amount < 0:
        result["reason"] = "中标金额为负数"
        return result
    result.update(
        value=_decimal_string(amount), currency=resolved_currency,
        normalized_unit=_CURRENCY_NAMES[resolved_currency],
        tax_basis={"(含税)": "tax_inclusive", "(不含税)": "tax_exclusive"}.get(match["tax"]),
        status="needs_review" if approximate else "valid",
        reason="近似金额，需人工确认精度" if approximate else "十进制金额及单位校验通过",
    )
    return result


def normalize_date(raw) -> dict:
    """Normalize complete dates only; never fill missing month/day."""
    result = {"raw": raw, "value": None, "status": "needs_review", "reason": ""}
    text = _text(raw)
    if text.lower() in _MISSING:
        result.update(status="missing", reason="日期未披露")
        return result
    match = re.fullmatch(r"(\d{4})(?:年|-|/|\.)(\d{1,2})(?:月|-|/|\.)(\d{1,2})日?", text)
    if not match:
        match = re.fullmatch(r"(\d{4})(\d{2})(\d{2})", text)
    if not match:
        result["reason"] = "需要明确的年、月、日，不能补齐不完整日期"
        return result
    try:
        result["value"] = date(*(int(v) for v in match.groups())).isoformat()
    except ValueError:
        result["reason"] = "日期不存在"
        return result
    result.update(status="valid", reason="日期格式及日历校验通过")
    return result


def validate_records(records: list[dict]) -> list[dict]:
    """Preserve raw records and attach normalized fields and review issues.

    Missing award/disclosure dates are allowed because not all announcements
    disclose them. Missing company/project/amount requires review. Evidence
    correctness is checked by the pipeline's separate source verifier.
    """
    if not isinstance(records, list):
        raise TypeError("records must be a list of dictionaries")
    checked = []
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            raise TypeError(f"record {index} must be a dictionary")
        output = deepcopy(record)
        normalized = {
            "award_amount": normalize_amount(record.get("award_amount_raw"), record.get("currency")),
            "award_date": normalize_date(record.get("award_date")),
            "disclosure_date": normalize_date(record.get("disclosure_date")),
        }
        issues = []
        for field in ("company", "project"):
            if _text(record.get(field)).lower() in _MISSING:
                issues.append({"field": field, "reason": "关键事件字段缺失"})
        amount = normalized["award_amount"]
        if amount["status"] != "valid":
            issues.append({"field": "award_amount_raw", "reason": amount["reason"]})
        amount_type = _text(record.get("award_amount_type", ""))
        if amount_type and amount_type not in {"中标金额", "中标价", "中标价格", "成交金额", "成交价", "award", "award_amount"}:
            amount.update(value=None, status="needs_review", reason="字段口径为预算或合计，不属于单个项目中标金额")
            amount["reason"] = "金额标签不是明确的中标或成交口径，需核对合同、预算或联合体范围"
            issues.append({"field": "award_amount_type", "reason": amount["reason"]})
        for field in ("award_date", "disclosure_date"):
            if normalized[field]["status"] == "needs_review":
                issues.append({"field": field, "reason": normalized[field]["reason"]})
        # A date order anomaly is a review signal, not proof of extraction error.
        if (normalized["award_date"]["value"] and normalized["disclosure_date"]["value"]
                and normalized["award_date"]["value"] > normalized["disclosure_date"]["value"]):
            issues.append({"field": "award_date", "reason": "中标日期晚于公告日期，需核对日期含义"})
        output["normalized"] = normalized
        output["validation_status"] = "needs_review" if issues else "valid"
        output["validation_issues"] = issues
        checked.append(output)
    return checked
