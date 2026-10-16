#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""text_legibility_check.py <项目目录> —— 成品字高可读性门（V3.42）。

**为什么要有这道门**：盘上字大 ≠ 屏上字大。渲染器 `render_sequence.transformed()` 会把
文字卡 PNG **重采样到 `base_width × layer_scale` 宽**（见 render_sequence.py:112-114），
再乘相机 scale。所以"生成器声明的字号"到屏幕上要经过两级缩放：

    屏上字高 = 盘上墨高 × (base_width × 图层scale / PNG宽) × 相机scale

V3.41 之前**没有任何一道门量过这个数**——preflight 数图层、layout_check 量出画、
clutter 量拥挤、aesthetic 打分，全都不看字号。于是"字小到看不清"只能靠人眼在成片里发现，
而那时渲染+编码已经跑完了。本门把它前移到渲前。

三档判据（阈值只在本文件顶部定义一次，其它脚本 import 它，不许另写一份）：
  L1 保留率 = 屏上墨高 / 盘上墨高 ≥ KEEP_RATIO      —— 少于它说明字号在链路里被偷偷缩小了
  L2 屏上墨高 ≥ HARD_MIN_PX                        —— 物理上读不出的下限
  L3 屏上墨高 < WARN_MIN_PX 只亮灯                 —— 偏小但不拦，交人判
  L4 实测张数必须 > 0                              —— §81：PASS（0 次）不是通过，是没跑
  L5 底衬覆盖 ≥ COVER_MIN 才算"有底衬"            —— 裸字压在场景上，对比度随底图变，不可控

用法:
  py -3.14 scripts/text_legibility_check.py <项目目录>
  py -3.14 scripts/text_legibility_check.py <项目目录> --json-out qa/text-legibility.json
退出码: 0=通过 / 1=有硬 FAIL
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from PIL import Image                                     # noqa: E402

# ── 判据单一事实源 ──────────────────────────────────────────────────────────
KEEP_RATIO = 0.70      # L1 屏上/盘上 墨高保留率下限
HARD_MIN_PX = 20.0     # L2 屏上墨高硬下限（低于它物理上读不出）
WARN_MIN_PX = 44.0     # L3 偏小亮灯线
COVER_MIN = 0.50       # L5 底衬判定：不透明像素 / 裁切后外接框面积
INK_ALPHA = 128        # 墨迹判定的 alpha 阈
# ──────────────────────────────────────────────────────────────────────────


def is_text_layer(layer: dict) -> bool:
    """文字层 = 字卡(_is_card / c_ t_ 前缀) ∪ 带 label 的层（名字/标注常画在道具 PNG 上）。"""
    lid = str(layer.get("id", ""))
    if "-ghost" in lid:                     # 残影副本，墨高与母层相同，不重复计数
        return False
    return bool(layer.get("_is_card")) or layer.get("label") or lid.startswith(("c_", "t_"))


def ink_metrics(path: Path, trim_alpha: bool) -> tuple[int, int, float]:
    """返回 (墨高, 墨宽, 底衬覆盖率)。墨=alpha≥INK_ALPHA 的外接框；覆盖率=墨像素/外接框面积。"""
    im = Image.open(path).convert("RGBA")
    if trim_alpha:
        b = im.getchannel("A").getbbox()
        if b:
            im = im.crop(b)
    w, h = im.size
    if w <= 0 or h <= 0:
        return 0, 0, 0.0
    a = im.getchannel("A")
    bb = a.point(lambda v: 255 if v >= INK_ALPHA else 0).getbbox()
    if not bb:
        return 0, 0, 0.0
    ink_h, ink_w = bb[3] - bb[1], bb[2] - bb[0]
    # 底衬覆盖率：外接框内不透明像素占比。满板≈1.0，裸字笔画≈0.2~0.4。
    mask = a.point(lambda v: 1 if v >= INK_ALPHA else 0)
    solid = sum(mask.getdata()) / float((bb[2] - bb[0]) * (bb[3] - bb[1]))
    return ink_h, ink_w, solid


def cam_scale_min(scene: dict) -> float:
    """全片最坏情况相机 scale（推远到最小的那一刻）——可读性按最坏算。"""
    ks = (scene.get("camera_motion") or {}).get("keyframes") or []
    vals = [float(k.get("scale", 1)) for k in ks if isinstance(k, dict)]
    return min(vals) if vals else 1.0


def layer_scale_min(layer: dict) -> float:
    vals = [float(k.get("scale", 1)) for k in (layer.get("keyframes") or [])
            if isinstance(k, dict) and "scale" in k]
    return min(vals) if vals else 1.0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("project", type=Path)
    ap.add_argument("--json-out", type=Path, default=None)
    a = ap.parse_args()

    proj = a.project.resolve()
    scenes = sorted(proj.glob("scene_s*.json"))
    if not scenes:
        print(f"✗ FAIL: {proj.name} 下没有 scene_s*.json —— 无可检查不是通过，是本门没在跑")
        return 1

    rows, missing = [], []
    for sp in scenes:
        try:
            scene = json.loads(sp.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"✗ FAIL: {sp.name} 读不出 JSON: {e!r}")
            return 1
        cs = cam_scale_min(scene)
        for lay in scene.get("layers", []):
            if not isinstance(lay, dict) or not is_text_layer(lay):
                continue
            if lay.get("seq_dir"):                 # 数字滚动：逐帧同尺寸，取第一帧
                frames = sorted((proj / str(lay["seq_dir"])).glob("*.png"))
                if not frames:
                    missing.append(f"{sp.name}:{lay.get('id')} seq_dir 无帧 {lay.get('seq_dir')}")
                    continue
                f = frames[0]
            else:
                f = proj / str(lay.get("path", ""))
            if not f.exists():
                missing.append(f"{sp.name}:{lay.get('id')} 缺图 {lay.get('path')}")
                continue
            ink_h, ink_w, cover = ink_metrics(f, bool(lay.get("trim_alpha")))
            pw = Image.open(f).size[0]
            if lay.get("trim_alpha"):
                b = Image.open(f).convert("RGBA").getchannel("A").getbbox()
                if b:
                    pw = b[2] - b[0]
            if ink_h <= 0 or pw <= 0:
                missing.append(f"{sp.name}:{lay.get('id')} 图里没有墨({f.name})")
                continue
            bw = float(lay.get("base_width", 600))
            keep = (bw * layer_scale_min(lay) / pw) * cs
            rows.append({
                "scene": sp.name, "id": lay.get("id"), "png": f.name,
                "ink_png_px": ink_h, "base_width": bw, "png_w": pw,
                "cam_scale": round(cs, 3), "keep": round(keep, 3),
                "onscreen_px": round(ink_h * keep, 1), "cover": round(cover, 2),
            })

    n = len(rows)
    if n == 0:
        # §81：一条门的"通过"必须报出它查了多少次。0 次不是通过，是没跑。
        print(f"✗ FAIL: {proj.name} 一张文字层都没量到（实测 0 次）—— 无可检查不是通过。"
              f"确认场景里有 c_/t_/label 层，或补上缺图（{len(missing)} 处缺图）")
        for m in missing[:10]:
            print("   " + m)
        return 1

    px = sorted(r["onscreen_px"] for r in rows)
    keep = sorted(r["keep"] for r in rows)
    print(f"实测 {n} 张文字层（{len(scenes)} 场）")
    print(f"  屏上墨高  min={px[0]:.1f}px  中位={px[n // 2]:.1f}px  max={px[-1]:.1f}px")
    print(f"  保留率    min={keep[0]:.2f}  中位={keep[n // 2]:.2f}  max={keep[-1]:.2f}"
          f"   （屏上墨高/盘上墨高）")
    bare = [r for r in rows if r["cover"] < COVER_MIN]
    if bare:
        print(f"  ⚠ 无底衬 {len(bare)}/{n} 张（覆盖率<{COVER_MIN}）——裸字压在场景上，"
              f"对比度随底图变不可控；建议给字卡加底衬板")

    fails, warns = [], []
    for r in rows:
        if r["keep"] < KEEP_RATIO:
            fails.append(f"L1 保留率 {r['keep']:.2f}<{KEEP_RATIO}（字号被链路缩小） "
                         f"{r['scene']}:{r['id']}")
        elif r["onscreen_px"] < HARD_MIN_PX:
            fails.append(f"L2 屏上墨高 {r['onscreen_px']:.1f}px<{HARD_MIN_PX} "
                         f"{r['scene']}:{r['id']}")
        elif r["onscreen_px"] < WARN_MIN_PX:
            warns.append(f"L3 偏小 {r['onscreen_px']:.1f}px<{WARN_MIN_PX} "
                         f"{r['scene']}:{r['id']}")
    for m in missing:
        warns.append("缺图/无墨 " + m)

    for w in warns[:20]:
        print("  ⚠ " + w)
    if len(warns) > 20:
        print(f"  ⚠ …另有 {len(warns) - 20} 条 WARN")
    for f_ in fails[:20]:
        print("  ✗ " + f_)
    if len(fails) > 20:
        print(f"  ✗ …另有 {len(fails) - 20} 条 FAIL")

    if a.json_out:
        a.json_out.parent.mkdir(parents=True, exist_ok=True)
        a.json_out.write_text(json.dumps(
            {"project": proj.name, "checked": n, "hard": HARD_MIN_PX, "warn": WARN_MIN_PX,
             "keep_ratio": KEEP_RATIO, "rows": rows, "fails": fails, "warns": warns},
            ensure_ascii=False, indent=1), encoding="utf-8")

    if fails:
        print(f"\n✗ FAIL 文字可读性 {len(fails)}/{n} 张不过 —— 收口方式是拆卡/砍词/换底衬，"
              f"不是缩字号（缩字号只会把「看不清」换成「看不见」）")
        return 1
    print(f"\n✓ 文字可读性 PASS（实测 {n} 张，FAIL 0 / WARN {len(warns)}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
