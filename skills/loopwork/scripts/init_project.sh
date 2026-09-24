#!/usr/bin/env bash
# Loopwork Codex 版建家脚本（幂等，重复跑安全）：
#   骨架 + git + 状态机 + 围栏进驻（hooks/rules/agents/AGENTS.md）+ .gitignore
# 用法: init_project.sh <项目目录> [项目名]
set -eu
: "${LANG:=en_US.UTF-8}"; export LANG
PROJ="${1:?用法: init_project.sh <项目目录> [项目名]}"
NAME="${2:-$(basename "$PROJ")}"
SKILL_DIR="$(cd "$(dirname "$0")/.." && pwd)"

mkdir -p "$PROJ/.loopwork/hooks" "$PROJ/.loopwork/logs" "$PROJ/tests" "$PROJ/.codex/rules" "$PROJ/.codex/agents"
cd "$PROJ"

# 1. git（存档系统）
if [ ! -d .git ] && [ ! -f .git ]; then git init -q; echo "[init] git 存档系统已开启"; fi

# 2. 机器进驻（以标准库为准，覆盖更新）
for f in guard_rules.py guard_log.py guard_pre.py stop_hook.py audit_log.py progress.py interrupt_log.py verify.sh selftest.sh; do
  cp -f "$SKILL_DIR/scripts/$f" ".loopwork/hooks/$f"
done
chmod +x .loopwork/hooks/*.sh .loopwork/hooks/*.py 2>/dev/null || true

# 3. 状态文件（已存在则不动）
if [ ! -f .loopwork/state.json ]; then
  NODE_V="$(command -v node >/dev/null 2>&1 && node --version || echo none)"
  PY_V="$(command -v python3 >/dev/null 2>&1 && python3 --version 2>&1 | cut -d' ' -f2 || echo none)"
  cat > .loopwork/state.json <<EOF
{
  "schema": 1,
  "stage": "0",
  "phase": "test-writing",
  "cycle": 1,
  "project_name": "$NAME",
  "round_count": 0,
  "round_cap": 20,
  "batch_size": 5,
  "last_round_commit": "",
  "milestones": [],
  "env": {"node": "$NODE_V", "python3": "$PY_V"}
}
EOF
  echo "[init] 状态文件已创建"
fi
[ -f JOURNAL.md ] || printf '# 工作日志（每轮一行）\n\n' > JOURNAL.md
[ -f BLOCKED.md ] || printf '# 问题本（要用户拍板的事）\n\n' > BLOCKED.md

# 4. Codex 钩子接线：项目级 .codex/hooks.json（幂等合并）
# Codex 按定义哈希逐条信任钩子：hooks.json 内容一变，之前的信任就作废、围栏静默不跑。先记指纹，变了就提醒。
HJ_MD5_BEFORE="$(python3 -c 'import hashlib,sys; print(hashlib.md5(open(sys.argv[1],"rb").read()).hexdigest())' .codex/hooks.json 2>/dev/null || true)"
python3 - <<'PYEOF'
import json, os
p = ".codex/hooks.json"
cfg = {}
if os.path.exists(p):
    with open(p, encoding="utf-8") as f:
        try: cfg = json.load(f)
        except Exception: cfg = {}
hooks = cfg.setdefault("hooks", {})
# 顶层 description 是 hooks.json 的可选元数据（官方文档：不影响哪些钩子会跑），给翻这个文件的人一句交代
cfg.setdefault("description", "Loopwork：实时围栏 / 轮末检测门与代存档 / 审计与心跳 / 中断记录（init_project.sh 生成，幂等合并）")
def cmd(c): return {"type": "command", "command": c}
# 钩子命令锚定项目根：Codex 用登录 shell（$SHELL -lc）跑钩子命令，工作目录是会话当前目录
# （可能是子目录），所以用 $(git rev-parse --show-toplevel) 现算根，不再赌「以项目根为工作目录」。
# 本脚本已保证项目根就是 git 根（没有 .git 就 git init）；git 不在时退回 pwd（老行为）。
ROOT_EXPR = '$(git rev-parse --show-toplevel 2>/dev/null || pwd)'
def hook(script, args="", **extra):
    h = cmd('python3 "' + ROOT_EXPR + '/.loopwork/hooks/' + script + '"' + args)
    h.update(extra)
    return h
# PreToolUse 不写 matcher：Codex 侧 matcher 的 schema 没实测过，宁可全量收进来，
# 由 guard_pre.py 自己按 tool_name 分派——没见过的工具放行并记账，不会误伤。
# timeout / statusMessage 是 Codex hooks 的可选字段（官方文档，2026-09 核实；timeout 单位秒，缺省 600）：
#   Stop 400s——它代跑 verify.sh（自身 300s 保险丝、VERIFY_TIMEOUT 330s），写成显式数字是让依据可见；
#   PreToolUse 20s——纯函数判定，卡到 20s 一定是环境坏了，别拖住每一次工具调用；
#   Interrupt 平台硬上限 3s、只许无输出或 JSON——interrupt_log.py 只记一行、什么都不打印。
WANT = {
    "PreToolUse":   [{"hooks": [hook("guard_pre.py", timeout=20, statusMessage="Loopwork 围栏检查…")]}],
    "SessionStart": [{"hooks": [hook("progress.py", " card")]}],
    "Stop":         [{"hooks": [hook("stop_hook.py", timeout=400, statusMessage="Loopwork 检测门 / 代存档…")]}],
    "PostToolUse":  [{"hooks": [hook("audit_log.py")]}],
    "Interrupt":    [{"hooks": [hook("interrupt_log.py", timeout=3)]}],
}
def sig(x): return json.dumps(x, sort_keys=True, ensure_ascii=False)
for event, entries in WANT.items():
    have = hooks.setdefault(event, [])
    want_sigs = {sig(e) for e in entries}
    # 升级去重：旧版本的接线（同样指向 .loopwork/hooks/ 但签名过期）先清掉，
    # 防止新旧两条并存、同一事件钩子跑两遍；用户自己的钩子（不含该路径）原样保留
    have[:] = [h for h in have if sig(h) in want_sigs or ".loopwork/hooks/" not in sig(h)]
    for e in entries:
        if sig(e) not in {sig(h) for h in have}:
            have.append(e)
with open(p, "w", encoding="utf-8") as f:
    json.dump(cfg, f, ensure_ascii=False, indent=2)
print("[init] Codex 钩子已接线 (.codex/hooks.json：PreToolUse / SessionStart / Stop / PostToolUse / Interrupt)")
PYEOF
HJ_MD5_AFTER="$(python3 -c 'import hashlib,sys; print(hashlib.md5(open(sys.argv[1],"rb").read()).hexdigest())' .codex/hooks.json 2>/dev/null || true)"
if [ "$HJ_MD5_BEFORE" != "$HJ_MD5_AFTER" ]; then
  echo "[init] ⚠️ .codex/hooks.json 有变动：Codex 按定义哈希信任钩子，请在 TUI 里 /hooks 重新信任（已信任过的项目也要）"
fi

# 5. 规则层：危险命令 forbidden / 敏感改写 prompt（Starlark，前缀规则）
if [ ! -f .codex/rules/loopwork.rules ]; then
  cat > .codex/rules/loopwork.rules <<'EOF'
# Loopwork 安全规则（项目级；需项目被信任后生效）
prefix_rule(pattern=["rm", "-rf"], decision="forbidden", justification="删除必须先问用户，用精确路径")
prefix_rule(pattern=["rm", "-fr"], decision="forbidden", justification="同上")
prefix_rule(pattern=["rm", "-r", "-f"], decision="forbidden", justification="同上")
prefix_rule(pattern=["rm", "-f", "-r"], decision="forbidden", justification="同上")
prefix_rule(pattern=["git", "push", "--force"], decision="forbidden", justification="会抹掉远端历史，必须用户亲自决定")
prefix_rule(pattern=["git", "push", "-f"], decision="forbidden", justification="同上")
prefix_rule(pattern=["git", "reset", "--hard"], decision="prompt", justification="会丢弃未存档工作，需确认")
prefix_rule(pattern=["chmod", "777"], decision="forbidden", justification="不做全开权限")
prefix_rule(pattern=["sed", "-i"], decision="prompt", justification="就地改写文件，围栏要求确认目标不是考题/规格")
# 前缀规则按 argv 逐词匹配——sudo 前缀和长旗标写法是另一条命令，必须显式列出
prefix_rule(pattern=["sudo", "rm", "-rf"], decision="forbidden", justification="sudo 前缀不豁免删除禁令")
prefix_rule(pattern=["sudo", "rm", "-fr"], decision="forbidden", justification="同上")
prefix_rule(pattern=["rm", "--recursive", "--force"], decision="forbidden", justification="长旗标写法同样禁止")
prefix_rule(pattern=["rm", "--force", "--recursive"], decision="forbidden", justification="同上")
prefix_rule(pattern=["sudo", "git", "push", "--force"], decision="forbidden", justification="sudo 前缀不豁免强推禁令")
prefix_rule(pattern=["sudo", "chmod", "777"], decision="forbidden", justification="sudo 前缀不豁免权限禁令")
# 改历史 / 销毁证据：Loopwork 的存档只增不减，改得动的历史不算证据
prefix_rule(pattern=["git", "commit", "--amend"], decision="forbidden", justification="改写已有存档等于抹掉证据，要修正就再存一档")
prefix_rule(pattern=["git", "rebase"], decision="forbidden", justification="重排历史会让基线存档凭空消失，检测门会判假历史并停机")
prefix_rule(pattern=["git", "filter-branch"], decision="forbidden", justification="同上，批量伪造历史")
prefix_rule(pattern=["git", "filter-repo"], decision="forbidden", justification="同上，批量伪造历史")
prefix_rule(pattern=["git", "update-ref"], decision="forbidden", justification="直接改引用 = 手工伪造历史")
prefix_rule(pattern=["git", "stash"], decision="forbidden", justification="把改动藏进不在存档里的暗格；藏起来的不算证据")
prefix_rule(pattern=["git", "clean"], decision="forbidden", justification="批量删未跟踪文件，git 里也找不回来——要删就点名删单个文件")
prefix_rule(pattern=["sudo", "git", "commit", "--amend"], decision="forbidden", justification="sudo 前缀不豁免改历史禁令")
prefix_rule(pattern=["sudo", "git", "rebase"], decision="forbidden", justification="同上")
prefix_rule(pattern=["sudo", "git", "filter-branch"], decision="forbidden", justification="同上")
prefix_rule(pattern=["sudo", "git", "filter-repo"], decision="forbidden", justification="同上")
prefix_rule(pattern=["sudo", "git", "update-ref"], decision="forbidden", justification="同上")
prefix_rule(pattern=["sudo", "git", "stash"], decision="forbidden", justification="同上")
prefix_rule(pattern=["sudo", "git", "clean"], decision="forbidden", justification="同上")
EOF
  echo "[init] 安全规则已写入 (.codex/rules/loopwork.rules)"
else
  # 旧版规则文件：缺哪块补哪块，只追加，不动用户可能加过的自定义规则
  if ! grep -qF 'pattern=["sudo", "rm", "-rf"]' .codex/rules/loopwork.rules; then
    cat >> .codex/rules/loopwork.rules <<'EOF'

# 前缀规则按 argv 逐词匹配——sudo 前缀和长旗标写法是另一条命令，必须显式列出（升级追加）
prefix_rule(pattern=["sudo", "rm", "-rf"], decision="forbidden", justification="sudo 前缀不豁免删除禁令")
prefix_rule(pattern=["sudo", "rm", "-fr"], decision="forbidden", justification="同上")
prefix_rule(pattern=["rm", "--recursive", "--force"], decision="forbidden", justification="长旗标写法同样禁止")
prefix_rule(pattern=["rm", "--force", "--recursive"], decision="forbidden", justification="同上")
prefix_rule(pattern=["sudo", "git", "push", "--force"], decision="forbidden", justification="sudo 前缀不豁免强推禁令")
prefix_rule(pattern=["sudo", "chmod", "777"], decision="forbidden", justification="sudo 前缀不豁免权限禁令")
EOF
    echo "[init] 安全规则已升级（追加 sudo/长旗标条目）"
  fi
  if ! grep -qF 'pattern=["git", "commit", "--amend"]' .codex/rules/loopwork.rules; then
    cat >> .codex/rules/loopwork.rules <<'EOF'

# 改历史 / 销毁证据：存档只增不减，改得动的历史不算证据（升级追加）
prefix_rule(pattern=["git", "commit", "--amend"], decision="forbidden", justification="改写已有存档等于抹掉证据，要修正就再存一档")
prefix_rule(pattern=["git", "rebase"], decision="forbidden", justification="重排历史会让基线存档凭空消失，检测门会判假历史并停机")
prefix_rule(pattern=["git", "filter-branch"], decision="forbidden", justification="同上，批量伪造历史")
prefix_rule(pattern=["git", "filter-repo"], decision="forbidden", justification="同上，批量伪造历史")
prefix_rule(pattern=["git", "update-ref"], decision="forbidden", justification="直接改引用 = 手工伪造历史")
prefix_rule(pattern=["git", "stash"], decision="forbidden", justification="把改动藏进不在存档里的暗格；藏起来的不算证据")
prefix_rule(pattern=["git", "clean"], decision="forbidden", justification="批量删未跟踪文件，git 里也找不回来——要删就点名删单个文件")
prefix_rule(pattern=["sudo", "git", "commit", "--amend"], decision="forbidden", justification="sudo 前缀不豁免改历史禁令")
prefix_rule(pattern=["sudo", "git", "rebase"], decision="forbidden", justification="同上")
prefix_rule(pattern=["sudo", "git", "filter-branch"], decision="forbidden", justification="同上")
prefix_rule(pattern=["sudo", "git", "filter-repo"], decision="forbidden", justification="同上")
prefix_rule(pattern=["sudo", "git", "update-ref"], decision="forbidden", justification="同上")
prefix_rule(pattern=["sudo", "git", "stash"], decision="forbidden", justification="同上")
prefix_rule(pattern=["sudo", "git", "clean"], decision="forbidden", justification="同上")
EOF
    echo "[init] 安全规则已升级（追加改历史/销毁证据条目）"
  fi
fi

# 6. 只读判卷员（原生只读子代理定义）。developer_instructions 让代理自己就知道职责与格式，
#    不再全靠主代理记得把 reviewer.md 正文贴过来。老版只有 3 行没这个字段——文件全是 init
#    生成的、没有用户内容，缺字段就整体重写（原地升级），有就不动。
if [ ! -f .codex/agents/loopwork-reviewer.toml ] \
   || ! grep -q '^developer_instructions' .codex/agents/loopwork-reviewer.toml; then
  cat > .codex/agents/loopwork-reviewer.toml <<'EOF'
name = "loopwork-reviewer"
description = "Loopwork 只读判卷员：两段式审查（合规+质量），只看不改"
sandbox_mode = "read-only"
developer_instructions = """
你是 Loopwork 的只读判卷员（loopwork-reviewer）。只看不改：绝不修改任何文件；shell 只用于跑
`bash .loopwork/hooks/verify.sh` 和只读 git 命令（status / diff / log / show）。沙箱是 read-only，
但纪律不靠沙箱——发现自己想改代码，就停下来把它写进报告。
完整任务指令是 skill 目录下的 references/reviewer.md（主代理派你时会把正文一并交给你；没交就先索要）。
按它的四段式审：第一段 · 合规（对得上 spec？碰过红线？）→ 第二段 · 质量（🔴 / 🟡 / ⚪）
→ 第三段 · 作弊清单（八条逐条过）→ 第四段 · 考题盲区（两问必答）。
最后按固定格式交卷：判卷结论 / N 对 M / 考题 / 红线 / 问题 / 作弊清单 / 考题盲区 / 还漏了什么 / 给用户的一句话。
"""
EOF
  echo "[init] 只读判卷员已注册/升级 (.codex/agents/loopwork-reviewer.toml)"
fi

# 7. 项目根 AGENTS.md 锚点（不存在才写；存在则不动用户内容）
if [ ! -f AGENTS.md ]; then
  cat > AGENTS.md <<EOF
# ${NAME} —— 本项目由 Loopwork 循环工作法管理

任何会话开始：先读 \`.loopwork/state.json\`（或跑 \`python3 .loopwork/hooks/progress.py card\`），
按 loopwork skill 的点火路由续接。不凭记忆猜进度。

铁律指针（完整版在 loopwork skill）：
1. 考题先红后绿；实现期间绝不改 tests/、spec.md、rules.md
2. 勾选不是证据，存档才是——存档不由你执行，你只登记：
   \`python3 .loopwork/hooks/progress.py commit red|green|note "存档: …"\`，
   轮末钩子验过（密钥筛查 / 只许考题 / verify 全绿）才落 commit 并自动推进基线；
   下一轮看到「[代存档] …已落 <hash>」才算存住，看到「拒绝」就按理由重新登记
3. 花钱/删除/发布/改规矩/密钥 五类动作无条件先问用户
4. 要拍板的事写 BLOCKED.md 跳过，不停机干等
5. 永不宣布「项目完成」，清单空了 = 该续单了
EOF
  echo "[init] AGENTS.md 锚点已创建"
fi

# 8. .gitignore
touch .gitignore
for line in ".env" "*.local" ".loopwork/logs/" ".loopwork/batch.flag" ".loopwork/scratch/" "node_modules/" "__pycache__/"; do
  grep -qxF "$line" .gitignore || echo "$line" >> .gitignore
done

# 9. 首次存档（git 身份兜底，不碰全局）
git config user.name  >/dev/null 2>&1 || git config user.name "Loopwork User"
git config user.email >/dev/null 2>&1 || git config user.email "loopwork@local"
if ! git rev-parse HEAD >/dev/null 2>&1; then
  git add -A
  # 首次存档前的密钥筛查：疑似密钥文件剔出存档并提醒（密钥入库是最难撤销的事故之一）
  SUS="$(git diff --cached --name-only | grep -iE '(^|/)\.env(\.|$)|\.pem$|\.p12$|\.key$|(^|/)(secrets?|credentials?)\.' || true)"
  if [ -n "$SUS" ]; then
    printf '%s\n' "$SUS" | while IFS= read -r f; do git rm --cached -q -- "$f" || true; done
    echo "[init] ⚠️ 疑似密钥文件已剔出首次存档（确认安全后再自行决定是否入库）："
    printf '%s\n' "$SUS" | sed 's/^/         - /'
  fi
  git commit -qm "存档: Loopwork 项目初始化"
  echo "[init] 首次存档完成"
fi

echo "[init] ✅ 「${NAME}」建家完成：git + 状态机 + 实时围栏(PreToolUse) + 轮末检测门/代存档 + 审计/心跳 + 中断记录 + 规则 + 判卷员 + AGENTS.md"
echo "[init] 提醒：项目级规则/钩子需要 Codex 信任本项目后生效——首次在此项目使用 Codex 时请选择信任；钩子另按定义哈希逐条信任，hooks.json 每变一次都要回 TUI /hooks 重新审核（selftest 第 [7] 项会记指纹提醒）。"
