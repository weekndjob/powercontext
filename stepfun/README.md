# 端侧资料库：StepFun × seekdb

浏览器本地向量化、数据库原生混合检索的迷你知识库。源码基于官方 `2026-competition-ecosystem` 分支，全部项目资产位于 `stepfun/`。

[官方题面](https://oceanbase.yuque.com/org-wiki-obtech-vh7w9r/hc3pio/kw9wfx4bu9pyvat9) · [一页技术说明](TECHNICAL.md) · [第三方来源与许可](THIRD_PARTY.md)

## 做题顺序与实现

1. 固定开源模型、版本、量化文件及向量协议，在真实浏览器内生成文档和查询向量。
2. 优先选择 WebGPU/FP16；适配器或 FP16 不可用、GPU 初始化或执行失败时降级 INT8/WASM，并显示原因。
3. 使用 seekdb-js 建立 BENG 全文索引、384 维 cosine/HNSW 向量索引。`embeddingFunction:null` 禁止服务端自动向量化。
4. 先写入不可见的新文件版本、刷新索引，再用一个数据库原子 UPDATE 发布完整版本，最后刷新。混合检索的两路都过滤 `live=1`，旧分块不会混入结果。
5. 用固定语料和人工相关性标注比较 FP32、INT8、FP16 的质量和性能，再验证增量、切换、并发、故障恢复及重启。

```mermaid
flowchart LR
  A[浏览器文件导入 / 用户查询] --> B[Web Worker: 本地 embedding]
  B --> C[本地 Node 服务: 校验 + seekdb-js]
  C --> D[seekdb: 原文、元数据、向量]
  D --> E[DBMS_HYBRID_SEARCH / RRF]
  E --> F[浏览器展示排序结果与原文]
```

服务端没有 embedding 模型和云端推理依赖。模型及运行时文件预先下载后由本地服务提供；应用运行期间仅连接本地同源 HTTP 和配置的 seekdb。没有应用层两路检索拼接或重排，也没有预计算检索结果。

## 启动

需要 Node.js 24 LTS（最低 22.22.2）、npm、最新版 Chrome/Edge，以及可通过 MySQL 协议连接的 seekdb 1.4.x。本次实际使用 Chrome for Testing 156.0.8078.80 和 seekdb 1.4.0 原生服务。

### 1. 数据库

可以使用已有本地 seekdb；也可在 Linux/WSL 中安装官方 seekdb 后运行：

```bash
cd stepfun
SEEKDB_BINARY=/path/to/seekdb bash scripts/start-seekdb.sh
```

脚本前台运行独立数据目录 `.seekdb/`，默认端口 2881、CPU 2、memory_limit 1G、datafile 512M–1G、redo 2G。预留至少 4GB 可用磁盘。可通过 `SEEKDB_DATA_DIR`、`SEEKDB_PORT` 指定目录和端口；源码构建如需动态库，可设置 `SEEKDB_LIBRARY_PATH`。脚本不删除已有数据。停止时遵循 seekdb 的正常关闭方式。

### 2. 应用、浏览器运行时与模型

```bash
cd stepfun
npm ci --omit=optional --ignore-scripts
npm run build
npm run models
```

`build` 只获取浏览器分发文件，避免安装服务器推理引擎。`models` 获取同一固定版本的 FP32、FP16 和 INT8 文件。两步均校验大小及哈希；下载发生在准备阶段，不执行推理。模型合计约需 160MB，浏览器运行时另约 29MB，未将这些二进制提交到 Git。

复制 `.env.example` 为 `.env`，填入数据库连接参数。Linux/macOS 用 `cp .env.example .env`，PowerShell 用 `Copy-Item .env.example .env`。数据库与 Node 应用不在同一系统时，将连接地址或本地端口映射写入 `.env`，不要把数据库密码放到前端。

```bash
npm run db:init
npm start
```

打开 **http://localhost:18380**。创建知识库，导入 UTF-8 `.txt`/`.md` 文件，或载入示例；等待索引刷新完成后输入自然语言查询。已有知识库也可连续导入、切换和重新加载页面。

代理环境中，如 Node 下载受限，在启动下载命令前按本机网络设置 `HTTPS_PROXY`/`HTTP_PROXY`，Node 24 可使用 `NODE_USE_ENV_PROXY=1`。不要关闭证书校验。浏览器推理不依赖外网，运行时禁止远端模型回退。

## 数据与状态规则

- 模型协议固定为模型 ID、revision、mean pooling、L2 normalization、max_length=256、dimension=384；协议不匹配的请求返回 409。
- 文件先按 160 个词、20 词重叠切分并保留原文跨度；无空格长文本按 Unicode 字符切分。单文件最多 512KB，每批最多 64 个文件、128 个分块；单 HTTP JSON 请求最多 4MB。
- 同一知识库中文件名是来源身份。相同文件内容重复导入不重复写入；相同文件名的新内容替换旧版本，缩短文件也会隐藏旧尾部。
- `stepfun_kbs` 保存知识库身份、协议和待刷新状态。发布前失败只能留下不可见暂存行；发布后刷新失败会在下一次读取时恢复刷新。旧版行保留作历史，但不参与检索。
- 所有完整 SDK 操作串行化，避免 `hybridSearch()` 的连接级 `@search_parm` 在并发请求间串用。最多缓存 128 个集合句柄；每次请求仍读取数据库登记信息和刷新状态，不缓存向量或检索结果。`SEEKDB_CACHE_HANDLES=0` 可关闭句柄复用做对照。
- 浏览器用请求时捕获的知识库 ID 和递增 epoch 防止迟到结果显示到其他知识库。原文与文件名用 `textContent` 展示。
- 这是本地单用户应用，HTTP 仅监听 loopback，并校验 Host、Origin。不是多用户远程服务。

## 复现实测

```bash
npm test
npm run test:database
npm run test:http
npm run benchmark
```

数据库集成测试需要已运行的 seekdb，会创建并清理独立的 `stepfun_test_<uuid>` 测试库；不清理应用知识库。HTTP 测试需要已运行的应用。

浏览器基准还需要 Python 3.10+（仅标准库）与已安装 Chrome。可用 `CHROME_EXECUTABLE` 指向 Chrome/Chromium 可执行文件。基准自动启动专用浏览器进程，另起禁用 WebGPU 的进程验证真实降级；全部外部 HTTP 被阻断。原始结果保存在 `evidence/raw/`，不会覆盖已提交的验证包。完整 GPU 对照需有支持 WebGPU 和 shader-f16 的设备；普通使用可自动降级至 WASM。

基准使用 `public/dataset.json`：24 篇自行编写的英文知识片段、12 个人工分级相关性查询；每配置重复 3 次文档向量化及 36 次查询，保留各次数据并取中位数。质量指标为 Recall@5、nDCG@5，量化后容许的绝对下降门槛预设为 0.05。该小型控制集不代表通用检索能力；当前模型以英文为主，不宣称中文检索质量。

原始记录区分首次模型加载、文件获取事件、初始化、首次请求及预热后请求；文件网络时间是在同源本地 HTTP 分发条件下测得，不代表公网下载速度。写入与索引刷新是每配置一次完整导入的实际事件，查询和向量化则采用重复样本。端到端查询从提交至结果 DOM 更新，包含本地查询向量化、HTTP、SDK 和数据库操作，不仅是数据库 SQL 时间。

也可在应用浏览器控制台执行 `await (await import('/benchmark.js')).run('auto', 4, 'my-run')`，返回完整实测 JSON。`public/acceptance.js` 提供增量、版本替换、知识库切换、并发、非法请求和安全展示的真实浏览器验收。

## 提测

将本项目所在的规范分支和对应完整提交 SHA 填入队长报名仓库的提测表。Branch 填分支名，不填 GitHub 网页 URL。当前提交完成本地验收；平台审核和最终成绩以官方结果为准。
