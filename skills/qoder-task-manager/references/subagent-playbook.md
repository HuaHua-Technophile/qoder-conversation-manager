# 子智能体分工模板（大批量重命名）

任务超过 ~15 条、或单条历史很长时，单线程读会撑爆上下文。按下面的方式切分。

## 一、导出并自动分片

```bash
python <skill>/scripts/qoder_sessions.py rename --export --shards 6 --filter "status = active" --out ./exp
```

产出：

- `./exp/<sid8>.txt`：每条任务的完整历史
- `./exp/index.json`：含 `chars`、`messages`、`user_turns`、`file`
- `./exp/shards/group1.json … groupN.json`：按字数用 **LPT（最长处理时间优先）** 均衡分好的清单

分片逻辑：把任务按 `chars` 降序排序，逐条放进当前累计字数最小的那片。一条 20 万字的任务会独占一片，不会被硬塞进小片里。脚本最后会打印每片条数与字数，最大/最小比通常在 1.3 左右。

**不需要手工切片**，直接用脚本产出的 `groupN.json`。若某片明显过大（单条超 15 万字），再单独拆。

## 二、派活提示词（每片一份）

```
你是任务命名专家。通读整段任务的完整历史后再命名，不能只看开头。

输入清单：<绝对路径>/exp/shards/groupN.json
每项含 sid、title（旧标题）、chars、file（正文文件，在 <绝对路径>/exp/ 下）

背景：这些任务现有的标题只反映「首条用户消息」，往往漏掉真正的主线。
你要判断：用户最初想做什么 → 中途遇到什么 → 最后实际交付了什么。
若中途转向，以占篇幅最大或最终解决的那条主线命名。

读取要求：
1. chars ≤ 30000：完整读 file。
2. chars > 30000：先读开头 120 行、中部 120 行、结尾 120 行，必要时 Grep 搜「用户第」定位转折。
3. 必须覆盖清单里每一条，不得跳过。

标题规则：
1. 简体中文，正文 8–22 个汉字（加 `[分类] ` 前缀合计 12–30 字符，脚本默认按此校验）；SSH/RDP/RAID5/NAS/WinGet 等技术名词保留原文，与中文之间加半角空格。
2. 结构优先「动作 + 具体对象」，要能和同批其他任务区分。
3. 禁止引号、书名号、句号、问号、换行、文件路径、代码。
4. 不得照抄现有标题。
5. 分类短类 2–4 个汉字，从这套里选：系统 / 网络 / 开发 / 数据 / 硬件 / 办公 / 生活 / 其他；确实不合适才自拟，并在 why 里说明。
6. 允许与别的任务重名，不要为了避重而强行改写。

输出：Write 到 <绝对路径>/exp/results/groupN.json
[{"sid":"完整SESSION_ID","new_title":"正文（不含前缀）","category":"网络","why":"一句话依据"}]
```

`category` 由脚本在写回时自动拼成 `[网络] 正文`，**不要在 new_title 里手动加前缀**。

## 三、回收与合并

1. 检查每片 JSON 能否 `json.load`、条数是否与 `groupN.json` 一致。
2. 合并成 `titles.json`（保留 `category`）。
3. 交叉校验：
   - 同一 `cwd` 下的标题是否指向不同对象（尤其「工具包」「闲鱼」「RDP」这类同主题群）。
   - 分类是否收敛在 8–12 个，别出现十几个一次性短类。
   - 长度是否越界（默认 12–30 字符，含 `[分类] ` 前缀；确实要放宽再用 `--min-title-len` / `--max-title-len`）。
4. 先干跑：

```bash
python <skill>/scripts/qoder_sessions.py rename --import titles.json
```

5. 核对清单无异常后落盘：

```bash
python <skill>/scripts/qoder_sessions.py rename --import titles.json --apply
```

脚本会输出每条 `[OK]` / `[WARN]`、成功失败计数，以及备份组路径。误改可用：

```bash
python <skill>/scripts/qoder_sessions.py rollback --manifest "<备份组>/items/chat_sessions-<sid>.json" --yes --apply
```

## 四、二轮只改长度（不重分类）

用户嫌标题太长或太短时，**不要重读全文**。保留上一轮的 `category` / `why`，只让子智能体在原有 `new_title` 上扩写或压缩：

```json
{"sid": "...", "pass1_title": "...", "category": "网络", "target": "12-30 字符（含前缀）"}
```

合并后直接再跑一次 `rename --import`（备份会另起一组，不会覆盖上一轮）。

## 五、常见问题

| 现象 | 处理 |
|---|---|
| 子智能体只读了文件开头 | 提示词里强调「必须完整读完，长文件首中尾抽样」 |
| 标题重复 | 现在允许重名；只要指向对象不同就不算错 |
| 用了现有标题的措辞 | 明确要求「不得照抄 CURRENT_TITLE」 |
| 漏条 | 用 `groupN.json` 的 sid 列表做差集核对 |
| 分片极不均衡 | 检查是否有单条超 15 万字；LPT 已尽量均衡，单条巨头只能独占一片 |
| 前缀重复 | `new_title` 里别自己加 `[分类]`，交给 `category` 字段 |

## 六、实测数据参考

27 条任务、完整历史合计 409 KB / 约 41 万字，`--shards 6` 后每片 30–92 KB，6 个子智能体并行，端到端约 1 分钟。
其中最长一条 169 消息 / 57 轮 / 9.1 万字，独占一片。
