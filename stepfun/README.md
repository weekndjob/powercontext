# 星屿：浏览器本地推理与 seekdb 混合检索

阶跃星辰赛题实现。文档和查询的 embedding 都由浏览器 Web Worker 运行 Transformers.js 生成；Node 服务只处理文档、向量、集合状态及数据库检索，不运行模型。默认使用本地嵌入式 seekdb，也可连接本地 seekdb server。

## 启动

需要 Node.js 22.12+、Python 3.10+，以及当前 Chrome / Edge。浏览器访问 `localhost` 或 HTTPS，WebGPU 要求安全上下文。

```bash
cd stepfun
npm ci
python3 scripts/download_models.py
npm run build
npm start
# 打开 http://127.0.0.1:4173
```

Windows 将 `python3` 换成 `python`。下载脚本仅使用 Python 标准库。固定模型与 tokenizer revision，并校验三份 ONNX 权重的上游 LFS SHA-256；模型约 160 MB，不放入 Git。`public/models/manifest.json` 记录实际文件体积、哈希和压缩比。

默认第一次启动 seekdb-js 嵌入式模式时，其官方 native binding 可能需要联网下载。数据持久化于 `.data/seekdb`。若已经有本地数据库，可复制 `.env.example` 为 `.env`，配置 `SEEKDB_HOST`、端口及凭据，应用启动时会自动读取。不要提交 `.env`。

使用现有 seekdb 可执行文件启动独立服务：

```bash
SEEKDB_BIN=/absolute/path/to/seekdb SEEKDB_PORT=2881 bash scripts/start-db.sh
# 另一终端写入 .env：
# SEEKDB_HOST=127.0.0.1
# SEEKDB_PORT=2881
# SEEKDB_DATABASE=stepfun
npm start
```

数据库需要支持 `DBMS_HYBRID_SEARCH.GET_SQL` 和 `dbms_index_manager.refresh()`；本次验收使用 seekdb 1.4.0。应用默认仅监听 127.0.0.1，数据库密码不进入前端。远程实验室使用 SSH 隧道访问，例如 `ssh -L 4173:127.0.0.1:4173 dzp@服务器`，随后访问本地 4173；不要把普通 HTTP IP 地址当作 WebGPU 安全上下文。

也提供 `docker compose up -d` 的本地 server 启动配置，固定使用官方 `oceanbase/seekdb:1.4.0-100000172026082615`，并使用 Docker named volume 持久化。等待镜像完成 bootstrap 后，将 `.env` 的 `SEEKDB_HOST=127.0.0.1`、`SEEKDB_PORT=2881` 打开。本次实测采用实验室已有可执行文件启动服务；Docker 配置依据[官方部署文档](https://github.com/oceanbase/docker-images/blob/main/seekdb/README.md)，未在本次环境运行容器。

## 使用

1. 创建或选择知识库，加载模型。默认自动优先 WebGPU；不可用或初始化/推理失败时降级为 WASM INT8，界面显示实际后端。
2. 导入 TXT / Markdown / JSONL，或粘贴文字。JSONL 每行至少有 `text` 字段，可有 `title`。单文件最多 4 MB，单次最多 1000 个片段。
3. 等待浏览器向量化、写入和刷新完成，再输入问题。默认数据库内混合检索，显示 TOP 5 原文、来源、片段位置与排序分值。语义检索选项用于评测对照。
4. 可以连续导入、切换知识库、刷新页面。相同来源、片段位置和内容的导入会去重；修改内容产生新版本片段并保留旧版本。当前实现不自动覆盖同名文件的历史内容。

模型偏向英文；示例语料与质量评测使用英文。界面是中文，支持导入 UTF-8 中文文本，但未宣称该英文模型具有同等中文检索质量。长文按最多 600 字符、80 字符重叠切片，模型最大输入 256 tokens。

## 模型与量化

- 模型：[`Xenova/all-MiniLM-L6-v2`](https://huggingface.co/Xenova/all-MiniLM-L6-v2/tree/751bff37182d3f1213fa05d7196b954e230abad9)，revision `751bff37182d3f1213fa05d7196b954e230abad9`，Apache-2.0；原始模型为 sentence-transformers/all-MiniLM-L6-v2。
- FP32 基线：`onnx/model.onnx`；FP16：`onnx/model_fp16.onnx`；INT8：`onnx/model_quantized.onnx`。采用该公开仓库已导出的量化产物，没有训练模型，也没有声称这些产物由本队重新量化。
- 获取步骤由 `scripts/download_models.py` 固定复现：下载同一 revision 的 tokenizer/config 和三种权重，分块校验下载范围，核对公开权重哈希，然后按实际文件字节数统计。Transformers.js 显式设置 `dtype: 'fp32'/'fp16'/'q8'`，INT8 为量化权重推理，输出仍为归一化 FP32 向量；FP16 并不表示所有形状处理算子都在 GPU 上执行。
- 统一 mean pooling、L2 normalization、384 维。模型文件来自本地应用 `/models/`，推理时禁止远程模型下载；没有任何云端推理 SDK 或 API 调用。
- `python3 scripts/audit_models.py` 可核对 ONNX initializer 类型。q8 图包含 INT8 矩阵乘法权重、UINT8 词嵌入及 FP32 scale/LayerNorm，并非所有常量都是有符号 INT8；FP16 图的浮点权重为 FLOAT16，位置索引仍是 INT64。实测类型与字节数保存在 `artifacts/onnx-weight-audit.json`。
- `.npmrc` 的 `legacy-peer-deps` 避免 seekdb 的默认 embedding peer 被自动安装；应用显式传 `embeddingFunction: null`。`ignore-scripts` 避免安装前端依赖时运行无关的 Node 推理二进制下载脚本；浏览器 ONNX Runtime WASM 文件由构建脚本复制到本地站点。

## 数据与检索

每个知识库使用独立 SDK collection，保存 `id`、`document`、`embedding VECTOR(384)` 和 JSON 元数据。索引是 cosine HNSW 与 BENG 全文索引。`stepfun_kbs` 也是 seekdb 表，保存名称、模型版本、写入 revision、索引 revision、状态和片段数。

服务端使用 `collection.hybridSearch()`，一次提交全文 `query_string` 与浏览器生成的查询向量，由 `DBMS_HYBRID_SEARCH` 在数据库内生成并执行 RRF 检索；候选数为 max(20, 4K)，RRF 常数 60、窗口 50。客户端不拉取两路候选后自行合并。向量模式只作为同一数据库上的质量对照。

正常导入按最多 64 条 upsert，一次导入末尾调用 `CALL dbms_index_manager.refresh()`。刷新失败保留已写片段并标记 `needs_refresh`，查询返回 409，用户可显式重试刷新。所有写入值使用参数绑定。SDK 单连接上的多语句混合检索在应用中串行执行，避免 session variable 被并发请求覆盖。collection handle 缓存以减少重复元数据查询，数据库仍是持久状态来源。

SDK 1.4.0 原有 SQL 检查会误把查询字符串里的 `load` 等词当作 SQL 关键字。本应用在调用其原有检查器之前，用识别转义和双引号重复的扫描器屏蔽字符串内容，保留结构检查；原 SQL 未被改写。回归测试同时验证普通查询被接受，以及实际 `DROP`、额外语句、`LOAD_FILE` 仍被拒绝。

浏览器仅在 localStorage 保存当前知识库 ID，不在客户端维护检索数据库。每次操作捕获当前 collection ID；切换后旧查询响应不会覆盖新界面。刷新页面后从 seekdb 重载集合与索引状态。

## 复现评测

```bash
npm test
# 应用启动后，Windows 使用安装的 Edge，其他系统使用 Playwright Chromium：
npx playwright install chromium  # 已安装 Edge 的 Windows 可跳过
APP_URL=http://127.0.0.1:4173 node scripts/browser-smoke.mjs
APP_URL=http://127.0.0.1:4173 npm run benchmark
```

PowerShell：先执行 `$env:APP_URL='http://127.0.0.1:4173'`，再运行 Node 命令。浏览器界面“运行与评测实验室”也可运行同一评测并导出原始 JSON。

固定语料与人工分级相关性位于 `public/data/evaluation.json`（原创 CC0，32 篇、16 条查询）。每配置三轮，保存全部查询排名、Recall@5、nDCG@5 与阶段计时；不筛选最快一次。配置依次比较 FP32/WASM batch1、FP32/WASM batch8、INT8/WASM batch1、INT8/WASM batch8、FP32/WebGPU batch8、FP16/WebGPU batch8。另比较逐条刷新与批写末尾刷新。硬件 WebGPU 与使用真实浏览器启动参数禁用 WebGPU 的降级路径分别验证。

`artifacts/benchmark.json`、`artifacts/fallback.json`、`artifacts/smoke.json` 是提交应用实际运行的证据。浏览器自动化拒绝任何非同源网络请求，原始网络审计随日志保存。这些文件仅作报告，应用从不读取日志回放向量或检索结果。实际数据与解释见 [一页技术说明](TECHNICAL.md)（[可打印 HTML](TECHNICAL.html)）和 [完整实验报告](EXPERIMENTS.md)。

计时边界：Worker 记录模型传输 ResourceTiming 与模型加载（包含解码/会话初始化）、文档/查询推理；API 记录 upsert、刷新和 SDK 检索；端到端从提交查询到结果插入 DOM 后两次 animation frame。首次加载与预热后的查询分别保留。模型体积包含当前精度的单个 ONNX 文件及同一组 tokenizer/config，不包含共同运行时或浏览器缓存。
