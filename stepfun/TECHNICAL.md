# 端侧资料库：一页技术说明

**实现与复现。** 项目位于官方生态分支的 `stepfun/`，浏览器 Web Worker 完成文档及查询 embedding；Node 仅校验、存取数据。依赖安装、离线资产准备、本地 seekdb 启动和测试见 [README](README.md)，实测原始数据见 [验证包](evidence/verified-20261103/README.md)。无需云端推理 API。当前完成本地验收，官方审核及成绩尚待提测。

**模型与量化。** 使用公开 Apache-2.0 模型 [Xenova/all-MiniLM-L6-v2](https://huggingface.co/Xenova/all-MiniLM-L6-v2/tree/751bff37182d3f1213fa05d7196b954e230abad9)，固定 revision `751bff37182d3f1213fa05d7196b954e230abad9`，384 维、mean pooling、L2、max_length=256。采用发布者已转换的 `model_fp16.onnx` 和 `model_quantized.onnx`（INT8），并非自行训练或声称重新量化；下载脚本、文件大小及完整性校验固定在 manifest。按“一个权重文件 + 相同 5 个配置/词表文件（944,310 B）”统计：FP32 **91,331,916 B**，FP16 **46,242,135 B，1.975×**，INT8 **23,916,680 B，3.819×**。模型以英文为主，未宣称中文质量。

**端侧后端。** Transformers.js 4.3.2 + ONNX Runtime Web 1.31.0-dev.20260914-8d85527a0（asyncify 浏览器分发）。显式申请 high-performance WebGPU，支持 shader-f16 时选 FP16；无适配器、无 FP16 或 GPU 初始化/执行失败时自动选 INT8/WASM，界面显示后端及原因。真实 NVIDIA 适配器通过完整流程；独立浏览器进程禁用 WebGPU、requestAdapter 返回空时，也完成本地向量化及数据库检索。推理资产由本地同源服务提供，远程模型禁用；基准阻断外部 HTTP，保留请求审计。

**数据层与状态。** seekdb-js（npm `seekdb@1.4.0`）server 模式，VECTOR(384)、cosine/HNSW、BENG 全文索引，`embeddingFunction:null`。调用 SDK 原生 `hybridSearch`，由 seekdb `DBMS_HYBRID_SEARCH`/RRF 排序；应用不融合两路结果。原文、向量、文件身份、内容哈希及版本均持久化。相同内容跳过；更新先暂存不可见版本并刷新，用单个原子 UPDATE 发布，再刷新；持久化待刷新标记支持失败恢复。两路都过滤 live=1。SDK 完整操作串行，避免连接级会话变量串用；浏览器知识库 ID/epoch 排除迟到响应。

**固定条件与结果。** 2026-11-03，Windows、Ryzen 7 5800H（8 核/16 线程）、约 13.86 GiB RAM、RTX 3050 Laptop / NVIDIA Ampere，Chrome for Testing **156.0.8078.80**；原生 seekdb 1.4.0（Ubuntu VM，CPU 2、内存 1G、数据文件 512M–1G），SSH 转发后使用同一数据库连接。固定 24 篇自编英文语料、12 个分级相关性查询；文档向量化重复 3 次、查询 12×3 次，下面均报告中位数。质量各配置均 **Recall@5=0.95833、nDCG@5=0.96626**，较 FP32 下降为 0；预设容许绝对下降 0.05。小型控制集不代表通用能力。

| 配置 | batch | 文档/s | 查询向量化 ms | seekdb 操作 ms | 端到端 ms |
|---|---:|---:|---:|---:|---:|
| FP32 / WASM 基线 | 1 | 20.09 | 14.86 | 7.24 | 29.44 |
| INT8 / WASM | 1 | 37.08 | 9.42 | 5.89 | 22.24 |
| INT8 / WASM | 4 | 37.28 | 9.15 | 5.93 | 21.92 |
| FP16 / WebGPU | 4 | 186.27 | 11.19 | 5.75 | 23.76 |
| 自动降级 INT8 / WASM | 4 | 37.20 | 9.61 | 5.99 | 22.90 |

**优化与计时边界。** Worker 与模型实例复用，支持批处理；该语料上 WASM batch=4 没有明显收益，GPU 更适合文档批量导入，不声称单查询必然更快。集合句柄有界复用，仍逐请求检查数据库状态：最终同源代码仅关闭句柄复用的 FP32/WASM/batch1 对照，端到端 **92.46→29.44 ms**，质量不变。DB 列为服务端 SDK hybridSearch 调用计时（含数据库两路检索与排序），不含此前登记/状态读取，也不是单条 SQL 执行时间；端到端为提交至结果 DOM 更新，非屏幕刷新时刻。每配置保留首次加载、资产事件/本地 HTTP 字节与时长、首次文档和查询、预热样本、一次完整写入/刷新数据；本地资产传输不代表公网下载。完整多轮原始结果保留，GPU 吞吐曾在约 186–297 文档/s 波动，表格使用最后一轮，未挑最快值。额外通过 12 项真实浏览器状态检查、真实文件上传、应用与数据库重启持久化、故障注入恢复、非法输入和 HTTP 边界检查。
