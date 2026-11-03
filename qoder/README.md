# 研途 Research Desk

面向学习、科研和项目工作的个人资料台：把笔记和实验记录存入 **真实 seekdb**，通过全文检索找到资料与来源，再把后续工作转为待办并生成进度汇总。无需额外的 LLM API。

主要后端及界面由 **Qoder CN CLI 1.1.81** 实际开发，Codex 负责需求整理、代码审查、缺陷修复、独立验收与交付整理。实际开发记录见 [evidence/qoder-development.json](evidence/qoder-development.json)，不含私有推理和登录凭据。Qoder UID：`01a1a00b-e8da-7d4c-bc2f-744a5a10cad8`。

## 运行环境

- Python **3.12**；本次验证版本为 3.12.14。
- 可通过 MySQL 协议连接、支持 IK 全文索引的 seekdb。本次实际验证版本为 `5.7.25-OceanBase seekdb-v1.4.0.0`。
- 运行依赖精确版本见 `requirements.txt`；验收另需 `requirements-dev.txt` 中的 httpx。

## 从安装到运行

1. 准备 seekdb。可使用已有服务器，或按 [seekdb 官方部署说明](https://github.com/oceanbase/seekdb/blob/master/README_CN.md#快速开始)部署独立实例。Docker 示例：

```bash
docker run -d --name qoder-seekdb -p 127.0.0.1:2881:2881 -v qoder-seekdb-data:/var/lib/oceanbase oceanbase/seekdb:latest
```

镜像的实际版本随 `latest` 更新，请记录 `SELECT VERSION()`；本次验收使用上述明确版本的原生实例，未将未执行的 Docker 部署声称为验收结果。按所用实例配置用户名和密码。

2. 在仓库的 `qoder/` 目录安装应用：

```powershell
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements-dev.txt
$env:SEEKDB_HOST='127.0.0.1'
$env:SEEKDB_PORT='2881'
$env:SEEKDB_USER='root'
$env:SEEKDB_PASSWORD='' # 仅当该开发实例允许空密码；有密码时在本机填写
$env:SEEKDB_DATABASE='qoder_research_desk'
.venv/Scripts/python setup_database.py
.venv/Scripts/python import_samples.py
.venv/Scripts/python -m uvicorn app:app --host 127.0.0.1 --port 8000
```

Linux/macOS 将解释器路径替换为 `.venv/bin/python`，环境变量使用 `export SEEKDB_HOST=127.0.0.1` 等设置。`.env.example` 是配置示例，应用不会自动加载 `.env`。数据库账号需具备本项目库的读写、建表和索引权限；初始化新库还需建库权限。

浏览器打开 `http://127.0.0.1:8000`。API 文档位于 `/docs`，数据库健康检查为 `/api/health`。应用默认用于个人本机运行；本题的公开展示网站与本机应用分别部署。

## 复现主要功能

1. 样例导入成功后，打开“全文检索”，搜索 `科研`，标签输入 `科研`。应返回中文资料及其明确标注的样例来源；搜索 `retrieval` 可命中英文样例。
2. 搜索 `nonexistentwordzxqv`，应显示无匹配。空关键词返回资料列表。标签 `科` 不会匹配完整标签 `科研`。
3. 在“资料管理”表单保存资料，或上传 UTF-8 的 `.txt`/`.md`；文件上限 2 MB、正文上限 50,000 字符。错误编码、超限和无效格式会明确失败。
4. 在检索结果上创建待办，在待办页查看关联资料、标记完成或编辑。删除资料会在同一事务中清空任务关联。
5. 在“进度汇总”选择日期区间并复制报告。顶部总数与每日分组均按 **created_at 的日期（数据库会话时区）** 筛选；任务完成数表示该期间创建的任务的**当前完成状态**，不表示期间内完成的事件数。
6. 停止并重新启动应用，资料与任务仍从 seekdb 读取。样例均为人工构造验证资料，不对应正式论文或真实用户反馈。

## 检索与一致性

`materials` 的 `(title, content)` 建立 `WITH PARSER ik` 全文索引。查询使用参数化 `MATCH(title, content) AGAINST(%s IN NATURAL LANGUAGE MODE)`，按相关性、创建时间、ID 排序。分词由 IK 决定，不承诺任意子串命中，也不把相关性分数解释为概率。标签去空白、去重，以完整标签进行 AND 筛选。

SQL 值全部通过参数绑定。同步路由在线程池执行；每个数据库连接上下文提交或回滚后关闭。关联资料的创建、删除和重关联使用事务与行锁。更新中的 `material_id: null`、`due_date: null` 表示清空，省略表示保持；重复设置相同完成状态保留原完成时间，并仍允许修改其他字段。

页面通过文本节点与属性转义呈现用户内容，避免把标题拼入 JavaScript 事件属性。上传内容作为文本存储与展示，不执行 Markdown 中的 HTML 或脚本。

正文列使用 `MEDIUMTEXT`，支持声明的 50,000 字符上限（包括多字节中文和 emoji）。初始化会把本项目旧版的 `TEXT` 正文列升级为 `MEDIUMTEXT` 并保留数据；实际验收包含 48,000 个中文和 emoji 字符的写入与读回。

## 自动验收

关闭占用端口 18080 的其他程序，然后运行：

```powershell
.venv/Scripts/python verify.py
```

脚本会启动真实 HTTP 应用，连接配置中的真实 seekdb，检查中英文检索、标签、输入与文件边界、任务状态、并发关联一致性、日期汇总、应用重启后读取；仅清理它创建并记录 ID 的测试数据。使用本项目的专用测试数据库运行。成功输出 `status: passed`，任一断言或数据库不可用则非零退出。实际结果写入 `evidence/independent-acceptance.json`。

## 项目网站与提测

Qoder Sites 的公开网站、匿名访问证据、仓库与分支填写信息见 [SUBMISSION.md](SUBMISSION.md)。`site/` 是项目介绍、真实截图与复现入口；网站不会从公网访问本机数据库。网站由 Qoder Sites 实际发布，正式审核与得分以赛事平台为准。

源码结构：`app.py` 路由与业务，`database.py` 连接及建表，`models.py` 输入输出约束，`templates/` 界面，`samples/` 合成样例，`verify.py` 验收，`evidence/` 实际证据，`site/` 展示网站。

官方赛题：https://oceanbase.yuque.com/org-wiki-obtech-vh7w9r/hc3pio/uygu3273xzlrcmrm
