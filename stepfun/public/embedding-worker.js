import { pipeline, env } from '/vendor/transformers.js?v=4.3.2-bundle';

const spec = await (await fetch('/model-info.json')).json();
env.allowRemoteModels = false;
env.allowLocalModels = true;
env.localModelPath = '/models/' + spec.revision + '/';
env.useBrowserCache = true;
env.useWasmCache = false;
env.backends.onnx.wasm.numThreads = 1;
env.backends.onnx.wasm.proxy = false;
env.backends.onnx.wasm.wasmPaths = {
  mjs:'/vendor/ort-wasm-simd-threaded.asyncify.mjs',
  wasm:'/vendor/ort-wasm-simd-threaded.asyncify.wasm'
};
let extractor, state, requestedProfile, chain = Promise.resolve();
const send = value => self.postMessage(value);

async function load(profile='auto') {
  if (extractor && profile === requestedProfile) return {...state,reused:true,loadMs:0,originalLoadMs:state.loadMs};
  if (extractor) await extractor.dispose();
  extractor = null;
  const begin = performance.now();
  const resourceStart=performance.getEntriesByType('resource').length,assetEvents=[];
  let adapter = null, reason = '', device='wasm', dtype='q8';
  if (profile==='auto' || profile.endsWith('webgpu')) {
    try { adapter = await navigator.gpu?.requestAdapter({powerPreference:'high-performance'}); }
    catch (error) { reason=error.message; }
    if (adapter) {
      device='webgpu';
      dtype=profile==='fp32-webgpu'?'fp32':'fp16';
      if (dtype==='fp16' && !adapter.features.has('shader-f16')) {
        reason='WebGPU 适配器不支持 shader-f16，使用 INT8/WASM'; device='wasm';dtype='q8';
      } else if (env.backends.onnx.webgpu) env.backends.onnx.webgpu.adapter=adapter;
    } else reason ||= '浏览器未提供可用 WebGPU 适配器，自动使用 INT8/WASM';
  } else if (profile==='fp32-wasm') dtype='fp32';
  else if (profile!=='q8-wasm') throw new Error('未知推理配置');
  const progress_callback = event => {
    if(['initiate','done','download'].includes(event.status))assetEvents.push({status:event.status,file:event.file,ms:performance.now()-begin});
    send({type:'progress',event:{status:event.status,file:event.file,progress:event.progress}});
  };
  try {
    extractor=await pipeline('feature-extraction',spec.id,{device,dtype,progress_callback,revision:spec.revision});
  } catch(error) {
    if(device!=='webgpu') throw error;
    reason='WebGPU 初始化失败，已降级 INT8/WASM：'+error.message;
    device='wasm';dtype='q8';
    extractor=await pipeline('feature-extraction',spec.id,{device,dtype,progress_callback,revision:spec.revision});
  }
  requestedProfile=profile;
  const assetLastDone=Math.max(0,...assetEvents.filter(e=>e.status==='done').map(e=>e.ms));
  const resources=performance.getEntriesByType('resource').slice(resourceStart).map(e=>({
    name:e.name,durationMs:e.duration,transferBytes:e.transferSize,bodyBytes:e.encodedBodySize}));
  state={device,dtype,reason,model:spec.id,revision:spec.revision,protocol:spec.protocol,
    dimension:384,loadMs:performance.now()-begin,threads:1,
    reused:false,assetEvents,assetReadyMs:assetLastDone,
    postAssetsInitializationMs:performance.now()-begin-assetLastDone,resources,
    adapter:adapter?{vendor:adapter.info?.vendor,architecture:adapter.info?.architecture,
      description:adapter.info?.description,device:adapter.info?.device}:null};
  send({type:'state',state});
  return state;
}
async function embed(texts,batchSize=4) {
  if(!extractor) await load();
  if(!Array.isArray(texts)||texts.length>128||texts.some(t=>typeof t!=='string'||!t.trim())) throw new Error('向量化输入无效');
  if(!Number.isInteger(batchSize)||batchSize<1||batchSize>16) throw new Error('批大小应为 1–16');
  const started=performance.now(),vectors=[],batches=[];
  for(let offset=0;offset<texts.length;offset+=batchSize) {
    const batch=texts.slice(offset,offset+batchSize),begin=performance.now();
    let output;
    try { output=await extractor(batch,{pooling:'mean',normalize:true,truncation:true,max_length:spec.maxLength}); }
    catch(error) {
      if(state.device!=='webgpu') throw error;
      await extractor.dispose().catch(()=>{}); extractor=null;
      await load('q8-wasm');
      state.reason='WebGPU 执行失败，已降级 INT8/WASM：'+error.message;
      send({type:'state',state});
      output=await extractor(batch,{pooling:'mean',normalize:true,truncation:true,max_length:spec.maxLength});
    }
    const rows=output.tolist();
    if(rows.length!==batch.length||rows.some(v=>v.length!==384||v.some(x=>!Number.isFinite(x)))) throw new Error('模型输出无效');
    vectors.push(...rows);batches.push({offset,count:batch.length,ms:performance.now()-begin});
    send({type:'embedding-progress',completed:vectors.length,total:texts.length});
  }
  return {vectors,ms:performance.now()-started,batches,state};
}
self.onmessage = ({data}) => {
  chain=chain.then(async()=>{
    try {
      const value=data.action==='load'?await load(data.profile):data.action==='embed'?await embed(data.texts,data.batchSize):null;
      if(value===null) throw new Error('未知推理操作');
      send({id:data.id,value});
    } catch(error) { send({id:data.id,error:error.message}); }
  });
};
send({type:'ready'});
