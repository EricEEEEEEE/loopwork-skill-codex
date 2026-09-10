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
        for f in ("guard_rules.py", "guard_log.py", "guard_pre.py", "stop_hook.py",
                  "audit_log.py", "progress.py", "verify.sh"):
            check(f"A2 机器进驻 {f}", os.path.exists(os.path.join(H, f)))
        check("A3 Codex 钩子接线", os.path.exists(os.path.join(S, ".codex", "hooks.json")))
        hooks = json.load(open(os.path.join(S, ".codex", "hooks.json"), encoding="utf-8"))
        check("A4 四个事件均已挂载",
              all(k in hooks.get("hooks", {})
                  for k in ("PreToolUse", "SessionStart", "Stop", "PostToolUse")))
        rules = open(os.path.join(S, ".codex", "rules", "loopwork.rules"), encoding="utf-8").read()
        check("A5 规则含 forbidden 危险命令", 'decision="forbidden"' in rules and '"--force"' in rules)
        check("A5b 规则含 sudo 前缀与长旗标变体", '"sudo"' in rules and '"--recursive"' in rules)
        check("A5c 规则含改历史/销毁证据禁令",
              all(f'"{k}"' in rules for k in ("--amend", "rebase", "filter-branch",
                                              "update-ref", "stash", "clean"))
              and '"sudo", "git", "rebase"' in rules)
        check("A6 只读判卷员注册", 'sandbox_mode = "read-only"' in
              open(os.path.join(S, ".codex", "agents", "loopwork-reviewer.toml"), encoding="utf-8").read())
        # 判卷员的任务指令不许悄悄消失或缩水（与 CC 版同一份职责，锁住）
        rv_p = os.path.join(REPO, "skills", "loopwork", "references", "reviewer.md")
        check("A6b 判卷员任务指令在", os.path.exists(rv_p))
        rv = open(rv_p, encoding="utf-8").read() if os.path.exists(rv_p) else ""
        check("A6c 判卷员四段齐全（合规/质量/作弊清单/考题盲区 + 固定输出格式）",
              all(k in rv for k in ("第一段 · 合规", "第二段 · 质量", "第三段 · 作弊清单",
                                    "第四段 · 考题盲区", "判卷结论：", "N 对 M", "verify.sh")))
        check("A6e 作弊清单八条齐全，且如实交代自动探测只查得动前五条",
              all(k in rv for k in ("空转修复", "断言放水", "断言消失", "吞异常",
                                    "抑制检查", "假重构", "查表蒙混", "功能孤岛"))
              and "0/27" in rv and "只查得动 1–5" in rv)
        s5 = open(os.path.join(REPO, "skills", "loopwork", "references", "stage-5-accept.md"),
                  encoding="utf-8").read()
        check("A6d stage-5 指向判卷员并说明只读由系统强制",
              "references/reviewer.md" in s5 and "read-only" in s5)
        s0 = open(os.path.join(REPO, "skills", "loopwork", "references", "stage-0-setup.md"),
                  encoding="utf-8").read()
        check("A6f stage-0 交代围栏管不到供应链：清点别人的钩子 + 搜来的安装指引只转述不执行",
              all(k in s0 for k in (".codex/hooks.json", "AgentBaiting", "只转述",
                                    "装什么由用户指定", "不再询问")))
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
        check("A11b 旧规则同时补上改历史禁令且幂等",
              r1txt.count('pattern=["git", "commit", "--amend"]') == 1
              and r2txt.count('pattern=["git", "commit", "--amend"]') == 1
              and 'pattern=["git", "clean"]' in r2txt)
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

        # ---- 实时围栏（PreToolUse · guard_pre.py）----
        # 喂真实形状的 payload：0.153.4 实测 Bash / apply_patch 的 tool_input 只有 command 一个键。
        BLK = os.path.join(S, ".loopwork", "logs", "blocks.jsonl")

        def gpre(tool, command, phase=None, ti=None):
            if phase is not None:
                setp("phase", phase)
            p = run(["python3", os.path.join(H, "guard_pre.py")], S, env,
                    inp=json.dumps({"tool_name": tool, "cwd": S,
                                    "tool_input": ti if ti is not None else {"command": command}}))
            return p.returncode, p.stderr

        def patch(*lines):
            return "*** Begin Patch\n" + "\n".join(lines) + "\n@@\n-old\n+new\n*** End Patch\n"

        rc, err = gpre("apply_patch", patch("*** Update File: tests/exam.py"), "implementing")
        check("P1 实现期补丁改考题被拦", rc == 2 and "实现阶段" in err, err[-160:])
        rc, _ = gpre("apply_patch", patch("*** Update File: src/app.py"))
        check("P2 实现期补丁改实现文件放行", rc == 0)
        rc, _ = gpre("apply_patch", patch("*** Add File: tests/exam2.py"), "test-writing")
        check("P3 出题期补丁写考题放行", rc == 0)
        rc, err = gpre("apply_patch", patch("*** Move to: tests/renamed.py"), "implementing")
        check("P4 Move to: 行也算落点", rc == 2 and "实现阶段" in err, err[-160:])
        rc, err = gpre("apply_patch", patch(f"*** Update File: {os.path.join(S, 'tests', 'exam.py')}"))
        check("P5 绝对路径落点照样归一后被拦", rc == 2, err[-160:])
        rc, err = gpre("apply_patch", patch("*** Update File: /etc/hosts"))
        check("P6 补丁写到项目外被拦", rc == 2 and "之外" in err, err[-160:])
        rc, err = gpre("apply_patch", patch("*** Update File: JOURNAL.md"))
        check("P7 补丁改 JOURNAL.md 被拦（只许追加）", rc == 2 and "只许追加" in err, err[-160:])
        rc, err = gpre("Bash", "sed -i '' -e 's/a/b/' .loopwork/state.json")
        check("P8 shell 绕道改状态文件被拦", rc == 2 and "state.json" in err, err[-160:])
        rc, err = gpre("Bash", "echo '{}' > .codex/hooks.json")
        check("P9 shell 改 Codex 接线被拦（围栏自保）", rc == 2 and ".codex/hooks.json" in err, err[-160:])
        rc, err = gpre("Bash", "rm -rf build/")
        check("P10 rm -rf 被拦", rc == 2 and "rm -rf" in err, err[-160:])
        rc, err = gpre("Bash", "git commit --amend -m x")
        check("P11 改历史被拦", rc == 2 and "amend" in err, err[-160:])
        rc, _ = gpre("Bash", "python3 -m pytest tests/ -q")
        check("P12 实现期跑考题放行（提到路径不算写）", rc == 0)
        rc, err = gpre("Bash", "apply_patch <<'EOF'\n" + patch("*** Update File: tests/exam.py") + "EOF")
        check("P13 heredoc 走 shell 的补丁一样被拦", rc == 2 and "实现阶段" in err, err[-160:])
        rc, _ = gpre("web_search", "", ti={"query": "loopwork"})
        check("P15 没见过的工具放行", rc == 0)
        recs = [json.loads(x) for x in open(BLK, encoding="utf-8").read().splitlines() if x.strip()]
        check("P16 取证账本一次拦截一行（10 次拦截 + 1 次未知工具）",
              len(recs) == 11 and recs[0].get("rule") == "impl-locked"
              and recs[-1].get("rule") == "unknown-tool"
              and recs[-1].get("target") == "keys=query", f"{len(recs)} 条 / {str(recs[-1])[:100]}")
        check("P17 账本字段齐（ts/tool/target/rule/phase）",
              all(set(r) == {"ts", "tool", "target", "rule", "phase"} for r in recs))
        rc, _ = gpre("Bash", "cat .loopwork/state.json")
        check("P18 判定核心缺席不阻塞（先确认在场时正常）", rc == 0)
        gr = os.path.join(H, "guard_rules.py")
        os.replace(gr, gr + ".bak")
        rc, err = gpre("apply_patch", patch("*** Update File: tests/exam.py"))
        check("P19 判定核心不在时放行但出声（不做纸老虎也不砖会话）",
              rc == 0 and "guard_rules.py" in err, err[-160:])
        os.replace(gr + ".bak", gr)
        os.remove(BLK)
        setp("phase", "test-writing")

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
        # —— 围栏保护自己：动 .loopwork/hooks/ 也是动受保护文件 ——
        gp = os.path.join(S, ".loopwork", "hooks", "stop_hook.py")
        with open(gp, "a") as f:
            f.write("# tamper\n")
        code, d = stop_hook()
        check("B8 实现期改围栏脚本被顶回",
              d.get("decision") == "block" and ".loopwork/hooks/" in d.get("reason", ""))
        git("checkout", "--", ".loopwork/hooks/stop_hook.py")
        code, d = stop_hook()
        check("B9 围栏脚本恢复后放行", code == 0 and not d)
        setp("phase", "test-writing")
        # —— 只增不减：JOURNAL 是历史，审计账本是流水 ——
        jp = os.path.join(S, "JOURNAL.md")
        git("add", "JOURNAL.md"); git("commit", "-qm", "存档: 批末状态落盘")
        setp("last_round_commit", git("rev-parse", "HEAD").stdout.strip())  # 存档即推进基线
        j_head = open(jp, encoding="utf-8").read()
        with open(jp, "w", encoding="utf-8") as f:
            f.write("\n".join(j_head.splitlines()[:-1]) + "\n")
        code, d = stop_hook()
        check("B10 JOURNAL 未存档删行被顶回（日志只增不减）",
              d.get("decision") == "block" and "JOURNAL" in d.get("reason", ""))
        with open(jp, "w", encoding="utf-8") as f:
            f.write(j_head + "- 补记一行\n")
        code, d = stop_hook()
        check("B11 JOURNAL 追加放行", code == 0 and not d)
        with open(jp, "w", encoding="utf-8") as f:
            f.write("\n".join(j_head.splitlines()[:-1]) + "\n")
        git("add", "JOURNAL.md"); git("commit", "-qm", "改写日志")
        code, d = stop_hook()
        check("B12 JOURNAL 已存档的删行也被顶回",
              d.get("decision") == "block" and "JOURNAL" in d.get("reason", ""))
        with open(jp, "w", encoding="utf-8") as f:
            f.write(j_head)
        git("add", "JOURNAL.md"); git("commit", "-qm", "还原日志")
        setp("last_round_commit", git("rev-parse", "HEAD").stdout.strip())
        code, d = stop_hook()
        check("B13 还原并推进基线后放行", code == 0 and not d)
        audit = os.path.join(S, ".loopwork", "logs", "audit.jsonl")
        os.makedirs(os.path.dirname(audit), exist_ok=True)
        line = '{"ts":"x","tool":"Bash","summary":"a"}\n'
        with open(audit, "w", encoding="utf-8") as f:
            f.write(line * 20)
        stop_hook()  # 记下基准
        with open(audit, "w", encoding="utf-8") as f:
            f.write(line)
        code, d = stop_hook()
        check("B14 审计账本被抹短被顶回", d.get("decision") == "block" and "审计" in d.get("reason", ""))
        code, d = stop_hook()
        check("B15 抹账只报一次（基准已重置，不死循环）", code == 0 and not d)
        with open(audit, "w", encoding="utf-8") as f:
            f.write(line * 20)
        stop_hook()
        os.replace(audit, audit + ".1")
        with open(audit, "w", encoding="utf-8") as f:
            f.write(line)
        code, d = stop_hook()
        check("B16 轮转后账本变短不误报", code == 0 and not d)

        # ---- 挂机批模式 ----
        flag = os.path.join(S, ".loopwork", "batch.flag")
        with open(os.path.join(S, "tasks.md"), "w", encoding="utf-8") as f:
            f.write("- [ ] T01 a\n- [ ] T02 b\n- [ ] T03 c\n")
        open(flag, "w").close()
        setp("round_count", 0); setp("batch_size", 2)
        code, d = stop_hook()
        check("C1 批中顶回", d.get("decision") == "block" and "批模式进行中" in d.get("reason", ""))
        fp = lambda: open(flag).read().strip().split(",")
        check("C2 flag 记录起点+防打转标记+顶回总数+进展指纹",
              fp()[:4] == ["0", "0", "0", "1"] and len(fp()[4]) == 12)
        code, d = stop_hook()
        check("C3 无进展第 1 次仅警告", d.get("decision") == "block" and "没涨" in d.get("reason", "")
              and fp()[:4] == ["0", "0", "1", "2"])
        code, d = stop_hook()
        check("C3b 连续 2 次无进展自动停批", d.get("decision") == "block" and "打转" in d.get("reason", "")
              and not os.path.exists(flag))
        # 无进展 = 轮数没涨 ∧ HEAD 没动 ∧ tasks.md 没动 ∧ BLOCKED.md 没动。
        # 只看轮数会把「一条硬任务跨两次顶回」误判成打转——两版量同一把尺（guard_rules.PROGRESS_FILES）。
        open(flag, "w").close()
        stop_hook()                                     # 第 1 次：记下起点与指纹
        with open(os.path.join(S, "BLOCKED.md"), "a", encoding="utf-8") as f:
            f.write("## B01 · 图表库选择\n")             # 轮数仍没涨，但问题本新增了一条
        code, d = stop_hook()
        rs = d.get("reason", "")
        check("C3c 轮数没涨但问题本新增 → 算进展，不计打转",
              d.get("decision") == "block" and "没涨" not in rs and fp()[2] == "0", rs[-160:])
        with open(os.path.join(S, "tasks.md"), "a", encoding="utf-8") as f:
            f.write("- [ ] T04 d\n")                    # 轮数仍没涨，但 tasks.md 动了
        code, d = stop_hook()
        rs = d.get("reason", "")
        check("C3d 轮数没涨但 tasks.md 动了 → 算进展，不计打转",
              d.get("decision") == "block" and "没涨" not in rs and fp()[2] == "0", rs[-160:])
        git("commit", "-qm", "存档: 进展指纹用例", "--allow-empty")
        code, d = stop_hook()
        rs = d.get("reason", "")
        check("C3e 轮数没涨但落了新存档 → 算进展，不计打转",
              d.get("decision") == "block" and "没涨" not in rs and fp()[2] == "0", rs[-160:])
        code, d = stop_hook()
        rs = d.get("reason", "")
        check("C3f 三样全没动才计无进展",
              d.get("decision") == "block" and "没涨" in rs and fp()[2] == "1", rs[-160:])
        os.remove(flag)
        os.remove(os.path.join(S, "BLOCKED.md"))
        with open(os.path.join(S, "tasks.md"), "w", encoding="utf-8") as f:
            f.write("- [ ] T01 a\n- [ ] T02 b\n- [ ] T03 c\n")
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
        # —— 顶回总数上限：Codex 平台不给顶回设硬上限，这道刹车只能围栏自己踩 ——
        with open(os.path.join(S, "tasks.md"), "w", encoding="utf-8") as f:
            f.write("- [ ] T01 a\n- [ ] T02 b\n")
        with open(flag, "w") as f:
            f.write("2,,0,6")  # 起点=第 2 轮、已顶回 6 次：下一次就撞上限
        code, d = stop_hook()
        check("C7 顶回累计到上限自动停批（摘 flag）",
              d.get("decision") == "block" and "安全上限" in d.get("reason", "")
              and not os.path.exists(flag))
        code, d = stop_hook()
        st_now = json.load(open(os.path.join(S, ".loopwork", "state.json"), encoding="utf-8"))
        check("C8 停机后下一轮无条件放行且计数归零（会话真能停下来）",
              code == 0 and not d and st_now.get("stop_blocks") == 0)

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

        # ---- 钩子代存档（pending_commit）----
        # 模型在沙箱里写不动 .git：它只登记意图，钩子（沙箱外）验完再落。
        # 这一组盯的是「验」这一半——什么该拒、拒了以后登记有没有清干净。
        PG = os.path.join(H, "progress.py")

        def pcommit(kind, msg):
            return run(["python3", PG, "commit", kind, msg], S, env)

        def head():
            return git("rev-parse", "HEAD").stdout.strip()

        def stjson():
            return json.load(open(os.path.join(S, ".loopwork", "state.json"), encoding="utf-8"))

        def exam(body="def test_x():\n    assert False\n"):
            with open(os.path.join(S, "tests", "exam_red.py"), "w", encoding="utf-8") as f:
                f.write(body)

        with open(os.path.join(S, "tests", "run.sh"), "w", encoding="utf-8") as f:
            f.write("exit 0\n")
        git("add", "-A"); git("commit", "-qm", "代存档测试起点")
        setp("stage", "4"); setp("phase", "test-writing"); setp("round_count", 0)
        setp("last_round_commit", head())
        h0 = head()

        code, d = stop_hook()
        check("G1 无 pending 时钩子不碰 git", code == 0 and not d and head() == h0, str(d)[:120])
        p = pcommit("blue", "存档: T9")
        check("G2 kind 只认 red/green", p.returncode == 1 and "red|green" in p.stderr,
              p.stderr[-120:])
        p = pcommit("red", "   ")
        check("G3 存档必须带一句话说明", p.returncode == 1 and "一句话" in p.stderr, p.stderr[-120:])
        exam()
        p = pcommit("red", "存档: T9 红考题")
        check("G4 登记只写 state，不自己碰 git",
              p.returncode == 0 and stjson().get("pending_commit", {}).get("kind") == "red"
              and head() == h0, (p.stdout + p.stderr)[-120:])
        os.makedirs(os.path.join(S, "src"), exist_ok=True)
        with open(os.path.join(S, "src", "app.py"), "w", encoding="utf-8") as f:
            f.write("x = 1\n")
        code, d = stop_hook()
        check("G5 红存档混进实现文件被拒，登记清空",
              d.get("decision") == "block" and "只该有考题" in d.get("reason", "")
              and "src/app.py" in d.get("reason", "")
              and head() == h0 and "pending_commit" not in stjson(), str(d)[:200])
        os.remove(os.path.join(S, "src", "app.py"))
        exam("KEY = '" + "sk-" + "A1b2C3d4" * 3 + "'\n")   # 假密钥拼出来：不把像密钥的字面量留在仓库里
        pcommit("red", "存档: T9 红考题")
        code, d = stop_hook()
        check("G6 疑似密钥命中被拒（内容层筛查）",
              d.get("decision") == "block" and "疑似密钥" in d.get("reason", "")
              and head() == h0 and "pending_commit" not in stjson(), str(d)[:200])
        exam()
        pcommit("green", "存档: T9 绿实现")
        code, d = stop_hook()
        check("G7 手里没有红存档票的绿存档被拒（先红后绿）",
              d.get("decision") == "block" and "没有过红存档" in d.get("reason", "")
              and head() == h0 and "pending_commit" not in stjson(), str(d)[:200])
        pcommit("red", "存档: T9 红考题")
        code, d = stop_hook()
        h1, st_a = head(), stjson()
        check("G8 红存档落地：基线自动前进 + 记下红票 + 单次顶回带 hash",
              d.get("decision") == "block" and "红存档已落" in d.get("reason", "")
              and h1[:10] in d.get("reason", "") and h1 != h0
              and st_a.get("last_round_commit") == h1 and st_a.get("red_commit_pending") is True
              and "pending_commit" not in st_a, str(d)[:200])
        with open(os.path.join(S, "src", "app.py"), "w", encoding="utf-8") as f:
            f.write("x = 1\n")   # 绿存档带的是实现——这次它就该跟着一起入库
        with open(os.path.join(S, "tests", "run.sh"), "w", encoding="utf-8") as f:
            f.write("exit 1\n")
        pcommit("green", "存档: T9 绿实现")
        code, d = stop_hook()
        check("G9 考题没全绿的绿存档被拒，红票不被吃掉",
              d.get("decision") == "block" and "verify.sh 不是 exit 0" in d.get("reason", "")
              and head() == h1 and stjson().get("red_commit_pending") is True, str(d)[:200])
        with open(os.path.join(S, "tests", "run.sh"), "w", encoding="utf-8") as f:
            f.write("exit 0\n")
        rounds_before = int(stjson().get("round_count", 0))
        pcommit("green", "存档: T9 绿实现")
        code, d = stop_hook()
        h2, st_b = head(), stjson()
        jr = open(os.path.join(S, "JOURNAL.md"), encoding="utf-8").read()
        check("G10 绿存档落地：verify 全绿 + 轮数 +1 + 日志一行 + 红票被消费",
              d.get("decision") == "block" and "绿存档已落" in d.get("reason", "")
              and h2 not in (h0, h1) and st_b.get("last_round_commit") == h2
              and int(st_b.get("round_count", 0)) == rounds_before + 1
              and st_b.get("red_commit_pending") is False
              and f"- [存档] {h2[:10]}" in jr, str(d)[:200])
        git("add", "-A"); git("commit", "-qm", "收尾")
        pcommit("red", "存档: T9 又一次")
        code, d = stop_hook()
        check("G11 只剩状态文件的存档被拒（空档不算数）",
              d.get("decision") == "block" and "空档" in d.get("reason", ""), str(d)[:200])
        with open(os.path.join(S, "tasks.md"), "w", encoding="utf-8") as f:
            f.write("- [x] T01 a\n- [x] T02 b\n- [ ] T03 c\n")
        exam("def test_y():\n    assert False\n")
        setp("batch_size", 5)
        open(flag, "w").close()
        pcommit("red", "存档: T10 红考题")
        code, d = stop_hook()
        check("G12 挂机时存档结果与批次顶回合并成同一次",
              d.get("decision") == "block" and "红存档已落" in d.get("reason", "")
              and "[挂机档]" in d.get("reason", ""), str(d)[:200])
        os.remove(flag)
        git("add", "-A"); git("commit", "-qm", "收尾 2")
        exam("def test_z():\n    assert False\n")
        pcommit("red", "存档: T11 红考题")
        gr = os.path.join(H, "guard_rules.py")
        os.replace(gr, gr + ".bak")
        h3 = head()
        code, d = stop_hook()
        check("G13 判定核心缺席时拒绝代存档（筛查缺席就不落档）",
              d.get("decision") == "block" and "判定核心" in d.get("reason", "")
              and head() == h3 and "pending_commit" not in stjson(), str(d)[:200])
        os.replace(gr + ".bak", gr)
        git("add", "-A"); git("commit", "-qm", "收尾 3")
        setp("last_round_commit", head())

        # 记事存档：阶段切换 / 登记 / 批末落盘用的杂项档，不是一轮 TDD。
        setp("red_commit_pending", "0")   # 手里先没有红票，才看得出记事存档发不发票
        h4 = head()
        with open(os.path.join(S, "spec.md"), "w", encoding="utf-8") as f:
            f.write("# 规格\n- 新增一条验收句\n")
        exam("def test_w():\n    assert False\n")
        pcommit("note", "存档: 阶段切换")
        code, d = stop_hook()
        check("G14 记事存档夹带考题被拒（考题只能走红存档）",
              d.get("decision") == "block" and "夹带了考题" in d.get("reason", "")
              and "tests/exam_red.py" in d.get("reason", "")
              and head() == h4 and "pending_commit" not in stjson(), str(d)[:200])
        git("checkout", "--", "tests/exam_red.py")   # 考题撤回，只留 spec.md 这条台账改动
        rounds_before = int(stjson().get("round_count", 0))
        pcommit("note", "存档: 阶段切换")
        code, d = stop_hook()
        h5, st_c = head(), stjson()
        check("G15 记事存档落地：基线前进，但不动轮数、不发红票",
              d.get("decision") == "block" and "记事存档已落" in d.get("reason", "")
              and h5[:10] in d.get("reason", "") and h5 != h4
              and st_c.get("last_round_commit") == h5
              and int(st_c.get("round_count", 0)) == rounds_before
              and not st_c.get("red_commit_pending"), str(d)[:200])
        with open(os.path.join(S, "spec.md"), "a", encoding="utf-8") as f:
            f.write("- 再来一条\n")
        pcommit("green", "存档: 想蒙混过关")
        code, d = stop_hook()
        check("G16 记事存档不发红票：紧跟其后的绿存档照样被拒",
              d.get("decision") == "block" and "没有过红存档" in d.get("reason", "")
              and head() == h5, str(d)[:200])
        git("add", "-A"); git("commit", "-qm", "收尾 4")
        setp("last_round_commit", head())

        # ---- L 系列：取证账本 blocks.jsonl（拦了什么要留痕，顶回时要说出来）----
        nline = lambda p: sum(1 for _ in open(p, encoding="utf-8")) if os.path.exists(p) else 0
        setp("stage", "1")      # 出循环阶段：检测门不插话，只看取证这一条线
        stop_hook()             # 先推平水位线，从干净起点数
        base = nline(BLK)
        gpre("Bash", "sed -i s/a/b/ spec.md", phase="implementing")
        gpre("apply_patch", patch("*** Update File: tests/exam.py"))
        rows = [json.loads(x) for x in open(BLK, encoding="utf-8").read().splitlines()
                if x.strip()][base:] if os.path.exists(BLK) else []
        check("L1 两次拦截留下两行取证，字段齐、相位对",
              len(rows) == 2 and all({"ts", "tool", "target", "rule", "phase"} <= set(r) for r in rows)
              and [r["phase"] for r in rows] == ["implementing"] * 2, str(rows)[:200])
        with open(os.path.join(S, "tasks.md"), "w", encoding="utf-8") as f:
            f.write("- [ ] T01 a\n- [ ] T02 b\n- [ ] T03 c\n")
        open(flag, "w").close()
        setp("round_count", 0); setp("batch_size", 2)
        code, d = stop_hook()
        check("L2 顶回理由带上本轮拦截数",
              d.get("decision") == "block" and "拦下 2 次" in d.get("reason", ""), str(d)[:200])
        setp("round_count", 1)
        code, d = stop_hook()
        check("L3 水位线已推进：同一批拦截不重复计入下一轮",
              d.get("decision") == "block" and "[取证]" not in d.get("reason", ""), str(d)[:200])
        os.remove(flag)

        # ---- T 系列：判卷预警 tripwire（绿灯不等于没作弊；只出声，不改判决）----
        # Codex 半边比 CC 版多一条：绿存档的 verify.sh 是钩子替模型跑的，模型看不见那段
        # 输出——预警必须被捎进顶回理由，否则这道预警等于没做。
        setp("stage", "4"); setp("phase", "implementing"); setp("stop_blocks", 0)
        git("add", "-A"); git("commit", "-qm", "tripwire 起点")
        v = run(["bash", os.path.join(H, "verify.sh")], S, env)
        check("T1 干净轮一声不吭（预警不制造噪音）",
              v.returncode == 0 and "判卷预警" not in v.stdout, v.stdout[-200:])
        with open(os.path.join(S, "tests", "exam_red.py"), "w", encoding="utf-8") as f:
            f.write("import pytest\n\n@pytest.mark.skip\ndef test_z():\n    pass\n")
        with open(os.path.join(S, "src", "app.py"), "w", encoding="utf-8") as f:
            f.write("# type: ignore\ndef f():\n    try:\n        return g()\n    except Exception:\n        pass\n")
        v = run(["bash", os.path.join(H, "verify.sh")], S, env)
        check("T2 四种作弊痕迹被逐条点名，且判决不变（还是 exit 0）",
              v.returncode == 0 and v.stdout.count("⚠️ 判卷预警：") == 4
              and all(k in v.stdout for k in ("抑制标记", "跳过考题", "吞异常", "删掉了")),
              v.stdout[-400:])
        git("checkout", "--", "tests/exam_red.py", "src/app.py")
        setp("phase", "test-writing"); setp("last_round_commit", head())
        exam("def test_t():\n    assert False\n")
        pcommit("red", "存档: T12 红考题")
        stop_hook()                      # 红票到手，基线随存档自动推进
        setp("phase", "implementing")
        with open(os.path.join(S, "src", "app.py"), "w", encoding="utf-8") as f:
            f.write("# type: ignore\ndef f():\n    try:\n        return g()\n    except Exception:\n        pass\n")
        pcommit("green", "存档: T12 绿实现")
        code, d = stop_hook()
        check("T3 绿存档的预警被捎回顶回理由（verify 是钩子跑的，不捎就没人看得见）",
              d.get("decision") == "block" and "绿存档已落" in d.get("reason", "")
              and all(k in d.get("reason", "") for k in ("判卷预警：", "抑制标记", "吞异常", "作弊清单")),
              str(d)[:300])
        git("add", "-A"); git("commit", "-qm", "tripwire 收尾")

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
