import { createServer } from 'node:http';
import { readFile, stat } from 'node:fs/promises';
import { resolve, extname, sep } from 'node:path';
import { fileURLToPath } from 'node:url';
import { KnowledgeStore, model } from './lib/store.mjs';
import { requireValue } from './lib/validation.mjs';

const port = Number(process.env.PORT || 18380);
const publicRoot = fileURLToPath(new URL('./public/',import.meta.url));
const store = new KnowledgeStore({host:process.env.SEEKDB_HOST||'127.0.0.1',
  port:Number(process.env.SEEKDB_PORT||2881),user:process.env.SEEKDB_USER||'root',
  password:process.env.SEEKDB_PASSWORD||'',database:process.env.SEEKDB_DATABASE||'stepfun_edge_2026'},
  {cacheHandles:process.env.SEEKDB_CACHE_HANDLES!=='0'});
await store.initialize();
const mime = {'.html':'text/html; charset=utf-8','.js':'text/javascript; charset=utf-8',
  '.mjs':'text/javascript; charset=utf-8','.json':'application/json; charset=utf-8',
  '.css':'text/css; charset=utf-8','.svg':'image/svg+xml','.wasm':'application/wasm','.onnx':'application/octet-stream'};
const app = createServer(async (req,res) => {
  res.setHeader('Cross-Origin-Opener-Policy','same-origin');
  res.setHeader('Cross-Origin-Embedder-Policy','require-corp');
  res.setHeader('X-Content-Type-Options','nosniff');
  res.setHeader('Content-Security-Policy',"default-src 'self'; script-src 'self' 'wasm-unsafe-eval'; worker-src 'self' blob:; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; object-src 'none'");
  try {
    requireValue(['localhost:'+port,'127.0.0.1:'+port].includes(req.headers.host),'不接受此 Host',403);
    const url = new URL(req.url,'http://localhost');
    if (url.pathname.startsWith('/api/')) {
      requireValue(!req.headers.origin || ['http://localhost:'+port,'http://127.0.0.1:'+port].includes(req.headers.origin),'不接受跨站请求',403);
      let body = {};
      if (req.method === 'POST') {
        requireValue(req.headers['content-type']?.startsWith('application/json'),'请求必须为 JSON',415);
        if(Number(req.headers['content-length']||0)>4*1024*1024){req.resume();throw Object.assign(new Error('导入数据超过 4MB'),{status:413});}
        let size = 0; const chunks=[];
        for await (const chunk of req) { size+=chunk.length; requireValue(size<=4*1024*1024,'导入数据超过 4MB',413); chunks.push(chunk); }
        try { body=JSON.parse(Buffer.concat(chunks).toString('utf8')); } catch { throw Object.assign(new Error('JSON 格式无效'),{status:400}); }
      }
      const value = await store.queue.run(async () => {
        if (url.pathname==='/api/health' && req.method==='GET') return {status:'ok',version:store.version,embedding:'browser only',protocol:model.protocol,cacheHandles:store.cacheHandles};
        if (url.pathname==='/api/kbs' && req.method==='GET') return {collections:await store.list()};
        if (url.pathname==='/api/kbs' && req.method==='POST') return store.create(body.title);
        const match = url.pathname.match(/^\/api\/kbs\/([^/]+)\/(import|search)$/);
        if (match && req.method==='POST') return match[2]==='import' ? store.import(match[1],body) : store.search(match[1],body);
        throw Object.assign(new Error('接口不存在'),{status:404});
      });
      res.writeHead(200,{'Content-Type':'application/json; charset=utf-8','Cache-Control':'no-store'});
      res.end(JSON.stringify(value)); return;
    }
    requireValue(req.method==='GET'||req.method==='HEAD','请求方法不支持',405);
    const pathname=url.pathname.replace('/models/'+model.revision+'/', '/models/');
    const path=resolve(publicRoot,'.'+decodeURIComponent(pathname==='/'?'/index.html':pathname));
    requireValue(path.startsWith(resolve(publicRoot)+sep),'路径无效',403);
    const info=await stat(path); requireValue(info.isFile(),'文件不存在',404);
    res.writeHead(200,{'Content-Type':mime[extname(path)]||'application/octet-stream','Content-Length':info.size,
      'Cache-Control':url.pathname.startsWith('/models/')||url.pathname.startsWith('/vendor/')?'public, max-age=86400':'no-cache'});
    res.end(req.method==='HEAD'?undefined:await readFile(path));
  } catch(error) {
    const status=error.status||(error.code==='ENOENT'?404:500);
    if(status===500) console.error(error);
    if(!res.headersSent) res.writeHead(status,{'Content-Type':'application/json; charset=utf-8'});
    res.end(JSON.stringify({error:status===500?'数据库操作失败，请查看本地服务日志':error.message}));
  }
});
app.listen(port,'127.0.0.1',()=>console.log('StepFun Edge Knowledge Base: http://localhost:'+port));
for (const signal of ['SIGINT','SIGTERM']) process.on(signal,()=>app.close(async()=>{await store.client.close();process.exit(0);}));
