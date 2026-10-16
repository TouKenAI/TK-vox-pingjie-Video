#!/usr/bin/env python3
"""V6.8 布局门禁校验(修复 V6.5 盲区):整屏可见(HARD)+ 安全区/同屏密度/重叠(WARN)。

V6.5 bug(2026-08-26 实录,NVC_V67 字出画事故): 只按 layer 关键帧的 x/y/scale 算包围盒
距画布边 ≥20px, **完全未计入**:
  1) camera_motion 整体缩放(各场景 scale 高达 1.16~1.28, 放大 + 居中裁剪会把边缘
     ~90~110px 的内容推出画面——6 张字卡被裁, 如「说事实·只说看到的」顶切 60px,
     「从想吵·变成愿意改」底切 48px, layout 报告却全是 PASS);
  2) 卡片 rotation 旋转后的外扩包围盒(rotate expand=True 会显著放大 bbox);
  3) jitter 抖动的极端位移。

V6.8 算法: 与 render_sequence.py **同一套确定性数学**(tween + transform + rotate +
camera resize/居中裁剪), 逐帧计算每张文字卡在"成品画面坐标"下的包围盒。
  - HARD = 成品坐标内越出画布(>0px): 一字不可见即 HARD 拦截渲染。
  - WARN = 距画布边不足安全边距 MARGIN / 同屏同时存活文字卡 >MAX_SIM_CARDS /
          卡两两重叠 >OVERLAP_MAX(均在成品坐标下评估)。
  - WARN(V6.9+ 平台适配): 卡 bbox 底部落入平台自动字幕带(SUBtitle_BAND) →
          PLATFORM_CAPTION 提醒让位(抖音自动字幕通常渲染在画面底部 ~20%)。
用法/退出码与 V6.5 兼容:
  py -3.12 scripts/layout_check.py <项目目录> [--canvas 1080 1440] [--strict]

V8.1.1 两处修复(一次性原理审查):
  ① ease() 直接从 render_sequence.py 导入(导入失败退回内置镜像),V300 三缓动
    (ease-out-back 过冲≈1.02 / ease-out-expo / ease-spring)不再被按 linear 低估——
    消灭"V300 缓动卡假 PASS"(P14 实测文字卡 28 处关键帧踩此盲区);test_layout_parity.py 对拍锁死。
  ② 四边阈值统一:HARD=任一边出画 >0px(旧版 left/top 出画 ≤20px 漏放行);
    WARN TIGHT_MARGIN=画布内但距边 <20px(旧版 right/bottom 把"距边<20px 但完全可见"误判 HARD OFFSCREEN)。
已知限制:camera_motion 的 rotation 未建模(渲染器支持;当前所有生产场景只用 scale/x/y,
  启用 camera rotation 前必须先扩展 camera_point 数学,否则布局评估失真)。
"""
from __future__ import annotations

import argparse
import collections
import json
import math
import sys
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")   # FAIL 信息走 stderr；只配 stdout 时管道/日志里是乱码
except (AttributeError, ValueError):
    pass  # 老 Python/流被重定向才有;NameError(漏 import sys)必须响,不能装死

from pathlib import Path

from PIL import Image

MARGIN = 20          # 安全边距:成品画面坐标下文字卡距边 ≥20px
MAX_SIM_CARDS = 3    # 同屏同时存活文字卡上限(WARN)
OVERLAP_MAX = 0.25   # 卡两两重叠面积/较小卡面积 上限(WARN)
SEVERE_OVERLAP = 0.45  # V8.2 卡×卡严重互压(HARD):信息互相吞没
OCCLUDE_MAX = 0.30    # V8.2 非卡层遮卡面积/卡面积 上限(WARN):字卡被道具/角色压住=信息不全
SUBTITLE_BAND = 280  # V6.9 平台自动字幕带高度(成品坐标, 自底部向上), 关键字卡应让位
PLATFORM_RAIL = 130   # V8.1.3 右侧互动按钮栏宽度(点赞/评论/分享), 字卡右缘应避开


# ---- 与 render_sequence.py 完全一致的插值/几何数学 ----
def _load_renderer_ease():
    """V8.1.1: 优先直接复用渲染器的 ease(单一事实源,门禁与渲染永不漂移);失败退回内置镜像。"""
    here = Path(__file__).resolve().parent
    cand = here / "render_sequence.py"
    if not cand.exists():
        cand = here.parent.parent / "create-collage-animation" / "scripts" / "render_sequence.py"
    if cand.exists():
        import importlib.util
        spec = importlib.util.spec_from_file_location("_render_sequence_parity", cand)
        mod = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(mod)
            return mod.ease
        except Exception:
            pass
    return None


_RS_EASE = _load_renderer_ease()


def ease(name: str, t: float) -> float:
    if _RS_EASE is not None:
        return _RS_EASE(name, t)
    # 内置镜像(render_sequence.py 逐字拷贝;test_layout_parity.py 保证两边一致)
    t = max(0.0, min(1.0, t))
    if name == "ease-in":
        return t * t * t
    if name == "ease-out":
        return 1 - (1 - t) ** 3
    if name == "ease-in-out":
        return 4 * t**3 if t < 0.5 else 1 - ((-2 * t + 2) ** 3) / 2
    if name == "ease-out-expo":
        return 1 - 2 ** (-10 * t) if t < 1 else 1
    if name == "ease-out-back":
        c1, c3 = 1.70158 * 0.7, 1.70158 * 0.7 + 1
        return 1 + c3 * (t - 1) ** 3 + c1 * (t - 1) ** 2
    if name == "ease-spring":
        d = 0.3
        return 1 - (1 - t) ** 3 * ((1 - d) * (1 - t) + d) if t < 1 else 1
    return t


def tween(keys: list[dict], frame: int) -> dict:
    keys = sorted(keys, key=lambda item: item["frame"])
    if frame <= keys[0]["frame"]:
        return dict(keys[0])
    if frame >= keys[-1]["frame"]:
        return dict(keys[-1])
    for left, right in zip(keys, keys[1:]):
        if left["frame"] <= frame <= right["frame"]:
            span = max(1, right["frame"] - left["frame"])
            t = ease(right.get("ease", "linear"), (frame - left["frame"]) / span)
            out: dict = {"frame": frame}
            for field in ("x", "y", "scale", "rotation", "opacity"):
                a = float(left.get(field, right.get(field, 0)))
                b = float(right.get(field, a))
                out[field] = a + (b - a) * t
            return out
    return dict(keys[-1])


def rotate_extents(w: float, h: float, deg: float) -> tuple[int, int]:
    """PIL rotate(expand=True) 后图像宽高(对齐 renderer 的 round)。"""
    th = math.radians(abs(deg))
    return max(1, round(abs(w * math.cos(th)) + abs(h * math.sin(th)))), \
        max(1, round(abs(w * math.sin(th)) + abs(h * math.cos(th))))


def camera_point(x: float, y: float, cam_state: dict, W: int, H: int) -> tuple[float, float]:
    """原画布坐标 → camera resize(以原点放大)+居中裁剪 后的成品坐标。"""
    s = float(cam_state.get("scale", 1))
    cx = float(cam_state.get("x", 0))
    cy = float(cam_state.get("y", 0))
    left = round((W * s - W) / 2 - cx)
    top = round((H * s - H) / 2 - cy)
    return x * s - left, y * s - top


def card_png_wh(project: Path, layer: dict) -> tuple[int, int]:
    """层的原生像素尺寸。

    V3.35: `seq_dir`(数字滚动层)取序列**第一帧**——make_countup 产出的每帧同尺寸，
    而旧版这里只认 `layer["path"]`，于是**读数层在整道门里完全隐形**：
    它既不是 card(没有 path) 也进不了 others(`path` 取不到 → 被 exists() 滤掉)。
    p17 那两处可见缺陷(滚动的 4090 压在菜单牌上、收尾四张同 y 叠成糊)至今无门，就是这个原因。
    """
    if layer.get("seq_dir"):
        d = project / str(layer["seq_dir"])
        frames = sorted(d.glob("*.png"))
        if not frames:
            raise FileNotFoundError(f"seq_dir 无帧: {d}")
        f = frames[0]
    else:
        f = project / str(layer["path"])
    im = Image.open(f)
    if layer.get("trim_alpha"):
        rgba = im.convert("RGBA")
        b = rgba.getchannel("A").getbbox()
        if b:
            im = rgba.crop(b)
    return im.size


def card_bbox_sim(layer: dict, cam_keys: list[dict], nf: int, project: Path,
                  W: int, H: int) -> tuple[dict, dict, int]:
    """逐帧精确模拟成品 bbox。返回 (extreme_min, extreme_max, worst_frame)。
    extreme_min/max: 全生命周期居中标, 由所有帧(含 jitter 极值)的合成推最值。"""
    pw, ph = card_png_wh(project, layer)
    an = layer.get("anchor", [0.5, 0.5])
    bw = float(layer.get("base_width", 600))
    jit = layer.get("jitter", {})
    jx, jy, jr = float(jit.get("x", 0)), float(jit.get("y", 0)), float(jit.get("rotation", 0))
    xs, ys = [], []
    worst_frame = -1
    worst_ext = 0
    for fr in range(nf):
        st = tween(layer["keyframes"], fr)
        # V3.26: 渲染器 tween 会先 sorted(keyframes) 再钳位, 所以"入场帧"是**最小 frame**,
        # 不是 keyframes[0]。旧写法用文件首元素: 图层关键帧一旦写成乱序, 本门会把入场前的
        # 那段(正是"字卡从画外飞进来"要抓的区间)整段跳过 → 假 PASS。p13 s13 t_download 实测中招。
        _enter = min([k["frame"] for k in layer["keyframes"]
                      if isinstance(k, dict) and "frame" in k] or [0])
        if st.get("opacity", 1) < 0.4 or fr < _enter:
            continue
        cam = tween(cam_keys, fr) if cam_keys else {"scale": 1, "x": 0, "y": 0}
        for sxp, syp, srp in ((1, 1, 1), (1, -1, 1), (-1, 1, 1), (-1, -1, 1), (1, 1, -1), (1, -1, -1), (-1, 1, -1), (-1, -1, -1)):
            sx, sy, sr = st["x"] + sxp * jx, st["y"] + syp * jy, st["rotation"] + srp * jr
            ow = max(1, round(bw * st["scale"]))
            oh = max(1, round(ph * ow / pw))
            rw, rh = rotate_extents(ow, oh, sr)
            cx_, cy_ = camera_point(sx, sy, cam, W, H)
            x0, y0 = cx_ - rw * an[0], cy_ - rh * an[1]
            xs.append((x0, x0 + rw)); ys.append((y0, y0 + rh))
            ext = max(-x0, x0 + rw - W, -y0, y0 + rh - H, 0)
            if ext > worst_ext:
                worst_ext, worst_frame = ext, fr
    if not xs:
        return {}, {}, -1
    # xs/ys 元组是 (边0, 边1)=(左,右)/(顶,底): mn[1] 必须取**顶边**最小值,
    # 旧写法 min(y for _, y in ys) 取了底边最小值 → 顶部出画/顶部贴边永远检不出(假阴性)。
    return (min(x for x, _ in xs), min(y for y, _ in ys)), \
           (max(x for _, x in xs), max(y for _, y in ys)), worst_frame


def _is_card(l: dict) -> bool:
    """哪些层算"字卡"（撞卡/出画/字幕带都按这个集合判）。

    判据**保持原样**（`c_ in id` 或资产在 assets/text/ 下），只加一条显式退出：
    `decor: True`。p20 实录——报纸栏底片 id 叫 `c_data`（在 assets/lines/ 下、无 label），
    被 `c_ in id` 当成字卡，于是压在它上面的机型名牌被判 SEVERE_OVERLAP 1.0。
    背景装饰不该参与撞卡判定，但它该由作者**明说**，而不是靠改判据。

    ⚠ 我第一版把判据改成"text/ 或带 label"，听着更讲道理，实测回放：
      p19 多算 11 层、凭空多出 7 条 HARD（带 label 的**道具**被当字卡量矩形）。
      判据放宽一格，假阳性的代价比漏报大得多——所以退回原判据 + 显式 decor。
    """
    if l.get("decor"):
        return False
    return "c_" in l.get("id", "") or str(l.get("path", "")).startswith("assets/text/")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("project", type=str)
    ap.add_argument("--canvas", nargs=2, type=int, default=[1080, 1440])
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--report-dir", type=Path, default=None,
                    help="把报告写到别处（默认 <项目>/qa）。回放历史片用它，**不要覆盖已交付片的 QA 记录**。")
    args = ap.parse_args()

    proj = Path(args.project)
    cw, ch = args.canvas
    hard, warns = [], []

    scene_files = sorted(proj.glob("scene_s*.json"))
    if not scene_files:
        print("FAIL: 未找到 scene_s*.json"); return 1

    for jf in scene_files:
        sc = json.loads(jf.read_text(encoding="utf-8"))
        # V8.2 修: nf 兜底 duration_s×30——P15 类场景 JSON 只有 duration_s, 旧取值恒 0 = 整个门禁空转
        nf = int(sc.get("frame_count", sc.get("frames", 0))
                 or round(float(sc.get("duration_s", 0)) * 30))
        cam_keys = [k for k in sc.get("camera_motion", {}).get("keyframes", [])]
        cards = [l for l in sc.get("layers", []) if _is_card(l)]
        # V3.35: 读数层(seq_ 数字滚动)与字卡同权参与几何判定——它屏幕上就是字。
        # 旧版它两头都不进(不是 card、path 取不到也进不了 others)，p17 两类缺陷至今无门。
        readouts = [l for l in sc.get("layers", [])
                    if l.get("seq_dir") and not l.get("decor") and l not in cards]
        seq_ids = {l["id"] for l in readouts}
        for l in readouts:
            d = proj / str(l["seq_dir"])
            if not d.is_dir() or not sorted(d.glob("*.png")):
                hard.append({"scene": jf.stem, "card": l["id"], "category": "ASSET_MISSING",
                             "error": f"seq_dir 无帧: {l['seq_dir']}——渲染器会在这里 FileNotFoundError"})
        readouts = [l for l in readouts if (proj / str(l["seq_dir"])).is_dir()
                    and sorted((proj / str(l["seq_dir"])).glob("*.png"))]
        # V8.1.1: 先验字卡 PNG 存在性——缺失给清晰 HARD 诊断, 不再 traceback 崩溃
        missing = [l for l in cards if not (proj / str(l["path"])).exists()]
        for l in missing:
            hard.append({"scene": jf.stem, "card": l["id"], "category": "ASSET_MISSING",
                         "error": f"文字卡 PNG 缺失: {l['path']}——先补素材再渲染"})
        cards = [l for l in cards if l not in missing] + readouts
        for l in cards:
            cid = l["id"]
            mn, mx, peak = card_bbox_sim(l, cam_keys, nf, proj, cw, ch)
            if not mn:
                continue
            # V8.1.1 统一阈值: HARD=出画>0px(任一边,一字不可见即拦); WARN TIGHT_MARGIN=画布内但距边<20px
            out = {"left": max(0.0, -mn[0]), "right": max(0.0, mx[0] - cw),
                   "top": max(0.0, -mn[1]), "bottom": max(0.0, mx[1] - ch)}
            out = {d: round(v, 1) for d, v in out.items() if v > 0}
            if out:
                hard.append({"scene": jf.stem, "card": cid, "category": "OFFSCREEN",
                             "bbox": [round(mn[0]), round(mn[1]), round(mx[0]), round(mx[1])],
                             "margin": MARGIN, "out": out, "peak_frame": peak})
            if mx[0] > cw - PLATFORM_RAIL:
                warns.append({"scene": jf.stem, "card": cid, "category": "PLATFORM_RAIL",
                              "right_edge": round(mx[0], 1), "rail_left": cw - PLATFORM_RAIL,
                              "hint": "字卡右缘进入平台互动按钮区(右侧130px), 建议左移/缩幅"})
            else:
                tight = {"left": MARGIN - mn[0], "right": MARGIN - (cw - mx[0]),
                         "top": MARGIN - mn[1], "bottom": MARGIN - (ch - mx[1])}
                tight = {d: round(v, 1) for d, v in tight.items() if v > 0}
                if tight:
                    warns.append({"scene": jf.stem, "card": cid, "category": "TIGHT_MARGIN",
                                  "bbox": [round(mn[0]), round(mn[1]), round(mx[0]), round(mx[1])],
                                  "short": tight,
                                  "hint": f"完全可见但距边不足 {MARGIN}px, 建议再向中心让位"})
            # 单卡超宽
            if mx[0] - mn[0] > cw - 2 * MARGIN:
                warns.append({"scene": jf.stem, "card": cid, "category": "TOO_WIDE",
                              "width": round(mx[0] - mn[0], 1), "limit": cw - 2 * MARGIN})
            # V6.9 平台字幕带让位:卡 bbox 底部进入底部字幕带 → WARN(成品坐标)
            if mx[1] > ch - SUBTITLE_BAND:
                warns.append({"scene": jf.stem, "card": cid, "category": "PLATFORM_CAPTION",
                              "bbox_bottom": round(mx[1], 1),
                              "caption_band_top": ch - SUBTITLE_BAND,
                              "overlap_px": round(mx[1] - (ch - SUBTITLE_BAND), 1),
                              "hint": "关键字卡落入平台自动字幕带, 建议上移至 y≤%d" % (ch - SUBTITLE_BAND)})
        # V8.2 全层密集采样门禁: 每 6 帧采样(含末帧), 覆盖入场动画瞬间; 按成品坐标
        # 三类: ①卡×卡重叠(>25% WARN / >45% HARD SEVERE_OVERLAP) ②非卡层遮卡(>30% WARN OCCLUDE)
        #       ③同屏卡密度(>3 WARN)。bbox 为保守估计(透明矩形亦计入), 命中后按提示目检裁决。
        # V8.2.3: bg_overlay 全屏半透明背景层(暗角/去暖蒙版)不参与道具遮卡判定
        others = [l for l in sc.get("layers", []) if l not in cards
                  and not l.get("bg_overlay")
                  and (proj / str(l.get("path", ""))).exists()]
        sample_frames = list(range(0, nf, 6)) + [nf - 1]
        card_sizes = {l["id"]: card_png_wh(proj, l) for l in cards}
        other_sizes = {}
        for l in others:
            try:
                other_sizes[l["id"]] = card_png_wh(proj, l)
            except Exception:
                pass
        others = [l for l in others if l["id"] in other_sizes]

        def layer_rect(l, kf, size):
            ks = l.get("keyframes", [])
            # V3.26 同 :160 的修法: 入场帧取最小 frame, 不取文件首元素(乱序时会漏测入场前那段)
            _ent = min([k["frame"] for k in ks if isinstance(k, dict) and "frame" in k] or [-1])
            if not ks or kf < _ent:
                return None
            st = tween(ks, kf)
            if st.get("opacity", 1) < 0.4:
                return None
            pw, ph = size
            bw = float(l.get("base_width", 600))
            an = l.get("anchor", [0.5, 0.5])
            ow = max(1, round(bw * st["scale"]))
            oh = max(1, round(ph * ow / pw))
            rw, rh = rotate_extents(ow, oh, st["rotation"])
            cam = tween(cam_keys, kf) if cam_keys else {"scale": 1, "x": 0, "y": 0}
            cx_, cy_ = camera_point(st["x"], st["y"], cam, cw, ch)
            return (cx_ - rw * an[0], cy_ - rh * an[1], cx_ - rw * an[0] + rw, cy_ - rh * an[1] + rh)

        occ_max, pair_max = {}, {}
        rop_max = {}      # V3.35: 读数层 × 道具(带烤字的牌子/屏幕) 的像素碰撞，只 WARN
        dens_max = [0, -1]    # V3.35: 每场只报"最挤的那一帧"一次（旧版逐 6 帧采样，p23 一场刷 176 条）
        cards_by_id = {l["id"]: l for l in cards}
        for kf in sample_frames:
            rects_c = {l["id"]: r for l in cards if (r := layer_rect(l, kf, card_sizes[l["id"]]))}
            # 同屏密度只数**字卡**：读数层(seq_)是同一个数字在滚，不是又一张卡
            _ncard = len([i for i in rects_c if i not in seq_ids])
            if _ncard > dens_max[0]:
                dens_max[0], dens_max[1] = _ncard, kf     # V3.35 每场只留最挤那一帧
            ids = list(rects_c)
            for i in range(len(ids)):
                for j in range(i + 1, len(ids)):
                    a, b = rects_c[ids[i]], rects_c[ids[j]]
                    ox = max(0, min(a[2], b[2]) - max(a[0], b[0]))
                    oy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
                    inter = ox * oy
                    if inter <= 0:
                        continue
                    mn_area = min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1]))
                    if mn_area <= 0:
                        continue
                    key = tuple(sorted((ids[i], ids[j])))
                    ratio = inter / mn_area
                    min_op = min(tween(cards_by_id[ids[i]]["keyframes"], kf).get("opacity", 1),
                                 tween(cards_by_id[ids[j]]["keyframes"], kf).get("opacity", 1))
                    prev = pair_max.get(key)
                    if prev is None or ratio > prev[0]:
                        pair_max[key] = (ratio, kf, min_op)
            rects_o = {l["id"]: r for l in others if (r := layer_rect(l, kf, other_sizes[l["id"]]))}
            # V3.35: 滚动的数字压在**带字道具**上(p17 的 4090 压在菜单牌上)——道具里有没有字，
            # 纯几何判不出来，所以只 WARN 交目检；但 seq×seq / seq×卡 是实心字压实心字，走 HARD。
            for sid in seq_ids:
                sr = rects_c.get(sid)
                if not sr:
                    continue
                s_area = max(1.0, (sr[2] - sr[0]) * (sr[3] - sr[1]))
                for pid, pr in rects_o.items():
                    ox = max(0, min(sr[2], pr[2]) - max(sr[0], pr[0]))
                    oy = max(0, min(sr[3], pr[3]) - max(sr[1], pr[1]))
                    if ox * oy <= 0:
                        continue
                    p_area = max(1.0, (pr[2] - pr[0]) * (pr[3] - pr[1]))
                    ratio = (ox * oy) / min(s_area, p_area)
                    key = (sid, pid)
                    if ratio > rop_max.get(key, 0):
                        rop_max[key] = ratio
            for cid, cr in rects_c.items():
                cw_, chh_ = cr[2] - cr[0], cr[3] - cr[1]
                cr = (cr[0] + cw_ * 0.12, cr[1] + chh_ * 0.12, cr[2] - cw_ * 0.12, cr[3] - chh_ * 0.12)
                c_area = (cr[2] - cr[0]) * (cr[3] - cr[1])
                if c_area <= 0:
                    continue
                for oid, orct in rects_o.items():
                    ox = max(0, min(cr[2], orct[2]) - max(cr[0], orct[0]))
                    oy = max(0, min(cr[3], orct[3]) - max(cr[1], orct[1]))
                    inter = ox * oy
                    if inter <= 0:
                        continue
                    key = (cid, oid)
                    occ_max[key] = max(occ_max.get(key, 0), inter / c_area)
        if dens_max[0] > MAX_SIM_CARDS:
            warns.append({"scene": jf.stem, "category": "DENSITY", "at_frame": dens_max[1],
                          "cards": dens_max[0], "limit": MAX_SIM_CARDS,
                          "hint": f"本场最挤的一帧同屏 {dens_max[0]} 张字卡(限 {MAX_SIM_CARDS})——"
                                  f"每场只报一次，逐类分诊见 KICKOFF E3"})
        for (a_id, b_id), (ratio, kf_at, min_op) in sorted(pair_max.items()):
            # 交接豁免: 叠压只发生在换卡交叉淡化期(一方 opacity<0.75)→ 降级 HANDOFF
            handoff = min_op < 0.75
            # V3.35 分级：seq×seq(两个滚动读数互咬)=HARD，p17"四档同 y 叠成糊"就是这个；
            # seq×卡 **只 WARN** —— 回放 13 部片时 p20/p21/p23 全亮红(bar_a×400万、p_ref×5、
            # 6.4×暗底卡)，那都是"数字标在它所属的卡上"的**合法设计**：分母取 min(面积) 时
            # 小数字整块落进大卡框就等于 1.0。假阳性比漏报致命(§57)，故不判红。
            n_seq = len(seq_ids & {a_id, b_id})
            seq_pair = n_seq >= 2
            cat = "READOUT_COLLIDE" if seq_pair else "SEVERE_OVERLAP"
            if ratio > SEVERE_OVERLAP and not handoff and (seq_pair or n_seq == 0):
                hard.append({"scene": jf.stem, "category": cat, "cards": [a_id, b_id],
                             "ratio": round(ratio, 2), "at_frame": kf_at, "limit": SEVERE_OVERLAP,
                             "hint": "两个读数叠在同一块像素上=糊成一团，竖排错开 y 或错时" if seq_pair else
                                     "卡×卡同位叠印且双方实心=信息互相吞没——旧卡须先退场"})
            elif ratio > SEVERE_OVERLAP and n_seq == 1:
                warns.append({"scene": jf.stem, "category": "READOUT_ON_CARD", "cards": [a_id, b_id],
                              "ratio": round(ratio, 2), "at_frame": kf_at,
                              "hint": "读数压在字卡上：若这是'数字属于这张卡'的标注设计可忽略；"
                                      "若两块文字互相咬住，错开 y 或错时"})
            elif ratio > SEVERE_OVERLAP:
                warns.append({"scene": jf.stem, "category": "HANDOFF", "cards": [a_id, b_id],
                              "ratio": round(ratio, 2), "at_frame": kf_at,
                              "hint": "换卡交叉淡化期短暂交叠(≤0.75 透明度), 正常手法"})
            elif ratio > OVERLAP_MAX:
                warns.append({"scene": jf.stem, "category": "OVERLAP", "cards": [a_id, b_id],
                              "ratio": round(ratio, 2), "limit": OVERLAP_MAX})
        # V3.22: 遮挡必须看 **z 序** —— 渲染器按 z 合成, z 比卡低的层(如常驻舞台/背景板)在卡的**下面**,
        # 数学上不可能压住它。旧版只比包围盒 → 每张卡都被 z=5 的舞台报一次 ratio=1.0 假告警
        # (p14 的 t_cta2/t_cta3 "by p_board_settle 1.0" 就是这个, 当时被误记成"入场穿过可留")。
        zmap = {l.get("id", "?"): float(l.get("z", 0)) for l in sc.get("layers", [])}
        for (cid, oid), ratio in sorted(occ_max.items()):
            if ratio > OCCLUDE_MAX and zmap.get(oid, 0) >= zmap.get(cid, 0):
                warns.append({"scene": jf.stem, "category": "OCCLUDE", "card": cid, "by": oid,
                              "ratio": round(ratio, 2), "limit": OCCLUDE_MAX,
                              "hint": "道具/角色矩形压住字卡(保守估计)——挪位/缩幅/错时, 目检裁决"})
        # V3.35: 读数层压在道具上（旧版读数层在整道门里隐形，这类缺陷一条都报不出来）
        for (sid, pid), ratio in sorted(rop_max.items()):
            if ratio > OCCLUDE_MAX:
                warns.append({"scene": jf.stem, "category": "READOUT_ON_PROP", "readout": sid, "on": pid,
                              "ratio": round(ratio, 2), "limit": OCCLUDE_MAX,
                              "hint": "滚动的数字与道具共用一块像素：道具上若烤了字就是互相吞没，"
                                      "目检决定错开 y 还是错时（读数层此前完全无门）"})

    report = {"canvas": [cw, ch], "hard": hard, "warns": warns}
    out = (args.report_dir or proj / "qa") / "layout-check-report.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"layout_check(V6.8): hard={len(hard)} warn={len(warns)} (report→{out.name})")
    # V3.35 一行分类汇总：p19/p22 实测每片 187~312 条 WARN，而 render_all 成功时只打
    # "✓ layout_check.py 通过" → 这些警告一条都没进过人眼（§62 元结论：先怀疑信息没人看）。
    # 带 `SUMMARY ` 前缀的行会被 render_all 在通过时也打印出来。
    _cw = collections.Counter(w.get("category", "?") for w in warns)
    _ch = collections.Counter(h.get("category", "?") for h in hard)
    print("SUMMARY layout: hard=" + (", ".join(f"{k}×{v}" for k, v in _ch.most_common()) or "0")
          + " | warn=" + (", ".join(f"{k}×{v}" for k, v in _cw.most_common(6)) or "0"))
    for h in hard:
        print("  HARD", json.dumps(h, ensure_ascii=False))
    for w in warns:
        print("  WARN", json.dumps(w, ensure_ascii=False))

    if hard:
        return 1
    if warns and args.strict:
        return 1
    print("PASS: 所有文字卡全程整屏可见(含 camera 缩放); 密度/重叠告警见报告")
    return 0


if __name__ == "__main__":
    sys.exit(main())