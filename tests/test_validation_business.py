from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'prototype'))
from validation import normalize_amount, normalize_date, validate_records


class BusinessValidationTests(unittest.TestCase):
    def test_decimal_and_scale(self):
        self.assertEqual(normalize_amount('人民币0.326亿元')['value'], '32600000')
        self.assertEqual(normalize_amount('人民币1,280.50万元')['value'], '12805000')

    def test_transaction_label(self):
        self.assertEqual(normalize_amount('成交金额：人民币10万元')['value'], '100000')

    def test_budget_contract_and_joint_totals_rejected(self):
        for label in ('预算', '最高限价', '合同金额', '联合体总额', '合计'):
            with self.subTest(label=label):
                self.assertIsNone(normalize_amount(label+'人民币100万元')['value'])

    def test_semantic_amount_type_is_preserved_for_review(self):
        row={'company':'甲','project':'项目甲','award_amount_raw':'人民币100万元','award_amount_type':'合同金额'}
        result=validate_records([row])[0]
        self.assertEqual(result['validation_status'], 'needs_review')
        self.assertIsNone(result['normalized']['award_amount']['value'])

    def test_missing_states_are_distinct(self):
        self.assertEqual(normalize_amount(None)['missing_reason'],'not_extracted')
        self.assertEqual(normalize_amount('尚未确定')['missing_reason'],'not_disclosed')
        self.assertEqual(normalize_amount('不适用')['missing_reason'],'not_applicable')

    def test_tax_basis_preserved(self):
        self.assertEqual(normalize_amount('人民币100万元（不含税）')['tax_basis'],'tax_exclusive')

    def test_currency_conflict_range_negative_and_bad_date(self):
        for amount in ('人民币100至200万元','人民币-1万元'):
            self.assertIsNone(normalize_amount(amount)['value'])
        self.assertIsNone(normalize_amount('USD20万元','人民币')['value'])
        self.assertIsNone(normalize_date('2026年2月30日')['value'])


if __name__=='__main__': unittest.main()
