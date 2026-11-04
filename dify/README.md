# 夜班便利店：老板记得你

一个使用 Dify Chatflow 和 PowerContext 的跨会话互动故事。玩家在雨夜便利店与老板阿墨聊天，借走红伞或归还红伞。阿墨在新会话中仍能提起玩家过去的选择。作品入口是 Dify 自带的聊天页面，无需单独前端。

## 分工与运行链路

1. Dify 的开始节点接收固定的 `player_id` 和玩家消息，代码节点安全编码 JSON。
2. HTTP Request 节点调用本目录的游戏网关。网关根据玩家编号取得稳定的 PowerContext Scope，记录明确的借伞或归还事件，再读取与红伞有关的历史上下文。
3. Dify 的 LLM 节点使用本轮行为与召回的历史生成阿墨的台词，Answer 节点返回剧情和选择。

PowerContext 是跨会话记忆的实际存储与召回来源。Dify 的会话历史只用于当前会话的语言连贯性。网关仅做身份空间映射、输入校验和 PowerContext API 适配；它不生成 NPC 台词。

## 文件

| 文件 | 用途 |
| --- | --- |
| `dsl/night_shop.yml` | 唯一需要导入的 Dify Chatflow DSL |
| `backend/game_gateway.py` | 标准库实现的 HTTP 网关 |
| `examples/verify.py` | 不需要模型的记忆写入、跨会话召回、玩家隔离验证 |
| `examples/sample.md` | 在 Dify 界面中重现主要玩法的步骤与预期表现 |
| `.env.example` | 配置项示例，不含凭据 |

## 环境与依赖

- Linux，Python 3.11+，Git，`uv`。
- Dify 自行部署版或云端版，支持导入 `version: 0.1.2` 的 Chatflow YAML、Code、HTTP Request 和 LLM 节点。建议固定使用一个已验证的 Dify 版本，并在实际提交证据中记录版本。当前交付未包含 Dify 服务安装包。
- PowerContext 使用与本仓库适配的版本；本作品调用 `/v1/scopes`、`/v1/memory/remember`、`/v1/context/prepare`。部署时记录所用 PowerContext commit。默认本地 SQLite 配置即可体验，无需 Embedding 或 Rerank 服务。
- 一个在 Dify 中可用的聊天模型。DSL 中预设 `langgenius/openai/openai` 与 `gpt-4o-mini`；可在导入后改为评审环境中可用的聊天模型。模型凭据不会随 DSL 交付。

## 安装与启动

在可信的 Linux 环境中安装并启动 PowerContext。将下面的 `<POWERCONTEXT_COMMIT>` 替换成实际使用的、与 API 兼容的 commit；服务保持运行。

```bash
uv tool install --force "powercontext[cli,server] @ git+https://github.com/oceanbase/powercontext.git@<POWERCONTEXT_COMMIT>"
powercontext server run
curl --fail http://127.0.0.1:8000/health/live
```

在另一个终端启动网关。示例凭据只用于说明配置方式；请使用随机值，不要提交真实值。

```bash
cd dify
export POWERCONTEXT_URL=http://127.0.0.1:8000
export GAME_GATEWAY_TOKEN='<replace-with-random-secret>'
export GAME_BIND=0.0.0.0
export GAME_PORT=8765
python3 backend/game_gateway.py
```

PowerContext 启用鉴权时，额外设置 `POWERCONTEXT_TOKEN`。网关启动后用 `curl http://127.0.0.1:8765/health` 检查。若 Dify 部署在容器或另一主机，必须让 Dify 的 HTTP Request 节点能够访问网关；`127.0.0.1` 在 Dify 容器内指向容器自身。可把网关加入相同的容器网络并使用 `http://game-gateway:8765`，或配置该节点可到达的内网地址。网关应只暴露在可信网络。

在 Dify Studio 选择“导入 DSL”，导入 `dsl/night_shop.yml`。导入后设置：

1. 工作流环境变量 `GAME_GATEWAY_URL`：Dify 节点可访问的网关地址，不带末尾斜杠。
2. Secret 环境变量 `GAME_GATEWAY_TOKEN`：与网关环境变量一致。
3. LLM 节点选择当前工作区可用的聊天模型并配置凭据。
4. 运行一次预览，检查 HTTP 节点返回 200、`memory_status` 为 `ready` 或 `empty`；然后发布 Chatflow，并打开 Dify 自带聊天页面。

DSL 不包含外部服务、模型凭据和任何玩家记忆。这里不需要自定义插件、知识库或额外初始数据。导入顺序只有一个文件，首次运行时网关自动创建玩家 Scope。

## 验证

先用新玩家编号执行不依赖模型的集成验证：

```bash
GAME_GATEWAY_URL=http://127.0.0.1:8765 GAME_GATEWAY_TOKEN='<same-secret>' python3 examples/verify.py
```

脚本会输出每步的 `memory_status`、事件和召回情况，并在断言失败时退出非零状态。随后按 [`examples/sample.md`](examples/sample.md) 在 Dify 界面完成交互，保存 Dify 节点执行记录和 PowerContext 记忆读写结果。验证时使用全新的玩家编号即可恢复初始状态，不需要清空其他玩家的数据。

网关的标准库测试可直接运行：`python3 -m unittest discover -s backend -p 'test_*.py'`。该测试使用内存中的 PowerContext API 替身，检查 HTTP 鉴权、事件写入调用、跨会话召回和玩家隔离；正式验收还需运行上面的真实服务集成脚本，并在 Dify 中导入 DSL 体验。

## 已知边界

本作品使用固定规则识别“借红伞”“归还红伞”两类需要长期保存的行为。其他自由输入仍由阿墨回答，但不会写成长期事实。演示版的玩家编号由玩家自己填写，适合比赛复现；面向真实用户部署时，应由可信登录层分配编号并隔离玩家身份。相同借伞消息重复发送会产生重复事件，样例不依赖重复提交。PowerContext 调用失败时，网关返回错误，Dify HTTP 节点停止本轮，避免生成虚假的记忆承诺。

## 题解要点

题目要求的是可体验的 Dify 应用，以及 seekdb 或 PowerContext 的真实作用。这里把“新会话记得旧选择”设为核心玩法和技术验证点：玩家首次借伞时，网关调用 PowerContext 显式记忆接口；玩家在新 Dify 会话中只说“老板，我又来了”，网关从相同 Scope 读取历史，Dify LLM 才能提起红伞。玩家编号不同则使用不同 Scope，避免互相串戏。提交材料同时包含 DSL、网关源码、配置方式和可重复的样例，评审不依赖作者预先创建的数据。
