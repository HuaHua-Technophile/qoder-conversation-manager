# CHANGELOG

## 1.2.2 — 2026-11-15

搬空的源项目目录自动清理，不再留空壳。

- `move` / `repair` 结束后，源项目目录若已无任何 `*.jsonl`，直接删除（含残留记忆）；`--keep-orphans` 可保留。
- 删除清单写入 `batch.json` 的 `removed_dirs`，便于追溯。
- 本机实战：清理 17 个历史残留目录，`projects/` 从 25 个目录收敛到 8 个有会话的目录。

## 1.2.1 — 2026-11-15

补两个能力，用于修正历史「只改库没搬文件」的迁移。

- 新增 `repair`：按当前 `cwd` 把正文、子目录、项目记忆、产出归位，只搬文件不动数据库。
  记忆按源目录判断：独享目录才合并，共用目录保留在原项目，避免复制污染。
- 新增 `doctor --deep`：加查「每条会话是否有正文文件」「项目目录与 `cwd` 是否一致」「项目记忆分布」「产出索引覆盖」。
- 本机实战：17 条历史会话完成归位，目录一致性从 17 条不一致降为 0。

## 1.2.0 — 2026-11-15

`move` 从「只改归属」升级为**全量迁移**：会话文件、项目记忆、产出一起搬。

- 会话文件：`projects/<旧cwd编码>/<sid>.jsonl` 与 `<sid>/` 子目录搬到新 cwd 编码的目录。
- 项目记忆：`projects/<cwd编码>/memory/` 合并到目标项目；`MEMORY.md` 逐行去重追加，同名不同内容另存带时间戳文件。
- 产出：按 `turn_file_change_files` 的相对路径搬到新工作区根，旧路径留硬链接（跨盘退回复制）。
- 新增 `--metadata-only`：只改数据库，不碰文件。
- 新增 `--qoder-home`：指向沙箱副本演练，默认 `~/.qoder`。
- 回滚扩展到文件：`rollback --manifest/--batch` 会把已搬的文件放回原位；记忆合并不可逆，回滚时提示人工核对。
- 搬文件前先备份到备份组的 `files/<sid>/`。

## 1.1.2 — 2026-11-15

备份与临时产物改放**当前工作目录**，不再写进 Qoder 数据目录。

- 备份根目录：`./qoder-cm-backups/`（`db/` 放整库快照，`<动作>-<时间戳>/` 放按对象清单），可用 `--backup-dir` 或 `QODER_CM_BACKUP_DIR` 覆盖。
- 根目录自动写 `.gitignore`（内容 `*`），避免整库快照被提交。
- `rename --export` 默认目录改为 `./qoder-extract`。
- 不保留旧位置（数据库旁 `main.sqlite.bak-*`）的兼容读取；旧文件已清理。
- `doctor` 的备份项改为纯提示（新工作目录天然没有备份），不再计入异常。

## 1.1.1 — 2026-11-15

文档与包装订正：技能只描述自己操作 Qoder 桌面端数据，不再用「不操作某个其他产品」来界定范围，也不再指定某个宿主目录为默认安装位置；上架包改为按格式命名（`-root` / `-dir`）。

## 1.1.0 — 2026-11-15

补齐六项工程能力：按对象备份、事务隔离、热写、均衡分片、标题分类、允许重名。

### 变更

- **按对象备份 + 单条回滚（对齐 1）**：`rename` / `move` 每次落盘新建 `qoder-cm-backups/<动作>-<时间戳>/`，`items/` 下每条会话一份完整行，`batch.json` 汇总。新增 `rollback --manifest`（只回滚一条）与 `rollback --batch`（回滚整批）。整库快照仍用于破坏性操作。
- **每条独立事务 + 失败隔离（对齐 2）**：批量写不再整批一个事务；单条失败只标记 `[FAIL]` 并继续，结束后返回成功/失败计数（有失败时退出码 1）。
- **允许热写（对齐 3）**：Qoder 运行中不再直接拒绝写入，改为 `[WARN]` 提示并继续；写完提示重启应用做重建验证。需要旧行为时加 `--require-closed`（退出码 3）。`doctor` 的进程检查改为提示项，不再计为异常。
- **LPT 均衡分片（对齐 7）**：`rename --export --shards N` 按字数用最长优先算法切片，输出 `shards/groupN.json`，供子智能体并行；`index.json` 增加 `chars` 字段。
- **分类维度（对齐 8）**：`titles.json` 支持 `category` 字段，自动补成 `[分类] 标题`；新增 `--require-prefix`、`--min-title-len`、`--max-title-len`。
- **允许重名（对齐 9）**：移除重复标题告警，不同会话可同名。

### 其它

- `--ids` 中匹配不到的 ID 会输出 `[WARN]`，不再静默忽略。
- `--force` 参数移除，由 `--require-closed` 取代。
- 文档订正：影子会话拒绝是 **Qoder 数据形态特有**的必要防护（对端会话正文不在本机），不作为与其他技能的优劣比较项。

## 1.0.0 — 2026-11-15

首个版本。把「重命名会话 / 迁移会话 / 管理工作区」三件事打包成一个技能，操作对象为 Qoder 桌面端本地数据。

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
- 每次落盘前自动备份（当时存放在数据库同目录，v1.1.2 起改到工作目录）。
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
