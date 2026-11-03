import test from 'node:test';
import assert from 'node:assert/strict';
import {randomUUID} from 'node:crypto';
import {SeekdbAdminClient} from 'seekdb';
import {KnowledgeStore,model} from '../lib/store.mjs';

const config={host:process.env.SEEKDB_HOST||'127.0.0.1',port:Number(process.env.SEEKDB_PORT||2881),
  user:process.env.SEEKDB_USER||'root',password:process.env.SEEKDB_PASSWORD||'',
  database:process.env.SEEKDB_DATABASE||'stepfun_edge_2026'};
// Synthetic normalized vectors exercise publication/recovery semantics only.
// Retrieval-quality evidence uses real browser-generated model vectors instead.
const embedding=Array(384).fill(0);embedding[0]=1;
const payload=text=>({protocol:model.protocol,dtype:'q8',files:[{source:'recovery.txt',chunks:[{text,embedding}]}]});
test('real seekdb: publication failure, refresh recovery and new-client persistence',async()=>{
  const namespace='stepfun_test_'+randomUUID().replaceAll('-','');
  const admin=new SeekdbAdminClient({host:config.host,port:config.port,user:config.user,password:config.password});
  await admin.createDatabase(namespace);
  const isolated={...config,database:namespace};
  const store=new KnowledgeStore(isolated);await store.initialize();
  const kb=await store.create('故障注入 '+Date.now());let restarted;
  try {
    await store.import(kb.id,payload('Original durable recovery passage.'));
    const execute=store.client.execute.bind(store.client);
    store.client.execute=async(sql,params)=>{
      if(sql.startsWith('UPDATE `c$v2$'))throw Error('injected before atomic publication');
      return execute(sql,params);
    };
    await assert.rejects(store.import(kb.id,payload('Incomplete replacement must remain invisible.')),/injected/);
    store.client.execute=execute;
    let result=await store.search(kb.id,{protocol:model.protocol,text:'recovery',embedding});
    assert.equal(result.results.length,1);assert.equal(result.results[0].text,'Original durable recovery passage.');
    const {collection}=await store.get(kb.id);
    const refresh=collection.refresh_index.bind(collection);let count=0;
    collection.refresh_index=async()=>{if(++count===2)throw Error('injected after publication before final refresh');return refresh();};
    await assert.rejects(store.import(kb.id,payload('Published complete replacement survives refresh failure.')),/injected/);
    collection.refresh_index=refresh;
    restarted=new KnowledgeStore(isolated);await restarted.initialize();
    result=await restarted.search(kb.id,{protocol:model.protocol,text:'replacement',embedding});
    assert.equal(result.results.length,1);assert.equal(result.results[0].text,'Published complete replacement survives refresh failure.');
    const rows=await restarted.client.execute('SELECT refresh_pending FROM stepfun_kbs WHERE id=?',[kb.id]);
    assert.equal(rows[0].refresh_pending,0);
    const {table}=await restarted.get(kb.id);
    const ddl=await restarted.client.execute('SHOW CREATE TABLE '+table);
    assert.match(ddl[0]['Create Table'],/VECTOR\(384\)/i);assert.match(ddl[0]['Create Table'],/FULLTEXT/i);
  } finally {
    if(restarted)await restarted.client.close();
    await store.client.deleteCollection(kb.id);
    await store.client.execute('DELETE FROM stepfun_kbs WHERE id=?',[kb.id]);
    await store.client.close();
    await admin.deleteDatabase(namespace);
    await admin.close();
  }
});
