#!/usr/bin/env python3
"""围栏 · 判定核心（两版逐字节相同的共享库；纯函数，不碰文件系统）。

这里只回答一个问题：**「这条命令 / 这次编辑，拦还是不拦？」**
读状态、解析平台 payload、打印、退出码——全归调用方：
  Claude Code：guard_bash.py / guard_edits.py（PreToolUse）
  Codex：guard_pre.py（PreToolUse）
判定归一份代码管，才不会「一版补了洞、另一版还漏着」——这是两版同步的单一真相源。

对外五个函数（前三个命中返回元组，干净返回 None）：
  check_bash(cmd, phase="", in_project=False, extra_protected=()) -> None | (rule, 理由)
  check_edit(rel, phase="", extra_protected=())                   -> None | (rule, 理由)
  looks_like_secret(name, body="")                                -> None | 理由
  impl_files(files)                                               -> 清单里的「实现物」路径
  progress_sig(head, blobs)                                       -> 本轮末进展快照的短指纹
rule 是短标识（写进 .loopwork/logs/blocks.jsonl 取证用）；理由是给模型看的整句白话，
调用方原样打到 stderr，前面加自己的 `[围栏]` 抬头。

约定：路径一律用调用方算好的「项目内相对路径」，本模块不做 realpath——
符号链接还原、大小写归一属于 I/O 与平台差异，归适配层。
"""
import hashlib, re

# ---------- 清单（两版共享的规则本体）----------

DANGEROUS = [
    (r"\bgit\s+push\s+.*--force", "push-force",
     "git push --force 被围栏拦下：会抹掉远端历史，必须用户亲自决定。"),
    (r"\bgit\s+push\s+(?:\S+\s+)*-[a-zA-Z]*f\b", "push-force",
     "git push -f 被围栏拦下：等于 --force，会抹掉远端历史，必须用户亲自决定。"),
    (r"\bgit\s+push\s+[^;|&]*\s\+\S", "push-force",
     "git push +refspec 被围栏拦下：加号写法等于强推，必须用户亲自决定。"),
    (r"\bchmod\s+777\b", "chmod-777", "chmod 777 被围栏拦下：不做全开权限。"),
]

# 分段：换行和 ; | & 一样是命令分隔符——多行脚本是最常见的绕道写法。
SEP = r"[;|&\n]+"

# git 自己的全局选项（在子命令之前），带值的要连值一起跳过。
GIT_OPT_VALUE = ("-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path")
RESET_MODES = ("--hard", "--soft", "--mixed", "--merge", "--keep")

# 只许追加的保护文件：>> 和 tee -a 放行，覆盖/改写/删除/搬走一律拦。
APPEND_ONLY = ["journal.md"]

# 永久保护（任何相位）：围栏脚本 / 状态 / 批次 flag / 日志正本。
# 各版自己的接线文件（CC 的 .claude/settings.json、Codex 的 .codex/hooks.json）
# 由调用方用 extra_protected 传进来——那是平台差异，不是规则差异。
PROTECT_ALWAYS = [
    ".loopwork/hooks",
    ".loopwork/state.json",
    ".loopwork/batch.flag",
    "journal.md",
]
# 实现期加锁：考题先红后绿，写实现期间不许碰考题/规格/规矩。
PROTECT_IMPL = ["tests/", "spec.md", "rules.md"]

# 红存档除考题外还允许捎带的台账文件：勾任务、记日志、写状态。
RED_ALLOWED = ("tasks.md", "JOURNAL.md", ".loopwork/state.json")

# 「有进展」的证据面（HEAD 之外还看这两份台账）。轮数没涨 ≠ 没干活：
# 红考题落了档（HEAD 变）、勾了一条任务或标了〔卡〕（tasks.md 变）、
# 问题本新增一条（BLOCKED.md 变）——都算干出了东西，一条硬任务本来就可能跨两次顶回。
# 轮数没涨 **且** 这三样一个字都没动，才是真打转。两版停滞判定量的是同一把尺。
PROGRESS_FILES = ("tasks.md", "BLOCKED.md")

# 疑似密钥：文件名一层 + 文件内容一层。命中不是「肯定是密钥」，是「必须停下来问」。
SECRET_NAME = re.compile(r"(^|/)\.env(\.|$)|\.pem$|\.p12$|\.key$|(^|/)(secrets?|credentials?)\.", re.I)
SECRET_BODY = [
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), "私钥文件头"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "AWS Access Key"),
    (re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"), "sk- 开头的 API key"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"), "GitHub token"),
    (re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"), "Slack token"),
]


def append_ok(target):
    """这个保护路径是不是「只许追加」的那一类。"""
    return any(a in target for a in APPEND_ONLY)


def impl_files(files):
    """从一份存档文件清单里挑出「实现物」：考题目录之外、也不在红档白名单里的路径。
    空清单 = 这一档只有考题和台账 = 红存档；非空 = 绿存档，得先有红票才准落。
    两版共用同一把尺：Codex 由钩子代存档时量它，CC 由模型自己 git commit 时量它。"""
    return [f for f in files if not (str(f).startswith("tests/") or f in RED_ALLOWED)]


def progress_sig(head, blobs):
    """把「本轮末的进展快照」压成一个短指纹，存进 batch.flag 供下一轮比对。
    head = HEAD 的 hash（读不出来给 ""）；blobs = 按 PROGRESS_FILES 顺序读来的字节
    （文件不在给 None）。指纹一样 = 这一轮 HEAD 和两份台账都没动过。
    读文件、跑 git 归调用方的适配层——本模块不碰文件系统。"""
    h = hashlib.sha1()
    h.update(str(head or "").encode("utf-8"))
    for b in blobs:
        h.update(b"\0" + (b if isinstance(b, bytes) else b"\x01missing"))
    return h.hexdigest()[:12]


# ---------- 命令拆解 ----------

def dangerous_rm(cmd):
    """rm 同时带 r 和 f 旗标即危险：合写(-rf/-fr)、分写(-r -f)、长写(--recursive --force)一视同仁。
    一段里可能有多个 rm（`rm a.txt` 后面跟真正危险的那条），逐个看，不能只看第一个。"""
    for seg in re.split(SEP, cmd):
        for m in re.finditer(r"\brm\b(.*)", seg):
            args = m.group(1)
            flags = "".join(re.findall(r"(?:^|\s)-([a-zA-Z]+)", args)).lower()
            longs = set(re.findall(r"(?:^|\s)--([a-z-]+)", args.lower()))
            if ("r" in flags or "recursive" in longs) and ("f" in flags or "force" in longs):
                return True
    return False


def git_calls(cmd):
    """把命令里每一处 git 调用拆成 (子命令, 参数列表)。
    只认「跳过 git 全局选项后的第一个词」这个位置当子命令——这样
    `git commit -m "clean up rebase"` 不会被提交信息里的词误伤。
    用 shlex 分词，引号里的内容整体成一个 token，旗标比对走精确相等。"""
    import shlex
    out = []
    for seg in re.split(SEP, cmd):
        try:
            toks = shlex.split(seg)
        except ValueError:  # 引号不成对，退回粗分词，宁可多看几个词
            toks = seg.split()
        for i, t in enumerate(toks):
            if t != "git" and not t.endswith("/git"):
                continue
            j = i + 1
            while j < len(toks):
                if toks[j] in GIT_OPT_VALUE:
                    j += 2
                elif toks[j].startswith("-"):
                    j += 1
                else:
                    break
            if j < len(toks):
                out.append((toks[j].lower(), toks[j + 1:]))
            break  # 一段里只认第一处 git 调用（后面的词是它的参数）
    return out


def reset_moves_pointer(args):
    """git reset 只放行「取消暂存」形态：git reset [HEAD] [--] <路径>。
    带模式旗标、或第一个位置参数不是 HEAD（是某个版本号/分支）→ 就是在搬分支指针。"""
    for a in args:
        if a in RESET_MODES:
            return f"{a} 会搬动分支指针并丢弃工作"
    head = args[: args.index("--")] if "--" in args else args
    pos = [a for a in head if not a.startswith("-")]
    if pos and pos[0] != "HEAD":
        return f"把分支指针搬到 {pos[0]}，中间的存档等于被抹掉"
    return None


def git_rewrite_ban(cmd):
    """改历史 / 销毁证据类 git 动作。命中返回 (动作名, 白话原因)，否则 None。
    Loopwork 的流程从不需要改历史：存档只增不减，改得动的历史不算证据。
    （用户自己在终端做这些事不经过围栏，这里只管住模型。）"""
    for sub, args in git_calls(cmd):
        flags = [a for a in args if a.startswith("-")]
        if sub == "commit" and "--amend" in flags:
            return ("git commit --amend", "改写已有存档 = 抹掉证据。要修正就再存一档，旧的留着")
        if sub in ("rebase", "filter-branch", "filter-repo", "update-ref"):
            return (f"git {sub}", "会重排或伪造 git 历史——基线存档一旦凭空消失，检测门会判定假历史并停机")
        if sub == "stash":
            return ("git stash", "把改动藏进一个不在存档里的暗格；存档才是证据，藏起来的不算")
        if sub == "clean":
            return ("git clean", "批量删除未跟踪文件，删掉的东西 git 里也找不回来——要删就点名删单个文件")
        if sub == "reflog" and any(a in ("expire", "delete") for a in args):
            return ("git reflog expire/delete", "销毁最后一层找回历史的后路")
        if sub == "gc" and any(a.startswith("--prune") for a in flags):
            return ("git gc --prune", "立刻回收悬空对象——误删的存档就真的没了")
        if sub == "branch" and ("--force" in flags or
                                any(re.fullmatch(r"-[a-zA-Z]*[fD][a-zA-Z]*", a) for a in flags)):
            return ("git branch -f/-D", "强制搬动或删除分支指针")
        if sub == "switch" and "--discard-changes" in flags:
            return ("git switch --discard-changes", "丢弃未存档的工作")
        if sub == "push" and ("--delete" in flags or "-d" in flags):
            return ("git push --delete", "删除远端分支——远端是别人也在看的东西")
        if sub == "reset":
            why = reset_moves_pointer(args)
            if why:
                return ("git reset", why)
    return None


def write_target_hit(cmd, targets):
    """只有当写动作『指向』保护路径才算命中——提到路径不算（跑考题 pytest tests/ 必须放行）。
    大小写不敏感比对（macOS 文件系统默认不区分）。返回命中的保护路径，未命中返回 None。"""
    # 1) 重定向落点：> 或 >> 后面的那个 token（只许追加的文件放行 >>，拦 >）
    for m in re.finditer(r"(>>?)\s*([^\s;|&<>]+)", cmd):
        op, tok = m.group(1), m.group(2).lower()
        for t in targets:
            if t in tok:
                if op == ">>" and append_ok(t):
                    continue
                return t
    # 2) 写型命令的参数区：按管道/分号/换行切段，每段里每个匹配都要看（不能只看第一个）。
    #    sed -i/tee/truncate 对每个文件参数都是写；mv 也算——把考题搬走等于删掉源文件。
    for seg in re.split(SEP, cmd):
        for m in re.finditer(r"\b(sed\s+-i\S*|tee(?:\s+-a\b)?|mv|truncate)\b(.*)", seg):
            verb, args = m.group(1).lower(), m.group(2).lower()
            appending = verb.startswith("tee") and "-a" in verb
            for t in targets:
                if t in args:
                    if appending and append_ok(t):
                        continue
                    return t
        # cp 只有目的地算写：从考题目录拷出去是读，必须放行。
        # 目的地通常是最后一个参数，但 -t <目录> / --target-directory=<目录> 会把它挪到前面。
        for m in re.finditer(r"\bcp\b(.*)", seg):
            raw = m.group(1).lower().split()
            dest = None
            for i, x in enumerate(raw):
                if x == "-t" and i + 1 < len(raw):
                    dest = raw[i + 1]
                elif x.startswith("--target-directory="):
                    dest = x.split("=", 1)[1]
            if dest is None:
                toks = [x for x in raw if not x.startswith("-")]
                dest = toks[-1] if toks else None
            if dest:
                for t in targets:
                    if t in dest:
                        return t
        # 3) 删也是写的一种：删掉围栏脚本/接线/批次 flag 等于把围栏关掉。
        #    普通文件的 rm 不受影响（只看参数是否落在保护清单上）。
        for m in re.finditer(r"\brm\b(.*)", seg):
            for tok in m.group(1).lower().split():
                if tok.startswith("-"):
                    continue
                for t in targets:
                    if t in tok:
                        return t
    return None


def git_rewrite_hit(cmd, protected):
    """实现期二号绕道：用 git 改写考题内容而不经过编辑工具。
    checkout/restore 带保护路径 = 把考题回滚成旧版本；apply/revert 的落点从命令行根本看不见。
    命中返回 (子命令, 白话原因)；未命中返回 None。"""
    for seg in re.split(SEP, cmd):
        for m in re.finditer(r"\bgit\s+(checkout|restore)\b(.*)", seg):
            if any(t in m.group(2).lower() for t in protected):
                return (m.group(1), "指向考题/规格路径")
        m = re.search(r"\bgit\s+(apply|revert)\b", seg)
        if m:
            return (m.group(1), "补丁/回滚会改哪些文件，围栏从命令行看不见")
    return None


# ---------- 对外判定 ----------

def check_bash(cmd, phase="", in_project=False, extra_protected=()):
    """判一条 shell 命令。命中返回 (rule, 白话理由)，干净返回 None。

    in_project=False（不是 loopwork 项目）：只做通用净化——危险删除、强推、全开权限、
    改历史一族。这几条与项目无关，任何地方都不该由模型代做。
    in_project=True：再加保护文件判定；phase == "implementing" 时把考题/规格/规矩一并锁上。
    """
    if dangerous_rm(cmd):
        return ("rm-rf", "rm -rf 类命令被围栏拦下：删除动作必须先问用户，并改用精确路径删除。")
    for pat, rule, msg in DANGEROUS:
        if re.search(pat, cmd):
            return (rule, msg)
    ban = git_rewrite_ban(cmd)
    if ban:
        return ("git-rewrite", f"{ban[0]} 被围栏拦下：{ban[1]}。"
                "存档只增不减——要改就往前再存一档；确实非做不可，停下来向用户说明，由他自己在终端执行。")
    if not in_project:
        return None
    targets = list(PROTECT_ALWAYS) + [str(x).lower() for x in extra_protected]
    if str(phase) == "implementing":
        targets += PROTECT_IMPL
        g = git_rewrite_hit(cmd, PROTECT_IMPL)
        if g:
            return ("git-touch-exam",
                    f"拦截：实现期不许用 git {g[0]} 改写考题/历史（{g[1]}）。"
                    "红考题只能靠写实现变绿；确需回滚或打补丁，停下来向用户说明并征得同意。")
    hit = write_target_hit(cmd, targets)
    if hit:
        tail = ('只许追加：记一笔用 `python3 .loopwork/hooks/progress.py journal "…"`，或 `>>` / `tee -a`。'
                if append_ok(hit)
                else "保护文件不许绕道修改——需要改就向用户说明并走正规流程。")
        rule = "append-only" if append_ok(hit) else "write-protected"
        return (rule, f"拦截：这条命令在用 shell 改写或删除保护文件（{hit}）。{tail}")
    return None


def check_edit(rel, phase="", extra_protected=()):
    """判一次文件编辑。rel 是调用方算好的「项目内相对路径」（已还原符号链接）。
    越界用 ".." 开头的 rel 表示。命中返回 (rule, 白话理由)，干净返回 None。"""
    rel = str(rel).replace("\\", "/")
    if rel.startswith(".."):
        return ("outside-project", "拦截：不许改项目文件夹之外的文件。需要的话请先问用户。")
    low = rel.casefold()
    while low.startswith("./"):
        low = low[2:]
    if low.rsplit("/", 1)[-1] == "journal.md":
        return ("append-only",
                f"拦截：{rel} 只许追加，不许改写（日志是历史，改得动就不算证据）。"
                '记一笔用 `python3 .loopwork/hooks/progress.py journal "T02 ✅ 2 红→绿 | 备注"`，'
                "或 shell 里 `>>` / `tee -a` 追加。")
    always = [p for p in PROTECT_ALWAYS if p != "journal.md"] + [str(x).lower() for x in extra_protected]
    for p in always:
        if low == p.rstrip("/") or low.startswith(p.rstrip("/") + "/"):
            return ("protected-file",
                    f"拦截：{rel} 受保护。围栏脚本与钩子接线不许改；"
                    "状态请用 progress.py 更新；批次开关归用户和 Stop 钩子。")
    if str(phase) == "implementing":
        if low.startswith("tests/") or low in ("spec.md", "rules.md"):
            return ("impl-locked",
                    f"拦截：现在是实现阶段，{rel} 已锁定（考题先红后绿，写实现期间不许改考题/规格/规矩）。"
                    "确需修改：停下来，向用户说明理由并征得明确同意。")
    return None


def looks_like_secret(name, body=""):
    """疑似密钥判定：文件名一层 + 内容一层。命中返回白话理由，干净返回 None。
    密钥入库是最难撤销的事故之一——宁可多问一句，也不要事后去改历史。"""
    if SECRET_NAME.search(str(name).replace("\\", "/")):
        return f"{name} 的文件名像密钥/凭据文件"
    for pat, what in SECRET_BODY:
        if pat.search(body or ""):
            return f"{name} 里出现{what}"
    return None
