import { mkdir, copyFile, readdir } from 'node:fs/promises';
import path from 'node:path';
const source = path.resolve('node_modules/onnxruntime-web/dist');
await mkdir('dist/ort', { recursive: true });
for (const name of await readdir(source)) {
  if (name.endsWith('.wasm') || (name.startsWith('ort-wasm') && name.endsWith('.mjs'))) {
    await copyFile(path.join(source, name), path.join('dist/ort', name));
  }
}
