import { pipeline, env } from '@huggingface/transformers';

env.allowRemoteModels = false;
env.allowLocalModels = true;
env.localModelPath = '/models/';
env.useBrowserCache = true;
env.backends.onnx.wasm.wasmPaths = '/ort/';
env.backends.onnx.wasm.numThreads = globalThis.crossOriginIsolated ? Math.min(4, navigator.hardwareConcurrency || 1) : 1;

const MODEL = 'Xenova/all-MiniLM-L6-v2';
let extractor, current, loading;
const send = (type, value) => self.postMessage({ type, ...value });
async function choose(request) {
  let adapter;
  if (request.device !== 'wasm' && navigator.gpu) {
    try { adapter = await navigator.gpu.requestAdapter({ powerPreference: 'high-performance' }); } catch { /* fallback below */ }
  }
  if (request.device === 'webgpu' && !adapter) throw new Error('本浏览器没有可用的 WebGPU adapter');
  const gpu = adapter && (request.dtype !== 'fp16' || adapter.features.has('shader-f16'));
  if (request.device === 'webgpu' && !gpu) throw new Error('WebGPU adapter 不支持 shader-f16');
  const device = request.device === 'wasm' ? 'wasm' : gpu ? 'webgpu' : 'wasm';
  const dtype = request.dtype || (device === 'webgpu' && adapter.features.has('shader-f16') ? 'fp16' : 'q8');
  const info = adapter?.info || {};
  return { device, dtype, adapter: adapter ? { vendor: info.vendor, architecture: info.architecture, device: info.device, description: info.description, fallback: adapter.isFallbackAdapter } : null,
    reason: device === 'wasm' && request.device !== 'wasm' ? 'WebGPU 不可用，已自动切换 WASM INT8' : '', model: MODEL,
    threads: env.backends.onnx.wasm.numThreads };
}
async function load(request = {}) {
  const selection = await choose(request);
  const key = `${selection.device}/${selection.dtype}`;
  if (extractor && current?.key === key) return { ...current, reused: true, loadMs: 0 };
  if (extractor) { await extractor.dispose(); extractor = null; }
  performance.clearResourceTimings();
  const start = performance.now();
  try {
    extractor = await pipeline('feature-extraction', MODEL, {
      device: selection.device, dtype: selection.dtype,
      progress_callback: (progress) => send('progress', { progress }),
    });
  } catch (error) {
    if (request.device === 'webgpu' || selection.device !== 'webgpu') throw error;
    send('notice', { message: `WebGPU 初始化失败，自动降级 WASM：${error.message}` });
    return load({ device: 'wasm', dtype: 'q8' });
  }
  const resources = performance.getEntriesByType('resource').map(entry => ({
    url: entry.name, durationMs: entry.duration, startTime: entry.startTime,
    responseEnd: entry.responseEnd, transferBytes: entry.transferSize,
    encodedBytes: entry.encodedBodySize, decodedBytes: entry.decodedBodySize,
  }));
  const transfers = resources.filter(entry => entry.url.includes('/models/') && entry.transferBytes > 0);
  current = { ...selection, key, loadMs: performance.now() - start, reused: false,
    resources, modelTransferBytes: transfers.reduce((sum, entry) => sum + entry.transferBytes, 0),
    modelTransferMs: transfers.length ? Math.max(...transfers.map(x => x.responseEnd)) - Math.min(...transfers.map(x => x.startTime)) : 0 };
  send('backend', { backend: current });
  return current;
}
async function embed(texts, options = {}) {
  if (!extractor) await load(options);
  const start = performance.now(), vectors = [];
  const batchSize = Math.max(1, Math.min(32, options.batchSize || 8));
  // Group similar lengths to avoid padding every sequence to the longest document.
  const ordered = texts.map((text, index) => ({ text, index })).sort((a, b) => a.text.length - b.text.length);
  for (let offset = 0; offset < ordered.length; offset += batchSize) {
    const batch = ordered.slice(offset, offset + batchSize);
    let output;
    try {
      output = await extractor(batch.map(x => x.text), { pooling: 'mean', normalize: true, truncation: true, max_length: 256 });
    } catch (error) {
      if (options.device === 'webgpu' || current.device !== 'webgpu') throw error;
      await extractor.dispose(); extractor = null;
      await load({ device: 'wasm', dtype: 'q8' });
      send('notice', { message: `WebGPU 推理失败，已降级 WASM：${error.message}` });
      output = await extractor(batch.map(x => x.text), { pooling: 'mean', normalize: true, truncation: true, max_length: 256 });
    }
    const rows = output.tolist();
    batch.forEach((item, i) => { vectors[item.index] = rows[i]; });
    send('embedding-progress', { done: Math.min(offset + batchSize, ordered.length), total: texts.length });
  }
  return { vectors, embeddingMs: performance.now() - start, backend: current };
}
let queue = Promise.resolve();
self.onmessage = ({ data: { id, action, ...args } }) => {
  queue = queue.catch(() => {}).then(async () => {
    try {
      let result;
      if (action === 'load') result = await load(args.options);
      else if (action === 'embed') result = await embed(args.texts, args.options);
      else if (action === 'dispose') { if (extractor) await extractor.dispose(); extractor = null; current = null; result = {}; }
      else throw new Error('未知 Worker 操作');
      self.postMessage({ id, result });
    } catch (error) { self.postMessage({ id, error: error.message }); }
  });
};
