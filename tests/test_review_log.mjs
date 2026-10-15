import test from 'node:test';
import assert from 'node:assert/strict';
import {reviewKey,makeReview,exportReview} from '../prototype/web/review-log.mjs';
const result={run_id:'run1',meta:{source_sha256:'abc'},metrics:{field_accuracy:0.5},records:[]};
const record={event_id:'event-1',award_amount_raw:'人民币100万元',evidence:{award_amount_raw:{quote:'人民币100万元'}}};
test('corrections retain original value and evidence without mutating source',()=>{
  const e=makeReview(result,record,'award_amount_raw','corrected','人民币200万元','复核人','见第二标段');
  assert.equal(e.original_value,'人民币100万元');assert.equal(e.proposed_value,'人民币200万元');
  e.original_evidence.quote='changed';assert.equal(record.evidence.award_amount_raw.quote,'人民币100万元');
});
test('review requires author and justification for corrections',()=>{
  assert.throws(()=>makeReview(result,record,'award_amount_raw','corrected','1','','reason'));
  assert.throws(()=>makeReview(result,record,'award_amount_raw','corrected','1','reviewer',''));
});
test('different runs and input bytes are isolated',()=>{
  assert.notEqual(reviewKey(result),reviewKey({...result,meta:{source_sha256:'other'}}));
  const e=makeReview(result,record,'award_amount_raw','confirmed','ignored','复核人','');
  const out=exportReview(result,[e,{...e,run_id:'other'}]);
  assert.equal(out.review_log.length,1);assert.equal(out.automatic_result.metrics.field_accuracy,0.5);
});
