# 2026-11-03 本地验证包

本包是应用实际运行记录，不是官方评分。完整复现命令见项目 README。`scripts/browser-benchmark.py` 使用真实浏览器、真实模型与 seekdb，保存逐次原始数据，禁止外部 HTTP；重新运行默认写入被忽略的 `evidence/raw/`，不覆盖本包。

- `final/`：最后一轮 Chrome 156 的五组配置、3 次文档向量化、每组 36 次预热查询、首次事件、模型大小及压缩比、网络审计与 GPU/WASM 截图。`benchmark-state.json` 为汇总和结果文件 SHA256。DB 耗时为服务端 SDK hybridSearch 调用，不含此前登记/状态读取，端到端含 DOM 更新。
- `before-handle-cache/`、`after-handle-cache/`：此前完整实验记录。较早的前后版本还有计时仪表差异，因此单项优化结论使用下面最终源码的开关对照，不仅依赖早期两版本比较。GPU 吞吐随运行状态变化，未择最快一轮报告。
- `same-source-cache-off.json`：最终源码仅用 `SEEKDB_CACHE_HANDLES=0` 关闭句柄复用；同一设备、模型、数据、FP32/WASM/batch1，36 次查询。`database.cacheHandles=false`。对照 `final/baseline-fp32-wasm.json` 的 true，端到端中位数 92.455→29.4375 ms。此为串行实测，仍可能受运行状态影响，不保证所有硬件同幅提升。
- `browser-acceptance.json`：12 项真实浏览器验收，覆盖重复导入、缩短替换、连续导入、知识库切换、并发隔离、非法向量/协议/文件输入及安全展示。
- `database-integration-isolated.txt`：独立测试数据库中的故障注入、持久化待刷新恢复和真实表/索引检查。这里的合成向量只检验状态语义；质量数据使用浏览器模型向量。
- `real-upload.txt`：实际浏览器文件选择上传；`persistence-restart.json`、`persistence-restart-verified.txt`：Node 和原生 seekdb 均重启后，所选知识库、原文件、检索结果仍存在。
- `unit-tests.txt`、`http-integration.txt`：4 项核心测试与真实 HTTP 边界检查；`node-model-verification.txt` 为 Node 模型资产完整性检查。
- `hardware.json`、`tested-source-sha256.json`：设备/版本与测试源码文件哈希。公开模型/运行时哈希另见项目 manifest；大体积下载资产不纳入 Git。
- `mobile.png`：390px 宽浏览器实际截图，无水平溢出。桌面截图在 `final/`。

首次状态测试曾与共享数据库清理并行，导致测试夹具被另一连接删除；已将数据库集成测试改为私有 UUID 数据库并串行复验通过。最早基准的计时仪表随后增加了冷加载和资源字节记录；最终报告使用包含这些仪表的版本。安装机旧 Chrome 141 也通过过完整流程，但技术说明统一采用最后 Chrome 156 的实测。

数据范围：24 篇自编英文短文、12 个人工分级相关性查询。模型英文为主，质量指标只说明本控制集。模型加载、写入/刷新每配置记录一次实际事件；预热文档 3 次、查询 36 次。Asset 事件为本地同源 HTTP 下载与加载，不等同于公网模型下载速度。官方审核和最终分数须由参赛平台确认。
