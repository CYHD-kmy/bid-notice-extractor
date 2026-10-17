import * as pdfjs from './node_modules/pdfjs-dist/build/pdf.mjs';
import {projectPath,resultPath,percentage} from './result-path.mjs';
import {reviewKey,makeReview,exportReview} from './review-log.mjs';
pdfjs.GlobalWorkerOptions.workerSrc = './node_modules/pdfjs-dist/build/pdf.worker.mjs';
const labels = {company:'中标公司',project:'项目名称',bidder:'招标方',award_amount_raw:'中标金额原文',currency:'币种',award_date:'中标日期',disclosure_date:'披露日期'};
const el = id => document.getElementById(id);
let result, selected, proof, documentPdf, pageNumber=1, scale=1, serial=0, selectionSerial=0;
const pdfCache = new Map();
let reviewEntries=[];
function node(tag, cls, text) { const n=document.createElement(tag); if(cls)n.className=cls;if(text!==undefined)n.textContent=text;return n; }
function money(record) { const amount=record.normalized.award_amount;return amount.value===null?(amount.status==='missing'?'未取得金额':'金额待复核'):`${amount.value} ${amount.normalized_unit}`; }
function renderRecords() {
  el('records').replaceChildren();
  for(const record of result.records) {
    const button=node('button',`event${record===selected?' active':''}`);
    const top=node('div','event-top');top.append(node('span','project',record.project||'未识别项目'));
    top.append(node('span',`status${record.validation_status==='needs_review'?' review':''}`,record.validation_status==='needs_review'?'待复核':'规则通过'));
    button.append(top,node('div','company',record.company||'公司未披露'));
    const bottom=node('div','event-bottom');bottom.append(node('span','amount',money(record)),node('span','',`${record.case_id}.pdf`));button.append(bottom);
    button.onclick=()=>selectRecord(record);el('records').append(button);
  }
}
async function selectRecord(record) {
  selected=record;renderRecords();el('details').replaceChildren();el('issues').replaceChildren();
  for(const [field,label] of Object.entries(labels)) {
    const evidence=record.evidence[field];
    const button=node('button','field');button.dataset.field=field;button.disabled=!evidence;
    button.append(node('span','field-label',label),node('span','field-value',record[field]??'未披露'));
    if(evidence)button.append(node('span','source-tag',`第 ${evidence.page} 页 ↗`));
    button.onclick=()=>showEvidence(evidence,field);el('details').append(button);
  }
  for(const issue of record.validation_issues)el('issues').append(node('div','issue',`${labels[issue.field]||issue.field}：${issue.reason}`));
  renderReviewHistory();syncReviewValue();
  const first=record.evidence.project||Object.values(record.evidence)[0];
  if(first)await showEvidence(first,'project');
  else {selectionSerial++;serial++;proof=null;documentPdf=null;el('highlights').replaceChildren();el('pdf').getContext('2d').clearRect(0,0,el('pdf').width,el('pdf').height);el('file-name').textContent='';el('page-number').textContent='';el('prev').disabled=true;el('next').disabled=true;el('evidence-caption').textContent='该事件没有可验证的原文定位，请人工复核。';}
}
async function showEvidence(evidence,field) {
  const thisSelection=++selectionSerial;
  serial++;documentPdf=null;el('highlights').replaceChildren();
  el('pdf').getContext('2d').clearRect(0,0,el('pdf').width,el('pdf').height);
  el('prev').disabled=true;el('next').disabled=true;
  proof=evidence;pageNumber=evidence.page;
  document.querySelectorAll('.field').forEach(n=>n.classList.toggle('selected',n.dataset.field===field));
  el('file-name').textContent=evidence.file.split('/').pop();
  el('evidence-caption').textContent=`逐字引文：${evidence.quote} · 第 ${evidence.page} 页 · ${evidence.bboxes.length} 个原文区域`;
  try {
    if(!pdfCache.has(evidence.file))pdfCache.set(evidence.file,pdfjs.getDocument({url:`../../${projectPath(evidence.file)}`,isEvalSupported:false}).promise);
    const loadedPdf=await pdfCache.get(evidence.file);
    if(thisSelection!==selectionSerial)return;
    documentPdf=loadedPdf;await renderPage();
  } catch(error) {if(thisSelection===selectionSerial)el('evidence-caption').textContent=`PDF显示失败：${error.message}`;}
}
async function renderPage() {
  const thisRender=++serial;
  const page=await documentPdf.getPage(pageNumber);if(thisRender!==serial)return;
  scale=Math.min((el('pdf-scroll').clientWidth-36)/page.getViewport({scale:1}).width,1.5);
  const viewport=page.getViewport({scale});
  // Render to an independent canvas so rapid selection cannot start two
  // PDF.js render tasks on the same canvas.
  const canvas=document.createElement('canvas');canvas.id='pdf';
  const dpr=window.devicePixelRatio||1;canvas.width=Math.floor(viewport.width*dpr);canvas.height=Math.floor(viewport.height*dpr);
  canvas.style.width=`${viewport.width}px`;canvas.style.height=`${viewport.height}px`;
  await page.render({canvasContext:canvas.getContext('2d'),viewport,transform:dpr===1?null:[dpr,0,0,dpr,0,0]}).promise;
  if(thisRender!==serial)return;
  el('pdf').replaceWith(canvas);el('paper').style.width=`${viewport.width}px`;el('paper').style.height=`${viewport.height}px`;
  el('page-number').textContent=`第 ${pageNumber} / ${documentPdf.numPages} 页`;
  el('prev').disabled=pageNumber===1;el('next').disabled=pageNumber===documentPdf.numPages;
  el('highlights').replaceChildren();
  if(proof&&proof.page===pageNumber)for(const [x0,y0,x1,y1] of proof.bboxes) {
    const area=node('div','highlight');Object.assign(area.style,{left:`${x0*scale}px`,top:`${y0*scale}px`,width:`${(x1-x0)*scale}px`,height:`${(y1-y0)*scale}px`});el('highlights').append(area);
  }
}
el('prev').onclick=async()=>{if(pageNumber>1){pageNumber--;await renderPage();}};
el('next').onclick=async()=>{if(documentPdf&&pageNumber<documentPdf.numPages){pageNumber++;await renderPage();}};
function syncReviewValue(){el('review-value').value=selected?.[el('review-field').value]??'';}
function renderReviewHistory(){
  el('review-history').replaceChildren();
  for(const entry of reviewEntries.filter(e=>e.event_id===selected?.event_id))el('review-history').append(node('p','',`${labels[entry.field]} · ${{confirmed:'确认原值',corrected:'提出修改',unresolved:'仍需复核'}[entry.action]} · ${entry.proposed_value??'空值'} · ${entry.reviewer} · ${entry.note}`));
}
for(const [field,label] of Object.entries(labels)){const option=node('option','',label);option.value=field;el('review-field').append(option);}
el('review-field').onchange=syncReviewValue;
el('review-form').onsubmit=event=>{
  event.preventDefault();try{
    if(!selected)throw new Error('请先选择事件');
    const entry=makeReview(result,selected,el('review-field').value,el('review-action').value,el('review-value').value,el('reviewer').value,el('review-note').value);
    const next=[...reviewEntries,entry];localStorage.setItem(reviewKey(result),JSON.stringify(next));reviewEntries=next;
    renderReviewHistory();el('review-status').textContent='已保存。人工记录未改写自动提取结果，请导出备份。';
  }catch(error){el('review-status').textContent=`保存失败：${error.message}`;}
};
el('export-review').onclick=()=>{try{
  if(!result)throw new Error('尚未载入结果');
  const blob=new Blob([JSON.stringify(exportReview(result,reviewEntries),null,2)],{type:'application/json'});
  const url=URL.createObjectURL(blob);const link=node('a');link.href=url;link.download='review-log.json';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
}catch(error){el('review-status').textContent=error.message;}};
el('result-form').onsubmit=event=>{event.preventDefault();try{resultPath(el('result-path').value);const url=new URL(location.href);url.searchParams.set('result',el('result-path').value);location.href=url.href;}catch(error){el('records').replaceChildren(node('div','error',error.message));}};
try {
  const requested=new URLSearchParams(location.search).get('result')||'outputs/result.json';
  const path=resultPath(requested);el('result-path').value=requested;
  const response=await fetch(`../../${path}`);if(!response.ok)throw new Error(`无法读取 ${requested}，请确认任务已完成且文件存在`);
  result=await response.json();
  if(!Array.isArray(result.records)||!result.meta||!result.metrics)throw new Error('结果格式不正确');
  try{const saved=JSON.parse(localStorage.getItem(reviewKey(result))||'[]');reviewEntries=Array.isArray(saved)?saved.filter(e=>e.run_id===result.run_id&&e.source_sha256===result.meta.source_sha256):[];}catch(error){el('review-status').textContent=`无法读取本地复核记录：${error.message}`;}
  const directory=path.slice(0,-'result.json'.length);
  for(const [id,file] of [['result-link','result.json'],['metrics-link','metrics.json'],['trace-link','trace.jsonl']])el(id).href=`../../${directory}${file}`;
  el('data-kind').textContent=result.meta.synthetic_data===true?'合成数据':result.meta.synthetic_data===false?'标注声明为真实数据':'数据类别未确认';
  el('run-notice').textContent=`运行编号：${result.run_id}。${result.meta.mode==='replay'?'历史模型响应回放':'已保存的模型推理结果'}；页面操作不调用模型。`;
  el('evaluation-scope').textContent=result.metrics.evaluation_scope||'历史样例评测；不能外推真实公告效果。';
  const accuracy=result.metrics?.field_accuracy;
  const stats=[['事件数',result.records.length],['配套标签字段正确率',percentage(accuracy)],['事件精确率',percentage(result.metrics.event_precision)],['事件召回率',percentage(result.metrics.event_recall)],['待复核事件',result.records.filter(r=>r.validation_status==='needs_review').length],['本次运行模型调用',result.meta.model_calls_this_run??0]];
  for(const [label,value] of stats){const card=node('div','stat');card.append(node('div','value',value),node('div','label',label));el('summary').append(card);}
  el('run-mode').textContent=`${result.meta.model} · ${result.meta.mode==='live'?'已保存真实试跑':'录制结果回放'}`;
  if(result.records.length)await selectRecord(result.records[0]);
  else el('records').append(node('div','error','未提取到事件，请查看执行日志。'));
} catch(error) {el('records').append(node('div','error',error.message));}
