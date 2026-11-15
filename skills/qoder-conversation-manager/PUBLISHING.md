# 发布与上架

本文件记录分发渠道状态与提交步骤。平台规则可能变化，**以页面提示为准**；下列流程核对于 2026-11-15。

## 状态总览

| 平台 | 状态 | 说明 |
|---|---|---|
| GitHub | ✅ 已发布 | [仓库](https://github.com/HuaHua-Technophile/qoder-conversation-manager)，MIT，Release 含两个安装包 |
| skills.sh（Vercel Labs 目录） | ⚠️ 未收录 | 2026-11-15 复核：技能页提示不在该仓库下，发布者页 404。该站按 `npx skills add` 安装量索引，无手动提交入口；根目录 SKILL.md 的布局可能不被识别为仓库内的 skill。 |
| WorkBuddy 开放平台 | ⏳ 待提交 | 需开发者认证；提审有配额（当日 5 次 / 当月 20 次） |
| Qoder 技能市场 | ⏳ 待提交 | 客户端「扩展 → 技能 → 添加技能」可先自用；公开市场走拓展发布 |
| skillstore.io / Skill Vault | ⏳ 可选 | 第三方目录，填仓库地址或上传 SKILL.md |

## 提交材料

- **标识名**：`qoder-conversation-manager`（小写字母、数字、连字符）
- **中文名**：`Qoder会话管理`　**英文名**：`Qoder Conversation Manager`
- **版本**：见 `SKILL.md` 的 `version`
- **分类**：开发工具 / 效率工具 / 数据管理
- **许可证**：MIT

**中文简介**

> 管理 Qoder 桌面端会话与工作区：按完整对话历史重命名、迁移归属、新建与维护工作区、备份回滚，默认干跑并按对象备份。

**英文简介**

> Manage Qoder desktop sessions and workspaces — rename from full transcripts, move between workspaces, backup & rollback, with dry-run default and per-object backups.

**适用场景**

- 侧栏标题只反映第一句话，批量重命名
- 把同一主题的对话归入对应工作区（含文件、记忆、产出）
- 新建 / 调整 / 清理工作区
- 改库前体检与回滚

**限制**

- 仅 Windows；Python 3.9+
- 只操作本机 Qoder 数据；跨设备影子会话只读
- 全局记忆 `~/.qoder/memory/` 不随迁移变动

## 渠道一：WorkBuddy 开放平台

1. 打开 <https://open.workbuddy.cn>，完成开发者认证（个人：身份材料 + 人脸）。
2. 左侧「发布管理 → 技能 → 创建」。
3. 上传压缩包。**要求：解压后第一层就是技能目录**，即 `qoder-conversation-manager/SKILL.md`，且只允许两级目录。用 `-dir` 包。
4. 平台自动解析 `SKILL.md` 的 frontmatter，以下字段缺一不可（本仓库已齐）：

   | 字段 | 本仓库取值 |
   |---|---|
   | `name` | `qoder-conversation-manager` |
   | `version` | 与发布版本一致 |
   | `display_name` | `Qoder会话管理`（中文展示名） |
   | `display_name_en` | `Qoder Conversation Manager` |
   | `description_zh` | 中文描述 |
   | `description_en` | 英文描述 |

   解析失败时平台会逐条列出缺什么，照补即可。
5. 「确认信息」：市场展示名称、分类、头像（512×512、≤500KB、JPG/PNG）、服务类目（1–5 个）。
6. 提交审核。标注 7 个工作日，实测多在 1 天内。
7. **过审后还要手动点「发布」并选公开发布**，否则一直躺在后台。
8. 付费为可选项：过审后在「收入变现」开通收款账户（微信签约）。注意计费模式一经发布不可改。

> 提审有额度：页面显示「当日 5 次、当月 20 次」，改完再传，别浪费在格式错误上。

## 渠道二：Qoder

**自用安装**（不需要审核）：

1. Qoder → 扩展 → 技能 → 添加技能 → 上传 Skill。
2. 支持 `.zip` / `.skill` / `SKILL.md`，**一次一项，不能传文件夹**。
3. 也可以直接把目录放到 `~/.qoder/skills/qoder-conversation-manager/`。

**上架公开市场**：

1. 同一入口提交发布，审核后在「我的发布」管理。
2. 审核重点（官方口径）：描述用第三人称写清职责与触发场景并含自然语言关键词；正文有步骤、注意事项与验证方式；不得含占位符或不可执行伪代码；不得有恶意脚本或真实凭证。
3. Skill 为机审为主、人工抽检，通常数分钟出结果。
4. 指南：<https://docs.qoder.com/zh/qoderwork/skill-marketplace-guidelines>

## 渠道三：第三方目录（可选）

- **skills.sh**：`npx skills add HuaHua-Technophile/qoder-conversation-manager` 即可安装，收录后出现在目录索引。
- **skillstore.io**：<https://skillstore.io/submit> 填仓库地址，自动扫描后人工审核。
- **Skill Vault**：<https://skillvault.md> 登录后上传 `SKILL.md`。

## 打包

```bash
python skills/qoder-conversation-manager/scripts/build_pkg.py
```

产物：

- `dist/qoder-conversation-manager-dir-<版本>.zip`：单层目录，**WorkBuddy 与 Qoder 都用这个**
- `dist/qoder-conversation-manager-root-<版本>.zip`：SKILL.md 在根，供要求扁平结构的目录使用

> 两个包内容一致，只差一层目录。上传报「结构不符合」时换另一个再试。

## 版本发布流程

```bash
# 1) 改 SKILL.md 的 version 与 CHANGELOG
# 2) 同步脚本里的 VERSION
python skills/qoder-conversation-manager/scripts/build_pkg.py
git add -A && git commit -m "feat(vX.Y.Z): ..."
git push
gh release create vX.Y.Z dist/*.zip --title "vX.Y.Z — 摘要" --notes "..."
# 3) 到各平台重新上传 zip，版本号与 SKILL.md 保持一致
```

## 发布前自检

- [ ] `SKILL.md` 的 `version` = 本次发布版本
- [ ] `python scripts/qoder_sessions.py doctor` 通过
- [ ] `python skills/qoder-conversation-manager/scripts/build_pkg.py` 重新打包
- [ ] 解压 zip 确认第一层目录名与 `name` 一致
- [ ] frontmatter 六个必填字段齐全
- [ ] 头像尺寸与大小合规
- [ ] 提交后用新会话实测：能识别何时触发、命令能跑通
