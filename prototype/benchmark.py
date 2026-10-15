"""Prepare pinned real-source labels, or assess one saved run. Never calls a model."""
import argparse
import hashlib
import json
from pathlib import Path
import re
from urllib.request import urlopen

from evaluation_scope import evaluate_inputs, sha256

ROOT=Path(__file__).resolve().parents[1]

def prepare(dataset, download=False):
    prepared=[]
    for case in dataset['cases']:
        case_id=case['case_id']
        if not re.fullmatch(r'[a-z0-9-]+',case_id):raise ValueError('Invalid case_id')
        pdf=ROOT/'work/benchmark-inputs'/(case_id+'.pdf')
        if not pdf.exists():
            if not download:raise ValueError('缺少来源PDF；明确使用 --download 下载：'+case_id)
            if not case['url'].startswith('https://'):raise ValueError('来源必须为HTTPS')
            with urlopen(case['url'],timeout=25) as response:data=response.read()
            if not data.startswith(b'%PDF') or hashlib.sha256(data).hexdigest()!=case['sha256']:
                raise ValueError('来源PDF格式或SHA256变化：'+case_id)
            pdf.parent.mkdir(parents=True,exist_ok=True);pdf.write_bytes(data)
        if sha256(pdf)!=case['sha256']:raise ValueError('来源PDF指纹不一致：'+case_id)
        folder=ROOT/'work/benchmark-labels'/case_id;folder.mkdir(parents=True,exist_ok=True)
        labels=folder/'expected.json';labels.write_text(json.dumps(case['records'],ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        manifest=folder/'expected.manifest.json'
        manifest.write_text(json.dumps({'data_kind':'real','input_files':[{'file':pdf.relative_to(ROOT).as_posix(),'sha256':case['sha256']}],
                                       'labels_sha256':sha256(labels)},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        prepared.append({'case_id':case_id,'input':str(pdf.relative_to(ROOT)), 'labels':str(labels.relative_to(ROOT)),
                         'manifest':str(manifest.relative_to(ROOT)), 'status':'prepared_not_inferred'})
    return prepared

def assess(case,result_path):
    result=json.loads(result_path.read_text(encoding='utf-8'))
    origin=json.loads(result_path.with_name('origin.json').read_text(encoding='utf-8'))
    expected_file='work/benchmark-inputs/'+case['case_id']+'.pdf'
    fingerprints=[{**p,'file':p['file'].replace('\\','/')} for p in origin['input_files']]
    if fingerprints!=[{'file':expected_file,'sha256':case['sha256']}]:raise ValueError('运行来源与评测样例不匹配')
    if origin.get('source_sha256')!=result['meta'].get('source_sha256'):raise ValueError('运行与来源记录不匹配')
    folder=ROOT/'work/benchmark-labels'/case['case_id']
    metrics=evaluate_inputs(result['records'],[ROOT/expected_file],ROOT,folder/'expected.json',folder/'expected.manifest.json')
    metrics.update(run_mode=result['meta']['mode'],annotation_status='pending_independent_review',
                   is_new_inference=result['meta']['mode']=='live',elapsed_seconds=result['meta'].get('elapsed_seconds'))
    return metrics

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['prepare','assess'])
    parser.add_argument('--download',action='store_true')
    parser.add_argument('--case')
    parser.add_argument('--result',type=Path)
    args=parser.parse_args()
    dataset=json.loads((ROOT/'benchmarks/real-seed.json').read_text(encoding='utf-8'))
    try:
        if args.action=='prepare':report=prepare(dataset,args.download)
        else:
            case=next((c for c in dataset['cases'] if c['case_id']==args.case),None)
            if not case or not args.result:parser.error('assess需要 --case 和 --result')
            report=assess(case,args.result)
        print(json.dumps(report,ensure_ascii=False,indent=2))
    except (ValueError,OSError) as error:parser.error(str(error))

if __name__=='__main__':main()
