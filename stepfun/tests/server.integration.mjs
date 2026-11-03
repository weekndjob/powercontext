import test from 'node:test';
import assert from 'node:assert/strict';
import {request} from 'node:http';
const port=Number(process.env.PORT||18380),base='http://127.0.0.1:'+port;
test('running HTTP app: health, origin/host checks and malformed input limits',async()=>{
  const health=await(await fetch(base+'/api/health')).json();
  assert.equal(health.embedding,'browser only');assert.equal(health.status,'ok');
  assert.equal((await fetch(base+'/api/health',{headers:{Origin:'https://untrusted.invalid'}})).status,403);
  const hostStatus=await new Promise((resolve,reject)=>{
    const req=request({hostname:'127.0.0.1',port,path:'/api/health',headers:{Host:'untrusted.invalid'}},res=>{res.resume();res.on('end',()=>resolve(res.statusCode));});
    req.on('error',reject);req.end();
  });assert.equal(hostStatus,403);
  assert.equal((await fetch(base+'/api/kbs',{method:'POST',headers:{'Content-Type':'text/plain'},body:'{}'})).status,415);
  assert.equal((await fetch(base+'/api/kbs',{method:'POST',headers:{'Content-Type':'application/json'},body:'{not json'})).status,400);
  assert.equal((await fetch(base+'/api/kbs',{method:'POST',headers:{'Content-Type':'application/json'},body:'{"title":""}'})).status,400);
  assert.equal((await fetch(base+'/api/kbs',{method:'POST',headers:{'Content-Type':'application/json'},body:'x'.repeat(4*1024*1024+1)})).status,413);
  assert.ok([403,404].includes((await fetch(base+'/%2e%2e/server.mjs')).status));
  assert.equal((await fetch(base+'/favicon.svg')).headers.get('Content-Type'),'image/svg+xml');
});
