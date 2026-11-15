# 安装到宿主 agent

技能是纯目录 + Python 标准库脚本，不需要 `pip install`。凡是能解析 `SKILL.md` 的宿主，都可以直接使用同一份目录。

## 目录要求

```
qoder-task-manager/
├── SKILL.md
├── CHANGELOG.md
├── README.md
├── LICENSE
├── scripts/
│   ├── qoder_sessions.py
│   └── build_pkg.py
├── references/
│   ├── qoder-storage.md
│   ├── subagent-playbook.md
│   ├── cases.md
│   └── install.md
├── examples/
│   └── titles.example.json      # titles.json 的合法样例（默认长度参数下可直接导入）
└── tests/
    └── test_qoder_sessions.py   # 端到端测试（标准库 unittest，真跑 CLI）
```

`tests/` 不进发布包（`build_pkg.py` 只打包 `scripts / references / examples`），但留在仓库里——拿到源码就可以 `python -m unittest discover -s skills/qoder-task-manager/tests -v` 自检。`examples/` 会进包。

依赖：Python 3.9+；对 Qoder 数据目录的读写权限。仅支持 Windows（路径探测按 Windows 实现）。

## 通用安装

把整个 `qoder-task-manager/` 目录放进宿主 agent 的**用户级技能目录**（所有项目可用），或放进项目的技能目录（仅当前项目）。目录名与 `SKILL.md` 里的 `name` 字段保持一致。

各宿主的目录约定不同，以宿主自己的设置为准。常见形态：

| 宿主 | 用户级目录（示例） |
|---|---|
| Qoder | `~/.qoder/skills/qoder-task-manager/` |
| Codex | `~/.codex/skills/qoder-task-manager/` |
| 其他 | 宿主设置页里「技能 / Skills」标明的目录，通常形如 `~/.<host>/skills/` |

复制命令（Git Bash / macOS / Linux）：

```bash
cp -r "<源>/qoder-task-manager" "<宿主技能目录>/"
```

复制后让宿主重新加载技能列表：多数宿主重启任务即可，部分提供 `/skills reload`。

## 验证

任选一个终端：

```bash
python "<技能目录>/scripts/qoder_sessions.py" --version
python "<技能目录>/scripts/qoder_sessions.py" doctor
```

`doctor` 会打印数据库路径与**七项基础检查**（数据库、WAL、表结构、Qoder 进程、工作区路径、影子任务、备份），全部 `OK` 说明数据目录与权限正常；加 `--deep` 再查五项（任务文件、目录一致性、项目记忆、产出索引、孤立项目目录）。刚装好还没备份过时，「备份」项只提示先跑一次 `backup`、**不判失败**（首次写入会自动建备份）。

## 安全演练（不碰真库）

给别人演示或自己练手时，先复制一份库：

```bash
cp "$APPDATA/com.qoder.app.stable/main.sqlite" "C:/temp/qoder-copy.sqlite"
python "<技能目录>/scripts/qoder_sessions.py" --db "C:/temp/qoder-copy.sqlite" doctor
```

给 `--db` 指向副本时，写操作与真库完全隔离，可完整演练 rename / move / rollback。

## 多端同步

只保留一份源目录，更新后整体覆盖其他宿主的副本：

```bash
SRC="<你的源目录>/qoder-task-manager"
cp -r "$SRC" "$HOME/.qoder/skills/"
[ -d "$HOME/.codex" ] && cp -r "$SRC" "$HOME/.codex/skills/"
```

不要在多端分别手改，否则版本漂移。

## 常见安装问题

| 现象 | 处理 |
|---|---|
| 宿主技能列表没有出现 | 检查目录名与 frontmatter 的 `name` 一致；重启任务或执行宿主的技能重载命令 |
| 运行报 `未找到 Qoder 数据库` | 用 `--db` 指向 `main.sqlite`；确认 Qoder 已安装并登录过 |
| 中文输出乱码 | 终端编码设为 UTF-8（`chcp 65001`）；脚本已把 stdout/stderr 强制成 UTF-8，GBK 终端会显示乱码但不会再抛 `UnicodeEncodeError` |
| `doctor` 提示工作区路径不可达 | 该工作区根目录可能在外接盘或另一台设备上，属正常 |
