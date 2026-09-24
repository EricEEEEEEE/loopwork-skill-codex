#!/usr/bin/env python3
"""围栏 · Codex PreToolUse 守卫——薄适配层（判定住在 guard_rules.py，两版共享）。

0.153.4 实测的 payload 形状（VERIFICATION.md · P0-4）：
  tool_name == "Bash"        → tool_input["command"] 是 shell 命令原文
  tool_name == "apply_patch" → tool_input["command"] 是补丁全文，落点写在
                               `*** Add File: / Update File: / Delete File: / Move to:` 行
两者的 tool_input 都只有 command 一个键——没有 file_path，别照搬 CC 版的记忆去找。

命中 → exit 2 + stderr 白话理由（0.153.4 实测拦得住：日志出现 `hook: PreToolUse Blocked`，
考题文件原样保留）。没见过的 tool_name → 放行，但记一行 tools_seen.jsonl（不进 blocks.jsonl：
放行不是拦截，不该把轮末「本轮被拦 N 次」和进度卡累计数撑大）：Codex 加新工具时
要看得见，而不是某天才发现围栏对它一直是瞎的。
项目外 / 内部异常 → 放行（fail-open：围栏自身故障不砖会话）。

这是第二道，不是唯一一道。信任门没接通时项目级钩子整体不加载——那时守阵地的是
OS 沙箱边界（第一道）和轮末检测门 stop_hook.py（第三道）。三道各自能独立成立。
"""
import json, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import guard_rules
except Exception:  # 共享库不在（旧项目没重跑 init）——放行但吭一声，别默默变纸老虎
    guard_rules = None
try:
    import guard_log
except Exception:
    guard_log = None

# Codex 专属的接线文件：改它们等于把围栏拆了。平台差异不进共享规则。
EXTRA_PROTECTED = [".codex/hooks.json", ".codex/rules", ".codex/agents"]

# 工具名归一（实测是 Bash / apply_patch；沙箱 PATH 里两个补丁壳都装着，别名一并认）
TOOL_BASH = ("bash", "shell")
TOOL_PATCH = ("apply_patch", "applypatch")

# 补丁落点行：`*** Update File: tests/exam.py` / `*** Move to: src/x.py`
PATCH_PATH = re.compile(r"^\*\*\*\s+(?:Add File|Update File|Delete File|Move to):\s*(.+?)\s*$", re.M)


def patch_targets(patch, base):
    """取出补丁正文里的所有落点，归一成绝对路径（补丁里的相对路径以 cwd 为准）。"""
    out = []
    for raw in PATCH_PATH.findall(patch or ""):
        p = raw.strip().strip('"').strip("'")
        if p:
            out.append(p if os.path.isabs(p) else os.path.join(base, p))
    return out


def block(root, tool, target, phase, verdict):
    """命中就记一笔取证账、把白话理由喂回模型，然后 exit 2。"""
    if not verdict:
        return 0
    if guard_log is not None:
        guard_log.record(root, tool=tool, target=target, rule=verdict[0], phase=phase)
    print(f"[围栏] {verdict[1]}", file=sys.stderr)
    return 2


def patch_scan(root, tool, patch, base, phase, in_project):
    """补丁正文里的每一个落点都过一遍编辑判定，命中第一个就拦。"""
    if not in_project:
        return 0
    infra = []
    for ap in patch_targets(patch, base):
        rel = os.path.relpath(os.path.realpath(ap), os.path.realpath(root))
        verdict = guard_rules.check_edit(rel, phase=phase, extra_protected=EXTRA_PROTECTED)
        if verdict:
            return block(root, tool, rel, phase, verdict)
        if str(phase) == "implementing" and guard_rules.tests_infra_ok(rel):
            infra.append(rel)
    if guard_log is not None:
        for rel in infra:    # 整个补丁都放行了才留痕：被拦的补丁一处都没落地
            guard_log.allowed(root, tool=tool, target=rel, rule="tests-infra", phase=phase)
    return 0


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0
    if guard_rules is None:
        print("[围栏] ⚠️ 判定核心 guard_rules.py 不在 .loopwork/hooks/，本次未做检查。"
              "请重跑 init_project.sh 补齐围栏。", file=sys.stderr)
        return 0
    try:
        start = payload.get("cwd") or os.getcwd()
        root = (guard_log.find_root(start, script=__file__, env_keys=()) if guard_log is not None
                else start)
        base = payload.get("cwd") or root   # 补丁里的相对路径以会话 cwd 为准，不是项目根
        state_p = os.path.join(root, ".loopwork", "state.json")
        phase, in_project = "", os.path.exists(state_p)
        if in_project:
            with open(state_p, encoding="utf-8") as f:
                phase = str(json.load(f).get("phase", ""))
        tool = str(payload.get("tool_name") or "")
        ti = payload.get("tool_input") or {}
        cmd = ti.get("command") or ""
        low = tool.casefold()

        if low in TOOL_BASH:
            verdict = guard_rules.check_bash(cmd, phase=phase, in_project=in_project,
                                             extra_protected=EXTRA_PROTECTED)
            if verdict:
                return block(root, tool, cmd, phase, verdict)
            # `apply_patch <<'EOF' … EOF` 也能从 shell 走：落点不在命令行上，而在 heredoc
            # 正文里——沙箱 PATH 里就装着 apply_patch 壳，这条绕道是真的，得一起扫。
            rc = patch_scan(root, tool, cmd, base, phase, in_project)
            if rc == 0 and guard_log is not None and guard_rules.infra_passes(
                    cmd, phase=phase, in_project=in_project, extra_protected=EXTRA_PROTECTED):
                guard_log.allowed(root, tool=tool, target=cmd, rule="tests-infra", phase=phase)   # 放行也留痕
            return rc
        if low in TOOL_PATCH:
            return patch_scan(root, tool, cmd, base, phase, in_project)

        # 没见过的工具：放行，但留痕（tools_seen.jsonl，不是 blocks.jsonl——放行不算撞墙）。
        # 记下它带了哪些键，下次升级围栏时照着补。
        if in_project and guard_log is not None:
            keys = ",".join(sorted(str(k) for k in ti))
            guard_log.seen(root, tool=tool, target=(cmd or f"keys={keys}"), phase=phase)
        return 0
    except Exception:
        return 0  # 围栏自身故障不砖会话


if __name__ == "__main__":
    sys.exit(main())
