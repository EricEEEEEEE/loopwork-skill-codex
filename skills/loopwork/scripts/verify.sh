#!/usr/bin/env bash
# Loopwork 验收裁判：跑考题，exit code 说了算。
# 0=全绿；非 0=不通过。找不到考题运行方式 => exit 3（fail closed：不确定 = 不通过）。
# 考题挂住（交互等待/watch 模式）=> 超时保险强制终止，exit 124（默认 300s，LOOPWORK_VERIFY_TIMEOUT 可调）。
set -u
ROOT="${CLAUDE_PROJECT_DIR:-${CODEX_PROJECT_DIR:-$(pwd)}}"
cd "$ROOT" || exit 3
mkdir -p .loopwork/logs
# 日志只留最近 20 份（含本次），防跑几百轮后把仓库塞满
ls -t .loopwork/logs/verify-*.log 2>/dev/null | tail -n +20 | while IFS= read -r old; do rm -f "$old"; done
LOG=".loopwork/logs/verify-$(date +%Y%m%d-%H%M%S).log"
TIMEOUT_S="${LOOPWORK_VERIFY_TIMEOUT:-300}"
export CI=true   # 测试框架一律走非交互模式（jest/vitest 据此关掉 watch）

run() { # run <描述> <命令...>
  echo "[verify] $1（超时上限 ${TIMEOUT_S}s）" | tee -a "$LOG"
  shift
  # macOS 没有 GNU timeout，用 python3 做便携超时；进程组整组收割，防测试框架留孤儿
  python3 - "$TIMEOUT_S" "$@" >>"$LOG" 2>&1 <<'PYEOF'
import os, signal, subprocess, sys
limit = float(sys.argv[1])
try:
    p = subprocess.Popen(sys.argv[2:], start_new_session=True)
except FileNotFoundError as e:
    print(f"[verify] 命令不存在: {e}", flush=True)
    sys.exit(127)
try:
    sys.exit(p.wait(timeout=limit))
except subprocess.TimeoutExpired:
    try:
        os.killpg(os.getpgid(p.pid), signal.SIGKILL)
    except Exception:
        p.kill()
    print(f"[verify] 考题运行超过 {int(limit)}s 被强制终止——多半卡在交互等待或 watch 模式。", flush=True)
    sys.exit(124)
PYEOF
  local code=$?
  if [ $code -eq 0 ]; then
    echo "[verify] ✅ 全绿 (exit 0) — 日志: $LOG"
  elif [ $code -eq 124 ]; then
    echo "[verify] ⏰ 超时 (exit 124) — 考题挂住了，按不通过处理。最后 20 行："
    tail -20 "$LOG"
  else
    echo "[verify] ❌ 不通过 (exit $code) — 最后 20 行："
    tail -20 "$LOG"
  fi
  return $code
}

# 判卷预警（tripwire）：绿灯不等于没作弊。扫本轮还没入库的改动，找几种「让考题闭嘴」
# 的机械痕迹——只出声，绝不改 exit code。
#
# 为什么不做成闸门：公开抽样的 327 个 agent PR 里，自动探测器对野生作弊的独立命中是
# 0/27（同一套规则在人工种下的样本上却有 92.6%）。这类规则擅长抓自己见过的花样，
# 对真事基本睁眼瞎；拿它当硬闸门，收的只会是误报停机。闸门是判卷员和用户的眼睛，
# 这里只负责把放大镜递过去。清单与出处见判卷员指令 reviewer.md。
tripwire() {
  git rev-parse --verify HEAD >/dev/null 2>&1 || return 0
  local d; d="$(git diff HEAD 2>/dev/null)"
  [ -n "$d" ] || return 0
  local out="" n m phase files h
  n=$(printf '%s\n' "$d" | grep -Ec '^\+[^+].*(@ts-ignore|@ts-expect-error|eslint-disable|type: *ignore|noqa|#\[allow\(|nolint)')
  [ "$n" -gt 0 ] && out="${out}新增 $n 处抑制标记（ts-ignore / eslint-disable / type: ignore / noqa …）——被压住的那句检查原本在说什么？"$'\n'
  n=$(printf '%s\n' "$d" | grep -Ec '^\+[^+].*(pytest\.mark\.(skip|xfail)|unittest\.skip|\.(skip|todo)\(|xit\(|xdescribe\(|t\.Skip\(|#\[ignore\])')
  [ "$n" -gt 0 ] && out="${out}新增 $n 处跳过考题的标记（skip / xfail / todo …）——被跳过的那道题，本来是这轮该做的吗？"$'\n'
  n=$(printf '%s\n' "$d" | grep -Ec '^\+[^+].*(catch *(\([^)]*\))? *\{ *\}|except[^:]*: *(pass|continue))')
  m=$(printf '%s\n' "$d" | grep -E -A1 '^\+[^+].*except' | grep -Ec '^\+[[:space:]]*(pass|continue)[[:space:]]*$')
  [ $((n + m)) -gt 0 ] && out="${out}新增 $((n + m)) 处吞异常的写法（except: pass / catch {}）——错误被咽下去，考题当然不红。"$'\n'
  n=$(printf '%s\n' "$d" | grep -Ec '^-[^-].*(assert|expect\(|\.to(Be|Equal)|should\.)')
  [ "$n" -gt 0 ] && out="${out}删掉了 $n 行断言——搬家就说清楚搬到哪了；删题的话，这盏绿灯不算数。"$'\n'
  files=$(git diff HEAD --name-only 2>/dev/null)
  phase=$(sed -n 's/.*"phase"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' .loopwork/state.json 2>/dev/null | head -1)
  if [ "$phase" = "implementing" ] && [ -n "$files" ] &&
     ! printf '%s\n' "$files" | grep -Ev '(^tests/|(^|/)test_|_test\.|\.spec\.|\.test\.|^\.loopwork/)' | grep -q .; then
    out="${out}实现期里没入库的改动只碰了考题，一行实现都没动——这盏绿灯是改考题改出来的吗？"$'\n'
  fi
  [ -n "$out" ] || return 0
  echo "[verify] ── 判卷预警：绿灯不等于没作弊，下面的痕迹请当面说清楚 ──"
  printf '%s' "$out" | while IFS= read -r h; do echo "[verify] ⚠️ 判卷预警：$h"; done
  echo "[verify]    痕迹不是判决：正当重构也会命中，真作弊也可能一条都不命中。"
  echo "[verify]    逐条给理由，或者改回去——判卷员会照作弊清单（reviewer.md）逐条核对。"
  return 0
}

# 探测考题运行方式：tests/run.sh 是项目自己的总裁判（只跑它）；
# 没有总裁判时，探测到的栈全部要跑、全部要绿——只跑第一个会漏掉混合项目的另一半考题。
if [ -f tests/run.sh ]; then
  run "tests/run.sh" bash tests/run.sh; code=$?; tripwire; exit $code
fi

RAN=0; FINAL=0
note() { RAN=$((RAN+1)); if [ "$1" -ne 0 ] && [ "$FINAL" -eq 0 ]; then FINAL=$1; fi; }

if [ -f package.json ] && grep -q '"test"' package.json; then
  run "npm test" npm test --silent; note $?
fi
if [ -d tests ] && ls tests/*.py >/dev/null 2>&1; then
  if command -v pytest >/dev/null 2>&1; then
    run "pytest" pytest -q tests; note $?
  else
    run "python unittest" python3 -m unittest discover -s tests
    code=$?
    # fail closed：discover 找到 0 个测试时 unittest 也报 exit 0，这是假绿
    if [ $code -eq 0 ] && grep -q "Ran 0 tests" "$LOG"; then
      echo "[verify] ⚠️ unittest 发现 0 个测试（假绿），按不通过处理。"
      code=3
    fi
    note $code
  fi
fi
if [ -f go.mod ]; then
  run "go test" go test ./...; note $?
fi
if [ -f Cargo.toml ]; then
  run "cargo test" cargo test --quiet; note $?
fi

if [ "$RAN" -eq 0 ]; then
  echo "[verify] ⚠️ 未找到考题运行方式（fail closed，按不通过处理）。" | tee -a "$LOG"
  echo "         需要先建立考题体系：npm test / pytest / go test / cargo test / tests/run.sh 任一即可。"
  exit 3
fi
if [ "$FINAL" -eq 0 ]; then
  echo "[verify] ✅ 共 ${RAN} 个测试栈全部通过"
else
  echo "[verify] ❌ ${RAN} 个测试栈中有失败（首个失败 exit ${FINAL}）"
fi
tripwire
exit $FINAL
