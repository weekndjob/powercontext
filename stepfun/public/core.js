export function chunkText(input,maxWords=160,overlap=20) {
  const text=input.replace(/^\uFEFF/,'').trim();
  if(!text) throw new Error('文件内容为空');
  const tokens=[...text.matchAll(/\S+/gu)],chunks=[];
  for(let begin=0;begin<tokens.length;begin+=maxWords-overlap) {
    const last=tokens[Math.min(tokens.length,begin+maxWords)-1];
    const value=text.slice(tokens[begin].index,last.index+last[0].length);
    if(value.length<=3000) chunks.push(value);
    else {
      const chars=Array.from(value);
      for(let i=0;i<chars.length;i+=700) chunks.push(chars.slice(i,i+800).join(''));
    }
    if(begin+maxWords>=tokens.length) break;
  }
  return chunks;
}
export function median(values) {
  const sorted=[...values].sort((a,b)=>a-b),m=Math.floor(sorted.length/2);
  return sorted.length%2?sorted[m]:(sorted[m-1]+sorted[m])/2;
}
export function quality(results,relevance,k=5) {
  const ranked=results.slice(0,k),relevant=Object.entries(relevance).filter(([,v])=>v>0);
  const unique=[...new Set(ranked)];
  const recall=unique.filter(id=>relevance[id]>0).length/Math.max(1,relevant.length);
  const gain=(grade,index)=>(2**grade-1)/Math.log2(index+2);
  const seen=new Set();
  const dcg=ranked.reduce((sum,id,index)=>{const grade=seen.has(id)?0:(relevance[id]||0);seen.add(id);return sum+gain(grade,index);},0);
  const ideal=relevant.map(([,v])=>v).sort((a,b)=>b-a).slice(0,k).reduce((sum,v,i)=>sum+gain(v,i),0);
  return {recall,ndcg:ideal?dcg/ideal:0};
}
