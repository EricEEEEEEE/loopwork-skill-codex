#!/usr/bin/env python3
"""Loopwork 状态机：唯一被允许读写 state.json 的入口。

用法:
  progress.py card                 # 打印进度卡（SessionStart 钩子也用它）
  progress.py get <key>
  progress.py set <key> <value>   # stage/phase/batch_size/round_cap/...
  progress.py bump-round          # 内循环轮数 +1
  progress.py bump-cycle          # 外循环圈数 +1，round 归零
  progress.py milestone <name>    # 记录里程碑（幂等，返回 new/dup）
  progress.py journal "<一行>"    # 向 JOURNAL.md 追加一行（日志只增不减的唯一入口）
  progress.py commit red|green|note "存档: T3 …"  # 登记存档意图，交轮末钩子代为落 commit
"""
import json, os, subprocess, sys, datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import guard_log    # 拦截取证账本（两版共享）
except Exception:
    guard_log = None

STAGE_NAMES = {
    "0": "Stage 0 开场体检", "1": "Stage 1 想法访谈", "2": "Stage 2 规格与规矩",
    "3": "Stage 3 摊开计划", "4": "Stage 4 循环执行", "5": "Stage 5 验收",
    "6": "Stage 6 首航收尾", "loop": "循环模式（下半场）", "quick": "快速通道",
}
NEXT_HINT = {
    "0": "完成体检与建家，进入访谈", "1": "问清六件事，定稿项目简介",
    "2": "逐节确认规格与规矩", "3": "等用户批准计划（批准前不写代码）",
    "4": "继续内循环：取下一条任务", "5": "请用户照验收单点一遍",
    "6": "收尾三件套 + 进环仪式", "loop": "等点火：继续 / 加功能 / 报修 / 续单",
    "quick": "完成小任务并汇报",
}

def root():
    r = (os.environ.get("CLAUDE_PROJECT_DIR") or os.environ.get("CODEX_PROJECT_DIR")
         or os.getcwd())
    return r

def state_path():
    return os.path.join(root(), ".loopwork", "state.json")

def load():
    try:
        with open(state_path(), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def save(st):
    st["last_session"] = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
    tmp = state_path() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=2)
    os.replace(tmp, state_path())

def count_tasks():
    """返回 (done, total)，读项目根 tasks.md。"""
    p = os.path.join(root(), "tasks.md")
    done = total = 0
    try:
        with open(p, encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if s.startswith("- [x]") or s.startswith("- [X]"):
                    done += 1; total += 1
                elif s.startswith("- [ ]"):
                    total += 1
    except FileNotFoundError:
        pass
    return done, total

def count_archive_commits():
    """返回 (存档数, 空存档数)。「存档: T…」提交但 0 文件变更 = 空存档（假完成信号）。
    勾选不是证据，存档才是；空存档连存档都不算数。无 git 时返回 (None, 0)。"""
    try:
        out = subprocess.check_output(["git", "-C", root(), "log", "--pretty=%H|%s"],
                                      stderr=subprocess.DEVNULL).decode("utf-8", "replace")
        t_commits = [l.split("|", 1)[0] for l in out.splitlines()
                     if "|" in l and l.split("|", 1)[1].startswith("存档: T")]
        empty = 0
        for h in t_commits[:50]:  # 上限 50 条，防超长历史拖慢开屏
            files = subprocess.check_output(
                ["git", "-C", root(), "diff-tree", "--no-commit-id", "--name-only", "-r", h],
                stderr=subprocess.DEVNULL).decode("utf-8", "replace").strip()
            if not files:
                empty += 1
        return len(t_commits), empty
    except Exception:
        return None, 0

def count_blocked():
    p = os.path.join(root(), "BLOCKED.md")
    n = 0
    try:
        with open(p, encoding="utf-8") as f:
            n = sum(1 for line in f if "待拍板" in line)
    except FileNotFoundError:
        pass
    return n

def card():
    st = load()
    if st is None:
        return 0  # 非 loopwork 项目，静默
    done, total = count_tasks()
    blocked = count_blocked()
    stage = str(st.get("stage", "?"))
    lines = [
        f"[Loopwork 进度卡] 项目「{st.get('project_name', '?')}」",
        f"你在：{STAGE_NAMES.get(stage, stage)}（第 {st.get('cycle', 1)} 圈）",
        f"任务：{done}/{total} 完成" + (f"；问题本 {blocked} 件待拍板" if blocked else ""),
        f"下一步：{NEXT_HINT.get(stage, '读 references 对应剧本')}",
    ]
    # 围栏降级横幅：selftest 探到本机不具备实时拦截能力时会写 enforce_mode=detect。
    # 首屏就得说，不能等违规了才说——用户有权知道今天守在门口的是几层。
    if str(st.get("enforce_mode", "")) == "detect":
        lines.append(
            "⚠️ 围栏降级中（enforce_mode=detect）：本机 codex 低于 0.153 或钩子层未接通，"
            "实时拦截（PreToolUse）不可用，只剩 OS 沙箱 + 轮末检测门——违规不会当场被拦，"
            "但轮末必被顶回。挂机前建议先升级 codex 再重跑 selftest.sh。"
        )
    commits, empty = count_archive_commits()
    if done > 0 and commits is not None and done > commits:
        lines.append(
            f"⚠️ 对账警告：{done} 项打勾但只有 {commits} 次任务存档——勾选没有证据支撑，"
            "续接前先核实（git log / verify.sh），别在假地基上盖楼。"
        )
    if empty > 0:
        lines.append(
            f"⚠️ 对账警告：{empty} 次任务存档是空提交（没有任何文件变更）——「完成」可能没有实体，"
            "续接前用 git show --stat 逐条核验。"
        )
    # 拦截取证：围栏至今拦了多少次。不是罪状，是体检单——数字异常高说明
    # 上一段挂机里模型在反复试探边界，续接前值得翻一眼账本。
    hits = guard_log.count(root()) if guard_log is not None else 0
    if hits:
        lines.append(f"围栏拦截：累计 {hits} 次（明细 .loopwork/logs/blocks.jsonl）")
    print("\n".join(lines))
    return 0

def journal_append(line):
    """向 JOURNAL.md 追加一行。日志是历史：只增不减，围栏拦住一切改写/删除，
    这里是模型记账的正门。换行被压平——一轮一行才读得下去。"""
    text = " ".join(str(line).splitlines()).strip()
    if not text:
        print("journal 需要一行内容", file=sys.stderr)
        return 1
    if not text.startswith("-"):
        text = "- " + text
    with open(os.path.join(root(), "JOURNAL.md"), "a", encoding="utf-8") as jf:
        jf.write(text + "\n")
    print("ok")
    return 0

def request_commit(st, kind, msg):
    """登记一次存档意图，交给轮末钩子（跑在沙箱外）去真正执行 git。

    为什么不自己 commit：Codex 版模型跑在沙箱里，.git 写不动。存档因此不是
    「模型说存了」，而是「围栏验过才算」——密钥筛查、相位核对、verify.sh 全过才落。
    没有代存档钩子的版本（CC 版由模型自己 git commit）在这里直接报错：存档意图宁可
    当场拒绝，也不能写进 state 然后没人执行、被静静吞掉。

    三种存档：red 只许考题（落地发一张红票）；green 要手里有红票且 verify.sh 全绿；
    note 是阶段切换/登记/批末落盘这类记事存档，唯独不许夹带考题——考题的唯一入口
    是红存档，否则先红后绿的入场券就被绕开了。"""
    if kind not in ("red", "green", "note"):
        print('用法: progress.py commit <red|green|note> "存档: T3 …"', file=sys.stderr)
        return 1
    text = " ".join(str(msg).splitlines()).strip()
    if not text:
        print('存档要有一句话说明：commit red "存档: T3 红考题"', file=sys.stderr)
        return 1
    if not os.path.exists(os.path.join(root(), ".loopwork", "hooks", "stop_hook.py")):
        print("这个项目没有代存档钩子（.loopwork/hooks/stop_hook.py 不在）——"
              "本版由你自己执行 git add / git commit。没有登记任何待存档意图。",
              file=sys.stderr)
        return 1
    st["pending_commit"] = {"kind": kind, "msg": text}
    save(st)
    print(f"已登记待存档（{kind}）：{text}")
    print("轮末钩子会做密钥筛查 + 相位核对" + (" + verify.sh" if kind == "green" else "") +
          "，全过才落 commit，结果下一轮告诉你。")
    return 0

def main(argv):
    if len(argv) < 2:
        print(__doc__); return 1
    cmd = argv[1]
    if cmd == "card":
        return card()
    st = load()
    if st is None:
        print("no .loopwork/state.json here", file=sys.stderr); return 1
    if cmd == "get":
        print(st.get(argv[2], ""))
    elif cmd == "set":
        key, val = argv[2], argv[3]
        st[key] = int(val) if val.isdigit() and key not in ("stage", "phase") else val
        save(st)
        if key == "phase":  # 审计留痕：围栏开锁/上锁必须可追溯
            try:
                with open(os.path.join(root(), "JOURNAL.md"), "a", encoding="utf-8") as jf:
                    jf.write(f"- [audit] phase → {val} @ {st['last_session']}\n")
            except Exception:
                pass
        print(f"{key}={st[key]}")
    elif cmd == "bump-round":
        st["round_count"] = int(st.get("round_count", 0)) + 1
        save(st); print(st["round_count"])
    elif cmd == "bump-cycle":
        st["cycle"] = int(st.get("cycle", 1)) + 1
        st["round_count"] = 0
        st["phase"] = "test-writing"  # 换圈复位相位：防上一圈中断在实现期导致围栏误锁下一圈
        save(st)
        try:
            with open(os.path.join(root(), "JOURNAL.md"), "a", encoding="utf-8") as jf:
                jf.write(f"- [audit] phase → test-writing (bump-cycle) @ {st['last_session']}\n")
        except Exception:
            pass
        print(st["cycle"])
    elif cmd == "journal":
        return journal_append(argv[2] if len(argv) > 2 else "")
    elif cmd == "commit":
        return request_commit(st, argv[2] if len(argv) > 2 else "",
                              argv[3] if len(argv) > 3 else "")
    elif cmd == "milestone":
        ms = st.setdefault("milestones", [])
        if argv[2] in ms:
            print("dup")
        else:
            ms.append(argv[2]); save(st); print("new")
    else:
        print(__doc__); return 1
    return 0

if __name__ == "__main__":
    sys.exit(main(sys.argv))
