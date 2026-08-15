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
        # 剥掉外部 CLAUDE_PROJECT_DIR：它在 root() 里优先级更高，泄漏进来会把机器指向别的项目
        env = {k: v for k, v in os.environ.items() if k != "CLAUDE_PROJECT_DIR"}
        env["CODEX_PROJECT_DIR"] = S
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
        check("A5b 规则含 sudo 前缀与长旗标变体", '"sudo"' in rules and '"--recursive"' in rules)
        check("A6 只读判卷员注册", 'sandbox_mode = "read-only"' in
              open(os.path.join(S, ".codex", "agents", "loopwork-reviewer.toml"), encoding="utf-8").read())
        check("A7 AGENTS.md 锚点", "Loopwork" in open(os.path.join(S, "AGENTS.md"), encoding="utf-8").read())
        r2 = run(["bash", INIT, S, "沙盒项目"], S, env)
        check("A8 init 幂等", r2.returncode == 0)
        hooks2 = json.load(open(os.path.join(S, ".codex", "hooks.json"), encoding="utf-8"))
        check("A9 重复 init 不重复接线", len(hooks2["hooks"]["Stop"]) == 1)
        SELFTEST = os.path.join(REPO, "skills", "loopwork", "scripts", "selftest.sh")
        check("A10 selftest 语法完好", run(["bash", "-n", SELFTEST], S, env).returncode == 0)
        # A11 规则文件升级：旧版缺 sudo/长旗标条目 → 追加一次、幂等、用户自定义规则不动
        rules_p = os.path.join(S, ".codex", "rules", "loopwork.rules")
        with open(rules_p, "w", encoding="utf-8") as f:
            f.write('prefix_rule(pattern=["rm", "-rf"], decision="forbidden", justification="旧版")\n'
                    'prefix_rule(pattern=["my", "custom"], decision="prompt", justification="用户自定义")\n')
        run(["bash", INIT, S, "沙盒项目"], S, env)
        r1txt = open(rules_p, encoding="utf-8").read()
        run(["bash", INIT, S, "沙盒项目"], S, env)
        r2txt = open(rules_p, encoding="utf-8").read()
        check("A11 旧规则升级追加 sudo 条目且幂等",
              r1txt.count('"sudo", "rm", "-rf"') == 1 and r2txt.count('"sudo", "rm", "-rf"') == 1
              and "用户自定义" in r2txt)
        # A12 钩子接线升级：过期签名的自家接线被清、用户钩子保留
        hp = os.path.join(S, ".codex", "hooks.json")
        cfgh = json.load(open(hp, encoding="utf-8"))
        cfgh["hooks"]["Stop"] = [
            {"hooks": [{"type": "command", "command": "python3 .loopwork/hooks/stop_hook.py --legacy"}]},
            {"hooks": [{"type": "command", "command": "echo user-hook"}]},
        ]
        with open(hp, "w", encoding="utf-8") as f:
            json.dump(cfgh, f, ensure_ascii=False, indent=2)
        run(["bash", INIT, S, "沙盒项目"], S, env)
        stop_entries = json.load(open(hp, encoding="utf-8"))["hooks"]["Stop"]
        blob = json.dumps(stop_entries, ensure_ascii=False)
        check("A12 过期接线被清+用户钩子保留",
              len(stop_entries) == 2 and "--legacy" not in blob and "user-hook" in blob and "stop_hook.py" in blob)
        # A13 首次存档密钥筛查：疑似密钥文件不入库、不删盘（独立沙盒走首次提交路径）
        S2 = tempfile.mkdtemp(prefix="lwc-sec-")
        try:
            with open(os.path.join(S2, "fake.pem"), "w") as f:
                f.write("PRIVATE KEY\n")
            with open(os.path.join(S2, "notes.txt"), "w") as f:
                f.write("hello\n")
            run(["bash", INIT, S2, "密钥沙盒"], S2, env)
            ls = run(["git", "ls-files"], S2, env).stdout
            check("A13 首次存档剔除疑似密钥（盘上保留）",
                  "fake.pem" not in ls and "notes.txt" in ls and os.path.exists(os.path.join(S2, "fake.pem")))
        finally:
            shutil.rmtree(S2, ignore_errors=True)

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
        # —— B01 回归：存档即推进基线 的快乐路径与两种忘推场景 ——
        git("add", "tests/exam.py"); git("commit", "-qm", "存档: 红考题")
        head2 = git("rev-parse", "HEAD").stdout.strip()
        setp("last_round_commit", head2); setp("phase", "implementing")
        code, d = stop_hook()
        check("B5 红考题存档+基线推进后实现期放行", code == 0 and not d)
        setp("last_round_commit", base)
        code, d = stop_hook()
        check("B6 忘推基线被顶回并教推进", d.get("decision") == "block" and "last_round_commit" in d.get("reason", ""))
        setp("last_round_commit", head2)
        with open(os.path.join(S, "tests", "exam.py"), "a") as f:
            f.write("# tamper\n")
        code, d = stop_hook()
        check("B7 实现期未存档改考题要求撤销", d.get("decision") == "block" and "撤销" in d.get("reason", ""))
        git("checkout", "--", "tests/exam.py")
        setp("phase", "test-writing")

        # ---- 挂机批模式 ----
        flag = os.path.join(S, ".loopwork", "batch.flag")
        with open(os.path.join(S, "tasks.md"), "w", encoding="utf-8") as f:
            f.write("- [ ] T01 a\n- [ ] T02 b\n- [ ] T03 c\n")
        open(flag, "w").close()
        setp("round_count", 0); setp("batch_size", 2)
        code, d = stop_hook()
        check("C1 批中顶回", d.get("decision") == "block" and "批模式进行中" in d.get("reason", ""))
        check("C2 flag 记录起点+防打转标记", open(flag).read().strip() == "0,0,0")
        code, d = stop_hook()
        check("C3 无进展第 1 次仅警告", d.get("decision") == "block" and "没涨" in d.get("reason", "")
              and open(flag).read().strip() == "0,0,1")
        code, d = stop_hook()
        check("C3b 连续 2 次无进展自动停批", d.get("decision") == "block" and "打转" in d.get("reason", "")
              and not os.path.exists(flag))
        with open(flag, "w") as f:
            f.write("0,0")  # 旧版两段 flag 格式（模拟批已开跑，起点=第0轮）
        setp("round_count", 2)
        code, d = stop_hook()
        check("C4 满批强制验收（兼容旧 flag）", d.get("decision") == "block" and "验收" in d.get("reason", "") and not os.path.exists(flag))
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
        # R1 审计日志单代轮转：超 5MB 顶成 .1，新账本从头记
        with open(audit, "w") as f:
            f.write("x" * (5 * 1024 * 1024 + 100))
        p = run(["python3", os.path.join(H, "audit_log.py")], S, env,
                inp=json.dumps({"tool_name": "Bash", "tool_input": {"command": "ls"}, "cwd": S}))
        check("R1 审计日志超 5MB 单代轮转",
              p.returncode == 0 and os.path.exists(audit + ".1")
              and os.path.getsize(audit) < 1000 and '"ls"' in open(audit, encoding="utf-8").read())
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

        # ---- verify：绿灯 / 超时保险 / fail-closed ----
        with open(os.path.join(S, "tests", "run.sh"), "w", encoding="utf-8") as f:
            f.write("exit 0\n")
        v = run(["bash", os.path.join(H, "verify.sh")], S, env)
        check("E0 考题全绿 exit 0", v.returncode == 0)
        with open(os.path.join(S, "tests", "run.sh"), "w", encoding="utf-8") as f:
            f.write("sleep 30\n")
        v = run(["bash", os.path.join(H, "verify.sh")], S, {**env, "LOOPWORK_VERIFY_TIMEOUT": "2"})
        check("E2 考题挂住被超时保险击杀 (exit 124)", v.returncode == 124)
        # E3 多栈裁判：没有 tests/run.sh 时探测到的栈全都要跑，一红全局红（假 npm shim，不依赖本机 npm）
        os.remove(os.path.join(S, "tests", "run.sh"))
        shim = os.path.join(S, "shim")
        os.makedirs(shim, exist_ok=True)
        with open(os.path.join(shim, "npm"), "w") as f:
            f.write("#!/bin/sh\nexit 1\n")
        os.chmod(os.path.join(shim, "npm"), 0o755)
        with open(os.path.join(S, "package.json"), "w", encoding="utf-8") as f:
            f.write('{"name": "x", "version": "1.0.0", "scripts": {"test": "exit 1"}}\n')
        with open(os.path.join(S, "tests", "test_ok.py"), "w", encoding="utf-8") as f:
            f.write("import unittest\nclass TestOK(unittest.TestCase):\n    def test_ok(self):\n        self.assertTrue(True)\n")
        v = run(["bash", os.path.join(H, "verify.sh")], S, {**env, "PATH": shim + os.pathsep + env["PATH"]})
        check("E3 多栈一红全局红", v.returncode == 1, f"rc={v.returncode}")
        os.remove(os.path.join(S, "package.json"))
        shutil.rmtree(os.path.join(S, "tests"), ignore_errors=True)
        v = run(["bash", os.path.join(H, "verify.sh")], S, env)
        check("E1 无考题 fail-closed(exit 3)", v.returncode == 3)
    finally:
        shutil.rmtree(S, ignore_errors=True)

    print(f"\n{'=' * 42}\n{sum(RESULTS)}/{len(RESULTS)} 通过")
    return 0 if all(RESULTS) else 1

if __name__ == "__main__":
    sys.exit(main())
