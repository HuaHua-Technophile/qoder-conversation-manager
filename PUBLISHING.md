# 发布与上架

本文件记录该技能在各分发渠道的状态，以及还需要人工完成的步骤。

## 状态总览

| 平台 | 状态 | 说明 |
|---|---|---|
| GitHub | ✅ 已发布 | [仓库](https://github.com/HuaHua-Technophile/qoder-conversation-manager)，MIT，含 v1.0.0 Release 与两个安装包 |
| skills.sh（Vercel Labs Agent Skills Directory） | ✅ 已收录 | 通过 `npx skills add` 安装即进入索引；已安装到 `~/.agents/skills/`，榜单检索有延迟 |
| WorkBuddy 开放平台 | ⏳ 待提交 | 安装包已就绪，需开发者认证后在后台上传 |
| Qoder 技能市场 | ⏳ 待提交 | 安装包已就绪，需在 Qoder 内提交（机审，通常几分钟） |
| skillstore.io | ⏳ 待提交 | 填仓库地址即可，需 GitHub 登录授权 |
| Skill Vault（skillvault.md） | ⏳ 待提交 | 需注册登录后上传 SKILL.md |
| Claude 插件目录 | ❌ 暂不适用 | 需要付费开发者计划 |

## 一键安装（已可用）

```bash
npx skills add HuaHua-Technophile/qoder-conversation-manager
```

也可以直接克隆：

```bash
git clone https://github.com/HuaHua-Technophile/qoder-conversation-manager.git
```

## 提交材料（可直接复制）

**技能名（英文）**：Qoder Conversation Manager
**技能名（中文）**：Qoder会话管理
**版本**：1.0.0
**分类**：开发工具 / 效率工具 / 数据管理
**许可证**：MIT

**一句话简介（中文）**
> 管理 Qoder 本地会话与工作区：按完整对话历史重命名、迁移归属、新建与维护工作区、备份回滚，默认干跑并自动备份。

**一句话简介（英文）**
> Manage local Qoder sessions and workspaces — rename from full transcripts, move between workspaces, backup & rollback, with dry-run default and automatic backups.

**适用场景**
- 侧栏会话标题只反映第一句话、难以辨认时批量重命名
- 把同一主题的对话归入对应工作区
- 新建/调整/清理工作区
- 改库前的体检与回滚

**限制说明**
- 仅 Windows；需 Python 3.9+
- 只操作本机 Qoder 数据，不处理其他设备的影子会话
- 写入前需退出 Qoder

## 待人工完成的步骤

### 1. WorkBuddy 开放平台

1. 打开 <https://open.workbuddy.cn>，完成开发者认证（个人：身份证 + 人脸）。
2. 进入「发布管理 → 技能 → 创建」，上传 `qoder-conversation-manager-workbuddy-1.0.0.zip`。
   - 包内根目录直接是 `SKILL.md`，符合平台要求；体积 34 KB，远低于 3 MB 上限。
3. 补充头像（512×512，≤500KB）、分类、使用说明。
4. 提交审核（官方口径 7 个工作日，实测常当天出结果）。
5. 若要做付费：审核通过后再开通收款账户；注意**展示名称不能含空格**，本包已使用 `Qoder会话管理`。

### 2. Qoder 技能市场

1. 在 Qoder 内打开技能市场 → 上传自有 Skill。
2. 使用 `qoder-conversation-manager-qoder-1.0.0.zip`（单层同名目录 + SKILL.md）。
3. 审核以机审为主，通常几分钟出结果。
4. 参考文档：<https://docs.qoder.com/zh/qoderwork/skill-marketplace-guidelines>

> 也可走 API：`POST https://api.qoder.com.cn/api/v1/cloud/skills`，需 `QODER_ACCESS_TOKEN`，`files` 字段传上述 zip。

### 3. skillstore.io

1. 打开 <https://skillstore.io/submit>。
2. 填入仓库地址 `https://github.com/HuaHua-Technophile/qoder-conversation-manager`。
3. 等待自动安全扫描与人工审核。

### 4. Skill Vault

1. 打开 <https://skillvault.md>，用 GitHub / Google / 邮箱登录。
2. 上传 `SKILL.md`，填写工具兼容性标签（WorkBuddy / Qoder / Codex）。

## 打包

```bash
python build_pkg.py
```

生成两个包：

- `dist/qoder-conversation-manager-workbuddy-1.0.0.zip`：根目录直接含 `SKILL.md`
- `dist/qoder-conversation-manager-qoder-1.0.0.zip`：单层目录 `qoder-conversation-manager/`

## 版本发布流程

```bash
git add -A
git commit -m "feat: ..."
git tag v1.0.1
git push && git push --tags
gh release create v1.0.1 dist/*.zip --title "v1.0.1" --notes "..."
```

> 本机 HTTPS 访问 GitHub 的 git 端点会被重置，仓库已改用 SSH（部署密钥仅授权该仓库）。
> 若在其他机器上推送，需要自行配置凭据。
