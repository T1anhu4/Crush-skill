import {readFileSync} from 'node:fs';
import {test} from 'node:test';
import assert from 'node:assert/strict';
import ts from 'typescript';

const source=readFileSync(new URL('../src/presentation.ts',import.meta.url),'utf8');
const js=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.ESNext}}).outputText;
const {newMessageIds,draftAfterSend,scrollBehavior,acceptSnapshot}=await import('data:text/javascript;base64,'+Buffer.from(js).toString('base64'));
const old={id:'a',revision:1,messages:[{id:'first'}]};

test('history does not animate on initial load or session switch',()=>{
  assert.deepEqual(newMessageIds(null,old),[]);
  assert.deepEqual(newMessageIds(old,{...old,id:'b'}),[]);
});
test('only newly delivered messages animate, not repeated SSE snapshots',()=>{
  const next={...old,revision:2,messages:[...old.messages,{id:'new'}]};
  assert.deepEqual(newMessageIds(old,next),['new']);
  assert.deepEqual(newMessageIds(next,next),[]);
});
test('late send acknowledgement preserves newly edited text and other sessions',()=>{
  assert.equal(draftAfterSend('下一句话','已经发送','a','a'),'下一句话');
  assert.equal(draftAfterSend('相同内容','相同内容','b','a'),'相同内容');
  assert.equal(draftAfterSend('已经发送','已经发送','a','a'),'');
});
test('initial positioning and reduced motion never smooth scroll',()=>{
  assert.equal(scrollBehavior(true),'instant');
  assert.equal(scrollBehavior(false,true),'instant');
  assert.equal(scrollBehavior(false),'smooth');
});
test('stale snapshots cannot replace another session or newer revision',()=>{
  assert.equal(acceptSnapshot(old,{...old,id:'b'},'a'),false);
  assert.equal(acceptSnapshot({...old,revision:3},old,'a'),false);
  assert.equal(acceptSnapshot(old,{...old,revision:2},'a'),true);
});
