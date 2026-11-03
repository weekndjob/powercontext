import test from 'node:test';
import assert from 'node:assert/strict';
import { maskSqlStrings } from '../server/sql-safety.mjs';
import { Collection } from 'seekdb';
const validate = sql => Collection.prototype.validateDynamicSql(maskSqlStrings(sql));
test('ordinary query words and semicolons inside literals are accepted', () => {
  assert.doesNotThrow(() => validate("SELECT 'how to load a model; delete cache?' AS query"));
  assert.doesNotThrow(() => validate("SELECT 'it\\'s a model update', 'double ''quote'''"));
});
test('executable dangerous keywords and additional statements stay rejected', () => {
  assert.throws(() => validate("SELECT 1; DROP TABLE docs"));
  assert.throws(() => validate("SELECT LOAD_FILE('/etc/passwd')"));
  assert.throws(() => validate('DELETE FROM docs'));
  assert.throws(() => validate("SELECT 'unterminated"));
});
