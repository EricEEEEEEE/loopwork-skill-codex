# 实测记录（VERIFICATION.md）

> 本文件记录 Codex 版围栏架构的每一条事实依据与实测结果。Codex 迭代极快（alpha 通道日更），
> 这里的结论标注了验证日期与版本——**装机后请跑 `bash skills/loopwork/scripts/selftest.sh` 用你自己的版本重测**。
> 历史结论一律保留（往下翻），不删不改：删掉的实测记录等于没做过实测。

## 当前实测环境

- 日期：**2026-09-10**（复核：**2026-09-24** / codex-cli 0.155.0-alpha.16，见「2026-09-24 复核」一节）
- 二进制：codex-cli **0.153.4**（`/Applications/ChatGPT.app/Contents/Resources/codex`，alpha 自动更新通道）
- 平台：macOS（Seatbelt 沙箱）

## 八条实测结论（0.153.4）

| # | 项目 | 结论 | 证据 |
|---|---|---|---|
| 1 | **PreToolUse 拦截力** | **有效**。钩子 `exit 2` + stderr 理由 → 命令被拒绝执行，目标文件原样未动 | 实现期改考题探针：日志 `error=Command blocked by PreToolUse hook: [考题锁] 实现期禁止改考题 tests/exam.py` + `hook: PreToolUse Blocked`；事后核对考题内容仍是 `assert True`（未被改写），钩子被调用 2 次 |
| 2 | **钩子跑在沙箱外** | **是**。模型 shell 处于 `workspace-write`（`.git` 拒写）时，钩子进程仍能写 `.git` | 钩子写入 `.git/HOOK_PROBE` 成功，同一会话里模型自己写 `.git` 被 Seatbelt 拒绝 |
| 3 | **钩子可以 commit** | **可以**。这是「代存档」架构成立的前提 | 钩子在模型 `.git` 无写权限的前提下创建了提交 `22e3801` |
| 4 | **Stop 钩子在 `codex exec` 下触发** | **触发**。07-21 的「未观察到触发」已过期，根因是信任门（见 #7），不是 exec 生命周期 | `--json` 事件流出现 Stop 钩子调用；payload 含 `stop_hook_active` |
| 5 | **Stop 的 `decision:block` 生效** | **生效**。顶回后模型确实回来继续，不是走过场 | `hook: Stop Blocked` → 模型回「收到顶回」→ 第二次放行收尾 |
| 6 | **PreToolUse payload 字段形状** | shell 命令：`tool_name="Bash"`；补丁：`tool_name="apply_patch"`。**两者 `tool_input` 都只有 `command` 一个键**——`apply_patch` 时它是补丁全文，落点写在 `*** Add File: / Update File: / Delete File: / Move to:` 行里，**没有 `file_path` 字段可读** | 直接打印 payload 实测；`guard_pre.py` 的 `PATCH_PATH` 正则即按此形状写 |
| 7 | **项目信任门** | **项目级 `.codex/` 的 hooks/rules 只在项目被 Codex 信任后才加载**；未信任 = 钩子层静默不跑，**不报任何错**。这是实战里最常见的静默失效点 | `~/.codex/config.toml` 当时有 10 个 trusted 项目，`loopwork` / `loopwork-codex` 都不在其中 |
| 8 | **没有连续顶回上限** | **没有**。连续 12 次 `decision:block` 全部生效，第 13 次是探针自己解除的。对照：Claude Code 有 `CLAUDE_CODE_STOP_HOOK_BLOCK_CAP`（默认 8）兜底 | 自增计数探针；因此 `MAX_BLOCKS=7` 是 Codex 版**唯一**的自停线，不是可选项 |

**#8 的意义值得单独说一句**：平台不替你踩刹车，意味着一个消不掉的违规能把会话永远钉在原地——顶回、再顶回、无限顶回。所以围栏必须自带刹车（`stop_hook.py` 的 `MAX_BLOCKS`），到数就放行并交还用户。

## 由此确定的围栏架构（三层 + 代存档）

```
第一层 OS 沙箱     工作区边界物理不可写（Seatbelt，实测 #2 反证）
                   .git 对模型也不可写 → 历史墙 + 代存档的前提
第二层 实时围栏    PreToolUse：动手瞬间拦（实测 #1）
                   guard_pre.py 看 Bash 命令，也看 apply_patch 补丁正文的落点（实测 #6）
                   ⚠️ 依赖项目信任（实测 #7）；未信任时退回第一 + 第三层
第三层 检测门      Stop 钩子轮末快检（实测 #4/#5）：基线对账 + 相位纪律 +
                   JOURNAL/审计只增不减；自带 MAX_BLOCKS=7 刹车（实测 #8）
代存档             同一个 Stop 钩子在沙箱外落 commit（实测 #3）：模型只登记意图
                   （progress.py commit red|green|note），钩子验过才落——
                   密钥筛查 / red 只许考题 / green 要红票 + verify 全绿 / note 不许夹带考题；
                   挑着收：红档只收 tests/ 与台账，根上其他新文件不自动入档，回执点名「未入档」
审计               PostToolUse 全量日志 .loopwork/logs/audit.jsonl（只增不减）+ 活体心跳 hook_heartbeat.json
                   拦截取证 blocks.jsonl / 未知工具 tools_seen.jsonl / 基建放行 allowed.jsonl / Interrupt 只记 interrupts.jsonl
```

**升级路径**（selftest 持续探测，条件满足即可启用）：
- 具名 Permission Profile（子路径只读）在 0.153.4 仍不可用——配置后二进制 SIGABRT（exit 134），连 `echo hi` 都跑不了。稳定版可用后，`tests/` 实现期只读可升级为 OS 级；
- `~/.agents/skills`（新开放标准路径）本机 2026-09-24 仍不存在；它是可选路径，安装说明保留双写，缺它不影响 `~/.codex/skills` 生效。

## 真项目跑通记录 · 2026-09-11（不是单元测试，是拿一个空目录从头做完一轮）

在一个临时项目（`行前缀计数器`，规格两句、任务两条）上，用**装出来的钩子**跑完整条流水线。
每一步的观察都在下表；这不替代 `tests/`，它证明的是「各部件接上电以后真的连成一条线」。

| 步骤 | 观察到的 | 结论 |
|---|---|---|
| `init_project.sh` | 状态机 + 钩子 + 台账 + 首次存档一次到位 | 建家可用 |
| Stage 1–3 存档 | `ecca3a0` 落档 | — |
| 红考题 → `commit red` | 钩子落档 `3953070`，**轮数仍 0**、基线推进到 HEAD、`pending_commit` 清空 | 代存档成立，红不计轮 |
| 实现期改 `tests/` | shell `sed -i` 与 `apply_patch` 两条路径都 `exit 2` 被拒 | 考题锁双路径有效 |
| 第一次 `verify.sh` | **`⚠️ unittest 发现 0 个测试（假绿），按不通过处理`** | 见下方「假绿抓了我一次」 |
| 改对考题重跑 | `Ran 2 tests` / 2 个 `ModuleNotFoundError` = 真红 | 红是真红 |
| 实现 → `commit green` | 钩子复跑 verify.sh、核对红票，落档 `67e521e`，**轮数 0→1**，基线推进 | 先红后绿闸在真项目生效 |
| `touch batch.flag` | 顶回 + `flag=1,1,0,1,2df406f41bca`（五段，末段 12 位进展指纹） | 挂机批接通 |
| 空转一轮 | 计数 `stalls=1` + 警告「轮数没涨…都没动」 | 第 1 次只警告 |
| 只往 `BLOCKED.md` 添一条 | 指纹 `2df406f4…`→`b48bcbe9…`，`stalls` 归 0 | **停滞判定认「四条同时成立」，不再把硬任务误判成打转** |
| T02 撞到规格缺口 | 标〔卡·B02〕入问题本 → 钩子判「只剩受阻任务」→ **自动摘 flag 停批** | 优雅停批路径通 |
| `commit note` | 落档 `1c1bf1c`，基线推进，不动轮数 | 第三种存档可用 |

**假绿抓了我一次（最有价值的一条）**：我把考题写成 pytest 风格的裸函数，而 `verify.sh` 跑的是
`python3 -m unittest discover`——收集到 0 个测试。它没有报「通过」，而是判**假绿 = 不通过**。
如果这道闸不在，这一轮会带着「0 个测试全过」的绿灯进历史。这不是演练，是真踩上了。

**T02 的规格缺口也是真的**：任务写「按计数降序打印（S1.1）」，但 S1.1 只规定 `tally()` 的返回值，
没有一句管 CLI 的输出格式。无验收句 = 考题只能靠猜——按纪律进问题本交用户拍板，没有硬写。

**一条已知的良性残留**：轮末落档后 `git status` 不干净，差异只有 `state.json` 里的
`last_round_commit`（指向刚生成的那一档）和被清空的 `pending_commit`。
**一个 commit 装不下自己的 hash**，这是设计固有的，两版对称（CC 版模型自己 `commit` 后再
`set last_round_commit` 是同一情形）。下一次存档会顺手带上，不作处理。

## 与 Claude Code 版的机制差异（同样写在 README）

两版都是三层围栏，接线方式不同：

| | Claude Code 版 | Codex 版 |
|---|---|---|
| 实时拦截 | PreToolUse 钩子（`guard_edits.py` / `guard_bash.py`） | PreToolUse 钩子（`guard_pre.py`），实测同样生效 |
| 物理边界 | 无 OS 沙箱，靠钩子覆盖面 | **多一层 Seatbelt**：工作区外、`.git` 对模型物理不可写 |
| 存档 | 模型自己 `git commit`（含 verify-stale 闸：改完没重判不许存） | **钩子代存档**：模型只登记，围栏验过才落，且挑着收（红档只收 tests/ 与台账） |
| 顶回刹车 | 平台 `CLAUDE_CODE_STOP_HOOK_BLOCK_CAP`（默认 8）+ 围栏 `MAX_BLOCKS=7` | **只有**围栏 `MAX_BLOCKS=7`（平台无上限，实测 #8） |
| 静默失效点 | 钩子未接通时 settings.json 双写兜底 | **项目未被信任时钩子层整体不加载**（实测 #7） |

围栏规则本身是同一份源码：`guard_rules.py` 两版字节相同（`cmp` 可验），`progress.py` 同理。
保护等级相当，不假装等价——差异逐条列在上表。

## 2026-09-24 复核

- 环境：macOS，python3 3.9.6，codex-cli 0.155.0-alpha.16；`~/.agents/skills` 本机仍不存在（可选路径）。
- 复核过的（本机可复跑）：
  - 机器回归 `python3 tests/test_codex_machines.py`：171/171 通过；
  - 本轮新增覆盖：五事件接线含 Interrupt A4、Interrupt 只记录不动作 U3a–U3c、测试基建放行 X1 / X1b / X4、取证账本 blocks + tools_seen P16 / P16b、心跳 U1a / U1c / U1d / U1f、init 变动 hooks.json 时提醒重新信任 A1b / A9d、技能库 .py 全部 3.9 可编译 A2b、selftest 记指纹 A2c、建家 .gitignore 含 .loopwork/scratch/ A2d；review 收尾新增：代存档不代收受保护文件 GH0–GH6（实现期考题/围栏脚本有改动 green 拒、note 不收并点名待撤销、red 不受理）、检测门放行测试基建 B7b / B7c（与实时围栏同一把尺）、目录白名单钉死 X7 / X8（cp 到 tests/fixtures/ 目录本身仍拦）；
  - 离线自检 `selftest.sh` 在临时项目上：10 项通过 / 1 项警告（唯一警告仍是具名 Permission Profile exit 134，与 09-10 相同）；hooks.json 指纹首跑记录、重跑判「没变」。
- 没重测的（结论沿用 2026-09-10 实测）：
  - 0.155 上 PreToolUse 实时拦截（自检第 [8] 项咬合联测未开 `--live`）；
  - 真会话里的 Interrupt 事件及其 1s 默认 / 3s 上限超时；
  - 上游 PR #47610（钩子从 `$SHELL -lc` 改为原生 spawn，预计 ≥ 0.156.1）落地后需重跑自检第 [9] 项。

---

# 历史记录（保留，不代表当前行为）

## 复核记录 · 2026-08-15

- 本机（开发机）当时无 codex CLI 可用，第 3/4/5/6 项无法原样复测——07-21 的结论保留为当日事实；
- 第 5 项（Stop hook 未触发）根因收敛到**项目信任门**：`.codex/` 项目级 hooks/rules 仅在项目被信任后加载，`codex exec` 的隔离探针项目大概率从未被信任过。**2026-09-10 已实测确认这条推断成立**（新表 #4/#7）；
- 第 6 项（#27833 hook-deny 缺陷）当时无法本机复现，架构按「不依赖 hook-deny」设计。**2026-09-10 实测推翻了这条前提**：0.153.4 的 PreToolUse 拦截确实有效（新表 #1），围栏因此升级为三层。

## 七项实测结论 · 2026-07-21（codex-cli 0.145.0-alpha.27）

| # | 项目 | 当日结论 | 现状 |
|---|---|---|---|
| 1 | 版本与通道 | App 捆绑版走 alpha 通道日更（当天从 alpha.18 自更到 alpha.27） | 仍然如此（今为 0.153.4） |
| 2 | skills 扫描路径 | `~/.codex/skills` 生效；`~/.agents/skills` 本机不存在。安装建议双写 | 未变 |
| 3 | 具名 Permission Profile | 不可用：配置后二进制 SIGABRT（exit 134） | 0.153.4 仍不可用 |
| 4 | 工作区边界（workspace-write） | OS 级强制有效：工作区外写被 Seatbelt 拒绝 | 未变（新表 #2 进一步测到 `.git` 也拒写） |
| 5 | Stop hook | `codex exec` 下未观察到触发 | **已过期**：根因是信任门，新表 #4 实测触发 |
| 6 | hook-deny 拦截力（上游 #27833） | 未直接复现；架构不依赖 hook-deny | **已过期**：新表 #1 实测有效 |
| 7 | `multi_agent` / `goals` 默认状态 | 官方配置页标 "stable; on by default"；本机未独立验证 | 未复测 |
