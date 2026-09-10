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
if [ ! -d .git ]; then git init -q; echo "[init] git 存档系统已开启"; fi

# 2. 机器进驻（以标准库为准，覆盖更新）
for f in stop_hook.py audit_log.py progress.py verify.sh; do
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
python3 - <<'PYEOF'
import json, os
p = ".codex/hooks.json"
cfg = {}
if os.path.exists(p):
    with open(p, encoding="utf-8") as f:
        try: cfg = json.load(f)
        except Exception: cfg = {}
hooks = cfg.setdefault("hooks", {})
def cmd(c): return {"type": "command", "command": c}
WANT = {
    "SessionStart": [{"hooks": [cmd("python3 .loopwork/hooks/progress.py card")]}],
    "Stop":         [{"hooks": [cmd("python3 .loopwork/hooks/stop_hook.py")]}],
    "PostToolUse":  [{"hooks": [cmd("python3 .loopwork/hooks/audit_log.py")]}],
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
print("[init] Codex 钩子已接线 (.codex/hooks.json)")
PYEOF

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

# 6. 只读判卷员（原生只读子代理定义）
if [ ! -f .codex/agents/loopwork-reviewer.toml ]; then
  cat > .codex/agents/loopwork-reviewer.toml <<'EOF'
name = "loopwork-reviewer"
description = "Loopwork 只读判卷员：两段式审查（合规+质量），只看不改"
sandbox_mode = "read-only"
EOF
  echo "[init] 只读判卷员已注册 (.codex/agents/loopwork-reviewer.toml)"
fi

# 7. 项目根 AGENTS.md 锚点（不存在才写；存在则不动用户内容）
if [ ! -f AGENTS.md ]; then
  cat > AGENTS.md <<EOF
# ${NAME} —— 本项目由 Loopwork 循环工作法管理

任何会话开始：先读 \`.loopwork/state.json\`（或跑 \`python3 .loopwork/hooks/progress.py card\`），
按 loopwork skill 的点火路由续接。不凭记忆猜进度。

铁律指针（完整版在 loopwork skill）：
1. 考题先红后绿；实现期间绝不改 tests/、spec.md、rules.md
2. 勾选不是证据，存档才是——每完成一条任务 git commit + 更新基线
3. 花钱/删除/发布/改规矩/密钥 五类动作无条件先问用户
4. 要拍板的事写 BLOCKED.md 跳过，不停机干等
5. 永不宣布「项目完成」，清单空了 = 该续单了
EOF
  echo "[init] AGENTS.md 锚点已创建"
fi

# 8. .gitignore
touch .gitignore
for line in ".env" "*.local" ".loopwork/logs/" ".loopwork/batch.flag" "node_modules/" "__pycache__/"; do
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

echo "[init] ✅ 「${NAME}」建家完成：git + 状态机 + Codex 钩子 + 规则 + 判卷员 + AGENTS.md"
echo "[init] 提醒：项目级规则/钩子需要 Codex 信任本项目后生效——首次在此项目使用 Codex 时请选择信任。"
