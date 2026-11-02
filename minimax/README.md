# MiniMax SDD 工程上下文模块

本作品对应「规有所依——面向软件持续演进的 SDD 上下文管理系统」。基于官方生态分支 `2026-competition-ecosystem`，资产均在 `minimax/`。工作分支为 `competition/2026/minimax-sdd-context`。

**当前状态：上下文、真实 seekdb 检索和 PowerContext 状态恢复已实现；尚未开通 MiniMax，真实模型修改及修改后测试待执行，尚未达到六项全部通过的提测条件。** 本文的运行流程支持开通后生成完整证据；不会用模拟响应代替真实 MiniMax 开发记录。

## 做题顺序与验收

1. 从完整清单导入规格、历史决策、代码与固定测试；使用 seekdb 全文索引选择任务资料，排除失效决策。
2. 运行同一组目标/兼容测试，保存真实命令、退出码及规格、代码、测试哈希。
3. 使用 PowerContext Memory 保存任务进展；在独立进程中重新打开运行时并读取原始引用，供后续上下文使用。
4. 更新规格并重新导入，确认新内容进入上下文，先前验证被标记为需要重新核实。
5. 将实际检索的规格、代码、测试和恢复状态发送给 MiniMax，接受仅限 `taskboard.py` 的修改，保存请求、脱敏响应、前后快照和 diff。
6. 保持测试内容不变，运行目标与回归测试；保存结果后再次重启、读取并使用状态。仅六项全部通过时，`readiness.json` 才输出 `ready_for_submission`。

## 依赖和配置

Python 3.11+，建议新建虚拟环境。已在 Python 3.14、PowerContext 1.2.0 和真实 seekdb 1.4.0 上验证本地模块。依赖版本见 `requirements.txt`。

```bash
cd minimax
python -m venv .venv
# Linux/macOS
source .venv/bin/activate
# Windows PowerShell 改用 .venv/Scripts/Activate.ps1
python -m pip install -r requirements.txt
```

准备可用的 seekdb 或 OceanBase MySQL 模式实例，创建专用数据库：

```sql
CREATE DATABASE minimax_sdd CHARACTER SET utf8mb4;
```

使用环境变量提供配置，以下是 Bash 示例，PowerShell 用 `$env:变量名='值'`：

```bash
export SEEKDB_HOST=127.0.0.1
export SEEKDB_PORT=2881
export SEEKDB_USER=root
export SEEKDB_PASSWORD='YOUR_DATABASE_PASSWORD'
export SEEKDB_DATABASE=minimax_sdd
export MINIMAX_API_KEY='YOUR_MINIMAX_API_KEY'
export MINIMAX_BASE_URL=https://api.minimax.io/v1
export MINIMAX_MODEL=MiniMax-M3.1-Flash
```

MiniMax 接入使用官方 OpenAI 兼容 HTTP 接口；国内官方地址可配置为 `https://api.minimaxi.com/v1`。实际模型名须是账号可用模型。若使用 Token Plan，须先确认账号提供该兼容接口；当前程序不实现 Anthropic 协议。密钥不写入开发记录。

数据库用户需具有专用库的建表、读写和全文索引权限。模块会创建 `sdd_documents` 表，不创建或删除用户数据库。不同演示运行使用独立 project_id；同一 project_id 的导入表示完整快照替换。

## 一次完整开发任务

```bash
python run_demo.py --output runs/minimax-live-001
```

输出目录必须尚不存在。程序从已交付的初始工程复制全新样例，不依赖此前的本地数据或状态。运行失败保留原始日志，修复问题后使用新目录重新运行，不覆盖历史证据。

没有 MiniMax 配置时，可先验证其余流程：

```bash
python run_demo.py --prepare-only --output runs/prepare-001
```

此命令明确输出 `awaiting_minimax`，`minimax_actual` 和 `code_modification_valid` 为 false，不能拿该记录作为完整提测通过证据。重置样例只需选择新的输出目录；原始 `sample/` 始终保留修改前代码。

## 验证样例与必要上下文

业务工程是随作品交付的原创小型 taskboard 查询模块，入口 `sample/taskboard.py::list_tasks`。目标是默认排除 archived 行，显式 `include_archived=True` 时允许包含，并始终保持 status 筛选交集。必须保持输入顺序、不修改原输入、空输入及已有可见行筛选行为。

必要来源如下，内容必须真实来自数据库查询：

| 来源 | 作用 |
| --- | --- |
| `specs/archive_policy.md` | 当前规格 R1-R3、兼容要求 C1-C2 |
| `taskboard.py` | 要修改的函数 |
| `tests/test_archive.py` | 固定目标测试 |
| `tests/test_compatibility.py` | 固定回归测试 |

`specs/archive_policy_legacy.md` 明确为失效决策，不可作为当前要求返回。完整演示还会更新当前规格并重新导入，检查 `archive-spec-updated` 内容出现在下一次上下文中。

修改前目标测试应为 **3 failed、2 passed**，兼容测试应为 **3 passed**。这是目标行为断言失败，环境错误不能充当修改前证据。修改后目标应为 **5 passed**、兼容 **3 passed**，且两个测试文件哈希必须前后一致。

## 调用入口

```bash
python -m sdd_context import --project sample --output runs/manual/import.json
python -m sdd_context context --project sample --query archive --state .state --output runs/manual/context.json
python -m sdd_context validate --project sample --output runs/manual/before.json
python -m sdd_context save --project sample --state .state --record runs/manual/before.json --output runs/manual/saved.json
python -m sdd_context resume --project sample --state .state --output runs/manual/resumed.json
```

`context` 输出任务查询、实际来源与检索分数、来源哈希、先前任务状态，以及已有验证是否仍适用。使用 `develop` 会真实调用 MiniMax 并修改传入工程的代码，建议通过 `run_demo.py` 的独立工程副本使用。

重新导入前，如果选中的本地来源与数据库哈希不一致，模块报错，要求重新导入。恢复状态时，会比较所有资料及清单的类型/生效状态指纹；变化后不会将旧验证当作当前验证。

## 测试

```bash
python -m pytest -q tests
SDD_REAL_DATABASE_TESTS=1 python -m pytest -q tests
```

第一条会跳过两个真实数据库测试；第二条必须连接真实 seekdb，覆盖来源筛选、规格更新、项目隔离和无效导入不破坏旧快照。PowerContext 状态测试使用真实 SDK 和持久化运行时，在独立 Python 进程间读写。`test_agent.py` 是明确的本地边界模拟，只验证越权写入被拒绝，不计为真实 MiniMax 使用。

## 提交材料和技术使用记录

完整真实运行目录应交付到 `evidence/live/`，其中包括：

- `versions.json`、`commands.jsonl`：版本和命令/退出码。
- `database.jsonl`：实际入库和全文查询记录，查询结果直接构成上下文。
- `initial-context.json`、`updated-context.json`：必要来源和重新导入后的新规格。
- `saved-before.json`、`resumed-before.json`、`saved-after.json`、`resumed-after.json`：PowerContext 引用、任务进展和独立进程 PID。
- `minimax/minimax-request.json`、`minimax-response.json`：实际请求上下文、模型名、响应 ID、用量及输出代码；不提交私有推理内容。
- `minimax/taskboard.before.py`、`taskboard.after.py`、`code.diff`：代码快照与差异。
- `before-tests/`、`after-tests/` 和相应 JSON：同一测试集的目标失败、修改后成功与兼容结果，以及对应代码/测试哈希。
- `readiness.json`：六项是否全部通过。

提交前检查记录中没有真实凭据。实际模型输出不同不影响复现，评审可使用已记录的代码修改和固定测试，无需重新生成相同补丁。

## 已知限制

当前演示是单写入进程，不保证并发修改同一任务指针。检索使用词法全文索引，不包含向量模型；多语言分词质量由数据库 space parser 决定。资料上限为单文件 16 KB、一次最多 20 条，超长或不完整的模型上下文不能作为当前样例的有效输入。

MiniMax 输出是可执行代码，应先审阅保存的 diff，在隔离样例中运行。生产环境部署需另行采用进程/容器沙箱。本作品不宣称实现完整 Agent 会话恢复。

开源组件来源：PowerContext、seekdb（OceanBase），PyMySQL、HTTPX、pytest；通过安装固定依赖复用，不复制其源码。业务样例与上下文模块为本作品新增代码。

官方参考：[题面](https://oceanbase.yuque.com/org-wiki-obtech-vh7w9r/hc3pio/qlqnoryzrs7gtqbw)、[MiniMax OpenAI 兼容接口](https://platform.minimax.io/docs/api-reference/text-openai-api)。
