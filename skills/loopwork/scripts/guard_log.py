#!/usr/bin/env python3
"""围栏 · 取证账本（两版逐字节相同的共享库）。

围栏拦了什么、什么时候拦的、当时在哪个相位——一次拦截一行 JSON 追加进
`.loopwork/logs/blocks.jsonl`：{ts, tool, target, rule, phase}。
没见过的工具被放行时另记一本 `.loopwork/logs/tools_seen.jsonl`：{ts, tool, target, phase}——
放行不是拦截，混进 blocks.jsonl 会把轮末「本轮被拦 N 次」和进度卡累计数撑大
（Codex 版用；CC 版钩子按 matcher 只收固定工具，暂无此路径）。
还管两份「围栏到底在不在跑」的证据：钩子活体心跳 `.loopwork/logs/hook_heartbeat.json`
（PostToolUse 每次被调用就整文件覆写 {event, time, session_id, tool}——接线在盘上不等于平台在调用它）
和人为中断 `.loopwork/logs/interrupts.jsonl`（Codex Interrupt 事件，只记录不干预）。
它回答的不是「拦没拦住」（那是围栏的事），而是**「这一轮模型在反复撞哪面墙」**：
连着十次都撞考题锁，说明它在想办法绕过考题，不是手滑。
另有一本放行留痕 `.loopwork/logs/allowed.jsonl`：实现期改 tests/ 里的夹具/基础设施（conftest.py、
_infra/**、fixtures/**）被围栏放行时记一行 {ts, tool, target, rule=tests-infra, phase}——
放行不进 blocks.jsonl，但事后要查得出「实现期到底动了 tests/ 里的什么」。

只写不判——判定归 guard_rules.py，平台 payload 解析归各版适配层。
任何异常一律吞掉：取证日志写不成是小事，把会话弄崩是大事。

顺带住着 find_root()：所有钩子找项目根的唯一算法（自身落点 → 环境变量 → 向上爬 → 原地）。
两版九台机器都从这里取根，会话开在子目录 / 平台把钩子 cwd 设成别处时才不会集体失明。
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


def seen_path_of(root):
    return os.path.join(root, ".loopwork", "logs", "tools_seen.jsonl")


def heartbeat_path_of(root):
    return os.path.join(root, ".loopwork", "logs", "hook_heartbeat.json")


def interrupts_path_of(root):
    return os.path.join(root, ".loopwork", "logs", "interrupts.jsonl")


def allowed_path_of(root):
    return os.path.join(root, ".loopwork", "logs", "allowed.jsonl")


def find_root(start=None, script=None, env_keys=("CLAUDE_PROJECT_DIR",)):
    """定位项目根——所有钩子共用的唯一算法。找不到就原样返回 start，
    调用方照旧按「不是 loopwork 项目」放行。

    优先级：
      1. 钩子自己住哪：脚本在 <根>/.loopwork/hooks/ 里，根就是往上两级。装在哪个项目
         就守哪个项目，跟会话从哪个子目录启动无关——这是最硬的证据；
      2. 平台环境变量：CC 给 CLAUDE_PROJECT_DIR；Codex 没有对应变量，调用方传 env_keys=()；
      3. 从 start（平台 payload 里的 cwd，没有就进程 cwd）向上爬，第一个含
         .loopwork/state.json 的目录——会话开在子目录、或平台把钩子 cwd 设成当前
         轮次的目录时，靠这条兜底；
      4. 都没有：返回 start。
    用 abspath 不用 realpath：hooks 目录哪怕是符号链接，也算住在这个项目里。"""
    start = start or os.getcwd()
    try:
        if script:
            here = os.path.dirname(os.path.abspath(script))
            if (os.path.basename(here) == "hooks"
                    and os.path.basename(os.path.dirname(here)) == ".loopwork"):
                return os.path.dirname(os.path.dirname(here))
        for k in env_keys:
            v = os.environ.get(k)
            if v:
                return v
        d = os.path.abspath(start)
        while True:
            if os.path.exists(os.path.join(d, ".loopwork", "state.json")):
                return d
            parent = os.path.dirname(d)
            if parent == d:
                break
            d = parent
    except Exception:
        pass
    return start


def count(root):
    """账本累计行数。轮末钩子拿它算「本轮被拦几次」，进度卡拿它显示累计。

    读不到（没这个文件 / 不是 loopwork 项目）一律 0——取证是加分项，
    不是前置条件：账本缺席不该让检测门或进度卡罢工。"""
    try:
        with open(path_of(root), "rb") as f:
            return sum(1 for _ in f)
    except Exception:
        return 0


def _append(root, p, fields):
    """往 p 追加一行 {ts + fields} JSON（超 MAX_BYTES 单代轮转成 .1）。
    不是 loopwork 项目就什么都不做；每个字段落盘前都过 _clean。"""
    try:
        if not os.path.isdir(os.path.join(root, ".loopwork")):
            return
        os.makedirs(os.path.dirname(p), exist_ok=True)
        try:
            if os.path.getsize(p) > MAX_BYTES:
                os.replace(p, p + ".1")
        except OSError:
            pass
        rec = {"ts": datetime.datetime.now().astimezone().isoformat(timespec="seconds")}
        for k, v in fields.items():
            rec[k] = _clean(v)
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass


def record(root, tool="", target="", rule="", phase=""):
    """追加一行拦截记录到 blocks.jsonl。不是 loopwork 项目就什么都不做。"""
    _append(root, path_of(root), {"tool": tool, "target": target, "rule": rule, "phase": phase})


def seen(root, tool="", target="", phase=""):
    """没见过的工具被放行：追加一行到 tools_seen.jsonl（不进 blocks.jsonl，不计入 count()）。"""
    _append(root, seen_path_of(root), {"tool": tool, "target": target, "phase": phase})


def allowed(root, tool="", target="", rule="", phase=""):
    """白名单放行留痕：追加一行到 allowed.jsonl（实现期动了 tests/ 里的夹具/基础设施）。"""
    _append(root, allowed_path_of(root), {"tool": tool, "target": target, "rule": rule, "phase": phase})


def beat(root, event="", session_id="", tool=""):
    """钩子活体心跳：PostToolUse 每次被调用就整文件覆写 hook_heartbeat.json {event, time, session_id, tool}。
    它回答的是「平台本会话到底有没有调用围栏」——接线在盘上但平台没加载（Codex 未信任 / 会话根不是
    项目根 / settings 没生效）时围栏是静默失效的，这个文件是唯一能把静默暴露出来的证据。
    只许 PostToolUse 写它：别的事件（Stop / 进度卡）也写的话，同会话的心跳会把「PostToolUse 死了」盖住。
    原子写（tmp + os.replace）：读方永远看到完整 JSON；不是 loopwork 项目就什么都不做。"""
    try:
        if not os.path.isdir(os.path.join(root, ".loopwork")):
            return
        p = heartbeat_path_of(root)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        rec = {"event": _clean(event),
               "time": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
               "session_id": _clean(session_id), "tool": _clean(tool)}
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False))
        os.replace(tmp, p)
    except Exception:
        pass


def last_beat(root):
    """最近一次心跳（dict），没有或读不出就 None。"""
    try:
        with open(heartbeat_path_of(root), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else None
    except Exception:
        return None


def interrupt(root, session_id="", cwd=""):
    """人为中断（Codex Interrupt 事件）：追加一行到 interrupts.jsonl。只记录，不动 batch.flag。"""
    _append(root, interrupts_path_of(root), {"session_id": session_id, "cwd": cwd})


def last_interrupt(root):
    """最近一次人为中断（dict），没有就 None。"""
    try:
        last = None
        with open(interrupts_path_of(root), encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    last = line
        return json.loads(last) if last else None
    except Exception:
        return None


def no_beat_note(root, session_id=""):
    """轮末钩子用：心跳文件不存在，或心跳的 session_id 与本次 Stop 的 session_id 都非空且不同 → 提醒一句；
    任一方没有 session_id 就不下判断（fail-quiet：平台不给会话号时宁可不说，也不误报）。"""
    try:
        b = last_beat(root)
        if b is None:
            hit = True
        else:
            sid_b = str(b.get("session_id", "") or "")
            sid = str(session_id or "")
            hit = bool(sid_b and sid and sid_b != sid)
        if not hit:
            return ""
        return ("\n[活体] 围栏接线在，但平台本会话没有调用过它——先跑 selftest / 检查信任门"
                "（.loopwork/logs/hook_heartbeat.json 没有本会话的 PostToolUse 心跳）。")
    except Exception:
        return ""
