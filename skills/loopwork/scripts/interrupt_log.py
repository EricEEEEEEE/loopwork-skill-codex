#!/usr/bin/env python3
"""Loopwork Codex 版 · Interrupt 钩子（用户打断主线程时触发）。只记录，不干预：
追加一行 {ts, session_id, cwd} 到 .loopwork/logs/interrupts.jsonl，进度卡显示「上次人为中断」。
不摘 batch.flag——误触 Ctrl-C 不该悄悄结束一批；停批仍只归用户（删 .loopwork/batch.flag）和轮末钩子。
平台约束（官方文档，2026-09 核实）：Interrupt 钩子缺省 1 秒、上限 3 秒；输出只许空或 JSON，
纯文本视为无效——所以这里什么都不打印，永远 exit 0（fail-open）。"""
import json, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import guard_log    # 共享库：find_root + interrupt()
except Exception:
    guard_log = None


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0
    try:
        if guard_log is None or not isinstance(payload, dict):
            return 0
        start = payload.get("cwd") or os.getcwd()
        root = guard_log.find_root(start, script=__file__, env_keys=())
        guard_log.interrupt(root, session_id=payload.get("session_id", ""), cwd=start)
        return 0
    except Exception:
        return 0


if __name__ == "__main__":
    sys.exit(main())
