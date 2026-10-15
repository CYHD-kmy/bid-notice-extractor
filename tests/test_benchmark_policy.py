from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'prototype'))
from evaluate import field_matches,evaluate_records
from validation import normalize_amount

class BenchmarkPolicyTests(unittest.TestCase):
    def test_source_yuan_unit_can_be_scored_without_inventing_currency_text(self):
        gold={'award_amount_raw':'1,608.50万元','currency':'元'}
        self.assertTrue(field_matches('award_amount_raw',gold,{'award_amount_raw':'1,608.50 万元','currency':'元'}))
        self.assertEqual(normalize_amount(gold['award_amount_raw'],'元')['value'],'16085000')

    def test_different_amount_does_not_match(self):
        self.assertFalse(field_matches('award_amount_raw',{'award_amount_raw':'10万元'},{'award_amount_raw':'20万元'}))

    def test_extra_events_remain_visible(self):
        gold=[{'case_id':'x','project':'甲'}]
        metrics=evaluate_records(gold,gold+[{'case_id':'x','project':'乙'}])
        self.assertEqual(metrics['field_accuracy'],1)
        self.assertEqual(metrics['event_precision'],0.5)

if __name__=='__main__':unittest.main()
