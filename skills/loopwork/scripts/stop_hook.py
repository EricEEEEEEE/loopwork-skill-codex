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
   判定原地打转自动停批（flag 存 "起点,上次顶回轮数,无进展次数,顶回总数"，兼容旧格式）。
3. 顶回总数上限 MAX_BLOCKS：顶回是「不让会话结束」，Codex 平台不给这件事设硬上限——
   实测连续 12 次顶回全部生效。所以这道刹车必须由围栏自己踩：累计到上限就优雅停机
   （摘 flag + 记 stop_blocks=-1，下一轮无条件放行一次，把会话真正交还给用户）。
   批模式记在 flag 第 4 段，非批模式记在 state.stop_blocks——与 CC 版同格式同上限。
非 loopwork 项目 / git 异常 / 内部异常：放行（fail-open，不砖会话）。
输出协议：阻断用 stdout JSON {"decision":"block","reason":...}；放行 exit 0 无输出。
"""
import json, os, subprocess, sys

MAX_STALLS = 2  # 连续 N 次顶回轮数未涨 → 判定打转，自动停批
MAX_BLOCKS = 7  # 顶回总数上限 → 优雅停机。与 CC 版同数，方便两版对照排障

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

def journal_deleted(root, revs):
    """JOURNAL.md 在这段区间里被删掉多少行（numstat 第二列）。读不到就当 0（fail-open）。"""
    code, out = sh(["git", "diff", "--numstat"] + revs + ["--", "JOURNAL.md"], root)
    cols = out.split() if code == 0 else []
    return int(cols[1]) if len(cols) >= 2 and cols[1].isdigit() else 0

def save_state(root, st):
    """写回 state.json（原子替换）。只有钩子走这条路——模型改状态一律用 progress.py。"""
    try:
        p = os.path.join(root, ".loopwork", "state.json")
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(st, f, ensure_ascii=False, indent=2)
        os.replace(tmp, p)
    except Exception:
        pass

def protected(lines):
    """受保护文件 = 考题/规格/规矩 + 围栏自己（改围栏脚本等于把围栏关掉，任何借口都不行）。"""
    return [l for l in lines
            if l.startswith("tests/") or l.startswith(".loopwork/hooks/")
            or l in ("spec.md", "rules.md")]

def gate_reason(root, st):
    """检测门：命中返回处置指令（原样交给模型当下一轮输入），干净返回 None。
    抽成函数是为了让「顶回」只有一个出口——顶回要记账，记账只能记一处。"""
    stage = str(st.get("stage", ""))
    phase = str(st.get("phase", ""))
    baseline = str(st.get("last_round_commit", "") or "")
    if stage in ("4", "loop", "quick") and os.path.isdir(os.path.join(root, ".git")):
        if baseline:
            code, _ = sh(["git", "merge-base", "--is-ancestor", baseline, "HEAD"], root)
            if code != 0:
                return (
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
                return (
                    "[检测门] 实现期有未存档的受保护文件改动：" + ", ".join(live[:5]) +
                    "。考题先红后绿，实现期间不许碰考题/规格/规矩；围栏脚本（.loopwork/hooks/）"
                    "任何时候都不许改。立即：①撤销"
                    "（已跟踪文件 git checkout -- <文件>；新建文件直接删除）"
                    "②在 JOURNAL.md 记一行原因 ③向用户说明。"
                )
            if baseline:
                code3, out3 = sh(["git", "diff", "--name-only", baseline, "HEAD"], root)
                committed = protected(out3.splitlines() if code3 == 0 else [])
                if committed:
                    return (
                        "[检测门] 基线之后有已存档的受保护文件改动：" + ", ".join(committed[:5]) +
                        "。若这是你刚存档的红考题——只是忘了推进基线，立即执行 "
                        "python3 .loopwork/hooks/progress.py set last_round_commit "
                        "$(git rev-parse HEAD)（存档即推进基线）；若是实现期偷改后存档的——"
                        "revert 该存档、JOURNAL.md 记一行原因并向用户坦白。"
                    )

        # 只增不减（一）：JOURNAL.md 是历史，删行 = 抹掉证据（无论哪个相位）。
        # 两段都要看：基线..HEAD 抓「改写后存了档」，HEAD..工作区 抓「还没存档的改写」。
        gone = journal_deleted(root, [baseline, "HEAD"]) if baseline else 0
        gone += journal_deleted(root, ["HEAD"])
        if gone > 0:
            return (
                f"[检测门] JOURNAL.md 少了 {gone} 行——日志只增不减，改写过的历史不是证据。"
                "立即 git checkout -- JOURNAL.md 还原（已存档的改写用 git revert 撤销），"
                '要记新内容用 python3 .loopwork/hooks/progress.py journal "…" 追加；'
                "若删除是用户要求的，停下来让用户自己动手。"
            )

    # 只增不减（二）：审计账本只能变长。
    # 变短 = 有人抹账。唯一合法的变短是单代轮转（老账本被顶成 .1）。
    # 抹账无法由模型补回，所以只响一次：报完把基准重置，避免死循环把会话钉死。
    audit = os.path.join(root, ".loopwork", "logs", "audit.jsonl")
    try:
        now_bytes = os.path.getsize(audit)
    except OSError:
        now_bytes = None
    if now_bytes is not None:
        mark = st.get("audit_bytes")
        mark = int(mark) if str(mark).isdigit() else None
        if mark is not None and now_bytes < mark:
            try:
                rotated = os.path.getsize(audit + ".1")
            except OSError:
                rotated = 0
            st["audit_bytes"] = now_bytes
            save_state(root, st)
            if rotated < mark:
                return (
                    f"[检测门] 审计账本 .loopwork/logs/audit.jsonl 从 {mark} 字节缩到 {now_bytes} 字节，"
                    "且不是轮转——有人抹了账。审计只增不减：立即向用户如实报告这件事"
                    "（谁、什么时候、少了多少），并在 JOURNAL.md 记一行。基准已重置，不再重复顶回。"
                )
        elif now_bytes != mark:
            st["audit_bytes"] = now_bytes
            save_state(root, st)
    return None

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

        # 上一轮已优雅停机 → 本轮无条件放行一次，让会话真的能停下来交还给用户
        try:
            carried = int(st.get("stop_blocks", 0) or 0)
        except (TypeError, ValueError):
            carried = 0
        if carried < 0:
            st["stop_blocks"] = 0
            save_state(root, st)
            return 0

        flag = os.path.join(root, ".loopwork", "batch.flag")
        has_flag = os.path.exists(flag)
        # flag 格式："起点,上次顶回轮数,无进展次数,顶回总数"（兼容旧版三段/两段/纯数字）
        raw = ""
        if has_flag:
            try:
                raw = open(flag, encoding="utf-8").read().strip()
            except Exception:
                pass
        parts = raw.split(",") if raw else []

        def num(i, default=None):
            return int(parts[i]) if len(parts) > i and parts[i].lstrip("-").isdigit() else default

        cap = int(st.get("round_cap", 20))
        batch_size = int(st.get("batch_size", 5))
        rounds = int(st.get("round_count", 0))
        start = num(0)
        if start is None:
            start = rounds
        last_nag = num(1)
        stalls = num(2, 0)
        blocks = num(3, 0) if has_flag else carried

        def drop_flag():
            try:
                os.remove(flag)
            except OSError:
                pass

        def write_blocks(n):
            """顶回记账：批模式记 flag 第 4 段，非批模式记 state.stop_blocks。"""
            if has_flag:
                with open(flag, "w", encoding="utf-8") as f:
                    f.write(f"{start},{'' if last_nag is None else last_nag},{stalls},{n}")
            else:
                st["stop_blocks"] = n
                save_state(root, st)

        def graceful(msg):
            """优雅停机：摘 flag + 记「下轮放行」，本次仍顶回一次把话说完。"""
            drop_flag()
            st["stop_blocks"] = -1
            save_state(root, st)
            return block(msg)

        # ---------- 1. 检测门（永远执行，与批模式无关）----------
        reason = gate_reason(root, st)
        if reason:
            blocks += 1
            if blocks >= MAX_BLOCKS:
                return graceful(
                    reason + f"\n[检测门] 同一违规已顶回 {MAX_BLOCKS} 次仍未消除，自动停机"
                    "（挂机批也一并停了）。不要再试第二遍：把这件事原样告诉用户，让他决定怎么办。"
                )
            write_blocks(blocks)
            return block(reason)
        if not has_flag:
            if carried:  # 检测门通过 = 连续顶回的链断了，账清零
                st["stop_blocks"] = 0
                save_state(root, st)
            return 0

        # ---------- 2. 挂机批模式 ----------
        actionable = blocked = 0
        try:
            with open(os.path.join(root, "tasks.md"), encoding="utf-8") as f:
                for line in f:
                    s = line.strip()
                    if s.startswith("- [ ]"):
                        if "〔卡" in s:
                            blocked += 1
                        else:
                            actionable += 1
        except FileNotFoundError:
            pass

        def finish(msg):
            drop_flag()
            return block(msg)

        if actionable <= 0 and blocked <= 0:
            drop_flag()
            return 0  # 任务全清，正常收工
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
        else:
            stalls = 0
        blocks += 1
        if blocks >= MAX_BLOCKS:
            return graceful(
                f"[挂机档] 本批顶回已达安全上限（{MAX_BLOCKS} 次），自动停批。"
                "请按停批汇报格式向用户汇总进度；要继续挂机请用户重新开批。"
            )
        with open(flag, "w", encoding="utf-8") as f:
            f.write(f"{start},{rounds},{stalls},{blocks}")
        if stalls > 0:
            return block(
                f"[挂机档] 顶回后轮数没涨（仍是第 {rounds} 轮）——若卡在同一任务：按失败分级处理（3 次转诊断），"
                "或写 BLOCKED.md 跳过取下一条。再次无进展将自动停批。"
            )
        return block(
            f"[挂机档] 批模式进行中：本批 {rounds - start}/{batch_size} 条，剩余可做 {actionable} 条"
            f"（总轮数 {rounds}/{cap}）。按内循环节奏继续取下一条任务。用户喊停 = 删除 .loopwork/batch.flag。"
        )
    except Exception:
        return 0

if __name__ == "__main__":
    sys.exit(main())
