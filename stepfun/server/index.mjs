import express from 'express';
import { SeekdbClient, SeekdbAdminClient, Schema, FulltextIndexConfig, VectorIndexConfig } from 'seekdb';
import { randomUUID } from 'node:crypto';
import { mkdir, readFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { performance } from 'node:perf_hooks';
import { maskSqlStrings } from './sql-safety.mjs';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const model = { id: 'Xenova/all-MiniLM-L6-v2', revision: '751bff37182d3f1213fa05d7196b954e230abad9', dimension: 384 };
const database = process.env.SEEKDB_DATABASE || 'stepfun';
if (!/^[a-zA-Z][a-zA-Z0-9_]{0,50}$/.test(database)) throw new Error('Invalid database name');
const connection = process.env.SEEKDB_HOST ? {
  host: process.env.SEEKDB_HOST, port: Number(process.env.SEEKDB_PORT || 2881), user: process.env.SEEKDB_USER || 'root',
  password: process.env.SEEKDB_PASSWORD || '', queryTimeout: 120000,
} : { path: path.resolve(root, process.env.SEEKDB_PATH || '.data/seekdb') };
const admin = new SeekdbAdminClient(connection);
await admin.createDatabase(database).catch(error => { if (!/exist/i.test(error.message)) throw error; });
await admin.close();
const client = new SeekdbClient({ ...connection, database });
await client.execute(`CREATE TABLE IF NOT EXISTS stepfun_kbs (
  id VARCHAR(64) PRIMARY KEY, title VARCHAR(160) NOT NULL, model_revision VARCHAR(64) NOT NULL,
  revision BIGINT NOT NULL DEFAULT 0, indexed_revision BIGINT NOT NULL DEFAULT 0,
  status VARCHAR(32) NOT NULL DEFAULT 'ready', chunk_count BIGINT NOT NULL DEFAULT 0,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, last_error TEXT)`);
// SDK hybridSearch uses a session variable and three SQL statements. Serializing
// operations on this single SDK connection prevents cross-request session leakage.
let queue = Promise.resolve();
const serial = task => { const result = queue.catch(() => {}).then(task); queue = result.catch(() => {}); return result; };
const app = express();
app.disable('x-powered-by');
app.use((req, res, next) => {
  res.setHeader('Cross-Origin-Opener-Policy', 'same-origin');
  res.setHeader('Cross-Origin-Embedder-Policy', 'require-corp');
  res.setHeader('X-Content-Type-Options', 'nosniff');
  if (req.path.startsWith('/api')) res.setHeader('Cache-Control', 'no-store');
  if (req.headers.origin && req.headers.origin !== `${req.protocol}://${req.headers.host}`) return res.status(403).json({ error: '仅允许同源访问' });
  next();
});
app.use(express.json({ limit: '32mb' }));
const route = handler => (req, res, next) => serial(() => handler(req, res)).catch(next);
const fail = (message, status = 400) => Object.assign(new Error(message), { status });
async function kb(id) {
  if (!/^kb_[a-f0-9]{32}$/.test(id)) throw fail('知识库 ID 无效');
  const rows = await client.execute('SELECT * FROM stepfun_kbs WHERE id=?', [id]);
  if (!rows?.length) throw fail('知识库不存在', 404);
  return rows[0];
}
const handles = new Map();
async function collection(id) {
  if (!handles.has(id)) {
    const coll = await client.getCollection({ name: id, embeddingFunction: null });
    const original = coll.validateDynamicSql.bind(coll);
    coll.validateDynamicSql = sql => original(maskSqlStrings(sql));
    handles.set(id, coll);
  }
  return handles.get(id);
}
function vector(value) {
  if (!Array.isArray(value) || value.length !== model.dimension || !value.every(Number.isFinite)) throw fail('需要浏览器生成的 384 维有限数值向量');
}
async function refresh(id, coll, publish = true) {
  const start = performance.now();
  // Official seekdb refresh procedure; errors remain visible, never silently skipped.
  await client.execute('CALL dbms_index_manager.refresh()');
  const count = await coll.count();
  if (publish) await client.execute("UPDATE stepfun_kbs SET status='ready', indexed_revision=revision, chunk_count=?, last_error=NULL WHERE id=?", [count, id]);
  return { refreshMs: performance.now() - start, count };
}
app.get('/api/health', route(async (_req, res) => {
  const version = await client.execute('SELECT VERSION() AS version');
  res.json({ ok: true, database, storage: connection.path ? 'embedded' : 'server', version: version?.[0]?.version, model });
}));
app.get('/api/kbs', route(async (_req, res) => res.json(await client.execute('SELECT * FROM stepfun_kbs ORDER BY created_at,id'))));
app.post('/api/kbs', route(async (req, res) => {
  const title = String(req.body.title || '').trim();
  if (!title || title.length > 80) throw fail('知识库名称需要 1–80 个字符');
  const id = `kb_${randomUUID().replaceAll('-', '')}`;
  await client.createCollection({ name: id, embeddingFunction: null, schema: new Schema({
    fulltextIndex: new FulltextIndexConfig('beng'),
    vectorIndex: new VectorIndexConfig({ hnsw: { dimension: model.dimension, distance: 'cosine' }, embeddingFunction: null }),
  }) });
  try { await client.execute('INSERT INTO stepfun_kbs(id,title,model_revision) VALUES(?,?,?)', [id, title, model.revision]); }
  catch (error) { await client.deleteCollection(id); throw error; }
  res.status(201).json(await kb(id));
}));
app.delete('/api/kbs/:id', route(async (req, res) => {
  await kb(req.params.id); await client.deleteCollection(req.params.id);
  handles.delete(req.params.id);
  await client.execute('DELETE FROM stepfun_kbs WHERE id=?', [req.params.id]); res.json({ ok: true });
}));
app.post('/api/kbs/:id/import', route(async (req, res) => {
  const state = await kb(req.params.id), body = req.body;
  if (body.model?.id !== model.id || body.model?.revision !== state.model_revision) throw fail('向量模型版本与知识库不一致');
  if (!Array.isArray(body.documents) || !body.documents.length || body.documents.length > 1000) throw fail('每次导入需要 1–1000 个文本片段');
  for (const doc of body.documents) {
    if (typeof doc.id !== 'string' || doc.id.length > 128 || !doc.id) throw fail('文档 ID 无效');
    if (typeof doc.text !== 'string' || !doc.text.trim() || doc.text.length > 4000) throw fail('文本片段需要 1–4000 个字符');
    if (typeof doc.source !== 'string' || doc.source.length > 240) throw fail('来源名称无效');
    vector(doc.embedding);
  }
  const batchSize = Math.max(1, Math.min(64, Number(body.writeBatchSize) || 64));
  const coll = await collection(state.id), begin = performance.now();
  let writeMs = 0, refreshMs = 0, lastRefresh;
  await client.execute("UPDATE stepfun_kbs SET status='importing', revision=revision+1 WHERE id=?", [state.id]);
  try {
    for (let i = 0; i < body.documents.length; i += batchSize) {
      const batch = body.documents.slice(i, i + batchSize), start = performance.now();
      await coll.upsert({ ids: batch.map(x => x.id), documents: batch.map(x => x.text), embeddings: batch.map(x => x.embedding),
        metadatas: batch.map(x => ({ source: x.source, title: String(x.title || x.source), chunk: Number(x.chunk || 0), model: model.id, revision: model.revision })) });
      writeMs += performance.now() - start;
      if (body.refreshEveryBatch) { lastRefresh = await refresh(state.id, coll, false); refreshMs += lastRefresh.refreshMs; }
    }
    let timing;
    if (lastRefresh) {
      const start = performance.now();
      await client.execute("UPDATE stepfun_kbs SET status='ready', indexed_revision=revision, chunk_count=?, last_error=NULL WHERE id=?", [lastRefresh.count, state.id]);
      refreshMs += performance.now() - start;
      timing = lastRefresh;
    } else { timing = await refresh(state.id, coll); refreshMs += timing.refreshMs; }
    res.json({ writeMs, refreshMs, totalMs: performance.now() - begin, count: timing.count, revision: Number(state.revision) + 1, indexed: true });
  } catch (error) {
    await client.execute("UPDATE stepfun_kbs SET status='needs_refresh', last_error=? WHERE id=?", [String(error.message).slice(0, 2000), state.id]);
    throw error;
  }
}));
app.post('/api/kbs/:id/refresh', route(async (req, res) => { const state = await kb(req.params.id); res.json(await refresh(state.id, await collection(state.id))); }));
app.post('/api/kbs/:id/search', route(async (req, res) => {
  const state = await kb(req.params.id);
  if (state.status !== 'ready' || Number(state.revision) !== Number(state.indexed_revision)) throw fail('索引尚未刷新完成，请先刷新', 409);
  vector(req.body.embedding);
  const text = String(req.body.text || '').trim();
  if (!text || text.length > 2000) throw fail('查询需要 1–2000 个字符');
  const nResults = Math.max(1, Math.min(20, Number(req.body.k) || 5)), coll = await collection(state.id), start = performance.now();
  const options = { knn: { queryEmbeddings: [req.body.embedding], nResults: Math.max(20, nResults * 4) },
    query: { whereDocument: { $contains: text }, nResults: Math.max(20, nResults * 4) },
    rank: { rrf: { rankConstant: 60, rankWindowSize: 50 } }, nResults, include: ['documents', 'metadatas', 'distances'] };
  const result = req.body.mode === 'vector' ? await coll.query({ queryEmbeddings: [req.body.embedding], nResults, include: options.include }) : await coll.hybridSearch(options);
  const dbMs = performance.now() - start;
  res.json({ dbMs, revision: state.indexed_revision, mode: req.body.mode === 'vector' ? 'vector' : 'hybrid',
    results: (result.ids?.[0] || []).map((id, i) => ({ id, text: result.documents?.[0]?.[i], metadata: result.metadatas?.[0]?.[i], score: result.distances?.[0]?.[i] })) });
}));
app.get('/api/model-manifest', async (_req, res) => {
  try { res.json(JSON.parse(await readFile(path.join(root, 'public/models/manifest.json'), 'utf8'))); }
  catch { res.status(503).json({ error: '模型文件未准备好，请运行 python3 scripts/download_models.py' }); }
});
app.use('/models', express.static(path.join(root, 'public/models'), { immutable: true, maxAge: '1y', setHeaders: res => res.setHeader('Cross-Origin-Resource-Policy', 'same-origin') }));
if (process.argv.includes('--dev')) {
  const { createServer } = await import('vite');
  const vite = await createServer({ root, server: { middlewareMode: true }, appType: 'spa' });
  app.use(vite.middlewares);
} else app.use(express.static(path.join(root, 'dist')));
app.use((error, _req, res, _next) => {
  console.error(error.message);
  res.status(error.status || 500).json({ error: error.message });
});
await mkdir(path.join(root, 'artifacts'), { recursive: true });
const port = Number(process.env.PORT || 4173);
const server = app.listen(port, process.env.HOST || '127.0.0.1', () => console.log(`星屿 http://127.0.0.1:${port} · seekdb ${connection.path ? 'embedded' : 'server'}`));
for (const signal of ['SIGTERM', 'SIGINT']) process.on(signal, () => server.close(async () => { await client.close(); process.exit(0); }));
