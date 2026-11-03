import { api, MODEL, median, retrievalMetrics } from './core.js';

export const configurations = [
  { name: 'FP32 · WASM · batch 1', device: 'wasm', dtype: 'fp32', batchSize: 1 },
  { name: 'FP32 · WASM · batch 8', device: 'wasm', dtype: 'fp32', batchSize: 8 },
  { name: 'INT8 · WASM · batch 1', device: 'wasm', dtype: 'q8', batchSize: 1 },
  { name: 'INT8 · WASM · batch 8', device: 'wasm', dtype: 'q8', batchSize: 8 },
  { name: 'FP32 · WebGPU · batch 8', device: 'webgpu', dtype: 'fp32', batchSize: 8 },
  { name: 'FP16 · WebGPU · batch 8', device: 'webgpu', dtype: 'fp16', batchSize: 8 },
];
export function summarize(run) {
  if (run.error) return { configuration: run.configuration.name, error: run.error };
  const queries = run.repeats.flatMap(r => r.queries);
  const avg = key => queries.reduce((sum, row) => sum + row[key], 0) / queries.length;
  return { configuration: run.configuration.name, backend: run.backend.device, dtype: run.backend.dtype,
    loadMs: run.backend.loadMs, firstEncodingMs: run.repeats[0].documentEmbeddingMs,
    documentEmbeddingMs: median(run.repeats.map(r => r.documentEmbeddingMs)),
    docsPerSecond: median(run.repeats.map(r => r.documents / (r.documentEmbeddingMs / 1000))),
    writeMs: median(run.repeats.map(r => r.writeMs)), refreshMs: median(run.repeats.map(r => r.refreshMs)),
    queryEmbeddingMs: median(queries.map(r => r.queryEmbeddingMs)), dbMs: median(queries.map(r => r.dbMs)),
    queryDisplayedMs: median(queries.map(r => r.queryDisplayedMs)), vectorRecall5: avg('vectorRecall5'),
    vectorNdcg5: avg('vectorNdcg5'), hybridRecall5: avg('hybridRecall5'), hybridNdcg5: avg('hybridNdcg5') };
}
export async function runBenchmark(embeddings, { repeats = 3, onProgress = () => {}, display = async () => {}, configs = configurations } = {}) {
  const corpus = await (await fetch('/data/evaluation.json')).json();
  const report = { format: 1, recordedAt: new Date().toISOString(), model: MODEL,
    userAgent: navigator.userAgent, hardwareConcurrency: navigator.hardwareConcurrency, deviceMemory: navigator.deviceMemory,
    crossOriginIsolated, protocol: '32 original documents, 16 graded queries, K=5, all queries embedded anew; no server inference',
    corpus, modelManifest: await api('/model-manifest'), database: await api('/health'), runs: [] };
  for (const configuration of configs) {
    onProgress(`加载 ${configuration.name}`);
    const run = { configuration, repeats: [] };
    report.runs.push(run);
    try {
      await embeddings.dispose();
      run.backend = await embeddings.load(configuration);
      for (let repeat = 0; repeat < repeats; repeat++) {
        onProgress(`${configuration.name} · 第 ${repeat + 1}/${repeats} 轮`);
        const kb = await api('/kbs', { method: 'POST', body: { title: `bench ${configuration.name} ${repeat + 1}` } });
        try {
          const encoded = await embeddings.embed(corpus.documents.map(x => x.text), configuration);
          const uploaded = await api(`/kbs/${kb.id}/import`, { method: 'POST', body: { model: MODEL,
            documents: corpus.documents.map((doc, i) => ({ ...doc, source: doc.title, chunk: 0, embedding: encoded.vectors[i] })), writeBatchSize: 64 } });
          const observation = { repeat, documents: corpus.documents.length, documentEmbeddingMs: encoded.embeddingMs, ...uploaded, queries: [] };
          run.repeats.push(observation);
          for (const query of corpus.queries) {
            const begin = performance.now();
            const encodedQuery = await embeddings.embed([query.text], configuration);
            const response = await api(`/kbs/${kb.id}/search`, { method: 'POST', body: { text: query.text, embedding: encodedQuery.vectors[0], k: 5 } });
            const queryReadyMs = performance.now() - begin;
            await display(response.results, query.text);
            await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
            const queryDisplayedMs = performance.now() - begin;
            const vectorResponse = await api(`/kbs/${kb.id}/search`, { method: 'POST', body: { text: query.text, embedding: encodedQuery.vectors[0], mode: 'vector', k: 5 } });
            const hybrid = retrievalMetrics(response.results.map(x => x.id), query.relevant);
            const vector = retrievalMetrics(vectorResponse.results.map(x => x.id), query.relevant);
            observation.queries.push({ text: query.text, queryEmbeddingMs: encodedQuery.embeddingMs, dbMs: response.dbMs,
              queryReadyMs, queryDisplayedMs, hybridRecall5: hybrid.recall, hybridNdcg5: hybrid.ndcg,
              vectorRecall5: vector.recall, vectorNdcg5: vector.ndcg, hybridIds: response.results.map(x => x.id), vectorIds: vectorResponse.results.map(x => x.id) });
          }
        } finally { await api(`/kbs/${kb.id}`, { method: 'DELETE' }); }
      }
    } catch (error) { run.error = error.message; }
    run.summary = summarize(run);
  }
  report.summary = report.runs.map(summarize);
  onProgress('对比逐条刷新与批量刷新');
  await embeddings.load({ device: 'wasm', dtype: 'q8' });
  const encoded = await embeddings.embed(corpus.documents.map(x => x.text), { device: 'wasm', dtype: 'q8', batchSize: 8 });
  report.indexExperiment = [];
  for (const configuration of [{ name: '逐条写入并刷新', writeBatchSize: 1, refreshEveryBatch: true }, { name: '64 条批写，末尾刷新', writeBatchSize: 64, refreshEveryBatch: false }]) {
    const observations = [];
    for (let repeat = 0; repeat < repeats; repeat++) {
      const kb = await api('/kbs', { method: 'POST', body: { title: `index ${configuration.name}` } });
      try {
        const start = performance.now();
        const result = await api(`/kbs/${kb.id}/import`, { method: 'POST', body: { ...configuration, model: MODEL,
          documents: corpus.documents.map((doc, i) => ({ ...doc, source: doc.title, embedding: encoded.vectors[i] })) } });
        observations.push({ repeat, ...result, requestMs: performance.now() - start });
      } finally { await api(`/kbs/${kb.id}`, { method: 'DELETE' }); }
    }
    report.indexExperiment.push({ configuration, observations, medianWriteMs: median(observations.map(x => x.writeMs)),
      medianRefreshMs: median(observations.map(x => x.refreshMs)), medianTotalMs: median(observations.map(x => x.totalMs)) });
  }
  onProgress('评测完成，原始数据可导出');
  return report;
}
