# Loopwork Skill · Codex Edition

![status](https://img.shields.io/badge/status-beta-orange) ![license](https://img.shields.io/badge/license-MIT-blue) ![codex](https://img.shields.io/badge/OpenAI_Codex-%E2%89%A5_0.144-10a37f) ![lang](https://img.shields.io/badge/%E4%B8%AD%E6%96%87-first-red)

**A drop-in OpenAI Codex skill that turns a complete beginner's idea into working, continuously-evolving software — through a guided loop workflow.**

一个放进 Codex 就能用的引导型 skill：不会编程的人说出一个想法，它以向导身份带他走完「访谈 → 白话规格 → 批准计划 → 自主循环开发 → 亲手验收」的全过程，然后把项目装进永续循环——**你出方向，AI 跑圈，项目不是做完的，是转起来的。**

> 🔵 **Claude Code 用户**：请用姊妹版 [loopwork-skill-claude-code](https://github.com/EricEEEEEEE/loopwork-skill-claude-code)。两版方法论同源，围栏按各自平台原生机制实现。

## 🇨🇳 中文快速上手（3 分钟）

**第 1 步 · 下载**：点本页绿色 **Code** 按钮 → **Download ZIP** → 解压。（会 git：`git clone https://github.com/EricEEEEEEE/loopwork-skill-codex.git`）

**第 2 步 · 安装**：把 **`skills/loopwork` 文件夹**放进（两个位置都放，兼容新旧版本）：

- `~/.codex/skills/loopwork`
- `~/.agents/skills/loopwork`

命令行一步到位：

```bash
git clone https://github.com/EricEEEEEEE/loopwork-skill-codex.git /tmp/lwc \
  && mkdir -p ~/.codex/skills ~/.agents/skills \
  && cp -R /tmp/lwc/skills/loopwork ~/.codex/skills/ \
  && cp -R /tmp/lwc/skills/loopwork ~/.agents/skills/
```

在 Codex 会话里也可以直接说：`$skill-installer https://github.com/EricEEEEEEE/loopwork-skill-codex`

**第 3 步 · 开口**：打开 Codex（ChatGPT 桌面 App 的 Codex 入口，或终端 `codex`），直接说：

> 我想做一个记账工具，但我不会编程

显式调用：`$loopwork`（注意是 `$` 不是 `/`——Codex 的规矩），或从 `/skills` 列表选中。装完建议跑一次 30 秒自检：`bash ~/.codex/skills/loopwork/scripts/selftest.sh`

你全程只做三件事：**回答问题、看结果、点批准**。中途随时关掉，回来说「继续」就能接上。

## How it works（两个半场）

```
上半场 · 首航（直线，走一次）
0 开场体检 → 1 想法访谈 → 2 白话规格+项目规矩 → 3 摊开计划(你批准)
→ 4 循环执行 ⟲ → 5 验收(照单点一遍) → 6 收尾 → 进环仪式

下半场 · 循环模式（圆环，转无限次）
点火(30秒) → AI 跑批(挂机) → 收货(3-10分钟) → 续单(5分钟) → 再点火…
```

## What's inside

```
skills/loopwork/
├── SKILL.md               # 向导本体：铁律 + 点火路由 + 内循环引擎
├── agents/openai.yaml     # 隐式触发开关
├── references/            # 7 阶段剧本 + 循环模式 + 快速通道 + 白话词典 + 判卷员指令
└── scripts/
    ├── init_project.sh    # 建家：git + 状态机 + Codex 钩子/规则/只读判卷员/AGENTS.md 锚点
    ├── verify.sh          # 验收裁判：exit code 说了算（fail closed）
    ├── progress.py        # 状态机 + 进度卡（SessionStart 自动播报 + 存档对账警告）
    ├── stop_hook.py       # 检测门 + 挂机档（基线锚定 / 相位纪律 / 批次外部计数）
    ├── audit_log.py       # PostToolUse 全量审计日志
    └── selftest.sh        # 装机自检：30 秒探明你这台机器的围栏能力面
```

## Discipline, honestly（纪律与诚实）

Codex 的 hook-deny 拦截当前存在已知上游缺陷（[openai/codex#27833](https://github.com/openai/codex/issues/27833)），所以本版**不把 hooks 当拦截点**，围栏这样排：

- **OS 级物理墙**：工作区外不可写（Seatbelt 实测证实，见 [VERIFICATION.md](VERIFICATION.md)）
- **规则禁令**：`rm -rf` 族 / force push / `chmod 777` 直接 forbidden（项目级 Starlark 规则）
- **基线锚定 + 检测门**：每轮存档 hash 入账；实现期碰考题/规格 → 轮末被顶回强制撤销并解释——**事后必然败露，改历史也会被发现**
- **只读判卷员**：`sandbox_mode="read-only"` 的原生子代理，系统层保证只看不改
- **外部计数**：批次/轮数上限由脚本数，不靠模型自数；验收只认 `verify.sh` 的 exit code（fail closed）

与 Claude Code 版的差异：CC 是「动手瞬间物理拦截」，Codex 是「边界物理墙 + 事后必然败露强制回滚」。保护等级相当，机制不同——每条差异的实测依据都在 [VERIFICATION.md](VERIFICATION.md)。

## Status

**v1 built; 40-case machine regression green（`python3 tests/test_codex_machines.py` 可复跑）; Stop-hook 接通与真实小白field test 待首跑验证（步骤已写进剧本）。** Codex alpha 通道日更，装机后请跑 selftest 以你的版本为准。Treat as beta.

## License

MIT — see [LICENSE](LICENSE).
