# Third-party components

- [seekdb-js](https://github.com/oceanbase/seekdb-js), `seekdb` 1.4.0, Apache-2.0. Used in server mode; no server embedding provider is installed.
- [Transformers.js](https://github.com/huggingface/transformers.js), 4.3.2, Apache-2.0. The browser distribution is downloaded by `npm run build`, with immutable version and SHA-256 checks in `runtime-manifest.json`.
- [ONNX Runtime Web](https://github.com/microsoft/onnxruntime), 1.31.0-dev.20260914-8d85527a0, MIT. The matching asyncify JavaScript/WASM pair is self-hosted.
- [Xenova/all-MiniLM-L6-v2](https://huggingface.co/Xenova/all-MiniLM-L6-v2/tree/751bff37182d3f1213fa05d7196b954e230abad9), Apache-2.0, original model [sentence-transformers/all-MiniLM-L6-v2](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2). This project uses the publisher's FP32, FP16 and dynamically quantized INT8 ONNX exports. It does not claim to train or newly quantize those weights. Model file identities, sizes and integrity checks are in `model-manifest.json`.

Model and runtime binaries are fetched separately and are not included in Git. Keep the upstream licenses when redistributing downloaded artifacts.
