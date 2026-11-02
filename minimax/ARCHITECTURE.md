# 一页技术说明

```text
manifest + specs + code + tests
              |
        校验来源并整体导入
              v
seekdb: sdd_documents + FULLTEXT(body)
              |
  project_id + active 状态 + 任务全文查询
              v
任务上下文 <---- PowerContext Memory 任务状态
    |             | 保存精确引用、进度和验证指纹
    |             + 独立进程重启读取，变化则要求重新验证
    v
MiniMax 官方 HTTP 接口
    |
仅允许 taskboard.py 修改，保留模型输入/输出和代码差异
    v
固定目标测试 + 兼容测试 ----> PowerContext 新验证记录
```

工程资料由 seekdb 保存，实际查询结果提供路径、正文、检索分数和哈希。历史决策以 superseded 状态保留，检索只取 active 项；完整快照导入删除已从清单移除的来源。提交前校验所有文件，防止无效导入破坏旧快照。

PowerContext Memory 负责持久化任务进展与测试结果。任务指针只保存 scope 和 citation；恢复时通过 SDK 读取真正的 Memory 记录。项目/任务身份分别隔离。代码、规格、测试或清单的生效状态变动后，旧验证记录仍作为历史证据保留，但标记为不适用于当前工程。

MiniMax 接收前述完整上下文，负责实际代码修改。程序不让模型改测试；同一组目标测试修改前应因归档逻辑错误失败，修改后应全部通过，兼容测试应始终通过。真实调用证据与本地边界模拟分别记录；六项全部满足才生成可提测状态。
