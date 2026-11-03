# 星屿：阶跃星辰赛题技术说明

**实现与环境。** 浏览器 Worker 运行 Transformers.js 3.8.1 / ONNX Runtime Web，Node + seekdb-js 1.4.0 只存储和检索。实测设备 Intel(R) Core(TM) Ultra 5 225H、15.4 GiB 内存、Windows 10.0.26200、Edge 156.0.4314.58；真实 Intel xe-lpg WebGPU。数据库在实验室 i9-14900K Linux 服务器运行 seekdb 1.4.0，4 GiB 配额，经 SSH 隧道访问。

**模型与量化。** Xenova/all-MiniLM-L6-v2，Apache-2.0，固定 revision `751bff37182d3f1213fa05d7196b954e230abad9`。采用上游已发布 FP32、FP16、INT8 ONNX 产物；下载脚本校验权重 SHA-256。384 维、mean pooling、L2 归一化。模型体积含相应 ONNX 与相同 tokenizer/config，排除共同运行时：FP32 86.88 MiB，FP16 43.88 MiB（1.98×），INT8 22.59 MiB（3.85×）。

**实测中位数。** 固定 32 篇原创语料、16 条人工分级查询，每配置 3 轮；每轮均重新编码所有文档与查询。文档吞吐取 3 轮中位数，查询延迟取 48 次中位数。

| 配置 | 模型 MiB | 文档/秒 | DB ms | 端到端 ms | 混合 nDCG@5 |
|---|---:|---:|---:|---:|---:|
| FP32 · WASM · batch 1 | 86.88 | 41.0 | 2.27 | 57.6 | 0.805 |
| FP32 · WASM · batch 8 | 86.88 | 56.6 | 2.26 | 59.7 | 0.805 |
| INT8 · WASM · batch 1 | 22.59 | 53.5 | 2.36 | 70.3 | 0.818 |
| INT8 · WASM · batch 8 | 22.59 | 136.7 | 2.17 | 50.6 | 0.836 |
| FP32 · WebGPU · batch 8 | 86.88 | 201.2 | 2.06 | 70.6 | 0.805 |
| FP16 · WebGPU · batch 8 | 43.88 | 127.6 | 2.51 | 95.2 | 0.805 |

**质量与优化。** 同后端、batch8 对比：FP16/GPU 的混合 nDCG 与 FP32/GPU 差 0.0000；INT8/WASM 比 FP32/WASM 差 0.0310，Recall@5 均为 0.703。FP32/WASM batch8 对 batch1 吞吐 1.38×；INT8 同条件为 2.56×。32 次逐条刷新与 1 次批末刷新对照，导入总耗时 20990.7 → 676.6 ms。FP16/GPU 的文档吞吐低于 FP32/GPU；GPU 对单查询并非更快；本小型合成集混合排序也未优于纯向量，不能外推通用质量。

**后端、状态与复现。** 默认显式选择 WebGPU FP16，失败自动降至 WASM INT8；真实禁用 WebGPU 的 Edge 进程已完成导入及检索，界面显示 WASM。所有浏览器网络请求同源，无云推理。每库独立集合，content-derived ID upsert 去重，revision/索引 revision 存于 seekdb；每批最多 64 条，完成后显式刷新，失败状态禁止检索。集合切换忽略旧响应，选择跨刷新恢复。SDK hybridSearch 把全文与向量交给数据库 RRF（60/50），没有客户端合并。

**证据。** 首载、传输窗口、首推理和预热请求分别记录；首载样本不作为重复加载中位数。端到端包括 API/隧道和 DOM 展示，DB 栏仅为 SDK 检索调用。README 提供启动与复现步骤，artifacts/benchmark.json、fallback.json、smoke.json 保存原始数据；EXPERIMENTS.md 给出完整边界和限制。