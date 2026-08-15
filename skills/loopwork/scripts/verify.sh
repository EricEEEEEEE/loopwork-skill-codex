#!/usr/bin/env bash
# Loopwork 验收裁判：跑考题，exit code 说了算。
# 0=全绿；非 0=不通过。找不到考题运行方式 => exit 3（fail closed：不确定 = 不通过）。
# 考题挂住（交互等待/watch 模式）=> 超时保险强制终止，exit 124（默认 300s，LOOPWORK_VERIFY_TIMEOUT 可调）。
set -u
ROOT="${CLAUDE_PROJECT_DIR:-${CODEX_PROJECT_DIR:-$(pwd)}}"
cd "$ROOT" || exit 3
mkdir -p .loopwork/logs
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

# 按项目类型探测考题运行方式（显式入口优先，找到第一个匹配即用）
if [ -f tests/run.sh ]; then
  run "tests/run.sh" bash tests/run.sh; exit $?
elif [ -f package.json ] && grep -q '"test"' package.json; then
  run "npm test" npm test --silent; exit $?
elif [ -d tests ] && ls tests/*.py >/dev/null 2>&1; then
  if command -v pytest >/dev/null 2>&1; then
    run "pytest" pytest -q tests; exit $?
  else
    run "python unittest" python3 -m unittest discover -s tests
    code=$?
    # fail closed：discover 找到 0 个测试时 unittest 也报 exit 0，这是假绿
    if [ $code -eq 0 ] && grep -q "Ran 0 tests" "$LOG"; then
      echo "[verify] ⚠️ unittest 发现 0 个测试（假绿），按不通过处理。"
      exit 3
    fi
    exit $code
  fi
elif [ -f go.mod ]; then
  run "go test" go test ./...; exit $?
elif [ -f Cargo.toml ]; then
  run "cargo test" cargo test --quiet; exit $?
fi

echo "[verify] ⚠️ 未找到考题运行方式（fail closed，按不通过处理）。" | tee -a "$LOG"
echo "         需要先建立考题体系：npm test / pytest / go test / cargo test / tests/run.sh 任一即可。"
exit 3
