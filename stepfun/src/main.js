import './style.css';
import { Embeddings, api, MODEL, chunkText, documentId } from './core.js';
import { runBenchmark } from './benchmark.js';

const $ = selector => document.querySelector(selector);
const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]));
let selected = localStorage.getItem('stepfun.selected'), kbs = [], epoch = 0, working = false, backend, report;
let profile = { device: 'auto', batchSize: 8 }, showImportProgress = false;
const icon = (name) => ({ search: '⌕', plus: '+', book: '▤', arrow: '↗', upload: '↑', bolt: 'ϟ' }[name]);
$('#app').innerHTML = `
<aside class="sidebar"><a class="brand" href="/"><span class="brand-mark">✳</span><span>星屿<small>STARISLAND / LOCAL AI</small></span></a>
  <div class="side-heading">我的知识库 <button id="new-kb" aria-label="新建知识库">+</button></div>
  <nav id="kb-list" aria-label="知识库"></nav>
  <div class="side-note"><span class="orb"></span><strong>知识，在你的设备上生长</strong><p>浏览器完成向量化<br>seekdb 保存与检索</p><a href="#technical">查看运行与评测说明 ↗</a></div>
  <footer>seekdb × 阶跃星辰 <span>2026</span></footer>
</aside>
<main><header class="topbar"><span>WORKSPACE <i>/</i> <span id="breadcrumb">本地知识库</span></span><span id="db-status" class="badge">连接数据库…</span></header>
  <section class="intro"><div><div class="eyebrow">A LITTLE SPACE FOR YOUR KNOWLEDGE</div><h1 id="kb-title">让资料，成为答案。</h1><p>导入你的文字，用语义找到线索。推理就在浏览器里发生。</p></div><div class="local-seal"><span>◎</span> 本地推理<small>NO CLOUD INFERENCE</small></div></section>
  <section class="runtime-strip"><div><span class="status-dot"></span><span id="backend-label">模型尚未加载</span></div><span class="model-name">MiniLM-L6 · 384 维</span><label>推理后端 <select id="backend-choice"><option value="auto">自动 · 优先 WebGPU</option><option value="wasm">WASM · INT8</option><option value="webgpu">WebGPU · FP16</option></select></label><button id="load-model" class="text-button">加载模型 ↗</button></section>
  <div id="notice" class="notice" role="status" aria-live="polite">首次使用会下载公开模型，随后可复用浏览器缓存。文档和向量写入当前连接的 seekdb。</div>
  <div class="workspace-grid"><section class="panel import-panel"><div class="panel-heading"><div><span class="section-number">01</span><h2>把资料放进来</h2></div><span id="chunk-count">0 个片段</span></div>
    <label class="dropzone" id="dropzone"><input id="files" type="file" accept=".txt,.md,.jsonl,text/plain" multiple><span class="upload-icon">${icon('upload')}</span><strong>拖入文件，或点击选择</strong><span>TXT / Markdown / JSONL · 支持连续导入</span></label>
    <div class="or"><span></span>或直接粘贴<span></span></div><input id="source-name" class="source-input" value="随手记" aria-label="资料名称" placeholder="资料名称"><textarea id="paste" placeholder="粘贴一段文字，开始建立你的知识库…" rows="5"></textarea>
    <button id="import-paste" class="primary">向量化并导入 <span>↗</span></button>
    <div class="import-progress" hidden><div><span id="progress-label">准备中</span><span id="progress-value"></span></div><progress id="progress" max="100" value="0"></progress></div>
    <div class="sample-card"><span>先试试看</span><strong>一份关于本地 AI 的小型资料库</strong><p>32 篇英文短文，涵盖浏览器推理、向量检索和数据库。</p><button id="import-demo" class="text-button">导入示例语料 →</button></div>
    <div class="panel-foot"><span>相同来源与内容会去重</span><button id="refresh" class="text-button">刷新索引</button></div>
  </section>
  <section class="panel search-panel"><div class="panel-heading"><div><span class="section-number">02</span><h2>从问题出发</h2></div><select id="search-mode" aria-label="检索方式"><option value="hybrid">混合检索 · RRF</option><option value="vector">语义检索 · 评测对照</option></select></div>
    <form id="search-form"><div class="searchbox"><span>⌕</span><input id="query" required placeholder="例如：浏览器没有 GPU 时如何运行模型？" aria-label="输入查询"><button id="search-button" type="submit" aria-label="检索">→</button></div></form>
    <div class="query-suggestions"><button data-query="How can embeddings run without a cloud service?">本地推理如何保护隐私？</button><button data-query="What happens if the browser cannot access a GPU?">没有 GPU 怎么办？</button></div>
    <div class="results-heading"><span id="results-label">等待你的第一个问题</span><span>TOP 5</span></div><div id="results" aria-live="polite"><div class="empty-state"><div class="empty-graphic">▤<span>✳</span></div><h3>每一个答案，都有出处</h3><p>导入资料后，输入问题。<br>这里将展示数据库排序后的原文与来源。</p></div></div>
    <div id="query-timings" class="query-timings" hidden></div>
  </section></div>
  <section class="stage-metrics"><div><span>文档向量化</span><strong id="m-embed">—<small>ms</small></strong></div><div><span>seekdb 写入</span><strong id="m-write">—<small>ms</small></strong></div><div><span>索引刷新</span><strong id="m-refresh">—<small>ms</small></strong></div><div><span>数据状态</span><strong id="m-state" class="state-value">等待导入</strong></div></section>
  <details class="technical" id="technical"><summary><span>运行与评测实验室<small>模型精度 · 分阶段计时 · 检索质量</small></span><span>展开 +</span></summary><div class="technical-body"><p>模型：${MODEL.id}，revision <code>${MODEL.revision.slice(0, 12)}</code>。英文检索优先；中文检索质量未作保证。文档和查询都由同一浏览器 Worker 编码，模型文件从本地应用加载。</p><p>评测使用 32 篇固定语料、16 条人工标注查询；每个配置重复 3 轮，记录全部原始数据。精度变化比较同一后端、同一批大小；批处理变化比较同一精度。WebGPU 不可用的配置会明确记为失败。</p><div class="bench-actions"><button id="benchmark" class="secondary">运行完整评测</button><button id="export-report" class="text-button" disabled>导出原始 JSON ↓</button><span id="bench-status"></span></div><div id="bench-table"></div><div id="bench-preview"></div></div></details>
  <footer class="main-footer"><span>浏览器本地 embedding → seekdb 存储与数据库内混合检索</span><span>BUILT FOR CURIOUS MINDS ↗</span></footer>
</main><dialog id="create-dialog"><form method="dialog"><h2>新建知识库</h2><p>为一组资料留一个独立的空间。</p><input id="new-title" maxlength="80" placeholder="例如：研究笔记" required><div><button value="cancel" formnovalidate class="text-button">取消</button><button id="create-confirm" class="primary" value="create">创建</button></div></form></dialog>`;

function notify(message, isError = false) { $('#notice').textContent = message; $('#notice').classList.toggle('error', isError); }
function progress(done, total, label) { $('.import-progress').hidden = false; $('#progress-label').textContent = label; $('#progress-value').textContent = `${done}/${total}`; $('#progress').value = total ? done / total * 100 : 0; }
function showBackend(info) { backend = info; $('#backend-label').textContent = `${info.device.toUpperCase()} · ${info.dtype === 'q8' ? 'INT8' : info.dtype.toUpperCase()}`; $('#backend-label').title = JSON.stringify(info.adapter || {}); if (info.reason) notify(info.reason); }
const embeddings = new Embeddings(event => {
  if (event.type === 'backend') showBackend(event.backend);
  else if (event.type === 'notice') notify(event.message);
  else if (event.type === 'progress' && event.progress.status === 'progress') notify(`加载模型 ${event.progress.file || ''} · ${Math.round(event.progress.progress || 0)}%`);
  else if (event.type === 'embedding-progress' && showImportProgress) progress(event.done, event.total, '浏览器正在向量化');
});
function setBusy(value) { working = value; for (const selector of ['#load-model', '#import-paste', '#import-demo', '#search-button', '#benchmark', '#backend-choice', '#files', '#refresh']) $(selector).disabled = value; }
async function task(fn) { if (working) return; setBusy(true); try { return await fn(); } catch (error) { notify(error.message, true); throw error; } finally { setBusy(false); } }
function activeKb() { return kbs.find(x => x.id === selected); }
function selectKb(id) {
  selected = id; epoch++; localStorage.setItem('stepfun.selected', id || '');
  $('#results').innerHTML = '<div class="empty-state"><div class="empty-graphic">▤<span>✳</span></div><h3>在这份资料里寻找线索</h3><p>输入问题，查看原文和来源。</p></div>';
  $('#query-timings').hidden = true; $('#results-label').textContent = '等待你的问题'; renderKbs();
  for (const selector of ['#m-embed', '#m-write', '#m-refresh']) $(selector).innerHTML = '—<small>ms</small>';
}
function renderKbs() {
  $('#kb-list').innerHTML = kbs.map(kb => `<button class="kb-item ${kb.id === selected ? 'active' : ''}" data-kb="${kb.id}"><span>▤</span><span>${esc(kb.title)}<small>${kb.chunk_count} 个片段 · ${kb.status === 'ready' ? '已刷新' : '待刷新'}</small></span><span class="kb-dot">•</span></button>`).join('');
  const kb = activeKb(); $('#kb-title').textContent = kb?.title || '让资料，成为答案。'; $('#breadcrumb').textContent = kb?.title || '本地知识库'; $('#chunk-count').textContent = `${kb?.chunk_count || 0} 个片段`; $('#m-state').textContent = kb ? kb.status === 'ready' ? `已刷新 · r${kb.indexed_revision}` : '需要刷新' : '等待导入';
  for (const item of document.querySelectorAll('[data-kb]')) item.onclick = () => selectKb(item.dataset.kb);
}
async function reloadKbs() { kbs = await api('/kbs'); if (!kbs.some(x => x.id === selected)) selected = kbs[0]?.id; renderKbs(); }
async function ensureKb() {
  if (activeKb()) return activeKb();
  const kb = await api('/kbs', { method: 'POST', body: { title: '我的第一份知识库' } }); await reloadKbs(); selectKb(kb.id); return kb;
}
function resultMarkup(rows, mode = 'hybrid') { return rows.map((row, i) => `<article class="result"><div class="result-top"><span class="rank">${String(i + 1).padStart(2, '0')}</span><span>${esc(row.metadata?.source || '文档')} · 片段 ${Number(row.metadata?.chunk || 0) + 1}</span><span class="result-score">${mode === 'hybrid' ? '排序分值' : '余弦距离'} ${Number(row.score ?? 0).toFixed(4)}</span></div><h3>${esc(row.metadata?.title || row.metadata?.source || '相关原文')}</h3><p>${esc(row.text)}</p><details><summary>查看片段 ID ↗</summary><code>${esc(row.id)}</code></details></article>`).join(''); }
async function importDocuments(docs) {
  const kb = await ensureKb(), capture = epoch;
  notify(`正在导入「${kb.title}」：向量仅在浏览器中计算。`);
  const loaded = await embeddings.load(profile); showBackend(loaded);
  let encoded;
  showImportProgress = true;
  try { encoded = await embeddings.embed(docs.map(x => x.text), profile); }
  finally { showImportProgress = false; }
  progress(0, 1, '写入 seekdb 并刷新索引');
  const response = await api(`/kbs/${kb.id}/import`, { method: 'POST', body: { documents: docs.map((doc, i) => ({ ...doc, embedding: encoded.vectors[i] })), model: MODEL } });
  await reloadKbs();
  if (capture === epoch) { $('#m-embed').innerHTML = `${encoded.embeddingMs.toFixed(0)}<small>ms</small>`; $('#m-write').innerHTML = `${response.writeMs.toFixed(0)}<small>ms</small>`; $('#m-refresh').innerHTML = `${response.refreshMs.toFixed(0)}<small>ms</small>`; }
  progress(1, 1, `「${kb.title}」导入完成`); notify(`「${kb.title}」已保存 ${response.count} 个片段，索引刷新完成。可以开始检索。`);
  return response;
}
async function prepare(source, text) { return Promise.all(chunkText(text).map(async (text, chunk) => ({ id: await documentId(source, text, chunk), text, source, title: source, chunk }))); }
async function search(text, { mode = $('#search-mode').value } = {}) {
  const kb = activeKb(); if (!kb) throw new Error('请先导入资料');
  const capture = epoch, start = performance.now();
  const loaded = await embeddings.load(profile); showBackend(loaded);
  const encoded = await embeddings.embed([text], profile);
  const response = await api(`/kbs/${kb.id}/search`, { method: 'POST', body: { text, embedding: encoded.vectors[0], k: 5, mode } });
  if (capture !== epoch) return { ...response, ignored: true };
  $('#results').innerHTML = response.results.length ? resultMarkup(response.results, mode) : '<div class="empty-state"><h3>暂时没有找到相关片段</h3><p>尝试更换关键词，或导入更多资料。</p></div>';
  $('#results-label').textContent = `${response.results.length} 条相关原文 · ${mode === 'hybrid' ? 'seekdb 混合排序' : '语义检索'}`;
  await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
  const displayedMs = performance.now() - start;
  $('#query-timings').hidden = false;
  $('#query-timings').innerHTML = `<span>查询向量化 <b>${encoded.embeddingMs.toFixed(0)} ms</b></span><span>seekdb <b>${response.dbMs.toFixed(0)} ms</b></span><span>端到端 <b>${displayedMs.toFixed(0)} ms</b></span>`;
  notify(`结果来自「${kb.title}」r${response.revision}。${loaded.loadMs ? `本次包含模型加载 ${loaded.loadMs.toFixed(0)} ms。` : '复用了预热模型。'}`);
  return { ...response, embeddingMs: encoded.embeddingMs, displayedMs };
}
function handle(fn) { return (...args) => Promise.resolve(fn(...args)).catch(error => { console.error(error); notify(error.message, true); }); }
$('#new-kb').onclick = () => $('#create-dialog').showModal();
$('#create-dialog').addEventListener('close', handle(async () => {
  if ($('#create-dialog').returnValue !== 'create') return;
  const kb = await api('/kbs', { method: 'POST', body: { title: $('#new-title').value } }); await reloadKbs(); selectKb(kb.id); $('#new-title').value = '';
}));
$('#load-model').onclick = handle(() => task(async () => { const loaded = await embeddings.load(profile); showBackend(loaded); notify(`模型就绪，加载 ${loaded.loadMs.toFixed(0)} ms · ${loaded.device.toUpperCase()} / ${loaded.dtype}`); }));
$('#backend-choice').onchange = () => { const device = $('#backend-choice').value; profile = { device, batchSize: 8, ...(device === 'wasm' ? { dtype: 'q8' } : device === 'webgpu' ? { dtype: 'fp16' } : {}) }; notify('后端选择已更新，下次操作将加载对应模型。'); };
$('#import-paste').onclick = handle(() => task(async () => { const text = $('#paste').value.trim(); if (!text) throw new Error('请先粘贴资料'); return importDocuments(await prepare($('#source-name').value.trim() || '随手记', text)); }));
async function importFiles(files) { return task(async () => {
  const docs = [];
  for (const file of files) {
    if (!/\.(txt|md|jsonl)$/i.test(file.name)) throw new Error(`${file.name}：目前只支持 TXT、Markdown 与 JSONL`);
    if (file.size > 4 * 1024 * 1024) throw new Error(`${file.name} 超过 4 MB，请拆分文件`);
    const text = await file.text();
    if (file.name.endsWith('.jsonl')) {
      for (const [i, line] of text.split('\n').filter(x => x.trim()).entries()) { const record = JSON.parse(line); if (typeof record.text !== 'string') throw new Error('JSONL 每行需要 text 字段'); docs.push(...await prepare(record.title || `${file.name}:${i + 1}`, record.text)); }
    } else docs.push(...await prepare(file.name, text));
  }
  if (!docs.length) throw new Error('文件中没有可导入文本'); if (docs.length > 1000) throw new Error('单次最多 1000 个片段，请分次导入'); return importDocuments(docs);
}); }
$('#files').onchange = handle(async event => { await importFiles(Array.from(event.target.files)); event.target.value = ''; });
$('#dropzone').ondragover = event => { event.preventDefault(); $('#dropzone').classList.add('dragging'); };
$('#dropzone').ondragleave = () => $('#dropzone').classList.remove('dragging');
$('#dropzone').ondrop = handle(async event => { event.preventDefault(); $('#dropzone').classList.remove('dragging'); if (!working) await importFiles(Array.from(event.dataTransfer.files)); });
$('#import-demo').onclick = handle(() => task(async () => { const data = await (await fetch('/data/evaluation.json')).json(); return importDocuments(data.documents.map(x => ({ ...x, source: x.title, chunk: 0 }))); }));
$('#search-form').onsubmit = handle(async event => { event.preventDefault(); await task(() => search($('#query').value.trim())); });
for (const button of document.querySelectorAll('[data-query]')) button.onclick = () => { $('#query').value = button.dataset.query; $('#search-form').requestSubmit(); };
$('#refresh').onclick = handle(() => task(async () => { if (!selected) throw new Error('请先创建知识库'); const response = await api(`/kbs/${selected}/refresh`, { method: 'POST' }); await reloadKbs(); notify(`索引已刷新 · ${response.refreshMs.toFixed(0)} ms`); }));
async function benchmark(options) {
  report = await runBenchmark(embeddings, { ...options, onProgress: message => { $('#bench-status').textContent = message; }, display: async (rows, text) => { $('#bench-preview').innerHTML = `<h4>实时评测查询：${esc(text)}</h4>${resultMarkup(rows.slice(0, 1))}`; } });
  $('#export-report').disabled = false;
  $('#bench-table').innerHTML = `<table><thead><tr><th>配置</th><th>片段/秒</th><th>DB ms</th><th>端到端 ms</th><th>nDCG@5</th></tr></thead><tbody>${report.summary.map(row => `<tr><td>${esc(row.configuration)}</td>${row.error ? `<td colspan="4">${esc(row.error)}</td>` : `<td>${row.docsPerSecond.toFixed(1)}</td><td>${row.dbMs.toFixed(1)}</td><td>${row.queryDisplayedMs.toFixed(1)}</td><td>${row.hybridNdcg5.toFixed(3)}</td>`}</tr>`).join('')}</tbody></table>`;
  await reloadKbs(); return report;
}
$('#benchmark').onclick = handle(() => task(() => benchmark()));
$('#export-report').onclick = () => { const link = document.createElement('a'); link.href = URL.createObjectURL(new Blob([JSON.stringify(report, null, 2)], { type: 'application/json' })); link.download = 'stepfun-benchmark.json'; link.click(); setTimeout(() => URL.revokeObjectURL(link.href), 5000); };
window.stepfun = { embeddings, api, importDocuments, prepare, search, selectKb, reloadKbs, benchmark, getState: () => ({ selected, backend, kbs }), setProfile: options => { profile = options; } };
handle(async () => { const health = await api('/health'); $('#db-status').textContent = `seekdb · ${health.storage === 'embedded' ? '本地嵌入式' : '本地服务'}`; $('#db-status').classList.add('connected'); await reloadKbs(); })();
