# 实验报告

记录时间：2026-11-03T07:14:39.056Z。本报告由提交应用的真实浏览器运行记录生成，未在服务端运行 embedding。q8 为混合 8 位图：INT8 矩阵权重、UINT8 词嵌入及 FP32 scale/LayerNorm；FP16 浮点权重类型为 FLOAT16，位置索引保留 INT64。initializer 类型审计见 artifacts/onnx-weight-audit.json。

## 条件与方法

- 设备：Intel(R) Core(TM) Ultra 5 225H / 16535973888 bytes RAM，Windows 10.0.26200，Edge 156.0.4314.58。WASM 使用 4 threads；页面启用 COOP/COEP。WebGPU adapter 信息保存在各 run.backend.adapter（Intel xe-lpg，非模拟输入）。
- 数据库：seekdb 1.4.0，Linux i9-14900K，32 logical CPUs，应用与数据库同机，4 GiB 数据库配置；浏览器经本地 SSH 转发访问。源代码、依赖锁和 artifacts/build-fingerprint.txt 固定被测实现。Docker 与嵌入式 SDK 不是本轮性能环境。
- 数据：public/data/evaluation.json，32 篇原创英文短文，16 条人工标注查询；每篇短于模型输入上限。语料很小，仅用于可复现实验，不代表大规模或中文检索性能。
- 每配置三轮独立集合，向量来自当轮浏览器推理；每条查询重新编码，再请求数据库混合检索。另请求同库纯向量结果用于质量对照，不在客户端合并结果。nDCG@5 采用 gain=2^relevance-1；Recall@5 分母为该查询全部标注相关文档数。质量值对全部 48 条查询求均值。
- 吞吐取三次完整语料编码吞吐的中位数。检索与端到端取 48 次查询中位数。端到端从提交开始，包含查询向量化、API/SSH、服务端状态读取、检索、DOM 插入与两次 animation frame；不包含随后用于评测对照的纯向量请求。DB ms 是 hybridSearch SDK 调用区间，不是整个 HTTP 请求。
- 第一轮文档编码可能包括 shader/kernel 预热，单独列出；仍保留在三轮原始数据中，没有剔除或只选最快一次。

## 体积与性能

| 配置 | 模型 MiB | 文档/秒 | DB ms | 端到端 ms | 混合 nDCG@5 |
|---|---:|---:|---:|---:|---:|
| FP32 · WASM · batch 1 | 86.88 | 41.0 | 2.27 | 57.6 | 0.805 |
| FP32 · WASM · batch 8 | 86.88 | 56.6 | 2.26 | 59.7 | 0.805 |
| INT8 · WASM · batch 1 | 22.59 | 53.5 | 2.36 | 70.3 | 0.818 |
| INT8 · WASM · batch 8 | 22.59 | 136.7 | 2.17 | 50.6 | 0.836 |
| FP32 · WebGPU · batch 8 | 86.88 | 201.2 | 2.06 | 70.6 | 0.805 |
| FP16 · WebGPU · batch 8 | 43.88 | 127.6 | 2.51 | 95.2 | 0.805 |

| 配置 | 模型加载 ms（单样本） | 首次文档编码 ms | 文档编码中位数 ms | 写入 ms | 刷新 ms | 查询编码 ms |
|---|---:|---:|---:|---:|---:|---:|
| FP32 · WASM · batch 1 | 39609.3 | 1037.6 | 780.1 | 73.7 | 510.2 | 13.7 |
| FP32 · WASM · batch 8 | 395.1 | 557.6 | 565.4 | 69.8 | 505.9 | 13.1 |
| INT8 · WASM · batch 1 | 8368.3 | 598.1 | 598.1 | 67.6 | 605.4 | 9.6 |
| INT8 · WASM · batch 8 | 112.4 | 236.4 | 234.1 | 71.0 | 605.5 | 8.3 |
| FP32 · WebGPU · batch 8 | 309.9 | 633.8 | 159.0 | 62.6 | 604.6 | 26.7 |
| FP16 · WebGPU · batch 8 | 16714.1 | 1065.5 | 250.9 | 70.6 | 505.3 | 27.2 |

## 首次加载与缓存

| 配置 | 模型网络传输字节 | 模型传输窗口 ms | 加载总时长 ms |
|---|---:|---:|---:|
| FP32 · WASM · batch 1 | 91101483 | 30324.7 | 39609.3 |
| FP32 · WASM · batch 8 | 0 | 0.0 | 395.1 |
| INT8 · WASM · batch 1 | 22972670 | 7980.1 | 8368.3 |
| INT8 · WASM · batch 8 | 0 | 0.0 | 112.4 |
| FP32 · WebGPU · batch 8 | 0 | 0.0 | 309.9 |
| FP16 · WebGPU · batch 8 | 45298125 | 16001.2 | 16714.1 |

加载总时长包含文件获取、解析和会话建立；传输窗口与加载总时长存在重叠，不能相减作为严格的纯初始化耗时。此表的加载是每配置一个样本，不是三次加载中位数。评测使用全新浏览器上下文：FP32/WASM batch1 为首次 FP32 获取，batch8 为缓存后重建会话；INT8 同理。FP32/WebGPU 复用前面已缓存的 FP32 文件，FP16/WebGPU 首次获取 FP16 权重，所以这些加载值不能简单用来宣称 GPU 加载更快。公共 tokenizer/config 可以复用；WASM 运行时传输保存在 resources，但不计入“模型传输字节”。

## 检索质量

| 配置 | 向量 Recall@5 | 向量 nDCG@5 | 混合 Recall@5 | 混合 nDCG@5 |
|---|---:|---:|---:|---:|
| FP32 · WASM · batch 1 | 0.7760 | 0.8266 | 0.7031 | 0.8049 |
| FP32 · WASM · batch 8 | 0.7760 | 0.8266 | 0.7031 | 0.8049 |
| INT8 · WASM · batch 1 | 0.7760 | 0.8562 | 0.7031 | 0.8185 |
| INT8 · WASM · batch 8 | 0.7760 | 0.8507 | 0.7031 | 0.8359 |
| FP32 · WebGPU · batch 8 | 0.7760 | 0.8266 | 0.7031 | 0.8049 |
| FP16 · WebGPU · batch 8 | 0.7760 | 0.8266 | 0.7031 | 0.8049 |

同后端、同 batch8 的量化比较：INT8 与 FP32 的混合 nDCG 差 0.0310；FP16 与 FP32 GPU 差 0.0000。未观察到明显量化质量损失，不等于统计显著性结论。该语料上混合排序的相关文档覆盖率低于纯向量；RRF 不是自动优于语义检索的保证，保留这个实际结果。

## 刷新策略独立对照

同一 INT8/WASM 浏览器生成的 32 条向量，分别用于两个写入策略；编码不计入此项比较。每策略三轮新集合，逐条策略准确调用 32 次刷新，批处理策略调用一次；两者最终都发布 ready revision。

| 策略 | 写入中位数 ms | 累计刷新中位数 ms | 导入服务端总时长中位数 ms |
|---|---:|---:|---:|
| 逐条写入并刷新 | 111.9 | 20874.1 | 20990.7 |
| 64 条批写，末尾刷新 | 69.1 | 604.9 | 676.6 |

整体导入总时长比为 31.02×，该值包含应用的写入、count 和状态维护，不声称全是数据库内核提速。

## 功能、降级与网络审计

五项单元/回归测试与真实 Edge 完整流程通过。浏览器 smoke 覆盖实际 TXT 文件上传、本地推理、增量可见性、重复导入去重、集合隔离、查询中切换集合忽略旧响应及选择恢复。独立 Edge 进程使用 --disable-blink-features=WebGPU、--disable-gpu、--disable-software-rasterizer，使实际 adapter 不可用；自动选择 WASM q8，完成写入刷新与检索。详见 fallback.json。原始 networkAudit 的外部请求为 0，页面异常为 0；自动化只允许同源请求。ORT 输出的形状算子 CPU 分配警告不是云端执行，也不意味着 GPU 路径失效。

## 原始文件

- artifacts/benchmark.json：所有轮次、查询 ID 排名、阶段耗时、资源传输和参数。
- artifacts/fallback.json、smoke.json：真实降级与流程证据。
- artifacts/model-manifest.json：实际模型文件大小与哈希。
- artifacts/server-environment.txt、runtime-versions.json、build-fingerprint.txt：环境与实现指纹。

应用不读取这些日志，它们不用于预计算回放。按 README 的命令运行可重新测量；网络、功耗模式与后台负载都会影响结果。