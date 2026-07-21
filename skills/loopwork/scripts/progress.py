#!/usr/bin/env python3
"""Loopwork 状态机：唯一被允许读写 state.json 的入口。

用法:
  progress.py card                 # 打印进度卡（SessionStart 钩子也用它）
  progress.py get <key>
  progress.py set <key> <value>   # stage/phase/batch_size/round_cap/...
  progress.py bump-round          # 内循环轮数 +1
  progress.py bump-cycle          # 外循环圈数 +1，round 归零
  progress.py milestone <name>    # 记录里程碑（幂等，返回 new/dup）
"""
import json, os, subprocess, sys, datetime

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
    r = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
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
    """数 git 历史里「存档: T…」的次数——勾选不是证据，存档才是。无 git 时返回 None。"""
    try:
        out = subprocess.check_output(["git", "-C", root(), "log", "--pretty=%s"],
                                      stderr=subprocess.DEVNULL)
        return sum(1 for l in out.decode("utf-8", "replace").splitlines()
                   if l.startswith("存档: T"))
    except Exception:
        return None

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
    commits = count_archive_commits()
    if done > 0 and commits is not None and done > commits:
        lines.append(
            f"⚠️ 对账警告：{done} 项打勾但只有 {commits} 次任务存档——勾选没有证据支撑，"
            "续接前先核实（git log / verify.sh），别在假地基上盖楼。"
        )
    print("\n".join(lines))
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
