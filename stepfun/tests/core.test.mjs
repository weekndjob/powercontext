import test from 'node:test';
import assert from 'node:assert/strict';
import {chunkText,quality,median} from '../public/core.js';
import {vector,validateImport,SerialQueue} from '../lib/validation.mjs';
test('chunking preserves source spans, covers the tail, and bounds long CJK text',()=>{
  const text=Array.from({length:410},(_,i)=>'word'+i).join('  \n');
  const chunks=chunkText(text);assert.equal(chunks.length,3);
  for(const chunk of chunks)assert.ok(text.includes(chunk));
  assert.ok(chunks.at(-1).endsWith('word409'));assert.ok(chunks[0].includes('word159'));
  assert.throws(()=>chunkText(' \n'));
  for(const part of chunkText('𠮷'.repeat(4000)))assert.ok(part.length<=3000&&!/[\uD800-\uDBFF]$/.test(part));
});
test('rank metrics count duplicate hits once and use graded nDCG',()=>{
  assert.deepEqual(quality(['a','b'],{a:2,b:1},2),{recall:1,ndcg:1});
  const duplicate=quality(['a','a'],{a:2,b:1},2);assert.equal(duplicate.recall,.5);assert.ok(duplicate.ndcg<1);
  assert.equal(median([9,1,5]),5);assert.equal(median([1,4]),2.5);
});
test('reject malformed, nonfinite and wrong-space vectors before any DB mutation',()=>{
  const value=Array(384).fill(1/Math.sqrt(384));assert.equal(vector(value),value);
  for(const bad of [[],Array(384).fill(0),[...value.slice(1),NaN],[...value.slice(1),Infinity]])assert.throws(()=>vector(bad));
  assert.throws(()=>validateImport({protocol:'old'},'current'));
  const file={source:'a.txt',chunks:[{text:'hello',embedding:value}]};
  assert.throws(()=>validateImport({protocol:'p',dtype:'q8',files:[file,file]},'p'));
});
test('complete SDK operations stay serialized even when one request fails',async()=>{
  const queue=new SerialQueue(),events=[];
  const first=queue.run(async()=>{events.push('a:set');await new Promise(r=>setTimeout(r,15));events.push('a:query');throw Error('expected');});
  const second=queue.run(async()=>{events.push('b:set');events.push('b:query');return 7;});
  await assert.rejects(first);assert.equal(await second,7);
  assert.deepEqual(events,['a:set','a:query','b:set','b:query']);
});
