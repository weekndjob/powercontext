import { randomUUID } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import { SeekdbClient, Schema, VectorIndexConfig, FulltextIndexConfig } from 'seekdb';
import { hash, kbId, vector, validateImport, requireValue, SerialQueue } from './validation.mjs';

export const model = JSON.parse(await readFile(new URL('../model-manifest.json', import.meta.url)));
export class KnowledgeStore {
  queue = new SerialQueue();
  handles = new Map();
  constructor(config,{cacheHandles=true}={}) {
    this.client = new SeekdbClient(config);
    this.cacheHandles=cacheHandles;
  }
  async initialize() {
    await this.client.execute(`CREATE TABLE IF NOT EXISTS stepfun_kbs (
      id VARCHAR(40) PRIMARY KEY, title VARCHAR(100) NOT NULL,
      protocol VARCHAR(255) NOT NULL, refresh_pending INT NOT NULL DEFAULT 0,
      created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)`);
    const rows = await this.client.execute('SELECT VERSION() AS version');
    this.version = rows[0].version;
  }
  async get(id) {
    kbId(id);
    const rows = await this.client.execute('SELECT * FROM stepfun_kbs WHERE id=?', [id]);
    requireValue(rows.length === 1, '知识库不存在', 404);
    requireValue(rows[0].protocol === model.protocol, '此知识库使用其他模型版本', 409);
    let collection=this.cacheHandles?this.handles.get(id):null;
    if(!collection) {
      collection=await this.client.getCollection({name:id,embeddingFunction:null});
      if(this.cacheHandles) {
        this.handles.set(id,collection);
        if(this.handles.size>128)this.handles.delete(this.handles.keys().next().value);
      }
    }
    // Pinned seekdb-js 1.4.0 documents the c$v2$ naming convention. Validate
    // its database-generated ID before using this identifier in atomic SQL.
    requireValue(/^[a-zA-Z0-9_-]+$/.test(String(collection.collectionId)), '数据库集合标识异常', 500);
    const table = '`c$v2$' + collection.collectionId + '`';
    if (rows[0].refresh_pending) {
      await collection.refresh_index();
      await this.client.execute('UPDATE stepfun_kbs SET refresh_pending=0 WHERE id=?', [id]);
    }
    return { row:rows[0], collection, table };
  }
  async list() {
    const rows = await this.client.execute('SELECT id,title,created_at FROM stepfun_kbs ORDER BY created_at,id');
    const result = [];
    for (const row of rows) {
      const { table } = await this.get(row.id);
      const counts = await this.client.execute(`SELECT COUNT(*) AS chunks,
        COUNT(DISTINCT JSON_UNQUOTE(JSON_EXTRACT(metadata,'$.sourceKey'))) AS files
        FROM ${table} WHERE JSON_UNQUOTE(JSON_EXTRACT(metadata,'$.live'))='1'`);
      result.push({ ...row, ...counts[0] });
    }
    return result;
  }
  async create(title) {
    requireValue(typeof title === 'string' && title.trim().length > 0 && title.length <= 80, '知识库名称长度应为 1–80');
    const id = 'sf_' + randomUUID().replaceAll('-','');
    await this.client.createCollection({ name:id, schema:new Schema({
      fulltextIndex:new FulltextIndexConfig('beng'),
      vectorIndex:new VectorIndexConfig({ hnsw:{dimension:384,distance:'cosine'}, embeddingFunction:null })
    }) });
    try {
      await this.client.execute('INSERT INTO stepfun_kbs(id,title,protocol) VALUES(?,?,?)', [id,title.trim(),model.protocol]);
    } catch (error) {
      await this.client.deleteCollection(id).catch(() => {});
      throw error;
    }
    return { id, title:title.trim(), files:0, chunks:0 };
  }
  async import(id, body) {
    validateImport(body, model.protocol);
    const { collection, table } = await this.get(id);
    const started = performance.now();
    const importId = randomUUID();
    const ids=[],documents=[],embeddings=[],metadatas=[],sourceKeys=[];
    let skipped = 0;
    for (const file of body.files) {
      const sourceKey = hash(file.source);
      const contentHash = hash(JSON.stringify(file.chunks.map(c => c.text)));
      const old = await this.client.execute(`SELECT COUNT(*) AS n FROM ${table}
        WHERE JSON_UNQUOTE(JSON_EXTRACT(metadata,'$.live'))='1'
        AND JSON_UNQUOTE(JSON_EXTRACT(metadata,'$.sourceKey'))=?
        AND JSON_UNQUOTE(JSON_EXTRACT(metadata,'$.contentHash'))=?`, [sourceKey,contentHash]);
      if (Number(old[0].n) === file.chunks.length) { skipped++; continue; }
      sourceKeys.push(sourceKey);
      file.chunks.forEach((chunk,index) => {
        ids.push(hash(importId+sourceKey+index)); documents.push(chunk.text); embeddings.push(chunk.embedding);
        metadatas.push({ source:file.source,sourceKey,contentHash,importId,chunk:index,
          live:0,dtype:body.dtype,protocol:model.protocol });
      });
    }
    if (!ids.length) return { written:0,skipped,writeMs:0,refreshMs:0,totalMs:performance.now()-started };
    await this.client.execute('UPDATE stepfun_kbs SET refresh_pending=1 WHERE id=?',[id]);
    const writeStart = performance.now();
    await collection.add({ids,documents,embeddings,metadatas});
    const writeMs = performance.now()-writeStart;
    const refreshStart = performance.now();
    await collection.refresh_index();
    // All new rows are invisible until this single atomic publication. A
    // failed/partial add cannot mix an incomplete generation into searches.
    await this.client.execute(`UPDATE ${table} SET metadata=JSON_SET(metadata,'$.live',
      IF(JSON_UNQUOTE(JSON_EXTRACT(metadata,'$.importId'))=?,1,0))
      WHERE JSON_UNQUOTE(JSON_EXTRACT(metadata,'$.sourceKey')) IN (${sourceKeys.map(()=>'?').join(',')})`,
      [importId,...sourceKeys]);
    await collection.refresh_index();
    await this.client.execute('UPDATE stepfun_kbs SET refresh_pending=0 WHERE id=?',[id]);
    return { written:ids.length,skipped,writeMs,refreshMs:performance.now()-refreshStart,totalMs:performance.now()-started };
  }
  async search(id, body) {
    requireValue(body?.protocol === model.protocol, '模型协议不匹配',409);
    requireValue(typeof body.text === 'string' && body.text.trim().length > 0 && body.text.length <= 1000, '查询长度应为 1–1000 字符');
    vector(body.embedding);
    const limit = body.limit ?? 5;
    requireValue(Number.isInteger(limit) && limit >= 1 && limit <= 20,'结果数应为 1–20');
    const { collection } = await this.get(id);
    const started = performance.now();
    const result = await collection.hybridSearch({
      query:{ whereDocument:{$contains:body.text},where:{live:1} },
      knn:{queryEmbeddings:[body.embedding],where:{live:1},nResults:Math.max(30,limit)},
      rank:{rrf:{rankConstant:60,rankWindowSize:50}}, nResults:limit,
      include:['documents','metadatas']
    });
    return { id, engine:'seekdb DBMS_HYBRID_SEARCH (RRF)',dbMs:performance.now()-started,
      results:result.ids[0].map((value,index)=>({id:value,text:result.documents[0][index],
        metadata:result.metadatas[0][index],score:result.distances[0][index]})) };
  }
}
