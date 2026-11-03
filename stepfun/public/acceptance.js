export async function run() {
  const app=window.edgeKB,checks=[];
  const check=(name,value,detail)=>{checks.push({name,passed:!!value,detail});if(!value)throw Error(name+': '+JSON.stringify(detail));};
  const a=await app.create('功能验收 A '+Date.now());
  const original='Obsolete cedar archive. '+Array.from({length:350},(_,i)=>'astronomy'+i).join(' ');
  const imported=await app.importFiles([{name:'versioned.txt',textValue:original}]);
  check('long file has multiple persisted chunks',imported.storage.written>1,imported.storage);
  const duplicate=await app.importFiles([{name:'versioned.txt',textValue:original}]);
  check('identical reimport does not duplicate rows',duplicate.storage.written===0&&duplicate.storage.skipped===1,duplicate.storage);
  const replacement='Updated azimuth calibration reference. The spectrometer requires precise optical alignment and repeated calibration before measuring stellar emissions.';
  const replaced=await app.importFiles([{name:'versioned.txt',textValue:replacement}]);
  check('replace long file with one current chunk',replaced.storage.written===1,replaced.storage);
  const fresh=await app.search('Obsolete cedar archive astronomy');
  check('retired chunks never leak into retrieval',fresh.results.length===1&&fresh.results[0].text===replacement,fresh.results.map(x=>x.text));
  await app.importFiles([{name:'incremental.txt',textValue:'Lyra orchard care guide. Apple trees need balanced irrigation, organic nutrients and careful seasonal pruning to produce healthy fruit.'}]);
  const incremental=await app.search('Lyra orchard irrigation');
  check('incremental write immediately searchable',incremental.results.some(r=>r.metadata.source==='incremental.txt'),incremental.results.map(r=>r.metadata.source));
  const b=await app.create('功能验收 B '+Date.now());
  await app.importFiles([{name:'separate.txt',textValue:'Indigo marine research. Coral reefs are underwater ecosystems that support biodiversity. Ocean acidification threatens coral skeletons.'}]);
  const vectors=await app.embed(['azimuth spectrometer calibration','indigo marine coral reefs'],{profile:'auto',batchSize:2});
  const request=(id,text,embedding)=>app.api(`/api/kbs/${id}/search`,{protocol:app.spec.protocol,text,embedding});
  const calls=Array.from({length:8},()=>[
    request(a.id,'azimuth spectrometer calibration',vectors.vectors[0]),
    request(b.id,'indigo marine coral reefs',vectors.vectors[1])]).flat();
  const concurrent=await Promise.all(calls);
  check('sixteen concurrent requests preserve KB and session SQL state',concurrent.every((r,i)=>
    r.id===(i%2?b.id:a.id)&&r.results.length>0&&r.results.every(row=>i%2?row.metadata.source==='separate.txt':row.metadata.source!=='separate.txt')));
  await app.select(a.id);
  const late=app.search('azimuth spectrometer calibration');
  await app.select(b.id);await late;
  check('late results do not render into a newly selected KB',document.getElementById('results').children.length===0);
  await app.select(a.id);
  const before=(await app.api('/api/kbs')).collections.find(k=>k.id===a.id);
  async function rejected(body,status) {
    const response=await fetch(`/api/kbs/${a.id}/import`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    check('invalid import rejected with '+status,response.status===status,await response.json());
  }
  const file={source:'bad.txt',chunks:[{text:'must not persist',embedding:vectors.vectors[0]}]};
  await rejected({protocol:'wrong model',dtype:'fp16',files:[file]},409);
  await rejected({protocol:app.spec.protocol,dtype:'fp16',files:[{...file,chunks:[{text:'bad dimension',embedding:[1]}]}]},400);
  await rejected({protocol:app.spec.protocol,dtype:'fp16',files:[file,file]},400);
  const after=(await app.api('/api/kbs')).collections.find(k=>k.id===a.id);
  check('invalid batches have no visible side effects',before.chunks===after.chunks&&before.files===after.files);
  const markup='<img src=x onerror="window.__stepfunXss=1"> A browser must display this document as plain source text.';
  await app.importFiles([{name:'<script>.txt',textValue:markup}]);
  await app.search('browser plain source text');
  check('untrusted document and filename render as text',!window.__stepfunXss&&document.getElementById('results').querySelector('img')===null&&document.getElementById('results').textContent.includes('<img'));
  await app.select(b.id);
  const result={status:'passed',checks,collections:{a:a.id,b:b.id},expectedSelected:b.id,
    browser:navigator.userAgent,backend:app.state};
  window.edgeAcceptance=result;return result;
}
