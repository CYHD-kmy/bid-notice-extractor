export function reviewKey(result) {
  if(!result.run_id||!result.meta?.source_sha256)throw new Error('缺少运行或输入指纹，无法保存复核记录');
  return `bid-review-v1:${result.run_id}:${result.meta.source_sha256}`;
}
export function makeReview(result,record,field,action,value,reviewer,note,now=new Date()) {
  const fields=['company','project','bidder','award_amount_raw','currency','award_date','disclosure_date'];
  if(!fields.includes(field)||!['confirmed','corrected','unresolved'].includes(action))throw new Error('复核字段或动作无效');
  if(!String(reviewer).trim())throw new Error('请填写复核人');
  if(action!=='confirmed'&&!String(note).trim())throw new Error('修改或保留疑点时请说明理由');
  if(!record.event_id)throw new Error('事件缺少编号');
  const original=record[field]??null;
  return {schema_version:1,run_id:result.run_id,source_sha256:result.meta.source_sha256,
    event_id:record.event_id,field,action,original_value:original,
    proposed_value:action==='corrected'?(String(value).trim()||null):original,
    reviewer:String(reviewer).trim(),note:String(note).trim(),time:now.toISOString(),
    original_evidence:structuredClone(record.evidence?.[field]??null)};
}
export function exportReview(result,entries) {
  const matching=entries.filter(e=>e.run_id===result.run_id&&e.source_sha256===result.meta.source_sha256);
  return {schema_version:1,automatic_result:structuredClone(result),review_log:structuredClone(matching),
    scope:'人工复核日志独立保存，不改写自动结果、标准金额或自动评测成绩；修改值需另行核验证据与重新计算。'};
}
