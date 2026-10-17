"""Exercise event association through the real record-building pipeline."""
from pathlib import Path
from types import SimpleNamespace
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'prototype'))
from run_demo import build_records


class PipelineAssociationTests(unittest.TestCase):
    def test_cross_project_amount_does_not_pass_pipeline(self):
        text='项目甲。甲公司中标。中标金额人民币100万元。项目乙。乙公司中标。中标金额人民币200万元。'
        page={'file':'fixture.pdf','page':1,'case_id':'fixture','text':text,'start':0,'end':len(text),
              'chars':[{'text':ch,'bbox':[i,0,i+1,1]} for i,ch in enumerate(text)]}
        item=SimpleNamespace(extraction_class='中标事件',extraction_text='项目甲',
            char_interval=SimpleNamespace(start_pos=0,end_pos=3),
            attributes={'company':'甲公司','award_amount_raw':'人民币200万元','currency':'人民币'})
        trace=SimpleNamespace(log=lambda *a,**k:None)
        record=build_records(SimpleNamespace(extractions=[item]),text,[page],trace)[0]
        self.assertEqual(record['validation_status'],'needs_review')
        self.assertEqual(record['award_amount_raw'],'人民币200万元')
        self.assertTrue(record['evidence_issues'])

if __name__=='__main__':unittest.main()
