# Qoder 赛题提交材料

| 字段 | 填写内容 |
| --- | --- |
| 项目名称 | 研途 Research Desk |
| 项目网站 | https://yantuo-research-desk-wp1a3l0vxnl.qoder.zone |
| Qoder UID | 01a1a00b-e8da-7d4c-bc2f-744a5a10cad8 |
| 队长提测仓库 | https://github.com/weekndjob/powercontext.git |
| 个人备份仓库 | https://github.com/2167762157/powercontext-competition-prep.git |
| 分支 | `competition/2026/qoder-research-desk` |
| 项目目录 | `qoder/` |
| Commit id | 填最终交付消息或材料包版本文件中的完整 40 位 SHA |

Branch 字段填写分支名，不填写 GitHub 网页 URL。正式平台提交由参赛者完成，平台审核及得分尚未产生。

## 材料对应关系

- 运行环境、安装启动、数据库部署与接入、复现输入和预期结果：[README.md](README.md)。
- 初始数据：`samples/sample_materials.json`，全部明确标注为人工构造样例；`import_samples.py` 支持重复运行。
- 可执行验收：`verify.py`，真实 HTTP 和 seekdb；本次最终结果为 63 项检查通过，见 `evidence/independent-acceptance.json`。包含 48,000 个中文及 emoji 字符、并发关联一致性和应用重启后读取。
- Qoder 开发记录：`evidence/qoder-development.json`，保留真实会话标识、开发事件与源日志校验值；原始完整本机会话仍保留以供核对。Qoder 负责主要实现，Codex 负责审查修复、独立验收与交付。
- 真实数据库作用：验收 JSON 内的版本、原生 IK 索引 DDL、检索与日期汇总响应。
- Qoder Sites 实际发布：`evidence/qoder-sites-publication.json`，公开访问状态与部署标识；匿名请求记录见 `evidence/public-access.json`。
- 截图：`site/images/`；浏览器操作与边界结果见 `evidence/browser-acceptance.json` 和相关 JSON。

项目网站通过 Qoder Sites 公开发布，提供说明、真实截图、源码和复现入口。本机应用按 README 部署运行；展示网站不从公网连接局域网数据库。没有提供虚构的用户使用规模、效率提升数据或正式得分。

提交时可上传随最终交付提供的项目 ZIP；其内容来自该提交已跟踪文件，不含密钥、虚拟环境、运行日志或临时发布输入。
