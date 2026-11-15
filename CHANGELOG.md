# CHANGELOG

## 1.0.0 — 2026-11-15

首个版本。把「重命名会话 / 迁移会话 / 管理工作区」三件事打包成一个跨 Harness 技能，操作对象为 Qoder 本地数据。

### 新增命令

- `doctor`：七项体检（数据库可读、WAL 状态、表结构、Qoder 进程、工作区路径可达、影子会话占比、备份情况）。
- `list`：六维筛选（`--workspace` / `--cwd` / `--keyword` / `--filter` / `--since` / `--include-deleted` / `--include-peer` / `--limit`）。
- `rename --export` / `rename --import`：两步式重命名。导出完整对话历史供 agent 起名，导入时做基础校验并锁定标题来源。
- `move`：把会话迁入工作区，三处字段（`workspace_id` / `cwd` / `execution_target_json`）同步更新；支持 `--filter` 批量。
- `workspace list|new|rename|retarget|archive|unarchive|delete`。
- `backup` / `rollback`：整库快照、自动保留最近 10 份、回滚前先另存当前库。

### 设计决策

- 默认 dry-run，所有写完必须显式 `--apply`。
- 写入前要求 Qoder 已退出，运行时拒绝（退出码 3）；`--force` 可绕过。
- 每次落盘前自动备份，命名 `main.sqlite.bak-<动作>-<时间戳>`。
- 影子会话（`peerOriginSessionId` 非空或 `mode=peer`）一律拒绝改名与迁移。
- 工作区解析优先本地，避免同名对端投影干扰。
- `execution_target_json.workspace.id` 优先复用目标工作区已有值，新建工作区退回 UUID（该值算法不可复现，详见 `references/qoder-storage.md`）。
- `workspace delete` 只做软删除（`deleted_at`），级联其下会话，需 `--yes`。
- 输出默认人读表格，`--json` 给结构化结果。

### 已知限制

- 仅支持 Windows（路径探测按 Windows 实现）。
- 不改对话正文，不重建 FTS 索引（标题不在索引内，无需重建）。
- 不支持操作另一台设备的 Qoder 数据。
- 元信息校验为「尽力兼容」：Qoder 升级导致表结构变化时，缺失列会被跳过而非报错。

### 实测

数据库副本上完成闭环：rename → 断言标题与锁定标记 → rollback 恢复；move → 断言 `cwd` 与执行目标 → rollback 恢复；同名工作区拒绝新建；缺 `--yes` 的删除被拦截（退出码 2）。

真实库上完成 27 条会话重命名与 13 条会话跨工作区迁移，`PRAGMA integrity_check` 均为 `ok`。
