#!/usr/bin/env python3
"""Loopwork Codex 版 · Stop 钩子（检测门 + 挂机批模式，合一）。

顺序：
1. 检测门（快检，永远执行）：
   a. 基线锚定：state.last_round_commit 必须仍在 git 历史中可达（防 amend/rebase 假历史）；
   b. 相位纪律：phase==implementing 时，受保护文件（tests/ spec.md rules.md）分两段核对——
      未存档改动（工作区/未跟踪）→ 顶回要求撤销；
      已存档改动（基线..HEAD）→ 多半是红考题存档后忘了推进基线（协议：存档即推进基线，
      见 SKILL.md 铁律 8），顶回教它补 progress.py set last_round_commit。
   违规 → decision:"block"，reason=处置指令（Codex 会把 reason 当下一轮输入续跑）。
2. 挂机批模式（.loopwork/batch.flag 存在时）：外部计数——批中顶回 / 满批强制验收 /
   只剩受阻任务转清问题本 / 轮数上限安全停机 / 连续 MAX_STALLS 次顶回轮数没涨 →
   判定原地打转自动停批（flag 存 "起点,上次顶回轮数,无进展次数"，兼容旧格式）。
非 loopwork 项目 / git 异常 / 内部异常：放行（fail-open，不砖会话）。
输出协议：阻断用 stdout JSON {"decision":"block","reason":...}；放行 exit 0 无输出。
"""
import json, os, subprocess, sys

MAX_STALLS = 2  # 连续 N 次顶回轮数未涨 → 判定打转，自动停批

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

def protected(lines):
    return [l for l in lines if l.startswith("tests/") or l in ("spec.md", "rules.md")]

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
                code, out = sh(["git", "diff", "--name-only", "HEAD"], root)
                code2, out2 = sh(["git", "ls-files", "--others", "--exclude-standard"], root)
                live = protected((out.splitlines() if code == 0 else []) +
                                 (out2.splitlines() if code2 == 0 else []))
                if live:
                    return block(
                        "[检测门] 实现期有未存档的受保护文件改动：" + ", ".join(live[:5]) +
                        "。考题先红后绿，实现期间不许碰考题/规格/规矩。立即：①撤销"
                        "（已跟踪文件 git checkout -- <文件>；新建文件直接删除）"
                        "②在 JOURNAL.md 记一行原因 ③向用户说明。"
                    )
                if baseline:
                    code3, out3 = sh(["git", "diff", "--name-only", baseline, "HEAD"], root)
                    committed = protected(out3.splitlines() if code3 == 0 else [])
                    if committed:
                        return block(
                            "[检测门] 基线之后有已存档的受保护文件改动：" + ", ".join(committed[:5]) +
                            "。若这是你刚存档的红考题——只是忘了推进基线，立即执行 "
                            "python3 .loopwork/hooks/progress.py set last_round_commit "
                            "$(git rev-parse HEAD)（存档即推进基线）；若是实现期偷改后存档的——"
                            "revert 该存档、JOURNAL.md 记一行原因并向用户坦白。"
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

        # flag 格式："起点,上次顶回轮数,无进展次数"（兼容旧版两段/纯数字）
        raw = ""
        try:
            raw = open(flag, encoding="utf-8").read().strip()
        except Exception:
            pass
        parts = raw.split(",") if raw else []

        def num(i, default=None):
            return int(parts[i]) if len(parts) > i and parts[i].lstrip("-").isdigit() else default

        start = num(0)
        last_nag = num(1)
        stalls = num(2, 0)
        if start is None:
            start = rounds

        def write_flag(nag, stall_n):
            with open(flag, "w", encoding="utf-8") as f:
                f.write(f"{start},{nag},{stall_n}")

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
            stalls += 1
            if stalls >= MAX_STALLS:
                return finish(
                    f"[挂机档] 连续 {MAX_STALLS} 次顶回轮数都没涨（仍是第 {rounds} 轮），判定原地打转，自动停批。"
                    "请按停批汇报格式向用户汇总：完成了什么、卡在哪、问题本新增了什么。"
                )
            write_flag(rounds, stalls)
            return block(
                f"[挂机档] 顶回后轮数没涨（仍是第 {rounds} 轮）——若卡在同一任务：按失败分级处理（3 次转诊断），"
                "或写 BLOCKED.md 跳过取下一条。再次无进展将自动停批。"
            )
        write_flag(rounds, 0)
        return block(
            f"[挂机档] 批模式进行中：本批 {rounds - start}/{batch_size} 条，剩余可做 {actionable} 条"
            f"（总轮数 {rounds}/{cap}）。按内循环节奏继续取下一条任务。用户喊停 = 删除 .loopwork/batch.flag。"
        )
    except Exception:
        return 0

if __name__ == "__main__":
    sys.exit(main())
