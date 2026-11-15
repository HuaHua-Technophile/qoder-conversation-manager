# 开发指南

这个仓库是 `qoder-task-manager` 的**唯一源码**。所有改动都从这里出发，推上去自动发布。

## 一、目录结构：符号链接，只有一份代码

`~/.workbuddy/skills/qoder-task-manager` 是指向本仓库的**符号链接**：

```
~/.workbuddy/skills/qoder-task-manager
        └─(symlink)→ C:/Users/HuaHua/dev/qoder-task-manager/skills/qoder-task-manager
```

改仓库里的文件，等于直接改运行时——不用复制、不用重装、不用重启 WorkBuddy（新会话即生效）。

确认当前是不是链接：

```powershell
Get-Item "$HOME\.workbuddy\skills\qoder-task-manager" | Select-Object LinkType, Target
```

新机器上重建：

```bash
python install.py --link        # 符号链接（开发用）
python install.py               # 复制安装（分发用）
```

Windows 建符号链接需要**开发者模式**或管理员权限。

`doctor` / `rename` 的备份默认落在技能目录，也就是仓库内，已在 `.gitignore` 排除 `qoder-cm-backups/`。想放别处用 `--backup-dir`。

## 二、环境

- Python 3.9+（脚本只用标准库，无第三方依赖）
- Windows（脚本针对 Qoder 桌面端的本地数据）
- git 走 SSH（本机已配 `github_huahua_pc`）
- 仓库必须放**本地磁盘**：技能目录是指向它的符号链接，仓库在网络盘上时，笔记本离线技能会跟着失效

## 三、改代码的完整流程

### 1. 改之前先拉最新

```bash
cd C:/Users/HuaHua/dev/qoder-task-manager
git pull
```

### 2. 改代码

主要文件：

| 文件 | 作用 |
|---|---|
| `skills/qoder-task-manager/SKILL.md` | 技能定义，agent 读它决定何时触发、怎么执行 |
| `skills/qoder-task-manager/scripts/qoder_sessions.py` | 全部功能实现（单文件） |
| `skills/qoder-task-manager/references/*.md` | 深入参考：存储结构、安装、案例、子代理话术 |
| `skills/qoder-task-manager/CHANGELOG.md` | 变更记录，发版必写 |
| `skills/qoder-task-manager/PUBLISHING.md` | 各渠道发布规则与踩坑记录 |

### 3. 本地验证（关键：别动真库）

只读命令可以直接跑：

```bash
cd skills/qoder-task-manager
python scripts/qoder_sessions.py doctor
python scripts/qoder_sessions.py list --limit 5
```

要测**写入**（rename / move / rollback）时，先复制一份库再指过去，避免污染真实数据：

```bash
cp "$APPDATA/com.qoder.app.stable/main.sqlite" /tmp/test.sqlite
python scripts/qoder_sessions.py rename --db /tmp/test.sqlite --ids xxx --apply
```

`--db` 指向副本时脚本会自动放行（不再要求 Qoder 退出）。

### 4. 同步三处版本号

**这三处必须一致，少一处 CI 会直接失败**（故意设计成会挡）：

```bash
# 1) SKILL.md            → version:
# 2) scripts/qoder_sessions.py → VERSION
# 3) scripts/build_pkg.py      → VERSION
```

顺手在 `CHANGELOG.md` 顶部加本版条目。

### 5. 提交推送

```bash
cd C:/Users/HuaHua/dev/qoder-task-manager
git add -A
git commit -m "feat(vX.Y.Z): 一句话说明"
git push
```

### 6. 打标签触发发布

```bash
git tag -a vX.Y.Z -m "vX.Y.Z — 摘要"
git push origin vX.Y.Z
```

到这一步就结束了，剩下的自动完成：

```
release   job → 校验版本号 → 打包两个 zip → 建 GitHub Release
skillhub  job → 装 CLI → 登录 → 剔除 assets → 发布 → 等审核
```

看进度：<https://github.com/HuaHua-Technophile/qoder-task-manager/actions>

### 7. 更新自己用的版本

SkillHub 审核通过后（通常几分钟），在 WorkBuddy 技能市场里点「更新」，或：

```bash
skillhub install qoder-task-manager --namespace user_3c4d2464
```

## 四、发布后各渠道

| 渠道 | 自动？ | 说明 |
|---|---|---|
| GitHub Release | ✅ | tag push 即触发，含两个 zip |
| SkillHub | ✅ | 同一 workflow 第二个 job，过审后市场可见 |
| skills.sh | ✅ 被动 | 自己扫仓库，无提交入口，收录时机不可控 |
| WorkBuddy 开放平台 | ❌ 手动 | 无 API/CLI，只能控制台上传 `-dir` 包，且当日限 5 次 |

WorkBuddy 那次需要手动：拿 `dist/qoder-task-manager-dir-<版本>.zip` 到 <https://open.workbuddy.cn/skill/all> 点「更新版本」。

## 五、踩过的坑

**换行符**：仓库里 `SKILL.md` 和脚本是 CRLF，但 `references/*.md`、`examples/*.json` 是 LF。用脚本批量改文件后再复制，容易整文件 diff。用 Python 读写时统一 `\r\n` 归一。

**assets 不能进发布包**：`assets/` 是仓库的展示图（README 图标、平台头像），SkillHub 拒收 png。CI 里发布前会 `rm -rf` 掉。本地发布之所以没这问题，是因为运行时目录本来不含 assets。

**同版本号会被拒**：`slug 冲突: 版本 x.y.z 已存在，请使用新的版本号发布`。哪怕只改一个错别字也得升版本。

**524 是假失败**：Cloudflare 网关超时，但服务端往往已经处理完。CI 已加重试 + 「版本已存在即视为成功」的判断，看到红叉先查 SkillHub 上有没有该版本。

**`skillhub publish` 会打包整个目录**：临时文件、`__pycache__`、`dist/` 都会进去。发布前确认目录干净。

**仓库不要放网络盘**：技能目录是指向仓库的符号链接。仓库若落在 SMB 共享上（例如 `X:` ＝ `//huahua-book/B/`），笔记本离线时链接会断、技能读不到。仓库固定在 `C:\Users\HuaHua\dev\` 就没有这个问题；而工作区（对话空间）照旧放 SMB 互不影响，两者可以分开。

## 六、改完之后

- 本地运行时不会自动更新，需要去市场点「更新」
- 已发布版本不可撤回，只能再发一版覆盖
- 撤回整条技能：`DELETE /api/v1/community/skills/<slug>`
