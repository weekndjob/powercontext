import { chromium } from 'playwright';
import { mkdir, writeFile } from 'node:fs/promises';
import os from 'node:os';

const url = process.env.APP_URL || 'http://127.0.0.1:4173';
const dir = process.env.ARTIFACT_DIR || 'artifacts';
await mkdir(dir, { recursive: true });
const origin = new URL(url).origin;
async function launch(args = []) {
  return chromium.launch({ headless: true, ...(process.platform === 'win32' ? { channel: 'msedge' } : {}), args });
}
async function pageFor(browser) {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1024 } });
  const external = [], errors = [];
  await page.route('**/*', route => {
    if (new URL(route.request().url()).origin !== origin) { external.push(route.request().url()); return route.abort(); }
    return route.continue();
  });
  page.on('pageerror', error => errors.push(error.message));
  page.on('console', message => { if (message.type() === 'error') console.error('browser:', message.text()); });
  await page.goto(url);
  await page.waitForFunction(() => window.stepfun);
  return { page, external, errors };
}
const browser = await launch();
try {
  const { page, external, errors } = await pageFor(browser);
  console.log('Running browser benchmark; all inference executes in the page worker.');
  const report = await page.evaluate(async () => {
    document.querySelector('#technical').open = true;
    return window.stepfun.benchmark({ repeats: 3 });
  });
  report.host = { platform: os.platform(), release: os.release(), arch: os.arch(), cpu: os.cpus()[0]?.model, memoryBytes: os.totalmem(), browserVersion: browser.version() };
  report.networkAudit = { externalRequests: external, pageErrors: errors };
  await writeFile(`${dir}/benchmark.json`, JSON.stringify(report, null, 2));
  console.log(JSON.stringify(report.summary, null, 2));
  await page.screenshot({ path: `${dir}/benchmark.png`, fullPage: true });
  if (report.runs.some(run => run.configuration.device === 'wasm' && run.error)) throw new Error('A required WASM configuration failed');
  if (external.length || errors.length) throw new Error('Network or page error audit failed');
} finally { await browser.close(); }

// A second real browser process with WebGPU disabled, including in workers.
const fallbackBrowser = await launch(['--disable-blink-features=WebGPU', '--disable-gpu', '--disable-software-rasterizer']);
try {
  const { page, external, errors } = await pageFor(fallbackBrowser);
  const result = await page.evaluate(async () => {
    const app = window.stepfun;
    const adapterAvailable = Boolean(await navigator.gpu?.requestAdapter());
    if (adapterAvailable) throw new Error('The fallback test browser still has a GPU adapter');
    app.setProfile({ device: 'auto', batchSize: 8 });
    const kb = await app.api('/kbs', { method: 'POST', body: { title: 'WASM 自动降级验证' } });
    await app.reloadKbs(); app.selectKb(kb.id);
    try {
      const docs = await app.prepare('fallback.txt', 'The browser runs local embedding inference using WebAssembly when WebGPU is unavailable.');
      const imported = await app.importDocuments(docs);
      const response = await app.search('How can the browser run a model without a GPU?');
      const backend = app.getState().backend;
      if (backend.device !== 'wasm' || backend.dtype !== 'q8' || response.results[0]?.id !== docs[0].id) throw new Error('WASM fallback retrieval failed');
      return { adapterAvailable, backend, imported, response, backendLabel: document.querySelector('#backend-label').textContent };
    } finally { await app.api(`/kbs/${kb.id}`, { method: 'DELETE' }); }
  });
  await writeFile(`${dir}/fallback.json`, JSON.stringify({ ...result, externalRequests: external, errors }, null, 2));
  if (external.length || errors.length) throw new Error('Fallback network or page errors');
  console.log('Automatic WASM fallback: PASS');
} finally { await fallbackBrowser.close(); }
