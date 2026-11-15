---
name: qoder-conversation-manager
description: 管理本机 Qoder 的会话与工作区：列出与筛选会话、按完整对话历史重命名、把会话迁移到指定工作区、新建/改名/改路径/归档/删除工作区、整库备份与回滚、七项体检。当用户说「重命名 Qoder 会话、给对话改标题、整理会话名称、移动对话、换工作区、改归属、把对话放到某个工作区、新建空间/工作区、改工作区路径、删除工作区、列出 Qoder 会话、Qoder 体检」时使用。只操作 Qoder 桌面端的本地数据（Windows）。
description_zh: 管理 Qoder 桌面端本地会话与工作区：按完整对话历史重命名、迁移归属、新建与维护工作区、备份回滚、七项体检。默认干跑，按对象备份，拒绝影子会话。
description_en: Manage Qoder desktop sessions and workspaces — rename from full transcripts, move between workspaces, create/retarget/delete workspaces, backup & rollback, and a 7-point doctor. Dry-run by default with automatic backups.
display_name: Qoder会话管理
display_name_zh: Qoder会话管理
display_name_en: Qoder Conversation Manager
version: 1.2.2
tags: [Qoder, 会话管理, 重命名, 工作区, SQLite]
license: MIT
---

# Qoder 会话管理

Manage local Qoder sessions and workspaces: list/filter, rename from full transcript,
move to a workspace, create/rename/retarget/archive/delete workspaces, backup/rollback, doctor.

## 这个技能做什么

| 命令 | 用途 | 是否写库 |
|---|---|---|
| `doctor` | 七项体检：库、WAL、表结构、进程、工作区路径、影子会话、备份 | 否 |
| `list` | 列出会话，支持六维筛选 | 否 |
| `rename --export` | 导出完整对话历史，供 agent 生成标题 | 否 |
| `rename --import` | 把 titles.json 写回，并锁定标题来源 | 是 |
| `move` | 迁移会话：改归属 + 搬会话文件、项目记忆、产出（`--metadata-only` 只改库） | 是 |
| `repair` | 补齐历史「只改库没搬文件」的会话：按当前 cwd 把文件/记忆/产出归位 | 文件 |
| `workspace` | list / new / rename / retarget / archive / unarchive / delete | 部分 |
| `backup` / `rollback` | 整库快照与恢复 | 是 |

**不做什么**：不删会话（只做工作区级联软删除）、不改对话正文、不操作另一台设备的影子会话。

## 核心事实（改库前必须知道）

- 数据库：`%APPDATA%\com.qoder.app.stable\main.sqlite`（自动探测；另有 `Qoder`、`qoder`、`com.qoder.app.insider` 等候选）。
- 会话表 `chat_sessions`：`title` 是侧栏标题；`workspace_id` 决定归属；`cwd` 必须等于工作区根路径。
- 标题来源：`extra_json.titleSource` + `titleResolved`。Qoder 原生只用「首条用户消息 + 首条助手回复」起名，留下的 `provisional` / `fallback` 标题会很难看。写入时本技能统一置 `custom` + `resolved=true` + `titleRevision+1`，防止被重新生成覆盖。
- 执行目标：`execution_target_json.workspace` 需同时改 `id` 与 `path`。本地工作区的 `id` 是 `ws_<64位哈希>`，**无法由路径复现**；技能会优先复用目标工作区已有会话的值，新工作区才退回工作区 UUID。
- 影子会话：`extra_json.peerOriginSessionId` 非空，或 `execution_target_json.mode == "peer"` 的会话，正文在另一台设备，本机只有元数据。**一律拒绝改名与迁移**（改了也会被同步覆盖）。
- 项目目录：`~/.qoder/projects/<cwd 编码>/`，内含 `<sid>.jsonl`、同名子目录（附件/子代理）与 `memory/`。编码规则是把 cwd 里的非字母数字换成 `-`，且**按创建时的 cwd 生成、不随改库更新**。
- 记忆分两层：`projects/<cwd 编码>/memory/` 是**项目级**（MEMORY.md + `project-*` / `feedback-*` / `reference-*`）；`~/.qoder/memory/` 是**全局**（跨项目偏好），迁移时不动全局。
- 产出：`turn_file_change_files` join `turn_file_change_sets`（按 `session_id`），`path` 是相对 `roots_json[primary].path` 的路径。
- 会话查找按 sid 扫描 `projects/*`，所以只改库不会丢历史；但**项目记忆挂在 cwd 编码下**，不搬就会读不到。
- 工作区来源：`workspaces.workspace_source` 为 `local` 或以 `peer:` 开头。只有 `local` 能作为操作对象与迁移目标。
- 同一台机器上可能存在**同名工作区**（本地一份 + 对端投影若干）。技能解析名称时优先取唯一的本地工作区。

## 安装

把整个目录放进宿主 agent 的用户级技能目录即可。目录约定由宿主决定，例如：

```
~/.qoder/skills/qoder-conversation-manager/
~/.codex/skills/qoder-conversation-manager/
```

各宿主对 SKILL.md 的解析规则一致，同一份目录可直接复用；具体路径以宿主自己的设置页为准。详见 `references/install.md`。

验证：

```bash
python <skill-dir>/scripts/qoder_sessions.py doctor
```

七项全 `OK` 说明可用。`Qoder 进程` 只是提示项——运行中也允许热写。

## 命令总览

所有命令都支持 `--db <path>`（指向副本做演练）、`--json`（结构化输出）。

写操作默认**允许 Qoder 运行中热写**：写完提示重启应用，让侧栏按数据库重建。需要硬性拦截时加 `--require-closed`（退出码 3）。

### doctor

```bash
python <skill>/scripts/qoder_sessions.py doctor
python <skill>/scripts/qoder_sessions.py doctor --json
```

退出码：0 全绿；1 有告警项。

### list

```bash
python <skill>/scripts/qoder_sessions.py list --workspace NAS
python <skill>/scripts/qoder_sessions.py list --keyword 路由器 --include-peer
python <skill>/scripts/qoder_sessions.py list --filter "cwd contains NAS and title contains 工具包"
python <skill>/scripts/qoder_sessions.py list --since 2026-11-01 --limit 20
```

筛选维度：`--workspace`（名/路径/UUID）、`--cwd`、`--keyword`、`--filter`、`--since`、`--include-deleted` / `--include-peer`、`--limit`。

`--filter` 是受限表达式，只支持 `and` 连接与 `contains / like / startswith / endswith / = / !=`，字段限 `title / cwd / workspace / id / status`。**不是 SQL**，不要写子查询。

### rename（两步式）

第一步，导出完整历史：

```bash
python <skill>/scripts/qoder_sessions.py rename --export --out ./qoder-extract
# 可限定范围
python <skill>/scripts/qoder_sessions.py rename --export --filter "status = active" --out ./exp
```

导出目录里每个会话一个 `.txt`（含 SESSION_ID、现有标题、标题来源、工作区、cwd、消息数、用户轮数、完整对话），外加 `index.json`。

大批量时加 `--shards N`，会按字数用 LPT 均衡切片，生成 `shards/group1.json … groupN.json`，每组一份清单直接派给子智能体：

```bash
python <skill>/scripts/qoder_sessions.py rename --export --shards 6 --out ./exp
```

第二步，agent 读这些 txt 生成 `titles.json`：

```json
[
  {"sid": "e3d0af7b-8f30-40a9-a5aa-08b000dc0b3d", "new_title": "把会话迁移技能传到笔记本", "category": "开发"},
  {"sid": "2dd673fa", "new_title": "排除代理误判定位 RDP 链路丢包", "category": "网络"}
]
```

`sid` 可写完整 UUID 或前 8 位。`category` 可选：写了会**自动补成 `[分类] 标题`**（标题已带前缀则不重复加）。然后写回：

```bash
python <skill>/scripts/qoder_sessions.py rename --import titles.json                          # 干跑
python <skill>/scripts/qoder_sessions.py rename --import titles.json --apply                  # 落盘
python <skill>/scripts/qoder_sessions.py rename --import titles.json --apply \
  --min-title-len 12 --max-title-len 30 --require-prefix                                      # 带长度与前缀约束
```

校验规则：非空、长度落在 `--min-title-len` / `--max-title-len`（默认 2–40）、不含引号/书名号/句号/问号/控制字符/路径分隔符；`--require-prefix` 时校验 `^\[[^\[\]]{1,8}\]\s+\S`。**允许不同会话重名**，不去重。

**分类约定**：短类 2–4 个汉字，全库收敛在 8–12 个（如 系统/网络/开发/数据/硬件/办公/生活/其他）。前缀计入长度。

**标题怎么写**：必须读完整对话再定名，不要只看开头。判断真实主线——用户最初想做什么 → 中途遇到什么 → 最后实际交付什么；中途转向时以占篇幅最大或最终解决的那条命名。长度 8–22 个汉字，技术名词保留原文并与中文之间加半角空格。详见 `references/subagent-playbook.md`。

### move

```bash
# 单条
python <skill>/scripts/qoder_sessions.py move --to NAS --ids e3d0af7b
# 批量按条件（先干跑看清单）
python <skill>/scripts/qoder_sessions.py move --to VMs --filter "title contains 工具包"
# 确认后落盘
python <skill>/scripts/qoder_sessions.py move --to VMs --filter "title contains 工具包" --apply
```

`--to` 接受工作区名称、根路径或 UUID。**默认是全量迁移**，一条会话会同时处理四件事：

1. 数据库：`workspace_id`、`cwd`、`execution_target_json.workspace.{id,path}` 一起改；
2. 会话文件：`projects/<旧cwd编码>/<sid>.jsonl` 与 `<sid>/` 子目录 → `projects/<新cwd编码>/`；
3. 项目记忆：旧项目的 `memory/` → 目标项目，`MEMORY.md` 逐行去重追加，同名不同内容另存为带时间戳文件；
4. 产出：`turn_file_change_files` 记过的文件按相对路径搬到新工作区根，**旧路径留硬链接**（跨盘失败则复制），历史里的旧链接仍能打开。

只要元数据时加 `--metadata-only`，此时只改数据库，文件一律不动。

搬空的源项目目录默认自动删除（`--keep-orphans` 可保留），避免 `projects/` 下堆一堆没有会话的空目录。

已在目标工作区的会话自动跳过；`--ids` 里匹配不到的 ID 会告警。每条会话独立事务，文件搬运失败会把已搬的文件放回原位；记忆合并不可逆，回滚时只提示需人工核对。

落盘时**每条会话一个独立事务**：某条失败只标记 `[FAIL]`，其余继续。写完逐条回读三处字段并打 `[OK]` / `[WARN]`，最后输出成功/失败计数与备份组路径。

### repair

修历史欠账：早先用旧版本（或 `--metadata-only`）迁过的会话，数据库归属改了，但 `projects/<cwd编码>/` 下的正文、子目录、项目记忆还留在旧目录。`repair` 只搬文件、不改数据库：

```bash
python <skill>/scripts/qoder_sessions.py repair                 # 干跑：列出待修清单
python <skill>/scripts/qoder_sessions.py repair --ids e3d0af7b  # 只修指定会话
python <skill>/scripts/qoder_sessions.py repair --apply         # 落盘
```

记忆策略（默认按源目录判断）：

- 源目录只剩这一条会话 → 视为独享，把它的 `memory/` 合并进目标项目；
- 源目录还有别的会话 → 该记忆属于留下的项目，**不搬**，避免把共用记忆复制到别的项目；
- `--memory-mode always` 强制总是合并（慎用，会产生重复记忆）。

判断依据是「处理前的目录会话数」，不是逐条实时计算，所以同一目录的多条会话不会因为处理顺序不同而结果不一致。

搬完后源项目目录若已没有任何会话，会被**自动删除**（连带其中的记忆残留）；要保留加 `--keep-orphans`。删除清单写进 `batch.json` 的 `removed_dirs`。

### workspace

```bash
python <skill>/scripts/qoder_sessions.py workspace list
python <skill>/scripts/qoder_sessions.py workspace new --name VMs --path D:/VMs            # 干跑
python <skill>/scripts/qoder_sessions.py workspace new --name VMs --path D:/VMs --apply
python <skill>/scripts/qoder_sessions.py workspace rename --name VMs --new-name 虚拟机 --apply
python <skill>/scripts/qoder_sessions.py workspace retarget --name VMs --path D:/VM2 --apply   # 级联改会话 cwd
python <skill>/scripts/qoder_sessions.py workspace archive --name VMs --apply
python <skill>/scripts/qoder_sessions.py workspace delete --name VMs --yes --apply             # 级联软删除
```

- `new`：只查**本地**同名工作区；同名已存在则列出并停止，不新建（后续用 `move --to` 归入即可）。目录是否存在只做提示，**由 agent 判断要不要建目录**，脚本不自动创建；目录缺失时需 `--allow-missing` 才继续。
- `retarget`：改根路径并**强制级联**更新该工作区所有会话的 `cwd` 与执行目标（影子会话跳过）。
- `delete`：软删除工作区 + 其下全部会话（写 `deleted_at`，进 Qoder 回收站，可恢复）。必须 `--yes`。

### backup / rollback

两级备份，回滚粒度不同：

```bash
# 按对象清单（rename / move 自动生成）
python <skill>/scripts/qoder_sessions.py rollback --manifest "<备份组>/items/chat_sessions-<sid>.json" --yes --apply
python <skill>/scripts/qoder_sessions.py rollback --batch "<备份组>/batch.json" --yes --apply

# 整库快照（手动，或破坏性操作前）
python <skill>/scripts/qoder_sessions.py backup --list
python <skill>/scripts/qoder_sessions.py backup
python <skill>/scripts/qoder_sessions.py rollback --backup ./qoder-cm-backups/db/<快照> --yes --apply
```

- `rename` / `move` 每次落盘会在**当前工作目录**新建一组 `qoder-cm-backups/<动作>-<时间戳>/`：`items/` 下每条会话一份完整行，`batch.json` 汇总。**单条回滚只动那一行**，不影响同批其他会话。
- `backup` / `workspace delete` / `workspace retarget` / `rollback --backup` 用整库快照，存在 `./qoder-cm-backups/db/`，保留最近 10 份。
- `rollback --backup` 会先把当前库另存为 `bak-pre-rollback-*` 再覆盖。
- 备份根目录可用 `--backup-dir` 或环境变量 `QODER_CM_BACKUP_DIR` 改到别处；根目录自带 `.gitignore`（内容为 `*`），不会被 git 提交。

## 典型工作流

**批量重命名全部会话**

```bash
python <skill>/scripts/qoder_sessions.py doctor
python <skill>/scripts/qoder_sessions.py rename --export --out ./exp
# agent（或子智能体团队）读 ./exp/*.txt，产出 titles.json
python <skill>/scripts/qoder_sessions.py rename --import titles.json          # 先看清单
python <skill>/scripts/qoder_sessions.py rename --import titles.json --apply
```

**按主题给会话归类到工作区**

```bash
python <skill>/scripts/qoder_sessions.py list --include-peer=false
python <skill>/scripts/qoder_sessions.py move --to Cross-Platform --filter "cwd contains NAS"
# 看清单无误后加 --apply
```

**新建一个工作区并接收会话**

```bash
python <skill>/scripts/qoder_sessions.py workspace new --name VMs --path D:/VMs
# 若提示目录不存在，先与用户确认是否建目录，再决定 --allow-missing
python <skill>/scripts/qoder_sessions.py workspace new --name VMs --path D:/VMs --apply
python <skill>/scripts/qoder_sessions.py move --to VMs --filter "title contains 工具包" --apply
```

## 安全规则

1. **默认 dry-run**：所有写命令不加 `--apply` 只打印计划，不落盘。
2. **允许热写**：Qoder 运行中也能写（WAL 保证一致性），写完必须重启应用做一次重建验证；要硬性拦截用 `--require-closed`。
3. **按对象备份**：每条被改动的会话在 `./qoder-cm-backups/<动作>-<时间戳>/items/` 下存一份完整行，`batch.json` 汇总，支持单条或整批回滚。备份与临时产物都放在**当前工作目录**，不写入数据库目录。
4. **每条独立事务**：批量操作某条失败只影响它自己，其余继续；结束后按成功/失败计数返回退出码。
5. **破坏性操作仍做整库快照**（`./qoder-cm-backups/db/`，保留最近 10 份）：`workspace delete`、`workspace retarget`、`rollback --backup`。
6. **影子会话一律拒绝**改名与迁移，并在输出里说明原因。这是 Qoder 特有的数据形态——`peerOriginSessionId` 非空的会话正文在另一台设备，本机只有元数据，改了会被同步覆盖。
7. **只操作本地工作区**；对端投影既不能作为迁移目标，也不能被改名/删除。
8. **搬文件前先备份**：会话文件、子目录、记忆、产出在移动前都会复制到备份组的 `files/<sid>/` 下。
9. **产出旧路径留链接**：优先硬链接，跨盘失败退回复制；两者都失败时只在清单里记 `link:false`，不中断迁移。
8. **删除只做软删除**（进回收站），且必须 `--yes`。
9. **只改元数据**，不碰 `chat_session_messages` 正文与搜索索引。
10. **副本演练**：给 `--db` 指向副本时，与真库互不影响，可放心跑全套写操作。

退出码：`0` 全部成功；`1` 有失败或 doctor 有告警；`2` 参数/选择/目标错误或缺少确认；`3` 指定了 `--require-closed` 且 Qoder 在运行。

## 常见错误

| 现象 | 原因 | 处理 |
|---|---|---|
| 写完标题没变 | 应用还在用旧缓存 | 重启 Qoder；仍不变则查 `titleSource` 是否为 `custom` |
| `目标工作区名不唯一` | 存在同名本地/对端工作区 | 用 `workspace list` 查 UUID，`--to <UUID>` |
| 迁完侧栏没变 | 应用未重启 | 重启 Qoder |
| 迁移后新项目读不到旧记忆 | 只用了 `--metadata-only`，记忆没搬 | 去掉该参数重跑，或手工合并 `projects/*/memory/` |
| 产出旧路径打不开 | 硬链接与复制都失败（如跨盘且无权限） | 看清单里的 `link` 字段，手工补链接或复制 |
| `--qoder-home` 指错 | 沙箱演练时未指向副本 | 确认指向含 `projects/` 的根目录 |
| 迁完发现目录还在旧位置 | 早先只改了数据库 | 跑 `repair`（先干跑看清单） |
| `repair` 说「共用目录，未搬」 | 源项目还有其他会话 | 正常；该记忆属于原项目，需要时手工合并 |
| 改完标题又变回去 | 只改了 `title`，没锁 `titleSource` | 用本技能 `rename --import`（会自动锁定） |
| `未找到 Qoder 数据库` | 非默认安装位置 | `--db` 指定 `main.sqlite` |
| 迁移后执行目录不对 | `execution_target_json` 未同步 | 本技能会三处同改；手工改库容易漏 |
| 想改的会话被判定为影子 | 该会话属于另一台设备 | 到那台设备上执行，或在 Qoder 里确认归属 |

## 资源

- `references/qoder-storage.md`：表结构、关键字段、写入约定、验证 SQL、已知坑。
- `references/subagent-playbook.md`：大批量重命名的子智能体分工模板。
- `references/cases.md`：真实案例（27 条重命名、按主题归类工作区）。
- `references/install.md`：三端安装与验证。
- `CHANGELOG.md`：版本记录。
