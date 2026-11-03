import {chunkText} from './core.js';
const $=id=>document.getElementById(id);
const spec=await(await fetch('/model-info.json')).json();
let worker,workerReady,sequence=0,pending=new Map(),currentState=null,activeId=null,epoch=0,busy=false;
function status(text,error=false){$('status').textContent=text;$('status').classList.toggle('error',error);}
function setBusy(value){busy=value;for(const id of ['import','demo','search','create','collections','files']) $(id).disabled=value;}
async function workerCall(action,payload={}) {
  if(!worker){
    let ready,failed;
    workerReady=new Promise((resolve,reject)=>{ready=resolve;failed=reject;});
    worker=new Worker('/embedding-worker.js',{type:'module'});
    worker.onmessage=({data})=>{
      if(data.type==='ready') ready();
      else if(data.type==='state') {
        currentState=data.state;$('backend').textContent=data.state.device.toUpperCase()+' · '+data.state.dtype.toUpperCase();
        $('backend-note').textContent=data.state.reason||'文档与查询均在当前浏览器内计算';
      } else if(data.type==='progress') {
        $('model-progress').textContent=(data.event.file||'模型初始化')+(Number.isFinite(data.event.progress)?' · '+data.event.progress.toFixed(0)+'%':'');
      } else if(data.type==='embedding-progress') {
        $('progress').max=data.total;$('progress').value=data.completed;
        $('model-progress').textContent=`正在本地向量化 ${data.completed}/${data.total}`;
      } else if(data.id) {
        const item=pending.get(data.id);if(!item)return;pending.delete(data.id);
        data.error?item.reject(new Error(data.error)):item.resolve(data.value);
      }
    };
    worker.onerror=error=>{const value=new Error(error.message||'推理 Worker 模块加载失败，请确认已运行 npm run build');failed(value);for(const item of pending.values())item.reject(value);pending.clear();worker?.terminate();worker=null;};
  }
  await workerReady;
  return new Promise((resolve,reject)=>{const id=++sequence;pending.set(id,{resolve,reject});worker.postMessage({id,action,...payload});});
}
async function api(path,body) {
  const response=await fetch(path,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  const data=await response.json();if(!response.ok)throw new Error(data.error||'请求失败');return data;
}
async function refreshList(preferred=activeId) {
  const version=epoch;
  const {collections}=await api('/api/kbs');if(version!==epoch)return collections;
  $('collections').replaceChildren();
  for(const item of collections){const option=document.createElement('option');option.value=item.id;option.textContent=item.title;$('collections').append(option);}
  activeId=collections.some(c=>c.id===preferred)?preferred:collections[0]?.id||null;
  if(activeId)$('collections').value=activeId;
  localStorage.setItem('stepfun-active-kb',activeId||'');
  const current=collections.find(c=>c.id===activeId);$('counts').textContent=current?`${current.files} 份文件 · ${current.chunks} 个分块`:'先创建一个知识库';
  return collections;
}
async function create(title){const value=await api('/api/kbs',{title});epoch++;await refreshList(value.id);$('results').replaceChildren();return value;}
async function importFiles(files,{batchSize=4,profile='auto'}={}) {
  if(!activeId)throw new Error('请先创建知识库');
  if(!files.length)throw new Error('请选择文本文件');
  const names=new Set(),prepared=[];
  for(const file of files){
    if(names.has(file.name))throw new Error('同一批不能包含重复文件名');names.add(file.name);
    if(file.size>512*1024)throw new Error('单份文件上限为 512KB');
    const text=file.textValue??new TextDecoder('utf-8',{fatal:true}).decode(await file.arrayBuffer());
    prepared.push({source:file.name,chunks:chunkText(text).map(text=>({text}))});
  }
  const texts=prepared.flatMap(f=>f.chunks.map(c=>c.text));if(texts.length>128)throw new Error('每次最多 128 个分块，请分批导入');
  const id=activeId,revision=epoch,started=performance.now();
  status('加载本地模型…');const load=await workerCall('load',{profile});
  status('在浏览器内生成文档向量…');
  const embeddings=await workerCall('embed',{texts,batchSize});
  let i=0;for(const file of prepared)for(const chunk of file.chunks)chunk.embedding=embeddings.vectors[i++];
  status('写入 seekdb 并刷新索引…');
  const stored=await api(`/api/kbs/${id}/import`,{protocol:spec.protocol,dtype:embeddings.state.dtype,files:prepared});
  if(revision===epoch){await refreshList(id);status(`导入完成：写入 ${stored.written} 个分块，${stored.skipped} 份文件未变化`);}
  return {load,embedding:embeddings,storage:stored,totalMs:performance.now()-started};
}
async function search(text,{batchSize=4,profile='auto',limit=5}={}) {
  if(!activeId)throw new Error('请先创建知识库');
  const id=activeId,revision=epoch,started=performance.now();
  await workerCall('load',{profile});
  const embedding=await workerCall('embed',{texts:[text],batchSize});
  const value=await api(`/api/kbs/${id}/search`,{text,embedding:embedding.vectors[0],protocol:spec.protocol,limit});
  if(revision===epoch){render(value.results);status(`找到 ${value.results.length} 条结果 · 浏览器向量化 ${embedding.ms.toFixed(1)}ms · seekdb ${value.dbMs.toFixed(1)}ms`);}
  return {...value,queryEmbeddingMs:embedding.ms,e2eMs:performance.now()-started,state:embedding.state};
}
function render(results){
  $('results').replaceChildren();
  if(!results.length){const p=document.createElement('p');p.textContent='没有结果。可尝试换一种表达，或确认文档已经导入。';$('results').append(p);}
  for(const [index,result]of results.entries()){
    const article=document.createElement('article'),heading=document.createElement('h3'),meta=document.createElement('p'),body=document.createElement('p');
    heading.textContent=`${index+1}. ${result.metadata.source}`;meta.className='result-meta';meta.textContent=`分块 ${result.metadata.chunk+1} · seekdb 混合检索排序`;
    body.textContent=result.text;body.className='source-text';article.append(heading,meta,body);$('results').append(article);
  }
}
async function run(action){if(busy)return;setBusy(true);try{await action();}catch(error){status(error.message,true);}finally{setBusy(false);}}
$('create').onclick=()=>run(async()=>{await create($('new-name').value);$('new-name').value='';status('知识库已创建，可以导入资料。');});
$('collections').onchange=()=>{activeId=$('collections').value;epoch++;localStorage.setItem('stepfun-active-kb',activeId);$('results').replaceChildren();refreshList(activeId).catch(e=>status(e.message,true));};
$('import').onclick=()=>run(()=>importFiles([...$('files').files]));
$('demo').onclick=()=>run(async()=>{if(!activeId)await create('英文技术资料示例');const data=await(await fetch('/dataset.json')).json();await importFiles(data.documents.map(d=>({name:d.id+'.txt',textValue:d.text})));});
$('search').onclick=()=>run(()=>search($('query').value.trim()));
$('query-form').onsubmit=event=>{event.preventDefault();$('search').click();};
window.edgeKB={spec,create,importFiles,search,workerCall,api,refreshList,get state(){return currentState;},get activeId(){return activeId;},
  async select(id){epoch++;activeId=id;await refreshList(id);$('results').replaceChildren();},
  async embed(texts,options={}){await workerCall('load',{profile:options.profile||'auto'});return workerCall('embed',{texts,batchSize:options.batchSize||4});}};
try{await refreshList(localStorage.getItem('stepfun-active-kb'));const health=await api('/api/health');$('database').textContent='seekdb 已连接';status(activeId?'可以导入资料或输入查询。':'先创建知识库，或载入示例。');}catch(error){status(error.message,true);}
