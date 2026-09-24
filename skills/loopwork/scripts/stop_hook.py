#!/usr/bin/env python3
"""Loopwork Codex 版 · Stop 钩子（代存档 + 检测门 + 挂机批模式，合一）。

顺序：
0. 代存档（state.pending_commit 有登记时）：模型跑在沙箱里，.git 写不动；钩子跑在
   沙箱外，替它把存档落下去。落之前先验：改动清单 → 按档种挑该入档的（stage_plan：
   red 只收考题和台账，note 不收考题，仓库根上的新文件谁都不收，围栏脚本谁都不收，
   实现期的考题/规格/规矩 note 也不收）→ 只对要入档的做密钥筛查 → green 要 verify.sh
   全绿且手里有红存档票（先红后绿）。两条硬拒绝：red 只在 test-writing 相位受理（实现期
   补考题先 progress.py set phase test-writing，会留审计）；green 遇到受保护文件有未存档
   改动直接拒绝——判卷不能在动过手脚的考题或判卷员上进行，收了就是替偷改洗白。
   其余验不过就拒绝并清掉登记；没挑上的留在工作区、在回执里点名，不整档拒绝。
   落成了推进基线、green 时轮数 +1 并记一行 JOURNAL，结果并进本轮那一次顶回告诉模型。
   ——存档因此不是「模型说存了」，而是「围栏验过才算」。
1. 检测门（快检，永远执行）：
   a. 基线锚定：state.last_round_commit 必须仍在 git 历史中可达（防 amend/rebase 假历史）；
   b. 相位纪律：phase==implementing 时，受保护文件（tests/ 除基础设施白名单、.loopwork/hooks/、
      spec.md rules.md）分两段核对——
      未存档改动（工作区/未跟踪）→ 顶回要求撤销；
      已存档改动（基线..HEAD）→ 代存档会自动推进基线，所以这里多半是人手动 commit 的，
      顶回教它对齐基线或坦白。
   违规 → decision:"block"，reason=处置指令（Codex 会把 reason 当下一轮输入续跑）。
2. 挂机批模式（.loopwork/batch.flag 存在时）：外部计数——批中顶回 / 满批强制验收 /
   只剩受阻任务转清问题本 / 轮数上限安全停机 / 连续 MAX_STALLS 次「一点进展都没有」→
   判定原地打转自动停批。无进展 = 轮数没涨 ∧ HEAD 没动 ∧ tasks.md 没动 ∧ BLOCKED.md 没动
   （见 progress_sig；flag 存 "起点,上次顶回轮数,无进展次数,顶回总数,进展指纹"，兼容旧格式）。
3. 顶回总数上限 MAX_BLOCKS：顶回是「不让会话结束」，Codex 平台不给这件事设硬上限——
   实测连续 12 次顶回全部生效。所以这道刹车必须由围栏自己踩：累计到上限就优雅停机
   （摘 flag + 记 stop_blocks=-1，下一轮无条件放行一次，把会话真正交还给用户）。
   批模式记在 flag 第 4 段，非批模式记在 state.stop_blocks——与 CC 版同格式同上限。
非 loopwork 项目 / git 异常 / 内部异常：放行（fail-open，不砖会话）。
输出协议：阻断用 stdout JSON {"decision":"block","reason":...}；放行 exit 0 无输出。
"""
import json, os, subprocess, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import guard_rules  # 密钥筛查的判定核心（两版共享）
except Exception:
    guard_rules = None
try:
    import guard_log    # 拦截取证账本（两版共享）
except Exception:
    guard_log = None

MAX_STALLS = 2  # 连续 N 次顶回「一点进展都没有」→ 判定打转（定义见 progress_sig）
MAX_BLOCKS = 7  # 顶回总数上限 → 优雅停机。与 CC 版同数，方便两版对照排障
VERIFY_TIMEOUT = 330    # 比 verify.sh 自己的 300s 保险丝多留一点，让它先自杀
SCAN_MAX_BYTES = 512 * 1024   # 单文件密钥筛查上限，超了只查文件名——轮末不做全盘扫描
# 代存档按档种挑落点（stage_plan），不再 git add -A 一把抓：
#   red   只收 tests/ 和台账（guard_rules.RED_ALLOWED，两版共享——CC 版的存档闸量的是同一把尺）；
#   green 收所有已跟踪改动 + 子目录里的新文件 + 仓库根上的台账（LEDGER_ROOT）；
#   note  同 green，但考题不收（考题只能走红存档）。
# 仓库根上的其他新文件（scratch.txt 之类）一律不自动收：进不进仓库由用户在沙箱外拍板。
# 另有 fence_held：围栏脚本（.loopwork/hooks/）任何档种任何时候不代收；实现期的考题/规格/规矩
# green 直接拒档、note 不收——代存档不能成为绕过实时围栏、把偷改落进历史的后门。
LEDGER_ROOT = ("spec.md", "rules.md", "tasks.md", "JOURNAL.md", "BLOCKED.md", "PROJECT.md")

def sh(args, cwd, timeout=20, strip=True):
    try:
        p = subprocess.run(args, cwd=cwd, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout)
        # strip=False 是给 porcelain 用的：它每行开头那两位状态码可能是空格，
        # 顺手 strip 一下就会把第一条记录啃掉一个字符，路径从此对不上。
        out = p.stdout.strip() if strip else p.stdout
        if p.returncode != 0 and not out:   # 失败时把 stderr 顶上来，理由才说得清
            out = p.stderr.strip()
        return p.returncode, out
    except Exception:
        return 1, ""

def block(reason):
    print(json.dumps({"decision": "block", "reason": reason}, ensure_ascii=False))
    return 0  # Codex 协议：决定放 stdout JSON，退出码 0

def journal_deleted(root, revs):
    """JOURNAL.md 在这段区间里被删掉多少行（numstat 第二列）。读不到就当 0（fail-open）。"""
    code, out = sh(["git", "diff", "--numstat"] + revs + ["--", "JOURNAL.md"], root)
    cols = out.split() if code == 0 else []
    return int(cols[1]) if len(cols) >= 2 and cols[1].isdigit() else 0

def progress_sig(root):
    """本轮末的进展快照指纹：HEAD + guard_rules.PROGRESS_FILES 的内容。
    共享库不在就返回 ""——退回「只看轮数」的老判法，宁可少停批也不误停。"""
    if guard_rules is None:
        return ""
    code, head = sh(["git", "rev-parse", "HEAD"], root)
    if code != 0:
        head = ""
    blobs = []
    for name in guard_rules.PROGRESS_FILES:
        try:
            with open(os.path.join(root, name), "rb") as f:
                blobs.append(f.read())
        except OSError:
            blobs.append(None)
    return guard_rules.progress_sig(head, blobs)

def save_state(root, st):
    """写回 state.json（原子替换）。只有钩子走这条路——模型改状态一律用 progress.py。"""
    try:
        p = os.path.join(root, ".loopwork", "state.json")
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(st, f, ensure_ascii=False, indent=2)
        os.replace(tmp, p)
    except Exception:
        pass

def round_hits(root, st):
    """本轮被实时围栏拦了几次 = 取证账本新增行数，并把水位线推到当前值。

    每轮末调一次。账本轮转过（行数反而变小）就复位水位线——宁可少报，
    也不报出负数：一个说谎的计数比没有计数更糟。"""
    if guard_log is None:
        return 0
    total = guard_log.count(root)
    try:
        seen = int(st.get("blocks_seen", 0) or 0)
    except (TypeError, ValueError):
        seen = 0
    if total < seen:
        seen = 0
    if total != seen:
        st["blocks_seen"] = total
        save_state(root, st)
    return max(0, total - seen)

def hits_note(n):
    """挂在顶回理由末尾的一句取证。没拦过就什么都不说，别给噪音。"""
    if not n:
        return ""
    return (f"\n[取证] 本轮实时围栏拦下 {n} 次动作（明细 .loopwork/logs/blocks.jsonl）。"
            "同一面墙撞两次以上就别再找绕路了：改走合规路径，或写进 BLOCKED.md 交给用户拍板。")

def is_protected(p):
    """受保护文件 = 考题/规格/规矩 + 围栏自己（改围栏脚本等于把围栏关掉，任何借口都不行）。
    tests/ 里的基础设施（conftest / _infra / fixtures，见 guard_rules.tests_infra_ok）实现期
    本就放行，这里同样不算受保护——否则实时围栏放过去的改动到轮末又被顶回，规矩自相矛盾。
    判定核心缺席时从严：tests/ 下全部算受保护。"""
    if p.startswith(".loopwork/hooks/") or p in ("spec.md", "rules.md"):
        return True
    if p.startswith("tests/"):
        return guard_rules is None or not guard_rules.tests_infra_ok(p)
    return False

def protected(lines):
    return [l for l in lines if is_protected(l)]

def fence_held(p, phase):
    """代存档不代收的路径：围栏脚本任何时候不收；考题/规格/规矩在实现期不收。
    收了等于替模型把「实现期偷改考题」落进历史——实时围栏拦在前面，这里是最后一道。"""
    if p.startswith(".loopwork/hooks/"):
        return True
    return phase == "implementing" and is_protected(p)

def changed_entries(root):
    """工作区改动清单 [(XY, 路径)]（仓库根相对；XY 是 porcelain 的两位状态码，未跟踪是 ??）。
    git 读不出来返回 None。
    -z：文件名里有空格/引号时 porcelain 的引号转义会把路径读歪。
    -uall：默认会把整个未跟踪目录折成一行 `secrets/`，里头的文件就永远过不了密钥筛查。"""
    code, out = sh(["git", "status", "--porcelain", "-z", "-uall"], root, strip=False)
    if code != 0:
        return None
    items = [x for x in out.split("\0") if x]
    ents, i = [], 0
    while i < len(items):
        it = items[i]
        i += 1
        if len(it) < 4:
            continue
        xy = it[:2]
        ents.append((xy, it[3:]))
        if xy[0] in ("R", "C") and i < len(items):  # 改名/复制：原路径是紧随的下一段
            ents.append((xy, items[i]))
            i += 1
    return ents

def stage_plan(kind, ents, phase=""):
    """按档种把改动清单分成 (要入档, 留在工作区)。留下的不是丢弃：回执里会点名。
    red：只收 tests/ 和台账；green：已跟踪改动 + 子目录新文件 + 根上台账；note：同 green 但不收考题。
    green/note 另外不收 fence_held 的路径（围栏脚本任何时候、受保护文件在实现期）。"""
    take, skip = [], []
    for xy, p in ents:
        if kind == "red":
            ok = p.startswith("tests/") or p in guard_rules.RED_ALLOWED
        else:
            ok = xy != "??" or "/" in p or p in LEDGER_ROOT
            if kind == "note" and p.startswith("tests/"):
                ok = False
            if fence_held(p, phase):
                ok = False
        (take if ok else skip).append(p)
    return take, skip

def skipped_note(kind, skip, phase=""):
    """回执里点名没入档的路径：留在工作区的东西不会丢，但得让模型和用户都知道它在那儿。
    其中受保护路径（fence_held）不是「待收」而是「待撤销」——回执里要说清，别让模型换个档种再试。"""
    if not skip:
        return ""
    why = {"red": "红档只收 tests/ 和台账；实现文件等绿存档再收，其余留在工作区",
           "note": "记事档不收考题（考题走红存档）；仓库根上的新文件也不自动收",
           }.get(kind, "仓库根上的新文件不自动收，留在工作区")
    held = [p for p in skip if fence_held(p, phase)]
    if held:
        why += "；受保护路径（围栏脚本任何时候、考题/规格/规矩在实现期）不代收"
    shown = ", ".join(skip[:8]) + (f" 等 {len(skip)} 项" if len(skip) > 8 else "")
    text = (f" 未入档（{why}）：{shown}。留在工作区的东西不会丢：该入档的下次按对应档种再收；"
            "仓库根上的新文件由用户拍板（沙箱外 git add，或写进 .gitignore）。")
    if held:
        text += (" 其中受保护路径（" + ", ".join(held[:4]) + "）不是「待收」而是「待撤销」："
                 "git checkout -- <文件> / 删掉新建文件；若是用户升级围栏，请用户在沙箱外亲手 commit。")
    return text

def secret_hits(root, files):
    """对将要入库的文件做密钥筛查（文件名一层 + 内容一层）。返回白话理由列表。"""
    hits = []
    for rel in files:
        p = os.path.join(root, rel)
        body = ""
        try:
            if os.path.getsize(p) <= SCAN_MAX_BYTES:
                with open(p, encoding="utf-8", errors="replace") as f:
                    body = f.read()
        except OSError:
            pass  # 删除/读不到：只查得了文件名，那就只查文件名
        why = guard_rules.looks_like_secret(rel, body)
        if why:
            hits.append(why)
    return hits

def trip_note(vout):
    """把 verify.sh 的判卷预警捎回给模型。

    绿存档时 verify.sh 是钩子替模型跑的，那段输出模型根本看不见——不捎这一趟，
    预警就只会烂在日志里，等于没做。只捎预警行，不捎测试输出：顶回理由是给人读的。"""
    lines = [l.strip() for l in (vout or "").splitlines() if "判卷预警：" in l]
    if not lines:
        return ""
    return ("\n" + "\n".join(lines[:4]) +
            "\n[代存档] 预警不改判决，档已经落了；但这几条痕迹要么当面给理由，"
            "要么改回去——判卷员会照作弊清单（reviewer.md）逐条核对。")

def archive_pending(root, st):
    """执行 state.pending_commit 登记的存档。返回 (ok, 一段话)；没有登记 → (True, "")。

    验不过就拒绝，并把登记清空——宁可让模型重新登记一次，也不留一条每轮都被拒的
    死意图，把顶回额度耗光。密钥筛查缺了判定核心一律不落档（fail closed）：
    筛查缺席时代存档，等于把最难撤销的事故自动化。"""
    pend = st.get("pending_commit")
    if not isinstance(pend, dict):
        return True, ""
    kind = str(pend.get("kind", ""))
    msg = " ".join(str(pend.get("msg", "")).splitlines()).strip()

    def reject(why):
        st.pop("pending_commit", None)
        save_state(root, st)
        return False, ("[代存档] 拒绝：" + why +
                       " 登记已清空——处理完重新执行 progress.py commit 登记一次。")

    if kind not in ("red", "green", "note") or not msg:
        return reject(f"登记不完整（kind={kind or '空'}，说明{'空' if not msg else '有'}）。")
    if not os.path.isdir(os.path.join(root, ".git")):
        return reject("这个项目没有 git 存档系统，没法代你存档。")
    if guard_rules is None:
        return reject("判定核心 guard_rules.py 不在 .loopwork/hooks/，密钥筛查做不了——"
                      "筛查缺席就不代存档。请重跑 init_project.sh 补齐围栏。")
    phase = str(st.get("phase", ""))
    if kind == "red" and phase == "implementing":
        return reject("红存档要在 test-writing 相位登记（现在是 implementing）。实现期改考题是偷改，"
                      "不能借红存档洗白：真要补考题，先 progress.py set phase test-writing（会留审计）"
                      "再登记；偷改的先撤销（git checkout -- <文件> / 删掉新建文件），并在 JOURNAL 记一行。")
    ents = changed_entries(root)
    if ents is None:
        return reject("git status 读不出来。")
    if kind == "green":
        # 判卷不能在动过手脚的考题或判卷员上进行：verify.sh 跑的是工作区，考题/围栏脚本
        # 有未存档改动，绿了也不算数——收进去就是替偷改洗白，检测门再拦也只剩事后追责。
        held = [p for _, p in ents if fence_held(p, phase)]
        if held:
            return reject("受保护文件有未存档改动（围栏脚本任何时候、考题/规格/规矩在实现期都不代收）："
                          + ", ".join(held[:6]) + (f" 等 {len(held)} 项" if len(held) > 6 else "")
                          + "。判卷不能在动过手脚的考题或判卷员上进行，这一档不代存。"
                          "先撤销（git checkout -- <文件> / 删掉新建文件）再重新登记；"
                          "若是用户升级了围栏，请用户在沙箱外先 commit。")
    # 按档种挑落点：red 只收考题和台账，note 不收考题，仓库根上的新文件谁都不收，
    # 围栏脚本谁都不收，实现期的受保护文件 note 不收——不该进的不再整档拒绝，而是留在
    # 工作区、在回执里点名（模型在沙箱里本来就动不了 .git，拒绝只会让它反复登记；
    # 而考题的唯一入口仍是 test-writing 相位的红存档，先红后绿没有松动）。
    take, skip = stage_plan(kind, ents, phase)
    # 登记动作本身就会写 state.json，所以它出现在改动清单里什么都不证明——
    # 把它剔掉再看还剩什么，才是「这次存档到底有没有实体」。空存档是假完成信号。
    if not [f for f in take if f != ".loopwork/state.json"]:
        return reject("除了状态文件没有任何改动，这次存档会是个空档——空存档不算数。"
                      + skipped_note(kind, skip, phase))
    hits = secret_hits(root, take)     # 只筛要入档的：留在工作区的东西进不了历史
    if hits:
        return reject("疑似密钥要进这次存档：" + "；".join(hits[:3]) +
                      "。密钥入库是最难撤销的事故：先把它移出仓库或写进 .gitignore，再来存档。")
    warn = ""   # 判卷预警：只有绿存档跑 verify.sh，也只有那一路可能带回痕迹
    if kind == "green":
        if not st.get("red_commit_pending"):
            return reject("上一次绿存档之后没有过红存档。考题先红后绿：先写会失败的考题、"
                          "存一次红档，再来存绿档。")
        code, vout = sh(["bash", os.path.join(root, ".loopwork", "hooks", "verify.sh")],
                        root, timeout=VERIFY_TIMEOUT)
        if code != 0:
            return reject(f"verify.sh 不是 exit 0（实际 {code}）——考题没全绿就不是绿存档。"
                          "看 .loopwork/logs/verify-*.log 最后 20 行。")
        warn = trip_note(vout)
    for i in range(0, len(take), 200):    # 点名暂存（--literal-pathspecs：路径里的 * ? [ 不当通配），分批免得命令行过长
        code, out = sh(["git", "--literal-pathspecs", "add", "-A", "--"] + take[i:i + 200],
                       root, timeout=60)
        if code != 0:
            return reject("git add 失败：" + out[-160:])
    code, out = sh(["git", "commit", "-m", msg], root, timeout=60)
    if code != 0:
        return reject("git commit 失败：" + out[-160:])
    _, head = sh(["git", "rev-parse", "HEAD"], root)
    st["last_round_commit"] = head          # 存档即推进基线，一步到位，不劳模型手推
    st.pop("pending_commit", None)
    if kind == "red":
        st["red_commit_pending"] = True     # 这张票是绿存档的入场券（先红后绿）
        note = (f"[代存档] 红存档已落 {head[:10]}：{msg}。基线已推进，可以开始写实现了。"
                + skipped_note(kind, skip, phase))
    elif kind == "note":
        # 记事存档不动轮数、不发也不吃红票——它不是一轮 TDD，只是把台账落进历史。
        note = f"[代存档] 记事存档已落 {head[:10]}：{msg}。基线已推进。" + skipped_note(kind, skip, phase)
    else:
        st["red_commit_pending"] = False
        st["round_count"] = int(st.get("round_count", 0) or 0) + 1
        note = (f"[代存档] 绿存档已落 {head[:10]}：{msg}。verify.sh 全绿，"
                f"基线已推进，本圈第 {st['round_count']} 轮。") + warn + skipped_note(kind, skip, phase)
        try:
            with open(os.path.join(root, "JOURNAL.md"), "a", encoding="utf-8") as jf:
                jf.write(f"- [存档] {head[:10]} {msg}\n")
        except Exception:
            pass
    save_state(root, st)
    return True, note

def gate_reason(root, st):
    """检测门：命中返回处置指令（原样交给模型当下一轮输入），干净返回 None。
    抽成函数是为了让「顶回」只有一个出口——顶回要记账，记账只能记一处。"""
    stage = str(st.get("stage", ""))
    phase = str(st.get("phase", ""))
    baseline = str(st.get("last_round_commit", "") or "")
    if stage in ("4", "loop", "quick") and os.path.isdir(os.path.join(root, ".git")):
        if baseline:
            code, _ = sh(["git", "merge-base", "--is-ancestor", baseline, "HEAD"], root)
            if code != 0:
                return (
                    "[检测门] 基线存档 " + baseline[:10] + " 在当前 git 历史中不可达——"
                    "历史可能被改写（amend/rebase）。停止一切实现工作：先向用户如实报告，"
                    "恢复历史或经用户同意后用 progress.py set last_round_commit 重设基线。"
                )
        if phase == "implementing":
            code, out = sh(["git", "diff", "--name-only", "HEAD"], root)
            code2, out2 = sh(["git", "ls-files", "--others", "--exclude-standard"], root)
            live = protected((out.splitlines() if code == 0 else []) +
                             (out2.splitlines() if code2 == 0 else []))
            if live:
                return (
                    "[检测门] 实现期有未存档的受保护文件改动：" + ", ".join(live[:5]) +
                    "。考题先红后绿，实现期间不许碰考题/规格/规矩；围栏脚本（.loopwork/hooks/）"
                    "任何时候都不许改。立即：①撤销"
                    "（已跟踪文件 git checkout -- <文件>；新建文件直接删除）"
                    "②在 JOURNAL.md 记一行原因 ③向用户说明。"
                )
            if baseline:
                code3, out3 = sh(["git", "diff", "--name-only", baseline, "HEAD"], root)
                committed = protected(out3.splitlines() if code3 == 0 else [])
                if committed:
                    return (
                        "[检测门] 基线之后有已存档的受保护文件改动：" + ", ".join(committed[:5]) +
                        "。代存档落档时会自动推进基线，所以这多半不是你登记的那次存档，"
                        "而是用户或别的会话手动 commit 的。确认无害就把基线对齐："
                        "python3 .loopwork/hooks/progress.py set last_round_commit "
                        "$(git rev-parse HEAD)；若是实现期偷改后存进去的——"
                        "revert 该存档、JOURNAL.md 记一行原因并向用户坦白。"
                    )

        # 只增不减（一）：JOURNAL.md 是历史，删行 = 抹掉证据（无论哪个相位）。
        # 两段都要看：基线..HEAD 抓「改写后存了档」，HEAD..工作区 抓「还没存档的改写」。
        gone = journal_deleted(root, [baseline, "HEAD"]) if baseline else 0
        gone += journal_deleted(root, ["HEAD"])
        if gone > 0:
            return (
                f"[检测门] JOURNAL.md 少了 {gone} 行——日志只增不减，改写过的历史不是证据。"
                "立即 git checkout -- JOURNAL.md 还原（已存档的改写用 git revert 撤销），"
                '要记新内容用 python3 .loopwork/hooks/progress.py journal "…" 追加；'
                "若删除是用户要求的，停下来让用户自己动手。"
            )

    # 只增不减（二）：审计账本只能变长。
    # 变短 = 有人抹账。唯一合法的变短是单代轮转（老账本被顶成 .1）。
    # 抹账无法由模型补回，所以只响一次：报完把基准重置，避免死循环把会话钉死。
    audit = os.path.join(root, ".loopwork", "logs", "audit.jsonl")
    try:
        now_bytes = os.path.getsize(audit)
    except OSError:
        now_bytes = None
    if now_bytes is not None:
        mark = st.get("audit_bytes")
        mark = int(mark) if str(mark).isdigit() else None
        if mark is not None and now_bytes < mark:
            try:
                rotated = os.path.getsize(audit + ".1")
            except OSError:
                rotated = 0
            st["audit_bytes"] = now_bytes
            save_state(root, st)
            if rotated < mark:
                return (
                    f"[检测门] 审计账本 .loopwork/logs/audit.jsonl 从 {mark} 字节缩到 {now_bytes} 字节，"
                    "且不是轮转——有人抹了账。审计只增不减：立即向用户如实报告这件事"
                    "（谁、什么时候、少了多少），并在 JOURNAL.md 记一行。基准已重置，不再重复顶回。"
                )
        elif now_bytes != mark:
            st["audit_bytes"] = now_bytes
            save_state(root, st)
    return None

def main():
    try:
        payload = {}
        try:
            payload = json.load(sys.stdin)
        except Exception:
            pass
        start = payload.get("cwd") or os.getcwd()
        root = (guard_log.find_root(start, script=__file__, env_keys=()) if guard_log is not None
                else start)
        state_p = os.path.join(root, ".loopwork", "state.json")
        if not os.path.exists(state_p):
            return 0
        with open(state_p, encoding="utf-8") as f:
            st = json.load(f)

        # 本轮取证：账本比上轮末多出几行，就是模型这一轮撞了几次墙。水位线在这里
        # 一次推进并落盘——不能让「记没记账」取决于后面走哪个分支。
        hits = round_hits(root, st)
        # 活体核对：本会话有没有收到过 PostToolUse 心跳。没有 = 接线在、平台没在跑围栏
        # （最常见是信任门没过 / 会话开在子目录）。只挂在顶回文案尾，不单独顶回。
        beat_note = (guard_log.no_beat_note(root, payload.get("session_id", ""))
                     if guard_log is not None else "")

        # 上一轮已优雅停机 → 本轮无条件放行一次，让会话真的能停下来交还给用户
        try:
            carried = int(st.get("stop_blocks", 0) or 0)
        except (TypeError, ValueError):
            carried = 0
        if carried < 0:
            st["stop_blocks"] = 0
            save_state(root, st)
            return 0

        # ---------- 0. 代存档（钩子在沙箱外，.git 只有它写得动）----------
        arch_ok, arch_text = archive_pending(root, st)
        arch_note = arch_text if arch_ok else ""      # 落成了：并进本轮那一次顶回
        arch_reject = "" if arch_ok else arch_text    # 被拒了：它就是本轮的顶回理由

        flag = os.path.join(root, ".loopwork", "batch.flag")
        has_flag = os.path.exists(flag)
        # flag 格式："起点,上次顶回轮数,无进展次数,顶回总数"（兼容旧版三段/两段/纯数字）
        raw = ""
        if has_flag:
            try:
                raw = open(flag, encoding="utf-8").read().strip()
            except Exception:
                pass
        parts = raw.split(",") if raw else []

        def num(i, default=None):
            return int(parts[i]) if len(parts) > i and parts[i].lstrip("-").isdigit() else default

        cap = int(st.get("round_cap", 20))
        batch_size = int(st.get("batch_size", 5))
        rounds = int(st.get("round_count", 0))
        start = num(0)
        if start is None:
            start = rounds
        last_nag = num(1)
        stalls = num(2, 0)
        blocks = num(3, 0) if has_flag else carried
        last_sig = parts[4] if len(parts) > 4 else ""   # 上次挂机顶回时的进展指纹

        def drop_flag():
            try:
                os.remove(flag)
            except OSError:
                pass

        def write_blocks(n):
            """顶回记账：批模式记 flag 第 4 段，非批模式记 state.stop_blocks。
            第 2、5 段（上次顶回轮数、进展指纹）原样带过去——它俩是一对，
            都是「上一次挂机顶回时的样子」，检测门的顶回不该动它们。"""
            if has_flag:
                with open(flag, "w", encoding="utf-8") as f:
                    f.write(f"{start},{'' if last_nag is None else last_nag},"
                            f"{stalls},{n},{last_sig}")
            else:
                st["stop_blocks"] = n
                save_state(root, st)

        def emit(msg):
            """本轮只顶回一次：代存档结果与检测门/挂机档要说的话合并成同一条，
            话尾挂上本轮取证——连撞同一面墙是「在找绕路」的信号，模型自己也该看见。"""
            return block((f"{arch_note}\n{msg}" if arch_note else msg) + hits_note(hits) + beat_note)

        def quiet():
            """没有要顶回的事。但刚落了存档就得顶回一次，把 hash 交到模型手里。"""
            return block(arch_note) if arch_note else 0

        def graceful(msg):
            """优雅停机：摘 flag + 记「下轮放行」，本次仍顶回一次把话说完。"""
            drop_flag()
            st["stop_blocks"] = -1
            save_state(root, st)
            return emit(msg)

        # ---------- 1. 检测门（永远执行，与批模式无关）----------
        # 代存档被拒时它就是本轮的理由：存档没落地，别再叠一条检测门的话进来。
        reason = arch_reject or gate_reason(root, st)
        if reason:
            blocks += 1
            if blocks >= MAX_BLOCKS:
                return graceful(
                    reason + f"\n[检测门] 同一违规已顶回 {MAX_BLOCKS} 次仍未消除，自动停机"
                    "（挂机批也一并停了）。不要再试第二遍：把这件事原样告诉用户，让他决定怎么办。"
                )
            write_blocks(blocks)
            return emit(reason)
        if not has_flag:
            if carried:  # 检测门通过 = 连续顶回的链断了，账清零
                st["stop_blocks"] = 0
                save_state(root, st)
            return quiet()

        # ---------- 2. 挂机批模式 ----------
        actionable = blocked = 0
        try:
            with open(os.path.join(root, "tasks.md"), encoding="utf-8") as f:
                for line in f:
                    s = line.strip()
                    if s.startswith("- [ ]"):
                        if "〔卡" in s:
                            blocked += 1
                        else:
                            actionable += 1
        except FileNotFoundError:
            pass

        def finish(msg):
            drop_flag()
            return emit(msg)

        if actionable <= 0 and blocked <= 0:
            drop_flag()
            return quiet()  # 任务全清，正常收工
        if actionable <= 0:
            return finish(f"[挂机档] 只剩 {blocked} 条受阻任务。汇总本批结果，把问题本（BLOCKED.md）提请用户拍板。")
        if rounds >= cap:
            return finish(f"[挂机档] 轮数达上限 {cap}，安全停机。汇总本批并请用户验收。")
        if rounds - start >= batch_size:
            return finish(f"[挂机档] 本批已做满 {batch_size} 条（外部计数）。按纪律进验收环节，不许跳过检查点。")
        # 无进展 = 轮数没涨 ∧ HEAD 没动 ∧ tasks.md 没动 ∧ BLOCKED.md 没动（见 progress_sig）。
        # 只看轮数会把「一条硬任务跨两次顶回」误判成打转——红考题存了档、任务标了〔卡〕、
        # 问题本添了一条，都是进展，不该因此停批。
        sig = progress_sig(root)
        if last_nag is not None and rounds == last_nag and sig == last_sig:
            stalls += 1
            if stalls >= MAX_STALLS:
                return finish(
                    f"[挂机档] 连续 {MAX_STALLS} 次顶回一点进展都没有（仍是第 {rounds} 轮，"
                    "HEAD、tasks.md、BLOCKED.md 都没动过），判定原地打转，自动停批。"
                    "请按停批汇报格式向用户汇总：完成了什么、卡在哪、问题本新增了什么。"
                )
        else:
            stalls = 0
        blocks += 1
        if blocks >= MAX_BLOCKS:
            return graceful(
                f"[挂机档] 本批顶回已达安全上限（{MAX_BLOCKS} 次），自动停批。"
                "请按停批汇报格式向用户汇总进度；要继续挂机请用户重新开批。"
            )
        with open(flag, "w", encoding="utf-8") as f:
            f.write(f"{start},{rounds},{stalls},{blocks},{sig}")
        if stalls > 0:
            return emit(
                f"[挂机档] 顶回后轮数没涨（仍是第 {rounds} 轮），存档、tasks.md、BLOCKED.md 也都没动——"
                "若卡在同一任务：按失败分级处理（3 次转诊断），或写 BLOCKED.md 跳过取下一条。"
                "再次无进展将自动停批。"
            )
        return emit(
            f"[挂机档] 批模式进行中：本批 {rounds - start}/{batch_size} 条，剩余可做 {actionable} 条"
            f"（总轮数 {rounds}/{cap}）。按内循环节奏继续取下一条任务。用户喊停 = 删除 .loopwork/batch.flag。"
        )
    except Exception:
        return 0

if __name__ == "__main__":
    sys.exit(main())
