"""技能：跨字段一致性核验。

复用原有规则（prototype/validation.py 的 validate_records），额外补充：
  · 日期顺序：中标日期晚于披露日期 → 待复核（不判为错误，只提示核对含义）
  · 金额口径：字段值含预算/合计字样 → 拦截
  · 证据完整度：事实字段缺失证据 → 记录
  · 计算链完整：金额有值但无换算记录 → 记录

竞赛对应条款：
  「逻辑核验」+「分析严谨性」+「风险审慎性」

本技能**不修改数据**，只产出问题清单 —— 与原 validation.py 的
「Keep original fields unchanged」原则一致。
"""
from __future__ import annotations

from core.models import FIELDS, Record, ReviewStatus
from skills.base import Skill, SkillResult

import sys
from pathlib import Path
_PROTOTYPE = Path(__file__).resolve().parents[1] / "prototype"
if str(_PROTOTYPE) not in sys.path:
    sys.path.insert(0, str(_PROTOTYPE))
from validation import validate_records                        # noqa: E402

#: 关键字段（缺失即需复核）
KEY_FIELDS = ("company", "project")

#: 金额口径关键词（出现即怀疑串用）
AMOUNT_TRAP_WORDS = ("预算", "合计", "汇总", "总计", "累计", "总投资", "最高限价", "项目总额")


class ConsistencyCheckSkill(Skill):
    name = "consistency_check"
    description = "跨字段一致性核验：金额口径、日期顺序、证据完整度、计算链完整"
    uses_tools = ("evidence", "calculate")
    uses_prompts = ("schema",)

    def run(self, records: list[Record]) -> SkillResult:
        self._log_start(records=len(records))
        issues: list[str] = []
        per_record: dict[str, list[dict]] = {}

        # ---- ① 复用原有校验（不改其逻辑）----
        raw_records = [dict(r.record, case_id=r.case_id) for r in records]
        checked = validate_records(raw_records)

        for rec, original in zip(records, checked):
            mine: list[dict] = list(original.get("validation_issues") or [])

            # ---- ② 金额口径：字段值含预算/合计字样 ----
            raw_amount = rec.record.get("award_amount_raw") or ""
            if any(w in str(raw_amount) for w in AMOUNT_TRAP_WORDS):
                mine.append({"field": "award_amount_raw",
                             "reason": "金额原文含预算/合计口径，不能作为单项目中标金额"})

            # ---- ③ 日期顺序 ----
            norm = rec.normalized.get("award_amount")
            award = (original.get("normalized") or {}).get("award_date", {})
            disc = (original.get("normalized") or {}).get("disclosure_date", {})
            if award.get("value") and disc.get("value") and award["value"] > disc["value"]:
                mine.append({"field": "award_date",
                             "reason": "中标日期晚于公告日期，需核对日期含义"})

            # ---- ④ 关键字段缺失 ----
            for field in KEY_FIELDS:
                if not (rec.record.get(field) or "").strip():
                    mine.append({"field": field, "reason": "关键字段缺失"})

            # ---- ⑤ 证据完整度 ----
            for field in FIELDS:
                value = rec.record.get(field)
                if value and field not in rec.evidence:
                    mine.append({"field": field,
                                 "reason": "字段有值但未生成逐字证据"})

            # ---- ⑥ 计算链完整 ----
            if raw_amount and not rec.calculations:
                mine.append({"field": "award_amount_raw",
                             "reason": "金额有值但无单位换算计算记录"})

            # 去重（保留首次出现的）
            seen, dedup = set(), []
            for it in mine:
                key = (it.get("field"), it.get("reason"))
                if key in seen:
                    continue
                seen.add(key)
                dedup.append(it)

            per_record[rec.case_id] = dedup
            rec.validation_issues = dedup
            rec.validation_status = (ReviewStatus.NEEDS_REVIEW if dedup
                                     else ReviewStatus.VALID)
            issues.extend(f"{rec.case_id} · {it['field']}：{it['reason']}" for it in dedup)

        result = SkillResult(
            skill=self.name,
            status=ReviewStatus.NEEDS_REVIEW if issues else ReviewStatus.VALID,
            payload={"per_record": per_record, "checked": checked},
            issues=issues,
            metrics={"records": len(records),
                     "issues_total": len(issues),
                     "needs_review": sum(1 for v in per_record.values() if v)},
        )
        return self._log_end(result)
