import {quality,median} from './core.js';
const average=values=>values.reduce((a,b)=>a+b,0)/values.length;
export async function run(profile='auto',batchSize=4,label=profile) {
  const api=window.edgeKB;
  const dataset=await(await fetch('/dataset.json')).json();
  const corpus=dataset.documents.map(d=>({name:d.id+'.txt',textValue:d.text}));
  const querySet=dataset.queries;
  const report={label,profile,batchSize,startedAt:new Date().toISOString(),
    userAgent:navigator.userAgent,hardwareConcurrency:navigator.hardwareConcurrency,
    deviceMemory:navigator.deviceMemory,corpusCount:corpus.length,queryCount:querySet.length,
    protocol:api.spec.protocol,warmRepetitions:3,queries:[],embeddingSamples:[]};
  report.database=await api.api('/api/health');
  window.edgeBenchmark={phase:'creating collection',label};
  const kb=await api.create('验收 '+label+' '+Date.now());report.collection=kb.id;
  const importResult=await api.importFiles(corpus,{profile,batchSize});
  report.state=importResult.embedding.state;
  report.loadMs=importResult.load.loadMs;
  report.sessionReused=!!importResult.load.reused;
  report.initialization=importResult.load;
  report.firstEmbeddingMs=importResult.embedding.ms;
  report.writeMs=importResult.storage.writeMs;
  report.refreshMs=importResult.storage.refreshMs;
  report.importE2eMs=importResult.totalMs;
  for(let repeat=0;repeat<3;repeat++) {
    window.edgeBenchmark={phase:'warm document embedding',label,repeat};
    const measured=await api.embed(dataset.documents.map(d=>d.text),{profile,batchSize});
    report.embeddingSamples.push({repeat,ms:measured.ms,batches:measured.batches,
      device:measured.state.device,dtype:measured.state.dtype});
  }
  // Keep the first complete query separate from the warmed distribution.
  const first=await api.search(querySet[0].text,{profile,batchSize});
  report.firstQuery={embeddingMs:first.queryEmbeddingMs,dbMs:first.dbMs,e2eMs:first.e2eMs};
  for(let repeat=0;repeat<3;repeat++) {
    for(const [index,query] of querySet.entries()) {
      window.edgeBenchmark={phase:'hybrid queries',label,repeat,index};
      const result=await api.search(query.text,{profile,batchSize,limit:5});
      const ranked=result.results.map(r=>r.metadata.source.replace(/\.txt$/,''));
      report.queries.push({repeat,index,text:query.text,ranked,engine:result.engine,
        queryEmbeddingMs:result.queryEmbeddingMs,dbMs:result.dbMs,e2eMs:result.e2eMs,
        ...quality(ranked,query.relevance,5)});
    }
  }
  const spec=api.spec,commonBytes=spec.common.reduce((n,name)=>n+spec.files[name].bytes,0);
  report.modelBytes=spec.files[spec.weights[report.state.dtype]].bytes+commonBytes;
  report.baselineBytes=spec.files[spec.weights.fp32].bytes+commonBytes;
  report.compressionRatio=report.baselineBytes/report.modelBytes;
  report.summary={embeddingMs:median(report.embeddingSamples.map(s=>s.ms)),
    docsPerSecond:corpus.length*1000/median(report.embeddingSamples.map(s=>s.ms)),
    queryEmbeddingMs:median(report.queries.map(q=>q.queryEmbeddingMs)),
    dbMs:median(report.queries.map(q=>q.dbMs)),e2eMs:median(report.queries.map(q=>q.e2eMs)),
    recallAt5:average(report.queries.map(q=>q.recall)),ndcgAt5:average(report.queries.map(q=>q.ndcg))};
  report.finishedAt=new Date().toISOString();
  window.edgeBenchmark={phase:'complete',label,summary:report.summary};
  window.edgeReports??=[];window.edgeReports.push(report);
  return report;
}
