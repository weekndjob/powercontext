import {readFile,writeFile,mkdir} from 'node:fs/promises';
import {createHash} from 'node:crypto';
const root=new URL('../',import.meta.url);
const manifest=JSON.parse(await readFile(new URL('model-manifest.json',root)));
for(const [name,info]of Object.entries(manifest.files)) {
  const target=new URL('public/models/'+manifest.id+'/'+name,root);
  await mkdir(new URL('./',target),{recursive:true});
  let data;
  try{data=await readFile(target);}catch{}
  const valid=value=>{
    if(!value||value.length!==info.bytes)return false;
    return info.sha256?createHash('sha256').update(value).digest('hex')===info.sha256:
      createHash('sha1').update('blob '+value.length+'\0').update(value).digest('hex')===info.gitBlobSha1;
  };
  if(!valid(data)) {
    for(let attempt=0;attempt<3;attempt++) {
      try{
        const response=await fetch(`https://huggingface.co/${manifest.id}/resolve/${manifest.revision}/${name}`,{signal:AbortSignal.timeout(240000)});
        if(!response.ok)throw new Error('HTTP '+response.status);
        data=Buffer.from(await response.arrayBuffer());
        if(!valid(data))throw new Error('模型大小或哈希不一致：'+name);
        await writeFile(target,data);break;
      }catch(error){if(attempt===2)throw error;}
    }
  }
  console.log(name,data.length,createHash('sha256').update(data).digest('hex'));
}
