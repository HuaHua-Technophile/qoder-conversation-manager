# 发布与上架

本文件记录分发渠道状态与提交步骤。平台规则可能变化，**以页面提示为准**；下列流程核对于 2026-11-15。

## 状态总览

| 平台 | 状态 | 说明 |
|---|---|---|
| GitHub | ✅ 已发布 v1.7.2 | [仓库](https://github.com/HuaHua-Technophile/qoder-task-manager)，MIT。Actions run `43791453827`，`release` + `skillhub` 两个 job 全绿；[Release v1.7.2](https://github.com/HuaHua-Technophile/qoder-task-manager/releases/tag/v1.7.2) 资产 `dir` 91,190 B / `root` 90,772 B，**与本地 `dist/` 同名包大小逐字节相同**（11 条目内容与 `HEAD` 全等） |
| SkillHub（skillhub.cn） | ✅ 已提交 v1.7.2（审核中） | CI 自动发布成功：`stats.versions` → **9**、8 个 tag 条目唯一值均为 **1.7.2**。`latestVersion` 仍回 **1.7.1**（该字段按「已过审版本」计算，审核通过后才刷新，属已知滞后）。1.7.0 时的实测可作参考：`category=dev-programming`、`iconUrl` 走 jsdelivr、`securityReports`（keen / sanbu）均 `benign`「安全，无风险」 |
| skills.sh（Vercel Labs 目录） | ⚠️ 未收录（2026-11-16 复核仍 404） | 该站按 `npx skills add` 安装量索引，**无手动上传入口**；搜索页只回显查询词、无结果条目，详情页 404。仓库已是 `skills/<name>/` 布局，等它下次扫描 |
| WorkBuddy 开放平台 | ⏳ 待更新 v1.7.2 | 能力 ID `os_f2f623a10e63b114`，公开。**无 API/CLI，只能手动上传 `-dir` 包**；包已就绪：`dist/qoder-task-manager-dir-1.7.2.zip`（1.7.0 卡在 frontmatter YAML、1.7.1 卡在示例数超限，见下方「1.7.1 / 1.7.2 补发」） |

### 1.7.2 补发（2026-11-16）

1.7.1 的包 YAML 已能解析，同一次上传卡在下一道字段校验：

```
解析失败：
examples_zh 最多 3 个示例，当前 4 个
examples_en 最多 3 个示例，当前 4 个
```

- **平台限制**：`examples_zh` / `examples_en` **最多 3 条**（官方文档只给字段表、没写数量上限，是校验器实测出来的）。
- **改动**：中英各裁到 3 条，保留「批量重命名 / 定时自动整理 / 迁移到工作区」，去掉健康体检那条（`doctor` 在正文与命令总览里仍有完整说明）。
- **把上限写进测试**：`test_required_fields_present` 从「恰好 4 条」改为「1 ≤ 条数 ≤ 3」，加第 4 条本地就红（已反向验证），不必等上传到平台才发现。
- **校验是分层的**：1.7.1 先报 YAML 语法，修好后同一次上传才轮到字段数量。所以「改一点、传一次」是正常节奏，不是包坏了。
| Qoder 技能市场 | ⏳ 待提交（本地已装 1.7.1） | 公开市场走拓展发布；本机 `~/.qoder/skills/qoder-task-manager` 用 `install.py` 同步 |

### 1.7.1 补发（2026-11-16）

1.7.0 对外发布后，用户在 WorkBuddy 开放平台上传 `-root-1.7.0.zip` 被拒：

```
解析失败：SKILL.md 格式错误 — frontmatter 无法解析
（yaml: line 9: mapping values are not allowed in this context）
```

- **根因**：`description_en` 是未加引号的 plain scalar，值里含半角冒号+空格 `on a daily schedule: any task`，YAML 会把它当成嵌套 mapping 的开头。平台报的 `line 9` 是**去掉开头 `---` 之后**的行号（用 PyYAML 复现：整文件第 10 行、第 262 列）。
- **为何一直没暴露**：SkillHub 只按正则取 camelCase 字段，从不跑 YAML 解析；WorkBuddy 渠道停更在 v1.3.3，没人传过带这段文案的包。
- **改动**：该处改为破折号 `— any task`（**不改用加引号**：SkillHub 会把 frontmatter 值当展示文案渲染，怕引号带进页面）；新增 frontmatter lint 测试（手搓规则 + 可选 `yaml.safe_load` 严格断言）防复发；版本升 1.7.1。**功能与 1.7.0 完全一致**，重发只为让制品与「可被 WorkBuddy 解析」的包一致。
- **待人工**：上传 `dist/qoder-task-manager-dir-1.7.1.zip`。注意 `-root` 包顶层是散开的（`SKILL.md` 直接在根），不符合平台「解压后第一层即技能目录」的要求。
| skillstore.io / Skill Vault | ⏳ 可选 | 第三方目录，填仓库地址或上传 SKILL.md |

### v1.7.0 发布核验记录（2026-11-16）

| 平台 | 核验手段 | 结论 |
|---|---|---|
| GitHub | `gh release view` + `gh run view --log` | 两资产齐、CI 测试步骤 `Ran 51 tests / OK (skipped=1)`（Linux 跳 1 条 nt-only 断言） |
| SkillHub | `GET /api/v1/skills/qoder-task-manager`（公共接口，无需 token） | `latestVersion=1.7.0`、安全扫描 benign、分类与图标已写入 |
| skills.sh | `curl` 搜索页 + 详情页状态码 | 搜索无结果条目、详情页 404 → 未收录（预期） |
| WorkBuddy | 浏览器 MCP / ComputerUse | **两条通道均不可用**，见下 |

**GUI 通道故障记录（本轮实测，非操作问题）**

- **Browser Use（内置浏览器）**：`dom_cua_get_visible_dom` 对 GitHub / skills.sh / `example.com` **一律返回空 snapshot**；`tab_screenshot` 连 200×200 的裁剪也报 `exceeds the 10 MiB image limit`（clip 未生效，整屏采集）。页面本身加载正常（`tab_title` 正确）。→ 无法读页面、也无法点击。
- **Computer Use**：`gui_permission_status` = `ready`（`all_granted:true`），`gui_screenshot(window_id="child_session")` 能正常出图；但 `create_task` 连续两次在 **step 0** 返回 `error: LLM: timeout`（各耗 600s，`history: []`），即内置 GUI agent 的推理侧超时。→ 截图可用，但主 agent 没有坐标点击工具，无法自行操作页面。
- 结论：本轮 WorkBuddy 上传只能人工完成。人工步骤见「渠道二」，用 `-dir` 包，注意当日/当月提审额度。

> **发布以 CI 为准**：本机直接 `publish` 上传会被重置（`[Errno 10054] 远程主机强迫关闭了一个现有的连接`），`auth whoami` 这类 GET 正常、POST 上传不通，疑似本地网络/代理对 multipart 的处理问题。CI 用同样的 CLI 与打包方式（剔除 `assets/`）可以成功，不要在本地反复重试，否则可能留下重复版本记录。
>
> **核对线上到底是不是新版**：直接下包比对，比刷页面可靠——
> `curl -sSL "https://api.skillhub.cn/api/v1/download?slug=%40user_3c4d2464%2Fqoder-task-manager" -o sh.zip`，解压读 `SKILL.md` 的 `version`。列表页与下载包都按「已过审版本」呈现，刚发布时仍是上一版。

## 提交材料

- **标识名**：`qoder-task-manager`（小写字母、数字、连字符）
- **中文名**：`Qoder任务管理`　**英文名**：`Qoder Task Manager`
- **版本**：见 `SKILL.md` 的 `version`
- **分类**：开发工具 / 效率工具 / 数据管理
- **许可证**：MIT

**中文简介**

> 管理 Qoder 桌面端任务与工作区：按完整任务历史重命名、迁移归属、新建与维护工作区、备份回滚，默认干跑并按对象备份。内置增量判定，可直接挂定时任务每天自动整理标题——改过名的任务只要之后又对话过就会重新判断。

**英文简介**

> Manage Qoder desktop tasks and workspaces — rename from full transcripts, move between workspaces, backup & rollback, with dry-run default and per-object backups. Built-in incremental rename lets it run on a daily schedule: any task talked to again since its last rename is re-evaluated.

**适用场景**

- 侧栏标题只反映第一句话，批量重命名
- **挂定时任务，每天自动把标题跟上内容**（改过名的任务被问及新话题后会自动重判）
- 把同一主题的任务归入对应工作区（含文件、记忆、产出）
- 新建 / 调整 / 清理工作区
- 改库前体检与回滚

**限制**

- 仅 Windows；Python 3.9+
- 只操作本机 Qoder 数据；跨设备影子任务只读
- 全局记忆 `~/.qoder/memory/` 不随迁移变动

## 渠道一：SkillHub（skillhub.cn）

CLI 是纯 Python 单文件，**Windows 不需要 WSL**（官方教程只提 Mac/Linux，实测 Git Bash + Python 3.13 可跑）。

**一次性安装**

```bash
curl -fsSL https://skillhub-1388575217.cos.ap-guangzhou.myqcloud.com/install/latest.tar.gz -o /tmp/kit.tar.gz
mkdir -p /tmp/kit && tar -xzf /tmp/kit.tar.gz -C /tmp/kit
mkdir -p ~/.skillhub ~/.local/bin
cp /tmp/kit/cli/skills_store_cli.py /tmp/kit/cli/skills_upgrade.py \
   /tmp/kit/cli/version.json /tmp/kit/cli/metadata.json ~/.skillhub/
printf '{\n  "self_update_url": "https://skillhub-1388575217.cos.ap-guangzhou.myqcloud.com/version.json",\n  "auto_self_upgrade": false\n}\n' > ~/.skillhub/config.json
```

之后统一用 `python3 ~/.skillhub/skills_store_cli.py <cmd>`，不依赖 wrapper 与 PATH。

**登录**：Token 在 <https://skillhub.cn/dashboard/keys> 创建（`skh_` 前缀，仅显示一次）。

```bash
python3 ~/.skillhub/skills_store_cli.py login --key skh_xxx --host https://api.skillhub.cn
python3 ~/.skillhub/skills_store_cli.py auth whoami
```

**frontmatter 要求**：平台只读 `slug` / `version` / `displayName` / `summary` / `description` / `tags` / `license` / `homepage` 这几个**驼峰**字段，WorkBuddy 用的 `display_name`、`description_zh` 它**不认**。所以 SKILL.md 头部必须同时写两套：

```yaml
slug: qoder-task-manager      # 全网唯一，kebab-case
displayName: Qoder任务管理              # 驼峰，平台用
summary: ……                            # 平台列表页简介
iconUrl: https://…png                  # 图标，先调 skill-icons/upload 拿
categoryIds: [dev-programming]         # 分类 key 数组
name: qoder-task-manager      # 下划线族，WorkBuddy 用
display_name: Qoder任务管理
```

**发布**

```bash
python3 ~/.skillhub/skills_store_cli.py publish <skill-dir> --dry-run
python3 ~/.skillhub/skills_store_cli.py publish <skill-dir> --changelog "本次变更"
```

成功输出 `✓ Published: skillId=xxxxx`。CLI **不回传 URL 和 status**，需到 <https://skillhub.cn/dashboard> 看：审核中 → `安全审核中`，通过后详情页 `https://skillhub.cn/skills/<slug>` 才完整可读。

**图标与分类（CLI 不带，必须自己补）**

平台把图标和分类放在 publish 的 payload 里，CLI 只传了 slug/version/displayName/summary/description/tags/license/homepage，所以发出来是默认占位图 + 未分类。

图标可以绕过界面直接补：

```bash
curl -X POST "https://api.skillhub.cn/api/v1/community/skill-icons/upload" \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@icon-512.png;type=image/png"
# → {"iconUrl":"https://...cos.accelerate.myqcloud.com/skill-icons/uploads/<uid>/<hash>.png"}
```

拿到 `iconUrl` 后写进 frontmatter，并给本地 CLI 补三个字段（`~/.skillhub/skills_store_cli.py` 的 `_post_publish_multipart`，约 2500 行）：

```python
_icon = str(metadata.get("iconUrl") or "").strip()
if _icon:
    payload["iconUrl"] = _icon
_cat = str(metadata.get("category") or "").strip()   # 一级分类 key
if _cat:
    payload["category"] = _cat
_subs = metadata.get("subCategories")                # 二级分类 key 数组，可选
if isinstance(_subs, list):
    _subs = [str(c).strip() for c in _subs if str(c).strip()]
    if _subs:
        payload["subCategories"] = _subs
```

然后 bump 版本重发（**同版本号会被拒**：`slug 冲突: 版本 x.y.z 已存在，请使用新的版本号发布`）。

**iconUrl 也可以用仓库自己的图标**（推荐，摆脱平台托管）：

```
https://cdn.jsdelivr.net/gh/HuaHua-Technophile/qoder-task-manager@main/skills/qoder-task-manager/assets/icon-qoder-512.png
```

- SkillHub **接受外部 iconUrl**，不限自家 CDN。上传接口拿到的 `skill-icons/uploads/...` 地址只是默认路径。
- 写入是**异步**的：publish 成功后 `skill.iconUrl` 仍可能是旧值，约 30–60 秒后才更新；同一 skill 更新版本可以覆盖。
- 用 jsdelivr 而不是 `raw.githubusercontent.com`：服务端两种都认，但 jsdelivr 在国内可达性明显更好（raw 实测也能写入，只是加载不稳）。
- 好处：图标跟仓库走，换平台、换托管都不影响；坏处：`@main` 会随分支变，要冻结就用 tag 或 commit（`@v1.3.6`）。

**分类字段是 `category`，不是 `categoryIds`** —— 这条坑了两次：

- `categoryIds` 是**企业/团队版** Skill 的字段（对应数字 id）。普通 Skill 传它会被服务端静默忽略，不报错，只是 `skill.category` 永远为空、后台一直显示「未分类」。
- 普通 Skill 用 `category`（一级分类 key，如 `dev-programming`）。实测**新建和更新版本都能写入**，无需重建。

一级分类 key（`GET /api/v1/categories`，共 13 个）：`office-efficiency` 办公效率、`content-creation` 内容创作、`dev-programming` 开发编程、`data-analysis` 数据分析、`design-media` 设计多媒体、`ai-agent`、`knowledge-management` 知识管理、`business-ops` 商业运营、`education` 教育学习、`professional` 行业专业、`it-ops-security` IT 运维与安全、`life-service` 生活服务、`pay-skill`。

**验证方法**（不用开浏览器）：

```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  "https://api.skillhub.cn/api/v1/skills/<slug>" | python3 -m json.tool | grep -E 'category|iconUrl'
```

**已知限制**

- 同 slug 重复发布 = 该 skill 的新版本（skillId 不变），但**版本号必须递增**。
- 审核中详情页「概述」区会显示 `无法加载文档 skill not found`，过审后自动正常。
- 网页「发布新技能」表单对已有 slug 会提示「该 Slug 已被占用」，不能拿来改已有 skill。
- 「从 GitHub 导入」能自动识别仓库 `skills/<name>/` 布局并推断 slug，但同样走新建流程。

## 渠道二：WorkBuddy 开放平台

1. 打开 <https://open.workbuddy.cn>，完成开发者认证（个人：身份材料 + 人脸）。
2. 左侧「发布管理 → 技能 → 创建」。
3. 上传压缩包。**要求：解压后第一层就是技能目录**，即 `qoder-task-manager/SKILL.md`，且只允许两级目录。用 `-dir` 包。
4. 平台自动解析 `SKILL.md` 的 frontmatter，以下字段缺一不可（本仓库已齐）：

   | 字段 | 本仓库取值 |
   |---|---|
   | `name` | `qoder-task-manager` |
   | `version` | 与发布版本一致 |
   | `display_name` | `Qoder任务管理`（中文展示名） |
   | `display_name_en` | `Qoder Task Manager` |
   | `description_zh` | 中文描述 |
   | `description_en` | 英文描述 |

   解析失败时平台会逐条列出缺什么，照补即可。
5. 「确认信息」：市场展示名称、分类、头像（512×512、≤500KB、JPG/PNG）、服务类目（1–5 个）。
6. 提交审核。标注 7 个工作日，实测多在 1 天内。
7. **过审后还要手动点「发布」并选公开发布**，否则一直躺在后台。
8. 付费为可选项：过审后在「收入变现」开通收款账户（微信签约）。注意计费模式一经发布不可改。

> 提审有额度：页面显示「当日 5 次、当月 20 次」，改完再传，别浪费在格式错误上。

**已上架后更新版本**：技能列表卡片右侧有「更新版本」，传新的 `-dir` 包即可，能力 ID（如 `os_f2f623a10e63b114`）与 slug 都不变。同样消耗提审额度——额度用尽时页面顶部显示 `今日 技能提审 5/5`，需次日再传。

## 渠道三：Qoder

**自用安装**（不需要审核）：

1. Qoder → 扩展 → 技能 → 添加技能 → 上传 Skill。
2. 支持 `.zip` / `.skill` / `SKILL.md`，**一次一项，不能传文件夹**。
3. 也可以直接把目录放到 `~/.qoder/skills/qoder-task-manager/`。

**上架公开市场**：

1. 同一入口提交发布，审核后在「我的发布」管理。
2. 审核重点（官方口径）：描述用第三人称写清职责与触发场景并含自然语言关键词；正文有步骤、注意事项与验证方式；不得含占位符或不可执行伪代码；不得有恶意脚本或真实凭证。
3. Skill 为机审为主、人工抽检，通常数分钟出结果。
4. 指南：<https://docs.qoder.com/zh/qoderwork/skill-marketplace-guidelines>

## 渠道四：第三方目录（可选）

- **skills.sh**：`npx skills add HuaHua-Technophile/qoder-task-manager` 即可安装，收录后出现在目录索引。
- **skillstore.io**：<https://skillstore.io/submit> 填仓库地址，自动扫描后人工审核。
- **Skill Vault**：<https://skillvault.md> 登录后上传 `SKILL.md`。

## 打包

```bash
python skills/qoder-task-manager/scripts/build_pkg.py
```

产物：

- `dist/qoder-task-manager-dir-<版本>.zip`：单层目录，**WorkBuddy 与 Qoder 都用这个**
- `dist/qoder-task-manager-root-<版本>.zip`：SKILL.md 在根，供要求扁平结构的目录使用

> 两个包内容一致，只差一层目录。上传报「结构不符合」时换另一个再试。

## 版本发布流程

**自动化程度一览**

| 渠道 | 推 GitHub 后自动更新 | 机制 |
|---|---|---|
| GitHub Release | ✅ 全自动 | `.github/workflows/release.yml`，push tag `v*` 即打包并发布 |
| skills.sh | ✅ 被动自动 | 无接口，它自己扫仓库，推上去等它收录 |
| SkillHub | ✅ 全自动 | 同一 workflow 的 `skillhub` job，Release 建好后自动发布。Token 存在仓库 secret `SKILLHUB_KEY` |
| WorkBuddy 开放平台 | ❌ 只能手动 | 官方文档确认无 API / CLI / CI，仅控制台上传 zip，另有提审额度 |

**标准流程（GitHub 全自动）**

```bash
# 1) 改两处版本号（自 v1.7.0 起版本号只有一个真源）
#    skills/qoder-task-manager/scripts/qoder_sessions.py → VERSION        ← 真源
#    skills/qoder-task-manager/SKILL.md                  → version:       ← 必须与真源一致
#    build_pkg.py 不再手改：它用正则从 qoder_sessions.py 读 VERSION，
#    读不到才回退 VERSION_FALLBACK（那个常量只在脚本缺失时才生效，正常不用动）
# 2) 写 CHANGELOG
git add -A && git commit -m "feat(vX.Y.Z): ..."
git push
git tag -a vX.Y.Z -m "vX.Y.Z — 摘要"
git push origin vX.Y.Z          # ← 到这里 GitHub Release 自动完成
```

CI 先校验 tag 与 `qoder_sessions.py` / `build_pkg.py`(读取值) / `SKILL.md` 三处是否一致，再跑测试、打包上传；任一处不一致会 `::error::` 中止，不会发出错版包。`tests/test_qoder_sessions.py` 里的 `test_single_source_of_truth` 会在本地就把这种漂移挡下来。

需要补发历史版本或重跑时，用 `workflow_dispatch` 手动指定 tag：

```bash
gh workflow run Release --repo HuaHua-Technophile/qoder-task-manager -f tag=v1.3.7
```

**SkillHub 自动发布的两个坑**

1. **不能另建 release-triggered workflow**：用 `GITHUB_TOKEN` 创建的 Release 不会触发其它 workflow（GitHub 防递归）。所以 SkillHub 发布必须做成**同一个 workflow 的第二个 job**（`needs: release`）。
2. **必须先剔除 `assets/`**：CLI 会把技能目录下所有文件打包上传，而仓库里的 `assets/*.png` 会被平台拒（`400 不允许的文件类型`）。CI 里是先 `cp` 到临时目录再 `rm -rf .../assets`。本地发布之所以没这个问题，是因为安装目录本来就不含 assets。

之后只剩 WorkBuddy 需要手动：控制台上传 `-dir` 包。

## 发布前自检

- [ ] 版本号一致：`qoder_sessions.py` 的 `VERSION` 与 `SKILL.md` 的 `version:`（`build_pkg.py` 自动跟随；CI 与本地测试都会挡）
- [ ] `python -m unittest discover -s skills/qoder-task-manager/tests -v` 全绿（v1.7.0 起 CI 也跑这一步，红则不发版）
- [ ] `python scripts/qoder_sessions.py doctor` 通过
- [ ] `CHANGELOG.md` 已写下本版条目（Release notes 由 CI 自动生成，Changelog 仍是主要说明）
- [ ] 本地 `python scripts/build_pkg.py` 跑一次，确认能打出两个 zip
- [ ] frontmatter 必填字段齐全：WorkBuddy 要 `name`/`display_name`/`display_name_en`/`description`/`description_zh`/`description_en`/`version`/`author`；SkillHub 要 `slug`/`version`/`displayName`
- [ ] 用到 `iconUrl` 时确认地址可达（`curl -I`）
- [ ] 打 tag 后看 Actions 跑绿，再处理 SkillHub / WorkBuddy 两个外部渠道
- [ ] 提交后用新任务实测：能识别何时触发、命令能跑通
