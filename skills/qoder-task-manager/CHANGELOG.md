# CHANGELOG

## 1.4.1 — 2026-11-15

补写 SkillHub 分类与图标。

- 1.4.0 是新建技能条目，平台在**首次创建时不写入** `category` 与 `iconUrl`（payload 里带了也忽略），导致市场里「未分类」且无图标。
- 本版只改版本号重发一次，让这两项落到条目上；功能与 1.4.0 完全一致。

## 1.4.0 — 2026-11-15

项目标识统一为 `qoder-task-manager`。

- 技能标识：`slug` / `name` / 目录名 / GitHub 仓库名，全部由 `qoder-conversation-manager` 改为 `qoder-task-manager`。
- 英文品牌名：`Qoder Conversation Manager` → `Qoder Task Manager`；中文名仍是「Qoder任务管理」。
- `iconUrl` 同步指向新仓库路径（jsdelivr）。
- **这是一次标识变更**：SkillHub 上是新条目，旧 slug `qoder-conversation-manager` 需单独下架；已安装旧版的用户不会自动迁移。
- 命令、参数、数据库行为全部不变。

## 1.3.9 — 2026-11-15

英文描述改用 Tasks，纠正 1.3.7 / 1.3.8 的判断错误。

- 实测本机 Qoder 0.5.12 的 `app.asar`，i18n 里 `sessions` 这个 key 的中文值是「任务」、英文值是 **`Tasks`**、韩文是「작업」。也就是说 `sessions` 只是代码里的键名，英文界面显示的本来就是 Tasks。
- 此前认为「英文界面叫 sessions、改成 tasks 会对不上界面」是错的，实际正好相反。
- `description_en`、`examples_en`、正文英文摘要、README、PUBLISHING 的英文简介统一改为 tasks。
- 保留不变：`qoder-task-manager`（slug/name）、`Qoder Task Manager`（英文品牌名）、`chat_sessions` 等数据库标识。
- 无功能改动。

## 1.3.8 — 2026-11-15

示例数据术语对齐，1.3.7 的收尾。

- `examples/titles.example.json` 的示例标题「把会话迁移技能传到笔记本」改为「把任务迁移…」，与正文保持一致。
- 英文描述维持 `sessions` / `conversations`：Qoder 英文界面与 TIX 安全报告的措辞都是这两个词，改成 tasks 反而对不上。
- 无功能改动。

## 1.3.7 — 2026-11-15

术语统一，全篇不再混用「空间 / 对话 / 会话」三种叫法。

- 「空间」→「工作区」（6 处），与 Qoder 自身的 workspace 叫法一致。
- 「对话」「会话」→「任务」（约 200 处），文档、脚本注释与 CLI 输出一并调整。
- 展示名同步改为「Qoder任务管理」（`displayName` / `display_name` / `display_name_zh`）；`slug` 与 `name` 仍是 `qoder-task-manager`，不影响安装与升级。
- 英文描述保留 `sessions` / `conversations` 未动：那是 Qoder 英文界面的原生叫法，改成 tasks 反而对不上，也影响英文检索。
- 无功能改动，命令、参数、退出码、数据库字段全部不变。

## 1.3.6 — 2026-11-15

图标改指向仓库自身，不再依赖 SkillHub 的图片托管。

- `iconUrl` 由 `skillhub-...cos.accelerate.myqcloud.com/skill-icons/uploads/...` 改为 `cdn.jsdelivr.net/gh/<owner>/<repo>@main/skills/qoder-task-manager/assets/icon-qoder-512.png`。
- 起因：原地址是平台个人上传目录，重新上传图标会生成新 URL、旧地址将来可能失效，且无法在 GitHub / 其他渠道复用。
- 实测 SkillHub **接受外部 iconUrl**，但写入是异步的（发布后约 30–60 秒才出现在 `skill.iconUrl`）；同一 skill 更新版本可覆盖。
- 仍无脚本逻辑改动。

## 1.3.5 — 2026-11-15

修正上架分类字段：普通 Skill 认 `category`，不认 `categoryIds`。

- `categoryIds` 是企业/团队版 Skill 用的字段，普通发布传它会被服务端静默忽略，表现为上架后长期「未分类」。
- 改为 `category: dev-programming`（一级分类 key），实测新建与**更新版本**都能写入。
- 仍不含脚本逻辑改动，清单页行为与 1.3.4 一致。

## 1.3.4 — 2026-11-15

补齐 SkillHub 上架所需的驼峰元数据与图标，无脚本逻辑改动。

- frontmatter 增加 `slug` / `displayName` / `summary`：SkillHub CLI 只认驼峰字段，此前只有 WorkBuddy 用的下划线族，CLI 校验会直接报「缺少 slug」。
- frontmatter 增加 `iconUrl`：平台的图标要在发布 payload 里带，CLI 默认不传，上架后是默认占位图。
- 两套字段并存，WorkBuddy 的 `name` / `display_name` / `description_zh` 不受影响。

## 1.3.3 — 2026-11-15

frontmatter 增加 `examples_zh` / `examples_en` / `author`，市场上架时「试试这样问我」不再为空。

## 1.3.2 — 2026-11-15

产出识别补第三路：任务专属 cwd。

- 当 `cwd` 末段等于任务 ID 前 8 位（Qoder 给无工作区任务分配的临时目录）时，该目录下**全部顶层条目**都算产出，一并搬迁。
- 覆盖 Bash 创建、正文里没有 `Write`/`Edit` 记录的目录与日志。
- 明确策略：无归属任务默认不动、不询问。

## 1.3.1 — 2026-11-15

标题长度默认值改为 20–30。

- 不传 `--min-title-len` / `--max-title-len` 时，按 20–30 字符（含 `[分类] ` 前缀与空格）校验。
- 想用旧行为显式传参即可，例如 `--min-title-len 2 --max-title-len 40`。
- 短标题现在会被拦下并提示实际字符数。

## 1.3.0 — 2026-11-15

产出识别不再只靠低覆盖率的 DB 索引。

- 新增正文解析：从任务 JSONL 里抓 `Write` / `Edit` / `MultiEdit` / `NotebookEdit` 的 `file_path`，与 `turn_file_change_files` 合并去重。
- 仍只搬落在任务 `cwd` 之下、且与目标不重合的文件；外部路径不搬。
- 明确默认：**全量搬运**，`--metadata-only` 是显式开关而非默认。
- 修 bug：正文解析曾放在搬走 JSONL 之后，导致永远抽不到路径；已改为搬前抽取。
- 覆盖实测：本机 27 条任务中 2 条有 cwd 内产出，共 7 个文件（此前只识别到 3 个）。

## 1.2.3 — 2026-11-15

`move` 支持目标不存在时自动建工作区。

- `--create`：按 `--to` 的绝对路径新建本地工作区，名称默认取路径末段，`--name` 可覆盖。
- 目录不存在时默认拒绝，加 `--allow-missing` 才继续。
- 干跑只提示将新建，不写库；`--apply` 时先建工作区再迁移。
- 修复：根路径统一存绝对路径（之前传相对路径会原样落库）。

## 1.2.2 — 2026-11-15

搬空的源项目目录自动清理，不再留空壳。

- `move` / `repair` 结束后，源项目目录若已无任何 `*.jsonl`，直接删除（含残留记忆）；`--keep-orphans` 可保留。
- 删除清单写入 `batch.json` 的 `removed_dirs`，便于追溯。
- 本机实战：清理 17 个历史残留目录，`projects/` 从 25 个目录收敛到 8 个有任务的目录。

## 1.2.1 — 2026-11-15

补两个能力，用于修正历史「只改库没搬文件」的迁移。

- 新增 `repair`：按当前 `cwd` 把正文、子目录、项目记忆、产出归位，只搬文件不动数据库。
  记忆按源目录判断：独享目录才合并，共用目录保留在原项目，避免复制污染。
- 新增 `doctor --deep`：加查「每条任务是否有正文文件」「项目目录与 `cwd` 是否一致」「项目记忆分布」「产出索引覆盖」。
- 本机实战：17 条历史任务完成归位，目录一致性从 17 条不一致降为 0。

## 1.2.0 — 2026-11-15

`move` 从「只改归属」升级为**全量迁移**：任务文件、项目记忆、产出一起搬。

- 任务文件：`projects/<旧cwd编码>/<sid>.jsonl` 与 `<sid>/` 子目录搬到新 cwd 编码的目录。
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

- **按对象备份 + 单条回滚（对齐 1）**：`rename` / `move` 每次落盘新建 `qoder-cm-backups/<动作>-<时间戳>/`，`items/` 下每条任务一份完整行，`batch.json` 汇总。新增 `rollback --manifest`（只回滚一条）与 `rollback --batch`（回滚整批）。整库快照仍用于破坏性操作。
- **每条独立事务 + 失败隔离（对齐 2）**：批量写不再整批一个事务；单条失败只标记 `[FAIL]` 并继续，结束后返回成功/失败计数（有失败时退出码 1）。
- **允许热写（对齐 3）**：Qoder 运行中不再直接拒绝写入，改为 `[WARN]` 提示并继续；写完提示重启应用做重建验证。需要旧行为时加 `--require-closed`（退出码 3）。`doctor` 的进程检查改为提示项，不再计为异常。
- **LPT 均衡分片（对齐 7）**：`rename --export --shards N` 按字数用最长优先算法切片，输出 `shards/groupN.json`，供子智能体并行；`index.json` 增加 `chars` 字段。
- **分类维度（对齐 8）**：`titles.json` 支持 `category` 字段，自动补成 `[分类] 标题`；新增 `--require-prefix`、`--min-title-len`、`--max-title-len`。
- **允许重名（对齐 9）**：移除重复标题告警，不同任务可同名。

### 其它

- `--ids` 中匹配不到的 ID 会输出 `[WARN]`，不再静默忽略。
- `--force` 参数移除，由 `--require-closed` 取代。
- 文档订正：影子任务拒绝是 **Qoder 数据形态特有**的必要防护（对端任务正文不在本机），不作为与其他技能的优劣比较项。

## 1.0.0 — 2026-11-15

首个版本。把「重命名任务 / 迁移任务 / 管理工作区」三件事打包成一个技能，操作对象为 Qoder 桌面端本地数据。

### 新增命令

- `doctor`：七项体检（数据库可读、WAL 状态、表结构、Qoder 进程、工作区路径可达、影子任务占比、备份情况）。
- `list`：六维筛选（`--workspace` / `--cwd` / `--keyword` / `--filter` / `--since` / `--include-deleted` / `--include-peer` / `--limit`）。
- `rename --export` / `rename --import`：两步式重命名。导出完整任务历史供 agent 起名，导入时做基础校验并锁定标题来源。
- `move`：把任务迁入工作区，三处字段（`workspace_id` / `cwd` / `execution_target_json`）同步更新；支持 `--filter` 批量。
- `workspace list|new|rename|retarget|archive|unarchive|delete`。
- `backup` / `rollback`：整库快照、自动保留最近 10 份、回滚前先另存当前库。

### 设计决策

- 默认 dry-run，所有写完必须显式 `--apply`。
- 写入前要求 Qoder 已退出，运行时拒绝（退出码 3）；`--force` 可绕过。
- 每次落盘前自动备份（当时存放在数据库同目录，v1.1.2 起改到工作目录）。
- 影子任务（`peerOriginSessionId` 非空或 `mode=peer`）一律拒绝改名与迁移。
- 工作区解析优先本地，避免同名对端投影干扰。
- `execution_target_json.workspace.id` 优先复用目标工作区已有值，新建工作区退回 UUID（该值算法不可复现，详见 `references/qoder-storage.md`）。
- `workspace delete` 只做软删除（`deleted_at`），级联其下任务，需 `--yes`。
- 输出默认人读表格，`--json` 给结构化结果。

### 已知限制

- 仅支持 Windows（路径探测按 Windows 实现）。
- 不改任务正文，不重建 FTS 索引（标题不在索引内，无需重建）。
- 不支持操作另一台设备的 Qoder 数据。
- 元信息校验为「尽力兼容」：Qoder 升级导致表结构变化时，缺失列会被跳过而非报错。

### 实测

数据库副本上完成闭环：rename → 断言标题与锁定标记 → rollback 恢复；move → 断言 `cwd` 与执行目标 → rollback 恢复；同名工作区拒绝新建；缺 `--yes` 的删除被拦截（退出码 2）。

真实库上完成 27 条任务重命名与 13 条任务跨工作区迁移，`PRAGMA integrity_check` 均为 `ok`。
