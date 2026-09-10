#!/usr/bin/env python3
"""围栏 · 取证账本（两版逐字节相同的共享库）。

围栏拦了什么、什么时候拦的、当时在哪个相位——一次拦截一行 JSON 追加进
`.loopwork/logs/blocks.jsonl`：{ts, tool, target, rule, phase}。
它回答的不是「拦没拦住」（那是围栏的事），而是**「这一轮模型在反复撞哪面墙」**：
连着十次都撞考题锁，说明它在想办法绕过考题，不是手滑。

只写不判——判定归 guard_rules.py，平台 payload 解析归各版适配层。
任何异常一律吞掉：取证日志写不成是小事，把会话弄崩是大事。
"""
import datetime, json, os, sys

MAX_BYTES = 2 * 1024 * 1024   # 超了单代轮转成 .1，与审计账本同一规矩

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import guard_rules
except Exception:  # 判定核心不在也要能记账——记账本身不依赖判定
    guard_rules = None


def _clean(v):
    """字段落盘前过一遍密钥筛查——取证日志自己不能变成泄密面。"""
    if not isinstance(v, str):
        v = str(v)
    v = v.strip().replace("\n", " ")[:200]
    if guard_rules is not None and guard_rules.looks_like_secret("", v):
        return "[已隐去：疑似密钥]"
    return v


def path_of(root):
    return os.path.join(root, ".loopwork", "logs", "blocks.jsonl")


def count(root):
    """账本累计行数。轮末钩子拿它算「本轮被拦几次」，进度卡拿它显示累计。

    读不到（没这个文件 / 不是 loopwork 项目）一律 0——取证是加分项，
    不是前置条件：账本缺席不该让检测门或进度卡罢工。"""
    try:
        with open(path_of(root), "rb") as f:
            return sum(1 for _ in f)
    except Exception:
        return 0


def record(root, tool="", target="", rule="", phase=""):
    """追加一行拦截记录。不是 loopwork 项目就什么都不做。"""
    try:
        if not os.path.isdir(os.path.join(root, ".loopwork")):
            return
        p = path_of(root)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        try:
            if os.path.getsize(p) > MAX_BYTES:
                os.replace(p, p + ".1")
        except OSError:
            pass
        rec = {
            "ts": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
            "tool": _clean(tool),
            "target": _clean(target),
            "rule": _clean(rule),
            "phase": _clean(phase),
        }
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass
