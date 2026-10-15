import test from 'node:test';
import assert from 'node:assert/strict';
import {resultPath,projectPath,percentage} from '../prototype/web/result-path.mjs';
test('run paths and Windows evidence paths',()=>{
  assert.equal(resultPath('outputs/new/result.json'),'outputs/new/result.json');
  assert.equal(projectPath('samples\\one.pdf'),'samples/one.pdf');
});
test('reject traversal and external paths',()=>{
  for(const p of ['../result.json','outputs/../result.json','https://evil/result.json','outputs/%2e%2e/result.json','samples/result.json'])assert.throws(()=>resultPath(p));
});
test('unknown accuracy differs from zero',()=>{
  assert.equal(percentage(null),'未评测');assert.equal(percentage(0),'0.0%');
});
