# 实测记录（VERIFICATION.md）

> 本文件记录 Codex 版围栏架构的每一条事实依据与实测结果。Codex 迭代极快（alpha 通道日更），
> 这里的结论标注了验证日期与版本——**装机后请跑 `bash skills/loopwork/scripts/selftest.sh` 用你自己的版本重测**。

## 实测环境

- 日期：2026-07-21
- 二进制：codex-cli **0.145.0-alpha.27**（ChatGPT.app 捆绑，alpha 自动更新通道）
- 平台：macOS（Seatbelt 沙箱）

## 七项实测结论

| # | 项目 | 结论 | 证据 |
|---|---|---|---|
| 1 | 版本与通道 | App 捆绑版走 alpha 通道日更（当天从 alpha.18 自更到 alpha.27） | `codex --version` |
| 2 | skills 扫描路径 | `~/.codex/skills` 实际生效（本机已装 skill 均在此且可用）；`~/.agents/skills`（新开放标准路径）本机不存在。**安装建议双写两路径** | 本机目录 + 官方文档对旧路径保持沉默 |
| 3 | 具名 Permission Profile（子路径只读） | **本版本不可用：配置后二进制直接 SIGABRT（exit 134），连 `echo hi` 都无法执行**。文档 schema 与 alpha 实现不同步 → 围栏采用降级架构（见 README） | `CODEX_HOME=<隔离配置> codex sandbox -- bash -c 'echo hi'` → exit 134 |
| 4 | 工作区边界（旧体系 workspace-write） | **OS 级强制有效**：工作区内写 OK；工作区外写被 Seatbelt 拒绝（"Operation not permitted"） | `codex sandbox` 实测 T1/T2 |
| 5 | Stop hook（检测门/挂机档载体） | `codex exec` 非交互下**未观察到触发**（单轮即止，探针 flag 未写入）。原因未定：项目信任机制 / exec 生命周期 / schema 差异。**首次使用需在交互会话验证接通**（剧本已写入验证步骤） | 自解除探针 + `--json` 事件流：仅 1 次 turn.completed |
| 6 | hook-deny 拦截力（上游 issue #27833） | 未直接复现（受 #5 制约）；上游 issue 截至 07-21 仍 open、无修复 PR。**架构不依赖 hook-deny**（仅审计） | github.com/openai/codex/issues/27833 |
| 7 | `multi_agent` / `goals` 默认状态 | 官方配置参考页均标 "stable; on by default"（07-21 复核）；本机未独立验证 | learn.chatgpt.com/docs/config-file/config-reference |

## 由此决定的围栏架构（降级版，诚实标注）

```
硬（OS 级）   工作区边界：项目外物理不可写（实测 #4 证实）
硬（规则层）  rm -rf 族 / git push --force / chmod 777 → forbidden；sed -i → prompt
硬（数据层）  基线锚定：每轮存档 hash 记入 state，改历史必被发现
软→硬（检测门）Stop 钩子每轮快检：实现期碰考题/规格 → 顶回强制撤销+解释
              （接通依赖项目信任，首跑验证；未接通时模型侧铁律 + 审计日志兜底）
审计          PostToolUse 全量日志 .loopwork/logs/audit.jsonl
```

**升级路径**（selftest 持续探测，条件满足即可启用）：
- Permission Profile schema 在稳定版可用后 → `tests/` 实现期只读升级为 OS 级（selftest 第 4 项变 ✅ 即可配）；
- 上游 #27833 修复后 → PreToolUse deny 升级为第四道防线。

## 与 Claude Code 版的机制差异（同样写在 README）

CC 版：动手瞬间物理拦截（PreToolUse 钩子实测可拦 + Bash 层等价拦截）。
Codex 版：边界物理墙 + 危险命令禁令 + 事后必然败露强制回滚。
对小白的实际保护等级相当；机制不同，不假装等价。
