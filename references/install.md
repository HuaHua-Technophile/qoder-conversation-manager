# 跨 Harness 安装

技能是纯目录 + Python 标准库脚本，不需要 `pip install`。同一份目录可直接复制给 WorkBuddy、Qoder、Codex 使用。

## 目录要求

```
qoder-conversation-manager/
├── SKILL.md
├── CHANGELOG.md
├── scripts/
│   └── qoder_sessions.py
└── references/
    ├── qoder-storage.md
    ├── subagent-playbook.md
    ├── cases.md
    └── install.md
```

依赖：Python 3.9+；对 Qoder 数据目录的读写权限。仅支持 Windows（路径探测按 Windows 实现）。

## WorkBuddy（默认位置）

```
C:\Users\<用户>\.workbuddy\skills\qoder-conversation-manager\
```

复制：

```bash
cp -r "<源>/qoder-conversation-manager" "$HOME/.workbuddy/skills/"
```

WorkBuddy 读取 `~/.workbuddy/skills/*/SKILL.md`；复制后重启应用或在技能页刷新即可看到。
`display_name_zh` 作为中文显示名。

## Qoder

```
C:\Users\<用户>\.qoder\skills\qoder-conversation-manager\
```

复制：

```bash
cp -r "<源>/qoder-conversation-manager" "$HOME/.qoder/skills/"
```

加载：在 Qoder 里执行 `/skills reload`，再 `/skills list` 确认出现 `qoder-conversation-manager`。

> 注意：Qoder 的部分内置技能是指向 `~/.agents/skills/` 的软链。本技能需要独立目录，复制实体即可，不必建链。

## Codex

常见技能目录（以实际版本为准）：

```
~/.codex/skills/<skill-name>/
```

```bash
if [ -d "$HOME/.codex" ]; then
  mkdir -p "$HOME/.codex/skills"
  cp -r "<源>/qoder-conversation-manager" "$HOME/.codex/skills/"
fi
```

若该版本 Codex 使用共享目录 `~/.agents/skills/`，也可以复制到那里。

复制后重启 Codex 会话，确认技能列表出现该项。

## 验证

任选一个 Harness 的终端：

```bash
python "<技能目录>/scripts/qoder_sessions.py" --version
python "<技能目录>/scripts/qoder_sessions.py" doctor
```

`doctor` 能打印出数据库路径与七项检查，说明数据目录与权限正常。
若 `Qoder 进程` 一项显示 `!!`，只是应用在运行，不影响只读命令。

## 安全演练（不碰真库）

给别人演示或自己练手时，先复制一份库：

```bash
cp "$APPDATA/com.qoder.app.stable/main.sqlite" /c/temp/qoder-copy.sqlite
python "<技能目录>/scripts/qoder_sessions.py" --db "C:/temp/qoder-copy.sqlite" doctor
```

给 `--db` 指向副本时，写操作不再要求 Qoder 退出，可完整演练 rename / move / rollback。

## 多端同步

只保留一份源目录（建议 WorkBuddy 用户级），更新后整体覆盖其他端：

```bash
SRC="$HOME/.workbuddy/skills/qoder-conversation-manager"
cp -r "$SRC" "$HOME/.qoder/skills/"
[ -d "$HOME/.codex" ] && cp -r "$SRC" "$HOME/.codex/skills/"
```

不要在多端分别手改，否则版本漂移。

## 常见安装问题

| 现象 | 处理 |
|---|---|
| Qoder 技能列表没有出现 | 检查目录名与 frontmatter 的 `name` 一致；执行 `/skills reload` |
| WorkBuddy 看不到技能 | 确认 `~/.workbuddy/skills/qoder-conversation-manager/SKILL.md` 存在；重启应用 |
| 运行报 `未找到 Qoder 数据库` | 用 `--db` 指向 `main.sqlite`；确认 Qoder 已安装并登录过 |
| 提示 `Qoder 进程` 告警 | 正常，退出应用后再执行写操作 |
| 中文输出乱码 | 终端编码设为 UTF-8（`chcp 65001`） |
