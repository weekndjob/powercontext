export const MODEL = { id: 'Xenova/all-MiniLM-L6-v2', revision: '751bff37182d3f1213fa05d7196b954e230abad9', dimension: 384 };
export function chunkText(text, maxChars = 600, overlap = 80) {
  const clean = text.replace(/\r\n/g, '\n').trim();
  const chunks = [];
  let start = 0;
  while (start < clean.length) {
    let end = Math.min(start + maxChars, clean.length);
    if (end < clean.length) {
      const boundary = Math.max(clean.lastIndexOf('\n', end - 1), clean.lastIndexOf('. ', end - 1), clean.lastIndexOf('。', end - 1));
      if (boundary > start + maxChars / 2) end = boundary + 1;
    }
    chunks.push(clean.slice(start, end).trim());
    if (end === clean.length) break;
    start = Math.max(start + 1, end - overlap);
  }
  return chunks.filter(Boolean);
}
export async function documentId(source, text, index) {
  const bytes = new TextEncoder().encode(`${source}\0${index}\0${text}`);
  return Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', bytes)), x => x.toString(16).padStart(2, '0')).join('');
}
export function median(values) {
  if (!values.length) return null;
  const sorted = [...values].sort((a, b) => a - b), m = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[m] : (sorted[m - 1] + sorted[m]) / 2;
}
export function retrievalMetrics(ids, relevant, k = 5) {
  const gains = ids.slice(0, k).map(id => relevant[id] || 0);
  const dcg = gains.reduce((sum, gain, i) => sum + (2 ** gain - 1) / Math.log2(i + 2), 0);
  const ideal = Object.values(relevant).sort((a, b) => b - a).slice(0, k)
    .reduce((sum, gain, i) => sum + (2 ** gain - 1) / Math.log2(i + 2), 0);
  return { recall: gains.filter(x => x > 0).length / Object.keys(relevant).length, ndcg: ideal ? dcg / ideal : 0 };
}
export class Embeddings {
  constructor(onEvent = () => {}) {
    this.worker = new Worker(new URL('./embedding-worker.js', import.meta.url), { type: 'module' });
    this.pending = new Map(); this.counter = 0;
    this.worker.onmessage = ({ data }) => {
      if (data.id) {
        const item = this.pending.get(data.id); this.pending.delete(data.id);
        if (data.error) item?.reject(new Error(data.error)); else item?.resolve(data.result);
      } else onEvent(data);
    };
    this.worker.onerror = event => {
      for (const item of this.pending.values()) item.reject(new Error(event.message || '推理 Worker 启动失败'));
      this.pending.clear();
    };
  }
  call(action, args = {}) {
    const id = ++this.counter;
    return new Promise((resolve, reject) => { this.pending.set(id, { resolve, reject }); this.worker.postMessage({ id, action, ...args }); });
  }
  load(options) { return this.call('load', { options }); }
  embed(texts, options) { return this.call('embed', { texts, options }); }
  dispose() { return this.call('dispose'); }
}
export async function api(path, options = {}) {
  const response = await fetch(`/api${path}`, { headers: { 'content-type': 'application/json' }, ...options,
    body: options.body === undefined ? undefined : JSON.stringify(options.body) });
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || response.statusText);
  return result;
}
