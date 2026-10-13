import * as pdfjs from './node_modules/pdfjs-dist/build/pdf.mjs';
pdfjs.GlobalWorkerOptions.workerSrc = './node_modules/pdfjs-dist/build/pdf.worker.mjs';
const labels = {company:'中标公司',project:'项目名称',bidder:'招标方',award_amount_raw:'中标金额原文',currency:'币种',award_date:'中标日期',disclosure_date:'披露日期'};
const el = id => document.getElementById(id);
let result, selected, proof, documentPdf, pageNumber=1, scale=1, serial=0;
const pdfCache = new Map();
function node(tag, cls, text) { const n=document.createElement(tag); if(cls)n.className=cls;if(text!==undefined)n.textContent=text;return n; }
function money(record) { const amount=record.normalized.award_amount;return amount.value===null?'未披露':`${Number(amount.value).toLocaleString('zh-CN',{maximumFractionDigits:6})} ${amount.normalized_unit}`; }
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
  const first=record.evidence.project||Object.values(record.evidence)[0];
  if(first)await showEvidence(first,'project');
  else el('evidence-caption').textContent='该事件没有可验证的原文定位，请人工复核。';
}
async function showEvidence(evidence,field) {
  proof=evidence;pageNumber=evidence.page;
  document.querySelectorAll('.field').forEach(n=>n.classList.toggle('selected',n.dataset.field===field));
  el('file-name').textContent=evidence.file.split('/').pop();
  el('evidence-caption').textContent=`逐字引文：${evidence.quote} · 第 ${evidence.page} 页 · ${evidence.bboxes.length} 个原文区域`;
  try {
    if(!pdfCache.has(evidence.file))pdfCache.set(evidence.file,pdfjs.getDocument({url:`../../${evidence.file}`,isEvalSupported:false}).promise);
    documentPdf=await pdfCache.get(evidence.file);await renderPage();
  } catch(error) {el('evidence-caption').textContent=`PDF显示失败：${error.message}`;}
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
try {
  const response=await fetch('../../outputs/result.json');if(!response.ok)throw new Error('请先运行原型生成 outputs/result.json');
  result=await response.json();
  const stats=[['事件数',result.records.length],['合成样例字段正确率',`${(result.metrics.field_accuracy*100).toFixed(1)}%`],['待复核事件',result.records.filter(r=>r.validation_status==='needs_review').length],['成功试跑模型调用',result.meta.mode==='live'?result.meta.model_calls_this_run:0]];
  for(const [label,value] of stats){const card=node('div','stat');card.append(node('div','value',value),node('div','label',label));el('summary').append(card);}
  el('run-mode').textContent=`${result.meta.model} · ${result.meta.mode==='live'?'已保存真实试跑':'录制结果回放'}`;
  if(result.records.length)await selectRecord(result.records[0]);
  else el('records').append(node('div','error','未提取到事件，请查看执行日志。'));
} catch(error) {el('records').append(node('div','error',error.message));}
