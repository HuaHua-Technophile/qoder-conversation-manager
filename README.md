# Qoder Conversation Manager

[![Python](https://img.shields.io/badge/python-3.9%2B-blue)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/platform-Windows-lightgrey)]()
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

一个给 AI Agent 用的技能：管理本机 **Qoder** 的会话与工作区——列出筛选、按完整对话历史重命名、迁移到指定工作区、新建/改名/改路径/归档/删除工作区、整库备份与回滚、七项体检。

> A portable agent skill for managing local **Qoder** sessions and workspaces: list & filter, rename from the full transcript, move between workspaces, create/rename/retarget/archive/delete workspaces, backup & rollback, and a 7-point doctor.

---

## 为什么需要它

Qoder 自带的会话命名只取「首条用户消息 + 首条助手回复」。结果是侧栏里大量标题长这样：

- `在本机（HUAHUA-PC）把工具包里的旧 Win11 精简版镜像换成新镜像`
- `请您根据今日公…`

而对话真正的落点往往在中后段。举个例子，一条标题为「局域网远程控制方案」的会话，通读全文后真正的收尾是查出部署里的 `Any/Any` 防火墙规则和明文密码；一条「闲鱼2TB硬盘审计」的核心是从标签识破官翻盘。

这个技能把「读完整历史 → 起一个准确标题 → 安全写回」变成可重复的两步流程，并把会话归类、工作区管理一并做掉。

## 能做什么

| 命令 | 用途 | 写库 |
|---|---|---|
| `doctor` | 七项体检：数据库、WAL、表结构、Qoder 进程、工作区路径、影子会话、备份 | 否 |
| `list` | 六维筛选会话 | 否 |
| `rename --export` | 导出完整对话历史，供 agent 生成标题 | 否 |
| `rename --import` | 写回标题并锁定来源标记 | 是 |
| `move` | 会话迁入工作区（归属 / cwd / 执行目标三处同改） | 是 |
| `workspace` | `list` / `new` / `rename` / `retarget` / `archive` / `unarchive` / `delete` | 部分 |
| `backup` / `rollback` | 整库快照与恢复 | 是 |

**不做**：不删会话（只做工作区级联软删除）、不改对话正文、不操作另一台设备的影子会话、不碰 WorkBuddy 数据。

## 快速开始

```bash
# 1. 体检
python scripts/qoder_sessions.py doctor

# 2. 看看有哪些会话
python scripts/qoder_sessions.py list --limit 20

# 3. 导出完整历史（默认导出全部活跃会话；大批量加 --shards 做均衡分片）
python scripts/qoder_sessions.py rename --export --shards 6 --out ./exp

# 4. 让 agent 读 ./exp/*.txt，产出 titles.json，然后先干跑
python scripts/qoder_sessions.py rename --import titles.json

# 5. 确认无误后落盘（需先完全退出 Qoder）
python scripts/qoder_sessions.py rename --import titles.json --apply
```

`titles.json` 格式：

```json
[
  {"sid": "e3d0af7b-8f30-40a9-a5aa-08b000dc0b3d", "new_title": "把会话迁移技能传到笔记本"},
  {"sid": "2dd673fa", "new_title": "排除代理误判定位 RDP 链路丢包"}
]
```

## 命令示例

```bash
# 迁移：按条件批量
python scripts/qoder_sessions.py move --to Cross-Platform --filter "cwd contains NAS"
python scripts/qoder_sessions.py move --to Cross-Platform --filter "cwd contains NAS" --apply

# 工作区
python scripts/qoder_sessions.py workspace list
python scripts/qoder_sessions.py workspace new --name VMs --path D:/VMs --apply
python scripts/qoder_sessions.py workspace retarget --name VMs --path D:/VM2 --apply
python scripts/qoder_sessions.py workspace delete --name VMs --yes --apply

# 备份与回滚
python scripts/qoder_sessions.py backup --list
python scripts/qoder_sessions.py rollback --backup <main.sqlite.bak-...> --yes --apply
```

所有命令支持 `--json` 输出结构化结果，方便 agent 解析。

## 安全设计

- **默认 dry-run**：所有写命令不加 `--apply` 只打印计划。
- **允许热写**：Qoder 运行中也能写（WAL 保证一致性），写完重启应用做一次重建验证；要硬性拦截加 `--require-closed`。
- **按对象备份**：每条被改动的会话单独存一份完整行，支持单条回滚（`rollback --manifest`）或整批回滚（`rollback --batch`）；破坏性操作仍做整库快照，保留最近 10 份。
- **每条独立事务**：批量操作某条失败不影响其余，结束时按成功/失败计数返回退出码。
- **影子会话一律拒绝**：`peerOriginSessionId` 非空的会话正文在另一台设备，改了会被同步覆盖。
- **只操作本地工作区**：同名工作区解析优先取本地那份。
- **删除只做软删除**（进 Qoder 回收站），且必须 `--yes`。
- **副本演练**：`--db` 指向数据库副本时，不要求 Qoder 退出，可完整跑 rename / move / rollback。

## 安装到 AI Agent

技能是纯目录 + Python 标准库脚本，不需要 `pip install`。同一份目录可复制给 WorkBuddy、Qoder、Codex 使用。

```bash
# WorkBuddy
cp -r qoder-conversation-manager "$HOME/.workbuddy/skills/"

# Qoder
cp -r qoder-conversation-manager "$HOME/.qoder/skills/"

# Codex
mkdir -p "$HOME/.codex/skills" && cp -r qoder-conversation-manager "$HOME/.codex/skills/"
```

详见 [`references/install.md`](references/install.md)。

## 文档

| 文件 | 内容 |
|---|---|
| [`SKILL.md`](SKILL.md) | 技能主文档：完整命令、工作流、安全规则 |
| [`references/qoder-storage.md`](references/qoder-storage.md) | 表结构、写入约定、验证 SQL、已知坑 |
| [`references/subagent-playbook.md`](references/subagent-playbook.md) | 大批量重命名的子智能体切片与派活模板 |
| [`references/cases.md`](references/cases.md) | 真实案例：27 条重命名、13 条跨工作区迁移 |
| [`references/install.md`](references/install.md) | 三端安装与验证 |
| [`CHANGELOG.md`](CHANGELOG.md) | 版本记录 |

## 已知限制

- 仅支持 **Windows**（路径探测按 Windows 实现）。
- 不支持操作另一台设备的 Qoder 数据；影子会话会被拒绝。
- 不改对话正文，不重建 FTS 索引（标题不在索引内，无需重建）。
- 本地工作区的 `execution_target_json.workspace.id` 是 `ws_<64位哈希>`，算法不可复现；技能采用「复用目标工作区已有值，新工作区退回 UUID」的策略。

## 环境要求

- Python 3.9+
- Qoder（Windows），已登录并产生过会话
- 对 `%APPDATA%\com.qoder.app.stable\` 的读写权限

## License

[MIT](LICENSE)
