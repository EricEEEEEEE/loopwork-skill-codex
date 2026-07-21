#!/usr/bin/env python3
"""Loopwork Codex 版 · Stop 钩子（检测门 + 挂机批模式，合一）。

顺序：
1. 检测门（快检，永远执行）：
   a. 基线锚定：state.last_round_commit 必须仍在 git 历史中可达（防 amend/rebase 假历史）；
   b. 相位纪律：phase==implementing 时，自基线以来的改动不得触碰 tests/ spec.md rules.md；
   违规 → decision:"block"，reason=撤销与解释指令（Codex 会把 reason 当下一轮输入续跑）。
2. 挂机批模式（.loopwork/batch.flag 存在时）：外部计数——批中顶回 / 满批强制验收 /
   只剩受阻任务转清问题本 / 轮数上限安全停机 / 防原地打转（轮数没涨不重复顶）。
非 loopwork 项目 / git 异常 / 内部异常：放行（fail-open，不砖会话）。
输出协议：阻断用 stdout JSON {"decision":"block","reason":...}；放行 exit 0 无输出。
"""
import json, os, subprocess, sys

def sh(args, cwd):
    try:
        p = subprocess.run(args, cwd=cwd, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=20)
        return p.returncode, p.stdout.strip()
    except Exception:
        return 1, ""

def block(reason):
    print(json.dumps({"decision": "block", "reason": reason}, ensure_ascii=False))
    return 0  # Codex 协议：决定放 stdout JSON，退出码 0

def main():
    try:
        payload = {}
        try:
            payload = json.load(sys.stdin)
        except Exception:
            pass
        root = os.environ.get("CODEX_PROJECT_DIR") or payload.get("cwd") or os.getcwd()
        state_p = os.path.join(root, ".loopwork", "state.json")
        if not os.path.exists(state_p):
            return 0
        with open(state_p, encoding="utf-8") as f:
            st = json.load(f)

        # ---------- 1. 检测门 ----------
        stage = str(st.get("stage", ""))
        phase = str(st.get("phase", ""))
        baseline = str(st.get("last_round_commit", "") or "")
        if stage in ("4", "loop", "quick") and os.path.isdir(os.path.join(root, ".git")):
            if baseline:
                code, _ = sh(["git", "merge-base", "--is-ancestor", baseline, "HEAD"], root)
                if code != 0:
                    return block(
                        "[检测门] 基线存档 " + baseline[:10] + " 在当前 git 历史中不可达——"
                        "历史可能被改写（amend/rebase）。停止一切实现工作：先向用户如实报告，"
                        "恢复历史或经用户同意后用 progress.py set last_round_commit 重设基线。"
                    )
            if phase == "implementing":
                ref = baseline if baseline else "HEAD"
                code, out = sh(["git", "diff", "--name-only", ref], root)
                code2, out2 = sh(["git", "ls-files", "--others", "--exclude-standard"], root)
                if code == 0:
                    changed = out.splitlines() + (out2.splitlines() if code2 == 0 else [])
                    touched = [l for l in changed
                               if l.startswith("tests/") or l in ("spec.md", "rules.md")]
                    if touched:
                        return block(
                            "[检测门] 实现期改动了受保护文件：" + ", ".join(touched[:5]) +
                            "。考题先红后绿，实现期间不许碰考题/规格/规矩。立即：①撤销这些文件的改动"
                            "（git checkout -- <文件>）②在 JOURNAL.md 记一行原因 ③向用户说明。"
                        )

        # ---------- 2. 挂机批模式 ----------
        flag = os.path.join(root, ".loopwork", "batch.flag")
        if not os.path.exists(flag):
            return 0
        cap = int(st.get("round_cap", 20))
        batch_size = int(st.get("batch_size", 5))
        rounds = int(st.get("round_count", 0))
        actionable = blocked = 0
        try:
            with open(os.path.join(root, "tasks.md"), encoding="utf-8") as f:
                for line in f:
                    s = line.strip()
                    if s.startswith("- [ ]"):
                        blocked += 1 if "〔卡" in s else 0
                        actionable += 0 if "〔卡" in s else 1
        except FileNotFoundError:
            pass

        raw = ""
        try:
            raw = open(flag, encoding="utf-8").read().strip()
        except Exception:
            pass
        parts = raw.split(",") if raw else []
        start = int(parts[0]) if parts and parts[0].lstrip("-").isdigit() else None
        last_nag = int(parts[1]) if len(parts) > 1 and parts[1].lstrip("-").isdigit() else None
        if start is None:
            start = rounds
        def write_flag(nag):
            with open(flag, "w", encoding="utf-8") as f:
                f.write(f"{start},{nag}")
        def finish(msg):
            try:
                os.remove(flag)
            except OSError:
                pass
            return block(msg)

        if actionable <= 0 and blocked <= 0:
            try:
                os.remove(flag)
            except OSError:
                pass
            return 0
        if actionable <= 0:
            return finish(f"[挂机档] 只剩 {blocked} 条受阻任务。汇总本批结果，把问题本（BLOCKED.md）提请用户拍板。")
        if rounds >= cap:
            return finish(f"[挂机档] 轮数达上限 {cap}，安全停机。汇总本批并请用户验收。")
        if rounds - start >= batch_size:
            return finish(f"[挂机档] 本批已做满 {batch_size} 条（外部计数）。按纪律进验收环节，不许跳过检查点。")
        if last_nag is not None and rounds == last_nag:
            # 防原地打转：上次顶回后轮数没涨，说明没进展，放行让它正常汇报
            try:
                os.remove(flag)
            except OSError:
                pass
            return 0
        write_flag(rounds)
        return block(
            f"[挂机档] 批模式进行中：本批 {rounds - start}/{batch_size} 条，剩余可做 {actionable} 条"
            f"（总轮数 {rounds}/{cap}）。按内循环节奏继续取下一条任务。用户喊停 = 删除 .loopwork/batch.flag。"
        )
    except Exception:
        return 0

if __name__ == "__main__":
    sys.exit(main())
