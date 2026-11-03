import {mkdir,copyFile,readFile,writeFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
const root=new URL('../',import.meta.url),vendor=new URL('public/vendor/',root);
await mkdir(vendor,{recursive:true});
const manifest=JSON.parse(await readFile(new URL('runtime-manifest.json',root)));
for(const [name,info]of Object.entries(manifest.assets)) {
  const target=new URL(name,vendor);let data;
  try{data=await readFile(target);}catch{}
  const valid=value=>value?.length===info.bytes&&createHash('sha256').update(value).digest('hex')===info.sha256;
  if(!valid(data)){
    const response=await fetch(info.url,{signal:AbortSignal.timeout(240000)});
    if(!response.ok)throw Error('运行时下载失败：'+name+' HTTP '+response.status);
    data=Buffer.from(await response.arrayBuffer());
    if(!valid(data))throw Error('运行时哈希不一致：'+name);
    await writeFile(target,data);
  }
}
await copyFile(new URL('model-manifest.json',root),new URL('public/model-info.json',root));
console.log('Self-hosted Transformers.js and ONNX WASM assets ready. No CDN is used at runtime.');
