#!/usr/bin/env python3
"""Loopwork Codex 版 · PostToolUse 审计日志（只记录，不拦截——拦截靠沙箱/规则/检测门）。
每次工具调用追加一行 JSONL 到 .loopwork/logs/audit.jsonl，并覆写钩子活体心跳
.loopwork/logs/hook_heartbeat.json（证明平台本会话真的在调用围栏；进度卡与轮末钩子都看它）。fail-open。"""
import datetime, json, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import guard_log    # 共享库：项目根解析 find_root（不在也不影响记账/放行）
except Exception:
    guard_log = None

def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0
    try:
        start = payload.get("cwd") or os.getcwd()
        root = (guard_log.find_root(start, script=__file__, env_keys=()) if guard_log is not None
                else start)
        logdir = os.path.join(root, ".loopwork", "logs")
        if not os.path.isdir(os.path.join(root, ".loopwork")):
            return 0
        os.makedirs(logdir, exist_ok=True)
        tool = payload.get("tool_name", "?")
        ti = payload.get("tool_input") or {}
        summary = (ti.get("command") or ti.get("file_path") or ti.get("path") or "")
        rec = {
            "ts": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
            "tool": tool,
            "summary": str(summary)[:200],
        }
        path = os.path.join(logdir, "audit.jsonl")
        # 单代轮转：超 5MB 把老账本顶成 .1（审计要能追溯，但不能无限吃盘）
        try:
            if os.path.getsize(path) > 5 * 1024 * 1024:
                os.replace(path, path + ".1")
        except OSError:
            pass
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        if guard_log is not None:   # 钩子活体心跳：只有 PostToolUse 写它（别的事件写了会把「PostToolUse 死了」盖住）
            guard_log.beat(root, event=payload.get("hook_event_name", "PostToolUse"),
                           session_id=payload.get("session_id", ""), tool=tool)
        return 0
    except Exception:
        return 0

if __name__ == "__main__":
    sys.exit(main())
