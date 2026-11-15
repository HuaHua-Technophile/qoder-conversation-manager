# Qoder 存储结构与写入约定

本机电实测（Qoder 0.5.11 / Windows）。字段以实际库为准，升级后可能变化，用 `doctor` 校验。

## 数据库位置

| 系统 | 路径 |
|---|---|
| Windows | `%APPDATA%\com.qoder.app.stable\main.sqlite`，另有 `%APPDATA%\Qoder`、`%APPDATA%\qoder`、`%APPDATA%\com.qoder.app.insider`、`%LOCALAPPDATA%\Qoder` 等候选 |
| 同目录其他库 | `chat-session-turn-payload-buffer.sqlite`（未落盘的轮次缓冲，非标题权威源）、`sessionMigration.sqlite`、`remote-control.sqlite` |

`main.sqlite` 默认 WAL 模式，干净退出后 `-wal` 会被 checkpoint。写入前 `doctor` 会报告 WAL 状态。

## chat_sessions（核心表）

| 列 | 说明 |
|---|---|
| `session_id` | UUID 主键 |
| `title` | 侧栏显示标题 |
| `cwd` | 任务语义上的工作目录。挂到工作区后**必须等于该工作区根路径** |
| `workspace_id` | 归属工作区；`NULL` 表示游离任务。侧栏按此列分组（有索引 `chat_sessions_workspace_updated`） |
| `extra_json` | 元数据。标题相关：`titleSource`(`provisional`/`fallback`/`ai`/`custom`)、`titleResolved`、`titleRevision`、`provisionalTitle` |
| `execution_target_json` | 执行目标：`{mode, host, workspace:{id,path}}`。`mode` 为 `local` 或 `peer` |
| `created_at` / `updated_at` | 毫秒时间戳 |
| `archived` / `deleted_at` / `archived_at` | 归档与回收站；`deleted_at` 非空即已进回收站 |
| `session_kind` | `standard` / `sideChat` / `automationExecution` |

## workspaces

| 列 | 说明 |
|---|---|
| `workspace_id` | UUID 主键 |
| `name` | 显示名称，**可能重复**（本地一份 + 每台对端设备各一份） |
| `workspace_source` | `local` 或以 `peer:<deviceId>:<workspaceId>` 开头 |
| `root_paths_json` | 根路径数组，通常只有一个元素 |
| `product_mode` | `coding` / `general` |
| `extra_json` | 图标、颜色、索引开关等 |
| `archived` / `deleted_at` | 归档与软删除 |

## chat_session_messages（正文）

`session_id + message_id` 主键，`payload_json` 是 JSON：

```
{"parts":[{"type":"text","text":"..."},
          {"type":"tool_call","toolCall":{"name":"Bash"}}, ...]}
```

取文本：遍历 `parts`，`type=="text"` 拼 `text`，`type=="tool_call"` 只记工具名（用于统计次数，不展开参数）。`role` 为 `user` / `assistant` / `system`，`system` 多为 hook 事件，重命名时应忽略。

## 其他相关表

- `chat_session_search_fts` / `chat_session_search_segments`：FTS5 只索引**消息正文**，不含标题。改标题**不需要**重建索引。
- `chat_session_sidebar_placements`：侧栏位置（`work_directory` / `sort_order` / `pinned`），与工作区归属无关，迁移时不用动。
- `chat_session_history_revisions`：由触发器维护，改消息时自动更新，改标题不受影响。

## 写入约定

### 改标题

```sql
UPDATE chat_sessions
   SET title = ?,
       extra_json = ?   -- titleResolved=true, titleSource='custom', titleRevision+1
 WHERE session_id = ?;
```

必须同时改 `extra_json`，否则 Qoder 下次仍可能按首条消息重新生成并把标题覆盖掉。这是实测过的坑。

### 迁工作区

三处必须同时改，缺一不可：

```sql
UPDATE chat_sessions
   SET workspace_id = ?,
       cwd = ?,
       execution_target_json = ?   -- workspace:{id, path}
 WHERE session_id = ?;
```

`execution_target_json.workspace.id` 的取值规则：

1. 目标工作区若已有任务，读取它们的 `workspace.id`，取出现次数最多的那个（同一本地工作区的值稳定）。
2. 目标工作区是新建的、还没有任何任务时，退回使用工作区 UUID。

原因：本地工作区的 `workspace.id` 形如 `ws_<64 位十六进制>`，由 Qoder 原生层生成。实测 md5 / sha1 / sha256 / sha3_256 / blake2b / blake2s、UTF-8 与 UTF-16LE 编码、大小写/斜杠/尾斜杠/`\\?\` 前缀/JSON 转义等各种归一化组合，**都无法由路径或工作区 UUID 复现该值**，Electron 层（app.asar）中也没有生成代码。因此只能复用或退让，不要臆造。

### 新建工作区

```sql
INSERT INTO workspaces(workspace_id, name, workspace_source, root_paths_json,
                       product_mode, extra_json, created_at, updated_at, archived, deleted_at)
VALUES(?, ?, 'local', '["D:\\VMs"]', 'coding',
       '{"workspaceIcon":"folder","workspaceColor":"primary","workspaceIndexEnabled":true}',
       <ms>, <ms>, 0, NULL);
```

`root_paths_json` 必须是 JSON 数组字符串（Windows 反斜杠要转义）。目录是否已存在只影响体验，不影响记录有效性。

### 删除工作区（软删）

```sql
UPDATE chat_sessions SET deleted_at=?, archived=1, archived_at=? WHERE workspace_id=? AND deleted_at IS NULL;
UPDATE workspaces   SET deleted_at=?, archived=1, updated_at=? WHERE workspace_id=?;
```

## 验证 SQL

```sql
-- 三处是否一致
SELECT session_id, workspace_id, cwd,
       json_extract(execution_target_json,'$.workspace.id')   AS et_id,
       json_extract(execution_target_json,'$.workspace.path') AS et_path
  FROM chat_sessions WHERE session_id LIKE 'xxxx%';

-- 标题锁定是否生效
SELECT title, json_extract(extra_json,'$.titleSource') AS src,
       json_extract(extra_json,'$.titleResolved') AS resolved
  FROM chat_sessions WHERE session_id LIKE 'xxxx%';

-- 工作区任务统计
SELECT w.name, w.workspace_source, w.root_paths_json,
       (SELECT count(*) FROM chat_sessions c
         WHERE c.workspace_id=w.workspace_id AND c.deleted_at IS NULL) AS n
  FROM workspaces w WHERE w.workspace_source='local';

-- 完整性
PRAGMA integrity_check;
```

## 已知坑

1. **同名工作区**：`NAS`、`VMs`、`Cross-Platform` 这类名字常有多份（本地 + 各对端）。按名称操作时必须优先本地，否则会误操作投影。
2. **影子任务**：`peerOriginSessionId` 非空的任务，正文不在本机，改了标题或归属会被对端同步覆盖，且它的 `cwd` 可能指向本机不存在的盘符。
3. **cwd 与根路径不一致**：历史手工改动容易只改 `workspace_id`，导致侧栏归了组但执行目录还是旧的。本技能三处同改。
4. **`additional_direcotries`**（原文拼写如此）通常是 `{}`，迁移时无需改动。
5. **应用运行中写库**：WAL 允许并发写，但 Qoder 可能用内存缓存回写，导致改动被覆盖。所以写操作要求应用退出。
6. **同一秒两次备份**：备份文件名含到秒的时间戳，同秒内连续两次写会互相覆盖。批量操作时留意先后顺序，或手工 `backup` 一次作为锚点。
7. **Python 路径**：Git Bash 的 `/tmp` 在原生 Python 里不成立，脚本参数一律用 `C:\...` 绝对路径。

## 热写与验证（v1.1.0）

Qoder 用 WAL 模式，允许在应用运行时写入。技能默认不再拦截，只打 `[WARN]`：

1. 写库（每条任务独立事务，失败隔离）。
2. 立即回读三处字段（`workspace_id` / `cwd` / `execution_target_json.workspace.path`）或（`title` / `extra_json.titleSource`）校验。
3. 提示用户重启 Qoder，让侧栏按数据库重建。

实测：应用运行中写入后**没有被内存缓存覆盖**——重启后标题与归属都保持。但仍建议重启后核对一次；若回退，用对应备份组回滚。

需要旧行为（运行中直接拒绝）时加 `--require-closed`，退出码 3。

## 备份布局（v1.1.0）

```
<当前工作目录>/qoder-cm-backups/
└── move-20261115-135526/
    ├── batch.json                 # 本批汇总：每个 item 的 sid/status/manifest
    └── items/
        └── chat_sessions-<sid>.json   # 该任务改动前的完整行（所有列）
```

`items/*.json` 结构：

```json
{"version":1,"table":"chat_sessions","key_column":"session_id",
 "key_value":"<sid>","saved_at":1794...,"row":{ ...所有列... }}
```

回滚时按 `row` 逐列写回（只写当前表里存在的列），因此**只影响这一行**。

整库快照存在 `<当前工作目录>/qoder-cm-backups/db/main.sqlite.bak-<动作>-<时间戳>`，用于 `workspace delete` / `retarget` / 手动 `backup`，保留最近 10 份。

`rollback` 三种形态：

| 参数 | 作用 |
|---|---|
| `--manifest <items/xxx.json>` | 只恢复一条任务 |
| `--batch <batch.json>` | 恢复该批全部条目 |
| `--backup ./qoder-cm-backups/db/<快照>` | 整库覆盖（先另存 pre-rollback） |


## 项目目录、记忆与产出（v1.2.0）

```
~/.qoder/
├── projects/
│   └── <cwd 编码>/
│       ├── <sid>.jsonl        # 任务正文
│       ├── <sid>/             # 附件、子代理、工具结果
│       └── memory/            # 项目级记忆
│           ├── MEMORY.md
│           └── project-*.md / feedback-*.md / reference-*.md
├── memory/                    # 全局记忆（跨项目偏好），迁移时不动
└── memories/db/memory.db      # 结构化长期记忆（chat_session.memory_refs）
```

**cwd 编码**：把 cwd 里的非 `[A-Za-z0-9._-]` 字符替换成 `-`。
例：`D:\HuaHua\Documents\Qoder\2026-11-15\11679d46` → `D--HuaHua-Documents-Qoder-2026-11-15-11679d46`。

**关键事实**：目录名在任务创建时生成，**改 `cwd` 不会自动更新**。应用按 sid 扫描 `projects/*`，所以不搬文件也不会丢历史；但项目记忆挂在旧编码目录下，迁走后新项目读不到。

**产出索引**：

```sql
SELECT f.path, f.operation, s.roots_json
  FROM turn_file_change_files f
  JOIN turn_file_change_sets s ON f.change_set_id = s.change_set_id
 WHERE s.session_id = ?;
```

`roots_json` 形如 `[{"id":"primary","path":"E:\\B\\NAS","kind":"primary"}]`，`path` 相对该根。覆盖率不高（仅记录进过评审/检查点的 turn），所以产出迁移是「尽力而为」：没索引到的文件不会搬，报告里也不列。

**迁移策略**：

| 对象 | 处理 | 失败时 |
|---|---|---|
| 任务 jsonl / 子目录 | 移动到新编码目录 | 该条标记失败，已搬部分回滚 |
| 项目记忆 | 合并（MEMORY.md 去重追加） | 冲突另存带时间戳文件 |
| 产出 | 移动 + 旧路径硬链接 | 跨盘退回复制；再失败只记 `link:false` |
