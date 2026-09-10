# Loopwork Skill · Codex Edition

![version](https://img.shields.io/badge/version-2.0-blue) ![status](https://img.shields.io/badge/status-beta-orange) ![license](https://img.shields.io/badge/license-MIT-blue) ![codex](https://img.shields.io/badge/OpenAI_Codex-%E2%89%A5_0.153-10a37f) ![lang](https://img.shields.io/badge/%E4%B8%AD%E6%96%87-first-red)

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
    ├── progress.py        # 状态机 + 进度卡 + 存档登记（与 CC 版字节相同）
    ├── guard_rules.py     # 围栏规则内核：纯函数、无 I/O（与 CC 版字节相同）
    ├── guard_pre.py       # PreToolUse 实时围栏：Bash 命令 + apply_patch 补丁落点
    ├── guard_log.py       # 拦截取证：blocks.jsonl（只增不减）
    ├── stop_hook.py       # 检测门 + 代存档 + 挂机档（基线锚定 / 相位纪律 / 外部计数）
    ├── audit_log.py       # PostToolUse 全量审计日志
    └── selftest.sh        # 装机自检：30 秒探明你这台机器的围栏能力面
```

## Discipline, honestly（纪律与诚实）

围栏三层，外加一条「存档由围栏代落」。每一条都有实测依据，逐条列在 [VERIFICATION.md](VERIFICATION.md)（2026-09-10 / codex-cli 0.153.4）：

- **第一层 · OS 物理墙**：工作区外不可写，**`.git` 对模型也不可写**（Seatbelt 实测）。改不动历史，就伪造不了证据；
- **第二层 · 实时围栏（PreToolUse）**：动手那一刻拦。`guard_pre.py` 既看 Bash 命令，也看 `apply_patch` 补丁正文里的落点——0.153.4 实测拦得住（日志出现 `hook: PreToolUse Blocked`，目标文件原样保留）。⚠️ 项目级钩子要**先信任本项目**才加载，未信任时静默不跑（实战最常见的失效点，selftest 第 5 项专门探它）；
- **第三层 · 检测门（Stop 钩子）**：每轮收尾快检——基线锚定对账 + 实现期碰考题/规格即被顶回 + JOURNAL 与审计账本只增不减。**顶回自带刹车**：Codex 平台不给顶回设上限（实测连续 12 次全部生效），所以围栏自己数到 7 就放行交还用户；
- **代存档**：模型跑在沙箱里写不了 `.git`，钩子跑在沙箱外可以——所以模型只**登记**存档意图（`progress.py commit red|green|note`），钩子核验后才落 commit：密钥筛查 / red 只许考题 / green 要红票 + `verify.sh` 全绿 / note 不许夹带考题。**存档不是「AI 说存了」，是「围栏验过才算」**；
- **规则禁令**：`rm -rf` 族 / force push / `chmod 777` / 改历史与销毁证据一族（`amend`/`rebase`/`filter-branch`/`stash`/`clean`）直接 forbidden（项目级 Starlark 规则）；
- **只读判卷员**：`sandbox_mode="read-only"` 的原生子代理，系统层保证只看不改；
- **外部计数**：批次/轮数上限由脚本数，不靠模型自数；验收只认 `verify.sh` 的 exit code（fail closed）。

与 Claude Code 版的差异：两版都是三层围栏，**围栏规则是同一份源码**（`guard_rules.py` 两版字节相同）。CC 靠钩子覆盖面，Codex 多一层 OS 物理墙、少一层平台顶回上限、存档改由钩子代落。保护等级相当，接线方式不同——差异表在 [VERIFICATION.md](VERIFICATION.md) 末尾。

## 诚实的能力边界（围栏拦不住什么）

围栏是**减少偶然违规**的工程装置，不是**对抗蓄意规避**的安全边界。一个想绕的模型（或一个想绕的你）总有路。把缝摊开说清楚，比假装没有更有用：

- **命令行匹配面永远有缝**。`guard_pre.py` 读的是命令文本，所以解释器一行程序（`python3 -c "open('tests/a.py','w')…"`）、变量间接（`X=tests; sed -i "" … $X/a.py`）、以及各种拼接写法都可能不命中。**这正是第三层检测门存在的理由**：绕过实时围栏改了考题，轮末基线对账照样把它翻出来——两层的缝不重合，才是覆盖面。
- **项目未被信任 = 第二、三层整体不加载，且不报错**。这是本版最危险的静默失效点：你以为围栏在，其实只剩 OS 沙箱。**首次使用必须盯着看一轮**，轮末出现「[挂机档] …」才算接通（VERIFICATION.md 实测 #7）。
- **用户自己终端里敲的命令不经过围栏**。这是特性不是缺陷：关批的开关只在你手上（`rm .loopwork/batch.flag`），模型删不掉。反过来说，你在自己终端里做的任何事，围栏一概不知情。
- **版本漂移**。Codex alpha 通道日更，钩子字段形状、沙箱行为、信任门语义都可能变。VERIFICATION.md 里每条结论都带日期和版本号，**装机后请跑 `selftest.sh` 以你自己的版本为准**——本仓库的实测是 2026-09-10 / 0.153.4 那一天的事实，不是永久承诺。
- **姊妹版有一条对称的坑**：Claude Code 版的检测门依赖平台顶回，而 `CLAUDE_CODE_STOP_HOOK_BLOCK_CAP=0` 能把顶回整个关掉。两版的静默失效点不同，但都存在。

## 围栏管不到的地方：第三方 skill 是供应链（这一个也是）

围栏管的是**我**（模型）在这个项目里能干什么。它管不了**你装了什么**。

- **skill / MCP server / 钩子 = 每轮自动执行的代码，权限和 AI 一样大**——Codex 版的钩子还跑在沙箱外，比模型权限更大。装之前读一遍，尤其是 `scripts/` 里的东西。loopwork 自己也不例外：它的每个脚本都在这个仓库里摊开，`init_project.sh` 往你项目里写哪几个文件，上面 What's inside 一节列得清清楚楚。
- **别让 AI 替你挑安装来源。** 2026 年 7 月 Island 的实测（[CSA AI Safety Initiative 研究简报](https://labs.cloudsecurityalliance.org/research/csa-research-note-fakegit-agentbaiting-mcp-supply-chain-2026/)）：约 7,600 个伪装仓库、约 6,600 个假开发者账号，其中 800+ 直接伪装成 AI Skill / MCP server，在 LobeHub / Glama / MCP.so / MCP Market 等公开目录挂了 600+ 条，Release 附件累计下载 1,400 万+。这套打法（AgentBaiting）不骗人点链接，它骗 **AI 去发现仓库**、把攻击者写的 README 当成正经文档、再由 AI 把安装指引转达给你——你面对的问题从「要不要点这个陌生链接」变成「要不要照我的 AI 刚给的指引做」。载荷是 SmartLoader → StealC（浏览器凭据 / cookie / token / SSH 密钥 / 截图）。
- **「不再询问」是按动作类别记的，不是按这一次记的。** 学术侧在 Claude Code 上复现过：为一次正常操作点下的 "Yes, and don't ask again"，让之后一条恶意脚本无需再确认就跑了起来（[arXiv:2510.26328](https://arxiv.org/abs/2510.26328)）。凡是带「记住我的选择」的权限框都该按这个心态对待——这个勾只对你真的放心的类别点。

Stage 0 的体检会把这几条讲给用户，并报出「这个项目里除了 loopwork 还挂着谁」。

## Status

**v2.0；105-case machine regression green（`python3 tests/test_codex_machines.py` 可复跑）；Stop 钩子接通、代存档、挂机批与优雅停批已在真项目上跑通一整轮**（记录见 [VERIFICATION.md](VERIFICATION.md) 「真项目跑通记录 · 2026-09-11」）。真实小白 field test 仍待首跑。Codex alpha 通道日更，装机后请跑 selftest 以你的版本为准。Treat as beta.

## License

MIT — see [LICENSE](LICENSE).
