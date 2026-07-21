#!/usr/bin/env bash
# Loopwork 验收裁判：跑考题，exit code 说了算。
# 0=全绿；非 0=不通过。找不到考题运行方式 => exit 3（fail closed：不确定 = 不通过）。
set -u
ROOT="${CLAUDE_PROJECT_DIR:-$(pwd)}"
cd "$ROOT" || exit 3
mkdir -p .loopwork/logs
LOG=".loopwork/logs/verify-$(date +%Y%m%d-%H%M%S).log"

run() { # run <描述> <命令...>
  echo "[verify] $1" | tee -a "$LOG"
  shift
  "$@" >>"$LOG" 2>&1
  local code=$?
  if [ $code -eq 0 ]; then
    echo "[verify] ✅ 全绿 (exit 0) — 日志: $LOG"
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
