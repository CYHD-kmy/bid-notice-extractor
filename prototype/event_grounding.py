"""Conservative event association checks; exact quotes are not semantic proof."""
from collections import defaultdict
import re


def check_event_associations(records, pages):
    by_page = defaultdict(list)
    page_map = {(p['file'], p['page']): p for p in pages}
    for record in records:
        proof = record.get('evidence', {}).get('project')
        record['association_status'] = 'needs_review'
        if proof:
            by_page[proof['file'], proof['page']].append(record)
    for key, group in by_page.items():
        page = page_map[key]
        text = page['text']
        group.sort(key=lambda r: r['evidence']['project']['start'])
        anchors = [r['evidence']['project']['start'] - page['start'] for r in group]
        # A missed event can leave only one extracted anchor. More explicit
        # award labels than extracted events is a reason to withhold approval.
        possible_events = len(re.findall(r'(?:中标金额|成交金额|中标价(?:格)?)(?=\s*(?:为|[:：]|人民币|[¥￥\d]|尚未确定|未披露|暂))', text))
        starts = [max(text.rfind(mark, 0, a) for mark in ('。', '；', ';', '\n')) + 1 for a in anchors]
        ambiguous = len(set(starts)) != len(starts) or len(set(anchors)) != len(anchors)
        incomplete = possible_events > len(group)
        for index, record in enumerate(group):
            issues = record['evidence_issues']
            if ambiguous or incomplete:
                issues.append({'field': 'project', 'reason': '同页事件边界不明确或存在未绑定金额，需复核项目与字段归属'})
                continue
            lo = starts[index] if index else 0
            hi = starts[index + 1] if index + 1 < len(starts) else len(text)
            for field in ('company', 'bidder', 'award_amount_raw', 'award_date'):
                proof = record['evidence'].get(field)
                if not proof:
                    continue
                start, end = proof['start'] - page['start'], proof['end'] - page['start']
                occurrences = len(list(re.finditer(re.escape(proof['quote']), text[lo:hi])))
                if not (lo <= start < end <= hi) or occurrences != 1:
                    issues.append({'field': field, 'reason': '证据落在其他事件范围或事件内重复，不能确认字段归属'})
            record['association_status'] = 'needs_review' if issues else 'no_conflict_detected'
    return records
