import { createHash } from 'node:crypto';
export const DIMENSION = 384;
export function requireValue(condition, message, status = 400) {
  if (!condition) throw Object.assign(new Error(message), { status });
}
export function vector(value) {
  requireValue(Array.isArray(value) && value.length === DIMENSION, '向量必须有 384 个分量');
  requireValue(value.every(x => typeof x === 'number' && Number.isFinite(x) && Math.abs(x) <= 2), '向量包含非法分量');
  const norm = Math.sqrt(value.reduce((s,x) => s+x*x, 0));
  requireValue(norm > .95 && norm < 1.05, '向量必须经过 L2 归一化');
  return value;
}
export function kbId(value) {
  requireValue(typeof value === 'string' && /^sf_[a-f0-9]{32}$/.test(value), '知识库标识无效');
  return value;
}
export const hash = value => createHash('sha256').update(value).digest('hex');
export function validateImport(body, protocol) {
  requireValue(body?.protocol === protocol, '模型版本或向量协议不匹配，请重新加载页面', 409);
  requireValue(Array.isArray(body.files) && body.files.length > 0 && body.files.length <= 64, '请选择 1–64 份文件');
  let total = 0;
  const sources = new Set();
  for (const file of body.files) {
    requireValue(typeof file.source === 'string' && file.source.trim().length > 0 && file.source.length <= 200, '文件名无效');
    requireValue(!sources.has(file.source), '同一批次不能有重复文件名'); sources.add(file.source);
    requireValue(Array.isArray(file.chunks) && file.chunks.length > 0, '文件内容不能为空');
    total += file.chunks.length;
    for (const chunk of file.chunks) {
      requireValue(typeof chunk.text === 'string' && chunk.text.trim().length > 0 && chunk.text.length <= 3000, '文档分块长度必须为 1–3000 字符');
      vector(chunk.embedding);
    }
  }
  requireValue(total <= 128, '每次最多导入 128 个分块，请分批导入');
  requireValue(['q8','fp16','fp32'].includes(body.dtype), '模型精度无效');
  return body;
}
// SDK hybridSearch uses a connection-local @search_parm. Serialize complete
// operations, not individual SQL statements, to prevent cross-request leakage.
export class SerialQueue {
  #tail = Promise.resolve();
  run(operation) {
    const result = this.#tail.then(operation);
    this.#tail = result.catch(() => {});
    return result;
  }
}
