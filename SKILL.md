---
name: qoder-conversation-manager
description: 管理本机 Qoder 的会话与工作区：列出与筛选会话、按完整对话历史重命名、把会话迁移到指定工作区、新建/改名/改路径/归档/删除工作区、整库备份与回滚、七项体检。当用户说「重命名 Qoder 会话、给对话改标题、整理会话名称、移动对话、换工作区、改归属、把对话放到某个工作区、新建空间/工作区、改工作区路径、删除工作区、列出 Qoder 会话、Qoder 体检」时使用。只操作 Qoder 本地数据（Windows），不操作 WorkBuddy 数据。
display_name: Qoder 会话管理
display_name_zh: Qoder 会话管理
display_name_en: Qoder Conversation Manager
version: 1.0.0
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
| `move` | 把会话迁到指定工作区（改归属、cwd、执行目标） | 是 |
| `workspace` | list / new / rename / retarget / archive / unarchive / delete | 部分 |
| `backup` / `rollback` | 整库快照与恢复 | 是 |

**不做什么**：不删会话（只做工作区级联软删除）、不改对话正文、不碰 WorkBuddy 数据、不操作另一台设备的影子会话。

## 核心事实（改库前必须知道）

- 数据库：`%APPDATA%\com.qoder.app.stable\main.sqlite`（自动探测；另有 `Qoder`、`qoder`、`com.qoder.app.insider` 等候选）。
- 会话表 `chat_sessions`：`title` 是侧栏标题；`workspace_id` 决定归属；`cwd` 必须等于工作区根路径。
- 标题来源：`extra_json.titleSource` + `titleResolved`。Qoder 原生只用「首条用户消息 + 首条助手回复」起名，留下的 `provisional` / `fallback` 标题会很难看。写入时本技能统一置 `custom` + `resolved=true` + `titleRevision+1`，防止被重新生成覆盖。
- 执行目标：`execution_target_json.workspace` 需同时改 `id` 与 `path`。本地工作区的 `id` 是 `ws_<64位哈希>`，**无法由路径复现**；技能会优先复用目标工作区已有会话的值，新工作区才退回工作区 UUID。
- 影子会话：`extra_json.peerOriginSessionId` 非空，或 `execution_target_json.mode == "peer"` 的会话，正文在另一台设备，本机只有元数据。**一律拒绝改名与迁移**（改了也会被同步覆盖）。
- 工作区来源：`workspaces.workspace_source` 为 `local` 或以 `peer:` 开头。只有 `local` 能作为操作对象与迁移目标。
- 同一台机器上可能存在**同名工作区**（本地一份 + 对端投影若干）。技能解析名称时优先取唯一的本地工作区。

## 安装

技能目录（用户级，所有项目可用）：

```
C:\Users\<用户>\.workbuddy\skills\qoder-conversation-manager\
```

也可以整目录复制到 `~/.qoder/skills/` 或 `~/.codex/skills/`，三端 SKILL.md 格式一致。详见 `references/install.md`。

验证：

```bash
python <skill-dir>/scripts/qoder_sessions.py doctor
```

七项全 `OK` 说明可用；`Qoder 进程` 一项在应用运行时会是 `!!`，属正常。

## 命令总览

所有命令都支持 `--db <path>`（指向副本做演练）、`--json`（结构化输出）、`--force`（Qoder 运行中仍写入，慎用）。

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
python <skill>/scripts/qoder_sessions.py rename --export --out ./qoder-rename-export
# 可限定范围
python <skill>/scripts/qoder_sessions.py rename --export --filter "status = active" --out ./exp
```

导出目录里每个会话一个 `.txt`（含 SESSION_ID、现有标题、标题来源、工作区、cwd、消息数、用户轮数、完整对话），外加 `index.json`。

第二步，agent 读这些 txt 生成 `titles.json`：

```json
[
  {"sid": "e3d0af7b-8f30-40a9-a5aa-08b000dc0b3d", "new_title": "把会话迁移技能传到笔记本"},
  {"sid": "2dd673fa", "new_title": "排除代理误判定位 RDP 链路丢包"}
]
```

`sid` 可写完整 UUID 或前 8 位。然后写回：

```bash
python <skill>/scripts/qoder_sessions.py rename --import titles.json            # 干跑
python <skill>/scripts/qoder_sessions.py rename --import titles.json --apply    # 落盘
```

校验规则（基础档）：非空、2–40 字符、不含引号/书名号/句号/问号/换行/路径分隔符。重复标题只告警不拦截。

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

`--to` 接受工作区名称、根路径或 UUID。迁移会同时改 `workspace_id`、`cwd`、`execution_target_json.workspace.{id,path}` 三处，保持一致。已在目标工作区的会话自动跳过。

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

```bash
python <skill>/scripts/qoder_sessions.py backup --list
python <skill>/scripts/qoder_sessions.py backup
python <skill>/scripts/qoder_sessions.py rollback --backup <某个 .bak 文件> --yes --apply
```

备份写在数据库同目录，命名 `main.sqlite.bak-<动作>-<时间戳>`，默认保留最近 10 份。任何写操作落盘前会自动备份一次。`rollback` 会先把当前库另存为 `bak-pre-rollback-*` 再覆盖。

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
2. **写入前必须 Qoder 已退出**。运行中会直接拒绝（退出码 3）；`--force` 可绕过但不推荐。
3. **每次落盘前自动整库备份**，保留最近 10 份。
4. **影子会话一律拒绝**改名与迁移，并在输出里说明原因。
5. **只操作本地工作区**；对端投影既不能作为迁移目标，也不能被改名/删除。
6. **删除只做软删除**（进回收站），且必须 `--yes`。
7. **只改元数据**，不碰 `chat_session_messages` 正文与搜索索引。
8. **副本演练**：给 `--db` 指向副本时，不要求 Qoder 退出，可放心跑全套写操作。

退出码：`0` 成功；`1` doctor 有告警；`2` 参数/选择/目标错误或缺少确认；`3` Qoder 正在运行。

## 常见错误

| 现象 | 原因 | 处理 |
|---|---|---|
| `检测到 N 个 Qoder 进程` | 应用未退出 | 完全退出（含托盘）后重试，或先 `--db` 指向副本演练 |
| `目标工作区名不唯一` | 存在同名本地/对端工作区 | 用 `workspace list` 查 UUID，`--to <UUID>` |
| 迁完侧栏没变 | 应用未重启 | 重启 Qoder |
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
