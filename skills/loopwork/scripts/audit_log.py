#!/usr/bin/env python3
"""Loopwork Codex 版 · PostToolUse 审计日志（只记录，不拦截——拦截靠沙箱/规则/检测门）。
每次工具调用追加一行 JSONL 到 .loopwork/logs/audit.jsonl。fail-open。"""
import datetime, json, os, sys

def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0
    try:
        root = os.environ.get("CODEX_PROJECT_DIR") or payload.get("cwd") or os.getcwd()
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
        with open(os.path.join(logdir, "audit.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        return 0
    except Exception:
        return 0

if __name__ == "__main__":
    sys.exit(main())
