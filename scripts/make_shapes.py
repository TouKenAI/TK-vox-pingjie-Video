#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""V3.2 纸艺形状直绘器（production2 教训固化）。

红/暖色道具（红心/红叉/红星等）与洋红键色同高红通道，AI 生图+抠图常抠不净
（production2 红心 semi_edge 0.27 打回）。这类**纯色几何道具优先 PIL 直绘**：
确定性、边缘利落、颜色可控，不走生图+抠图链。写实/复杂道具仍走 gen_assets+cutout_key。

用法:
  py make_shapes.py --out-dir <项目>/assets/source --which heart,check,cross,star,arrow,lock --scale 1.0
"""
from __future__ import annotations
import argparse, math
from pathlib import Path
from PIL import Image, ImageDraw


def _canvas(w, h):
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    return im, ImageDraw.Draw(im)


def heart(sz, color=(200, 40, 52, 255), edge=(150, 25, 35, 255)):
    W, H = int(sz), int(sz * 0.92); im, d = _canvas(W, H)
    pts = [(W/2 + 16*math.sin(math.radians(t))**3 * (W-40)/34,
            H/2 - (13*math.cos(math.radians(t)) - 5*math.cos(math.radians(2*t))
                  - 2*math.cos(math.radians(3*t)) - math.cos(math.radians(4*t))) * (H-40)/34)
           for t in range(0, 360)]
    d.polygon(pts, fill=color, outline=edge, width=6)
    d.ellipse([W*0.28, H*0.22, W*0.44, H*0.38], fill=(min(255, color[0]+30), color[1]+50, color[2]+50, 170))
    return im


def star(sz, color=(220, 170, 60, 255)):
    W = H = int(sz); im, d = _canvas(W, H); cx, cy = W/2, H/2; R, r = W*0.46, W*0.19
    pts = []
    for k in range(10):
        ang = -90 + k*36; rad = R if k % 2 == 0 else r
        pts.append((cx + rad*math.cos(math.radians(ang)), cy + rad*math.sin(math.radians(ang))))
    d.polygon(pts, fill=color, outline=(max(0, color[0]-40), max(0, color[1]-40), color[2], 255), width=4)
    return im


def arrow(sz, color=(220, 120, 40, 255), up=True):
    W = int(sz*0.7); H = int(sz); im, d = _canvas(W, H); cx = W/2
    s = 1 if up else -1; y0 = H/2
    head = [(cx, y0 - s*H*0.46), (cx - W*0.42, y0 - s*H*0.12), (cx - W*0.16, y0 - s*H*0.12),
            (cx - W*0.16, y0 + s*H*0.44), (cx + W*0.16, y0 + s*H*0.44), (cx + W*0.16, y0 - s*H*0.12),
            (cx + W*0.42, y0 - s*H*0.12)]
    d.polygon(head, fill=color, outline=(max(0, color[0]-40), color[1], color[2], 255), width=4)
    return im


def check(sz, color=(70, 150, 95, 255)):
    W = H = int(sz); im, d = _canvas(W, H)
    w = max(6, int(sz*0.16))
    d.line([(W*0.16, H*0.52), (W*0.42, H*0.78), (W*0.86, H*0.24)], fill=color, width=w, joint="curve")
    return im


def cross(sz, color=(200, 40, 52, 255)):
    W = H = int(sz); im, d = _canvas(W, H); w = max(6, int(sz*0.16)); m = sz*0.2
    d.line([(m, m), (W-m, H-m)], fill=color, width=w); d.line([(W-m, m), (m, H-m)], fill=color, width=w)
    return im


def lock(sz, color=(70, 90, 120, 255)):
    W = int(sz*0.8); H = int(sz); im, d = _canvas(W, H)
    d.arc([W*0.24, H*0.06, W*0.76, H*0.56], 180, 360, fill=(120, 130, 150, 255), width=int(W*0.12))
    d.rounded_rectangle([W*0.16, H*0.36, W*0.84, H*0.94], radius=int(W*0.08), fill=color,
                        outline=(max(0, color[0]-30), color[1], color[2], 255), width=4)
    d.ellipse([W*0.44, H*0.56, W*0.56, H*0.68], fill=(20, 25, 35, 255))
    return im


SHAPES = {"heart": heart, "star": star, "arrow": arrow, "check": check, "cross": cross, "lock": lock}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--which", default="heart,star,arrow,check,cross,lock")
    ap.add_argument("--scale", type=float, default=1.0)
    a = ap.parse_args()
    a.out_dir.mkdir(parents=True, exist_ok=True)
    for name in [w.strip() for w in a.which.split(",") if w.strip()]:
        if name not in SHAPES:
            print(f"跳过未知形状: {name}"); continue
        im = SHAPES[name](int(440 * a.scale))
        out = a.out_dir / f"prop_{name}.png"
        im.save(out); print(f"{out.name}: {im.size} (PIL 直绘, 不走抠图)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
