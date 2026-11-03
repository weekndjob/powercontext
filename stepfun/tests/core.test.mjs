import test from 'node:test';
import assert from 'node:assert/strict';
import { chunkText, documentId, retrievalMetrics, median } from '../src/core.js';

test('overlapping chunks stay bounded and cover a long document', () => {
  const text = Array.from({ length: 300 }, (_, i) => `Sentence ${i} has evidence.`).join(' ');
  const chunks = chunkText(text);
  assert.ok(chunks.length > 5);
  assert.ok(chunks.every(chunk => chunk.length <= 600));
  for (let i = 0; i < 300; i++) assert.ok(chunks.some(chunk => chunk.includes(`Sentence ${i} has evidence.`)));
  assert.deepEqual(chunkText(' \n '), []);
  assert.ok(chunkText('a'.repeat(600) + '\n' + 'b'.repeat(600)).every(chunk => chunk.length <= 600));
});
test('IDs deduplicate identical imports and preserve changed content versions', async () => {
  assert.equal(await documentId('a.txt', 'text', 0), await documentId('a.txt', 'text', 0));
  assert.notEqual(await documentId('a.txt', 'text', 0), await documentId('a.txt', 'changed', 0));
});
test('graded ranking metrics reward order and relevant coverage', () => {
  assert.deepEqual(retrievalMetrics(['a', 'b'], { a: 3, b: 1 }), { recall: 1, ndcg: 1 });
  assert.ok(retrievalMetrics(['b', 'a'], { a: 3, b: 1 }).ndcg < 1);
  assert.equal(retrievalMetrics(['x'], { a: 3 }).recall, 0);
  assert.equal(median([9, 2, 4, 6]), 5);
});
