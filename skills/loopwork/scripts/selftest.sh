#!/usr/bin/env bash
# Loopwork Codex 版 · 装机自检（零模型调用，约 30 秒）
# 探测本机 Codex 的真实能力面，输出哪些围栏层可用。随版本升级重跑即可。
set -u
: "${LANG:=en_US.UTF-8}"; export LANG
CODEX_BIN="${CODEX_BIN:-$(command -v codex || echo "/Applications/ChatGPT.app/Contents/Resources/codex")}"
T="$(mktemp -d)"; trap 'rm -r "$T" 2>/dev/null' EXIT
PASS=0; WARN=0

say()  { printf '%s\n' "$*"; }
ok()   { say "  ✅ $*"; PASS=$((PASS+1)); }
warn() { say "  ⚠️  $*"; WARN=$((WARN+1)); }

say "== Loopwork Codex 装机自检 =="
if [ ! -x "$CODEX_BIN" ]; then
  warn "找不到 codex 可执行文件（设 CODEX_BIN 环境变量后重跑）"; exit 1
fi

say "[1] 版本"
V="$("$CODEX_BIN" --version 2>/dev/null || echo unknown)"
ok "$V"

say "[2] skills 扫描路径"
[ -d "$HOME/.codex/skills" ]  && ok "~/.codex/skills 存在（旧路径，当前多数安装仍生效）" || warn "~/.codex/skills 不存在"
[ -d "$HOME/.agents/skills" ] && ok "~/.agents/skills 存在（新开放标准路径）" || warn "~/.agents/skills 不存在（新路径未启用；建议双写安装）"

say "[3] 沙箱工作区边界（OS 级物理墙）"
mkdir -p "$T/ws/src" && cd "$T/ws"
if "$CODEX_BIN" sandbox -c 'sandbox_mode="workspace-write"' -- bash -c "echo x > src/in.txt" >/dev/null 2>&1 && [ -f src/in.txt ]; then
  ok "工作区内可写"
else
  warn "工作区内写入失败（sandbox 异常）"
fi
# 注意：/tmp 与 \$TMPDIR 在 workspace-write 下默认可写（官方设计如此），
# 探针必须用真正的外部路径（\$HOME 下无害临时名），否则会误报。
PROBE="$HOME/.loopwork_selftest_probe_$$.tmp"
if "$CODEX_BIN" sandbox -c 'sandbox_mode="workspace-write"' -- bash -c "echo x > '$PROBE'" >/dev/null 2>&1 && [ -f "$PROBE" ]; then
  rm -f "$PROBE"
  warn "工作区外写入未被拦截！沙箱边界失效，请勿挂机使用"
else
  ok "工作区外写入被 OS 拒绝（边界物理墙有效；/tmp 可写属设计预期）"
fi

say "[4] 具名 Permission Profile（子路径只读——可用则围栏自动升级）"
mkdir -p "$T/home" "$T/ws/tests"
cat > "$T/home/config.toml" <<'EOF'
default_permissions = "lw"
[permissions.lw.filesystem.":workspace_roots"]
"." = "write"
"tests" = "read"
EOF
OUT="$(cd "$T/ws" && CODEX_HOME="$T/home" "$CODEX_BIN" sandbox -- bash -c 'echo probe > tests/p.txt && echo WRITABLE || echo DENIED' 2>&1)"; CODE=$?
if [ $CODE -ne 0 ]; then
  warn "profile 配置无法运行（exit $CODE，本版本 schema 不可用/崩溃）——维持降级围栏（规则+检测门）"
elif echo "$OUT" | grep -q DENIED; then
  ok "profile 生效：tests/ 只读被 OS 强制！可在 config 启用具名 profile 升级围栏"
elif [ -f "$T/ws/tests/p.txt" ]; then
  warn "profile 已解析但未强制（tests/ 仍可写）——维持降级围栏"
else
  warn "profile 行为不明（无输出）——维持降级围栏"
fi

say "[5] 钩子生效性（需交互验证的部分）"
say "     Stop 检测门与挂机档依赖 .codex/hooks.json——非交互模式下无法自动验证。"
say "     首次使用时请在交互会话里跑一轮任务，确认轮末能看到检测门/挂机档的提示；"
say "     没看到 → 检查项目信任状态（Codex 需信任本项目的 .codex/ 层）。"

say ""
say "== 自检完成：$PASS 项通过，$WARN 项警告 =="
say "警告不代表不能用：Loopwork 的验收纪律（verify.sh exit code + 存档对账）不依赖上述任何一层。"
