# 真实案例

两段实操，均在本机 Qoder（Windows，286→288 条任务）上完成。

## 案例一：27 条任务按完整历史重命名

### 背景

侧栏里大量标题是「请您根据今日公…」「在本机（HUAHUA-PC）把工具包里的旧…」这类首句截断。
`extra_json.titleSource` 分布显示：`provisional` 234 条、`custom` 26 条、`ai` 19 条、`fallback` 7 条。

### 关键判断：先分清哪些能改

```bash
python <skill>/scripts/qoder_sessions.py doctor
python <skill>/scripts/qoder_sessions.py list --include-peer --limit 10
```

体检发现 288 条里 260 条是 `peer` 影子任务（来自笔记本 HuaHua-Book），本机只有元数据、没有正文。
**这些不能改**——正文在对端，改了会被同步覆盖。

最终可操作的是 28 条本机任务。

### 第一版做错了什么

先按「首 10 轮 + 末 4 轮」导出摘要起名，结果标题仍偏向开头。用户反馈：

> 它的重命名只根据我发出去的首条消息和 Agent 回复的首条消息来做，我不满意。

确实如此——摘要把中段砍了，等于换了个方式看开头。

### 第二版：完整历史 + 子智能体

```bash
python <skill>/scripts/qoder_sessions.py rename --export --out ./exp
```

27 条完整历史合计 409 KB，最长一条 169 消息 / 57 轮 / 91 KB。按体积切 6 片，6 个子智能体并行通读，
各自回答「最初想做什么 → 中途遇到什么 → 最后交付什么」。

### 效果对照

| 首句版 | 全文版 |
|---|---|
| 局域网远程控制方案 | 配通 RDP 并审计防火墙与明文密码 |
| 闲鱼选4块2T硬盘 | 为选盘 Agent 编写分阶段审计提示词 |
| 闲鱼2TB硬盘审计 | 私聊核实 SMART 后识别官翻并重排硬盘 |
| 修复 Tailscale RDP 中继绕路 | 排除 Clash 代理定位 RDP 链路丢包 |

「局域网远程控制方案」这条，真正的收尾是查出 Apollo 部署里的 Any/Any 规则和明文密码；
「闲鱼2TB硬盘审计」的核心是从标签识破官翻盘。这些都发生在任务中后段。

### 落盘与校验

```bash
python <skill>/scripts/qoder_sessions.py rename --import titles.json           # 干跑
python <skill>/scripts/qoder_sessions.py rename --import titles.json --apply
```

写入 27 条，`PRAGMA integrity_check` 为 `ok`，与备份逐行 diff 确认**只这 27 行变化**，影子任务零改动。

教训：**标题必须读全文**。摘要是省事，但省掉的正是判断依据。

---

## 案例二：按主题把任务归入工作区

### 目标工作区

用户新建了 `Cross-Platform`（根路径 `\\huahua-book\B\Cross-Platform`）。
库里同时存在一个同名的对端投影（根路径 `D:\B\Cross-Platform`），本机没有该盘符。

```bash
python <skill>/scripts/qoder_sessions.py workspace list
```

技能解析名称时优先取唯一的本地工作区，因此 `--to Cross-Platform` 直接命中本地那份。

### 分批迁移

```bash
# 跨设备类（SSH / RDP / SMB / 记忆同步）
python <skill>/scripts/qoder_sessions.py move --to Cross-Platform --filter "cwd contains NAS and status = active" --apply

# 新建工作区后归入工具包类
python <skill>/scripts/qoder_sessions.py workspace new --name VMs --path D:/VMs --apply
python <skill>/scripts/qoder_sessions.py move --to VMs --filter "title contains 工具包" --apply

# 硬盘类归入 NAS
python <skill>/scripts/qoder_sessions.py move --to NAS --ids c7e0c1a7,d447aa22,b62e62ad,6ede7059 --apply
```

### 最终归属

| 工作区 | 根路径 | 任务数 |
|---|---|---|
| Cross-Platform | `\\huahua-book\B\Cross-Platform` | 9（另 1 条在回收站） |
| NAS | `E:\B\NAS` | 8 |
| VMs | `D:\VMs` | 4 |

### 中途踩的坑

1. **漏移一条**：`e3d0af7b` 是筛查之后（当天 10:34）才新建的任务，不在候选名单里。用户发现后补移。
   → 批量操作前重新 `list` 一次，别用旧清单。
2. **备份同名覆盖**：两次迁移在同一秒执行，`bak-before-move-20261115-110456` 被后一次覆盖。
   → 批量操作前先手工 `backup` 一次作为锚点。
3. **`execution_target_json` 的 id 猜不出来**：本地工作区的值是 `ws_<64位哈希>`，无法由路径复现。
   最终策略是「复用目标工作区已有任务的值，新建工作区才用工作区 UUID」，实测应用接受且不报错。
4. **路由器类任务的归属有歧义**：`小米路由器刷 SSH 装 lucky 远程开机` 看标题像 NAS 相关，
   读全文才发现唤醒目标是台式机 HUAHUA-PC，路由器只是常开哨兵，与 `E:\B\NAS` 无关。
   → 归类前先看正文，别被标题骗。
