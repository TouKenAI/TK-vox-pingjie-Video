#!/usr/bin/env python3
"""V6.1 渲染前三门禁:
1) 素材账本 —— scene JSON 引用图必须在 ledger 且 production=本目录名(跨片零复用)
2) 节奏密度 —— 每场景任意 120 帧滑窗必有 keyframe/effect 事件(防静帧)
3) 长场景换式 —— >600 帧的场景,主力动效层须有方向反转或 scale 非单调(防"一直走")
用法: python preflight_v6.py <项目目录>
"""

from __future__ import annotations

import json
import re as _re          # 切点声明要从 KICKOFF 文本里正则取（V3.41）
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")   # FAIL 信息走 stderr；只配 stdout 时管道/日志里是乱码
except (AttributeError, ValueError):
    pass  # 老 Python/流被重定向才有;NameError(漏 import sys)必须响,不能装死  # 老 Python 没这 API；有就救回 ✓/⚠ 不被 GBK 崩掉

WINDOW = 120
LONG_SCENE = 600


# V3.22: 渲染器对 effects 各类型**实际读取**的键(照 render_sequence.draw_burst/draw_debris 抄)。
# 用途: 缺必需键=ERROR(渲到一半 KeyError), 出现渲染器不读的键=WARN(拼错的可选键会静默退回默认值)。
EFFECT_REQUIRED = {
    "radial-burst": {"start_frame", "end_frame", "origin"},
    "debris": {"start_frame", "end_frame", "origin", "source", "sprite_boxes"},
}
EFFECT_OPTIONAL = {
    "type", "ray_count", "max_ray_length", "color",
    "particle_count", "max_delay", "vx", "vy", "gravity", "scale", "fade_after",
}


def sign(v: float) -> int:
    return 1 if v > 1e-6 else (-1 if v < -1e-6 else 0)


def check_scene_motion(name: str, d: dict) -> list[str]:
    """长场景:找关键帧最多的动效层,要求 ≥6 个关键帧 且 存在方向反转或 scale 换向。"""
    total = round(d["duration_s"] * 30)
    if total <= LONG_SCENE:
        return []
    best, best_n = None, 0
    for l in d.get("layers", []):
        ks = sorted(l.get("keyframes", []), key=lambda k: k["frame"])
        if len(ks) > best_n and not l["id"].startswith("t_"):
            best, best_n = l, len(ks)
    if not best or best_n < 6:
        return [f"[换式] {name} >{LONG_SCENE}f 但主力动效层关键帧仅 {best_n}(<6),单调动效"]
    ks = sorted(best["keyframes"], key=lambda k: k["frame"])
    dx = [sign(ks[i+1]["x"] - ks[i]["x"]) for i in range(len(ks)-1)]
    dy = [sign(ks[i+1]["y"] - ks[i]["y"]) for i in range(len(ks)-1)]
    ds = [sign(ks[i+1]["scale"] - ks[i]["scale"]) for i in range(len(ks)-1)]
    rev = any(a * b < 0 for a, b in zip(dx, dx[1:])) or \
          any(a * b < 0 for a, b in zip(dy, dy[1:])) or \
          any(a * b < 0 for a, b in zip(ds, ds[1:]))
    if not rev:
        return [f"[换式] {name} 主力层 '{best['id']}' 无方向反转/缩放换向——像'一直走',应加停顿回望或变速"]
    return []


def main() -> None:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    ledger = {}
    lg = root / "assets" / "ledger.jsonl"
    if not lg.exists():
        sys.exit("FATAL: assets/ledger.jsonl 不存在(先跑生图登记)")
    for line in lg.read_text(encoding="utf-8").splitlines():
        try:
            e = json.loads(line)
            ledger.setdefault(e["file"], e)
        except Exception:
            pass

    scenes = sorted(root.glob("scene_s*.json"))
    if not scenes:
        sys.exit("FATAL: 无 scene_s*.json")
    errors = []
    warns = []
    refs = set()
    for sp in scenes:
        d = json.loads(sp.read_text(encoding="utf-8"))
        paths = [d["background"]["path"]] + [l["path"] for l in d.get("layers", []) if "path" in l]
        paths += [e["source"] for e in d.get("effects", []) if "source" in e]
        # V8.2.2: seq_dir 数字序列层无 path, 校验目录存在且末帧已登记账本
        for l in d.get("layers", []):
            sd = l.get("seq_dir")
            if sd:
                sd_dir = root / sd
                if not sd_dir.exists():
                    errors.append(f"[账本] {sp.name} seq_dir {sd} 目录不存在")
                else:
                    frames = sorted(sd_dir.glob("*.png"))
                    if not frames:
                        errors.append(f"[账本] {sp.name} seq_dir {sd} 无序列帧")
                    else:
                        last = "assets/" + frames[-1].relative_to(root / "assets").as_posix()
                        if last not in ledger:
                            errors.append(f"[账本] {sp.name} seq_dir 末帧 {last} 未登记")
        for p in paths:
            norm = p.replace("\\", "/")
            refs.add(norm)
            ent = ledger.get(norm)
            if ent is None:
                errors.append(f"[账本] {sp.name} 引用 {norm} 未登记")
            elif ent["production"] != root.name:
                errors.append(f"[账本] {sp.name} 引用 {norm} 出生地={ent['production']} 跨片复用")

        # V3.24 顶层标量门: render_sequence 用 int(plan["seed"]) 取随机种子。
        # p16 实录: build_scenes 误把场景名当 seed 传进去(scene() 第 1 参是整数),
        # 五道渲前门全绿, 一直到 animatic 真渲染才 ValueError —— 白跑一轮。在这里点名。
        for _k, _cast, _dflt in (("seed", int, 1), ("fps", int, 30)):
            _v = d.get(_k, _dflt)
            try:
                _cast(_v)
            except (TypeError, ValueError):
                errors.append(f"[顶层字段] {sp.name} 的 {_k}={_v!r} 不是 {_cast.__name__}"
                              f" —— 渲染器 int({_k}) 会直接崩; scene() 第 1 参是整数 seed, 不是场景名")
        _cv = (d.get("canvas") or {})
        if not (isinstance(_cv.get("width"), int) and isinstance(_cv.get("height"), int)):
            errors.append(f"[顶层字段] {sp.name} canvas 缺 width/height 整数")
        if not d.get("background", {}).get("path"):
            errors.append(f"[顶层字段] {sp.name} background.path 缺失")

        # V3.6 元素下限: 每场图层(主体+卡+道具)不得过少, 防"越做越薄"退化
        # V3.11: 默认 6→7, 锁定 production8 质量基线(用户2026-09-16 钦定 p8 为最满意标杆, 后续不得低于)
        _minl = int(__import__("os").environ.get("MIN_LAYERS", "7"))
        _nl = len(d.get("layers", []))
        if _nl < _minl:
            errors.append(f"[元素下限] {sp.name} 仅 {_nl} 图层 < {_minl}——画面太薄, 补主体/道具/卡")
        # V3.22 关键帧结构门: keyframes 必须是 **dict 列表**。模板里 fly(fade=True) 曾把裸元组
        # 直接 append 进去 → 本文件与 first_frame_check / layout_check / 渲染器全部 .get() 崩栈,
        # 报的是 TypeError/'list' has no attribute 'get', 不告诉你是哪一场哪一层。先点名再统计。
        _total_f = round(float(d.get("duration_s", 0) or 0) * 30)   # 供下面的越界检查用(正式 total 在下方)
        for l in d.get("layers", []):
            _fr = []
            for _i, k in enumerate(l.get("keyframes", []) or []):
                if not isinstance(k, dict):
                    errors.append(f"[关键帧结构] {sp.name} 图层 {l.get('id','?')} keyframes[{_i}] 不是字典"
                                  f"(得到 {type(k).__name__}: {str(k)[:60]})——helper 里裸元组要走 kf() 转换")
                    continue
                if "frame" not in k:
                    errors.append(f"[关键帧结构] {sp.name} 图层 {l.get('id','?')} keyframes[{_i}] 缺 frame 键")
                    continue
                _fr.append(k["frame"])
            # V3.26 关键帧顺序门。渲染器 render_sequence:45 会 `sorted(keys)` 再"第 0 帧钳到首帧姿态",
            # 于是**写乱顺序的图层会在入场前就按满不透明姿态画出来**。实测 5 部已交付片 18 个图层顺序
            # 非升序, 其中 12 个的首帧 opacity≥0.4 → 元素提前 1.6~6.5 秒全程可见(p14 s01 的交叉箭头
            # 设计入场 6.5s, 实际第 0 帧就在画面里)。两道门都漏: first_frame_check 只要求"第 0 帧有
            # 不透明图层"(反而更容易绿), layout_check 用未排序的 keyframes[0] 把入场前的帧全部跳过。
            if any(f < 0 for f in _fr):
                errors.append(f"[关键帧顺序] {sp.name} 图层 {l.get('id','?')} 有负帧号 "
                              f"{sorted(set(f for f in _fr if f < 0))}"
                              f" —— 渲染器按最小帧钳位, 负帧会让图层带着进行中的姿态从第 0 帧就开始")
            if _fr != sorted(_fr):
                errors.append(f"[关键帧顺序] {sp.name} 图层 {l.get('id','?')} 关键帧 frame 非升序 {_fr}"
                              f" → 排序后首帧={min(_fr)}f({min(_fr)/30:.1f}s); 若该帧 opacity≥0.4,"
                              f" 图层会在入场前就被画满。生成处按时间顺序 append, 或显式 sort")
            # V3.28 图层 jitter 形状门。渲染器 `jitter.get("hold")` 要求图层 jitter 是 **dict**
            # {x,y,rotation,hold}(模板 JIT)，而**背景**的 jitter 才是 list [0,0] —— 两个同名字段
            # 形状不同。p18 实录：为了"关掉水墨抖动"把图层 jitter 写成 [0,0]，s03/s16 在渲染器里
            # AttributeError 崩掉，**431 秒并行渲染跑完才暴露**，且那两场是 0 帧。
            # 关抖动的正确做法是删键(渲染器缺省 {} → 幅度 0)。这条纯形状判定不该用一次渲染去换。
            _j = l.get("jitter", None)
            if _j is not None and not isinstance(_j, dict):
                errors.append(f"[jitter形状] {sp.name} 图层 {l.get('id','?')} 的 jitter={_j!r} 不是 dict"
                              f" —— 图层 jitter 必须是 {{'x','y','rotation','hold'}} 形状(背景才是 list)；"
                              f"想关抖动请**删掉这个键**，渲染器缺省按 0 幅度处理")
            elif isinstance(_j, dict):
                _bad = [k for k in _j if k not in ("x", "y", "rotation", "hold")]
                if _bad:
                    errors.append(f"[jitter形状] {sp.name} 图层 {l.get('id','?')} jitter 有渲染器不读的键 "
                                  f"{_bad}(写了也不生效, 见 effects 同类门)")
            # 越界: 渲染器循环是 range(frame_count), 最大帧号 total-1, 所以 mx>=total 的那一拍永远到不了。
            # mx == total 是**全库通行写法**(245 处里 225 处是这样, 只差 33ms), 报出来只会淹掉消息, 故不报;
            # 明显越界(>total)才 WARN —— p16 实测 4 个 ip_host 图层末关键帧落在 1038~1088 帧,
            # 而所在场只有 84~265 帧: 那是把**全片秒数当成场内帧号**用了, 退场动画一次都没播过。
            if _fr and max(_fr) > _total_f:
                warns.append(f"[关键帧越界] {sp.name} 图层 {l.get('id','?')} 末关键帧 {max(_fr)}f 超出本场 {_total_f}f"
                             f" 共 {max(_fr) - _total_f}f —— 渲染器到不了这一拍, 该图层的退场/收尾动画被静默丢弃;"
                             f" 若这是全片时间轴的数字, 说明混用了全局帧号与场内帧号")
        total = round(d["duration_s"] * 30)
        ev = set()
        for l in d.get("layers", []):
            for k in l.get("keyframes", []):
                if isinstance(k, dict):
                    ev.add(k["frame"])
        for _i, e in enumerate(d.get("effects", [])):
            # fly_blur/slam_squash/pop_spring 返回的是**图层**, 误塞进 E 会在此 KeyError 崩半路(p13)
            if not isinstance(e, dict) or "start_frame" not in e:
                errors.append(f"[effects 结构] {sp.name} effects[{_i}] 不是带 start_frame 的效果字典"
                              f"(得到 {type(e).__name__})——图层一律进 L,E 只放 burst/motes")
                continue
            # V3.22: 按类型查必需键 + 拦"拼错的可选键"。渲染器读 max_ray_length, 写成 length
            # 会**静默退回默认 280**(p15 15 场全中招); debris 缺 source/sprite_boxes 则渲到
            # 一半 KeyError。两者都是"门绿了、画面错了"的静默失效, 必须在渲前点名。
            _et = str(e.get("type", ""))
            _req = EFFECT_REQUIRED.get(_et)
            if _req is None:
                if _et not in ("radial-burst", "debris"):
                    warns.append(f"[effects] {sp.name} effects[{_i}] 未知类型 {_et!r}——渲染器只认 radial-burst/debris")
            else:
                miss = [k for k in _req if k not in e]
                if miss:
                    errors.append(f"[effects 结构] {sp.name} effects[{_i}] type={_et} 缺必需键 {miss}")
                unknown = [k for k in e if k not in _req | EFFECT_OPTIONAL]
                if unknown:
                    warns.append(f"[effects 键名] {sp.name} effects[{_i}] type={_et} 有渲染器不读的键 {unknown}"
                                 f"(拼错的可选键会静默退回默认值, 不是报错)")
            ev.add(e["start_frame"]); ev.add(e["end_frame"])
        evs = sorted(f for f in ev if 0 <= f < total)
        # V3.26 修尾窗盲区: 旧版 range(0, total-WINDOW+1, 60) 在 total=159 时只得到 st=0,
        # 即只查 0-119 帧, 120-158 可以一个事件都没有照样 PASS(最多 59 帧无人看守),
        # 与本文档"每场景任意 120 帧滑窗"的承诺不符。补一个贴尾窗。
        _ws = list(range(0, max(1, total - WINDOW + 1), 60))
        if total > WINDOW and (_ws[-1] if _ws else -1) != total - WINDOW:
            _ws.append(total - WINDOW)
        for st in _ws:
            if not any(st <= f < st + WINDOW for f in evs):
                errors.append(f"[节奏] {sp.name} 帧{st}-{st+WINDOW} 无事件")
        errors += check_scene_motion(sp.name, d)
        print(f"{sp.name}: {total}f 事件{len(evs)} 密度{len(evs)/max(1,total/WINDOW):.1f}/窗")

    # ---- V300 呼吸预算(R1): 最后一张**进场**的字卡要有 ≥30f(1s) 停留 ----
    # 旧判据取"最后一个不透明关键帧"，而模板每张卡都以 `[场景末, opacity 1]` 收尾，
    # 于是它恒等于"距场景末 1f"：已交付的 p22(审美 87.9)与 p23 各刷 11 条一模一样的 WARN。
    # 一条永远亮红的门等于没有门(§57)，所以改成量真正要量的东西——这张卡**什么时候出现**、
    # 出现之后还剩几帧可看。
    for sp in scenes:
        d = json.loads(sp.read_text(encoding="utf-8"))
        total_f = round(d["duration_s"] * 30)
        late = []
        for l in d.get("layers", []):
            # V8.1.1: 与 layout_check 同判据——id 前缀 t_/c_ 或 path=assets/text/ 均算文字卡
            if not (l["id"].startswith(("t_", "c_")) or str(l.get("path", "")).startswith("assets/text/")):
                continue
            opaque = [k["frame"] for k in l.get("keyframes", []) if k.get("opacity", 0) >= 0.9]
            if not opaque:
                continue
            entry = min(opaque)
            if total_f - entry < 30:
                late.append((entry, l["id"], total_f - entry))
        if late:
            entry, pid, gap = max(late)
            warns.append(f"[呼吸] {sp.name} 字卡 {pid} 第 {entry}f 才进场、只停 {gap}f"
                         f"(<30f/1s)——用 clamp_card_in() 在设计期夹帧(R1)")

    # ---- V300 冲击预算(R4): 全片大 burst(ray_count≥12) ≤3 处 ----
    big_bursts = 0
    for sp in scenes:
        d = json.loads(sp.read_text(encoding="utf-8"))
        for e in d.get("effects", []):
            if not isinstance(e, dict):
                continue  # 图层误塞进 E 的情况上面已记账; 这里再 e.get() 会把设计好的报错变成 AttributeError
            if e.get("type") == "radial-burst" and e.get("ray_count", 0) >= 12:
                big_bursts += 1
    if big_bursts > 3:
        warns.append(f"[冲击] 全片大 burst(ray_count≥12) {big_bursts} 处>3(R4)")

    # ---- V3.29/V3.41 节拍切点生效门（p20 立，p26 补全）----
    # 规矩是 build_scenes → split_beats → 渲染。p20 我在 split_beats 之后又跑了三轮 build_scenes，
    # 场景 JSON 被覆盖回"一镜到底"，渲完 471s 才发现 S03 的 10.8s 只有一条线性推镜——六道工序没有一道会红。
    # 判据只看产物本身：这场声明了 N 个切点，相机就必须有 **2+N 段**关键帧。
    #   2+N 不是推的，是实测的：p24/p25 的 (声明数, 相机段数) 分布 = {(0,2), (1,3)}，
    #   即 split_beats 每加一个切点多产出恰好一段。旧版写成 "≥N+1"，1 个切点只要 2 段就放行，
    #   而 2 段=一条线性推镜=根本没切——**旧判据自己就是那个漏口**。
    # V3.41 补的第二件事：声明的来源有两处，必须**逐场合并**。第一版写成"没有 beats.json 才读 B 表"
    #   (all-or-nothing)，实测：beats.json 只写 S02 时，S01 在 B 表声明的切点整段不查、门静默。
    try:
        _bt = json.loads((root / "qa" / "beats.json").read_text(encoding="utf-8"))
        _cuts = _bt.get("scenes", {}) if isinstance(_bt, dict) else {}
    except FileNotFoundError:
        _cuts = {}
    except Exception as e:                      # beats.json 存在但读不动/格式错：必须响，不能当"没声明"
        errors.append(f"[beats.json] 读不动: {e!r} —— 不能把坏文件当成『没有切点声明』放行")
        _cuts = {}
    NONE_CLAIM = {"", "-", "—", "无", "一镜到底", "保持一镜", "n/a", "N/A"}
    _claim_txt = {}
    kf_md = root / "KICKOFF.md"
    if kf_md.exists():
        in_b = False
        for ln in kf_md.read_text(encoding="utf-8").splitlines():
            if ln.startswith("#"):
                in_b = bool(_re.match(r"#+\s*B[\.、\s]", ln.strip())); continue
            if in_b and _re.match(r"\|\s*S\d+", ln):
                cells = [c.strip() for c in ln.strip().strip("|").split("|")]
                if len(cells) >= 8:
                    _claim_txt[int("".join(c for c in cells[0] if c.isdigit())[-2:])] = cells[7]
    m_w = _re.search(r"^\s*[`*>#\-\s]*cuts_waived\s*[:：]\s*(.*?)\s*[`*]*\s*$",
                     kf_md.read_text(encoding="utf-8") if kf_md.exists() else "", _re.M)
    # 豁免必须说清"为什么这部片不该切"。第一版只要求 ≥6 字，实测"全片一镜到底"六个字就把门洗白
    # (§70 同一类病：允许书面豁免的硬门，豁免解析器本身必须做 RED 探针)。
    _BAD_WHY = {"豁免", "无", "N/A", "na", "-", "ok", "好", "一镜到底", "保持一镜",
                "全片一镜到底", "不需要切点", "就这样"}
    _why = m_w.group(1).strip() if m_w else ""
    waived = len(_why) >= 20 and _why not in _BAD_WHY
    missed_b, missed_bt, checked_b, checked_bt = [], [], 0, 0
    for sp in scenes:
        n = int("".join(c for c in sp.stem if c.isdigit())[-2:])
        _no = "S%02d" % n
        d = json.loads(sp.read_text(encoding="utf-8"))
        n_cam = len(d.get("camera_motion", {}).get("keyframes", []))
        dur = d.get("duration_s", 0)
        if _cuts.get(_no):                                   # ① beats.json 说话优先（它才是 split_beats 的输入）
            nb = len(_cuts[_no]); checked_bt += 1
            if n_cam < nb + 2:
                missed_bt.append(f"{sp.name}(声明 {nb} 切点/相机 {n_cam} 段，需 ≥{nb + 2})")
            continue
        claim = _claim_txt.get(n, "")                         # ② 否则回落到 KICKOFF B 表第 8 列
        if claim in NONE_CLAIM or claim.startswith("无"):
            continue
        if dur <= 6:
            continue                                          # B 表那一列本就只管 >6s 的场
        checked_b += 1
        if n_cam < 3:
            missed_b.append(f"S{n:02d}({dur:.1f}s)")
    if missed_bt:
        errors.append(f"[切点丢失] beats.json 声明的切点没落到相机上：{'; '.join(missed_bt)}"
                      f"——split_beats 没跑，或跑完又被 build_scenes 覆盖了。"
                      f"正确顺序：build_scenes → split_beats → 渲染")
    if missed_b:
        if waived:
            print(f"· [切点] B 表声明的 {len(missed_b)} 场未落地：{' '.join(missed_b)}"
                  f" —— 已按 KICKOFF `cuts_waived: {_why}` 放行")
        else:
            errors.append(f"[切点丢失] {' '.join(missed_b)} 在 KICKOFF B 表声明了「>6s 的景别切点」，"
                          f"相机却只有 2 段关键帧(一镜到底)。要么写 qa/beats.json 后跑 "
                          f"`py -3.14 scripts/split_beats.py {root.name}`，"
                          f"要么在 KICKOFF 明写 `cuts_waived: <≥20 字的理由>`")
    elif checked_b or checked_bt:
        print(f"· [切点] 对账 {checked_bt + checked_b} 场(beats.json {checked_bt} / B 表 {checked_b})，全部落地")

    print(f"\n素材引用 {len(refs)} 项")
    # V3.26: 旧版 `if errors: sys.exit(1)` 排在打印 warns 之前 → **门一红, 全部 WARN 就看不见**。
    # 实测因此多跑一轮: 修完 7 条关键帧顺序错, 才发现还有 4 条 ip_host 越界 WARN。先报完再退出。
    for w in warns:
        print("WARN:", w)
    if errors:
        print("=== FAIL ===")
        for e in errors:
            print(" ", e)
        print(f"共 {len(errors)} 条 ERROR / {len(warns)} 条 WARN")
        sys.exit(1)
    print("PASS: 账本清白 + 节奏密度达标 + 长场景换式达标" + (f" ({len(warns)} WARN)" if warns else ""))


if __name__ == "__main__":
    main()
