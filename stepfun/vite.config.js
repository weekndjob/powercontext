import { defineConfig } from 'vite';
export default defineConfig({
  server: { host: '127.0.0.1' },
  worker: { format: 'es' },
  build: { target: 'es2022' },
});
