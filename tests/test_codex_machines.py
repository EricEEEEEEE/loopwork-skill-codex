#!/usr/bin/env python3
"""Loopwork Codex 版机器回归套件（本仓库的考题）。

沙盒建家后验证：init 产物、Codex 钩子接线、规则文件、AGENTS.md 锚点、
stop_hook（检测门：基线锚定/相位纪律；挂机档：批次外部计数/受阻出口/防打转）、
audit_log、progress 对账、verify fail-closed。exit 0 = 全绿。
"""
import json, os, shutil, subprocess, sys, tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INIT = os.path.join(REPO, "skills", "loopwork", "scripts", "init_project.sh")
RESULTS = []

def check(name, ok, detail=""):
    RESULTS.append(ok)
    print(("✅" if ok else "❌") + f" {name}" + (f"  [{detail}]" if detail and not ok else ""))

def run(args, cwd, env=None, inp=None):
    return subprocess.run(args, cwd=cwd, env=env or os.environ, input=inp,
                          capture_output=True, text=True, encoding="utf-8", errors="replace")

def main():
    S = tempfile.mkdtemp(prefix="lwc-test-")
    try:
        env = {**os.environ, "CODEX_PROJECT_DIR": S}
        H = os.path.join(S, ".loopwork", "hooks")

        r = run(["bash", INIT, S, "沙盒项目"], S, env)
        check("A1 init 建家成功", r.returncode == 0, r.stderr[-200:])
        for f in ("stop_hook.py", "audit_log.py", "progress.py", "verify.sh"):
            check(f"A2 机器进驻 {f}", os.path.exists(os.path.join(H, f)))
        check("A3 Codex 钩子接线", os.path.exists(os.path.join(S, ".codex", "hooks.json")))
        hooks = json.load(open(os.path.join(S, ".codex", "hooks.json"), encoding="utf-8"))
        check("A4 三个事件均已挂载", all(k in hooks.get("hooks", {}) for k in ("SessionStart", "Stop", "PostToolUse")))
        rules = open(os.path.join(S, ".codex", "rules", "loopwork.rules"), encoding="utf-8").read()
        check("A5 规则含 forbidden 危险命令", 'decision="forbidden"' in rules and '"--force"' in rules)
        check("A6 只读判卷员注册", 'sandbox_mode = "read-only"' in
              open(os.path.join(S, ".codex", "agents", "loopwork-reviewer.toml"), encoding="utf-8").read())
        check("A7 AGENTS.md 锚点", "Loopwork" in open(os.path.join(S, "AGENTS.md"), encoding="utf-8").read())
        r2 = run(["bash", INIT, S, "沙盒项目"], S, env)
        check("A8 init 幂等", r2.returncode == 0)
        hooks2 = json.load(open(os.path.join(S, ".codex", "hooks.json"), encoding="utf-8"))
        check("A9 重复 init 不重复接线", len(hooks2["hooks"]["Stop"]) == 1)

        def setp(key, val):
            run(["python3", os.path.join(H, "progress.py"), "set", key, str(val)], S, env)

        def stop_hook():
            p = run(["python3", os.path.join(H, "stop_hook.py")], S, env, inp="{}")
            try:
                d = json.loads(p.stdout) if p.stdout.strip() else {}
            except Exception:
                d = {}
            return p.returncode, d

        # ---- 检测门 ----
        def git(*a):
            return run(["git", *a], S, env)
        git("add", "-A"); git("commit", "-qm", "base")
        base = git("rev-parse", "HEAD").stdout.strip()
        setp("stage", "4"); setp("last_round_commit", base); setp("phase", "implementing")
        os.makedirs(os.path.join(S, "tests"), exist_ok=True)
        with open(os.path.join(S, "tests", "exam.py"), "w") as f:
            f.write("tampered\n")
        code, d = stop_hook()
        check("B1 实现期改考题被检测门顶回", code == 0 and d.get("decision") == "block" and "受保护文件" in d.get("reason", ""))
        os.remove(os.path.join(S, "tests", "exam.py"))
        code, d = stop_hook()
        check("B2 恢复后放行", code == 0 and not d)
        setp("last_round_commit", "0000000000deadbeef0000000000000000000000")
        code, d = stop_hook()
        check("B3 基线不可达报警（防改历史）", d.get("decision") == "block" and "不可达" in d.get("reason", ""))
        setp("last_round_commit", base); setp("phase", "test-writing")
        with open(os.path.join(S, "tests", "exam.py"), "w") as f:
            f.write("legit test\n")
        code, d = stop_hook()
        check("B4 test-writing 期写考题放行", not d)

        # ---- 挂机批模式 ----
        flag = os.path.join(S, ".loopwork", "batch.flag")
        with open(os.path.join(S, "tasks.md"), "w", encoding="utf-8") as f:
            f.write("- [ ] T01 a\n- [ ] T02 b\n- [ ] T03 c\n")
        open(flag, "w").close()
        setp("round_count", 0); setp("batch_size", 2)
        code, d = stop_hook()
        check("C1 批中顶回", d.get("decision") == "block" and "批模式进行中" in d.get("reason", ""))
        check("C2 flag 记录起点+防打转标记", open(flag).read().strip() == "0,0")
        code, d = stop_hook()
        check("C3 轮数无进展自动放行（防原地打转）", not d and not os.path.exists(flag))
        with open(flag, "w") as f:
            f.write("0,0")  # 批次起点=第0轮（模拟批已开跑）
        setp("round_count", 2)
        code, d = stop_hook()
        check("C4 满批强制验收", d.get("decision") == "block" and "验收" in d.get("reason", "") and not os.path.exists(flag))
        open(flag, "w").close()
        with open(os.path.join(S, "tasks.md"), "w", encoding="utf-8") as f:
            f.write("- [ ] T01 a 〔卡·B01〕\n- [x] T02 b\n")
        code, d = stop_hook()
        check("C5 只剩受阻→清问题本", d.get("decision") == "block" and "问题本" in d.get("reason", "") and not os.path.exists(flag))
        open(flag, "w").close()
        with open(os.path.join(S, "tasks.md"), "w", encoding="utf-8") as f:
            f.write("- [x] T01\n- [x] T02\n")
        code, d = stop_hook()
        check("C6 批空放行+摘 flag", not d and not os.path.exists(flag))

        # ---- 审计与对账 ----
        p = run(["python3", os.path.join(H, "audit_log.py")], S, env,
                inp=json.dumps({"tool_name": "apply_patch", "tool_input": {"file_path": "src/x.js"}, "cwd": S}))
        audit = os.path.join(S, ".loopwork", "logs", "audit.jsonl")
        check("D1 审计日志落盘", p.returncode == 0 and os.path.exists(audit) and "apply_patch" in open(audit).read())
        with open(os.path.join(S, "tasks.md"), "w", encoding="utf-8") as f:
            f.write("- [x] T01 a\n- [x] T02 b\n- [ ] T03 c\n")
        p = run(["python3", os.path.join(H, "progress.py"), "card"], S, env)
        check("D2 进度卡对账警告（勾选>存档）", "对账警告" in p.stdout)
        run(["git", "commit", "-qm", "存档: T01 假完成", "--allow-empty"], S, env)
        run(["git", "commit", "-qm", "存档: T02 假完成", "--allow-empty"], S, env)
        p = run(["python3", os.path.join(H, "progress.py"), "card"], S, env)
        check("D2b 空存档假完成被点破", "空提交" in p.stdout)
        setp("phase", "implementing")
        run(["python3", os.path.join(H, "progress.py"), "bump-cycle"], S, env)
        st = json.load(open(os.path.join(S, ".loopwork", "state.json"), encoding="utf-8"))
        check("D3 bump-cycle 复位 phase", st.get("phase") == "test-writing")

        # ---- verify fail-closed ----
        shutil.rmtree(os.path.join(S, "tests"), ignore_errors=True)
        v = run(["bash", os.path.join(H, "verify.sh")], S, env)
        check("E1 无考题 fail-closed(exit 3)", v.returncode == 3)
    finally:
        shutil.rmtree(S, ignore_errors=True)

    print(f"\n{'=' * 42}\n{sum(RESULTS)}/{len(RESULTS)} 通过")
    return 0 if all(RESULTS) else 1

if __name__ == "__main__":
    sys.exit(main())
