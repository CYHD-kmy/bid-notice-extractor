from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'prototype'))
from event_grounding import check_event_associations


class EventAssociationTests(unittest.TestCase):
    def records(self, text, projects, amounts):
        rows = []
        for project, amount in zip(projects, amounts):
            evidence = {}
            for field, value in [('project', project), ('award_amount_raw', amount)]:
                i = text.index(value)
                evidence[field] = {'file': 'test.pdf', 'page': 1, 'quote': value, 'start': i, 'end': i+len(value)}
            rows.append({'project': project, 'evidence': evidence, 'evidence_issues': []})
        return rows, [{'file': 'test.pdf', 'page': 1, 'start': 0, 'text': text}]

    def test_swapped_amount_is_flagged(self):
        text = '项目甲中标金额人民币100万元。项目乙中标金额人民币200万元。'
        rows, pages = self.records(text, ['项目甲', '项目乙'], ['人民币200万元', '人民币100万元'])
        check_event_associations(rows, pages)
        self.assertTrue(all(r['evidence_issues'] for r in rows))

    def test_correct_associations_have_no_conflicts(self):
        text = '项目甲中标金额人民币100万元。项目乙中标金额人民币200万元。'
        rows, pages = self.records(text, ['项目甲', '项目乙'], ['人民币100万元', '人民币200万元'])
        self.assertTrue(all(not r['evidence_issues'] for r in check_event_associations(rows, pages)))

    def test_omitted_event_with_extra_amount_is_flagged(self):
        text = '项目甲中标金额人民币100万元。项目乙中标金额人民币200万元。'
        rows, pages = self.records(text, ['项目甲'], ['人民币200万元'])
        self.assertTrue(check_event_associations(rows, pages)[0]['evidence_issues'])

    def test_shared_sentence_is_not_treated_as_verified(self):
        text = '项目甲中标金额人民币100万元，项目乙中标金额人民币200万元。'
        rows, pages = self.records(text, ['项目甲', '项目乙'], ['人民币100万元', '人民币200万元'])
        self.assertTrue(all(r['association_status'] == 'needs_review' for r in check_event_associations(rows, pages)))

    def test_repeated_amount_in_same_scope_requires_review(self):
        text = '项目甲中标金额人民币100万元，合同金额人民币100万元。'
        rows, pages = self.records(text, ['项目甲'], ['人民币100万元'])
        self.assertTrue(check_event_associations(rows, pages)[0]['evidence_issues'])

    def test_narrative_reference_to_amount_is_not_an_extra_event(self):
        text = '项目甲中标金额人民币100万元。预算不代表中标金额。'
        rows, pages = self.records(text, ['项目甲'], ['人民币100万元'])
        self.assertFalse(check_event_associations(rows, pages)[0]['evidence_issues'])


if __name__ == '__main__':
    unittest.main()
