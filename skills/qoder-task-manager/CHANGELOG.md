# CHANGELOG

## 1.7.0 — 2026-11-16

审计后的一次迭代：24 项修复 + 端到端测试套件。按「数据安全 / 输出契约 / 功能正确性 / 健壮性 / 工程化」五组推进，**全部在副本库与独立夹具上验证，真实库零写入**。

### 数据安全（这四处会真丢数据）

- **`backup_path()` 备份被同名文件覆盖**：原来只按 basename 落到 `files/<sid8>/<bucket>/`，`out/x/log.txt` 与 `out/y/log.txt` 备份成同一个 `output/log.txt`，后者覆盖前者——原始内容直接丢。现在文件按**相对 cwd 的相对路径**存放（`files/<sid8>/output/out/x/log.txt`，自动建中间目录），拿不到相对路径时退回 `basename-<绝对路径 sha1 前 8 位>`；目录（sidecar / memory）保持整棵复制。实测搬两个不同子目录的同名文件后两份都在、内容各自正确。另加一道守卫：`rel` 是盘相对路径（`D:x.txt`）时 `os.path.join` 会把它退化成自身、把备份写到备份根之外，现按 `os.path.splitdrive` 拒绝并走 `basename-sha1` 回退。
- **整库回滚在 Qoder 运行时不拦截**：`rollback --backup` 是 `shutil.copy2` 覆盖文件 + 删 `-wal/-shm`，不是 WAL 事务，应用在跑时会把库写坏；其它写操作都有事务保护，只有这条裸奔。现在检测到 Qoder 进程直接 `die(...,3)`，新增 `--force-hot` 逃生开关（显式传才放行并打风险提示）；`--manifest/--batch` 分支行为不变。
- **`CUSTOM_DB` 判定按路径语义比较（P0）**：`--db` 是否指向副本原来用 `os.path.abspath(...) != default` 判断，不做大小写归一——`--db` 只要写成 `c:\users\…` 这种小写形式，同一个库就被判成「副本」，而 `CUSTOM_DB` 是 A2 的唯一开关，一旦为真会**同时**跳过整库覆盖硬拦、`gate_running()`、`post_write_hint()` 三处保护，正好把上一条堵的洞重新打开。现抽成 `is_custom_db()`，先 `realpath`（解开 junction / 符号链接 / `\\?\` 前缀，否则 `mklink /J` 一条指向同一个库的链接就能绕过硬拦）再 `normcase`（大小写不敏感）。v1.6.0 里它只是个提示开关无所谓，v1.7.0 起它是安全闸门，必须按路径语义比。
- **回滚清单加表名/主键白名单（P0）**：`restore_row()` 要把表名与主键列拼进 SQL（标识符无法用占位符），原来完全不校验——一份手改的清单 `{"table":"workspaces","key_column":"1 or 1=1 or workspace_id","op":"insert","key_value":"x"}` 就能把 `workspaces` 整表删空，还回报 `[OK]`。现按 `KEY_COLUMNS = {chat_sessions: session_id, workspaces: workspace_id}` 校验，不匹配直接 `die(...,2)`（JSON 模式仍有 `{"error","exit"}` 出口），并中止整批而不是静默跳过。
- **`move` 承诺的「搬空的源项目目录自动删除」从未生效**：清空目录时是在**搬完之后**才求值 `find_project_dir`，那时只会命中新目录（在 keep 里），`removed_dirs` 永远为空，`projects/` 下永久堆积空目录。现在进循环前先拍 `pre_dirs` 快照，搬完按快照清理（与 `repair` 的写法对齐）。实测搬走目录里最后一条任务后目录被删、`batch.json.removed_dirs` 非空。

### 输出契约（`--json` 现在能直接喂给 `json.load`）

- **`--json --apply` 不再吐两份 JSON + 人话**：新增模块级 `JSON_MODE`，`out()` 在 JSON 模式下静音、`warn()` 收集告警、`die()` 输出 `{"error":..., "exit":N}`，每条命令只在最后 `emit_json()` 打**一份**文档。
- **空结果也是合法 JSON**：`move` 无任务、`rename --export` 无匹配时输出 `{"target":..., "plan":[], "applied":false, ...}` / `{"out_dir":null, "count":0, "items":[], ...}`，不再打印「没有需要迁移的任务」。
- **告警不再污染 stdout**：`[WARN]` / `[NOTE]` 统一进 `warnings` 字段（数组型结果如 `list` 打到 stderr）。
- 形状固定：`rename --export {out_dir,count,items,shards,skipped,warnings}`、`rename --import {applied,plan,touched,skipped,results,backup,warnings}`、`move {target,plan,applied,results,backup,removed_dirs,warnings}`、`repair {applied,plan,results,backup,removed_dirs,warnings}`、`rollback {restored,failed,items,warnings}`、`workspace *` 单文档。`... --json --apply | python -c "import json,sys;json.load(sys.stdin)"` 已全覆盖通过。
- **影子计数口径**：`list` 的「另有 N 条影子任务未显示」按「同一筛选范围内再加 `--include-peer` 会多出来的行数」统计，在 `--limit` **之前**算，不能用「全库总数 − 结果数」——否则 `--limit`/`--keyword`/`--workspace` 会把被筛掉的本地任务也算成影子（沙箱实测 `--keyword 路由器` 旧口径报 271，真值 2）。

### 功能正确性

- **标题长度默认值与文档冲突**：`--min-title-len` 默认 20，文档规则却是「正文 8–22 汉字 + `[分类] ` 前缀」（合计 12–30 字符）——`[网络] 排查 RDP 丢包`（14 字符）被拒，仓库自带的 `examples/titles.example.json` 3 条里 2 条不合法。默认改为 **12–30 字符**，错误信息写明「字符」；示例文件补 `category` 字段并调到 3 条全合法。实测不带任何长度参数导入示例，0 条因长度被拒。
- **`--filter` 不支持的语法静默返回空集**：`title contains x or cwd like y` 原来把 `x or cwd like y` 当字面值匹配，输出「没有匹配的任务」，用户误以为真没有。现在检测 `or` / 括号 / `not` / 比较运算即 `FilterError`（退出码 2），消息点明「只支持 and 连接与 contains/like/startswith/endswith/=/!=」。
- **`list` 默认隐藏影子任务却不提示**：本机 291 条里 260 条是影子，`list` 只说「共 29 条」，看起来像数据丢了。末尾加一行「另有 N 条影子任务未显示，加 `--include-peer` 查看」，N = **同一筛选范围内**被默认隐藏的影子行数（在 `--limit` 之前统计，口径见下方 B 组最后一条）；`--json` 时该提示走 stderr。
- **`workspace list` 同名对端工作区无法区分**：`野草云4C8G` 出现两行且完全一样，实际是 `peer:f659e85d…` 与 `peer:c174a08a…` 两台设备。表格加「设备」列（本地 `本机`，对端取设备 ID 前 8 位），`--json` 加 `device` 字段。
- **`--skip-in-target` 是死开关**：`action='store_true', default=True` 恒为真、无法关闭。改用 `argparse.BooleanOptionalAction`，得到 `--skip-in-target/--no-skip-in-target`；`--no-skip-in-target` 现在真的会把已在目标工作区的任务一起重跑（用于只补搬文件），默认行为不变。顺带把 `--ids` 的两种落空分开报：库里根本没有 → `[WARN] 未匹配到任务`；任务存在但已在目标被跳过 → `[NOTE] 已在目标工作区，跳过（要重跑加 --no-skip-in-target）`，不再把后者误报成前者。
- **`workspace retarget` 改完不提示后果**：retarget 只改库里的 `cwd`，项目目录仍在旧编码下 → 项目记忆立刻读不到，`doctor --deep` 会报「目录一致性」。成功率后打印「cwd 已改，项目目录未搬；如需恢复项目记忆请运行 repair（先干跑看清单）」，JSON 加 `note` 字段，SKILL.md 与常见错误表同步补行。
- **记忆合并报告漏报 copied**：`merge_memory()` 返回 `{copied,merged,skipped}`，输出只打 `记忆 +{merged}/跳过{skipped}`，首次迁移实际复制了 2 个文件却显示「记忆 +0」。改成 `记忆 新增N/合并N/跳过N`，`batch.json` 的条目里带上完整 `memory_report`；JSON 结果里的 `memory_merged` 也改成 `copied + merged` 之和（原来只数 merged，copied 3 时仍是 0，按该字段判定的自动化会以为没搬记忆）。

### 健壮性

- **非 UTF-8 控制台遇 emoji 直接 traceback**：Windows 管道按 locale（GBK）编码，标题里一个 emoji 就 `UnicodeEncodeError` 崩掉整条命令（`PYTHONIOENCODING=gbk python … list` 已复现）。`main()` 开头对 stdout/stderr 做 `reconfigure(encoding='utf-8', errors='replace')`，try/except + hasattr 包裹，老版本或非 `TextIOWrapper` 静默跳过。
- **`find_project_dir` 多副本时结果不确定**：原来返回 `os.listdir()` 遍历里第一个命中，顺序无保证，新旧目录并存时可能选错。新增 `find_project_dirs()`（排序返回全部命中），`find_project_dir()` 取第一个并在命中数 >1 时 `warn` 报出有几个副本。
- **`rename_apply` 全 ID 分支可能取错行**：`by_short = {sid[:8]: row}` 后写覆盖前写，传完整 36 位 ID 时按前 8 位反查，前缀撞车就改错任务。改为 `by_full` 直查完整 ID；短 ID 分支按前缀统计命中数，>1 时跳过并报「ID 前缀不唯一，请给完整 ID」。
- **`move --create` 新建的工作区不在任何备份清单里**：`rollback --batch` 之后工作区行残留成孤儿。新建时往备份组写 `items/workspaces-<id>.json`，payload 带 `"op":"insert"`；`restore_row()` 遇到 `op=="insert"` 执行 `delete from workspaces where workspace_id=?`，`batch.json` 的 items 里带上这条。实测回滚后 session 回到原工作区、新建行被删干净。

### 工程化

- **新增端到端测试套件** `tests/test_qoder_sessions.py`：标准库 `unittest`，绝大多数用例**通过 subprocess 真跑 CLI**（不 mock）；只有「Qoder 正在运行」没法用 subprocess 伪造，改用 `mock.patch.object(qs, 'qoder_running')` 直接调 `cmd_rollback()` 断言 exit 3。每个用例用 `tempfile.TemporaryDirectory` 建独立夹具（最小但真实的 schema + `projects/` 目录 + 记忆/产出文件），覆盖路径编码（UNC 与盘符）、筛选表达式正常/非法、标题边界（11/12/30/31 字符）、示例文件回归、rename 往返与 `titleSource`/`titleRevision`、`--json` 单文档、move 的文件/记忆/产出/空目录清理/同名文件备份、rollback 的 `op:insert` 回滚与批量干跑、`doctor --deep` 十二项、安全边界（回滚清单白名单、`is_custom_db` 的 realpath + normcase 判定、盘相对 rel 不越界）、版本一致性。**51 个用例全绿**；`python -m unittest discover -s skills/qoder-task-manager/tests -v` 即可跑。
- **版本号单一来源**：`build_pkg.py` 改为正则从 `qoder_sessions.py` 读 `VERSION`（读不到才回退 `VERSION_FALLBACK`），CI 的 tag 校验也改读主脚本；SKILL.md frontmatter 由测试兜住——三处任一漂移，测试直接红。
- **`doctor` 补两项**：`--deep` 增加「孤立项目目录」（`projects/*` 下 jsonl 数为 0 的目录，本机实测就有一个 `D--…-11679d46`）；`备份` 项从「永远 OK」改成真检查——最近备份**超过 14 天**时标 `!!`。「库里有任务但从未备份」只提示 `建议先跑一次 backup`、**不判失败**：首次写入本来就会自动建备份，判失败会让新装用户第一眼看到 `!!`、让自动化拿到 exit 1，还与「七项基础全 OK 说明可用」自相矛盾。
- **文档同步**：`SKILL.md` 安全规则编号重排为 1..14（原来有两个 6、两个 8、两个 9）、标题规则改 12–30 字符、`--json` 契约写清单文档与空结果、`move` 孤立目录清理确认有效、`retarget` 加 repair 提示、`--filter` 补「不支持 or/括号」；`references/qoder-storage.md` 补「文件按相对路径存放」、已知坑加「整库回滚必须关应用」「retarget 后需 repair」、修正 `workspace.id` 表述（也可能是工作区 UUID，不只 `ws_` 哈希）；`references/subagent-playbook.md` 长度参数对齐新默认值；`.github/workflows/release.yml` 在打包前加跑测试。

## 1.6.0 — 2026-11-15

新增增量重命名（`rename --pending`），核心是「**改名过的任务，只要之后又对话过就重新判断**」；顺带修掉 `rename --apply` 必定抛 NameError 的老 bug。

- **新功能 `rename --export --pending`**：只导出「值得改名」的任务，供定时任务反复运行而不重复劳动。候选 = 本地 + 未删除 + 非影子，且满足其一：
  - 标题未定稿（`titleSource != custom`）；
  - **上次判断之后又产生过新对话**。基准取 `extra_json.qoderCm.renamedAt`（上次写入/确认时间），**不是「今天零点」**——所以「一个月前改过名、今天又追加对话」的任务照样会被重新判断，跨零点、跨天都不漏。
  
  只有没有改名留痕的老任务（v1.4.x 改过的、Qoder 自带 `ai` 标题已定稿的）才退回 `--pending-since` 兜底窗口（默认 `yesterday`，解决 23:00 之后到零点的对话被漏掉）；这些任务被重新判断过一次后即写入留痕，之后按精确时间比对。
- **留痕与收敛**：`--apply` 在 `extra_json.qoderCm` 写 `{title, renamedAt, by}`。重新判断后**标题仍合适**的，也会刷新 `renamedAt`（输出 `[SAME]`）并认领 `titleSource`，否则下一轮会因「比上次判断新」被反复导出。
- **人工改名**：默认不特殊对待，之后有对话就重新判断；要保护手改标题加 `--respect-manual`（仅当 `titleSource` 仍为 custom 且与记录不符时视为手改）。
- **空任务跳过**：没有任何用户轮的任务无法起名，增量模式下自动排除。
- **修 bug**：`rename_apply()` 末尾残留了 move 分支的 `metadata_only` / `removed` 判断，这两个变量在该函数内不存在，导致每次 `--apply` 写完标题后必抛 `NameError`——标题其实已落盘，但退出码非 0、清单不打完。现删除该段，改为标准的备份与回滚提示。
- 兼容性：不带 `--pending` 时行为与 1.4.x 完全一致。已在副本库跑通：跨零点对话、一个月前改名后追加对话、刚改名无新对话、同标题 `[SAME]` 收敛、再次导出无候选。

## 1.4.4 — 2026-11-15

统一换行符，消除跨平台 diff 噪音。功能无变化。

- 新增 `.gitattributes`：`* text=auto eol=lf`，文本文件在仓库存储与工作区检出两侧统一为 LF；png/jpg/zip 标记为二进制，不做转换。
- 此前 `core.autocrlf=true` 使 blob 存 LF 而工作区检出 CRLF，同一文件在不同机器、不同工具下形态不一致，用脚本批量改写后再复制容易整文件 diff。现在两侧一致，也不再依赖各人的 git 配置。
- `SKILL.md`、脚本、`references/`、`examples/` 等 14 个文本文件转为 LF，**内容零改动**（`git diff` 为空，仅换行符变化）；`--version` 与 `doctor` 七项复测通过。
- 发布包内容不变，仍为 11 个文件；zip 体积各减约 3KB（CRLF 相对 LF 每行多一个字节）。

## 1.4.3 — 2026-11-15

修复 `workspace retarget --apply` 必定崩溃，并纠正影子任务判断。

- **崩溃**：retarget 分支调用 `is_peer_type()` 只传 1 个参数，而函数签名要 2 个，直接抛 `TypeError: is_peer_type() missing 1 required positional argument: 'd'`。异常在 `with` 事务内抛出，`workspaces` 那条更新一并回滚——表现为「跑完没报成功、库也没变」，路径改不动。
- **影子任务漏判**：原代码给 `execution_target_json` 传的是空串，`mode == "peer"` 的影子任务永远识别不出来，会被一起改掉 `cwd`，随后被同步覆盖。现在按行读出真实值判断，输出里报「跳过影子任务 N 条」。
- `is_peer_type()` 的第二个参数改为可选，只传一个字段 dict 也能用，避免同类调用再踩同一个坑。
- 任务计数改为按实际处理行数统计（含已删除任务），已删除的额外注明，不再和循环范围对不上。

## 1.4.2 — 2026-11-15

用打过补丁的 CLI 重发，让分类与图标真正落到条目上。

- 根因：CI 里调用的是**官方 `skillhub publish`**，它只传 slug/version/displayName/summary/description/tags/license/homepage/changelog，**不传 `category` 和 `iconUrl`**。本地那份 CLI 之前打过补丁，所以本地发有效、CI 发无效。
- 1.4.1 因此仍然「未分类」且无图标。本版改用本地补丁版 CLI 发布。
- 功能无变化。

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
