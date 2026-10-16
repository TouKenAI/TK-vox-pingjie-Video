#!/usr/bin/env python3
"""V6.1 场景生成器模板 —— 复制到项目根改名 build_scenes.py 后改场景函数。

V6.1 新增（相对 V6）：
- card() 四种入场模式轮换：bounce 弹入 / slide 滑移(带方向) / flip 翻页 / emph 两段强调
  用法: card("t_x", 600, x, y, f_in, mode="slide", slide_dir=(1,0))
- ghost() 残影拖尾：出画主体 2 层 opacity 递减幽灵层（矢量接力的"甩"感）
- drop_in() 坠落回弹四段式（V5 传承）
- motes() drift-motes 漂浮纸屑（debris 零重力实现，需 confetti_sheet.png）
- relay() handoff 常量速记：矢量接力字段直接进 shot-plan
规则：>20s 场景主要主体≥2 种动效式（preflight_v6 会查）；单一卡片模式占比≤50%。
"""

from __future__ import annotations

import json
import sys
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parent
W, H = 1080, 1440
# V8.1.8 视觉增强: 阴影更强/更贴地(offset 下移=接触投影), 消"贴纸感"——新片全层生效
SHADOW = {"blur": 14, "offset": [8, 11], "color": [0, 0, 0, 185]}
BIG = {"blur": 20, "offset": [13, 18], "color": [0, 0, 0, 165]}
JIT = {"x": 1, "y": 1, "rotation": 0.15, "hold": 5}

# V8.1.8 数字增长动画(获得感杠杆): make_countup.py 生成帧序列 → scene 里加 seq 层
#   {"id": "c_count", "seq_dir": "assets/text/count_72", "seq_rate": 1,
#    "base_width": 620, "anchor": [0.5, 0.5], "z": 14,
#    "keyframes": kf((f0, 540, 760, 1.0, 0, 0), (f0 + 40, 540, 760, 1.0, 0, 1))}
#   seq_rate=1 → 每渲染帧换一张(36 帧=1.2s); 末帧定格自动; 可再配 kf scale 放大强调
# 金句定格 zoom(惊喜感): 金句卡入屏 bounce 后加 scale 1→1.15 缓放 + 场景 camera 微缩 1.0→1.05


def stagger_decreasing(base: int, decay: float = 0.7, n: int = 5, min_gap: int = 2) -> list:
    """递减错帧(V7.0/video-shotcraft R2+card-stack):首卡 base 帧、逐卡 ×decay、最低 min_gap。
    返回 [gap0, gap1, ...](n-1 个间隔)。比等距 stagger 更有加速感。
    用法: f_start = f0; for gap in stagger_decreasing(8, 0.7, 5): f_start += gap; card(..., f_in=f_start)"""
    gaps = []
    cur = base
    for _ in range(n - 1):
        gaps.append(max(min_gap, round(cur)))
        cur *= decay
    return gaps


def kf(*rows):
    """keyframes 元组行写法(V7.0 推广,P11 根治手写括号错):
    kf((frame,x,y,scale,rot,opacity[,ease]), ...) -> [{"frame":..,"x":..,...}]
    杜绝手写图层 dict 收尾错误(P11 事故:括号连环错 3 轮)。"""
    out = []
    for r in rows:
        row = {"frame": r[0], "x": r[1], "y": r[2], "scale": r[3], "rotation": r[4], "opacity": r[5]}
        if len(r) == 7:
            row["ease"] = r[6]
        out.append(row)
    return out


def ip_host(png, x, y, f_in, f_out, width=330, z=15, enter_ease="ease-out-back"):
    """V8.1.2 IP 角色层("讲书人")—— z=15(道具上/字卡下,试产实录:z 低会被遮)。
    png ∈ present/point/wave(姿态库见 ip_registry.json); 出场节奏=钩子讲解/金句指向/CTA 挥手, 每片≤3 处。
    pose 生成契约: prompt 必须逐字复述身份特征(眼镜/发型/服装色), 禁止只靠 --ref。"""
    return {"id": f"ip_host_{png}", "path": f"assets/source/ip_{png}.png", "trim_alpha": True,
            "base_width": width, "anchor": [0.5, 0.5], "z": z,
            "keyframes": kf((f_in, x, y + 60, 0.85, 0, 0),
                          (f_in + 28, x, y, 1.0, 0, 1, enter_ease),
                          (f_out - 16, x, y, 1.0, 0, 1),
                          (f_out, x, y + 8, 0.97, 0, 0, "ease-in")),
            "jitter": {"x": 1, "y": 1, "rotation": 0.15, "hold": 5},
            "shadow": {"blur": 14, "offset": [7, 9], "color": [0, 0, 0, 140]}}


def clamp_card_in(f_in, scene_frames, breath=56):
    """V3.19 呼吸门(R1)设计期夹帧:字卡入场帧不得晚于 场景末-breath。
    bounce/emph 落定约 14-20f,再加 ≥30f 呼吸留白 → 56f。
    短场(<3s)里"说到才出"的字卡天然贴场景末,事后调坐标无效,必须在算 f_in 时就夹(p13 实录 5 场 WARN)。"""
    return max(0, min(f_in, scene_frames - breath))


# ============ V3.34 平台安全夹取盒 + 名字卡提前量（p23 实测两条，模板化） ============
# p23 手工付过的两笔学费，别在下一部再付一次：
#  ① 58→42→17→0 次坐标夹取失败：文字卡要躲**平台互动按钮区(右 130px)**和**自动字幕带(y>1160)**，
#    而道具/纸人/标注线**必须允许出血**（柜台横贯画面、雨棚贴顶、纸人脚在画外）。
#    一套盒子夹所有层 = 要么卡出画，要么把贯穿画面的线截成小棍。所以是**两个盒子**。
#  ② name_ledger 5 处 FAIL（酷安 18% / 6.4 27% / 防窥 0%×2 / 小米之家 27%）：名字卡若"念到才入场"，
#    落定行程走完时这句话已经念过去了，覆盖率永远不够 60%。入场帧必须**提前一个落定行程**。
CARD_EDGE = {"left": 70, "top": 300, "right": 880, "bottom": 1080}   # 中心点边界；右缘 880 < 950(1080-130)
STAGE_EDGE = {"left": 30, "top": 210, "right": 1050, "bottom": 1330}  # 舞台件允许出血
ENTRY_TRAVEL = {"bounce": 6, "slide": 8, "flip": 8, "emph": 14,
                "drop_in": 22, "slam_squash": 22, "fly": 20, "land": 22, "drop_on": 14}


def clamp_center(x, y, w, h, edge=None, decor=False):
    """把中心点夹进盒子。返回 (nx, ny, moved)——moved>0 说明设计坐标越界，建场脚本应收集它并在
    verify() 里断言为空（p23 的 CLAMP_FAIL 就是这么从 58 条清到 0 的：每条都照着改坐标，而不是放宽盒子）。
    decor=True = 舞台涂装（整幅分界线/雨棚/彩带），设计上就要出血，原样返回。"""
    if decor:
        return x, y, 0.0
    e = edge or CARD_EDGE
    nx = min(max(x, e["left"] + w / 2), max(e["left"] + w / 2, e["right"] - w / 2))
    ny = min(max(y, e["top"] + h / 2), max(e["top"] + h / 2, e["bottom"] - h / 2))
    return nx, ny, abs(nx - x) + abs(ny - y)


def stage_or_card(path):
    """按盘路径选盒子：assets/source 与 assets/lines 是舞台件（出血），其余（字卡/读数）走平台安全盒。"""
    p = str(path).replace("\\", "/")
    return STAGE_EDGE if ("/source/" in p or "/lines/" in p) else CARD_EDGE


def name_lead(f_anchor, mode="bounce", pad=0):
    """名字卡入场帧 = 念到该名字的帧 − 落定行程 − pad。
    name_ledger 要求名字在念它的窗口里在屏 ≥60%；"说到才出"的卡落定完这句话也念完了(p23 五处 FAIL)。
    mode 必须和实际用的入场动效一致——行程取错就等于没提前。"""
    return max(0, f_anchor - ENTRY_TRAVEL.get(mode, 8) - pad)


def card(name, width, x, y, f_in, mode="bounce", slide_dir=(0, 1), rot=0.0,
         f_out=None, z=20, path=None, label=None):
    """文字卡四模式入场。slide_dir 是滑移入的方向单位向量(接力方向)。
    每片轮换使用，单一模式占比应 ≤50%。

    `path`  —— 显式盘路径。项目若由 `assets/text/manifest.json` 发号(如 p19)，就按 manifest 传，
               别让下面的前缀兜底去猜文件名：p18 那次 `card("c11ch")` 与场景里 `c_11ch` 对不上
               直接 FileNotFoundError，根因就是文件名有两个来源。
    `label` —— 这层屏幕上写的**名字**。§66 名字对账门(name_ledger)只认这个字段；
               不登记 label 的层对门来说是隐形的，等于没有对账。"""
    d = [max(-1, min(1, v)) for v in slide_dir]
    if mode == "slide":        # 从动势反方向滑入 90px + 淡入
        k = [
            {"frame": max(0, f_in-8), "x": x - d[0]*90, "y": y - d[1]*90, "scale": 1.0, "rotation": rot, "opacity": 0},
            {"frame": f_in, "x": x, "y": y, "scale": 1.0, "rotation": rot, "opacity": 1, "ease": "ease-out"},
        ]
    elif mode == "flip":       # 翻页感:rot ±22° 归零 + 轻微放大
        k = [
            {"frame": max(0, f_in-8), "x": x, "y": y-10, "scale": 0.94, "rotation": rot + 22*abs(d[0] or 1)*(1 if d[0] >= 0 else -1), "opacity": 0},
            {"frame": f_in, "x": x, "y": y, "scale": 1.0, "rotation": rot, "opacity": 1, "ease": "ease-out"},
        ]
    elif mode == "emph":       # 两段强调:先落小定住,再弹大一次
        k = [
            {"frame": max(0, f_in-6), "x": x, "y": y-14, "scale": 1.12, "rotation": rot*1.6, "opacity": 0},
            {"frame": f_in, "x": x, "y": y, "scale": 0.96, "rotation": rot, "opacity": 1, "ease": "ease-out"},
            {"frame": f_in+7, "x": x, "y": y-4, "scale": 1.04, "rotation": rot, "opacity": 1, "ease": "ease-in-out"},
            {"frame": f_in+14, "x": x, "y": y, "scale": 1.0, "rotation": rot, "opacity": 1, "ease": "ease-out"},
        ]
    else:                      # bounce 默认弹入(V5 传承)
        k = [
            {"frame": max(0, f_in-6), "x": x, "y": y-14, "scale": 1.12, "rotation": rot*1.6, "opacity": 0},
            {"frame": f_in, "x": x, "y": y, "scale": 1.0, "rotation": rot, "opacity": 1, "ease": "ease-out"},
        ]
    if f_out is not None:
        k += [{"frame": f_out-10, "x": x, "y": y, "scale": 1.0, "rotation": rot, "opacity": 1},
              {"frame": f_out, "x": x + d[0]*10, "y": y-10, "scale": 0.96, "rotation": rot*2.2, "opacity": 0}]
    # V8.1.1: 文件名前缀归一化——文字卡盘上以 c_/t_ 开头(make_cards 产物),调用方漏写/双写前缀都在这里兜住
    if not name.startswith(("c_", "t_")):
        name = f"c_{name}"
    lay = {"id": name, "path": path or f"assets/text/{name}.png", "trim_alpha": True,
           "base_width": width, "anchor": [0.5, 0.5], "z": z, "shadow": SHADOW, "keyframes": k}
    if label:
        lay["label"] = label
    return lay


def ghost(src_layer: dict, f_exit: int, n=2, decay=0.35, lag=4) -> list[dict]:
    """残影拖尾：出画瞬间(n×lag)帧内叠 opacity 递减的幽灵副本。
    src_layer 传已建好的主体图层 dict;在 f_exit 前后各留 lag 帧。"""
    outs = []
    kfs = src_layer["keyframes"]
    for i in range(1, n + 1):
        g = json.loads(json.dumps(src_layer))
        g["id"] = f"{src_layer['id']}-ghost{i}"
        g["z"] = src_layer.get("z", 10) - 1
        g.pop("jitter", None)
        gk = []
        for k in kfs:
            kk = dict(k)
            kk["frame"] = k["frame"] + lag * i
            kk["opacity"] = round(k.get("opacity", 1) * decay ** i, 3)
            gk.append(kk)
        gk = [k for k in gk if k["frame"] >= f_exit - lag]
        g["keyframes"] = gk[:2] if gk else []
        if g["keyframes"]:
            outs.append(g)
    return outs


def drop_in(name, path, width, x, y_t, f0, z=12, rot=0.0, anchor=(0.5, 0.9)):
    return {"id": name, "path": f"assets/source/{path}", "base_width": width,
            "anchor": list(anchor), "z": z, "shadow": BIG,
            "keyframes": [
                {"frame": f0, "x": x, "y": y_t-320, "scale": 0.85, "rotation": rot, "opacity": 0},
                {"frame": f0+8, "x": x, "y": y_t-40, "scale": 1.0, "rotation": rot, "opacity": 1, "ease": "ease-in"},
                {"frame": f0+14, "x": x, "y": y_t+12, "scale": 1.0, "rotation": rot, "opacity": 1, "ease": "ease-out"},
                {"frame": f0+22, "x": x, "y": y_t, "scale": 1.0, "rotation": rot, "opacity": 1, "ease": "ease-out"},
            ]}


def burst(fs, fe, o, rays=11, ln=170):
    return {"type": "radial-burst", "start_frame": fs, "end_frame": fe,
            "origin": list(o), "ray_count": rays, "max_ray_length": ln}


def motes(f0, f1, o=(540, 700), n=12):
    return {"type": "debris", "source": "assets/source/confetti_sheet.png",
            "sprite_boxes": [[14, 14, 46, 46], [74, 14, 106, 46], [134, 14, 166, 46],
                             [194, 14, 226, 46], [254, 14, 286, 46], [314, 14, 346, 46],
                             [374, 14, 406, 46], [434, 14, 466, 46]],
            "start_frame": f0, "end_frame": f1, "origin": list(o),
            "particle_count": n, "max_delay": 40,
            "vx": [-8, 8], "vy": [-14, -4], "gravity": 0.0,
            "scale": [0.10, 0.20], "fade_after": 90}


def relay(mv, speed="medium", momentum=None, rule="continue", tol=30) -> dict:
    """handoff 扩展字段速记。mv=[dx,dy] 单位矢量;momentum={主体id:[vx,vy]}。"""
    return {"motion_vector": list(mv), "exit_speed": speed,
            "subject_momentum": momentum or {},
            "next_enter_rule": {"angle": rule, "tolerance_deg": tol}}


def echo_cover(frames_total: int, fade_in: int = 10, hold: int = 6) -> dict:
    """片尾循环彩蛋(V7.0 可选层):末场景最后 ~16 帧封面渐入定格——结尾画面回到开头,
    触发重播。用法: 末场景 layers.append(echo_cover(frames_total)),z=39。"""
    fe = frames_total - 1
    return {"id": "echo-cover", "path": "assets/source/cover.png", "base_width": 1080,
            "anchor": [0.5, 0.5], "z": 39,
            "keyframes": [
                {"frame": max(0, fe - fade_in - hold), "x": 540, "y": 720, "scale": 1.0, "rotation": 0, "opacity": 0},
                {"frame": fe - hold, "x": 540, "y": 720, "scale": 1.0, "rotation": 0, "opacity": 0.94, "ease": "ease-in"},
                {"frame": fe, "x": 540, "y": 720, "scale": 1.0, "rotation": 0, "opacity": 0.94}]}


def band(y=1395, color=(18, 30, 58, 205)):
    return {"stage": "front", "y": y, "amplitude": 9, "wavelength": 380, "speed": 4,
            "thickness": 70, "color": list(color), "edge_color": [240, 246, 252, 80], "edge_width": 3}


def scene(seed, frames, bg, scale, layers, effects, grain=0.05, bands=None, bg_end=None, drift=None,
          parallax=None, cam_pan=None):
    d = {"canvas": {"width": W, "height": H}, "fps": 30, "duration_s": frames/30,
         "seed": seed, "procedural_frame_offset": 0,
         "background": {"path": bg, "scale": scale, "jitter": [0, 0]},  # bg 传完整相对路径(如 assets/raw/bg_s01.png)
         "grain_opacity": grain, "png_compress_level": 6,
         "wave_bands": bands if bands is not None else [band()]}
    cam_x_end = cam_pan[0] if cam_pan else 0
    cam_y_end = cam_pan[1] if cam_pan else 0
    if bg_end or cam_pan:
        d["camera_motion"] = {"fill": [10, 14, 30, 255], "keyframes": [
            {"frame": 0, "x": 0, "y": 0, "scale": scale, "rotation": 0, "opacity": 1},
            {"frame": frames-1, "x": cam_x_end, "y": cam_y_end, "scale": bg_end or scale,
             "rotation": 0, "opacity": 1, "ease": "ease-in-out"}]}
    # V3.12 视差: (bg_depth, fg_depth) → 相机平移时背景慢、前景快, 造 2.5D 纵深
    if parallax:
        d["parallax"] = {"bg_depth": parallax[0], "fg_depth": parallax[1]}
    if drift: d["container_drift"] = {"x": drift[0], "y": drift[1]}
    d["layers"] = layers
    d["effects"] = effects
    return d




# ============ V3.4 词级卡点接线（① 与 word_timing.py 配合） ============
def load_phrase_timing(project_dir=None):
    """读 qa/phrase_timing.json（word_timing.py 产物）。缺则返回 {} → 退回固定比例。

    ★ V3.24 时长口径修正：word_timing 里的 `dur` 是 **ASR 语音跨度**（首字起音→末字收音），
    系统性短于 mp3 的实际时长（p16 实测 25 段里 15 段偏短，最多差 1.97s：chunk_23 3.96 vs 5.928）。
    拿它做帧预算 → 画面比旁白短 → check_timeline_ratio 判"旁白未播完就切走"，13 场全中。
    p15 只是被 ×1.03 的余量盖住了，不是它对。
    现统一在入口处用**唯一时长权威 `audio_duration.py`** 覆盖 `dur`，ASR 原值留在 `asr_dur`。
    """
    import json as _json
    proj = Path(project_dir or ROOT)
    p = proj / "qa" / "phrase_timing.json"
    if not p.exists():
        return {}
    timing = _json.loads(p.read_text(encoding="utf-8"))
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from audio_duration import duration as _ad
    except Exception as e:
        # ⚠ 这里原来是 print 一个 ⚠ 然后**照旧返回 ASR 跨度**。V3.24① 花整节写的教训:
        #   `dur` 是 ASR 语音跨度、系统性短于 mp3 实测(p16 25 段里 15 段偏短, 最多 1.97s),
        #   拿它做帧预算 → 画面比旁白短。p20 实录: audio_duration.py 漏 import sys,
        #   这个 except 把它吞了, 于是**全片帧预算静默降级**。门里的兜底就是假绿。
        raise SystemExit(f"[FAIL] 时长权威源 audio_duration 不可用, 拒绝用 ASR 跨度做帧预算: {e!r}")
    missing = []
    for cid, ent in timing.items():
        mp3 = proj / "assets" / "audio" / f"{cid}.mp3"
        ent["asr_dur"] = ent.get("dur")
        if mp3.exists():
            ent["dur"] = _ad(mp3)
            ent["dur_source"] = "mp3"
        else:
            missing.append(cid)
    if missing:
        raise SystemExit(f"[FAIL] {len(missing)} 段缺 mp3, 帧预算会偏短: "
                         f"{','.join(sorted(missing)[:8])} —— 先补 TTS 再建场景")
    return timing

def pf(timing, chunk_id, phrase, fps=30):
    """短语→场景内触发帧(段内0基)。用法: card("t_x",...,f_in=pf(TIMING,"chunk_02","93 万人预约"))。
    让字卡/道具在'念到该短语'的真实时刻出现，而非固定比例——① 词级卡点。"""
    for ph in timing.get(chunk_id, {}).get("phrases", []):
        if phrase in ph["phrase"] or ph["phrase"] in phrase:
            return round(ph["start"] * fps)
    return 0


# ============ V3.5 语义→动作预设（④：让"演语义"系统化，少手摆） ============
import re as _re

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")   # FAIL 信息走 stderr；只配 stdout 时管道/日志里是乱码
except (AttributeError, ValueError):
    pass  # 老 Python/流被重定向才有;NameError(漏 import sys)必须响,不能装死  # 老 Python 没这 API；有就救回 ✓/⚠ 不被 GBK 崩掉
MOTION_RULES = [
    (("涨","升","冲","加","攀","爬","挤进"), "rise"),
    (("降","沉","下架","跌","坠","退","掉"), "sink"),
    (("塞","进","投","飞入","撞入","吸入"), "fly"),
    (("抄","拼","组装","整合","合","攒"), "assemble"),
    (("缠","绕","锁","围","圈"), "orbit"),
    (("砸","立","钉","锤","定"), "slam"),
    (("岔","分","跑偏","背道"), "split"),
    (("转","竞赛","提速","加速"), "spin"),
    (("爆","炸","亮","闪"), "pop"),
]
def verb_to_motion(verb):
    for keys, m in MOTION_RULES:
        if any(k in verb for k in keys):
            return m
    return "pop"

def motion(verb, path, w, x, y, f0, f1, cx=None, cy=None, z=8):
    """按台词动词选动效配方，返回一个 layer dict。cx/cy 为 assemble/orbit 的中心。"""
    m = verb_to_motion(verb); cx = cx or x; cy = cy or y
    if m == "rise":     return rise(path, w, x, y, f0, dur=min(26, max(8,(f1-f0)//3)), z=z)
    if m == "sink":     return {"id":"p_sink"+_re.sub(r"\W","",path)+str(f0),"path":SRC_DIR+path,"base_width":w,"anchor":[0.5,0.5],"z":z,"shadow":SHADOW,
                                "keyframes":kf((f0,x,y-40,1.0,0,1),(f1,x,y+320,0.9,18,0,"ease-in"))}
    if m == "fly":      return fly(path, w, x-260, y-200, x, y, f0, dur=min(24,(f1-f0)//2), z=z)
    if m == "slam":     return drop_in("p_slam"+str(f0), path, w, x, y, f0, z=z)
    if m == "orbit":    return orbit(path, w, cx, cy, 240, f1-f0, z=z)
    if m == "spin":     return {"id":"p_spin"+str(f0),"path":SRC_DIR+path,"base_width":w,"anchor":[0.5,0.5],"z":z,"shadow":SHADOW,
                                "keyframes":kf((f0,x,y,0.8,0,0),(f0+8,x,y,1.0,0,1),(f1,x,y,1.0,300,1,"linear"))}
    if m == "split":    return fly(path, w, cx, cy, x, y, f0, dur=min(24,(f1-f0)//2), z=z)
    if m == "assemble": return fly(path, w, x, y, cx, cy, f0, dur=min(26,(f1-f0)//2), s0=1.1, s1=0.9, z=z)
    return {"id":"p_pop"+str(f0),"path":SRC_DIR+path,"base_width":w,"anchor":[0.5,0.5],"z":z,"shadow":SHADOW,
            "keyframes":kf((f0,x,y,0.4,0,0),(f0+8,x,y,1.12,0,1,"ease-out-back"),(f1,x,y,1.0,0,1))}

# ================== V3.1 语义动效助手（§36 标准，production1 实测） ==================
SRC_DIR = "assets/source/"

def rise(path, w, x, yt, f0, dur=26, z=8, anchor=(0.5, 1.0)):
    """§19.7 柱状升起：从屏下升入。语义=涨/冲上/升（方向必须向上）。"""
    return {"id": "p_r" + Path(path).stem + str(f0), "path": SRC_DIR + path, "base_width": w,
            "anchor": list(anchor), "z": z, "shadow": SHADOW,
            "keyframes": kf((f0, x, 1490, 1.0, 0, 0), (f0 + dur, x, yt, 1.0, 0, 1, "ease-out"))}

def climb(path, w, pts, f0, gap=40, z=9):
    """§19.14 台阶攀登：沿停靠点逐级上行、向灭点渐小。语义=分级/晋升/逐级。pts=[(x,y,scale),...]"""
    rows = [(f0, pts[0][0], pts[0][1], pts[0][2], 0, 0), (f0 + 5, pts[0][0], pts[0][1], pts[0][2], 0, 1)]
    for i, (x, y, sc) in enumerate(pts[1:], 1):
        rows.append((f0 + i * gap, x, y, sc, 0, 1, "ease-in-out"))
    return {"id": "p_cl" + Path(path).stem, "path": SRC_DIR + path, "base_width": w,
            "anchor": [0.5, 0.9], "z": z, "shadow": BIG, "keyframes": kf(*rows)}

def fly(path, w, x0, y0, x1, y1, f0, dur=20, s0=1.3, s1=0.9, rot0=0, rot1=0, z=8, fade=False):
    """§19.8 飞行塞入：从画外飞入落定。语义=进/塞/投入。fade=True 落定后再坠出画（消耗/沉没）。"""
    d = {"id": "p_f" + Path(path).stem + str(f0), "path": SRC_DIR + path, "base_width": w,
         "anchor": [0.5, 0.5], "z": z, "shadow": SHADOW,
         "keyframes": kf((f0, x0, y0, s0, rot0, 0), (f0 + 4, x0, y0, s0, rot0, 1),
                         (f0 + dur, x1, y1, s1, rot1, 1, "ease-in"))}
    if fade:
        # 这行必须走 kf(): keyframes 是 **dict 列表**, 直接 += 裸元组会写出 list 型关键帧,
        # 下游 render_sequence / preflight / first_frame_check / layout_check 全部 .get() 崩栈。
        d["keyframes"] += kf((f0 + dur + 14, x1 + 40, y1 + 240, s1 * 0.8, rot1 + 45, 0, "ease-in"))
    return d

def scatter(path, w, x, y, f0, dx, dy, rot):
    """§20 拍1 chaos：从原地散飞出画。语义=混乱/否定/旧秩序瓦解。"""
    return {"id": "p_sc" + Path(path).stem + str(f0), "path": SRC_DIR + path, "base_width": w,
            "anchor": [0.5, 0.5], "z": 8, "shadow": SHADOW,
            "keyframes": kf((f0, x, y, 1.0, 0, 1), (f0 + 35, x + dx, y + dy, 0.7, rot, 0, "ease-in"))}

def orbit(path, w, cx, cy, r, frames, z=8, phase=0, op=1.0):
    """§28 V6 / §19.4 环绕：绕中心公转。语义=缠绕/锁定/生态。多副本 phase 错开=多线缠绕。"""
    import math as _m
    n = 12; step = max(1, frames // n); rows = []
    for k in range(n + 1):
        th = phase + k * 30.0
        x = cx + r * _m.cos(_m.radians(th)); y = cy + r * _m.sin(_m.radians(th))
        rows.append((k * step, round(x), round(y), 1.0, round(th + 90), op if k > 0 else 0))
    return {"id": "orb_" + Path(path).stem + str(phase), "path": SRC_DIR + path, "base_width": w,
            "anchor": [0.5, 0.5], "z": z, "shadow": SHADOW, "keyframes": kf(*rows)}

def seq(name, w, x, y, f0, f1, z=14, hold=False):
    """V8.1.8 countup 数字滚动层（make_countup 产物目录）。⚠ id 必须 seq_ 前缀（勿用 c_/t_，
    否则 layout_check 当文字卡要 path 字段崩溃）。hold=True 末窗口定格不淡出（终值数字）。"""
    k = [(f0, x, y, 1.0, 0, 0), (f0 + 4, x, y, 1.0, 0, 1)]
    k += [(f1, x, y, 1.0, 0, 1)] if hold else [(f1 - 6, x, y, 1.0, 0, 1), (f1, x, y, 0.95, 0, 0, "ease-out")]
    return {"id": "seq_" + name, "seq_dir": f"assets/text/{name}", "seq_rate": 1, "base_width": w,
            "anchor": [0.5, 0.5], "z": z, "shadow": BIG, "keyframes": kf(*k)}


# ============ V3.12 增强动效库：挤压拉伸 / 落定回弹 / 运动模糊（配 render_sequence scale_x/y + motion_blur） ============
def _kf(frame, x, y, scale=1.0, rot=0, op=1, ease=None, sx=None, sy=None):
    d = {"frame": frame, "x": x, "y": y, "scale": scale, "rotation": rot, "opacity": op}
    if ease:
        d["ease"] = ease
    if sx is not None:
        d["scale_x"] = sx
    if sy is not None:
        d["scale_y"] = sy
    return d


def slam_squash(path, w, x, y, f0, z=12, rot=0.0, anchor=(0.5, 1.0)):
    """坠落→落地瞬间挤压(扁)→拉伸回弹→定住。卡通挤压拉伸=重量感, 比匀速落定"活"。"""
    return {"id": "p_sq" + Path(path).stem + str(f0), "path": SRC_DIR + path, "base_width": w,
            "anchor": list(anchor), "z": z, "shadow": BIG, "jitter": JIT,
            "keyframes": [
                _kf(f0, x, y - 360, 1.0, rot, 0, sx=1.0, sy=1.0),
                _kf(f0 + 7, x, y - 8, 1.0, rot, 1, "ease-in", sx=1.0, sy=1.0),
                _kf(f0 + 11, x, y + 6, 1.0, rot, 1, "ease-out", sx=1.20, sy=0.76),   # 挤压(扁)
                _kf(f0 + 16, x, y - 5, 1.0, rot, 1, "ease-in-out", sx=0.90, sy=1.14),  # 拉伸回弹
                _kf(f0 + 22, x, y, 1.0, rot, 1, "ease-out", sx=1.0, sy=1.0),
            ]}


def pop_spring(path, w, x, y, f0, f1, z=8, s=1.0):
    """弹入过冲 + 轻微挤压, spring 收尾。比 pop 的 ease-out-back 多一点回弹二次运动。"""
    return {"id": "p_sp" + Path(path).stem + str(f0), "path": SRC_DIR + path, "base_width": w,
            "anchor": [0.5, 0.5], "z": z, "shadow": SHADOW,
            "keyframes": [
                _kf(f0, x, y, 0.3 * s, 0, 0, sx=0.3 * s, sy=0.3 * s),
                _kf(f0 + 6, x, y, 1.0 * s, 0, 1, "ease-out-back", sx=1.18 * s, sy=0.86 * s),
                _kf(f0 + 12, x, y, 1.0 * s, 0, 1, "ease-in-out", sx=0.94 * s, sy=1.08 * s),
                _kf(f1, x, y, 1.0 * s, 0, 1, None, sx=1.0 * s, sy=1.0 * s),
            ]}


def fly_blur(path, w, x0, y0, x1, y1, f0, dur=16, z=8, samples=4, min_speed=24):
    """高速飞入带运动模糊拖影(方向=速度矢量), 落定后无糊。"""
    return {"id": "p_fb" + Path(path).stem + str(f0), "path": SRC_DIR + path, "base_width": w,
            "anchor": [0.5, 0.5], "z": z, "shadow": SHADOW,
            "motion_blur": {"samples": samples, "min_speed": min_speed},
            "keyframes": [
                _kf(f0, x0, y0, 1.25, 0, 0), _kf(f0 + 3, x0, y0, 1.25, 0, 1),
                _kf(f0 + dur, x1, y1, 0.92, 0, 1, "ease-in"),
            ]}


# ======================= 场景函数示例（照抄改写） =======================
def s01_example():
    L = []
    # 四模式示例
    L.append(card("t_open", 600, 540, 500, 6, mode="bounce", rot=-2, f_out=60, z=24))
    L.append(card("t_open2", 620, 540, 700, 36, mode="slide", slide_dir=(1, 0), rot=2, f_out=90))
    L.append(card("t_key", 520, 540, 420, 120, mode="flip", slide_dir=(-1, 0)))
    L.append(card("t_big", 640, 540, 560, 200, mode="emph"))
    # 主体 + 残影
    hero = {"id": "hero", "path": "assets/source/hero.png", "base_width": 400,
            "anchor": [0.5, 0.92], "z": 14, "jitter": JIT, "shadow": BIG,
            "keyframes": [
                {"frame": 100, "x": 400, "y": 1200, "scale": 0.9, "rotation": 0, "opacity": 0},
                {"frame": 120, "x": 400, "y": 1200, "scale": 0.9, "rotation": 0, "opacity": 1},
                {"frame": 430, "x": 700, "y": 900, "scale": 1.0, "rotation": 0, "opacity": 1, "ease": "ease-in-out"},
            ]}
    L.append(hero)
    L += ghost(hero, f_exit=430)          # 出画拖尾
    return scene(1, 480, "bg_x.png", 1.15, L, [burst(6, 30, [540, 500]), motes(0, 480)])


def main():
    # V3.31: 这个文件是**模板库**，不是可执行脚本。以前任何调用（含 `--help`）都会往 ROOT 落一份
    # scene_s01.json——冒烟测试 `for f in scripts/*.py; do py $f --help`，或随手 -h 看用法，
    # 就会在 scripts/ 留下一个**假场景**，而按 scene_s*.json glob 的门会把它当成本片场景读。
    if {"-h", "--help"} & set(sys.argv[1:]):
        print((__doc__ or "").strip()[:600])
        print("… 本文件是模板库(import 用)，不可执行。真正的建场脚本在每个项目里: productionN/build_scenes.py")
        return
    for i, b in enumerate([s01_example], 1):   # ← 换成 [s01, s02, ..., s08]
        d = b()
        (ROOT / f"scene_s{i:02d}.json").write_text(
            json.dumps(d, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"scene_s{i:02d}  {d['duration_s']:.2f}s  layers={len(d['layers'])}")
    print(f"⚠ 已在 {ROOT} 写出示例场景——模板自检用，别留在项目目录里")


if __name__ == "__main__":
    main()
